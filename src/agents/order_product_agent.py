"""Order & Product Agent: order composition, items, sellers, products, categories.

Reads: bundle.order, bundle.items, bundle.seller_ids, bundle.product_ids
Hands off: composition findings to the Coordinator (and on to the Policy Agent).
"""

import json

from agents.base import Agent, as_bool, as_text

MAX_ORDER_IDS = 5
MAX_ITEM_IDS = 5
MAX_SELLER_IDS = 3
MAX_PRODUCT_IDS = 5
MAX_CATEGORY_NAMES = 5


class OrderProductAgent(Agent):
    name = "order_product_agent"
    system_prompt = (
        "You are the Order & Product Agent in an e-commerce dispute "
        "investigation. You receive verified order composition facts from the "
        "Olist dataset. Never invent items, sellers or products. "
        "Reply with JSON: {\"is_multi_item\": bool, \"is_multi_seller\": bool, "
        "\"has_multiple_categories\": bool, \"order_status\": \"string\", "
        "\"summary\": \"one short sentence\"}."
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
            "order_status": facts.get("order_status"),
            "summary": as_text(response.get("summary")),
        }

    def fallback(self, facts):
        return {
            "is_multi_item": facts.get("item_count", 0) >= 2,
            "is_multi_seller": facts.get("seller_count", 0) >= 2,
            "has_multiple_categories": facts.get("category_count", 0) >= 2,
            "order_status": facts.get("order_status"),
            "summary": "",
            "llm_available": False,
        }


def build_order_facts(bundle):
    """Compact fact sheet handed to the Order & Product Agent."""
    return {
        "order_id": bundle["order_id"],
        "order_status": bundle["order"]["order_status"],
        "item_count": len(bundle["items"]),
        "seller_count": len(bundle["seller_ids"]),
        "category_count": len(bundle["category_names"]),
        "items": [
            {
                "order_item_id": item["order_item_id"],
                "product_id": item["product_id"],
                "seller_id": item["seller_id"],
                "price": item["price"],
                "freight_value": item["freight_value"],
                "product_category_name": item["product_category_name"],
            }
            for item in bundle["items"]
        ],
    }


def build_affected_entities(bundle):
    """affected_entities block: the claimed order only, never history orders."""
    order_id = bundle["order_id"]
    return {
        "order_ids": [order_id][:MAX_ORDER_IDS],
        "item_ids": [
            "%s:%s" % (order_id, item["order_item_id"]) for item in bundle["items"]
        ][:MAX_ITEM_IDS],
        "seller_ids": bundle["seller_ids"][:MAX_SELLER_IDS],
        "payment_ids": [
            "%s:%s" % (order_id, payment["payment_sequential"])
            for payment in bundle["payments"]
        ][:MAX_ITEM_IDS],
    }


def build_product_context(bundle):
    return {
        "product_ids": bundle["product_ids"][:MAX_PRODUCT_IDS],
        "category_names": bundle["category_names"][:MAX_CATEGORY_NAMES],
    }
