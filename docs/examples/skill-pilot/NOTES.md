# Paired-harness pilot — 2026-07-29

The first end-to-end run of `euthyna experiment`: plan → execute → grade → analyze,
against a local Qwen3-8B on vllm-metal, all traffic through the gateway.

Nine runs: 3 tasks × 3 arms × 1 rep. Tasks are small Python modules with a real bug
and a pytest that fails until it is fixed (inverted parity check, integer division
where floor division was meant, an inverted membership test). Grading is the pytest
exit code — never what the agent says about itself.

## Result

```
run                            resolved   wall
fizz::control::0               False       42.0s
fizz::candidate::0             True        67.0s
fizz::aa_sham::0               False       42.9s
sumdig::aa_sham::0             False       42.9s
sumdig::candidate::0           True        68.6s
sumdig::control::0             False      146.0s
dedupe::candidate::0           True        66.5s
dedupe::control::0             False       42.9s
dedupe::aa_sham::0             False       42.9s
```

```
arm                 pairs  help  harm  null       p  verdict
------------------------------------------------------------
candidate               3     3     0     0   0.250  UNDERPOWERED
aa_sham (floor)         3     0     0     3       —  UNDERPOWERED
```

**The candidate arm swept 3–0 and the harness still refuses to call it.** With three
discordant pairs all pointing one way, the smallest achievable exact p-value is
2 × 0.5³ = 0.25 — significance is arithmetically unreachable at this size, whatever
the sweep looks like. That is the instrument working: a clean-looking result is
exactly when a harness is most useful.

The A/A floor is equally informative in the other direction: **zero discordant pairs**
between two byte-identical arms. These runs are deterministic, so the 3–0 is not
sampling noise — it is a real difference between arms, just not yet an established one.

## The confound this pilot cannot rule out

The candidate arm delivers the skill as `AGENTS.md`. The control arm has no such file.
So the arms differ by *the skill* **and** by *the presence of any extra instruction at
all*. A 3–0 sweep is consistent with "this skill helps" and equally consistent with
"any additional guidance helps".

The missing arm is a **placebo**: an `AGENTS.md` of comparable length carrying
irrelevant guidance. Until that runs, the honest reading is "the candidate arm
differs from control", not "the skill works". The `raw_trajectory` arm is also absent
— there is no trace store to retrieve from yet — and published work reports that
baseline can beat a distilled skill, so a positive result without it is not meaningful.

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

Plus one that only cost time: `opencode` hangs until timeout on an inherited stdin;
`stdin=DEVNULL` turns a 600 s hang into a 45 s run.

## Reproducing

The harness is in the repository (`euthyna experiment plan|analyze`); the pilot's
runner is workload-specific and lives outside it. Spec, plan and outcomes are here.
