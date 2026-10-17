# N02 Run Summary

Input snapshot: `<private-input-snapshot>`

Label: **GPU-formal-final-snapshot-descriptive-analysis**

Raw transition cells found: 24/24.

The paired table has one row per method × seed × development parent. See `paired_comparison.csv`; `MISSING` means the input snapshot did not provide a source value.

Trigger count, requested reconstruction, concrete non-NOOP action count, producer-reported effective count, and independently receipt-verified effective count are separate. Verification uses task-owner-change, queue-reorder, or valid before/after queue receipts. Missing confirmation stays `MISSING`.

Outcome and reported values come from `DEVELOPMENT_EVALUATION.json`. `producer_crosscheck.csv` compares raw-transition recounts with that producer summary and marks each match or mismatch. `paired_comparison.csv` includes per-cell mismatch details.

`method_summary.csv` reports descriptive means and available/missing cell counts. `paired_contrasts.csv` reports mean matched-cell differences for four predefined contrasts; each metric has valid and missing pair denominators. Independent effective counts are never filled from producer-reported counts.

Method means are recomputed from the six explicit method×seed×development-parent episode rows (three seeds × two parents), not the producer's aggregate `descriptive_means`. Delay uses the episode `environment_metrics.mean_delay` value in its source unit of minutes per original task.

In this snapshot `environment_metrics.safety_risk` is present but null and its validity mask is false; the risk metric is therefore reported as `MISSING`, not zero. Other mapped task/resource fields are read from their matching episode `environment_metrics` keys.

For effective reconstruction, exact means use only cells with complete mutation receipts and show that valid N. Cells with receipt gaps retain `MISSING` exact counts; separate lower/upper-bound means and paired contrast intervals give a sensitivity range without imputing a point value.

Rows that requested an action but lacked valid allocation mutation receipts are listed in `receipt_gaps.csv` (7 rows). Missing independent counts therefore remain `MISSING`; a selected dispatch alone does not qualify.

`audit_artifacts.csv` inventories relevant model, restore, receipt, resource, gradient and ledger artifacts with hashes and selected scalar fields. Missing artifacts are absent from this inventory; absent report metrics remain `MISSING`.

## Required Interpretation

- Treat results as descriptive for three seeds and two development parents; do not claim statistical significance or general superiority.
- Event-G-WM changes both trigger and critic, so this comparison cannot isolate the critic effect.
- A reduction in triggers does not establish a reduction in actual reconstructions; use the reported and receipt-verified effective metrics.
- GPU completion and acceptance require matching attempt/source identity and an external review receipt; this tool does not issue a PASS.
