# Euthyna

**A local audit gateway for AI coding agents.** Euthyna sits between your agent
(opencode, Claude Code, OpenHands, …) and your model backend as a bump-in-the-wire
proxy, and answers three questions the agent itself never will:

1. **What did this task actually cost?** Task-total dollars with native cache
   categories (cached / uncached / output), never fabricated: every billing field is
   flagged *observed* or *imputed*.
2. **Is the agent loop healthy?** A byte-level prefix-stability watchdog catches
   cache-busting context rewrites — the single biggest silent cost multiplier in
   cached agent loops.
3. **What should change?** Evidence-gated advice only. Out of the box Euthyna alters
   nothing the model sees; interventions require evidence, experiments require consent.

*Euthyna (εὔθυνα): the accounting audit every Athenian official underwent on leaving
office. Nothing in excess; know thyself.*

## Quickstart

Developer smoke test — no GPU, no model, no network:

```bash
git clone https://github.com/cdc542559455/euthyna.git && cd euthyna
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

Point your agent at `http://127.0.0.1:4517/v1` instead of the backend, run a task,
then in another terminal:

```bash
euthyna report      # per-session calls, tokens, cache ratio, $, prefix stability
euthyna doctor      # preflight: backend → gateway → host wiring
```

Full walkthrough incl. opencode + vllm-metal on Apple Silicon: **[docs/SETUP.md](docs/SETUP.md)**.

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

- **Ledger** — one JSONL row per call in `~/.euthyna/ledger/YYYY-MM-DD.jsonl`: raw
  provider usage, cost row with observed/imputed flags, prefix-stability ratio.
- **Traces** — metadata only (`~/.euthyna/traces/<session>.jsonl`): hashes, sizes,
  roles. Message content is never stored. Nothing ever leaves your machine.
  All state lives under `~/.euthyna`; override with `EUTHYNA_HOME`.
- **Profiles** — `euthyna probe` measures what a backend's usage payloads actually
  surface and writes the evidence into `profiles/<name>.yaml`. Nothing is assumed.
- **Serving-B slot** — `euthyna analyze` feeds the day's *metadata* to an advisor
  model (default: a small local model on a second port) which annotates waste and
  recommends static config changes. Advisory only; it never touches the request path.
- **Local by default, frontier by choice** — both the backend and the advisor accept
  any OpenAI/Anthropic-dialect endpoint (`profiles/*.example.yaml`); API keys are
  referenced by env-var name only and never stored.

The one mutation the gateway is allowed: injecting `stream_options.include_usage`
into streaming OpenAI requests so usage is observable at all — always flagged
`gateway_injected: true` with before/after request hashes. `EUTHYNA_TRANSPARENT=1`
disables everything and leaves a pure pipe.

## Design lineage

Euthyna is the product distillation of an agent-runtime research program
(see [PROVENANCE.md](PROVENANCE.md)). The design choices are downstream of its
evidence: prefix rewriting causally busts provider caches (the "cache tax"), visible
token reduction ≠ cost reduction, and no trace-conditioned adaptive policy has yet
beaten the best static config. Hence: observe faithfully, keep prefixes append-only,
intervene only with evidence. Architecture v0.3 (hourglass, four actuators, two
operating modes): [docs/architecture-v0.3.html](docs/architecture-v0.3.html) ·
[docs/interaction-flows-v0.3.html](docs/interaction-flows-v0.3.html).

## Status

v0.1: core accounting library (ported from the research SDK, 22 tests) + sidecar
gateway + CLI (`up · probe · report · doctor · analyze`) + opencode zero-fork
integration, e2e-verified against vllm-metal on Apple Silicon. HARNESS mode (Euthyna
owns the loop: calibrate/experiment) is next; see the architecture docs.

## Contributing

`uv pip install -e ".[test]" && pytest` — the suite is fast and mock-backed; no GPU
or model needed. Start with `docs/SETUP.md` part 1 to get a feel for the pipeline.
Apache-2.0.
