"""`euthyna mine` — Stage 0/1 repeated-flow miner + classifier (offline).

Deterministic, no LLM, no network. Ingests agent-trace corpora described by a
config JSON and emits candidate flows + a classification report. This is the
perception half of v0.2 "evidence-gated flow compilation": it mines and
describes candidates only — no skills generated, no efficacy claims.

Config JSON maps corpus name -> {glob, mode|adapter}:
  {"miniswe":  {"glob": ".../miniswe/*.jsonl",  "adapter": "miniswe"},
   "euthyna":  {"glob": "~/.euthyna/traces/*.jsonl", "mode": "hash_only"}}

Outputs (all STRUCTURE only — no raw trace content):
  <out>/candidates.jsonl              per-candidate records (brief schema)
  <out>/candidates_classified.jsonl   + taxonomy label + skill sketch
  <out>/flows_report.md               Stage-0 per-corpus stats + ranked table
  <out>/inspect.json                  schema dump (from `--inspect`)
"""
from __future__ import annotations

import json
import os

from euthyna.mine.loaders import (discover, inspect_file, load_content_jsonl,
                                   load_hash_only_jsonl)
from euthyna.mine.adapters import ADAPTERS
from euthyna.mine.miner import mine_level, dedup_maximal
from euthyna.mine.estimate import estimate_flow


def _load_config(path):
    with open(os.path.expanduser(path)) as f:
        return json.load(f)


def _load_all(config):
    globs = {name: c["glob"] for name, c in config.items()}
    found = discover(globs)
    sessions, missing = [], []
    for name, c in config.items():
        files = found.get(name, [])
        if not files:
            missing.append(name)
            continue
        for fp in files:
            mode, adapter = c.get("mode"), c.get("adapter")
            if mode == "hash_only":
                sessions.extend(load_hash_only_jsonl(fp, name))
            elif adapter and adapter in ADAPTERS:
                sessions.extend(ADAPTERS[adapter](fp, name))
            else:
                sessions.extend(load_content_jsonl(fp, name))
    return sessions, found, missing


def run(args) -> int:
    if not args.config:
        print("mine: --config <corpora.json> is required "
              "(maps corpus -> {glob, mode|adapter}); see docs/flow-mining.md")
        return 1
    config = _load_config(args.config)
    os.makedirs(args.out, exist_ok=True)

    if args.inspect:
        globs = {name: c["glob"] for name, c in config.items()}
        out = {name: {"n_files": len(fs),
                      "files": [inspect_file(fp) for fp in fs[:5]]}
               for name, fs in discover(globs).items()}
        p = os.path.join(args.out, "inspect.json")
        with open(p, "w") as f:
            json.dump(out, f, indent=2)
        for name, d in out.items():
            print(f"  {name}: {d['n_files']} files")
        print(f"mine: schema dump -> {p}")
        return 0

    sessions, found, missing = _load_all(config)
    per_corpus = {name: {"n_files": len(found.get(name, [])),
                         "n_sessions": len([s for s in sessions if s.corpus == name]),
                         "n_steps": sum(len(s) for s in sessions if s.corpus == name),
                         "mode": config[name].get("mode",
                                 config[name].get("adapter", "content")),
                         "present": name not in missing}
                  for name in config}

    all_flows, level_counts = [], {}
    for lv in ("L0", "L1", "L2"):
        fl = mine_level(sessions, lv, args.min_len, args.max_len,
                        args.min_occ, args.min_sessions, args.min_distinct)
        if args.dedup:
            fl = dedup_maximal(fl)
        level_counts[lv] = len(fl)
        all_flows.extend(fl)

    def amort_key(f):
        pb, tb = f.byte_stats()
        _, cons, _ = estimate_flow(pb, tb, f.n_occurrences_nonoverlap)
        return cons or 0
    all_flows.sort(key=lambda f: (-amort_key(f), -f.length_steps, f.sig_key))

    cand_path = os.path.join(args.out, "candidates.jsonl")
    records = []
    with open(cand_path, "w") as f:
        for i, fl in enumerate(all_flows, 1):
            pb, tb = fl.byte_stats()
            per_occ, cons, upper = estimate_flow(pb, tb, fl.n_occurrences_nonoverlap)
            fl.flow_id = f"F{i:04d}"
            rec = {
                "flow_id": fl.flow_id, "signature_level": fl.level,
                "length_steps": fl.length_steps,
                "occurrences": fl.n_occurrences_nonoverlap,
                "occurrences_raw_windows": fl.n_occurrences,
                "n_sessions": fl.n_sessions, "corpora": fl.corpora,
                "readable_signature": fl.readable_sig,
                "est_tokens_per_occurrence": per_occ,
                "est_amortizable_tokens": cons,
                "est_amortizable_tokens_upper": upper,
                "example_refs": [f"{o.corpus}/{o.session_id}:steps{o.start_idx}-{o.end_idx}"
                                 for o in fl.occurrences[:6]],
                "label": None, "skill_sketch": None,
            }
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _write_report(args, config, per_corpus, level_counts, records, missing)
    print(f"mine: {len(records)} candidates -> {cand_path}")
    print(f"mine: level counts {level_counts}")
    if missing:
        print(f"mine: SIGNAL_NOT_DETECTED / absent corpora: {missing}")
    if args.classify:
        from euthyna.mine.classify import enrich
        outp = os.path.join(args.out, "candidates_classified.jsonl")
        merged = enrich(cand_path, outp)
        print(f"mine: classified {len(merged)} flow families -> {outp}")
    return 0


def _write_report(args, config, per_corpus, level_counts, records, missing):
    rp = os.path.join(args.out, "flows_report.md")
    top = records[:10]
    # recurrence-ranked view (n_sessions, then occ) — the PRIMARY honest ranking.
    # Ranking by amortizable tokens conflates step SIZE with distillation VALUE,
    # so it is shown only as a labeled secondary axis below.
    top_recur = sorted(records, key=lambda r: (-r["n_sessions"], -r["occurrences"]))[:10]
    with open(rp, "w") as f:
        w = f.write
        w("# Flow Mining Report (Stage 0)\n\n")
        w("> **Descriptive only.** No skills are generated (Stage 2) and no "
          "efficacy/savings claims are made (Stage 3 A/B + A/A floor only). "
          "Amortization is a byte-weight **upper bound**, not a saving. Scope: "
          "only the corpora below — no generalization.\n\n")
        w(f"_window {args.min_len}-{args.max_len} steps · repeated = >={args.min_occ} "
          f"occ across >={args.min_sessions} sessions · min distinct steps/flow = "
          f"{args.min_distinct}._\n\n")
        w("## Per-corpus stats\n\n| corpus | mode | files | sessions | steps | present |\n")
        w("|---|---|---|---|---|---|\n")
        for name, d in per_corpus.items():
            w(f"| {name} | {d['mode']} | {d['n_files']} | {d['n_sessions']} | "
              f"{d['n_steps']} | {'yes' if d['present'] else '**NO**'} |\n")
        if missing:
            w(f"\n> **SIGNAL_NOT_DETECTED / absent:** {', '.join(missing)} — "
              f"reported, not omitted.\n")
        w("\n## Flows by signature level\n\n| level | candidate flows |\n|---|---|\n")
        for lv, c in level_counts.items():
            w(f"| {lv} | {c} |\n")
        w("\n## Top-10 candidates — PRIMARY ranking: recurrence (n_sessions, then occ)\n\n")
        if not top_recur:
            w("_No repeated flows met threshold. Reported SIGNAL_NOT_DETECTED._\n")
        else:
            _cand_table(w, top_recur)
        w("\n## Secondary view — byte-weight (amortizable tokens); NOT a value ranking\n\n")
        w("_Favors verbose-serialization frameworks (a large per-step payload tops "
          "this by size alone); says nothing about reuse or compressibility._\n\n")
        if top:
            _cand_table(w, top)
    print(f"mine: report -> {rp}")


def _cand_table(w, rows):
    w("| # | flow_id | lvl | len | occ | sess | corpora | per-occ tok | "
      "amort (cons) | amort (upper) |\n|---|---|---|---|---|---|---|---|---|---|\n")
    for i, r in enumerate(rows, 1):
        w(f"| {i} | {r['flow_id']} | {r['signature_level']} | {r['length_steps']} "
          f"| {r['occurrences']} | {r['n_sessions']} | {','.join(r['corpora'])} "
          f"| {r['est_tokens_per_occurrence']} | {r['est_amortizable_tokens']} "
          f"| {r['est_amortizable_tokens_upper']} |\n")
