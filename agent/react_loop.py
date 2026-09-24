"""The agent's core loop: thought -> action -> observation, repeated until the target test
passes or the step budget runs out. Ties together prompts, tools, memory, and logging —
this is the one file that assembles every independently-tested piece into a working agent.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import difflib
import json

import prompts
import tools
import memory as memory_module
import logger as logger_module

MAX_STEPS = 12  # bounds a single attempt's model calls and tool actions
MAX_OBSERVATION_CHARS = 4000  # per tool result sent back to the model
OBSERVATION_WINDOW = 4  # older observations are collapsed to a placeholder in history


def _truncate(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    """Caps a single tool observation. Large file reads dominate token cost — the full history
    is resent on every call, so one 2,500-token file read costs ~35,000 tokens across a 15-step
    attempt. Keeping head and tail preserves the parts that carry signal (imports, signatures,
    and the failing assertion at the end) while cutting the middle."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2):]
    omitted = len(text) - limit
    return f"{head}\n\n... [{omitted} characters omitted] ...\n\n{tail}"


def _compact_history(messages: list[dict], window: int = OBSERVATION_WINDOW) -> list[dict]:
    """Replaces the content of tool observations older than the last `window` with a short
    placeholder. The model keeps the full recent context it's actively reasoning about, while
    stale file dumps stop being resent on every subsequent call."""
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    stale = set(tool_indices[:-window]) if len(tool_indices) > window else set()
    if not stale:
        return messages
    compacted = []
    for i, m in enumerate(messages):
        if i in stale:
            compacted.append({**m, "content": "[earlier observation omitted to save context]"})
        else:
            compacted.append(m)
    return compacted


@dataclass
class AttemptResult:
    """What run_attempt() hands back once an attempt ends, one way or another."""
    solved: bool
    steps_taken: int
    changed_files: dict[str, str]  # path -> unified diff of everything that changed in it
    run_id: str = ""
    policy_violations: list[str] = field(default_factory=list)  # guardrail trips, measured not just blocked


def _unified_diff(path: str, before: str, after: str) -> str:
    """Builds a readable unified diff for one file — what the verifier actually needs to
    judge a change, rather than just the replacement text with no surrounding context."""
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))


def _dispatch_tool(name: str, tool_input: dict, bug, project_dir: str) -> tools.ToolResult:
    """Routes a model-requested tool call to the matching real function, injecting the
    project context every tool needs but the model never has to specify itself."""
    if name == "read_file":
        return tools.read_file(project_dir, tool_input["path"])
    if name == "edit_file":
        protected = bug.test_node.split("::")[0]
        return tools.edit_file(project_dir, tool_input["path"], tool_input["old_text"],
                               tool_input["new_text"], protected_path=protected)
    if name == "run_tests":
        return tools.run_tests(bug, project_dir)
    if name == "bash_exec":
        return tools.bash_exec(project_dir, tool_input["command"])
    return tools.ToolResult(success=False, output=f"unknown tool: {name}")


def run_attempt(bug, project_dir: str, call_model, initial_test_output: str, max_steps: int = MAX_STEPS) -> AttemptResult:
    """Runs one full debugging attempt against an already-set-up checkout. call_model is
    injected (see llm_client.call_model for the real implementation) so this stays testable
    with a stub, same discipline as verifier.py. Message/tool-call shapes here follow the
    OpenAI-compatible format llm_client.py's provider speaks (Gemini, previously Groq):
    tool_calls carry JSON-string arguments (parsed per call), and
    each tool result is sent back as its own 'tool' role message, not a combined block."""
    run_id = logger_module.new_run_id()
    attempt_memory = memory_module.AttemptMemory()
    messages = [{"role": "user", "content": prompts.format_bug_intro(bug, initial_test_output)}]
    original_contents: dict[str, str] = {}  # first-seen state per file, for end-to-end diffs
    latest_contents: dict[str, str] = {}
    policy_violations: list[str] = []

    def _finish(solved: bool, steps: int) -> AttemptResult:
        diffs = {
            path: _unified_diff(path, original_contents[path], latest_contents[path])
            for path in latest_contents
        }
        return AttemptResult(solved=solved, steps_taken=steps, changed_files=diffs,
                             run_id=run_id, policy_violations=policy_violations)

    for step in range(1, max_steps + 1):
        response = call_model(_compact_history(messages), tools.TOOL_SCHEMAS, prompts.SYSTEM_PROMPT)
        message = response.choices[0].message

        assistant_entry = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_entry["tool_calls"] = []
            for tc in message.tool_calls:
                entry = {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                # Gemini rejects any later request whose history includes a function-call
                # turn missing this field ("Function call is missing a thought_signature"),
                # so it must round-trip through history exactly like it came in. Providers
                # (and the test stub) that don't set it are unaffected — getattr just no-ops.
                extra_content = getattr(tc, "extra_content", None)
                if extra_content:
                    entry["extra_content"] = extra_content
                assistant_entry["tool_calls"].append(entry)
        messages.append(assistant_entry)

        if message.content:
            attempt_memory.add("assistant", message.content)
            logger_module.log_step(bug.bug_id, step, "assistant", message.content, run_id=run_id)

        if not message.tool_calls:
            messages.append({"role": "user", "content": "Continue: take an action using one of your tools."})
            continue

        for call in message.tool_calls:
            tool_input = json.loads(call.function.arguments)
            result = _dispatch_tool(call.function.name, tool_input, bug, project_dir)
            if result.policy_violation:
                policy_violations.append(result.policy_violation)
            attempt_memory.add("observation", result.output)
            logger_module.log_step(bug.bug_id, step, "observation", result.output, run_id=run_id)

            if call.function.name == "edit_file" and result.success and result.before_text is not None:
                path = tool_input["path"]
                original_contents.setdefault(path, result.before_text)
                latest_contents[path] = result.before_text.replace(tool_input["old_text"], tool_input["new_text"])

            if call.function.name == "run_tests" and result.success:
                return _finish(solved=True, steps=step)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": prompts.format_observation(call.function.name, _truncate(result.output)),
            })

    return _finish(solved=False, steps=max_steps)
