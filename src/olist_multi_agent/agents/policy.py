from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from ..policy_engine import resolve_policy
from .base import BaseAgent


class PolicyAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "policy"

    async def run(self, context: CaseContext) -> AgentHandoff:
        decision = resolve_policy(context.handoffs)
        facts = {"decision": decision.model_dump(mode="json")}
        review, llm_meta = await self.call_llm(
            context,
            system_prompt=(
                "You are the Policy Agent for EC_POLICY_V2. Review the deterministic "
                "decision and facts. Do not override the rule priority, refund, or "
                "responsible parties. Return one JSON object only with agrees (boolean), "
                "primary_issue (string), policy_consistent (boolean), note (string)."
            ),
            user_payload={
                "case_id": context.case.case_id,
                "policy_version": context.case.policy_version,
                "deterministic_decision": facts["decision"],
                "fact_summary": {
                    name: {
                        key: value
                        for key, value in handoff.facts.items()
                        if key != "_llm"
                        and key
                        in {
                            "order_status",
                            "payment_total_brl",
                            "payment_count",
                            "reconciled",
                            "delivery_late",
                            "late_handoff_seller_ids",
                            "delivery_variance_hours",
                            "multi_item_order",
                            "multi_seller_order",
                            "split_payment",
                            "repeat_customer",
                        }
                    }
                    for name, handoff in context.handoffs.items()
                },
            },
        )
        self.attach_llm_review(facts, review, llm_meta)
        return AgentHandoff(
            case_id=context.case.case_id,
            agent=self.name,
            status="ok",
            facts=facts,
            confidence=decision.confidence,
        )
