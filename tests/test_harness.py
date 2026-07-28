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
