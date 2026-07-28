"""Turns raw benchmark results into the categorized breakdown that is the actual deliverable.

A single overall success rate hides where an agent is genuinely capable versus where it fails —
the same reason rag_scratch reported retrieval performance per method rather than one aggregate
number. Breaking results down by bug category is what makes the result interpretable.
"""

from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path


def load_results(path: str) -> list[dict]:
    """Reads one timestamped results file written by run_benchmark.py."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def latest_results(results_dir: str = "eval/results") -> list[dict]:
    """Loads the most recent results file, so analysis can be run without naming a file."""
    files = sorted(Path(results_dir).glob("run-*.json"))
    if not files:
        return []
    return load_results(str(files[-1]))


def summarize(results: list[dict]) -> dict:
    """Aggregates outcomes overall and per category, plus the reward-hacking measurements that
    a plain success rate would hide entirely."""
    by_category: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_category[r["category"]][r["outcome"]] += 1

    violation_counts = Counter()
    for r in results:
        for v in r["policy_violations"]:
            violation_counts[v] += 1

    total = len(results)
    overall = Counter(r["outcome"] for r in results)
    attempted_gaming = sum(1 for r in results if r["policy_violations"])

    return {
        "total_bugs": total,
        "overall": dict(overall),
        "solve_rate": round(overall["solved"] / total, 3) if total else 0.0,
        "by_category": {cat: dict(counts) for cat, counts in by_category.items()},
        "bugs_attempting_policy_violation": attempted_gaming,
        "policy_violation_counts": dict(violation_counts),
        "mean_steps": round(sum(r["steps_taken"] for r in results) / total, 1) if total else 0.0,
    }


def format_report(summary: dict) -> str:
    """Renders the summary as readable text — what actually goes in the README."""
    lines = [
        f"Bugs evaluated: {summary['total_bugs']}",
        f"Solve rate: {summary['solve_rate']:.1%}",
        f"Mean steps per attempt: {summary['mean_steps']}",
        "",
        "Outcomes:",
    ]
    for outcome, count in sorted(summary["overall"].items()):
        lines.append(f"  {outcome}: {count}")

    lines += ["", "By category:"]
    for cat, counts in sorted(summary["by_category"].items()):
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        lines.append(f"  {cat}: {breakdown}")

    lines += ["", f"Bugs where the agent attempted a blocked action: "
                  f"{summary['bugs_attempting_policy_violation']}/{summary['total_bugs']}"]
    for violation, count in sorted(summary["policy_violation_counts"].items()):
        lines.append(f"  {violation}: {count}")

    return "\n".join(lines)


if __name__ == "__main__":
    results = latest_results()
    if not results:
        print("no results found in eval/results — run eval/run_benchmark.py first")
    else:
        print(format_report(summarize(results)))
