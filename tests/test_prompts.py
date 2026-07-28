"""Smoke tests for prompts.py — confirms templates render the right content, and that the
planning-phase requirement is actually present in the system prompt, not just intended."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import prompts


def test_system_prompt_requires_a_plan_phase():
    """This is the concrete check that roadmap gap #198 (planning-based agents) is actually
    addressed in the prompt, not just noted as a TODO somewhere."""
    assert "PLAN" in prompts.SYSTEM_PROMPT
    assert "before taking any action" in prompts.SYSTEM_PROMPT


def test_system_prompt_forbids_editing_the_test_file():
    assert "not by editing the test itself" in prompts.SYSTEM_PROMPT


def test_format_bug_intro_includes_the_real_test_output():
    text = prompts.format_bug_intro(
        bug=type("Bug", (), {"project": "fastapi", "test_node": "tests/x.py::test_y"})(),
        failing_test_output="TypeError: something broke",
    )
    assert "tests/x.py::test_y" in text
    assert "TypeError: something broke" in text
