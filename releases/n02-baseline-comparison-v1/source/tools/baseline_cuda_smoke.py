"""Synthetic engineering CUDA smoke for baseline PPO learning and restore."""
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
sys.path.insert(0, str(ROOT / "tools"))

import baseline_learning
from baseline_checkpoints import restore_trainer_checkpoint
import gpu_smoke


_RESTORE_SCRIPT = r"""
import json,sys,torch
sys.path.insert(0,sys.argv[1])
from baseline_checkpoints import restore_trainer_checkpoint
identities=json.loads(sys.argv[3])
probe=json.loads(sys.argv[4])
trainer,receipt=restore_trainer_checkpoint(sys.argv[2],expected_identities=identities,device='cuda:0',fixed_input=probe)
if receipt['status'] != 'complete' or not receipt['fixed_prediction_verified']:
    raise RuntimeError('BASELINE_CUDA_SMOKE_RESTORE_INCOMPLETE')
print(json.dumps({'status':'complete','device':str(trainer.device),'optimizer_steps':trainer.counters['optimizer_steps'],'fixed_prediction_verified':receipt['fixed_prediction_verified']},sort_keys=True,separators=(',',':')))
"""


def _wm(value: float) -> dict:
    from event_models import WORLD_MODEL_HEADS
    return {
        "means": {head: [[value, value * 0.5]] for head in WORLD_MODEL_HEADS},
        "variances": {head: [[abs(value) * 0.25, abs(value) * 0.5]] for head in WORLD_MODEL_HEADS},
    }


def _device_inventory(trainer) -> dict:
    moment_devices = set()
    step_devices = set()
    for state in trainer.optimizer.state.values():
        for name, value in state.items():
            if not isinstance(value, torch.Tensor):
                continue
            (step_devices if name == "step" else moment_devices).add(str(value.device))
    return {
        "model_parameter_devices": sorted({str(parameter.device) for parameter in trainer.policy.parameters()}),
        "optimizer_parameter_devices": sorted({str(parameter.device) for group in trainer.optimizer.param_groups for parameter in group["params"]}),
        "adam_moment_devices": sorted(moment_devices),
        "adam_step_devices": sorted(step_devices),
    }


def _transitions(trainer, observation: dict, candidates: list[dict], wm_critic: dict | None) -> list[dict]:
    rows = []
    for index, reward in enumerate((0.25, 1.75)):
        action = trainer.policy.act(
            observation, candidates, [True] * len(candidates), wm_critic=wm_critic, deterministic=True,
        )
        rows.append({
            "observation": observation, "candidates": candidates,
            "candidate_mask": [True] * len(candidates), "action_index": action["candidate_index"],
            "old_log_probability": action["log_probability"], "old_value": action["value"],
            "reward": reward, "terminated": index == 1, "truncated": False,
            "next_value": 0.0, "actor_decision": True, "wm_critic": wm_critic,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, unique evidence directory")
    args = parser.parse_args()
    if not torch.cuda.is_available() or os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise RuntimeError("BASELINE_CUDA_SMOKE_REQUIRES_CUDA_VISIBLE_DEVICES_0")
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    torch.cuda.set_device(device)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    observation = gpu_smoke._observation(1)
    candidates = gpu_smoke._candidates()
    updates = []
    restore_artifact = None

    for method_id in ("PPO", "GPPO", "Event-GPPO-WM"):
        seed = 8201
        trainer = baseline_learning.make_trainer(method_id, seed, device=device, config={"hidden_dim": 32})
        wm_input = _wm(0.1) if method_id.endswith("-WM") else None
        logits_before = trainer.policy.actor_logits(observation, candidates).detach().clone()
        if wm_input is not None:
            trainer.policy.critic_values(observation, wm_input)
            wm_variant = _wm(0.9)
            trainer.policy.critic_values(observation, wm_variant)
            if not torch.equal(logits_before, trainer.policy.actor_logits(observation, candidates).detach()):
                raise RuntimeError("BASELINE_CUDA_SMOKE_ACTOR_WM_INPUT_LEAK:" + method_id)
        wm_before = hashlib.sha256(json.dumps(wm_input, sort_keys=True).encode("ascii")).hexdigest() if wm_input else None
        receipts = trainer.train_update(
            _transitions(trainer, observation, candidates, wm_input),
            epochs=1, minibatch_size=2, update_cap=1,
        )
        if len(receipts) != 1:
            raise RuntimeError("BASELINE_CUDA_SMOKE_UPDATE_COUNT:" + method_id)
        receipt = receipts[0]
        devices = _device_inventory(trainer)
        if (
            devices["model_parameter_devices"] != ["cuda:0"]
            or devices["adam_moment_devices"] != ["cuda:0"]
            or receipt["model_parameter_devices"] != ["cuda:0"]
            or receipt["optimizer_parameter_devices"] != ["cuda:0"]
            or receipt["optimizer_moment_devices"] != ["cuda:0"]
        ):
            raise RuntimeError("BASELINE_CUDA_SMOKE_DEVICE_MISMATCH:" + method_id)
        if not receipt["critic_parameter_digest_changed"]:
            raise RuntimeError("BASELINE_CUDA_SMOKE_CRITIC_UNCHANGED:" + method_id)
        if method_id.endswith("-WM") and (
            receipt["auxiliary_critic_gradient_norm_preclip"] <= 0
            or not receipt["auxiliary_critic_parameter_digest_changed"]
            or hashlib.sha256(json.dumps(wm_input, sort_keys=True).encode("ascii")).hexdigest() != wm_before
        ):
            raise RuntimeError("BASELINE_CUDA_SMOKE_WM_AUX_AUDIT_FAILED")
        if method_id == "PPO":
            identities = {
                "source_sha256": hashlib.sha256(b"baseline-cuda-smoke-source-v1").hexdigest(),
                "config_sha256": hashlib.sha256(b"baseline-cuda-smoke-config-v1").hexdigest(),
                "data_identity": "synthetic-baseline-cuda-smoke-only",
                "trigger_sha256": hashlib.sha256(b"synthetic-trigger-v1").hexdigest(),
                "wm_sha256": None,
            }
            probe = {
                "observation": observation, "candidates": candidates,
                "candidate_mask": [True] * len(candidates),
            }
            checkpoint = output / "ppo_cuda_smoke.pt"
            save = trainer.save_checkpoint(checkpoint, identities=identities, fixed_input=probe)
            restore_artifact = {"checkpoint": checkpoint.name, "save_receipt": save, "identities": identities, "probe": probe}
        updates.append({
            "method_id": method_id, "optimizer_updates": trainer.counters["optimizer_steps"],
            "receipt": receipt, **devices,
            "actor_logits_invariant_to_wm_prediction_change": method_id.endswith("-WM"),
            "wm_input_unchanged_during_update": method_id.endswith("-WM"),
        })

    if restore_artifact is None:
        raise RuntimeError("BASELINE_CUDA_SMOKE_CHECKPOINT_MISSING")
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = "0"
    environment["OMP_NUM_THREADS"] = environment["MKL_NUM_THREADS"] = "1"
    child = subprocess.run(
        [sys.executable, "-B", "-c", _RESTORE_SCRIPT, str(ROOT / "package" / "civilian"),
         str(output / restore_artifact["checkpoint"]),
         json.dumps(restore_artifact["identities"], sort_keys=True),
         json.dumps(restore_artifact["probe"], sort_keys=True)],
        capture_output=True, text=True, timeout=600, check=False, env=environment,
    )
    if child.returncode:
        raise RuntimeError("BASELINE_CUDA_SMOKE_FRESH_PROCESS_RESTORE_FAILED:" + child.stderr[-4000:])
    restore = json.loads(child.stdout.splitlines()[-1])
    receipt = {
        "schema": "n02-baseline-learning-cuda-engineering-smoke/1",
        "status": "PASS_ENGINEERING_SMOKE", "scientific_evidence": False,
        "synthetic_inputs": True, "python": sys.version.split()[0],
        "torch": torch.__version__, "device": "cuda:0",
        "device_name": torch.cuda.get_device_name(device), "updates": updates,
        "fresh_process_checkpoint_restore": restore,
    }
    receipt_path = output / "BASELINE_CUDA_SMOKE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "status": receipt["status"], "device": receipt["device"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
