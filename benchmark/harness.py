"""Runs a single BugsInPy bug end-to-end: checkout, environment setup, and repeatable test execution.

Two-speed API: setup_bug() is slow (checkout + compile + fixes, runs once per attempt),
run_test() is fast (just reruns pytest against whatever code currently exists, called many
times per attempt as the agent edits and retries).
"""

from __future__ import annotations
from dataclasses import dataclass
import subprocess
import tempfile

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


def _docker_exec(command: str, workdir: str, timeout: int) -> subprocess.CompletedProcess:
    """Runs one command inside the container's shell, scoped to a working directory.

    Wraps the inner command with the container's own `timeout` utility — a Python-side
    subprocess timeout only kills the local docker.exe client on Windows, not the remote
    process running inside the container, which then keeps running orphaned and starves
    later commands. Captures output via temp files rather than pipes, because piped
    stdout/stderr hung indefinitely on this Windows+Docker Desktop setup waiting for an EOF
    that never reliably arrived even after the command had finished."""
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


SNAPSHOT_DIR = "/home/snapshots"  # inside the container, deliberately NOT under the bind mount


def _snapshot_path(bug) -> str:
    return f"{SNAPSHOT_DIR}/{bug.bug_id}.tar"


def snapshot_exists(bug) -> bool:
    """True when a prepared environment archive already exists for this bug."""
    result = _docker_exec(f"test -f {_snapshot_path(bug)} && echo OK", workdir="/", timeout=30)
    return "OK" in result.stdout


def save_snapshot(bug, workdir: str) -> bool:
    """Archives a prepared checkout so it can be restored instead of rebuilt. setup_bug() costs
    ~44 minutes (measured), almost all network wait across 100+ individual pip calls, and must be
    repaid every time an agent run leaves a checkout dirty.

    Uses tar rather than `docker commit`: /home/workspace is a bind-mounted volume from the host,
    and commit captures only the container's own layers, silently excluding exactly the directory
    that matters. The archive lives outside the mount so it stays part of the container itself."""
    _docker_exec(f"mkdir -p {SNAPSHOT_DIR}", workdir="/", timeout=30)
    result = _docker_exec(
        f"tar -cf {_snapshot_path(bug)} -C {workdir} {bug.project}",
        workdir="/", timeout=900)
    return result.returncode == 0 and snapshot_exists(bug)


def restore_snapshot(bug, workdir: str) -> bool:
    """Restores a prepared checkout from this bug's archive, replacing whatever state an earlier
    agent run left behind. Returns False when no snapshot exists, so callers fall back to a full
    setup_bug(). Extracts to a staging path and verifies the venv actually arrived before swapping
    it into place — a failed restore leaves the existing checkout untouched rather than deleting
    it first and discovering the problem afterwards."""
    if not snapshot_exists(bug):
        return False

    staging = f"{workdir}-restoring"
    _docker_exec(f"rm -rf {staging} && mkdir -p {staging}", workdir="/", timeout=120)

    extracted = _docker_exec(f"tar -xf {_snapshot_path(bug)} -C {staging}", workdir="/", timeout=900)
    if extracted.returncode != 0:
        _docker_exec(f"rm -rf {staging}", workdir="/", timeout=60)
        return False

    check = _docker_exec(f"test -x {staging}/{bug.project}/env/bin/pip && echo OK",
                         workdir="/", timeout=60)
    if "OK" not in check.stdout:
        _docker_exec(f"rm -rf {staging}", workdir="/", timeout=60)
        return False

    _docker_exec(f"rm -rf {workdir} && mkdir -p {workdir} && "
                 f"mv {staging}/{bug.project} {workdir}/{bug.project} && rm -rf {staging}",
                 workdir="/", timeout=180)
    return True


def setup_bug(bug, version: int, workdir: str, use_snapshot: bool = True) -> list[str]:
    """Checks out one version of a bug fresh (0=buggy, 1=fixed), compiles it, and applies its known fixes.
    Slow — meant to run once per attempt, not on every test retry. Wipes any prior checkout at workdir first.
    Returns the list of known_env_fixes entries that had no matching command, if any.

    When use_snapshot is set and a snapshot exists for this bug, restores from it instead —
    seconds rather than ~44 minutes. Snapshots are only used for the buggy version (0), since
    that is what agent runs repeatedly dirty and need reset."""
    if use_snapshot and version == 0 and restore_snapshot(bug, workdir):
        return []

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

    if version == 0:
        save_snapshot(bug, workdir)

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
