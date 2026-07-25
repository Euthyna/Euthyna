"""`euthyna analyze` — the Serving-B slot, v0: perception only.

Feeds a compact, metadata-only summary of today's ledger + traces to a small local
model (Serving B, its own server/port, KV-isolated from the model under test) and
prints its annotations and recommendations.

ADVISORY ONLY. This command never changes gateway behavior, never touches the
request path, and its output is not consumed by any policy. Per architecture v0.3
the Serving-B model "reads traces, never load-bearing": task-level recommendation
is gated, in-flight action selection is rejected.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.request

from euthyna.ledger import aggregate, home as _home, load_rows

BANNER = "ADVISORY ONLY — Euthyna does not act on any of this automatically."
QUALITY_NOTE = ("experimental narrative advisor — judgment quality is NOT validated "
                "(zero-shot small models failed our own benchmark: docs/benchmarks/serving-b)")

PROMPT = """You are Euthyna's Serving-B advisor: the perception half of an agent-runtime \
audit gateway. You read METADATA ONLY (token counts, cache ratios, prefix stability, \
costs) from an agent's day of LLM calls. You never see message content and you never \
take actions; you only annotate and recommend.

Evidence rules: flag only what the numbers support; say "insufficient data" freely; \
every recommendation must cite the metric that motivates it.

Analyze the sessions below. Output three short sections:
1. WASTE FLAGS — per session: redundant re-reads (low prefix stability), context bloat \
(prompt growth without cached growth), retry churn (many calls, few completion tokens).
2. CACHE HEALTH — cached_fraction and prefix_stable_ratio interpretation; is the \
append-only prefix contract holding?
3. RECOMMENDATIONS — static config suggestions only (e.g. "enable APC", "keep prefix \
stable", "consider fewer max steps"). No in-flight interventions.

DATA:
"""


def _serving_b(base_url: str, text: str, api_key_env=None, model=None) -> tuple[str, str]:
    from .util import bearer

    base = base_url.rstrip("/")
    auth = bearer(api_key_env)
    if model is None:
        req = urllib.request.Request(f"{base}/v1/models", headers=auth)
        models = json.loads(urllib.request.urlopen(req, timeout=10).read())
        model = models["data"][0]["id"]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "max_tokens": 2000,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **auth},
    )
    body = json.loads(urllib.request.urlopen(req, timeout=600).read())
    content = body["choices"][0]["message"]["content"] or ""
    # Thinking-style models may prepend a chain-of-thought block; keep the answer only.
    content = re.sub(r"<think>.*?(</think>|\Z)", "", content, flags=re.S).strip()
    return content, model


def _trace_shapes(sessions: dict, date: str) -> dict:
    shapes = {}
    for sid in sessions:
        path = _home() / "traces" / f"{sid}.jsonl"
        if not path.exists():
            continue
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        events = [e for e in events if e.get("ts", "").startswith(date)]
        if events:
            shapes[sid] = {
                "n_calls": len(events),
                "n_messages_first": events[0].get("n_messages"),
                "n_messages_last": events[-1].get("n_messages"),
                "prefix_ratios": [e.get("prefix_stable_ratio") for e in events],
            }
    return shapes


def run(args) -> int:
    date = args.date or _dt.date.today().isoformat()
    rows = load_rows(date)
    if not rows:
        print(f"analyze: no ledger rows for {date}; run a task through the gateway first")
        return 0
    sessions = aggregate(rows)
    shapes = _trace_shapes(sessions, date)
    # Re-map session ids before anything leaves this process: the advisor endpoint
    # (possibly a cloud model) sees s001…, never the host's real session keys.
    mapping = {sid: f"s{i + 1:03d}" for i, sid in enumerate(sorted(sessions))}
    sessions = {mapping[sid]: s for sid, s in sessions.items()}
    shapes = {mapping[sid]: shape for sid, shape in shapes.items() if sid in mapping}
    data = {"date": date, "sessions": sessions, "trace_shapes": shapes}
    text = PROMPT + json.dumps(data, indent=1, default=str)

    try:
        advice, model = _serving_b(args.advisor_url, text,
                                   api_key_env=args.advisor_api_key_env,
                                   model=args.advisor_model)
    except Exception as exc:
        print(f"analyze: Serving B unreachable at {args.advisor_url} ({exc})")
        print("analyze: start it separately (see docs/SETUP.md §Serving B) — "
              "the gateway and report work fine without it.")
        return 1

    out_dir = _home() / "advice"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date}.md"
    out.write_text(f"# Euthyna advisory — {date}\n\n> {BANNER}\n> {QUALITY_NOTE}\n"
                   f"> model: {model}\n\n{advice}\n")
    print(f"[{BANNER}]\n[{QUALITY_NOTE}]  (serving-b: {model})\n")
    print(advice)
    print(f"\nanalyze: saved to {out}")
    return 0
