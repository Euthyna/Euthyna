#!/usr/bin/env python3
"""euthyna.accountant — list-price cost accounting (B3).

House rules (ported verbatim in spirit from the p2prime accountant):
  * LIST-PRICE accounting with a DATED price sheet. What we PAY is not what we REPORT.
  * Native token categories per provider. A cost row records an observed-vs-imputed flag per
    cache category and NEVER fabricates a missing field.
  * If a provider does not surface cached_tokens, we record observed=False / value=None and impute
    0 only for the cost arithmetic (flagged imputed). We never invent a cache-creation line.

CRITICAL calibration fact (encoded in the schema): the GPT-5.5 / PlugBoard route exposes NO
cached_tokens and NO cache-creation field. Recording anything else there would be fabrication.
"""
import json
import datetime  # noqa: F401 (kept for dated-sheet callers)

# --------------------------------------------------------------------------------------------------
# Provider cache SCHEMAS. Declares, per provider, which cache categories the provider *can* surface.
# A category with surfaces=False means: this route never exposes it -> observed is always False and
# the value is always None (never fabricate).
# --------------------------------------------------------------------------------------------------
PROVIDER_CACHE_SCHEMAS = {
    # GPT-5.5 on the PlugBoard route: prompt/completion/reasoning surface; cache is UNOBSERVED.
    "openai/gpt-5-5": {
        "cached_tokens": {"surfaces": False,  # PlugBoard gpt-5-5 route returns None (L-1 calibration)
                          "path": ("prompt_tokens_details", "cached_tokens")},
        "cache_creation_tokens": {"surfaces": False, "path": None},  # no cache-creation line at all
        "reasoning_tokens": {"surfaces": True,
                             "path": ("completion_tokens_details", "reasoning_tokens")},
    },
    # A hypothetical provider that DOES surface cache reads + creation (e.g. an Anthropic-style route).
    # Included to prove the observed/imputed logic is provider-parameterized, not hard-coded to None.
    "anthropic/claude-cache": {
        "cached_tokens": {"surfaces": True, "path": ("prompt_tokens_details", "cached_tokens")},
        "cache_creation_tokens": {"surfaces": True,
                                  "path": ("prompt_tokens_details", "cache_creation_tokens")},
        "reasoning_tokens": {"surfaces": False, "path": None},
    },
}

# --------------------------------------------------------------------------------------------------
# DATED list-price sheet (USD per 1M tokens). Append-only; never edited retroactively.
# --------------------------------------------------------------------------------------------------
PRICE_SHEET = {
    "2026-07-15": {
        "openai/gpt-5-5": {
            "input_per_1m": 1.25,
            "cached_input_per_1m": 0.125,
            "output_per_1m": 10.00,
            "cache_creation_per_1m": None,  # GPT-5.5 exposes NO cache-creation field -> None
            "notes": "gpt-5-5 (PlugBoard route). L-1 calibration (30 calls): no prompt_tokens_details, "
                     "cached_tokens NEVER surfaced (None). cache-read UNOBSERVED; no cache-creation "
                     "line. cached_tokens recorded observed=False/imputed (never fabricated).",
        },
        "anthropic/claude-cache": {
            "input_per_1m": 3.00,
            "cached_input_per_1m": 0.30,
            "output_per_1m": 15.00,
            "cache_creation_per_1m": 3.75,
            "notes": "example provider that DOES surface cache reads + creation.",
        },
    },
}


def price_for(model, price_date):
    sheet = PRICE_SHEET.get(price_date)
    if sheet is None:
        raise ValueError(f"no dated price sheet for {price_date}; sheets: {sorted(PRICE_SHEET)}")
    if model not in sheet:
        raise ValueError(f"model {model} not in price sheet {price_date}")
    return sheet[model]


def _schema(model):
    if model not in PROVIDER_CACHE_SCHEMAS:
        raise ValueError(f"no cache schema for provider/model {model}; "
                         f"known: {sorted(PROVIDER_CACHE_SCHEMAS)}")
    return PROVIDER_CACHE_SCHEMAS[model]


def _dig(d, path):
    if path is None:
        return None
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def cost_row_from_usage(usage, model="openai/gpt-5-5", price_date="2026-07-15"):
    """Map a provider `usage` dict -> a native-category cost row with observed/imputed flags.

    Returns dict: token categories, per-category list-price USD, observed_flags, imputed_flags,
    list_cost_usd. NEVER fabricates a cache field: if the schema says a category does not surface,
    observed=False and the value is None. If the provider *could* surface it but omitted it on this
    call, observed=False and the value is imputed to 0 (flagged imputed).
    """
    p = price_for(model, price_date)
    sch = _schema(model)
    u = usage or {}
    prompt_tokens = u.get("prompt_tokens")
    completion_tokens = u.get("completion_tokens")

    # cached_tokens: only read from provider if the schema says it can surface.
    cached_spec = sch["cached_tokens"]
    if cached_spec["surfaces"]:
        cached = _dig(u, cached_spec["path"])
    else:
        cached = None  # route never exposes it -> never fabricate

    cache_creation_spec = sch["cache_creation_tokens"]
    if cache_creation_spec["surfaces"]:
        cache_creation = _dig(u, cache_creation_spec["path"])
    else:
        cache_creation = None

    reasoning_spec = sch["reasoning_tokens"]
    reasoning = _dig(u, reasoning_spec["path"]) if reasoning_spec["surfaces"] else None

    observed = {
        "prompt_tokens": prompt_tokens is not None,
        "completion_tokens": completion_tokens is not None,
        # observed IFF the schema can surface it AND the provider actually returned it
        "cached_tokens": cached_spec["surfaces"] and cached is not None,
        "cache_creation_tokens": cache_creation_spec["surfaces"] and cache_creation is not None,
        "reasoning_tokens": reasoning_spec["surfaces"] and reasoning is not None,
    }

    # imputation for the cost arithmetic (only for categories the route CAN surface but omitted).
    if cached_spec["surfaces"]:
        cached_imputed = cached is None
        cached_val = cached if cached is not None else 0
    else:
        cached_imputed = False  # not imputed — genuinely absent
        cached_val = 0
    if cache_creation_spec["surfaces"]:
        cc_imputed = cache_creation is None
        cc_val = cache_creation if cache_creation is not None else 0
    else:
        cc_imputed = False
        cc_val = None  # never fabricate a value for a route that has no such line

    uncached = (prompt_tokens - cached_val) if prompt_tokens is not None else None

    def usd(tokens, per_1m):
        if tokens is None or per_1m is None:
            return None
        return round(tokens / 1_000_000.0 * per_1m, 8)

    list_cost = None
    if prompt_tokens is not None and completion_tokens is not None:
        c_in = usd(uncached, p["input_per_1m"]) or 0.0
        c_cache = usd(cached_val, p["cached_input_per_1m"]) or 0.0
        c_cc = usd(cc_val, p["cache_creation_per_1m"]) if cc_val else 0.0
        c_out = usd(completion_tokens, p["output_per_1m"]) or 0.0
        list_cost = round(c_in + c_cache + (c_cc or 0.0) + c_out, 8)

    return {
        "model": model,
        "price_date": price_date,
        "native_tokens": {
            "prompt_tokens": prompt_tokens,
            "uncached_prompt_tokens": uncached,
            "cached_tokens": cached_val,
            "cache_creation_tokens": cc_val,  # None for routes with no cache-creation line
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning,
        },
        "observed_flags": observed,
        "imputed_flags": {
            "cached_tokens": cached_imputed,
            "cache_creation_tokens": cc_imputed if cache_creation_spec["surfaces"] else True,
        },
        "list_price_per_1m": {k: p.get(k) for k in ("input_per_1m", "cached_input_per_1m",
                                                    "output_per_1m", "cache_creation_per_1m")},
        "list_cost_usd": list_cost,
    }


def effective_cost_h1(usage, weights=(1.0, 0.1, 5.0)):
    """Frozen H1 estimand (weights = (w_uncached_input, w_cached, w_output)). Study-level frozen;
    the accountant only APPLIES weights, never chooses them. Returns None if usage incomplete."""
    u = usage or {}
    pt = u.get("prompt_tokens")
    ct = u.get("completion_tokens")
    if pt is None or ct is None:
        return None
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    uncached = max(pt - cached, 0)
    w_in, w_cache, w_out = weights
    return w_in * uncached + w_cache * cached + w_out * ct


def recompute(usage_rows, model="openai/gpt-5-5", price_date="2026-07-15"):
    """Recompute script: given raw usage rows -> cost rows. Pure, offline, deterministic."""
    return [cost_row_from_usage(r, model=model, price_date=price_date) for r in usage_rows]


if __name__ == "__main__":
    demo = {"prompt_tokens": 10000, "completion_tokens": 2000,
            "prompt_tokens_details": {"cached_tokens": 4000},
            "completion_tokens_details": {"reasoning_tokens": 800}}
    # gpt-5-5 route: cached NEVER surfaces -> observed False, value None -> imputed for arithmetic
    row = cost_row_from_usage(demo, model="openai/gpt-5-5")
    print(json.dumps(row, indent=2))
    print("H1:", effective_cost_h1(demo))
