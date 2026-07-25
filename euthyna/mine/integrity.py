"""Integrity / self-consistency check (NOT precision — see docs/flow-mining.md).

Randomly sample N candidate flows, resolve each example_ref back to the source
records, recompute the step signatures at the candidate's level, and verify the
referenced spans are byte/structure-identical across occurrences. Reports
hits/misses. This is a SELF-CONSISTENCY check (the miner groups by signature, so re-checking
the signature is tautological — it verifies no hash collisions / correct ref
resolution, NOT that flows are meaningful). Real precision needs an external
falsifiable adjudicator and is not done here. Deterministic given --seed.

Verification is done on the SAME normalized signatures the miner uses — it does
not print raw content, so the audit itself leaks nothing.
"""
from __future__ import annotations
import json
import os
import random
import glob
from .adapters import ADAPTERS
from .loaders import load_hash_only_jsonl
from .miner import _step_sig


def _load_corpus_sessions(config):
    sess_by_ref = {}
    for name, c in config.items():
        files = sorted(glob.glob(os.path.expanduser(c["glob"])))
        for fp in files:
            if c.get("mode") == "hash_only":
                sessions = load_hash_only_jsonl(fp, name)
            elif c.get("adapter") in ADAPTERS:
                sessions = ADAPTERS[c["adapter"]](fp, name)
            else:
                from .loaders import load_content_jsonl
                sessions = load_content_jsonl(fp, name)
            for s in sessions:
                sess_by_ref[(name, s.session_id)] = s
    return sess_by_ref


def _parse_ref(ref):
    # "corpus/session_id:stepsA-B"
    corpus, rest = ref.split("/", 1)
    sid, span = rest.rsplit(":steps", 1)
    a, b = span.split("-")
    return corpus, sid, int(a), int(b)


def run_precision(config_path, candidates_path, n=10, seed=1):
    with open(config_path) as f:
        config = json.load(f)
    cands = [json.loads(line) for line in open(candidates_path)]
    sess = _load_corpus_sessions(config)

    rng = random.Random(seed)
    sample = rng.sample(cands, min(n, len(cands)))
    results = []
    hits = 0
    for c in sample:
        level = c["signature_level"]
        refs = c["example_refs"]
        detail = {"flow_id": c["flow_id"], "level": level,
                  "claimed_occ": c["occurrences"], "refs_checked": len(refs)}
        ok = True
        first_sig = None
        for ref in refs:
            corpus, sid, a, b = _parse_ref(ref)
            s = sess.get((corpus, sid))
            if s is None or b >= len(s.steps):
                ok = False
                detail["error"] = f"ref {ref} unresolved"
                break
            window = s.steps[a:b + 1]
            sig = "|".join(_step_sig(st, level) for st in window)
            if first_sig is None:
                first_sig = sig
            elif sig != first_sig:
                ok = False
                detail["error"] = f"ref {ref} signature mismatch"
                break
        detail["verified_repeat"] = ok
        if ok:
            hits += 1
        results.append(detail)
    return {"sampled": len(sample), "hits": hits,
            "misses": len(sample) - hits,
            "self_consistency": round(hits / len(sample), 3) if sample else None,
            "seed": seed, "details": results}


if __name__ == "__main__":
    import sys
    cfg, cand = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    out = run_precision(cfg, cand, n, seed)
    print(json.dumps(out, indent=2))
