# N02 v2 final status

New archive: `archive/n02-baseline-comparison-v1`. The existing mechanism branch `archive/n02-event-trigger-v2-100x100` is preserved at its earlier commit and is not overwritten by this publication.
Tags: `n02-baseline-comparison-v1`, `n02-event-trigger-v2`.

Gate1, Gate2 and Gate3: GPT-6.1 Sol High PASS for engineering integrity within the stated scope. Research result: **RESEARCH_CRITERIA_FAILED**. Do not claim a validated scientific advantage or statistical significance.

Completed workload: 9 methods × 3 seeds × 2 development parents = 54 evaluations, 3240 ticks; 240 CUDA WM updates; 2304 CUDA policy updates; 288 training episodes; 3 WM and 18 policy fresh-process restore receipts. Revised independent causal replay: zero mismatches and zero missing items. Old oracle failure and measurement revision are preserved.

Both event methods have 9 distinct local reconstruction actions and zero empty-domain global reconstructions. The raw witness records number 11 for Event-GPPO and 12 for Event-GPPO-WM because an action can have both queue and owner-change evidence. Event-method candidate counts are 1–7; all-method counts are 1–8; maximum configured 16. WM is critic-only. Rule methods are candidate-constrained; CBBA-lite is not full CBBA; PPO/GPPO are not parameter matched.

Metadata erratum: the frozen coordinator consistency summary has `episodes.record_count=16`, a per-group count mislabeled as the total. Independent Sol row-by-row counting found 18 groups and 288 actual training episodes. The original frozen report remains unchanged; see the Gate3 review.

The reviewed release stage is frozen before publication. Its stage status records Gate3 as pending at freeze; the final Gate3 receipt is outside that stage to avoid a circular hash. Root status and that receipt supersede staging metadata for the final review decision.

Small graph/WM checkpoints and sanitized replay data are public. Large Flat PPO checkpoints and raw 1.44 GB training action receipts are private with public digest commitments. Historical transport CPU/wall and host RSS have missing fields explicitly retained; no complete all-session resource total is asserted.

Publication verification is recorded in the local publication receipt after pushing; this file describes the contents of this archive commit.
