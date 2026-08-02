---
name: swe-localize-symbol
description: Narrow from a symbol name to its definition site in three passes
signature: [bash:grep, bash:grep, bash:grep]
steps_replaced: 3
preconditions:
  - a symbol or identifier is named in the issue text
  - no file has been read yet this session
harness: mini-swe-agent   # the vocabulary the signature above speaks
source: mined from 20 mini-SWE-agent sessions; opens 5 of them
---

Collapse the three-grep opening into one progressive search. Observed shape: a broad
recursive grep, then a grep restricted to the files the first pass surfaced, then a
grep for the exact call form.

```bash
SYM="$1"
grep -rn --exclude-dir={tests,node_modules,.git} -e "def $SYM" -e "class $SYM" . \
  || grep -rn --exclude-dir={tests,node_modules,.git} -e "$SYM" . | head -40
```

Stop at the first pass that returns a definition site. If the second pass returns the
same file set as the first, the symbol is not defined in this tree — say so and read
the issue again rather than running a third variant, which is the observed failure
mode (three greps, no narrowing).
