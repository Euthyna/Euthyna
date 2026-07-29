"""What a skill costs to carry, and how many steps it must save to earn its place.

A skill's body is not free. Introduced with R turns remaining, it is written once at
the cache-creation rate and then re-read on every later turn at the cache-read rate:

    hold_cost_tok_eq = 1.25*S + 0.10*S*R

Against that, the skill only pays when it actually fires *and* helps. Published paired
evidence over 513 runs gives help 13.5% / harm 8.4% / no effect 78.2%, so the expected
return of a skill that saves G steps when it helps is `help_rate * G`, while its
expected loss is the hold cost plus `harm_rate * harm_steps`. Setting them equal:

    break_even_G = (hold_steps + harm_rate * harm_steps) / help_rate

Every constant here is a published measurement, not a tuned parameter, and each is
named and overridable so a caller can substitute their own measured rates. Euthyna
applies rates; it does not choose them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

# Paired-run counterfactual (SelSkill, n=513). Substitute your own once the paired
# harness has produced them for your workload — that is the whole point of measuring.
DEFAULT_HELP_RATE = 0.135
DEFAULT_HARM_RATE = 0.084
# Steps lost when a skill misleads. This one IS an assumption: no published work
# separates the cost of a false invoke from that of a false skip.
DEFAULT_HARM_STEPS = 3.0

# Session shape used when a caller has no measurement of its own. Both are overridable.
DEFAULT_REMAINING_TURNS = 40


def hold_cost_tok_eq(body_tokens: int, remaining_turns: int = DEFAULT_REMAINING_TURNS) -> float:
    """Token-equivalent cost of carrying a skill body for the rest of a session."""
    return round(CACHE_WRITE_MULTIPLIER * body_tokens
                 + CACHE_READ_MULTIPLIER * body_tokens * remaining_turns, 1)


def break_even_steps(body_tokens: int, step_cost_tok_eq: float,
                     remaining_turns: int = DEFAULT_REMAINING_TURNS,
                     help_rate: float = DEFAULT_HELP_RATE,
                     harm_rate: float = DEFAULT_HARM_RATE,
                     harm_steps: float = DEFAULT_HARM_STEPS) -> Optional[float]:
    """Steps a skill must save *when it helps* to break even. None if step cost is
    unknown — an unpriced step makes the whole comparison meaningless, and guessing
    one would be exactly the fabrication this project exists to avoid."""
    if not step_cost_tok_eq or not help_rate:
        return None
    hold_steps = hold_cost_tok_eq(body_tokens, remaining_turns) / step_cost_tok_eq
    return round((hold_steps + harm_rate * harm_steps) / help_rate, 2)


@dataclass
class Economics:
    """A skill's cost side, and the verdict it implies."""

    body_tokens: int
    steps_replaced: int
    step_cost_tok_eq: Optional[float]
    remaining_turns: int = DEFAULT_REMAINING_TURNS

    @property
    def net_steps_saved(self) -> int:
        """Invoking the skill is itself one agent step, so a ritual of N steps saves
        N-1. A one-step ritual saves nothing however often it recurs — frequency is
        not value, and this is where that shows up."""
        return max(self.steps_replaced - 1, 0)

    @property
    def hold_cost(self) -> float:
        return hold_cost_tok_eq(self.body_tokens, self.remaining_turns)

    @property
    def break_even(self) -> Optional[float]:
        return break_even_steps(self.body_tokens, self.step_cost_tok_eq, self.remaining_turns)

    @property
    def verdict(self) -> str:
        """PAYS / CANNOT_PAY / UNPRICED — never a number we did not derive."""
        be = self.break_even
        if be is None:
            return "UNPRICED"
        return "PAYS" if self.net_steps_saved >= be else "CANNOT_PAY"

    def as_dict(self) -> dict:
        return {
            "body_tokens": self.body_tokens,
            "steps_replaced": self.steps_replaced,
            "net_steps_saved": self.net_steps_saved,
            "step_cost_tok_eq": self.step_cost_tok_eq,
            "remaining_turns": self.remaining_turns,
            "hold_cost_tok_eq": self.hold_cost,
            "break_even_steps": self.break_even,
            "verdict": self.verdict,
        }
