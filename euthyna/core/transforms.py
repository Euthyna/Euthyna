#!/usr/bin/env python3
"""euthyna.transforms — the two P2b context transforms as DETERMINISTIC pure functions.

Ported from p2b_intervention_shim.py (the HTTP-server harness stripped out; the pure transform
logic retained verbatim). These are exercised by the verifier/engine indirectly and are their own
self-tested unit.

  - admission_cap (write-time, APPEND-ONLY): cap each tool observation to CAP tokens/lines at its
    first write; never rewrite an earlier slot. Cached prefix stays valid.
  - masking (retroactive, PREFIX-MUTATING): once total context crosses THRESHOLD, elide the OLDEST
    large observation (>MIN_OBS tokens) to a stub. Mutates a prefix slot => cache miss downstream.

Contracts (self-tested): idempotence, stability, single-mutation-per-crossing.
"""
import copy
from dataclasses import dataclass, field

CHARS_PER_TOKEN = 4
STUB = "[observation elided by retroactive masking]"


@dataclass
class TransformParams:
    cap_tokens: int = 800
    threshold_tokens: int = 24000
    min_obs_tokens: int = 800
    cap_mode: str = "tokens"       # tokens | lines | unlimited
    cap_lines: object = 512        # int, or "unlimited"


def _txt(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                          if isinstance(b, dict) and isinstance(b.get("text"), str))
    return str(content) if content else ""


def _is_obs(i, m):
    if m.get("role") != "tool":
        return False
    c = m.get("content")
    if isinstance(c, list):
        return any(isinstance(b, dict) and isinstance(b.get("text"), str) for b in c)
    return isinstance(c, str) and len(c) > 0


def _tok(text):
    return max(1, len(text) // CHARS_PER_TOKEN)


def _set_text(msg, new_text):
    c = msg.get("content")
    if isinstance(c, list):
        tb = [b for b in c if isinstance(b, dict) and isinstance(b.get("text"), str)]
        if tb:
            tb[0]["text"] = new_text
            for b in tb[1:]:
                b["text"] = ""
            return True
        return False
    msg["content"] = new_text
    return True


def _cap_text(text, cap_tokens):
    limit = cap_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[admission-cap: truncated to {cap_tokens} tokens]", True


def _cap_text_lines(text, cap_lines):
    lines = text.split("\n")
    if len(lines) <= cap_lines:
        return text, False
    kept = lines[:cap_lines]
    return "\n".join(kept) + f"\n[admission-cap: truncated to {cap_lines} lines]", True


def apply_admission_cap(messages, params=None):
    """Write-time cap, APPEND-ONLY, idempotent. cap_mode selects lines (P2a sweep) or tokens (P2b);
    'unlimited' => passthrough."""
    p = params or TransformParams()
    out = [copy.deepcopy(m) for m in messages]
    changed = 0
    unlimited = (str(p.cap_mode).lower() == "unlimited") or (
        str(p.cap_lines).lower() == "unlimited" and p.cap_mode == "lines")
    if unlimited:
        return out, {"transform": "admission_cap", "cap_mode": "unlimited", "obs_capped": 0}
    for i, m in enumerate(out):
        if not _is_obs(i, m):
            continue
        t = _txt(m.get("content"))
        if "[admission-cap:" in t and (t.rstrip().endswith("tokens]") or t.rstrip().endswith("lines]")):
            continue
        if p.cap_mode == "lines":
            cl = 999999 if str(p.cap_lines).lower() == "unlimited" else int(p.cap_lines)
            new_t, did = _cap_text_lines(t, cl)
        else:
            new_t, did = _cap_text(t, p.cap_tokens)
        if did:
            _set_text(m, new_t)
            changed += 1
    return out, {"transform": "admission_cap", "cap_mode": p.cap_mode,
                 "cap": (p.cap_lines if p.cap_mode == "lines" else p.cap_tokens),
                 "obs_capped": changed}


def apply_masking(messages, params=None):
    """Retroactive masking: if total context > THRESHOLD, elide the OLDEST large (>MIN_OBS) non-stub
    observation to a fixed STUB. Deterministic single elision per crossing."""
    p = params or TransformParams()
    out = [copy.deepcopy(m) for m in messages]
    total_tok = sum(_tok(_txt(m.get("content"))) for m in out)
    info = {"transform": "masking", "total_tokens_est": total_tok,
            "threshold": p.threshold_tokens, "elided_index": None}
    if total_tok <= p.threshold_tokens:
        return out, info
    for i, m in enumerate(out):
        if not _is_obs(i, m):
            continue
        t = _txt(m.get("content"))
        if t.strip() == STUB:
            continue
        if _tok(t) >= p.min_obs_tokens:
            _set_text(m, STUB)
            info["elided_index"] = i
            break
    return out, info


def transform(messages, arm, params=None):
    if arm == "admission":
        return apply_admission_cap(messages, params)
    if arm == "masking":
        return apply_masking(messages, params)
    return [copy.deepcopy(m) for m in messages], {"transform": "raw"}
