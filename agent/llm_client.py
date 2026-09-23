"""Thin wrapper around the Groq API — the only file in this project that imports the groq
SDK directly. react_loop.py depends on call_model()'s signature and response shape only,
never on the SDK itself, so the model or provider can be swapped without touching the
loop's logic.
"""

from types import SimpleNamespace

from groq import Groq
import groq

_client = Groq(timeout=90.0, max_retries=2)  # reads GROQ_API_KEY from the environment
MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was removed from Groq's catalog; this is the largest tool-calling-capable model left on this key


def call_model(messages: list[dict], tools: list[dict], system: str):
    """Sends one turn to Groq with the current tool schema and conversation so far.
    Groq's API has no separate system parameter — the system prompt is prepended as the
    first message here, keeping call_model()'s external signature identical regardless
    of which provider is behind it.

    The client is configured with an explicit request timeout and retry count — every
    Docker-side call in this project is timeout-bounded, and the model call shouldn't be
    the one unbounded exception that can hang an attempt indefinitely.

    Occasionally the model emits a malformed function-call attempt that Groq's own parser
    rejects with a 400 tool_use_failed error, instead of a clean structured tool call — a
    known behavior of LLM function calling generally, not specific to this project. Rather
    than crash the whole attempt on one bad generation, that failure is caught here and
    turned into a plain-text nudge asking the model to retry correctly — react_loop.py
    never needs to know this happened, since it already knows how to handle a turn with
    no tool calls."""
    full_messages = [{"role": "system", "content": system}] + messages
    try:
        return _client.chat.completions.create(
            model=MODEL,
            max_tokens=2048,
            tools=tools,
            messages=full_messages,
        )
    except groq.BadRequestError as e:
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
