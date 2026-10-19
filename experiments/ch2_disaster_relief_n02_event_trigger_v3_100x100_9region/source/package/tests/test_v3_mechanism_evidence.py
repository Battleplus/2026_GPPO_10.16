from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))
sys.path.insert(0, str(ROOT.parent / "tools"))

from event_oracle import recompute_consequence_labels
from region_scenarios import build_s0_local_repair_fixture
from run_v3_mechanism import _selection_plan, export_branches


def test_public_selection_projection_preserves_same_owner_queue_and_appends_transfer() -> None:
    observation = {
        "tasks": [
            {"id": "taskA", "assignee": "uav-1"},
            {"id": "taskB", "assignee": "uav-1"},
            {"id": "taskC", "assignee": "uav-2"},
            {"id": "taskD", "assignee": "uav-2"},
        ],
        "queues": {"uav-1": ["taskA", "taskB"], "uav-2": ["taskC", "taskD"]},
    }
    same_owner_candidate = {
        "candidate_key": "same-owner-dispatch",
        "legal": True,
        "full_environment_action": {
            "action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
            "queue_operations": [], "dispatches": [{"platform_id": "uav-1", "task_id": "taskA"}],
        },
    }
    selected, projected = _selection_plan(observation, [same_owner_candidate])
    assert selected is None
    assert projected[0]["effective_planned_mutation"] is False
    assert projected[0]["projected_owner_queue_state"] == {
        "owners": {row["id"]: row["assignee"] for row in observation["tasks"]},
        "queues": observation["queues"],
    }

    transfer_candidate = {
        "candidate_key": "cross-owner-transfer",
        "legal": True,
        "full_environment_action": {
            "action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
            "queue_operations": [{"op": "transfer", "task_id": "taskA",
                                  "from_platform": "uav-1", "to_platform": "uav-2"}],
            "dispatches": [],
        },
    }
    selected, projected = _selection_plan(observation, [transfer_candidate])
    assert selected == transfer_candidate
    assert projected[0]["projected_owner_queue_state"]["queues"] == {
        "uav-1": ["taskB"], "uav-2": ["taskC", "taskD", "taskA"],
    }


def test_mechanism_export_contains_replayable_same_snapshot_branches() -> None:
    with TemporaryDirectory(dir=ROOT.parent) as temporary:
        tmp_path = Path(temporary)
        wrapper = build_s0_local_repair_fixture()
        wrapper_path = tmp_path / "wrapper.json"
        wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")

        summary = export_branches(wrapper_path, tmp_path / "evidence")
        evidence = Path(summary["evidence_root"])
        window = json.loads((evidence / "WINDOW.json").read_text(encoding="utf-8"))
        branch_rows = json.loads((evidence / "BRANCH_EVIDENCE.json").read_text(encoding="utf-8"))
        selection_plan = json.loads((evidence / "SELECTION_PLAN.json").read_text(encoding="utf-8"))
        request = json.loads((evidence / "REQUEST.json").read_text(encoding="utf-8"))

    assert summary["event_time"] == 4
    assert summary["triggered"] is True
    assert summary["decision_scope"] == "LOCAL_REPAIR"
    assert summary["identified_scope"] == "LOCAL_REPAIR"
    assert summary["legal_noop_count"] == 1
    assert summary["legal_nonnoop_local_candidate_count"] >= 2
    assert summary["source_hashes_unchanged"] is True
    assert len(branch_rows) == len(window["branches"])
    assert selection_plan["private_simulator_truth_read"] is False
    assert request["selection_plan"]["selected_candidate_key"] == selection_plan["selected_candidate_key"]
    projected_mutations = [
        row for row in selection_plan["candidate_projections"]
        if row["scope"] == "LOCAL_REPAIR" and row["effective_planned_mutation"]
    ]
    assert selection_plan["selected_candidate_key"] == projected_mutations[0]["candidate_key"]
    assert selection_plan["candidate_projections"][1]["effective_planned_mutation"] is False
    assert selection_plan["candidate_projections"][1]["projected_owner_queue_state"] == (
        selection_plan["candidate_projections"][0]["projected_owner_queue_state"]
    )

    initial_hashes = {row["private_binding"]["simulator_snapshot_sha256"] for row in window["branches"]}
    assert initial_hashes == {window["private_binding"]["simulator_snapshot_sha256"]}
    for branch, audit in zip(window["branches"], branch_rows):
        steps = branch["trajectory"]["steps"]
        assert steps[0]["full_environment_action"] == branch["candidate"]["full_environment_action"]
        assert all(step["full_environment_action"]["noop"] for step in steps[1:])
        assert audit["action_audit"][0]["requested_action"] == audit["action_audit"][0]["repaired_action"]
        assert audit["action_audit"][0]["executed_action"] == audit["action_audit"][0]["repaired_action"]
        assert "owner_queue_diff" in audit["action_audit"][0]

    selected_audit = next(
        row for row in branch_rows if row["candidate_key_producer"] == selection_plan["selected_candidate_key"]
    )["action_audit"][0]
    assert selected_audit["owner_queue_diff"]["owner_changes"]
    assert selected_audit["owner_queue_diff"]["queue_changes"]
    selected_projection = next(
        row for row in selection_plan["candidate_projections"]
        if row["candidate_key"] == selection_plan["selected_candidate_key"]
    )
    assert not any(event.get("type") == "logical_task_completed" for event in selected_audit["raw_events"])
    assert selected_projection["projected_owner_queue_state"] == selected_audit["owner_queue_after"]

    labels = recompute_consequence_labels(window)
    assert labels["window_start"] == 4
    assert len(labels["candidate_labels"]) == len(window["branches"])
    assert not summary["label_recompute"]["self_certified_pass"]


def test_mechanism_export_rejects_event_time_not_in_tape() -> None:
    import pytest
    with TemporaryDirectory(dir=ROOT.parent) as temporary:
        tmp_path = Path(temporary)
        wrapper = build_s0_local_repair_fixture()
        wrapper_path = tmp_path / "wrapper.json"
        wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")

        with pytest.raises(ValueError, match="MECHANISM_EVENT_TIME_NOT_IN_TAPE"):
            export_branches(wrapper_path, tmp_path / "evidence", event_time=5)
