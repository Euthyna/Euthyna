"""`euthyna report` — a day's ledger as per-session and total accounting.

Pure read of the JSONL ledger the gateway appends to; safe to run any time.
Aggregation lives in euthyna.ledger (shared with the gateway's /euthyna/stats).
"""
from __future__ import annotations

import datetime as _dt
import json

from euthyna.ledger import aggregate, home, load_rows, repetition_waste


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

    waste = repetition_waste(rows)
    header = f"{'session':<18} {'calls':>5} {'prompt':>9} {'cached':>9} {'compl':>7} {'$':>10} {'prefix':>7}"
    print(f"euthyna report — {date}")
    print(header)
    print("-" * len(header))
    totals = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    cached_total, cache_unknown = 0, False
    quality = {"exact": 0, "estimated": 0, "unavailable": 0}
    for sid, s in sorted(sessions.items()):
        ratio = s["mean_prefix_stable_ratio"]
        cached = s["cached_tokens"]
        if cached is None:
            cache_unknown = True  # unknown is rendered as unknown, never as 0
        else:
            cached_total += cached
        print(f"{sid[:18]:<18} {s['calls']:>5} {s['prompt_tokens']:>9} "
              f"{cached if cached is not None else '—':>9} "
              f"{s['completion_tokens']:>7} {s['cost_usd']:>10.4f} "
              f"{ratio if ratio is not None else '—':>7}")
        for key in totals:
            totals[key] += s[key]
        for k, v in s["cost_quality"].items():
            quality[k] = quality.get(k, 0) + v
    print("-" * len(header))
    cached_disp = f"{cached_total}*" if cache_unknown and cached_total else ("—" if cache_unknown else cached_total)
    print(f"{'TOTAL':<18} {totals['calls']:>5} {totals['prompt_tokens']:>9} {cached_disp:>9} "
          f"{totals['completion_tokens']:>7} {totals['cost_usd']:>10.4f}")
    models = sorted({m for s in sessions.values() for m in s["models"]})
    print(f"models: {', '.join(models) if models else '—'}")
    if cache_unknown:
        print("—/* cache not observable on some calls (backend does not surface cached_tokens); "
              "unknown is not counted as 0")
    if quality["estimated"] or quality["unavailable"]:
        print(f"cost quality: {quality['exact']} exact · {quality['estimated']} estimated "
              f"(cache unobserved; true bill may be lower) · {quality['unavailable']} unavailable")

    mutations = sum(s["prefix_mutations"] for s in sessions.values())
    if mutations:
        cost = sum(s["prefix_mutation_cost_tok_eq"] for s in sessions.values())
        causes = {}
        for s in sessions.values():
            for k, v in s["mutation_causes"].items():
                causes[k] = causes.get(k, 0) + v
        detail = " · ".join(f"{k} ×{v}" for k, v in sorted(causes.items(), key=lambda kv: -kv[1]))
        print(f"prefix mutations: {mutations} ({detail}) — re-write cost "
              f"{cost:,.0f} tok-eq at 1.15× the cached prefix")
    if waste["actions"]:
        frac = waste["repeated_cost_fraction"]
        longest = waste["longest_run"]
        print(f"repetition: {waste['repeated_actions']}/{waste['actions']} actions sit "
              f"inside a run of the same command repeated 3+ times "
              f"({waste['repeated_fraction']:.0%} of actions, "
              f"{frac:.0%} of spend = {waste['repeated_cost_tok_eq']:,.0f} tok-eq)")
        if longest and longest["length"] >= 3:
            print(f"  longest run: {longest['action']} x{longest['length']} — an agent "
                  "repeating one command has stopped making progress, and every "
                  "repetition after the second is charged in full")

    priced = [s for s in sessions.values() if s["mean_step_cost_tok_eq"] is not None]
    if priced:
        weighted = sum(s["mean_step_cost_tok_eq"] * s["calls"] for s in priced)
        saving = sum((s["mean_step_saving_tok_eq"] or 0) * s["calls"] for s in priced)
        calls = sum(s["calls"] for s in priced)
        premium = (saving / weighted - 1) * 100 if weighted else 0
        print(f"step cost: {weighted / calls:,.0f} tok-eq/step · eliminating one step "
              f"actually saves {saving / calls:,.0f} ({premium:+.0f}% from the tokens it "
              "would have added to every later turn)")

    unexplained = sum(s["cache_miss_unexplained"] for s in sessions.values())
    if unexplained:
        print(f"cache misses with an unmutated prefix: {unexplained} "
              "(TTL expiry or provider-side eviction — not self-inflicted)")
    return 0
