# Changelog

## [Unreleased]

### Added
- **Cost per solved task** in `euthyna experiment analyze`. A cheap failure is not
  cheap — its tokens bought nothing and the task still has to be done — so comparing
  per-run cost across arms with different outcomes flatters whichever arm gives up
  fastest. Cost is now reported per arm against the number of tasks it actually
  solved, and an arm that solved nothing reports **no** cost per solve rather than a
  small number. On the pilot data the control arm burned 120k more tokens than the
  candidate arm and solved nothing, while the cheapest arm in raw tokens was the A/A
  sham, which gave up fastest.

### Changed
- **Skill token estimation is now calibrated against a measurement.** Running a real
  skill document through the gateway put chars/4 **31% low** (204 observed vs 156
  estimated, stable across three sessions). Under-pricing is the direction that admits
  skills which cannot pay, so `estimate_tokens` carries the correction and a skill may
  record `measured_body_tokens` to override it outright — measured always beats
  estimated. Evidence and two further findings in
  `docs/examples/skill-pilot/MEASUREMENTS.md`, including that the document is not in
  the prefix from turn one (so the hold horizon is `R−1`), and that its footprint is
  2.4% of a session while step count varies up to 30× on the same task.

### Added
- **Paired A/B harness** (RFC-002 layer 2) — `euthyna experiment plan|analyze`.
  `plan` turns a spec into a reproducible randomised run list (seeded Fisher-Yates
  over stratified permuted blocks) and adds two arms unless declined: an **A/A sham**
  whose discordant rate is the noise floor, and a **raw-trajectory** baseline, since
  published work reports that retrieving the raw trace can beat retrieving its
  distillate. `analyze` pairs outcomes on identical (task, rep) cells, runs an **exact
  McNemar** test (stdlib binomial — the chi-square approximation is not trustworthy at
  affordable sample sizes), joins per-run cost from the ledger, and reports
  **help/harm/null counts rather than a mean**, which would hide runs moving in
  opposite directions. An arm at or below the A/A floor is reported `WITHIN_NOISE`
  whatever its p-value. Planning defaults come from the published paired split and
  reproduce RFC-002's ~650-run figure.
- **Signature-keyed skill registry with per-skill economics** (RFC-002 layers 1 and 3).
  `euthyna skills` loads SKILL.md-style files, matches them by exact flow signature
  (suffix of the recent action window — no embedding index below the sizes where
  retrieval is warranted), and prices every entry: hold cost
  (`1.25*body + 0.10*body*turns`), net steps saved (ritual − 1, because invoking the
  skill is itself a step), and the break-even it must clear at published paired rates.
  Gates from RFC-002 §8 are enforced, each citing its measurement. Ships three skills
  distilled from 20 real mini-SWE-agent sessions, each naming the corpus it came from.
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
