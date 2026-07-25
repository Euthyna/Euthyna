# Flow Classification & Distillation Candidates (Stage 1) — committee-corrected

> Regenerated from the committed `candidates.jsonl` in this same directory, so every number here is reproducible from the PR. Went through an adversarial methodology review; the corrections below are baked in.

_Corpora: 3 SMALL PUBLIC sets — miniswe (20 sess), taubench (25), magagent (25); 70 sessions, 1619 steps. All claims scoped **'among these 3 corpora'**; no generalization. magagent is a SINGLE orchestrator framework (MagenticOne) — its dominant flows are framework-specific plumbing, not general behavior._

> **Scope:** descriptive only. No skills generated (Stage 2), no efficacy/savings claims (Stage 3 A/B + A/A floor only). Amortization = byte-weight UPPER BOUND, not a saving.

## Counts (reconciled)

- **975** raw candidate flows (across L0/L1/L2, one per signature level).
- **333** cross-level families (a family = same tool-sequence + length + corpus; richest level kept). `candidates_classified.jsonl` has 333 rows (the de-duplicated cross-level families).
- **189** families remain after excluding the two non-distill-target categories (`dialog_turntaking`, `orchestrator_stall`).

## ⚠️ Integrity check (NOT 'precision')
An earlier draft reported 'precision = 1.0'. **Retracted as a quality signal — it was tautological** (the miner groups by signature; re-checking the signature within a group cannot fail). It is an **integrity/self-consistency** check only. A real precision measure needs an external, falsifiable adjudicator against a negative class — **not yet done.**

## ⚠️ PRIMARY ranking: recurrence (n_sessions, then occ)
Ranking by amortizable tokens conflates step SIZE with distillation VALUE (magagent's ~5k-token ledger JSON would otherwise dominate on byte-weight alone). Recurrence is the honest primary axis.

| # | category | lvl | len | n_sess | occ | corpora |
|---|---|---|---|---|---|---|
| 1 | `orchestrator_delegation` | L2 | 3 | 22 | 39 | magagent |
| 2 | `orchestrator_delegation` | L2 | 3 | 20 | 30 | magagent |
| 3 | `orchestrator_plan` | L2 | 3 | 18 | 22 | magagent |
| 4 | `orchestrator_execute_loop` | L2 | 3 | 16 | 35 | magagent |
| 5 | `orchestrator_execute_loop` | L2 | 3 | 15 | 52 | magagent |
| 6 | `orchestrator_plan` | L2 | 4 | 13 | 14 | magagent |
| 7 | `orchestrator_websearch` | L2 | 3 | 4 | 4 | magagent |
| 8 | `repo_exploration` | L1 | 3 | 3 | 3 | miniswe |
| 9 | `orchestrator_websearch` | L2 | 5 | 3 | 3 | magagent |
| 10 | `edit_verify_loop` | L1 | 4 | 2 | 6 | miniswe |

## ⚠️ Within- vs cross-session amortization (miniswe inflation disclosed)
'Conservative' per_occ×(occ−1) counts WITHIN-session repeats. Cross-session per_occ×(n_sess−1) is stricter. For miniswe: Σ within = **2,044,348**, Σ cross = **703,602** → **2.9× inflation**, disclosed not hidden.

## ⚠️ miniswe = 1–2-witness observation, not an established regularity
Every miniswe ritual sits at the n_sessions=2–3 filter floor; median single-session concentration ≈ **0.67** (most occurrences from one session). Hypothesis-generating only. Categories with a single family (e.g. repo_exploration, env_setup_rerun) are anecdotes.

## Emergent taxonomy (recurrence-honest)

| category | families | max n_sess | corpora |
|---|---|---|---|
| `dialog_turntaking` | 144 | 22 | {'taubench': 144} |
| `orchestrator_execute_loop` | 85 | 16 | {'magagent': 85} |
| `orchestrator_delegation` | 65 | 22 | {'magagent': 65} |
| `orchestrator_plan` | 24 | 18 | {'magagent': 24} |
| `edit_verify_loop` | 10 | 2 | {'miniswe': 10} |
| `orchestrator_websearch` | 3 | 4 | {'magagent': 3} |
| `repo_exploration` | 1 | 3 | {'miniswe': 1} |
| `env_setup_rerun` | 1 | 2 | {'miniswe': 1} |

## Top distillation candidates — skill sketches (descriptive; what a static program *would* do)

**1. `orchestrator_delegation`** (L2, 3 steps, n_sessions=22, occ=39)  
`assistant:text() → assistant:ledger(next_speaker=<slot>) → assistant:ledger(next_speaker=<slot>)`  

> A routing helper that collapses the ledger→text delegation turns into one call: evaluate the ledger, emit the delegation message to the chosen agent, and advance — instead of re-serializing the full ledger state each turn. Parameterized by next_speaker.

**2. `orchestrator_delegation`** (L2, 3 steps, n_sessions=20, occ=30)  
`assistant:ledger(next_speaker=<slot>) → assistant:ledger(next_speaker=<slot>) → assistant:text()`  

> A routing helper that collapses the ledger→text delegation turns into one call: evaluate the ledger, emit the delegation message to the chosen agent, and advance — instead of re-serializing the full ledger state each turn. Parameterized by next_speaker.

**3. `orchestrator_plan`** (L2, 3 steps, n_sessions=18, occ=22)  
`assistant:reason(secs=GIVEN OR VERIFIED FACTS/FACTS TO LOOK UP/FACTS TO DERIVE/EDUCATED GUESSES) → assistant:text() → assistant:ledger(next_speaker=<slot>)`  

> A planning-scaffold program that materializes the fact-sheet / reasoning sections once and threads them through the ledger loop, so the plan is computed a single time rather than re-derived across the repeated reason→ledger steps.

**4. `orchestrator_execute_loop`** (L2, 3 steps, n_sessions=16, occ=35)  
`assistant:ledger(next_speaker=<slot>) → assistant:ledger(next_speaker=<slot>) → assistant:code:python()`  

> A static orchestration primitive that replaces the repeated ledger→execute→ledger cycle: given the current task ledger, decide the next speaker and, when it is the coder, run the code block and fold stdout/exit-code back into the ledger deterministically — skipping the LLM round-trip that currently re-emits the near-identical ledger JSON on every step. Parameterized by next_speaker and code_body.

**5. `orchestrator_execute_loop`** (L2, 3 steps, n_sessions=15, occ=52)  
`assistant:ledger(next_speaker=<slot>) → assistant:code:python() → assistant:ledger(next_speaker=<slot>)`  

> A static orchestration primitive that replaces the repeated ledger→execute→ledger cycle: given the current task ledger, decide the next speaker and, when it is the coder, run the code block and fold stdout/exit-code back into the ledger deterministically — skipping the LLM round-trip that currently re-emits the near-identical ledger JSON on every step. Parameterized by next_speaker and code_body.

**6. `orchestrator_plan`** (L2, 4 steps, n_sessions=13, occ=14)  
`assistant:reason(secs=GIVEN OR VERIFIED FACTS/FACTS TO LOOK UP/FACTS TO DERIVE/EDUCATED GUESSES) → assistant:text() → assistant:ledger(next_speaker=<slot>) → assistant:ledger(next_speaker=<slot>)`  

> A planning-scaffold program that materializes the fact-sheet / reasoning sections once and threads them through the ledger loop, so the plan is computed a single time rather than re-derived across the repeated reason→ledger steps.

**7. `orchestrator_websearch`** (L2, 3 steps, n_sessions=4, occ=4)  
`assistant:ledger(next_speaker=<slot>) → assistant:tool:web_search() → assistant:ledger(next_speaker=<slot>)`  

> A retrieval sub-routine wrapping ledger→web_search→ledger: issue the query, attach results to the ledger, and re-evaluate — as one static step rather than three LLM turns.

**8. `repo_exploration`** (L1, 3 steps, n_sessions=3, occ=3)  
`assistant:grep → assistant:grep → assistant:cat`  

> A search-then-read helper: run the grep/find with a narrowing pattern, and if it resolves to a single file, cat the relevant region — one call instead of the grep→grep→cat opener the agent repeats when orienting in a repo. Parameterized by search_pattern and read_path.

**9. `orchestrator_websearch`** (L2, 5 steps, n_sessions=3, occ=3)  
`assistant:tool:web_search() → assistant:ledger(next_speaker=<slot>) → assistant:text() → assistant:ledger(next_speaker=<slot>) → assistant:ledger(next_speaker=<slot>)`  

> A retrieval sub-routine wrapping ledger→web_search→ledger: issue the query, attach results to the ledger, and re-evaluate — as one static step rather than three LLM turns.

**10. `edit_verify_loop`** (L1, 4 steps, n_sessions=2, occ=6)  
`assistant:echo → assistant:sed → assistant:sed → assistant:echo`  

> A parameterized edit-and-lint program: apply the sed edit to the target file, then run the sqlfluff/echo lint check and parse pass/fail — replacing the hand-rolled echo|sqlfluff verify the agent re-types each iteration. Parameterized by edit_file and lint_target.

## Honest nulls & limits
- taubench = **SIGNAL_NOT_DETECTED** for distillation (dialog, no tool structure).
- `orchestrator_stall` = consecutive ledger-only steps = a WASTE class (PREEMPTIVE_HELPER_TOOL_BUILD mirror), NOT a distillation target.
- n=20/25/25 sessions; magagent is ONE framework. No generalization beyond these corpora.
- External falsifiable precision NOT yet measured.
- Reference run is over corpora whose raw traces are **not shipped** (excluded by design); not rebuildable from this repo alone.
