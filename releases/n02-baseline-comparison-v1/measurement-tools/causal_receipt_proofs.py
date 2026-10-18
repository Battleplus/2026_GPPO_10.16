"""Strict raw-receipt proofs for delayed dispatches and environment releases."""

from __future__ import annotations

import math
from typing import Any


def _event_kind(event: dict[str, Any]) -> Any:
    return event.get("type", event.get("kind"))


def _events(row: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    raw = row.get("raw_events")
    if not isinstance(raw, list):
        return []
    return [event for event in raw if isinstance(event, dict) and _event_kind(event) == kind]


def _leaf_task(state: Any, task_id: str) -> dict[str, Any] | None:
    if not isinstance(state, dict) or not isinstance(state.get("leaf_tasks"), list):
        return None
    found = [task for task in state["leaf_tasks"] if isinstance(task, dict) and task.get("id") == task_id]
    return found[0] if len(found) == 1 else None


def _cell(row: dict[str, Any]) -> tuple[Any, ...]:
    return row.get("method_id"), row.get("seed"), row.get("parent_id"), row.get("event_tape_id")


def _finite_time(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _proof(row: dict[str, Any], task_id: str, origin_id: str | None, time: int, kind: str) -> dict[str, Any]:
    return {"actionid": row.get("action_id"), "taskid": task_id, "originid": origin_id,
            "time": time, "kind": kind}


def validated_delayed_dispatches(
    row: dict[str, Any], action_index: dict[str, dict[str, Any]],
) -> tuple[set[str], list[dict[str, Any]]]:
    """Return leaf task IDs with a complete, raw-evidence delayed-dispatch chain."""
    causal: set[str] = set()
    proofs: list[dict[str, Any]] = []
    before, after = row.get("raw_state_before"), row.get("raw_state_after")
    row_time = row.get("time")
    if not _finite_time(row_time):
        return causal, proofs
    effects = row.get("command_effects")
    effects = effects if isinstance(effects, list) else []

    for delivered in _events(row, "communication_delivered"):
        if delivered.get("reason") != "dispatch" or delivered.get("time") != row_time:
            continue
        origin_id = delivered.get("originating_action_id")
        origin = action_index.get(origin_id) if isinstance(origin_id, str) else None
        task_id, platform_id = delivered.get("task_id"), delivered.get("platform_id")
        if (origin is None or not isinstance(task_id, str) or not isinstance(platform_id, str)
                or origin.get("action_id") != origin_id or any(value is None for value in _cell(row))
                or any(value is None for value in _cell(origin)) or type(row.get("seed")) is not int
                or _cell(origin) != _cell(row) or not _finite_time(origin.get("time"))
                or origin["time"] >= row_time or delivered.get("delivery_time") != row_time):
            continue

        action = origin.get("full_environment_action")
        dispatches = action.get("dispatches") if isinstance(action, dict) else None
        if not isinstance(dispatches, list) or not any(
                isinstance(item, dict) and item.get("task_id") == task_id
                and item.get("platform_id") == platform_id for item in dispatches):
            continue

        receipts = origin.get("communication_receipts")
        if not isinstance(receipts, list) or not any(
                isinstance(receipt, dict) and receipt.get("reason") == "dispatch"
                and receipt.get("connected") is True and receipt.get("delivered") is False
                and _finite_time(receipt.get("delay_minutes")) and receipt["delay_minutes"] > 0
                and receipt.get("delay_minutes") == row_time - origin["time"]
                and receipt.get("target") == platform_id and receipt.get("task_id") == task_id
                and receipt.get("sent_time") == origin.get("time")
                and receipt.get("delivery_time") == row_time for receipt in receipts):
            continue

        origin_events = origin.get("raw_events")
        if not isinstance(origin_events, list) or not any(
                isinstance(event, dict) and _event_kind(event) == "communication_tx"
                and event.get("task_id") == task_id
                and event.get("target") == platform_id and event.get("delivery_time") == row_time
                and event.get("time") == origin.get("time") and event.get("delivered") is False
                for event in origin_events):
            continue

        task_before, task_after = _leaf_task(before, task_id), _leaf_task(after, task_id)
        if task_before is None or task_after is None:
            continue
        old_owner, new_owner = task_before.get("assignee"), task_after.get("assignee")
        if old_owner == platform_id or new_owner != platform_id or old_owner == new_owner:
            continue
        assignments = [event for event in _events(row, "assignment")
                       if event.get("task_id") == task_id and event.get("time") == row_time
                       and event.get("previous_assignee") == old_owner and event.get("new_assignee") == new_owner]
        if len(assignments) != 1:
            continue

        if not any(isinstance(effect, dict) and effect.get("delivered") is True
                   and effect.get("owner_changed") is True and effect.get("task_id") == task_id
                   and effect.get("platform_id") == platform_id
                   and effect.get("originating_action_id") == origin_id for effect in effects):
            continue
        causal.add(task_id)
        proofs.append(_proof(row, task_id, origin_id, int(row_time), "delayed_dispatch_owner_change"))
    return causal, proofs


def validated_environment_releases(row: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    """Return root IDs whose owner removal is fully evidenced as a route release."""
    roots: set[str] = set()
    proofs: list[dict[str, Any]] = []
    before, after = row.get("raw_state_before"), row.get("raw_state_after")
    for failure in _events(row, "task_failed"):
        task_id, platform_id, time = failure.get("task_id"), failure.get("platform_id"), failure.get("time")
        if (failure.get("released") is not True or failure.get("terminal") is not False
                or failure.get("reason") != "blocked_route" or not isinstance(task_id, str)
                or not isinstance(platform_id, str) or not _finite_time(time)
                or not _finite_time(row.get("time")) or time != row.get("time")):
            continue
        route_proof = any(event.get("task_id") == task_id and event.get("platform_id") == platform_id
                          and event.get("time") == time for event in _events(row, "route_blocked"))
        after_time = after.get("time", row.get("time") + 1) if isinstance(after, dict) else row.get("time") + 1
        report_proof = any(event.get("platform_id") == platform_id and _finite_time(event.get("time"))
                           and event.get("time") >= time and event.get("time") <= after_time
                           and isinstance(event.get("released_task_ids"), list)
                           and task_id in event["released_task_ids"]
                           for event in _events(row, "report_received"))
        task_before, task_after = _leaf_task(before, task_id), _leaf_task(after, task_id)
        if (not route_proof or not report_proof or task_before is None or task_after is None
                or task_before.get("assignee") != platform_id or task_after.get("assignee") is not None):
            continue
        mapping = after.get("root_mapping") if isinstance(after, dict) else None
        root_id = mapping.get(task_id, task_id) if isinstance(mapping, dict) else task_id
        roots.add(root_id)
        proofs.append(_proof(row, task_id, None, int(row.get("time")), "environment_route_release"))
    return roots, proofs
