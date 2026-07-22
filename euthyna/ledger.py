"""Reading and aggregating the JSONL ledger. Shared by `euthyna report` and the
gateway's /euthyna/stats endpoint — one parser, one aggregation, two front-ends."""
from __future__ import annotations

import json
import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("EUTHYNA_HOME", "~/.euthyna")).expanduser()


def load_rows(date: str, home_dir: Path | None = None) -> list[dict]:
    path = (home_dir or home()) / "ledger" / f"{date}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _tokens(row: dict) -> tuple[int, int]:
    """(prompt, completion) for a row, whichever dialect produced it.

    Prefers the accountant's normalized native_tokens; falls back to raw usage in
    OpenAI shape, then Anthropic shape (input_tokens excludes cache reads/writes).
    """
    native = (row.get("cost") or {}).get("native_tokens") or {}
    usage = row.get("usage") or {}
    prompt = native.get("prompt_tokens")
    if prompt is None:
        prompt = usage.get("prompt_tokens")
    if prompt is None and "input_tokens" in usage:
        prompt = (usage["input_tokens"]
                  + (usage.get("cache_read_input_tokens") or 0)
                  + (usage.get("cache_creation_input_tokens") or 0))
    completion = native.get("completion_tokens")
    if completion is None:
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
    return prompt or 0, completion or 0


def aggregate(rows: list[dict]) -> dict:
    """Per-session aggregates over ledger rows."""
    sessions: dict = {}
    for row in rows:
        s = sessions.setdefault(row.get("session") or "?", {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
            "cost_usd": 0.0, "ratios": [], "models": set(), "injected": 0,
        })
        s["calls"] += 1
        prompt, completion = _tokens(row)
        s["prompt_tokens"] += prompt
        s["completion_tokens"] += completion
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
