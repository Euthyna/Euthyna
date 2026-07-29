# What the pilot's ledger says about our own cost model — 2026-07-29

> **Partial retraction.** The pilot these numbers come from was invalidated by a harness
> defect ([NOTES.md](NOTES.md)). Sections 1 and 2 survive it: they are byte-level facts
> about token counts on the wire, and hold whether or not any run solved its task.
> **Section 3 does not.** Its cost-per-solve table compares arms whose solve rates were
> determined by whether an `AGENTS.md` file happened to exist in the workspace, so the
> "control burned 120k more tokens and solved nothing" finding is measuring the defect.
> The *methodological* point in §3 — that a cheap failure is not cheap, and that an arm
> solving nothing has no cost per solve — was arrived at independently and stands.

The pilot ([NOTES.md](NOTES.md)) was run to test a skill. Its ledger turned out to
test *us*: three assumptions in the RFC-002 economics were checkable against the wire,
and two of them were wrong.

Joined by time window to the 12 pilot runs; every number below is observed
`prompt_tokens`, never derived.

## 1. The skill document is not in the prefix from turn one

Every arm's **first** call is 598 tokens — control, candidate, placebo, sham,
identically. The document enters at call two:

| task | control call-2 | candidate call-2 | Δ | placebo call-2 | Δ |
|---|---|---|---|---|---|
| fizz | 8,720 | 8,924 | **+204** | 8,883 | +163 |
| sumdig | 8,724 | 8,926 | **+202** | 8,883 | +159 |
| dedupe | 8,722 | 8,929 | **+207** | 8,884 | +162 |

The hold-cost formula `1.25·S + 0.10·S·R` assumes the body is written into the prefix
at session start and re-read for `R` turns after. In this harness it is written at
turn two, so the correct exponent is `R − 1`. A small correction — but it was an
assumption, and now it is a measurement.

## 2. Our token estimator ran 31% low

The `swe-patch-probe` body estimates at **156** tokens under chars/4. It measured
**204**, stable to ±3 across three independent sessions. Ratio 1.31.

That direction matters: under-pricing a skill is what admits skills that cannot pay.
`estimate_tokens` now carries the correction, and any skill may override it with a
`measured_body_tokens` field — measured always beats estimated. `swe-patch-probe`
now carries its 204.

Consequence in the registry: `swe-localize-symbol`'s break-even moved 2.7 → 3.0 steps
against 2 saved. It was already CANNOT_PAY; it is now further from paying.

## 3. Hold cost is not the binding constraint — and per-run cost is not a metric

> ⚠ **The numbers in this section are retracted.** The solve rates they divide by are
> artifacts. The reasoning about *what* to divide by is not, and is why
> `cost_per_solve` exists. Read this section for the argument, not the table.

The first version of this section compared per-run token totals across arms and
reported that the candidate arm cost "5.99× more" on fizz. **That comparison is
meaningless and the ratio should never have been written down.** It set the cost of a
run that *failed* against the cost of a run that *succeeded*. A cheap failure is not
cheap: those tokens bought nothing and the task still has to be done.

The only denominator that means anything is cost per **solved** task:

| arm | solved | tokens | tokens per solve |
|---|---|---|---|
| control | **0 / 3** | 297,299 | **— nothing solved** |
| candidate | 3 / 3 | 177,135 | **59,045** |
| placebo | 2 / 3 | 158,534 | 79,267 |
| aa_sham | **0 / 3** | 27,979 | **— nothing solved** |

That inverts the picture completely. The control arm burned **120,000 more tokens
than the candidate arm and solved nothing** — one of its runs thrashed to thirty calls
and 278k tokens without a fix. And the "cheapest" arm in raw tokens is the A/A sham at
27,979, precisely because it gave up fastest.

> **The cheapest agent is the one that does nothing.** Any cost metric that ranks it
> well is measuring the wrong thing.

The document's own footprint is 2.4% of a candidate session — still rounding error, so
the original point stands: at these session lengths a ≤500-token body cap is not where
the money is. But the money is not in "steps" either. It is in **whether the run
produced anything at all**, and the two failure shapes here cost three orders of
magnitude apart: give up at call two (9.3k), or thrash to the cap (278k).

`euthyna experiment analyze` now reports cost per solve per arm, and reports an arm
that solved nothing as having *no* cost per solve rather than a flattering small
number.

## What this changes

- `estimate_tokens` carries the measured correction; skills can record a measured
  footprint that overrides it. (Shipped.)
- The hold-cost horizon should be `R − 1`, not `R`, when delivery is document-style.
  Small enough to fold into the next economics change rather than churn it now.
- **The gate that matters is not body size.** A skill that reliably prevents a
  thrash-to-cap run is worth more than one that saves five clean steps, and neither
  the current break-even nor the ≤500-token cap expresses that. This belongs in
  RFC-002 §8 as an open question rather than a silent design assumption.

None of this says anything about whether skills work. It says our cost model had two
untested assumptions in it, and the instrument found them in its first real run.
