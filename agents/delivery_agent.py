"""
Delivery Agent — Calculates delivery variance and seller handoff analysis.
Deterministic datetime math + LLM responsibility analysis.
"""

from datetime import datetime
from agents.data_access import DataAccessLayer
from agents.llm_client import LLMClient


class DeliveryAgent:
    """
    Analyzes delivery timing:
    - delivery_variance_hours: actual delivery vs estimated
    - handoff_variance_hours: carrier pickup vs seller shipping limit
    - Identifies late sellers
    """

    AGENT_NAME = "DeliveryAgent"
    TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, dal: DataAccessLayer, llm: LLMClient):
        self.dal = dal
        self.llm = llm

    def analyze(self, order_id: str) -> dict:
        """Main entry point. Returns delivery analysis."""
        print(f"  [{self.AGENT_NAME}] Analyzing delivery for order {order_id}...")

        order = self.dal.get_order(order_id)
        if order is None:
            return self._empty_result(order_id, "Order not found")

        items = self.dal.get_order_items(order_id)

        # ── Phase 1: Deterministic calculations ──

        delivered_at = order.get("order_delivered_customer_date")
        estimated_at = order.get("order_estimated_delivery_date")
        carrier_handoff_at = order.get("order_delivered_carrier_date")

        # Delivery variance
        delivery_variance_hours = self._calc_variance_hours(delivered_at, estimated_at)

        # Seller handoff analysis
        seller_handoff_analysis = []
        late_handoff_seller_ids = []

        for item in items:
            seller_id = item.get("seller_id")
            shipping_limit = item.get("shipping_limit_date")

            if seller_id is None or shipping_limit is None:
                continue

            # Check if we already analyzed this seller (use earliest shipping_limit)
            existing = next(
                (s for s in seller_handoff_analysis if s["seller_id"] == seller_id),
                None,
            )

            handoff_variance = self._calc_variance_hours(carrier_handoff_at, shipping_limit)

            if existing is None:
                late = handoff_variance is not None and handoff_variance > 0
                seller_handoff_analysis.append({
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit,
                    "handoff_variance_hours": handoff_variance,
                    "late_handoff": late,
                })
                if late:
                    late_handoff_seller_ids.append(seller_id)
            else:
                # Update if this shipping_limit is earlier
                if shipping_limit < existing["shipping_limit_at"]:
                    existing["shipping_limit_at"] = shipping_limit
                    existing["handoff_variance_hours"] = handoff_variance
                    existing["late_handoff"] = handoff_variance is not None and handoff_variance > 0
                    # Update late list
                    if existing["late_handoff"] and seller_id not in late_handoff_seller_ids:
                        late_handoff_seller_ids.append(seller_id)
                    elif not existing["late_handoff"] and seller_id in late_handoff_seller_ids:
                        late_handoff_seller_ids.remove(seller_id)

        is_late_delivery = delivery_variance_hours is not None and delivery_variance_hours > 0

        result = {
            "agent": self.AGENT_NAME,
            "order_id": order_id,
            "delivered_at": delivered_at,
            "estimated_delivery_at": estimated_at,
            "carrier_handoff_at": carrier_handoff_at,
            "delivery_variance_hours": delivery_variance_hours,
            "is_late_delivery": is_late_delivery,
            "seller_handoff_analysis": seller_handoff_analysis,
            "late_handoff_seller_ids": late_handoff_seller_ids,
            "has_late_seller": len(late_handoff_seller_ids) > 0,
        }

        # ── Phase 2: LLM responsibility analysis ──
        llm_analysis = self._llm_analyze(result)
        result["llm_analysis"] = llm_analysis

        return result

    def _calc_variance_hours(self, actual: str | None, reference: str | None) -> float | None:
        """Calculate hours difference: actual - reference. Positive = late."""
        if actual is None or reference is None:
            return None
        try:
            actual_dt = datetime.strptime(str(actual).strip(), self.TIMESTAMP_FMT)
            reference_dt = datetime.strptime(str(reference).strip(), self.TIMESTAMP_FMT)
            delta = actual_dt - reference_dt
            return round(delta.total_seconds() / 3600, 2)
        except (ValueError, TypeError):
            return None

    def _llm_analyze(self, data: dict) -> str:
        """Use LLM to analyze delivery responsibility."""
        system_prompt = (
            "You are a delivery analysis agent for e-commerce disputes. "
            "Analyze the delivery data and determine responsibility. "
            "Respond ONLY with a JSON object with keys: "
            "responsibility (seller/logistics/none/unknown), "
            "reasoning (brief explanation), "
            "severity (low/medium/high)."
        )

        user_prompt = (
            f"Order: {data['order_id']}\n"
            f"Delivered at: {data['delivered_at']}\n"
            f"Estimated delivery: {data['estimated_delivery_at']}\n"
            f"Carrier handoff: {data['carrier_handoff_at']}\n"
            f"Delivery variance (hours): {data['delivery_variance_hours']}\n"
            f"Is late delivery: {data['is_late_delivery']}\n"
            f"Seller handoff analysis: {data['seller_handoff_analysis']}\n"
            f"Late sellers: {data['late_handoff_seller_ids']}\n"
        )

        try:
            return self.llm.call(system_prompt, user_prompt, max_tokens=512)
        except Exception as e:
            return f'{{"responsibility": "unknown", "reasoning": "LLM failed: {str(e)}", "severity": "unknown"}}'

    def _empty_result(self, order_id: str, reason: str) -> dict:
        return {
            "agent": self.AGENT_NAME,
            "order_id": order_id,
            "delivered_at": None,
            "estimated_delivery_at": None,
            "carrier_handoff_at": None,
            "delivery_variance_hours": None,
            "is_late_delivery": False,
            "seller_handoff_analysis": [],
            "late_handoff_seller_ids": [],
            "has_late_seller": False,
            "llm_analysis": '{"responsibility": "unknown", "reasoning": "' + reason + '", "severity": "unknown"}',
        }
