"""Small OpenAI-compatible client abstraction used by every logical agent."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import Settings


class LLMDisabledError(RuntimeError):
    "LLM calls are disabled. Set LLM_ENABLED=true after configuring .env."


class LLMConfigurationError(RuntimeError):
    "The selected hosted provider is missing its API key."


class LLMClient(ABC):
    @abstractmethod
    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class DisabledLLMClient(LLMClient):
    async def complete_json(self, **_: Any) -> dict[str, Any]:
        raise LLMDisabledError


class OpenAICompatibleClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._rate_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def _wait_for_rate_limit(self) -> None:
        interval = max(0.0, self.settings.llm_min_interval_seconds)
        if interval <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._rate_lock:
            wait_seconds = max(0.0, self._next_request_at - loop.time())
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            self._next_request_at = loop.time() + interval

    @staticmethod
    def _parse_content(content: Any) -> dict[str, Any]:
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        text = str(content).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response must be a JSON object")
        return parsed

    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.api_key()
        if self.settings.llm_provider in {"groq", "openrouter", "huggingface", "hf"} and not api_key:
            raise LLMConfigurationError(
                f"Missing API key for provider {self.settings.llm_provider}"
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if self.settings.llm_provider == "openrouter":
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
            headers["X-Title"] = self.settings.openrouter_app_name

        body = {
            "model": model,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }
        await self._wait_for_rate_limit()
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return self._parse_content(content)


def build_llm_client(settings: Settings) -> LLMClient:
    if not settings.llm_enabled:
        return DisabledLLMClient()
    return OpenAICompatibleClient(settings)
