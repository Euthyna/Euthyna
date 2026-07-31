

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


def test_anthropic_price_sheet_reproduces_the_frozen_constants():
    """The derivation is validated by reproducing the constants it replaces."""
    from euthyna.ledger import FALLBACK_STEP_WEIGHTS, weights_from_prices
    w, basis = weights_from_prices({
        "input_per_1m": 5.0, "cached_input_per_1m": 0.50,
        "cache_creation_per_1m": 6.25, "output_per_1m": 25.0})
    assert w == FALLBACK_STEP_WEIGHTS
    assert basis["cached"] == basis["output"] == "derived"


def test_another_providers_sheet_yields_different_weights():
    """DeepSeek V4-Pro: a cache read is 12x cheaper and output 2.5x cheaper than the
    Anthropic constants assume — applying those constants would misprice both."""
    from euthyna.ledger import weights_from_prices
    w, basis = weights_from_prices({
        "input_per_1m": 0.435, "cached_input_per_1m": 0.003625, "output_per_1m": 0.87})
    assert round(w["cached"], 4) == 0.0083
    assert w["output"] == 2.0
    # No cache-write price published, so that one weight stays assumed and says so.
    assert basis["cache_creation"] == "assumed"
    assert basis["cached"] == "derived"


def test_a_zero_input_price_yields_no_ratios_and_admits_it():
    """Every local model prices at $0, so no denominator exists. Falling back is fine;
    falling back silently is not."""
    from euthyna.ledger import FALLBACK_STEP_WEIGHTS, weights_from_prices
    for sheet in ({"input_per_1m": 0.0, "cached_input_per_1m": 0.0},
                  {"input_per_1m": None}, {}, None):
        w, basis = weights_from_prices(sheet)
        assert w == FALLBACK_STEP_WEIGHTS
        assert set(basis.values()) == {"assumed"}


def test_step_cost_weights_each_row_by_its_own_provider():
    from euthyna.ledger import step_cost
    tokens = {"prompt_tokens": 1000, "cached_tokens": 900,
              "cache_creation_tokens": 0, "completion_tokens": 100}
    anthropic = step_cost({"native_tokens": tokens, "list_price_per_1m": {
        "input_per_1m": 5.0, "cached_input_per_1m": 0.50,
        "cache_creation_per_1m": 6.25, "output_per_1m": 25.0}})
    deepseek = step_cost({"native_tokens": tokens, "list_price_per_1m": {
        "input_per_1m": 0.435, "cached_input_per_1m": 0.003625, "output_per_1m": 0.87}})
    # 100 uncached + 900 cached + 100 output, weighted by each provider's own ratios
    assert anthropic == round(100 + 900 * 0.10 + 100 * 5.0, 1)      # 690.0
    assert deepseek == round(100 + 900 * 0.0083333 + 100 * 2.0, 1)  # 307.5
    assert anthropic > deepseek * 2


def _rep_row(actions, digests=None, epoch="e1", session="s"):
    row = {"session": session, "ts": "1", "actions": actions, "cost": {}}
    if digests is not None:
        row["action_digests"] = digests
        row["digest_epoch"] = epoch
    return row


def test_narrowing_a_search_is_no_longer_charged_as_a_loop():
    """Three greps with three DIFFERENT commands is how a search narrows. Keyed on the
    verb they are indistinguishable from a loop, which is what overstated the published
    SWE-bench figure by 2.5x."""
    from euthyna.ledger import repetition_waste
    greps = ["bash:grep"] * 3
    assert repetition_waste([_rep_row(greps, ["a", "b", "c"])])["repeated_actions"] == 0
    assert repetition_waste([_rep_row(greps, ["a", "a", "a"])])["repeated_actions"] == 1
    # Without digests the old, coarser answer is still produced rather than a crash.
    assert repetition_waste([_rep_row(greps)])["repeated_actions"] == 1


def test_the_result_says_which_granularity_it_used():
    """A caller cannot tell 24% from 59% apart unless the measure reports its own keying."""
    from euthyna.ledger import repetition_waste
    greps = ["bash:grep"] * 3
    assert repetition_waste([_rep_row(greps)])["keyed_on"] == "verb"
    assert repetition_waste([_rep_row(greps, ["a", "b", "c"])])["keyed_on"] == "command"
    mixed = repetition_waste([_rep_row(greps), _rep_row(greps, ["a", "b", "c"])])
    assert mixed["keyed_on"] == "mixed"
    assert mixed["actions_keyed_by_digest"] == 3


def test_digests_from_two_gateway_lifetimes_are_flagged_not_merged():
    """Salts differ per process, so identical commands across epochs look distinct and
    UNDER-count repetition. Under-counting silently is the failure being prevented."""
    from euthyna.ledger import repetition_waste
    greps = ["bash:grep"] * 3
    one = repetition_waste([_rep_row(greps, ["a", "a", "a"], epoch="e1")])
    assert one["digest_epochs"] == 1 and one["digest_epochs_comparable"] is True
    two = repetition_waste([_rep_row(greps, ["a", "a", "a"], epoch="e1"),
                            _rep_row(greps, ["a", "a", "a"], epoch="e2")])
    assert two["digest_epochs"] == 2 and two["digest_epochs_comparable"] is False


def test_longest_run_reports_the_verb_not_the_digest():
    from euthyna.ledger import repetition_waste
    r = repetition_waste([_rep_row(["bash:grep"] * 4, ["a"] * 4)])
    assert r["longest_run"] == {"action": "bash:grep", "length": 4}
