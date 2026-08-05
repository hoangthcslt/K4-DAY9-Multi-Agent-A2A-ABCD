"""Order & Product Agent: order composition, items, sellers, products, categories.

Reads: the composition facts src.policy_rules.analyze_order_product() already
computed. Hands off a composition judgement to the Coordinator (used by the
Policy Agent as a cross-check input). affected_entities/product_context are
built deterministically here, ported unchanged from the original
VerifierAgent.build_final.
"""

import json

from src.agents.base import Agent, as_bool, as_text

MAX_ORDER_IDS = 5
MAX_ITEM_IDS = 5
MAX_SELLER_IDS = 3
MAX_PAYMENT_IDS = 5
MAX_PRODUCT_IDS = 5
MAX_CATEGORY_NAMES = 5


class OrderProductAgent(Agent):
    name = "order_product_agent"
    system_prompt = (
        "You are the Order & Product Agent in an e-commerce dispute "
        "investigation. You receive verified order composition facts from the "
        "Olist dataset. Never invent items, sellers or products. "
        "Reply with JSON: {\"is_multi_item\": bool, \"is_multi_seller\": bool, "
        "\"has_multiple_categories\": bool, \"summary\": \"one short sentence\"}."
    )

    def build_prompt(self, facts):
        return (
            "Order composition facts:\n"
            + json.dumps(facts, ensure_ascii=False, indent=1)
            + "\n\nAssess whether this order has multiple items, multiple "
            "distinct sellers, and multiple product categories. Summarise."
        )

    def validate(self, response, facts):
        # Counts come from data; the model's booleans are cross-checked, not trusted.
        item_count = facts.get("item_count", 0)
        seller_count = facts.get("seller_count", 0)
        category_count = facts.get("category_count", 0)
        return {
            "is_multi_item": as_bool(
                response.get("is_multi_item"), default=item_count >= 2
            ),
            "is_multi_seller": as_bool(
                response.get("is_multi_seller"), default=seller_count >= 2
            ),
            "has_multiple_categories": as_bool(
                response.get("has_multiple_categories"), default=category_count >= 2
            ),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        return {
            "is_multi_item": facts.get("item_count", 0) >= 2,
            "is_multi_seller": facts.get("seller_count", 0) >= 2,
            "has_multiple_categories": facts.get("category_count", 0) >= 2,
            "summary": "",
            "llm_available": False,
        }


def build_order_facts(order_id, order, raw_items):
    """Compact fact sheet handed to the Order & Product Agent's LLM call."""
    return {
        "order_id": order_id,
        "item_count": len(raw_items),
        "seller_count": len(order.get("seller_ids", [])),
        "category_count": len(order.get("category_names", [])),
    }


def build_affected_entities(order_id, order, payment):
    """affected_entities block: the claimed order only, never history orders.
    Ported unchanged from the original VerifierAgent.build_final."""
    unique_seller_ids = list(dict.fromkeys(order.get("seller_ids", [])))[:MAX_SELLER_IDS]
    return {
        "order_ids": [order_id][:MAX_ORDER_IDS],
        "item_ids": order.get("item_ids", [])[:MAX_ITEM_IDS],
        "seller_ids": unique_seller_ids,
        "payment_ids": payment.get("payment_ids", [])[:MAX_PAYMENT_IDS],
    }


def build_product_context(order):
    return {
        "product_ids": order.get("product_ids", [])[:MAX_PRODUCT_IDS],
        "category_names": order.get("category_names", [])[:MAX_CATEGORY_NAMES],
    }
