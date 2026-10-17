"""Engineering-only CUDA path smoke with synthetic public-shaped inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "package" / "civilian"))
import event_models
import event_policy


_RESTORE_SCRIPT = r"""
import hashlib,json,sys,torch
sys.path.insert(0,sys.argv[1])
import event_models,event_policy
with open(sys.argv[2],encoding='utf-8') as f: request=json.load(f)
torch.set_num_threads(1)
torch.cuda.set_device('cuda:0')
ensemble=event_models.load_ensemble(request['world_model_checkpoints'],device='cuda:0')
predictions=event_models.predict_ensemble(ensemble,request['history'],request['candidates'])
raw=json.dumps(predictions,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
prediction_sha=hashlib.sha256(raw).hexdigest()
if prediction_sha != request['expected_prediction_sha256']: raise RuntimeError('GPU_SMOKE_WM_RESTORE_MISMATCH')
policies=[event_policy.verify_policy_checkpoint(path,ensemble=ensemble,device='cuda:0') for path in request['policy_checkpoints']]
print(json.dumps({'status':'complete','device':'cuda:0','world_model_prediction_sha256':prediction_sha,'world_model_members':len(ensemble.models),'policy_checks':policies},sort_keys=True,separators=(',',':'),allow_nan=False))
"""


def _observation(time_index: int) -> dict:
    return {
        "time": time_index, "horizon": 60, "map": {"rows": 100, "cols": 100},
        "platforms": [{
            "id": "u1", "type": "uav", "position": [10, 12], "energy": 80 - time_index / 10,
            "capacity_kg": 20, "speed_km_min": 1.2, "energy_per_km": 0.5,
            "service_energy_per_min": 0.1, "failed": False, "busy": False,
            "health": "healthy", "load": {"active_tasks": 1, "queued_tasks": 0},
            "capabilities": ["inspect", "deliver"],
        }],
        "tasks": [{
            "id": "t1", "kind": "delivery", "position": [20, 22], "local": True,
            "deadline": 50, "priority": 4, "quantity": 5, "status": "active",
            "progress": time_index / 100,
        }],
        "queues": {"u1": ["t1"]}, "predecessors": {"t1": []},
        "cooperation": {"t1": []}, "task_progress": {"t1": time_index / 100},
        "environment": [],
        "communication": [{"source": "u1", "target": "u1", "quality": 0.9,
                            "latency_minutes": 0.1, "loss_rate": 0.01, "connected": True}],
    }


def _candidates() -> list[dict]:
    rows = [
        ("noop", {"scope": "NOOP", "noop": True, "queue_operations": [], "dispatches": []}),
        ("local", {"scope": "LOCAL_REPAIR", "noop": False, "queue_operations": [], "dispatches": [{"platform_id": "u1", "task_id": "t1"}]}),
        ("global", {"scope": "GLOBAL_REPLAN", "noop": False, "queue_operations": [{"op": "transfer", "task_id": "t1", "from_platform": "u1", "to_platform": "u1"}], "dispatches": [{"platform_id": "u1", "task_id": "t1"}]}),
    ]
    return [{
        "candidate_key": "gpu-smoke-" + key, "candidate_scope": key, "legal": True,
        "full_environment_action": {"action_type": "reconstruct", **action},
    } for key, action in rows]


def _sample() -> dict:
    candidates = _candidates()
    targets = {}
    for head in event_models.WORLD_MODEL_HEADS:
        values = [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]] if head == "next_state" else [0.1, 0.2, 0.3]
        targets[head] = {"values": values, "valid": [True, True, True]}
    return {
        "sample_id": "synthetic-gpu-smoke", "split": "train", "parent_id": "synthetic-only",
        "history": [_observation(index) for index in range(4)],
        "candidates": candidates, "targets": targets,
    }


def _devices(optimizer: torch.optim.Optimizer) -> tuple[list[str], list[str]]:
    moments = sorted({str(value.device) for state in optimizer.state.values()
                      for name, value in state.items()
                      if name != "step" and isinstance(value, torch.Tensor)})
    steps = sorted({str(state["step"].device) for state in optimizer.state.values()
                    if isinstance(state.get("step"), torch.Tensor)})
    return moments, steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, unique evidence directory")
    args = parser.parse_args()
    if not torch.cuda.is_available() or os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise RuntimeError("GPU_SMOKE_REQUIRES_CUDA_VISIBLE_DEVICES_0")
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    torch.cuda.set_device(device)
    torch.cuda.reset_peak_memory_stats(device)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sample = _sample()
    data_identity = hashlib.sha256(b"synthetic engineering smoke only").hexdigest()
    model_checkpoints = []
    model_updates = []
    models = []
    for seed in event_models.ENSEMBLE_SEEDS:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        model, metadata = event_models._train_single_model(
            [sample], seed=seed, epochs=1, batch_size=1, hidden_dim=16,
            learning_rate=1e-3, data_identity=data_identity, device=device,
        )
        payload = {
            "schema": event_models.EVENT_MODEL_SCHEMA, "seed": seed,
            "data_identity": data_identity, "config": model.config,
            "training_config": {"epochs": 1, "batch_size": 1, "learning_rate": 1e-3, "device": "cuda:0"},
            "normalization": metadata["normalization"], "model_state": model.state_dict(),
            "optimizer_state": metadata["optimizer_state"],
            "model_state_sha256": metadata["model_state_sha256"],
            "optimizer_updates": metadata["optimizer_updates"],
            "training_device": "cuda:0",
        }
        path = output / f"world_model_seed_{seed}.pt"
        event_models._atomic_save(payload, path)
        model_checkpoints.append(str(path))
        models.append(model)
        model_updates.append({
            "seed": seed, "optimizer_updates": metadata["optimizer_updates"],
            "training_device": metadata["training_device"],
            "model_parameter_devices": metadata["model_parameter_devices"],
            "optimizer_moment_devices": metadata["optimizer_state_devices"],
            "optimizer_step_devices": metadata["optimizer_step_device"],
            "parameter_delta_l2": metadata["parameter_delta_l2"],
        })
    ensemble = event_models.load_ensemble(model_checkpoints, device=device)
    predictions = event_models.predict_ensemble(ensemble, sample["history"], sample["candidates"])
    prediction_sha = hashlib.sha256(json.dumps(predictions, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    model_digests_before_ppo = [event_models._state_digest(model.state_dict()) for model in ensemble.models]
    policy_checkpoints = []
    policy_updates = []
    for variant, use_wm in (("Event-G", False), ("Event-G-WM", True)):
        torch.manual_seed(8201)
        torch.cuda.manual_seed_all(8201)
        policy = event_policy.build_hierarchical_policy(8201, use_wm_aux=use_wm, device=device)
        policy.variant = variant
        optimizer = torch.optim.Adam(policy.parameters(), lr=3e-4)
        wm_predictions = predictions if use_wm else None
        action = policy.act(sample["history"][-1], sample["candidates"], [True, True, True], None, wm_predictions, deterministic=True)
        transitions = [{
            "advantage": advantage, "return": action["value"] + 1.0 + (advantage + 1.0) * 0.5,
            "old_log_probability": action["log_probability"],
            "observation": sample["history"][-1], "candidates": sample["candidates"],
            "scope_index": action["scope_index"], "candidate_index": action["candidate_index"],
            "high_level_mask": [True, True, True], "wm_predictions": wm_predictions,
        } for advantage in (-1.0, 1.0)]
        before = event_policy._tensor_digest(policy.state_dict())
        updates = event_policy._update_policy(
            policy, optimizer, transitions, seed=8201, epochs=1, minibatch_size=2,
            updates_per_epoch=1, learning_rate=3e-4, clip_ratio=0.2,
            entropy_coefficient=0.01,
        )
        moment_devices, step_devices = _devices(optimizer)
        after = event_policy._tensor_digest(policy.state_dict())
        if before == after or moment_devices != ["cuda:0"] or (use_wm and updates[0]["auxiliary_critic_gradient_norm_preclip"] <= 0):
            raise RuntimeError("GPU_SMOKE_POLICY_UPDATE_AUDIT_FAILED:" + variant)
        policy_path = output / f"policy_{variant}.pt"
        event_policy._save_policy_checkpoint(
            policy_path, policy, optimizer, variant=variant, seed=8201,
            config={"device": "cuda:0", "smoke": True}, data_identity=data_identity,
            wm_hash=ensemble.ensemble_hash, update_log=updates,
            restore_probe={"observation": sample["history"][-1], "candidates": sample["candidates"],
                           "high_level_mask": [True, True, True], "wm_predictions": wm_predictions},
        )
        policy_checkpoints.append(str(policy_path))
        policy_updates.append({
            "variant": variant, "optimizer_updates": len(updates),
            "training_device": updates[0]["training_device"],
            "model_parameter_devices": sorted({str(parameter.device) for parameter in policy.parameters()}),
            "optimizer_moment_devices": moment_devices, "optimizer_step_devices": step_devices,
            "auxiliary_critic_gradient_norm": updates[0]["auxiliary_critic_gradient_norm_preclip"],
            "parameter_changed": before != after,
        })
    model_digests_after_ppo = [event_models._state_digest(model.state_dict()) for model in ensemble.models]
    if model_digests_before_ppo != model_digests_after_ppo or any(parameter.grad is not None for model in ensemble.models for parameter in model.parameters()):
        raise RuntimeError("GPU_SMOKE_WORLD_MODEL_NOT_FROZEN")
    request = {
        "world_model_checkpoints": model_checkpoints,
        "policy_checkpoints": policy_checkpoints,
        "history": sample["history"], "candidates": sample["candidates"],
        "expected_prediction_sha256": prediction_sha,
    }
    request_path = output / "restore_request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = "0"
    environment["OMP_NUM_THREADS"] = environment["MKL_NUM_THREADS"] = "1"
    child = subprocess.run(
        [sys.executable, "-B", "-c", _RESTORE_SCRIPT, str(ROOT / "package" / "civilian"), str(request_path)],
        capture_output=True, text=True, timeout=600, check=False, env=environment,
    )
    if child.returncode:
        raise RuntimeError("GPU_SMOKE_FRESH_PROCESS_RESTORE_FAILED:" + child.stderr[-4000:])
    restore = json.loads(child.stdout.splitlines()[-1])
    if restore.get("status") != "complete" or len(restore.get("policy_checks", [])) != 2:
        raise RuntimeError("GPU_SMOKE_FRESH_PROCESS_RESTORE_INCOMPLETE")
    receipt = {
        "schema": "n02-event-gpu-engineering-smoke/1", "status": "PASS_ENGINEERING_SMOKE",
        "scientific_evidence": False, "synthetic_inputs": True,
        "python": sys.version.split()[0], "torch": torch.__version__,
        "device": "cuda:0", "device_name": torch.cuda.get_device_name(device),
        "world_model_updates": model_updates, "policy_updates": policy_updates,
        "world_model_frozen_during_ppo": True,
        "fresh_process_restore": restore,
        "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
    }
    receipt_path = output / "GPU_SMOKE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "status": receipt["status"], "device": receipt["device"], "peak_memory_allocated_bytes": receipt["peak_memory_allocated_bytes"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
