"""Harness for mutation-testing bugs: applies/reverts a bug.patch against a local tenacity checkout and runs its regression test. No Docker/snapshot needed - plain venv, seconds not minutes.

PYTHONDONTWRITEBYTECODE is forced for every subprocess call here: several mutmut-style
patches change a single character without changing file size (e.g. tenacity-05's `0` -> `1`),
and CPython's default .pyc cache key is (mtime truncated to whole seconds, file size) - a fast
apply/test/revert/test cycle can land two different file contents in the same wall-clock
second with identical size, causing stale bytecode to be served silently. Disabling bytecode
caching entirely for this harness costs nothing (these are tiny files, no import-heavy startup)
and removes the whole class of bug.
"""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CORPUS = Path("benchmark/mutation_corpus/corpus")
CHECKOUT = Path("benchmark/mutation_corpus/tenacity_checkout")

_NO_PYC_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _clear_pycache() -> None:
    """Removes every __pycache__ directory under the tenacity package as a belt-and-suspenders measure alongside PYTHONDONTWRITEBYTECODE."""
    for p in (CHECKOUT / "tenacity").rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)


def apply_bug(bug) -> None:
    """Applies bug.patch to the tenacity checkout; raises CalledProcessError if it does not apply cleanly."""
    patch_path = (CORPUS / bug.patch_file).resolve()
    subprocess.run(["git", "apply", str(patch_path)], cwd=CHECKOUT, check=True)
    _clear_pycache()


def revert_bug(bug) -> None:
    """Reverts all changes in the tenacity checkout back to the pinned commit."""
    subprocess.run(["git", "checkout", "--", "tenacity"], cwd=CHECKOUT, check=True)
    _clear_pycache()


def stage_test(bug) -> Path:
    """Copies the bug's regression test into the checkout root so pytest can import the local tenacity package."""
    dest = CHECKOUT / "test_regression.py"
    shutil.copy(CORPUS / bug.test_file, dest)
    return dest


@dataclass
class MutationTestResult:
    """Mirrors harness.TestResult's shape so run_benchmark.py can treat both harnesses uniformly."""
    outcome: str  # "passed" or "failed"
    raw_output: str
    unrecognized: bool = False


def run_test_result(bug) -> MutationTestResult:
    """Stages and runs the bug's regression test with bytecode caching disabled; returns the full
    outcome plus raw pytest output, for callers that need more than pass/fail (e.g. seeding the
    agent's first prompt with the actual failure)."""
    stage_test(bug)
    result = subprocess.run(
        [str((CHECKOUT / "env" / "Scripts" / "python.exe").resolve()), "-B", "-m", "pytest", "test_regression.py", "-q"],
        cwd=CHECKOUT, capture_output=True, text=True, env=_NO_PYC_ENV,
    )
    outcome = "passed" if result.returncode == 0 else "failed"
    return MutationTestResult(outcome=outcome, raw_output=result.stdout + result.stderr)


def run_test(bug) -> bool:
    """Stages and runs the bug's regression test with bytecode caching disabled; returns True if it passes."""
    return run_test_result(bug).outcome == "passed"

