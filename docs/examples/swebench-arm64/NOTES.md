# What 28 SWE-bench instances measured — 2026-07-30

`SWE-Lego-Qwen3-8B` (42.2% Pass@1 on SWE-bench Verified, via OpenHands) run through
mini-SWE-agent against arm64 containers, every call through the gateway. Protocol and its
caveats: [swebench50/NOTES.md](../swebench50/NOTES.md).

**The headline is not the resolve rate. It is that 68% of everything spent went into
repeating the same command.**

## Outcomes

| exit status | count |
|---|---|
| `LimitsExceeded` (hit the 40-step budget) | 18 |
| `Submitted` | 3 |
| `RepeatedFormatError` (stopped emitting actions mid-run) | 2 |

One instance of 23 produced a non-empty patch. Whether it *resolves* needs the SWE-bench
evaluator, which has not been run — so **at most 1**, and the number is reported as
"produced a patch", not as a resolve rate.

The two `RepeatedFormatError` runs died at steps 21 and 15: under a long context this model
stops producing well-formed actions at all.

## The waste, measured

Across 35 sessions and 1,282 recorded actions:

| | |
|---|---|
| actions inside a 3+ identical-verb run (beyond the 2nd) | **797 of 1,282 — 62%** |
| token-equivalents spent on them | **7,297,871 of 10,791,323 — 68%** |

The most frequent flows in the entire corpus are degenerate:

```
('cd',   'cd',   'cd')     316 occurrences across 19 sessions
('grep', 'grep', 'grep')   232 occurrences across 22 sessions
('find', 'find', 'find')    75 occurrences across 12 sessions
('mkdir','mkdir','mkdir')   68 occurrences across  3 sessions
```

The `cd` loops are the clearest: mini-SWE-agent executes every command in a **fresh
subshell**, so `cd` never persists — and `swebench_xml.yaml:83` says so explicitly. The
model is told the rule and loops on it anyway. This is what out-of-distribution looks like
in practice: a model that scores 42.2% in its native harness does not merely score lower
elsewhere, it degenerates.

**Raising the step limit would buy more loop iterations, not more solutions.**

## The apparent ritual does not survive inspection

At first reading the corpus looks like it contains a genuine localization ritual:

```
('find', 'grep', 'grep')    21 occurrences across 15 of 35 sessions
```

It does not. Classifying each occurrence by whether any of its three positions sits inside
a run of 3+ identical verbs:

| 3-gram | total | **healthy** | inside a loop |
|---|---|---|---|
| `(find, grep, grep)` | 24 | **5** | 19 |
| `(find, find, grep)` | 12 | **3** | 9 |
| `(grep, grep, grep)` | 252 | **0** | 252 |
| `(cd, cd, cd)` | 325 | **0** | 325 |

The best candidate is **79% an artifact of thrashing**, and five clean occurrences across
an entire 28-instance corpus is not a flow — it is noise with a shape.

`swe-localize-symbol`'s exact signature, `(grep, grep, grep)`, occurs **252 times and not
once outside a loop**. Whether we keep its current key or re-mine it against this
vocabulary, it fires only during pathology. For this workload that skill is not
mis-keyed; it is unmineable.

**So this corpus cannot support re-distillation.** That is the answer pass 1 existed to
produce, and it is worth more than a resolve rate would have been: the plan was to harvest
successful trajectories and distil skills from their recurring rituals, and the measurement
says the recurring patterns here are overwhelmingly failure, not ritual.

The single non-empty patch is the exception that shows what a productive trajectory looks
like:

```
find find find ls grep grep grep grep grep grep grep sed grep sed sed grep mkdir find grep sed sed echo
```

Even it opens with seven consecutive greps — but the tail is a real edit-verify loop,
`sed grep sed sed grep`, which is roughly what `swe-patch-probe` compiles. It occurred in
exactly one run out of 28, so it is an observation, not evidence.

## The shipped skill, for the record

Excluding pure repetition, the strongest recurring flow is:

```
('find', 'grep', 'grep')    21 occurrences across 15 of 35 sessions
('find', 'find', 'grep')    10 occurrences across 10 sessions
```

A genuine localization ritual — locate candidate files, then narrow twice — present in
nearly half of all runs. `swe-localize-symbol` compiles exactly this idea and its signature
is `[bash:grep, bash:grep, bash:grep]`: **mined from a different model's traces, and keyed
one verb off from what this workload actually does.**

## A failure mode worse than a dead trigger

Against this corpus the vocabulary finally matches, and `dead_triggers` reports **0 of 3**
— every shipped skill is live. That is not the good news it looks like.

`swe-localize-symbol`'s trigger would fire **272 times across 37 sessions, and 195 of those
(72%) land inside a 5-long identical-verb run** — the skill gets presented while the agent
is stuck grepping in circles, which is precisely when a 3-step localization shortcut cannot
help. Its economics were computed for a healthy three-step ritual; it would instead be
offered, and charged for, in the middle of a pathology.

> A trigger that never fires wastes nothing. A trigger that fires *during* the pathology it
> cannot fix is charged for every time.

The registry cannot tell these apart, because a signature is a sequence of action names and
has no notion of whether the flow is making progress. Three identical greps that narrow a
search and three identical greps that are a stuck loop are the same string.

**So a signature needs a progress predicate, not just an action pattern.** That is a design
gap in RFC-002 §6, and it was invisible until a real corpus contained both cases.

## What this says about the next step

The corpus is rich but the interventions it suggests are inverted from the plan. A skill
compressing a 3-step ritual competes for a few percent. A guard that interrupts a
same-verb run once it stops making progress is competing for **68%**.

That is a different kind of intervention — waste elimination rather than ritual compression
— and the cost-primary harness measures it the same way, on tasks where the outcome is held
constant.
