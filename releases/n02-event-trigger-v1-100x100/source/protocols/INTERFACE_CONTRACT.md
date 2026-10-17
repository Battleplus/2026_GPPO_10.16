# Event-trigger V1 implementation contract

This version extends the frozen N02 baseline without modifying its archived files. Data remain simulator generated. All policy/model inputs must come from public observations, with no future event tape or truth fields. Names below are shared APIs; implementers may add methods but coordinate signature changes.

## Environment and events (`event_environment.py`, `event_scenarios.py`, `event_trigger.py`)

- `build_event_scenarios() -> list[dict]`: exactly six validated 100x100 parent scenarios, four training and two development; each has `parent_id`, `split`, `condition`, six platforms (4 UAV/2 helicopter), twelve tasks and a deterministic tape. Seed variants are external to split identity.
- `EventReliefEnv(scenario)`: supports `reset()`, `public_observation()`, `step(full_environment_action)`, `episode_metrics()`, `export_trajectory()`, plus deterministic snapshot/restore by deepcopy. Step follows baseline five-tuple API. `full_environment_action` is a JSON dictionary containing explicit complete queue/dispatch operations and scope; NOOP is explicit. Underlying executable baseline action IDs may be included. No arbitrary candidate label may substitute for action execution.
- `generate_reconstruction_candidates(env, scope=None, max_candidates=16) -> list[dict]`: same public snapshot => same unique ordered catalog, NOOP and public C1 plus actual transfer/exchange/insertion/cross-platform alternatives. Each record includes `candidate_key`, `full_environment_action`, `candidate_scope`, `public_prefix_hash`, `snapshot_hash`, `event_tape_id`, `legal`, `infeasibility_reason`. Legal actions satisfy capability/stock/time/energy/communication constraints; expose rejected reasons separately. Keys bind full actions. Public generation cannot inspect truth or future tape. Snapshot hash/tape identity are provenance-only and excluded from model tensors.
- `repair_action(env, action) -> (action, receipt)` deterministic constraint repair based on public information, with invalid cases and postrepair legality recorded.
- Public observations extend baseline with `environment` nodes, `communication` links, public task progress/predecessors/cooperation and public platform health/load. Each public node carries only information available now.
- `TriggerEngine(config, threshold_manifest)`, `detect(previous_public, current_public, history=None, wm_summary=None) -> dict`, `decide(detection, time, mode='event') -> dict`. Logs contain all user-required fields and four severities plus state/degradation/margin/uncertainty; strong events bypass 4-minute cooldown.
- `identify_affected_scope(public_observation, detection) -> dict` contains task/platform IDs, local/global eligibility, connectivity and reasons. High level action mask enforces scope rules.
- `calibrate_threshold(training_observation_sequences, config) -> dict`: reject development input. Preregister q=.75 of positive training gamma, weights [.35,.30,.25,.10], delta_min=4; record raw scores/source parents/config hashes. Never silently replace measured threshold to achieve a result.

## Models (`event_models.py`)

- `TemporalGraphWorldModel`, public heterogeneous graph encoder + GRU over latest four public observations; takes public history and full candidate actions. Predict next state, progress, delay, energy, failure, communication risk, constraint risk and utility with explicit valid masks.
- `train_ensemble(samples, output_dir, config) -> dict`: samples carry public history/candidate catalog/independent targets; only train split fits normalization. Three seeds 8201/8202/8203, 40 epochs, batch 8, save model/optimizer/config/data identity/RNG. New-process restore is orchestrated by runner.
- `load_ensemble(checkpoint_paths)`, `predict_ensemble(ensemble, history, candidates) -> dict`: output per-candidate means/variance with finite values, no truth access. Frozen in PPO.

## Policies (`event_policy.py`)

- Hierarchical graph PPO with high-level NOOP/LOCAL_REPAIR/GLOBAL_REPLAN masked by trigger/scope and low-level categorical over actual catalog. Same actor initialization for every variant per seed. WM enters auxiliary critic only, never actor logits. Discrete sampled full action must actually execute; no heuristic replacing policy output.
- `train_four_variants(scenarios, ensemble, threshold_manifest, output_dir, config) -> dict` trains all four named methods and evaluates both dev parents for all three policy seeds. Same update budget per method, event tapes, seed, parent order, reward and candidate generator. Paired fixed-snapshot evaluation must additionally use byte-identical candidate catalogs for all methods; closed-loop paths may diverge and their hashes must be reported honestly.
- Record high/low logits, log probabilities, advantages/GAE, returns, losses, gradients, parameter digests, candidate identity and repair receipts. Frozen WM hash before/after; changing auxiliary critic; actor invariance under changed WM outputs. Checkpoints must load in a new process.

## Runner (`event_runner.py`) and evidence

CLI stages `m0`, `m1`, `m2`, `m3`, `m4`, `all`, `restore-check` with `--output` and `--config`. It must persist named user deliverables, call independent consequence oracle before training, stop on <80% distinct legal-window coverage and preserve first failure. M1 never trains PPO. M2 branches use deepcopy of exact same snapshot and same event tape, up to 30 minutes, windows 8/16/24/32.

Config defaults: horizon=60; collection branch_horizon=30; max_candidates=16; WM epochs=40/batch=8/seeds=[8201,8202,8203]. PPO: 4 rounds, each four real training episodes (one per train parent), four PPO epochs, minibatch32, equal explicit update cap128 per seed/method. Derive actual updates identically; do not inflate losses without optimizer.step. CPU threads1, CUDA hidden; reuse verified Python/Torch/NumPy runtime with fresh identity and ledger.

Root coordinator owns `protocols/`, `configs/`, `tools/`, plan/tracker, deployment, final integration and publishing. Other file ownership is assigned explicitly. Existing baseline files are read-only for workers unless coordinated.
