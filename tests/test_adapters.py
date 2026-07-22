import os, json
from euthyna.core.adapters import SweAgentAdapter, OpenHandsAdapter
from tests.conftest import FIXTURES


def test_both_adapters_same_internal_shape():
    swe = SweAgentAdapter().parse_file(os.path.join(FIXTURES, "sweagent_matching.traj"),
                                       task_id="django__django-12858")
    oh = OpenHandsAdapter().parse_file(os.path.join(FIXTURES, "openhands_eventlog.json"),
                                       task_id="django__django-12858")
    # both map to the SAME internal Trajectory shape
    assert swe.shape() == oh.shape(), f"\nSWE: {swe.shape()}\nOH:  {oh.shape()}"


def test_sweagent_fields():
    swe = SweAgentAdapter().parse_file(os.path.join(FIXTURES, "sweagent_matching.traj"))
    assert swe.task_id == "django__django-12858"
    assert swe.exit_status == "submitted"
    assert swe.submitted_patch.startswith("diff --git")
    assert swe.empty_patch is False
    assert swe.usage["prompt_tokens"] == 12000
    # observation steps carry OBSERVATION: text
    obs = [s for s in swe.steps if s.is_observation]
    assert len(obs) == 2 and all("OBSERVATION:" in s.text for s in obs)


def test_openhands_fields():
    oh = OpenHandsAdapter().parse_file(os.path.join(FIXTURES, "openhands_eventlog.json"))
    assert oh.exit_status == "submitted"
    assert oh.submitted_patch.startswith("diff --git")
    obs = [s for s in oh.steps if s.is_observation]
    assert len(obs) == 2 and all("OBSERVATION:" in s.text for s in obs)
    assert oh.usage["prompt_tokens"] == 12000


def test_openhands_roles_mapped():
    oh = OpenHandsAdapter().parse_file(os.path.join(FIXTURES, "openhands_eventlog.json"))
    roles = [s.role for s in oh.steps]
    assert roles[0] == "system"
    assert roles[1] == "user"
    assert "assistant" in roles and "tool" in roles
