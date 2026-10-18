"""Public-only C1 initial assignment and the Chapter 1 handoff contract."""

from __future__ import annotations

import copy
import math

try:
    from .baselines import choose_step_c1_actions
    from .scenario_schema import C1_ALGORITHM_ID, C1_SNAPSHOT_SOURCE, validate_scenario
    from .stable_identity import key_digest
except ImportError:
    from baselines import choose_step_c1_actions
    from scenario_schema import C1_ALGORITHM_ID, C1_SNAPSHOT_SOURCE, validate_scenario
    from stable_identity import key_digest


def _distance(left: list[float], right: list[float]) -> float:
    return math.hypot(float(left[0]) - float(right[0]), float(left[1]) - float(right[1]))


def _travel_ticks(distance: float, speed: float) -> int:
    if distance <= 1e-9:
        return 0
    return math.ceil(distance / speed - 1e-9)


def _mission_metrics(platform: dict, task: dict, depots: dict[str, dict]) -> tuple[float, float]:
    speed = float(platform["speed_km_min"])
    energy_per_km = float(platform["energy_per_km"])
    service_energy = float(platform["service_energy_per_min"])
    if task["kind"] == "inspection":
        distance = _distance(platform["position"], task["position"])
        service = float(task["service_minutes"])
        return (
            _travel_ticks(distance, speed) + service,
            distance * energy_per_km + service * service_energy,
        )
    depot = depots[task["depot_id"]]
    to_depot = _distance(platform["position"], depot["position"])
    to_task = _distance(depot["position"], task["position"])
    load = float(task["load_minutes"])
    unload = float(task["unload_minutes"])
    completion = _travel_ticks(to_depot, speed) + load + _travel_ticks(to_task, speed) + unload
    required_energy = (to_depot + to_task) * energy_per_km + (load + unload) * service_energy
    return completion, required_energy


def generate_public_c1_initial_assignment(scenario: dict, *, seed: int, schedule_backlog: bool = False) -> dict:
    """Run the existing deterministic civilian C1 rule over public t=0 inputs."""

    if type(seed) is not int or seed < 0:
        raise ValueError("C1_INITIAL_SEED")
    if schedule_backlog:
        return _generate_public_c1_backlog(scenario, seed=seed)
    known_tasks = [copy.deepcopy(task) for task in scenario["tasks"] if task["known_initial"]]
    platforms = [copy.deepcopy(platform) for platform in scenario["platforms"]]
    depots = [copy.deepcopy(depot) for depot in scenario["depots"]]
    task_by_id = {task["id"]: task for task in known_tasks}
    platform_by_id = {platform["id"]: platform for platform in platforms}
    depot_by_id = {depot["id"]: depot for depot in depots}

    public_input = {
        "schema": "civilian-public-c1-input/1",
        "seed": seed,
        "map": copy.deepcopy(scenario["map"]),
        "platforms": platforms,
        "depots": depots,
        "known_tasks": known_tasks,
    }
    observation = {
        "schema": "relief-public-observation/1",
        "time": 0,
        "horizon": int(scenario["horizon"]),
        "map": copy.deepcopy(scenario["map"]),
        "platforms": [
            {
                **copy.deepcopy(platform),
                "energy": float(platform["energy_initial"]),
                "failed": False,
                "busy": False,
            }
            for platform in platforms
        ],
        "depots": depots,
        "tasks": [
            {
                **copy.deepcopy(task),
                "status": "pending",
                "phase": "pending",
                "assignee": None,
                "original_assignee": None,
                "discovered": True,
            }
            for task in known_tasks
        ],
        "chapter1_snapshot": {
            "source": C1_SNAPSHOT_SOURCE,
            "time": 0,
            "queues": {platform["id"]: [] for platform in platforms},
        },
    }
    candidates = []
    rejected_by_task: dict[str, set[str]] = {task["id"]: set() for task in known_tasks}
    for platform_id in sorted(platform_by_id):
        platform = platform_by_id[platform_id]
        for task_id in sorted(task_by_id):
            task = task_by_id[task_id]
            required_capability = "inspect" if task["kind"] == "inspection" else "deliver"
            if required_capability not in platform["capabilities"] or bool(platform["local"]) != bool(task["local"]):
                rejected_by_task[task_id].add("no_compatible_platform")
                continue
            if task["kind"] == "delivery" and float(task["quantity"]) > float(platform["capacity_kg"]) + 1e-9:
                rejected_by_task[task_id].add("capacity_exceeded")
                continue
            if task["kind"] == "delivery":
                depot = depot_by_id[task["depot_id"]]
                stock = float(depot["stock"].get(task["commodity"], 0.0))
                if stock + 1e-9 < float(task["quantity"]):
                    rejected_by_task[task_id].add("insufficient_stock")
                    continue
            completion, required_energy = _mission_metrics(platform, task, depot_by_id)
            if float(platform["energy_initial"]) + 1e-9 < required_energy:
                rejected_by_task[task_id].add("insufficient_energy")
                continue
            candidates.append({
                "id": f"dispatch:{platform_id}:{task_id}",
                "type": "dispatch",
                "platform_id": platform_id,
                "task_id": task_id,
                "kind": task["kind"],
                "estimated_completion": float(completion),
                "required_energy": float(required_energy),
                "locked": False,
            })

    selected = choose_step_c1_actions(observation, candidates)
    queues = {platform_id: [] for platform_id in sorted(platform_by_id)}
    for action in selected:
        queues[action["platform_id"]].append(action["task_id"])
    assigned = {task_id for values in queues.values() for task_id in values}
    unassigned_reasons = {}
    for task in known_tasks:
        task_id = task["id"]
        if task_id in assigned:
            continue
        reasons = rejected_by_task[task_id]
        unassigned_reasons[task_id] = (
            sorted(reasons) if reasons else ["c1_priority_or_one_task_per_platform"]
        )

    receipt = {
        "schema": "chapter1-public-c1-assignment/1",
        "algorithm_id": C1_ALGORITHM_ID,
        "algorithm_source": "package/civilian/baselines.py:C1/choose_step_c1_actions",
        "seed": seed,
        "seed_usage": "recorded_for_reproducibility; deterministic C1 uses no random draws",
        "public_input_sha256": key_digest(public_input),
        "known_task_ids": sorted(task_by_id),
        "candidate_pair_count": len(candidates),
        "selected_action_ids": [action["id"] for action in selected],
        "assignments": copy.deepcopy(queues),
        "assignment_output_sha256": key_digest(queues),
        "feasibility": {
            "all_selected_actions_legal": True,
            "known_task_count": len(known_tasks),
            "feasible_candidate_pair_count": len(candidates),
            "assigned_task_count": len(assigned),
            "unassigned_known_task_reasons": unassigned_reasons,
        },
    }
    return {"queues": queues, "receipt": receipt}


def _generate_public_c1_backlog(scenario: dict, *, seed: int) -> dict:
    """Iterate the existing C1 selector using only projected public mission costs.

    This is a queue-planning extension, not a Chapter 1 learned solver. The
    virtual clock consumes no simulator observations, events or future tasks.
    """
    single = generate_public_c1_initial_assignment(scenario, seed=seed)
    tasks = {task["id"]: copy.deepcopy(task) for task in scenario["tasks"] if task["known_initial"]}
    platforms = {p["id"]: {**copy.deepcopy(p), "energy": float(p["energy_initial"]), "failed": False, "busy": False} for p in scenario["platforms"]}
    depots = {d["id"]: copy.deepcopy(d) for d in scenario["depots"]}
    available = {p: 0.0 for p in platforms}
    queues = {p: [] for p in sorted(platforms)}
    pending, selected_all, trace = set(tasks), [], []
    reasons = {t: set() for t in tasks}
    now = 0.0
    for _ in range(2 * len(tasks) + len(platforms) + 1):
        if not pending:
            break
        candidates = []
        for pid, platform in sorted(platforms.items()):
            if available[pid] > now + 1e-9:
                continue
            for tid in sorted(pending):
                task = tasks[tid]
                capability = "inspect" if task["kind"] == "inspection" else "deliver"
                if capability not in platform["capabilities"] or bool(platform["local"]) != bool(task["local"]):
                    reasons[tid].add("no_compatible_platform")
                    continue
                if task["kind"] == "delivery":
                    if float(task["quantity"]) > float(platform["capacity_kg"]) + 1e-9:
                        reasons[tid].add("capacity_exceeded")
                        continue
                    if float(depots[task["depot_id"]]["stock"].get(task["commodity"], 0.0)) + 1e-9 < float(task["quantity"]):
                        reasons[tid].add("insufficient_stock")
                        continue
                duration, energy = _mission_metrics(platform, task, depots)
                if energy > platform["energy"] + 1e-9:
                    reasons[tid].add("insufficient_energy")
                    continue
                if now + duration > min(float(task["deadline"]), float(scenario["horizon"])):
                    reasons[tid].add("deadline_or_horizon")
                    continue
                candidates.append({"id": f"dispatch:{pid}:{tid}", "type": "dispatch", "platform_id": pid,
                                   "task_id": tid, "kind": task["kind"], "estimated_completion": now + duration,
                                   "required_energy": energy, "locked": False})
        observation = {"time": now, "tasks": [tasks[t] for t in sorted(pending)],
                       "platforms": list(platforms.values()), "depots": list(depots.values())}
        selected = choose_step_c1_actions(observation, candidates)
        if not selected:
            later = [time for time in available.values() if time > now + 1e-9]
            if not later:
                break
            now = min(later)
            continue
        before = {"platforms": copy.deepcopy(platforms), "available_at": dict(available), "depots": copy.deepcopy(depots)}
        for action in selected:
            pid, tid = action["platform_id"], action["task_id"]
            if tid not in pending or available[pid] > now + 1e-9 or action not in candidates:
                raise ValueError("C1_BACKLOG_INVALID_SELECTED_ACTION")
            task = tasks[tid]
            queues[pid].append(tid)
            pending.remove(tid)
            available[pid] = float(action["estimated_completion"])
            platforms[pid]["position"] = copy.deepcopy(task["position"])
            platforms[pid]["energy"] -= float(action["required_energy"])
            if task["kind"] == "delivery":
                depots[task["depot_id"]]["stock"][task["commodity"]] -= float(task["quantity"])
            selected_all.append(copy.deepcopy(action))
        trace.append({"virtual_time": now, "public_candidates": copy.deepcopy(candidates), "selected_actions": copy.deepcopy(selected),
                      "state_before": before, "state_after": {"platforms": copy.deepcopy(platforms), "available_at": dict(available), "depots": copy.deepcopy(depots)}})
    else:
        raise ValueError("C1_BACKLOG_PLANNING_ITERATION_LIMIT")
    receipt = copy.deepcopy(single["receipt"])
    receipt.update({"public_input_sha256": key_digest({"single_step_public_input_sha256": single["receipt"]["public_input_sha256"],
                                                      "horizon": int(scenario["horizon"]), "schedule_backlog": True,
                                                      "queue_planning_algorithm": "public-C1-iterative-mission-projection-v1"}),
                    "assignments": copy.deepcopy(queues), "assignment_output_sha256": key_digest(queues),
                    "selected_action_ids": [a["id"] for a in selected_all],
                    "queue_planning_algorithm": "public-C1-iterative-mission-projection-v1",
                    "queue_planning_source": "package/civilian/chapter1_adapter.py:_generate_public_c1_backlog",
                    "queue_planning_trace_sha256": key_digest(trace), "queue_planning_trace": trace})
    receipt["feasibility"].update({"assigned_task_count": len(tasks)-len(pending),
                                  "unassigned_known_task_reasons": {t: sorted(reasons[t]) or ["c1_no_feasible_projected_mission"] for t in sorted(pending)}})
    return {"queues": queues, "receipt": receipt}


def normalize_initial_assignment(scenario):
    validate_scenario(scenario)
    snapshot = scenario["chapter1_snapshot"]
    handoff = {
        "schema": "relief-chapter-handoff/1",
        "source": snapshot["source"],
        "synthetic": True,
        "time": snapshot["time"],
        "units": copy.deepcopy(scenario["units"]),
        "map": copy.deepcopy(scenario["map"]),
        "platforms": copy.deepcopy(scenario["platforms"]),
        "depots": copy.deepcopy(scenario["depots"]),
        "known_tasks": [copy.deepcopy(task) for task in scenario["tasks"] if task["known_initial"]],
        "queues": copy.deepcopy(snapshot["queues"]),
    }
    if "assignment_receipt" in snapshot:
        handoff["assignment_receipt"] = copy.deepcopy(snapshot["assignment_receipt"])
    handoff["public_sha256"] = key_digest(handoff)
    return handoff
