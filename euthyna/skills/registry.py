"""Signature-keyed skill registry.

A skill is distilled *from* a recurring flow signature, so its trigger is "that
signature recurred" — an exact match, not a semantic guess. That choice is what keeps
the runtime path deterministic and removes any need for embedding retrieval below the
sizes where retrieval is even warranted (RFC-002 §6).

On-disk format is a Markdown file with YAML front matter, deliberately close to the
SKILL.md convention so skills stay portable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .economics import Economics

# RFC-002 §8. Each threshold cites the measurement it comes from; none is taste.
GATES = {
    # break-even at 500 tokens is 3.7 steps; at 2,000 it is 9.3, above anything observed
    "max_body_tokens": 500,
    # SkillsBench: 2-3 presented is optimal (+20.0pp); 4+ falls to +5.2pp
    "max_presented_per_task": 3,
    # shadowing measured at -8pp with 52 skills, and it is monotone upward
    "max_active_skills": 50,
    # a skill that replaces fewer steps than this cannot pay for itself at any size
    "min_steps_replaced": 1,
}

# 4 chars/token is the convention euthyna.core.transforms uses, but measuring a real
# skill document through the gateway put it 31% low (204 observed vs 156 estimated,
# consistent across three sessions — see docs/examples/skill-pilot). Estimating a
# skill's cost too low is the direction that admits skills that cannot pay, so the
# estimator carries the measured correction and a skill may override it outright.
_TOKENS_PER_CHAR = 0.25
_MEASURED_CORRECTION = 1.31
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def estimate_tokens(text: str) -> int:
    return int(len(text) * _TOKENS_PER_CHAR * _MEASURED_CORRECTION)


@dataclass
class Skill:
    name: str
    signature: list                      # the flow signature this compiles, in order
    steps_replaced: int
    body: str
    description: str = ""
    preconditions: list = field(default_factory=list)
    source: str = ""                     # corpus/evidence the distillation came from
    measured_body_tokens: Optional[int] = None   # observed on the wire, beats any estimate
    path: Optional[Path] = None

    @property
    def body_tokens(self) -> int:
        """Measured footprint when someone has run this skill through a gateway and
        recorded it; otherwise the corrected estimate. Measured always wins."""
        return self.measured_body_tokens or estimate_tokens(self.body)

    @property
    def tokens_are_measured(self) -> bool:
        return self.measured_body_tokens is not None

    def economics(self, step_cost_tok_eq: Optional[float],
                  remaining_turns: int = 40) -> Economics:
        return Economics(self.body_tokens, self.steps_replaced, step_cost_tok_eq,
                         remaining_turns)

    def gate_failures(self) -> list:
        """Every gate this skill violates, with the measured basis for each."""
        out = []
        if self.body_tokens > GATES["max_body_tokens"]:
            out.append(f"body {self.body_tokens} tok > {GATES['max_body_tokens']} "
                       "(break-even rises past anything observed)")
        if self.steps_replaced < GATES["min_steps_replaced"]:
            out.append(f"replaces {self.steps_replaced} steps — nothing to amortize")
        if not self.signature:
            out.append("no trigger signature — nothing to key on")
        return out

    def card(self) -> str:
        """The ~70-token roster entry that sits in the prefix; the body is not in it."""
        return f"{self.name}: {self.description} [when: {' → '.join(self.signature)}]"


def load_skill(path) -> Skill:
    path = Path(path)
    m = _FRONT_MATTER.match(path.read_text())
    if not m:
        raise ValueError(f"{path}: expected YAML front matter delimited by ---")
    meta = yaml.safe_load(m.group(1)) or {}
    missing = {"name", "signature", "steps_replaced"} - set(meta)
    if missing:
        raise ValueError(f"{path}: missing front-matter keys {sorted(missing)}")
    return Skill(
        name=meta["name"],
        signature=list(meta["signature"]),
        steps_replaced=int(meta["steps_replaced"]),
        body=m.group(2).strip(),
        description=meta.get("description", ""),
        preconditions=list(meta.get("preconditions") or []),
        source=meta.get("source", ""),
        measured_body_tokens=meta.get("measured_body_tokens"),
        path=path,
    )


class SkillRegistry:
    """Skills on disk, keyed by flow signature.

    Lookup is exact-match on a rolling window of recent action signatures. There is no
    embedding index and, below 50 skills, no reason for one.
    """

    def __init__(self, skills: Optional[list] = None) -> None:
        self.skills = list(skills or [])

    @classmethod
    def load(cls, directory) -> "SkillRegistry":
        directory = Path(directory)
        if not directory.exists():
            return cls()
        return cls([load_skill(p) for p in sorted(directory.glob("*.md"))])

    def match(self, recent_signatures: list) -> list:
        """Skills whose signature is a suffix of the recent action window.

        Suffix, not "contains": a ritual is compilable only when the agent has just
        finished performing it, which is exactly when the next occurrence can be
        replaced.
        """
        hits = []
        for s in self.skills:
            n = len(s.signature)
            if n and len(recent_signatures) >= n and recent_signatures[-n:] == s.signature:
                hits.append(s)
        # Cap what is ever presented, independent of library size.
        return sorted(hits, key=lambda s: -s.steps_replaced)[:GATES["max_presented_per_task"]]

    def gate_failures(self) -> list:
        out = [f"{s.name}: {f}" for s in self.skills for f in s.gate_failures()]
        if len(self.skills) > GATES["max_active_skills"]:
            out.append(f"library holds {len(self.skills)} skills > "
                       f"{GATES['max_active_skills']} (shadowing territory)")
        return out

    def report(self, step_cost_tok_eq: Optional[float],
               remaining_turns: int = 40) -> list:
        rows = []
        for s in self.skills:
            e = s.economics(step_cost_tok_eq, remaining_turns)
            rows.append({"name": s.name, "signature": s.signature,
                         "source": s.source, "tokens_measured": s.tokens_are_measured,
                         **e.as_dict(), "gate_failures": s.gate_failures()})
        return rows

    def to_json(self, step_cost_tok_eq: Optional[float]) -> str:
        return json.dumps(self.report(step_cost_tok_eq), indent=2)
