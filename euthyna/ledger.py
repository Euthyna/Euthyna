"""Reading and aggregating the JSONL ledger. Shared by `euthyna report` and the
gateway's /euthyna/stats endpoint — one parser, one aggregation, two front-ends."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


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


# A verb repeated this many times in a row stops being a search and becomes a loop. Two
# identical actions are ordinary — narrow a grep, list another directory. The third is
# where the evidence says progress has stopped: in a 28-instance SWE-bench corpus, runs of
# 3+ accounted for 68% of all spend, and the longest were 33 identical greps and 30
# identical cds against a prompt that explicitly says cd does not persist.
REPETITION_RUN = 3


def repetition_waste(rows: list[dict]) -> dict:
    """Spend sitting inside runs of the same action repeated until it stopped helping.

    Charged from the third occurrence onward: the first two are the ordinary shape of
    narrowing a search, and everything after them is the agent going in circles. Rows
    without recorded actions are skipped rather than assumed innocent — a call whose
    response could not be read is unknown, not clean.
    """
    by_session: dict = {}
    for row in rows:
        actions = row.get("actions")
        if isinstance(actions, list):
            by_session.setdefault(row.get("session") or "?", []).append(row)

    total_actions = wasted_actions = 0
    total_cost = wasted_cost = 0.0
    longest = ("", 0)
    digest_keyed = 0
    epochs: set = set()
    for sid, session_rows in by_session.items():
        session_rows.sort(key=lambda r: r.get("ts") or "")
        # Key on the argument digest when the row carries one. Without it the key is the
        # verb, and `bash:grep` cannot distinguish a search being narrowed from a loop
        # going nowhere — which overstated this measure by 2.5x on the SWE-bench corpus
        # (59.5% keyed on the verb against 24.0% keyed on the command).
        flat = []
        for r in session_rows:
            actions = r.get("actions") or []
            digests = r.get("action_digests") or []
            cost = step_cost(r.get("cost") or {}) or 0.0
            if r.get("digest_epoch"):
                epochs.add(r["digest_epoch"])
            for i, a in enumerate(actions):
                d = digests[i] if i < len(digests) else None
                if d:
                    digest_keyed += 1
                flat.append(((a, d) if d else a, a, cost))
        run_key, run_len = None, 0
        for key, action, cost in flat:
            total_actions += 1
            total_cost += cost
            if key == run_key:
                run_len += 1
            else:
                run_key, run_len = key, 1
            if run_len > longest[1]:
                # The verb, not the key: the digest is an identity, not something to report.
                longest = (action, run_len)
            if run_len >= REPETITION_RUN:
                wasted_actions += 1
                wasted_cost += cost
    return {
        "actions": total_actions,
        "repeated_actions": wasted_actions,
        "repeated_fraction": (wasted_actions / total_actions) if total_actions else None,
        "cost_tok_eq": round(total_cost, 1),
        "repeated_cost_tok_eq": round(wasted_cost, 1),
        "repeated_cost_fraction": (wasted_cost / total_cost) if total_cost else None,
        "longest_run": {"action": longest[0], "length": longest[1]} if longest[1] else None,
        "sessions_with_actions": len(by_session),
        # Which granularity actually got used. "verb" cannot tell a narrowing search from
        # a loop and reads high; on the SWE-bench corpus it read 2.5x the command-keyed
        # figure. Rows predating action_digests still land here, so the caller has to be
        # told rather than left to assume the better number.
        "keyed_on": ("command" if digest_keyed == total_actions and total_actions
                     else "mixed" if digest_keyed else "verb"),
        "actions_keyed_by_digest": digest_keyed,
        # Digests are salted per gateway process. More than one epoch means identical
        # commands from different lifetimes look distinct, which UNDER-counts repetition —
        # a quiet wrongness, so it is surfaced rather than absorbed.
        "digest_epochs": len(epochs),
        "digest_epochs_comparable": len(epochs) <= 1,
    }


def observed_vocabulary(rows: list[dict]) -> set:
    """Every action name this traffic actually emitted.

    Rows written before the actions tap existed carry no ``actions`` key, and rows whose
    response could not be read carry ``None``. Neither is an observation that no actions
    occurred, so both are skipped rather than folded in as empty — the same
    unknown-is-not-zero rule the cache fields follow.
    """
    vocab: set = set()
    for row in rows:
        actions = row.get("actions")
        if isinstance(actions, list):
            vocab.update(str(a) for a in actions)
    return vocab


def action_coverage(rows: list[dict]) -> dict:
    """How much of this traffic can speak about actions at all."""
    total = len(rows)
    recorded = sum(1 for r in rows if isinstance(r.get("actions"), list))
    unreadable = sum(1 for r in rows if r.get("actions") is None and "actions" in r)
    return {"calls": total, "with_actions": recorded, "unreadable": unreadable,
            "pre_tap": total - recorded - unreadable}


def step_cost_quality(cost: dict) -> str:
    """Quality of the *token-equivalent* step cost, which is not the quality of the bill.

    ``cost_quality`` asks whether the USD total is certain, so it clears a row whose
    cache rates equal its input rate — for a local model priced at zero, every rate is
    equal and the dollar bill is exactly zero however the prompt was cached. That says
    nothing about ``step_cost``, which weights uncached at 1.0 against cached at 0.10 no
    matter what the money says. A row can therefore be an exact $0 and a 10x-uncertain
    step.

    So this asks the only question the weights care about: was the cache split observed?
    If not, ``step_cost`` counts the whole prompt as uncached, which is an upper bound
    rather than a measurement.
    """
    if cache_status(cost) == "observed":
        return "exact"
    return "estimated_under_no_cache_assumption"


# Fallback weights, used only when a row's price sheet cannot yield ratios. These
# extend the frozen H1 estimand (w_uncached, w_cached, w_output) = (1.0, 0.1, 5.0) with
# the cache-write line the original study's route never exposed, and they are
# **Anthropic Opus's** published ratios — cache read 0.10x input, cache write 1.25x
# (5-minute TTL; 2x at 1-hour), output 5x ($25 out over $5 in).
#
# They are not universal. DeepSeek V4-Pro prices a cache read at $0.003625 against
# $0.435 input — 0.0083x, twelve times cheaper — and its output at 2.0x, not 5x. Every
# weight here is provider-specific, so applying this dict to another provider's traffic
# misprices all four categories at once. Prefer weights_from_prices().
FALLBACK_STEP_WEIGHTS = {"uncached": 1.0, "cached": 0.10,
                         "cache_creation": 1.25, "output": 5.0}
STEP_WEIGHTS = FALLBACK_STEP_WEIGHTS   # back-compat alias


def weights_from_prices(prices: dict | None) -> tuple[dict, dict]:
    """Effective-cost weights derived from the provider's own price sheet.

    A token-equivalent normalises every token class to "one uncached input token", so
    each weight is just that class's price over the input price. Anthropic Opus returns
    the frozen constants exactly; another provider returns its own.

    Returns ``(weights, basis)`` where basis maps each key to ``derived`` or
    ``assumed``, because a sheet that prices input at zero — every local model — cannot
    yield a ratio at all, and silently substituting one provider's constants there is
    the assumption that has to stay visible.
    """
    weights = dict(FALLBACK_STEP_WEIGHTS)
    basis = {k: "assumed" for k in weights}
    prices = prices or {}
    base = prices.get("input_per_1m")
    if not base:            # None or 0.0 — no denominator, so no ratio exists
        return weights, basis
    for key, price_key in (("cached", "cached_input_per_1m"),
                           ("cache_creation", "cache_creation_per_1m"),
                           ("output", "output_per_1m")):
        rate = prices.get(price_key)
        if rate is not None:
            weights[key] = rate / base
            basis[key] = "derived"
    return weights, basis


def step_cost(cost: dict) -> Optional[float]:
    """Effective cost of one agent step in token-equivalents.

    ``c_step = 1.0*uncached + 0.10*cached + 1.25*cache_creation + 5.0*output``

    Returns None when prompt or completion tokens were never observed. When the cache
    split is unobservable the whole prompt counts as uncached, which OVERSTATES the
    step — the row's existing ``cost_quality`` already records that as
    ``estimated_under_no_cache_assumption``; no separate flag is invented here.
    """
    native = cost.get("native_tokens") or {}
    prompt, completion = native.get("prompt_tokens"), native.get("completion_tokens")
    if prompt is None or completion is None:
        return None
    cached = native.get("cached_tokens") or 0
    creation = native.get("cache_creation_tokens") or 0
    uncached = max(prompt - cached - creation, 0)
    # Each row carries the price sheet it was billed under, so each row is weighted by
    # its own provider's ratios rather than by one provider's constants.
    w, _ = weights_from_prices(cost.get("list_price_per_1m"))
    return round(w["uncached"] * uncached + w["cached"] * cached
                 + w["cache_creation"] * creation + w["output"] * completion, 1)


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
            "step_costs": [], "prompt_series": [], "cached_weights": set(),
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
        if prompt:
            s["prompt_series"].append(prompt)
        cost = row.get("cost")
        if cost:
            sc = step_cost(cost)
            if sc is not None:
                s["step_costs"].append(sc)
            # The compounding term below re-reads earlier context at the CACHED rate, so it
            # has to use the rate this row was actually billed at. Collected per session
            # because a session is normally one provider; when it is not, that is visible
            # rather than averaged away.
            _w, _b = weights_from_prices(cost.get("list_price_per_1m"))
            s["cached_weights"].add((_w["cached"], _b["cached"]))
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
        costs, series = s.pop("step_costs"), s.pop("prompt_series")
        s["mean_step_cost_tok_eq"] = round(sum(costs) / len(costs), 1) if costs else None
        # Eliminating step k also spares every later turn the 0.10x re-read of the
        # tokens it added — the compounding term. Context growth is measured, not
        # assumed: it is the observed prompt delta between consecutive calls.
        # mean_step_cost_tok_eq is weighted per row by its own provider, so pricing the
        # compounding term with one provider's frozen constant would build a single number
        # out of two different price sheets.
        seen = s.pop("cached_weights")
        if len(seen) == 1:
            # One price sheet. Its own basis carries through: a local model prices at $0 and
            # yields the fallback weight, which is "assumed" and must not read as "derived"
            # merely because exactly one sheet produced it.
            cached_w, cached_basis = next(iter(seen))
        elif len(seen) > 1:
            cached_w, cached_basis = FALLBACK_STEP_WEIGHTS["cached"], "mixed-providers"
        else:
            cached_w, cached_basis = FALLBACK_STEP_WEIGHTS["cached"], "no-priced-calls"
        s["cached_weight_basis"] = cached_basis
        compounding = 0.0
        n = len(series)
        for k in range(n - 1):
            growth = max(series[k + 1] - series[k], 0)
            compounding += cached_w * growth * (n - k - 2)
        s["mean_step_saving_tok_eq"] = (
            round(s["mean_step_cost_tok_eq"] + compounding / max(n - 1, 1), 1)
            if costs and n > 1 else s["mean_step_cost_tok_eq"])
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
