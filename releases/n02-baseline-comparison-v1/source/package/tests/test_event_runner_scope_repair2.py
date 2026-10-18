from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_runner
import event_scenarios
from event_environment import EventReliefEnv


class _CountingLedger:
    def count(self, _name: str, _amount: int) -> None:
        return None


def _noop() -> list[dict]:
    return [{
        "candidate_scope": "noop",
        "legal": True,
        "full_environment_action": {"noop": True, "scope": "NOOP"},
    }]


def _assert_full_decision_masks(logs: list[dict], mode: str) -> None:
    for row in logs:
        decision = row["decision"]
        affected = row["affected_scope_detail"]
        mask = decision["high_level_mask"]
        global_required = bool(affected.get("global_required"))
        assert mask == {
            "NOOP": True,
            "LOCAL_REPAIR": bool(row["triggered"] and affected["local_eligible"] and not global_required),
            "GLOBAL_REPLAN": bool(
                row["triggered"]
                and affected["global_eligible"]
                and (
                    mode == "periodic"
                    or global_required
                    or affected.get("global_fallback_authorized_by") == "current_assignment_infeasible"
                )
            ),
        }
        assert decision["high_level_action"] in mask
        assert mask[decision["high_level_action"]] is True
        if not affected["affected_task_ids"] and not affected["affected_platform_ids"]:
            assert decision["high_level_action"] == "NOOP"


def test_m1_empty_impact_forces_noop_without_global_generation() -> None:
    calls: list[str] = []

    def generate(*args, **kwargs):
        calls.append(str(kwargs.get("scope")))
        raise AssertionError("empty public impact must not generate a global catalog")

    affected = {
        "affected_task_ids": [],
        "affected_platform_ids": [],
        "local_eligible": True,
        "global_eligible": True,
        "scope": "LOCAL_REPAIR",
        "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, generate, 16, affected, _noop()
    )
    assert calls == []
    assert len(candidates) == 1
    assert adjusted["scope"] == "NOOP"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert receipt["code"] == "no_affected_public_entities"


def test_m1_ineligible_without_affected_entities_stays_noop() -> None:
    def generate(*args, **kwargs):
        raise AssertionError("no eligible scope must not generate candidates")

    affected = {
        "affected_task_ids": [],
        "affected_platform_ids": [],
        "local_eligible": False,
        "global_eligible": False,
        "scope": "NOOP",
        "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, generate, 16, affected, _noop()
    )
    assert len(candidates) == 1
    assert adjusted["scope"] == "NOOP"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert receipt["code"] == "no_affected_public_entities"


def test_m1_empty_local_catalog_does_not_generate_global_without_authorization() -> None:
    calls: list[str] = []

    def generate(*args, **kwargs):
        calls.append(str(kwargs.get("scope")))
        raise AssertionError("local candidate absence does not authorize global planning")

    affected = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
        "local_eligible": True, "global_eligible": False,
        "scope": "LOCAL_REPAIR", "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, generate, 16, affected, _noop(), current_assignment_feasible=None,
    )

    assert calls == []
    assert len(candidates) == 1
    assert candidates[0]["full_environment_action"]["scope"] == "NOOP"
    assert adjusted["scope"] == "NOOP"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert receipt["code"] == "no_authorized_global_fallback"


def test_m1_strong_event_without_local_candidate_does_not_authorize_global() -> None:
    generated_scopes: list[str] = []
    affected = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
        "local_eligible": True, "global_eligible": False,
        "global_required": False, "scope": "LOCAL_REPAIR", "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, lambda _env, *, scope, max_candidates: generated_scopes.append(scope) or _noop(),
        4, affected, _noop(),
        current_assignment_feasible=None,
    )

    assert generated_scopes == []
    assert candidates[0]["full_environment_action"]["scope"] == "NOOP"
    assert adjusted["scope"] == "NOOP"
    assert adjusted["global_eligible"] is False
    assert "global_fallback_authorized_by" not in adjusted
    assert receipt["code"] == "no_authorized_global_fallback"


def test_terminal_historical_owner_does_not_authorize_production_global_fallback() -> None:
    scenario = next(
        row for row in event_scenarios.build_event_scenarios()
        if row["split"] == "train" and row["condition"] == "platform_failure"
    )
    env = EventReliefEnv(scenario)
    env.reset()
    noop_action = {
        "action_type": "reconstruct", "scope": "NOOP", "noop": True,
        "queue_operations": [], "dispatches": [],
    }
    for _ in range(10):
        env.step(noop_action)

    observation = env.public_observation()
    failed_platforms = {row["id"] for row in observation["platforms"] if row.get("failed")}
    historical_owners = [
        row for row in observation["tasks"]
        if row.get("assignee") in failed_platforms
    ]
    assert all(not queue for queue in observation["queues"].values())
    assert env._queue_schedule_issues(observation, env._queues) == []
    assert {row["status"] for row in historical_owners} == {"completed", "failed"}
    assert env.current_assignment_feasible() is True

    generated_scopes: list[str] = []

    def generate(_env, *, scope, max_candidates):
        generated_scopes.append(scope)
        return [{
            "candidate_key": "global-plan", "legal": True,
            "full_environment_action": {"noop": False, "scope": "GLOBAL_REPLAN"},
            "snapshot_hash": "snapshot", "event_tape_id": "tape",
        }]

    affected = {
        "affected_task_ids": [row["id"] for row in historical_owners],
        "affected_platform_ids": sorted(failed_platforms),
        "local_eligible": True, "global_eligible": True,
        "scope": "LOCAL_REPAIR", "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        env, generate, 16, affected, _noop(),
        current_assignment_feasible=env.current_assignment_feasible(),
    )

    assert generated_scopes == []
    assert candidates[0]["full_environment_action"]["scope"] == "NOOP"
    assert adjusted["scope"] == "NOOP"
    assert adjusted["global_eligible"] is False
    assert "global_fallback_authorized_by" not in adjusted
    assert receipt["code"] == "current_assignment_feasible"


def test_m1_narrow_strong_event_keeps_legal_local_candidate() -> None:
    import event_trigger

    observation = {
        "time": 12, "horizon": 60,
        "platforms": [{
            "id": "u1", "type": "uav", "position": [0.0, 0.0],
            "energy": 80.0, "energy_initial": 100.0, "capacity_kg": 20.0,
            "speed_km_min": 1.0, "energy_per_km": 1.0,
            "service_energy_per_min": 0.1, "failed": False,
            "active_task_id": "t1", "capabilities": ["inspect", "deliver"],
        }],
        "tasks": [{
            "id": "t1", "kind": "inspection", "position": [2.0, 0.0],
            "deadline": 50, "priority": 5, "status": "active",
            "phase": "to_inspection", "progress": 0.0,
            "assignee": "u1", "service_minutes": 5,
            "predecessors": [], "cooperative_with": [],
        }],
        "depots": [], "environment": [], "communication": [],
    }
    detection = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
        "event_details": {"category_count": 1}, "strong_event": True,
        "event_severity": "strong", "triggered": True,
    }
    affected = event_trigger.identify_affected_scope(observation, detection)
    assert affected["local_eligible"] is True
    assert affected["global_required"] is False

    local_action = {
        "noop": False, "scope": "LOCAL_REPAIR",
        "queue_operations": [{"op": "reorder", "platform_id": "u1", "task_id": "t1"}],
    }
    local_candidate = {
        "candidate_key": "strong-narrow-local", "legal": True,
        "full_environment_action": local_action,
        "snapshot_hash": "snapshot", "event_tape_id": "tape",
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        object(), lambda *_args, **_kwargs: [local_candidate], 4,
        affected, [* _noop(), local_candidate], current_assignment_feasible=None,
    )
    assert receipt["local_non_noop_candidate_count"] == 1
    assert candidates[-1]["full_environment_action"] == local_action
    mask = event_runner._m1_final_high_level_mask(detection, adjusted, "event", True)
    assert mask["LOCAL_REPAIR"] is True
    assert mask["GLOBAL_REPLAN"] is False
    assert candidates[-1]["legal"] is True


def test_m1_global_required_uses_global_even_when_assignment_is_feasible() -> None:
    global_action = {"noop": False, "scope": "GLOBAL_REPLAN"}
    generated_scopes: list[str] = []

    def generate(_env, *, scope, max_candidates):
        generated_scopes.append(scope)
        assert max_candidates == 4
        return [{
            "candidate_key": "global-plan", "legal": True,
            "full_environment_action": global_action,
            "snapshot_hash": "snapshot", "event_tape_id": "tape",
        }]

    affected = {
        "affected_task_ids": ["t1"], "affected_platform_ids": [],
        "local_eligible": False, "global_eligible": True,
        "global_required": True, "scope": "GLOBAL_REPLAN", "reasons": [],
    }
    candidates, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, generate, 4, affected, _noop(), current_assignment_feasible=True,
    )

    assert generated_scopes == ["GLOBAL_REPLAN"]
    assert candidates[-1]["full_environment_action"] == global_action
    assert adjusted["scope"] == "GLOBAL_REPLAN"
    assert adjusted["global_fallback_authorized_by"] == "global_scope_required"
    assert receipt["code"] == "global_scope_required"
    assert event_runner._m1_final_high_level_mask(
        {"event_severity": "light"}, adjusted, "event", True
    )["GLOBAL_REPLAN"] is True


def test_m1_public_infeasibility_probe_dict_authorizes_global_fallback() -> None:
    global_action = {"noop": False, "scope": "GLOBAL_REPLAN"}
    calls: list[str] = []

    def generate(_env, *, scope, max_candidates):
        calls.append(scope)
        return [{
            "candidate_key": "global-plan", "legal": True,
            "full_environment_action": global_action,
            "snapshot_hash": "snapshot", "event_tape_id": "tape",
        }]

    affected = {
        "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
        "local_eligible": True, "global_eligible": False,
        "scope": "LOCAL_REPAIR", "reasons": [],
    }
    _, adjusted, receipt = event_runner._m1_catalog_scope_fallback(
        None, generate, 4, affected, _noop(),
        current_assignment_feasible={"feasible": False},
    )

    assert calls == ["GLOBAL_REPLAN"]
    assert adjusted["global_fallback_authorized_by"] == "current_assignment_infeasible"
    assert receipt["code"] == "local_repair_no_feasible_solution"


def _legacy_energy_drop_fixture(event_time: int) -> dict:
    from event_scenarios import build_event_scenarios
    scenario = next(
        row for row in build_event_scenarios()
        if row["split"] == "train" and row["condition"] == "energy_drop"
    )
    # Separate mechanism diagnostic; the formal six-parent v1 tapes remain unchanged.
    import copy
    from event_scenarios import _digest, validate_event_scenario
    scenario = copy.deepcopy(scenario)
    # Explicit legacy backlog fixture isolates the local-repair mechanism.
    # This fixture is not used by build_event_scenarios or any formal run.
    from chapter1_adapter import generate_public_c1_initial_assignment
    legacy = generate_public_c1_initial_assignment(scenario["base_scenario"], seed=scenario["seed_variant"])
    scenario["base_scenario"]["chapter1_snapshot"]["queues"] = legacy["queues"]
    scenario["base_scenario"]["chapter1_snapshot"]["assignment_receipt"] = legacy["receipt"]
    scenario["queue_plan"] = copy.deepcopy(legacy["queues"])
    scenario["queue_plan"]["n02-uav-3"].append("n02-task-05")
    scenario["queue_plan"]["n02-uav-4"].append("n02-task-06")
    for event in scenario["event_tape"]:
        if event["kind"] == "energy_drop":
            event["time"], event["new_energy"] = event_time, 0.0
    scenario["event_tape_id"] = _digest(scenario["event_tape"])
    validate_event_scenario(scenario)
    return scenario


def _run_diagnostic_through_window(scenario: dict, event_time: int, monkeypatch):
    EventEnv, generate, repair, identify, build, validate, TriggerEngine, calibrate = event_runner._modules()

    class BoundedEventEnv(EventEnv):
        def step(self, action):
            observation, reward, terminated, truncated, info = super().step(action)
            if observation.get("time", 0) > event_time:
                truncated = True
            return observation, reward, terminated, truncated, info

    monkeypatch.setattr(
        event_runner, "_modules",
        lambda: (BoundedEventEnv, generate, repair, identify, build, validate, TriggerEngine, calibrate),
    )
    config_path = ROOT.parent / "configs" / "EVENT_TRIGGER_CONFIG.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return event_runner._run_m1_mode(
        scenario,
        "event",
        {
            "threshold": 0.02713750305597446,
            "weights": {
                "d_state": 0.35,
                "d_degradation": 0.30,
                "d_margin": 0.25,
                "d_uncertainty": 0.10,
            },
            "world_model_used": False,
            "source_split": "train",
        },
        config,
        _CountingLedger(),
    )


def test_diagnostic_active_task_uses_infeasible_authorized_global_fallback(monkeypatch) -> None:
    logs, _scopes, summary, used = _run_diagnostic_through_window(
        _legacy_energy_drop_fixture(6), 6, monkeypatch,
    )
    rows = [row for row in logs if row["time"] == 6]
    assert len(rows) == 1
    row = rows[0]
    task = next(task for task in row["observation"]["tasks"] if task["id"] == "n02-task-05")
    assert task["status"] == "active"
    assert row["strong_event"] is False
    assert row["affected_scope_detail"]["global_fallback_authorized_by"] == "current_assignment_infeasible"
    assert row["scope_catalog_receipt"]["local_non_noop_candidate_count"] == 0
    assert row["scope_catalog_receipt"]["global_non_noop_candidate_count"] >= 1
    assert row["decision"]["high_level_mask"]["GLOBAL_REPLAN"] is True
    assert row["decision"]["high_level_mask"]["LOCAL_REPAIR"] is False
    assert row["selected_full_environment_action"]["scope"] == "GLOBAL_REPLAN"
    assert summary["local_repair_count"] == 0
    candidate_row = next(item for item in used if item["time"] == 6)
    assert not any(
        candidate["full_environment_action"].get("scope") == "LOCAL_REPAIR"
        and candidate["full_environment_action"].get("queue_operations")
        for candidate in candidate_row["candidate_catalog"]
    )


def test_diagnostic_event_mode_executes_real_local_repair_while_task_is_queued(monkeypatch) -> None:
    """A queued task can be locally transferred after the trigger fires."""
    logs, _scopes, summary, _used = _run_diagnostic_through_window(
        _legacy_energy_drop_fixture(4), 4, monkeypatch,
    )
    local_rows = [
        row for row in logs
        if (
            row["time"] == 4
            and row["event_type"] == "platform_disturbance"
            and row["triggered"]
            and row["selected_full_environment_action"]["scope"] == "LOCAL_REPAIR"
            and not row["selected_full_environment_action"]["noop"]
        )
    ]
    assert summary["local_repair_count"] >= 1
    assert len(local_rows) == 1
    row = local_rows[0]
    assert row["effective_assignment_change"] is True
    task = next(task for task in row["observation"]["tasks"] if task["id"] == "n02-task-05")
    assert task["status"] == "pending"
    assert "n02-task-05" in row["queues_before"]["n02-uav-3"]
    assert row["assignment_after"]["n02-task-05"] != row["assignment_before"]["n02-task-05"]
    assert row["queues_after"] != row["queues_before"]
    assert row["affected_scope_detail"]["scope"] == "LOCAL_REPAIR"
    assert row["affected_scope_detail"]["direct_affected_platform_ids"] == ["n02-uav-3"]
    assert row["scope_catalog_receipt"]["local_non_noop_candidate_count"] >= 1
    assert row["decision"]["high_level_action"] == "LOCAL_REPAIR"
    assert row["decision"]["high_level_mask"]["LOCAL_REPAIR"] is True
    assert row["decision"]["high_level_mask"]["GLOBAL_REPLAN"] is False
    assert row["decision"]["high_level_mask"]["NOOP"] is True
    _assert_full_decision_masks(logs, "event")


def test_periodic_mode_persists_available_scope_mask_for_every_row() -> None:
    """Periodic decisions preserve the legal NOOP option and all available scopes."""
    from event_scenarios import build_event_scenarios

    config_path = ROOT.parent / "configs" / "EVENT_TRIGGER_CONFIG.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    scenario = next(
        row for row in build_event_scenarios()
        if row["split"] == "train" and row["condition"] == "platform_failure"
    )
    logs, _scopes, _summary, _used = event_runner._run_m1_mode(
        scenario,
        "periodic",
        {
            "threshold": 0.02713750305597446,
            "weights": {
                "d_state": 0.35,
                "d_degradation": 0.30,
                "d_margin": 0.25,
                "d_uncertainty": 0.10,
            },
            "world_model_used": False,
            "source_split": "train",
        },
        config,
        _CountingLedger(),
    )
    assert any(row["triggered"] for row in logs)
    _assert_full_decision_masks(logs, "periodic")
