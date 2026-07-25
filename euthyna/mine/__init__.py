"""euthyna.mine — Stage 0/1 repeated-flow miner + classifier.

Deterministic (no LLM, no network, stdlib only) miner for agent traces. Finds
every *repeated static flow* (contiguous >=3-step subsequence whose signature
recurs >=3x across >=2 sessions) at three signature levels, then classifies the
flows into a data-driven taxonomy with distillation candidates.

This is the perception half of the v0.2 "evidence-gated flow compilation" slot:
it mines and describes candidates ONLY. It generates no skills (Stage 2) and
makes no efficacy/savings claims (Stage 3 A/B + A/A floor only). Amortization
figures are conservative byte-weight UPPER BOUNDS, never predicted savings.

Privacy: only STRUCTURE leaves the miner — signatures, hashes, tool names,
normalized argument SHAPES (literals slotted), counts, and positional refs.
No raw path, command value, or file content is ever emitted. Euthyna live
traces are mined on provided message_sha256 sequences (hash-only; never reversed).
"""
from .miner import mine_level, dedup_maximal, Flow
from .model import Step, Session

__all__ = ["mine_level", "dedup_maximal", "Flow", "Step", "Session"]
