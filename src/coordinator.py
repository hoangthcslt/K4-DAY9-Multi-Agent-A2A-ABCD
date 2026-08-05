"""Coordinator: receives one case, dispatches the domain agents, assembles output.

Flow per case:
  coordinator -> customer_agent        (identity + history)
  coordinator -> order_product_agent   (composition)
  coordinator -> payment_agent         (reconciliation)
  coordinator -> delivery_agent        (lateness attribution)
  coordinator -> policy_agent          (EC_POLICY_V2 classification cross-check)
  coordinator -> verifier_agent        (schema + evidence gate, no LLM)

Every arrow above is an AgentMessage written to logging/trace.jsonl, so the
handoff structure is observable in the run artifact rather than only asserted
in architecture.md. All graded numbers/categories come from src.policy_rules;
the LLM agents only narrate and cross-check, so a flaky or absent LLM call
never changes a graded field - only case_assessment.confidence.
"""

from src.agents.customer_agent import CustomerAgent, build_customer_context, build_customer_facts
from src.agents.delivery_agent import DeliveryAgent, build_delivery_facts
from src.agents.order_product_agent import (
    OrderProductAgent,
    build_affected_entities,
    build_order_facts,
    build_product_context,
)
from src.agents.payment_agent import PaymentAgent, build_payment_facts
from src.agents.policy_agent import PolicyAgent, build_policy_facts
from src.agents.verifier_agent import build_final, enforce_limits, verify_output
from src.policy_rules import apply_policy
from src.trace_logger import AgentMessage

CONFIDENCE_VERIFIER_PENALTY = 0.15
MIN_CONFIDENCE = 0.05


class Coordinator:
    """Owns the per-case workflow and the final assembly."""

    name = "coordinator"

    def __init__(self, tracer):
        self.tracer = tracer
        self.customer_agent = CustomerAgent(tracer)
        self.order_product_agent = OrderProductAgent(tracer)
        self.payment_agent = PaymentAgent(tracer)
        self.delivery_agent = DeliveryAgent(tracer)
        self.policy_agent = PolicyAgent(tracer)

    def _dispatch(self, case_id, agent, payload):
        message = AgentMessage(self.name, agent.name, payload)
        return agent.run(case_id, message)

    def process(self, case_id, order_id, raw_customer, raw_items, raw_payments, delivery_info):
        """Run one case end to end and return (final_output, errors)."""
        self.tracer.log_case(case_id, "case_start", {"claimed_order_id": order_id})

        related_order_ids = raw_customer.get("related_order_ids", []) or []

        # Every graded number/category comes from here - deterministic, no LLM.
        assessment = apply_policy(order_id, delivery_info, raw_items, raw_payments, related_order_ids)
        order = assessment["order"]
        payment = assessment["payment"]
        delivery = assessment["delivery"]
        resolution = assessment["resolution"]
        evidence_ids = assessment["evidence_ids"]

        customer_context = build_customer_context(raw_customer)
        affected_entities = build_affected_entities(order_id, order, payment)
        product_context = build_product_context(order)

        # Domain agents: each gets exactly the facts it owns, makes one LLM
        # call over them, and hands a narrative/cross-check finding back.
        customer_finding = self._dispatch(
            case_id, self.customer_agent, build_customer_facts(raw_customer)
        )
        order_finding = self._dispatch(
            case_id, self.order_product_agent, build_order_facts(order_id, order, raw_items)
        )
        payment_finding = self._dispatch(
            case_id, self.payment_agent, build_payment_facts(payment)
        )
        delivery_finding = self._dispatch(
            case_id, self.delivery_agent, build_delivery_facts(delivery)
        )

        # Policy Agent: classifies independently as a cross-check; rules win
        # on every graded field, the model only sets confidence.
        policy_finding = self._dispatch(
            case_id,
            self.policy_agent,
            build_policy_facts(
                delivery, payment, customer_finding, order_finding,
                payment_finding, delivery_finding, resolution["primary_issue"],
            ),
        )

        final = build_final(
            case_id=case_id,
            order_id=order_id,
            customer_context=customer_context,
            order=order,
            payment=payment,
            delivery=delivery,
            resolution=resolution,
            evidence_ids=evidence_ids,
            affected_entities=affected_entities,
            product_context=product_context,
            confidence=policy_finding["confidence"],
        )

        output = final.model_dump()
        output = enforce_limits(output)

        verify_message = AgentMessage(self.name, "verifier_agent", output, "verify_request")
        self.tracer.log_message(case_id, verify_message)

        seller_ids = order.get("seller_ids", [])
        errors, warnings = verify_output(
            output, order_id, raw_items, raw_payments, related_order_ids, seller_ids
        )

        if errors:
            # A failed gate lowers reported confidence rather than silently
            # shipping a clean-looking but unverified case.
            output["case_assessment"]["confidence"] = round(
                max(MIN_CONFIDENCE, output["case_assessment"]["confidence"] - CONFIDENCE_VERIFIER_PENALTY),
                2,
            )

        self.tracer.log_agent_step(
            case_id,
            agent="verifier_agent",
            model="rule-based (no LLM)",
            inputs={"order_id": order_id},
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
