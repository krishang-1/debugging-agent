"""Smoke test for logger.py — confirms steps write and read back in order, using a
throwaway log directory so it doesn't pollute the real logs/ folder."""

import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import logger

TEST_LOG_DIR = "logs/_test_scratch"


def test_steps_write_and_read_back_in_order():
    shutil.rmtree(TEST_LOG_DIR, ignore_errors=True)
    logger.log_step("fastapi-1", 1, "assistant", "PLAN: check the encoder", log_dir=TEST_LOG_DIR)
    logger.log_step("fastapi-1", 2, "observation", "read_file returned 40 lines", log_dir=TEST_LOG_DIR)

    records = logger.read_log("fastapi-1", log_dir=TEST_LOG_DIR)
    assert len(records) == 2
    assert records[0]["step"] == 1
    assert records[1]["role"] == "observation"

    shutil.rmtree(TEST_LOG_DIR, ignore_errors=True)


def test_run_id_separates_executions_in_a_shared_log():
    """Two runs against the same bug share one file — filtering by run_id should return
    only one run's lines, which is the whole point of adding run_id at all."""
    shutil.rmtree(TEST_LOG_DIR, ignore_errors=True)
    run_a, run_b = logger.new_run_id(), logger.new_run_id()
    logger.log_step("fastapi-1", 1, "assistant", "run A step", run_id=run_a, log_dir=TEST_LOG_DIR)
    logger.log_step("fastapi-1", 1, "assistant", "run B step", run_id=run_b, log_dir=TEST_LOG_DIR)

    assert len(logger.read_log("fastapi-1", log_dir=TEST_LOG_DIR)) == 2
    only_a = logger.read_log("fastapi-1", run_id=run_a, log_dir=TEST_LOG_DIR)
    assert len(only_a) == 1
    assert only_a[0]["content"] == "run A step"

    shutil.rmtree(TEST_LOG_DIR, ignore_errors=True)


def test_reading_a_nonexistent_bug_returns_empty():
    assert logger.read_log("no-such-bug", log_dir=TEST_LOG_DIR) == []
