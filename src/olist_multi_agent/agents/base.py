"""Base class and shared helpers for logical agents."""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Any

from ..config import Settings
from ..contracts import AgentHandoff, CaseContext
from ..data_loader import OlistIndexes
from ..llm_client import LLMClient


def _response_status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _retryable(exc: Exception) -> bool:
    status_code = _response_status(exc)
    if status_code in {400, 401, 403, 404, 422}:
        return False
    return status_code is None or status_code in {408, 409, 425, 429} or status_code >= 500


def _delay_from_header(raw_value: object) -> float | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip().lower()
    try:
        return max(0.0, float(text))
    except ValueError:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([smh])", text)
        if not match:
            return None
        amount = float(match.group(1))
        multiplier = {"s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
        return amount * multiplier


async def call_llm_json(
    *,
    settings: Settings,
    llm: LLMClient,
    agent_name: str,
    case_id: str,
    model: str,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the configured model and return a safe, traceable call envelope.

    The deterministic facts remain authoritative. The model is required to
    review/interpret those facts, while this helper keeps retry and failure
    behavior consistent across all seven logical agents.
    """

    max_attempts = max(1, settings.max_agent_retries + 1)
    last_error: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            result = await llm.complete_json(
                model=model,
                system_prompt=system_prompt,
                user_payload=user_payload,
            )
            if not isinstance(result, dict):
                raise ValueError("LLM response must be a JSON object")
            return result, {
                "called": True,
                "success": True,
                "attempts": attempt,
                "agent": agent_name,
                "case_id": case_id,
                "model": model,
                "provider": settings.llm_provider,
            }
        except Exception as exc:  # model/provider failures must be observable
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            last_error = {
                "error_type": type(exc).__name__,
                "status_code": status_code,
            }
            if attempt >= max_attempts or not _retryable(exc):
                break
            retry_after = None
            headers = getattr(response, "headers", None)
            if headers is not None:
                raw_retry_after = headers.get("retry-after")
                retry_after = _delay_from_header(raw_retry_after)
                if retry_after is None and status_code == 429:
                    retry_after = _delay_from_header(headers.get("x-ratelimit-reset-tokens"))
            await asyncio.sleep(
                max(0.0, retry_after)
                if retry_after is not None
                else min(2.0**attempt, 8.0)
            )

    meta = {
        "called": True,
        "success": False,
        "attempts": max_attempts,
        "agent": agent_name,
        "case_id": case_id,
        "model": model,
        "provider": settings.llm_provider,
        **last_error,
    }
    if settings.llm_required:
        status = (
            f" status_code={last_error['status_code']}"
            if last_error.get("status_code") is not None
            else ""
        )
        raise RuntimeError(
            f"Required LLM call failed for {agent_name}/{case_id}: "
            f"{last_error.get('error_type', 'unknown')}{status}"
        )
    return {}, meta


class BaseAgent(ABC):
    def __init__(self, settings: Settings, indexes: OlistIndexes, llm: LLMClient) -> None:
        self.settings = settings
        self.indexes = indexes
        self.llm = llm

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    def model(self) -> str:
        return self.settings.model_for(self.name)

    @abstractmethod
    async def run(self, context: CaseContext) -> AgentHandoff:
        raise NotImplementedError

    async def call_llm(
        self,
        context: CaseContext,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await call_llm_json(
            settings=self.settings,
            llm=self.llm,
            agent_name=self.name,
            case_id=context.case.case_id,
            model=self.model,
            system_prompt=system_prompt,
            user_payload=user_payload,
        )

    @staticmethod
    def attach_llm_review(
        facts: dict[str, Any], review: dict[str, Any], meta: dict[str, Any]
    ) -> dict[str, Any]:
        facts["_llm"] = {**meta, "review": review}
        return facts

    def pending(self, context: CaseContext, message: str) -> AgentHandoff:
        """Return an explicit scaffold handoff until the agent is implemented."""
        return AgentHandoff(
            case_id=context.case.case_id,
            agent=self.name,
            status="pending",
            warnings=[message],
        )
