"""Thin wrapper around Gemini's OpenAI-compatible endpoint — the only file in this project
that imports the openai SDK directly. react_loop.py depends on call_model()'s signature and
response shape only, never on the SDK itself, so the model or provider can be swapped
without touching the loop's logic (previously Groq, via the same seam).
"""

from types import SimpleNamespace

from dotenv import load_dotenv
load_dotenv()

import os
from openai import OpenAI
import openai

_client = OpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=90.0, max_retries=2,
)
MODEL = "gemini-3.5-flash-lite"  # free tier: 15 RPM, ~500 RPD (Google no longer publishes
                                 # exact numbers) — picked over gemini-3.6-flash's ~20 RPD,
                                 # since attempt volume matters more here than raw capability


def call_model(messages: list[dict], tools: list[dict], system: str):
    """Sends one turn to Gemini with the current tool schema and conversation so far. The
    OpenAI-compatible endpoint has no separate system parameter — the system prompt is
    prepended as the first message here, keeping call_model()'s external signature identical
    regardless of which provider is behind it.

    The client is configured with an explicit request timeout and retry count — every
    Docker-side call in this project is timeout-bounded, and the model call shouldn't be
    the one unbounded exception that can hang an attempt indefinitely.

    A malformed function-call attempt that the API's parser rejects with a 400 is caught
    here and turned into a plain-text nudge asking the model to retry correctly, the same
    defensive handling Groq needed — react_loop.py never needs to know this happened, since
    it already knows how to handle a turn with no tool calls."""
    full_messages = [{"role": "system", "content": system}] + messages
    try:
        return _client.chat.completions.create(
            model=MODEL,
            max_tokens=2048,
            tools=tools,
            messages=full_messages,
        )
    except openai.BadRequestError as e:
        error_text = str(e)
        message = SimpleNamespace(
            content=(
                "Your last response wasn't a valid tool call and was rejected. "
                "Call exactly one tool using the provided schema, with correctly "
                f"formatted arguments. (Parser error: {error_text[:200]})"
            ),
            tool_calls=None,
        )
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])
