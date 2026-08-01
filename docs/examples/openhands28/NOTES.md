# 28 SWE-bench instances under OpenHands — 2026-07-31

`SWE-Lego-Qwen3-8B-MLX-4bit` on OpenHands 0.53.0 CodeActAgent, every call through the
gateway, arm64 containers, `max_iterations=100`.

**Graded result: 6 of 28 resolved (21.4%), 95% lower bound 9.8%.**

The same 28 instances under mini-SWE-agent produced 1 non-empty patch and were never
graded, so that arm's resolve rate is unknown with an upper bound of 3.6%. This run is the
first in this project where "resolved" means the SWE-bench evaluator said so.

| resolved | |
|---|---|
| `astropy-14309` `astropy-14995` `flask-5014` | |
| `pylint-6903` `sympy-13480` `sympy-24539` | |

What the 22 non-resolved actually were — a single number hides four different failures:

| count | |
|---|---|
| 8 | empty patch: produced nothing at all |
| 9 | real patch that did not fix the target |
| 3 | edited ONLY its own scratch scripts, never a source file |
| 1 | fixed the right file, patch unusable (build artifacts, never applied) |
| 1 | ungraded / other |

## Three harness defects, each of which silently produced a wrong number

None of these announced themselves. Every one logged success.

**1. Grading reported `resolved: False` for an instance that passed every required test.**
SWE-bench's `get_logs_eval` needs both `>>>>> Start Test Output` and `>>>>> End Test
Output` in the log. OpenHands reads the log with `cat` through a 30,000-char observation
limit, and the truncation drops the HEAD — where the start marker is. Missing marker →
`found=False` → `patch_successfully_applied=False` → `resolved=False`, **regardless of the
tests**. Measured on `pylint-7277`: 30,047 chars captured, end marker present, start marker
gone, target test PASSED, verdict False. Fixed by extracting only the marked span with
`awk`. The same patch then graded True.

Left unfixed, all 28 would have graded 0, and the conclusion would have been that the model
cannot solve anything.

**2. No condenser meant the agent worked for ~34 steps and then failed for 66 more.**
`run_infer.py:815` falls back to `NoOpCondenser` unless `EVAL_CONDENSER` names one; the
`[core] enable_default_condenser` flag does not apply. History grew past the 40,960-token
window and every later call returned HTTP 400. The run **still emitted a patch**, which is
what makes it dangerous: it fails by producing plausible output. Fixed with an LLM
summarising condenser; the same instance then made 88 successful calls instead of 34 good
and 66 failing.

**3. Grading asked for an image that does not exist.** `eval_infer.py` omitted
`swebench_official_image`, so it resolved `docker.io/xingyaoww/...` while inference used
`docker.io/swebench/...` — different registry, different id format. Work that ran fine
would have failed to grade.

## What the corpus does not support

An earlier document concluded this corpus "cannot support re-distillation". That conclusion
rested on an action vocabulary in which **33.8% of commands had the wrong verb recorded**
(`cd /repo && grep ...` logged as `bash:cd`) and a grading path that reported solved
instances as unsolved. Both are fixed; the conclusion has to be re-derived rather than
inherited.

Re-derived on the corrected vocabulary, against the 4 traces verified resolved at the time:

| pattern | resolved | not | p |
|---|---|---|---|
| `read → edit → bash:python` | 4/4 | 9/18 | 0.115 |
| `edit → bash:python` | 4/4 | 11/18 | 0.263 |
| `edit` | 4/4 | 15/18 | 1.000 |

**No action-sequence pattern separates the resolved traces from the failures.** The one
suggestive signal is that resolved traces cluster tightly on edit count (3, 3, 3, 5) while
failures spread 0–21 — on four points.

## A hypothesis this run raised and then refuted

At the 22-instance mark: of the 14 instances whose repository does not use pytest, none had
resolved and **14 of 14 never invoked the correct test runner**. Reported as a mechanism
"without exception", p = 0.13.

The remaining 6 instances were all sympy — the one repository not yet measured. Two of them
resolved, **having never invoked `bin/test`**. The contingency became 4/14 vs 2/14,
p = 0.65.

The mechanism fact survives: 14/14 never found the command. The claim that finding it is
what separates success from failure does not.

## Reproducing

`docs/examples/openhands28/` holds the graded outcomes. The rig is four local patches to an
OpenHands 0.53.0 checkout (arm64 image names, `--eval-ids` on the plain path, a podman
`buildx` guard, and the two grading fixes above); the runner lives outside this repo.
