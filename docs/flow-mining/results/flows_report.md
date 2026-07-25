# Flow Mining Report (Stage 0)

> **Descriptive only.** No skills are generated (Stage 2) and no efficacy/savings claims are made (Stage 3 A/B + A/A floor only). Amortization is a byte-weight **upper bound**, not a saving. Scope: only the corpora below — no generalization.

_window 3-8 steps · repeated = >=3 occ across >=2 sessions · min distinct steps/flow = 2._

## Per-corpus stats

| corpus | mode | files | sessions | steps | present |
|---|---|---|---|---|---|
| miniswe | miniswe | 20 | 20 | 402 | yes |
| taubench | taubench | 25 | 25 | 471 | yes |
| magagent | magagent | 25 | 25 | 746 | yes |

## Flows by signature level

| level | candidate flows |
|---|---|
| L0 | 321 |
| L1 | 333 |
| L2 | 321 |

## Top-10 candidates — PRIMARY ranking: recurrence (n_sessions, then occ)

| # | flow_id | lvl | len | occ | sess | corpora | per-occ tok | amort (cons) | amort (upper) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | F0540 | L0 | 3 | 46 | 22 | taubench | 336 | 15120 | 22026 |
| 2 | F0541 | L1 | 3 | 46 | 22 | taubench | 336 | 15120 | 22026 |
| 3 | F0542 | L2 | 3 | 46 | 22 | taubench | 336 | 15120 | 22026 |
| 4 | F0043 | L0 | 3 | 39 | 22 | magagent | 4003 | 152114 | 260858 |
| 5 | F0044 | L1 | 3 | 39 | 22 | magagent | 4003 | 152114 | 260858 |
| 6 | F0045 | L2 | 3 | 39 | 22 | magagent | 4003 | 152114 | 260858 |
| 7 | F0092 | L0 | 3 | 30 | 20 | magagent | 3862 | 111998 | 187411 |
| 8 | F0093 | L1 | 3 | 30 | 20 | magagent | 3862 | 111998 | 187411 |
| 9 | F0094 | L2 | 3 | 30 | 20 | magagent | 3862 | 111998 | 187411 |
| 10 | F0025 | L0 | 4 | 28 | 20 | magagent | 6213 | 167751 | 278527 |

## Secondary view — byte-weight (amortizable tokens); NOT a value ranking

_Favors verbose-serialization frameworks (a large per-step payload tops this by size alone); says nothing about reuse or compressibility._

| # | flow_id | lvl | len | occ | sess | corpora | per-occ tok | amort (cons) | amort (upper) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | F0001 | L0 | 3 | 52 | 15 | magagent | 5034 | 256734 | 490274 |
| 2 | F0002 | L1 | 3 | 52 | 15 | magagent | 5034 | 256734 | 490274 |
| 3 | F0003 | L2 | 3 | 52 | 15 | magagent | 5034 | 256734 | 490274 |
| 4 | F0004 | L0 | 5 | 13 | 10 | magagent | 18670 | 224040 | 302209 |
| 5 | F0005 | L1 | 5 | 13 | 10 | magagent | 18670 | 224040 | 302209 |
| 6 | F0006 | L2 | 5 | 13 | 10 | magagent | 18670 | 224040 | 302209 |
| 7 | F0007 | L0 | 4 | 31 | 11 | magagent | 6533 | 195990 | 361978 |
| 8 | F0008 | L1 | 4 | 31 | 11 | magagent | 6533 | 195990 | 361978 |
| 9 | F0009 | L2 | 4 | 31 | 11 | magagent | 6533 | 195990 | 361978 |
| 10 | F0010 | L0 | 5 | 11 | 9 | magagent | 18745 | 187450 | 250902 |
