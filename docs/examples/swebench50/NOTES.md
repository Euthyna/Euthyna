# SWE-bench arm64 — pass 1 protocol — 2026-07-29

> **Amended after standing the environment up.** The subset is **28**, not 50, and the
> reason is architectural rather than scientific — see
> [§ Why 28](#why-28-and-what-that-costs). The runner is
> [`swebench-arm64.sh`](swebench-arm64.sh); `swebench50.sh` is kept for the x86_64 path.

Everything needed to run the 50-instance SWE-bench Verified subset through
mini-SWE-agent with the gateway in the loop. **Nothing here has been run yet**; it is
committed because the preflight encodes requirements that cost real time to discover, and
because a protocol written after seeing results is not a protocol.

## Why this experiment

The [cost-primary run](../cost-primary/NOTES.md) measured a skill on tasks solvable in 7
calls and found it saved nothing — it could not, because a skill that compresses a
6-step ritual has nothing to compress in a 7-step trajectory containing no ritual. Real
repository work has 20–50 step trajectories with genuine repeated rituals. That is where
the question can be asked at all.

It also fixes the vocabulary problem for free: mini-SWE-agent's tool is
`bash(command=...)`, so the tap emits `bash:<verb>` — the vocabulary the shipped
signatures already speak, verified in
[harness-vocabulary](../harness-vocabulary/NOTES.md).

## Design

**Sequential, not all-in.** Pass 1 is one rep over 50 instances, to learn three things
before committing more compute: the quantized resolve rate, the real action vocabulary,
and whether repeated ritual n-grams exist. Only instances that resolve are worth further
reps ([RFC-002 §5.1](../../rfcs/RFC-002-skill-economics.md)).

**The subset is inherited, not sampled.** These 50 ids come from the research
programme's own config, spread over 10 repositories. Whatever selected them selected
them — **any resolve rate here describes this subset, not SWE-bench Verified.**

**Contamination is tolerable here and only here.** The goal is harvesting successful
trajectories for distillation, not estimating capability. If the model saw these
instances in training, the resolve rate goes up, which serves the goal. The cost is that
**the resolve rate must never be reported as a capability result.**

## Why 28, and what that costs

SWE-bench publishes `sweb.eval.x86_64.*` images and mini-SWE-agent defaults to them. This
host is arm64, and x86_64 emulation was **measured at 17.6× overhead** — 0.07 s native
against 1.23 s emulated on CPU-bound Python. At that rate the run is roughly 100 hours,
which is not a run.

`sweb.eval.arm64.*` images exist for **28 of the 50**. mini-SWE-agent honours
`instance["image_name"]` before its x86_64 default and `--subset` accepts a dataset path,
so a local 28-row dataset carrying arm64 names fixes it with **no fork**.

The filtering now compounds, and this is the honest accounting:

```
500  SWE-bench Verified
 50  the research programme's own subset      (non-random, selection criteria unknown)
 28  arm64 image published                    (an accident of what SWE-bench built)
```

Two non-random filters, the second having nothing to do with task difficulty but no reason
to be independent of it either. **Any resolve rate from this describes the 28 and nothing
else.** That is tolerable only because the goal is harvesting successful trajectories for
distillation rather than estimating capability — and it is the second reason, after
possible contamination, that the resolve rate must never be reported as a capability
result.

Diversity survives: 9 repositories (sympy 6, sphinx 5, pylint 5, pytest 3, django 3,
astropy 3, scikit-learn 1, requests 1, flask 1). Lost entirely: xarray (6) and most of
scikit-learn (5).

## The RAM budget, which set the context window

Three things want the same 24 GB: model weights, the KV cache, and a container VM.
Measured, not guessed:

| | |
|---|---|
| Metal reports | 25.8 GB total, 12.0 GB available |
| KV budget at `VLLM_METAL_MEMORY_FRACTION=auto` (0.90) | **11.91 GB** (80,784 tokens) |
| KV budget at `0.60` | **6.19 GB** (41,952 tokens) |
| free after the change | 6.7 GB → **9.5 GB** |

`--max-model-len` does not size the cache; `usable_metal × fraction − model − overhead`
does. Capping the fraction is what makes room for containers.

So the preflight's context threshold moved from 65,536 to **40,960** — the model's native
pre-YaRN window. It moved because a measurement forced it, not to make the check pass, and
the compensating control is capping a single observation at 20,000 chars
(`agent.max_observation_length`, down from mini-SWE-agent's 100,000) so one file read cannot
consume 60% of the window in a single step. That cap is itself a risk to resolve rate, and
it is a forced trade rather than a tuned one.

## Preflight

Twelve checks, each corresponding to something that actually broke or to a measured
limit. Current state:

```
[PASS] gateway reachable · observing · routed · cost tracking ignore_errors
[PASS] mini-extra present · instance list is 50 · actions tap recording (174/892 calls)
[PASS] observed vocabulary is bash-shaped
[FAIL] context window >= 65,536 — serving 16,384
[FAIL] container runtime available — neither docker nor podman
[WARN] serving mlx-community/Qwen3-8B-4bit, not the SWE-tuned model
```

The two failures are environment decisions, not code:

- **Context window.** A toy task overran 16,384 *after* solving. Real observations are
  whole-file reads and test output; 16,384 guarantees truncation.
  `SWE-Lego-Qwen3-8B` supports 163,840, so Serving-A needs relaunching with a much
  larger window.
- **Containers.** SWE-bench needs one per instance. Nothing else in the pipeline does.

`--preflight-only` runs the checks without starting anything.

## The model

`SWE-Lego/SWE-Lego-Qwen3-8B` — 42.2% Pass@1 on SWE-bench Verified, Apache-2.0, SFT from
Qwen3-8B with no expert-model calls at inference. Converted locally to MLX **8-bit**
(8.1 GB, 15.4 tok/s) and **4-bit** (4.3 GB, 27.9 tok/s); both kept so the
quality-versus-speed choice can be made on measured resolve rate instead of a guess.

Its `config.json` ships `max_position_embeddings: 163840.0` — a float where transformers
requires an int, which aborts conversion. Worked around with a symlinked source directory
carrying a patched config, rather than mutating the content-addressed HF cache.

**It was trained on OpenHands trajectories, not mini-SWE-agent.** Running it under a
bash-only harness is out of distribution and the 42.2% may not survive. That is the first
thing pass 1 measures, and the reason pass 1 exists.

## Two things that will not be assumed

- **Parallel workers break window-based cost attribution.** `window_costs` needs disjoint
  `[started_at, ended_at]` per run. With `--workers > 1` only prefix-chaining separates
  sessions — which it does — but cost then has to be keyed on session id, not the clock.
  The runner warns when workers > 1.
- **Format errors are billed steps.** On Qwen3-8B-4bit one 5-step run emitted valid tool
  calls on 2 of 5 calls; the rest were format errors, re-prompted. They appear in the
  ledger as `actions: []` — read fine, called nothing — and they cost money. Budget for
  them rather than discovering them in the totals.
