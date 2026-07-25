"""Stage 1 — data-driven flow classification + skill sketches.

Categories were NOT imposed from the brief's guesses; they emerged from
clustering the mined L1 flows by their tool-set fingerprint (see classify's
CLUSTER_RULES, each grounded in inspected templated commands). We:
  * assign every candidate a category + human name + parameter slots
  * merge semantically-equivalent flows (same job, differ only at L2 args)
  * pick the top-10 distillation candidates and write a one-paragraph skill
    sketch for each (what a STATIC program replacing the flow would do)
No skills are generated (that's Stage 2) — only descriptive sketches.
"""
from __future__ import annotations
import json
import re
import collections


def toolseq(sig):
    steps = [s.strip() for s in sig.split("→")]
    return [re.sub(r"^assistant:", "", s).split("(")[0].split("#")[0] for s in steps]


def toolset(sig):
    return frozenset(toolseq(sig))


# --- taxonomy: (predicate over toolset) -> (category, name, slots) ----------
# Ordered; first match wins. Grounded in inspected command templates.
def classify_flow(c):
    ts = toolset(c["readable_signature"])

    # ----- miniswe (real shell rituals) -----
    if ts <= {"echo", "sed"} and ts:
        return ("edit_verify_loop",
                "sed-edit → sqlfluff/echo-lint verify loop",
                ["edit_file", "lint_target"])
    if ts <= {"grep", "cat", "find"} and ("grep" in ts or "find" in ts):
        return ("repo_exploration",
                "grep/find narrow → cat read (search-then-inspect)",
                ["search_pattern", "read_path"])
    if ts <= {"python", "pip"} and "pip" in ts:
        return ("env_setup_rerun",
                "python-run → pip-install(fix) → python-rerun",
                ["script", "package"])
    if ts <= {"python", "pylint", "cat", "cd"} and "python" in ts:
        return ("test_run_parse",
                "python/pylint run-and-parse ritual",
                ["target"])
    if "git" in ts and ts <= {"git", "echo", "cd"}:
        return ("submit_ritual",
                "git add/diff/commit submit ritual",
                ["message"])

    # ----- magagent (MagenticOne orchestration) -----
    if ts == {"ledger", "code:python"} or ts == {"ledger", "code:sh"}:
        return ("orchestrator_execute_loop",
                "orchestrator ledger-check → code exec → ledger-recheck",
                ["next_speaker", "code_body"])
    if ts == {"ledger", "text"}:
        return ("orchestrator_delegation",
                "ledger routing → text delegation turns",
                ["next_speaker"])
    if "reason" in ts and "ledger" in ts:
        return ("orchestrator_plan",
                "reason/fact-sheet → ledger planning loop",
                ["plan_sections", "next_speaker"])
    if "tool:web_search" in ts:
        return ("orchestrator_websearch",
                "ledger → web_search → ledger (retrieval loop)",
                ["query", "next_speaker"])
    if ts == {"ledger"}:
        return ("orchestrator_stall",
                "consecutive ledger re-evaluations (no progress step)",
                ["next_speaker"])

    # ledger-dominant mixes (ledger + code + text, etc.) — still the execute loop
    if "ledger" in ts and (ts & {"code:python", "code:sh"}):
        return ("orchestrator_execute_loop",
                "orchestrator ledger + code exec (+delegation) loop",
                ["next_speaker", "code_body"])
    if "ledger" in ts and "text" in ts:
        return ("orchestrator_delegation",
                "ledger routing → text delegation turns",
                ["next_speaker"])

    # ----- taubench (dialog) -----
    if ts <= {"turn_text", "turn_empty"}:
        return ("dialog_turntaking",
                "customer-service dialog turn-taking (no tool structure)",
                [])

    return ("unclassified", "unclassified flow", [])


def enrich(candidates_path, out_path):
    cands = [json.loads(line) for line in open(candidates_path)]
    # semantic merge: group by (category, length, corpus) across L0/L1/L2 that
    # share the same L1 tool sequence -> keep the richest-level representative,
    # record merged_from.
    for c in cands:
        cat, name, slots = classify_flow(c)
        c["label"] = {"name": name, "category": cat,
                      "parameter_slots": slots, "merged_from": []}

    # group L0/L1/L2 variants of the SAME flow (same corpus, same tool seq, same len)
    def mergekey(c):
        return (tuple(toolseq(c["readable_signature"])),
                c["length_steps"], tuple(c["corpora"]))
    groups = collections.defaultdict(list)
    for c in cands:
        groups[mergekey(c)].append(c)

    merged = []
    level_rank = {"L2": 3, "L1": 2, "L0": 1}
    for key, cs in groups.items():
        rep = max(cs, key=lambda c: (level_rank[c["signature_level"]],
                                     c["est_amortizable_tokens"] or 0))
        rep["label"]["merged_from"] = sorted(
            {c["flow_id"] for c in cs if c["flow_id"] != rep["flow_id"]})
        merged.append(rep)

    merged.sort(key=lambda c: -(c["est_amortizable_tokens"] or 0))
    with open(out_path, "w") as f:
        for c in merged:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return merged


# --- one-paragraph skill sketches for the top-10 (descriptive, not generated)
SKETCHES = {
    "orchestrator_execute_loop":
        "A static orchestration primitive that replaces the repeated "
        "ledger→execute→ledger cycle: given the current task ledger, decide "
        "the next speaker and, when it is the coder, run the code block and "
        "fold stdout/exit-code back into the ledger deterministically — "
        "skipping the LLM round-trip that currently re-emits the near-identical "
        "ledger JSON on every step. Parameterized by next_speaker and code_body.",
    "orchestrator_delegation":
        "A routing helper that collapses the ledger→text delegation turns into "
        "one call: evaluate the ledger, emit the delegation message to the "
        "chosen agent, and advance — instead of re-serializing the full ledger "
        "state each turn. Parameterized by next_speaker.",
    "orchestrator_plan":
        "A planning-scaffold program that materializes the fact-sheet / "
        "reasoning sections once and threads them through the ledger loop, so "
        "the plan is computed a single time rather than re-derived across the "
        "repeated reason→ledger steps.",
    "orchestrator_websearch":
        "A retrieval sub-routine wrapping ledger→web_search→ledger: issue the "
        "query, attach results to the ledger, and re-evaluate — as one static "
        "step rather than three LLM turns.",
    "orchestrator_stall":
        "NOT a distillation target — consecutive ledger-only steps are the "
        "orchestrator stalling / re-checking without progress. Flag as a waste "
        "pattern (candidate PREEMPTIVE_HELPER_TOOL_BUILD mirror) for Stage 2 to "
        "AVOID, not compile.",
    "edit_verify_loop":
        "A parameterized edit-and-lint program: apply the sed edit to the "
        "target file, then run the sqlfluff/echo lint check and parse pass/fail "
        "— replacing the hand-rolled echo|sqlfluff verify the agent re-types "
        "each iteration. Parameterized by edit_file and lint_target.",
    "repo_exploration":
        "A search-then-read helper: run the grep/find with a narrowing pattern, "
        "and if it resolves to a single file, cat the relevant region — one "
        "call instead of the grep→grep→cat opener the agent repeats when "
        "orienting in a repo. Parameterized by search_pattern and read_path.",
    "env_setup_rerun":
        "A run-install-rerun wrapper: execute the script, and on "
        "ImportError/ModuleNotFound, pip-install the missing package and retry "
        "once — compiling the python→pip→python recovery the agent does by "
        "hand. Parameterized by script and package.",
    "test_run_parse":
        "A test/lint run-and-parse primitive that executes the target and "
        "returns a structured pass/fail + first failure, instead of the agent "
        "re-issuing the run and re-reading raw output each time.",
    "submit_ritual":
        "A one-shot submit program for the git add→diff→commit closing ritual, "
        "parameterized by commit message.",
    "dialog_turntaking":
        "NOT a distillation target — tau-bench turn-taking has no tool "
        "structure; the repetition is conversational, not a compilable "
        "procedure. Report as SIGNAL_NOT_DETECTED for skill distillation.",
    "unclassified": "Unclassified; needs manual review.",
}
