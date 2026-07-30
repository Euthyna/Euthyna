"""Cost-primary analysis: hold the outcome constant, measure the spend.

The binary endpoint answers "did it work". On tasks the baseline already solves that
question is settled, and the interesting one is "what did it cost" — which is a
continuous, paired quantity and therefore far cheaper to measure:

    binary resolve, exact McNemar        ~650 paired runs for 80% power
    paired cost, Wilcoxon signed-rank     ~15-25 paired runs for a moderate effect

Every run contributes its full magnitude instead of one bit, and each task is compared
against itself, so between-task variance — which is the dominant term in agent work —
cancels entirely.

The corresponding discipline: cost is only comparable where the outcome matched.
A run that failed cheaply did not save anything, so pairs are restricted to those
**both arms solved**, and the resolve rate is carried alongside as a non-inferiority
guard rather than dropped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def _rank(values: list) -> list:
    """Ranks with ties averaged."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def cost_of(row: dict, costs: Optional[dict]) -> Optional[float]:
    """A run's cost, keyed by session when one was recorded and by run_id otherwise.

    Zero is a legitimate cost, so membership is tested rather than truthiness.
    """
    if not costs:
        return None
    for key in (row.get("session"), row.get("run_id")):
        if key is not None and key in costs:
            return costs[key]
    return None


def wilcoxon_signed_rank(deltas: list) -> Optional[float]:
    """Two-sided p-value for paired differences; exact below 20 pairs.

    Zero differences are dropped (Wilcoxon's own convention) — a pair that cost
    exactly the same carries no evidence either way. Returns None when nothing
    non-zero survives, because that is an absence of evidence, not a p of 1.
    """
    nz = [d for d in deltas if d != 0]
    n = len(nz)
    if n == 0:
        return None
    ranks = _rank([abs(d) for d in nz])
    w_plus = sum(r for d, r in zip(nz, ranks) if d > 0)
    w = min(w_plus, n * (n + 1) / 2 - w_plus)

    if n <= 20:  # exact: enumerate every sign assignment
        count = 0
        for mask in range(1 << n):
            s = sum(i + 1 for i in range(n) if mask >> i & 1)
            if s <= w:
                count += 1
        return min(1.0, 2 * count / (1 << n))
    mean = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w - mean) / sd if sd else 0.0
    return min(1.0, 2 * 0.5 * math.erfc(abs(z) / math.sqrt(2)))


@dataclass
class CostResult:
    """Paired cost comparison on tasks both arms solved."""

    arm_a: str
    arm_b: str
    pairs: int                    # concordant-solved pairs actually compared
    dropped_discordant: int       # outcome differed: cost is not comparable
    median_delta: Optional[float]
    mean_delta: Optional[float]
    relative_delta: Optional[float]
    p_value: Optional[float]
    # Pairs where both arms solved but at least one run had no cost. Counted separately
    # because a vanished pair and a pair that never existed look identical in `pairs`,
    # and the difference is the whole story when the cost source could not attribute.
    unpriced: int = 0
    resolve_a: int = 0
    resolve_b: int = 0
    n_tasks: int = 0

    @property
    def skewed(self) -> bool:
        """Do the per-pair median and the total-weighted change point opposite ways?

        `median_delta` is the middle pair; `relative_delta` is the sum over the sum. One
        pair costing far less than the rest can drag the total negative while most pairs
        got more expensive. When they disagree the distribution is skewed and the median
        is the one to trust — which is why the verdict reads it, not the total.
        """
        if self.median_delta is None or self.relative_delta is None:
            return False
        return (self.median_delta > 0) != (self.relative_delta > 0) and \
            self.median_delta != 0 and self.relative_delta != 0

    @property
    def resolve_guard(self) -> str:
        """A cost win is only a win if quality did not fall with it."""
        if self.resolve_b > self.resolve_a:
            return "improved"
        if self.resolve_b == self.resolve_a:
            return "held"
        return "REGRESSED"

    def verdict(self, alpha: float = 0.05) -> str:
        if self.resolve_guard == "REGRESSED":
            return "QUALITY_REGRESSED"
        if self.pairs == 0 and self.unpriced:
            # Not "no effect" and not "too few runs": the runs happened and the cost
            # source could not attribute them. Saying UNDERPOWERED here would blame the
            # sample size for a plumbing failure.
            return "UNPRICED"
        if self.p_value is None or self.pairs < 6:
            return "UNDERPOWERED"
        if self.p_value > alpha:
            return "NO_COST_DIFFERENCE"
        return "CHEAPER" if (self.median_delta or 0) < 0 else "MORE_EXPENSIVE"

    def as_dict(self) -> dict:
        return {
            "arm_a": self.arm_a, "arm_b": self.arm_b, "pairs": self.pairs,
            "dropped_discordant": self.dropped_discordant,
            "unpriced": self.unpriced,
            "median_delta": self.median_delta, "mean_delta": self.mean_delta,
            "relative_delta": self.relative_delta, "p_value": self.p_value,
            "resolve_a": self.resolve_a, "resolve_b": self.resolve_b,
            "n_tasks": self.n_tasks, "resolve_guard": self.resolve_guard,
            "skewed": self.skewed,
            "verdict": self.verdict(),
        }


def compare_cost(outcomes: list, arm_a: str, arm_b: str, costs: dict) -> CostResult:
    index = {(r["task"], r["arm"], r["rep"]): r for r in outcomes}
    cells = sorted({(r["task"], r["rep"]) for r in outcomes})
    deltas, base = [], []
    unpriced = 0
    dropped = res_a = res_b = n_tasks = 0
    for task, rep in cells:
        a, b = index.get((task, arm_a, rep)), index.get((task, arm_b, rep))
        if a is None or b is None:
            continue
        n_tasks += 1
        res_a += bool(a["resolved"])
        res_b += bool(b["resolved"])
        if not (a["resolved"] and b["resolved"]):
            dropped += 1          # cost of a failure is not comparable to cost of a solve
            continue
        ca, cb = cost_of(a, costs), cost_of(b, costs)
        if ca is None or cb is None:
            unpriced += 1
            continue
        deltas.append(cb - ca)
        base.append(ca)
    median = mean = rel = None
    if deltas:
        s = sorted(deltas)
        n = len(s)
        median = round(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, 1)
        mean = round(sum(deltas) / n, 1)
        rel = round(sum(deltas) / sum(base), 4) if sum(base) else None
    return CostResult(arm_a=arm_a, arm_b=arm_b, pairs=len(deltas),
                      dropped_discordant=dropped, unpriced=unpriced,
                      median_delta=median, mean_delta=mean,
                      relative_delta=rel, p_value=wilcoxon_signed_rank(deltas),
                      resolve_a=res_a, resolve_b=res_b, n_tasks=n_tasks)


def required_pairs_cost(effect_d: float = 0.8, power: float = 0.80) -> int:
    """Paired runs for a standardised effect on the cost difference.

    The reason to prefer solvable tasks: a moderate paired effect needs tens of runs,
    not hundreds, because each pair contributes a magnitude and each task is its own
    control.
    """
    z_a, z_b = 1.959964, 0.841621
    return max(6, math.ceil(((z_a + z_b) / effect_d) ** 2))
