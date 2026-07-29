"""Paired A/B harness: plan a randomised experiment, then read it honestly.

This is HARNESS mode's first real job — the instrument that turns "this skill pays"
from a derivation into a measurement, and the only thing that can produce the labelled
pairs a future retriever would need.
"""
from .analyze import analyze, compare, load_outcomes, session_costs
from .plan import RAW_ARM, SHAM_ARM, ExperimentSpec, build_plan, plan_summary
from .stats import PairedResult, mcnemar_exact, required_pairs

__all__ = ["ExperimentSpec", "PairedResult", "RAW_ARM", "SHAM_ARM", "analyze",
           "build_plan", "compare", "load_outcomes", "mcnemar_exact", "plan_summary",
           "required_pairs", "session_costs"]
