---
name: swe-submit
description: Stage everything and emit the final diff, the fixed end-of-task ritual
signature: [bash:echo]
steps_replaced: 1
preconditions:
  - working tree has at least one modification
harness: mini-swe-agent   # the vocabulary the signature above speaks
source: mined from 20 mini-SWE-agent sessions; byte-identical in 6 of them
---

Run the terminal submission sequence as one command:

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git add -A && git diff --cached
```

Nothing in it is parameterised — the marker string, the staging flag and the diff
form are identical in every observed occurrence. Emit it verbatim once the fix is
verified; do not stage selectively first, since `-A` is what the harness expects.
