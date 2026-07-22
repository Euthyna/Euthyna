#!/usr/bin/env python3
"""euthyna.verifier — pluggable acceptance-suite interface (B4).

A Verifier takes (patch, command_set, timeout) and returns an OPERATING-POINT INTERVAL:
a success-rate point estimate plus a confidence interval (NOT a boolean). This is the product's
statistical contract: an acceptance gate reports where on the success-rate axis a patch lands, with
uncertainty, rather than a single accept/reject bit.

The command runner is INJECTED (runner_fn(image_ref, patch, cmd, timeout) -> (passed, detail)), so
the exec mechanism (podman overlay, mock, remote) is swappable. Ported from hooks.AcceptanceGate but
returns an interval by running the command set n_trials times.
"""
import json
import math
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Dict, Any


@dataclass
class OperatingPoint:
    """Success-rate estimate + CI. Never collapse to a boolean at the interface."""
    n_trials: int
    n_pass: int
    point: float                 # MLE success rate
    ci_low: float
    ci_high: float
    ci_method: str = "wilson"
    detail: str = ""
    available: bool = True
    command_set_id: Optional[str] = None
    command_set_sha: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_trials": self.n_trials, "n_pass": self.n_pass, "point": self.point,
            "ci_low": self.ci_low, "ci_high": self.ci_high, "ci_method": self.ci_method,
            "available": self.available, "command_set_id": self.command_set_id,
            "command_set_sha": self.command_set_sha, "detail": self.detail[:400],
        }


def wilson_interval(n_pass, n_trials, z=1.96):
    """Wilson score interval for a binomial proportion. Robust at n_pass in {0, n_trials}."""
    if n_trials == 0:
        return (0.0, 0.0, 1.0)
    p = n_pass / n_trials
    denom = 1 + z * z / n_trials
    center = (p + z * z / (2 * n_trials)) / denom
    half = (z * math.sqrt((p * (1 - p) + z * z / (4 * n_trials)) / n_trials)) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


@dataclass
class CommandSet:
    """A frozen acceptance command set bound to a task (the 'D2 command set' concept)."""
    command_set_id: str
    commands: Dict[str, Dict[str, Any]]     # task_id -> {"D2": {"cmd":..., "kind":..., "credible":True}}
    sha256: str
    kind_key: str = "D2"
    timeout: int = 120

    def for_task(self, task_id):
        blk = self.commands.get(task_id, {})
        d2 = blk.get(self.kind_key) if isinstance(blk, dict) else None
        if not d2 or not d2.get("credible") or not d2.get("cmd"):
            return None
        return d2


class Verifier:
    """Pluggable acceptance-suite verifier. Runs the command set n_trials times through an injected
    runner and returns an OperatingPoint interval. Never mutates a persistent testbed (contract of
    the injected runner)."""

    def __init__(self, command_set: CommandSet, n_trials: int = 1):
        self.cs = command_set
        self.n_trials = n_trials

    def evaluate(self, task_id, patch, image_ref, runner_fn: Callable,
                 n_trials: Optional[int] = None) -> OperatingPoint:
        n = n_trials or self.n_trials
        d2 = self.cs.for_task(task_id)
        if d2 is None:
            return OperatingPoint(0, 0, 0.0, 0.0, 0.0, available=False,
                                  detail="ACCEPTANCE_UNAVAILABLE",
                                  command_set_id=self.cs.command_set_id, command_set_sha=self.cs.sha256)
        if not (patch and patch.strip()):
            # empty patch is a deterministic reject at rate 0 with zero-width CI
            return OperatingPoint(n, 0, 0.0, 0.0, 0.0, detail="empty_patch",
                                  command_set_id=self.cs.command_set_id, command_set_sha=self.cs.sha256)
        cmd = d2["cmd"]
        n_pass = 0
        last_detail = ""
        for _ in range(n):
            passed, detail = runner_fn(image_ref, patch, cmd, self.cs.timeout)
            n_pass += 1 if passed else 0
            last_detail = detail
        point, lo, hi = wilson_interval(n_pass, n)
        return OperatingPoint(n, n_pass, point, lo, hi, detail=last_detail,
                              command_set_id=self.cs.command_set_id, command_set_sha=self.cs.sha256)


# ---- default: a D2-command-set-bound verifier factory ----
def default_d2_verifier(command_sets_path, command_sets_sha, command_set_id="D2", n_trials=1,
                        timeout=120):
    with open(command_sets_path) as f:
        commands = json.load(f)
    cs = CommandSet(command_set_id=command_set_id, commands=commands,
                    sha256=command_sets_sha, kind_key="D2", timeout=timeout)
    return Verifier(cs, n_trials=n_trials)
