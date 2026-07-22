"""`euthyna report` — aggregate a day's ledger into per-session and total accounting.

Reads the JSONL ledger the gateway appends to; no live state, safe to run any time.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("EUTHYNA_HOME", "~/.euthyna")).expanduser()


def load_rows(date: str) -> list[dict]:
    path = _home() / "ledger" / f"{date}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def aggregate(rows: list[dict]) -> dict:
    sessions: dict = {}
    for row in rows:
        s = sessions.setdefault(row.get("session") or "?", {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
            "cost_usd": 0.0, "ratios": [], "models": set(), "injected": 0,
        })
        s["calls"] += 1
        usage = row.get("usage") or {}
        s["prompt_tokens"] += usage.get("prompt_tokens") or 0
        s["completion_tokens"] += usage.get("completion_tokens") or 0
        cost = row.get("cost") or {}
        cached = (cost.get("native_tokens") or {}).get("cached_tokens")
        s["cached_tokens"] += cached or 0
        s["cost_usd"] += cost.get("list_cost_usd") or 0.0
        if row.get("prefix_stable_ratio") is not None:
            s["ratios"].append(row["prefix_stable_ratio"])
        if row.get("model"):
            s["models"].add(row["model"])
        if row.get("gateway_injected"):
            s["injected"] += 1

    out = {}
    for sid, s in sessions.items():
        ratios = s.pop("ratios")
        s["mean_prefix_stable_ratio"] = round(sum(ratios) / len(ratios), 4) if ratios else None
        s["cached_fraction"] = (
            round(s["cached_tokens"] / s["prompt_tokens"], 4) if s["prompt_tokens"] else None
        )
        s["cost_usd"] = round(s["cost_usd"], 6)
        s["models"] = sorted(s["models"])
        out[sid] = s
    return out


def run(args) -> int:
    date = args.date or _dt.date.today().isoformat()
    rows = load_rows(date)
    sessions = aggregate(rows)
    if args.json:
        print(json.dumps({"date": date, "sessions": sessions}, indent=2))
        return 0
    if not rows:
        print(f"report: no ledger rows for {date} under {_home() / 'ledger'}")
        return 0

    header = f"{'session':<18} {'calls':>5} {'prompt':>9} {'cached':>9} {'compl':>7} {'$':>10} {'prefix':>7}"
    print(f"euthyna report — {date}")
    print(header)
    print("-" * len(header))
    totals = {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    for sid, s in sorted(sessions.items()):
        ratio = s["mean_prefix_stable_ratio"]
        print(f"{sid[:18]:<18} {s['calls']:>5} {s['prompt_tokens']:>9} {s['cached_tokens']:>9} "
              f"{s['completion_tokens']:>7} {s['cost_usd']:>10.4f} "
              f"{ratio if ratio is not None else '—':>7}")
        for key in totals:
            totals[key] += s[key]
    print("-" * len(header))
    print(f"{'TOTAL':<18} {totals['calls']:>5} {totals['prompt_tokens']:>9} {totals['cached_tokens']:>9} "
          f"{totals['completion_tokens']:>7} {totals['cost_usd']:>10.4f}")
    models = sorted({m for s in sessions.values() for m in s["models"]})
    print(f"models: {', '.join(models) if models else '—'}")
    return 0
