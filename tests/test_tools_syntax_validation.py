"""Test for edit_file's Python syntax validation — added after real live runs showed the
model twice producing code with literal backslash-n instead of real newlines, corrupting a
file in a way that wasn't caught until a later run_tests call, several steps later."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmark"))

import tools

PROJECT_DIR = "/home/workspace/fastapi-fixed/fastapi"


def test_edit_file_rejects_mis_escaped_newlines_in_python_files():
    """Reproduces the exact failure mode observed in run 518f6a3e: new_text containing a
    literal '\\n' sequence instead of a real line break, which parses as invalid Python."""
    result = tools.edit_file(
        PROJECT_DIR, "fastapi/encoders.py",
        old_text="from enum import Enum",
        new_text='from enum import Enum\\ntry: pass\\nexcept Exception as e:\\n    raise e',
    )
    assert not result.success
    assert "not valid Python" in result.output
    assert "mis-escaped" in result.output


def test_edit_file_accepts_genuinely_valid_python():
    """Same file, a real edit with a real newline — should not be rejected by the new check."""
    result = tools.edit_file(
        PROJECT_DIR, "fastapi/encoders.py",
        old_text="from enum import Enum",
        new_text="from enum import Enum\nfrom decimal import Decimal",
    )
    assert result.success
    # revert immediately so the checkout stays clean for other manual reference
    tools.edit_file(PROJECT_DIR, "fastapi/encoders.py",
                     old_text="from enum import Enum\nfrom decimal import Decimal",
                     new_text="from enum import Enum")


def test_syntax_validation_skips_non_python_files():
    """The check is only meaningful for .py files — a non-Python file with the same
    'literal backslash-n' content should not be rejected on syntax grounds."""
    result = tools.edit_file(PROJECT_DIR, "README.md",
                              old_text="FastAPI", new_text='FastAPI\\nSomething')
    # Whatever happens here should not be the Python-syntax rejection path.
    if not result.success:
        assert "not valid Python" not in result.output
    if result.success:
        tools.edit_file(PROJECT_DIR, "README.md", old_text='FastAPI\\nSomething', new_text="FastAPI")
