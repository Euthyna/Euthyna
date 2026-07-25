"""Core data model: a corpus -> sessions -> ordered steps.

A Step is the unit the brief defines: an assistant action + the tool
observation that resulted from it. We keep enough to compute all three
signature levels and byte/token estimates, but we DO NOT retain raw content
in any emitted artifact — only hashes, tool names, normalized arg shapes,
and byte counts leave this process.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    # index within its session (0-based)
    idx: int
    # role that produced the action (usually "assistant")
    role: str
    # tool / action name invoked by the assistant this step (None if pure text)
    tool: Optional[str]
    # normalized argument SHAPE for L2 (literals slotted, e.g. read(<path>)).
    # This is a structural string, never raw literal content.
    arg_shape: str
    # sha256 of the *normalized* step content for L0 exact matching.
    content_hash: str
    # byte length of the step content (assistant action + observation), for
    # token estimation. For hash-only corpora this comes from message_bytes.
    byte_len: int
    # whether byte_len is real (measured) or unknown (None -> not estimated)
    byte_len_known: bool = True

    def sig_l0(self) -> str:
        return self.content_hash

    def sig_l1(self) -> str:
        # structural: (role, tool) with args stripped
        return f"{self.role}:{self.tool or '_text_'}"

    def sig_l2(self) -> str:
        # templated: tool + normalized argument shape (literals slotted)
        return f"{self.role}:{self.tool or '_text_'}({self.arg_shape})"


@dataclass
class Session:
    session_id: str
    corpus: str
    steps: list[Step] = field(default_factory=list)
    # provenance: source file this session came from
    source_file: str = ""
    # mode: "content" (we hashed content) or "hash_only" (euthyna-style)
    mode: str = "content"

    def __len__(self) -> int:
        return len(self.steps)
