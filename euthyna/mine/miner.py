"""The deterministic flow miner.

Definitions (from the brief, used exactly):
  * Flow            = contiguous subsequence of steps, length >= 3.
  * Repeated static = signature occurs >= 3 times across >= 2 distinct sessions.
  * Signature ladder: L0 exact (content hash), L1 structural (role,tool),
                      L2 template (tool, normalized arg shape).

We enumerate ALL contiguous windows of length in [min_len, max_len] per
session, key each window by its per-level signature tuple, and aggregate
occurrences with session provenance and byte totals. Then filter by the
repeated-static thresholds. Deterministic: identical input -> identical output.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
from typing import Literal
from .model import Session, Step

Level = Literal["L0", "L1", "L2"]


def _step_sig(step: Step, level: Level) -> str:
    if level == "L0":
        return step.sig_l0()
    if level == "L1":
        return step.sig_l1()
    return step.sig_l2()


def _window_sig(steps: list[Step], level: Level) -> str:
    """Deterministic signature of a window at a given level."""
    joined = "|".join(_step_sig(s, level) for s in steps)
    # hash to keep keys compact and comparable across levels
    return hashlib.sha256(f"{level}::{joined}".encode()).hexdigest()[:16]


@dataclass
class FlowOccurrence:
    corpus: str
    session_id: str
    start_idx: int
    end_idx: int          # inclusive
    byte_len: int
    byte_len_known: bool


@dataclass
class Flow:
    flow_id: str
    level: Level
    length_steps: int
    # human-readable structural signature (the shape, NOT literals)
    readable_sig: str
    sig_key: str
    occurrences: list[FlowOccurrence] = field(default_factory=list)

    @property
    def n_occurrences(self) -> int:
        return len(self.occurrences)

    @property
    def n_occurrences_nonoverlap(self) -> int:
        """Greedy non-overlapping occurrence count, per session. Overlapping
        windows of a self-similar pattern within one session are NOT each a
        distinct 'use' of the flow — counting them all inflates amortization.
        This is the CONSERVATIVE count used for savings estimates."""
        by_sess: dict = {}
        for o in self.occurrences:
            by_sess.setdefault((o.corpus, o.session_id), []).append(o)
        total = 0
        for occs in by_sess.values():
            occs = sorted(occs, key=lambda o: o.start_idx)
            last_end = -1
            for o in occs:
                if o.start_idx > last_end:
                    total += 1
                    last_end = o.end_idx
        return total

    @property
    def sessions(self) -> set:
        return {(o.corpus, o.session_id) for o in self.occurrences}

    @property
    def n_sessions(self) -> int:
        return len(self.sessions)

    @property
    def corpora(self) -> list[str]:
        return sorted({o.corpus for o in self.occurrences})

    def byte_stats(self):
        """Return (per_occ_median_bytes, total_bytes_nonoverlap).
        Total uses the NON-OVERLAPPING occurrences so amortization is not
        inflated by self-similar overlapping windows."""
        # pick the non-overlapping representative occurrences
        by_sess: dict = {}
        for o in self.occurrences:
            by_sess.setdefault((o.corpus, o.session_id), []).append(o)
        chosen = []
        for occs in by_sess.values():
            occs = sorted(occs, key=lambda o: o.start_idx)
            last_end = -1
            for o in occs:
                if o.start_idx > last_end:
                    chosen.append(o)
                    last_end = o.end_idx
        known = [o.byte_len for o in chosen if o.byte_len_known]
        if not known:
            return (None, None)
        s = sorted(known)
        med = s[len(s) // 2]
        return (med, sum(known))


def _readable_window_sig(steps: list[Step], level: Level) -> str:
    if level == "L0":
        return " → ".join(f"{s.role}:{s.tool or 'text'}#{s.content_hash[:6]}" for s in steps)
    if level == "L1":
        return " → ".join(s.sig_l1() for s in steps)
    return " → ".join(s.sig_l2() for s in steps)


def mine_level(sessions: list[Session], level: Level,
               min_len: int = 3, max_len: int = 8,
               min_occ: int = 3, min_sessions: int = 2,
               min_distinct: int = 2) -> list[Flow]:
    """Mine repeated flows at one signature level.

    min_distinct: a candidate flow must contain at least this many DISTINCT
    per-step signatures. A run of one repeated step (AAAA...) is a loop, not a
    distillable ritual, and spawns spurious overlapping "flows"; requiring >=2
    distinct steps removes that degenerate class (conservative, honest)."""
    # sig_key -> Flow (accumulating occurrences)
    flows: dict[str, Flow] = {}
    for sess in sessions:
        n = len(sess.steps)
        for L in range(min_len, max_len + 1):
            if L > n:
                break
            for start in range(0, n - L + 1):
                window = sess.steps[start:start + L]
                # skip degenerate homogeneous windows early
                if min_distinct > 1:
                    distinct = len({_step_sig(s, level) for s in window})
                    if distinct < min_distinct:
                        continue
                key = _window_sig(window, level)
                # composite key includes length to keep windows of different
                # length distinct even if hashes collide across L
                ck = f"{level}:{L}:{key}"
                if ck not in flows:
                    flows[ck] = Flow(flow_id="", level=level, length_steps=L,
                                     readable_sig=_readable_window_sig(window, level),
                                     sig_key=ck)
                bl = sum(s.byte_len for s in window)
                blk = all(s.byte_len_known for s in window)
                flows[ck].occurrences.append(FlowOccurrence(
                    corpus=sess.corpus, session_id=sess.session_id,
                    start_idx=start, end_idx=start + L - 1,
                    byte_len=bl, byte_len_known=blk))
    # filter to repeated-static definition (use NON-OVERLAPPING occurrence
    # count so a single self-similar session can't fake a "repeat")
    kept = [f for f in flows.values()
            if f.n_occurrences_nonoverlap >= min_occ and f.n_sessions >= min_sessions]
    # deterministic ordering: by (amortizable bytes desc, length desc, sig)
    def sortkey(f: Flow):
        _, tot = f.byte_stats()
        return (-(tot or 0), -f.length_steps, f.sig_key)
    kept.sort(key=sortkey)
    return kept


def dedup_maximal(flows: list[Flow]) -> list[Flow]:
    """Optional: drop a flow if it is a strict sub-window of a longer flow with
    the SAME occurrence count (i.e. the longer one fully explains it). Reduces
    n-gram explosion; keeps the maximal repeated flows. Conservative: only drops
    when occurrence counts match exactly and every occurrence is contained."""
    by_len = sorted(flows, key=lambda f: -f.length_steps)
    kept = []
    for f in by_len:
        contained = False
        for lf in kept:
            if lf.length_steps <= f.length_steps:
                continue
            if lf.n_occurrences != f.n_occurrences:
                continue
            # every occ of f must sit inside some occ of lf, same session
            ok = True
            lf_spans = {(o.corpus, o.session_id): [] for o in lf.occurrences}
            for o in lf.occurrences:
                lf_spans[(o.corpus, o.session_id)].append((o.start_idx, o.end_idx))
            for o in f.occurrences:
                spans = lf_spans.get((o.corpus, o.session_id), [])
                if not any(s <= o.start_idx and o.end_idx <= e for s, e in spans):
                    ok = False
                    break
            if ok:
                contained = True
                break
        if not contained:
            kept.append(f)
    return kept
