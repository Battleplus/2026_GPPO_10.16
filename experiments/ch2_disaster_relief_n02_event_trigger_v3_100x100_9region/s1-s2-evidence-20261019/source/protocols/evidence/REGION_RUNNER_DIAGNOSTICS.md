# v3 CPU Runner Diagnostics

`package/civilian/region_runner.py` writes a fresh UUID attempt directory containing `REQUEST.json`, `SOURCE_HASHES_BEFORE.json`, `SOURCE_HASHES_AFTER.json`, `C1_PUBLIC_INPUT.json`, `C1_RECEIPT.json`, `DECISIONS.jsonl`, `TRAJECTORY.json`, `SUMMARY.json`, and `ATTEMPT.json`. A change in the Python/config hash inventory marks an attempt `STALE`; the runner does not convert stale or first-zero attempts to pass.

The first v3 environment diagnostic was run on CPU with a fixed new-arrival tape and stopped at its first zero trigger. Raw artifact:

```text
package/tmp-evidence5/smoke-7b59777f008b4aafbee6eaaf501d4da9
```

It recorded `trigger_count=1`, `effective_mutations=0`, and stopped with `FIRST_ZERO_TRIGGER_AT_EXTERNAL_EVENT` after the first scheduled arrival. The diagnostic was then rerun with `diagnostic_event_kind=environment_perturbation` so earlier arrivals remained in the public trace but did not define the stop point:

```text
package/tmp-evidence-env/s0-v3-diagnostic-f8be0996e8e74c0b9fe8dae1dfe3903a
```

That attempt recorded `trigger_count=3`, `effective_mutations=0`, `local_repair_count=0`, `regional_replan_count=0`, `global_replan_count=0`, and stopped at the target perturbation with `FIRST_ZERO_TRIGGER_AT_EXTERNAL_EVENT`. These artifacts are failure diagnostics and do not establish S0/S1 acceptance.
