from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from run_s1_cpu import _communication_receipt_from_records


def _wrapper() -> dict:
    return {"event_tape": [{
        "event_id": "drop-18", "kind": "communication_drop", "time": 18,
        "links": [["uav-a", "uav-b"], ["uav-c", "uav-d"]], "quality": 0.0,
    }]}


def _branches(raw_events: list[dict]) -> list[dict]:
    return [{"candidate": {"full_environment_action": {"noop": True}},
             "action_audit": [{"raw_events": raw_events}]}]


def test_unobserved_future_communication_drop_has_no_receipt() -> None:
    assert _communication_receipt_from_records(
        "mixed_events", _wrapper(), _branches([]),
        {"event_details": {"communication_edge_changes": []}},
    ) is None


def test_receipt_counts_only_links_observed_in_raw_branch() -> None:
    raw = [{"type": "communication_changed", "event_id": "drop-18", "time": 18,
            "links": [{"source": "uav-a", "target": "uav-b", "old_quality": 0.9,
                       "new_quality": 0.0}]}]
    receipt = _communication_receipt_from_records(
        "global_fallback", _wrapper(), _branches(raw),
        {"event_details": {"communication_edge_changes": []}},
    )
    assert receipt is not None
    assert receipt["event_ids_observed"] == ["drop-18"]
    assert receipt["link_change_count"] == 1
    assert receipt["event_tape_events"][0]["links"] == [["uav-a", "uav-b"]]


def test_receipt_uses_only_tape_links_matching_current_detection() -> None:
    detection = {"event_details": {"communication_edge_changes": [{
        "source": "uav-c", "target": "uav-d", "changed_fields": ["quality"],
    }]}}
    receipt = _communication_receipt_from_records(
        "communication_drop", _wrapper(), _branches([]), detection,
    )
    assert receipt is not None
    assert receipt["event_ids_observed"] == ["drop-18"]
    assert receipt["link_change_count"] == 1
    assert receipt["event_tape_events"][0]["links"] == [["uav-c", "uav-d"]]
    assert len(receipt["detected_public_link_changes"]) == 1
