

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


def _arow(session, actions, prompt=1000, completion=10, ts="2026-01-01T00:00:00"):
    return {"session": session, "ts": ts, "actions": actions,
            "cost": {"native_tokens": {"prompt_tokens": prompt, "cached_tokens": 0,
                                       "cache_creation_tokens": 0,
                                       "completion_tokens": completion}}}


def test_repetition_waste_charges_from_the_third_occurrence():
    """Two identical actions are ordinary narrowing; the third is where progress stopped."""
    from euthyna.ledger import repetition_waste
    rows = [_arow("s", ["grep"], ts=f"2026-01-01T00:00:0{i}") for i in range(5)]
    w = repetition_waste(rows)
    assert w["actions"] == 5
    assert w["repeated_actions"] == 3          # occurrences 3, 4, 5
    assert w["longest_run"] == {"action": "grep", "length": 5}


def test_a_broken_run_restarts_the_count():
    from euthyna.ledger import repetition_waste
    rows = [_arow("s", [a], ts=f"2026-01-01T00:00:0{i}")
            for i, a in enumerate(["grep", "grep", "cat", "grep", "grep"])]
    assert repetition_waste(rows)["repeated_actions"] == 0
    assert repetition_waste(rows)["longest_run"]["length"] == 2


def test_repetition_is_measured_within_a_session_not_across():
    """Two agents each grepping twice is not one agent grepping four times."""
    from euthyna.ledger import repetition_waste
    rows = [_arow("a", ["grep"]), _arow("a", ["grep"]),
            _arow("b", ["grep"]), _arow("b", ["grep"])]
    w = repetition_waste(rows)
    assert w["repeated_actions"] == 0 and w["sessions_with_actions"] == 2


def test_rows_without_actions_are_skipped_not_assumed_clean():
    from euthyna.ledger import repetition_waste
    rows = [_arow("s", ["grep"]), {"session": "s", "ts": "x"},
            {"session": "s", "ts": "y", "actions": None}]
    assert repetition_waste(rows)["actions"] == 1


def test_empty_ledger_reports_no_fractions_rather_than_zero():
    from euthyna.ledger import repetition_waste
    w = repetition_waste([])
    assert w["actions"] == 0
    assert w["repeated_fraction"] is None and w["repeated_cost_fraction"] is None
