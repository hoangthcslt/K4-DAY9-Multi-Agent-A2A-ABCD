"""Customer Agent: identity and purchase history.

Reads: the customer/related-order facts data_loader.get_customer_info() already
extracted. Hands off a repeat-customer judgement to the Coordinator; the
customer_context block itself is built deterministically (build_customer_context).
"""

import json

from src.agents.base import Agent, as_bool, as_text

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


def build_customer_facts(raw_customer):
    """Compact fact sheet handed to the Customer Agent's LLM call."""
    related = raw_customer.get("related_order_ids", []) or []
    return {
        "customer_unique_id": raw_customer.get("customer_unique_id"),
        "related_order_ids": related[:10],
    }


def build_customer_context(raw_customer):
    """Deterministic customer_context block for the final output. Ported
    unchanged from the original CustomerAgent.analyze."""
    uid = raw_customer.get("customer_unique_id") or ""
    related = raw_customer.get("related_order_ids", []) or []
    return {
        "customer_unique_id": str(uid),
        "related_order_ids": [str(r) for r in related][:MAX_RELATED_ORDER_IDS],
    }
