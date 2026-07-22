#!/usr/bin/env python3
"""Serving-B candidate benchmark: deterministic trace features -> taxonomy labels.

Ground truth: the research repo's 174 traces that carry BOTH deterministic features
(bootstrap/pilot manifests) and adjudicated human-consensus labels. This is the same
task shape as Euthyna's runtime advisor input (metadata in, labels out), so scores
here transfer. Usage:

    python bench.py --endpoint http://127.0.0.1:8001 --tag minicpm5-1b
    python bench.py --baseline          # majority-class floor, no model needed
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import urllib.request

RESEARCH = os.path.expanduser(
    "~/Documents/agent-runtime-trace-taxonomy/projects/agent-runtime-trace-taxonomy")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

import yaml  # noqa: E402  (after RESEARCH so the module reads top-down)

L1_IDS: list[str] = []
L2_IDS: list[str] = []


def load_taxonomies() -> str:
    w = yaml.safe_load(open(f"{RESEARCH}/taxonomy/workload_taxonomy_v1.yaml"))
    z = yaml.safe_load(open(f"{RESEARCH}/taxonomy/waste_taxonomy_v1.yaml"))
    lines = ["WORKLOAD_L1 options (pick exactly one):"]
    for c in w["l1_primary"]:
        L1_IDS.append(c["id"])
        lines.append(f"- {c['id']}: {c['definition']}")
    lines.append("\nWASTE_L2 options (pick all that clearly apply, or none):")
    for fam in z["l2"]:
        for c in (fam.get("children") or [fam]):
            L2_IDS.append(c["id"])
            definition = (c.get("definition") or "").split(". ")[0]
            lines.append(f"- {c['id']}: {definition}")
    return "\n".join(lines)


def load_examples() -> list[dict]:
    labels = {}
    for f in glob.glob(f"{RESEARCH}/annotations/adjudicated/solver_*.jsonl"):
        for line in open(f):
            r = json.loads(line)
            labels[r["trace_id"]] = r["merged"]
    out = []
    for name in ("taxonomy_bootstrap_manifest.jsonl", "taxonomy_pilot_manifest.jsonl"):
        for line in open(f"{RESEARCH}/manifests/{name}"):
            r = json.loads(line)
            lab = labels.get(r["trace_id"])
            if not lab:
                continue
            features = {k: v for k, v in r["deterministic_features"].items() if v is not None}
            out.append({
                "trace_id": r["trace_id"],
                "features": features,
                "l1": lab["workload_primary_l1"],
                "waste": sorted(lab.get("waste_l2_labels") or []),
            })
    return out


PRIOR_NOTE = """
Base rates in this corpus (be conservative — deviate only on strong evidence):
- workload_l1 is PATCH_REASONING_DOMINANT for ~80%% of traces; LOCALIZATION_DOMINANT \
~13%%; the rest are rare (<2%% each).
- Two thirds of traces have NO waste labels at all. The most common waste labels are \
EDIT_TOOL_MECHANICAL_FAILURE, PATCH_CHURN, ENVIRONMENT_BLOCKED, VERIFICATION_GAP. \
Flag a waste label only when a metric clearly supports it; an empty list is the \
most likely correct answer.
"""


def build_prompt(taxonomy_text: str, features: dict, prior: bool = False) -> str:
    return f"""You are an annotator for SWE-agent execution traces. From the deterministic \
metrics of one trace, assign taxonomy labels.

{taxonomy_text}
{PRIOR_NOTE if prior else ''}
Trace metrics (fields with no signal are omitted):
{json.dumps(features, indent=0, sort_keys=True)}

Reply with ONLY this JSON, nothing else:
{{"workload_l1": "<one L1 id>", "waste_l2": ["<zero or more L2 ids>"]}}"""


def call_model(endpoint: str, model: str, prompt: str) -> str:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 200, "temperature": 0}
    req = urllib.request.Request(f"{endpoint}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    body = json.loads(urllib.request.urlopen(req, timeout=300).read())
    text = body["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?(</think>|\Z)", "", text, flags=re.S).strip()


def parse_reply(text: str):
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    l1 = d.get("workload_l1")
    waste = d.get("waste_l2")
    if l1 not in L1_IDS or not isinstance(waste, list):
        return None
    return {"l1": l1, "waste": sorted(w for w in waste if w in L2_IDS)}


def score(rows: list[dict]) -> dict:
    n = len(rows)
    parsed = [r for r in rows if r["pred"] is not None]
    l1_hits = sum(1 for r in parsed if r["pred"]["l1"] == r["gold_l1"])
    tp = fp = fn = 0
    set_hits = 0
    any_tp = any_tn = any_fp = any_fn = 0
    for r in parsed:
        gold, pred = set(r["gold_waste"]), set(r["pred"]["waste"])
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        set_hits += gold == pred
        if gold and pred: any_tp += 1
        elif not gold and not pred: any_tn += 1
        elif pred: any_fp += 1
        else: any_fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n": n,
        "parse_fail_rate": round(1 - len(parsed) / n, 4) if n else None,
        "l1_accuracy": round(l1_hits / len(parsed), 4) if parsed else None,
        "waste_exact_set": round(set_hits / len(parsed), 4) if parsed else None,
        "waste_micro_f1": round(2 * precision * recall / (precision + recall), 4)
                          if precision + recall else 0.0,
        "waste_any_balanced_acc": round(
            ((any_tp / (any_tp + any_fn) if any_tp + any_fn else 0.0)
             + (any_tn / (any_tn + any_fp) if any_tn + any_fp else 0.0)) / 2, 4)
            if parsed else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:8001")
    ap.add_argument("--tag", default=None, help="output name; default: served model id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--baseline", action="store_true", help="majority-class floor")
    ap.add_argument("--prior", action="store_true", help="include corpus base rates in the prompt")
    args = ap.parse_args()

    taxonomy_text = load_taxonomies()
    examples = load_examples()
    if args.limit:
        examples = examples[:args.limit]
    os.makedirs(OUT_DIR, exist_ok=True)

    if args.baseline:
        from collections import Counter
        majority = Counter(e["l1"] for e in examples).most_common(1)[0][0]
        rows = [{"pred": {"l1": majority, "waste": []},
                 "gold_l1": e["l1"], "gold_waste": e["waste"]} for e in examples]
        summary = {"tag": f"BASELINE(majority={majority})", **score(rows)}
        print(json.dumps(summary, indent=2))
        return 0

    models = json.loads(urllib.request.urlopen(f"{args.endpoint}/v1/models", timeout=10).read())
    model = models["data"][0]["id"]
    tag = args.tag or model.split("/")[-1]

    rows = []
    for i, e in enumerate(examples):
        try:
            reply = call_model(args.endpoint, model,
                               build_prompt(taxonomy_text, e["features"], prior=args.prior))
            pred = parse_reply(reply)
        except Exception as exc:
            reply, pred = f"ERROR: {exc}", None
        rows.append({"trace_id": e["trace_id"], "pred": pred, "gold_l1": e["l1"],
                     "gold_waste": e["waste"], "raw": reply[:400]})
        if (i + 1) % 25 == 0:
            print(f"  {tag}: {i + 1}/{len(examples)}")

    out = os.path.join(OUT_DIR, f"{tag}.jsonl")
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"tag": tag, "model": model, "date": datetime.date.today().isoformat(),
               **score(rows)}
    with open(os.path.join(OUT_DIR, f"{tag}.summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
