"""Observation taps: usage extraction, JSONL ledger, metadata-only traces, prefix watchdog.

Everything here is fail-open: the gateway calls ``Taps.observe`` inside try/except and a
tap failure must never block or alter the pipe. Billing fields are never fabricated —
usage lands in the ledger exactly as the provider sent it, and cost rows carry
observed/imputed flags (euthyna.core.accountant). Traces record hashes and structure,
not content: metadata-only capture is the privacy default.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections import OrderedDict
from typing import Optional

from euthyna.core.accountant import cost_row_from_usage

from .config import GatewayConfig

SESSION_HEADER = "X-Euthyna-Session"
_MAX_SESSIONS = 64
_SAFE_SESSION = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _safe_session(session: str) -> str:
    """Session ids become filenames; anything unusual is replaced by a hash id."""
    if _SAFE_SESSION.fullmatch(session):
        return session
    return "hdr-" + _sha(session.encode())[:10]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(messages) -> str:
    return json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


class PrefixMonitor:
    """Per-session byte-prefix stability over canonicalized ``messages[]``.

    Session key is the X-Euthyna-Session header when present; otherwise calls are
    chained by the append-only property of agent loops (a new call's canonical form
    starts with the previous call's, minus the closing bracket).
    """

    def __init__(self) -> None:
        self._last: "OrderedDict[str, str]" = OrderedDict()

    def observe(self, messages, session: Optional[str]) -> tuple[str, Optional[float]]:
        canonical = _canonical(messages)
        if not messages:
            # No messages (e.g. /v1/completions uses `prompt`): nothing to chain or
            # compare. Storing '[]' would make every later call chain onto it.
            return session or "auto-" + _sha(canonical.encode())[:10], None
        if session is None:
            session = self._chain(canonical)
        prev = self._last.get(session)
        ratio = None
        if prev:
            # Compare against the open form (closing bracket stripped) so that a pure
            # append-only continuation scores exactly 1.0.
            base = prev[:-1] if prev.endswith("]") else prev
            ratio = _common_prefix_len(base, canonical) / len(base) if base else None
        self._last[session] = canonical
        self._last.move_to_end(session)
        while len(self._last) > _MAX_SESSIONS:
            self._last.popitem(last=False)
        return session, ratio

    def _chain(self, canonical: str) -> str:
        for session, prev in reversed(self._last.items()):
            if len(prev) > 2 and canonical.startswith(prev[:-1]):
                return session
        return "auto-" + _sha(canonical.encode())[:10]


def extract_usage(dialect: str, body: Optional[dict], sse_text: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    """Pull (usage, model) out of a response body or SSE stream. Returns raw provider shapes."""
    if body is not None:
        return body.get("usage"), body.get("model")
    if sse_text is None:
        return None, None
    if dialect == "anthropic":
        return _anthropic_stream(sse_text)
    return _openai_stream(sse_text)


def _openai_stream(sse_text: str) -> tuple[Optional[dict], Optional[str]]:
    usage, model = None, None
    for data in _sse_datas(sse_text):
        model = data.get("model") or model
        if data.get("usage"):
            usage = data["usage"]
    return usage, model


def _anthropic_stream(sse_text: str) -> tuple[Optional[dict], Optional[str]]:
    usage: dict = {}
    model = None
    for data in _sse_datas(sse_text):
        if data.get("type") == "message_start":
            message = data.get("message") or {}
            model = message.get("model") or model
            usage.update(message.get("usage") or {})
        elif data.get("type") == "message_delta" and data.get("usage"):
            usage.update(data["usage"])
    return (usage or None), model


def _sse_datas(sse_text: str):
    for line in sse_text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    yield json.loads(payload)
                except ValueError:
                    continue


def normalize_anthropic_usage(usage: dict) -> dict:
    """Map Anthropic usage names onto the accountant's normalized shape.

    Anthropic's input_tokens EXCLUDES cache reads/writes; the normalized
    prompt_tokens INCLUDES them (OpenAI convention). Mechanical mapping only —
    absent fields stay absent, never invented.
    """
    out: dict = {}
    cached = usage.get("cache_read_input_tokens")
    creation = usage.get("cache_creation_input_tokens")
    if "input_tokens" in usage:
        out["prompt_tokens"] = usage["input_tokens"] + (cached or 0) + (creation or 0)
    if "output_tokens" in usage:
        out["completion_tokens"] = usage["output_tokens"]
    details = {}
    if cached is not None:
        details["cached_tokens"] = cached
    if creation is not None:
        details["cache_creation_tokens"] = creation
    if details:
        out["prompt_tokens_details"] = details
    return out


class Taps:
    """Ledger + trace + prefix watchdog. One instance per gateway process."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.prefix = PrefixMonitor()

    def observe(
        self,
        *,
        dialect: str,
        path: str,
        status: int,
        latency_ms: float,
        request_json: Optional[dict],
        response_json: Optional[dict],
        response_sse: Optional[str],
        session_header: Optional[str],
        injected: bool,
        request_sha: Optional[tuple[str, str]] = None,
        truncated: bool = False,
    ) -> None:
        request_json = request_json or {}
        messages = request_json.get("messages") or []
        if session_header is not None:
            session_header = _safe_session(session_header)
        session, ratio = self.prefix.observe(messages, session_header)
        usage, model = extract_usage(dialect, response_json, response_sse)
        model = model or request_json.get("model")

        cost, cost_error = None, None
        profile = self.config.profile_for(dialect)
        if usage is not None and profile and profile.accountant_model:
            normalized = normalize_anthropic_usage(usage) if dialect == "anthropic" else usage
            try:
                cost = cost_row_from_usage(
                    normalized, model=profile.accountant_model, price_date=profile.price_date
                )
            except Exception as exc:  # unknown model / missing sheet: record why, never guess
                cost_error = str(exc)
        elif usage is not None:
            cost_error = "no accountant_model in profile"

        # Local timezone: ledger files are named by local day, matching `euthyna report`.
        now = _dt.datetime.now().astimezone()
        row = {
            "ts": now.isoformat(timespec="milliseconds"),
            "session": session,
            "dialect": dialect,
            "path": path,
            "status": status,
            "model": model,
            "latency_ms": round(latency_ms, 1),
            "usage": usage,  # exactly as the provider sent it
            "gateway_injected": injected,
            "prefix_stable_ratio": ratio,
            "cost": cost,
            "cost_error": cost_error,
            # True when the response was not fully observed (buffer cap, disconnect):
            # the call is still counted, usage may be missing.
            "tap_truncated": truncated,
        }
        if request_sha is not None:
            row["request_sha_before"], row["request_sha_after"] = request_sha
        self._append(self.config.ledger_dir / f"{now.date().isoformat()}.jsonl", row)

        self._append(
            self.config.traces_dir / f"{session}.jsonl",
            {
                "ts": row["ts"],
                "status": status,
                "model": model,
                "n_messages": len(messages),
                "roles": [m.get("role") for m in messages if isinstance(m, dict)],
                "message_sha256": [
                    _sha(_canonical(m).encode())[:16] for m in messages
                ],
                "message_bytes": [len(_canonical(m).encode()) for m in messages],
                "prefix_stable_ratio": ratio,
                "usage": usage,
            },
        )

    @staticmethod
    def _append(path, obj) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
