# Changelog

## [Unreleased]

### Added
- **Step cost with the compounding term** (RFC-002 layer 1, S3).
  `c_step = 1.0*uncached + 0.10*cached + 1.25*cache_creation + 5.0*output`, applying
  the provider-published multipliers to the frozen H1 estimand. `euthyna report` now
  prices a step and, separately, what eliminating one actually saves — the step's own
  cost plus the 0.10x re-read every later turn would have paid for the tokens it added.
  Context growth is the observed prompt delta between consecutive calls, never an
  assumed value. This turns "the headroom is in steps, not prompt tokens" into an
  audited quantity.
- **Prefix-mutation ledger** (RFC-002 layer 1, S1). The gateway now watches the two
  cache-critical request segments — `tools[]` and `system` — plus the model id, and
  records every mid-session change as a `prefix_mutation` row field: which segments
  changed, which tools were added/removed by name, and the marginal re-write cost at
  1.15x (cache-write 1.25x minus cache-read 0.10x). The cost is priced from the
  previous call's **observed** `prompt_tokens`; when the provider did not report them
  it is `null` with `cost_basis: "unavailable"` — an unmeasurable mutation is never
  given an invented size. A cache miss on an *unmutated* prefix is recorded separately
  as `cache_miss_unexplained` (TTL expiry or provider-side eviction), so self-inflicted
  and provider-side cache losses are never conflated. `euthyna report` summarises both.


## [0.1.1] — 2026-07-25

Contract and privacy hardening; no behavior change to the proxied traffic.

### Fixed
- **Unknown cache no longer renders as zero.** Cost rows now carry a three-state
  `cache_status` (observed / imputed_zero / unavailable) derived at the ledger
  boundary; `report`, `/euthyna/stats`, and aggregation show `—`/null for
  unavailable instead of summing a fabricated 0, and each row carries
  `cost_quality` (exact / estimated_under_no_cache_assumption / unavailable).
- **Malformed request bodies are still ledgered.** Request-body parsing moved
  out of the fail-open observation call; a bad body records
  `request_parse_error` on a full ledger row instead of silently dropping it.

### Changed
- `euthyna submit` privacy is now allowlist-shaped: rows are projected through
  an explicit schema (unknown fields dropped, never copied); message hashes are
  re-keyed with a per-submission random HMAC salt (discarded after packaging);
  model names are pseudonymized by default (`--include-model-names` opts in);
  free-text `cost_error` becomes a closed enum. Submission schema v2.
- `euthyna analyze` re-maps session ids to `s001…` before anything is sent to
  the advisor endpoint, and is now labeled everywhere as an **experimental
  narrative advisor** whose judgment quality is not validated (per our own
  benchmark, docs/benchmarks/serving-b).


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
