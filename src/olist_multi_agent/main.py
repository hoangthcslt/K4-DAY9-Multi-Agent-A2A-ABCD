"""CLI entrypoint for the seven-agent Olist investigation workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .agents.coordinator import CoordinatorAgent
from .config import Settings
from .contracts import CaseInput
from .data_loader import OlistIndexes
from .llm_client import build_llm_client
from .output_writer import write_case_output
from .tracing import TraceWriter


def _load_case(path: Path) -> CaseInput:
    return CaseInput.model_validate(json.loads(path.read_text(encoding="utf-8")))


async def run_scaffold(settings: Settings) -> None:
    indexes = OlistIndexes.load(settings.data_dir)
    llm = build_llm_client(settings)
    coordinator = CoordinatorAgent(settings, indexes, llm)
    trace = TraceWriter(settings.trace_path)
    trace.reset()
    run_id = datetime.now(UTC).isoformat()
    settings.metadata_path.parent.mkdir(parents=True, exist_ok=True)
    settings.metadata_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "framework": "custom-python-modular-monolith",
                "runtime": f"python-{platform.python_version()}",
                "provider": settings.llm_provider,
                "llm_enabled": settings.llm_enabled,
                "llm_required": settings.llm_required,
                "llm_min_interval_seconds": settings.llm_min_interval_seconds,
                "expected_llm_calls": len(
                    {"coordinator", "customer", "order_product", "payment", "delivery", "policy", "verifier"}
                )
                * len(list(settings.input_dir.glob("EC_*.json"))),
                "parameter_limit": "<=10B per logical agent",
                "model_parameters_b": {
                    agent: 8
                    for agent in (
                        "coordinator",
                        "customer",
                        "order_product",
                        "payment",
                        "delivery",
                        "policy",
                        "verifier",
                    )
                },
                "models": settings.models,
                "row_counts": indexes.row_counts,
                "agents": [
                    "coordinator",
                    "customer",
                    "order_product",
                    "payment",
                    "delivery",
                    "policy",
                    "verifier",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    completed = 0
    for case_path in sorted(settings.input_dir.glob("EC_*.json")):
        case = _load_case(case_path)
        started = perf_counter()
        trace.event(run_id=run_id, case_id=case.case_id, agent="coordinator", event="start")
        result = await coordinator.run_case(case)
        for agent_name, handoff in result["handoffs"].items():
            llm_meta = handoff.get("facts", {}).get("_llm", {})
            trace.event(
                run_id=run_id,
                case_id=case.case_id,
                agent=agent_name,
                event="handoff",
                status=handoff["status"],
                evidence_count=len(handoff.get("evidence_ids", [])),
                warning_count=len(handoff.get("warnings", [])),
                model=settings.model_for(agent_name),
                llm_called=bool(llm_meta.get("called")),
                llm_success=bool(llm_meta.get("success")),
                llm_attempts=llm_meta.get("attempts"),
            )
        write_case_output(settings.output_dir, case.case_id, result["candidate"])
        completed += 1
        trace.event(
            run_id=run_id,
            case_id=case.case_id,
            agent="coordinator",
            event="end",
            status="ok",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            llm_agents=len(result["handoffs"]),
            llm_success_count=sum(
                bool(handoff.get("facts", {}).get("_llm", {}).get("success"))
                for handoff in result["handoffs"].values()
            ),
        )
    print(f"Generated {completed} case outputs in {settings.output_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Olist multi-agent scaffold")
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.check_config:
        print(f"provider={settings.llm_provider}")
        print(f"llm_enabled={settings.llm_enabled}")
        print(f"llm_required={settings.llm_required}")
        print(f"llm_min_interval_seconds={settings.llm_min_interval_seconds}")
        print(f"data_dir={settings.data_dir}")
        print("API key configured=" + ("yes" if bool(settings.api_key()) else "no"))
        return 0
    if not settings.llm_enabled:
        print("LLM is disabled. Set LLM_ENABLED=true in .env to run the workflow.")
        return 0
    asyncio.run(run_scaffold(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
