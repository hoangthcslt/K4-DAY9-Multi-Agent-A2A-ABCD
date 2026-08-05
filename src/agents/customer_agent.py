"""Customer Agent: identity and purchase history.

Reads: bundle.customer, bundle.related_order_ids
Hands off: customer_context plus a repeat-customer judgement to the Coordinator.
"""

import json

from agents.base import Agent, as_bool, as_text

MAX_RELATED_ORDER_IDS = 5


class CustomerAgent(Agent):
    name = "customer_agent"
    system_prompt = (
        "You are the Customer Agent in an e-commerce dispute investigation. "
        "You receive verified customer facts extracted from the Olist dataset. "
        "Never invent orders or IDs; judge only what the facts show. "
        "Reply with JSON: {\"is_repeat_customer\": bool, "
        "\"related_order_count\": int, \"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Customer facts:\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nIs this a repeat customer (same customer_unique_id has other "
            "orders)? Report the count of related orders and summarise briefly."
        )

    def validate(self, response, facts):
        true_count = len(facts.get("related_order_ids", []))
        return {
            # The count is authoritative from data; the model only narrates.
            "is_repeat_customer": as_bool(
                response.get("is_repeat_customer"), default=true_count > 0
            ),
            "related_order_count": true_count,
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        count = len(facts.get("related_order_ids", []))
        return {
            "is_repeat_customer": count > 0,
            "related_order_count": count,
            "summary": "",
            "llm_available": False,
        }


def build_customer_context(bundle):
    """Deterministic customer_context block for the final output."""
    return {
        "customer_unique_id": bundle["customer"]["customer_unique_id"],
        "related_order_ids": bundle["related_order_ids"][:MAX_RELATED_ORDER_IDS],
    }
