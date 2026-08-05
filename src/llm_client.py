"""Groq chat-completions wrapper.

The model name lives here in source (never in .env) so the grader can read it
directly from code, matching what is declared in metadata.json. Only the API
key comes from .env.
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# Model declared in source per README section 9. 8B parameters, under the 10B cap.
MODEL_NAME = "llama-3.1-8b-instant"
MODEL_PARAMETER_SIZE = "8B"
PROVIDER = "groq"

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 500
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 20


class LLMError(RuntimeError):
    pass


def _api_key():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY is not set; put it in .env (never commit it)")
    return key


def call_llm(system_prompt, user_prompt, temperature=DEFAULT_TEMPERATURE,
             max_tokens=DEFAULT_MAX_TOKENS, json_mode=True):
    """One chat completion. Returns (parsed_or_text, usage_dict).

    json_mode asks Groq to constrain the reply to a JSON object, which keeps
    the small model's output parseable for agent handoff. Raises LLMError on
    any failure so callers can fall back to a deterministic finding.
    """
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": "Bearer %s" % _api_key(),
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                GROQ_ENDPOINT, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after else RETRY_BACKOFF_SECONDS * (attempt + 1)
            last_error = LLMError("HTTP %s: %s" % (response.status_code, response.text[:200]))
            time.sleep(delay)
            continue

        if response.status_code != 200:
            raise LLMError("HTTP %s: %s" % (response.status_code, response.text[:400]))

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})

        if not json_mode:
            return content, usage

        try:
            return json.loads(content), usage
        except json.JSONDecodeError as exc:
            last_error = LLMError("model returned non-JSON: %s" % content[:200])
            if attempt == MAX_RETRIES - 1:
                raise last_error from exc
            time.sleep(RETRY_BACKOFF_SECONDS)

    raise LLMError("LLM call failed after %d attempts: %s" % (MAX_RETRIES, last_error))
