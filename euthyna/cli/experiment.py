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
    ExperimentSpec, analyze, build_plan, load_outcomes, plan_summary,
    required_pairs, session_costs,
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
    costs = session_costs(args.dates or [_dt.date.today().isoformat()]) \
        if not args.no_cost else None
    result = analyze(outcomes, control=args.control, costs=costs)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"paired analysis — control arm: {result['control']}\n")
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


def run(args) -> int:
    return _plan(args) if args.experiment_command == "plan" else _analyze(args)
