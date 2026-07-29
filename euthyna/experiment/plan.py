"""Deterministic randomised run plans.

Randomisation is seeded and reproducible: the same spec and seed always yield the same
plan, so an experiment can be re-derived from its declaration rather than trusted from
its log. Assignment uses stratified permuted blocks (block = one task's replicate set),
which keeps arms balanced within every task even if the run is abandoned part-way.

Two arms are added automatically unless the spec opts out, because RFC-002 makes both
mandatory:

* an **A/A sham** — byte-identical to the control, whose discordant rate is the noise
  floor every claim must clear;
* a **raw-trajectory-retrieval** arm — the real baseline, since published work reports
  that retrieving the raw trace can beat retrieving its distillate.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

SHAM_ARM = "aa_sham"
RAW_ARM = "raw_trajectory"


def _shuffle(items: list, key: str) -> list:
    """Fisher-Yates driven by SHA-256 of the key — no RNG state, no platform drift."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        digest = hashlib.sha256(f"{key}|{i}".encode()).digest()
        j = int.from_bytes(digest[:8], "big") % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


@dataclass
class ExperimentSpec:
    name: str
    tasks: list
    arms: list                      # arm ids under test, control first
    reps: int = 3
    seed: str = "euthyna"
    include_sham: bool = True
    include_raw_baseline: bool = True
    notes: str = ""
    _extra: dict = field(default_factory=dict)

    @property
    def all_arms(self) -> list:
        arms = list(self.arms)
        if self.include_raw_baseline and RAW_ARM not in arms:
            arms.append(RAW_ARM)
        if self.include_sham and SHAM_ARM not in arms:
            arms.append(SHAM_ARM)
        return arms

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentSpec":
        missing = {"name", "tasks", "arms"} - set(d)
        if missing:
            raise ValueError(f"experiment spec missing keys {sorted(missing)}")
        known = {"name", "tasks", "arms", "reps", "seed", "include_sham",
                 "include_raw_baseline", "notes"}
        return cls(**{k: v for k, v in d.items() if k in known},
                   _extra={k: v for k, v in d.items() if k not in known})


def build_plan(spec: ExperimentSpec) -> list:
    """One row per (task, arm, rep), order randomised within each task block."""
    plan = []
    arms = spec.all_arms
    for task in spec.tasks:
        cells = [(arm, rep) for rep in range(spec.reps) for arm in arms]
        for order, (arm, rep) in enumerate(_shuffle(cells, f"{spec.seed}|{spec.name}|{task}")):
            plan.append({"task": task, "arm": arm, "rep": rep, "order": order,
                         "run_id": f"{task}::{arm}::{rep}"})
    return plan


def plan_summary(spec: ExperimentSpec, plan: list) -> dict:
    return {
        "name": spec.name,
        "seed": spec.seed,
        "tasks": len(spec.tasks),
        "arms": spec.all_arms,
        "reps": spec.reps,
        "total_runs": len(plan),
        "sham_included": SHAM_ARM in spec.all_arms,
        "raw_baseline_included": RAW_ARM in spec.all_arms,
    }
