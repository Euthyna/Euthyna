

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


def test_observed_vocabulary_skips_unknown_rather_than_counting_it_as_empty():
    """A row with no actions key predates the tap; None means unreadable. Neither is
    an observation that no actions occurred."""
    from euthyna.ledger import observed_vocabulary
    rows = [
        {"actions": ["read", "glob"]},
        {"actions": ["bash:grep", "read"]},
        {"actions": None},          # response could not be parsed
        {"session": "s"},           # written before the actions tap existed
        {"actions": []},            # read fine, called nothing — a real observation
    ]
    assert observed_vocabulary(rows) == {"read", "glob", "bash:grep"}
    assert observed_vocabulary([]) == set()
    assert observed_vocabulary([{"actions": None}]) == set()


def test_action_coverage_separates_pre_tap_from_unreadable():
    from euthyna.ledger import action_coverage
    rows = [{"actions": ["read"]}, {"actions": []}, {"actions": None}, {"session": "s"}]
    cov = action_coverage(rows)
    assert cov == {"calls": 4, "with_actions": 2, "unreadable": 1, "pre_tap": 1}


def test_empty_vocabulary_must_not_be_read_as_all_triggers_reachable():
    """The distinction the CLI depends on: no observation is not a clean bill of health."""
    from euthyna.ledger import observed_vocabulary
    from euthyna.skills.registry import SkillRegistry
    reg = SkillRegistry.load("skills")
    vocab = observed_vocabulary([{"session": "s"}])
    assert vocab == set()
    # dead_triggers on an empty vocabulary would call everything dead, which is why the
    # CLI reports UNKNOWN instead of calling it.
    assert len(reg.dead_triggers(vocab)) == len(reg.skills)
