from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from .base import BaseAgent


class CustomerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "customer"

    async def run(self, context: CaseContext) -> AgentHandoff:
        case_id = context.case.case_id
        order_id = context.case.claimed_order_id
        try:
            order = self.indexes.order(order_id)
            customer = self.indexes.customers_by_id[order["customer_id"]]
            unique_id = customer["customer_unique_id"]
            related = [
                value
                for value in self.indexes.customer_order_ids_by_unique_id.get(unique_id, [])
                if value != order_id
            ]
            related = related[:5] if context.case.investigation_scope.get(
                "include_customer_history", False
            ) else []
            facts = {
                "customer_unique_id": unique_id,
                "related_order_ids": related,
                "repeat_customer": bool(related),
            }
            review, llm_meta = await self.call_llm(
                context,
                system_prompt=(
                    "You are the Customer Agent. Review only the deterministic customer "
                    "join below. Do not invent IDs. Return one JSON object only with "
                    "consistent (boolean), customer_unique_id (string or null), "
                    "related_order_ids (array), note (string)."
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
                evidence_ids=[f"order:{order_id}"],
                confidence=1.0,
            )
        except KeyError as exc:
            facts = {"error": str(exc)}
            review, llm_meta = await self.call_llm(
                context,
                system_prompt=(
                    "You are the Customer Agent. Review the failed customer join. "
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
