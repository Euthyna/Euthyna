from euthyna.experiment.calibrate import (
    TaskCalibration, calibrate, clopper_pearson_lower, schedule,
)


def _runs(task, arm, results):
    return [{"task": task, "arm": arm, "rep": i, "resolved": r}
            for i, r in enumerate(results)]


def test_three_clean_runs_do_not_establish_reliability():
    """The point of reporting the bound: 3/3 feels like proof and is not."""
    assert round(clopper_pearson_lower(3, 3), 3) == 0.368
    assert round(clopper_pearson_lower(5, 5), 3) == 0.549
    # 14 clean runs is what an 0.80 claim actually costs.
    assert clopper_pearson_lower(14, 14) > 0.80
    assert clopper_pearson_lower(13, 13) < 0.80


def test_lower_bound_is_zero_without_a_success():
    assert clopper_pearson_lower(0, 10) == 0.0
    assert clopper_pearson_lower(3, 0) == 0.0


def test_partial_success_bound_sits_below_the_point_estimate():
    lo = clopper_pearson_lower(8, 10)
    assert 0.0 < lo < 0.8


def test_never_solved_task_is_excluded_not_merely_weak():
    """The pilot's regime. Nothing is held constant, so there is no cost question."""
    c = TaskCalibration(task="hard", baseline_solved=0, baseline_runs=3)
    assert c.verdict() == "EXCLUDE_NEVER_SOLVED"
    assert c.pairs_to_schedule is None


def test_reliable_task_is_eligible_and_needs_few_extra_pairs():
    c = TaskCalibration(task="easy", baseline_solved=5, baseline_runs=5)
    assert c.verdict() == "ELIGIBLE"
    assert c.yield_rate == 1.0
    assert c.pairs_to_schedule == 13


def test_unreliable_task_costs_pairs_rather_than_validity():
    """Yield loss inflates the schedule; it does not bias the estimate."""
    c = TaskCalibration(task="flaky", baseline_solved=3, baseline_runs=4)
    assert c.verdict() == "MARGINAL"
    assert c.yield_rate == 0.5625
    assert c.pairs_to_schedule == 24  # ceil(13 / 0.5625)


def test_low_yield_task_is_excluded():
    c = TaskCalibration(task="coinflip", baseline_solved=2, baseline_runs=3)
    assert c.verdict() == "EXCLUDE_LOW_YIELD"  # 0.444 < MIN_YIELD


def test_candidate_rate_replaces_the_baseline_guess_once_measured():
    c = TaskCalibration(task="t", baseline_solved=4, baseline_runs=4,
                        candidate_solved=2, candidate_runs=4)
    assert c.yield_rate == 0.5
    assert c.pairs_to_schedule == 26


def test_calibrate_sorts_worst_yield_first():
    rows = (_runs("good", "control", [True, True, True])
            + _runs("bad", "control", [False, False, False])
            + _runs("mid", "control", [True, True, False]))
    out = calibrate(rows)
    assert [c.task for c in out] == ["bad", "mid", "good"]
    assert out[0].verdict() == "EXCLUDE_NEVER_SOLVED"
    assert out[-1].verdict() == "ELIGIBLE"


def test_calibrate_ignores_arms_that_were_not_asked_for():
    rows = _runs("t", "control", [True, True]) + _runs("t", "aa_sham", [False, False])
    out = calibrate(rows, baseline_arm="control")
    assert len(out) == 1 and out[0].baseline_runs == 2 and out[0].candidate_rate is None


def test_schedule_reports_nothing_to_price_when_no_task_qualifies():
    out = schedule(calibrate(_runs("hard", "control", [False, False, False])))
    assert out["eligible_tasks"] == 0
    assert "nothing to price" in out["note"]


def test_schedule_splits_target_across_eligible_tasks_and_inflates_for_yield():
    rows = (_runs("a", "control", [True, True, True])
            + _runs("b", "control", [True, True, True])
            + _runs("dead", "control", [False, False, False]))
    out = schedule(calibrate(rows), target_pairs=13)
    assert out["eligible_tasks"] == 2 and out["excluded_tasks"] == 1
    assert out["pairs_per_task"] == 7          # ceil(13 / 2)
    assert out["total_runs"] == 28             # both at full yield, two runs per pair
