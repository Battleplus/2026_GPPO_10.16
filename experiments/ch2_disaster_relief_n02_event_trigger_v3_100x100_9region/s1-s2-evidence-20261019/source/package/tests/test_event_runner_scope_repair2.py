from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_runner


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
        assert mask == {
            "NOOP": True,
            "LOCAL_REPAIR": bool(row["triggered"] and affected["local_eligible"] and not row["strong_event"]),
            "GLOBAL_REPLAN": bool(
                row["triggered"]
                and affected["global_eligible"]
                and (
                    mode == "periodic"
                    or row["event_severity"] != "light"
                    or row["scope_catalog_receipt"].get("code") == "local_repair_no_feasible_solution"
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


def test_diagnostic_event_mode_does_not_repair_active_tasks_after_energy_drop() -> None:
    """An energy event cannot make active queue items locally reassignable."""
    from event_scenarios import build_event_scenarios

    config_path = ROOT.parent / "configs" / "EVENT_TRIGGER_CONFIG.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
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
            event["time"], event["new_energy"] = 6, 0.0
    scenario["event_tape_id"] = _digest(scenario["event_tape"])
    validate_event_scenario(scenario)
    logs, _scopes, summary, _used = event_runner._run_m1_mode(
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

    event_rows = [
        row for row in logs
        if (
            row["time"] == 6
            and row["event_type"] == "platform_disturbance"
            and row["triggered"]
        )
    ]
    assert len(event_rows) == 1
    row = event_rows[0]
    assert summary["local_repair_count"] == 0
    assert row["affected_scope_detail"]["local_eligible"] is False
    assert row["scope_catalog_receipt"]["local_non_noop_candidate_count"] == 0
    assert row["selected_full_environment_action"]["scope"] != "LOCAL_REPAIR"
    assert not any(
        entry["feasible"]
        for entry in row["affected_scope_detail"]["resource_feasibility"]["local"].values()
    )
    assert row["affected_scope_detail"]["direct_affected_platform_ids"] == ["n02-uav-3"]
    assert row["decision"]["high_level_mask"]["LOCAL_REPAIR"] is False
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
