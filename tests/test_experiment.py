"""Paired harness: reproducible plans, exact McNemar, and honest verdicts."""
import json

import pytest

from euthyna.cli.main import build_parser
from euthyna.experiment import (
    ExperimentSpec, RAW_ARM, SHAM_ARM, analyze, build_plan, compare,
    load_outcomes, mcnemar_exact, required_pairs,
)

SPEC = {"name": "exp", "tasks": ["t1", "t2"], "arms": ["control", "candidate"], "reps": 2}


def test_plan_is_reproducible_and_balanced():
    spec = ExperimentSpec.from_dict(SPEC)
    a, b = build_plan(spec), build_plan(spec)
    assert a == b, "same spec and seed must produce the same plan"
    # 2 tasks x 4 arms (control, candidate, raw, sham) x 2 reps
    assert len(a) == 2 * 4 * 2
    per_arm = {}
    for row in a:
        per_arm[row["arm"]] = per_arm.get(row["arm"], 0) + 1
    assert len(set(per_arm.values())) == 1, "arms must be balanced within the plan"


def test_plan_changes_with_seed_but_keeps_the_same_cells():
    base = build_plan(ExperimentSpec.from_dict(SPEC))
    other = build_plan(ExperimentSpec.from_dict({**SPEC, "seed": "different"}))
    assert {r["run_id"] for r in base} == {r["run_id"] for r in other}
    assert [r["run_id"] for r in base] != [r["run_id"] for r in other]


def test_mandatory_arms_are_added_unless_declined():
    spec = ExperimentSpec.from_dict(SPEC)
    assert SHAM_ARM in spec.all_arms and RAW_ARM in spec.all_arms
    bare = ExperimentSpec.from_dict({**SPEC, "include_sham": False,
                                     "include_raw_baseline": False})
    assert bare.all_arms == ["control", "candidate"]


def test_spec_requires_its_keys():
    with pytest.raises(ValueError, match="missing keys"):
        ExperimentSpec.from_dict({"name": "x"})


def test_mcnemar_matches_hand_computed_values():
    # 10 discordant, all favouring one arm: p = 2 * 0.5^10
    assert mcnemar_exact(10, 0) == pytest.approx(2 * 0.5 ** 10)
    # an even split is as unsurprising as possible
    assert mcnemar_exact(5, 5) == 1.0
    # no discordant pairs is an absence of evidence, not p=1
    assert mcnemar_exact(0, 0) is None


def test_required_pairs_reproduces_the_rfc_figure():
    """Planned against the published rate and split, not a round number."""
    assert required_pairs() == 650
    # a larger effect is cheaper to detect; a rarer discordant rate is dearer
    assert required_pairs(effect=0.70) < required_pairs()
    assert required_pairs(discordant_rate=0.10) > required_pairs()


def _outcomes(pattern):
    """pattern: {(task, arm): resolved}; rep 0 only."""
    return [{"task": t, "arm": a, "rep": 0, "resolved": r, "session": f"{t}-{a}"}
            for (t, a), r in pattern.items()]


def test_compare_counts_help_harm_null_not_a_mean():
    rows = _outcomes({
        ("t1", "control"): False, ("t1", "cand"): True,    # help
        ("t2", "control"): True, ("t2", "cand"): False,    # harm
        ("t3", "control"): True, ("t3", "cand"): True,     # null
        ("t4", "control"): False, ("t4", "cand"): False,   # null
    })
    r = compare(rows, "control", "cand")
    assert (r.help_count, r.harm_count, r.null_count, r.pairs) == (1, 1, 2, 4)
    assert r.discordant_rate == 0.5


def test_unmatched_cells_are_dropped_never_imputed():
    rows = _outcomes({("t1", "control"): True, ("t1", "cand"): True,
                      ("t2", "cand"): True})  # t2 has no control
    assert compare(rows, "control", "cand").pairs == 1


def test_effect_at_or_below_the_aa_floor_is_called_noise():
    rows = []
    # candidate: 2 of 10 tasks discordant; sham: the same 2 — pure noise
    for i in range(10):
        disc = i < 2
        rows += _outcomes({(f"t{i}", "control"): not disc, (f"t{i}", "cand"): True,
                           (f"t{i}", SHAM_ARM): True})
    out = analyze(rows, control="control")
    cand = next(r for r in out["results"] if r["arm_b"] == "cand")
    assert cand["verdict"] == "WITHIN_NOISE"
    assert out["floor"]["discordant_rate"] == cand["discordant_rate"]


def test_missing_baseline_arms_are_flagged():
    rows = _outcomes({("t1", "control"): True, ("t1", "cand"): True})
    out = analyze(rows, control="control")
    assert out["floor"] is None
    assert out["raw_baseline_present"] is False


def test_cost_delta_is_paired_and_optional(tmp_path):
    rows = _outcomes({("t1", "control"): True, ("t1", "cand"): True})
    costs = {"t1-control": 10000.0, "t1-cand": 7000.0}
    r = compare(rows, "control", "cand", costs=costs)
    assert r.cost_delta_tok_eq == -3000.0 and r.cost_pairs == 1
    assert compare(rows, "control", "cand").cost_delta_tok_eq is None


def test_outcomes_loader_rejects_incomplete_rows(tmp_path):
    p = tmp_path / "o.jsonl"
    p.write_text(json.dumps({"task": "t", "arm": "a", "rep": 0}) + "\n")
    with pytest.raises(ValueError, match="missing keys"):
        load_outcomes(p)


def test_parser_exposes_experiment_subcommands():
    parser = build_parser()
    assert parser.parse_args(["experiment", "plan", "s.yaml"]).experiment_command == "plan"
    a = parser.parse_args(["experiment", "analyze", "o.jsonl", "--no-cost"])
    assert (a.experiment_command, a.control, a.no_cost) == ("analyze", "control", True)
