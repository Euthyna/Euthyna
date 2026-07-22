#!/usr/bin/env python3
"""Classical supervised baseline on the same 174 examples: 5-fold CV, logistic
regression + gradient boosting over the deterministic features. If this beats
zero-shot LLMs, the label-assignment job belongs to supervised learning, not
prompting."""
from __future__ import annotations

import json

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from bench import load_examples

TOP_WASTE = ["EDIT_TOOL_MECHANICAL_FAILURE", "PATCH_CHURN", "ENVIRONMENT_BLOCKED",
             "VERIFICATION_GAP", "FAILED_RECOVERY", "CONTEXT_BLOAT"]


def vectorize(examples):
    keys = sorted({k for e in examples for k, v in e["features"].items()
                   if isinstance(v, (int, float, bool))})
    event_keys = sorted({k for e in examples
                         for k in (e["features"].get("event_type_counts") or {})})
    rows = []
    for e in examples:
        f = e["features"]
        row = [float(f.get(k) or 0) for k in keys]
        counts = f.get("event_type_counts") or {}
        row += [float(counts.get(k) or 0) for k in event_keys]
        rows.append(row)
    return np.array(rows), keys + [f"evt_{k}" for k in event_keys]


def main():
    examples = load_examples()
    X, _ = vectorize(examples)
    out = {"n": len(examples), "cv": "5-fold stratified, out-of-fold predictions"}

    # L1: 6-way — collapse rare classes into OTHER so folds stratify.
    y_l1 = np.array([e["l1"] if e["l1"] in ("PATCH_REASONING_DOMINANT",
                     "LOCALIZATION_DOMINANT") else "OTHER" for e in examples])
    for name, clf in [
        ("logreg", make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000,
                                                                      class_weight="balanced"))),
        ("gbdt", GradientBoostingClassifier(random_state=0)),
    ]:
        pred = cross_val_predict(clf, X, y_l1, cv=StratifiedKFold(5, shuffle=True,
                                                                  random_state=0))
        out[f"l1_accuracy_{name}"] = round(float((pred == y_l1).mean()), 4)
        out[f"l1_balanced_acc_{name}"] = round(
            float(balanced_accuracy_score(y_l1, pred)), 4)

    # Waste: any-flag binary + per-label binaries for the frequent labels.
    y_any = np.array([bool(e["waste"]) for e in examples])
    clf = GradientBoostingClassifier(random_state=0)
    pred = cross_val_predict(clf, X, y_any, cv=StratifiedKFold(5, shuffle=True,
                                                               random_state=0))
    out["waste_any_balanced_acc_gbdt"] = round(
        float(balanced_accuracy_score(y_any, pred)), 4)

    per_label = {}
    for label in TOP_WASTE:
        y = np.array([label in e["waste"] for e in examples])
        if y.sum() < 8:
            continue
        pred = cross_val_predict(GradientBoostingClassifier(random_state=0), X, y,
                                 cv=StratifiedKFold(5, shuffle=True, random_state=0))
        per_label[label] = {"n_pos": int(y.sum()),
                            "balanced_acc": round(float(balanced_accuracy_score(y, pred)), 4),
                            "f1": round(float(f1_score(y, pred)), 4)}
    out["waste_per_label_gbdt"] = per_label
    print(json.dumps(out, indent=2))
    with open("results/classical-baseline.summary.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
