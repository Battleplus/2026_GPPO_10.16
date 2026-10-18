# Baseline Analysis Results

The analysis CLI consumes one completed `BASELINE_EVALUATION_MANIFEST.json`, its `EVALUATION_EPISODES.jsonl`, the corresponding raw `EVALUATION_ACTION_RECEIPTS.jsonl`, and every available resource receipt. It writes four files: `FINAL_METHOD_COMPARISON.json`, `FINAL_BASELINE_REPORT.md`, `FINAL_TRIGGER_REPORT.md`, and `FINAL_RESOURCE_SETTLEMENT.json`.

Run it from the project root:

```powershell
[REDACTED_LOCAL_PATH] -B tools\analyze_baseline_results.py `
  --profile pilot `
  --episodes path\EVALUATION_EPISODES.jsonl `
  --actions path\EVALUATION_ACTION_RECEIPTS.jsonl `
  --manifest path\BASELINE_EVALUATION_MANIFEST.json `
  --oracle-report path\INDEPENDENT_ORACLE_REPORT.json `
  --resource-receipt path\probe\PROBE_RECEIPT.json `
  --resource-receipt path\phase\BASELINE_GUARDIAN_SETTLEMENT.json `
  --attempt-resolution path\ATTEMPT_RESOLUTION.json `
  --output-dir path\analysis
```

Use `--profile formal` for formal data. Formal expects 54 unique cells (nine methods, three seeds, two development parents); pilot expects 18 (nine methods, one seed, two parents). Every method must have one episode per expected seed-parent cell. The method, seed, parent, event tape, and canonical initial C1 assignment must match across methods. Action receipts must cover every episode tick. Missing or duplicated cells, mismatched pairing, absent/non-finite required production metrics, or production/oracle mismatches stop analysis. The independent oracle report must be `PASS` and contain every expected cell before its raw recomputed global utility can be used by the gate. Without it, the raw global utility criterion is `MISSING`, never inferred from production summary metrics.

`FINAL_METHOD_COMPARISON.json` uses schema `n02-baseline-final-comparison/1`. It reports per-method metric means, paired Event/Periodic gate contrasts, descriptive PPO/GPPO and rule comparisons, deterministic rule seed-repeat annotations, and separate run, engineering, and scientific status fields. It makes no statistical significance claim. Pilot status is always `PILOT_DESCRIPTIVE_ONLY`; pilot data cannot be presented as formal completion, including in pair rows. A negative frozen criterion is reported as `RESEARCH_CRITERIA_FAILED`; missing raw evidence is `EVIDENCE_MISSING`.

The two frozen gates are evaluated separately from paired Event minus Periodic cell differences. The global utility gate uses the independent oracle's raw recomputation. Mean critical failures must not increase; completion and on-time rate differences must be at least -0.02; event planning invocations must be lower; and at least one of delivery messages, rule-protocol messages, effective reconstructions, or reconstruction size must decrease. Trigger count equals planning invocations. Detector edges, nonempty affected scope, actionable legal catalogues, the legacy actionable alias, requested actions, effective reconstructions, local/global invocations, owner changes, and queue reorders remain separate fields and are cross-checked against the oracle. Event empty-scope global actions are counted from tick receipts; missing scope evidence is `MISSING`. A local witness requires a requested `LOCAL_REPAIR` and either an action-bound queue-changing operation receipt or an action-bound delivered command whose raw task owner changes. Missing local raw evidence is `MISSING`, never `PASS`. Net utility is reported as secondary and never substitutes for global utility.

Resource receipt paths are supplied explicitly and must include every available probe, smoke, launch, and phase attempt, including failed attempts. Each receipt is retained in the settlement output and all measured failed-attempt costs remain in totals. Only explicit `resource_budget_scope: per_phase` establishes the accounting scope. Complete totals are emitted only when every supplied receipt has that measurement; known subtotals and guardian cgroup phase totals are reported separately when partial. Historical transport CPU unavailable from receipts remains `MISSING`, never zero. Per-phase configured limits are not added together or represented as a single cumulative budget.

Engineering completion requires a successful, same-profile active receipt for each `freeze-wm`, `train`, and `evaluate` phase. A failed attempt is historical cost and does not block that active chain only when `--attempt-resolution` explicitly binds its receipt path and SHA-256 to a successful replacement receipt for the same phase, and names the replacement as the active attempt. The resolution document uses schema `n02-baseline-attempt-resolution/1`, with `profile`, `active_phases` (phase keys mapped to `attempt`, `receipt_path`, and `receipt_sha256`), and `supersessions` rows containing `phase`, failed attempt/path/hash, and successful attempt/path/hash. The analyzer verifies each binding against supplied receipt bytes and fails closed on unresolved failures, missing phases, mismatched profiles/phases/attempts, or unprovided receipts. Omitting the optional document leaves failed history visible and settlement incomplete.

`FINAL_RESOURCE_SETTLEMENT.json` uses schema `n02-baseline-resource-settlement/1`. Its `receipts` list contains source path, schema, status, phase, scope, wall seconds, cgroup CPU seconds (settlement minus start), and peak allocated memory when available. Guardian receipts with failed status remain in totals. Probe, launch, and smoke receipts without time measurements remain visible with missing fields; unavailable historical transport CPU is explicitly `MISSING`.
