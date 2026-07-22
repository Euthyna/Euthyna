#!/usr/bin/env python3
"""euthyna.trajectory — provider-neutral Trajectory abstraction (B6).

Every harness adapter (SWE-agent .traj, OpenHands event log) maps its native format onto this ONE
internal shape so the calibration harness + verifier operate on a single abstraction.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Step:
    role: str                          # system | user | assistant | tool
    text: str = ""                     # flattened text content
    is_observation: bool = False       # a tool observation (carries OBSERVATION: text)
    raw: Optional[Dict[str, Any]] = None


@dataclass
class Trajectory:
    task_id: str
    steps: List[Step] = field(default_factory=list)
    exit_status: Optional[str] = None
    submitted_patch: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)   # aggregated provider usage
    source: str = "unknown"                                # adapter name

    # -- outcome predicates the engine + verifier consume --
    @property
    def empty_patch(self) -> bool:
        return not bool(self.submitted_patch and self.submitted_patch.strip())

    @property
    def error(self) -> bool:
        return "error" in str(self.exit_status or "").lower()

    def outcome(self) -> Dict[str, Any]:
        return {
            "exit_status": self.exit_status,
            "empty_patch": self.empty_patch,
            "error": self.error,
            "submitted_patch": self.submitted_patch,
            "terminal_patch": self.submitted_patch,
        }

    def shape(self) -> Dict[str, Any]:
        """A comparable structural fingerprint. Two adapters that map the same underlying trajectory
        must produce equal shape() dicts."""
        return {
            "task_id": self.task_id,
            "n_steps": len(self.steps),
            "roles": [s.role for s in self.steps],
            "n_observations": sum(1 for s in self.steps if s.is_observation),
            "exit_status": self.exit_status,
            "empty_patch": self.empty_patch,
        }
