from euthyna.core.verifier import Verifier, CommandSet, wilson_interval, default_d2_verifier
import os
from tests.conftest import FIXTURES

CS_PATH = os.path.join(FIXTURES, "command_sets.json")
CS_SHA = "test_sha"


def _always_pass(image, patch, cmd, timeout):
    return True, "ok"


def _always_fail(image, patch, cmd, timeout):
    return False, "rc=1"


def _flaky(image, patch, cmd, timeout):
    # deterministic 3-of-5 pattern via a mutable counter closure
    _flaky.i = getattr(_flaky, "i", 0) + 1
    return (_flaky.i % 2 == 1), f"trial {_flaky.i}"


def test_returns_interval_not_boolean():
    v = default_d2_verifier(CS_PATH, CS_SHA, n_trials=5)
    op = v.evaluate("django__django-12858", "some patch", "img", _always_pass, n_trials=5)
    # NOT a boolean; it's an operating point with a CI
    assert op.n_trials == 5 and op.n_pass == 5
    assert op.point == 1.0
    assert op.ci_low <= op.point <= op.ci_high
    assert hasattr(op, "ci_low") and hasattr(op, "ci_high")


def test_all_fail_interval():
    v = default_d2_verifier(CS_PATH, CS_SHA, n_trials=4)
    op = v.evaluate("django__django-12858", "patch", "img", _always_fail, n_trials=4)
    assert op.n_pass == 0 and op.point == 0.0
    assert op.ci_high > 0.0  # wilson upper bound is non-zero even at 0/4


def test_flaky_gives_intermediate_point():
    _flaky.i = 0
    v = default_d2_verifier(CS_PATH, CS_SHA, n_trials=5)
    op = v.evaluate("django__django-12858", "patch", "img", _flaky, n_trials=5)
    assert 0.0 < op.point < 1.0
    assert op.ci_low < op.point < op.ci_high


def test_unavailable_command_set():
    v = default_d2_verifier(CS_PATH, CS_SHA)
    op = v.evaluate("django__django-11820", "patch", "img", _always_pass)  # credible=False
    assert op.available is False
    assert op.detail == "ACCEPTANCE_UNAVAILABLE"


def test_empty_patch_deterministic_reject():
    v = default_d2_verifier(CS_PATH, CS_SHA, n_trials=3)
    op = v.evaluate("django__django-12858", "   ", "img", _always_pass, n_trials=3)
    assert op.point == 0.0 and op.detail == "empty_patch"


def test_wilson_bounds():
    p, lo, hi = wilson_interval(0, 10)
    assert p == 0.0 and lo == 0.0 and 0.0 < hi < 1.0
    p, lo, hi = wilson_interval(10, 10)
    assert p == 1.0 and 0.0 < lo < 1.0 and hi == 1.0
