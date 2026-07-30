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
from euthyna.ledger import cache_status, cost_quality

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

    def observe(self, messages, session: Optional[str],
                seed: Optional[str] = None) -> tuple[str, Optional[float]]:
        canonical = _canonical(messages)
        if not messages:
            # No messages (e.g. /v1/completions uses `prompt`): nothing to chain or
            # compare. Storing '[]' would make every later call chain onto it.
            # Hash the caller-provided seed (the prompt) rather than the constant
            # '[]', so unrelated completions calls don't collapse into one session.
            return session or "auto-" + _sha((seed or canonical).encode())[:10], None
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


# Cache-write vs cache-read multipliers: a mutated prefix is re-written at 1.25x
# instead of re-read at 0.10x, so the marginal cost of a mutation is (1.25 - 0.10).
PREFIX_MUTATION_MULTIPLIER = 1.15


def _tool_names(tools) -> list:
    out = []
    for t in tools or []:
        if isinstance(t, dict):
            fn = t.get("function") if isinstance(t.get("function"), dict) else None
            name = (fn or t).get("name")
            if name:
                out.append(name)
    return out


class PrefixSegmentMonitor:
    """Watches the two cache-critical request segments — ``tools`` and ``system`` —
    for byte-level change within a session.

    Providers invalidate a cached prefix top-down (tools -> system -> messages), so a
    change to either segment re-writes the whole prefix at the cache-creation rate
    instead of re-reading it. Nobody publishes what that costs in practice for any
    agent harness; this records it per event.

    The cost is expressed in the previous call's OBSERVED prompt tokens whenever the
    provider reported them. If it did not, ``cost_tok_eq`` is None with a stated basis
    — an unmeasurable mutation is never given an invented size.
    """

    def __init__(self) -> None:
        self._last: "OrderedDict[str, dict]" = OrderedDict()

    def observe(self, session: str, request_json: dict,
                prev_prompt_tokens: Optional[int]) -> Optional[dict]:
        tools = request_json.get("tools")
        system = request_json.get("system")
        state = {
            "tools": _canonical(tools) if tools is not None else None,
            "system": _canonical(system) if system is not None else None,
            "model": request_json.get("model"),
            "tool_names": _tool_names(tools),
        }
        prev = self._last.get(session)
        self._last[session] = state
        self._last.move_to_end(session)
        while len(self._last) > _MAX_SESSIONS:
            self._last.popitem(last=False)
        if prev is None:
            return None  # first call of a session establishes the baseline

        changed = [k for k in ("tools", "system", "model") if prev[k] != state[k]]
        if not changed:
            return None
        before, after = set(prev["tool_names"]), set(state["tool_names"])
        return {
            "segments": changed,
            "tools_added": sorted(after - before),
            "tools_removed": sorted(before - after),
            "cost_tok_eq": (round(PREFIX_MUTATION_MULTIPLIER * prev_prompt_tokens, 1)
                            if prev_prompt_tokens else None),
            "cost_basis": ("observed_prev_prompt_tokens" if prev_prompt_tokens
                           else "unavailable"),
        }


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


# Tools whose first argument is a command line, so the tool name alone says nothing
# about what the step did. mini-SWE-agent has exactly one tool, and every action in a
# trace mined from it would otherwise be the same symbol.
_COMMAND_TOOLS = {"bash", "shell", "terminal", "run_command", "execute_bash",
                  "run_shell_command", "execute_command"}
_COMMAND_ARG_KEYS = ("command", "cmd", "script", "shell_command")


# A plausible command name, and nothing else, may be recorded. This is an ALLOWLIST on
# purpose: anything not shaped like a bare command name is data, and data does not go in
# the ledger.
#
# Two constraints beyond the character set, both there to keep a credential out:
#
#   <= 16 chars — every command an agent actually runs is far shorter (grep, sed, python3,
#   pytest, git); `docker-compose` at 14 is about the longest real one. Most secrets are
#   longer. A genuinely longer command name records as bare `bash`: less detail, never a
#   leak.
#
#   at least one lowercase letter — Unix command names are lowercase by overwhelming
#   convention, while env-var names, constants and access keys are upper. This is what
#   rejects a line consisting of nothing but `AKIAIOSFODNN7EXAMPLE`, which the character
#   set alone accepts because it is indistinguishable from a command name by shape.
#
# Residual risk, stated rather than papered over: a short all-lowercase high-entropy token
# still passes. The surface is small and the alternative — a maintained list of command
# names — breaks on every real toolchain.
_VERB = re.compile(r"\A(?=[A-Za-z0-9_.+-]{1,16}\Z)(?=.*[a-z])[A-Za-z0-9][A-Za-z0-9_.+-]*\Z")
# Leading VAR=VALUE assignments are shell prefix syntax, not the verb — and they are
# exactly where secrets appear. mini-swe-agent's own prompt template tells the agent to
# write `MY_ENV_VAR=MY_VALUE cd /path && ...`, so this is a routine input, not an edge case.
_ENV_ASSIGN = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")


def _command_verb(command: str) -> Optional[str]:
    """The command name a shell line invokes, or None when it cannot be named safely.

    Only a bare command name is ever returned. Everything else in the line — paths,
    patterns, source text, credentials — is the user's data and is discarded. When the
    first meaningful token does not look like a command name, this returns None rather
    than guessing, because a wrong guess here writes user data into the ledger.
    """
    for token in command.strip().split():
        if _ENV_ASSIGN.match(token):
            continue                      # VAR=VALUE prefix: keep looking for the verb
        token = token.strip("'\"")       # a quoted verb is still that verb
        token = token.split("/")[-1]      # /usr/bin/grep and grep are one action
        return token if _VERB.match(token) else None
    return None


def _refine_action(name: str, arguments) -> str:
    """``tool`` normally, ``tool:verb`` for shell-style tools.

    Only the command NAME is kept. That name is what distinguishes one ritual from
    another — ``bash:grep`` from ``bash:sed`` — and everything else in the line is the
    user's data. When the name cannot be established safely the bare tool name is
    returned, so the tap degrades to less detail rather than to leaked content.
    """
    if name not in _COMMAND_TOOLS:
        return name
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return name
    if not isinstance(arguments, dict):
        return name
    for key in _COMMAND_ARG_KEYS:
        raw = arguments.get(key)
        if isinstance(raw, str) and raw.strip():
            verb = _command_verb(raw)
            return f"{name}:{verb}" if verb else name
    return name


def extract_actions(dialect: str, body: Optional[dict],
                    sse_text: Optional[str]) -> Optional[list]:
    """The tool calls this response actually made, in order.

    ``_tool_names`` records the tools a request *offered*, which is what prefix-mutation
    detection needs. This records the ones the model *invoked*, which is what a flow is
    made of. Without it a signature can only be mined from whatever corpus produced the
    skill, never from the harness it is deployed into — and a signature in the wrong
    harness's vocabulary is dead code that looks alive (RFC-002 §6).

    Returns None when the response could not be read at all, distinguished from ``[]``
    meaning a response that genuinely called no tools.
    """
    try:
        if body is not None:
            return (_anthropic_actions_body(body) if dialect == "anthropic"
                    else _openai_actions_body(body))
        if sse_text is None:
            return None
        return (_anthropic_actions_stream(sse_text) if dialect == "anthropic"
                else _openai_actions_stream(sse_text))
    except Exception:
        return None  # fail-open: an unparseable response never costs us the row


def _openai_actions_body(body: dict) -> list:
    out = []
    for choice in body.get("choices") or []:
        message = choice.get("message") or {}
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name"):
                out.append(_refine_action(fn["name"], fn.get("arguments")))
    return out


def _openai_actions_stream(sse_text: str) -> list:
    """Accumulate by tool_calls index: the name arrives once, arguments in fragments.

    Two details matter and neither is hypothetical. A provider that omits ``index``
    entirely would collapse every call into slot 0 and lose all but the last, so a *name*
    arriving at a slot that already has one opens a new slot instead of overwriting.
    And deltas can arrive out of index order, while a flow signature is an ordered suffix
    match — so the result is ordered by index, not by arrival.
    """
    slots: list = []          # [{"index", "name", "args"}], in creation order
    by_index: dict = {}       # index -> the open slot currently accumulating for it
    for data in _sse_datas(sse_text):
        for choice in data.get("choices") or []:
            for call in (choice.get("delta") or {}).get("tool_calls") or []:
                idx = call.get("index", 0)
                fn = call.get("function") or {}
                slot = by_index.get(idx)
                if slot is None or (fn.get("name") and slot["name"]):
                    slot = {"index": idx, "name": None, "args": ""}
                    slots.append(slot)
                    by_index[idx] = slot
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if isinstance(fn.get("arguments"), str):
                    slot["args"] += fn["arguments"]
    named = [s for s in slots if s["name"]]
    named.sort(key=lambda s: s["index"])   # stable: ties keep creation order
    return [_refine_action(s["name"], s["args"]) for s in named]


def _anthropic_actions_body(body: dict) -> list:
    out = []
    for block in body.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name"):
            out.append(_refine_action(block["name"], block.get("input")))
    return out


def _anthropic_actions_stream(sse_text: str) -> list:
    """content_block_start carries the name; input arrives as input_json_delta fragments.

    Each start opens its own slot even when an index repeats, so a reused index cannot
    make two distinct calls render as the last one twice.
    """
    slots: list = []
    by_index: dict = {}
    for data in _sse_datas(sse_text):
        kind = data.get("type")
        if kind == "content_block_start":
            block = data.get("content_block") or {}
            if block.get("type") == "tool_use" and block.get("name"):
                slot = {"name": block["name"], "args": ""}
                slots.append(slot)
                by_index[data.get("index", len(slots) - 1)] = slot
        elif kind == "content_block_delta":
            slot = by_index.get(data.get("index"))
            delta = data.get("delta") or {}
            if slot is not None and isinstance(delta.get("partial_json"), str):
                slot["args"] += delta["partial_json"]
    return [_refine_action(s["name"], s["args"]) for s in slots]


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
        self.segments = PrefixSegmentMonitor()
        self._prev_prompt_tokens: "OrderedDict[str, int]" = OrderedDict()

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
        request_parse_error: Optional[str] = None,
    ) -> None:
        request_json = request_json or {}
        messages = request_json.get("messages") or []
        if session_header is not None:
            session_header = _safe_session(session_header)
        prompt = request_json.get("prompt")
        seed = _canonical(prompt) if prompt is not None else None
        session, ratio = self.prefix.observe(messages, session_header, seed=seed)
        mutation = self.segments.observe(session, request_json,
                                         self._prev_prompt_tokens.get(session))
        usage, model = extract_usage(dialect, response_json, response_sse)
        model = model or request_json.get("model")
        actions = extract_actions(dialect, response_json, response_sse)

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
            # The tool calls this step actually made, in order — the unit a flow
            # signature is built from. None means the response was unreadable; [] means
            # it read fine and called nothing.
            "actions": actions,
            "prefix_stable_ratio": ratio,
            # Cache-critical segment change (tools/system/model) since the previous
            # call in this session, with its marginal re-write cost. None = unchanged.
            "prefix_mutation": mutation,
            # cache_read == 0 with an unmutated prefix is NOT a mutation: it is TTL
            # expiry or a provider-side block-distance miss. Kept separable so the two
            # causes are never conflated in analysis.
            "cache_miss_unexplained": bool(
                mutation is None and cost
                and (cost.get("native_tokens") or {}).get("cached_tokens") == 0
                and cost["observed_flags"].get("cached_tokens")
            ),
            "cost": {**cost, "cache_status": cache_status(cost)} if cost else None,
            "cost_quality": cost_quality(cost) if cost else "unavailable",
            "cost_error": cost_error,
            "request_parse_error": request_parse_error,
            # True when the response was not fully observed (buffer cap, disconnect):
            # the call is still counted, usage may be missing.
            "tap_truncated": truncated,
        }
        if request_sha is not None:
            row["request_sha_before"], row["request_sha_after"] = request_sha
        self._append(self.config.ledger_dir / f"{now.date().isoformat()}.jsonl", row)

        # Remember this call's OBSERVED prompt size so the next mutation in this
        # session can be priced from measurement rather than an estimate.
        observed_prompt = (usage or {}).get("prompt_tokens")
        if observed_prompt:
            self._prev_prompt_tokens[session] = observed_prompt
            self._prev_prompt_tokens.move_to_end(session)
            while len(self._prev_prompt_tokens) > _MAX_SESSIONS:
                self._prev_prompt_tokens.popitem(last=False)

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
