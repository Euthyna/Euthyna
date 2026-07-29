"""Paired statistics for skill A/B, stdlib only.

Two decisions are baked in here and both come from RFC-002 §5:

* **Paired, not unpaired.** Detecting a +1.2pp effect unpaired needs ~27,300 runs per
  arm; paired McNemar on a 21.9% discordant rate needs ~665 runs total. Forty times
  cheaper, and the only version anyone can actually afford to run.
* **Counts, not a mean delta.** The published counterfactual is help 13.5% / harm
  8.4% / no effect 78.2%. A mean hides that a fifth of runs moved in opposite
  directions, which is the thing a reader needs to see.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def _binom_cdf(k: int, n: int, p: float = 0.5) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def mcnemar_exact(help_count: int, harm_count: int) -> Optional[float]:
    """Two-sided exact McNemar p-value.

    Under the null, every discordant pair is a fair coin flip, so the number favouring
    one arm is Binomial(b+c, 0.5). The exact form is used rather than the chi-square
    approximation because at the sample sizes we can afford, the approximation is not
    trustworthy. Returns None when there are no discordant pairs at all — that is an
    absence of evidence, not a p-value of 1.
    """
    n = help_count + harm_count
    if n == 0:
        return None
    return min(1.0, 2 * _binom_cdf(min(help_count, harm_count), n))


@dataclass
class PairedResult:
    """The outcome of comparing two arms over the same tasks."""

    arm_a: str
    arm_b: str
    pairs: int
    help_count: int      # b wins where a fails
    harm_count: int      # a wins where b fails
    null_count: int      # both agree
    p_value: Optional[float]
    cost_delta_tok_eq: Optional[float] = None
    cost_pairs: int = 0

    @property
    def discordant_rate(self) -> Optional[float]:
        return round((self.help_count + self.harm_count) / self.pairs, 4) if self.pairs else None

    def verdict(self, alpha: float = 0.05, floor: Optional["PairedResult"] = None) -> str:
        """SUPPORTED / NOT_SUPPORTED / UNDERPOWERED / WITHIN_NOISE.

        A result is only SUPPORTED if it is significant *and* its discordant rate
        exceeds the A/A floor's — an effect no larger than what two byte-identical
        arms produce is noise, whatever its p-value says.
        """
        if self.p_value is None:
            return "UNDERPOWERED"
        if floor is not None and floor.discordant_rate is not None \
                and (self.discordant_rate or 0) <= floor.discordant_rate:
            return "WITHIN_NOISE"
        if self.p_value > alpha:
            return "NOT_SUPPORTED" if self.pairs >= 60 else "UNDERPOWERED"
        return "SUPPORTED" if self.help_count > self.harm_count else "SUPPORTED_NEGATIVE"

    def as_dict(self) -> dict:
        return {
            "arm_a": self.arm_a, "arm_b": self.arm_b, "pairs": self.pairs,
            "help": self.help_count, "harm": self.harm_count, "null": self.null_count,
            "discordant_rate": self.discordant_rate, "p_value": self.p_value,
            "cost_delta_tok_eq": self.cost_delta_tok_eq, "cost_pairs": self.cost_pairs,
        }


# The published paired split: of a 21.9% discordant rate, 13.5pp favour the skill.
# Planning against the effect someone actually observed beats planning against a
# round number nobody has seen.
PUBLISHED_DISCORDANT_RATE = 0.219
PUBLISHED_SPLIT = 0.135 / 0.219


def required_pairs(discordant_rate: float = PUBLISHED_DISCORDANT_RATE,
                   effect: float = PUBLISHED_SPLIT,
                   power: float = 0.80, alpha: float = 0.05) -> int:
    """Paired runs needed to detect a discordant split of `effect` at the given power.

    Normal approximation on the discordant subset — enough to plan a run, not to
    report a result. At the published rate and split this returns 650, which is where
    RFC-002 §5's "~665 paired runs" comes from.
    """
    if not 0 < discordant_rate <= 1 or not 0 < effect < 1:
        return 0
    z_a, z_b = 1.959964, 0.841621  # two-sided 0.05, power 0.80
    delta = abs(effect - 0.5)
    if delta == 0:
        return 0
    n_disc = ((z_a * 0.5 + z_b * math.sqrt(effect * (1 - effect))) / delta) ** 2
    return math.ceil(n_disc / discordant_rate)
