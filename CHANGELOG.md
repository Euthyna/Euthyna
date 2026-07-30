# Changelog

## [Unreleased]

### Fixed
- **Command arguments could leak into the ledger through an env-assignment prefix.** The
  action tap kept the first whitespace token of a shell command as the verb, so
  `AWS_SECRET_ACCESS_KEY=... grep foo .` recorded the *assignment*, secret included. Not
  hypothetical: mini-swe-agent's own prompt template instructs the agent to write
  `MY_ENV_VAR=MY_VALUE cd /path && ...`. Also leaked when the whole command was a single
  token with no spaces (a URL with a query token, a base64 blob).
  Leading `VAR=VALUE` prefixes are now skipped to find the real verb, and the verb must
  match an **allowlist** shape — at most 16 characters and containing a lowercase letter,
  since command names are lowercase by convention while keys and env-var names are upper.
  Anything else records as the bare tool name: less detail, never content. A property test
  sweeps a credential across six positions in the line; it was that test, not the
  hand-picked cases, that caught a line consisting of nothing but an access key.
  Residual risk is documented in the source rather than papered over: a short all-lowercase
  high-entropy token still passes.
- **Pairs that could not be priced vanished from `compare_cost` without a count.** Both
  arms solved, but a run had no cost, so the pair was skipped — `pairs` shrank and
  `dropped_discordant` did not move, leaving no stated reason. With the overlap fix above
  this became load-bearing: every pair can go unpriced at once, and the output would have
  read `pairs: 0, dropped: 0`, indistinguishable from having no data. Now counted as
  `unpriced`, shown as its own column, and given the verdict **`UNPRICED`** rather than
  `UNDERPOWERED` — blaming the sample size for a plumbing failure sends someone to run
  more reps that cannot help.
- **`window_costs` double-counted every call shared by two overlapping run windows.**
  Window attribution assumes one call belongs to one run, which holds only for serial
  runs; with parallel workers the windows interleave and a shared call was counted in
  both, inflating every arm. One 1,050 tok-eq call attributed 2,100. `overlapping_runs`
  now names the affected runs and they are left **unpriced** so they drop out of the
  comparison, with the CLI saying so — unknown is never rendered as a number.
- **Three streaming action-parser defects**, all of which corrupt flow signatures:
  deltas that omit `index` collapsed into one slot and lost every call but the last;
  results came back in arrival order rather than index order, which mis-keys an ordered
  suffix match; and a reused Anthropic `content_block` index made two distinct calls
  render as the last one twice.

### Added
- **`repetition` line in `euthyna report`** — spend sitting inside runs of the same command
  repeated until it stopped helping, charged from the third occurrence (the first two are
  the ordinary shape of narrowing a search). On a 28-instance SWE-bench corpus this is
  **62% of actions and 68% of all spend**, with a longest run of 39 identical `find` calls.
  Measured per session, never across, and rows without recorded actions are skipped rather
  than assumed innocent.
- **mini-swe-agent integration** in `docs/SETUP.md` — zero fork and, unlike opencode,
  deliberately **no session plugin**. mini-swe-agent builds its model per instance inside
  `process_instance()`, so a per-instance header would mean patching the runner, and a
  header set once per batch would collapse every instance into one session. The gateway's
  prefix-chaining handles it instead: two instances run back to back produced two distinct
  sessions with `prefix_stable_ratio` 1.0 inside each, and content-keyed grouping survives
  parallel workers that a process-scoped header would not. Documents the two measured
  gotchas — `MSWEA_COST_TRACKING=ignore_errors` (litellm aborts computing cost for a local
  model) and the context window, which a toy task overran *after* solving.
- **`euthyna skills` reports trigger reachability** against the action vocabulary
  measured from your own ledger, not an assumed one. A signature can only match a harness
  that emits those action names, so a skill mined from one harness and deployed into
  another is dead code that looks alive — `match()` cannot say so, because never-matching
  and not-yet-matching are the same observation. All three shipped skills come back DEAD
  against opencode traffic. When no vocabulary has been observed the command says
  reachability is UNKNOWN rather than treating silence as a clean bill of health.
- **`observed_vocabulary` / `action_coverage`** on the ledger, which skip rows that
  predate the actions tap and rows whose response was unreadable instead of folding them
  in as "no actions" — the same unknown-is-not-zero rule the cache fields follow.
- **`measured_steps_replaced` / `measured_in`** on a skill, with the same precedence rule
  as `measured_body_tokens`: measured beats declared. `steps_replaced` is inherited from
  the corpus a skill was mined from and travels with the file, so the economics gate would
  return PAYS on a number that was never true of the workload in front of it.
  `swe-patch-probe` declares 6 and now carries a measured **0** from the cost-primary run
  — its verdict moves PAYS → CANNOT_PAY, and the gate message names both the basis and the
  workload. A measured zero is honoured rather than read as absent.
- **`actions` on every ledger row** — the tool calls a step actually made, in order.
  `_tool_names` records the tools a request *offered*, which is what prefix-mutation
  detection needs; this records the ones the model *invoked*, which is what a flow is
  made of. Without it a signature can only be mined from whatever corpus produced a
  skill, never from the harness it is deployed into. Both dialects, streaming and not;
  fragmented streaming arguments are accumulated by index. `None` means the response was
  unreadable, `[]` means it read fine and called nothing — never conflated.
  For shell-style tools only the **first token** of the command is kept (`bash:grep`,
  not the pattern): the verb is what distinguishes one ritual from another and
  everything after it is the user's data.
- **`step_cost_quality`** — the quality of a token-equivalent step cost is not the
  quality of the bill. `cost_quality` clears a row whose cache rates equal its input
  rate, which for a local model priced at zero is every row: the dollar total is exactly
  $0 however the prompt was cached. `step_cost` weights uncached at 1.0 against cached at
  0.10 regardless, so a row can be an exact $0 and a 10x-uncertain step. Surfaced by
  `euthyna experiment analyze --window-costs`, which now reports how many calls were
  priced under a no-cache assumption instead of leaving it implicit.
- **`euthyna experiment calibrate`** — which tasks a cost experiment can be run on, with
  exact one-sided Clopper-Pearson bounds beside every point estimate, because 3/3 clean
  runs only rule out a solve rate below 0.37.
- **`baseline_check`** on every `analyze` result — refuses to be read silently when the
  control arm solves nothing (no cost comparison is possible) or everything (binary
  endpoint saturated, which is the regime a cost experiment wants).
- **`window_costs`** — cost attributed by each run's `[started_at, ended_at]` rather than
  by session id, since one agent invocation can open more than one upstream session.
- **Skew flag** on cost rows where the per-pair median and the total disagree in sign;
  the verdict follows the median.
- **Cost-primary analysis** — `compare_cost`, Wilcoxon signed-rank, surfaced by
  `euthyna experiment analyze`. On tasks the baseline already solves, the interesting
  question is not whether it worked but what it cost, and that endpoint is a paired
  continuous magnitude rather than one bit per run: **13 paired runs for 80% power
  against 650 for the binary endpoint**, fifty times cheaper. Cost is compared only on
  pairs both arms solved — discordant pairs are dropped and counted, never averaged —
  and resolve rate rides along as a non-inferiority guard, so a cost win with a quality
  regression reports `QUALITY_REGRESSED` whatever its p-value. RFC-002 §5.1.
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
