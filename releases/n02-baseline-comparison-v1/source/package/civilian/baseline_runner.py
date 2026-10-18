"""Paired nine-method baseline training and closed-loop evaluation runner."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

try:
    from . import event_runner
    from .baseline_metrics import summarize_episode
except ImportError:
    import event_runner
    from baseline_metrics import summarize_episode


RULE_METHODS = ("Greedy", "Auction", "CBBA-lite")
LEARNING_METHODS = ("PPO", "GPPO", "Periodic-GPPO", "Event-GPPO", "Event-GPPO-WM", "Periodic-GPPO-WM")
METHODS = RULE_METHODS + LEARNING_METHODS
PERIODIC = {"Periodic-GPPO", "Periodic-GPPO-WM"}
EVENT = {"Event-GPPO", "Event-GPPO-WM"}
WM_METHODS = {"Event-GPPO-WM", "Periodic-GPPO-WM"}
SCHEMA = "n02-baseline-run/1"


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _json_file_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _parameter_devices(model: Any) -> list[str]:
    return sorted({str(parameter.device) for parameter in model.parameters()})


def _world_model_state_audit(ensemble: Any) -> dict:
    try:
        from .baseline_checkpoints import state_digest
    except ImportError:
        from baseline_checkpoints import state_digest
    rows = []
    for index, model in enumerate(ensemble.models):
        parameters = list(model.parameters())
        rows.append({
            "member_index": index,
            "state_digest": state_digest(model.state_dict()),
            "parameter_count": sum(parameter.numel() for parameter in parameters),
            "requires_grad_false": all(not parameter.requires_grad for parameter in parameters),
            "gradients_none": all(parameter.grad is None for parameter in parameters),
        })
    return {"members": rows}


def _assert_optimizer_excludes_world_model(trainer: Any, ensemble: Any) -> dict:
    world_model_ids = {id(parameter) for model in ensemble.models for parameter in model.parameters()}
    optimizer_ids = {id(parameter) for group in trainer.optimizer.param_groups for parameter in group["params"]}
    overlap = len(world_model_ids & optimizer_ids)
    if overlap:
        raise ValueError("BASELINE_WORLD_MODEL_IN_POLICY_OPTIMIZER")
    return {
        "method_id": trainer.method_id,
        "seed": trainer.seed,
        "world_model_parameter_count": len(world_model_ids),
        "policy_optimizer_parameter_count": len(optimizer_ids),
        "overlap_parameter_count": overlap,
        "world_model_excluded": True,
    }


def _perturb_wm_predictions(predictions: dict) -> dict:
    perturbed = copy.deepcopy(predictions)
    for collection, offset in (("means", 0.25), ("variances", 0.125)):
        for head, rows in perturbed[collection].items():
            perturbed[collection][head] = [
                [float(value) + offset for value in row] if isinstance(row, (list, tuple))
                else float(row) + offset
                for row in rows
            ]
    return perturbed


def _audit_wm_critic_boundary(policy: Any, probe: dict, *, method: str, seed: int) -> dict:
    if not method.endswith("-WM") or not isinstance(probe.get("wm_critic"), dict):
        raise ValueError("BASELINE_WM_CRITIC_AUDIT_PROBE_REQUIRED")
    try:
        import torch
        from .event_policy import _world_model_critic_features
    except ImportError:
        import torch
        from event_policy import _world_model_critic_features
    observation, candidates = probe["observation"], probe["candidates"]
    original = probe["wm_critic"]
    perturbed = _perturb_wm_predictions(original)
    with torch.no_grad():
        actor_logits_original = policy.actor_logits(observation, candidates).detach()
        total_original, base_original, auxiliary_original = policy.critic_values(observation, original)
        actor_logits_perturbed = policy.actor_logits(observation, candidates).detach()
        total_perturbed, base_perturbed, auxiliary_perturbed = policy.critic_values(observation, perturbed)
        features = _world_model_critic_features(original, device=next(policy.parameters()).device)
    actor_invariant = torch.equal(actor_logits_original, actor_logits_perturbed)
    critic_sensitive = not torch.isclose(auxiliary_original, auxiliary_perturbed, rtol=1e-7, atol=1e-9)
    if not actor_invariant or not critic_sensitive or float(features.norm().cpu()) <= 0:
        raise ValueError("BASELINE_WM_CRITIC_BOUNDARY_AUDIT_FAILED")
    logits_bytes = actor_logits_original.cpu().contiguous().numpy().tobytes()
    return {
        "method_id": method, "seed": seed,
        "fixed_observation_sha256": _sha(observation),
        "fixed_candidates_sha256": _sha(candidates),
        "actual_wm_critic_sha256": _sha(original),
        "perturbed_wm_critic_sha256": _sha(perturbed),
        "actual_wm_critic_feature_l2": float(features.norm().cpu()),
        "actor_logits_invariant": actor_invariant,
        "actor_logits_sha256": hashlib.sha256(logits_bytes).hexdigest(),
        "base_value_original": float(base_original.cpu()),
        "base_value_perturbed": float(base_perturbed.cpu()),
        "auxiliary_value_original": float(auxiliary_original.cpu()),
        "auxiliary_value_perturbed": float(auxiliary_perturbed.cpu()),
        "total_value_original": float(total_original.cpu()),
        "total_value_perturbed": float(total_perturbed.cpu()),
        "auxiliary_critic_sensitive_to_wm_features": critic_sensitive,
        "rng_draws": 0,
    }


def _finalize_world_model_freeze_audit(start: dict, ensemble: Any, optimizer_checks: list[dict]) -> dict:
    end = _world_model_state_audit(ensemble)
    unchanged = [row["state_digest"] for row in start["members"]] == [row["state_digest"] for row in end["members"]]
    frozen = all(row["requires_grad_false"] for row in start["members"] + end["members"])
    no_gradients = all(row["gradients_none"] for row in start["members"] + end["members"])
    excluded = bool(optimizer_checks) and all(row["world_model_excluded"] and row["overlap_parameter_count"] == 0 for row in optimizer_checks)
    audit = {
        "schema": "n02-world-model-freeze-audit/1",
        "status": "complete" if unchanged and frozen and no_gradients and excluded else "failed",
        "phase_start": start,
        "phase_end": end,
        "state_unchanged": unchanged,
        "requires_grad_false": frozen,
        "all_gradients_none": no_gradients,
        "optimizer_exclusion_checks": optimizer_checks,
        "optimizer_excludes_world_model": excluded,
    }
    if audit["status"] != "complete":
        raise ValueError("BASELINE_WORLD_MODEL_FREEZE_AUDIT_FAILED")
    return audit


def _write_gpu_execution_receipt(output: Path, phase: str, config: dict, result: dict) -> dict:
    device = str(config.get("runtime", {}).get("device", "cpu"))
    receipt = {
        "schema": "n02-gpu-execution-receipt/1",
        "status": "complete" if device.startswith("cuda:") else "cpu_smoke",
        "phase": phase,
        "device": device,
        "systemd_invocation_id": os.environ.get("INVOCATION_ID", ""),
        "peak_memory_allocated_bytes": 0,
    }
    try:
        import torch
        if device.startswith("cuda:") and torch.cuda.is_available():
            torch.cuda.synchronize(torch.device(device))
            receipt["peak_memory_allocated_bytes"] = int(torch.cuda.max_memory_allocated(torch.device(device)))
        else:
            receipt["peak_memory_allocated_bytes"] = int(result.get("peak_memory_allocated_bytes", 0))
    except ImportError:
        pass
    if phase == "freeze-wm":
        receipt.update({
            "world_model_parameter_devices": result.get("world_model_parameter_devices", []),
            "world_model_optimizer_state_devices": result.get("world_model_optimizer_state_devices", []),
            "training_forward_calls": int(result.get("training_forward_calls", 0)),
            "optimizer_steps": int(result.get("optimizer_steps", 0)),
        })
    elif phase == "train":
        receipt.update({
            "policy_parameter_devices": result.get("policy_parameter_devices", []),
            "policy_optimizer_state_devices": result.get("policy_optimizer_state_devices", []),
            "policy_forward_calls": int(result.get("policy_forward_calls", 0)),
            "optimizer_steps": int(result.get("optimizer_steps", 0)),
            "world_model_freeze_audit_sha256": result.get("world_model_freeze_audit_sha256"),
            "actor_initialization_audit_sha256": result.get("actor_initialization_audit_sha256"),
            "wm_critic_boundary_audit_sha256": result.get("wm_critic_boundary_audit_sha256"),
        })
    else:
        receipt.update({
            "world_model_parameter_devices": result.get("world_model_parameter_devices", []),
            "policy_parameter_devices": result.get("policy_parameter_devices", []),
            "inference_forward_calls": int(result.get("inference_forward_calls", 0)),
            "optimizer_steps": 0,
        })
    _write_json(output / "GPU_EXECUTION_RECEIPT.json", receipt)
    return receipt


def _write_json(path: Path, value: Any) -> None:
    event_runner._write_json(path, value)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    event_runner._write_jsonl(path, rows)


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def load_profile(profile: str) -> tuple[dict, Path, str]:
    if profile not in {"pilot", "formal"}:
        raise ValueError("BASELINE_UNKNOWN_PROFILE")
    path = Path(__file__).resolve().parents[2] / "configs" / f"BASELINE_{profile.upper()}_CONFIG.json"
    raw = path.read_bytes()
    config = json.loads(raw)
    if config.get("profile") != profile:
        raise ValueError("BASELINE_PROFILE_CONFIG_MISMATCH")
    if config.get("methods") != list(METHODS):
        raise ValueError("BASELINE_METHOD_SET_MISMATCH")
    return config, path, hashlib.sha256(raw).hexdigest()


def _modules():
    EventReliefEnv, generate, repair, identify, build, validate, TriggerEngine, _ = event_runner._modules()
    try:
        from .baseline_policies import select_rule
        from .baseline_learning import make_trainer
        from .baseline_checkpoints import restore_trainer
        from .event_models import load_ensemble, predict_ensemble
    except ImportError:
        from baseline_policies import select_rule
        from baseline_learning import make_trainer
        from baseline_checkpoints import restore_trainer
        from event_models import load_ensemble, predict_ensemble
    return EventReliefEnv, generate, repair, identify, TriggerEngine, select_rule, make_trainer, restore_trainer, load_ensemble, predict_ensemble


def _load_world_model(world_model_dir: Path, device: str, expected_profile: str):
    _, _, _, _, _, _, _, _, load_ensemble, _ = _modules()
    manifest_path = world_model_dir / "WORLD_MODEL_MANIFEST.json"
    if not manifest_path.is_file():
        raise ValueError("BASELINE_WORLD_MODEL_MANIFEST_REQUIRED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("profile") != expected_profile:
        raise ValueError("BASELINE_WORLD_MODEL_NOT_FROZEN")
    checkpoints = [world_model_dir / Path(path) for path in manifest.get("checkpoint_paths", [])]
    hashes = manifest.get("checkpoint_sha256", {})
    if len(checkpoints) != 3 or any(not path.is_file() for path in checkpoints):
        raise ValueError("BASELINE_WORLD_MODEL_CHECKPOINT_SET")
    for path in checkpoints:
        relative = path.relative_to(world_model_dir).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes.get(relative):
            raise ValueError("BASELINE_WORLD_MODEL_CHECKPOINT_HASH")
    if not isinstance(manifest.get("strict_restore_receipt"), dict) or manifest["strict_restore_receipt"].get("status") != "complete":
        raise ValueError("BASELINE_WORLD_MODEL_STRICT_RESTORE_REQUIRED")
    if _json_file_sha(manifest.get("training_receipt")) != manifest.get("training_receipt_sha256"):
        raise ValueError("BASELINE_WORLD_MODEL_TRAINING_RECEIPT_HASH")
    ensemble = load_ensemble(checkpoints, device=device)
    if ensemble.ensemble_hash != manifest.get("ensemble_hash"):
        raise ValueError("BASELINE_WORLD_MODEL_HASH_MISMATCH")
    return ensemble, manifest


def _r8_binding(root: Path, config: dict | None = None) -> dict:
    configured = ((root / config["data_reuse"]["gate1_evidence"]) if config else
                  root / "evidence" / "gate1-cpu-m0-m2-20261018-r8")
    reuse_candidates = [configured, root / "data" / "gate1-r8"]
    reuse = next((path for path in reuse_candidates if (path / "M2_MODEL_SAMPLES.jsonl").is_file()), reuse_candidates[0])
    expected = "00c9631e9265bd72254a846d34e1ea997fb46f777cb9adb0d9fab45dbc197def"
    manifest_candidates = [reuse / "RUN_IDENTITY.json", reuse / "ATTEMPT.json"]
    manifest = next((path for path in manifest_candidates if path.is_file()), None)
    if manifest is None:
        raise ValueError("BASELINE_R8_SOURCE_MANIFEST_MISSING")
    identity = event_runner._read_json(manifest)
    if identity.get("manifest_sha256") != expected:
        raise ValueError("BASELINE_R8_GATE1_MANIFEST_HASH_MISMATCH")
    train_path = reuse / "M2_MODEL_SAMPLES.jsonl"
    dev_path = reuse / "M2_DEVELOPMENT_MODEL_SAMPLES.jsonl"
    threshold_path = reuse / "THRESHOLD_MANIFEST.json"
    if any(not path.is_file() for path in (train_path, dev_path, threshold_path)):
        raise ValueError("BASELINE_R8_REUSE_INPUT_MISSING")
    train = event_runner._read_jsonl(train_path)
    dev = event_runner._read_jsonl(dev_path)
    threshold = event_runner._read_json(threshold_path)
    if len(train) != 16 or {row.get("split") for row in train} != {"train"}:
        raise ValueError("BASELINE_R8_TRAIN_SAMPLE_SET")
    if len(dev) != 8 or {row.get("split") for row in dev} != {"development"}:
        raise ValueError("BASELINE_R8_DEVELOPMENT_SAMPLE_SET")
    if threshold.get("source_split") != "train" or threshold.get("frozen_before_development_evaluation") is not True:
        raise ValueError("BASELINE_R8_THRESHOLD_PROVENANCE")
    return {
        "relative_evidence_path": reuse.relative_to(root).as_posix(),
        "gate1_freeze_manifest_sha256": expected,
        "gate1_manifest_binding_verified": True,
        "run_identity_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "training_samples_sha256": hashlib.sha256(train_path.read_bytes()).hexdigest(),
        "development_samples_sha256": hashlib.sha256(dev_path.read_bytes()).hexdigest(),
        "threshold_sha256": hashlib.sha256(threshold_path.read_bytes()).hexdigest(),
        "training_samples": len(train), "development_samples": len(dev),
        "threshold_source_split": threshold["source_split"],
        "threshold_value": float(threshold["threshold"]),
    }


def _freeze_world_model(profile: str, output: Path, root: Path, config: dict) -> dict:
    """Train a fresh profile-specific ensemble exclusively from accepted r8 data."""
    from .event_models import train_ensemble, load_ensemble
    from .baseline_checkpoints import verify_wm_checkpoint_resume

    binding = _r8_binding(root, config)
    source = root / binding["relative_evidence_path"]
    samples = event_runner._read_jsonl(source / "M2_MODEL_SAMPLES.jsonl")
    model_dir = output / "WORLD_MODEL"
    training = train_ensemble(samples, model_dir, {
        **config["world_model"], "seeds": [8201, 8202, 8203], "epochs": 40,
        "batch_size": 8, "device": config.get("runtime", {}).get("device", "cuda:0"),
    })
    if training.get("status") != "complete" or len(training.get("checkpoint_paths", [])) != 3:
        raise ValueError("BASELINE_WORLD_MODEL_TRAINING_INCOMPLETE")
    ensemble = load_ensemble(training["checkpoint_paths"], device=config.get("runtime", {}).get("device", "cuda:0"))
    strict_restore = verify_wm_checkpoint_resume(
        training["checkpoint_paths"], expected_data_identity=training["data_identity"],
        fixed_sample={"history": samples[0]["history"], "candidates": samples[0]["candidates"]},
        device=config.get("runtime", {}).get("device", "cuda:0"))
    relative_checkpoints = [Path(path).resolve().relative_to(output.resolve()).as_posix() for path in training["checkpoint_paths"]]
    training_receipt = copy.deepcopy(training)
    training_receipt["checkpoint_paths"] = relative_checkpoints
    for record, relative in zip(training_receipt.get("checkpoints", []), relative_checkpoints):
        record["checkpoint_path"] = relative
    data_hashes = {
        "data/gate1-r8/M2_MODEL_SAMPLES.jsonl": binding["training_samples_sha256"],
        "data/gate1-r8/M2_DEVELOPMENT_MODEL_SAMPLES.jsonl": binding["development_samples_sha256"],
        "data/gate1-r8/THRESHOLD_MANIFEST.json": binding["threshold_sha256"],
    }
    checkpoint_hashes = {path: hashlib.sha256((output / path).read_bytes()).hexdigest() for path in relative_checkpoints}
    manifest = {
        "schema": "n02-baseline-world-model/1", "status": "complete", "profile": profile,
        "data_binding": binding, "dataset_sha256": data_hashes,
        "checkpoint_paths": relative_checkpoints, "checkpoint_sha256": checkpoint_hashes,
        "ensemble_hash": ensemble.ensemble_hash, "training_receipt": training_receipt,
        "training_receipt_sha256": _json_file_sha(training_receipt),
        "strict_restore_receipt": strict_restore,
        "training_forward_calls": int(training.get("training_forward_calls", 0)),
        "optimizer_steps": sum(int(row.get("optimizer_updates", 0)) for row in training.get("checkpoints", [])),
        "world_model_parameter_devices": sorted({device for row in training.get("checkpoints", [])
                                                   for device in row.get("model_parameter_devices", [])}),
        "world_model_optimizer_state_devices": sorted({device for row in training.get("checkpoints", [])
                                                         for device in row.get("optimizer_state_devices", [])}),
    }
    _write_json(output / "WORLD_MODEL_MANIFEST.json", manifest)
    return manifest


def _scope_and_clock(env: Any, engine: Any, observation: dict, previous: dict,
                     history: list[dict], method_id: str, time_index: int) -> tuple[dict, dict, bool]:
    detection = engine.detect(previous, observation, history=history[-4:])
    trigger_decision = engine.decide(detection, time_index, mode="event")
    affected = event_runner._modules()[3](observation, detection)
    feasible_raw = env.current_assignment_feasible()
    feasible = feasible_raw.get("feasible") if isinstance(feasible_raw, dict) else bool(feasible_raw)
    reason = "current_assignment_infeasible" if not feasible else "affected_scope"
    affected = copy.deepcopy(affected)
    affected["current_assignment_feasible"] = bool(feasible)
    affected["feasibility_reason"] = reason
    if not affected.get("affected_task_ids") and not affected.get("affected_platform_ids"):
        affected.update({"scope": "NOOP", "local_eligible": False, "global_eligible": False,
                         "global_required": False, "reasons": list(affected.get("reasons", [])) + ["empty_impact_domain"]})
    elif not feasible:
        affected.update({"scope": "GLOBAL_REPLAN", "local_eligible": False, "global_eligible": True,
                         "global_required": True, "reasons": list(affected.get("reasons", [])) + ["current_assignment_infeasible"]})
    elif affected.get("global_required"):
        affected.update({"scope": "GLOBAL_REPLAN", "local_eligible": False, "global_eligible": True})
    elif affected.get("local_eligible") or affected.get("affected_platform_ids"):
        affected.update({"scope": "LOCAL_REPAIR", "local_eligible": True, "global_eligible": False,
                         "global_required": False})
    else:
        affected.update({"scope": "NOOP", "local_eligible": False, "global_eligible": False, "global_required": False})

    if method_id in EVENT:
        planned = bool(trigger_decision.get("triggered"))
    elif method_id in PERIODIC:
        planned = time_index % 4 == 0
    else:
        planned = True
    scope = {"detection": detection, "trigger_decision": trigger_decision, "affected": affected,
             "current_assignment_feasible": feasible, "feasibility_reason": reason}
    return detection, scope, planned


def _catalog(env: Any, generate: Any, observation: dict, affected: dict, cap: int) -> tuple[list[dict], list[bool]]:
    if not affected.get("affected_task_ids") and not affected.get("affected_platform_ids"):
        candidates = generate(env, scope="NOOP", max_candidates=cap)
    else:
        candidates = generate(env, scope=affected, max_candidates=cap)
    noop = event_runner._noop_record(candidates)
    if len(candidates) > cap:
        raise ValueError("BASELINE_CANDIDATE_CAP")
    mask = []
    for row in candidates:
        action = row.get("full_environment_action", {})
        action_scope = str(action.get("scope", "NOOP"))
        eligible = bool(row.get("legal"))
        if action.get("noop") is not True:
            eligible = eligible and bool(affected.get("affected_task_ids") or affected.get("affected_platform_ids"))
            if action_scope == "GLOBAL_REPLAN":
                eligible = eligible and bool(affected.get("global_required") and affected.get("global_eligible"))
            elif action_scope == "LOCAL_REPAIR":
                eligible = eligible and bool(affected.get("local_eligible") and not affected.get("global_required"))
            else:
                eligible = False
        mask.append(eligible)
    if not any(mask[index] and candidates[index]["candidate_key"] == noop["candidate_key"] for index in range(len(candidates))):
        raise ValueError("BASELINE_LEGAL_NOOP_REQUIRED")
    return candidates, mask


def _clock_config(config: dict) -> dict:
    value = copy.deepcopy(config)
    value["trigger"] = {
        "weights": [0.35, 0.30, 0.25, 0.10], "quantile": 0.75,
        "delta_min": 4, "history_length": 4, "warmup_steps": 4,
        "persistence_steps": 2, "hysteresis_margin": 0.05,
    }
    return value


def _initial_task_rows(observation: dict) -> list[dict]:
    return [copy.deepcopy(row) for row in observation.get("tasks", [])]


def _environment_root_tasks(env: Any) -> list[dict]:
    return copy.deepcopy(env._raw_truth()["tasks"])


def _action_id(method: str, parent: str, seed: int, tick: int) -> str:
    return f"{method}:{parent}:{seed}:{tick}"


def _operation_queue_order_changed(receipt: dict) -> bool:
    operation = receipt.get("operation", {})
    platform = operation.get("to_platform")
    if operation.get("op") != "insert" or operation.get("from_platform") != platform:
        return False
    before = receipt.get("before_queues", {})
    after = receipt.get("after_queues", {})
    return list(before.get(platform, [])) != list(after.get(platform, []))


def _raw_audit_snapshot(env: Any) -> dict:
    base = env._base
    specs = env._task_specs
    return {
        "leaf_tasks": [copy.deepcopy(base._tasks[key]) for key in sorted(base._tasks)],
        "leaf_task_specs": [copy.deepcopy(specs[key]) for key in sorted(specs)],
        "root_task_specs": [copy.deepcopy(env._original_task_specs[key]) for key in sorted(env._original_task_specs)],
        "split_manifests": [copy.deepcopy(env._split_manifests[key]) for key in sorted(env._split_manifests)],
        "root_mapping": {key: str(specs[key].get("parent_task_id", key)) for key in sorted(specs)},
        "leaf_platforms": [copy.deepcopy(base._platforms[key]) for key in sorted(base._platforms)],
        "platform_specs": [copy.deepcopy(base._platform_spec[key]) for key in sorted(base._platform_spec)],
        "queues": copy.deepcopy(env._queues), "time": int(env.time),
    }


def _step_receipt(*, method: str, parent: dict, seed: int, tick: int, before: dict,
                  after: dict, detection: dict, scope: dict, planned: bool, catalog: list | None,
                  mask: list | None, selected: dict, selected_index: int | None, repair: dict, reward: float, info: dict,
                  planning_latency: float, response: float, protocol_messages: int = 0,
                  policy_receipt: dict | None = None, action_id: str, env: Any) -> dict:
    action = copy.deepcopy(info.get("full_environment_action", selected.get("full_environment_action", {})))
    raw_events = copy.deepcopy(info.get("raw_events", []))
    selected_receipt = copy.deepcopy(selected)
    selected_receipt["candidate_index"] = selected_index
    if catalog is not None and selected_index is not None:
        selected_receipt["candidate_key"] = catalog[selected_index].get("candidate_key")
    return {
        "schema": "baseline-action-receipt/1", "method_id": method, "parent_id": parent["parent_id"],
        "split": parent["split"], "event_tape_id": parent.get("event_tape_id"), "seed": seed,
        "time": tick, "action_id": action_id, "observation_before": before, "observation_after": after,
        "detection": copy.deepcopy(detection), "affected_scope": copy.deepcopy(scope["affected"]),
        "scope_feasibility": {"feasible": scope["current_assignment_feasible"], "reason": scope["feasibility_reason"]},
        "decision_clock": {"planned": planned, "explicit_noop": not planned},
        "candidate_catalog": copy.deepcopy(catalog) if catalog is not None else None,
        "candidate_catalog_sha256": _sha(catalog) if catalog is not None else None,
        "candidate_mask": copy.deepcopy(mask), "selected_candidate": selected_receipt,
        "full_environment_action": action, "repair_receipt": copy.deepcopy(repair),
        "operation_receipts": copy.deepcopy(info.get("operation_receipts", [])),
        "communication_receipts": copy.deepcopy(info.get("communication_receipts", [])),
        "raw_events": raw_events, "queues_before": copy.deepcopy(before.get("queues", {})),
        "queues_after": copy.deepcopy(after.get("queues", {})),
        "owners_before": {str(row["id"]): row.get("assignee") for row in before.get("tasks", [])},
        "owners_after": {str(row["id"]): row.get("assignee") for row in after.get("tasks", [])},
        "raw_endpoint_tasks": copy.deepcopy(env._raw_truth().get("tasks", [])),
        "raw_endpoint_platforms": copy.deepcopy(env._raw_truth().get("platforms", [])),
        "raw_state_before": copy.deepcopy(info.get("raw_state_before", {})),
        "raw_state_after": _raw_audit_snapshot(env),
        "reward_formula": copy.deepcopy(info.get("reward_formula", {})),
        "reward_formula_sha256": _sha(info.get("reward_formula", {})),
        "command_effects": copy.deepcopy(info.get("command_effects", [])),
        "command_application_receipts": {
            "operation_receipts": copy.deepcopy(info.get("operation_receipts", [])),
            "communication_receipts": copy.deepcopy(info.get("communication_receipts", [])),
            "causal_change_events": [copy.deepcopy(row) for row in raw_events
                                      if row.get("type") in {"communication_delivered", "task_owner_change"} and
                                      row.get("originating_action_id")],
        },
        "reward": reward, "reward_terms": copy.deepcopy(info.get("reward_terms", {})),
        "reward_primitives": copy.deepcopy(info.get("reward_primitives", {})),
        "requested_nonnoop": bool(info.get("requested_reconstruction_count", 0)),
        "effective_reconstruction_count": int(info.get("effective_reconstruction_count", 0)),
        "reconstruction_size": int(info.get("reconstruction_size", 0)),
        "owner_change_count": int(info.get("task_owner_change_count", 0)),
        "queue_reorder_count": int(info.get("queue_reorder_count", 0)),
        "environment_action_delivery_message_count": sum(int(row.get("message_count", 1)) for row in raw_events if row.get("type") == "communication_tx"),
        "rule_protocol_message_count": int(protocol_messages),
        "planning_latency_seconds": planning_latency, "policy_response_seconds": response,
        "policy_receipt": copy.deepcopy(policy_receipt or {}),
        "constraint_violations": len(info.get("constraint_violations", [])),
    }


def _environment_task_endpoint(observation: dict) -> list[dict]:
    return copy.deepcopy(observation.get("tasks", []))


def rollout_episode(method_id: str, scenario: dict, seed: int, config: dict, *,
                    policy: Any = None, ensemble: Any = None, training: bool = False) -> tuple[list[dict], list[dict], dict]:
    EventReliefEnv, generate, repair_action, identify, TriggerEngine, select_rule, _, _, _, predict_ensemble = _modules()
    env = EventReliefEnv(scenario)
    observation = env.reset()
    initial_tasks = copy.deepcopy(env._raw_truth().get("tasks", []))
    initial_raw_state = _raw_audit_snapshot(env)
    previous = copy.deepcopy(observation)
    history = [copy.deepcopy(observation)]
    threshold_manifest = config.get("resolved_threshold")
    threshold_value = threshold_manifest.get("threshold") if isinstance(threshold_manifest, dict) else None
    if threshold_value is None:
        threshold_value = config.get("trigger", {}).get("threshold", config.get("threshold_value"))
    if threshold_value is None:
        raise ValueError("BASELINE_FROZEN_THRESHOLD_REQUIRED")
    trigger_config = _clock_config(config)
    if not isinstance(threshold_manifest, dict):
        threshold_manifest = {"threshold": float(threshold_value)}
    trigger_engine = TriggerEngine(trigger_config["trigger"], threshold_manifest)
    rows: list[dict] = []
    transitions: list[dict] = []
    pending_dispatch_origin: dict[tuple[str, str, int], str] = {}
    terminated = truncated = False
    tick = 0
    while not (terminated or truncated):
        tick = int(observation.get("time", env.time))
        detection, scope, planned = _scope_and_clock(env, trigger_engine, observation, previous, history, method_id, tick)
        candidates = None
        mask = None
        policy_response = 0.0
        planning_latency = 0.0
        protocol_messages = 0
        policy_receipt: dict = {}
        if planned:
            started = time.perf_counter()
            candidates, mask = _catalog(env, generate, observation, scope["affected"], int(config["environment"]["candidate_cap"]))
            catalog_hash = _sha(candidates)
            if method_id in RULE_METHODS:
                selected = select_rule(method_id.lower().replace("-", "_"), observation, candidates,
                                       {"candidate_mask": mask, "affected_scope": scope["affected"],
                                        "no_eligible_scope": not any(mask[i] and candidates[i].get("legal") for i in range(len(mask)) if not candidates[i].get("full_environment_action", {}).get("noop"))})
                protocol_messages = int(selected.get("rule_protocol_message_count", selected.get("communication_messages", 0)))
                policy_receipt = selected
                selected_index = int(selected["candidate_index"])
                chosen = candidates[selected_index]
                policy_response = time.perf_counter() - started
            else:
                call_started = time.perf_counter()
                wm_input = None
                if method_id in WM_METHODS and ensemble is not None and candidates:
                    prediction = predict_ensemble(ensemble, history[-4:], candidates)
                    wm_input = prediction
                action_record = policy.act(observation, candidates, mask, wm_critic=wm_input, deterministic=not training)
                if not training:
                    try:
                        import torch
                        if str(config.get("runtime", {}).get("device", "cpu")).startswith("cuda"):
                            torch.cuda.synchronize(torch.device(config["runtime"]["device"]))
                    except ImportError:
                        pass
                policy_response = time.perf_counter() - call_started
                selected_index = int(action_record["candidate_index"])
                chosen = candidates[selected_index]
                selected = chosen
                policy_receipt = {key: value for key, value in action_record.items() if key not in {"logits"}}
                if training:
                    value_row = policy.value(observation, wm_critic=wm_input)
                    transitions.append({
                        "observation": copy.deepcopy(observation), "candidates": copy.deepcopy(candidates),
                        "candidate_mask": copy.deepcopy(mask), "candidate_catalog_sha256": catalog_hash,
                        "action_index": selected_index, "old_log_probability": action_record["log_probability"],
                        "old_logits": [float(value) for value in action_record.get("logits", [])],
                        "old_value": action_record.get("value", value_row), "reward": 0.0,
                        "terminated": False, "truncated": False, "next_value": 0.0,
                        "actor_decision": True, "wm_critic": wm_input,
                    })
            planning_latency = time.perf_counter() - started
            if not mask[selected_index]:
                raise ValueError("BASELINE_POLICY_SELECTED_MASKED_CANDIDATE")
        else:
            candidates = None
            chosen = None
            selected = {"candidate_index": None, "candidate_key": None,
                        "full_environment_action": {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
                                                     "queue_operations": [], "dispatches": []}}
            if training and policy is not None:
                value_row = policy.value(observation, wm_critic=None)
                transitions.append({
                    "observation": copy.deepcopy(observation), "candidates": [], "candidate_mask": [],
                    "candidate_catalog_sha256": None, "action_index": 0,
                    "old_log_probability": 0.0, "old_value": value_row, "reward": 0.0,
                    "terminated": False, "truncated": False, "next_value": 0.0,
                    "actor_decision": False, "wm_critic": None,
                })
        action_input = copy.deepcopy(selected.get("full_environment_action", selected.get("selected_full_environment_action", {})))
        action, repair_receipt = repair_action(env, action_input)
        if repair_receipt.get("postrepair_legal") is not True:
            raise ValueError("BASELINE_SHARED_REPAIR_FAILED")
        if not planned and (action.get("noop") is not True or action.get("dispatches") or action.get("queue_operations")):
            raise ValueError("BASELINE_NONDECISION_TICK_MUST_NOOP")
        if planned and action != action_input:
            raise ValueError("BASELINE_RULE_OR_POLICY_ACTION_REQUIRES_SHARED_REPAIR")
        action_id = _action_id(method_id, str(scenario["parent_id"]), seed, tick)
        before = copy.deepcopy(observation)
        raw_before = _raw_audit_snapshot(env)
        next_observation, reward, terminated, truncated, info = env.step(action)
        info["raw_state_before"] = raw_before
        info["command_effects"] = []
        for command in info.get("communication_receipts", []):
            if not command.get("delivered"):
                key = (str(command.get("task_id", "")), str(command.get("target", "")), int(command.get("delivery_time", -1)))
                pending_dispatch_origin[key] = action_id
        raw_after = _raw_audit_snapshot(env)
        before_leaf = {str(row["id"]): row for row in raw_before["leaf_tasks"]}
        after_leaf = {str(row["id"]): row for row in raw_after["leaf_tasks"]}
        for command in info.get("communication_receipts", []):
            if not command.get("delivered") or command.get("reason") != "dispatch":
                continue
            task_id, platform_id = str(command.get("task_id", "")), str(command.get("target", ""))
            if not any(str(row.get("task_id", "")) == task_id and
                       str(row.get("platform_id", "")) == platform_id for row in action.get("dispatches", [])):
                continue
            owner_changed = before_leaf.get(task_id, {}).get("assignee") != after_leaf.get(task_id, {}).get("assignee")
            for event in info.get("raw_events", []):
                if event.get("type") == "task_owner_change" and str(event.get("task_id", "")) == task_id:
                    event["originating_action_id"] = action_id
            info["command_effects"].append({
                "originating_action_id": action_id, "delivered": True,
                "command_id": f"{action_id}:dispatch:{task_id}:{command.get('delivery_time', tick)}",
                "task_id": task_id, "platform_id": platform_id,
                "owner_changed": owner_changed, "queue_order_changed": False,
            })
        for event in info.get("raw_events", []):
            if event.get("type") != "communication_delivered":
                continue
            key = (str(event.get("task_id", "")), str(event.get("platform_id", "")), int(event.get("delivery_time", event.get("time", -1))))
            origin = pending_dispatch_origin.pop(key, None)
            if origin is None:
                continue
            event["originating_action_id"] = origin
            task_id = key[0]
            owner_changed = before_leaf.get(task_id, {}).get("assignee") != after_leaf.get(task_id, {}).get("assignee")
            info["command_effects"].append({
                "originating_action_id": origin, "delivered": True,
                "command_id": f"{origin}:delivery:{task_id}:{key[2]}",
                "task_id": task_id, "platform_id": key[1],
                "owner_changed": owner_changed, "queue_order_changed": False,
            })
        for operation in info.get("operation_receipts", []):
            operation["originating_action_id"] = action_id
            info["command_effects"].append({
                "originating_action_id": action_id, "delivered": True,
                "owner_changed": any(event.get("type") == "task_owner_change" and
                                      event.get("task_id") in operation.get("owners_before", {})
                                      for event in info.get("raw_events", [])),
                "queue_order_changed": _operation_queue_order_changed(operation),
                "operation": copy.deepcopy(operation.get("operation", {})),
            })
        if training and transitions:
            transition = transitions[-1]
            transition["reward"] = float(reward)
            transition["terminated"] = bool(terminated)
            transition["truncated"] = bool(truncated)
        receipt = _step_receipt(method=method_id, parent=scenario, seed=seed, tick=tick,
                                before=before, after=next_observation, detection=detection,
                                scope=scope, planned=planned, catalog=candidates, mask=mask,
                                selected=selected, selected_index=selected_index if planned else None, repair=repair_receipt,
                                reward=float(reward), info=info, planning_latency=planning_latency,
                                response=policy_response, protocol_messages=protocol_messages,
                                policy_receipt=policy_receipt, action_id=action_id, env=env)
        receipt["detector_event_edge"] = bool(scope["trigger_decision"].get("triggered"))
        receipt["triggered"] = bool(planned)
        receipt["selected_scope"] = str(action.get("scope", "NOOP"))
        receipt["initial_c1_assignment"] = copy.deepcopy(scenario.get("initial_c1_assignment"))
        rows.append(receipt)
        trigger_engine.record_reconstruction(tick, effective=bool(receipt["effective_reconstruction_count"]))
        previous = copy.deepcopy(observation)
        observation = next_observation
        history.append(copy.deepcopy(observation))
        history = history[-4:]
    if training:
        for index, transition in enumerate(transitions):
            if index + 1 < len(transitions):
                transition["next_value"] = float(transitions[index + 1]["old_value"])
            elif transition["terminated"] or transition["truncated"]:
                transition["next_value"] = 0.0
    final_tasks = _environment_root_tasks(env)
    metrics = summarize_episode(initial_tasks=initial_tasks, final_tasks=final_tasks, steps=rows,
                                horizon=int(config["environment"]["horizon_minutes"]),
                                parent_id=scenario["parent_id"],
                                protocol_message_weight=float(config["accounting"]["protocol_message_weight"]))
    episode = {
        "method_id": method_id, "parent_id": scenario["parent_id"], "split": scenario["split"],
        "seed": seed, "event_tape_id": scenario.get("event_tape_id"),
        "initial_c1_assignment": scenario.get("initial_c1_assignment"),
        "initial_raw_state": initial_raw_state,
        "initial_public_queues": copy.deepcopy(initial_raw_state.get("queues", {})),
        "initial_root_tasks": initial_tasks, "final_root_tasks": final_tasks,
        "metrics": metrics, "tick_count": len(rows), "training_transition_count": len(transitions),
        "policy_forward_calls": sum(1 for row in rows if row.get("decision_clock", {}).get("planned") and method_id in LEARNING_METHODS),
    }
    return rows, transitions, episode


def train_learning_methods(profile: str, output: str | Path, world_model_dir: str | Path,
                           *, config_override: dict | None = None) -> dict:
    config, config_path, config_hash = load_profile(profile)
    if config_override:
        config.update(copy.deepcopy(config_override))
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    binding = _r8_binding(root, config)
    ensemble, wm_manifest = _load_world_model(Path(world_model_dir).resolve(), str(config.get("runtime", {}).get("device", "cuda:0")), profile)
    world_model_start = _world_model_state_audit(ensemble)
    optimizer_exclusion_checks: list[dict] = []
    actor_initialization_records: list[dict] = []
    wm_critic_boundary_records: list[dict] = []
    paired_graph_initializations: dict[str, dict[str, str]] = {}
    all_scenarios = event_runner._build_scenarios(config)
    train_scenarios = [row for row in all_scenarios if row["split"] == "train"]
    scenarios = [row for row in all_scenarios if row["split"] == "development"]
    if len(train_scenarios) != int(config["parents"]["train"]):
        raise ValueError("BASELINE_TRAIN_PARENT_SET")
    if len(scenarios) != int(config["evaluation"]["development_parent_count"]):
        raise ValueError("BASELINE_DEVELOPMENT_PARENT_SET")
    threshold = event_runner._read_json(root / binding["relative_evidence_path"] / config["data_reuse"]["threshold_manifest"])
    config["resolved_threshold"] = threshold
    episode_receipts = []
    update_receipts = []
    total_policy_forward_calls = 0
    total_optimizer_steps = 0
    policy_parameter_devices: set[str] = set()
    optimizer_state_devices: set[str] = set()
    action_path = out / "TRAINING_ACTION_RECEIPTS.jsonl"
    action_path.write_text("", encoding="utf-8", newline="\n")
    seeds = [int(config["seed"])] if profile == "pilot" else [8201, 8202, 8203]
    learning_config = config["training"]
    for method in LEARNING_METHODS:
        for seed in seeds:
            _, _, _, _, _, _, make_trainer, _, _, _ = _modules()
            trainer = make_trainer(method, seed=seed, device=str(config.get("runtime", {}).get("device", "cuda:0")), config=config)
            actor_initial_digest = trainer._actor_digest()
            actor_initialization_records.append({
                "method_id": method, "seed": seed,
                "graph_policy": bool(trainer.policy.graph),
                "initial_actor_digest": actor_initial_digest,
            })
            if trainer.policy.graph:
                paired_graph_initializations.setdefault(str(seed), {})[method] = actor_initial_digest
            optimizer_exclusion_checks.append(_assert_optimizer_excludes_world_model(trainer, ensemble))
            updates_before = 0
            fixed_probe = None
            rounds = int(learning_config["rounds"])
            episodes_per_round = int(learning_config["episodes_per_round"])
            for round_index in range(rounds):
                for episode_index, scenario in enumerate(train_scenarios):
                    rows, transitions, episode = rollout_episode(method, scenario, seed, config,
                                                                  policy=trainer.policy, ensemble=ensemble, training=True)
                    total_policy_forward_calls += int(episode["policy_forward_calls"])
                    policy_parameter_devices.update(_parameter_devices(trainer.policy))
                    if fixed_probe is None:
                        probe_row = next((row for row in transitions if row.get("actor_decision")), None)
                        if probe_row is not None:
                            fixed_probe = {key: copy.deepcopy(probe_row[key]) for key in
                                           ("observation", "candidates", "candidate_mask", "wm_critic") if key in probe_row}
                    _append_jsonl(action_path, rows)
                    updates = trainer.train_update(transitions,
                        epochs=int(learning_config["epochs"]),
                        minibatch_size=int(learning_config["minibatch_size"]),
                        update_cap=int(learning_config["max_updates_per_learning_method"]))
                    updates_before += len(updates)
                    update_receipts.extend({"method_id": method, "seed": seed, "round": round_index,
                                            "episode": episode_index, **copy.deepcopy(item)} for item in updates)
                    total_optimizer_steps += len(updates)
                    for item in updates:
                        optimizer_state_devices.update(item.get("optimizer_moment_devices", item.get("optimizer_state_tensor_devices", [])))
                    episode_receipts.append({**episode, "round": round_index,
                                             "optimizer_updates_after_episode": len(updates),
                                             "cumulative_optimizer_updates": updates_before,
                                             "optimizer_cap_remaining": max(0, int(learning_config["max_updates_per_learning_method"]) - updates_before)})
            identities = {"profile": profile, "method_id": method, "seed": seed,
                          "config_sha256": config_hash, "source_identity_sha256": _source_hash(root),
                          "data_binding": binding, "trigger_sha256": _sha(threshold),
                          "world_model_hash": ensemble.ensemble_hash}
            checkpoint = out / "checkpoints" / method / f"seed-{seed}.pt"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            if fixed_probe is None:
                raise ValueError("BASELINE_CHECKPOINT_FIXED_PROBE_UNAVAILABLE")
            actor_initialization_records[-1]["final_actor_digest"] = trainer._actor_digest()
            actor_initialization_records[-1]["actor_changed_during_training"] = (
                actor_initialization_records[-1]["initial_actor_digest"] != actor_initialization_records[-1]["final_actor_digest"]
            )
            if method in WM_METHODS:
                wm_critic_boundary_records.append(_audit_wm_critic_boundary(trainer.policy, fixed_probe, method=method, seed=seed))
            trainer.save_checkpoint(checkpoint, identities=identities, fixed_input=fixed_probe)
    for seed, digests in paired_graph_initializations.items():
        if len(digests) != len(LEARNING_METHODS) - 1 or len(set(digests.values())) != 1:
            raise ValueError("BASELINE_PAIRED_GRAPH_ACTOR_INITIALIZATION_MISMATCH")
    actor_audit = {
        "schema": "n02-actor-initialization-audit/1",
        "status": "complete",
        "records": actor_initialization_records,
        "paired_graph_initializations": {
            seed: {"methods": values, "all_equal": len(set(values.values())) == 1,
                   "shared_digest": next(iter(values.values())) if values else None}
            for seed, values in paired_graph_initializations.items()
        },
    }
    world_model_audit = _finalize_world_model_freeze_audit(world_model_start, ensemble, optimizer_exclusion_checks)
    wm_critic_boundary_audit = {
        "schema": "n02-wm-critic-boundary-audit/1",
        "status": "complete",
        "records": wm_critic_boundary_records,
    }
    if len(wm_critic_boundary_records) != len(WM_METHODS) * len(seeds):
        raise ValueError("BASELINE_WM_CRITIC_BOUNDARY_AUDIT_INCOMPLETE")
    _write_json(out / "ACTOR_INITIALIZATION_AUDIT.json", actor_audit)
    _write_json(out / "WORLD_MODEL_FREEZE_AUDIT.json", world_model_audit)
    _write_json(out / "WM_CRITIC_BOUNDARY_AUDIT.json", wm_critic_boundary_audit)
    actor_audit_sha256 = hashlib.sha256((out / "ACTOR_INITIALIZATION_AUDIT.json").read_bytes()).hexdigest()
    world_model_audit_sha256 = hashlib.sha256((out / "WORLD_MODEL_FREEZE_AUDIT.json").read_bytes()).hexdigest()
    wm_critic_boundary_audit_sha256 = hashlib.sha256((out / "WM_CRITIC_BOUNDARY_AUDIT.json").read_bytes()).hexdigest()
    _write_jsonl(out / "TRAINING_EPISODES.jsonl", episode_receipts)
    _write_jsonl(out / "OPTIMIZER_UPDATE_RECEIPTS.jsonl", update_receipts)
    manifest = {"schema": SCHEMA, "status": "complete", "phase": "train", "profile": profile,
                "config_relative_path": str(config_path.relative_to(root)), "config_sha256": config_hash,
                "data_binding": binding, "world_model_hash": ensemble.ensemble_hash,
                "method_ids": list(LEARNING_METHODS), "seeds": seeds,
                "training_episode_count": len(episode_receipts),
                "policy_forward_calls": total_policy_forward_calls,
                "optimizer_steps": total_optimizer_steps,
                "policy_parameter_devices": sorted(policy_parameter_devices),
                "policy_optimizer_state_devices": sorted(optimizer_state_devices),
                "world_model_freeze_audit_sha256": world_model_audit_sha256,
                "world_model_freeze_audit_path": "WORLD_MODEL_FREEZE_AUDIT.json",
                "actor_initialization_audit_sha256": actor_audit_sha256,
                "actor_initialization_audit_path": "ACTOR_INITIALIZATION_AUDIT.json",
                "wm_critic_boundary_audit_sha256": wm_critic_boundary_audit_sha256,
                "wm_critic_boundary_audit_path": "WM_CRITIC_BOUNDARY_AUDIT.json",
                "checkpoints": [str(p.relative_to(out)) for p in sorted((out / "checkpoints").rglob("*.pt"))]}
    _write_json(out / "BASELINE_TRAINING_MANIFEST.json", manifest)
    return manifest


def _source_hash(root: Path) -> str:
    paths = sorted((root / "package" / "civilian").glob("*.py"))
    paths.extend([root / "configs" / "BASELINE_PILOT_CONFIG.json", root / "configs" / "BASELINE_FORMAL_CONFIG.json",
                  root / "configs" / "ENVIRONMENT_SPEC.json", root / "protocols" / "BASELINE_COMPARISON_CONTRACT.md"])
    if any(not path.is_file() for path in paths):
        raise ValueError("BASELINE_SOURCE_IDENTITY_INPUT_MISSING")
    values = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    return _sha(values)


def evaluate_methods(profile: str, output: str | Path, world_model_dir: str | Path,
                     checkpoint_dir: str | Path, *, config_override: dict | None = None) -> dict:
    config, config_path, config_hash = load_profile(profile)
    if config_override:
        config.update(copy.deepcopy(config_override))
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    binding = _r8_binding(root, config)
    ensemble, wm_manifest = _load_world_model(Path(world_model_dir).resolve(), str(config.get("runtime", {}).get("device", "cuda:0")), profile)
    scenarios = [row for row in event_runner._build_scenarios(config) if row["split"] == "development"]
    if len(scenarios) != int(config["evaluation"]["development_parent_count"]):
        raise ValueError("BASELINE_DEVELOPMENT_PARENT_SET")
    threshold = event_runner._read_json(root / binding["relative_evidence_path"] / config["data_reuse"]["threshold_manifest"])
    config["resolved_threshold"] = threshold
    seeds = [int(config["seed"])] if profile == "pilot" else [8201, 8202, 8203]
    episodes: list[dict] = []
    policy_devices: set[str] = set()
    policy_forward_calls = 0
    wm_forward_start = int(getattr(ensemble, "forward_calls", 0))
    action_path = out / "EVALUATION_ACTION_RECEIPTS.jsonl"
    action_path.write_text("", encoding="utf-8", newline="\n")
    repeated_rule_keys: set[str] = set()
    for seed in seeds:
        for method in METHODS:
            policy = None
            if method in LEARNING_METHODS:
                _, _, _, _, _, _, _, restore_trainer, _, _ = _modules()
                ckpt = Path(checkpoint_dir).resolve() / "checkpoints" / method / f"seed-{seed}.pt"
                identities = {"profile": profile, "method_id": method, "seed": seed,
                              "config_sha256": config_hash, "source_identity_sha256": _source_hash(root),
                              "data_binding": binding, "trigger_sha256": _sha(threshold),
                              "world_model_hash": ensemble.ensemble_hash}
                trainer, restore_receipt = restore_trainer(ckpt, expected_identities=identities,
                                                            device=str(config.get("runtime", {}).get("device", "cuda:0")))
                policy = trainer.policy
                policy_devices.update(_parameter_devices(policy))
            else:
                restore_receipt = None
            for scenario in scenarios:
                episode_rows, _, episode = rollout_episode(method, scenario, seed, config,
                                                            policy=policy, ensemble=ensemble, training=False)
                _append_jsonl(action_path, episode_rows)
                episode["checkpoint_restore"] = restore_receipt
                if method in RULE_METHODS and profile == "formal":
                    key = f"{method}:{scenario['parent_id']}"
                    episode["deterministic_repeat_group"] = key
                    episode["independent_seed_sample"] = False
                    repeated_rule_keys.add(key)
                episodes.append(episode)
                policy_forward_calls += int(episode.get("policy_forward_calls", 0))
    _write_jsonl(out / "EVALUATION_EPISODES.jsonl", episodes)
    manifest = {"schema": SCHEMA, "status": "complete", "phase": "evaluate", "profile": profile,
                "config_relative_path": str(config_path.relative_to(root)), "config_sha256": config_hash,
                "data_binding": binding, "world_model_hash": ensemble.ensemble_hash,
                "methods": list(METHODS), "primary_methods": config["primary_methods"], "seeds": seeds,
                "episode_count": len(episodes), "paired_cells": len(episodes),
                "world_model_parameter_devices": sorted({str(parameter.device) for model in ensemble.models
                                                           for parameter in model.parameters()}),
                "policy_parameter_devices": sorted(policy_devices),
                "inference_forward_calls": policy_forward_calls + int(getattr(ensemble, "forward_calls", 0)) - wm_forward_start,
                "development_parent_ids": sorted(row["parent_id"] for row in scenarios),
                "deterministic_rule_repeat_groups": sorted(repeated_rule_keys)}
    _write_json(out / "BASELINE_EVALUATION_MANIFEST.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("pilot", "formal"), required=True)
    parser.add_argument("--phase", choices=("train", "evaluate", "freeze-wm"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--world-model-dir")
    parser.add_argument("--checkpoint-dir")
    args = parser.parse_args(argv)
    if args.phase in {"train", "evaluate"} and not args.world_model_dir:
        parser.error("--world-model-dir is required for train and evaluate")
    config, _, _ = load_profile(args.profile)
    root = Path(__file__).resolve().parents[2]
    if args.phase == "freeze-wm":
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        result = _freeze_world_model(args.profile, output, root, config)
    elif args.phase == "train":
        result = train_learning_methods(args.profile, args.output, args.world_model_dir)
    else:
        if not args.checkpoint_dir:
            parser.error("--checkpoint-dir is required for evaluate")
        result = evaluate_methods(args.profile, args.output, args.world_model_dir, args.checkpoint_dir)
    _write_gpu_execution_receipt(Path(args.output).resolve(), args.phase, config, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
