"""Delivery Agent: delivery lateness and per-seller carrier handoff lateness.

Reads: the delivery analysis computed by policy_rules.
Hands off: a lateness attribution judgement to the Coordinator, which the Policy
Agent needs to separate seller fault from logistics fault.
"""

import json

from agents.base import Agent, as_bool, as_text


class DeliveryAgent(Agent):
    name = "delivery_agent"
    system_prompt = (
        "You are the Delivery Agent in an e-commerce dispute investigation. "
        "You receive pre-computed delivery timings from the Olist dataset. "
        "Do NOT recompute hours; read the provided variance values. "
        "A positive delivery_variance_hours means delivered AFTER the estimate. "
        "A positive handoff_variance_hours means the seller handed the parcel to "
        "the carrier AFTER its shipping limit. "
        "Reply with JSON: {\"delivered_late\": bool, \"any_seller_late_handoff\": "
        "bool, \"blame\": \"seller\" | \"logistics_provider\" | \"none\", "
        "\"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Delivery facts (already computed, do not recalculate):\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nWas the order delivered after the estimated date? Did any "
            "seller hand off late? Who is to blame for any delay?"
        )

    def validate(self, response, facts):
        variance = facts.get("delivery_variance_hours")
        delivered_late = variance is not None and variance > 0
        any_late_handoff = bool(facts.get("late_handoff_seller_ids"))

        # Facts decide; the model's blame call is recorded but reconciled to data.
        if not delivered_late:
            blame = "none"
        elif any_late_handoff:
            blame = "seller"
        else:
            blame = "logistics_provider"

        return {
            "delivered_late": delivered_late,
            "any_seller_late_handoff": any_late_handoff,
            "blame": blame,
            "model_blame": as_text(response.get("blame")),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        variance = facts.get("delivery_variance_hours")
        delivered_late = variance is not None and variance > 0
        any_late_handoff = bool(facts.get("late_handoff_seller_ids"))
        if not delivered_late:
            blame = "none"
        elif any_late_handoff:
            blame = "seller"
        else:
            blame = "logistics_provider"
        return {
            "delivered_late": delivered_late,
            "any_seller_late_handoff": any_late_handoff,
            "blame": blame,
            "model_blame": "",
            "summary": "",
            "llm_available": False,
        }


def build_delivery_facts(bundle, delivery_analysis):
    return {
        "order_id": bundle["order_id"],
        "order_status": bundle["order"]["order_status"],
        "delivered_at": delivery_analysis["delivered_at"],
        "estimated_delivery_at": delivery_analysis["estimated_delivery_at"],
        "carrier_handoff_at": delivery_analysis["carrier_handoff_at"],
        "delivery_variance_hours": delivery_analysis["delivery_variance_hours"],
        "seller_handoff_analysis": delivery_analysis["seller_handoff_analysis"],
        "late_handoff_seller_ids": delivery_analysis["late_handoff_seller_ids"],
    }
