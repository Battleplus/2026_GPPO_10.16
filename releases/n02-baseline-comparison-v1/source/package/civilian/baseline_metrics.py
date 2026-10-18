"""Independent baseline metric calculator using only JSON-compatible receipts."""

from __future__ import annotations

from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def effective_reconstruction(step: dict) -> bool:
    """Count attributable endpoint owner changes or same-platform reorders."""
    # Runner receipts expose these endpoint-derived counters. The independent
    # oracle checks them against raw before/after state and causal receipts.
    if "owner_change_count" in step or "queue_reorder_count" in step:
        return _float(step.get("owner_change_count")) > 0 or _float(step.get("queue_reorder_count")) > 0

    for event in step.get("raw_events", []):
        if event.get("type") == "task_owner_change" and event.get("previous_owners") != event.get("new_owners"):
            return True

    for receipt in step.get("operation_receipts", []):
        operation = receipt.get("operation", {})
        if operation.get("op") != "insert" or operation.get("from_platform") != operation.get("to_platform"):
            continue
        platform = operation.get("to_platform")
        before = receipt.get("before_queues", {})
        after = receipt.get("after_queues", {})
        if list(before.get(platform, [])) != list(after.get(platform, [])):
            return True

    command_changes = step.get("command_effects", [])
    for effect in command_changes:
        if effect.get("originating_action_id") and effect.get("delivered"):
            if effect.get("owner_changed") is True:
                return True
    return False


def summarize_episode(*, initial_tasks: list[dict], final_tasks: list[dict], steps: list[dict],
                      horizon: int, parent_id: str | None = None,
                      protocol_message_weight: float = 0.01) -> dict[str, Any]:
    """Recompute outcomes from original-root endpoints and action receipts.

    ``initial_tasks`` and ``final_tasks`` contain one row per original task;
    split children must be represented only through their parent aggregate.
    """
    initial = {str(row["id"]): row for row in initial_tasks}
    final = {str(row["id"]): row for row in final_tasks}
    if not initial or set(initial) != set(final):
        raise ValueError("BASELINE_METRICS_ROOT_TASK_IDENTITY")
    completion_times: list[float] = []
    delays: list[float] = []
    on_time: list[bool] = []
    critical_failures = 0
    failed = 0
    cancelled = 0
    cancellation_time: dict[str, float] = {}
    for step in steps:
        for event in step.get("raw_events", []):
            if "cancel" in str(event.get("type", "")).lower():
                task_id = str(event.get("task_id", ""))
                if task_id in initial:
                    cancellation_time[task_id] = _float(event.get("time"), horizon)
    for task_id, first in initial.items():
        last = final[task_id]
        deadline = _float(first.get("deadline", last.get("deadline", horizon)), horizon)
        status = str(last.get("status", "pending"))
        complete = status == "completed" and last.get("completed_at") is not None
        cancelled_task = status == "cancelled"
        completion_times.append(1.0 if complete else 0.0)
        finish = _float(last.get("completed_at"), horizon) if complete else (
            _float(last.get("cancelled_at", cancellation_time.get(task_id)), horizon) if cancelled_task else float(horizon)
        )
        delays.append(max(0.0, finish - deadline))
        is_on_time = bool(complete and finish <= deadline)
        on_time.append(is_on_time)
        if status == "failed":
            failed += 1
        if cancelled_task:
            cancelled += 1
        if _float(first.get("priority", last.get("priority", 0.0))) >= 5.0 and not complete:
            critical_failures += 1

    environment_utility = sum(_float(step.get("reward")) for step in steps)
    protocol_messages = sum(int(step.get("rule_protocol_message_count", 0)) for step in steps)
    effective = sum(effective_reconstruction(step) for step in steps)
    requested = sum(bool(step.get("requested_nonnoop")) for step in steps)
    local_invocations = sum(step.get("selected_scope") == "LOCAL_REPAIR" and step.get("requested_nonnoop") for step in steps)
    global_invocations = sum(step.get("selected_scope") == "GLOBAL_REPLAN" and step.get("requested_nonnoop") for step in steps)
    owner_changes = sum(int(step.get("owner_change_count", 0)) for step in steps)
    queue_reorders = sum(int(step.get("queue_reorder_count", 0)) for step in steps)
    reconstruction_size = sum(int(step.get("reconstruction_size", 0)) for step in steps)
    environment_messages = sum(int(step.get("environment_action_delivery_message_count", 0)) for step in steps)
    energy_units = sum(_float(step.get("reward_primitives", {}).get("energy_units")) for step in steps)
    switch_count = sum(int(step.get("reward_primitives", {}).get("switch_count", 0)) for step in steps)
    utility = {
        "environment_utility": environment_utility,
        "global_utility": environment_utility,
        "rule_protocol_message_count": protocol_messages,
        "protocol_cost": protocol_message_weight * protocol_messages,
        "net_utility": environment_utility - protocol_message_weight * protocol_messages,
    }
    return {
        "schema": "baseline-production-metrics/1",
        "parent_id": parent_id,
        "original_root_task_count": len(initial),
        "completion_rate": sum(completion_times) / len(initial),
        "on_time_rate": sum(on_time) / len(initial),
        "mean_delay_minutes": sum(delays) / len(initial),
        "critical_failure_count_priority_ge_5": critical_failures,
        "failed_root_task_count": failed,
        "cancelled_root_task_count": cancelled,
        **utility,
        "trigger_count": sum(bool(step.get("decision_clock", {}).get("planned")) for step in steps),
        "planning_invocation_count": sum(bool(step.get("decision_clock", {}).get("planned")) for step in steps),
        "scope_nonempty_planning_count": sum(
            bool(step.get("decision_clock", {}).get("planned")) and bool(
                step.get("affected_scope", {}).get("affected_task_ids") or
                step.get("affected_scope", {}).get("affected_platform_ids")
            ) for step in steps
        ),
        "actionable_catalog_planning_count": sum(
            bool(step.get("decision_clock", {}).get("planned")) and any(
                legal and not row.get("full_environment_action", {}).get("noop")
                for row, legal in zip(step.get("candidate_catalog") or [], step.get("candidate_mask") or [])
            ) for step in steps
        ),
        "nonempty_planning_invocation_count": sum(
            bool(step.get("decision_clock", {}).get("planned")) and any(
                legal and not row.get("full_environment_action", {}).get("noop")
                for row, legal in zip(step.get("candidate_catalog") or [], step.get("candidate_mask") or [])
            ) for step in steps
        ),
        "detector_event_edge_count": sum(bool(step.get("detector_event_edge")) for step in steps),
        "requested_nonnoop_count": requested,
        "effective_reconstruction_count": effective,
        "reconstruction_size": reconstruction_size,
        "local_repair_invocation_count": local_invocations,
        "global_replan_invocation_count": global_invocations,
        "task_owner_change_count": owner_changes,
        "queue_reorder_count": queue_reorders,
        "environment_action_delivery_message_count": environment_messages,
        "planning_latency_seconds": sum(_float(step.get("planning_latency_seconds")) for step in steps),
        "policy_response_seconds": sum(_float(step.get("policy_response_seconds")) for step in steps),
        "constraint_violations": sum(int(step.get("constraint_violations", 0)) for step in steps),
        "energy_units": energy_units,
        "task_switch_count": switch_count,
    }
