from __future__ import annotations

import pytest

from causal_receipt_proofs import validated_delayed_dispatches, validated_environment_releases


def make_delayed_rows() -> tuple[dict, dict, dict[str, dict]]:
    origin = {
        "action_id": "action-9", "method_id": "PPO", "seed": 8201, "parent_id": "parent-a",
        "event_tape_id": "tape-1", "time": 9,
        "full_environment_action": {"dispatches": [{"task_id": "task9", "platform_id": "uav3"}]},
        "communication_receipts": [{"reason": "dispatch", "connected": True, "delivered": False,
                                     "sent_time": 9, "delivery_time": 10, "delay_minutes": 1,
                                     "target": "uav3", "task_id": "task9"}],
        "raw_events": [{"type": "communication_tx", "reason": "dispatch", "task_id": "task9",
                        "target": "uav3", "delivery_time": 10, "time": 9, "delivered": False}],
    }
    current = {
        "action_id": "action-10", "method_id": "PPO", "seed": 8201, "parent_id": "parent-a",
        "event_tape_id": "tape-1", "time": 10,
        "raw_state_before": {"leaf_tasks": [{"id": "task9", "assignee": None}]},
        "raw_state_after": {"leaf_tasks": [{"id": "task9", "assignee": "uav3"}]},
        "raw_events": [
            {"type": "assignment", "task_id": "task9", "new_assignee": "uav3",
             "previous_assignee": None, "time": 10},
            {"type": "communication_delivered", "originating_action_id": "action-9",
             "task_id": "task9", "platform_id": "uav3", "reason": "dispatch",
             "delivery_time": 10, "time": 10},
        ],
        "command_effects": [{"delivered": True, "owner_changed": True, "task_id": "task9",
                             "platform_id": "uav3", "originating_action_id": "action-9", "command_id": "command-1"}],
    }
    return origin, current, {"action-9": origin}


def test_delayed_dispatch_requires_complete_origin_chain() -> None:
    origin, current, index = make_delayed_rows()

    tasks, proofs = validated_delayed_dispatches(current, index)

    assert tasks == {"task9"}
    assert proofs == [{"actionid": "action-10", "taskid": "task9", "originid": "action-9",
                       "time": 10, "kind": "delayed_dispatch_owner_change"}]


@pytest.mark.parametrize("tamper", ["missing_origin", "cross_cell", "wrong_target", "wrong_time",
                                     "missing_assignment", "missing_receipt", "wrong_delay", "missing_raw_send"])
def test_invalid_delayed_dispatch_evidence_is_not_causal(tamper: str) -> None:
    origin, current, index = make_delayed_rows()
    if tamper == "missing_origin":
        index = {}
    elif tamper == "cross_cell":
        origin["parent_id"] = "parent-b"
    elif tamper == "wrong_target":
        origin["communication_receipts"][0]["target"] = "uav-other"
    elif tamper == "wrong_time":
        current["raw_events"][1]["time"] = 11
    elif tamper == "missing_assignment":
        current["raw_events"] = current["raw_events"][1:]
    elif tamper == "missing_receipt":
        origin["communication_receipts"] = []
    elif tamper == "wrong_delay":
        origin["communication_receipts"][0]["delay_minutes"] = 2
    elif tamper == "missing_raw_send":
        origin["raw_events"] = []

    tasks, proofs = validated_delayed_dispatches(current, index)

    assert tasks == set()
    assert proofs == []


def make_release_row() -> dict:
    return {
        "action_id": "action-43", "time": 43,
        "raw_state_before": {"leaf_tasks": [{"id": "task9", "assignee": "heli2"}]},
        "raw_state_after": {"leaf_tasks": [{"id": "task9", "assignee": None}],
                             "root_mapping": {"task9": "root9"}},
        "raw_events": [
            {"type": "task_failed", "released": True, "terminal": False,
             "reason": "blocked_route", "platform_id": "heli2", "task_id": "task9", "time": 43},
            {"type": "route_blocked", "platform_id": "heli2", "task_id": "task9", "time": 43},
            {"type": "report_received", "released_task_ids": ["task9"], "platform_id": "heli2", "time": 44},
        ],
    }


def test_route_release_returns_root_but_is_not_causal_evidence_with_float_times() -> None:
    row = make_release_row()
    row["raw_events"][0]["time"] = 43.0
    row["raw_events"][1]["time"] = 43.0
    row["raw_events"][2]["time"] = 44.0

    roots, proofs = validated_environment_releases(row)

    assert roots == {"root9"}
    assert proofs == [{"actionid": "action-43", "taskid": "task9", "originid": None,
                       "time": 43, "kind": "environment_route_release"}]


@pytest.mark.parametrize("remove_event", ["task_failed", "route_blocked", "report_received"])
def test_route_release_without_any_required_receipt_is_not_excluded(remove_event: str) -> None:
    row = make_release_row()
    row["raw_events"] = [event for event in row["raw_events"] if event["type"] != remove_event]

    roots, proofs = validated_environment_releases(row)

    assert roots == set()
    assert proofs == []


@pytest.mark.parametrize("tamper", ["failure_tick", "report_too_late"])
def test_route_release_rejects_inconsistent_event_times(tamper: str) -> None:
    row = make_release_row()
    if tamper == "failure_tick":
        row["raw_events"][0]["time"] = 42.0
    else:
        row["raw_events"][2]["time"] = 45.0

    roots, proofs = validated_environment_releases(row)

    assert roots == set()
    assert proofs == []


def test_route_release_with_wrong_owner_transition_is_not_excluded() -> None:
    row = make_release_row()
    row["raw_state_before"]["leaf_tasks"][0]["assignee"] = "other-platform"

    roots, proofs = validated_environment_releases(row)

    assert roots == set()
    assert proofs == []
