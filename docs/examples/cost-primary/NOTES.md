# Cost-primary experiment — does the skill save money? — 2026-07-29

The question the first pilot could not ask. That pilot ran on tasks its baseline solved
**0 of 3** times, which measures capability; it was also invalidated by a harness defect
([retraction](../skill-pilot/NOTES.md)). This one runs on tasks the baseline solves
reliably, so the outcome is held fixed and the only thing free to vary is spend.

**Answer: no. The skill costs about 2% more per run and replaces no steps.**

## Design

Tasks were **selected by measurement, not judgement**. A calibration sweep ran the
baseline alone over a five-task difficulty ladder, 3 reps each:

| task | baseline | rate | 95% lower | joint yield | verdict |
|---|---|---|---|---|---|
| `double` | 3/3 | 1.00 | 0.37 | 1.00 | **ELIGIBLE** |
| `dedupe` | 3/3 | 1.00 | 0.37 | 1.00 | **ELIGIBLE** |
| `greet` | 2/3 | 0.67 | 0.14 | 0.44 | EXCLUDE_LOW_YIELD |
| `evens` | 2/3 | 0.67 | 0.14 | 0.44 | EXCLUDE_LOW_YIELD |
| `maxof` | 1/3 | 0.33 | 0.02 | 0.11 | EXCLUDE_LOW_YIELD |

`dedupe` also appeared in the retracted pilot, where the control arm failed it — though
on a **single run**, since that pilot used one rep per task. Under the corrected harness
it solves **3/3**. Suggestive rather than decisive: 0/1 against 3/3 is Fisher p = 0.25.

Sizing came from the measured yield: 2 eligible tasks × 7 reps × 4 arms = **56 runs**,
targeting 13 usable pairs (`required_pairs_cost(d=0.8)`). All four arms went through the
corrected harness; all traffic through the gateway; grading is the pytest exit code
against a pristine test copy the agent cannot have edited.

Solve rates came out near-saturated, which is the regime a cost experiment wants:
`aa_sham` 14/14, `dedupe` 7/7, `double` 6/7, every arm ≥ 13/14.

## Result

Cost compared only on pairs **both arms solved**; discordant pairs dropped and counted.

| contrast | pairs | dropped | Δ median | Δ relative | p | verdict |
|---|---|---|---|---|---|---|
| **A/A noise floor** (sham vs control) | 13 | 1 | **+50** | −10.4% | 1.000 | NO_COST_DIFFERENCE |
| placebo vs control | 12 | 2 | +552 | −5.3% | 0.470 | NO_COST_DIFFERENCE |
| **candidate vs control** | 12 | 2 | **+1,208** | **+6.3%** | 0.092 | NO_COST_DIFFERENCE |
| **candidate vs placebo** | 12 | 2 | +346 | −4.2% | 0.380 | NO_COST_DIFFERENCE |

The A/A floor at **+50 tok-eq** is the useful anchor: run-to-run noise in the median is
essentially nothing, so the instrument is sensitive enough for the question. Against
that floor the candidate's **+1,208** is a real shift in the wrong direction, though at
p = 0.092 over 12 pairs it does not clear significance.

`candidate vs placebo` is the contrast that isolates the skill's *content* from the fact
that a document exists at all (RFC-002 §5.2). It is **+346 tok-eq, p = 0.380** —
indistinguishable from nothing.

## Why it costs more: it changed nothing

Median calls per run, from the ledger:

| arm | median calls | median prompt tokens |
|---|---|---|
| `control` | **7** | 54,825 |
| `aa_sham` | **7** | 54,912 |
| `placebo` | **7** | 55,698 |
| `candidate` | **7** | 56,025 |

**Identical.** The skill did not shorten the trajectory by a single call. And the cost
delta is almost exactly the document's own footprint: the 204-token body is present from
call 2 of 7, so 6 × 204 = **1,224 raw prompt tokens** against an observed **+1,208
tok-eq**.

So the skill was pure overhead. It was carried, it was paid for, and it did no work.

### The registry priced it as PAYS

`swe-patch-probe` declares `steps_replaced: 6`, and on that basis the economics gate
returns PAYS. That 6 was **mined from 20 mini-SWE-agent sessions** — a different harness
and a different model. In this workload the flow it keys on never occurred, so it
replaced **zero** steps.

> `steps_replaced` is an assertion inherited from the corpus a skill was distilled from,
> not a measurement in the workload it is deployed into. The gate cannot tell the
> difference, and here it passed a skill that pays for nothing.

This is the strongest practical finding in the run, and it applies to any
signature-keyed registry: a skill's economics are workload-relative, and mining
establishes only that the flow existed *somewhere*.

## What this does not establish

- **12 pairs detects d = 0.8, not d = 0.5** (which needs 32). A real saving smaller than
  large would not be visible here.
- **Every step cost is an upper bound.** All 442 calls were priced under a no-cache
  assumption: this backend never reports a cache split, so `step_cost` counts the whole
  prompt as uncached. If the backend does cache internally, the true deltas are smaller
  than reported — including the candidate's +1,208. Reported by
  `euthyna experiment analyze --window-costs` rather than left implicit.
- **This says nothing about RFC-002's hold-cost formula.** `1.25·S + 0.10·S·(R−1)`
  predicts 377 tok-eq for this body over 7 calls, against 1,208 observed — but that gap
  is exactly what an unobservable cache split produces, so the formula is *untestable*
  on this backend, not refuted. Testing it needs a provider that reports cache tokens.
- **Two tasks, both easy, one model.** The eligible set is narrow because at n = 3 the
  yield floor is coarse — achievable yields are 0, 0.11, 0.44, 1.00, so "eligible"
  effectively means "solved 3/3", whose 95% lower bound is only 0.37.
- **No `raw_trajectory` arm.** Published work reports that retrieving the raw trace can
  beat retrieving its distillate, and there is still no trace store to retrieve from.

## Bottom line

On tasks this baseline already solves, `swe-patch-probe` does not save money. It adds
roughly 2% to a 57k-token run, replaces no steps, and is statistically
indistinguishable from an inert document of similar length. The honest verdict is
`NO_COST_DIFFERENCE` with the point estimate pointing the wrong way — and the reason is
not that the skill is badly written, but that the flow it compiles does not occur in
this workload.

## Reproducing

`euthyna experiment calibrate | plan | analyze` are in the repository. Raw outcomes for
all three stages are in this directory and in
[`../skill-pilot/`](../skill-pilot/). The runner is workload-specific and lives outside
the repo.
