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


def test_shipped_skills_load_and_cite_their_provenance():
    reg = SkillRegistry.load(SKILLS_DIR)
    assert len(reg.skills) >= 3
    for s in reg.skills:
        assert s.source, f"{s.name} must cite the corpus it was mined from"
        assert s.harness, f"{s.name} must record the vocabulary its signature speaks"
        assert s.body_tokens <= GATES["max_body_tokens"]


def test_the_only_gate_failure_is_the_one_we_measured():
    """`swe-patch-probe` fails the amortization gate, and it is supposed to.

    It was measured replacing 0 steps in the cost-primary run. A gate that stayed clean
    after that measurement would be a gate that ignores measurements.
    """
    reg = SkillRegistry.load(SKILLS_DIR)
    failures = reg.gate_failures()
    assert len(failures) == 1
    assert failures[0].startswith("swe-patch-probe: measured to replace 0 steps")


def test_shipped_skills_verdicts_are_derived_not_declared():
    """Frequency is not value, and neither is a step count inherited from another corpus.

    `swe-submit` is the most-repeated ritual in the mined corpus and still CANNOT_PAY.
    `swe-patch-probe` declares 6 steps replaced — enough to PAY on that number alone —
    and comes out CANNOT_PAY because it was measured replacing none.
    """
    reg = SkillRegistry.load(SKILLS_DIR)
    by_name = {r["name"]: r for r in reg.report(step_cost_tok_eq=7660)}
    assert by_name["swe-submit"]["verdict"] == "CANNOT_PAY"
    probe = by_name["swe-patch-probe"]
    assert probe["steps_declared"] == 6 and probe["steps_measured"] == 0
    assert probe["steps_basis"] == "measured"
    assert probe["verdict"] == "CANNOT_PAY"


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


def test_skills_mined_from_another_harness_can_never_fire():
    """The defect the cost-primary experiment exposed, now a gate."""
    from euthyna.skills.registry import SkillRegistry
    r = SkillRegistry.load("skills")
    dead = r.dead_triggers(["glob", "read", "edit", "bash"])   # opencode's vocabulary
    assert len(dead) == len(r.skills) and r.skills, "all three speak bash:* only"
    assert all(d["harness"] == "mini-swe-agent" for d in dead)
    assert all("can never fire here" in d["reason"] for d in dead)


def test_no_dead_triggers_in_the_harness_they_were_mined_from():
    from euthyna.skills.registry import SkillRegistry
    r = SkillRegistry.load("skills")
    assert r.dead_triggers(["bash:grep", "bash:sed", "bash:echo"]) == []


def test_a_skill_with_no_signature_is_not_reported_as_dead():
    """It fails a different gate — 'no trigger signature' — and should not double-report."""
    from euthyna.skills.registry import Skill, SkillRegistry
    s = Skill(name="x", signature=[], steps_replaced=2, body="b")
    assert SkillRegistry([s]).dead_triggers(["read"]) == []
    assert any("no trigger signature" in f for f in s.gate_failures())


def test_harness_provenance_round_trips_from_front_matter():
    from euthyna.skills.registry import load_skill
    s = load_skill("skills/swe-patch-probe.md")
    assert s.harness == "mini-swe-agent"
    assert s.vocabulary == {"bash:echo", "bash:sed"}


def test_a_measurement_overrides_the_corpus_claim_and_flips_the_verdict():
    """The whole point: PAYS on an inherited number, CANNOT_PAY on a measured one."""
    from euthyna.skills.registry import Skill
    body = "x" * 800   # ~262 tok under the corrected estimator
    declared = Skill(name="s", signature=["a"], steps_replaced=6, body=body)
    measured = Skill(name="s", signature=["a"], steps_replaced=6, body=body,
                     measured_steps_replaced=0, measured_in="cost-primary")
    assert declared.economics(8000).verdict == "PAYS"
    assert measured.economics(8000).verdict == "CANNOT_PAY"
    assert declared.effective_steps_replaced == 6
    assert measured.effective_steps_replaced == 0


def test_zero_measured_steps_is_honoured_not_treated_as_missing():
    """`or`-style precedence would read a measured 0 as absent and fall back to 6."""
    from euthyna.skills.registry import Skill
    s = Skill(name="s", signature=["a"], steps_replaced=6, body="b",
              measured_steps_replaced=0)
    assert s.effective_steps_replaced == 0
    assert s.steps_are_measured is True


def test_gate_message_names_its_basis_and_workload():
    from euthyna.skills.registry import Skill
    s = Skill(name="s", signature=["a"], steps_replaced=6, body="b",
              measured_steps_replaced=0, measured_in="cost-primary/opencode")
    failures = s.gate_failures()
    assert any("measured to replace 0 steps in cost-primary/opencode" in f for f in failures)
    d = Skill(name="s", signature=["a"], steps_replaced=0, body="b")
    assert any(f.startswith("declared to replace 0 steps —") for f in d.gate_failures())


def test_patch_probe_carries_its_measurement_on_disk():
    from euthyna.skills.registry import load_skill
    s = load_skill("skills/swe-patch-probe.md")
    assert s.steps_replaced == 6 and s.measured_steps_replaced == 0
    assert "opencode" in s.measured_in
    assert s.economics(8000).verdict == "CANNOT_PAY"
