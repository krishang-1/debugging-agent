"""Structured step logging for the agent — writes one JSON line per step, so a full
attempt can be reconstructed and inspected after the fact instead of relying on whatever
happened to print to a terminal during the run.
"""

import json
import time
import uuid
from pathlib import Path


def new_run_id() -> str:
    """Generates a short identifier for one execution, so lines from different runs against
    the same bug stay distinguishable in a shared log file — without this, repeated runs
    silently interleave and can only be untangled by reading timestamps by hand."""
    return uuid.uuid4().hex[:8]


def log_step(bug_id: str, step_number: int, role: str, content: str,
             run_id: str = "unknown", log_dir: str = "logs") -> None:
    """Appends one JSONL record for a single step in an attempt. One file per bug, with
    run_id distinguishing separate executions within it."""
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
