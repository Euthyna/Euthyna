# What the pilot's ledger says about our own cost model — 2026-07-29

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

## 3. Hold cost is not the binding constraint — step count is

| task | control | candidate | ratio |
|---|---|---|---|
| fizz | 2 calls / 9,318 tok (failed) | 7 calls / 55,831 tok (solved) | 5.99× |
| sumdig | **30 calls / 278,661 tok (failed)** | 7 calls / 56,083 tok (solved) | **0.20×** |
| dedupe | 2 calls / 9,320 tok (failed) | 8 calls / 65,221 tok (solved) | 7.00× |

The document's footprint is **2.4%** of a candidate session. The spread between runs
of the *same task* is up to **30×**. RFC-002 spends its care on a ≤500-token body cap
and a break-even in steps; at these session lengths the body is rounding error and
**the whole result is decided by how many steps the agent takes**.

Two shapes of failure show up, and they cost three orders of magnitude apart: the
agent gives up at call two (9.3k tokens), or it thrashes to the cap (278k tokens on
sumdig — thirty calls, still unsolved). A cost model built around what sits in the
context cannot see either of them.

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
