#!/usr/bin/env python3
"""euthyna.adapters.base — the adapter interface (B6)."""
from abc import ABC, abstractmethod
from ..trajectory import Trajectory


class HarnessAdapter(ABC):
    """Maps a native harness artifact (dict or file) to an internal Trajectory."""
    name = "base"

    @abstractmethod
    def parse(self, artifact, task_id=None) -> Trajectory:
        ...

    def parse_file(self, path, task_id=None) -> Trajectory:
        import json
        with open(path) as f:
            return self.parse(json.load(f), task_id=task_id)
