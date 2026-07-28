"""Runs the agent across every bug in the benchmark and records a structured outcome per bug.

Produces the raw results analysis.py turns into a categorized breakdown. Deliberately records
'gamed' as its own outcome distinct from solved/failed — an agent whose test passes only because
it cheated is neither a success nor an ordinary failure, and collapsing that distinction would
hide the single most interesting number this benchmark produces.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

from loader import load_bugs
import harness
import react_loop
import verifier


@dataclass
class BugOutcome:
    """One bug's full result — enough to reconstruct what happened without re-running anything."""
    bug_id: str
    category: str
    outcome: str  # "solved", "gamed", "failed", or "setup_error"
    steps_taken: int
    policy_violations: list[str]
    verifier_verdict: str
    changed_files: list[str]
    run_id: str
    notes: str = ""


def run_one_bug(bug, call_model, call_llm, workdir_root: str = "/home/workspace/bench") -> BugOutcome:
    """Sets up one bug fresh, runs a full agent attempt against it, then independently verifies
    the result. setup_bug() is slow (~44 min per bug, measured) — this is the cost that makes
    per-bug environment snapshotting worth building before running large benchmarks."""
    workdir = f"{workdir_root}-{bug.bug_id}"

    try:
        unrecognized = harness.setup_bug(bug, version=0, workdir=workdir)
    except harness.HarnessSetupError as e:
        return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome="setup_error",
                          steps_taken=0, policy_violations=[], verifier_verdict="not_run",
                          changed_files=[], run_id="", notes=str(e))

    project_dir = f"{workdir}/{bug.project}"
    initial = harness.run_test(bug, workdir=workdir)
    if initial.outcome != "failed":
        return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome="setup_error",
                          steps_taken=0, policy_violations=[], verifier_verdict="not_run",
                          changed_files=[], run_id="",
                          notes=f"bug did not reproduce cleanly: {initial.outcome}")

    attempt = react_loop.run_attempt(bug, project_dir, call_model, initial.raw_output)

    verdict = "not_run"
    if attempt.changed_files:
        verdict = verifier.verify_fix(bug, attempt.changed_files, call_llm).verdict

    if attempt.solved and verdict == "gamed_test":
        outcome = "gamed"
    elif attempt.solved:
        outcome = "solved"
    else:
        outcome = "failed"

    unrecognized_note = f"unrecognized env fixes: {unrecognized}" if unrecognized else ""
    return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome=outcome,
                      steps_taken=attempt.steps_taken, policy_violations=attempt.policy_violations,
                      verifier_verdict=verdict, changed_files=list(attempt.changed_files),
                      run_id=attempt.run_id, notes=unrecognized_note)


def run_benchmark(call_model, call_llm, bugs_path: str = "benchmark/selected_bugs.json",
                  results_dir: str = "eval/results") -> list[BugOutcome]:
    """Runs every bug in the benchmark and writes one timestamped results file, so successive
    runs accumulate rather than overwrite — progress over time is itself a result worth keeping."""
    bugs = load_bugs(bugs_path)
    outcomes = []
    for bug in bugs:
        print(f"[{bug.bug_id}] starting (setup takes ~44 min)...")
        outcome = run_one_bug(bug, call_model, call_llm)
        print(f"[{bug.bug_id}] {outcome.outcome} in {outcome.steps_taken} steps")
        outcomes.append(outcome)

    Path(results_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = Path(results_dir) / f"run-{stamp}.json"
    out_path.write_text(json.dumps([asdict(o) for o in outcomes], indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return outcomes


if __name__ == "__main__":
    import llm_client
    from groq import Groq

    _client = Groq()

    def call_llm(prompt: str) -> str:
        """Plain-text call for the verifier's soft check — no tools, no schema, just judgment."""
        response = _client.chat.completions.create(
            model=llm_client.MODEL, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    run_benchmark(llm_client.call_model, call_llm)
