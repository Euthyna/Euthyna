

def test_step_cost_quality_is_not_the_quality_of_the_bill():
    """A local model priced at zero has an exact $0 bill and a 10x-uncertain step."""
    from euthyna.ledger import cost_quality, step_cost_quality
    local = {
        "native_tokens": {"prompt_tokens": 8712, "cached_tokens": 0,
                          "cache_creation_tokens": None, "completion_tokens": 39},
        "observed_flags": {"prompt_tokens": True, "completion_tokens": True,
                           "cached_tokens": False, "cache_creation_tokens": False},
        "imputed_flags": {"cached_tokens": False, "cache_creation_tokens": True},
        "list_price_per_1m": {"input_per_1m": 0.0, "cached_input_per_1m": 0.0,
                              "output_per_1m": 0.0, "cache_creation_per_1m": None},
    }
    assert cost_quality(local) == "exact"                    # the dollar bill is certain
    assert step_cost_quality(local) == "estimated_under_no_cache_assumption"


def test_step_cost_quality_is_exact_when_the_cache_split_was_observed():
    from euthyna.ledger import step_cost_quality
    observed = {
        "native_tokens": {"prompt_tokens": 1000, "cached_tokens": 800,
                          "cache_creation_tokens": 0, "completion_tokens": 10},
        "observed_flags": {"cached_tokens": True, "cache_creation_tokens": True},
    }
    assert step_cost_quality(observed) == "exact"
