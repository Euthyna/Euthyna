"""Token estimation — deliberately conservative (keeps Stage 2 honest).

The brief: est_tokens_per_occurrence = tokens (or bytes/4). We use bytes/4 as
a documented, model-agnostic proxy. amortizable = per_occ * (occurrences - 1)
because the FIRST occurrence is the one you'd still pay to derive/compile the
skill — only the REPEATS are amortizable. This is stricter than occ*per_occ
(the brief's upper bound) and we report it as the conservative figure, with the
brief's upper bound alongside so nothing is hidden.
"""
from __future__ import annotations

BYTES_PER_TOKEN = 4  # documented proxy; real tokenizer would refine this


def tokens_from_bytes(byte_len):
    if byte_len is None:
        return None
    return round(byte_len / BYTES_PER_TOKEN)


def estimate_flow(per_occ_bytes, total_bytes, n_occurrences):
    """Return (per_occ_tokens, amortizable_tokens_conservative,
               amortizable_tokens_upper). None-safe."""
    if per_occ_bytes is None or total_bytes is None:
        return (None, None, None)
    per_occ_tok = tokens_from_bytes(per_occ_bytes)
    # conservative: only repeats after the first are amortizable
    repeats = max(n_occurrences - 1, 0)
    amort_cons = per_occ_tok * repeats if per_occ_tok is not None else None
    # brief's upper bound: total consumed across all occurrences
    amort_upper = tokens_from_bytes(total_bytes)
    return (per_occ_tok, amort_cons, amort_upper)
