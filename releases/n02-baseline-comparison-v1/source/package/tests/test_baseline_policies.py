from __future__ import annotations

import sys
import json
import math
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from civilian.baseline_policies import _pair_utility, select_rule
from civilian.event_environment import EventReliefEnv
from civilian.event_scenarios import build_event_scenarios


def _observation(platform_ids=("n02-uav-1", "p2", "p3"), task_ids=("t1", "t2", "t3"), links=None):
    platforms = [
        {"id": pid, "position": [i * 2.0, 0.0], "capabilities": ["inspect", "deliver"],
         "speed": 1.0, "energy": 100.0, "energy_per_km": 0.1,
         "service_energy_per_min": 0.01, "failed": False}
        for i, pid in enumerate(platform_ids)
    ]
    tasks = [
        {"id": tid, "kind": "inspection", "position": [float(i), 2.0], "priority": 2,
         "deadline": 20, "service_minutes": 1, "status": "pending", "assignee": None}
        for i, tid in enumerate(task_ids)
    ]
    return {
        "time": 0, "horizon": 30, "platforms": platforms, "tasks": tasks,
        "queues": {pid: [] for pid in platform_ids},
        "environment": [], "communication": links if links is not None else [
            {"source": "n02-uav-1", "target": "p2", "connected": True, "quality": 1.0},
            {"source": "p2", "target": "p3", "connected": True, "quality": 1.0},
        ],
    }


def _catalog(platform_ids=("n02-uav-1", "p2", "p3"), task_ids=("t1", "t2", "t3")):
    rows = [{"candidate_key": "NOOP", "legal": True,
             "full_environment_action": {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
                                          "queue_operations": [], "dispatches": []}}]
    for platform in platform_ids:
        for task in task_ids:
            rows.append({"candidate_key": f"{platform}:{task}", "legal": True,
                         "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                                                      "queue_operations": [], "dispatches": [{"platform_id": platform, "task_id": task}]}})
    return rows


def test_rules_are_repeatable_and_select_only_catalogue_rows():
    observation = _observation()
    candidates = _catalog()
    for method in ("greedy", "auction", "cbba_lite"):
        first = select_rule(method, observation, candidates)
        second = select_rule(method, observation, candidates)
        assert first["candidate_index"] == second["candidate_index"]
        assert first["candidate_key"] == second["candidate_key"]
        assert first["candidate_key"] in {row["candidate_key"] for row in candidates}
        assert first["full_environment_action"] == candidates[first["candidate_index"]]["full_environment_action"]


def test_auction_runs_until_stable_and_records_vector_packets_and_ties():
    observation = _observation()
    for platform in observation["platforms"]:
        platform["position"] = [0.0, 0.0]
    for task in observation["tasks"]:
        task["position"] = [5.0, 5.0]
    candidates = _catalog()
    result = select_rule("auction", observation, candidates)
    assert result["rounds"] > 2
    assert result["converged"] is True
    assert result["rule_protocol_message_count"] > 0
    assert result["protocol_payload_bytes"] > 0
    assert result["tie_break_ids"] == sorted(result["tie_break_ids"])
    assert result["protocol_receipt"]["bids"]["bids"]


def test_auction_watchdog_is_explicit_and_reports_nonconvergence():
    observation = _observation(task_ids=("t1", "t2", "t3"))
    candidates = _catalog()
    result = select_rule("auction", observation, candidates, {"auction_watchdog_rounds": 1})
    assert result["rounds"] == 1
    assert result["converged"] is False


def test_cbba_lite_propagates_over_neighbors_without_cross_partition_packets():
    platform_ids = ("n02-uav-1", "p2", "p3", "isolated")
    links = [
        {"source": "n02-uav-1", "target": "p2", "connected": True, "quality": 1.0},
        {"source": "p2", "target": "p3", "connected": True, "quality": 1.0},
    ]
    observation = _observation(platform_ids=platform_ids, links=links)
    candidates = _catalog(platform_ids=platform_ids)
    result = select_rule("cbba_lite", observation, candidates)
    neighbors = result["protocol_receipt"]["connected_neighbors"]
    assert neighbors["isolated"] == []
    assert result["rounds"] >= 3
    assert result["converged"] is True
    assert result["rule_protocol_message_count"] == 4 * result["rounds"]
    assert result["protocol_payload_bytes"] > 0
    assert "isolated" in result["tie_break_ids"]


def test_cbba_lite_watchdog_and_projection_miss_stay_inside_catalogue():
    observation = _observation()
    candidates = _catalog()
    result = select_rule("cbba_lite", observation, candidates, {"cbba_watchdog_rounds": 1})
    assert result["rounds"] == 1
    assert result["converged"] is False
    assert result["candidate_index"] < len(candidates)
    assert result["candidate_key"] in {row["candidate_key"] for row in candidates}


def test_cbba_partition_high_bid_cannot_change_coordinator_projection():
    connected = _observation(platform_ids=("n02-uav-1", "p2"), task_ids=("t1",))
    connected["tasks"][0]["position"] = [1.0, 0.0]
    candidates = _catalog(platform_ids=("n02-uav-1", "p2"), task_ids=("t1",))
    base = select_rule("cbba_lite", connected, candidates)

    partitioned = _observation(platform_ids=("n02-uav-1", "p2", "island"), task_ids=("t1",))
    partitioned["tasks"][0]["position"] = [1.0, 0.0]
    island = next(row for row in partitioned["platforms"] if row["id"] == "island")
    island["position"] = [1.0, 0.0]
    partitioned["tasks"][0]["priority"] = 100
    partitioned["communication"] = [
        {"source": "n02-uav-1", "target": "p2", "connected": True, "quality": 1.0},
    ]
    expanded = _catalog(platform_ids=("n02-uav-1", "p2", "island"), task_ids=("t1",))
    result = select_rule("cbba_lite", partitioned, expanded)
    assert result["candidate_key"] == base["candidate_key"]
    assert result["protocol_receipt"]["coordinator_component_platform_ids"] == ["n02-uav-1", "p2"]
    assert result["projection_receipt"]["desired_pairs"] == base["projection_receipt"]["desired_pairs"]


def test_nonpositive_incremental_gain_holds_current_head_assignment():
    observation = _observation(platform_ids=("n02-uav-1", "p2"), task_ids=("t1",))
    observation["platforms"][1]["position"] = [1000.0, 1000.0]
    observation["tasks"][0]["assignee"] = "n02-uav-1"
    observation["tasks"][0]["position"] = [0.0, 0.0]
    observation["queues"]["n02-uav-1"] = ["t1"]
    candidates = [
        {"candidate_key": "NOOP", "legal": True,
         "full_environment_action": {"action_type": "reconstruct", "scope": "NOOP", "noop": True, "queue_operations": [], "dispatches": []}},
        {"candidate_key": "same-head-dispatch", "legal": True,
         "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False, "queue_operations": [], "dispatches": [{"platform_id": "n02-uav-1", "task_id": "t1"}]}},
        {"candidate_key": "costly-transfer", "legal": True,
         "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                                      "queue_operations": [{"op": "transfer", "task_id": "t1", "from_platform": "n02-uav-1", "to_platform": "p2"}], "dispatches": []}},
    ]
    for method in ("greedy", "auction", "cbba_lite"):
        result = select_rule(method, observation, candidates)
        assert result["candidate_key"] == "NOOP"
        assert result["projection_receipt"]["projection_status"] == "no_feasible_candidate_pairs"


def test_public_swap_that_improves_assignment_utility_can_be_projected():
    observation = _observation(platform_ids=("n02-uav-1", "p2"), task_ids=("t1", "t2"))
    observation["platforms"][0]["position"] = [0.0, 0.0]
    observation["platforms"][1]["position"] = [10.0, 0.0]
    observation["tasks"][0].update({"position": [9.0, 0.0], "assignee": "n02-uav-1"})
    observation["tasks"][1].update({"position": [1.0, 0.0], "assignee": "p2"})
    observation["queues"]["n02-uav-1"] = ["t1"]
    observation["queues"]["p2"] = ["t2"]
    noop = _catalog(platform_ids=(), task_ids=())[0]
    swap = {"candidate_key": "swap-tasks", "legal": True,
            "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                                         "queue_operations": [{"op": "swap", "task_id": "t1", "other_task_id": "t2",
                                                               "from_platform": "n02-uav-1", "to_platform": "p2"}], "dispatches": []}}
    result = select_rule("greedy", observation, [noop, swap])
    assert result["candidate_key"] == "swap-tasks"
    assert result["projection_receipt"]["score"] > 0


def test_empty_scope_or_no_eligible_pairs_returns_legal_noop():
    observation = _observation()
    candidates = _catalog()
    result = select_rule("greedy", observation, candidates, {"affected_scope": {"affected_task_ids": []}})
    assert result["candidate_key"] == "NOOP"
    assert result["rule_protocol_message_count"] == 0


def test_private_future_and_labels_are_never_read():
    observation = _observation()
    observation["event_tape"] = object()
    observation["private_labels"] = object()
    candidates = _catalog()
    candidates[1]["future_state"] = object()
    candidates[1]["raw_label"] = object()
    result = select_rule("greedy", observation, candidates)
    assert result["candidate_key"] in {row["candidate_key"] for row in candidates}


def test_real_public_observation_uses_speed_km_min_and_grid_cell_risk():
    scenario = build_event_scenarios()[0]
    observation = EventReliefEnv(scenario).reset()
    platform = next(row for row in observation["platforms"] if row["id"] == "n02-uav-1")
    task = next(row for row in observation["tasks"] if row["kind"] == "delivery")
    depot = next(row for row in observation["depots"] if row["id"] == task["depot_id"])
    point = platform["position"]
    target = task["position"]
    depot_point = depot["position"]
    distance = math.dist(point, depot_point) + math.dist(depot_point, target)
    service = task.get("load_minutes", 1) + task.get("unload_minutes", 1)
    completion = observation["time"] + distance / platform["speed_km_min"] + service
    slack = max(0.0, task["deadline"] - observation["time"])
    urgency = 1.0 + 1.0 / (1.0 + slack)
    energy = distance * platform["energy_per_km"] + service * platform["service_energy_per_min"]
    target_cell = (math.floor(target[0]), math.floor(target[1]))
    risk = next(row["risk_level"] for row in observation["environment"] if tuple(row["grid_cell"]) == target_cell)
    expected = ((1.0 + task["priority"]) * urgency - 0.08 * distance - 0.12 * energy
                - 0.20 * distance * risk - 0.15 * max(0.0, completion - task["deadline"]))
    observed = _pair_utility(observation, {platform["id"]: platform}, {task["id"]: task},
                             platform["id"], task["id"], owner=None, queue_position=None)
    assert observed == pytest.approx(expected)


def test_failed_current_owner_can_be_rescued_with_finite_json_safe_score():
    scenario = build_event_scenarios()[0]
    observation = EventReliefEnv(scenario).reset()
    task = observation["tasks"][0]
    owner_id, target_id = "n02-uav-1", "n02-uav-3"
    owner = next(row for row in observation["platforms"] if row["id"] == owner_id)
    owner["failed"] = True
    task["assignee"] = owner_id
    for queue in observation["queues"].values():
        while task["id"] in queue:
            queue.remove(task["id"])
    observation["queues"][owner_id].append(task["id"])
    noop = _catalog(platform_ids=(), task_ids=())[0]
    rescue = {"candidate_key": "rescue-failed-owner", "legal": True,
              "full_environment_action": {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                                           "queue_operations": [],
                                           "dispatches": [{"platform_id": target_id, "task_id": task["id"]}]}}
    result = select_rule("greedy", observation, [noop, rescue])
    assert result["candidate_key"] == "rescue-failed-owner"
    assert math.isfinite(result["projection_receipt"]["score"])
    json.dumps(result, allow_nan=False)


def test_rule_receipt_reports_unsupported_split_and_cooperate_candidates():
    observation = _observation(platform_ids=("n02-uav-1",), task_ids=("t1",))
    noop = _catalog(platform_ids=(), task_ids=())[0]
    split = {"candidate_key": "split-option", "legal": True,
             "full_environment_action": {"queue_operations": [{"op": "split", "task_id": "t1", "to_platform": "n02-uav-1"}]}}
    cooperate = {"candidate_key": "cooperate-option", "legal": True,
                 "full_environment_action": {"queue_operations": [{"op": "cooperate", "task_id": "t1", "to_platform": "n02-uav-1"}]}}
    result = select_rule("cbba_lite", observation, [noop, split, cooperate])
    coverage = result["rule_receipt"]["candidate_coverage"]
    assert coverage["legal_candidate_count"] == 3
    assert coverage["unsupported_legal_candidate_count"] == 2
    assert coverage["supported_legal_candidate_fraction"] == pytest.approx(1 / 3)
    assert set(coverage["unsupported_candidate_types"]) == {"split", "cooperate"}
