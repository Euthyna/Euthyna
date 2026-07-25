# Flow mining (Stage 0 / Stage 1)

`euthyna mine` is the **perception half** of the v0.2 roadmap item
*evidence-gated flow compilation*. It answers a descriptive question only:

> Which multi-step agent behaviors **recur** across sessions, and how much token
> volume do they account for?

It does **not** compile skills (Stage 2), and it makes **no efficacy/savings
claims** (Stage 3 A/B read-out with an A/A floor only). Amortization figures are
conservative byte-weight **upper bounds**, never predicted savings.

## What it does

Deterministic, no LLM, no network, stdlib only. Given a config of corpora it
mines every *repeated static flow* — a contiguous ≥3-step subsequence whose
signature recurs ≥3× across ≥2 distinct sessions — at three signature levels,
then classifies the flows into a data-driven taxonomy.

- **L0 exact** — n-gram over per-step content hashes (byte-identical steps).
- **L1 structural** — sequence of (role, tool), arguments stripped.
- **L2 template** — (tool, normalized argument shape) with literals slotted
  (`<path>`, `<num>`, `<content>`, `<str>`, …).

## Privacy contract

Only **structure** leaves the miner: signatures, hashes, tool names, normalized
argument *shapes*, counts, and positional refs. No raw path, command value, or
file content is ever emitted — normalization slots every literal before anything
is written. Euthyna live traces are mined on the provided `message_sha256`
sequences (**hash-only; hashes are never reversed**). This mirrors the gateway's
metadata-only trace contract.

## Usage

```bash
# 1. describe your corpora (corpus -> {glob, mode|adapter})
cat > corpora.json <<'JSON'
{
  "miniswe":  {"glob": "~/traces/miniswe/*.jsonl",   "adapter": "miniswe"},
  "openhands":{"glob": "~/traces/openhands/*.jsonl", "adapter": "openhands"},
  "euthyna":  {"glob": "~/.euthyna/traces/*.jsonl",  "mode": "hash_only"}
}
JSON

# 2. (optional) verify record schemas before trusting output
euthyna mine --config corpora.json --out out --inspect

# 3. mine + classify
euthyna mine --config corpora.json --out out --classify
```

Outputs (all structure-only):

| file | contents |
|---|---|
| `candidates.jsonl` | one record per candidate flow (see schema below) |
| `candidates_classified.jsonl` | + taxonomy label, parameter slots, skill sketch |
| `flows_report.md` | per-corpus stats + ranked top-10 table |

Adapters: `miniswe` (mini-swe-agent THOUGHT/ACTION bash), `openhands`
(OpenHands action/observation events), `magagent`/`taubench` for the
corresponding public trace shapes, and `mode: hash_only` for Euthyna traces.

## Amortization is a bound, not a saving

`est_tokens_per_occurrence` = median step bytes / 4 (model-agnostic proxy).
`est_amortizable_tokens` (conservative) = per_occ × (occurrences − 1) — only the
*repeats* after the first amortize. `est_amortizable_tokens_upper` = total
bytes / 4. Unknown byte counts → `null`, never estimated silently.

This number is the **ceiling** a perfect distillation could remove — it says
nothing about whether a flow *can* be compiled, what the compiled skill costs,
or what an A/B would actually measure. Keeping it conservative is what keeps
Stage 2 honest (its mirror-image failure mode, `PREEMPTIVE_HELPER_TOOL_BUILD`,
is paying build cost for a flow that never recurs).

## Reference run on 3 public corpora

`results/` holds a committed run over three public LMCache agent-trace corpora
(miniswe, taubench, magagent — 70 sessions, 1,619 steps). Headlines, with the
caveats that survived an adversarial methodology review
(`flows_report_stage1.md`):

- 975 raw candidate flows (one per signature level) → 333 cross-level families → 189 after excluding non-distill-target categories. `candidates.jsonl` has 975 rows (one per flow × signature level); `candidates_classified.jsonl` has 333 (the de-duplicated cross-level families).
- **Ranking is by recurrence (n_sessions), not token volume.** Ranking by
  amortizable tokens conflates step *size* with distillation *value* — magagent's
  ~5k-token ledger JSON otherwise dominates purely on byte-weight.
- **miniswe results are a 1–2-witness observation, not an established regularity**
  — every miniswe ritual sits at the n_sessions=2 floor with ~0.67 single-session
  concentration. Hypothesis-generating only.
- **taubench = SIGNAL_NOT_DETECTED** for distillation: dialog turn-taking with no
  tool structure; the repetition is conversational, not a compilable procedure.
- magagent is a single orchestrator framework (MagenticOne); its dominant flow is
  that framework's own control loop — framework-specific, not general behavior.
- The per-candidate "integrity check" (re-resolve refs, recompute signatures) is
  a **self-consistency** check, **not** precision — a real precision measure needs
  an external, falsifiable adjudicator against a negative class, and is not yet done.

Scope everything as *"among these 3 small public corpora."* No generalization to
agent behavior at large.

## Candidate record schema

```json
{"flow_id": "F001", "signature_level": "L2", "length_steps": 4,
 "occurrences": 11, "occurrences_raw_windows": 14, "n_sessions": 5,
 "corpora": ["miniswe", "openhands"], "readable_signature": "...",
 "est_tokens_per_occurrence": 3400, "est_amortizable_tokens": 34000,
 "est_amortizable_tokens_upper": 47600,
 "example_refs": ["miniswe/<session>:steps12-15", "..."],
 "label": {"name": "pytest-run-and-parse ritual", "category": "verification",
           "parameter_slots": ["test_path"], "merged_from": ["F007"]},
 "skill_sketch": "One paragraph: what a static program replacing this would do."}
```
