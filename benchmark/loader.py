"""Loads the hand-curated benchmark bug list into structured records the harness can run."""

from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class BugRecord:
    """One benchmark entry: everything the harness needs to check out, fix, and test a single BugsInPy bug."""
    bug_id: str
    project: str
    bugsinpy_id: int
    category: str
    test_node: str
    commit_message: str
    known_env_fixes: list[str]
    bug_type: str = "bugsinpy"


def load_bugs(path: str | Path = "selected_bugs.json") -> list[BugRecord]:
    """Reads the curated bug list and returns it as BugRecord objects, ready for harness.py to run."""
    data = json.loads(Path(path).read_text())
    return [BugRecord(**entry) for entry in data]
