#!/usr/bin/env python3
"""Refuse to start a 50-instance SWE-bench run that cannot produce usable data.

Every check here corresponds to something that actually went wrong today, or to a
measured limit that would silently ruin the output. A run costs hours; a preflight costs
seconds, and the whole point of the instrument is to not discover this afterwards.

Exit 0 = safe to run. Exit 1 = at least one blocker. Warnings do not block.
"""
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
GATEWAY = "http://127.0.0.1:4517"
INSTANCES = HERE / "swebench28-arm64.txt"
MSWEA_ENV = Path.home() / "Library/Application Support/mini-swe-agent/.env"
# SWE-bench observations are whole-file reads and test output. The toy task overran 16384
# *after* solving, so anything near that truncates real work.
#
# This was 65536 until the RAM budget was measured. On 24 GB the KV cache for a 65k window
# leaves ~7 GB for a container VM, and SWE-bench containers were provisioned with 10 GB in
# the research config — it does not fit. 40960 is the model's native pre-YaRN window and
# costs 6.19 GB of KV, freeing 9.5 GB. The threshold moved because a measurement forced it,
# not to make this check pass; the compensating control is capping a single observation
# (MAX_OBSERVATION_CHARS below) so one file read cannot eat the window.
MIN_CONTEXT = 40960
# mini-swe-agent defaults to 100_000 chars (~25k tokens), which is 60% of a 40960 window in
# one step. Capped in the runner instead.
MAX_OBSERVATION_CHARS = 20000

blockers: list = []
warnings: list = []


def check(label, ok, detail="", blocking=True):
    mark = "PASS" if ok else ("FAIL" if blocking else "WARN")
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        (blockers if blocking else warnings).append(f"{label}: {detail}")
    return ok


def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    print("SWE-bench 50 preflight\n")

    # --- the instrument -------------------------------------------------------------
    try:
        h = get_json(f"{GATEWAY}/healthz")
        check("gateway reachable", h.get("ok") is True, f"version {h.get('version')}")
        check("gateway is observing", not h.get("transparent"),
              "transparent mode records nothing")
    except Exception as exc:
        check("gateway reachable", False, f"{type(exc).__name__}: {exc}")

    # --- the model ------------------------------------------------------------------
    served = None
    try:
        served = get_json(f"{GATEWAY}/v1/models")["data"][0]["id"]
        print(f"  [INFO] gateway fronts model: {served}")
    except Exception as exc:
        check("backend reachable through the gateway", False, f"{type(exc).__name__}")

    if served:
        ctx = None
        try:
            ctx = get_json("http://127.0.0.1:8000/v1/models")["data"][0].get("max_model_len")
        except Exception:
            pass
        check(f"context window >= {MIN_CONTEXT:,}", bool(ctx and ctx >= MIN_CONTEXT),
              f"serving {ctx:,} — real observations will truncate" if ctx else "unknown")
        check("model is the SWE-tuned one", "SWE-Lego" in served or "swe" in served.lower(),
              f"serving {served}; a base model will resolve far fewer instances",
              blocking=False)

    # --- the harness ----------------------------------------------------------------
    mini = shutil.which("mini-extra") or str(Path.home() / ".venv-mini-swe/bin/mini-extra")
    check("mini-extra present", Path(mini).exists(), mini)

    env_text = MSWEA_ENV.read_text() if MSWEA_ENV.exists() else ""
    check("mini-swe-agent global config exists", bool(env_text), str(MSWEA_ENV))
    check("routed through the gateway", "127.0.0.1:4517" in env_text,
          "OPENAI_BASE_URL must point at the gateway or nothing is recorded")
    # litellm aborts the whole run computing cost for a model it has no price sheet for.
    check("cost tracking set to ignore_errors",
          "MSWEA_COST_TRACKING=ignore_errors" in env_text,
          "litellm will abort the run on an unpriced local model")

    # --- containers -----------------------------------------------------------------
    # Honour whatever mini-swe-agent is configured to call, not whatever is installed:
    # MSWEA_DOCKER_EXECUTABLE=podman is how this host runs containers without Docker
    # Desktop (which needs an admin password).
    configured = "docker"
    for line in env_text.splitlines():
        if line.startswith("MSWEA_DOCKER_EXECUTABLE="):
            configured = line.split("=", 1)[1].strip()
    runtime = configured if shutil.which(configured) else None
    if check("container runtime available", bool(runtime),
              runtime or f"{configured!r} configured but not on PATH"):
        try:
            subprocess.run([runtime, "info"], capture_output=True, timeout=25, check=True)
            check(f"{runtime} daemon responding", True)
        except Exception as exc:
            check(f"{runtime} daemon responding", False, type(exc).__name__)

    # --- the work list --------------------------------------------------------------
    if check("instance list present", INSTANCES.exists(), str(INSTANCES)):
        ids = [x for x in INSTANCES.read_text().split() if x]
        check("instance list non-empty", len(ids) > 0, f"{len(ids)} arm64-available ids")

    # --- the tap actually records actions -------------------------------------------
    # A run that records no actions mines nothing, which is the failure that would only
    # show up after the hours were spent.
    sys.path.insert(0, "/Users/loki/Desktop/euthyna")
    try:
        import datetime as dt

        from euthyna.ledger import action_coverage, load_rows, observed_vocabulary
        rows = load_rows(dt.date.today().isoformat())
        cov = action_coverage(rows)
        vocab = observed_vocabulary(rows)
        check("actions tap is recording", cov["with_actions"] > 0,
              f"{cov['with_actions']}/{cov['calls']} calls carry actions")
        check("observed vocabulary is bash-shaped",
              any(v.startswith("bash") for v in vocab),
              f"{sorted(vocab)[:6]} — mini-swe-agent should produce bash:<verb>",
              blocking=False)
    except Exception as exc:
        check("ledger readable", False, f"{type(exc).__name__}: {exc}")

    print()
    for w in warnings:
        print(f"  warning: {w}")
    if blockers:
        print(f"\n{len(blockers)} blocker(s) — not safe to start:")
        for b in blockers:
            print(f"  - {b}")
        return 1
    print("preflight clean — safe to start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
