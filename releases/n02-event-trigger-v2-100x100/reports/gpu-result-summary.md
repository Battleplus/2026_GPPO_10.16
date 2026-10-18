# N02 v2 GPU Run: Public Result Summary

Status: `REPAIR_REQUIRED`. GPU engineering closure: `PASS_ENGINEERING_CLOSURE`. Registered mechanism and quality/utility acceptance: `REPAIR_REQUIRED`; desired scientific advantage is not established. Incremental sanitized-public-staging review and publication remain pending.

## Scope and engineering closure

This report covers frozen release `n02-event-trigger-v2-gpu-68e537cd0c5c43e19a8bec4a0a3e209d` and one completed attempt. Sol independently verified all 82 frozen source-manifest files and all 144 immutable-result files, with zero hash mismatches. It reconciled 12 PPO runs, 11,520 training rows, 1,440 development rows, zero raw reward/action-mask issues, 240 world-model updates, and 1,344 PPO updates. Each of 12 policies completed 112 updates; 128 was the ceiling. Three world-model and 12 policy checkpoints have fresh-process restore receipts. The reviewer corroborated the hashed receipts and source but did not independently replay CUDA restore.

Training ran on CUDA. World-model member digests remained unchanged. All 672 of 672 WM-variant updates had nonzero auxiliary gradients; non-WM updates had none. A separate, read-only CPU post-run reconstruction from the exact frozen seeded initializer independently verified six auxiliary-only parameter changes (L2: 0.9407560072, 0.8611670054, 0.9561769596, 0.9338288859, 0.8744000201, 0.9738106148) and nonzero Adam moments. That approximately one-second CPU audit performed no training, optimizer step, backward pass, or inference and is not contemporaneous CUDA telemetry.

## Development means

Each method mean is equally weighted over six development episodes: three trained seeds by two held-out parent scenarios. There are 24 episodes total, not 24 independent scenario families. Rates are proportions. Counts are per episode.

| Metric | Periodic-G | Event-G | Periodic-G-WM | Event-G-WM |
|---|---:|---:|---:|---:|
| Global utility | 1.9963501817 | 1.9857196234 | 1.2776771286 | 3.3732536340 |
| Completion rate | 0.6527777778 | 0.6527777778 | 0.6250000000 | 0.7083333333 |
| On-time rate | 0.6527777778 | 0.6527777778 | 0.6250000000 | 0.7083333333 |
| Failure rate | 0.0416666667 | 0.0416666667 | 0.0416666667 | 0.0416666667 |
| Critical failure rate | 0 | 0 | 0 | 0 |
| Trigger invocations | 10 | 1.5 | 10 | 1.5 |
| Communication messages | 8.3333333333 | 8.3333333333 | 8.0000000000 | 9.6666666667 |
| Effective reconstructions | 0.1666666667 | 0.3333333333 | 0 | 1 |
| Reconstruction size | 0.1666666667 | 0.3333333333 | 0 | 1 |
| Global replans | 0.1666666667 | 0.3333333333 | 0 | 1 |
| Local repairs | 0 | 0 | 0 | 0 |

## Registered criteria

- GPU engineering closure: `PASS_ENGINEERING_CLOSURE`.
- Requirement 7, at least one audited effective Event-G local-repair mutation: fail; training count 0, development count 0. Across all methods, requested/effective/audited local count was 0.
- Event-G utility non-decrease versus Periodic-G: fail; difference `-0.010630558319853822`.
- Event-G-WM utility non-decrease versus Periodic-G-WM: pass; difference `+2.0955765053992037`.
- Eight registered completion, on-time, failure, and critical-failure quality checks: all pass.
- Lower Event-G trigger count: pass (1.5 versus 10 per episode).
- At least one Event-G cost reduction: fail. Communication reduction: false (8.3333333333 versus 8.3333333333); effective-reconstruction reduction: false (0.3333333333 versus 0.1666666667); reconstruction-size reduction: false (0.3333333333 versus 0.1666666667).
- Actual empty-affected-domain global replans: 0.

Event-G-WM improves descriptive utility over Event-G while also changing WM-assisted triggering and the detached auxiliary critic; it incurs higher communication and reconstruction costs. This comparison does not isolate a trigger-only or critic-only causal effect. The v2 initialization also differs from v1, so this is not a trigger-only v1/v2 comparison. No significance, broad generalization, or deployment claim is supported by this design or 100x100 setting.

## Independent audit limits

The raw-consequence audit covered 243 branches and 24 windows, found zero label mismatches, and caught all 3 comparison mutations and 6 raw mutations. It did not reconstruct private initial simulator states or independently replay simulator transitions. Review was by an independent agent/context within the same model family, not cross-family replication or third-party signed certification.

Final independent review: `SOL_V2_FINAL_GPU_REVIEW_64651070_20261018`, JSON SHA-256 `7d19b9bbf080ab2dee922721f9be039abaceba0bb642a75c21b7e8c4dd7fefa7`. Overall registered acceptance remains `REPAIR_REQUIRED`. This is an honest negative result; no science-success claim is made. Public staging consistency/privacy review is pending, and no publication has occurred.
