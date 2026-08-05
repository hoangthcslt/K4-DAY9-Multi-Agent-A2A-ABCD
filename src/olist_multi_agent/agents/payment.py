from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from ..facts import decimal, money, unique_stable
from .base import BaseAgent


class PaymentAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "payment"

    async def run(self, context: CaseContext) -> AgentHandoff:
        case_id = context.case.case_id
        order_id = context.case.claimed_order_id
        payments = sorted(
            self.indexes.payments_by_order.get(order_id, []),
            key=lambda row: int(row.get("payment_sequential", "0") or 0),
        )
        items = self.indexes.items_by_order.get(order_id, [])
        payment_ids = [f"{order_id}:{row['payment_sequential']}" for row in payments]
        payment_total = sum((decimal(row.get("payment_value")) for row in payments), decimal())
        payment_types = unique_stable(row.get("payment_type", "") for row in payments if row.get("payment_type"))

        # Empty item sums are represented as zero; only the derived
        # reconciliation fields are undefined when no item row exists.
        item_total = freight_total = 0.0
        expected_total = difference = None
        reconciled = None
        if items:
            item_total_decimal = sum((decimal(row.get("price")) for row in items), decimal())
            freight_total_decimal = sum(
                (decimal(row.get("freight_value")) for row in items), decimal()
            )
            expected_decimal = item_total_decimal + freight_total_decimal
            difference_decimal = payment_total - expected_decimal
            item_total = money(item_total_decimal)
            freight_total = money(freight_total_decimal)
            expected_total = money(expected_decimal)
            difference = money(difference_decimal)
            reconciled = abs(difference_decimal) <= decimal("0.10")

        facts = {
            "payment_ids": payment_ids[:5],
            "payment_types": payment_types,
            "payment_count": len(payments),
            "payment_total_brl": money(payment_total),
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected_total,
            "difference_brl": difference,
            "reconciled": reconciled,
            "split_payment": len(payments) >= 2,
        }
        review, llm_meta = await self.call_llm(
            context,
            system_prompt=(
                "You are the Payment Agent. Review the deterministic Decimal-based "
                "reconciliation. Do not recalculate or alter amounts. Return one JSON "
                "object only with reconciled (boolean or null), split_payment (boolean), "
                "arithmetic_consistent (boolean), note (string)."
            ),
            user_payload={
                "case_id": case_id,
                "claimed_order_id": order_id,
                "deterministic_facts": facts,
            },
        )
        self.attach_llm_review(facts, review, llm_meta)
        return AgentHandoff(
            case_id=case_id,
            agent=self.name,
            status="ok",
            facts=facts,
            evidence_ids=[f"order:{order_id}"]
            + [f"payment:{payment_id}" for payment_id in payment_ids[:5]],
            confidence=1.0,
        )
