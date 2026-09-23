"""Runs the agent across every bug in the benchmark and records a structured outcome per bug.

Produces the raw results analysis.py turns into a categorized breakdown. Deliberately records
'gamed' as its own outcome distinct from solved/failed — an agent whose test passes only because
it cheated is neither a success nor an ordinary failure, and collapsing that distinction would
hide the single most interesting number this benchmark produces.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

from loader import load_bugs
from mutation_loader import load_mutation_bugs
import harness
import mutation_harness
import react_loop
import verifier
import groq


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


def _setup_error(bug, notes: str) -> BugOutcome:
    """Builds the outcome for a bug that never made it to an agent attempt at all."""
    return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome="setup_error",
                      steps_taken=0, policy_violations=[], verifier_verdict="not_run",
                      changed_files=[], run_id="", notes=notes)


def _attempt_and_verify(bug, project_dir: str, call_model, call_llm, initial_test_output: str) -> BugOutcome:
    """Runs one full agent attempt against an already-set-up checkout, then independently
    verifies the result — the part of run_one_bug that's identical regardless of which harness
    did the setup."""
    try:
        attempt = react_loop.run_attempt(bug, project_dir, call_model, initial_test_output)
    except groq.RateLimitError as e:
        return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome="rate_limited",
                          steps_taken=0, policy_violations=[], verifier_verdict="not_run",
                          changed_files=[], run_id="", notes=str(e))

    verdict = "not_run"
    if attempt.changed_files:
        verdict = verifier.verify_fix(bug, attempt.changed_files, call_llm).verdict

    if attempt.solved and verdict == "gamed_test":
        outcome = "gamed"
    elif attempt.solved:
        outcome = "solved"
    else:
        outcome = "failed"

    return BugOutcome(bug_id=bug.bug_id, category=bug.category, outcome=outcome,
                      steps_taken=attempt.steps_taken, policy_violations=attempt.policy_violations,
                      verifier_verdict=verdict, changed_files=list(attempt.changed_files),
                      run_id=attempt.run_id)


def _run_bugsinpy_bug(bug, call_model, call_llm, workdir_root: str) -> BugOutcome:
    """Sets up one BugsInPy bug fresh via the Docker harness, runs a full agent attempt against
    it, then independently verifies the result. setup_bug() restores from a per-bug snapshot
    when one exists (seconds), falling back to a full checkout+compile (~44 min, measured)
    otherwise."""
    workdir = f"{workdir_root}-{bug.bug_id}"

    try:
        unrecognized = harness.setup_bug(bug, version=0, workdir=workdir)
    except harness.HarnessSetupError as e:
        return _setup_error(bug, str(e))

    initial = harness.run_test(bug, workdir=workdir)
    if initial.outcome != "failed":
        return _setup_error(bug, f"bug did not reproduce cleanly: {initial.outcome}")

    project_dir = f"{workdir}/{bug.project}"
    outcome = _attempt_and_verify(bug, project_dir, call_model, call_llm, initial.raw_output)
    if unrecognized:
        outcome.notes = f"unrecognized env fixes: {unrecognized}"
    return outcome


def _run_mutation_bug(bug, call_model, call_llm) -> BugOutcome:
    """Applies one mutation bug's patch to the shared local tenacity checkout, runs a full
    agent attempt against it, then independently verifies the result. No workdir or snapshot —
    mutation_harness operates on a single checkout that must be reverted after every attempt
    (success, failure, or setup error alike) so the next bug starts clean."""
    try:
        mutation_harness.apply_bug(bug)
    except subprocess.CalledProcessError as e:
        return _setup_error(bug, str(e))

    try:
        initial = mutation_harness.run_test_result(bug)
        if initial.outcome != "failed":
            return _setup_error(bug, f"bug did not reproduce cleanly: {initial.outcome}")

        project_dir = str(mutation_harness.CHECKOUT.resolve())
        return _attempt_and_verify(bug, project_dir, call_model, call_llm, initial.raw_output)
    finally:
        mutation_harness.revert_bug(bug)


def run_one_bug(bug, call_model, call_llm, workdir_root: str = "/home/workspace/bench") -> BugOutcome:
    """Dispatches to the harness matching this bug's bug_type — harness.py (Docker) for
    'bugsinpy', mutation_harness.py (local checkout) for 'mutation' — so both bug types run
    through the same benchmark loop and produce the same BugOutcome shape."""
    if bug.bug_type == "mutation":
        return _run_mutation_bug(bug, call_model, call_llm)
    return _run_bugsinpy_bug(bug, call_model, call_llm, workdir_root)


def _latest_results_path(results_dir: str) -> Path | None:
    """Returns the most recently written results file in results_dir, or None if there isn't one yet."""
    files = sorted(Path(results_dir).glob("run-*.json"))
    return files[-1] if files else None


def run_benchmark(call_model, call_llm, bugs_path: str = "benchmark/selected_bugs.json",
                  mutation_bugs_path: str = "benchmark/mutation_corpus/corpus/mutation_bugs.json",
                  results_dir: str = "eval/results", resume: bool = False) -> list[BugOutcome]:
    """Runs every bug in the benchmark — BugsInPy bugs plus mutation-testing bugs — writing the
    results file after EACH bug rather than only at the end — a crash or closed terminal partway
    through then costs only the bug in progress, not every result that came before it. Each fresh
    run gets its own timestamped file, so successive runs accumulate rather than overwrite one
    another.

    resume=True instead picks up the most recent results file in results_dir and keeps appending
    to it: bugs already recorded there with a terminal outcome (anything but rate_limited) are
    skipped rather than re-attempted, and rate_limited entries are dropped so those bugs get
    retried. This is the intended way to work through the benchmark against a rate-limited key —
    run a few bugs, let it stop on rate_limited, come back later with resume=True and it picks up
    exactly where it left off instead of re-spending tokens on bugs already settled."""
    bugs = load_bugs(bugs_path) + load_mutation_bugs(mutation_bugs_path)
    Path(results_dir).mkdir(parents=True, exist_ok=True)

    outcomes: list[BugOutcome] = []
    out_path = _latest_results_path(results_dir) if resume else None
    if out_path is not None:
        prior = [BugOutcome(**o) for o in json.loads(out_path.read_text(encoding="utf-8"))]
        outcomes = [o for o in prior if o.outcome != "rate_limited"]
        completed_ids = {o.bug_id for o in outcomes}
        bugs = [b for b in bugs if b.bug_id not in completed_ids]
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = Path(results_dir) / f"run-{stamp}.json"

    if not bugs:
        print(f"nothing left to run — every bug already has a terminal outcome in {out_path}")
        return outcomes

    for bug in bugs:
        print(f"[{bug.bug_id}] starting...")
        outcome = run_one_bug(bug, call_model, call_llm)
        print(f"[{bug.bug_id}] {outcome.outcome} in {outcome.steps_taken} steps")
        outcomes.append(outcome)
        out_path.write_text(json.dumps([asdict(o) for o in outcomes], indent=2), encoding="utf-8")

        if outcome.outcome == "rate_limited":
            print(f"[{bug.bug_id}] hit the daily token limit — stopping here rather than "
                  f"burning through remaining bugs against a dead API. "
                  f"{len(bugs) - len(outcomes)} bug(s) not attempted this run.")
            break

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

    run_benchmark(llm_client.call_model, call_llm, resume="--resume" in sys.argv)
