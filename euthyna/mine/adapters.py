"""Per-corpus adapters — turn each corpus's native record format into Steps.

The generic loader assumed structured tool_calls. The real public agent-trace
corpora are different per source, verified by inspection:

  * miniswe  : output = "THOUGHT: ...\\n```bash\\n<cmd>\\n```" (mini-swe-agent).
               The ACTION is the bash command -> the real tool call. GOLD for
               flow mining (command sequences are genuine static flows).
  * taubench : natural-language customer-service dialog (tau-bench). No tool
               markers in these traces; output often empty (user turns). We
               extract a coarse (role, has_text) step; flows here are dialog
               shape, not command rituals. Reported honestly, low value.
  * magagent : MetaGPT long-form reasoning text (facts/plan/analysis). No bash;
               step "action" = a normalized section-kind of the reasoning.

Every adapter emits ONLY structure downstream: the command TEMPLATE (literals
slotted by normalize_command), never the raw command text.
"""
from __future__ import annotations
import re
import json
from .model import Step, Session
from .normalize import normalize_command, content_hash

_BASH = re.compile(r"```(?:bash|sh)?\s*(.+?)```", re.S)


def _first_program(cmd: str) -> str:
    """Leading program token of a (possibly compound) command, for L1 naming."""
    cmd = cmd.strip()
    # take first segment before &&/|/; and grab argv[0]
    seg = re.split(r"&&|\|\||\||;", cmd, 1)[0].strip()
    m = re.match(r"([A-Za-z0-9_./-]+)", seg)
    prog = m.group(1) if m else "?"
    return prog.split("/")[-1]  # basename (python3, grep, sed, git, ...)


def _mk_step(idx, role, tool, arg_shape, content_for_hash, byte_len):
    return Step(idx=idx, role=role, tool=tool, arg_shape=arg_shape,
                content_hash=content_hash(content_for_hash), byte_len=byte_len)


# ---------------------------------------------------------------------------
def load_miniswe(path: str, corpus: str = "miniswe") -> list[Session]:
    """One file = one session (filename hash = session id). Each record's
    `output` is a THOUGHT+ACTION; the ACTION (bash) is the step's tool call.
    byte_len counts input(observation)+output(action) = true per-step token cost."""
    import os
    sid = os.path.basename(path).split(".")[0]
    steps = []
    idx = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out = r.get("output", "") or ""
            inp = r.get("input", "") or ""
            m = _BASH.search(out)
            if m:
                cmd = m.group(1).strip()
                tool = _first_program(cmd)
                arg_shape = f"cmd={normalize_command(cmd)}"
            else:
                # no action block (final answer / thought-only)
                tool = "_noaction_"
                arg_shape = ""
            byte_len = len(inp.encode("utf-8", "replace")) + \
                       len(out.encode("utf-8", "replace"))
            # L0 hash over the NORMALIZED action (template), so L0 = byte-identical
            # templated step; keeps hashing content-free (no raw literals).
            steps.append(_mk_step(idx, "assistant", tool, arg_shape,
                                  f"{tool}|{arg_shape}", byte_len))
            idx += 1
    return [Session(sid, corpus, steps, source_file=path, mode="content")]


# ---------------------------------------------------------------------------
def load_taubench(path: str, corpus: str = "taubench") -> list[Session]:
    """tau-bench dialog. No tool markers here; represent each record as a step
    keyed by (who, has_text). Flows = dialog shape. Honest low-value corpus."""
    import os
    sid = os.path.basename(path).split(".")[0]
    steps = []
    idx = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out = r.get("output", "") or ""
            inp = r.get("input", "") or ""
            has = "text" if out.strip() else "empty"
            tool = f"turn_{has}"
            byte_len = len(inp.encode()) + len(out.encode())
            steps.append(_mk_step(idx, "assistant", tool, "", f"{tool}", byte_len))
            idx += 1
    return [Session(sid, corpus, steps, source_file=path, mode="content")]


# ---------------------------------------------------------------------------
_SECTION = re.compile(r"^\s*\d+\.\s+([A-Z][A-Z /]+)", re.M)
_TOOLCALL = re.compile(r"<tool_call>\s*(\{.*?\})", re.S)
_CODE = re.compile(r"```(\w+)?")


def _magagent_action(out: str):
    """Classify a magagent (MagenticOne-style) output into (tool, arg_shape).
    Verified shapes: orchestrator ledger JSON (is_request_satisfied/next_speaker
    /is_in_loop...), python code blocks, <tool_call>{name:...} objects, numbered
    reasoning sections, or free text. Only STRUCTURE is emitted."""
    o = out.strip()
    # 1) JSON object action (ledger or other) -> key-shape is the action id
    if o.startswith("{"):
        try:
            d = json.loads(o)
            if isinstance(d, dict):
                keys = tuple(sorted(d.keys()))
                if "next_speaker" in d or "is_request_satisfied" in d:
                    # orchestrator ledger; the routed speaker is the useful slot
                    nxt = d.get("next_speaker")
                    if isinstance(nxt, dict):
                        # value nested as {answer:..,reason:..}; keep only presence
                        return "ledger", "next_speaker=<slot>"
                    return "ledger", ""
                return "json_action", f"keys={'|'.join(keys[:6])}"
        except Exception:
            pass
    # 2) <tool_call>{"name": ...}
    m = _TOOLCALL.search(o)
    if m:
        try:
            d = json.loads(m.group(1))
            return f"tool:{d.get('name','?')}", ""
        except Exception:
            return "tool:?", ""
    # 3) fenced code block
    mc = _CODE.search(o)
    if mc:
        lang = (mc.group(1) or "code").lower()
        return f"code:{lang}", ""
    # 4) numbered reasoning sections
    secs = tuple(s.strip() for s in _SECTION.findall(o)[:6])
    if secs:
        return "reason", "secs=" + "/".join(secs)
    # 5) empty / freeform
    if not o:
        return "_empty_", ""
    return "text", ""


def load_magagent(path: str, corpus: str = "magagent") -> list[Session]:
    """MagenticOne-style orchestration traces. Step action = classified output
    kind (ledger / json_action / tool:<name> / code:<lang> / reason / text).
    No raw content emitted — only the action-kind and coarse key/slot shape."""
    import os
    sid = os.path.basename(path).split(".")[0]
    steps = []
    idx = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out = r.get("output", "") or ""
            inp = r.get("input", "") or ""
            tool, arg_shape = _magagent_action(out)
            byte_len = len(inp.encode()) + len(out.encode())
            steps.append(_mk_step(idx, "assistant", tool, arg_shape,
                                  f"{tool}|{arg_shape}", byte_len))
            idx += 1
    return [Session(sid, corpus, steps, source_file=path, mode="content")]


ADAPTERS = {
    "miniswe": load_miniswe,
    "taubench": load_taubench,
    "magagent": load_magagent,
}
