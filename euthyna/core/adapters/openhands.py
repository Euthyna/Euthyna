#!/usr/bin/env python3
"""euthyna.adapters.openhands — OpenHands event-log adapter (B6).

OpenHands emits a trajectory as a list of EVENT dicts. Documented shape adapted here:
  {"events": [ {"action": "run",       "args": {...}, "content": "...", "source": "agent"},
               {"observation": "run",  "content": "OBSERVATION: ...",   "source": "user"},
               ... ],
   "metadata": {"exit_status": "...", "submission": "<patch>", "usage": {...}}}

Action events -> assistant/user steps; observation events -> tool observation steps. Mapped to the
SAME internal Trajectory shape as the SWE-agent adapter.
"""
from .base import HarnessAdapter
from ..trajectory import Trajectory, Step


class OpenHandsAdapter(HarnessAdapter):
    name = "openhands"

    def parse(self, artifact, task_id=None) -> Trajectory:
        events = artifact.get("events") or []
        meta = artifact.get("metadata") or {}
        steps = []
        for ev in events:
            content = ev.get("content", "") or ""
            src = ev.get("source", "")
            if "observation" in ev:
                # observation event -> a tool observation step
                is_obs = "OBSERVATION:" in content
                steps.append(Step(role="tool", text=content, is_observation=is_obs, raw=ev))
            elif "action" in ev:
                # action event: agent action -> assistant; user/system message actions map by source
                if src in ("user",):
                    role = "user"
                elif src in ("system",):
                    role = "system"
                else:
                    role = "assistant"
                steps.append(Step(role=role, text=content, is_observation=False, raw=ev))
            else:
                # message-only event
                role = "user" if src == "user" else "system" if src == "system" else "assistant"
                steps.append(Step(role=role, text=content, is_observation=False, raw=ev))
        usage = meta.get("usage") or {}
        return Trajectory(
            task_id=task_id or meta.get("task_id") or artifact.get("task_id") or "unknown",
            steps=steps,
            exit_status=meta.get("exit_status"),
            submitted_patch=meta.get("submission") or "",
            usage=usage,
            source=self.name,
        )
