# One instrument, two harnesses, two vocabularies — 2026-07-29

The three skills in this repository were mined from mini-SWE-agent and were measured
**inert** against opencode: their `bash:*` trigger vocabulary and opencode's
`read`/`glob`/`edit`/`bash:python` share nothing
([cost-primary](../cost-primary/NOTES.md), RFC-002 §10.2). That raised a question the
tooling could not answer from opencode traffic alone: is the vocabulary check itself
correct, or does it just report whatever single harness happens to be running?

So the same gateway, the same `actions` tap and the same registry were pointed at
mini-SWE-agent 2.4.6 — the harness the skills came from — with no code change.

## The tap needed no change, and that was not obvious in advance

mini-SWE-agent's own `default.yaml` asks the model for a fenced
` ```mswea_bash_command ` block and parses the command out of the response **text**. A
tap that reads `message.tool_calls` would have recorded `[]` for every call and mined
nothing from a full benchmark run.

It survives because v2.0 moved to tool calls, and its tool is:

```python
BASH_TOOL = {"function": {"name": "bash",
                          "parameters": {"command": {"type": "string"}}}}
```

`bash` is already in the tap's `_COMMAND_TOOLS` and `command` already in its
`_COMMAND_ARG_KEYS`, so the refinement produces `bash:<verb>` — the exact shape the
mined signatures use. The benchmark config we would run (`swebench.yaml`) is tool-call
mode; the legacy text path (`actions_text.py`, "the method used for
mini-swe-agent v1.0") is not. **A repository still on the v1.0 text format would need a
text-mode parser, and this tap does not have one.**

## What one local run recorded

25 actions, all `bash:<verb>`, from a single trajectory:

```
bash:ls  bash:ls  bash:cat  bash:sed  bash:sed  bash:cat  bash:python
bash:python  bash:which  bash:python3 ×3  bash:brew  bash:python3  bash:brew ×2
bash:python3 ×4  bash:export  bash:python3 ×4
```

| | opencode | mini-SWE-agent |
|---|---|---|
| observed vocabulary | `read`, `glob`, `edit`, `bash:python` | `bash:{ls,cat,sed,python,which,python3,brew,export}` |
| dead triggers | **3 of 3** | **2 of 3** |

`swe-patch-probe` becomes **live** here — `bash:sed` occurs, so its signature is
expressible. The other two need `bash:grep` and `bash:echo`, which this trajectory did
not contain. So the check discriminates rather than reporting a constant: same registry,
same code, different answer per harness.

## The trajectory is also a finding, and not the one we wanted

The task was fixed at action 4–5 (`bash:sed`, `bash:sed`). The remaining ~19 actions are
the agent fighting the host Python: `which`, then `python3`, then **`brew`**, then
`python3` eight more times. Four consecutive `bash:python3` at the tail is a genuine
repeated n-gram — exactly the shape flow mining looks for.

**But it is an artifact of running without a container.** SWE-bench instances ship a
pre-built environment, so this particular thrash cannot occur there. This run is a
plumbing test, and its trajectory must not be mined as though it were representative
work. Recording it here so nobody later mistakes it for a SWE-bench observation.

## Two things this blocks on

- **Context window.** The run overran the backend's `--max-model-len 16384` after
  solving. Real repository observations are far longer; SWE-Lego-Qwen3-8B supports
  163,840, so Serving-A has to be relaunched with a much larger window before any
  benchmark run.
- **Containers.** Nothing above needed Docker. A SWE-bench run does.
