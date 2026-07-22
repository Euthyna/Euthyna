"""`euthyna report` — a day's ledger as per-session and total accounting.

Pure read of the JSONL ledger the gateway appends to; safe to run any time.
Aggregation lives in euthyna.ledger (shared with the gateway's /euthyna/stats).
"""
from __future__ import annotations

import datetime as _dt
import json

from euthyna.ledger import aggregate, home, load_rows


def run(args) -> int:
    date = args.date or _dt.date.today().isoformat()
    rows = load_rows(date)
    sessions = aggregate(rows)
    if args.json:
        print(json.dumps({"date": date, "sessions": sessions}, indent=2))
        return 0
    if not rows:
        print(f"report: no ledger rows for {date} under {home() / 'ledger'}")
        return 0

    header = f"{'session':<18} {'calls':>5} {'prompt':>9} {'cached':>9} {'compl':>7} {'$':>10} {'prefix':>7}"
    print(f"euthyna report — {date}")
    print(header)
    print("-" * len(header))
    totals = {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    for sid, s in sorted(sessions.items()):
        ratio = s["mean_prefix_stable_ratio"]
        print(f"{sid[:18]:<18} {s['calls']:>5} {s['prompt_tokens']:>9} {s['cached_tokens']:>9} "
              f"{s['completion_tokens']:>7} {s['cost_usd']:>10.4f} "
              f"{ratio if ratio is not None else '—':>7}")
        for key in totals:
            totals[key] += s[key]
    print("-" * len(header))
    print(f"{'TOTAL':<18} {totals['calls']:>5} {totals['prompt_tokens']:>9} {totals['cached_tokens']:>9} "
          f"{totals['completion_tokens']:>7} {totals['cost_usd']:>10.4f}")
    models = sorted({m for s in sessions.values() for m in s["models"]})
    print(f"models: {', '.join(models) if models else '—'}")
    return 0
