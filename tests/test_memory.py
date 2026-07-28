"""Smoke test for memory.py — confirms turns accumulate in order and render correctly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from memory import AttemptMemory


def test_turns_accumulate_in_order():
    mem = AttemptMemory()
    mem.add("assistant", "PLAN: check the encoder function")
    mem.add("observation", "read_file returned 40 lines")
    transcript = mem.as_transcript()
    assert transcript.index("PLAN") < transcript.index("read_file")
