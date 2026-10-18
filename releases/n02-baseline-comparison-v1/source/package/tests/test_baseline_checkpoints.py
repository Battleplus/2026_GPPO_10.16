from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import baseline_learning as learning
from baseline_checkpoints import verify_wm_checkpoint_resume
import event_models


def _input() -> dict:
    observation = {
        "time": 1, "horizon": 60, "map": {"rows": 100, "cols": 100},
        "platforms": [{"id": "u1", "type": "uav", "position": [10, 12], "energy": 80, "capacity_kg": 20, "speed_km_min": 1.2, "capabilities": ["deliver"]}],
        "tasks": [{"id": "t1", "kind": "delivery", "position": [20, 22], "deadline": 50, "priority": 4, "quantity": 5, "status": "active"}],
        "queues": {"u1": ["t1"]}, "predecessors": {}, "cooperation": {}, "task_progress": {}, "environment": [], "communication": [],
    }
    candidates = [
        {"candidate_key": "noop", "candidate_scope": "noop", "legal": True,
         "full_environment_action": {"action_type": "noop", "scope": "NOOP", "noop": True, "queue_operations": [], "dispatches": []}},
        {"candidate_key": "dispatch", "candidate_scope": "local", "legal": True,
         "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "queue_operations": [], "dispatches": [{"platform_id": "u1", "task_id": "t1"}]}},
    ]
    return {"observation": observation, "candidates": candidates, "candidate_mask": [True, True]}


def test_checkpoint_restores_training_state_and_probe_in_fresh_process(tmp_path: Path) -> None:
    trainer = learning.make_trainer("GPPO", 8201)
    probe = _input()
    act = trainer.policy.act(probe["observation"], probe["candidates"], probe["candidate_mask"], deterministic=True)
    transition = {
        **probe, "action_index": act["candidate_index"], "old_log_probability": act["log_probability"],
        "old_value": act["value"], "reward": 1.0, "terminated": True, "truncated": False,
        "next_value": 0.0, "actor_decision": True,
    }
    trainer.train_update([transition], epochs=1, minibatch_size=4, update_cap=1)
    checkpoint = tmp_path / "resume.pt"
    identities = {"source_sha256": "a" * 64, "config_sha256": "b" * 64, "data_identity": "train-set-v1", "trigger_sha256": "c" * 64, "wm_sha256": None}
    save_receipt = trainer.save_checkpoint(checkpoint, identities=identities, fixed_input=probe)
    assert save_receipt["fixed_prediction_verified"]
    script = (
        "import json,sys; "
        f"sys.path.insert(0, {str(ROOT / 'civilian')!r}); "
        "from baseline_checkpoints import restore_trainer_checkpoint; "
        "trainer,receipt=restore_trainer_checkpoint(sys.argv[1], expected_identities=json.loads(sys.argv[2]), device='cpu'); "
        "print(json.dumps(receipt, sort_keys=True))"
    )
    run = subprocess.run(
        [sys.executable, "-B", "-c", script, str(checkpoint), json.dumps(identities)],
        check=True, capture_output=True, text=True,
    )
    receipt = json.loads(run.stdout.strip().splitlines()[-1])
    assert receipt["status"] == "complete"
    assert receipt["fixed_prediction_verified"]
    assert receipt["optimizer_state_sha256"] == save_receipt["optimizer_state_sha256"]
    assert receipt["rng_state_sha256"] == save_receipt["rng_state_sha256"]


def test_wm_resume_checker_restores_rng_optimizer_and_presave_predictions_in_fresh_process(tmp_path: Path) -> None:
    probe = _input()
    history = [dict(probe["observation"], time=t) for t in range(4)]
    samples = []
    for index in range(8):
        targets = {}
        for head in event_models.WORLD_MODEL_HEADS:
            values = [[0.1, 0.2], [0.2, 0.3]] if head == "next_state" else [0.1, 0.2]
            targets[head] = {"values": values, "valid": [True, True]}
        samples.append({
            "sample_id": f"wm-{index}", "split": "train", "parent_id": f"parent-{index % 4}",
            "history": history, "candidates": probe["candidates"], "targets": targets,
        })
    trained = event_models.train_ensemble(samples, tmp_path / "wm", {"hidden_dim": 16})
    identity = event_models._identity(samples)
    checked = verify_wm_checkpoint_resume(
        trained["checkpoint_paths"], expected_data_identity=identity,
        fixed_sample={"history": history, "candidates": probe["candidates"]},
    )
    assert checked["status"] == "complete"
    assert checked["seeds"] == [8201, 8202, 8203]
    assert checked["fixed_prediction_verified"]
    assert checked["fresh_process_pid"] != checked["parent_pid"]
    assert checked["fresh_process_exit_status"] == 0
    members = checked["fresh_process_restore"]["members"]
    assert len(members) == 3
    assert all(row["rng_state_sha256"] == row["actual_restored_rng_sha256"] for row in members)
    assert all(row["optimizer_state_sha256"] for row in members)
    assert all(row["normalization_sha256"] and row["probe_identity_sha256"] for row in members)
    assert all(row["prediction_sha256"] for row in members)

    checkpoint = Path(trained["checkpoint_paths"][0])
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    def bump_first(value):
        if isinstance(value, list):
            return [bump_first(value[0]), *value[1:]]
        return value + 1.0
    payload["resume_proof"]["reference_prediction"]["heads"]["utility"] = bump_first(
        payload["resume_proof"]["reference_prediction"]["heads"]["utility"]
    )
    torch.save(payload, checkpoint)
    with pytest.raises(ValueError, match="BASELINE_WM_FRESH_PROCESS_RESTORE_FAILED"):
        verify_wm_checkpoint_resume(
            trained["checkpoint_paths"], expected_data_identity=identity,
            fixed_sample={"history": history, "candidates": probe["candidates"]},
        )


def test_wm_resume_rejects_legacy_checkpoint_without_presave_proof(tmp_path: Path) -> None:
    probe = _input()
    history = [dict(probe["observation"], time=t) for t in range(4)]
    samples = []
    for index in range(8):
        targets = {}
        for head in event_models.WORLD_MODEL_HEADS:
            values = [[0.1, 0.2], [0.2, 0.3]] if head == "next_state" else [0.1, 0.2]
            targets[head] = {"values": values, "valid": [True, True]}
        samples.append({
            "sample_id": f"legacy-proof-{index}", "split": "train", "parent_id": f"parent-{index % 4}",
            "history": history, "candidates": probe["candidates"], "targets": targets,
        })
    trained = event_models.train_ensemble(samples, tmp_path / "legacy-wm", {"hidden_dim": 16})
    identity = event_models._identity(samples)
    checkpoint = Path(trained["checkpoint_paths"][0])
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    payload.pop("resume_proof")
    torch.save(payload, checkpoint)
    with pytest.raises(ValueError, match="BASELINE_WM_STRICT_RESUME_PROOF_REQUIRED"):
        verify_wm_checkpoint_resume(
            trained["checkpoint_paths"], expected_data_identity=identity,
            fixed_sample={"history": history, "candidates": probe["candidates"]},
        )
