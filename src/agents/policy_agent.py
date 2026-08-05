"""Policy Agent: apply EC_POLICY_V2.

Reads: findings handed over by the Customer, Order/Product, Payment and
Delivery agents, plus the deterministic assessment from src.policy_rules.
Hands off the classified case (issue, responsibility, refund, actions) to the
Verifier.

The LLM classifies the case independently from the handed-over findings, as a
cross-check. Its answer is compared against policy_rules; the rules always
win for every graded field. Only case_assessment.confidence depends on
whether the model agrees.
"""

import json

from src.agents.base import Agent, as_text
from src.policy_rules import (
    PRIMARY_CANCELED,
    PRIMARY_LATE_LOGISTICS,
    PRIMARY_LATE_SELLER,
    PRIMARY_UNAVAILABLE,
    PRIMARY_UNSUPPORTED,
    PRIMARY_VALID_SPLIT,
)

VALID_PRIMARY_ISSUES = {
    PRIMARY_CANCELED,
    PRIMARY_UNAVAILABLE,
    PRIMARY_LATE_SELLER,
    PRIMARY_LATE_LOGISTICS,
    PRIMARY_VALID_SPLIT,
    PRIMARY_UNSUPPORTED,
}

# Confidence reported when the model's independent classification agrees with
# the deterministic rules, when it disagrees, and when no LLM was available.
CONFIDENCE_AGREEMENT = 0.95
CONFIDENCE_DISAGREEMENT = 0.75
CONFIDENCE_NO_LLM = 0.80


class PolicyAgent(Agent):
    name = "policy_agent"
    system_prompt = (
        "You are the Policy Agent applying policy EC_POLICY_V2 to an "
        "e-commerce dispute. Choose the FIRST matching rule in this priority "
        "order:\n"
        "1. canceled_order_paid: order_status is 'canceled' AND total payment > 0\n"
        "2. unavailable_order_paid: order_status is 'unavailable' AND total payment > 0\n"
        "3. late_delivery_seller: delivered after the estimate AND at least one "
        "seller handed off to the carrier after its shipping limit\n"
        "4. late_delivery_logistics: delivered after the estimate AND no seller "
        "handed off late\n"
        "5. valid_split_payment: 2 or more payment rows AND the payment total "
        "reconciles with item + freight within 0.10 BRL\n"
        "6. unsupported_late_claim: none of the above matched\n"
        "Reply with JSON: {\"primary_issue\": \"<one of the six>\", "
        "\"reasoning\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Findings handed over by the domain agents:\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nApply EC_POLICY_V2 and classify the primary issue."
        )

    def validate(self, response, facts):
        model_issue = as_text(response.get("primary_issue")).strip()
        if model_issue not in VALID_PRIMARY_ISSUES:
            model_issue = ""
        rules_issue = facts["deterministic_primary_issue"]
        agrees = model_issue == rules_issue
        return {
            # policy_rules is authoritative; the model provides a cross-check.
            "primary_issue": rules_issue,
            "model_primary_issue": model_issue,
            "agrees_with_rules": agrees,
            "confidence": CONFIDENCE_AGREEMENT if agrees else CONFIDENCE_DISAGREEMENT,
            "reasoning": as_text(response.get("reasoning")),
        }

    def fallback(self, facts):
        return {
            "primary_issue": facts["deterministic_primary_issue"],
            "model_primary_issue": "",
            "agrees_with_rules": False,
            "confidence": CONFIDENCE_NO_LLM,
            "reasoning": "",
            "llm_available": False,
        }


def build_policy_facts(delivery, payment, customer_finding, order_finding,
                        payment_finding, delivery_finding, deterministic_primary_issue):
    """Fact sheet assembled from every upstream agent's handoff."""
    return {
        "payment_total_brl": payment.get("payment_total_brl"),
        "payment_row_count": len(payment.get("payment_ids", [])),
        "reconciled": payment.get("reconciled"),
        "delivery_variance_hours": delivery.get("delivery_variance_hours"),
        "late_handoff_seller_ids": delivery.get("late_handoff_seller_ids"),
        "customer_finding": customer_finding,
        "order_finding": order_finding,
        "payment_finding": payment_finding,
        "delivery_finding": delivery_finding,
        "deterministic_primary_issue": deterministic_primary_issue,
    }
