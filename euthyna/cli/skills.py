"""`euthyna skills` — inspect the signature-keyed registry and price every entry.

Offline and read-only. The output that matters is the verdict column: whether a skill
can pay for the context it occupies, given what a step actually costs on your traffic.
"""
from __future__ import annotations

import datetime as _dt
import json

from euthyna.ledger import aggregate, load_rows
from euthyna.skills import GATES, SkillRegistry


def _measured_step_cost(date: str) -> tuple:
    """Step cost measured from your own ledger, or None with the reason why."""
    sessions = aggregate(load_rows(date))
    priced = [(s["mean_step_cost_tok_eq"], s["calls"]) for s in sessions.values()
              if s.get("mean_step_cost_tok_eq") is not None]
    if not priced:
        return None, f"no priced steps in the {date} ledger"
    total_calls = sum(c for _, c in priced)
    return round(sum(v * c for v, c in priced) / total_calls, 1), f"{date} ledger"


def run(args) -> int:
    registry = SkillRegistry.load(args.dir)
    if not registry.skills:
        print(f"skills: no skills in {args.dir}/ (expected *.md with YAML front matter)")
        return 0

    step_cost, basis = (args.step_cost, "--step-cost") if args.step_cost else \
        _measured_step_cost(args.date or _dt.date.today().isoformat())
    rows = registry.report(step_cost, remaining_turns=args.turns)

    if args.json:
        print(json.dumps({"step_cost_tok_eq": step_cost, "step_cost_basis": basis,
                          "remaining_turns": args.turns, "skills": rows}, indent=2))
        return 0

    if step_cost is None:
        print(f"skills: step cost unknown ({basis}) — run traffic through the gateway "
              "or pass --step-cost; skills are listed but NOT priced\n")
    else:
        print(f"euthyna skills — step cost {step_cost:,.0f} tok-eq (from {basis}), "
              f"session horizon {args.turns} turns\n")

    header = (f"{'skill':<22} {'ritual':>7} {'body':>6} {'hold':>8} {'saves':>6} "
              f"{'needs':>6}  verdict")
    print(header)
    print("-" * len(header))
    for r in rows:
        needs = f"{r['break_even_steps']:.1f}" if r["break_even_steps"] is not None else "—"
        print(f"{r['name'][:22]:<22} {r['steps_replaced']:>7} {r['body_tokens']:>6} "
              f"{r['hold_cost_tok_eq']:>8,.0f} {r['net_steps_saved']:>6} {needs:>6}  "
              f"{r['verdict']}")
    print("-" * len(header))
    print("ritual = agent steps the flow takes · saves = ritual − 1 (invoking the skill "
          "is itself a step)")
    print("hold = 1.25×body + 0.10×body×turns (written once, re-read every later turn)")
    print("needs = steps it must save WHEN IT HELPS to break even, at published paired "
          "rates (help 13.5% / harm 8.4%)")

    failures = registry.gate_failures()
    if failures:
        print(f"\ngate failures ({len(failures)}):")
        for f in failures:
            print(f"  ✗ {f}")
    else:
        print(f"\nall {len(registry.skills)} skills within gates "
              f"(≤{GATES['max_body_tokens']} tok body, ≤{GATES['max_active_skills']} active)")
    return 0
