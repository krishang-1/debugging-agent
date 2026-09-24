"""Structured step logging for the agent — writes one JSON line per step, so a full
attempt can be reconstructed and inspected after the fact instead of relying on whatever
happened to print to a terminal during the run.
"""

import json
import os
import time
import uuid
from pathlib import Path

DEFAULT_LOG_DIR = "logs"


def new_run_id() -> str:
    """Generates a short identifier for one execution, so lines from different runs against
    the same bug stay distinguishable in a shared log file — without this, repeated runs
    silently interleave and can only be untangled by reading timestamps by hand."""
    return uuid.uuid4().hex[:8]


def log_step(bug_id: str, step_number: int, role: str, content: str,
             run_id: str = "unknown", log_dir: str = DEFAULT_LOG_DIR) -> None:
    """Appends one JSONL record for a single step in an attempt. One file per bug, with
    run_id distinguishing separate executions within it.

    Refuses to write to the real log_dir when called from inside a pytest run — a test that
    exercises real logging (directly or via react_loop.run_attempt) must pass an explicit
    scratch directory (tmp_path) instead. This is the exact failure that previously left
    scripted fixture data mixed into logs/: something under test wrote through the default
    path without anyone noticing."""
    if log_dir == DEFAULT_LOG_DIR and "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError(
            "log_step() was called with the real log_dir from inside a test "
            f"({os.environ['PYTEST_CURRENT_TEST']}). Pass an explicit log_dir "
            "(e.g. tmp_path) instead of writing into the production logs/ folder."
        )
    Path(log_dir).mkdir(exist_ok=True)
    record = {
        "bug_id": bug_id,
        "run_id": run_id,
        "step": step_number,
        "role": role,
        "content": content,
        "timestamp": time.time(),
    }
    log_path = Path(log_dir) / f"{bug_id}.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_log(bug_id: str, run_id: str | None = None, log_dir: str = "logs") -> list[dict]:
    """Reads back a bug's logged steps, in order. Pass run_id to read only one execution's
    lines instead of every run ever recorded against that bug."""
    log_path = Path(log_dir) / f"{bug_id}.jsonl"
    if not log_path.exists():
        return []
    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    if run_id is None:
        return records
    return [r for r in records if r.get("run_id") == run_id]
