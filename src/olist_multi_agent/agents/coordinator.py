from __future__ import annotations

import asyncio

from ..config import Settings
from ..contracts import AgentHandoff, CaseContext, CaseInput
from ..data_loader import OlistIndexes
from ..llm_client import LLMClient
from ..output_builder import build_output
from .base import BaseAgent, call_llm_json
from .customer import CustomerAgent
from .delivery import DeliveryAgent
from .order_product import OrderProductAgent
from .payment import PaymentAgent
from .policy import PolicyAgent
from .verifier import VerifierAgent


class CoordinatorAgent:
    """Orchestrates handoffs; business calculations remain outside this class."""

    def __init__(self, settings: Settings, indexes: OlistIndexes, llm: LLMClient) -> None:
        self.settings = settings
        self.indexes = indexes
        self.fact_agents: list[BaseAgent] = [
            CustomerAgent(settings, indexes, llm),
            OrderProductAgent(settings, indexes, llm),
            PaymentAgent(settings, indexes, llm),
            DeliveryAgent(settings, indexes, llm),
        ]
        self.policy_agent = PolicyAgent(settings, indexes, llm)
        self.verifier_agent = VerifierAgent(settings, indexes, llm)

    async def run_case(self, case: CaseInput) -> dict[str, object]:
        context = CaseContext(case=case)
        coordinator_review, coordinator_llm_meta = await call_llm_json(
            settings=self.settings,
            llm=self.fact_agents[0].llm,
            agent_name="coordinator",
            case_id=case.case_id,
            model=self.settings.model_for("coordinator"),
            system_prompt=(
                "You are the Coordinator Agent. Plan the seven-agent handoff for this "
                "case. Do not decide facts or refunds. Return one JSON object only "
                "with route (array), required_checks (array), policy_version (string)."
            ),
            user_payload={
                "case_id": case.case_id,
                "customer_request": case.customer_request,
                "investigation_scope": case.investigation_scope,
                "policy_version": case.policy_version,
                "agents": [
                    "customer",
                    "order_product",
                    "payment",
                    "delivery",
                    "policy",
                    "verifier",
                ],
            },
        )
        context.handoffs["coordinator"] = AgentHandoff(
            case_id=case.case_id,
            agent="coordinator",
            status="ok",
            facts={"_llm": {**coordinator_llm_meta, "review": coordinator_review}},
            confidence=1.0,
        )
        fact_handoffs = await asyncio.gather(
            *(agent.run(context) for agent in self.fact_agents)
        )
        context.handoffs.update({handoff.agent: handoff for handoff in fact_handoffs})
        policy_handoff = await self.policy_agent.run(context)
        context.handoffs[policy_handoff.agent] = policy_handoff
        decision_payload = policy_handoff.facts.get("decision")
        if not isinstance(decision_payload, dict):
            raise RuntimeError("Policy agent did not return a decision")
        from ..contracts import PolicyDecision

        candidate = build_output(
            case,
            context.handoffs,
            PolicyDecision.model_validate(decision_payload),
            self.indexes,
        )
        context.candidate = candidate
        verifier_handoff = await self.verifier_agent.run(context)
        context.handoffs[verifier_handoff.agent] = verifier_handoff
        if verifier_handoff.status != "ok":
            errors = verifier_handoff.facts.get("errors", verifier_handoff.warnings)
            raise RuntimeError(f"Verifier rejected {case.case_id}: {errors}")
        return {
            "case_id": case.case_id,
            "status": "ok",
            "candidate": candidate,
            "handoffs": {key: value.model_dump(mode="json") for key, value in context.handoffs.items()},
        }
