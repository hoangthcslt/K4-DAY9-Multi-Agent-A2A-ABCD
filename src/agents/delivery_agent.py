"""Delivery Agent: delivery lateness and per-seller carrier handoff lateness.

Reads: the delivery analysis computed by src.policy_rules.analyze_delivery.
Hands off a lateness-attribution judgement to the Coordinator, which the
Policy Agent needs to separate seller fault from logistics fault.
"""

import json

from src.agents.base import Agent, as_text


class DeliveryAgent(Agent):
    name = "delivery_agent"
    system_prompt = (
        "You are the Delivery Agent in an e-commerce dispute investigation. "
        "You receive pre-computed delivery timings from the Olist dataset. "
        "Do NOT recompute hours; read the provided variance values. "
        "A positive delivery_variance_hours means delivered AFTER the estimate. "
        "A positive handoff_variance_hours means the seller handed the parcel to "
        "the carrier AFTER its shipping limit. "
        "Reply with JSON: {\"blame\": \"seller\" | \"logistics_provider\" | \"none\", "
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
        delivered_late, blame = self._deterministic_blame(facts)
        return {
            "delivered_late": delivered_late,
            "blame": blame,
            "model_blame": as_text(response.get("blame")),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        delivered_late, blame = self._deterministic_blame(facts)
        return {
            "delivered_late": delivered_late,
            "blame": blame,
            "model_blame": "",
            "summary": "",
            "llm_available": False,
        }

    @staticmethod
    def _deterministic_blame(facts):
        # Facts decide; the model's blame call is recorded but reconciled to data.
        variance = facts.get("delivery_variance_hours")
        delivered_late = variance is not None and variance > 0
        any_late_handoff = bool(facts.get("late_handoff_seller_ids"))
        if not delivered_late:
            blame = "none"
        elif any_late_handoff:
            blame = "seller"
        else:
            blame = "logistics_provider"
        return delivered_late, blame


def build_delivery_facts(delivery):
    return {
        "delivered_at": delivery["delivered_at"],
        "estimated_delivery_at": delivery["estimated_delivery_at"],
        "carrier_handoff_at": delivery["carrier_handoff_at"],
        "delivery_variance_hours": delivery["delivery_variance_hours"],
        "seller_handoff_analysis": delivery["seller_handoff_analysis"],
        "late_handoff_seller_ids": delivery["late_handoff_seller_ids"],
    }
