---
name: swe-test-runner
harness: openhands-0.53/CodeActAgent
source: >
  28 arm64-available SWE-bench Verified instances, OpenHands 0.53 CodeActAgent,
  SWE-Lego-Qwen3-8B-MLX-4bit, 2026-07-31 (run oh28b). Mined from the 14 instances
  whose repository does not use pytest, in all of which the correct runner was never
  invoked. NOT mined from the resolved traces: two of those resolved without it.
signature: []
trigger: task-start
steps_replaced: null
measured_in: null
vocabulary: [execute_bash]
notes: >
  steps_replaced is null on purpose. The skill it replaces claimed 6, inherited from the
  corpus it was mined in, and replaced zero in the workload it was deployed into. This one
  carries no number until an A/B measures it in the harness it ships to.
---

# How this repository runs its tests

The task instructions say to run the test suite. They do not say how, and the answer is not
the same across repositories. Assuming `pytest` is wrong for three of the nine projects in
SWE-bench Verified, and wrong in a way that produces no error the agent can learn from — the
command simply collects nothing, or fails for a reason unrelated to the change under test.

Use the invocation for this repository:

| repository | command |
|---|---|
| astropy, flask, requests, pylint, pytest, scikit-learn | `pytest -rA` |
| django | `./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1` |
| sphinx | `tox --current-env -epy39 -v --` |
| sympy | `PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose` |

Run it from the repository root.

## What this deliberately does not tell you

Which tests to run, which file to change, or where the defect is. Those are decisions, and a
supplied decision can be wrong in a way a supplied fact cannot. This is the boundary that
makes the skill safe to apply to a task it cannot help: on a repository where `pytest` is
already correct, it states what the agent was going to do anyway.

## Why this exists

Measured on 28 arm64-available SWE-bench Verified instances under OpenHands 0.53 with
SWE-Lego-Qwen3-8B-MLX-4bit: of the 14 instances whose repository does NOT use pytest,
**14 of 14 never invoked the correct runner**, and none resolved. Every resolved instance in
the run came from a repository where `pytest` happened to be the right answer.

The outcome difference is not significant on its own (Fisher p = 0.13 at the 22-instance
mark) and is not the claim. The claim is the mechanism, which has no exceptions: the agent
never found the command. Whether telling it changes the outcome is what the A/B measures.
