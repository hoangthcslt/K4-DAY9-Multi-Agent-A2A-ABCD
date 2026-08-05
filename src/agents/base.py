"""Shared agent scaffolding.

An agent receives an AgentMessage, runs one LLM call over facts the data layer
already extracted, and hands a structured finding to the next agent. The LLM
never invents numbers: it reads the facts it was given and reports judgements.
"""

import time

from llm_client import MODEL_NAME, LLMError, call_llm
from trace_logger import AgentMessage


class Agent:
    """Base class: wraps one LLM call with tracing and a safe fallback."""

    name = "agent"
    system_prompt = ""

    def __init__(self, tracer):
        self.tracer = tracer

    def build_prompt(self, facts):
        """Return the user prompt string for this agent's LLM call."""
        raise NotImplementedError

    def fallback(self, facts):
        """Deterministic finding used when the LLM is unreachable or invalid.

        The graded numbers never depend on the LLM, so a fallback keeps the run
        completing instead of dropping a case.
        """
        return {"llm_available": False}

    def validate(self, response, facts):
        """Subclasses may coerce or sanity-check the model reply."""
        return response

    def run(self, case_id, message):
        """Execute this agent on an incoming AgentMessage; return the finding."""
        facts = message.payload
        self.tracer.log_message(case_id, message)

        prompt = self.build_prompt(facts)
        started = time.time()
        usage = None
        error = None

        try:
            response, usage = call_llm(self.system_prompt, prompt)
            finding = self.validate(response, facts)
            finding["llm_available"] = True
        except (LLMError, KeyError, TypeError, ValueError) as exc:
            error = str(exc)[:300]
            finding = self.fallback(facts)

        duration_ms = int((time.time() - started) * 1000)
        self.tracer.log_agent_step(
            case_id,
            agent=self.name,
            model=MODEL_NAME,
            inputs=facts,
            outputs=finding,
            duration_ms=duration_ms,
            usage=usage,
            error=error,
        )
        return finding

    def handoff(self, to_agent, payload, message_type="handoff"):
        return AgentMessage(self.name, to_agent, payload, message_type)


def as_bool(value, default=False):
    """Small models return booleans as strings often enough to warrant this."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return default


def as_text(value, default=""):
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return default
    return str(value)
