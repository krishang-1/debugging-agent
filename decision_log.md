# Decision Log

A record of non-obvious debugging decisions made on this project — not "fixed X, see
commit Y," but the actual reasoning trail: what the symptom looked like, what the
default/lazy explanation would have been, why that explanation was wrong, and how the
real cause was isolated. Written for interview/quiz use — each entry should stand alone
as a story with a defensible general lesson, not just a changelog line.

---

## 2026-09-24 — The `thought_signature` bug: separating an infra bug from a capability gap

**Symptom:** In a real 8-bug benchmark run against Gemini, `tenacity-02` and
`tenacity-03` came back `failed` after burning their full 12-step budget. Two bugs
failing out of eight is unremarkable on its own — the default, lazy explanation is
"the model just isn't good enough at these two." That explanation is falsifiable, and
was never checked before this session (flagged, then left alone, across at least two
prior sessions' worth of work on this project).

**Why the lazy explanation was suspicious enough to check:** these were the *only* two
attempts that failed within the mutation-testing layer, a layer specifically designed
so that every bug is a small, single-symptom, single-file change — not the kind of
thing where "the model just isn't smart enough" is a priori plausible for exactly two
bugs and not the other three in the same layer, attempted with the same model, same
step budget, same day. A capability explanation should predict *which* bugs fail based
on their difficulty, not just retroactively rationalize whichever ones did.

**Investigation:** Read the actual attempt transcripts (`logs/tenacity-02.jsonl`,
`logs/tenacity-03.jsonl`) instead of trusting the outcome label. Found a striking
pattern: every *other* turn, the model's real response was replaced by a synthetic
"your tool call was invalid" nudge — a message `llm_client.py`'s own error handler
manufactures when it catches a 400 from the API. The real error underneath: `Function
call is missing a thought_signature in functionCall parts`. Traced it to
`react_loop.py`'s history-reconstruction code, which rebuilt each assistant
`tool_calls` entry with only `id`/`type`/`function`, silently dropping the
`extra_content.google.thought_signature` field Gemini's API attaches to every
tool-calling turn and requires echoed back on any later request whose history includes
that turn. Once one tool call happened, every subsequent API call 400'd, got quietly
converted into a fake "invalid tool call" message by an error handler that was built
for a *different* failure mode (Groq's malformed-JSON tool calls) and happened to also
catch this one — masking it instead of surfacing it.

**Reproduced in isolation** before touching any code: a clean 6-turn tool-calling loop,
no bug-specific context at all, hit the exact same 400 on every other turn. Confirmed
the fix (propagating `extra_content` through the reconstructed history) eliminates it
completely — 6/6 clean turns.

**Why this matters — the general lesson:** once a fix like this exists, the honest way
to answer "was tenacity-02/03's failure a bug or a capability gap" is not to just
re-run them and see if they pass now — a pass doesn't tell you *which* explanation was
right, since fixing an infra bug and the model getting lucky look identical from the
outside. The actual test is a **controlled experiment**: hold the bug and the fixed
code constant, and vary only the one thing you're trying to isolate. Here that meant:
1. Re-run `tenacity-02` with the fix, same model (`flash-lite`) → **solved**, 6 steps.
   This alone shows the infra bug was sufficient to explain the original failure.
2. Re-run `tenacity-03` with the fix, same model → **still failed**, 12 steps, and
   the transcript showed *why*: redundant re-reading, three wasted steps guessing raw
   shell commands instead of using the provided `run_tests` tool, never once attempting
   an edit. That's a real behavioral/capability signature, not an infra symptom.
3. Re-run `tenacity-03` again, same bug, same fixed code, only the model swapped to the
   full `gemini-3.5-flash` → **solved**, 7 steps, first try.

Step 3 is the one that actually separates the two hypotheses. If the codebase were
still broken, a stronger model would hit the *same* wall (an infra bug doesn't care how
smart the model is). If `tenacity-03` were just an unreachably hard bug, a stronger
model wouldn't have solved it on the first try either. The fact that changing exactly
one variable flipped the outcome is what makes the capability-gap conclusion
defensible rather than a guess. This is the same logic as changing one variable in a
scientific experiment — without it, "it works now" is anecdote, not evidence, and a
recurring intermittent failure could quietly reappear on the next hard bug with no way
to tell whether it's the same root cause or a new one.

**Fix:** `agent/react_loop.py`, commit `b8f8b39`. `getattr(tc, "extra_content", None)`
guards it so providers/stubs without this field are unaffected — no Groq-specific
regression, no change needed to the test stub.

**Interview-quiz framing:** *"Two out of five tests in a similar batch are failing.
What's your first move — retrain/upgrade the model, or something else? What experiment
would prove which one it is?"*

---

## 2026-09-24 — The BugsInPy checkout check validated the wrong signal

**Symptom:** `test_harness.py::test_fixed_version_passes` had been failing across
multiple sessions, each time noted as "pre-existing, unrelated, out of scope" and never
actually opened. It's `harness.py`'s own smoke test, checking out BugsInPy bug #1's
*fixed* version and expecting its test to pass.

**Investigation:** Ran it directly instead of trusting the label. `run_test()` reported
`environment_error` (pytest never reached collection) after only ~2 minutes — far short
of the ~44-minute compile this project's own code documents as normal, which was itself
a clue that something failed *before* compile ever got a fair shot. Reproduced the
checkout step manually and found the real signal: the `git clone` inside
`bugsinpy-checkout` was killed by the wrapper's own timeout mid-transfer
(`fetch-pack: unexpected disconnect while reading sideband packet`, subprocess exit
code 124) — yet `harness.py`'s own check
(`if "status=\"OK\"" not in checkout_result.stdout`) saw the checkout as successful
anyway and let it proceed straight into a doomed compile.

**Root cause:** read `bugsinpy-checkout`'s actual source. The string `status="OK"` is
echoed from a completely different, unrelated place — it's a line from the *project's
own static metadata file* (`project.info`), printed near the very start of the script,
**before the `git clone` that does the real work even runs.** The check was never
actually validating "did the checkout succeed" — it was validating "is this a project
BugsInPy knows about," which is always true for a project already in the dataset,
regardless of what happens next. This bug has presumably been present, silently, since
this project's harness was first written — invisible because the common path (a
snapshot already existing) never exercises this checkout code at all.

**Fix:** `benchmark/harness.py`, commit `2519282`. Replaced the string check with the
actual ground truth: the checkout subprocess's own return code, plus whether the
target directory's `.git` folder actually exists on disk.

**Why this matters — the general lesson:** a verification check is only as good as
what it actually observes. This one *looked* like a success check — it had the right
shape, sat in the right place in the code, had a plausible-sounding condition — but it
was checking output that happened to always be present regardless of the thing it
claimed to verify. The fix wasn't "add better error handling," it was "check a
different, more specific fact" — the presence of `.git`, not a string that was never
causally connected to clone success in the first place. Any check like this
(`if "OK" in output`, `if not error_seen`) is worth asking: *what specific event
produces this exact signal, and could that event happen for a reason unrelated to the
thing I'm actually trying to verify?*

**Interview-quiz framing:** *"A test that's supposed to catch a setup failure has been
silently passing through broken setups for months. How do you find that, and what's
the general pattern to watch for?"*

---

## 2026-09-24 — Docker vs. local `bash_exec`: an asymmetric timeout that crashed a real run

**Symptom:** The real 8-bug benchmark run crashed entirely partway through
`tenacity-04`, with an unhandled `subprocess.TimeoutExpired` traceback killing the
whole process instead of the run continuing to the next bug.

**Root cause:** `tools.bash_exec()` has two execution paths, added at different times
for different bug types. The Docker path (BugsInPy bugs) calls `_docker_exec()`, which
wraps every command with the *container's own* `timeout` utility — the subprocess
always exits cleanly on its own terms, so Python's `subprocess.run()` never raises.
The local path (added later, for mutation bugs, which run on a plain checkout with no
container) was written by analogy to the Docker path but skipped that detail: it calls
`subprocess.run(..., timeout=30)` directly, with no in-command wrapper. When the agent
ran an unbounded `find / -name pytest` and it genuinely took longer than 30 seconds,
Python's own timeout fired for real — something the Docker path structurally cannot
experience — and nothing was catching it.

**Fix:** `agent/tools.py`, commit `5b22de4`. Wrapped the local path's
`subprocess.run()` in a `try/except subprocess.TimeoutExpired`, returning a normal
failed `ToolResult` instead of letting the exception propagate. Verified with a real
35-second command.

**Why this matters — the general lesson:** two code paths that are supposed to be
equivalent (same tool, same contract, different backend) had a real behavioral
difference that only manifests under a failure condition neither path's happy-path
testing would ever exercise. "It's the same as the other path" is a claim worth
checking specifically at the failure boundaries, not just the success case — the two
paths agreed on what a *successful* command returns, but diverged completely on what
happens when a command doesn't finish in time, and that divergence was invisible until
a real agent, doing something a human wouldn't (searching the entire filesystem from
`/`), actually hit it.

**Interview-quiz framing:** *"You have two implementations of the same interface for
different backends. What's the fastest way to find behavioral differences between
them, before production does it for you?"*

---

## 2026-09-24 — Recording which model produced an outcome

**Context:** Not a bug in the sense of broken behavior, but a real gap discovered
while investigating whether the BugsInPy layer's 0/3 result would hold up on a re-run
with a different, stronger model. `BugOutcome` (the results schema) had no field
recording which model produced a given outcome — `call_model` is passed around as an
opaque injected callable with no identity of its own, so nothing in the whole call
chain ever recorded it.

**Why it mattered right then, not hypothetically:** a results file combining attempts
from `gemini-3.5-flash-lite` (cheap, high quota) and `gemini-3.5-flash` (stronger,
5 RPM / 20 RPD) was about to become a real, immediate need — not a someday concern.
Without this field, a combined file's solve rate would be uninterpretable: a "solved"
entry says nothing about whether it took the cheap model or the expensive one, which
is exactly the variable this whole investigation was trying to isolate (see the
`thought_signature` entry above — the same distinction, at the results-schema level).

**Fix:** `eval/run_benchmark.py`, commit `d3cc6f1`. Added `BugOutcome.model`, threaded
as an explicit required parameter through `run_one_bug` /
`_run_bugsinpy_bug` / `_run_mutation_bug` / `_attempt_and_verify` / `_setup_error` /
`run_benchmark` — the same dependency-injection discipline already used for
`call_model` and `call_llm`, not inferred by introspecting the callable. Backward
compatible: the empty-string default means `--resume` can still load an older results
file that predates this field.

**Why this matters — the general lesson:** a schema gap doesn't announce itself the
way a crash does — the benchmark runs fine, writes valid JSON, and looks complete
right up until someone asks a question the data was never designed to answer. The tell
here was noticing the gap *before* generating more data that would need it, not after.

**Interview-quiz framing:** *"Your experiment's results table doesn't have a column
for the one variable you're about to start varying. What's the cost of adding it now
versus after you've already generated a week of data?"*
