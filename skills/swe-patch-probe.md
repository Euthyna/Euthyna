---
name: swe-patch-probe
description: Apply a candidate edit, re-run the reproducer, revert if nothing changed
signature: [bash:echo, bash:sed, bash:sed, bash:echo, bash:sed, bash:echo]
steps_replaced: 6
measured_body_tokens: 204   # observed on the wire, 3 sessions; chars/4 estimated 156
preconditions:
  - a reproducer command exists and has been run at least once
  - the target file is known
harness: mini-swe-agent   # the vocabulary the signature above speaks
source: mined from 20 mini-SWE-agent sessions; the observed instance ran lint → patch
  → patch → lint → revert → lint against one file
---

Probe a candidate fix without leaving debris. Take the reproducer command and the
edit, then:

```bash
cp "$FILE" "$FILE.probe" &&
  <apply edit to $FILE> &&
  BEFORE=$(<reproducer>) &&
  AFTER=$(<reproducer>) &&
  if [ "$BEFORE" = "$AFTER" ]; then mv "$FILE.probe" "$FILE"; else rm "$FILE.probe"; fi
```

The observed six-step version interleaved edits and lint runs manually and left one
edit half-reverted. Capture the reproducer output before and after in the same shell
so the comparison is exact, and always restore from the copy rather than composing an
inverse `sed` — the inverse is where the observed run went wrong.
