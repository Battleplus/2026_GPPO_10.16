from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from event_environment import EventReliefEnv, generate_reconstruction_candidates
from event_trigger import TriggerEngine, identify_affected_scope
from region_scenarios import build_s0_local_repair_fixture, s0_fixture_receipt


def _noop() -> dict:
    return {
        "action_type": "reconstruct", "scope": "NOOP", "noop": True,
        "queue_operations": [], "dispatches": [],
    }


def test_s0_repair_fixture_uses_public_c1_and_executes_local_owner_transfer() -> None:
    scenario = build_s0_local_repair_fixture()
    base = scenario["base_scenario"]
    assert (len(base["platforms"]), len(base["tasks"])) == (6, 12)
    assert scenario["condition"] == "s0_local_repair_diagnostic"
    assert scenario["event_tape"] == [{
        "time": 4, "kind": "priority_change", "task_id": "n02-task-05",
        "new_priority": 4.9, "event_id": "s0-repair-8201-n02-task-05-t4",
    }]
    receipt = s0_fixture_receipt(scenario)
    assert receipt["production_9_region_evidence"] is False
    assert receipt["timeline_disclosure"]["event_time"] == 4
    assert receipt["timeline_disclosure"]["event_kind"] == "priority_change"
    assert receipt["timeline_disclosure"]["initial_owner_id"] == "n02-uav-1"
    assert receipt["timeline_disclosure"]["local_region_id"] == "r11"
    assert scenario["queue_plan"] == base["chapter1_snapshot"]["queues"]
    assert base["chapter1_snapshot"]["source"] == "civilian-public-C1/1"
    assert base["chapter1_snapshot"]["assignment_receipt"]["queue_planning_algorithm"] == (
        "public-C1-iterative-mission-projection-v1"
    )

    env = EventReliefEnv(scenario)
    observation = env.reset()
    trigger = TriggerEngine(
        {"trigger": {"threshold": 0.0, "warmup_steps": 0, "persistence_steps": 1}},
        {"threshold": 0.0, "warmup_steps": 0, "persistence_steps": 1},
    )
    previous = observation
    detection = None
    for _ in range(4):
        observation, _, _, _, _ = env.step(_noop())
        detection = trigger.detect(previous, observation)
        previous = observation

    assert detection is not None
    assert detection["event_details"]["priority_change_ids"] == ["n02-task-05"]
    assert detection["strong_event"] is False
    scope = identify_affected_scope(observation, detection)
    assert scope["scope"] == "LOCAL_REPAIR"
    assert scope["local_eligible"] is True

    target = next(row for row in observation["tasks"] if row["id"] == "n02-task-05")
    owner = target["assignee"]
    owner_row = next(row for row in observation["platforms"] if row["id"] == owner)
    assert owner is not None
    assert target["local"] is owner_row["local"] is True

    catalog = generate_reconstruction_candidates(observation, scope, env=env)
    local_alternatives = [
        row for row in catalog
        if row["legal"] and row["full_environment_action"]["scope"] == "LOCAL_REPAIR"
        and not row["full_environment_action"]["noop"]
    ]
    assert len(local_alternatives) >= 2
    transfer = next(
        row for row in local_alternatives
        if any(operation.get("op") == "transfer" for operation in row["full_environment_action"]["queue_operations"])
    )
    new_owner = next(
        row["platform_id"] for row in transfer["full_environment_action"]["dispatches"]
        if row["task_id"] == "n02-task-05"
    )
    assert new_owner != owner
    before_queue = {key: list(value) for key, value in observation["queues"].items()}

    after, _, _, _, info = env.step(transfer["full_environment_action"])

    moved = next(row for row in after["tasks"] if row["id"] == "n02-task-05")
    assert moved["assignee"] == new_owner
    assert after["queues"] != before_queue
    assert any(event.get("type") == "task_owner_change" and event.get("task_id") == "n02-task-05"
               for event in info["raw_events"])


@pytest.mark.parametrize("kwargs", [
    {"event_time": 0},
    {"event_time": 60},
    {"target_task_id": "n02-task-09"},
])
def test_s0_fixture_rejects_out_of_contract_parameters(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        build_s0_local_repair_fixture(**kwargs)
