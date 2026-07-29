# RFC-002 — Skill economics, a signature-keyed registry, and a deterministic runtime cascade

- **Status:** draft, open for comment
- **Date:** 2026-07-26
- **Scope:** Euthyna v0.2
- **Discussion:** see the RFC-002 issue

---

## 0. Summary

We are not going to build another skill library. We are going to build the **skill
economics layer** that every skill library needs and none of them has — and only then,
on top of it, a **signature-keyed** (not embedding-keyed) skill registry whose runtime
path is a deterministic cascade with a small, bounded model at the very end.

The literature is clear that skill systems fail on **selection**, not on generation.
Euthyna's unique asset is that it is the only instrument positioned to price selection
errors in dollars.

## 1. Motivation

Trace-to-skill distillation became a crowded subfield in 2026. Reading it closely
produces an uncomfortable set of numbers:

| Finding | Number | Source |
|---|---|---|
| Distillation is a compressor, and the compression is where the value lives | 200 traces → **5 skills**; ablating distillation (43 skills) drops success **99.3% → 53.0%** | Skill-DisCo, arXiv 2606.26669 |
| Skill libraries fail by **shadowing**, not context bloat | 52 skills −8%, 102 −14%, **202 −21%**; shadowing accounts for **68%** of the drop, context-overhead CI includes zero | arXiv 2605.24050 |
| Presenting more than three skills hurts | 2–3 optimal **+20.0pp**; 4+ → **+5.2pp** | SkillsBench |
| Agents have almost no need-awareness | skill-load rate differs by **+0.1pp** between natively solvable and unsolvable tasks | SRA, arXiv 2604.24594 |
| The counterfactual is mostly null | 513 paired runs: **help 13.5% / harm 8.4% / no effect 78.2%** | SelSkill |
| Generated skills frequently lose to no skill at all | ~**60%** of method × backbone combinations fall below the 13.8% no-skill baseline on repository-grounded tasks | SkillGenBench, arXiv 2605.18693 |
| **Retrieving the raw trajectory can beat retrieving its distillate** | distilled-minus-raw-retrieval "predominantly negative across models, variants, and metrics" | SkillEvolBench |
| Description-only indexing is broken | **−31 to −44pp** routing accuracy versus full-body indexing | SkillRouter, arXiv 2603.22455 |
| Small models *are* state of the art here — as rerankers | 0.6B × 0.6B reaches **74.0% Hit@1**, beating a 16B pipeline at 68.0%, in 495.8 ms | SkillRouter |
| Small models are *not* judges | on an adjacent judging task: 32B **95%** → 3B **43%** | governance literature |
| Cache-safe injection exists and is documented | deferred tools are "excluded from the system-prompt prefix… **the prefix is untouched, so prompt caching is preserved**" | Anthropic tool-search docs |
| Skills drift fast | ~**24%** of a real 49-skill sample carried a detectable drifted contract at a single snapshot | SkillGuard |

And one number of our own: flow mining over 90 real agent sessions returned
`FLOW_SIGNAL_NOT_ESTABLISHED` — a 200-permutation within-session null killed three of
our four headline numbers. **Any design here must be valuable even if that stays true.**

The gap nobody has filled: every one of those papers measures *success rate*. The
field's own survey concedes that skill evaluation "overlooks token cost and latency."
Nobody prices what a skill costs to carry.

## 2. Non-goals

- A general-purpose skill marketplace or a large curated library.
- Any in-flight, trace-conditioned steering decision. Our prior research found zero
  wins for adaptive control over the best static configuration, and this RFC does not
  re-litigate that.
- Content logging. Euthyna's default telemetry stays hash-only metadata.

## 3. Data, honestly

Euthyna's **runtime** traces are hash-only and **cannot** support distillation. Every
working system in the literature consumes `(reasoning, action, observation, outcome)`;
SkillGenBench's failure taxonomy for repository tasks is 53% runtime/dependency, 27%
interface/schema, 20% asset/artifact — categories diagnosable only from observation
text we deliberately do not store. That objection stands and we are not weakening the
privacy default to dodge it.

Distillation is therefore an **offline activity on owned or explicitly consented
corpora**, not on user telemetry. The product ships (a) the resulting skills and
(b) the economics layer.

If a user ever wants distillation over their own traffic, the mechanism is
**evidence-triggered local capture**: when a flow signature recurs ≥ k times *and*
clears a permutation null, capture that one flow's next occurrence in full — locally,
TTL-bounded, opt-in. Never a content log.

## 4. Layer 1 — the Skill Ledger (build first)

Three quantities that are true whether or not skills work, and that nobody has
published for any agent harness.

**S1 — prefix-mutation ledger.** *(shipped)* Byte-diff `tools[]`, `system`, and the
model id between consecutive calls in a session. On change, record which segments
moved, which tools were added or removed by name, and the marginal re-write cost:

```
prefix_mutation_cost_tok_eq = 1.15 × prev_prompt_tokens     # 1.25× write − 0.10× read
```

priced from the previous call's **observed** `prompt_tokens`, or `null` with
`cost_basis: "unavailable"` when the provider did not report them. A cache miss on an
*unmutated* prefix is recorded separately as `cache_miss_unexplained` — TTL expiry and
provider-side eviction must never be conflated with a self-inflicted bust, or every
future A/B misattributes its cache misses.

**S2 — skill presence cost.** For a body of `S` tokens introduced with `R` turns
remaining: `hold_cost_tok_eq = 1.25·S + 0.10·S·R`. This is the number that decides
whether a skill can ever pay for itself, and it appears in none of the work cited above.

**S3 — step cost with the compounding term.**

```
c_step = 0.10·C + 1.25·δ + 5·o                      # C context, δ new tokens, o output
second-order saving per eliminated step ≈ 0.10·δ·(R−k)       # ≈ +29% at R = 20
```

This turns "the headroom is in steps, not prompt tokens" from a slogan into an audited
quantity.

**Two open questions S1 answers immediately**, both unanswered in the literature:
(a) is a coding agent's skill roster carried in `system`, or re-injected per tool
result? (b) does tail-appending one entry to `tools[]` preserve a strict prefix on
each provider — as it provably does *not* on at least one, where dropping any tool
zeroed the entire cache including the system prompt? One request pair each.

## 5. Layer 2 — the paired harness (an instrument, not an intervention)

### 5.1 Amendment (2026-07-29) — measure cost on tasks the baseline already solves

The first pilot ran on tasks the baseline solved **0 of 3** times. On such tasks the
binary endpoint measures *capability*, and cost comparison is not merely weak but
meaningless: the cost of a run that failed is not comparable to the cost of a run that
succeeded. The pilot write-up made exactly that mistake before it was caught.

For a cost auditor the right regime is the opposite one: **tasks the baseline solves
reliably**, where the outcome is held fixed and the only thing that varies is spend.
That turns the endpoint from one bit per run into a paired continuous magnitude, and
each task becomes its own control, so between-task variance — the dominant term in
agent work — cancels.

| endpoint | test | n for 80% power |
|---|---|---|
| binary resolve | exact McNemar | **650 paired runs** |
| **paired cost** | Wilcoxon signed-rank | **13 paired runs** |

Fifty times cheaper: eleven hours of local compute becomes twenty minutes.

Consequences, all implemented:

- Cost is compared **only on pairs both arms solved**; discordant pairs are dropped and
  counted, never averaged in.
- Resolve rate is carried as a **non-inferiority guard**: a cost win with a resolve
  regression reports `QUALITY_REGRESSED` regardless of the p-value.
- Task selection acquires a criterion. Because discordant pairs are dropped rather than
  averaged, an unreliable task does not bias the estimate — it costs *pairs*. So
  reliability is a power question with a numeric answer,
  `scheduled = target / (p_a · p_b)`, and establishing it is a calibration run rather
  than an experiment. `euthyna experiment calibrate`.
- `analyze` refuses to be read silently in the bad regime: `baseline_check` reports
  `never_solves` (no cost comparison is possible) or `always_solves` (binary endpoint
  saturated — which is the regime a cost experiment *wants*).

This mirrors the guarded-lossless / loss-tolerant split from the underlying research
programme: hold quality constant and measure spend, rather than hoping to see both move
at once.

### 5.2 Amendment (2026-07-29) — the delivery channel is a variable

The pilot delivered the skill as an `AGENTS.md` file and compared it against a control
that carried nothing. Its arms therefore differed in **two** ways, not one: what the
document said, and whether a document existed. A placebo arm controls the first. Nothing
controlled the second.

The pilot's arms did separate exactly along that line — all six runs without an
`AGENTS.md` failed, five of six with one succeeded. That looked like the explanation,
and a direct test refused to confirm it: with the same broken prompt, adding an inert
`AGENTS.md` moved the solve rate from 1/3 to 2/3, Fisher exact **p = 1.0**. The
container is not the cause, and the pilot's pattern has no confirmed explanation.

Which is the point. The lesson does not rest on the container turning out to matter:

> An intervention delivered as a file changes the workspace, not just the prompt. The
> container is a variable even when it is meant to be a wrapper.

An uncontrolled variable does not have to be the cause to make a result unreadable. It
only has to be uncontrolled — after which no amount of analysis can rule it out, and the
experiment has to be rerun rather than reinterpreted. That is what happened here.

So: **an arm that adds a file must be compared against an arm that adds an inert file,
not against an arm that adds nothing.** The placebo is promoted from good practice to a
required arm whenever delivery is document-style. And the abandon criterion in §5 is
restated against the placebo, not against the empty control — `candidate ≤ placebo` is
the failure condition, because `candidate > empty control` can be satisfied by the
container alone.

Power arithmetic decides the design:

| Design | n to detect +1.2pp at 80% power |
|---|---|
| Unpaired two-proportion | **~27,300 runs per arm** |
| **Paired McNemar** (21.9% discordant, from SelSkill's 13.5/8.4/78.2) | **~665 paired runs total** |

Forty times cheaper. **Three mandatory arms:** `no-skill`,
`raw-trajectory-retrieval`, `candidate-skill`. The middle arm is not optional —
SkillEvolBench reports that it wins, which makes it the real baseline. Report
help/harm/null counts, never a mean delta.

**Abandon criterion, declared in advance:** if `candidate ≤ raw-trajectory-retrieval`
at n = 665, we ship the instrument and no skills.

## 6. Layer 3 — the registry: signature-keyed, three size tiers

A skill is distilled *from* a flow signature, so its trigger is "signature X recurred"
— exact match, zero hallucination. Semantic retrieval is for when you do not know what
you are looking for. Here, we do.

| Tier | Library size | Mechanism |
|---|---|---|
| **A — roster** | 1–12 | Every card (~70 tokens: name, one-line trigger, signature reference) sits in the session-start prefix; ≤ 840 tokens total. **No retrieval machinery at all.** At the observed yield rate this covers more than a year. |
| **B — signature-gated** | 13–50 | Cards still all in prefix; a deterministic signature matcher decides which **bodies** are eligible to be appended. Still no semantic retrieval. |
| **C — retrieval** | > 50 | Only here does a retriever earn its keep, and it must be a fine-tuned **cross-encoder** — a bi-encoder structurally cannot express query-conditional "skip" — indexed on **full bodies**, since description-only costs 31–44pp. |

**Invariants at every tier:**

- **≤ 3 skills presented per task**, regardless of library size.
- **Skill body ≤ 500 tokens.** Break-even at S = 500 is 3.7 steps saved (achievable:
  observed savings run 2–7 steps). At S = 2,000 it is 9.3 steps — structurally
  EV-negative.
- **Active library capped below 50** until we have our own shadowing measurement.
- **No new tool schemas, ever.** Skills are documents or programs delivered as text and
  executed by an existing, stable tool. This is the only provider-neutral cache-safe
  channel, and it converges with the independent recommendation to "implement dynamic
  capabilities through code generation rather than traditional function calling."

## 7. Layer 4 — the runtime cascade

```
L0  Signature match        deterministic, microseconds
    Rolling n-gram over the last k action signatures → exact registry lookup.
    No model, no hallucination. Expected to fire on ~5–10% of steps.
      ↓ hit
L1  Precondition check     deterministic, microseconds
    Skill-declared and machine-checkable: file exists / last tool result was error
    class Y / target already edited. Evaluated as code against ledger and trace state.
      ↓ 2–3 candidates remain and are genuinely ambiguous
L2  Bounded arbiter        1–2B local model, ~500 tokens of prefill, 0.2–0.5 s on CPU
    A fixed short prompt, ternary classification: use-A / use-B / use-neither.
    Not free-text judgment. Not retrieval. Not full-body reranking.
      ↓ still ambiguous
L3  Abstain                free — and correct 78.2% of the time
```

Amortised cost is 20–50 ms per step, against a 2–5 s step budget, because only 5–10%
of steps reach L2. Semantic retrieval would require full-body reranking of ~20
candidates (~32K tokens of prefill, 10–32 s on CPU); **signature keying removes that
step entirely.** This places the small model exactly where the literature supports it
(bounded classification and reranking) and away from where it collapses (free-text
judgment).

**Delivery is a measurement, not a design choice.** Harnesses differ: on one, adding a
skill mid-session provably preserves the cache; on another, any change to the skill set
mutates a tool description and busts the whole prefix; a third offers deferred tool
loading that leaves the prefix untouched. Euthyna measures which, per harness.

## 8. Go/no-go gates

These belong in the repository before implementation code is written.

| Gate | Threshold | Basis |
|---|---|---|
| Skill body | ≤ 500 tokens; ≤ 3 presented per task | break-even 3.7 steps; SkillsBench 2–3 optimal |
| Active library | < 50 skills | shadowing onset −8pp at 52 |
| Admission | paired execution test on held-out tasks + permutation null. **Never an LLM judge; never the small model** | a naive single-prompt LLM gate scores recall 0.596 — a 40% false-accept rate |
| Prefix-mutating injection | `expected_steps_saved ≥ 1.15·P / c_step` (≈ 6–9 at 50–200K context) | cache multipliers |
| Rollback | revert if success over the three most recent tasks drops > 20% | prior skill-lifecycle work |
| Abandon | `candidate ≤ raw-trajectory-retrieval` at n = 665 | SkillEvolBench |

## 9. Build order

1. **S1 + S3** — pure gateway measurement, no new concepts; answers two open questions
   in the literature immediately. *(S1 shipped.)*
2. **S2** — needs one skill to exist; exercised with a single hand-written skill.
3. **Paired harness** — three arms, McNemar, n ≈ 665.
4. **One hand-written skill, ≤ 500 tokens**, through the harness. Human-curated is the
   only variant with a measured positive effect.
5. **Distillation on an offline corpus**, evaluated by the harness against the
   raw-trajectory-retrieval arm.
6. **Signature registry, Tier A only.** Tiers B and C are designed here but not built
   until the library actually crosses 12 and 50 skills.

Steps 1–3 are valuable independent of whether recurring flows exist, whether
distillation adds information, whether retrieval is ever needed, and whether a small
model is competent at arbitration. They are also strict prerequisites for the ambitious
version: the fine-tuned cross-encoder of Tier C needs labelled pairs that only the
paired harness can produce. **Building the instrument first costs no optionality.**

## 10. Open questions for reviewers

1. Is the ≤ 500-token body cap too aggressive for real skills? It follows from the
   hold-cost arithmetic, but if useful skills cannot be written that small, the whole
   design changes.
2. Is signature keying too brittle? It buys exactness and cheap runtime at the cost of
   generalisation to flows that differ superficially.
3. Should the abandon criterion in §5 be stricter — for example, requiring the
   candidate to beat raw-trajectory retrieval by a margin rather than merely tie?
4. Which harnesses should the delivery measurement in §7 cover first?
