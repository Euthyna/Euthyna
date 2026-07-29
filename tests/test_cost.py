

def test_cost_of_prefers_session_then_falls_back_to_run_id():
    from euthyna.experiment.cost import cost_of
    assert cost_of({"session": "s1"}, {"s1": 10.0}) == 10.0
    assert cost_of({"run_id": "t::a::0"}, {"t::a::0": 7.0}) == 7.0
    assert cost_of({"session": "s1", "run_id": "r"}, {"s1": 1.0, "r": 2.0}) == 1.0
    assert cost_of({"run_id": "r"}, None) is None
    assert cost_of({"run_id": "missing"}, {"r": 1.0}) is None


def test_cost_of_treats_zero_as_a_real_cost_not_a_miss():
    """`or`-style lookup would fall through to run_id here and report the wrong run."""
    from euthyna.experiment.cost import cost_of
    assert cost_of({"session": "s1", "run_id": "r"}, {"s1": 0.0, "r": 99.0}) == 0.0


def test_skew_is_flagged_when_median_and_total_disagree():
    """Most pairs cost more, one pair costs far less: the total lies, the median does not."""
    from euthyna.experiment.cost import compare_cost
    out, costs = [], {}
    deltas = [200, 200, 200, -5000]
    for i, d in enumerate(deltas):
        out += [{"task": f"t{i}", "arm": "control", "rep": 0, "resolved": True,
                 "run_id": f"a{i}"},
                {"task": f"t{i}", "arm": "cand", "rep": 0, "resolved": True,
                 "run_id": f"b{i}"}]
        costs[f"a{i}"] = 10_000.0
        costs[f"b{i}"] = 10_000.0 + d
    r = compare_cost(out, "control", "cand", costs)
    assert r.median_delta > 0 and r.relative_delta < 0
    assert r.skewed is True
    # 4 pairs cannot support a cost claim whichever way the numbers lean.
    assert r.verdict() == "UNDERPOWERED"


def test_skew_is_not_flagged_when_they_agree():
    from euthyna.experiment.cost import compare_cost
    out, costs = [], {}
    for i, d in enumerate([200, 300, 250, 400]):
        out += [{"task": f"t{i}", "arm": "control", "rep": 0, "resolved": True,
                 "run_id": f"a{i}"},
                {"task": f"t{i}", "arm": "cand", "rep": 0, "resolved": True,
                 "run_id": f"b{i}"}]
        costs[f"a{i}"], costs[f"b{i}"] = 10_000.0, 10_000.0 + d
    assert compare_cost(out, "control", "cand", costs).skewed is False
