from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_models
import event_policy
from test_event_models import _sample as _wm_sample
from test_event_policy import _candidates, _observation, _wm_predictions


pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="requires target CUDA runtime")


def test_world_model_has_cuda_forward_backward_update_and_restore(tmp_path: Path) -> None:
    device = torch.device("cuda:0")
    model, metadata = event_models._train_single_model(
        [_wm_sample()], seed=8201, epochs=1, batch_size=1, hidden_dim=16,
        learning_rate=1e-3, data_identity="gpu-test-data", device=device,
    )
    assert metadata["optimizer_updates"] == 1
    assert metadata["training_device"] == "cuda:0"
    assert metadata["model_parameter_devices"] == ["cuda:0"]
    assert metadata["optimizer_state_devices"] == ["cuda:0"]
    assert all(value == "cuda:0" for name, value in metadata["update_log"][0]["input_tensor_devices"].items())
    assert all(parameter.device == device for parameter in model.parameters())

    restored = event_models.TemporalGraphWorldModel(model.config["head_dims"], hidden_dim=16).to(device)
    restored.load_state_dict(model.state_dict(), strict=True)
    assert event_models._state_digest(restored.state_dict()) == metadata["final_model_state_sha256"]


@pytest.mark.parametrize("use_wm_aux", [False, True])
def test_ppo_update_and_optimizer_moments_run_on_cuda(use_wm_aux: bool, tmp_path: Path) -> None:
    device = torch.device("cuda:0")
    policy = event_policy.build_hierarchical_policy(8201, use_wm_aux=use_wm_aux, device=device)
    optimizer = torch.optim.Adam(policy.parameters(), lr=3e-4)
    observation, candidates = _observation(), _candidates()
    predictions = _wm_predictions(0.2) if use_wm_aux else None
    action = policy.act(
        observation, candidates, [True, True, True], None, predictions,
        deterministic=True,
    )
    rows = []
    for advantage in (-1.0, 1.0):
        rows.append({
            "advantage": advantage,
            "return": action["value"] + 1.0 + (advantage + 1.0) * 0.5,
            "old_log_probability": action["log_probability"],
            "observation": observation,
            "candidates": candidates,
            "scope_index": action["scope_index"],
            "candidate_index": action["candidate_index"],
            "high_level_mask": [True, True, True],
            "wm_predictions": predictions,
        })
    before = event_policy._tensor_digest(policy.state_dict())
    updates = event_policy._update_policy(
        policy, optimizer, rows, seed=8201, epochs=1, minibatch_size=2,
        updates_per_epoch=1, learning_rate=3e-4, clip_ratio=0.2,
        entropy_coefficient=0.01,
    )
    assert len(updates) == 1 and updates[0]["optimizer_step_applied"]
    assert updates[0]["training_device"] == "cuda:0"
    assert updates[0]["value_device"] == "cuda:0"
    assert before != event_policy._tensor_digest(policy.state_dict())
    moment_devices = {
        str(value.device)
        for state in optimizer.state.values()
        for name, value in state.items()
        if name != "step" and isinstance(value, torch.Tensor)
    }
    assert moment_devices == {"cuda:0"}
    if use_wm_aux:
        assert updates[0]["auxiliary_critic_gradient_norm_preclip"] > 0.0
    checkpoint = tmp_path / "policy_cuda.pt"
    policy.variant = "Event-G-WM" if use_wm_aux else "Event-G"
    event_policy._save_policy_checkpoint(
        checkpoint, policy, optimizer, variant=policy.variant, seed=8201,
        config={"device": "cuda:0"}, data_identity="gpu-test-data",
        wm_hash="gpu-test-ensemble",
        update_log=updates,
        restore_probe={
            "observation": observation, "candidates": candidates,
            "high_level_mask": [True, True, True], "wm_predictions": predictions,
        },
    )
    restored = event_policy.verify_policy_checkpoint(checkpoint, device="cuda:0")
    assert restored["status"] == "complete"
    assert restored["restore_device"] == "cuda:0"
