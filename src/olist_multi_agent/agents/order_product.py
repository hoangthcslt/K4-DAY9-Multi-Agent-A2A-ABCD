from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from ..facts import unique_stable
from .base import BaseAgent


class OrderProductAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "order_product"

    async def run(self, context: CaseContext) -> AgentHandoff:
        case_id = context.case.case_id
        order_id = context.case.claimed_order_id
        try:
            order = self.indexes.order(order_id)
            items = self.indexes.items_by_order.get(order_id, [])
            item_ids = [f"{order_id}:{row['order_item_id']}" for row in items]
            seller_ids = unique_stable(row["seller_id"] for row in items if row.get("seller_id"))
            product_ids = unique_stable(row["product_id"] for row in items if row.get("product_id"))
            raw_categories = unique_stable(
                self.indexes.products_by_id.get(row.get("product_id", ""), {}).get(
                    "product_category_name", ""
                )
                for row in items
            )
            raw_categories = [value for value in raw_categories if value]
            facts = {
                "order_status": order["order_status"],
                "item_ids": item_ids[:5],
                "seller_ids": seller_ids[:3],
                "product_ids": product_ids[:5],
                # Keep the canonical category value from the products CSV.
                # The translation table is auxiliary and the output contract
                # does not ask agents to replace source values.
                "category_names": raw_categories[:5],
                "item_count": len(items),
                "seller_count": len(seller_ids),
                "product_count": len(product_ids),
                "category_count": len(raw_categories),
                "multi_item_order": len(items) >= 2,
                "multi_seller_order": len(seller_ids) >= 2,
                "multiple_categories": len(raw_categories) >= 2,
            }
            review, llm_meta = await self.call_llm(
                context,
                system_prompt=(
                    "You are the Order and Product Agent. Review deterministic joins "
                    "for order, item, seller, product and category. Do not invent IDs. "
                    "Return one JSON object only with consistent (boolean), "
                    "missing_entities (array), note (string). No markdown."
                ),
                user_payload={
                    "case_id": case_id,
                    "claimed_order_id": order_id,
                    "deterministic_facts": {
                        key: facts[key]
                        for key in (
                            "order_status",
                            "item_count",
                            "seller_count",
                            "product_count",
                            "category_count",
                            "multi_item_order",
                            "multi_seller_order",
                            "multiple_categories",
                        )
                    },
                },
            )
            self.attach_llm_review(facts, review, llm_meta)
            return AgentHandoff(
                case_id=case_id,
                agent=self.name,
                status="ok",
                facts=facts,
                evidence_ids=[f"order:{order_id}"]
                + [f"item:{item_id}" for item_id in item_ids[:5]],
                confidence=1.0,
            )
        except KeyError as exc:
            facts = {"error": str(exc)}
            review, llm_meta = await self.call_llm(
                context,
                system_prompt=(
                    "You are the Order and Product Agent. Review the failed data join. "
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
