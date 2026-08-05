"""Environment-backed runtime configuration.

This module never contains a real secret. Copy .env.example to .env locally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


GROQ_MODEL = "llama-3.1-8b-instant"
MODEL_NAMES = {
    "coordinator": GROQ_MODEL,
    "customer": GROQ_MODEL,
    "order_product": GROQ_MODEL,
    "payment": GROQ_MODEL,
    "delivery": GROQ_MODEL,
    "policy": GROQ_MODEL,
    "verifier": GROQ_MODEL,
}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    llm_enabled: bool
    llm_required: bool
    llm_provider: str
    llm_base_url: str
    llm_timeout_seconds: float
    llm_temperature: float
    llm_max_tokens: int
    llm_min_interval_seconds: float
    openrouter_api_key: str
    groq_api_key: str
    hf_token: str
    openrouter_site_url: str
    openrouter_app_name: str
    data_dir: Path
    input_dir: Path
    output_dir: Path
    log_dir: Path
    trace_path: Path
    metadata_path: Path
    max_agent_retries: int
    models: dict[str, str]

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> "Settings":
        root = (root_dir or Path.cwd()).resolve()
        load_dotenv(root / ".env")

        def path_env(name: str, default: str) -> Path:
            value = Path(os.getenv(name, default))
            return value if value.is_absolute() else root / value

        return cls(
            root_dir=root,
            llm_enabled=_as_bool(os.getenv("LLM_ENABLED")),
            llm_required=_as_bool(os.getenv("LLM_REQUIRED")),
            llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
            llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
            llm_timeout_seconds=_as_float(os.getenv("LLM_TIMEOUT_SECONDS"), 90.0),
            llm_temperature=_as_float(os.getenv("LLM_TEMPERATURE"), 0.0),
            llm_max_tokens=_as_int(os.getenv("LLM_MAX_TOKENS"), 128),
            llm_min_interval_seconds=_as_float(os.getenv("LLM_MIN_INTERVAL_SECONDS"), 0.0),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            hf_token=os.getenv("HF_TOKEN", ""),
            openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "http://localhost"),
            openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "olist-multi-agent"),
            data_dir=path_env("DATA_DIR", "data"),
            input_dir=path_env("INPUT_DIR", "input"),
            output_dir=path_env("OUTPUT_DIR", "output"),
            log_dir=path_env("LOG_DIR", "logging"),
            trace_path=path_env("TRACE_PATH", "logging/trace.jsonl"),
            metadata_path=path_env("METADATA_PATH", "logging/metadata.json"),
            max_agent_retries=_as_int(os.getenv("MAX_AGENT_RETRIES"), 1),
            # Model IDs are source-controlled to satisfy the lab contract; .env
            # contains provider credentials and runtime tuning only.
            models=dict(MODEL_NAMES),
        )

    def api_key(self) -> str:
        """Return only the selected provider key; never log this value."""
        if self.llm_provider == "openrouter":
            return self.openrouter_api_key
        if self.llm_provider == "groq":
            return self.groq_api_key
        if self.llm_provider in {"huggingface", "hf"}:
            return self.hf_token
        return ""

    def model_for(self, agent_name: str) -> str:
        return self.models.get(agent_name, self.models["coordinator"])
