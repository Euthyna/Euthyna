<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/euthyna-logo-wordmark-dark.svg">
    <img src="docs/brand/euthyna-logo-wordmark.svg" alt="euthyna — a flat owl with coin eyes and an hourglass belly, beside the name" width="440">
  </picture>
</p>

<p align="center"><em>A local audit gateway for AI coding agents.</em><br>
Nothing in excess; know thyself.</p>

<p align="center">
  <a href="https://github.com/Euthyna/Euthyna/actions/workflows/test.yml"><img src="https://github.com/Euthyna/Euthyna/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-3.9%E2%80%933.14-blue" alt="Python 3.9–3.14">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0">
</p>

---

Euthyna sits between your agent (opencode, Claude Code, OpenHands, …) and your
model backend as a bump-in-the-wire proxy, and answers three questions the agent
itself never will:

1. **What did this task actually cost?** Task-total dollars with native cache
   categories (cached / uncached / output), never fabricated: every billing field
   is flagged *observed* or *imputed*.
2. **Is the agent loop healthy?** A byte-level prefix-stability watchdog catches
   cache-busting context rewrites — the single biggest silent cost multiplier in
   cached agent loops — and separates client-side cache busts from provider-side
   eviction.
3. **What should change?** Evidence-gated advice only. Out of the box Euthyna
   alters nothing the model sees; interventions require evidence, experiments
   require consent.

*Euthyna (εὔθυνα): the accounting audit every Athenian official underwent on
leaving office.*

## Quickstart

Developer smoke test — no GPU, no model, no network:

```bash
git clone https://github.com/Euthyna/Euthyna.git && cd Euthyna
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest                    # mock-backed suite
```

(`uv venv && uv pip install -e ".[test]"` works too.)

Run the gateway — needs an OpenAI-dialect backend already serving (vLLM,
vllm-metal, or a cloud endpoint):

```bash
euthyna probe --base-url http://127.0.0.1:8000 --name my-backend  # measures, writes profiles/my-backend.yaml
euthyna up --profile profiles/my-backend.yaml                     # gateway on :4517, stays in the foreground
```

Point your agent at `http://127.0.0.1:4517/v1` instead of the backend, run a
task, then in another terminal:

```bash
euthyna report      # per-session calls, tokens, cache ratio, $, prefix stability
euthyna doctor      # preflight: backend → gateway → host wiring
```

Full walkthrough incl. opencode + vllm-metal on Apple Silicon:
**[docs/SETUP.md](docs/SETUP.md)**.

## How it works

```
agent (opencode, …)
      │  baseURL → 127.0.0.1:4517
      ▼
┌───────────────────────────────┐
│  euthyna gateway (data plane) │  byte-faithful proxy: /v1/chat/completions · /v1/messages
│  taps: ledger · trace ·       │  SSE relayed as received; auth headers untouched
│        prefix watchdog        │  every tap fail-open: observation can die, the pipe cannot
└───────────────┬───────────────┘
                ▼
   model backend (vllm, vllm-metal, any OpenAI/Anthropic dialect)
```

- **Ledger** — one JSONL row per call in `~/.euthyna/ledger/YYYY-MM-DD.jsonl`:
  raw provider usage, cost row with observed/imputed flags, prefix-stability
  ratio.
- **Traces** — metadata only (`~/.euthyna/traces/<session>.jsonl`): hashes,
  sizes, roles. Message content is never stored. Nothing ever leaves your
  machine. All state lives under `~/.euthyna`; override with `EUTHYNA_HOME`.
- **Profiles** — `euthyna probe` measures what a backend's usage payloads
  actually surface and writes the evidence into `profiles/<name>.yaml`. Nothing
  is assumed.
- **Serving-B slot** — `euthyna analyze` feeds the day's *metadata* to an
  advisor model (default: a small local model on a second port) which annotates
  waste and recommends static config changes. Advisory only; it never touches
  the request path.
- **Local by default, frontier by choice** — both the backend and the advisor
  accept any OpenAI/Anthropic-dialect endpoint (`profiles/*.example.yaml`); API
  keys are referenced by env-var name only and never stored.

The one mutation the gateway is allowed: injecting `stream_options.include_usage`
into streaming OpenAI requests so usage is observable at all — always flagged
`gateway_injected: true` with before/after request hashes. `EUTHYNA_TRANSPARENT=1`
disables everything and leaves a pure pipe.

## CLI

| Command | What it does |
|---|---|
| `euthyna up` | Run the gateway (sidecar data plane) on `:4517` |
| `euthyna probe` | Measure a backend's cache-field observability; write its profile |
| `euthyna report` | Aggregate a day's ledger: calls, tokens, cache ratio, dollars, prefix stability |
| `euthyna doctor` | Preflight the backend → gateway → host wiring |
| `euthyna analyze` | Serving-B advisory read of the day's metadata — **experimental narrative advisor**, judgment quality [not validated](docs/benchmarks/serving-b/REPORT.md); never acts |
| `euthyna submit` | Package telemetry (hash-only, anonymized, previewed) into an offline tarball for [community submission](https://github.com/Euthyna/euthyna-traces) |

## Design principles

| Principle | Meaning |
|---|---|
| Semantic-invariant by default | Out of the box, nothing the model sees is altered |
| Fail-open | The tap may go blind; it never blocks the agent |
| Never fabricate | Billing fields the provider didn't return are `None`/imputed — never silent zeros |
| Measured, never assumed | Backend capabilities come from `probe` evidence, not documentation |
| Local-only | Metadata-only capture, no phone home, keys referenced by env-var name only |
| Interventions by evidence | Every default traces to a measured claim; experiments are opt-in |

These are downstream of a research program's findings: prefix rewriting causally
busts provider caches (the "cache tax"), visible token reduction ≠ cost
reduction, and no trace-conditioned adaptive policy has yet beaten the best
static config. Hence: observe faithfully, keep prefixes append-only, intervene
only with evidence. See [PROVENANCE.md](PROVENANCE.md).

## Documentation

- [Setup guide](docs/SETUP.md) — local CP/DP/backend walkthrough (verified end
  to end), frontier APIs, model-side track
- [Architecture v0.3](docs/architecture.md) — the hourglass design,
  SIDECAR/HARNESS modes, the four actuators (diagrams render inline)
- [Serving-B model benchmark](docs/benchmarks/serving-b/REPORT.md) — why the
  advisor defaults to a 1.7B model, with numbers
- [First-run evidence](docs/examples/e2e-sample/NOTES.md) — a real agent
  session next to a real 400-retry storm the watchdog caught
- [RFC-002: skill economics](docs/rfcs/RFC-002-skill-economics.md) — the v0.2
  design, open for comment
- [Changelog](CHANGELOG.md) · [Provenance](PROVENANCE.md)

## Status and roadmap

**v0.1** — SIDECAR mode, end to end: gateway + ledger + prefix watchdog + CLI +
zero-fork opencode integration, verified against vllm-metal on Apple Silicon.
Known limitations are listed in the [changelog](CHANGELOG.md).

**Next (v0.2)** — HARNESS mode (Euthyna owns the loop: `calibrate` /
`experiment` with A/A floors), re-port of the upstream policy engine, and
evidence-gated flow compilation. Design already in
[docs/architecture.md](docs/architecture.md).

## Contributing

`pytest` is mock-backed and fast; no GPU or model needed. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) — it is short, and the ground rules
(fail-open contract, never-fabricate, ported-core parity) are the whole game.

## License

[Apache-2.0](LICENSE)
