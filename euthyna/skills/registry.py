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
    # None means NOT YET MEASURED, and is the honest state for a freshly mined skill.
    # Requiring an int here is what forces an author to invent one -- which is exactly
    # how swe-patch-probe came to declare 6 and replace 0.
    steps_replaced: Optional[int]
    body: str
    description: str = ""
    preconditions: list = field(default_factory=list)
    source: str = ""                     # corpus/evidence the distillation came from
    harness: str = ""                    # harness whose action vocabulary the signature speaks
    measured_body_tokens: Optional[int] = None   # observed on the wire, beats any estimate
    # Steps this skill was observed to replace in the workload it is DEPLOYED into, which
    # is not what `steps_replaced` says. That number is inherited from the corpus the
    # skill was mined from and travels with the file; this one has to be earned per
    # workload. Same precedence rule as measured_body_tokens: measured always wins.
    # 'signature' (default) fires on a matching action n-gram; 'task-start' fires once
    # per task. The second kind has no signature by construction, so the gates that ask
    # 'what does this key on?' do not apply to it -- and answering them with an empty
    # signature made it look like dead code when it is the opposite: it always fires.
    trigger: str = "signature"
    measured_steps_replaced: Optional[int] = None
    measured_in: str = ""                # workload the measurement above was taken in
    path: Optional[Path] = None

    @property
    def vocabulary(self) -> set:
        """The action names this skill's trigger is expressed in."""
        return {str(a) for a in self.signature}

    @property
    def body_tokens(self) -> int:
        """Measured footprint when someone has run this skill through a gateway and
        recorded it; otherwise the corrected estimate. Measured always wins."""
        return self.measured_body_tokens or estimate_tokens(self.body)

    @property
    def tokens_are_measured(self) -> bool:
        return self.measured_body_tokens is not None

    @property
    def effective_steps_replaced(self) -> int:
        """What this skill actually saves here, not what its corpus said it saved there.

        A skill mined from one harness carries its step count with it, and the economics
        gate will happily return PAYS on a number that was never true of the workload in
        front of it. `swe-patch-probe` declares 6 and replaced 0 in the cost-primary run —
        the flow it keys on never occurred (RFC-002 §10.6).
        """
        if self.measured_steps_replaced is not None:
            return self.measured_steps_replaced
        # Unmeasured and undeclared: claims nothing. The gate below reads 0 and refuses to
        # return PAYS, which is the correct answer to "does this pay?" before anyone looked.
        return self.steps_replaced if self.steps_replaced is not None else 0

    @property
    def steps_are_measured(self) -> bool:
        return self.measured_steps_replaced is not None

    def economics(self, step_cost_tok_eq: Optional[float],
                  remaining_turns: int = 40) -> Economics:
        return Economics(self.body_tokens, self.effective_steps_replaced,
                         step_cost_tok_eq, remaining_turns)

    def gate_failures(self) -> list:
        """Every gate this skill violates, with the measured basis for each."""
        out = []
        if self.body_tokens > GATES["max_body_tokens"]:
            out.append(f"body {self.body_tokens} tok > {GATES['max_body_tokens']} "
                       "(break-even rises past anything observed)")
        n = self.effective_steps_replaced
        if n < GATES["min_steps_replaced"]:
            where = f" in {self.measured_in}" if self.measured_in else ""
            if self.steps_are_measured:
                out.append(f"measured to replace {n} steps{where} — nothing to amortize")
            elif self.steps_replaced is None:
                # Distinct from declaring zero. "Nobody has measured this yet" is the state
                # every mined skill starts in, and the failure this project keeps hitting is
                # a number invented to escape it. Not deployable, but not disproven either.
                out.append("steps replaced not yet measured — deploy only behind an A/B")
            else:
                out.append(f"declared to replace {n} steps{where} — nothing to amortize")
        # A task-start skill has no signature by construction: it fires once per task. Asking
        # it what it keys on is a category error, and answering "nothing" made an always-on
        # skill read as dead code.
        if self.trigger == "signature" and not self.signature:
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
        steps_replaced=(None if meta["steps_replaced"] is None
                        else int(meta["steps_replaced"])),
        trigger=meta.get("trigger", "signature"),
        body=m.group(2).strip(),
        description=meta.get("description", ""),
        preconditions=list(meta.get("preconditions") or []),
        source=meta.get("source", ""),
        harness=meta.get("harness", ""),
        measured_body_tokens=meta.get("measured_body_tokens"),
        measured_steps_replaced=meta.get("measured_steps_replaced"),
        measured_in=meta.get("measured_in", ""),
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

    def dead_triggers(self, observed_vocabulary) -> list:
        """Skills whose trigger cannot fire in a harness that emits these actions.

        A signature is a sequence of action names, so it can only match a harness that
        emits those names. Mine a flow from one harness and deploy it into another and the
        trigger is dead code: it never matches, at any prefix of any trajectory, and
        nothing in ``match()`` says so — never-matching is exactly what matching looks
        like when there is nothing to match.

        This is not hypothetical. The three skills in this repository were distilled from
        mini-SWE-agent, which has one tool, so they speak ``bash:grep`` / ``bash:sed`` /
        ``bash:echo``. Run against opencode, which emits ``glob`` / ``read`` / ``edit`` /
        ``bash``, the vocabulary intersection is empty and all three are inert. The
        cost-primary experiment delivered one of them unconditionally as a document and
        measured it costing 6% more for nothing — but in a real deployment the registry
        would never have presented it at all.
        """
        vocab = {str(a) for a in observed_vocabulary}
        out = []
        for s in self.skills:
            if s.vocabulary and not (s.vocabulary & vocab):
                out.append({
                    "name": s.name,
                    "harness": s.harness or "unrecorded",
                    "signature_vocabulary": sorted(s.vocabulary),
                    "reason": ("trigger vocabulary is disjoint from the observed actions "
                               "— this skill can never fire here"),
                })
        return out

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
                         "source": s.source, "harness": s.harness,
                         "tokens_measured": s.tokens_are_measured,
                         "steps_declared": s.steps_replaced,
                         "steps_measured": s.measured_steps_replaced,
                         "steps_basis": "measured" if s.steps_are_measured else "declared",
                         "measured_in": s.measured_in,
                         **e.as_dict(), "gate_failures": s.gate_failures()})
        return rows

    def to_json(self, step_cost_tok_eq: Optional[float]) -> str:
        return json.dumps(self.report(step_cost_tok_eq), indent=2)
