# Euthyna setup guide

Two tracks. **Part 1** is the full local development loop — control plane + data plane
+ backend — the one every contributor should be able to run. **Part 2** is model-side
development (Serving-B and beyond); its scope is sketched and marked TBD.

Everything below was verified end-to-end on an Apple M5, 24 GB unified memory,
macOS 26.1, 2026-07-21. Nothing here needs an API key and nothing leaves your machine.

---

## Part 1 — Static CP + DP + backend (local development)

### 0. What you're building

```
opencode ──baseURL──▶ euthyna gateway :4517 ──▶ vllm-metal :8000 (Serving A, 7–8B)
                        │ ledger · traces · prefix watchdog
                        ▼
              euthyna report / doctor / analyze ◀── Qwen3-1.7B :8001 (Serving B, optional)
```

### 1. Euthyna itself

```bash
git clone https://github.com/cdc542559455/euthyna.git && cd euthyna
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"                    # or: uv venv && uv pip install -e ".[test]"
pytest                                      # mock-backed, no GPU needed
```

If you only want to hack on the gateway/CLI, you can stop here — the test suite
fakes both backend dialects. The rest brings up the real pipeline.

### 2. Serving A — vllm-metal + an 8B coder (Apple Silicon)

[vllm-metal](https://github.com/vllm-project/vllm-metal) must run natively on macOS
(Metal cannot run inside a VM). One-time install per its README gives you
`~/.venv-vllm-metal`. Then:

```bash
VLLM_METAL_USE_PAGED_ATTENTION=1 VLLM_METAL_MEMORY_FRACTION=0.45 caffeinate -i \
  ~/.venv-vllm-metal/bin/vllm serve mlx-community/Qwen3-8B-4bit \
  --host 127.0.0.1 --port 8000 --seed 1234 \
  --max-model-len 16384 --max-num-seqs 4 --disable-log-stats \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

Notes from the first run, so you don't rediscover them:

- **Model choice matters for tool calling.** Qwen2.5-Coder-7B-4bit *knows* the tools
  but emits calls as plain text (```json blocks) instead of `<tool_call>` tags, so the
  agent loop stalls. Qwen3-8B-4bit emits structured tool_calls reliably. If you swap
  models, smoke-test tools first (curl with a `tools` array; expect `tool_calls` in
  the response, not prose).
- `--enable-auto-tool-choice --tool-call-parser hermes` is required for opencode;
  without it every request 400s ("auto tool choice requires …").
- 24 GB machine budget: 8B-4bit weights ≈ 4.5 GB + 16k KV ≈ 2.3 GB inside
  `MEMORY_FRACTION 0.45`. Check `sysctl vm.swapusage` before going bigger.
- Thinking models: disable via `--default-chat-template-kwargs` or your agent drowns
  in `<think>` tokens at local speeds.

### 3. Probe it, run the gateway

```bash
euthyna probe --base-url http://127.0.0.1:8000 --name vllm-metal
euthyna up --profile profiles/vllm-metal.yaml        # gateway on :4517
```

`probe` writes `profiles/vllm-metal.yaml` with **measured** cache observability and a
$0 local price sheet. On current vllm-metal, `cached_tokens` does **not** surface
(`prompt_tokens_details: null`) — the profile records `surfaces: false` and the probe's
latency evidence (39.1 s cold → 0.17 s warm on an identical prefix; see the `probe:`
block in the committed profile) shows APC working anyway. Euthyna never fabricates
what the backend doesn't report.

### 4. opencode — zero fork

In the project you want the agent to work on:

```jsonc
// opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "euthyna": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:4517/v1" },
      "models": {
        "mlx-community/Qwen3-8B-4bit": {
          "limit": { "context": 16384, "output": 1536 }   // MUST match --max-model-len
        }
      }
    }
  },
  "model": "euthyna/mlx-community/Qwen3-8B-4bit"
}
```

Copy `plugins/opencode/euthyna.js` into `.opencode/plugins/` so every call carries the
real opencode session id (`X-Euthyna-Session`); without it the gateway falls back to
prefix-chaining heuristics (which work, but header is exact).

The `limit.context` line is load-bearing: opencode defaults to a 32k output budget,
and if context+output exceeds `--max-model-len` by even one token the loop 400s
(first run failed at 6657 + 1536 = 8193 > 8192).

```bash
euthyna doctor          # all PASS?
opencode run "write fizzbuzz.py plus a test, run it, make it pass"
euthyna report          # calls · tokens · $ · cache · prefix stability per session
```

A healthy agent session reports `prefix_stable_ratio ≈ 0.93+` (append-only context).
The first-run artifacts in `docs/examples/e2e-first-run/` include a real 400-retry storm the
watchdog caught at ratio 0.004 — that contrast is the product.

### 5. Serving B — the advisor slot (optional)

```bash
VLLM_METAL_USE_PAGED_ATTENTION=1 VLLM_METAL_MEMORY_FRACTION=0.2 caffeinate -i \
  ~/.venv-vllm-metal/bin/vllm serve mlx-community/Qwen3-1.7B-4bit \
  --host 127.0.0.1 --port 8001 --seed 1234 \
  --max-model-len 8192 --max-num-seqs 2 --disable-log-stats \
  --default-chat-template-kwargs '{"enable_thinking": false}'

euthyna analyze         # metadata in → annotations + recommendations out
```

Separate process, separate port, KV-isolated from Serving A — by design. The advisor
sees **metadata only** (counts, ratios, costs — never message content) and its output
is banner-labeled advisory; nothing consumes it automatically. v0 ships the slot, not
model quality. Default model per the measured comparison in
`docs/benchmarks/serving-b/REPORT.md`: Qwen3-1.7B-4bit (only format-reliable
1B-class model on this stack); recommendation quality is gated work (Part 2).

### 6. Frontier APIs — the same pipeline, bigger models

Both slots take any OpenAI/Anthropic-dialect endpoint; local serving is the default,
not a limit. Key hygiene rule everywhere: **configs and profiles store only the NAME
of an env var** (`api_key_env: OPENAI_API_KEY`), never the key itself.

**Backend (Serving A → cloud).** Copy `profiles/openai.example.yaml` →
`profiles/openai.yaml`, fill the current price sheet, then:

```bash
export OPENAI_API_KEY=...   # your key, env only
euthyna probe --base-url https://api.openai.com --name openai \
  --api-key-env OPENAI_API_KEY --model <model-id>
euthyna up --profile profiles/openai.yaml
```

Your agent keeps its own key: opencode's provider `apiKey` (or Claude Code's OAuth
headers, including `anthropic-beta`) rides through the gateway untouched — Euthyna
never injects or stores auth. For the Anthropic dialect, add
`--anthropic-profile profiles/anthropic.yaml` and point Claude Code at
`ANTHROPIC_BASE_URL=http://127.0.0.1:4517`. Now the ledger shows real dollars and
real `cached_tokens` instead of the local $0 sheet.

**Perception (Serving B → cloud).** The advisor slot is just an endpoint URL:

```bash
euthyna analyze --advisor-url https://api.openai.com \
  --advisor-api-key-env OPENAI_API_KEY --advisor-model <model-id>
```

Privacy note: `analyze` sends **metadata only** (counts, ratios, costs — never
message content), so pointing it at a cloud model leaks no prompt text. It remains
advisory-only regardless of how big the model is.

---

## Part 2 — Model-side development (TBD)

The Serving-B slot is the entry point for model work. Scope sketch, in evidence order:

1. **Annotation quality** (NOW tier): evaluate small models (Qwen3-0.6B/
   1.7B, …) on waste-taxonomy annotation against the research repo's 2,000-trace
   labeled dataset (LoRA splits exist: train 1107 / val 225 / test 168, repo-disjoint).
2. **Non-convergence early warning**: reproduce the T10 AUROC 0.70 prefix signal on
   live gateway traces; ship as an advisory metric, not a controller.
3. **Task-level config recommendation** (GATED): requires the predictability gate +
   preregistered read-out before any default changes.
4. **Fine-tuning loop**: LoRA on the annotation dataset → serve via vllm-metal on
   :8001 → A/B against the base model on held-out traces.

Ground rules that travel from the research program: no trace-conditioned in-flight
steering (rejected, stays rejected); no "Confirmed" claims without a prospective
protocol; every improvement claim needs an A/A noise floor under it. TBD details will
land here as this track opens.
