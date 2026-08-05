"""
Investigation Agent — Combines Customer + Order + Product lookups.
Deterministic data retrieval + LLM analysis summary.
"""

from agents.data_access import DataAccessLayer
from agents.llm_client import LLMClient


class InvestigationAgent:
    """
    Merges Customer, Order, and Product domains into a single investigation.
    - Pandas: data lookup (deterministic, accurate)
    - LLM: analyze findings, flag anomalies
    """

    AGENT_NAME = "InvestigationAgent"

    def __init__(self, dal: DataAccessLayer, llm: LLMClient):
        self.dal = dal
        self.llm = llm

    def investigate(self, order_id: str) -> dict:
        """
        Main entry point. Returns structured investigation results.
        """
        print(f"  [{self.AGENT_NAME}] Investigating order {order_id}...")

        # ── Phase 1: Deterministic data lookup ──
        order = self.dal.get_order(order_id)
        if order is None:
            return self._empty_result(order_id, "Order not found in database")

        items = self.dal.get_order_items(order_id)
        payments = self.dal.get_payments(order_id)

        # Customer info
        customer = self.dal.get_customer_by_id(order["customer_id"])
        customer_unique_id = customer["customer_unique_id"] if customer else None

        # Related orders (repeat customer)
        related_orders = []
        if customer_unique_id:
            all_customer_orders = self.dal.get_customer_orders(customer_unique_id)
            related_orders = [
                o["order_id"] for o in all_customer_orders
                if o["order_id"] != order_id
            ]

        # Products and categories
        product_ids = []
        category_names = []
        seller_ids = []
        products_detail = []

        for item in items:
            pid = item.get("product_id")
            sid = item.get("seller_id")

            if pid and pid not in product_ids:
                product_ids.append(pid)
                product = self.dal.get_product(pid)
                if product:
                    products_detail.append(product)
                    cat_pt = product.get("product_category_name")
                    cat_en = self.dal.get_category_english(cat_pt) if cat_pt else None
                    cat_name = cat_en if cat_en else cat_pt
                    if cat_name and cat_name not in category_names:
                        category_names.append(cat_name)

            if sid and sid not in seller_ids:
                seller_ids.append(sid)

        # Build structured result
        result = {
            "agent": self.AGENT_NAME,
            "order_id": order_id,
            "order": order,
            "order_status": order.get("order_status"),
            "items": items,
            "item_count": len(items),
            "seller_ids": seller_ids,
            "unique_seller_count": len(seller_ids),
            "product_ids": product_ids[:5],  # limit per spec
            "category_names": category_names[:5],
            "unique_category_count": len(category_names),
            "payments": payments,
            "payment_count": len(payments),
            "customer": {
                "customer_unique_id": customer_unique_id,
                "related_order_ids": related_orders[:5],  # limit per spec
            },
            "is_repeat_customer": len(related_orders) > 0,
            "flags": {
                "multi_item_order": len(items) >= 2,
                "multi_seller_order": len(seller_ids) >= 2,
                "split_payment": len(payments) >= 2,
                "repeat_customer": len(related_orders) > 0,
                "multiple_categories": len(category_names) >= 2,
            },
        }

        # ── Phase 2: LLM analysis ──
        llm_analysis = self._llm_analyze(result)
        result["llm_analysis"] = llm_analysis

        return result

    def _llm_analyze(self, data: dict) -> str:
        """Use LLM to summarize investigation findings."""
        system_prompt = (
            "You are an e-commerce investigation agent. Analyze the order data provided "
            "and produce a brief JSON summary of your findings. Focus on:\n"
            "1. Order status and any anomalies\n"
            "2. Whether this is a multi-item, multi-seller, or split-payment order\n"
            "3. Customer history (repeat customer or not)\n"
            "4. Product categories involved\n"
            "Respond ONLY with a JSON object with keys: summary, anomalies, risk_level (low/medium/high)."
        )

        user_prompt = (
            f"Order ID: {data['order_id']}\n"
            f"Order Status: {data['order_status']}\n"
            f"Item Count: {data['item_count']}\n"
            f"Unique Sellers: {data['unique_seller_count']}\n"
            f"Payment Methods: {data['payment_count']} payments\n"
            f"Categories: {data['category_names']}\n"
            f"Repeat Customer: {data['is_repeat_customer']}\n"
            f"Related Orders: {len(data['customer']['related_order_ids'])}\n"
            f"Flags: {data['flags']}\n"
        )

        try:
            response = self.llm.call(system_prompt, user_prompt, max_tokens=512)
            return response
        except Exception as e:
            return f'{{"summary": "LLM analysis failed: {str(e)}", "anomalies": [], "risk_level": "unknown"}}'

    def _empty_result(self, order_id: str, reason: str) -> dict:
        return {
            "agent": self.AGENT_NAME,
            "order_id": order_id,
            "error": reason,
            "order": None,
            "order_status": None,
            "items": [],
            "item_count": 0,
            "seller_ids": [],
            "unique_seller_count": 0,
            "product_ids": [],
            "category_names": [],
            "unique_category_count": 0,
            "payments": [],
            "payment_count": 0,
            "customer": {"customer_unique_id": None, "related_order_ids": []},
            "is_repeat_customer": False,
            "flags": {
                "multi_item_order": False,
                "multi_seller_order": False,
                "split_payment": False,
                "repeat_customer": False,
                "multiple_categories": False,
            },
            "llm_analysis": '{"summary": "' + reason + '", "anomalies": [], "risk_level": "unknown"}',
        }
