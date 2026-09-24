# debugging_agent

An autonomous LLM debugging agent. Given a failing test and a checked-out project, it
reads code, forms a hypothesis, edits source, and re-runs the test — until it passes or
it runs out of steps. The point of this project isn't just "can an LLM fix a bug," but
specifically whether it's doing genuine debugging *reasoning*, as opposed to
pattern-matching a bug it already saw during training.

## The three-layer benchmark design

**Layer 1 — BugsInPy (real historical bugs, `fastapi`).** Real bugs, real code, a
well-understood academic dataset with ground-truth buggy/fixed commits. The weakness:
these bugs are old and public. A large enough LLM may have memorized the actual fix
from GitHub history, blog posts, or Stack Overflow during training — so a "solve" here
doesn't, by itself, prove genuine reasoning versus recall.

**Layer 2 — mutation testing (`tenacity`).** Built specifically to answer Layer 1's
weakness: inject fresh, synthetic bugs — via `mutmut` mutation testing, hand-picked
from real survivors, each backed by a newly hand-written regression test — into a
modern, actively-maintained repo the model cannot have memorized a fix for, because the
bug never existed in that project's real history. A solve here is much stronger
evidence of genuine capability. Full construction methodology, including the mutants
that were discarded as equivalent (same behavior despite the code change) and a real
bug caught in the verification tooling itself, is documented in
[`benchmark/mutation_corpus/corpus/README.md`](benchmark/mutation_corpus/corpus/README.md).

**Layer 3 — own-repo dogfooding.** Planned, per this project's original design, but
**not yet implemented** — no corpus, no loader, no code. The intent is to eventually
run the agent against bugs in its own codebase. Stated here honestly rather than
implied: this layer does not exist yet.

## Architecture

```
agent/
  react_loop.py    thought -> action -> observation loop, 12-step budget per attempt
  tools.py         4 tools (read_file, edit_file, run_tests, bash_exec), each
                   dispatching to Docker or a local checkout depending on bug type
  llm_client.py    the one file that imports the model SDK directly — currently
                   Gemini via its OpenAI-compatible endpoint; call_model()'s fixed
                   signature keeps the provider swappable without touching react_loop
  verifier.py      independent second LLM pass judging whether a passing test is a
                   genuine fix or a gamed one (e.g. editing the test itself)
  logger.py        per-step JSONL logging, one file per bug, run_id-tagged
  memory.py        in-attempt memory scoped to a single run

benchmark/
  harness.py           Docker-based BugsInPy harness: checkout, compile, snapshot/restore
  mutation_harness.py  local-checkout harness for the mutation layer: apply/revert a
                       patch against a pinned tenacity commit, no Docker needed
  loader.py / mutation_loader.py   bug metadata -> structured records
  mutation_corpus/     the 5 hand-verified mutation bugs (see its own README)

eval/
  run_benchmark.py   dispatches each bug to the right harness by bug_type, runs the
                     agent, verifies the result, writes results incrementally
                     (crash-safe) — supports --resume for working across a
                     rate-limited key's daily quota over multiple sessions
  analysis.py        turns a results file into a categorized breakdown
```

## Results (as of 2026-09-24)

**Layer 2 (mutation testing / tenacity): 5/5 solved (100%)**, every one independently
verified as a genuine fix, not gamed. Full breakdown, including which of two Gemini
models solved each bug, in
[`eval/results/run-20260924-141632-post-thought-signature-fix.json`](eval/results/run-20260924-141632-post-thought-signature-fix.json).

**Layer 1 (BugsInPy / fastapi): pending — not a final result.** An earlier run showed
0/3, but that run predates a fix (`b8f8b39`) for a bug that was costing every attempt
in the run roughly half its step budget — so 0/3 is not trustworthy as a measure of
real agent capability and should not be cited as final. A re-run attempt after the fix,
using a stronger model to get real signal, was blocked by hitting that model's
confirmed 20-requests/day free-tier quota before producing any usable data. See the
same results file above — the `fastapi-7`/`fastapi-12` entries are explicitly flagged
`PENDING RE-VERIFICATION` in their notes rather than presented as current truth. This
is genuinely an open question, not a result.

**Layer 3 (own-repo dogfooding): not implemented.**

## Known limitations

- Free-tier Gemini rate limits (confirmed live: `gemini-3.5-flash` is 5 requests/min,
  20 requests/day; `gemini-3.5-flash-lite` is 15/min, ~500/day) make it genuinely hard
  to get a full-confidence read on the harder bugs in one sitting with the stronger
  model. This is a real, current constraint on how conclusively Layer 1 can be
  evaluated, not a benchmark design flaw.
- This environment's network to GitHub has been measured as severely throttled at
  times, which blocks `harness.py`'s own "fixed checkout" sanity test (not the real
  benchmark run — see `decision_log.md` for the full investigation).

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY
python eval/run_benchmark.py [--resume]
python eval/analysis.py
```

See [`decision_log.md`](decision_log.md) for the reasoning behind non-obvious fixes
made on this project — written as a reasoning trail, not a changelog.
