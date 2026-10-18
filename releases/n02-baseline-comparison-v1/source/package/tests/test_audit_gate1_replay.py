from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDITOR_PATH = ROOT / "tools" / "audit_gate1_replay.py"
SPEC = importlib.util.spec_from_file_location("audit_gate1_replay", AUDITOR_PATH)
AUDITOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDITOR)


def _branch() -> tuple[dict, dict]:
    action = {"scope": "NOOP", "noop": True, "queue_operations": [], "dispatches": []}
    candidate_key = "event-action-" + AUDITOR.digest(action)[:24]
    event_tape_id = "tape-1"
    weights = dict(AUDITOR.WEIGHTS)
    public = {
        "tasks": [
            {"id": "task-completed", "kind": "delivery", "status": "completed", "progress": 1.0},
            {"id": "task-pending", "kind": "delivery", "status": "pending", "progress": 0.2},
        ],
        "platforms": [{"id": "platform-1", "energy_used": 10.0}],
        "communication": [],
    }
    public["provenance"] = {
        "snapshot_hash": AUDITOR.digest(public),
        "public_prefix_hash": "a" * 64,
        "event_tape_id": event_tape_id,
    }
    candidate = {
        "candidate_key": candidate_key,
        "full_environment_action": action,
        "candidate_scope": "noop",
        "legal": True,
        "event_tape_id": event_tape_id,
        "snapshot_hash": public["provenance"]["snapshot_hash"],
        "public_prefix_hash": public["provenance"]["public_prefix_hash"],
    }
    events = [{"type": "logical_task_completed"}]
    components = AUDITOR.event_components(events)
    terms = AUDITOR.reward_terms(components, weights)
    step = {
        "time": 0,
        "public_observation": public,
        "full_environment_action": copy.deepcopy(action),
        "raw_events": events,
        "reward": sum(terms.values()),
        "reward_primitives": {field: components[name] for name, field in AUDITOR.PRIMITIVES.items()},
        "reward_terms": terms,
        "reward_formula": {"schema": "event-relief-reward/1", "weights": weights},
        "operation_receipts": [{"postrepair_legal": True}],
    }
    truth = {
        "time": 1,
        "tasks": [
            {"id": "task-completed", "kind": "delivery", "status": "completed", "delivered": True,
             "progress": 1.0, "deadline": 2, "completed_at": 0, "on_time": True},
            {"id": "task-pending", "kind": "delivery", "status": "pending", "progress": 0.2},
        ],
        "platforms": [{"id": "platform-1", "energy": 5.0, "energy_used": 10.0,
                       "position": [3, 4], "failed": False}],
    }
    trajectory = {
        "schema": "event-relief-window-trace/1", "parent_id": "parent-1", "split": "train",
        "event_tape_id": event_tape_id, "start_time": 0, "end_time": 1,
        "steps": [step], "raw_events": events, "raw_truth": truth,
    }
    branch = {
        "schema": "event-branch-trajectory/1", "window_id": "parent-1-t00",
        "parent_id": "parent-1", "split": "train", "candidate_key": candidate_key,
        "candidate": candidate, "trajectory": trajectory,
        "private_binding": {"simulator_snapshot_sha256": "b" * 64, "event_tape_sha256": "c" * 64},
    }
    return branch, weights


def test_recomputes_raw_trace_noop_and_non_target_outcomes_with_unknown_masks() -> None:
    branch, weights = _branch()

    label, binding = AUDITOR.compute_branch(branch, weights)
    window = AUDITOR.finish_window("parent-1-t00", [(label, binding)])

    assert window["explicit_noop_candidate_key"] == branch["candidate_key"]
    assert label["reward_recomputation"]["recomputed_utility"] == 1.0
    assert label["global_outcomes"]["utility"] == {"value": 1.0, "valid": True}
    pending = next(row for row in label["task_outcomes"] if row["id"] == "task-pending")
    assert pending["progress"] == 0.2
    assert pending["on_time_valid"] is False
    assert "task-pending" in binding["non_action_task_ids"]
    assert label["global_outcomes"]["on_time_rate"]["valid"] is False
    assert label["unknown"]["unresolved_task_ids"] == ["task-pending"]


def test_trace_and_label_tampering_are_detected() -> None:
    branch, weights = _branch()
    baseline, _ = AUDITOR.compute_branch(branch, weights)

    changed_trace = copy.deepcopy(branch)
    changed_trace["trajectory"]["steps"][0]["reward"] += 1.0
    try:
        AUDITOR.compute_branch(changed_trace, weights)
    except ValueError as exc:
        assert "event-derived reward mismatch" in str(exc)
    else:
        raise AssertionError("tampered recorded reward was accepted")

    changed_truth = copy.deepcopy(branch)
    changed_truth["trajectory"]["raw_truth"]["tasks"][1]["progress"] = 0.9
    recomputed, _ = AUDITOR.compute_branch(changed_truth, weights)
    assert AUDITOR.differences(baseline, recomputed)

    changed_label = copy.deepcopy(baseline)
    changed_label["global_outcomes"]["utility"]["value"] += 1.0
    assert AUDITOR.differences(baseline, changed_label)
