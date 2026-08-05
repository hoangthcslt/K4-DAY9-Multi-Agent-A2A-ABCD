"""
Coordinator Agent — Orchestrates all agents, manages handoff, produces final output.
"""

import json
import os
import time
from datetime import datetime

from agents.data_access import DataAccessLayer
from agents.llm_client import LLMClient
from agents.investigation_agent import InvestigationAgent
from agents.delivery_agent import DeliveryAgent
from agents.payment_agent import PaymentAgent
from agents.policy_agent import PolicyAgent
from agents.verifier_agent import VerifierAgent


class CoordinatorAgent:
    AGENT_NAME = "CoordinatorAgent"

    def __init__(self, dal: DataAccessLayer, llm: LLMClient):
        self.dal = dal
        self.llm = llm
        self.investigation = InvestigationAgent(dal, llm)
        self.delivery = DeliveryAgent(dal, llm)
        self.payment = PaymentAgent(dal, llm)
        self.policy = PolicyAgent(llm)
        self.verifier = VerifierAgent()

    def process_case(self, case_input: dict) -> tuple[dict, dict]:
        """
        Process a single case. Returns (output_json, trace_record).
        """
        case_id = case_input["case_id"]
        order_id = case_input["customer_request"]["claimed_order_id"]
        start_time = time.time()

        print(f"\n{'='*60}")
        print(f"[{self.AGENT_NAME}] Processing {case_id} (order: {order_id})")
        print(f"{'='*60}")

        trace_steps = []

        # ── Phase 2: Investigation agents (parallel in concept) ──
        t0 = time.time()
        inv_result = self.investigation.investigate(order_id)
        trace_steps.append({"agent": "InvestigationAgent", "duration_s": round(time.time() - t0, 2)})

        t0 = time.time()
        del_result = self.delivery.analyze(order_id)
        trace_steps.append({"agent": "DeliveryAgent", "duration_s": round(time.time() - t0, 2)})

        t0 = time.time()
        pay_result = self.payment.analyze(order_id)
        trace_steps.append({"agent": "PaymentAgent", "duration_s": round(time.time() - t0, 2)})

        # ── Phase 3: Policy evaluation ──
        t0 = time.time()
        pol_result = self.policy.evaluate(inv_result, del_result, pay_result)
        trace_steps.append({"agent": "PolicyAgent", "duration_s": round(time.time() - t0, 2)})

        # ── Assemble output ──
        output = self._assemble_output(case_id, inv_result, del_result, pay_result, pol_result)

        # ── Phase 4: Verification ──
        t0 = time.time()
        output = self.verifier.fix_limits(output)
        is_valid, errors = self.verifier.validate(output)
        trace_steps.append({
            "agent": "VerifierAgent",
            "duration_s": round(time.time() - t0, 2),
            "valid": is_valid,
            "errors": errors,
        })

        if not is_valid:
            print(f"  [VerifierAgent] Validation errors: {errors}")

        total_time = round(time.time() - start_time, 2)
        print(f"[{self.AGENT_NAME}] {case_id} completed in {total_time}s (valid={is_valid})")

        # Build trace record
        trace = {
            "case_id": case_id,
            "order_id": order_id,
            "timestamp": datetime.now().isoformat(),
            "total_duration_s": total_time,
            "steps": trace_steps,
            "valid": is_valid,
            "primary_issue": pol_result["primary_issue"],
        }

        return output, trace

    def _assemble_output(self, case_id, inv, deliv, pay, pol) -> dict:
        """Assemble the final output JSON from all agent results."""
        return {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": pol["primary_issue"],
                "secondary_issues": pol["secondary_issues"],
                "case_status": pol["case_status"],
                "confidence": pol["confidence"],
            },
            "affected_entities": pol["affected_entities"],
            "customer_context": inv["customer"],
            "product_context": {
                "product_ids": inv["product_ids"],
                "category_names": inv["category_names"],
            },
            "delivery_analysis": {
                "delivered_at": deliv["delivered_at"],
                "estimated_delivery_at": deliv["estimated_delivery_at"],
                "carrier_handoff_at": deliv["carrier_handoff_at"],
                "delivery_variance_hours": deliv["delivery_variance_hours"],
                "seller_handoff_analysis": deliv["seller_handoff_analysis"],
                "late_handoff_seller_ids": deliv["late_handoff_seller_ids"],
            },
            "payment_reconciliation": {
                "currency": pay["currency"],
                "item_total_brl": pay["item_total_brl"],
                "freight_total_brl": pay["freight_total_brl"],
                "expected_total_brl": pay["expected_total_brl"],
                "payment_total_brl": pay["payment_total_brl"],
                "difference_brl": pay["difference_brl"],
                "reconciled": pay["reconciled"],
                "payment_types": pay["payment_types"],
            },
            "root_cause_analysis": pol["root_cause_analysis"],
            "evidence_ids": pol["evidence_ids"],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": pol["recommended_refund_brl"],
            },
            "resolution_actions": pol["resolution_actions"],
        }
