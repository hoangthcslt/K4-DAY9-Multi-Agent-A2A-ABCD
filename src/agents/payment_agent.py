"""Payment Agent: reconcile payment rows against item price + freight.

The arithmetic is done in src.policy_rules.analyze_payment. This agent reads
the computed figures and reports whether the order reconciles and why - it
never recomputes any number.
"""

import json

from src.agents.base import Agent, as_bool, as_text
from src.policy_rules import RECONCILE_TOLERANCE_BRL


class PaymentAgent(Agent):
    name = "payment_agent"
    system_prompt = (
        "You are the Payment Agent in an e-commerce dispute investigation. "
        "You receive payment rows and a pre-computed reconciliation from the "
        "Olist dataset. Do NOT recompute any number; read the provided values. "
        "Reply with JSON: {\"is_split_payment\": bool, "
        "\"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Payment facts (already computed, do not recalculate):\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nIs this a split payment (2 or more payment rows)? "
            "Summarise the reconciliation briefly."
        )

    def validate(self, response, facts):
        # reconciled is authoritative and null for orders with no item row.
        return {
            "reconciled": facts.get("reconciled"),
            "is_split_payment": as_bool(
                response.get("is_split_payment"),
                default=facts.get("payment_row_count", 0) >= 2,
            ),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        return {
            "reconciled": facts.get("reconciled"),
            "is_split_payment": facts.get("payment_row_count", 0) >= 2,
            "summary": "",
            "llm_available": False,
        }


def build_payment_facts(payment):
    return {
        "payment_row_count": len(payment.get("payment_ids", [])),
        "payment_types": payment.get("payment_types", []),
        "item_total_brl": payment.get("item_total_brl"),
        "freight_total_brl": payment.get("freight_total_brl"),
        "expected_total_brl": payment.get("expected_total_brl"),
        "payment_total_brl": payment.get("payment_total_brl"),
        "difference_brl": payment.get("difference_brl"),
        "reconciled": payment.get("reconciled"),
        "tolerance_brl": RECONCILE_TOLERANCE_BRL,
    }
