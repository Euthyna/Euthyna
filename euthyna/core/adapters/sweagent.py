#!/usr/bin/env python3
"""euthyna.adapters.sweagent — SWE-agent .traj adapter (B6).

Native format: a dict with 'history' (list of {role, content}) where role in
system/user/assistant/tool and tool observations carry OBSERVATION: text; and 'info' carrying
submission + exit_status.
"""
from .base import HarnessAdapter
from ..trajectory import Trajectory, Step


def _flatten(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                          if isinstance(b, dict) and isinstance(b.get("text"), str))
    return str(content) if content else ""


class SweAgentAdapter(HarnessAdapter):
    name = "swe-agent"

    def parse(self, artifact, task_id=None) -> Trajectory:
        hist = artifact.get("history") or []
        info = artifact.get("info") or {}
        steps = []
        for m in hist:
            role = m.get("role", "unknown")
            text = _flatten(m.get("content"))
            is_obs = (role == "tool" and "OBSERVATION:" in text)
            steps.append(Step(role=role, text=text, is_observation=is_obs, raw=m))
        stats = info.get("model_stats") or {}
        usage = {
            "prompt_tokens": stats.get("tokens_sent"),
            "completion_tokens": stats.get("tokens_received"),
            "api_calls": stats.get("api_calls"),
            "instance_cost": stats.get("instance_cost"),
        }
        return Trajectory(
            task_id=task_id or artifact.get("task_id") or "unknown",
            steps=steps,
            exit_status=info.get("exit_status"),
            submitted_patch=info.get("submission") or "",
            usage=usage,
            source=self.name,
        )
