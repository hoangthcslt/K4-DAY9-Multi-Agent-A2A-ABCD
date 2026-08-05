"""
LLM Client — Wrapper around Groq API for all agent LLM calls.
Model: gemma2-9b-it (9B params, within the ≤10B constraint).
"""

import os
import json
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Model name declared explicitly in code as required by lab rules
MODEL_NAME = "llama-3.1-8b-instant"
MODEL_PARAMS = "8B"
FRAMEWORK = "groq-python-sdk"


class LLMClient:
    """Shared LLM client for all agents. Handles rate limiting and retries."""

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env file")
        self.client = Groq(api_key=api_key)
        self.model = MODEL_NAME
        self.call_count = 0
        self.total_tokens = 0

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        json_mode: bool = True,
        max_retries: int = 3,
    ) -> str:
        """
        Call LLM with retry logic and rate limiting.
        Returns the text content of the response.
        """
        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.client.chat.completions.create(**kwargs)

                self.call_count += 1
                if response.usage:
                    self.total_tokens += response.usage.total_tokens

                return response.choices[0].message.content

            except Exception as e:
                error_str = str(e)
                if "rate_limit" in error_str.lower() or "429" in error_str:
                    wait_time = 2 ** attempt * 5  # exponential backoff
                    print(f"  [LLM] Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                elif attempt < max_retries - 1:
                    print(f"  [LLM] Error: {error_str}, retrying ({attempt+1}/{max_retries})...")
                    time.sleep(2)
                else:
                    raise

    def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict:
        """Call LLM and parse response as JSON."""
        text = self.call(system_prompt, user_prompt, temperature, max_tokens, json_mode=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)

    def get_stats(self) -> dict:
        return {
            "model": self.model,
            "total_calls": self.call_count,
            "total_tokens": self.total_tokens,
        }
