# Mutation-testing corpus — `tenacity`

Layer 2 of the three-layer benchmark (BugsInPy → mutation testing → own-repo
dogfooding). Purpose: BugsInPy bugs are old, public, and possibly memorized by
the LLM's training data. This corpus injects fresh, never-seen bugs into a
modern, actively-maintained repo to isolate genuine debugging reasoning from
recall.

## Target repo

`tenacity` (https://github.com/jd/tenacity), pinned at commit
`3e58094d3bc414975aad9eadf343a32bdb3b89b3`. Chosen because it's unrelated to
the FastAPI/Starlette/Pydantic ecosystem used in the BugsInPy layer, and is
pure synchronous logic with no async-server test-harness noise.

## Method

1. `mutmut run` against `tenacity/` (whole package — mutmut 3.x requires the
   full package tree, not a subset of files, or imports break) using
   `pyproject.toml`'s `[tool.mutmut]` config (`source_paths`,
   `pytest_add_cli_args_test_selection` — note: `paths_to_mutate`/`tests_dir`
   are deprecated in mutmut 3.8.0 and silently produce a broken config that
   crashes with `TypeError: can only concatenate list (not "str") to list`).
2. 691 mutants generated; 525 killed by tenacity's own test suite, ~150
   survived (existing tests didn't catch them).
3. Hand-picked 5 survivors from the four core logic modules
   (`retry.py`, `wait.py`, `_utils.py`) for category diversity, each backed
   by a **new, hand-written regression test** — tenacity's own suite doesn't
   catch these, so without a dedicated test the bug would have no signal for
   the agent to work from (mirrors BugsInPy's per-bug test-node structure).
4. Each candidate was manually verified with the same buggy-fails/fixed-passes
   discipline used for the BugsInPy layer: apply `bug.patch`, confirm the
   regression test fails; revert, confirm it passes. Both directions run
   against a clean copy of the source with `__pycache__` cleared each time
   (stale bytecode caches silently made two early verification passes look
   green when they weren't — worth remembering as a gotcha).

## Equivalent mutants discarded

Two initially-promising survivors turned out to be **equivalent mutants**
(same observable behavior despite the code change) once checked directly,
rather than trusted on mutmut's "survived" label alone:

- `_utils.find_ordinal`: boundary changed from `11 <= n%100 <= 13` to
  `<= 14`. Looked like an off-by-one bug, but `14 % 100 == 14` still falls
  into the `4 <= pos_num <= 20` branch (or the recursive `pos_num % 10`
  branch for larger numbers), which also returns `"th"` — same output either
  way. Discarded.
- `_utils.is_coroutine_callable`: `partial_call` hardcoded to `None` instead
  of unwrapping `functools.partial`. Looked like it would misdetect
  `functools.partial`-wrapped coroutines, but `inspect.iscoroutinefunction`
  already unwraps `functools.partial` natively on this Python version, so
  the manual unwrap logic is dead code. Discarded, replaced with the
  `retry_if_exception_message.match` bug instead.

This is the same "don't just trust the tool's classification" discipline
used when picking BugsInPy bugs — mutmut's "survived" tag means *the
existing suite* didn't kill it, not that the mutant is a genuine, observable
bug.

## First real bug found in the *verification tooling itself*

Bug `tenacity-04`'s first-draft patch (`str.replace(old, new, 1)` on a
non-unique code block) silently mutated the wrong one of three near-identical
`self.exception_types = exception_types` class bodies
(`retry_if_exception_type` instead of the intended
`retry_if_not_exception_type`), so the "buggy" run passed cleanly — the bug
was there, just in the wrong class. Caught by the mandatory round-trip
verification step, not assumed from a clean diff. Fixed by widening the
`old`/`new` match to include the full class body so it's unique across the
file before regenerating the patch via a real `diff -u`, never by hand-typing
line numbers (which also produced corrupt/non-applying patches on the first
attempt against the real file — a second, smaller lesson).

## Files

```
mutation_bugs.json          # loader-compatible metadata for all 5 bugs
tenacity-0{1..5}/
  bug.patch                 # unified diff: fixed -> buggy (git apply to inject)
  test_regression.py        # hand-written regression test, buggy-fails/fixed-passes
```

## Integration with the existing harness

`bug.patch` applies with `git apply` from the repo root against a clean
checkout of `tenacity` at the pinned commit. `test_regression.py` is
self-contained (imports only from `tenacity`, no fixtures) and can be
dropped into the checkout's working directory and run with `pytest
test_regression.py`. This mirrors `benchmark/harness.py`'s existing
`setup_bug`/`run_test` contract closely enough that a `MutationBugRecord`
loader analogous to `BugRecord` in `benchmark/loader.py` should be a thin
adapter, not a rewrite — the main difference is there's no
`bugsinpy-checkout`/`bugsinpy-compile` step; the checkout is a plain `git
clone` + `pip install -e ".[test]"`.
