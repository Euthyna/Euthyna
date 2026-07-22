"""`euthyna doctor` — preflight for the sidecar pipeline (backend → gateway → host).

Every check prints PASS/WARN/FAIL with the reason; exit code 1 only on FAIL.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
from pathlib import Path

import yaml

from euthyna.gateway.config import DEFAULT_PORT


def _reach(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _opencode_configs() -> list[Path]:
    return [Path("opencode.json"), Path("opencode.jsonc"),
            Path.home() / ".config" / "opencode" / "opencode.json"]


def run(args) -> int:
    checks: list[tuple[str, str, str]] = []  # (level, name, detail)

    profile_path = Path(args.profile)
    base_url = None
    if profile_path.exists():
        try:
            data = yaml.safe_load(profile_path.read_text())
            base_url = data["base_url"]
            checks.append(("PASS", "profile", f"{profile_path} (backend {base_url})"))
        except Exception as exc:
            checks.append(("FAIL", "profile", f"{profile_path}: {exc}"))
    else:
        checks.append(("FAIL", "profile", f"{profile_path} not found — run `euthyna probe` first"))

    if base_url:
        try:
            models = _reach(f"{base_url.rstrip('/')}/v1/models")
            checks.append(("PASS", "backend", models["data"][0]["id"]))
        except Exception as exc:
            checks.append(("FAIL", "backend", f"{base_url}: {exc}"))

    gateway = f"http://127.0.0.1:{args.port}"
    try:
        health = _reach(f"{gateway}/healthz")
        detail = f"{gateway} v{health.get('version')}"
        if health.get("transparent"):
            detail += " (TRANSPARENT — taps disabled)"
        checks.append(("PASS", "gateway", detail))
    except Exception:
        checks.append(("WARN", "gateway", f"{gateway} not running — start with `euthyna up`"))

    if args.host == "opencode":
        if shutil.which("opencode"):
            checks.append(("PASS", "opencode", shutil.which("opencode")))
        else:
            checks.append(("WARN", "opencode", "binary not on PATH — npm i -g opencode-ai"))
        wired = [p for p in _opencode_configs() if p.exists() and f":{args.port}" in p.read_text()]
        if wired:
            checks.append(("PASS", "opencode config", f"gateway baseURL found in {wired[0]}"))
        else:
            checks.append(("WARN", "opencode config",
                           f"no opencode.json points at the gateway (:{args.port}) — see docs/SETUP.md"))

    if os.environ.get("EUTHYNA_TRANSPARENT") == "1":
        checks.append(("WARN", "env", "EUTHYNA_TRANSPARENT=1 — gateway is a pure pipe"))

    width = max(len(name) for _, name, _ in checks)
    for level, name, detail in checks:
        print(f"[{level:<4}] {name:<{width}}  {detail}")
    return 1 if any(level == "FAIL" for level, _, _ in checks) else 0
