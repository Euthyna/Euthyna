

def test_baseline_check_flags_a_control_that_solves_nothing():
    """The condition that invalidated the first pilot, now visible in the output."""
    from euthyna.experiment.analyze import analyze, baseline_check
    rows = [{"task": "t", "arm": "control", "rep": i, "resolved": False} for i in range(3)]
    rows += [{"task": "t", "arm": "candidate", "rep": i, "resolved": True} for i in range(3)]
    b = baseline_check(rows, "control")
    assert b["status"] == "never_solves" and b["solved"] == 0
    assert "measures capability" in b["note"]
    assert analyze(rows, control="control")["baseline"]["status"] == "never_solves"


def test_baseline_check_flags_a_saturated_binary_endpoint():
    from euthyna.experiment.analyze import baseline_check
    rows = [{"task": "t", "arm": "control", "rep": i, "resolved": True} for i in range(4)]
    b = baseline_check(rows, "control")
    assert b["status"] == "always_solves" and "cost endpoint" in b["note"]


def test_baseline_check_is_quiet_when_the_control_is_usable():
    from euthyna.experiment.analyze import baseline_check
    rows = [{"task": "t", "arm": "control", "rep": i, "resolved": i < 2} for i in range(3)]
    assert baseline_check(rows, "control")["status"] == "ok"


def test_baseline_check_reports_an_absent_control_rather_than_zero():
    from euthyna.experiment.analyze import baseline_check
    b = baseline_check([{"task": "t", "arm": "candidate", "rep": 0, "resolved": True}], "control")
    assert b["status"] == "absent" and b["runs"] == 0
