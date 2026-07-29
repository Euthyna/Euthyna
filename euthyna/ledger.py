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


def cache_status(cost: dict) -> str:
    """Three-state cache observability for a cost row: observed / imputed_zero /
    unavailable. 'unavailable' must render as unknown downstream, never as 0."""
    observed = cost.get("observed_flags") or {}
    imputed = cost.get("imputed_flags") or {}
    if observed.get("cached_tokens"):
        return "observed"
    if imputed.get("cached_tokens"):
        return "imputed_zero"
    if "observed_flags" not in cost:
        return "observed"  # synthetic rows without flags: trust the value as given
    return "unavailable"


def cost_quality(cost: dict) -> str:
    """exact — every category that can move the bill was observed;
    estimated_under_no_cache_assumption — a cache category is unobservable AND its
    rate differs from the input rate, so the true bill may be lower."""
    prices = cost.get("list_price_per_1m") or {}
    input_rate = prices.get("input_per_1m")
    observed = cost.get("observed_flags") or {}
    for cat, rate_key in (("cached_tokens", "cached_input_per_1m"),
                          ("cache_creation_tokens", "cache_creation_per_1m")):
        rate = prices.get(rate_key)
        if not observed.get(cat) and rate is not None and rate != input_rate:
            return "estimated_under_no_cache_assumption"
    return "exact"


def _row_cache_status(cost: dict) -> str:
    return cost.get("cache_status") or cache_status(cost)


def _row_cost_quality(row: dict, cost: dict | None) -> str:
    """Rows written before 0.1.1 carry no cost_quality — derive it from the cost row
    rather than assuming 'exact' (the same unknown-as-certainty bug as cache_status)."""
    if row.get("cost_quality"):
        return row["cost_quality"]
    return cost_quality(cost) if cost else "unavailable"


def aggregate(rows: list[dict]) -> dict:
    """Per-session aggregates over ledger rows.

    cached_tokens/cached_fraction are computed ONLY over calls whose cache
    observability is known (observed or imputed_zero). Sessions where the cache
    is unavailable on every call report None — unknown is never rendered as 0.
    """
    sessions: dict = {}
    for row in rows:
        s = sessions.setdefault(row.get("session") or "?", {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
            "cache_known_calls": 0, "cache_known_prompt": 0, "cache_unavailable_calls": 0,
            "cost_usd": 0.0, "cost_quality": {"exact": 0, "estimated": 0, "unavailable": 0},
            "prefix_mutations": 0, "prefix_mutation_cost_tok_eq": 0.0,
            "mutation_causes": {}, "cache_miss_unexplained": 0,
            "ratios": [], "models": set(), "injected": 0,
        })
        s["calls"] += 1
        prompt, completion = _tokens(row)
        s["prompt_tokens"] += prompt
        s["completion_tokens"] += completion
        mutation = row.get("prefix_mutation")
        if mutation:
            s["prefix_mutations"] += 1
            s["prefix_mutation_cost_tok_eq"] += mutation.get("cost_tok_eq") or 0
            for seg in mutation.get("segments") or []:
                s["mutation_causes"][seg] = s["mutation_causes"].get(seg, 0) + 1
        if row.get("cache_miss_unexplained"):
            s["cache_miss_unexplained"] += 1
        cost = row.get("cost")
        if cost:
            status = _row_cache_status(cost)
            if status == "unavailable":
                s["cache_unavailable_calls"] += 1
            else:
                s["cached_tokens"] += (cost.get("native_tokens") or {}).get("cached_tokens") or 0
                s["cache_known_calls"] += 1
                s["cache_known_prompt"] += prompt
            s["cost_usd"] += cost.get("list_cost_usd") or 0.0
        quality = _row_cost_quality(row, cost)
        key = "estimated" if quality.startswith("estimated") else quality
        s["cost_quality"][key] = s["cost_quality"].get(key, 0) + 1
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
        if s["cache_known_calls"] == 0:
            s["cached_tokens"] = None
            s["cached_fraction"] = None
        else:
            s["cached_fraction"] = (
                round(s["cached_tokens"] / s["cache_known_prompt"], 4)
                if s["cache_known_prompt"] else None
            )
        s["cost_usd"] = round(s["cost_usd"], 6)
        s["models"] = sorted(s["models"])
        out[sid] = s
    return out
