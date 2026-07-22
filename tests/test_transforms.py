import json, copy
from euthyna.core import transforms as T


def _ser(m): return json.dumps(m, sort_keys=True, ensure_ascii=False)


def _obs(text):
    return {"role": "tool", "content": [{"type": "text", "text": text}]}


def test_admission_cap_idempotent_and_appendonly():
    h = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
         _obs("OBSERVATION:\n" + "x" * 100000)]
    out1, meta = T.apply_admission_cap(h)
    out2, _ = T.apply_admission_cap(out1)
    assert _ser(out1) == _ser(out2)          # idempotent
    assert meta["obs_capped"] == 1
    # non-obs slots unchanged (append-only)
    assert _ser(h[0]) == _ser(out1[0]) and _ser(h[1]) == _ser(out1[1])


def test_admission_cap_stable():
    h = [_obs("OBSERVATION:\n" + "y" * 50000)]
    a, _ = T.apply_admission_cap(h)
    b, _ = T.apply_admission_cap(h)
    assert _ser(a) == _ser(b)


def test_masking_single_mutation_per_crossing():
    big = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    big += [_obs("OBSERVATION:\n[%d] " % i + "x" * 40000) for i in range(3)]
    out, meta = T.apply_masking(big)
    diffs = sum(1 for a, b in zip(big, out) if _ser(a) != _ser(b))
    assert diffs == 1                          # exactly one slot elided
    ei = meta["elided_index"]
    assert T._txt(out[ei]["content"]).strip() == T.STUB


def test_masking_noop_under_threshold():
    small = [_obs("OBSERVATION:\nshort")]
    out, meta = T.apply_masking(small)
    assert meta["elided_index"] is None
    assert _ser(out) == _ser([copy.deepcopy(m) for m in small])


def test_raw_passthrough():
    h = [_obs("OBSERVATION:\n" + "z" * 100000)]
    out, meta = T.transform(h, "raw")
    assert meta["transform"] == "raw"
    assert _ser(out) == _ser([copy.deepcopy(m) for m in h])


def test_line_cap_sweep_monotone():
    big = _obs("OBSERVATION:\n" + "\n".join(f"line {i}" for i in range(10000)))
    sizes = {}
    for cap in (512, 2048, 8192, "unlimited"):
        p = T.TransformParams(cap_mode="unlimited" if cap == "unlimited" else "lines",
                              cap_lines=cap)
        out, _ = T.apply_admission_cap([big], p)
        sizes[cap] = len(T._txt(out[0]["content"]))
    assert sizes[512] < sizes[2048] < sizes[8192] < sizes["unlimited"]
