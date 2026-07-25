"""Corpus loaders — schema-tolerant, self-describing.

We cannot see the real corpora from here, so loaders are defensive:
  * they accept the documented shape {timestamp, input, output, session_id}
  * they also handle OpenAI-chat records (messages[], tool_calls[]) and
    OpenHands event logs (action/observation events)
  * unknown shapes degrade gracefully and are COUNTED, never silently dropped

Each loader turns a JSONL file into one or more Session objects with ordered
Steps. A Step = assistant action + following tool observation.

`inspect_file` dumps structure (keys, sample shapes) WITHOUT emitting any raw
literal values beyond short key names — used to validate extraction against
source-of-truth before trusting mining output.
"""
from __future__ import annotations
import json
import os
import glob
from typing import Iterator
from .model import Step, Session
from .normalize import normalize_args, content_hash, canonical_json


# ---------------------------------------------------------------------------
def _read_jsonl(path: str) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"__parse_error__": True}


def _sid_from_path(path: str) -> str:
    b = os.path.basename(path)
    for suf in (".openai_chat.jsonl", ".jsonl", ".json"):
        if b.endswith(suf):
            return b[: -len(suf)]
    return b


# ---------------------------------------------------------------------------
# content-bearing extraction helpers
# ---------------------------------------------------------------------------
def _extract_tool_and_args(msg: dict):
    """Best-effort (tool_name, args) from a single assistant message dict."""
    # OpenAI-style tool_calls
    tcs = msg.get("tool_calls")
    if isinstance(tcs, list) and tcs:
        fn = tcs[0].get("function", {}) if isinstance(tcs[0], dict) else {}
        name = fn.get("name") or tcs[0].get("name")
        raw = fn.get("arguments", tcs[0].get("arguments"))
        args = raw
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except Exception:
                args = raw
        return name, args
    # single function_call
    fc = msg.get("function_call")
    if isinstance(fc, dict):
        raw = fc.get("arguments")
        args = raw
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except Exception:
                args = raw
        return fc.get("name"), args
    # OpenHands-style action
    if "action" in msg:
        act = msg.get("action")
        args = msg.get("args", msg.get("arguments"))
        return (act if isinstance(act, str) else None), args
    return None, None


def _step_content_str(role, tool, args, obs) -> str:
    """Serialize the full step content (for L0 hashing + byte counting).
    Includes the observation so byte_len reflects true token cost."""
    return canonical_json({
        "role": role, "tool": tool,
        "args": args if not isinstance(args, str) else args,
        "obs": obs,
    })


# ---------------------------------------------------------------------------
# Generic content loader: covers miniswe / taubench / magagent / openhands
# ---------------------------------------------------------------------------
def load_content_jsonl(path: str, corpus: str) -> list[Session]:
    """Load a JSONL where each line is a turn/record. Group by session_id if
    present, else the whole file is one session. Pairs assistant actions with
    the next observation to form Steps."""
    records = list(_read_jsonl(path))
    # group into sessions
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    file_sid = _sid_from_path(path)
    for r in records:
        sid = str(r.get("session_id") or file_sid)
        if sid not in groups:
            groups[sid] = []
            order.append(sid)
        groups[sid].append(r)

    sessions = []
    for sid in order:
        recs = groups[sid]
        steps: list[Step] = []
        idx = 0
        for r in recs:
            if r.get("__parse_error__"):
                continue
            # Documented shape: {timestamp, input, output, session_id}
            # 'output' is the assistant turn; 'input' often the observation
            # feeding the NEXT action. We treat each record's output as the
            # assistant action and its own input as the observation context.
            assistant = r.get("output", r.get("assistant", r.get("message")))
            observation = r.get("input", r.get("observation"))
            role = "assistant"
            tool, args = (None, None)
            if isinstance(assistant, dict):
                role = assistant.get("role", "assistant")
                tool, args = _extract_tool_and_args(assistant)
                if args is None:
                    args = assistant.get("content")
            elif isinstance(assistant, str):
                args = assistant
            obs_str = observation if isinstance(observation, str) else \
                (canonical_json(observation) if observation is not None else "")
            content = _step_content_str(role, tool, args, obs_str)
            steps.append(Step(
                idx=idx, role=role, tool=tool,
                arg_shape=normalize_args(tool, args),
                content_hash=content_hash(content),
                byte_len=len(content.encode("utf-8", "replace")),
            ))
            idx += 1
        sessions.append(Session(sid, corpus, steps, source_file=path, mode="content"))
    return sessions


# ---------------------------------------------------------------------------
# Hash-only loader: Euthyna traces (metadata only, NEVER content)
# ---------------------------------------------------------------------------
def load_hash_only_jsonl(path: str, corpus: str = "euthyna") -> list[Session]:
    """Euthyna trace: {ts, roles[], message_sha256[], message_bytes[], ...}.
    We mine on the provided sha256 sequence. No content exists here; we do NOT
    reconstruct any. L1/L2 are UNAVAILABLE (no tool/arg info) -> only L0 (the
    provided hash) is meaningful; L1/L2 fall back to the hash so higher levels
    simply won't over-merge. byte_len from message_bytes if present."""
    sessions = []
    for r in _read_jsonl(path):
        if r.get("__parse_error__"):
            continue
        sid = str(r.get("session_id") or r.get("trace_id") or _sid_from_path(path))
        hashes = r.get("message_sha256") or []
        roles = r.get("roles") or []
        byts = r.get("message_bytes") or []
        steps = []
        for i, h in enumerate(hashes):
            role = roles[i] if i < len(roles) else "?"
            bl = byts[i] if i < len(byts) else None
            steps.append(Step(
                idx=i, role=str(role), tool=None,
                arg_shape="",                     # unknown — hash-only
                content_hash=str(h),
                byte_len=int(bl) if isinstance(bl, (int, float)) else 0,
                byte_len_known=isinstance(bl, (int, float)),
            ))
        sessions.append(Session(sid, corpus, steps, source_file=path, mode="hash_only"))
    return sessions


# ---------------------------------------------------------------------------
# Discovery + inspection
# ---------------------------------------------------------------------------
def discover(corpus_globs: dict[str, str]) -> dict[str, list[str]]:
    """corpus_name -> list of files matching its glob."""
    found = {}
    for name, pat in corpus_globs.items():
        found[name] = sorted(glob.glob(os.path.expanduser(pat)))
    return found


def inspect_file(path: str, n: int = 3) -> dict:
    """Return a structural summary of a JSONL file WITHOUT leaking literals:
    top-level keys, value types, and (for the first n records) the shape."""
    recs = []
    keyset = {}
    total = 0
    for r in _read_jsonl(path):
        total += 1
        if r.get("__parse_error__"):
            continue
        for k, v in r.items():
            keyset.setdefault(k, type(v).__name__)
        if len(recs) < n:
            shape = {k: (type(v).__name__ +
                         (f"[{len(v)}]" if isinstance(v, (list, dict)) else ""))
                     for k, v in r.items()}
            recs.append(shape)
    return {"path": path, "records": total, "top_level_keys": keyset,
            "sample_shapes": recs}
