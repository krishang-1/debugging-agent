"""Prompt templates for the debugging agent — the actual text the model sees at each stage.
Kept separate from react_loop.py's control flow so wording can be iterated without touching
logic, and so every prompt used anywhere in the agent lives in exactly one place.
"""

SYSTEM_PROMPT = """You are an autonomous debugging agent. You are given a failing test in a \
Python project and a small set of tools. Your job is to make the failing test pass by fixing \
the actual bug in the source code — not by editing the test itself, which is never a valid \
fix and will be automatically rejected.

Available tools: read_file, edit_file, run_tests, bash_exec.

Work in two phases:
1. PLAN — before taking any action, write a short plan: what you believe is wrong, and what \
you intend to check or change first. This is separate from your ongoing reasoning in the loop.
2. LOOP — repeat: state your current thought, take one tool action, read the observation, and \
decide your next step. Continue until the test passes or your step budget runs out.
"""


def format_bug_intro(bug, failing_test_output: str) -> str:
    """The first user-turn message — what the agent is asked to fix, grounded in the actual
    observed test failure, not a description alone."""
    return (
        f"Project: {bug.project}\n"
        f"Failing test: {bug.test_node}\n\n"
        f"Test output:\n{failing_test_output}\n\n"
        "Write your PLAN now."
    )


def format_observation(tool_name: str, tool_output: str) -> str:
    """Wraps a tool's raw output into the message the model sees after acting — kept minimal
    on purpose, the model should reason from the real output, not a paraphrase of it."""
    return f"Observation from {tool_name}:\n{tool_output}"


def format_step_budget_warning(steps_remaining: int) -> str:
    """Injected once the agent is close to running out of steps, so it has a chance to wrap
    up deliberately rather than getting cut off mid-thought."""
    return f"Note: {steps_remaining} step(s) remaining before this attempt ends."
