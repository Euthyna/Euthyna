"""Normalization + argument-shape templating (the L2 machinery).

Turns raw tool arguments into a *shape* string with literals replaced by
typed slots. Crucially, the OUTPUT is structural only: no raw path, command,
or file content survives here. This is what enforces the "code-only leaves
the firm" boundary at the data level — candidates.jsonl carries shapes, not
literals.
"""
from __future__ import annotations
import hashlib
import re
import json
from typing import Any

# ---- literal -> slot rules (ordered; first match wins per token) -----------
# Each rule: (compiled regex, slot token). Applied to string literal VALUES.
_PATHish = re.compile(r"^[~./]?[\w./-]+\.\w{1,6}$")          # foo/bar/baz.py
_DIRish = re.compile(r"^[~./]?[\w./-]+/?$")                   # a/b/c or ./x
_URLish = re.compile(r"^[a-z]+://", re.I)
_NUMish = re.compile(r"^-?\d+(\.\d+)?$")
_HEXish = re.compile(r"^[0-9a-f]{7,}$", re.I)


def _slot_for_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "<bool>"
    if isinstance(v, (int, float)):
        return "<num>"
    if v is None:
        return "<null>"
    s = str(v)
    if _URLish.match(s):
        return "<url>"
    if _HEXish.match(s) and len(s) >= 12:
        return "<hash>"
    if _NUMish.match(s):
        return "<num>"
    if _PATHish.match(s):
        return "<path>"
    if "/" in s and _DIRish.match(s):
        return "<path>"
    if "\n" in s or len(s) > 80:
        return "<content>"       # long/multiline blob (file body, diff, etc.)
    if len(s) == 0:
        return "<empty>"
    return "<str>"


def normalize_command(cmd: str) -> str:
    """Normalize a shell command into a structural template.

    Keeps the *program* and recognizable subcommands/flags (structure), slots
    out file operands and quoted blobs. e.g.:
      'python3 /home/u/repro.py --v'      -> 'python3 <path> --v'
      'git commit -m "fix the bug"'       -> 'git commit -m <str>'
      'cat foo/bar.py | grep xyz'         -> 'cat <path> | grep <str>'
    """
    if not cmd:
        return "<empty>"
    # collapse whitespace but keep pipe/redirect structure
    toks = re.split(r"(\s+|\||&&|\|\||;|>|>>|<)", cmd.strip())
    out = []
    for t in toks:
        if t is None:
            continue
        ts = t.strip()
        if ts == "":
            # preserve a single space between kept structural tokens
            if out and out[-1] != " ":
                out.append(" ")
            continue
        if ts in ("|", "&&", "||", ";", ">", ">>", "<"):
            out.append(ts)
            continue
        # flags kept verbatim (structural); values slotted
        if ts.startswith("-"):
            out.append(ts.split("=")[0])   # --flag=val -> --flag
            continue
        # first bare token of a segment = program/subcommand -> keep if wordy
        if re.fullmatch(r"[A-Za-z0-9_.-]+", ts) and not _PATHish.match(ts) \
           and "/" not in ts and "." not in ts.strip("."):
            out.append(ts)
            continue
        out.append(_slot_for_scalar(ts))
    # collapse runs of identical slots and spaces
    joined = "".join(out)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined


def normalize_args(tool: str, args: Any) -> str:
    """Produce the normalized argument SHAPE for a tool call.

    args may be a dict (structured tool call), a string (raw command / text),
    or None. Returns a compact deterministic shape string.
    """
    if args is None:
        return ""
    # shell-style tools: template the command itself
    if isinstance(args, str):
        if tool in {"bash", "shell", "run", "execute_bash", "cmd"}:
            return f"cmd={normalize_command(args)}"
        return _slot_for_scalar(args)
    if isinstance(args, dict):
        parts = []
        for k in sorted(args.keys()):
            v = args[k]
            if k in {"command", "cmd", "script"} and isinstance(v, str):
                parts.append(f"{k}={normalize_command(v)}")
            elif isinstance(v, (dict, list)):
                parts.append(f"{k}=<{type(v).__name__}>")
            else:
                parts.append(f"{k}={_slot_for_scalar(v)}")
        return ",".join(parts)
    if isinstance(args, list):
        return f"[{len(args)} items]"
    return _slot_for_scalar(args)


def content_hash(*parts: str) -> str:
    """sha256 over normalized content parts (for L0 exact matching)."""
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
