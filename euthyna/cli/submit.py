"""`euthyna submit` — package your local Euthyna telemetry for community submission.

Privacy is allowlist-shaped, not filter-shaped: rows are PROJECTED through an
explicit schema (unknown fields are dropped, never copied), so nothing rides
along by accident. On top of that:

1. Session ids are re-mapped to s001, s002, … (the mapping never leaves your machine).
2. Message hashes are re-keyed with a fresh random HMAC salt per submission and
   the salt is discarded — within-submission structure (what flow mining needs)
   survives; dictionary guessing and cross-submission linkage do not.
3. Model names are pseudonymized by default (``--include-model-names`` opts in).
4. Free-text error fields become a closed enum; a length guard remains as backstop.
5. You see a full preview and must confirm. Nothing is uploaded — the output is
   an offline tarball you submit yourself.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac as _hmac
import io
import json
import secrets
import tarfile
from pathlib import Path
from typing import Callable, Optional

from euthyna.ledger import home
from euthyna.version import __version__

TIER = "hash-only"
SCHEMA_VERSION = 2
_MAX_STR = 120  # backstop guard over the projected output

_USAGE_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens",
               "output_tokens", "reasoning_tokens", "cache_read_input_tokens",
               "cache_creation_input_tokens"}
_DETAIL_KEYS = {"cached_tokens", "cache_creation_tokens", "reasoning_tokens"}
_ROLES = {"system", "user", "assistant", "tool"}
_PATHS = {"/v1/chat/completions", "/v1/completions", "/v1/messages"}


def _clean_usage(usage) -> Optional[dict]:
    if not isinstance(usage, dict):
        return None
    out = {k: v for k, v in usage.items() if k in _USAGE_KEYS and isinstance(v, (int, float))}
    for detail_key in ("prompt_tokens_details", "completion_tokens_details"):
        detail = usage.get(detail_key)
        if isinstance(detail, dict):
            sub = {k: v for k, v in detail.items()
                   if k in _DETAIL_KEYS and isinstance(v, (int, float))}
            if sub:
                out[detail_key] = sub
    return out or None


def _clean_cost(cost) -> Optional[dict]:
    if not isinstance(cost, dict):
        return None
    native = {k: v for k, v in (cost.get("native_tokens") or {}).items()
              if v is None or isinstance(v, (int, float))}
    return {"native_tokens": native,
            "list_cost_usd": cost.get("list_cost_usd"),
            "cache_status": cost.get("cache_status")}


def _error_enum(err) -> Optional[str]:
    if not err:
        return None
    text = str(err).lower()
    if "no dated price sheet" in text:
        return "missing_price_sheet"
    if "not in price sheet" in text or "no cache schema" in text:
        return "unknown_model"
    if "accountant_model" in text:
        return "no_profile"
    return "other"


def _guard_strings(obj, where: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > _MAX_STR:
                raise ValueError(
                    f"content-leak guard: field {k!r} in {where} is {len(v)} chars — "
                    "refusing to package")
            _guard_strings(v, where)
    elif isinstance(obj, list):
        for v in obj:
            _guard_strings(v, where)


def collect(home_dir: Path, date_from: str, date_to: str,
            include_model_names: bool = False) -> dict:
    """Project everything in the window through the allowlist schema."""
    session_map: dict[str, str] = {}
    salt = secrets.token_bytes(32)  # per-submission; discarded after packaging

    def anon(session: str) -> str:
        if session not in session_map:
            session_map[session] = f"s{len(session_map) + 1:03d}"
        return session_map[session]

    def rekey(digest: str) -> str:
        return _hmac.new(salt, str(digest).encode(), "sha256").hexdigest()[:16]

    model_fn: Callable[[Optional[str]], Optional[str]] = (
        (lambda m: m) if include_model_names else
        (lambda m: "model-" + hashlib.sha256(m.encode()).hexdigest()[:8] if m else None))

    def ledger_row(row: dict) -> dict:
        out = {
            "ts": row.get("ts"),
            "session": anon(row.get("session") or "?"),
            "dialect": row.get("dialect") if row.get("dialect") in ("openai", "anthropic") else "other",
            "path": row.get("path") if row.get("path") in _PATHS else "other",
            "status": row.get("status"),
            "latency_ms": row.get("latency_ms"),
            "model": model_fn(row.get("model")),
            "usage": _clean_usage(row.get("usage")),
            "gateway_injected": bool(row.get("gateway_injected", False)),
            "prefix_stable_ratio": row.get("prefix_stable_ratio"),
            "cost": _clean_cost(row.get("cost")),
            "cost_quality": row.get("cost_quality"),
            "cost_error": _error_enum(row.get("cost_error")),
            "tap_truncated": bool(row.get("tap_truncated", False)),
            "request_parse_error": row.get("request_parse_error"),
        }
        _guard_strings(out, "ledger")
        return out

    def trace_event(event: dict) -> dict:
        out = {
            "ts": event.get("ts"),
            "status": event.get("status"),
            "n_messages": event.get("n_messages"),
            "roles": [r if r in _ROLES else "other" for r in (event.get("roles") or [])],
            "message_hmac": [rekey(h) for h in (event.get("message_sha256") or [])],
            "message_bytes": [int(b) for b in (event.get("message_bytes") or [])
                              if isinstance(b, (int, float))],
            "prefix_stable_ratio": event.get("prefix_stable_ratio"),
            "usage": _clean_usage(event.get("usage")),
        }
        _guard_strings(out, "trace")
        return out

    ledgers = {}
    for f in sorted((home_dir / "ledger").glob("*.jsonl")):
        if not (date_from <= f.stem <= date_to):
            continue
        rows = []
        for line in f.read_text().splitlines():
            try:
                rows.append(ledger_row(json.loads(line)))
            except ValueError as exc:
                if "content-leak guard" in str(exc):
                    raise
                continue
        if rows:
            ledgers[f.name] = rows

    traces = {}
    for f in sorted((home_dir / "traces").glob("*.jsonl")):
        events = []
        for line in f.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if date_from <= event.get("ts", "")[:10] <= date_to:
                events.append(trace_event(event))
        if events:
            traces[anon(f.stem) + ".jsonl"] = events
    return {"ledgers": ledgers, "traces": traces, "n_sessions": len(session_map)}


def summarize(bundle: dict, include_model_names: bool = False) -> dict:
    rows = [r for rows in bundle["ledgers"].values() for r in rows]
    prompt = sum((r.get("usage") or {}).get("prompt_tokens") or 0 for r in rows)
    completion = sum((r.get("usage") or {}).get("completion_tokens") or 0 for r in rows)
    return {
        "tier": TIER,
        "schema": SCHEMA_VERSION,
        "model_names": "raw" if include_model_names else "pseudonymized",
        "euthyna_version": __version__,
        "calls": len(rows),
        "sessions": bundle["n_sessions"],
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "models": sorted({r.get("model") for r in rows if r.get("model")}),
        "ledger_days": sorted(bundle["ledgers"]),
    }


def write_bundle(bundle: dict, manifest: dict, out_dir: Path) -> Path:
    payload = json.dumps(manifest, sort_keys=True).encode()
    sid = hashlib.sha256(payload).hexdigest()[:10]
    manifest = {**manifest, "submission_id": sid}
    out = out_dir / f"euthyna-submission-{sid}.tar.gz"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        def add(name: str, text: str) -> None:
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        add("MANIFEST.json", json.dumps(manifest, indent=2))
        for fname, rows in bundle["ledgers"].items():
            add(f"ledger/{fname}", "\n".join(json.dumps(r) for r in rows))
        for fname, events in bundle["traces"].items():
            add(f"traces/{fname}", "\n".join(json.dumps(e) for e in events))
    return out


def run(args) -> int:
    home_dir = home()
    date_to = args.to_date or _dt.date.today().isoformat()
    date_from = args.from_date or date_to
    try:
        bundle = collect(home_dir, date_from, date_to,
                         include_model_names=args.include_model_names)
    except ValueError as exc:
        print(f"submit: BLOCKED — {exc}")
        return 1
    manifest = summarize(bundle, include_model_names=args.include_model_names)
    if not manifest["calls"]:
        print(f"submit: no ledger rows in {date_from}..{date_to} under {home_dir}")
        return 0

    print(f"submit: preview ({date_from}..{date_to}, tier: {TIER}, schema v{SCHEMA_VERSION} — "
          "allowlist-projected; no message content exists in this data)")
    for k, v in manifest.items():
        print(f"  {k}: {v}")
    sample = next(iter(bundle["ledgers"].values()))[0]
    print(f"  sample ledger row: {json.dumps(sample)[:200]}...")
    if not args.yes:
        answer = input("Package exactly this? [y/N] ").strip().lower()
        if answer != "y":
            print("submit: aborted, nothing written")
            return 0
    out = write_bundle(bundle, manifest, Path(args.out))
    print(f"submit: wrote {out}")
    print("submit: next step — open an issue titled 'submission: <id>' at "
          "https://github.com/Euthyna/euthyna-traces and attach this file. "
          "Nothing has been uploaded.")
    return 0
