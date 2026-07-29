"""Join run outcomes to the ledger and report paired results.

Outcomes are supplied as JSONL, one row per run:

    {"task": "t1", "arm": "candidate", "rep": 0, "resolved": true, "session": "s001"}

`session` is optional; when present the run's cost is read from the ledger, which is
what lets a single table carry both halves of the question — did it work, and what did
it cost. Nobody else pairs those.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import datetime as _dt

from euthyna.ledger import aggregate, load_rows, step_cost

from .cost import compare_cost, cost_of
from .plan import RAW_ARM, SHAM_ARM
from .stats import PairedResult, mcnemar_exact


def load_outcomes(path) -> list:
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        missing = {"task", "arm", "rep", "resolved"} - set(r)
        if missing:
            raise ValueError(f"outcome row missing keys {sorted(missing)}: {line[:80]}")
        rows.append(r)
    return rows


def session_costs(dates: list) -> dict:
    """session id -> effective cost in token-equivalents, summed over its calls."""
    costs: dict = {}
    for date in dates:
        for sid, s in aggregate(load_rows(date)).items():
            mean = s.get("mean_step_cost_tok_eq")
            if mean is not None:
                costs[sid] = costs.get(sid, 0.0) + mean * s["calls"]
    return costs


def window_costs(outcomes: list, dates: list) -> dict:
    """run_id -> cost, attributed by time containment rather than session identity.

    Session attribution is not one-to-one: a single agent invocation can open more than
    one upstream session (opencode opens a second, tiny one to title the conversation),
    so keying cost on a session id silently drops part of the run. Runs executed
    serially have disjoint [started_at, ended_at] windows, which makes containment both
    exact and auditable — every ledger call lands in at most one run.

    Requires ``started_at``/``ended_at`` on each outcome row. Rows without them are
    skipped rather than guessed at.
    """
    calls = []
    for date in dates:
        for r in load_rows(date):
            ts = r.get("ts")
            if isinstance(ts, str):  # ISO form, as written by some tap versions
                try:
                    ts = _dt.datetime.fromisoformat(ts).timestamp()
                except ValueError:
                    continue
            if ts is not None:
                calls.append((ts, step_cost(r.get("cost") or {})))
    out: dict = {}
    for row in outcomes:
        rid, t0, t1 = row.get("run_id"), row.get("started_at"), row.get("ended_at")
        if rid is None or t0 is None or t1 is None:
            continue
        out[rid] = sum(c for ts, c in calls if t0 <= ts <= t1 and c is not None)
    return out


def compare(outcomes: list, arm_a: str, arm_b: str,
            costs: Optional[dict] = None) -> PairedResult:
    """Pair arm_b against arm_a on identical (task, rep) cells."""
    index = {(r["task"], r["arm"], r["rep"]): r for r in outcomes}
    cells = sorted({(r["task"], r["rep"]) for r in outcomes})
    helped = harmed = null = 0
    cost_deltas = []
    for task, rep in cells:
        a, b = index.get((task, arm_a, rep)), index.get((task, arm_b, rep))
        if a is None or b is None:
            continue  # an unmatched cell is dropped, never imputed
        if bool(b["resolved"]) and not bool(a["resolved"]):
            helped += 1
        elif bool(a["resolved"]) and not bool(b["resolved"]):
            harmed += 1
        else:
            null += 1
        if costs:
            ca, cb = cost_of(a, costs), cost_of(b, costs)
            if ca is not None and cb is not None:
                cost_deltas.append(cb - ca)
    pairs = helped + harmed + null
    return PairedResult(
        arm_a=arm_a, arm_b=arm_b, pairs=pairs,
        help_count=helped, harm_count=harmed, null_count=null,
        p_value=mcnemar_exact(helped, harmed),
        cost_delta_tok_eq=(round(sum(cost_deltas) / len(cost_deltas), 1)
                           if cost_deltas else None),
        cost_pairs=len(cost_deltas),
    )


def cost_per_solve(outcomes: list, costs: Optional[dict] = None) -> dict:
    """Cost per SOLVED task, per arm — the only denominator that means anything.

    A cheap failure is not cheap, it is worthless: the tokens bought nothing and the
    task still has to be done. Comparing a failed run's cost against a solved run's
    makes the arm that gives up fastest look best, which is why this is reported
    separately from the paired cost delta. An arm that solves nothing is `None`,
    never a small number.
    """
    per: dict = {}
    for r in outcomes:
        a = per.setdefault(r["arm"], {"runs": 0, "solved": 0, "tokens": 0.0, "priced": 0})
        a["runs"] += 1
        a["solved"] += bool(r["resolved"])
        c = (costs or {}).get(r.get("session"))
        if c is not None:
            a["tokens"] += c
            a["priced"] += 1
    for a in per.values():
        a["tokens"] = round(a["tokens"], 1)
        a["per_solve"] = (round(a["tokens"] / a["solved"], 1)
                          if a["solved"] and a["priced"] else None)
    return per


def baseline_check(outcomes: list, control: str) -> dict:
    """Can the control arm do the task at all?

    Every comparison below is against this arm, so if it solves nothing the experiment
    is measuring capability rather than the intervention — and if it solves everything
    the binary endpoint is saturated and only cost can move. Neither is a reason to
    stop, but both change what the numbers mean, and the first invalidated this
    project's own first pilot without anything in the analysis noticing.
    """
    runs = [r for r in outcomes if r["arm"] == control]
    solved = sum(1 for r in runs if r.get("resolved"))
    status = "ok"
    if not runs:
        status = "absent"
    elif solved == 0:
        status = "never_solves"
    elif solved == len(runs):
        status = "always_solves"
    return {"arm": control, "runs": len(runs), "solved": solved, "status": status,
            "note": {
                "absent": f"no runs for control arm {control!r}",
                "never_solves": (f"control solved 0 of {len(runs)}: every comparison "
                                 "below measures capability, not the intervention, and "
                                 "no cost comparison is possible"),
                "always_solves": (f"control solved {len(runs)} of {len(runs)}: the "
                                  "binary endpoint is saturated, so read the cost "
                                  "endpoint"),
                "ok": "",
            }[status]}


def analyze(outcomes: list, control: str, costs: Optional[dict] = None) -> dict:
    """Every arm against the control, with the A/A sham read as the noise floor."""
    arms = [a for a in dict.fromkeys(r["arm"] for r in outcomes) if a != control]
    floor = compare(outcomes, control, SHAM_ARM, costs) if SHAM_ARM in arms else None
    results = []
    for arm in arms:
        if arm == SHAM_ARM:
            continue
        r = compare(outcomes, control, arm, costs)
        results.append({**r.as_dict(), "verdict": r.verdict(floor=floor)})
    return {
        "control": control,
        "baseline": baseline_check(outcomes, control),
        "cost_per_solve": cost_per_solve(outcomes, costs),
        "cost_primary": [compare_cost(outcomes, control, a, costs).as_dict()
                         for a in arms if a != SHAM_ARM] if costs else [],
        "floor": ({**floor.as_dict(), "verdict": floor.verdict()} if floor else None),
        "results": results,
        "raw_baseline_present": RAW_ARM in arms,
    }
