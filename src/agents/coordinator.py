"""Coordinator Agent: receives the case, dispatches work, assembles the output.

Flow per case:
  coordinator -> customer_agent        (identity + history)
  coordinator -> order_product_agent   (composition)
  coordinator -> payment_agent         (reconciliation)
  coordinator -> delivery_agent        (lateness attribution)
  coordinator -> policy_agent          (EC_POLICY_V2 classification)
  coordinator -> verifier_agent        (schema + evidence gate)

Each arrow is an AgentMessage written to trace.jsonl, so the handoff structure
is observable in the run artifact rather than only asserted in the docs.
"""

import json

from agents.base import Agent, as_text
from agents.customer_agent import CustomerAgent, build_customer_context
from agents.delivery_agent import DeliveryAgent, build_delivery_facts
from agents.order_product_agent import (
    OrderProductAgent,
    build_affected_entities,
    build_order_facts,
    build_product_context,
)
from agents.payment_agent import PaymentAgent, build_payment_facts
from agents.policy_agent import PolicyAgent, build_policy_facts
from agents.verifier_agent import enforce_limits, verify_output
from policy_rules import apply_policy
from trace_logger import AgentMessage

CONFIDENCE_VERIFIER_PENALTY = 0.15
MIN_CONFIDENCE = 0.05


class IntakeAgent(Agent):
    """The Coordinator's own LLM step: read the Vietnamese customer message and
    decide what the customer is actually claiming before dispatching work."""

    name = "coordinator_intake"
    system_prompt = (
        "You are the Coordinator of an e-commerce dispute investigation team. "
        "You receive a customer complaint (often Vietnamese) and the "
        "investigation scope. Classify the claim so the right specialist "
        "agents are dispatched. Do not judge the outcome; you only route work. "
        "Reply with JSON: {\"claim_type\": \"late_delivery\" | \"payment\" | "
        "\"cancellation\" | \"general\", \"needs_customer_history\": bool, "
        "\"needs_product_context\": bool, \"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Case intake:\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nClassify the claim type and confirm which specialist "
            "investigations the scope requires."
        )

    def validate(self, response, facts):
        scope = facts.get("investigation_scope", {})
        return {
            "claim_type": as_text(response.get("claim_type"), "general") or "general",
            # Scope in the input file is authoritative over the model's opinion.
            "needs_customer_history": bool(scope.get("include_customer_history", True)),
            "needs_product_context": bool(scope.get("include_product_context", True)),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        scope = facts.get("investigation_scope", {})
        return {
            "claim_type": "general",
            "needs_customer_history": bool(scope.get("include_customer_history", True)),
            "needs_product_context": bool(scope.get("include_product_context", True)),
            "summary": "",
            "llm_available": False,
        }


class Coordinator:
    """Owns the per-case workflow and the final assembly."""

    name = "coordinator"

    def __init__(self, tracer):
        self.tracer = tracer
        self.intake = IntakeAgent(tracer)
        self.customer_agent = CustomerAgent(tracer)
        self.order_product_agent = OrderProductAgent(tracer)
        self.payment_agent = PaymentAgent(tracer)
        self.delivery_agent = DeliveryAgent(tracer)
        self.policy_agent = PolicyAgent(tracer)

    def _dispatch(self, case_id, agent, payload):
        message = AgentMessage(self.name, agent.name, payload)
        return agent.run(case_id, message)

    def process(self, case_input, bundle):
        """Run one case end to end and return (output, errors)."""
        case_id = case_input["case_id"]
        request = case_input.get("customer_request", {})
        scope = case_input.get("investigation_scope", {})

        self.tracer.log_case(
            case_id,
            "case_start",
            {
                "claimed_order_id": request.get("claimed_order_id"),
                "policy_version": case_input.get("policy_version"),
            },
        )

        # Step 0: coordinator reads the complaint and routes the investigation.
        intake = self._dispatch(
            case_id,
            self.intake,
            {
                "case_id": case_id,
                "customer_message": request.get("message"),
                "language": request.get("language"),
                "claimed_order_id": request.get("claimed_order_id"),
                "investigation_scope": scope,
            },
        )

        # All figures come from the deterministic engine over the joined data.
        assessment = apply_policy(bundle)

        # Step 1-4: domain agents, each over facts the data layer extracted.
        customer_finding = self._dispatch(
            case_id,
            self.customer_agent,
            {
                "order_id": bundle["order_id"],
                "customer_unique_id": bundle["customer"]["customer_unique_id"],
                "related_order_ids": bundle["related_order_ids"][:10],
                "history_requested": intake["needs_customer_history"],
            },
        )

        order_finding = self._dispatch(
            case_id, self.order_product_agent, build_order_facts(bundle)
        )

        payment_finding = self._dispatch(
            case_id,
            self.payment_agent,
            build_payment_facts(bundle, assessment["payment_reconciliation"]),
        )

        delivery_finding = self._dispatch(
            case_id,
            self.delivery_agent,
            build_delivery_facts(bundle, assessment["delivery_analysis"]),
        )

        # Step 5: policy classification over every upstream finding.
        policy_finding = self._dispatch(
            case_id,
            self.policy_agent,
            build_policy_facts(
                bundle,
                assessment,
                customer_finding,
                order_finding,
                payment_finding,
                delivery_finding,
            ),
        )

        output = self._assemble(case_id, bundle, assessment, policy_finding, scope)

        # Step 6: verifier gate before anything is written to disk.
        output = enforce_limits(output)
        verify_message = AgentMessage(self.name, "verifier_agent", output, "verify_request")
        self.tracer.log_message(case_id, verify_message)
        errors, warnings = verify_output(output, bundle)

        if errors:
            # A failed gate lowers reported confidence rather than silently
            # shipping a clean-looking but unverified case.
            output["case_assessment"]["confidence"] = round(
                max(
                    MIN_CONFIDENCE,
                    output["case_assessment"]["confidence"] - CONFIDENCE_VERIFIER_PENALTY,
                ),
                2,
            )

        self.tracer.log_agent_step(
            case_id,
            agent="verifier_agent",
            model="rule-based (no LLM)",
            inputs={"order_id": bundle["order_id"]},
            outputs={"passed": not errors, "errors": errors, "warnings": warnings},
        )

        self.tracer.log_case(
            case_id,
            "case_complete",
            {
                "primary_issue": output["case_assessment"]["primary_issue"],
                "case_status": output["case_assessment"]["case_status"],
                "refund_brl": output["financial_resolution"]["recommended_refund_brl"],
                "verifier_passed": not errors,
            },
        )
        return output, errors

    def _assemble(self, case_id, bundle, assessment, policy_finding, scope):
        """Build the graded JSON. Every value traces back to the data layer."""
        customer_context = build_customer_context(bundle)
        product_context = build_product_context(bundle)

        # The scope flags describe what to investigate, not what to omit from
        # the schema, so both blocks are always present; they are empty when the
        # data has nothing to report.
        if not scope.get("include_customer_history", True):
            customer_context["related_order_ids"] = []
        if not scope.get("include_product_context", True):
            product_context = {"product_ids": [], "category_names": []}

        return {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": assessment["primary_issue"],
                "secondary_issues": assessment["secondary_issues"],
                "case_status": assessment["case_status"],
                "confidence": policy_finding["confidence"],
            },
            "affected_entities": build_affected_entities(bundle),
            "customer_context": customer_context,
            "product_context": product_context,
            "delivery_analysis": assessment["delivery_analysis"],
            "payment_reconciliation": assessment["payment_reconciliation"],
            "root_cause_analysis": {
                "ranked_causes": assessment["ranked_causes"],
                "responsible_parties": assessment["responsible_parties"],
            },
            "evidence_ids": assessment["evidence_ids"],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": assessment["recommended_refund_brl"],
            },
            "resolution_actions": assessment["resolution_actions"],
        }
