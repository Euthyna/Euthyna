# Changelog

## [Unreleased]

### Added
- **`euthyna mine`** — Stage 0/1 repeated-flow miner + classifier (offline;
  deterministic, no LLM, no network). Mines *repeated static flows* (contiguous
  ≥3-step subsequences recurring ≥3× across ≥2 sessions) at three signature
  levels (L0 exact / L1 structural / L2 template with literals slotted), then
  classifies them into a data-driven taxonomy with distillation candidates. The
  perception half of the v0.2 *evidence-gated flow compilation* slot: descriptive
  only — generates no skills (Stage 2) and makes no efficacy/savings claims
  (Stage 3 A/B + A/A floor only); amortization figures are conservative
  byte-weight upper bounds. Structure-only output (signatures, hashes, arg
  *shapes*, counts); no raw trace content is emitted; Euthyna traces mined on
  `message_sha256` (hash-only, never reversed). Adapters: `miniswe`, `openhands`,
  `magagent`, `taubench`, and `mode: hash_only`. New module `euthyna/mine/`
  (does not touch `euthyna/core/`), docs in `docs/flow-mining.md`, and a
  committed reference run over 3 public LMCache corpora in
  `docs/flow-mining/results/` (with an adversarial-review caveat section).

## [0.1.0] — 2026-07-22

First public release. SIDECAR mode end to end, verified against a real agent
(opencode) on a local backend (vllm-metal, Apple Silicon).

### Added
- **Gateway** (`euthyna up`): byte-faithful bump-in-the-wire proxy for the OpenAI
  and Anthropic dialects on one port; SSE relayed as received; auth headers pass
  through untouched. All observation is fail-open. One sanctioned request mutation
  (injecting `stream_options.include_usage`), always flagged and hash-logged.
  `EUTHYNA_TRANSPARENT=1` turns the gateway into a pure pipe.
- **Ledger + traces**: per-call JSONL cost rows with native cache categories and
  observed/imputed flags (billing fields are never fabricated); metadata-only
  per-session traces (hashes, sizes, roles — no content).
- **Prefix-stability watchdog**: byte-level canonical-prefix comparison per
  session, separating client-side cache busting from provider-side eviction.
- **CLI**: `up · probe · report · doctor · analyze`. `probe` measures what a
  backend's usage payloads actually surface and writes the evidence into the
  profile; nothing is assumed.
- **opencode integration, zero fork**: custom provider + a 13-line
  `chat.headers` plugin.
- **Serving-B advisory slot** (`euthyna analyze`): metadata-only day summary to a
  small local model; advisory output only, never load-bearing. Model choice is
  benchmarked in `docs/benchmarks/serving-b/REPORT.md`.
- **Frontier-API placeholders**: both the backend and the advisor accept any
  OpenAI/Anthropic-dialect endpoint; API keys are referenced by env-var name only.
- **Core accounting library** ported rename-only from the arcp research SDK
  (see PROVENANCE.md).

### Known limitations
- The Anthropic dialect (`/v1/messages`) is mock-tested, not yet verified against
  a live endpoint.
- vllm-metal does not surface `cached_tokens`; profiles record this honestly and
  probe latency serves as side evidence.
- HARNESS mode (Euthyna owns the loop: calibrate/experiment) is designed but not
  yet implemented.
