from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import baseline_learning as learning
import baseline_runner as runner
from baseline_checkpoints import state_digest


def _observation(task_count: int = 1) -> dict:
    tasks = [{"id": f"t{i}", "kind": "delivery", "position": [20 + i % 20, 22], "deadline": 50, "priority": 4, "quantity": 5, "status": "active"} for i in range(task_count)]
    return {
        "time": 1, "horizon": 60, "map": {"rows": 100, "cols": 100},
        "platforms": [{"id": "u1", "type": "uav", "position": [10, 12], "energy": 80, "capacity_kg": 20, "speed_km_min": 1.2, "capabilities": ["deliver"]}],
        "tasks": tasks, "queues": {"u1": [task["id"] for task in tasks]},
        "predecessors": {}, "cooperation": {}, "task_progress": {}, "environment": [], "communication": [],
    }


def _candidates() -> list[dict]:
    return [
        {"candidate_key": "noop", "candidate_scope": "noop", "legal": True,
         "full_environment_action": {"action_type": "noop", "scope": "NOOP", "noop": True, "queue_operations": [], "dispatches": []}},
        {"candidate_key": "dispatch", "candidate_scope": "local", "legal": True,
         "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "queue_operations": [], "dispatches": [{"platform_id": "u1", "task_id": "t0"}]}},
    ]


def _wm(value: float = 0.1) -> dict:
    heads = learning.WORLD_MODEL_HEADS
    return {
        "means": {head: [[value]] for head in heads},
        "variances": {head: [[value * 0.5]] for head in heads},
    }


def test_paired_candidate_modules_match_and_flat_keeps_full_cap_contract() -> None:
    ppo = learning.make_trainer("PPO", 8201)
    gppo = learning.make_trainer("GPPO", 8201)
    assert state_digest(ppo.policy.candidate_encoder.state_dict()) == state_digest(gppo.policy.candidate_encoder.state_dict())
    assert state_digest(ppo.policy.actor_head.state_dict()) == state_digest(gppo.policy.actor_head.state_dict())
    assert ppo.policy.actor_logits(_observation(), _candidates()).shape == (2,)
    with pytest.raises(ValueError, match="BASELINE_FLAT_NODE_CAP"):
        ppo.policy.actor_logits(_observation(task_count=learning.NODE_CAP), _candidates())


def test_wm_changes_aux_critic_only_and_auxiliary_receives_gradients() -> None:
    trainer = learning.make_trainer("Event-GPPO-WM", 8201)
    observation, candidates = _observation(), _candidates()
    logits_a = trainer.policy.actor_logits(observation, candidates).detach()
    trainer.policy.critic_values(observation, _wm(0.1))
    trainer.policy.critic_values(observation, _wm(0.9))
    logits_b = trainer.policy.actor_logits(observation, candidates).detach()
    assert torch.equal(logits_a, logits_b)
    action = trainer.policy.act(observation, candidates, [True, True], wm_critic=_wm(0.1), deterministic=True)
    row = {
        "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
        "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
        "old_value": action["value"], "reward": 2.0, "terminated": True,
        "truncated": False, "next_value": 0.0, "actor_decision": True, "wm_critic": _wm(0.1),
    }
    receipt = trainer.train_update([row], epochs=1, minibatch_size=1, update_cap=1)[0]
    assert receipt["auxiliary_critic_gradient_norm_preclip"] > 0
    assert receipt["auxiliary_critic_parameter_digest_changed"]
    assert receipt["auxiliary_critic_parameter_delta_l2"] > 0
    assert receipt["auxiliary_critic_loss_semantics"] == "diagnostic_only_not_in_total_loss"


@pytest.mark.parametrize("method_id", ["Event-GPPO-WM", "Periodic-GPPO-WM"])
def test_wm_aux_critic_allows_zero_features_only_for_nondecision_ticks(method_id: str) -> None:
    trainer = learning.make_trainer(method_id, 8210)
    observation, candidates = _observation(), _candidates()
    no_decision_value = trainer.policy.value(observation, wm_critic=None)
    assert torch.isfinite(torch.tensor(no_decision_value))
    with pytest.raises(ValueError, match="EVENT_POLICY_WM_PREDICTIONS_REQUIRED"):
        trainer.policy.act(observation, candidates, [True, True], wm_critic=None, deterministic=True)

    action = trainer.policy.act(observation, candidates, [True, True], wm_critic=_wm(0.1), deterministic=True)
    rows = [
        {
            "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
            "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
            "old_value": action["value"], "reward": 1.0, "terminated": False,
            "truncated": False, "next_value": 0.0, "actor_decision": True, "wm_critic": _wm(0.1),
        },
        {
            "observation": observation, "candidates": [], "candidate_mask": [],
            "action_index": 0, "old_log_probability": 0.0,
            "old_value": no_decision_value, "reward": 2.0, "terminated": True,
            "truncated": False, "next_value": 0.0, "actor_decision": False, "wm_critic": None,
        },
    ]
    receipt = trainer.train_update(rows, epochs=1, minibatch_size=2, update_cap=1)[0]
    assert receipt["critic_rows"] == 2
    assert receipt["eligible_actor_rows"] == 1
    assert receipt["auxiliary_critic_gradient_norm_preclip"] > 0
    assert receipt["auxiliary_critic_parameter_delta_l2"] > 0


def test_no_actor_decision_rows_leave_actor_parameters_unchanged() -> None:
    trainer = learning.make_trainer("GPPO", 8202)
    observation, candidates = _observation(), _candidates()
    action = trainer.policy.act(observation, candidates, [True, True], deterministic=True)
    actor_digest = trainer._actor_digest()
    row = {
        "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
        "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
        "old_value": action["value"], "reward": 3.0, "terminated": True,
        "truncated": False, "next_value": 0.0, "actor_decision": False,
    }
    receipt = trainer.train_update([row], epochs=1, minibatch_size=1, update_cap=1)[0]
    assert trainer._actor_digest() == actor_digest
    assert not receipt["actor_parameter_digest_changed"]
    assert receipt["actor_parameter_delta_l2"] == 0
    assert receipt["actor_row_records"] == []


def test_receipt_gae_and_returns_are_independently_recomputable() -> None:
    trainer = learning.make_trainer("GPPO", 8203, config={"gamma": 0.9, "gae_lambda": 0.8})
    observation, candidates = _observation(), _candidates()
    rows = []
    for index, (reward, value, next_value, terminated, truncated, actor_decision) in enumerate([
        (1.0, 0.5, 0.7, False, False, True),
        (2.0, 0.6, 0.4, False, True, True),
        (-1.0, 0.2, 0.0, True, False, False),
    ]):
        action = trainer.policy.act(observation, candidates, [True, True], deterministic=True)
        rows.append({
            "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
            "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
            "old_value": value, "reward": reward, "terminated": terminated,
            "truncated": truncated, "next_value": next_value, "actor_decision": actor_decision,
        })
    receipts = trainer.train_update(rows, epochs=1, minibatch_size=3, update_cap=1)
    records = {entry["physical_index"]: entry for entry in receipts[0]["physical_transition_records"]}
    gamma, lam = 0.9, 0.8
    expected = [0.0] * len(rows)
    running = 0.0
    for index in reversed(range(len(rows))):
        row = rows[index]
        terminal = row["terminated"]
        boundary = terminal or row["truncated"]
        delta = row["reward"] + gamma * (0.0 if terminal else row["next_value"]) - row["old_value"]
        running = delta + (0.0 if boundary else gamma * lam * running)
        expected[index] = running
    actor_values = [expected[index] for index, row in enumerate(rows) if row["actor_decision"]]
    mean, std = sum(actor_values) / len(actor_values), (sum((value - sum(actor_values) / len(actor_values)) ** 2 for value in actor_values) / len(actor_values)) ** 0.5
    for index, row in enumerate(rows):
        record = records[index]
        assert record["raw_gae"] == pytest.approx(expected[index])
        assert record["return_target"] == pytest.approx(expected[index] + row["old_value"])
        expected_advantage = ((expected[index] - mean) / max(std, 1e-8)) if row["actor_decision"] else expected[index]
        assert record["normalized_advantage"] == pytest.approx(expected_advantage)


def test_update_uses_physical_rows_decision_mask_tail_and_cumulative_cap() -> None:
    trainer = learning.make_trainer("PPO", 8201)
    observation, candidates = _observation(), _candidates()
    rows = []
    for index in range(3):
        action = trainer.policy.act(observation, candidates, [True, True], deterministic=True)
        rows.append({
            "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
            "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
            "old_value": action["value"], "reward": float(index), "terminated": index == 2,
            "truncated": False, "next_value": 0.0, "actor_decision": index != 1,
        })
    receipts = trainer.train_update(rows, epochs=1, minibatch_size=2, update_cap=2)
    assert len(receipts) == 2
    assert sum(item["eligible_actor_rows"] for item in receipts) == 2
    assert sum(item["critic_rows"] for item in receipts) == 3
    assert trainer.train_update(rows, epochs=4, minibatch_size=2, update_cap=2) == []
    assert trainer.counters["optimizer_steps"] == 2


def test_wm_freeze_actor_initialization_and_critic_boundary_audits() -> None:
    seed = 8201
    graph_digests = {
        method: learning.make_trainer(method, seed)._actor_digest()
        for method in learning.METHODS if method != "PPO"
    }
    assert len(set(graph_digests.values())) == 1

    trainer = learning.make_trainer("Event-GPPO-WM", seed)
    wm_member = torch.nn.Linear(2, 2)
    wm_member.requires_grad_(False)
    ensemble = SimpleNamespace(models=[wm_member])
    wm_start = runner._world_model_state_audit(ensemble)
    optimizer_check = runner._assert_optimizer_excludes_world_model(trainer, ensemble)
    observation, candidates = _observation(), _candidates()
    wm_predictions = _wm(0.1)
    action = trainer.policy.act(observation, candidates, [True, True], wm_critic=wm_predictions, deterministic=True)
    transition = {
        "observation": observation, "candidates": candidates, "candidate_mask": [True, True],
        "action_index": action["candidate_index"], "old_log_probability": action["log_probability"],
        "old_value": action["value"], "reward": 2.0, "terminated": True,
        "truncated": False, "next_value": 0.0, "actor_decision": True, "wm_critic": wm_predictions,
    }
    trainer.train_update([transition], epochs=1, minibatch_size=1, update_cap=1)
    freeze_audit = runner._finalize_world_model_freeze_audit(wm_start, ensemble, [optimizer_check])
    assert freeze_audit["status"] == "complete"

    boundary = runner._audit_wm_critic_boundary(
        trainer.policy,
        {"observation": observation, "candidates": candidates, "candidate_mask": [True, True], "wm_critic": wm_predictions},
        method="Event-GPPO-WM", seed=seed,
    )
    assert boundary["actor_logits_invariant"]
    assert boundary["actual_wm_critic_feature_l2"] > 0
    assert boundary["auxiliary_critic_sensitive_to_wm_features"]
