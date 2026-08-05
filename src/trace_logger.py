"""A2A message envelope and the trace.jsonl writer.

Every agent-to-agent handoff and every LLM call is appended here, so the trace
file is the runtime evidence that the agents really executed and really passed
findings to each other, instead of the handoff only being asserted in docs.
"""

import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_PATH = os.path.join(REPO_ROOT, "logging", "trace.jsonl")


def _now():
    return datetime.now(timezone.utc).isoformat()


class AgentMessage:
    """One handoff between two agents."""

    def __init__(self, from_agent, to_agent, payload, message_type="handoff"):
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.payload = payload
        self.message_type = message_type
        self.timestamp = _now()

    def to_dict(self):
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class TraceLogger:
    """Writes one JSON object per line. Truncates on start: README asks for
    the latest run only, never an append across runs."""

    def __init__(self, path=TRACE_PATH, truncate=True):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if truncate:
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write("")

    def _write(self, record):
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_message(self, case_id, message):
        """Record an A2A handoff."""
        record = {"case_id": case_id, "event": "a2a_message"}
        record.update(message.to_dict())
        self._write(record)

    def log_agent_step(self, case_id, agent, model, inputs, outputs,
                        duration_ms=None, usage=None, error=None):
        """Record one agent's execution, including its LLM call if it made one."""
        self._write(
            {
                "case_id": case_id,
                "event": "agent_step",
                "step": agent,
                "model": model,
                "input": inputs,
                "output": outputs,
                "duration_ms": duration_ms,
                "usage": usage,
                "error": error,
                "timestamp": _now(),
            }
        )

    def log_case(self, case_id, event, detail):
        self._write(
            {
                "case_id": case_id,
                "event": event,
                "detail": detail,
                "timestamp": _now(),
            }
        )
