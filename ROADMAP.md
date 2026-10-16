# N02 Execution Roadmap

## Objective

Complete and independently audit the five user-selected N02 minimal-closure checks:

```text
100x100 scenario
-> C1-derived civilian initial allocation
-> local 2x2 perturbation
-> legal candidate actions
-> branch consequences and recomputed labels
-> world-model training and recovery
-> real G/G-WM PPO updates
-> development evaluation and resource settlement
-> independent review
-> public GitHub archive
```

Full paper experiments, additional scales, multiple seeds, and a confirmation set are future work. They are outside this archive's current scope and are not to be started as part of the current minimal-closure work.

## Current execution boundary

The frozen candidate is `ch2_disaster_relief_n02_minimal_closure_v1_100x100_bhook_20261016`. Sol passed the local synthetic Gate A review with 19 local tests. The bounded target diagnostic unit completed expected success, normal-failure, and guardian-kill cases, and the measured same-unit prior-cost receipt replay was accepted. Sol independently passed bounded Node B diagnostics and the measured receipt. No formal authorization, real consequence collection, WM training/restore, or PPO update has occurred. See `STATUS.md` and the de-identified review summaries for exact limits. The only active objective is to complete and independently review the five core checks in `ACCEPTANCE_MATRIX.md`.

## Roles and identity rules

- Luna prepares and repairs code, evidence, and release material.
- Sol performs read-only review and returns `PASS`, `REPAIR`, or `STOP`.
- The main coordinator decides whether a gate opens and controls archive branches and tags.
- Every formal release gets new manifests, hashes, request identity, attempt identity, and authorization binding.
- Never reuse a token, authorization, attempt, run directory, resource ledger, request, or old/incompatible checkpoint, dataset, or model. A newly trained Stage E checkpoint may pass to Stage F only through the reviewed identity chain.
- A synthetic handoff or test result must never be described as a real run.

## Stage 0: inventory and freeze

Historical v4/v5 packages served only as local development baselines. The current candidate identity and local source manifest are recorded separately in `HASH_PROVENANCE.md`. Candidate source remains outside this public preparation directory pending independent publication review.

Historical inventory artifacts remain part of the private development record. This public preparation archive exposes only de-identified identities and summaries.

## Stage A: local 100x100 repair and acceptance

Gate A is complete for the local synthetic boundary. Sol independently passed C1-derived public initial allocation, causal 2x2 perturbation, NOOP/non-target independent recomputation, and the local L1/WM/G-WM interface checks. The core suite recorded 19 passing tests. See `history/gate-a-review/SOL_GATE_A_REPAIR1_SUMMARY.md` for the de-identified evidence and provenance. This does not establish any real data collection, WM training/restore, or PPO update.

The local acceptance record includes the required map, allocation, spatial, candidate, independent-oracle, L1, and synthetic gradient checks. The exact reviewed outcome is summarized in `history/gate-a-review/SOL_GATE_A_REPAIR1_SUMMARY.md`; do not treat a future re-run or test count by itself as a replacement for independent review.

The original local package has static, synthetic, map-contract, C1, spatial, oracle, L1, manifest, and hash evidence. Sol's Gate A decision is `PASS`. Real PPO updates and real world-model training/recovery remain pending in C4, not local Gate A requirements.

## Stage B: server deployment and unauthenticated preflight

After Gate A passed, one bounded unauthorized diagnostic unit completed. It exercised expected success, controlled normal failure, and guardian kill. A measured same-unit prior-cost receipt replay was accepted by the package parser. Sol independently passed bounded Node B diagnostics and the measured receipt. This does not complete the full runtime witness or authorize formal execution.

The completed cases returned the expected success and failure statuses and the guardian killed the controlled case. Systemd recorded success, exit 0, and zero restarts. The prior-cost parser replay recorded 2.391625 seconds wall and 0.821315 seconds CPU for the same successful diagnostic unit; this excludes earlier failed units and transport/probe costs. No formal token, attempt, training run, checkpoint, or research output was created. See `history/server-diagnostics/SOL_B_DIAGNOSTIC_SUMMARY.md`.

Node B bounded diagnostics and receipt review passed. The next formal release must capture the full runtime in the actual worker and receive its own identity review before research starts.

## Stage C: fresh formal release and authorization binding

After Stage A and B pass, regenerate the manifest, hash bundle, request, and attempt from the reviewed package. Publish to a new read-only package location. Bind a one-time authorization to the release hashes, request, attempt, runtime identity, measured prior-cost receipt, scope, and budget. Verify all identities and issue one unique launch command. Sol reviews the complete identity chain before collection begins.

## Stage D: real consequence data collection

Use two training parent scenarios and one development parent scenario, three UAVs and one helicopter, 2x2 local perturbations, windows at 8, 16, 24, and 32 minutes, up to four candidates per window, a 30-minute or episode-end branch cap, and seed 8201.

For every window, try NOOP, the current action, and up to two legal local alternatives. Candidates must share a public prefix, snapshot, and exogenous-event identity and bind both a complete environment action and a stable candidate key. Record branch traces and labels for on-time transport, patrol/report completion, newly late orders, unmet demand, energy, reassignment, and global utility change. Stop collection if fewer than two legal candidates with different consequences exist; repair the scenario and create new identities.

Expected evidence: candidate table, branch trajectories, consequence labels, label recomputation and feasibility reports, collection ledger, and settlement. Sol checks replayability, candidate legality, label recomputation, unknown handling, leakage boundaries, and split integrity.

## Stage E: world-model training and recovery

Train on collected consequence data for one epoch with batch size 4, at most eight optimizer updates, CPU device, and seed 8201. Record target construction, losses, masks, and each update. Save a checkpoint with model, optimizer, seed, configuration, and data identity. Restore it in a new process and compare predictions on the same inputs.

Acceptance requires measured optimizer updates that match the ledger, a complete checkpoint, matching restore predictions, matching checkpoint hashes, and prediction/coverage metrics for every head. Do not reuse old world-model weights.

## Stage F: real G and G-WM PPO

Run one training round per group, two real training episodes per group, at most eight PPO updates per group, and the same development parent. Initialize actor parameters in pairs and keep episodes, rewards, and PPO settings matched. G uses the graph critic. G-WM uses a frozen world model with an auxiliary critic.

When this future minimum-closure stage is authorized, record logits, log probabilities, values, GAE, losses, auxiliary gradient norm, parameter changes, and checkpoint hashes. Both groups must complete real PPO updates; the auxiliary critic must have finite nonzero gradients and change its parameters; world-model parameters must not change; and the actor must not be directly modified by the world model. Local Gate A verified the synthetic L1/WM/G-GWM interface only; this does not establish a real update.

## Stage G: final independent review

Sol checks the 100x100 calculation path, Chapter 1 allocation, dynamic 2x2 perturbation, candidates and branch traces, label recomputation, world-model training and recovery, G/G-WM wiring and PPO updates, development evaluation, resource accounting, identities, privacy, and proposed GitHub contents. The result is `ENGINEERING_PASS`, `REPAIR_REQUIRED`, or `ENGINEERING_STOP`.

## Stage H: public archive

Freeze each accepted node, run the allowlist privacy checker, generate public-sanitized hashes, obtain Sol publication review, and then require explicit main-coordinator authorization before any repository mutation. Branches or tags are not implied by this roadmap. Never overwrite an earlier result. See `ARCHIVE_RULES.md`.

Proposed public layout after the relevant review gates pass:

```text
n02/source/  tests/  configs/  fixtures/  protocols/
releases/n02-minimal-closure-v1/
evidence/node-a-local-100x100/  node-b-server-preflight/  node-c-consequence-data/
evidence/node-d-world-model/  node-e-g-gwm/  node-f-independent-review/
reports/  history/prior-v5-failure/  history/gate-a-review/
```

## Future work only: full paper experiment (out of current scope)

Do not start this work under the current five-check authorization. It requires a separate future scope decision after the complete minimum engineering closure and independent review.

## Final deliverables

The minimum closure includes runnable 100x100 source, real consequence data, world-model checkpoint and restore receipt, G/G-WM training and evaluation, resource accounting, identities and hashes, Sol review, and a truthful engineering conclusion. Full paper experiments add the event-triggered implementation, scales, baselines, seeds, confirmation set, statistical report, figures, and tables.
