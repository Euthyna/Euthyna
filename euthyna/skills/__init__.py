"""Signature-keyed skill registry with per-skill economics (RFC-002 layers 1 and 3).

The point of this module is not to hold skills. It is to **price** them.

Every published skill system measures success rate; the field's own survey concedes
that skill evaluation "overlooks token cost and latency". A skill is not free: its body
sits in the context for the rest of the session, re-read on every subsequent turn. This
module computes what that costs and how many agent steps the skill must eliminate
before it can possibly pay for itself — so a skill that cannot is rejected before it is
ever measured, rather than after.
"""
from .economics import Economics, break_even_steps, hold_cost_tok_eq
from .registry import GATES, Skill, SkillRegistry, load_skill

__all__ = ["Economics", "GATES", "Skill", "SkillRegistry",
           "break_even_steps", "hold_cost_tok_eq", "load_skill"]
