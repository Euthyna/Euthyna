"""Paired A/B harness: plan a randomised experiment, then read it honestly.

This is HARNESS mode's first real job — the instrument that turns "this skill pays"
from a derivation into a measurement, and the only thing that can produce the labelled
pairs a future retriever would need.
"""
from .analyze import (analyze, compare, cost_basis, load_outcomes,
                      overlapping_runs, session_costs, window_costs)
from .calibrate import TaskCalibration, calibrate, clopper_pearson_lower, schedule
from .cost import (CostResult, compare_cost, cost_of, required_pairs_cost,
                   wilcoxon_signed_rank)
from .plan import RAW_ARM, SHAM_ARM, ExperimentSpec, build_plan, plan_summary
from .stats import PairedResult, mcnemar_exact, required_pairs

__all__ = ["CostResult", "TaskCalibration", "calibrate", "clopper_pearson_lower", "schedule", "ExperimentSpec", "PairedResult", "RAW_ARM", "SHAM_ARM", "analyze",
           "compare_cost", "required_pairs_cost", "wilcoxon_signed_rank",
           "build_plan", "compare", "load_outcomes", "mcnemar_exact", "plan_summary",
           "required_pairs", "session_costs", "cost_of", "window_costs", "cost_basis", "overlapping_runs"]
