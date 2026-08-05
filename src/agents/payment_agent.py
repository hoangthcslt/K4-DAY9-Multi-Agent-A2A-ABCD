"""Payment Agent: reconcile payment rows against item price + freight.

Reads: bundle.payments plus the reconciliation computed by policy_rules.
Hands off: a reconciliation judgement to the Coordinator.

The arithmetic is done in policy_rules.analyze_payment. This agent reads the
computed figures and reports whether the order reconciles and why.
"""

import json

from agents.base import Agent, as_bool, as_text


class PaymentAgent(Agent):
    name = "payment_agent"
    system_prompt = (
        "You are the Payment Agent in an e-commerce dispute investigation. "
        "You receive payment rows and a pre-computed reconciliation from the "
        "Olist dataset. Do NOT recompute any number; read the provided values. "
        "Reply with JSON: {\"reconciled\": bool or null, \"is_split_payment\": "
        "bool, \"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Payment facts (already computed, do not recalculate):\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nDoes the payment total reconcile with expected item + freight "
            "total within the 0.10 BRL tolerance? Is this a split payment "
            "(2 or more payment rows)? Summarise briefly."
        )

    def validate(self, response, facts):
        # reconciled is null for orders with no item rows; preserve that.
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


def build_payment_facts(bundle, payment_reconciliation):
    return {
        "order_id": bundle["order_id"],
        "payment_row_count": len(bundle["payments"]),
        "payments": bundle["payments"],
        "item_total_brl": payment_reconciliation["item_total_brl"],
        "freight_total_brl": payment_reconciliation["freight_total_brl"],
        "expected_total_brl": payment_reconciliation["expected_total_brl"],
        "payment_total_brl": payment_reconciliation["payment_total_brl"],
        "difference_brl": payment_reconciliation["difference_brl"],
        "reconciled": payment_reconciliation["reconciled"],
        "tolerance_brl": 0.10,
    }
