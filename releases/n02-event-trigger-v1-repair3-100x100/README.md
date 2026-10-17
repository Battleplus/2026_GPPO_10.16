# N02 event-trigger V1 repair3 — 100x100

This directory records the repaired formal run for source release
`n02-event-trigger-v1-18f0ed76de7f433380d231b1dd28bb61` and attempt
`n02-event-v1-d0e59d2f21264863990169fe0874e764`. The source manifest SHA-256 is
`fc769fb36295501018afe43d7732684a5f3a843c13f591c786ac99e8f2f6ba09`.

GPT-6.1 Sol High independently reviewed the complete evidence snapshot and
returned `PASS`; 143/143 evidence hashes matched. The result is an engineering
pass. Scientific efficacy remains `UNVERIFIED` because development comparisons
cover two held-out parents and three seeds only.

The event diagnostic recorded 42 triggers, all `GLOBAL_REPLAN`, and 25
effective non-NOOP global actions. The periodic diagnostic recorded 13
`LOCAL_REPAIR` and 77 `GLOBAL_REPLAN` triggers; effective changes were 13 local
and 17 global. Local repair is demonstrated by periodic diagnostics in this
run, not by event-trigger mode.

M2's independent oracle recomputed 24/24 planned windows across 253 branches,
including explicit NOOP actions, without reading producer labels. M3 completed
three world-model trainings and fresh-process restores. M4 completed Event-G,
Event-G-WM, Periodic-G, and Periodic-G-WM for seeds 8201-8203, with 1,344 PPO
updates and 12/12 fresh-process policy checkpoint restores.

The public boundary contains the frozen source files and small sanitized audit
summaries. It omits model checkpoints, raw operational logs, private execution
context, and credentials. Run `python -B verify_public_snapshot.py` from this
directory to verify `PUBLIC_ARCHIVE_INVENTORY.json`.
