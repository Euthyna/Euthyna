

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


def test_overlapping_run_windows_are_left_unpriced_not_double_counted(tmp_path, monkeypatch):
    """Parallel workers interleave windows; a call in two windows belongs to one run."""
    import json
    from euthyna.experiment.analyze import overlapping_runs, window_costs
    home = tmp_path / "eu"
    (home / "ledger").mkdir(parents=True)
    (home / "ledger" / "2026-01-01.jsonl").write_text(json.dumps({
        "ts": 150.0, "session": "s",
        "cost": {"native_tokens": {"prompt_tokens": 1000, "cached_tokens": 0,
                                   "cache_creation_tokens": 0, "completion_tokens": 10}}}) + "\n")
    monkeypatch.setenv("EUTHYNA_HOME", str(home))

    overlap = [{"run_id": "a", "started_at": 100.0, "ended_at": 200.0},
               {"run_id": "b", "started_at": 140.0, "ended_at": 260.0}]
    assert overlapping_runs(overlap) == {"a", "b"}
    assert window_costs(overlap, ["2026-01-01"]) == {}      # unpriced, not 1050 each

    serial = [{"run_id": "a", "started_at": 100.0, "ended_at": 120.0},
              {"run_id": "b", "started_at": 140.0, "ended_at": 260.0}]
    assert overlapping_runs(serial) == set()
    assert window_costs(serial, ["2026-01-01"]) == {"a": 0, "b": 1050.0}


def test_touching_windows_are_not_treated_as_overlapping():
    """One run ending exactly when the next starts is serial, not parallel."""
    from euthyna.experiment.analyze import overlapping_runs
    assert overlapping_runs([{"run_id": "a", "started_at": 0.0, "ended_at": 10.0},
                             {"run_id": "b", "started_at": 10.0, "ended_at": 20.0}]) == {"a", "b"}


def test_overlap_detection_ignores_runs_with_no_window():
    from euthyna.experiment.analyze import overlapping_runs
    rows = [{"run_id": "a", "started_at": 0.0, "ended_at": 10.0},
            {"run_id": "b"}, {"started_at": 1.0, "ended_at": 2.0}]
    assert overlapping_runs(rows) == set()
