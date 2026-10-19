"""Deterministic 9-region event scenarios for N02 v3 CPU mechanisms."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

try:
    from .chapter1_adapter import generate_public_c1_initial_assignment
    from . import event_scenarios as legacy_event_scenarios
    from .region_contract import REGION_IDS, REGION_CONTRACT, build_region_contract, region_center, region_id_for_position
    from .scenario_schema import GRID_CELLS, MAP_COLS, MAP_CONTRACT, MAP_ROWS, validate_region_event_scenario
except ImportError:
    from chapter1_adapter import generate_public_c1_initial_assignment
    import event_scenarios as legacy_event_scenarios
    from region_contract import REGION_IDS, REGION_CONTRACT, build_region_contract, region_center, region_id_for_position
    from scenario_schema import GRID_CELLS, MAP_COLS, MAP_CONTRACT, MAP_ROWS, validate_region_event_scenario

BASE_SEED = 8201
HORIZON = 60
CONDITIONS = ("environment_perturbation", "new_arrival", "energy_drop", "platform_failure",
              "communication_drop", "regional_support", "mixed_events", "global_fallback")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _position(rid: str, dx: float, dy: float) -> list[float]:
    center = region_center(rid)
    return [round(center[0] + dx, 2), round(center[1] + dy, 2)]


def _base_scenario(parent_id: str, seed: int) -> dict:
    platforms: list[dict] = []
    uav_index = 0
    for ri, rid in enumerate(REGION_IDS):
        count = ((2, 3, 3), (3, 2, 3), (3, 3, 2))[ri // 3][ri % 3]
        offsets = [(-2.0, -1.0), (1.5, -1.0), (-1.5, 1.5)]
        for local_index in range(count):
            uav_index += 1
            position = _position(rid, *offsets[local_index])
            platforms.append({
                "id": f"n02-uav-{uav_index:02d}", "type": "uav", "position": position,
                "local": True, "region_id": rid, "region_center": region_center(rid),
                "capabilities": ["inspect", "deliver"], "capacity_kg": 10.0, "speed_km_min": 1.6,
                "energy_initial": 120.0, "energy_per_km": 1.0, "service_energy_per_min": 0.2,
            })
    non_diagonal = [rid for rid in REGION_IDS if rid not in {"r00", "r11", "r22"}]
    for index, rid in enumerate(non_diagonal, 1):
        platforms.append({
            "id": f"n02-heli-{index}", "type": "helicopter", "position": region_center(rid),
            "local": False, "region_id": None, "region_center": None, "support_scope": "global",
            "capabilities": ["inspect", "deliver"], "capacity_kg": 30.0, "speed_km_min": 2.2,
            "energy_initial": 200.0, "energy_per_km": 1.1, "service_energy_per_min": 0.3,
        })
    depots = []
    tasks = []
    task_index = 0
    for rid in REGION_IDS:
        center = region_center(rid)
        depot_id = f"depot-{rid}"
        depots.append({"id": depot_id, "position": _position(rid, -3.0, -3.0), "stock": {"water": 20.0, "medical": 20.0}})
        offsets = [(-1.5, -1.0), (1.5, -1.0), (-1.0, 1.5), (1.5, 1.5)]
        for local_index, (dx, dy) in enumerate(offsets):
            task_index += 1
            inspection = local_index == 0
            task_id = f"task-{rid}-{local_index + 1}"
            task = {
                "id": task_id, "kind": "inspection" if inspection else "delivery",
                "position": _position(rid, dx, dy), "local": True, "region_id": rid,
                "region_center": center, "known_initial": True, "deadline": 35 + local_index * 4,
                "priority": 5.0 - local_index * 0.4, "discovered_by": None, "report_delay": 0,
            }
            if inspection:
                task["service_minutes"] = 2
            else:
                task.update({"commodity": "water", "quantity": 2.0 + local_index % 2,
                             "depot_id": depot_id, "load_minutes": 1, "unload_minutes": 1})
            tasks.append(task)
        task_index += 1
        tasks.append({
            "id": f"task-{rid}-hidden", "kind": "delivery", "position": _position(rid, 0.0, 2.5),
            "local": True, "region_id": rid, "region_center": center, "known_initial": False,
            "deadline": 52, "priority": 3.5, "discovered_by": None, "report_delay": 0,
            "commodity": "medical", "quantity": 2.0, "depot_id": depot_id, "load_minutes": 1, "unload_minutes": 1,
        })
    map_data = {"grid_contract": MAP_CONTRACT, "rows": MAP_ROWS, "cols": MAP_COLS,
                "grid_cells": GRID_CELLS, "cell_km": 1.0, "local_block": [0, 0, 100, 100]}
    scenario = {
        "schema_version": "relief-engineering/2", "scenario_id": parent_id, "synthetic": True,
        "units": {"distance": "km", "time": "min", "quantity": "kg", "energy": "synthetic_unit"},
        "map": map_data, "region_contract": REGION_CONTRACT, "regions": build_region_contract(),
        "horizon": HORIZON, "dt": 1, "platforms": platforms, "depots": depots, "tasks": tasks,
        "chapter1_snapshot": {"source": "synthetic_initial_assignment", "time": 0,
                              "queues": {p["id"]: [] for p in platforms}},
        "disturbances": [],
    }
    assignment = generate_public_c1_initial_assignment(scenario, seed=seed, schedule_backlog=True)
    scenario["chapter1_snapshot"] = {"source": "civilian-public-C1/1", "time": 0,
        "queues": assignment["queues"], "assignment_receipt": assignment["receipt"]}
    return scenario


def _event_tape(condition: str, scenario: dict, seed: int) -> list[dict]:
    uavs = [p["id"] for p in scenario["platforms"] if p["type"] == "uav"]
    # The spatial mechanism witness must touch a public task that is still
    # actionable at t=12. The first inspection is often already complete by
    # then, which would correctly yield only NOOP and fail to test causality.
    target = next(t for t in scenario["tasks"] if t["known_initial"] and t["kind"] == "delivery" and t["id"] == "task-r01-4")
    target_rid = target["region_id"]
    tape: list[dict] = []
    # Keep single-event mechanism witnesses isolated. Hidden arrivals are
    # public event causes only for arrival/mixed scenarios; adding them to a
    # spatial-only tape would silently turn a local 2x2 witness into a
    # multi-region event.
    if condition in {"new_arrival", "mixed_events"}:
        hidden_tasks = sorted((t for t in scenario["tasks"] if not t["known_initial"]), key=lambda row: row["region_id"])
        for index, hidden in enumerate(hidden_tasks):
            tape.append({"time": 8 + index * 2, "kind": "task_arrival", "task_id": hidden["id"], "region_id": hidden["region_id"]})
    if condition in {"environment_perturbation", "mixed_events"}:
        x0, y0, _, _ = next(r["bounds"] for r in scenario["regions"] if r["region_id"] == target_rid)
        affected_task = target
        patch_x, patch_y = int(affected_task["position"][0]), int(affected_task["position"][1])
        patch_x, patch_y = max(x0, min(patch_x, x0 + 31)), max(y0, min(patch_y, y0 + 31))
        tape.append({"time": 12, "kind": "environment_perturbation", "patch": [patch_x, patch_y, 2, 2],
                     "region_id": target_rid, "target_type": "task", "target_id": affected_task["id"],
                     "wind_vector": [0.8, -0.5], "risk_delta": 0.35,
                     "blocked_cell": [patch_x, patch_y]})
    if condition in {"energy_drop", "mixed_events"}:
        tape.append({"time": 14, "kind": "energy_drop", "platform_id": uavs[0], "new_energy": 8.0})
    if condition in {"platform_failure", "global_fallback", "mixed_events", "regional_support"}:
        rid_by_pid = {p["id"]: p["region_id"] for p in scenario["platforms"] if p["type"] == "uav"}
        if condition == "global_fallback":
            affected = [next(pid for pid, rid in rid_by_pid.items() if rid == "r00"),
                        next(pid for pid, rid in rid_by_pid.items() if rid == "r22")]
        else:
            affected = [next(pid for pid, rid in rid_by_pid.items() if rid == target_rid)]
        for pid in affected:
            tape.append({"time": 16, "kind": "platform_failure", "platform_id": pid})
    if condition in {"communication_drop", "mixed_events", "regional_support", "global_fallback"}:
        links = [[uavs[0], uavs[1]], [uavs[5], uavs[6]]] if condition == "global_fallback" else [[uavs[0], uavs[1]]]
        tape.append({"time": 18, "kind": "communication_drop", "links": links,
                     "quality": 0.0 if condition == "global_fallback" else 0.1})
    for i, event in enumerate(tape):
        event["event_id"] = f"{condition}-{seed}-{i:02d}"
    return tape


def build_scenario(*, scenario_id: str, split: str, condition: str, seed_variant: int,
                   tape_id: str | None = None, event_tape: list[dict] | None = None) -> dict:
    """Build one event wrapper. A supplied tape can be reused across policy/mode comparisons."""
    if split not in {"train", "development"}:
        raise ValueError("split must be train or development")
    if condition not in CONDITIONS:
        raise ValueError(f"unsupported condition {condition!r}")
    base = _base_scenario(scenario_id, seed_variant)
    tape = copy.deepcopy(event_tape) if event_tape is not None else _event_tape(condition, base, seed_variant)
    actual_id = _digest(tape)
    if tape_id is not None and tape_id != actual_id:
        raise ValueError("supplied tape_id does not match event_tape")
    wrapper = {
        "parent_id": scenario_id, "split": split, "condition": condition, "seed_variant": seed_variant,
        "map": copy.deepcopy(base["map"]), "base_scenario": base,
        "queue_plan": copy.deepcopy(base["chapter1_snapshot"]["queues"]),
        "event_tape": tape, "event_tape_id": actual_id,
    }
    validate_region_event_scenario(wrapper)
    return wrapper


def build_scenario_set(train_count: int = 4, development_count: int = 2, *, tape_seed: int = BASE_SEED) -> list[dict]:
    if train_count < 4 or development_count < 2:
        raise ValueError("at least four train and two development parents are required")
    result = []
    for index in range(train_count + development_count):
        split = "train" if index < train_count else "development"
        condition = CONDITIONS[index % len(CONDITIONS)]
        seed = tape_seed + index
        sid = f"n02-v3-{split}-{index + 1:02d}-{condition}"
        result.append(build_scenario(scenario_id=sid, split=split, condition=condition, seed_variant=seed))
    return result


def build_s0_local_repair_fixture(*, seed: int = BASE_SEED, target_task_id: str = "n02-task-05",
                                  event_time: int = 4, new_priority: float = 4.9) -> dict:
    """Build a disclosed 6-platform/12-task S0 repair diagnostic from public C1 inputs.

    This is the original S0 scale, not a production 9-region scenario. The single
    public priority-change event and its time are fixture parameters; C1 queues
    are regenerated from the public base scenario and never supplied by hand.
    """
    if type(seed) is not int or seed < 0:
        raise ValueError("S0 seed must be a non-negative integer")
    if type(event_time) is not int or not 0 < event_time < HORIZON:
        raise ValueError("S0 event_time must be inside the episode")
    if not isinstance(new_priority, (int, float)) or not 0 < float(new_priority) <= 10:
        raise ValueError("S0 new_priority must be in (0, 10]")

    parent_id = f"n02-s0-repair-seed-{seed}-priority-{target_task_id}-t{event_time}"
    base = legacy_event_scenarios._base_scenario(parent_id, seed)
    target = next((task for task in base["tasks"] if task["id"] == target_task_id), None)
    if target is None or not target["known_initial"] or not target["local"]:
        raise ValueError("S0 target must be a known-initial local task")
    assignment = generate_public_c1_initial_assignment(base, seed=seed, schedule_backlog=True)
    base["chapter1_snapshot"] = {
        "source": "civilian-public-C1/1", "time": 0,
        "queues": copy.deepcopy(assignment["queues"]),
        "assignment_receipt": copy.deepcopy(assignment["receipt"]),
    }
    tape = [{
        "time": event_time, "kind": "priority_change", "task_id": target_task_id,
        "new_priority": float(new_priority), "event_id": f"s0-repair-{seed}-{target_task_id}-t{event_time}",
    }]
    wrapper = {
        "parent_id": parent_id, "split": "development", "condition": "s0_local_repair_diagnostic",
        "seed_variant": seed, "map": copy.deepcopy(base["map"]), "base_scenario": base,
        "queue_plan": copy.deepcopy(assignment["queues"]), "event_tape": tape,
        "event_tape_id": legacy_event_scenarios._digest(tape),
    }
    legacy_event_scenarios.validate_event_scenario(wrapper)
    return wrapper


def s0_fixture_receipt(scenario: dict) -> dict:
    """Describe the repair fixture's scale and intentional timeline change."""
    if scenario.get("condition") != "s0_local_repair_diagnostic":
        raise ValueError("receipt requires an S0 local-repair diagnostic fixture")
    base = scenario.get("base_scenario", {})
    tape = scenario.get("event_tape", [])
    if len(base.get("platforms", [])) != 6 or len(base.get("tasks", [])) != 12 or len(tape) != 1:
        raise ValueError("S0 diagnostic fixture shape mismatch")
    event = tape[0]
    task = next(row for row in base["tasks"] if row["id"] == event["task_id"])
    owner = next((platform_id for platform_id, queue in scenario["queue_plan"].items()
                  if event["task_id"] in queue), None)
    platform = next((row for row in base["platforms"] if row["id"] == owner), None)
    local_region_id = region_id_for_position(task["position"])
    if platform is None or region_id_for_position(platform["position"]) != local_region_id:
        raise ValueError("S0 target owner must share the target's local region")
    return {
        "schema": "s0-diagnostic-fixture-receipt/1",
        "fixture_id": scenario["parent_id"],
        "purpose": "repair-diagnostic-only",
        "study_scale": "S0-original-6-platform-12-task",
        "platform_count": 6,
        "task_count": 12,
        "production_9_region_evidence": False,
        "queue_provenance": "public-C1-backlog-generated-from-base-scenario",
        "timeline_disclosure": {
            "change": "replaced-production-event-tape-with-one-isolated-repair-diagnostic-event",
            "event_kind": event["kind"],
            "event_time": event["time"],
            "target_task_id": event["task_id"],
            "initial_owner_id": owner,
            "local_region_id": local_region_id,
        },
    }
