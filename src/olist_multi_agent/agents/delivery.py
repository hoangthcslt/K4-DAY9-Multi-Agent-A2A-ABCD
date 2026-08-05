from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from ..facts import hours_between, timestamp
from .base import BaseAgent


class DeliveryAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "delivery"

    async def run(self, context: CaseContext) -> AgentHandoff:
        case_id = context.case.case_id
        order_id = context.case.claimed_order_id
        try:
            order = self.indexes.order(order_id)
        except KeyError as exc:
            facts = {"error": str(exc)}
            review, llm_meta = await self.call_llm(
                context,
                system_prompt=(
                    "You are the Delivery Agent. Review the failed delivery lookup. "
                    "Return one JSON object with consistent (boolean) and note (string); "
                    "do not invent data."
                ),
                user_payload={"case_id": case_id, "error": str(exc)},
            )
            self.attach_llm_review(facts, review, llm_meta)
            return AgentHandoff(
                case_id=case_id,
                agent=self.name,
                status="error",
                facts=facts,
                warnings=[str(exc)],
            )

        delivered_at = order.get("order_delivered_customer_date") or None
        estimated_at = order.get("order_estimated_delivery_date") or None
        carrier_at = order.get("order_delivered_carrier_date") or None
        delivery_hours = hours_between(timestamp(delivered_at), timestamp(estimated_at))
        carrier_dt = timestamp(carrier_at)

        seller_limits: dict[str, tuple[str, object]] = {}
        for row in self.indexes.items_by_order.get(order_id, []):
            seller_id = row.get("seller_id", "")
            shipping_limit = row.get("shipping_limit_date", "")
            if not seller_id or not shipping_limit:
                continue
            limit_dt = timestamp(shipping_limit)
            if limit_dt is None:
                continue
            previous = seller_limits.get(seller_id)
            if previous is None or limit_dt < previous[1]:
                seller_limits[seller_id] = (shipping_limit, limit_dt)

        seller_analysis: list[dict[str, object]] = []
        late_seller_ids: list[str] = []
        for seller_id in seller_limits:
            shipping_limit_at, shipping_limit_dt = seller_limits[seller_id]
            variance = hours_between(carrier_dt, shipping_limit_dt)  # type: ignore[arg-type]
            late_handoff = variance is not None and variance > 0
            seller_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": variance,
                    "late_handoff": late_handoff,
                }
            )
            if late_handoff:
                late_seller_ids.append(seller_id)

        facts = {
            "delivered_at": delivered_at,
            "estimated_delivery_at": estimated_at,
            "carrier_handoff_at": carrier_at,
            "delivery_variance_hours": delivery_hours,
            "seller_handoff_analysis": seller_analysis,
            "late_handoff_seller_ids": late_seller_ids[:3],
            "delivery_late": delivery_hours is not None and delivery_hours > 0,
        }
        review, llm_meta = await self.call_llm(
            context,
            system_prompt=(
                "You are the Delivery Agent. Review deterministic datetime variance "
                "and seller handoff facts. Do not change timestamps or calculations. "
                "Return one JSON object only with delivery_late (boolean), "
                "late_handoff_seller_ids (array), consistent (boolean), note (string)."
            ),
            user_payload={
                "case_id": case_id,
                "claimed_order_id": order_id,
                "deterministic_facts": {
                    "delivery_variance_hours": facts["delivery_variance_hours"],
                    "late_handoff_seller_ids": facts["late_handoff_seller_ids"],
                    "delivery_late": facts["delivery_late"],
                    "seller_count": len(facts["seller_handoff_analysis"]),
                },
            },
        )
        self.attach_llm_review(facts, review, llm_meta)
        return AgentHandoff(
            case_id=case_id,
            agent=self.name,
            status="ok",
            facts=facts,
            evidence_ids=[f"order:{order_id}"],
            confidence=1.0,
        )
