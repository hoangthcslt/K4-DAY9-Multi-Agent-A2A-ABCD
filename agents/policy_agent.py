"""
Policy Agent — Applies EC_POLICY_V2 rules + LLM synthesis.
Rule engine determines primary/secondary issues deterministically.
LLM synthesizes findings from all agents and provides confidence.
"""

import json
from agents.llm_client import LLMClient


class PolicyAgent:
    AGENT_NAME = "PolicyAgent"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def evaluate(self, investigation: dict, delivery: dict, payment: dict) -> dict:
        print(f"  [{self.AGENT_NAME}] Evaluating policy for order {investigation['order_id']}...")

        order = investigation.get("order") or {}
        order_status = order.get("order_status")
        order_id = investigation["order_id"]
        items = investigation.get("items", [])
        flags = investigation.get("flags", {})

        payment_total = payment.get("payment_total_brl", 0)
        freight_total = payment.get("freight_total_brl", 0)
        reconciled = payment.get("reconciled")

        is_late = delivery.get("is_late_delivery", False)
        has_late_seller = delivery.get("has_late_seller", False)
        late_seller_ids = delivery.get("late_handoff_seller_ids", [])

        # ── Rule Engine: Primary Issue (priority order) ──
        primary_issue = None
        responsible_party_type = None
        responsible_party_id = None
        root_cause_code = None
        recommended_refund = 0
        main_action = None

        if order_status == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
            responsible_party_type = "platform"
            responsible_party_id = "OLIST_PLATFORM"
            root_cause_code = "ORDER_CANCELED_AFTER_PAYMENT"
            recommended_refund = payment_total
            main_action = "issue_full_refund"

        elif order_status == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
            responsible_party_type = "platform"
            responsible_party_id = "OLIST_PLATFORM"
            root_cause_code = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
            recommended_refund = payment_total
            main_action = "issue_full_refund"

        elif is_late and has_late_seller:
            primary_issue = "late_delivery_seller"
            responsible_party_type = "seller"
            responsible_party_id = None  # multiple sellers possible
            root_cause_code = "SELLER_HANDOFF_AFTER_LIMIT"
            recommended_refund = freight_total if freight_total else 0
            main_action = "refund_freight"

        elif is_late and not has_late_seller:
            primary_issue = "late_delivery_logistics"
            responsible_party_type = "logistics_provider"
            responsible_party_id = "LOGISTICS_PROVIDER"
            root_cause_code = "CARRIER_DELIVERED_AFTER_ESTIMATE"
            recommended_refund = freight_total if freight_total else 0
            main_action = "refund_freight"

        elif flags.get("split_payment") and reconciled:
            primary_issue = "valid_split_payment"
            responsible_party_type = None
            responsible_party_id = None
            root_cause_code = "MULTIPLE_PAYMENTS_RECONCILED"
            recommended_refund = 0
            main_action = "explain_valid_split_payment"

        else:
            primary_issue = "unsupported_late_claim"
            responsible_party_type = None
            responsible_party_id = None
            root_cause_code = "DELIVERY_WITHIN_ESTIMATE"
            recommended_refund = 0
            main_action = "reject_late_refund"

        # ── Secondary Issues (fixed order per spec) ──
        secondary_issues = []
        if flags.get("multi_item_order"):
            secondary_issues.append("multi_item_order")
        if flags.get("multi_seller_order"):
            secondary_issues.append("multi_seller_order")
        if flags.get("split_payment"):
            secondary_issues.append("split_payment")
        if flags.get("repeat_customer"):
            secondary_issues.append("repeat_customer")
        if flags.get("multiple_categories"):
            secondary_issues.append("multiple_categories")

        # ── Responsible Parties ──
        responsible_parties = []
        if responsible_party_type == "seller":
            for sid in late_seller_ids[:3]:
                responsible_parties.append({"party_type": "seller", "party_id": sid})
        elif responsible_party_type and responsible_party_id:
            responsible_parties.append({
                "party_type": responsible_party_type,
                "party_id": responsible_party_id,
            })

        # ── Root Causes ──
        ranked_causes = [{"cause_code": root_cause_code, "rank": 1}]

        # ── Case Status ──
        case_status = "action_required" if recommended_refund > 0 else "no_action"

        # ── Actions (fixed order per spec) ──
        actions = [main_action]
        if primary_issue in ("late_delivery_seller",):
            actions.append("review_seller_handoff")
        elif primary_issue in ("late_delivery_logistics",):
            actions.append("review_carrier_delay")

        if main_action == "issue_full_refund":
            actions.append("verify_refund_completion")

        if flags.get("multi_seller_order"):
            actions.append("coordinate_multi_seller_case")

        if flags.get("split_payment") and primary_issue != "valid_split_payment":
            actions.append("verify_payment_allocation")

        # ── Evidence IDs ──
        evidence_ids = [f"order:{order_id}"]
        for item in items[:5]:
            oid = item.get("order_item_id")
            if oid is not None:
                evidence_ids.append(f"item:{order_id}:{oid}")
        for p in payment.get("payment_rows", [])[:5]:
            seq = p.get("payment_sequential")
            if seq is not None:
                evidence_ids.append(f"payment:{order_id}:{seq}")
        if responsible_party_type == "seller":
            for sid in late_seller_ids[:3]:
                evidence_ids.append(f"seller:{sid}")
        evidence_ids.append(f"policy:{root_cause_code}")
        evidence_ids = evidence_ids[:20]

        # ── Affected Entities ──
        item_ids = []
        for item in items[:5]:
            oid = item.get("order_item_id")
            if oid is not None:
                item_ids.append(f"{order_id}:{oid}")

        payment_ids = []
        for p in payment.get("payment_rows", [])[:5]:
            seq = p.get("payment_sequential")
            if seq is not None:
                payment_ids.append(f"{order_id}:{seq}")

        affected_seller_ids = late_seller_ids[:3] if responsible_party_type == "seller" else investigation.get("seller_ids", [])[:3]

        # ── LLM Synthesis for confidence ──
        confidence = self._llm_confidence(
            primary_issue, secondary_issues, investigation, delivery, payment
        )

        result = {
            "agent": self.AGENT_NAME,
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "case_status": case_status,
            "confidence": confidence,
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": affected_seller_ids,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": ranked_causes,
                "responsible_parties": responsible_parties,
            },
            "evidence_ids": evidence_ids,
            "recommended_refund_brl": round(float(recommended_refund), 2),
            "resolution_actions": actions[:5],
        }

        return result

    def _llm_confidence(self, primary_issue, secondary_issues, inv, deliv, pay) -> float:
        system_prompt = (
            "You are a policy evaluation agent. Given the case analysis, "
            "rate your confidence in the assessment from 0.0 to 1.0. "
            "Respond with JSON: {confidence: float, reasoning: string}."
        )
        user_prompt = (
            f"Primary issue: {primary_issue}\n"
            f"Secondary issues: {secondary_issues}\n"
            f"Order status: {inv.get('order_status')}\n"
            f"Late delivery: {deliv.get('is_late_delivery')}\n"
            f"Late seller: {deliv.get('has_late_seller')}\n"
            f"Delivery variance hours: {deliv.get('delivery_variance_hours')}\n"
            f"Payment reconciled: {pay.get('reconciled')}\n"
            f"Payment difference: {pay.get('difference_brl')}\n"
        )
        try:
            resp = self.llm.call_json(system_prompt, user_prompt, max_tokens=256)
            conf = resp.get("confidence", 0.85)
            return max(0.0, min(1.0, round(float(conf), 2)))
        except Exception:
            return 0.85
