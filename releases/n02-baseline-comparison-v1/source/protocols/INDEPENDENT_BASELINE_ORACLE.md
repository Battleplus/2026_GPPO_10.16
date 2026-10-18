# Independent baseline oracle

This auditor is a separate standard-library implementation. It consumes action receipts, episode summaries, and an optional evaluation manifest. It does not import simulator or metric code. Run it from the project root:

```powershell
[REDACTED_LOCAL_PATH] -B tools\independent_baseline_oracle.py `
  --actions path\EVALUATION_ACTION_RECEIPTS.jsonl `
  --episodes path\EVALUATION_EPISODES.jsonl `
  --manifest path\BASELINE_EVALUATION_MANIFEST.json `
  --output path\INDEPENDENT_ORACLE_REPORT.json
```

Exit code 0 means no detected mismatch or missing evidence. Exit code 2 means at least one mismatch or missing evidence. The JSON report keeps these classes separate and names the affected method/parent/tape/seed/tick.

## Independent calculations

- Root outcomes come from the first and last raw audit endpoints. The auditor groups raw leaves by `root_mapping`, applies each split manifest's required child IDs, and uses the twelve initial `root_task_specs` as the denominator. Completion requires all leaves of a root to have completed by the horizon. Deadline, critical priority, lateness exposure, and cancellation time are evaluated at root level.
- Per-tick energy is the change in summed raw-platform `energy_used`. Move/service event energy is an independent cross-check. A missing endpoint or disagreement is reported; event reward primitives are not accepted as the sole source.
- Completion comes from newly completed root status between raw endpoints. Delay, risk, communication, and switch primitives are reconstructed from raw events and validated for required fields.
- A queue pop between physical endpoints is not evidence of reconstruction. Queue order mutations count only when an operation receipt shows the before/after mutation at application time. Owner mutations count only when raw root owner sets change and a command-application causal receipt corroborates them. For an immediate dispatch, the action's task/platform pair must match a same-tick assignment event and a delivered `dispatch` communication receipt with zero delay. A `communication_delivered` event is not required for delay-zero delivery. A same-owner queue-head dispatch has no owner-set change and is not effective. Delayed delivery events must identify the originating action; absent attribution is MISSING.
- Reward terms and reward are recomputed from raw-derived primitives and the per-receipt frozen `event-relief-reward/1` formula. Environment utility is the sum of those terms. Net utility subtracts `0.01` per rule-protocol message. Energy, reward terms, total reward, published reward primitives, and action-count fields are cross-checked independently.
- Ordered catalogues are checked using canonical sorted compact JSON SHA-256. The selected index/key and selected full action are bound back to the recorded catalogue. Across methods, episode pairing checks event tape and initial C1 assignment.
- Planning counts have distinct meanings: `planning_invocation_count`/`trigger_count` counts ticks where the method planned; `scope_nonempty_planning_count` counts planned ticks whose affected task or platform IDs are nonempty; `actionable_catalog_planning_count` counts planned ticks whose shared catalogue contains at least one legal non-NOOP action. The legacy `nonempty_planning_invocation_count` is an alias of `actionable_catalog_planning_count`. `requested_nonnoop_count` counts actions actually requested. Detector edges are a separate shared-observation count.
- The raw simulator records `platform_failed` and a corresponding `platform_failure` primitive with the same event identity. Reward risk counts the primitive event `platform_failure` once; `task_failed` counts once. `platform_failed` is the source log alias and does not add a second risk unit.

## Receipt evidence requirements

Every physical action receipt must carry `raw_state_before` and `raw_state_after`, each with `leaf_tasks`, `leaf_task_specs`, `root_task_specs`, `split_manifests`, `root_mapping`, `leaf_platforms`, `platform_specs`, `queues`, and `time`. Raw event energy/risk/communication fields must be present when those events occur. Reward formula, terms, and scalar reward must be recorded.

Operation receipts need operation identity, application-time queue endpoints, and owner endpoints. A delayed command's delivery event or command application receipt must include its originating action ID, task/platform/operation identity, and the application-time before/after owner or queue state. Without this linkage, a delivery may be reported as observed but its effective reconstruction attribution remains MISSING.

Episode summaries are comparisons only. They cannot repair missing raw evidence. The auditor intentionally reports incomplete roots, missing raw endpoints, absent reward weights, unbound delayed effects, and incomplete pairing as failures rather than assigning favorable defaults.

If `initial_c1_assignment` is null in the episode summary, the auditor derives the pairing signature from the first raw `queues` and `root_mapping`. It compares that signature across all method episodes sharing parent and seed; a single method episode can only establish the local signature, not cross-method equality.
