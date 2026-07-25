"""Mock-backed tests for euthyna.mine (Stage 0/1 flow miner + classifier).

No live services, no real corpora — synthetic fixtures with planted repeats so
the known answers are checkable. Also pins the privacy contract: literals must
be slotted out of every emitted signature.
"""
import json
import os
import tempfile

from euthyna.mine.model import Step, Session
from euthyna.mine.normalize import normalize_command, normalize_args, content_hash
from euthyna.mine.miner import mine_level
from euthyna.mine.estimate import estimate_flow
from euthyna.mine.adapters import load_miniswe, load_magagent


def _mk(idx, tool, args, obs="ok"):
    from euthyna.mine.loaders import _step_content_str
    c = _step_content_str("assistant", tool, args, obs)
    return Step(idx=idx, role="assistant", tool=tool,
                arg_shape=normalize_args(tool, args),
                content_hash=content_hash(c), byte_len=len(c.encode()))


def _ritual(paths):
    return [_mk(0, "read", {"path": paths[0]}),
            _mk(1, "edit", {"path": paths[0], "content": "x" * 200}),
            _mk(2, "bash", f"python3 {paths[1]}")]


def _sessions(triples, corpus="synth"):
    out = []
    for i, ps in enumerate(triples):
        steps = [_mk(0, "ls", {"path": "."})] + _ritual(ps)
        for j, s in enumerate(steps):
            s.idx = j
        out.append(Session(f"s{i}", corpus, steps))
    return out


def test_l1_finds_repeated_ritual():
    ss = _sessions([("a/b.py", "a/b.py"), ("c/d.py", "c/d.py"), ("e/f.py", "e/f.py")])
    l1 = mine_level(ss, "L1", 3, 6, 3, 2)
    assert any(f.length_steps == 3 and f.n_occurrences >= 3 for f in l1)


def test_l2_templating_merges_path_varying_ritual():
    ss = _sessions([("a/b.py", "a/b.py"), ("c/d.py", "c/d.py"), ("e/f.py", "e/f.py")])
    l2 = mine_level(ss, "L2", 3, 6, 3, 2)
    assert any(f.length_steps == 3 and f.n_occurrences >= 3 for f in l2)


def test_l0_exact_does_not_merge_varying_content():
    ss = _sessions([("a/b.py", "a/b.py"), ("c/d.py", "c/d.py"), ("e/f.py", "e/f.py")])
    l0 = mine_level(ss, "L0", 3, 6, 3, 2)
    assert not any(f.length_steps == 3 and f.n_occurrences >= 3 for f in l0)


def test_honest_null_no_repeat_returns_empty():
    uniq = [Session("u0", "s2", [_mk(0, "read", {"path": "z1"}),
            _mk(1, "edit", {"path": "z2"}), _mk(2, "bash", "echo 1")]),
            Session("u1", "s2", [_mk(0, "grep", {"q": "abc"}),
            _mk(1, "write", {"path": "z9"}), _mk(2, "bash", "echo 2")])]
    assert mine_level(uniq, "L1", 3, 6, 3, 2) == []


def test_hash_only_mode_mines_provided_sha256():
    ho = []
    for i in range(3):
        steps = [Step(idx=j, role="assistant", tool=None, arg_shape="",
                      content_hash=h, byte_len=100)
                 for j, h in enumerate(["H1", "H2", "H3", f"u{i}"])]
        ho.append(Session(f"h{i}", "euthyna", steps, mode="hash_only"))
    hf = mine_level(ho, "L0", 3, 4, 3, 2)
    assert any(f.n_occurrences >= 3 for f in hf)


def test_conservative_amortization_math():
    per_occ, cons, upper = estimate_flow(400, 2000, 5)
    assert per_occ == 100 and cons == 400 and upper == 500


def test_none_bytes_never_silently_zero():
    assert estimate_flow(None, None, 5) == (None, None, None)


def test_command_templating_slots_literals():
    a = normalize_command("python3 /home/u/repro.py --v")
    b = normalize_command("python3 /tmp/other.py --v")
    assert a == b and "python3" in a and "--v" in a


def test_homogeneous_run_suppressed_by_min_distinct():
    homo = [Session(f"g{i}", "s4", [_mk(j, "run", "cmd") for j in range(6)])
            for i in range(3)]
    assert mine_level(homo, "L1", 3, 4, 3, 2, min_distinct=2) == []
    assert mine_level(homo, "L1", 3, 4, 3, 2, min_distinct=1)


def test_nonoverlap_count_not_inflated_by_overlaps():
    homo = [Session(f"g{i}", "s5", [_mk(j, "run", "cmd") for j in range(5)])
            for i in range(3)]
    # allow homogeneous for this count check
    fl = mine_level(homo, "L1", 3, 3, 3, 2, min_distinct=1)
    assert fl and fl[0].n_occurrences > fl[0].n_occurrences_nonoverlap


def test_miniswe_adapter_extracts_bash_and_slots_paths():
    recs = [{"timestamp": 1, "session_id": "m", "input": "obs",
             "output": "THOUGHT: go.\n```bash\ngrep -rn foo /a/b.py\n```"},
            {"timestamp": 2, "session_id": "m", "input": "obs",
             "output": "THOUGHT: e.\n```bash\nsed -i s/x/y/ /a/b.py\n```"},
            {"timestamp": 3, "session_id": "m", "input": "obs",
             "output": "final answer, no action"}]
    td = tempfile.mkdtemp()
    fp = os.path.join(td, "deadbeef.jsonl")
    with open(fp, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    s = load_miniswe(fp)[0]
    assert len(s.steps) == 3
    assert s.steps[0].tool == "grep" and s.steps[1].tool == "sed"
    assert s.steps[2].tool == "_noaction_"
    # privacy: raw path must NOT appear; slot must
    assert "/a/b.py" not in s.steps[0].arg_shape and "<path>" in s.steps[0].arg_shape


def test_magagent_adapter_classifies_ledger_code_tool():
    recs = [{"timestamp": 1, "session_id": "x", "input": "i",
             "output": json.dumps({"is_request_satisfied": {"answer": False},
                                   "next_speaker": {"answer": "WebSurfer"},
                                   "is_in_loop": {}, "is_progress_being_made": {},
                                   "instruction_or_question": {}})},
            {"timestamp": 2, "session_id": "x", "input": "i",
             "output": "```python\nimport math\n```"},
            {"timestamp": 3, "session_id": "x", "input": "i",
             "output": '<tool_call>\n{"name": "web_search"}'}]
    td = tempfile.mkdtemp()
    fp = os.path.join(td, "z.openai_chat.jsonl")
    with open(fp, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    s = load_magagent(fp)[0]
    assert s.steps[0].tool == "ledger"
    assert s.steps[1].tool == "code:python"
    assert s.steps[2].tool == "tool:web_search"


def test_no_literal_leakage_in_emitted_signatures():
    ss = _sessions([("secret/path.py", "secret/path.py")] * 3)
    for lv in ("L0", "L1", "L2"):
        for f in mine_level(ss, lv, 3, 6, 3, 2):
            assert "secret/path.py" not in f.readable_sig
