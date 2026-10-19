from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from event_environment import EventReliefEnv, generate_reconstruction_candidates
from event_trigger import identify_affected_scope
from region_scenarios import CONDITIONS, build_scenario, build_scenario_set


def _noop() -> dict:
    return {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
            "queue_operations": [], "dispatches": []}


def _baseline() -> list[dict]:
    rows = []
    for index in range(6):
        split = "train" if index < 4 else "development"
        condition = CONDITIONS[index]
        seed = 8201 + index
        rows.append(build_scenario(
            scenario_id=f"n02-v3-{split}-{index + 1:02d}-{condition}",
            split=split, condition=condition, seed_variant=seed,
        ))
    return rows


def test_default_s2_parent_contract_and_single_disclosed_repair() -> None:
    scenarios = build_scenario_set(4, 2, tape_seed=8201)
    baseline = _baseline()
    assert len(scenarios) == 6
    assert [row["split"] for row in scenarios] == ["train"] * 4 + ["development"] * 2
    assert [(row["parent_id"], row["seed_variant"]) for row in scenarios] == [
        (row["parent_id"], row["seed_variant"]) for row in baseline
    ]

    for index, (actual, original) in enumerate(zip(scenarios, baseline)):
        base = actual["base_scenario"]
        assert len(base["platforms"]) == 30
        assert len(base["tasks"]) == 45
        assert len(base["regions"]) == 9
        if index != 1:
            assert actual == original

    repaired = scenarios[1]
    assert repaired["parent_id"] == "n02-v3-train-02-new_arrival"
    assert repaired["seed_variant"] == 8202
    assert repaired["event_tape"] == [{
        "time": 10, "kind": "task_arrival", "task_id": "task-r01-hidden",
        "region_id": "r01", "event_id": "n02-v3-train-02-new_arrival-local-arrival-r01-t10",
    }]
    assert repaired["base_scenario"]["chapter1_snapshot"]["source"] == "civilian-public-C1/1"
    assert repaired["queue_plan"] == repaired["base_scenario"]["chapter1_snapshot"]["queues"]
    assert repaired["base_scenario"]["chapter1_snapshot"]["assignment_receipt"]["queue_planning_source"]


def test_repaired_training_arrival_has_two_effective_local_catalog_alternatives() -> None:
    scenario = build_scenario_set(4, 2, tape_seed=8201)[1]
    env = EventReliefEnv(scenario)
    observation = env.reset()
    for _ in range(10):
        observation, _, _, _, _ = env.step(_noop())

    target = next(row for row in observation["tasks"] if row["id"] == "task-r01-hidden")
    assert target["status"] == "pending"
    assert target["assignee"] is None
    scope = identify_affected_scope(observation, {
        "affected_task_ids": [target["id"]], "affected_platform_ids": [],
        "direct_region_ids": ["r01"], "event_details": {"category_count": 1},
        "strong_event": False,
    })
    assert scope["scope"] == "LOCAL_REPAIR"
    catalog = generate_reconstruction_candidates(observation, scope, env=env)
    assert any(row["legal"] and row["full_environment_action"].get("noop") for row in catalog)
    alternatives = [row for row in catalog if row["legal"] is True
                    and row["candidate_scope"] == "local"
                    and not row["full_environment_action"].get("noop")]
    assert len(alternatives) >= 2
    assert len({row["full_environment_action"]["dispatches"][0]["platform_id"]
                for row in alternatives}) >= 2
    for candidate in alternatives:
        action = candidate["full_environment_action"]
        operation = action["queue_operations"][0]
        assert operation["op"] == "insert"
        assert operation["task_id"] == target["id"]
        assert operation["from_platform"] is None
        assert operation["to_platform"] == action["dispatches"][0]["platform_id"]

        branch = EventReliefEnv(scenario)
        branch_observation = branch.reset()
        for _ in range(10):
            branch_observation, _, _, _, _ = branch.step(_noop())
        assigned, _, _, _, _ = branch.step(copy.deepcopy(action))
        assert target["id"] in branch._queues[operation["to_platform"]]
        assigned_target = next(row for row in assigned["tasks"] if row["id"] == target["id"])
        assert assigned_target["assignee"] == operation["to_platform"]
