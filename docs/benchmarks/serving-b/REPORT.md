# Serving-B candidate benchmark — 2026-07-21

**Question:** can a 1B-class local model do the Serving-B job (trace metadata → waste
taxonomy labels), keeping "lightweight" as the selling point?

**Method:** 174 traces from the research corpus carrying BOTH deterministic features
(49 metrics) and adjudicated human-consensus labels. Zero-shot LLMs at temperature 0
with strict JSON output; a prior-informed prompt ablation; a classical supervised
baseline (5-fold stratified CV, out-of-fold predictions). Same input modality as
Euthyna's runtime (metadata only — annotators originally saw full trace text, so this
is deliberately the harder, privacy-default setting).

## Results

| system | parse fail | L1 acc | waste micro-F1 | waste any (bal.acc) |
|---|---|---|---|---|
| majority-class floor | — | **0.828** | 0.0 | 0.500 |
| **GBDT on features (supervised, 174 samples)** | — | 0.793 | — | **0.703** |
| Qwen3-8B zero-shot (ceiling) | 0.000 | 0.259 | 0.092 | 0.496 |
| Qwen3-8B + prior prompt | 0.000 | 0.736 | 0.123 | 0.487 |
| Qwen3-1.7B-4bit | **0.000** | 0.816 | 0.060 | 0.487 |
| Qwen3-0.6B-4bit | 0.000 | 0.132 | 0.0 | 0.500 |
| MiniCPM5-1B-MLX | 0.822 | (0.774)* | 0.077 | 0.500 |
| gemma-3-1b-it-qat-4bit | DNF | — | — | — |
| LFM2.5-1.2B-Instruct-4bit | DNF | — | — | — |

\* over the 18% of replies that parsed. DNF = could not run on vllm-metal (gemma
qat-4bit decodes garbage; LFM2.5 architecture unsupported, HTTP 500) — a stack
constraint on the candidate pool, not a verdict on those models.
Supervised per-label (GBDT): FAILED_RECOVERY bal.acc 0.79 / F1 0.67;
VERIFICATION_GAP 0.67 / 0.43; others weak (n_pos 11–25, underpowered).

## Findings

1. **Zero-shot judgment fails at every size.** Even the 8B lands below the
   majority-class floor on L1 (it over-reads error-ish features: 96/174 predicted
   ENVIRONMENT_DOMINANT vs 2 in gold) and is a coin flip on waste detection.
   A prior-informed prompt repairs L1 calibration (0.26 → 0.74) but not waste
   (0.49). Prompting is not the path to judgment here.
2. **The signal exists — supervision finds it.** A GBDT trained on the same 174
   examples reaches 0.70 balanced accuracy on "any waste?" and 0.79 on
   FAILED_RECOVERY. Judgment from metadata is learnable; it is not free.
3. **L1 workload class is not inferable from metadata** — supervised also trails the
   majority floor (and the label itself has weak inter-annotator agreement,
   α≈0.15–0.21). Drop L1 from the advisor's runtime claims.
4. **JSON discipline at 1B-class is a solved problem — by exactly one family here.**
   Qwen3-0.6B/1.7B: 0% parse failure. MiniCPM5-1B: 82% failure. On vllm-metal today
   the runnable, format-reliable small model is **Qwen3-1.7B-4bit** (~1.0 GB).

## Recommended Serving-B architecture (evidence-ordered)

- **Deterministic rules + tiny supervised classifier decide** (waste flags,
  retry-storm, prefix-health): GBDT/logreg is KB-sized — lighter than any LLM, and
  currently more accurate than an 8B.
- **The 1B narrates**: renders structured findings into the advisory prose
  (`euthyna analyze`), the part LLMs are actually good at. Default slot model:
  Qwen3-1.7B-4bit on today's evidence; swapping is one serve command.
- **LoRA is the path to "a 1B that truly does the job"**: the 2,000-trace labeled
  dataset exists for exactly this (train 1107 / val 225 / test 168). Until that
  read-out, the 1B stays annotation/prose tier — consistent with architecture v0.3
  (NOW=annotate, GATED=recommend).

## Caveats

n=174 single-seed; waste positives are sparse (11–25 per label); features are a lossy
projection of what human annotators saw. Numbers are for ranking approaches, not for
publication. The benchmark runners and raw per-example outputs are not shipped in this
repository because they depend on a not-yet-public research corpus; the summary
JSONs alongside this report are the committed evidence. Rerun instructions will
ship with the corpus.
