"""Smoke tests for harness.py — confirms it reproduces the same buggy-fails/fixed-passes
result we already verified by hand for bug #1, the most-solid ground truth we have."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

from loader import load_bugs
import harness

BUG = load_bugs(str(Path(__file__).resolve().parent.parent / "benchmark" / "selected_bugs.json"))[0]


def test_buggy_version_fails():
    """The buggy checkout should fail on the exclude_defaults assertion, same as our manual run."""
    workdir = "/home/workspace/test-harness-bug1-buggy"
    harness.setup_bug(BUG, version=0, workdir=workdir)
    result = harness.run_test(BUG, workdir=workdir)
    assert result.outcome == "failed"
    assert "exclude_defaults" in result.raw_output


def test_fixed_version_passes():
    """The fixed checkout should pass the identical test, same as our manual run."""
    workdir = "/home/workspace/test-harness-bug1-fixed"
    harness.setup_bug(BUG, version=1, workdir=workdir)
    result = harness.run_test(BUG, workdir=workdir)
    assert result.outcome == "passed"


def test_snapshot_save_and_restore_preserves_a_working_environment():
    """A snapshot is only useful if the restored environment still runs. Saves the current
    prepared checkout, restores it, and confirms the bug still reproduces afterwards —
    catches the two real failure modes found building this: docker commit silently excluding
    bind-mounted volumes, and a restore that deleted the original before verifying the copy."""
    workdir = "/home/workspace/test-harness-bug1-buggy"

    before = harness.run_test(BUG, workdir=workdir)
    assert before.outcome == "failed", f"precondition: expected the bug to reproduce, got {before.outcome}"

    assert harness.save_snapshot(BUG, workdir)
    assert harness.snapshot_exists(BUG)
    assert harness.restore_snapshot(BUG, workdir)

    after = harness.run_test(BUG, workdir=workdir)
    assert after.outcome == "failed", f"restored env should still reproduce the bug, got {after.outcome}"


def test_restore_returns_false_for_a_bug_with_no_snapshot():
    """Callers rely on False to mean 'fall back to a full setup_bug()' — it must not raise."""
    fake = type("Bug", (), {"bug_id": "no-such-bug-xyz", "project": "fastapi"})()
    assert harness.restore_snapshot(fake, "/home/workspace/does-not-matter") is False
