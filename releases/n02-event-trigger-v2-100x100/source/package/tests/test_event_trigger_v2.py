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
    previous = _observation()
    high = copy.deepcopy(previous)
    high["time"] = 1
    high["platforms"][0]["position"] = [2.0, 0.0]
    high_detection = engine.detect(previous, high)
    assert engine.decide(high_detection, 1)["triggered"] is True
    low = copy.deepcopy(high)
    low["time"] = 2
    low["platforms"][0]["position"] = [2.01, 0.0]
    low_detection = engine.detect(high, low)
    released = engine.decide(low_detection, 2)
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

