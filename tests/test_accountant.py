import math
from euthyna.core.accountant import cost_row_from_usage, effective_cost_h1, recompute


def test_gpt55_never_fabricates_cache_fields():
    """CRITICAL: gpt-5-5 route exposes NO cached_tokens and NO cache-creation. Even if a caller
    passes cached_tokens in usage, the schema says the route does not surface it -> observed=False
    and value must NOT be fabricated into a positive cost line beyond the imputed-0 arithmetic path."""
    demo = {"prompt_tokens": 10000, "completion_tokens": 2000,
            "prompt_tokens_details": {"cached_tokens": 4000},
            "completion_tokens_details": {"reasoning_tokens": 800}}
    row = cost_row_from_usage(demo, model="openai/gpt-5-5")
    # cache-creation: never fabricated, always None
    assert row["native_tokens"]["cache_creation_tokens"] is None
    assert row["observed_flags"]["cache_creation_tokens"] is False
    # cached_tokens: route does NOT surface -> observed False (NOT True), value not counted as observed
    assert row["observed_flags"]["cached_tokens"] is False
    # reasoning DOES surface on this route
    assert row["observed_flags"]["reasoning_tokens"] is True
    # list cost computed only from prompt+completion (cache unobserved -> treated as uncached)
    assert row["list_cost_usd"] is not None


def test_provider_that_surfaces_cache():
    """A provider whose schema DOES surface cache reads/creation records observed=True when present."""
    demo = {"prompt_tokens": 10000, "completion_tokens": 2000,
            "prompt_tokens_details": {"cached_tokens": 4000, "cache_creation_tokens": 500}}
    row = cost_row_from_usage(demo, model="anthropic/claude-cache")
    assert row["observed_flags"]["cached_tokens"] is True
    assert row["observed_flags"]["cache_creation_tokens"] is True
    assert row["native_tokens"]["cached_tokens"] == 4000
    assert row["native_tokens"]["cache_creation_tokens"] == 500


def test_missing_but_surfaceable_is_imputed():
    """If a provider CAN surface cached_tokens but omitted it on this call -> observed False, imputed True."""
    demo = {"prompt_tokens": 10000, "completion_tokens": 2000}  # no cache details
    row = cost_row_from_usage(demo, model="anthropic/claude-cache")
    assert row["observed_flags"]["cached_tokens"] is False
    assert row["imputed_flags"]["cached_tokens"] is True


def test_incomplete_usage_yields_none_cost():
    row = cost_row_from_usage({"prompt_tokens": 100}, model="openai/gpt-5-5")  # no completion
    assert row["list_cost_usd"] is None


def test_effective_cost_h1_frozen_weights():
    demo = {"prompt_tokens": 10000, "completion_tokens": 2000,
            "prompt_tokens_details": {"cached_tokens": 4000}}
    # H1 = 6000*1 + 4000*0.1 + 2000*5 = 16400
    assert abs(effective_cost_h1(demo) - 16400) < 1e-6


def test_anthropic_cache_creation_not_double_billed():
    """Normalized prompt_tokens includes cache reads AND creation writes; creation must be
    billed once at cache_creation rate, not also at input rate. True bill at claude-cache
    list prices for (input 1000, read 8000, creation 2000, output 500) is $0.0204."""
    usage = {"prompt_tokens": 11000, "completion_tokens": 500,
             "prompt_tokens_details": {"cached_tokens": 8000, "cache_creation_tokens": 2000}}
    row = cost_row_from_usage(usage, model="anthropic/claude-cache")
    assert row["native_tokens"]["uncached_prompt_tokens"] == 1000
    expected = 1000 * 3.00 / 1e6 + 8000 * 0.30 / 1e6 + 2000 * 3.75 / 1e6 + 500 * 15.00 / 1e6
    assert abs(row["list_cost_usd"] - expected) < 1e-9  # 0.0204


def test_unpriced_cache_creation_refuses_total(registries):
    """Creation tokens present but cache_creation_per_1m is null: a total would silently
    undercount, so list_cost_usd stays None with the reason on record."""
    from euthyna.core import accountant
    accountant.PROVIDER_CACHE_SCHEMAS["test/unpriced-cc"] = {
        "cached_tokens": {"surfaces": True, "path": ("prompt_tokens_details", "cached_tokens")},
        "cache_creation_tokens": {"surfaces": True,
                                  "path": ("prompt_tokens_details", "cache_creation_tokens")},
        "reasoning_tokens": {"surfaces": False, "path": None},
    }
    accountant.PRICE_SHEET["2026-07-15"]["test/unpriced-cc"] = {
        "input_per_1m": 1.0, "cached_input_per_1m": 0.1, "output_per_1m": 5.0,
        "cache_creation_per_1m": None, "notes": "test"}
    usage = {"prompt_tokens": 1000, "completion_tokens": 10,
             "prompt_tokens_details": {"cached_tokens": 100, "cache_creation_tokens": 50}}
    row = cost_row_from_usage(usage, model="test/unpriced-cc")
    assert row["list_cost_usd"] is None
    assert "cache_creation" in row["list_cost_note"]
    # without creation tokens the same route still prices normally
    usage2 = {"prompt_tokens": 1000, "completion_tokens": 10,
              "prompt_tokens_details": {"cached_tokens": 100}}
    assert cost_row_from_usage(usage2, model="test/unpriced-cc")["list_cost_usd"] is not None


def test_recompute_batch():
    rows = recompute([{"prompt_tokens": 100, "completion_tokens": 50}] * 3)
    assert len(rows) == 3
    assert all(r["list_cost_usd"] is not None for r in rows)
