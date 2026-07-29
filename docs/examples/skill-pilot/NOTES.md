# Paired-harness pilot — 2026-07-29

> ## ⚠ RETRACTED, same day
>
> **The separation between arms in this pilot is an artifact of the harness.** The run
> prompt interpolated an absolute path to a directory *outside* the workspace
> (`/Users/loki/Desktop/euthyna/.venv/bin/python`). Qwen3-8B read that as the project
> root, tried to open `test_task.py` there, was refused by opencode's
> external-directory guard, and ended the run having edited nothing.
>
> Arms that happened to carry an `AGENTS.md` were anchored to the correct root and
> worked normally. Arms that carried nothing were not. That file's presence — not its
> contents — is what the pilot measured. See
> [§ The defect that got through](#the-defect-that-got-through).
>
> What still stands: the instrument refused to call a 3–0 sweep significant, and the
> conclusion — *this establishes nothing about skills* — was right. It was right for
> the wrong reason, and none of the five controls could see why.
>
> Superseded by the cost-primary experiment in
> [`docs/examples/cost-primary/`](../cost-primary/).

The first end-to-end run of `euthyna experiment`: plan → execute → grade → analyze,
against a local Qwen3-8B on vllm-metal, all traffic through the gateway.

Twelve runs: 3 tasks × 4 arms × 1 rep. Tasks are small Python modules with a real bug
and a pytest that fails until it is fixed (inverted parity check, true division where
floor division was meant, an inverted membership test). Grading is the pytest exit
code — never what the agent says about itself.

| arm | what it carries |
|---|---|
| `control` | nothing |
| `candidate` | the `swe-patch-probe` skill body, delivered as `AGENTS.md` |
| `placebo` | an `AGENTS.md` of comparable length carrying **irrelevant** style guidance |
| `aa_sham` | byte-identical to `control` — the noise floor |

## Result

```
arm                 pairs  help  harm  null       p  verdict
------------------------------------------------------------
candidate               3     3     0     0   0.250  UNDERPOWERED
placebo                 3     2     0     1   0.500  UNDERPOWERED
aa_sham (floor)         3     0     0     3       —  UNDERPOWERED
```

Two things happened, and the second is why the pilot was worth running.

**The harness refused a clean sweep.** The candidate arm went 3–0 against control.
With three discordant pairs all pointing one way, the smallest achievable exact
p-value is 2 × 0.5³ = 0.25 — significance is arithmetically unreachable at this size,
however good the sweep looks. Meanwhile the A/A floor showed **zero** discordant
pairs, so these runs are deterministic and the 3–0 is a real difference between arms
rather than sampling noise. A clean-looking result is exactly when a harness earns
its keep.

**The placebo arm ate most of the effect.** An `AGENTS.md` of similar length telling
the agent to prefer descriptive variable names and group its imports — guidance with
no bearing on any of the bugs — recovered **2 of the 3 wins**. So the honest reading
is not "the skill works". It is:

> Most of what looked like a skill effect is the effect of *any* instruction document
> arriving through that channel. What remains specific to this skill is one task's
> difference at n = 3, which is nothing.

Without the placebo arm the write-up would have read "candidate 3–0, skill validated".
It would have been wrong, it would have looked rigorous, and the A/A floor alone would
not have caught it — a floor rules out noise, not confounds.

Still missing: a `raw_trajectory` arm. There is no trace store to retrieve from yet,
and published work reports that baseline can beat a distilled skill, so no positive
result here is meaningful until it runs.

## The defect that got through

The four bugs below were caught *before* the pilot ran. This one was not, and it
invalidated the result.

The prompt told the agent to run `{PY} -m pytest -q` with `PY` interpolated as an
absolute path into a different project. That path is the only directory named anywhere
in the instructions, and this model treated it as the project root:

```
! permission requested: external_directory (/Users/loki/Desktop/euthyna/*); auto-rejecting
✗ Read /Users/loki/Desktop/euthyna/test_task.py failed
Error: The user rejected permission to use this specific tool call.
```

The same task, same model, same harness, with the interpreter reaching the agent
through `PATH` instead of through the prompt, is solved in four steps on the first
attempt.

### The ledger shows the confound directly

Reconstructing all twelve runs from the gateway ledger by session. Arm totals match
[MEASUREMENTS.md](MEASUREMENTS.md) exactly — candidate 177,135 and placebo 158,534 —
so this is the same data the original write-up used:

| arm | `AGENTS.md` | calls per run | prompt tokens | solved |
|---|---|---|---|---|
| `control` | **no** | 2, 30, 2 | 297,307 | **0 / 3** |
| `aa_sham` | **no** | 2, 2, 2 | 27,966 | **0 / 3** |
| `placebo` | yes (irrelevant) | 2, 11, 7 | 158,534 | 2 / 3 |
| `candidate` | yes (the skill) | 7, 7, 8 | 177,135 | 3 / 3 |

A 2-call run at ~9,320 tokens is the signature of the failure above: read the prompt,
try the foreign directory, get refused, stop. **All six runs without an `AGENTS.md`
failed. Five of the six with one succeeded**, whatever the file said — Fisher exact
two-sided **p = 0.0152**, a cleaner separation than any effect the pilot attributed to
the skill.

The one control run that did not give up immediately thrashed to 30 calls and 278,661
tokens against the directory it could not reach. That run is the whole of the "control
burned 120k more tokens and solved nothing" finding in MEASUREMENTS.md §3.

### Why the placebo arm did not catch it

The placebo was designed to answer "does *any* document help, or this one?" — and it
did its job, recovering 2 of the 3 wins. But both it and the candidate differ from the
controls in **two** ways at once: content, and the existence of the file. A placebo
controls the first. Nothing in the design controlled the second, because nothing in the
design knew file presence could matter.

The general form, which is the part worth keeping:

> An intervention delivered as a file changes the workspace, not just the prompt. The
> container is a variable even when it is meant to be a wrapper.

### Rules this adds to the harness

- No absolute path outside the workspace may appear in an agent prompt. Tooling reaches
  the agent through the environment.
- Any arm delivering a document must be paired with an arm delivering an inert document
  of the same shape — and the **control** must be checked for whether it can perform
  the task at all before any arm is compared to it. That check is now
  `euthyna experiment calibrate`, and it returns `EXCLUDE_NEVER_SOLVED` for all three
  of this pilot's tasks.

## Four ways this pilot silently produced garbage before the controls caught it

Every one of these would have yielded a confident, publishable-looking, wrong number.

1. **The fixtures were not broken.** A shell heredoc wrote `== 0` where `== 1` was
   intended, so all three tasks passed before any agent touched them. Every arm would
   have scored 100%. Caught by asserting each fixture fails at build time.
2. **Cross-workspace contamination.** The agent, rooted above its own directory, edited
   the *pristine fixture* instead of its copy — so later runs found the task already
   solved. Caught by a pre-flight check on every run: if the task passes before the
   agent starts, the cell is void.
3. **`cwd` is not `PWD`.** `subprocess(cwd=…)` changes the process directory but leaves
   the `PWD` environment variable inherited from the parent shell, and the agent
   resolves its project root from `PWD`. Every run was editing the launcher's
   directory. Caught by the same pre-flight check, fixed by pinning `PWD`.
4. **The agent deleted the test file.** `pytest` reports "no tests collected" with a
   non-zero exit — indistinguishable from a failure. Fixed by having the grader own
   the test: a pristine copy is written in immediately before grading.

Plus one that only cost time: the agent hangs until timeout on an inherited stdin;
`stdin=DEVNULL` turns a 600 s hang into a 45 s run.

## What this pilot establishes

Nothing about skills — the original conclusion, and still the right one.

It does not establish that the instrument works. The instrument reported exactly what
it was given and gave no indication that what it was given was meaningless. Five
controls could not see a sixth confound, and the sixth was the one that mattered.

What it establishes is narrower and less comfortable: **a well-controlled experiment on
a broken harness produces a well-controlled wrong answer.** The A/A floor showed zero
discordant pairs — read at the time as "these runs are deterministic", which was true,
and taken as reassurance, which it was not. Determinism is not validity. A harness can
fail identically every time.

The one control that would have caught this is the one the pilot did not have: checking
that the baseline can solve the task at all. Six baseline runs solved nothing, and
nothing in the design treated that as a reason to stop. It is now
`euthyna experiment calibrate`, and it refuses this pilot outright.

## Reproducing

`euthyna experiment plan|analyze` are in the repository; the runner is
workload-specific and lives outside it. Spec, plan, outcomes and the analysis output
are in this directory.
