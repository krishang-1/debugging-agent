"""Tool contract for the debugging agent — the four actions it can take against a checked-out bug.

Each tool is a plain function with a describable signature, called by name from the ReAct
loop based on the model's structured tool_call output. No framework, no magic — this is the
whole surface the agent can act through.
"""

from __future__ import annotations
from dataclasses import dataclass
import subprocess
import tempfile

from harness import _docker_exec, CONTAINER


@dataclass
class ToolResult:
    """What every tool hands back to the agent loop, in one consistent shape regardless of which tool ran."""
    success: bool
    output: str
    before_text: str | None = None  # set by edit_file so callers can build a real diff
    policy_violation: str | None = None  # set when a guardrail fired, for measurement not just blocking


# Commands blocked in bash_exec — each observed causing real damage or judged able to.
# The agent once ran `pip install -e .` which replaced fastapi in the container's SYSTEM
# python, outside the project venv entirely, affecting every other checkout in the container.
BLOCKED_BASH_PATTERNS = [
    "pip install", "pip uninstall", "pip3 install", "pip3 uninstall",
    "apt-get", "apt ", "sudo", "rm -rf /", "curl", "wget",
    "git checkout", "git reset", "git clean",
]


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file in the checked-out project.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "path relative to the project root"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace one exact block of text in a file with new text. old_text must appear exactly once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path relative to the project root"},
                    "old_text": {"type": "string", "description": "exact text to replace, must appear exactly once"},
                    "new_text": {"type": "string", "description": "replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Rerun the bug's target test and report pass/fail with the full output.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash_exec",
            "description": "Run an arbitrary shell command in the project directory — for anything the other three tools don't cover, e.g. grepping or listing files.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "shell command to run"}},
                "required": ["command"],
            },
        },
    },
]


def read_file(project_dir: str, path: str) -> ToolResult:
    """Reads one file's full contents from inside the checked-out project."""
    result = _docker_exec(f"cat {path}", workdir=project_dir, timeout=15)
    if result.returncode != 0:
        return ToolResult(success=False, output=result.stderr)
    return ToolResult(success=True, output=result.stdout)


def edit_file(project_dir: str, path: str, old_text: str, new_text: str,
              protected_path: str | None = None) -> ToolResult:
    """Replaces one exact block of text in a file. Fails loudly if old_text isn't found
    exactly once — same discipline as str_replace, no silent partial edits. Returns the
    file's full prior contents in before_text so the caller can build a real diff rather
    than recording only the replacement text.

    protected_path is the bug's target test file. Edits to it are refused and recorded as
    a policy violation rather than silently blocked — the attempt itself is data worth
    measuring (how often does the agent try to game the test?), and refusing here also
    prevents the agent corrupting the test file badly enough that nothing can run at all,
    which happened on a real run and wasted its entire remaining step budget."""
    if protected_path is not None and path == protected_path:
        return ToolResult(
            success=False,
            output=(f"Editing {path} is not permitted — it is the test that defines the bug. "
                    "Fix the source code so the existing test passes unchanged."),
            policy_violation="edit_target_test_file",
        )

    read_result = read_file(project_dir, path)
    if not read_result.success:
        return read_result

    occurrences = read_result.output.count(old_text)
    if occurrences != 1:
        return ToolResult(success=False, output=f"old_text found {occurrences} times, expected exactly 1")

    new_content = read_result.output.replace(old_text, new_text)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False, encoding="utf-8") as tmp:
        tmp.write(new_content)
        local_path = tmp.name

    subprocess.run(["docker", "cp", local_path, f"{CONTAINER}:{project_dir}/{path}"],
                    capture_output=True, timeout=15)
    return ToolResult(success=True, output=f"{path} updated", before_text=read_result.output)


def run_tests(bug, project_dir: str) -> ToolResult:
    """Reruns the bug's target test via harness.run_test() and reports the result."""
    import harness
    workdir = project_dir.rsplit("/", 1)[0]
    result = harness.run_test(bug, workdir=workdir)
    return ToolResult(success=(result.outcome == "passed"), output=result.raw_output)


def bash_exec(project_dir: str, command: str) -> ToolResult:
    """Runs an arbitrary shell command inside the project directory — escape hatch for
    anything the other three tools don't cover. Commands matching BLOCKED_BASH_PATTERNS are
    refused: the escape hatch exists for inspection (grep, ls, cat), not for mutating the
    environment the benchmark depends on."""
    lowered = command.lower()
    for pattern in BLOCKED_BASH_PATTERNS:
        if pattern in lowered:
            return ToolResult(
                success=False,
                output=(f"Command blocked: '{pattern}' is not permitted. bash_exec is for "
                        "inspecting the project (grep, ls, cat), not changing its environment."),
                policy_violation=f"blocked_bash:{pattern.strip()}",
            )
    result = _docker_exec(command, workdir=project_dir, timeout=30)
    return ToolResult(success=(result.returncode == 0), output=result.stdout + result.stderr)
