"""Public-state disturbance scoring, cooldown decisions, and scope discovery."""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from typing import Any


DEFAULT_WEIGHTS = {"d_state": 0.35, "d_degradation": 0.30, "d_margin": 0.25, "d_uncertainty": 0.10}
DEFAULT_DELTA_MIN = 4
DEFAULT_WARMUP_STEPS = 0
DEFAULT_PERSISTENCE_STEPS = 1
DEFAULT_HYSTERESIS_MARGIN = 0.0
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "expired"})


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _index(rows: list[dict], field: str = "id") -> dict[str, dict]:
    return {str(row[field]): row for row in rows if isinstance(row, dict) and field in row}


def _clamp(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _setting(sources: list[dict], *keys: str, default: Any) -> Any:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key in source:
                return source[key]
    return default


def _nonnegative_int(value: Any, name: str, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _components(observation: dict) -> list[set[str]]:
    nodes = {str(row["id"]) for row in observation.get("platforms", []) if isinstance(row, dict) and "id" in row}
    adjacency = {node: set() for node in nodes}
    for link in observation.get("communication", []):
        if not link.get("connected", float(link.get("quality", 0.0)) >= 0.3):
            continue
        left, right = str(link.get("source")), str(link.get("target"))
        if left in nodes and right in nodes:
            adjacency[left].add(right)
            adjacency[right].add(left)
    result = []
    seen = set()
    for node in sorted(nodes):
        if node in seen:
            continue
        component, stack = set(), [node]
        seen.add(node)
        while stack:
            current = stack.pop()
            component.add(current)
            for neighbor in adjacency[current] - seen:
                seen.add(neighbor)
                stack.append(neighbor)
        result.append(component)
    return result


def _network_split(observation: dict) -> bool:
    return len(_components(observation)) > 1


def _task_capability(task: dict) -> str:
    return "inspect" if task.get("kind") == "inspection" else "deliver"


def _position(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        result = [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def _communication_metrics(observation: dict, start: str, end: str) -> dict[str, float | bool]:
    """Return the best public connected path quality and its latency."""
    if start == end:
        return {"connected": True, "quality": 1.0, "latency_minutes": 0.0, "loss_rate": 0.0}
    nodes = {str(row["id"]) for row in observation.get("platforms", []) if isinstance(row, dict) and "id" in row}
    if start not in nodes or end not in nodes:
        return {"connected": False, "quality": 0.0, "latency_minutes": 0.0, "loss_rate": 1.0}
    adjacency: dict[str, list[tuple[str, float, float, float]]] = {node: [] for node in nodes}
    for row in observation.get("communication", []):
        if not isinstance(row, dict):
            continue
        quality = _clamp(float(row.get("quality", 0.0)))
        connected = bool(row.get("connected", quality >= 0.3))
        if not connected or quality <= 0.0:
            continue
        left, right = str(row.get("source")), str(row.get("target"))
        if left not in nodes or right not in nodes:
            continue
        latency = max(0.0, float(row.get("latency_minutes", 0.0)))
        loss = _clamp(float(row.get("loss_rate", 1.0 - quality)))
        adjacency[left].append((right, quality, latency, loss))
        adjacency[right].append((left, quality, latency, loss))

    best: dict[str, tuple[float, float, float]] = {start: (1.0, 0.0, 0.0)}
    frontier = [start]
    while frontier:
        current = frontier.pop(0)
        quality, latency, loss = best[current]
        for neighbor, edge_quality, edge_latency, edge_loss in adjacency[current]:
            candidate = (quality * edge_quality, latency + edge_latency, 1.0 - (1.0 - loss) * (1.0 - edge_loss))
            prior = best.get(neighbor)
            if prior is None or candidate[0] > prior[0] + 1e-12 or (
                abs(candidate[0] - prior[0]) <= 1e-12 and candidate[1] < prior[1]
            ):
                best[neighbor] = candidate
                frontier.append(neighbor)
    if end not in best:
        return {"connected": False, "quality": 0.0, "latency_minutes": 0.0, "loss_rate": 1.0}
    quality, latency, loss = best[end]
    return {"connected": True, "quality": quality, "latency_minutes": latency, "loss_rate": loss}


def _task_route_metrics(observation: dict, task: dict, platform: dict) -> tuple[float, float, float]:
    """Estimate remaining route distance, service, and energy from public task phase."""
    platform_position = _position(platform.get("position")) or [0.0, 0.0]
    target = _position(task.get("position")) or platform_position
    phase = str(task.get("phase", ""))
    depots = _index(observation.get("depots", []))
    depot = depots.get(str(task.get("depot_id")), {})
    depot_position = _position(depot.get("position")) or target
    if task.get("kind") == "delivery" and phase in {"pending", "assigned", "released", "to_depot", "loading"}:
        if phase == "loading":
            distance = math.dist(platform_position, target)
        else:
            distance = math.dist(platform_position, depot_position) + math.dist(depot_position, target)
        total_service = float(task.get("load_minutes", 1)) + float(task.get("unload_minutes", 1))
    else:
        distance = math.dist(platform_position, target)
        total_service = float(task.get("service_minutes", 1))
    progress = _clamp(float(task.get("progress", 0.0)))
    remaining_service = max(0.0, total_service * (1.0 - progress))
    energy = distance * max(0.0, float(platform.get("energy_per_km", 0.0)))
    energy += remaining_service * max(0.0, float(platform.get("service_energy_per_min", 0.0)))
    speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
    return distance, remaining_service, energy


def _expected_position(platform: dict, task: dict | None, observation: dict, elapsed: float) -> tuple[list[float], float, bool]:
    start = _position(platform.get("position")) or [0.0, 0.0]
    if task is None:
        return start, 0.0, False
    phase = str(task.get("phase", ""))
    if task.get("kind") == "delivery":
        if phase in {"assigned", "to_depot", "loading"}:
            depot = _index(observation.get("depots", [])).get(str(task.get("depot_id")), {})
            target = _position(depot.get("position"))
        elif phase in {"in_transit", "to_delivery_site", "unloading", "delivery_confirmed"}:
            target = _position(task.get("position"))
        else:
            target = None
    else:
        target = _position(task.get("position")) if phase in {"assigned", "to_inspection", "observe"} else None
    if target is None:
        return start, 0.0, phase in {"loading", "unloading", "observe"}
    distance = math.dist(start, target)
    speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
    travel = min(distance, speed * max(0.0, elapsed))
    if distance <= 1e-12:
        return target, 0.0, phase in {"loading", "unloading", "observe"}
    fraction = travel / distance
    expected = [start[index] + fraction * (target[index] - start[index]) for index in range(2)]
    return expected, travel, phase in {"loading", "unloading", "observe"}


def _public_execution_residuals(previous: dict | None, current: dict) -> dict:
    """Compare current public telemetry with one-step estimates from prior public work."""
    zeros = {"position": 0.0, "energy": 0.0, "progress": 0.0}
    if not previous:
        return {"d_state": 0.0, "residuals": zeros, "platform_ids": [], "task_ids": []}
    elapsed = max(0.0, float(current.get("time", 0)) - float(previous.get("time", 0)))
    old_platforms = _index(previous.get("platforms", []))
    new_platforms = _index(current.get("platforms", []))
    old_tasks = _index(previous.get("tasks", []))
    new_tasks = _index(current.get("tasks", []))
    position_residuals, energy_residuals, progress_residuals = [], [], []
    affected_platforms, affected_tasks = set(), set()

    for platform_id in sorted(set(old_platforms) & set(new_platforms)):
        old = old_platforms[platform_id]
        now = new_platforms[platform_id]
        active_task_id = old.get("active_task_id")
        task = old_tasks.get(str(active_task_id)) if active_task_id is not None else None
        if task is None:
            task = next((row for row in old_tasks.values() if row.get("assignee") == platform_id and row.get("status") == "active"), None)
        expected, expected_distance, servicing = _expected_position(old, task, previous, elapsed)
        actual = _position(now.get("position"))
        if actual is not None:
            residual = _clamp(math.dist(expected, actual) / max(1.0, float(old.get("speed_km_min", 1.0)) * elapsed))
            position_residuals.append(residual)
            if residual > 1e-9:
                affected_platforms.add(platform_id)
        old_energy = float(old.get("energy", 0.0))
        new_energy = float(now.get("energy", old_energy))
        capacity = max(1.0, float(old.get("energy_initial", old_energy if old_energy > 0 else 1.0)))
        expected_use = expected_distance * max(0.0, float(old.get("energy_per_km", 0.0)))
        if servicing:
            expected_use += elapsed * max(0.0, float(old.get("service_energy_per_min", 0.0)))
        if "energy_used" in old and "energy_used" in now:
            observed_use = max(0.0, float(now.get("energy_used", 0.0)) - float(old.get("energy_used", 0.0)))
            energy_residual = _clamp(abs((old_energy - new_energy) - observed_use) / capacity)
        else:
            energy_residual = _clamp(abs((old_energy - new_energy) - expected_use) / capacity)
        energy_residuals.append(energy_residual)
        if energy_residual > 1e-9:
            affected_platforms.add(platform_id)

    for task_id in sorted(set(old_tasks) & set(new_tasks)):
        old = old_tasks[task_id]
        now = new_tasks[task_id]
        if old.get("status") in TERMINAL_TASK_STATUSES:
            continue
        phase = str(old.get("phase", ""))
        total_service = float(old.get("service_minutes", 0.0))
        if old.get("kind") == "delivery":
            total_service = float(old.get("load_minutes", 0.0)) + float(old.get("unload_minutes", 0.0))
        total_service = max(1.0, total_service)
        before = _clamp(float(old.get("progress", previous.get("task_progress", {}).get(task_id, 0.0))))
        after = _clamp(float(now.get("progress", current.get("task_progress", {}).get(task_id, before))))
        service_window = 0.0
        platform_id = old.get("assignee")
        platform = old_platforms.get(str(platform_id), {}) if platform_id is not None else {}
        if phase in {"observe", "loading", "unloading"}:
            service_window = elapsed
        elif platform and phase != "delivery_confirmed":
            target = None
            if old.get("kind") == "delivery" and phase in {"assigned", "to_depot"}:
                depot = _index(previous.get("depots", [])).get(str(old.get("depot_id")), {})
                target = _position(depot.get("position"))
            elif old.get("kind") == "delivery" and phase in {"in_transit", "to_delivery_site"}:
                target = _position(old.get("position"))
            elif old.get("kind") != "delivery" and phase in {"assigned", "to_inspection"}:
                target = _position(old.get("position"))
            if target is not None:
                start = _position(platform.get("position")) or target
                speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
                travel_time = math.dist(start, target) / speed
                service_window = max(0.0, elapsed - travel_time)
        expected_delta = min(max(0.0, service_window / total_service), max(0.0, 1.0 - before))
        residual = _clamp(abs((after - before) - expected_delta))
        progress_residuals.append(residual)
        if residual > 1e-9:
            affected_tasks.add(task_id)

    components = []
    for values in (position_residuals, energy_residuals, progress_residuals):
        if values:
            components.append(sum(values) / len(values))
    return {
        "d_state": _clamp(sum(components) / len(components)) if components else 0.0,
        "residuals": {
            "position": sum(position_residuals) / len(position_residuals) if position_residuals else 0.0,
            "energy": sum(energy_residuals) / len(energy_residuals) if energy_residuals else 0.0,
            "progress": sum(progress_residuals) / len(progress_residuals) if progress_residuals else 0.0,
        },
        "platform_ids": sorted(affected_platforms), "task_ids": sorted(affected_tasks),
    }


def _public_candidate_platform_ids(observation: dict, task: dict) -> list[str]:
    """Return the publicly eligible dispatch shortlist for one open task."""
    tasks = _index(observation.get("tasks", []))
    completed = {task_id for task_id, row in tasks.items() if row.get("status") == "completed"}
    if any(str(parent) not in completed for parent in task.get("predecessors", [])):
        return []
    depots = _index(observation.get("depots", []))
    depot = depots.get(str(task.get("depot_id")), {})
    stock = depot.get("stock", {})
    now = int(observation.get("time", 0))
    horizon = int(observation.get("horizon", 10**9))
    deadline = int(task.get("deadline", horizon))
    result = []
    for platform in observation.get("platforms", []):
        platform_id = str(platform.get("id", ""))
        source = _public_route_source(observation, task, platform_id)
        if not platform_id or platform.get("failed") or (platform.get("busy") and platform_id != source):
            continue
        if _task_capability(task) not in platform.get("capabilities", []):
            continue
        if task.get("kind") == "delivery":
            quantity = float(task.get("quantity", 0.0))
            if quantity > float(platform.get("capacity_kg", 0.0)) + 1e-9:
                continue
            if float(stock.get(task.get("commodity"), 0.0)) + 1e-9 < quantity:
                continue
        if not source or not _public_connected(observation, source, platform_id):
            continue
        distance, service, required_energy = _task_route_metrics(observation, task, platform)
        speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
        communication = _communication_metrics(observation, source, platform_id)
        eta = now + math.ceil(distance / speed) + math.ceil(service)
        eta += math.ceil(float(communication["latency_minutes"]))
        if eta > min(horizon, deadline) or required_energy > float(platform.get("energy", 0.0)) + 1e-9:
            continue
        result.append(platform_id)
    return sorted(set(result))


def _public_route_source(observation: dict, task: dict, candidate_platform_id: str) -> str:
    """Resolve a public route origin without inventing a coordinator for legacy fixtures."""
    source = task.get("assignee") or task.get("active_platform_id") or observation.get("coordinator_id")
    if isinstance(source, str) and source:
        return source
    if source is not None:
        return ""
    return candidate_platform_id


def _public_service_coverage(observation: dict) -> dict:
    """Summarize known pending work without an owner or a queue entry."""
    tasks = _index(observation.get("tasks", []))
    queues = observation.get("queues", {})
    queue_owner_by_task: dict[str, set[str]] = {}
    if isinstance(queues, dict):
        for platform_id, task_ids in queues.items():
            if not isinstance(task_ids, list):
                continue
            for task_id in task_ids:
                queue_owner_by_task.setdefault(str(task_id), set()).add(str(platform_id))

    open_task_ids = sorted(
        task_id for task_id, task in tasks.items()
        if task.get("status") in {"pending", "released"}
        and task.get("known", task.get("discovered", True)) is not False
    )
    unassigned = []
    eligible_by_task: dict[str, list[str]] = {}
    signature_rows = []
    for task_id in open_task_ids:
        task = tasks[task_id]
        owner = task.get("assignee") or task.get("active_platform_id")
        if owner is not None or queue_owner_by_task.get(task_id):
            continue
        unassigned.append(task_id)
        eligible = _public_candidate_platform_ids(observation, task)
        eligible_by_task[task_id] = eligible
        signature_rows.append({
            "task_id": task_id,
            "status": task.get("status"),
            "priority": task.get("priority"),
            "deadline": task.get("deadline"),
            "position": task.get("position"),
            "candidate_platform_ids": eligible,
        })
    return {
        "open_service_task_ids": open_task_ids,
        "unassigned_open_task_ids": unassigned,
        "eligible_platform_ids_by_task": eligible_by_task,
        "eligible_candidate_platform_ids": sorted({
            platform_id for platform_ids in eligible_by_task.values() for platform_id in platform_ids
        }),
        "uncovered_without_eligible_platform_ids": sorted(
            task_id for task_id, platform_ids in eligible_by_task.items() if not platform_ids
        ),
        "debt_ratio": _clamp(len(unassigned) / max(1, len(open_task_ids))),
        "public_debt_signature": _digest({
            "coordinator_id": observation.get("coordinator_id"),
            "debt": signature_rows,
        }),
    }


def _public_degradation(observation: dict) -> float:
    """Estimate current public feasibility loss without simulator truth or future events."""
    platforms = observation.get("platforms", [])
    depots = _index(observation.get("depots", []))
    completed = {row.get("id") for row in observation.get("tasks", []) if row.get("status") == "completed"}
    now = int(observation.get("time", 0))
    pending = [row for row in observation.get("tasks", []) if row.get("status") in {"pending", "assigned", "released", "active"}]
    infeasible = 0
    for task in pending:
        if any(parent not in completed for parent in task.get("predecessors", [])):
            continue
        feasible = False
        for platform in platforms:
            if _task_capability(task) not in platform.get("capabilities", []):
                continue
            if platform.get("failed") or float(platform.get("energy", 0.0)) <= 0:
                continue
            if task.get("kind") == "delivery":
                depot = depots.get(str(task.get("depot_id")), {})
                stock = float(depot.get("stock", {}).get(task.get("commodity"), 0.0))
                if stock + 1e-9 < float(task.get("quantity", 0.0)) or float(task.get("quantity", 0.0)) > float(platform.get("capacity_kg", 0.0)):
                    continue
            platform_id = str(platform.get("id", ""))
            source = _public_route_source(observation, task, platform_id)
            if not source or not platform_id:
                continue
            if not _public_connected(observation, source, platform_id):
                continue
            distance, service, estimated_energy = _task_route_metrics(observation, task, platform)
            speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
            eta = now + math.ceil(distance / speed) + math.ceil(service)
            if eta <= int(task.get("deadline", observation.get("horizon", 10**6))) and eta <= int(observation.get("horizon", 10**6)) and estimated_energy <= float(platform.get("energy", 0.0)):
                feasible = True
                break
        if not feasible:
            infeasible += 1
    return _clamp(infeasible / max(1, len(pending)))


def _margins(observation: dict) -> tuple[float, list[str], dict[str, float]]:
    """Estimate four public constraint-margin losses over unfinished work."""
    now = float(observation.get("time", 0))
    open_tasks = [row for row in observation.get("tasks", []) if row.get("status") in {"pending", "assigned", "released", "active"}]
    loss_samples: dict[str, list[float]] = {key: [] for key in ("capability", "time", "energy", "communication")}
    platforms = observation.get("platforms", [])
    for task in open_tasks:
        capable = []
        for platform in platforms:
            if platform.get("failed") or _task_capability(task) not in platform.get("capabilities", []):
                continue
            if task.get("kind") == "delivery":
                depots = _index(observation.get("depots", []))
                depot = depots.get(str(task.get("depot_id")), {})
                stock = float(depot.get("stock", {}).get(task.get("commodity"), 0.0))
                if stock + 1e-9 < float(task.get("quantity", 0.0)) or float(task.get("quantity", 0.0)) > float(platform.get("capacity_kg", 0.0)):
                    continue
            capable.append(platform)
        loss_samples["capability"].append(0.0 if capable else 1.0)
        if capable:
            deadline = float(task.get("deadline", observation.get("horizon", now)))
            remaining_time = max(0.0, deadline - now)
            time_losses, energy_losses = [], []
            for platform in capable:
                distance, service, required_energy = _task_route_metrics(observation, task, platform)
                speed = max(1e-6, float(platform.get("speed_km_min", 1.0)))
                eta = distance / speed + service
                time_losses.append(_clamp(eta / max(1.0, remaining_time)))
                available_energy = max(0.0, float(platform.get("energy", 0.0)))
                energy_losses.append(1.0 if available_energy <= 0.0 and required_energy > 0.0 else _clamp(required_energy / max(1e-9, available_energy)))
            loss_samples["time"].append(min(time_losses))
            loss_samples["energy"].append(min(energy_losses))
        else:
            loss_samples["time"].append(0.0)
            loss_samples["energy"].append(0.0)

        owner = task.get("assignee")
        if owner is None:
            loss_samples["communication"].append(0.0)
        else:
            metrics = _communication_metrics(observation, str(owner), "n02-uav-1")
            if not metrics["connected"]:
                communication_loss = 1.0
            else:
                deadline = float(task.get("deadline", observation.get("horizon", now)))
                remaining_time = max(1.0, deadline - now)
                communication_loss = max(
                    1.0 - float(metrics["quality"]), float(metrics["loss_rate"]),
                    _clamp(float(metrics["latency_minutes"]) / remaining_time),
                )
            loss_samples["communication"].append(_clamp(communication_loss))

    losses = {
        name: _clamp(sum(values) / len(values)) if values else 0.0
        for name, values in loss_samples.items()
    }
    low_platforms = [
        row["id"] for row in platforms
        if row.get("failed") or float(row.get("energy", 0.0)) <= 0.15 * max(1.0, float(row.get("energy_initial", row.get("energy", 1.0))))
    ]
    return _clamp(sum(losses.values()) / len(losses)), low_platforms, losses


def _changes(previous: dict | None, current: dict) -> dict:
    if not previous:
        return {"new_task_ids": [], "changed_platform_ids": [], "failed_platform_ids": [],
                "energy_drop_ids": [], "low_energy_entry_ids": [], "capability_change_ids": [], "load_change_ids": [],
                "environment_node_ids": [], "communication_changes": [],
                "cancelled_task_ids": [], "priority_change_ids": [], "deadline_change_ids": [],
                "task_changes": [],
                "assignment_edge_changes": [], "communication_edge_changes": [],
                "edge_changes": {"assignment": [], "communication": []},
                "event_severities": {"task": 0.0, "platform": 0.0, "environment": 0.0, "communication": 0.0},
                "category_count": 0, "network_split": _network_split(current), "network_split_new": False}
    previous_tasks = _index(previous.get("tasks", []))
    current_tasks = _index(current.get("tasks", []))
    new_ids = sorted(set(current_tasks) - set(previous_tasks))
    cancelled_ids = sorted(
        ident for ident, row in current_tasks.items()
        if ident in previous_tasks and row.get("status") == "cancelled" and previous_tasks[ident].get("status") != "cancelled"
    )
    priority_changes = [
        {"task_id": ident, "previous": previous_tasks[ident].get("priority"), "current": row.get("priority")}
        for ident, row in sorted(current_tasks.items())
        if ident in previous_tasks and row.get("priority") != previous_tasks[ident].get("priority")
    ]
    deadline_changes = [
        {"task_id": ident, "previous": previous_tasks[ident].get("deadline"), "current": row.get("deadline")}
        for ident, row in sorted(current_tasks.items())
        if ident in previous_tasks and row.get("deadline") != previous_tasks[ident].get("deadline")
    ]
    priority_ids = [row["task_id"] for row in priority_changes]
    deadline_ids = [row["task_id"] for row in deadline_changes]
    task_change_ids = sorted(set(new_ids) | set(cancelled_ids) | set(priority_ids) | set(deadline_ids))
    task_change_rows = []
    for ident in task_change_ids:
        old = previous_tasks.get(ident, {})
        row = current_tasks.get(ident, {})
        task_change_rows.append({
            "task_id": ident,
            "kind": "arrival" if ident in new_ids else "cancellation" if ident in cancelled_ids else "priority_change" if ident in priority_ids else "deadline_change",
            "previous_status": old.get("status"), "current_status": row.get("status"),
            "previous_priority": old.get("priority"), "current_priority": row.get("priority"),
            "previous_deadline": old.get("deadline"), "current_deadline": row.get("deadline"),
        })
    previous_platforms = _index(previous.get("platforms", []))
    current_platforms = _index(current.get("platforms", []))
    assignment_edge_changes = []
    for ident in sorted(set(previous_tasks) | set(current_tasks)):
        old = previous_tasks.get(ident, {})
        row = current_tasks.get(ident, {})
        old_owner = old.get("assignee") or old.get("active_platform_id")
        new_owner = row.get("assignee") or row.get("active_platform_id")
        if old_owner != new_owner:
            assignment_edge_changes.append({
                "edge_type": "assignment", "task_id": ident,
                "previous_platform_id": old_owner, "current_platform_id": new_owner,
            })
    failed_ids = sorted(
        ident for ident, row in current_platforms.items()
        if row.get("failed") and not previous_platforms.get(ident, {}).get("failed", False)
    )
    energy_ids = []
    low_energy_entry_ids = []
    for ident, row in current_platforms.items():
        if ident not in previous_platforms:
            continue
        old = previous_platforms[ident]
        capacity = max(1.0, float(old.get("energy_initial", old.get("energy", 1.0))))
        energy_drop = float(old.get("energy", 0.0)) - float(row.get("energy", old.get("energy", 0.0)))
        if "energy_used" in old and "energy_used" in row:
            expected_use = max(0.0, float(row.get("energy_used", 0.0)) - float(old.get("energy_used", 0.0)))
        else:
            expected_use = 0.0
        if energy_drop - expected_use > 0.12 * capacity:
            energy_ids.append(ident)
        reserve = 0.15 * capacity
        if float(old.get("energy", 0.0)) > reserve >= float(row.get("energy", old.get("energy", 0.0))) and not row.get("failed"):
            low_energy_entry_ids.append(ident)
    energy_ids.sort()
    low_energy_entry_ids.sort()
    capability_change_ids = sorted(
        ident for ident, row in current_platforms.items()
        if ident in previous_platforms
        and sorted(str(value) for value in row.get("capabilities", []))
        != sorted(str(value) for value in previous_platforms[ident].get("capabilities", []))
    )
    load_change_ids = sorted(
        ident for ident, row in current_platforms.items()
        if ident in previous_platforms
        and not math.isclose(
            float(row.get("capacity_kg", 0.0)),
            float(previous_platforms[ident].get("capacity_kg", 0.0)),
            rel_tol=1e-9, abs_tol=1e-9,
        )
    )
    changed_platforms = sorted(set(failed_ids) | set(energy_ids) | set(low_energy_entry_ids) | set(capability_change_ids) | set(load_change_ids))
    previous_environment = _index(previous.get("environment", []))
    current_environment = _index(current.get("environment", []))
    environment_ids = sorted(
        ident for ident, row in current_environment.items()
        if ident not in previous_environment or any(row.get(field) != previous_environment[ident].get(field) for field in ("wind_vector", "risk_level", "blocked"))
    )
    old_links = {tuple(sorted((str(row.get("source")), str(row.get("target"))))): row for row in previous.get("communication", [])}
    current_links = {tuple(sorted((str(row.get("source")), str(row.get("target"))))): row for row in current.get("communication", [])}
    communication_changes = []
    communication_impacts = []
    for key in sorted(set(old_links) | set(current_links)):
        old = old_links.get(key)
        row = current_links.get(key)
        fields = []
        if old is None or row is None:
            fields.append("link_state")
        else:
            for field in ("quality", "latency_minutes", "loss_rate", "connected"):
                old_value = old.get(field)
                new_value = row.get(field)
                if field in {"quality", "latency_minutes", "loss_rate"}:
                    try:
                        changed = abs(float(old_value or 0.0) - float(new_value or 0.0)) > 1e-9
                    except (TypeError, ValueError):
                        changed = old_value != new_value
                else:
                    changed = old_value != new_value
                if changed:
                    fields.append(field)
        if fields:
            communication_changes.append({
                "source": key[0], "target": key[1], "changed_fields": fields,
                "previous": copy_row(old) if old is not None else None,
                "current": copy_row(row) if row is not None else None,
            })
        if old is None or row is None:
            impact = 1.0 if old is not None and row is None else 0.0
        else:
            old_quality = _clamp(float(old.get("quality", 0.0)))
            new_quality = _clamp(float(row.get("quality", 0.0)))
            old_latency = max(0.0, float(old.get("latency_minutes", 0.0)))
            new_latency = max(0.0, float(row.get("latency_minutes", 0.0)))
            old_loss = _clamp(float(old.get("loss_rate", 1.0 - old_quality)))
            new_loss = _clamp(float(row.get("loss_rate", 1.0 - new_quality)))
            impact = max(
                old_quality - new_quality,
                (new_latency - old_latency) / max(1.0, old_latency),
                new_loss - old_loss,
                1.0 if old.get("connected", old_quality >= 0.3) and not row.get("connected", new_quality >= 0.3) else 0.0,
            )
        communication_impacts.append(_clamp(impact))
    urgent_task_changes = sum(
        float(current_tasks[item].get("priority", 0.0)) >= 5.0
        or float(current_tasks[item].get("deadline", 10**9)) - float(current.get("time", 0)) <= 6.0
        for item in task_change_ids if item in current_tasks and item not in cancelled_ids
    )
    capability_impacts = {
        ident: min(
            1.0,
            len(
                set(str(value) for value in previous_platforms[ident].get("capabilities", []))
                ^ set(str(value) for value in current_platforms[ident].get("capabilities", []))
            ) / max(1.0, len(set(str(value) for value in previous_platforms[ident].get("capabilities", [])))),
        )
        for ident in capability_change_ids
    }
    load_impacts = {
        ident: min(
            1.0,
            abs(float(previous_platforms[ident].get("capacity_kg", 0.0)) - float(current_platforms[ident].get("capacity_kg", 0.0)))
            / max(1.0, abs(float(previous_platforms[ident].get("capacity_kg", 0.0)))),
        )
        for ident in load_change_ids
    }
    platform_impact = max(
        1.0 if low_energy_entry_ids else 0.0,
        max(capability_impacts.values(), default=0.0),
        max(load_impacts.values(), default=0.0),
        0.45 * min(1.0, len(energy_ids) / 2.0) + 0.55 * max((
            (float(previous_platforms[item].get("energy", 0.0)) - float(current_platforms[item].get("energy", 0.0)))
            / max(1.0, float(previous_platforms[item].get("energy_initial", previous_platforms[item].get("energy", 1.0))))
            for item in energy_ids), default=0.0),
    )
    severities = {
        "task": _clamp(0.55 * min(1.0, len(task_change_ids) / 2.0) + 0.45 * urgent_task_changes / max(1, len(task_change_ids))),
        "platform": 1.0 if failed_ids else _clamp(platform_impact),
        "environment": _clamp(len(environment_ids) / 4.0),
        "communication": _clamp(max(communication_impacts, default=0.0) + (0.55 if len(_components(current)) > len(_components(previous)) else 0.0)),
    }
    category_count = sum(value > 0 for value in severities.values())
    communication_edge_changes = copy_row(communication_changes)
    edge_changes = {
        "assignment": copy_row(assignment_edge_changes),
        "communication": communication_edge_changes,
    }
    network_split = _network_split(current)
    return {"new_task_ids": new_ids, "cancelled_task_ids": cancelled_ids,
            "priority_change_ids": priority_ids, "deadline_change_ids": deadline_ids,
            "task_changes": task_change_rows, "changed_task_ids": task_change_ids,
            "changed_platform_ids": changed_platforms,
            "failed_platform_ids": failed_ids, "energy_drop_ids": energy_ids,
            "low_energy_entry_ids": low_energy_entry_ids,
            "capability_change_ids": capability_change_ids, "load_change_ids": load_change_ids,
            "environment_node_ids": environment_ids, "communication_changes": communication_changes,
            "assignment_edge_changes": assignment_edge_changes,
            "communication_edge_changes": communication_edge_changes,
            "edge_changes": edge_changes,
            "event_severities": severities, "category_count": category_count,
            "network_split": network_split,
            "network_split_new": bool(network_split and not _network_split(previous))}


def copy_row(value: dict) -> dict:
    return json.loads(json.dumps(value, sort_keys=True))


class TriggerEngine:
    """Threshold trigger with explicit cooldown state and strong-event bypass."""

    def __init__(self, config: dict | None, threshold_manifest: dict):
        self.config = dict(config or {})
        self.threshold_manifest = dict(threshold_manifest or {})
        trigger_config = self.config.get("trigger") if isinstance(self.config.get("trigger"), dict) else {}
        manifest_trigger = self.threshold_manifest.get("trigger") if isinstance(self.threshold_manifest.get("trigger"), dict) else {}
        settings = [self.threshold_manifest, manifest_trigger, self.config, trigger_config]
        self.weights = dict(_setting(settings, "weights", default=DEFAULT_WEIGHTS))
        if set(self.weights) != set(DEFAULT_WEIGHTS):
            raise ValueError("trigger weights must define d_state, d_degradation, d_margin, and d_uncertainty")
        self.delta_min = _nonnegative_int(_setting(settings, "delta_min", default=DEFAULT_DELTA_MIN), "delta_min", DEFAULT_DELTA_MIN)
        if self.delta_min < 0:
            raise ValueError("delta_min must be non-negative")
        self.threshold = float(_setting(settings, "threshold", "tau", default=0.5))
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        self.warmup_steps = _nonnegative_int(
            _setting(settings, "warmup_steps", "warm_up_steps", "warmup", default=DEFAULT_WARMUP_STEPS),
            "warmup_steps", DEFAULT_WARMUP_STEPS,
        )
        self.persistence_steps = max(1, _nonnegative_int(
            _setting(settings, "persistence_steps", "persistence", default=DEFAULT_PERSISTENCE_STEPS),
            "persistence_steps", DEFAULT_PERSISTENCE_STEPS,
        ))
        raw_hysteresis = _setting(settings, "hysteresis_margin", "hysteresis", default=DEFAULT_HYSTERESIS_MARGIN)
        if isinstance(raw_hysteresis, dict):
            raw_hysteresis = raw_hysteresis.get("margin", raw_hysteresis.get("delta", DEFAULT_HYSTERESIS_MARGIN))
        self.hysteresis_margin = float(raw_hysteresis)
        if not math.isfinite(self.hysteresis_margin) or not 0.0 <= self.hysteresis_margin < 1.0:
            raise ValueError("hysteresis_margin must be a relative fraction in [0, 1)")
        self.threshold_high = self.threshold
        self.threshold_low = self.threshold_high * (1.0 - self.hysteresis_margin)
        manifest_high = _setting(settings, "threshold_high", "tau_on", default=None)
        manifest_low = _setting(settings, "threshold_low", "tau_off", default=None)
        if manifest_high is not None and not math.isclose(float(manifest_high), self.threshold_high, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("threshold_high must match the training threshold manifest")
        if manifest_low is not None and not math.isclose(float(manifest_low), self.threshold_low, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("threshold_low must be derived from the training threshold manifest")
        self.residual_only = bool(_setting(settings, "residual_only", default=False))
        self._last_trigger_time: int | None = None
        self._last_reconstruction_time: int | None = None
        self._last_detection: dict | None = None
        self._observations_seen = 0
        self._persistence_count = 0
        self._hysteresis_latched = False
        self._service_debt_signature: str | None = None
        self._last_service_debt_retry_time: int | None = None

    def detect(self, previous_public: dict | None, current_public: dict, history: list[dict] | None = None,
               wm_summary: dict | None = None) -> dict:
        del history  # Explicitly accepted to keep the temporal model API stable; inputs remain public observations.
        self._observations_seen += 1
        warmup_complete = self._observations_seen > self.warmup_steps
        changes = _changes(previous_public, current_public)
        severities = changes["event_severities"]
        execution_residuals = _public_execution_residuals(previous_public, current_public)
        d_state_execution = float(execution_residuals["d_state"])
        d_state_structural = max((float(value) for value in severities.values()), default=0.0)
        d_state = max(d_state_execution, d_state_structural)
        changes["execution_residuals"] = execution_residuals["residuals"]
        changes["execution_residual_platform_ids"] = execution_residuals["platform_ids"]
        changes["execution_residual_task_ids"] = execution_residuals["task_ids"]
        changes["d_state_execution"] = d_state_execution
        changes["d_state_structural"] = d_state_structural
        changes["structural_change_components"] = dict(severities)
        service_coverage = _public_service_coverage(current_public)
        debt_signature = str(service_coverage["public_debt_signature"])
        service_debt_changed = debt_signature != self._service_debt_signature
        self._service_debt_signature = debt_signature
        service_debt_tasks = list(service_coverage["unassigned_open_task_ids"])
        eligible_service_candidates = list(service_coverage["eligible_candidate_platform_ids"])
        retry_anchor = self._last_service_debt_retry_time
        if retry_anchor is None:
            retry_anchor = self._last_reconstruction_time
        service_retry_interval_elapsed = (
            retry_anchor is None
            or int(current_public.get("time", 0)) - retry_anchor >= self.delta_min
        )
        service_debt_retry_due = bool(
            service_debt_tasks and (
                service_debt_changed
                or (eligible_service_candidates and service_retry_interval_elapsed)
            )
        )
        if self.residual_only:
            d_state_structural = 0.0
            d_state = d_state_execution
            changes["d_state_structural"] = 0.0
        previous_degradation = _public_degradation(previous_public) if previous_public else 0.0
        current_degradation = _public_degradation(current_public)
        if isinstance(wm_summary, dict):
            d_degradation = _clamp(wm_summary.get("d_degradation", wm_summary.get("degradation", current_degradation)))
            d_uncertainty = _clamp(wm_summary.get("d_uncertainty", wm_summary.get("uncertainty", 0.0)))
        else:
            d_degradation = _clamp(max(0.0, current_degradation - previous_degradation))
            d_uncertainty = 0.0
        d_margin, low_platforms, margin_losses = _margins(current_public)
        residual_only = bool(self.residual_only)
        raw_d_degradation, raw_d_margin, raw_d_uncertainty = d_degradation, d_margin, d_uncertainty
        if residual_only:
            # Structural changes remain in event_details for audit, while this
            # trigger stream responds only to public execution residuals.
            d_degradation = 0.0
            d_margin = 0.0
            d_uncertainty = 0.0
            severities = {key: 0.0 for key in severities}
            low_platforms = []
        gamma = sum(float(self.weights[key]) * value for key, value in {
            "d_state": d_state, "d_degradation": d_degradation,
            "d_margin": d_margin, "d_uncertainty": d_uncertainty,
        }.items())
        new_tasks = _index(current_public.get("tasks", []))
        critical_arrival = any(
            float(new_tasks[task_id].get("priority", 0.0)) >= 5.0
            or int(new_tasks[task_id].get("deadline", 10**9)) - int(current_public.get("time", 0)) <= 4
            for task_id in changes["new_task_ids"]
        )
        previous_tasks = _index(previous_public.get("tasks", [])) if previous_public else {}
        newly_critical_change = any(
            (float(previous_tasks.get(task_id, {}).get("priority", 0.0)) < 5.0 <= float(new_tasks[task_id].get("priority", 0.0)))
            or (float(previous_tasks.get(task_id, {}).get("deadline", 10**9)) - int(current_public.get("time", 0)) > 4
                >= float(new_tasks[task_id].get("deadline", 10**9)) - int(current_public.get("time", 0)))
            for task_id in set(changes.get("priority_change_ids", [])) | set(changes.get("deadline_change_ids", []))
            if task_id in new_tasks
        )
        strong = bool(changes["failed_platform_ids"] or critical_arrival or
                      newly_critical_change or
                      (changes["network_split"] and previous_public and not _network_split(previous_public)))
        if residual_only:
            strong = False
        event_type = "mixed" if changes["category_count"] > 1 else next(
            (name for name, value in severities.items() if value > 0), "none"
        )
        if event_type in {"task", "platform", "environment", "communication"}:
            event_type = {"task": "task_disturbance", "platform": "platform_disturbance",
                          "environment": "environment_disturbance", "communication": "communication_disturbance"}[event_type]
        if event_type == "none" and d_state > 0.0:
            event_type = "execution_residual"
        # Only execution-residual signals need consecutive high-threshold hits.
        if event_type == "execution_residual" and gamma >= self.threshold_high:
            self._persistence_count += 1
        else:
            self._persistence_count = 0
        event_severity = "strong" if strong else "moderate" if gamma >= self.threshold else "light"
        affected_task_ids = sorted(set(changes.get("changed_task_ids", changes["new_task_ids"])))
        affected_platform_ids = sorted(set(changes["changed_platform_ids"]))
        if residual_only:
            affected_task_ids = list(execution_residuals["task_ids"])
            affected_platform_ids = list(execution_residuals["platform_ids"])
        elif event_type == "execution_residual":
            affected_task_ids = sorted(set(affected_task_ids) | set(execution_residuals["task_ids"]))
            affected_platform_ids = sorted(set(affected_platform_ids) | set(execution_residuals["platform_ids"]))
        residual_signal = bool(execution_residuals["task_ids"] or execution_residuals["platform_ids"] or d_state > 0.0)
        result = {
            "schema": "event-detection/1", "time": int(current_public.get("time", 0)),
            "event_type": event_type, "event_severity": event_severity,
            "d_task": severities["task"], "d_platform": severities["platform"],
            "d_environment": severities["environment"], "d_communication": severities["communication"],
            "d_state": d_state, "d_degradation": d_degradation, "d_margin": d_margin,
            "d_uncertainty": d_uncertainty, "gamma_value": float(gamma), "threshold": self.threshold,
            "threshold_high": self.threshold_high, "threshold_low": self.threshold_low,
            "warmup_steps": self.warmup_steps, "warmup_complete": warmup_complete,
            "warmup_remaining": max(0, self.warmup_steps - self._observations_seen + 1),
            "persistence_steps": self.persistence_steps, "persistence_count": self._persistence_count,
            "hysteresis_margin": self.hysteresis_margin, "hysteresis_latched": self._hysteresis_latched,
            "hysteresis_active": self._hysteresis_latched,
            "residual_only": residual_only, "residual_signal": residual_signal,
            "raw_d_degradation": raw_d_degradation, "raw_d_margin": raw_d_margin,
            "raw_d_uncertainty": raw_d_uncertainty,
            "constraint_margin_losses": dict(margin_losses),
            "d_margin_capability": margin_losses["capability"],
            "d_margin_time": margin_losses["time"],
            "d_margin_energy": margin_losses["energy"],
            "d_margin_communication": margin_losses["communication"],
            "d_state_execution": d_state_execution,
            "d_state_structural": d_state_structural,
            "service_coverage": service_coverage,
            "coverage_debt_task_ids": service_debt_tasks,
            "coverage_debt_candidate_platform_ids": eligible_service_candidates,
            "service_debt_retry_due": service_debt_retry_due,
            "service_debt_state_changed": service_debt_changed,
            "triggered": False, "cooldown_suppressed": False, "strong_event": strong,
            "affected_task_ids": affected_task_ids,
            "affected_platform_ids": affected_platform_ids,
            "event_details": changes, "edge_changes": copy_row(changes.get("edge_changes", {})),
            "assignment_edge_changes": copy_row(changes.get("assignment_edge_changes", [])),
            "communication_edge_changes": copy_row(changes.get("communication_edge_changes", [])),
            "weights": dict(self.weights),
        }
        self._last_detection = copy_row(result)
        return result

    def decide(self, detection: dict, time: int, mode: str = "event") -> dict:
        if mode not in {"event", "periodic"}:
            raise ValueError("mode must be 'event' or 'periodic'")
        if type(time) is not int or time < 0:
            raise ValueError("time must be a non-negative integer")
        strong = bool(detection.get("strong_event"))
        gamma = float(detection.get("gamma_value", 0.0))
        threshold_hit = gamma >= float(detection.get("threshold_high", detection.get("threshold", self.threshold)))
        threshold_low = float(detection.get("threshold_low", self.threshold_low))
        warmup_complete = bool(detection.get("warmup_complete", True))
        # Older synthetic callers supplied only gamma/threshold.  Preserve
        # that API by treating an omitted persistence field as already ready;
        # real detections always include the detector-maintained count.
        persistence_value = detection.get("persistence_count", self.persistence_steps)
        persistence_ready = int(persistence_value) >= self.persistence_steps
        persistence_required = detection.get("event_type") == "execution_residual"
        residual_only = bool(detection.get("residual_only", self.residual_only))
        residual_signal = bool(detection.get("residual_signal", True))
        service_debt_retry_due = bool(detection.get("service_debt_retry_due", False)) and not residual_only
        hysteresis_enabled = (
            self.hysteresis_margin > 0.0
            or float(detection.get("hysteresis_margin", 0.0)) > 0.0
            or threshold_low < float(detection.get("threshold_high", detection.get("threshold", self.threshold)))
        )
        previous_active = self._hysteresis_latched
        elapsed_reconstruction = None if self._last_reconstruction_time is None else time - self._last_reconstruction_time
        elapsed_trigger = None if self._last_trigger_time is None else time - self._last_trigger_time
        cooldown_active = elapsed_reconstruction is not None and elapsed_reconstruction < self.delta_min
        suppression_reason = ""
        trigger_edge = "none"
        if mode == "periodic":
            triggered = time % max(1, self.delta_min) == 0
            suppressed = False
        elif strong:
            triggered, suppressed = True, False
            trigger_edge = "rising" if not previous_active else "held"
            self._hysteresis_latched = True
        elif residual_only and not residual_signal:
            triggered, suppressed = False, True
            suppression_reason = "residual_only_without_signal"
        elif not warmup_complete:
            triggered, suppressed = False, True
            suppression_reason = "warmup"
        elif service_debt_retry_due:
            if cooldown_active:
                triggered, suppressed = False, True
                suppression_reason = "cooldown"
            else:
                triggered, suppressed = True, False
                trigger_edge = "rising" if not previous_active else "service_debt_retry"
                self._hysteresis_latched = True
        elif not threshold_hit:
            triggered, suppressed = False, False
            if hysteresis_enabled and previous_active and gamma <= threshold_low:
                self._hysteresis_latched = False
                trigger_edge = "falling"
                suppression_reason = "hysteresis_release"
            elif hysteresis_enabled and previous_active:
                trigger_edge = "held"
                suppression_reason = "hysteresis_active"
            else:
                suppression_reason = "below_threshold"
        elif persistence_required and not persistence_ready:
            triggered, suppressed = False, True
            suppression_reason = "persistence"
        elif hysteresis_enabled and self._hysteresis_latched:
            triggered, suppressed = False, True
            trigger_edge = "held"
            suppression_reason = "hysteresis_active"
        elif threshold_hit and cooldown_active:
            triggered, suppressed = False, True
            suppression_reason = "cooldown"
        else:
            triggered, suppressed = True, False
            trigger_edge = "rising"
            self._hysteresis_latched = True
        explicit_empty_scope = (
            "affected_task_ids" in detection and "affected_platform_ids" in detection
            and not detection.get("affected_task_ids") and not detection.get("affected_platform_ids")
            and not detection.get("coverage_debt_task_ids")
        )
        # A deliberately empty catalog scope is a strict NOOP.  A detector
        # may still report a residual-only state change without entity ids;
        # that signal must be allowed to clear a latched event via hysteresis.
        empty_domain_asserted = explicit_empty_scope and detection.get("event_type", "none") == "none" \
            and not detection.get("residual_signal", False)
        releasing_latch = hysteresis_enabled and previous_active and gamma <= threshold_low
        if empty_domain_asserted and not strong and not releasing_latch:
            triggered, suppressed = False, True
            suppression_reason = "empty_impact_domain"
            self._hysteresis_latched = False
            trigger_edge = "none"
        if triggered:
            self._last_trigger_time = time
            if detection.get("coverage_debt_task_ids"):
                self._last_service_debt_retry_time = time
        affected = identify_affected_scope_from_detection(detection)
        mask = high_level_action_mask(detection, affected)
        result = {
            "schema": "event-trigger-decision/1", "time": time, "mode": mode,
            "gamma_value": gamma,
            "threshold": float(detection.get("threshold", self.threshold)),
            "threshold_high": float(detection.get("threshold_high", self.threshold_high)),
            "threshold_low": threshold_low,
            "strong_event": strong, "triggered": triggered, "cooldown_suppressed": suppressed,
            "trigger_edge": trigger_edge, "persistence_count": int(persistence_value),
            "persistence_ready": persistence_ready, "persistence_required": persistence_required,
            "event_active": self._hysteresis_latched,
            "residual_only": residual_only, "trigger_suppression_reason": suppression_reason,
            "cooldown_active": cooldown_active, "minutes_since_reconstruction": elapsed_reconstruction,
            "minutes_since_trigger": elapsed_trigger,
            "high_level_action": "GLOBAL_REPLAN" if triggered and affected["scope"] == "GLOBAL_REPLAN" else "LOCAL_REPAIR" if triggered else "NOOP",
            "high_level_mask": mask, "affected_scope": affected,
        }
        detection.update({"triggered": triggered, "cooldown_suppressed": suppressed,
                          "trigger_edge": trigger_edge, "event_active": self._hysteresis_latched,
                          "trigger_suppression_reason": suppression_reason})
        return result

    def record_reconstruction(self, time: int, effective: bool) -> None:
        """Advance the cooldown clock only after a real allocation mutation."""
        if type(time) is not int or time < 0:
            raise ValueError("time must be a non-negative integer")
        if type(effective) is not bool:
            raise ValueError("effective must be a bool")
        if effective:
            self._last_reconstruction_time = time


def identify_affected_scope_from_detection(detection: dict) -> dict:
    direct_task_ids = sorted(set(detection.get("affected_task_ids", [])))
    debt_task_ids = sorted(set(detection.get("coverage_debt_task_ids", [])))
    task_ids = sorted(set(direct_task_ids) | set(debt_task_ids))
    platform_ids = sorted(set(detection.get("affected_platform_ids", [])))
    candidate_platform_ids = sorted(set(platform_ids) | set(detection.get("coverage_debt_candidate_platform_ids", [])))
    empty = not task_ids and not platform_ids
    details = detection.get("event_details", {}) if isinstance(detection.get("event_details"), dict) else {}
    global_required = bool(
        not empty and (
            bool(details.get("network_split_new", False))
            or bool(details.get("network_split", False))
            or int(details.get("category_count", 0)) > 1
        )
    )
    return {
        "affected_task_ids": task_ids,
        "affected_platform_ids": platform_ids,
        "direct_affected_task_ids": direct_task_ids,
        "coverage_debt_task_ids": debt_task_ids,
        "closure_affected_task_ids": [],
        "direct_affected_platform_ids": platform_ids,
        "closure_affected_platform_ids": [],
        "candidate_platform_ids": candidate_platform_ids,
        "local_eligible": bool(not empty and candidate_platform_ids and not global_required),
        "global_eligible": bool(global_required),
        "global_required": global_required,
        "scope": "GLOBAL_REPLAN" if global_required else "LOCAL_REPAIR" if candidate_platform_ids else "NOOP",
        "connectivity": {"components": [], "connected": True},
        "reasons": (["global_required"] if global_required else ["threshold_event"])
        if not empty and candidate_platform_ids else ["empty_impact_domain"] if empty else ["no_public_candidate_platform"],
    }


def identify_affected_scope(public_observation: dict, detection: dict) -> dict:
    """Close affected tasks over public predecessor/cooperation edges and connected platforms."""
    tasks = _index(public_observation.get("tasks", []))
    platforms = _index(public_observation.get("platforms", []))
    components = _components(public_observation)
    component_by_platform = {platform_id: index for index, component in enumerate(components) for platform_id in component}
    live_tasks = {
        task_id: task for task_id, task in tasks.items()
        if task.get("status") not in TERMINAL_TASK_STATUSES
    }
    direct_tasks = set(detection.get("affected_task_ids", [])) & set(live_tasks)
    service_coverage = _public_service_coverage(public_observation)
    debt_tasks = set(service_coverage["unassigned_open_task_ids"]) & set(live_tasks)
    affected_tasks = direct_tasks | debt_tasks
    affected_platforms = set(detection.get("affected_platform_ids", [])) & set(platforms)
    direct_platforms = set(affected_platforms)
    details = detection.get("event_details", {})
    failed = set(details.get("failed_platform_ids", []))
    capability_changed = set(details.get("capability_change_ids", []))
    load_changed = set(details.get("load_change_ids", []))
    energy_low = set(details.get("energy_drop_ids", [])) | set(details.get("low_energy_entry_ids", []))
    platform_disturbances = failed | capability_changed | load_changed | energy_low
    affected_platforms.update(platform_disturbances & set(platforms))
    for task_id, task in live_tasks.items():
        if task.get("assignee") in platform_disturbances:
            affected_tasks.add(task_id)
    changed_cells = {
        tuple(node.get("grid_cell", [])) for node in public_observation.get("environment", [])
        if node.get("id") in set(details.get("environment_node_ids", []))
    }
    for task_id, task in live_tasks.items():
        position = task.get("position", [None, None])
        if len(position) == 2 and None not in position and (math.floor(float(position[0])), math.floor(float(position[1]))) in changed_cells:
            affected_tasks.add(task_id)
    graph: dict[str, set[str]] = {task_id: set() for task_id in live_tasks}
    for task_id, task in live_tasks.items():
        for neighbor in task.get("predecessors", []) + task.get("cooperative_with", []):
            if neighbor in live_tasks:
                graph[task_id].add(neighbor)
                graph[neighbor].add(task_id)
    queue = deque(affected_tasks)
    while queue:
        current = queue.popleft()
        for neighbor in graph.get(current, set()):
            if neighbor not in affected_tasks:
                affected_tasks.add(neighbor)
                queue.append(neighbor)
    for task_id in affected_tasks:
        owner = live_tasks.get(task_id, {}).get("assignee")
        if owner in platforms:
            affected_platforms.add(owner)
    candidate_platforms = set()
    for task_id in affected_tasks:
        task = live_tasks.get(task_id)
        if task is not None:
            candidate_platforms.update(_public_candidate_platform_ids(public_observation, task))
    closure_tasks = set(affected_tasks) - direct_tasks - debt_tasks
    closure_platforms = set(affected_platforms) - direct_platforms
    affected_components = sorted({component_by_platform[pid] for pid in affected_platforms if pid in component_by_platform})
    event_count = int(details.get("category_count", 0))
    task_limit, platform_limit = 6, 4
    key_failure = any(platforms.get(pid, {}).get("type") == "helicopter" for pid in failed)
    split = bool(details.get("network_split_new", False))
    overlapping_events = event_count > 1 and bool(affected_tasks)
    global_required = bool(
        len(affected_tasks) > task_limit
        or len(affected_platforms) > platform_limit
        or len(affected_components) > 1
        or key_failure
        or split
        or overlapping_events
    )
    local_eligible = bool(candidate_platforms) and (
        len(affected_tasks) <= task_limit
        and len(affected_platforms) <= platform_limit
        and len(affected_components) <= 1
        and not key_failure
        and not split
        and not overlapping_events
    )
    # A strong event bypasses trigger persistence; it does not by itself
    # force a global replan. Global scope is reserved for broad or coupled
    # impact, key-platform failure, split connectivity, or overlap.
    global_eligible = global_required
    reasons = []
    if len(affected_tasks) > task_limit:
        reasons.append("affected_task_limit_exceeded")
    if len(affected_platforms) > platform_limit:
        reasons.append("affected_platform_limit_exceeded")
    if len(affected_components) > 1 or split:
        reasons.append("communication_graph_split")
    if key_failure:
        reasons.append("key_platform_failure")
    if capability_changed:
        reasons.append("capability_disturbance")
    if load_changed:
        reasons.append("load_disturbance")
    if overlapping_events:
        reasons.append("overlapping_multiple_events")
    if not affected_tasks and not affected_platforms:
        return {
            "affected_task_ids": [], "affected_platform_ids": [],
            "direct_affected_task_ids": sorted(direct_tasks),
            "coverage_debt_task_ids": [],
            "closure_affected_task_ids": [],
            "direct_affected_platform_ids": sorted(direct_platforms),
            "closure_affected_platform_ids": [], "candidate_platform_ids": [],
            "local_eligible": False, "global_eligible": False, "global_required": False, "scope": "NOOP",
            "strong_event": bool(detection.get("strong_event")),
            "connectivity": {"components": [sorted(row) for row in components], "affected_component_ids": [], "connected": True},
            "reasons": ["empty_impact_domain"],
        }
    if not candidate_platforms and not global_required:
        reasons.append("no_public_candidate_platform")
    if not reasons:
        reasons.append("connected_local_impact")
    return {
        "affected_task_ids": sorted(affected_tasks), "affected_platform_ids": sorted(affected_platforms),
        "direct_affected_task_ids": sorted(direct_tasks), "closure_affected_task_ids": sorted(closure_tasks),
        "coverage_debt_task_ids": sorted(debt_tasks),
        "coverage_debt_ratio": float(service_coverage["debt_ratio"]),
        "coverage_debt_eligible_platform_ids_by_task": {
            task_id: list(service_coverage["eligible_platform_ids_by_task"].get(task_id, []))
            for task_id in sorted(debt_tasks)
        },
        "coverage_debt_without_eligible_platform_ids": list(service_coverage["uncovered_without_eligible_platform_ids"]),
        "direct_affected_platform_ids": sorted(direct_platforms),
        "closure_affected_platform_ids": sorted(closure_platforms),
        "candidate_platform_ids": sorted(candidate_platforms),
        "local_eligible": local_eligible, "global_eligible": global_eligible,
        "global_required": global_required,
        "scope": "GLOBAL_REPLAN" if global_required else "LOCAL_REPAIR" if local_eligible else "NOOP",
        "strong_event": bool(detection.get("strong_event")),
        "connectivity": {"components": [sorted(row) for row in components], "affected_component_ids": affected_components,
                         "connected": len(affected_components) <= 1 and not split},
        "reasons": reasons,
    }


def _public_connected(observation: dict, start: str, end: str) -> bool:
    if start == end:
        return True
    components = _components(observation)
    mapping = {node: index for index, group in enumerate(components) for node in group}
    return start in mapping and end in mapping and mapping[start] == mapping[end]


def _public_one_hop_connected(observation: dict, start: str, end: str) -> bool:
    if start == end:
        return True
    pair = tuple(sorted((str(start), str(end))))
    return any(
        tuple(sorted((str(row.get("source", "")), str(row.get("target", ""))))) == pair
        and bool(row.get("connected", float(row.get("quality", 0.0)) >= 0.3))
        and float(row.get("quality", 0.0)) > 0.0
        for row in observation.get("communication", [])
        if isinstance(row, dict)
    )


def high_level_action_mask(detection: dict, affected_scope: dict) -> dict[str, bool]:
    triggered = bool(detection.get("triggered", detection.get("strong_event", False)))
    event_severity = str(detection.get("event_severity", "")).lower()
    if not event_severity:
        event_severity = "strong" if bool(detection.get("strong_event")) else (
            "moderate" if float(detection.get("gamma_value", 0.0)) >= float(detection.get("threshold", 0.0)) else "light"
        )
    # A missing authorization flag is not permission for a light-event global
    # fallback. Real scopes always carry ``global_required`` explicitly.
    global_required = bool(affected_scope.get("global_required", False))
    global_fallback = bool(
        affected_scope.get("global_fallback_authorized")
        or affected_scope.get("global_fallback_authorized_by")
    )
    local_ok = bool(affected_scope.get("local_eligible")) and not global_required
    global_ok = bool(affected_scope.get("global_eligible")) and (
        global_required or event_severity != "light" or global_fallback
    )
    return {"NOOP": True, "LOCAL_REPAIR": bool(triggered and local_ok), "GLOBAL_REPLAN": bool(triggered and global_ok)}


def _training_pairs(training_observation_sequences: list[dict]) -> list[tuple[str, dict, dict, dict | None]]:
    pairs = []
    for row in training_observation_sequences:
        if not isinstance(row, dict) or row.get("split") != "train":
            raise ValueError("threshold calibration rejects non-training parents")
        parent_id = str(row.get("parent_id", ""))
        if "previous_public" in row and "current_public" in row:
            pairs.append((parent_id, row["previous_public"], row["current_public"], row.get("wm_summary")))
            continue
        observations = row.get("observations", row.get("public_observations", []))
        summaries = row.get("wm_summaries", [])
        if not isinstance(observations, list) or len(observations) < 2:
            continue
        for index in range(1, len(observations)):
            summary = summaries[index] if index < len(summaries) else None
            pairs.append((parent_id, observations[index - 1], observations[index], summary))
    return pairs


def calibrate_threshold(training_observation_sequences: list[dict], config: dict | None = None,
                        wm_summaries: dict | list | None = None) -> dict:
    """Calibrate q=.75 over positive training gamma values and bind source data."""
    config = dict(config or {})
    q = float(config.get("quantile", 0.75))
    if q != 0.75:
        raise ValueError("threshold quantile is preregistered at q=.75")
    weights = config.get("weights", DEFAULT_WEIGHTS)
    if weights != DEFAULT_WEIGHTS:
        raise ValueError("trigger weights are preregistered")
    delta_min = int(config.get("delta_min", DEFAULT_DELTA_MIN))
    if delta_min != DEFAULT_DELTA_MIN:
        raise ValueError("minimum trigger interval is preregistered at 4 minutes")
    hysteresis_margin = float(config.get("hysteresis_margin", 0.05))
    if not math.isfinite(hysteresis_margin) or not 0.0 <= hysteresis_margin < 1.0:
        raise ValueError("hysteresis_margin must be a relative fraction in [0, 1)")
    pairs = _training_pairs(training_observation_sequences)
    if not pairs:
        raise ValueError("threshold calibration needs training observation pairs")
    if isinstance(wm_summaries, dict):
        pairs = [(parent, previous, current, wm_summaries.get(parent, summary)) for parent, previous, current, summary in pairs]
    elif isinstance(wm_summaries, list):
        pairs = [(parent, previous, current, wm_summaries[index] if index < len(wm_summaries) else summary)
                 for index, (parent, previous, current, summary) in enumerate(pairs)]
    engine = TriggerEngine({"weights": DEFAULT_WEIGHTS, "delta_min": DEFAULT_DELTA_MIN}, {"threshold": 0.0, "weights": DEFAULT_WEIGHTS})
    scores, raw = [], []
    for parent_id, previous, current, summary in pairs:
        result = engine.detect(previous, current, wm_summary=summary)
        score = float(result["gamma_value"])
        if score > 0:
            scores.append(score)
            raw.append({"parent_id": parent_id, "time": int(current.get("time", 0)), "gamma_value": score,
                        "event_type": result["event_type"],
                        "d_state": result["d_state"],
                        "d_state_execution": result["d_state_execution"],
                        "d_state_structural": result["d_state_structural"],
                        "structural_change_components": copy_row(result["event_details"]["structural_change_components"]),
                        "wm_summary": copy_row(summary) if isinstance(summary, dict) else None})
    if not scores:
        raise ValueError("training observations contain no positive gamma values")
    ordered = sorted(scores)
    rank = max(0, math.ceil(q * len(ordered)) - 1)
    threshold = ordered[rank]
    if threshold <= 0.0:
        raise ValueError("training threshold must be positive")
    threshold_low = threshold * (1.0 - hysteresis_margin)
    if not 0.0 < threshold_low < threshold:
        raise ValueError("derived hysteresis release threshold must be positive and below threshold")
    return {
        "schema": "event-threshold-manifest/1", "threshold": float(threshold), "quantile": q,
        "score_definition": "d_state=max(execution_residual,structural_severity); gamma=weighted_sum(d_state,d_degradation,d_margin,d_uncertainty)",
        "tau_on": float(threshold), "tau_off": float(threshold_low),
        "hysteresis_margin": hysteresis_margin,
        "threshold_high": float(threshold), "threshold_low": float(threshold_low),
        "hysteresis": {
            "rule": "tau_off=tau_on*(1-hysteresis_margin)",
            "margin": hysteresis_margin, "margin_source": "preregistered_trigger_config",
        },
        "weights": dict(DEFAULT_WEIGHTS), "delta_min": DEFAULT_DELTA_MIN,
        "raw_positive_scores": raw, "score_count": len(raw),
        "source_parents": sorted({row["parent_id"] for row in raw}),
        "training_input_sha256": _digest(training_observation_sequences),
        "config_sha256": _digest({"quantile": q, "weights": DEFAULT_WEIGHTS, "delta_min": DEFAULT_DELTA_MIN,
                                   "hysteresis_margin": hysteresis_margin,
                                   "score_definition": "d_state=max(execution_residual,structural_severity)"}),
        "wm_summaries_used": any(row["wm_summary"] is not None for row in raw),
    }
