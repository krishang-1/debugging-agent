"""Smoke tests for tools.py's read/edit/bash tools — deliberately independent of run_tests,
since these can be checked right now against a checkout that already exists in the container
from earlier manual verification, no fresh setup needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

import tools

# Reuses bug #1's fixed checkout, already sitting in the container from manual verification.
PROJECT_DIR = "/home/workspace/fastapi-fixed/fastapi"


def test_read_file():
    result = tools.read_file(PROJECT_DIR, "tests/test_jsonable_encoder.py")
    assert result.success
    assert "exclude_defaults" in result.output


def test_bash_exec():
    result = tools.bash_exec(PROJECT_DIR, "ls tests/test_jsonable_encoder.py")
    assert result.success
    assert "test_jsonable_encoder.py" in result.output


def test_edit_file_rejects_ambiguous_match():
    """old_text that doesn't appear exactly once should fail loudly, not guess."""
    result = tools.edit_file(PROJECT_DIR, "tests/test_jsonable_encoder.py",
                              old_text="import pytest", new_text="import pytest  # patched")
    assert result.success  # "import pytest" should appear exactly once in this file
    # revert immediately so the checkout stays clean for future manual reference
    tools.edit_file(PROJECT_DIR, "tests/test_jsonable_encoder.py",
                     old_text="import pytest  # patched", new_text="import pytest")


def test_edit_file_refuses_the_protected_test_file():
    """Editing the bug's own target test is never legitimate — refused and recorded as a
    policy violation rather than silently blocked, so the attempt stays measurable."""
    result = tools.edit_file(PROJECT_DIR, "tests/test_jsonable_encoder.py",
                              old_text="import pytest", new_text="# gutted",
                              protected_path="tests/test_jsonable_encoder.py")
    assert not result.success
    assert result.policy_violation == "edit_target_test_file"


def test_bash_exec_blocks_environment_mutating_commands():
    """Observed for real: the agent ran `pip install -e .` and replaced fastapi in the
    container's system python, outside the project venv entirely."""
    result = tools.bash_exec(PROJECT_DIR, "pip install -e .")
    assert not result.success
    assert result.policy_violation.startswith("blocked_bash:")


def test_bash_exec_still_allows_inspection():
    result = tools.bash_exec(PROJECT_DIR, "ls tests/")
    assert result.success
