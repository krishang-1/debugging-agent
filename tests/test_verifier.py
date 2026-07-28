"""Smoke tests for verifier.py. The hard-rule path needs no LLM at all; the soft-check path
uses a stub call_llm so this runs fully offline, no API wiring needed yet."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

from loader import load_bugs
import verifier

BUG = load_bugs(str(Path(__file__).resolve().parent.parent / "benchmark" / "selected_bugs.json"))[0]  # fastapi-1


def test_editing_the_test_file_is_rejected_without_calling_the_model():
    """The hard rule should fire before call_llm is ever invoked — pass a call_llm that
    raises, to prove the LLM path is never reached for this case."""
    def call_llm_should_not_be_called(prompt):
        raise AssertionError("call_llm was invoked — the hard rule should have short-circuited first")

    diff = {BUG.test_node.split("::")[0]: "assert True  # gutted"}
    result = verifier.verify_fix(BUG, diff, call_llm_should_not_be_called)
    assert result.verdict == "gamed_test"


def test_genuine_fix_verdict_from_stubbed_model_response():
    stub_response = "GENUINE\nThe change adds the missing exclude_defaults parameter described in the bug."
    diff = {"fastapi/encoders.py": "def jsonable_encoder(obj, exclude_defaults=False): ..."}
    result = verifier.verify_fix(BUG, diff, lambda prompt: stub_response)
    assert result.verdict == "genuine_fix"


def test_not_genuine_verdict_from_stubbed_model_response():
    stub_response = "NOT_GENUINE\nThis change is unrelated to the described bug."
    diff = {"fastapi/routing.py": "# unrelated change"}
    result = verifier.verify_fix(BUG, diff, lambda prompt: stub_response)
    assert result.verdict == "gamed_test"
