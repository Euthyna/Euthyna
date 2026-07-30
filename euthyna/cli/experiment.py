"""`euthyna experiment` — plan a paired A/B, then read its outcomes.

Two subcommands, both offline:

* ``plan``    — spec in, reproducible randomised run list out.
* ``analyze`` — outcomes in, paired counts + exact McNemar + cost delta out, with the
  A/A sham arm read as the noise floor under every verdict.

Running the agent itself is deliberately out of scope: the plan is a list of
``run_id``s any harness can execute, and the outcomes are a flat JSONL anyone can
produce. The instrument does not need to own the loop to be trustworthy.
"""
from __future__ import annotations

import datetime as _dt
import json

import yaml

from euthyna.experiment import (
    ExperimentSpec, analyze, build_plan, calibrate, load_outcomes, plan_summary,
    cost_basis, overlapping_runs, required_pairs, schedule, session_costs,
    window_costs,
)


def _plan(args) -> int:
    spec = ExperimentSpec.from_dict(yaml.safe_load(open(args.spec).read()))
    plan = build_plan(spec)
    summary = plan_summary(spec, plan)
    if args.json:
        print(json.dumps({"summary": summary, "plan": plan}, indent=2))
        return 0
    with open(args.out, "w") as f:
        for row in plan:
            f.write(json.dumps(row) + "\n")
    print(f"experiment plan — {summary['name']} (seed {summary['seed']})")
    print(f"  {summary['tasks']} tasks × {len(summary['arms'])} arms × "
          f"{summary['reps']} reps = {summary['total_runs']} runs")
    print(f"  arms: {', '.join(summary['arms'])}")
    if not summary["sham_included"]:
        print("  ! no A/A sham arm — every effect will be unfloored")
    if not summary["raw_baseline_included"]:
        print("  ! no raw-trajectory arm — the real baseline is missing")
    need = required_pairs()
    print(f"  for reference, ~{need} paired runs are needed to detect a 65/35 "
          "discordant split at 80% power")
    print(f"  wrote {args.out}")
    return 0


def _analyze(args) -> int:
    outcomes = load_outcomes(args.outcomes)
    dates = args.dates or [_dt.date.today().isoformat()]
    if args.no_cost:
        costs = None
    elif getattr(args, "window_costs", False):
        costs = window_costs(outcomes, dates)
        missing = [r.get("run_id") for r in outcomes
                   if r.get("started_at") is None or r.get("ended_at") is None]
        if missing:
            print(f"! {len(missing)} run(s) carry no time window and were left "
                  "unpriced rather than guessed at\n")
        # Window attribution assumes one call belongs to one run. Parallel workers break
        # that, and counting a shared call in both runs would inflate every arm.
        overlap = overlapping_runs(outcomes)
        if overlap:
            print(f"! {len(overlap)} run(s) have overlapping time windows and were left "
                  "UNPRICED — the clock cannot say which run a shared call belongs to. "
                  "These runs were executed in parallel; use session-keyed costs "
                  "instead of --window-costs\n")
    else:
        costs = session_costs(dates)
    result = analyze(outcomes, control=args.control, costs=costs)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"paired analysis — control arm: {result['control']}\n")
    b = result.get("baseline") or {}
    if b.get("status") not in (None, "ok"):
        print(f"!! BASELINE {b['status'].upper()} — {b['note']}\n")
    header = (f"{'arm':<18} {'pairs':>6} {'help':>5} {'harm':>5} {'null':>5} "
              f"{'p':>7} {'Δcost':>10}  verdict")
    print(header)
    print("-" * len(header))
    rows = list(result["results"])
    if result["floor"]:
        rows.append({**result["floor"], "arm_b": "aa_sham (floor)"})
    for r in rows:
        p = f"{r['p_value']:.3f}" if r["p_value"] is not None else "—"
        dc = f"{r['cost_delta_tok_eq']:+,.0f}" if r["cost_delta_tok_eq"] is not None else "—"
        print(f"{r['arm_b'][:18]:<18} {r['pairs']:>6} {r['help']:>5} {r['harm']:>5} "
              f"{r['null']:>5} {p:>7} {dc:>10}  {r.get('verdict', '')}")
    print("-" * len(header))
    print("help/harm/null are counts of discordant pairs, not a mean — a mean would "
          "hide runs moving in opposite directions")
    if result["floor"]:
        print(f"A/A floor discordant rate: {result['floor']['discordant_rate']} — an "
              "arm at or below this is noise whatever its p-value")
    else:
        print("! no A/A sham arm in the outcomes: every verdict here is unfloored")
    if result.get("cost_primary"):
        print(f"\n{'arm':<18} {'pairs':>6} {'dropped':>8} {'Δmedian':>10} {'Δrel':>7} "
              f"{'p':>7} {'quality':>9}  verdict")
        for r in result["cost_primary"]:
            if not r["pairs"] and not r["dropped_discordant"]:
                continue
            md = f"{r['median_delta']:+,.0f}" if r["median_delta"] is not None else "—"
            rel = f"{r['relative_delta']:+.1%}" if r["relative_delta"] is not None else "—"
            p = f"{r['p_value']:.3f}" if r["p_value"] is not None else "—"
            mark = "*" if r.get("skewed") else " "
            print(f"{r['arm_b'][:17]:<17}{mark} {r['pairs']:>6} {r['dropped_discordant']:>8} "
                  f"{md:>10} {rel:>7} {p:>7} {r['resolve_guard']:>9}  {r['verdict']}")
        print("cost is compared only where BOTH arms solved the task; discordant pairs "
              "are dropped, not averaged in")
        if getattr(args, "window_costs", False):
            mix = cost_basis(outcomes, dates)
            est = mix.get("estimated_under_no_cache_assumption", 0)
            tot = sum(mix.values())
            if est:
                print(f"cost basis: {est} of {tot} calls priced under a NO-CACHE "
                      "assumption — this backend never reports a cache split, so every "
                      "step cost above is an upper bound, not a measurement")
        if any(r.get("skewed") for r in result["cost_primary"]):
            print("* marked rows: the per-pair median and the total disagree in sign — "
                  "the spread is skewed and the verdict follows the median")

    priced = {a: v for a, v in result["cost_per_solve"].items() if v["priced"]}
    if priced:
        print(f"\n{'arm':<18} {'solved':>7} {'tokens':>12} {'per solve':>12}")
        for arm, v in sorted(priced.items()):
            ps = f"{v['per_solve']:,.0f}" if v["per_solve"] is not None else "— (none solved)"
            print(f"{arm[:18]:<18} {v['solved']:>3}/{v['runs']:<3} {v['tokens']:>12,.0f} {ps:>12}")
        print("a cheap failure is not cheap: an arm that solves nothing has no cost "
              "per solve, however few tokens it spent")
    if not result["raw_baseline_present"]:
        print("! no raw-trajectory arm: the baseline published work says can win is "
              "missing, so a positive result here is not yet meaningful")
    return 0


def _calibrate(args) -> int:
    cals = calibrate(load_outcomes(args.outcomes), baseline_arm=args.baseline,
                     candidate_arm=args.candidate, target_pairs=args.target_pairs)
    plan = schedule(cals, target_pairs=args.target_pairs)
    if args.json:
        print(json.dumps({"tasks": [c.as_dict() for c in cals], "schedule": plan},
                         indent=2))
        return 0
    if not cals:
        print(f"no runs for baseline arm {args.baseline!r} in {args.outcomes}")
        return 1
    print(f"cost-experiment calibration — baseline arm: {args.baseline}\n")
    header = (f"{'task':<22} {'solved':>8} {'rate':>6} {'95% lo':>7} {'yield':>6} "
              f"{'sched':>6}  verdict")
    print(header)
    print("-" * len(header))
    for c in cals:
        d = c.as_dict()
        sched = d["pairs_to_schedule"] or "—"
        print(f"{c.task[:22]:<22} {c.baseline_solved:>3}/{c.baseline_runs:<4} "
              f"{d['baseline_rate']:>6.2f} {d['baseline_lower_95']:>7.2f} "
              f"{d['yield_rate']:>6.2f} {sched:>6}  {d['verdict']}")
    print("-" * len(header))
    print("a task the baseline never solves has nothing to hold constant, so there is "
          "no cost question to ask of it")
    print("95% lo is the exact one-sided Clopper-Pearson bound: 3/3 clean runs only "
          "rule out a solve rate below 0.37")
    if plan.get("total_runs"):
        print(f"\nto get {args.target_pairs} usable pairs: {plan['eligible_tasks']} "
              f"tasks x {plan['pairs_per_task']} pairs, {plan['scheduled_pairs']} pairs "
              f"scheduled after yield loss = {plan['total_runs']} runs")
    else:
        print(f"\n{plan['note']}")
    return 0


def run(args) -> int:
    if args.experiment_command == "plan":
        return _plan(args)
    if args.experiment_command == "calibrate":
        return _calibrate(args)
    return _analyze(args)
