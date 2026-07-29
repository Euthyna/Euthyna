"""Skill registry and economics: signature matching, gates, and break-even arithmetic."""
from pathlib import Path

import pytest

from euthyna.cli.main import build_parser
from euthyna.skills import GATES, SkillRegistry, break_even_steps, hold_cost_tok_eq
from euthyna.skills.registry import Skill, load_skill

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def make(name="s", signature=("a",), steps=3, body="x" * 400):
    return Skill(name=name, signature=list(signature), steps_replaced=steps, body=body)


def test_hold_cost_is_write_once_read_every_later_turn():
    # 1.25*500 + 0.10*500*40
    assert hold_cost_tok_eq(500, 40) == 625 + 2000


def test_break_even_rises_with_body_size():
    small = break_even_steps(200, step_cost_tok_eq=10000)
    large = break_even_steps(2000, step_cost_tok_eq=10000)
    assert small < large
    # the RFC's headline: a 2k-token body needs to save far more than a 500-token one
    assert break_even_steps(500, 10000) < large


def test_break_even_none_when_step_cost_unknown():
    assert break_even_steps(500, step_cost_tok_eq=None) is None
    assert make().economics(None).verdict == "UNPRICED"


def test_invoking_the_skill_is_itself_a_step():
    """A one-step ritual saves nothing however often it recurs."""
    e = make(steps=1).economics(step_cost_tok_eq=10000)
    assert e.net_steps_saved == 0
    assert e.verdict == "CANNOT_PAY"
    assert make(steps=6).economics(10000).net_steps_saved == 5


def test_verdict_flips_on_the_break_even_line():
    cheap = make(steps=6, body="x" * 200).economics(10000)
    assert cheap.verdict == "PAYS"
    # same ritual, a body four times larger: hold cost overtakes the saving
    bloated = make(steps=6, body="x" * 40000).economics(10000)
    assert bloated.break_even > bloated.net_steps_saved
    assert bloated.verdict == "CANNOT_PAY"


def test_gate_failures_are_reported_with_a_basis():
    over = make(body="x" * (GATES["max_body_tokens"] * 4 + 100))
    failures = over.gate_failures()
    assert any("body" in f for f in failures)
    assert make(signature=()).gate_failures()  # no signature is a gate failure


def test_registry_matches_signature_as_a_suffix():
    reg = SkillRegistry([make(name="triple", signature=("grep", "grep", "grep"), steps=3)])
    assert [s.name for s in reg.match(["ls", "grep", "grep", "grep"])] == ["triple"]
    assert reg.match(["grep", "grep", "grep", "cat"]) == []  # ritual not just finished
    assert reg.match(["grep", "grep"]) == []


def test_registry_never_presents_more_than_the_cap():
    reg = SkillRegistry([make(name=f"s{i}", signature=("a",), steps=i + 2) for i in range(6)])
    hits = reg.match(["a"])
    assert len(hits) == GATES["max_presented_per_task"]
    assert hits[0].steps_replaced > hits[-1].steps_replaced  # best-first


def test_shipped_skills_load_and_stay_within_gates():
    reg = SkillRegistry.load(SKILLS_DIR)
    assert len(reg.skills) >= 3
    assert reg.gate_failures() == []
    for s in reg.skills:
        assert s.source, f"{s.name} must cite the corpus it was mined from"
        assert s.body_tokens <= GATES["max_body_tokens"]


def test_shipped_skills_verdicts_are_derived_not_declared():
    """The most-repeated ritual in the corpus is a one-step one, and it must come out
    CANNOT_PAY — frequency is not value."""
    reg = SkillRegistry.load(SKILLS_DIR)
    by_name = {r["name"]: r for r in reg.report(step_cost_tok_eq=7660)}
    assert by_name["swe-submit"]["verdict"] == "CANNOT_PAY"
    assert by_name["swe-patch-probe"]["verdict"] == "PAYS"


def test_front_matter_is_required(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("no front matter here")
    with pytest.raises(ValueError, match="front matter"):
        load_skill(p)
    p.write_text("---\nname: x\n---\nbody")
    with pytest.raises(ValueError, match="missing front-matter keys"):
        load_skill(p)


def test_parser_exposes_skills_command():
    args = build_parser().parse_args(["skills", "--step-cost", "9000", "--turns", "20"])
    assert (args.step_cost, args.turns, args.dir) == (9000.0, 20, "skills")


def test_measured_tokens_beat_the_estimate():
    """A footprint observed on the wire always wins over chars/4 arithmetic."""
    s = make(body="x" * 400)
    assert not s.tokens_are_measured
    estimated = s.body_tokens
    s.measured_body_tokens = 999
    assert s.tokens_are_measured and s.body_tokens == 999 != estimated


def test_estimator_carries_the_measured_correction():
    """chars/4 ran 31% low against a real document; the estimator must not
    under-price, because under-pricing admits skills that cannot pay."""
    from euthyna.skills.registry import estimate_tokens
    raw_chars_over_four = 400 * 0.25
    assert estimate_tokens("x" * 400) > raw_chars_over_four


def test_shipped_skill_records_its_measurement():
    reg = SkillRegistry.load(SKILLS_DIR)
    probe = next(s for s in reg.skills if s.name == "swe-patch-probe")
    assert probe.tokens_are_measured, "the skill we actually ran must carry its measurement"
    assert probe.body_tokens == 204
