from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_trigger


def _observation(time: int = 0) -> dict:
    return {
        "time": time,
        "horizon": 60,
        "coordinator_id": "n02-uav-1",
        "queues": {"n02-uav-1": ["t1"]},
        "platforms": [{
            "id": "n02-uav-1", "type": "uav", "position": [0.0, 0.0],
            "energy": 100.0, "energy_initial": 100.0, "capacity_kg": 20.0,
            "speed_km_min": 1.0, "energy_per_km": 1.0,
            "service_energy_per_min": 0.1, "failed": False,
            "active_task_id": "t1", "capabilities": ["inspect", "deliver"],
        }],
        "tasks": [{
            "id": "t1", "kind": "inspection", "position": [2.0, 0.0],
            "deadline": 50, "priority": 3, "status": "active",
            "phase": "to_inspection", "progress": 0.0,
            "assignee": "n02-uav-1", "service_minutes": 5,
        }],
        "depots": [], "environment": [], "communication": [],
    }


def test_external_disturbance_triggers_after_warmup_without_residual_persistence() -> None:
    engine = event_trigger.TriggerEngine({
        "warmup_steps": 2, "persistence_steps": 2, "hysteresis_margin": 0.05,
    }, {"threshold": 0.05})
    previous = _observation()
    for step in range(1, 4):
        current = copy.deepcopy(previous)
        current["time"] = step
        current["platforms"][0]["position"] = [float(step), 0.0]
        current["platforms"][0]["energy"] -= 20.0
        detection = engine.detect(previous, current)
        decision = engine.decide(detection, step)
        if step <= 2:
            assert decision["triggered"] is False
            assert decision["trigger_suppression_reason"] == "warmup"
        else:
            assert decision["triggered"] is True
            assert decision["persistence_required"] is False
            assert decision["persistence_count"] == 0
        previous = current


def test_residual_persistence_needs_consecutive_high_scores(monkeypatch) -> None:
    engine = event_trigger.TriggerEngine({"persistence_steps": 2, "hysteresis_margin": 0.05, "residual_only": True}, {"threshold": 0.1})
    previous = _observation()
    # Identical telemetry excludes structural changes; only the independent
    # execution-residual estimator is controlled to probe the counter sequence.
    for step, score in enumerate([0.4, 0.28, 0.4, 0.4], 1):
        monkeypatch.setattr(event_trigger, "_public_execution_residuals", lambda *_, x=score: {
            "d_state": x, "residuals": {"position": x, "energy": 0., "progress": 0.},
            "platform_ids": ["n02-uav-1"], "task_ids": []})
        detection = engine.detect(previous, previous)
        assert detection["event_type"] == "execution_residual"
        assert detection["persistence_count"] == [1, 0, 1, 2][step-1]
        assert engine.decide(detection, step)["triggered"] is (step == 4)


def test_threshold_manifest_and_relative_hysteresis_are_binding() -> None:
    import pytest
    engine = event_trigger.TriggerEngine({"hysteresis_margin": 0.05}, {"threshold": 0.4})
    assert engine.threshold_high == 0.4
    assert engine.threshold_low == 0.38
    with pytest.raises(ValueError, match="training threshold"):
        event_trigger.TriggerEngine({"threshold_high": 0.03}, {"threshold": 0.4})
    with pytest.raises(ValueError, match="derived"):
        event_trigger.TriggerEngine({"threshold_low": 0.02}, {"threshold": 0.4})


def test_hysteresis_release_clears_event_active() -> None:
    engine = event_trigger.TriggerEngine({
        "persistence_steps": 1, "hysteresis_margin": 0.8,
    }, {"threshold": 0.05})
    high_detection = {
        "gamma_value": 0.06, "threshold": 0.05, "threshold_high": 0.05,
        "threshold_low": 0.01, "warmup_complete": True,
        "event_type": "platform_disturbance", "strong_event": False,
        "affected_task_ids": ["t1"], "affected_platform_ids": ["n02-uav-1"],
    }
    assert engine.decide(high_detection, 1)["triggered"] is True
    between_thresholds = {
        **high_detection, "gamma_value": 0.03,
    }
    held = engine.decide(between_thresholds, 2)
    assert held["trigger_edge"] == "held"
    assert held["event_active"] is True
    below_release_threshold = {
        **high_detection, "gamma_value": 0.005, "event_type": "none",
        "affected_task_ids": [], "affected_platform_ids": [], "residual_signal": False,
    }
    released = engine.decide(below_release_threshold, 3)
    assert released["triggered"] is False
    assert released["trigger_edge"] == "falling"
    assert released["event_active"] is False


def test_explicit_empty_impact_domain_cannot_trigger_global() -> None:
    engine = event_trigger.TriggerEngine({"threshold": 0.01}, {"threshold": 0.01})
    detection = {
        "gamma_value": 1.0, "threshold": 0.01,
        "affected_task_ids": [], "affected_platform_ids": [],
        "strong_event": False, "event_type": "none",
    }
    decision = engine.decide(detection, 1)
    assert decision["triggered"] is False
    assert decision["high_level_action"] == "NOOP"
    assert decision["trigger_suppression_reason"] == "empty_impact_domain"


def test_scope_keeps_direct_and_closure_fields_without_component_blowup() -> None:
    observation = _observation()
    observation["platforms"].append({**copy.deepcopy(observation["platforms"][0]), "id": "n02-uav-2"})
    observation["tasks"].append({
        **copy.deepcopy(observation["tasks"][0]), "id": "t2", "assignee": "n02-uav-2",
        "predecessors": ["t1"],
    })
    detection = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["n02-uav-1"],
        "event_details": {"category_count": 1}, "strong_event": False,
    }
    scope = event_trigger.identify_affected_scope(observation, detection)
    assert scope["direct_affected_task_ids"] == ["t1"]
    assert "t2" in scope["closure_affected_task_ids"]
    assert "direct_affected_task_ids" in scope
    assert scope["scope"] in {"LOCAL_REPAIR", "GLOBAL_REPLAN"}


def test_strong_narrow_event_can_use_local_repair_mask() -> None:
    observation = _observation()
    detection = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["n02-uav-1"],
        "event_details": {"category_count": 1}, "strong_event": True,
        "event_severity": "strong", "triggered": True,
    }
    scope = event_trigger.identify_affected_scope(observation, detection)
    assert scope["global_required"] is False
    assert scope["local_eligible"] is True
    assert scope["global_eligible"] is False
    mask = event_trigger.high_level_action_mask(detection, scope)
    assert mask["LOCAL_REPAIR"] is True
    assert mask["GLOBAL_REPLAN"] is False


def test_key_failure_or_split_requires_global_replan() -> None:
    observation = _observation()
    key_failure = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["n02-uav-1"],
        "event_details": {"category_count": 1, "failed_platform_ids": ["n02-uav-1"]},
        "strong_event": True, "event_severity": "strong", "triggered": True,
    }
    observation["platforms"][0]["type"] = "helicopter"
    scope = event_trigger.identify_affected_scope(observation, key_failure)
    assert scope["global_required"] is True
    assert scope["global_eligible"] is True
    assert event_trigger.high_level_action_mask(key_failure, scope)["GLOBAL_REPLAN"] is True

    split = {
        **key_failure,
        "event_details": {"category_count": 1, "network_split_new": True},
    }
    split_scope = event_trigger.identify_affected_scope(observation, split)
    assert split_scope["global_required"] is True


def test_structural_task_arrival_contributes_to_state_score() -> None:
    previous = _observation()
    current = copy.deepcopy(previous)
    current["tasks"].append({
        "id": "t2", "kind": "inspection", "position": [3.0, 2.0],
        "deadline": 50, "priority": 3, "status": "pending", "phase": "pending",
        "progress": 0.0, "assignee": None, "known": True, "service_minutes": 4,
    })
    engine = event_trigger.TriggerEngine({"warmup_steps": 0}, {"threshold": 0.02})

    detection = engine.detect(previous, current)
    assert detection["d_state_execution"] == 0.0
    assert detection["d_state_structural"] > 0.0
    assert detection["d_state"] == detection["d_state_structural"]
    assert detection["event_details"]["structural_change_components"]["task"] > 0.0
    assert detection["coverage_debt_task_ids"] == ["t2"]
    assert detection["service_coverage"]["eligible_platform_ids_by_task"]["t2"] == ["n02-uav-1"]
    assert engine.decide(detection, current["time"])["triggered"] is True


def test_service_coverage_retry_is_state_driven_and_rate_limited() -> None:
    previous = {
        "time": 0, "horizon": 20, "coordinator_id": "n02-uav-1", "queues": {"n02-uav-1": []},
        "platforms": [{
            "id": "n02-uav-1", "type": "uav", "position": [0.0, 0.0],
            "energy": 100.0, "energy_initial": 100.0, "capacity_kg": 20.0,
            "speed_km_min": 1.0, "energy_per_km": 1.0, "failed": False,
            "active_task_id": None, "capabilities": ["inspect"],
        }],
        "tasks": [], "depots": [], "environment": [], "communication": [],
    }
    engine = event_trigger.TriggerEngine({"warmup_steps": 0, "delta_min": 4}, {"threshold": 0.9})
    observations = []
    for time in range(1, 6):
        current = copy.deepcopy(previous)
        current["time"] = time
        current["tasks"] = [{
            "id": "arrival", "kind": "inspection", "position": [2.0, 0.0],
            "deadline": 18, "priority": 2, "status": "pending", "phase": "pending",
            "progress": 0.0, "assignee": None, "known": True, "service_minutes": 2,
        }]
        detection = engine.detect(previous, current)
        decision = engine.decide(detection, time)
        observations.append((detection, decision))
        previous = current

    assert [decision["triggered"] for _, decision in observations] == [True, False, False, False, True]
    assert observations[0][0]["service_debt_state_changed"] is True
    assert observations[1][0]["service_debt_state_changed"] is False
    assert observations[4][0]["service_debt_retry_due"] is True


def test_unassigned_task_uses_public_coordinator_reachability() -> None:
    observation = _observation()
    observation["coordinator_id"] = "n02-uav-2"
    observation["platforms"][0]["capabilities"] = ["deliver"]
    observation["platforms"].extend([
        {
            "id": "n02-uav-2", "type": "uav", "position": [1.0, 1.0],
            "energy": 100.0, "energy_initial": 100.0, "capacity_kg": 20.0,
            "speed_km_min": 1.0, "energy_per_km": 1.0, "failed": False,
            "active_task_id": None, "capabilities": ["deliver"],
        },
        {
            "id": "n02-uav-3", "type": "uav", "position": [3.0, 2.0],
            "energy": 100.0, "energy_initial": 100.0, "capacity_kg": 20.0,
            "speed_km_min": 1.0, "energy_per_km": 1.0, "failed": False,
            "active_task_id": None, "capabilities": ["inspect"],
        },
    ])
    observation["tasks"].append({
        "id": "new", "kind": "inspection", "position": [3.0, 2.0],
        "deadline": 50, "priority": 3, "status": "pending", "phase": "pending",
        "progress": 0.0, "assignee": None, "known": True, "service_minutes": 2,
    })
    observation["communication"] = [{
        "source": "n02-uav-2", "target": "n02-uav-3", "quality": 0.9,
        "connected": True, "latency_minutes": 0.0, "loss_rate": 0.1,
    }]
    detection = {
        "affected_task_ids": ["t1"], "affected_platform_ids": [],
        "event_details": {"category_count": 1}, "strong_event": False,
    }

    scope = event_trigger.identify_affected_scope(observation, detection)
    assert scope["direct_affected_task_ids"] == ["t1"]
    assert scope["coverage_debt_task_ids"] == ["new"]
    assert scope["candidate_platform_ids"] == ["n02-uav-3"]
    assert scope["scope"] == "LOCAL_REPAIR"


def test_missing_local_candidates_leave_nonempty_scope_noop() -> None:
    observation = _observation()
    observation["tasks"].append({
        "id": "new", "kind": "inspection", "position": [3.0, 2.0],
        "deadline": 50, "priority": 3, "status": "pending", "phase": "pending",
        "progress": 0.0, "assignee": None, "known": True, "service_minutes": 2,
    })
    observation["platforms"][0]["failed"] = True
    detection = {
        "affected_task_ids": ["new"], "affected_platform_ids": [],
        "event_details": {"category_count": 1}, "strong_event": False,
    }

    scope = event_trigger.identify_affected_scope(observation, detection)
    assert scope["scope"] == "NOOP"
    assert scope["global_required"] is False
    assert scope["reasons"] == ["no_public_candidate_platform"]
