"""Which tasks can a cost experiment even be run on.

`compare_cost` compares spend only on pairs where *both* arms solved, and drops the
rest. That single rule decides what calibration is for. An unreliable task does not
bias the cost estimate — its bad pairs are discarded, not averaged in. It costs
*pairs*. So baseline reliability is a power question, not a validity question, and the
answer it produces is a number rather than a verdict: how many pairs must be scheduled
to end up with the ones that count.

    usable pairs  =  scheduled  x  P(both arms solve)
    scheduled     =  target / (p_a . p_b)

Treating the two arms as independent understates the yield, because the same task and
seed make the arms succeed and fail together; the true joint rate is at or above the
product. Scheduling from the product therefore errs toward running too many pairs,
which is the direction that cannot invalidate a result.

The other half is honesty about small n. Three clean runs feel like proof and are not:
3/3 puts the exact one-sided 95% lower bound on the solve rate at 0.37, so a task that
truly solves half the time clears 3/3 more than one run in ten. This module reports
that bound next to the point estimate so the gap is visible rather than assumed away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# Below this joint yield a task is excluded. Unlike the RFC-002 gates, this threshold
# is a budget choice rather than a measurement: at 0.5 the schedule doubles, which is
# the most inflation the 50x advantage over the binary endpoint absorbs comfortably.
MIN_YIELD = 0.5
DEFAULT_TARGET_PAIRS = 13  # required_pairs_cost(0.8), RFC-002 §5.1


def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Exact; n here is single digits."""
    if k <= 0:
        return 1.0
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def clopper_pearson_lower(successes: int, trials: int, alpha: float = 0.05) -> float:
    """Exact one-sided lower confidence bound on a solve rate.

    Bisection on the binomial survival function — the inverse beta this needs is not in
    the stdlib, and a dependency for one monotone root-find is not worth it.
    """
    if trials <= 0 or successes <= 0:
        return 0.0
    if successes >= trials:
        return alpha ** (1.0 / trials)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binom_sf(successes, trials, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


@dataclass
class TaskCalibration:
    task: str
    baseline_solved: int
    baseline_runs: int
    candidate_solved: Optional[int] = None
    candidate_runs: int = 0
    target_pairs: int = DEFAULT_TARGET_PAIRS

    @property
    def baseline_rate(self) -> float:
        return self.baseline_solved / self.baseline_runs if self.baseline_runs else 0.0

    @property
    def baseline_lower_95(self) -> float:
        return clopper_pearson_lower(self.baseline_solved, self.baseline_runs)

    @property
    def candidate_rate(self) -> Optional[float]:
        if self.candidate_solved is None or not self.candidate_runs:
            return None
        return self.candidate_solved / self.candidate_runs

    @property
    def yield_rate(self) -> float:
        """Conservative P(both arms solve).

        With no candidate observations yet, the baseline rate is used for both arms —
        the honest guess before an intervention has been measured, and one this will
        replace as soon as it has.
        """
        other = self.candidate_rate
        return self.baseline_rate * (self.baseline_rate if other is None else other)

    @property
    def pairs_to_schedule(self) -> Optional[int]:
        y = self.yield_rate
        return math.ceil(self.target_pairs / y) if y > 0 else None

    def verdict(self) -> str:
        if self.baseline_solved == 0:
            # The pilot's regime: nothing to hold constant, so nothing to price.
            return "EXCLUDE_NEVER_SOLVED"
        if self.yield_rate < MIN_YIELD:
            return "EXCLUDE_LOW_YIELD"
        if self.baseline_solved < self.baseline_runs:
            return "MARGINAL"
        return "ELIGIBLE"

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "baseline_rate": round(self.baseline_rate, 3),
            "baseline_lower_95": round(self.baseline_lower_95, 3),
            "baseline_runs": self.baseline_runs,
            "candidate_rate": (None if self.candidate_rate is None
                               else round(self.candidate_rate, 3)),
            "yield_rate": round(self.yield_rate, 3),
            "pairs_to_schedule": self.pairs_to_schedule,
            "verdict": self.verdict(),
        }


def calibrate(outcomes: list, baseline_arm: str = "control",
              candidate_arm: Optional[str] = None,
              target_pairs: int = DEFAULT_TARGET_PAIRS) -> list:
    """Per-task eligibility from calibration runs, worst yield first."""
    tasks: dict = {}
    for row in outcomes:
        task, arm = row.get("task"), row.get("arm")
        if task is None or arm not in (baseline_arm, candidate_arm):
            continue
        t = tasks.setdefault(task, {"b": [0, 0], "c": [0, 0]})
        slot = t["b"] if arm == baseline_arm else t["c"]
        slot[0] += bool(row.get("resolved"))
        slot[1] += 1
    out = []
    for task, t in tasks.items():
        out.append(TaskCalibration(
            task=task,
            baseline_solved=t["b"][0], baseline_runs=t["b"][1],
            candidate_solved=t["c"][0] if t["c"][1] else None,
            candidate_runs=t["c"][1],
            target_pairs=target_pairs,
        ))
    return sorted(out, key=lambda c: c.yield_rate)


def schedule(calibrations: list, target_pairs: int = DEFAULT_TARGET_PAIRS) -> dict:
    """What a cost experiment over the eligible tasks would actually cost to run."""
    usable = [c for c in calibrations if c.verdict() in ("ELIGIBLE", "MARGINAL")]
    if not usable:
        return {"eligible_tasks": 0, "pairs_per_task": None, "total_runs": None,
                "note": "no task clears the yield floor — nothing to price"}
    per_task = math.ceil(target_pairs / len(usable))
    total = sum(math.ceil(per_task / c.yield_rate) for c in usable)
    return {
        "eligible_tasks": len(usable),
        "excluded_tasks": len(calibrations) - len(usable),
        "pairs_per_task": per_task,
        "scheduled_pairs": sum(math.ceil(per_task / c.yield_rate) for c in usable),
        "total_runs": total * 2,  # a pair is two runs
    }
