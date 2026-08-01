#!/usr/bin/env python3
"""Strip from a model patch the files the agent created but did not fix anything with.

This is a diagnostic, not a claim. It measures how much of the failure is delivery hygiene
rather than reasoning, by asking: if the patch contained only the source changes, would the
instance grade differently?

`psf__requests-1142` is the case that motivates it. The agent edited requests/models.py --
the same file and the same function as the gold patch -- and then shipped that edit inside
65 new files under build/lib/requests/, which already exist in the evaluation container.
`patch` reverse-applied, hit APPLY_PATCH_FAIL, and the test log came back 0 bytes long. The
verdict was False on a patch whose only real hunk was plausibly correct.

Two categories are removed, and the boundary matters:

  generated   build/, dist/, *.egg-info/, .tox/, __pycache__/ -- artifacts of running a
              build, not of solving anything. Present in the container already.
  scratch     new top-level files named like reproduce_*.py, test_*.py, debug_*.py that
              the agent wrote to explore. NEW FILES ONLY: a modification to an existing
              test file is a real change to the repository and is never touched.

Never removed: any modification to a file that existed. If the agent broke something, that
stays in the patch and stays its fault.
"""
import json
import re
import sys
from pathlib import Path

GENERATED = re.compile(
    r"^(build/|dist/|\.eggs?/|[^/]+\.egg-info/|\.tox/|__pycache__/|\.pytest_cache/"
    r"|node_modules/|\.mypy_cache/)")
SCRATCH_NAME = re.compile(
    r"^(test_|tests_|debug_|reproduce|repro_|comprehensive|simple_|validation|verify_"
    r"|check_|final_|demo_|scratch_|tmp_|my_)")


def split_patch(patch: str):
    """[(header_line, full_block)] per file, in order."""
    blocks = re.split(r"(?=^diff --git )", patch, flags=re.M)
    return [b for b in blocks if b.strip()]


def classify(block: str):
    m = re.match(r"^diff --git a/(\S+) b/(\S+)", block)
    if not m:
        return "other", None
    path = m.group(2)
    is_new = "new file mode" in block.split("\n@@")[0]
    if GENERATED.match(path):
        return "generated", path
    if is_new and "/" not in path and SCRATCH_NAME.match(path.rsplit("/", 1)[-1]):
        return "scratch", path
    return "keep", path


def clean(patch: str):
    kept, dropped = [], []
    for b in split_patch(patch):
        kind, path = classify(b)
        (kept if kind in ("keep", "other") else dropped).append((kind, path, b))
    out = "".join(b for _, _, b in kept)
    return (out.rstrip() + "\n") if out.strip() else "", dropped


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    only = sys.argv[3] if len(sys.argv) > 3 else None
    rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]
    out = []
    for x in rows:
        if only and x["instance_id"] != only:
            continue
        tr = x.get("test_result") or {}
        before = tr.get("git_patch") or ""
        after, dropped = clean(before)
        if dropped:
            print(f"{x['instance_id']}: {len(before)} -> {len(after)} chars, "
                  f"dropped {len(dropped)} files")
            for kind, path, _ in dropped[:6]:
                print(f"    {kind:9s} {path}")
            if len(dropped) > 6:
                print(f"    ... and {len(dropped)-6} more")
        tr["git_patch"] = after
        x["test_result"] = tr
        out.append(x)
    dst.write_text("".join(json.dumps(x) + "\n" for x in out))
    print(f"\nwrote {len(out)} instances to {dst}")


if __name__ == "__main__":
    main()
