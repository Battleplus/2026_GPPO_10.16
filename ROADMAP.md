# N02 Execution Roadmap

## Objective

Complete and independently audit the N02 disaster-relief reallocation loop:

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

After the minimum engineering closure passes, run the full event-triggered reconstruction study, baselines, multiple scales, three seeds, and an independent confirmation set.

## Roles and identity rules

- Luna prepares and repairs code, evidence, and release material.
- Sol performs read-only review and returns `PASS`, `REPAIR`, or `STOP`.
- The main coordinator decides whether a gate opens and controls archive branches and tags.
- Every formal release gets new manifests, hashes, request identity, attempt identity, and authorization binding.
- Never reuse a token, authorization, attempt, run directory, resource ledger, request, or old/incompatible checkpoint, dataset, or model. A newly trained Stage E checkpoint may pass to Stage F only through the reviewed identity chain.
- A synthetic handoff or test result must never be described as a real run.

## Stage 0: inventory and freeze

Use the v5 package only as the authorization-entry baseline and the v4 100x100 package as the algorithm baseline. Record reuse and non-reuse decisions, source manifests, and SHA-256 values. Exclude bytecode, unrelated historical datasets and checkpoints, old identities, credentials, and private server material. Sol confirms the baseline boundary before the candidate advances.

Expected evidence: `REUSE_INVENTORY.md`, `NON_REUSABLE_ASSETS.md`, `BASELINE_SOURCE_MANIFEST.json`, and `BASELINE_HASHES.json`.

## Stage A: local 100x100 repair and acceptance

Audit Python, JSON, fixtures, and registered data. Enforce `rows=100`, `cols=100`, `grid_cells=10000`, and `grid_contract=relief-grid-100x100-v1`. Check coordinates, distances, summaries, platforms, tasks, public prefixes, graph nodes, world-model inputs, and checkpoint metadata. The user approved adapting the existing public-information C1 allocator as a civilian initial-assignment generator. Record its algorithm source, inputs, seed, version, output, and hashes; verify valid allocations, input sensitivity, and hidden-future invariance. Do not call this the original Chapter 1 MILP. Validate real local 2x2 spatial state change, legal candidate/full-action/key binding, recomputable labels, and the G-WM interface.

Run the local suite with `python -B -m pytest -q package/tests`, plus AST, JSON, registry, dimension, bytecode, manifest, and hash checks. Acceptance requires the map contract to be exercised in calculations; invalid dimensions to be rejected; the C1-derived initial allocation to run; spatial perturbations and at least two legal, consequentially different candidates to be replayable; and labels to be recomputable against an independent state/event oracle. Include a NOOP reference and a synthetic case with a consequence for a non-target third order. Ensure training, recovery, and evaluation construct the actual L1 graph policy and prove its message-passing path runs. Validate the auxiliary critic and frozen world-model gradient contracts synthetically. A passing local test count alone is insufficient.

Expected evidence: static report, synthetic acceptance, map-contract report, C1 provenance and allocation output, spatial perturbation and consequence probes, L1 path probe, local test output, source manifest, SHA256 list, and candidate request/attempt identities. Sol independently decides whether Stage A passes. Pending prior-cost measurement, real PPO updates, and real world-model training/recovery belong to later gates and are not prerequisites for local Stage A.

## Stage B: server deployment and unauthenticated preflight

Only after Stage A passes, deploy to a new staging location and verify package hashes and the target runtime. The expected runtime is Python 3.11.16, PyTorch 2.7.0+cu128, NumPy 1.26.0, CPU affinity `[0]`, one Torch thread, empty `CUDA_VISIBLE_DEVICES`, and an uninitialized GPU. Execute the separate CPU kernel witness in `protocols/CPU_KERNEL_WITNESS.md` and capture a measured runtime receipt.

Run unauthenticated preflight, engineering smoke, controlled failure, and guardian-kill checks. Confirm StageServer, BudgetLedger, systemd, memory, disk, thread limits, timeout, and exit state. Unauthenticated preflight must not create a formal token, attempt, training run, formal SQLite database, checkpoint, or model output. Engineering smoke may create explicitly diagnostic-only SQLite data or test artifacts; each must have separate diagnostic identity, be charged to the resource ledger, and never be presented as formal research data. Produce and validate a measured `PRIOR_RESOURCE_COST.json` before any formal run. An import-only check is not a runtime pass. No compute-ledger evidence is currently available; an independent agent must perform and record these measurements before declaring the environment ready.

Expected evidence: preflight report, runtime identity, smoke report, resource ledger, prior-cost receipt, deployment receipt, and service receipts. Sol reviews server identity and resource gates. The current runtime witness state is `UNMEASURED`.

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

Record logits, log probabilities, values, GAE, losses, auxiliary gradient norm, parameter changes, and checkpoint hashes. Both groups must complete real PPO updates; the auxiliary critic must have finite nonzero gradients and change its parameters; world-model parameters must not change; and the actor must not be directly modified by the world model. The actual G/G-WM L0MLP path is currently a repair item and must pass this gate before any result is claimed.

## Stage G: final independent review

Sol checks the 100x100 calculation path, Chapter 1 allocation, dynamic 2x2 perturbation, candidates and branch traces, label recomputation, world-model training and recovery, G/G-WM wiring and PPO updates, development evaluation, resource accounting, identities, privacy, and proposed GitHub contents. The result is `ENGINEERING_PASS`, `REPAIR_REQUIRED`, or `ENGINEERING_STOP`.

## Stage H: public archive

Freeze each accepted node, run the allowlist privacy checker, generate public-sanitized hashes, obtain Sol review, and then let the main coordinator authorize the matching archive branch and tag. Never overwrite an earlier result. A failed node may be preserved in a reviewed failure archive without a success tag. See `ARCHIVE_RULES.md`.

Proposed public layout after the relevant review gates pass:

```text
n02/source/  tests/  configs/  fixtures/  protocols/
releases/n02-minimal-closure-v1/
evidence/node-a-local-100x100/  node-b-server-preflight/  node-c-consequence-data/
evidence/node-d-world-model/  node-e-g-gwm/  node-f-independent-review/
reports/  history/prior-v5-failure/  history/gate-a-review/
```

## Stage I: full paper experiment

Begin only after `ENGINEERING_PASS`. Implement and compare event-triggered local/global reconstruction, minimum trigger interval, strong-event triggers, affected-task/platform identification, constraint repair, communication disturbance, periodic reallocation, auction, greedy, graph GPPO, and G-WM. Evaluate 2x2, 4x4, and 8x8 scales with three seeds and an independent confirmation set; produce statistical analysis, paper tables/figures, and method audit.

## Final deliverables

The minimum closure includes runnable 100x100 source, real consequence data, world-model checkpoint and restore receipt, G/G-WM training and evaluation, resource accounting, identities and hashes, Sol review, and a truthful engineering conclusion. Full paper experiments add the event-triggered implementation, scales, baselines, seeds, confirmation set, statistical report, figures, and tables.
