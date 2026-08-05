"""
Payment Agent — Reconciles payments against items + freight.
Deterministic arithmetic + LLM pattern analysis.
"""

from agents.data_access import DataAccessLayer
from agents.llm_client import LLMClient


class PaymentAgent:
    AGENT_NAME = "PaymentAgent"

    def __init__(self, dal: DataAccessLayer, llm: LLMClient):
        self.dal = dal
        self.llm = llm

    def analyze(self, order_id: str) -> dict:
        print(f"  [{self.AGENT_NAME}] Analyzing payments for order {order_id}...")
        items = self.dal.get_order_items(order_id)
        payments = self.dal.get_payments(order_id)

        payment_total = round(sum(p.get("payment_value", 0) for p in payments), 2)
        payment_types = list(dict.fromkeys(
            p.get("payment_type") for p in payments if p.get("payment_type")
        ))

        if len(items) == 0:
            item_total = freight_total = expected_total = difference = reconciled = None
        else:
            item_total = round(sum(i.get("price", 0) for i in items), 2)
            freight_total = round(sum(i.get("freight_value", 0) for i in items), 2)
            expected_total = round(item_total + freight_total, 2)
            difference = round(payment_total - expected_total, 2)
            reconciled = abs(difference) <= 0.10

        result = {
            "agent": self.AGENT_NAME,
            "order_id": order_id,
            "currency": "BRL",
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected_total,
            "payment_total_brl": payment_total,
            "difference_brl": difference,
            "reconciled": reconciled,
            "payment_types": payment_types,
            "payment_count": len(payments),
            "payment_rows": payments,
        }

        llm_analysis = self._llm_analyze(result)
        result["llm_analysis"] = llm_analysis
        return result

    def _llm_analyze(self, data: dict) -> str:
        system_prompt = (
            "You are a payment reconciliation agent. Analyze payment data. "
            "Respond with JSON: {status, pattern, notes}."
        )
        user_prompt = (
            f"Order: {data['order_id']}, Item total: {data['item_total_brl']}, "
            f"Freight: {data['freight_total_brl']}, Expected: {data['expected_total_brl']}, "
            f"Payment total: {data['payment_total_brl']}, Diff: {data['difference_brl']}, "
            f"Reconciled: {data['reconciled']}, Types: {data['payment_types']}, Count: {data['payment_count']}"
        )
        try:
            return self.llm.call(system_prompt, user_prompt, max_tokens=256)
        except Exception as e:
            return f'{{"status":"unknown","notes":"LLM failed: {e}"}}'
