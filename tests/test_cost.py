

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
