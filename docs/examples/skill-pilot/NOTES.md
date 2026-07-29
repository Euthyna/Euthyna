# Paired-harness pilot — 2026-07-29

> ## ⚠ RETRACTED, same day
>
> **This pilot's harness misdirects the agent, so nothing below can be read as a result.**
> The run prompt interpolated an absolute path to a directory *outside* the workspace
> (`/Users/loki/Desktop/euthyna/.venv/bin/python`). Qwen3-8B takes that for the project
> root: it tries to open `test_task.py` there, opencode's external-directory guard
> refuses it, and the run ends having edited nothing.
>
> Two things invalidate this pilot, and neither is the one first proposed:
>
> 1. **The harness misdirects the agent**, demonstrably. Under the corrected harness the
>    same model solves `dedupe` — a task this pilot's control solved 0/3 — **3 of 3**.
> 2. **The control arm solved 0 of 6.** Nothing was held constant, so there was nothing
>    to compare against.
>
> **Why the four arms landed 0/3, 0/3, 2/3, 3/3 remains unexplained.** The first
> explanation offered here — that an `AGENTS.md` in the workspace re-anchors the agent —
> was tested directly and **not supported**. See
> [§ What broke, and what is still unexplained](#what-broke-and-what-is-still-unexplained).
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

*The rest of this document is the original write-up, kept unedited as the record of what
was claimed. It is superseded by the retraction above; the analysis in this section is
wrong in ways the section itself could not see.*

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

> **This inference is wrong.** Three A/A pairs agreeing is not evidence of determinism;
> it is three coin flips landing the same way, which happens 25% of the time at p = 0.5.
> Nine later runs on one task returned 1/3, 2/3 and 3/3 across conditions. The runs are
> stochastic, and a zero-discordance floor at n = 3 says almost nothing.

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

## What broke, and what is still unexplained

The four bugs below were caught *before* the pilot ran. This one was not.

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

### What the ledger shows

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
try the foreign directory, get refused, stop. All six runs without an `AGENTS.md`
failed; five of the six with one succeeded, whatever the file said.

> **Correction.** An earlier version of this section reported Fisher exact p = 0.0152
> for that split and called it a confound. Two things are wrong with it. The contingency
> table was built *after* noticing the pattern in the same data that suggested it, so
> the figure is descriptive, not inferential — the exact error this document exists to
> warn about. And the hypothesis it encoded was then tested directly, and failed.

The one control run that did not give up immediately thrashed to 30 calls and 278,661
tokens against the directory it could not reach. That run is the whole of the "control
burned 120k more tokens and solved nothing" finding in MEASUREMENTS.md §3.

### The direct test, which refused to confirm it

Three conditions on one task, nine runs, the only differences being the prompt and
whether an inert `AGENTS.md` — no skill content, no mention of paths or tests — sat in
the workspace:

| condition | prompt | `AGENTS.md` | solved | wall time |
|---|---|---|---|---|
| `bare` | broken | no | 1/3 | 42, 42, 65 s |
| `anchored` | broken | yes, inert | 2/3 | 42, 63, 66 s |
| `fixed` | corrected | no | **3/3** | 56, 60, 62 s |

- **Does the file rescue the broken prompt?** `bare` 1/3 vs `anchored` 2/3, Fisher exact
  **p = 1.0**. No. The explanation this document originally gave is not supported.
- **Does removing the foreign path rescue it?** `bare` 1/3 vs `fixed` 3/3, **p = 0.40**.
  The right direction, and consistent with the transcript above, but **not significant
  at n = 3**. Pooling `double` across the calibration sweep and this diagnostic — same
  task, same model, prompt the only difference — gives corrected 6/6 against broken 3/6,
  p = 0.09. Still not established.

Wall time is cleanly bimodal with no overlap: every failure ends at **42 s**, every
success takes **56–66 s**. Failures give up; they do not thrash. That is the same shape
as the 2-call, 9,320-token runs in the ledger.

So the honest position is narrower than the first draft of this retraction:

> The defect is real and its mechanism is directly observed. Its *magnitude* is not
> established, and the arm-by-arm pattern in the pilot has no confirmed explanation. The
> pilot is invalid because its harness misdirects the agent and its control could not do
> the task — not because of any mechanism this document can name.

The design lesson survives the failed hypothesis, on grounds of experimental design
rather than evidence:

> An intervention delivered as a file changes the workspace, not just the prompt. This
> pilot could not separate the container from the content, and when the container was
> tested on its own it explained nothing either. An uncontrolled variable does not have
> to be the cause to make the result unreadable.

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
