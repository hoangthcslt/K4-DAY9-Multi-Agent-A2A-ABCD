from __future__ import annotations

from ..contracts import AgentHandoff, CaseContext
from ..verifier import verify_candidate
from .base import BaseAgent


class VerifierAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "verifier"

    async def run(self, context: CaseContext) -> AgentHandoff:
        candidate = context.candidate or {}
        assessment = candidate.get("case_assessment", {})
        entities = candidate.get("affected_entities", {})
        root_analysis = candidate.get("root_cause_analysis", {})
        payment = candidate.get("payment_reconciliation", {})
        resolution = candidate.get("financial_resolution", {})
        candidate_snapshot = {
            "case_id": candidate.get("case_id"),
            "primary_issue": assessment.get("primary_issue"),
            "case_status": assessment.get("case_status"),
            "confidence": assessment.get("confidence"),
            "order_count": len(entities.get("order_ids", [])),
            "item_count": len(entities.get("item_ids", [])),
            "seller_count": len(entities.get("seller_ids", [])),
            "payment_count": len(entities.get("payment_ids", [])),
            "evidence_count": len(candidate.get("evidence_ids", [])),
            "root_cause_codes": [
                cause.get("cause_code")
                for cause in root_analysis.get("ranked_causes", [])
                if isinstance(cause, dict)
            ],
            "responsible_party_count": len(root_analysis.get("responsible_parties", [])),
            "refund_brl": resolution.get("recommended_refund_brl"),
            "action_count": len(candidate.get("resolution_actions", [])),
            "reconciled": payment.get("reconciled"),
        }
        review, llm_meta = await self.call_llm(
            context,
            system_prompt=(
                "You are the Verifier Agent. Review the candidate JSON for schema, "
                "IDs, evidence, null handling and array limits. Do not repair or "
                "invent values. Return one JSON object only with looks_valid (boolean), "
                "errors (array), note (string). No markdown."
            ),
            user_payload={
                "case_id": context.case.case_id,
                "candidate_snapshot": candidate_snapshot,
            },
        )
        result = verify_candidate(
            candidate,
            context.case.case_id,
            expected_order_id=context.case.claimed_order_id,
            indexes=self.indexes,
        )
        facts = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
        }
        self.attach_llm_review(facts, review, llm_meta)
        return AgentHandoff(
            case_id=context.case.case_id,
            agent=self.name,
            status="ok" if result.valid else "error",
            facts=facts,
            warnings=result.errors + result.warnings,
            confidence=1.0 if result.valid else 0.0,
        )
