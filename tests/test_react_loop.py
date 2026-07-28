"""Smoke test for react_loop.py using a scripted stub model — no real API call, no fresh
setup_bug() needed. Points at bug #1's already-fixed checkout, still sitting in the
container from earlier manual verification, so the target test should pass immediately.
Stub response shape matches Groq's OpenAI-compatible format (choices[0].message, tool_calls
with JSON-string arguments), not Anthropic's content-block format from the earlier draft.
"""

import sys
import json
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

from loader import load_bugs
import react_loop

BUG = load_bugs(str(Path(__file__).resolve().parent.parent / "benchmark" / "selected_bugs.json"))[0]
PROJECT_DIR = "/home/workspace/fastapi-fixed/fastapi"


def _stub_response(content, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _tool_call(name, arguments: dict, id_="call_1"):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(id=id_, function=function)


def test_agent_solves_immediately_against_already_fixed_code():
    """A scripted model that calls run_tests right away should succeed instantly, since
    PROJECT_DIR already points at fixed code — proves the loop's plumbing works end to end
    without needing a real model or a real bug fix."""
    def stub_call_model(messages, tool_schemas, system):
        return _stub_response(
            content="PLAN: check if the test already passes before changing anything.",
            tool_calls=[_tool_call("run_tests", {})],
        )

    result = react_loop.run_attempt(BUG, PROJECT_DIR, stub_call_model,
                                     initial_test_output="(not shown)", max_steps=3)
    assert result.solved
    assert result.steps_taken == 1


def test_large_observations_are_truncated_before_entering_history():
    """A full file dump resent on every subsequent call is the dominant token cost — one
    2,500-token read costs ~35,000 tokens across a full attempt. Truncation caps that."""
    huge = "x" * 20000
    out = react_loop._truncate(huge)
    assert len(out) < len(huge)
    assert "characters omitted" in out


def test_small_observations_pass_through_untouched():
    small = "collected 1 item\n1 passed"
    assert react_loop._truncate(small) == small


def test_old_tool_observations_are_collapsed_but_recent_ones_kept():
    """Stale file dumps stop being resent; the recent window the model is actively reasoning
    about stays intact."""
    messages = []
    for i in range(6):
        messages.append({"role": "assistant", "content": f"thought {i}"})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"observation {i}"})

    compacted = react_loop._compact_history(messages, window=2)
    tool_msgs = [m for m in compacted if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "[earlier observation omitted to save context]"
    assert tool_msgs[-1]["content"] == "observation 5"
    assert tool_msgs[-2]["content"] == "observation 4"


def test_compaction_is_a_noop_when_history_is_short():
    messages = [{"role": "tool", "tool_call_id": "c0", "content": "observation 0"}]
    assert react_loop._compact_history(messages, window=4) == messages
