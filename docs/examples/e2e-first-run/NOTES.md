# e2e first run — 2026-07-21

Pipeline: opencode 1.18.4 (zero fork: custom provider + chat.headers plugin)
→ euthyna gateway :4517 → vllm-metal 0.3.0.dev (vLLM 0.23) :8000 on Apple M5 24GB.

- Serving A: mlx-community/Qwen3-8B-4bit, max_model_len 16384, hermes tool parser,
  thinking disabled. (Qwen2.5-Coder-7B-4bit was tried first: emitted tool calls as
  plain text instead of <tool_call> — swapped for Qwen3-8B, which emits structured
  tool_calls reliably.)
- Task: create fizzbuzz.py + test, run test, fix, tests pass. Completed (needed two
  precise nudges — the 8B repeatedly diagnosed without editing; classic STAGNATION).
- Ledger verified: per-call usage rows, task-total $, per-session prefix stability.
  Healthy Qwen3 session: prefix_stable_ratio 0.93. The earlier 7B 400-retry storm
  shows as 96 calls at ratio 0.004 — the watchdog caught the thrash in real data.
- cached_tokens: NOT surfaced by this vllm-metal build (probe + all ledger rows agree;
  prompt_tokens_details is null). Recorded observed=false, never fabricated. APC is
  active (probe latency: first 13.4s vs second 0.15s on identical prefix).
- Known wrinkle: opencode context limit must be set in opencode.json (limit.context)
  to match --max-model-len, or the loop 400s at the boundary (8192+1536=8193 > 8192).
