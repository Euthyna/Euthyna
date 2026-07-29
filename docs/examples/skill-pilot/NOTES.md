# Paired-harness pilot — 2026-07-29

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

Nothing about skills. It establishes that the instrument works, that it declines to
overclaim on a 3–0 sweep, and that a placebo arm is not optional — three of the four
arms here were controls, and two of them changed the conclusion.

## Reproducing

`euthyna experiment plan|analyze` are in the repository; the runner is
workload-specific and lives outside it. Spec, plan, outcomes and the analysis output
are in this directory.
