"""Runs a single BugsInPy bug end-to-end: checkout, environment setup, and repeatable test execution.

Two-speed API: setup_bug() is slow (checkout + compile + fixes, runs once per attempt),
run_test() is fast (just reruns pytest against whatever code currently exists, called many
times per attempt as the agent edits and retries).
"""

from __future__ import annotations
from dataclasses import dataclass
import subprocess

CONTAINER = "debugagent"
COMPILE_TIMEOUT = 3300  # measured: 43m48s real time (mostly network wait across 100+ per-package pip calls, not CPU), set with genuine margin
TEST_TIMEOUT = 60       # a single test run should never legitimately take this long

# Maps a known_env_fixes entry from selected_bugs.json to the real command that applies it.
# Every command here was discovered and verified by hand across bugs #1, #7, and #12.
FIX_COMMANDS = {
    "build_essential": "apt-get update && apt-get install -y build-essential libffi-dev python3-dev libssl-dev",
    "pytest_upgrade": "./env/bin/pip install --upgrade --force-reinstall 'pytest>=7,<8'",
    "py_uninstall": "./env/bin/pip uninstall -y py",
    "pydantic_pin_1_10_26": "./env/bin/pip install --force-reinstall 'pydantic==1.10.26'",
    "pydantic_pin_0_26": "./env/bin/pip install --force-reinstall 'pydantic==0.26'",
    "setuptools_upgrade": "./env/bin/pip install --upgrade setuptools",
    "aiofiles_upgrade": "./env/bin/pip install --force-reinstall --upgrade aiofiles",
    "requests_urllib3_upgrade": "./env/bin/pip install --force-reinstall --upgrade requests urllib3",
}


class HarnessSetupError(Exception):
    """Raised when checkout or compile itself fails to complete — distinct from the target test merely failing."""


@dataclass
class TestResult:
    """What run_test() hands back — enough for the agent to actually act on, not just a verdict."""
    outcome: str          # "passed", "failed", or "environment_error"
    raw_output: str
    unrecognized: bool    # True when the result can't be trusted as a real bug signal


import tempfile


def _docker_exec(command: str, workdir: str, timeout: int) -> subprocess.CompletedProcess:
    """Runs one command inside the container's shell, scoped to a working directory.
    Wraps the inner command with the container's own `timeout` utility — a Python-side
    subprocess timeout only kills the local docker.exe client on Windows, not the remote
    process running inside the container. Without this, a killed client leaves the actual
    remote process (e.g. a stuck compile) running orphaned, which then starves or blocks
    completely unrelated later commands. Python's own timeout is kept as a safety net,
    given extra margin so the container-side timeout fires first under normal conditions."""
    wrapped_command = f"timeout {timeout}s {command}"
    full_command = ["docker", "exec", "-w", workdir, CONTAINER, "bash", "-c", wrapped_command]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out_f, \
         tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_f:
        proc = subprocess.run(full_command, stdout=out_f, stderr=err_f,
                               stdin=subprocess.DEVNULL, timeout=timeout + 15, text=True)
        out_f.seek(0)
        err_f.seek(0)
        stdout = out_f.read()
        stderr = err_f.read()
    return subprocess.CompletedProcess(full_command, proc.returncode, stdout, stderr)


def setup_bug(bug, version: int, workdir: str) -> list[str]:
    """Checks out one version of a bug fresh (0=buggy, 1=fixed), compiles it, and applies its known fixes.
    Slow — meant to run once per attempt, not on every test retry. Wipes any prior checkout at workdir first.
    Returns the list of known_env_fixes entries that had no matching command, if any."""
    _docker_exec(f"rm -rf {workdir}", workdir="/", timeout=30)

    checkout_cmd = f"bugsinpy-checkout -p {bug.project} -v {version} -i {bug.bugsinpy_id} -w {workdir}"
    checkout_result = _docker_exec(checkout_cmd, workdir="/", timeout=120)
    if "status=\"OK\"" not in checkout_result.stdout:
        raise HarnessSetupError(f"checkout failed for {bug.bug_id}:\n{checkout_result.stdout}{checkout_result.stderr}")

    project_dir = f"{workdir}/{bug.project}"
    try:
        _docker_exec("bugsinpy-compile", workdir=project_dir, timeout=COMPILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HarnessSetupError(f"compile timed out after {COMPILE_TIMEOUT}s for {bug.bug_id}")

    unrecognized_fixes = []
    for fix_name in bug.known_env_fixes:
        command = FIX_COMMANDS.get(fix_name)
        if command is None:
            unrecognized_fixes.append(fix_name)
            continue
        _docker_exec(command, workdir=project_dir, timeout=300)

    return unrecognized_fixes


def run_test(bug, workdir: str) -> TestResult:
    """Reruns the target test against whatever code currently exists in the checkout.
    Fast — this is what the agent calls after every edit. Distinguishes a real bug
    result from environment noise by checking whether pytest actually reached collection,
    not just by exit code, since both a real test failure and an import crash exit non-zero."""
    project_dir = f"{workdir}/{bug.project}"
    try:
        result = _docker_exec("bugsinpy-test", workdir=project_dir, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return TestResult(outcome="environment_error", raw_output="test run timed out", unrecognized=True)

    output = result.stdout + result.stderr

    if "collected" not in output:
        return TestResult(outcome="environment_error", raw_output=output, unrecognized=True)

    if " passed" in output:
        return TestResult(outcome="passed", raw_output=output, unrecognized=False)

    return TestResult(outcome="failed", raw_output=output, unrecognized=False)
