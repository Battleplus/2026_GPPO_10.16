from __future__ import annotations

import copy
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from region_pilot_acceptance import EXPECTED_VARIANTS, build_acceptance_report

WORK_ROOT = ROOT.parent / ".tmp-s2-engineering-gate-tests"


@pytest.fixture
def case_dir():
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    path = WORK_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _summary(parent_id: str, *, utility: float, on_time: float) -> dict:
    def metric(value: float) -> dict:
        return {"value": value, "valid": True, "denominator": 1}

    return {
        "parent_id": parent_id,
        "global_utility": utility,
        "on_time_rate": on_time,
        "operational_dispatch_count": 0,
        "communication_message_count": 0,
        "environment_metrics": {
            "energy_used": 0.0,
            "safety_risk": 0.0,
            "task_switch_count": 0,
            "reward_component_totals": {"completion": utility},
            "metrics": {
                "global_utility": metric(utility),
                "on_time_rate": metric(on_time),
                "energy_used": metric(0.0),
                "safety_risk": metric(0.0),
            },
        },
    }


def _transition(parent_id: str, tape_id: str, *, variant: str, local: bool = False,
                action_mismatch: bool = False, communication_messages: int = 0) -> dict:
    observation = {
        "tasks": [{"id": "t1", "region_id": "r00"}],
        "platforms": [{"id": "p1", "region_id": "r00"}],
        "provenance": {"snapshot_hash": "snapshot-hash", "event_tape_id": tape_id},
    }
    if local:
        noop = False
        action = {
            "action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
            "queue_operations": [{"op": "insert", "task_id": "t1", "from_platform": None, "to_platform": "p1"}],
            "dispatches": [],
        }
        candidate_key = f"{variant}-{parent_id}-local"
        assignment_before, assignment_after = {"t1": None}, {"t1": "p1"}
        queues_before, queues_after = {"p1": []}, {"p1": ["t1"]}
        operation = action["queue_operations"][0]
        operation_receipts = [{"operation": copy.deepcopy(operation), "before_queues": copy.deepcopy(queues_before),
                               "after_queues": copy.deepcopy(queues_after)}]
        events = [
            {"type": "queue_operation", "operation": copy.deepcopy(operation)},
            {"type": "task_owner_change", "task_id": "t1", "previous_owners": [], "new_owners": ["p1"]},
        ]
    else:
        noop = True
        action = {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
                  "queue_operations": [], "dispatches": []}
        candidate_key = f"{variant}-{parent_id}-noop"
        assignment_before = assignment_after = {"t1": None}
        queues_before = queues_after = {"p1": []}
        operation_receipts = []
        events = []
    if communication_messages:
        events.append({"type": "communication_tx", "message_count": communication_messages})
    executed = copy.deepcopy(action)
    return {
        "parent_id": parent_id,
        "candidates": [{"candidate_key": candidate_key, "legal": True,
                        "full_environment_action": copy.deepcopy(action)}],
        "candidate_keys": [candidate_key],
        "candidate_index": 0,
        "candidate_key": candidate_key,
        "selected_candidate_legal": True,
        "observation": observation,
        "affected_scope": {"affected_region_ids": ["r00"]},
        "selected_action": copy.deepcopy(action),
        "repair_receipt": {"legal_before": True, "postrepair_legal": True, "repaired": False,
                           "public_snapshot_hash": "snapshot-hash", "event_tape_id": tape_id},
        "executed_action": executed,
        "assignment_before": assignment_before,
        "assignment_after": assignment_after,
        "queues_before": queues_before,
        "queues_after": queues_after,
        "operation_receipts": operation_receipts,
        "raw_events": events,
        "effective_reconstruction_count": int(local),
    }


def _fixture(
    tmp_path: Path, *, utility_drop: bool = False, on_time_regression: bool = False,
    no_strict_cost: bool = False, local_zero: bool = False, action_mismatch: bool = False,
    update_count: int = 8, unknown_on_time: bool = False,
) -> dict:
    parents = [(f"train-{i}", "train") for i in range(4)] + [(f"dev-{i}", "development") for i in range(2)]
    metadata = [{
        "parent_id": parent, "split": split, "event_tape_id": f"tape-{parent}",
        "initial_owner_queue_sha256": f"owners-{parent}",
        "public_reset_prefix_sha256": f"reset-{parent}",
        "scenario_wrapper_sha256": f"wrapper-{parent}",
    } for parent, split in parents]
    variants = {}
    for variant in EXPECTED_VARIANTS:
        seed_root = tmp_path / variant / "seed_8201"
        seed_root.mkdir(parents=True)
        summaries = []
        dev_summaries = []
        train_rows = []
        for parent, split in parents:
            is_event = variant == "Event-G"
            utility = 1.5 if is_event else 1.0
            on_time = 0.78 if is_event else 0.80
            if utility_drop and is_event:
                utility = 0.5
            if on_time_regression and is_event:
                on_time = 0.75
            summary = _summary(parent, utility=utility, on_time=on_time)
            if unknown_on_time and is_event and split == "development" and parent == "dev-0":
                summary["on_time_rate"] = None
                summary["environment_metrics"]["metrics"]["on_time_rate"] = {"value": None, "valid": False, "denominator": 0}
            if split == "train":
                summaries.append(summary)
            else:
                dev_summaries.append(summary)
                if not no_strict_cost and not (is_event and parent == "dev-0"):
                    summary["global_utility"] = utility
                # Periodic-G sends one message in each dev episode; Event-G sends none.
            row = _transition(
                parent, f"tape-{parent}", variant=variant,
                local=(split == "train" and parent == "train-0" and not local_zero),
                action_mismatch=(action_mismatch and split == "train" and parent == "train-1"),
                communication_messages=(0 if is_event or no_strict_cost else (1 if split == "development" else 0)),
            )
            if action_mismatch and split == "train" and parent == "train-1":
                row["executed_action"] = {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                                          "queue_operations": [], "dispatches": []}
            if split == "train":
                train_rows.append(row)
            else:
                (seed_root / f"development_{parent}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
                artifact = {
                    "parent_id": parent, "variant": variant, "event_tape_id": f"tape-{parent}",
                    "actor_initialization_sha256": "actor-init", "trajectory": {"steps": [row]},
                }
                (seed_root / f"development_{parent}_trajectory.json").write_text(json.dumps(artifact), encoding="utf-8")
        (seed_root / "rollouts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in train_rows), encoding="utf-8")
        variants[variant] = {"8201": {"training": {
            "initial_actor_digest": "actor-init", "optimizer_updates": update_count, "episodes": summaries,
        }, "development": dev_summaries}}
    return {"paired_parent_metadata": metadata, "variants": variants}


def test_engineering_gate_passes_fixture_but_never_authorizes_s3(case_dir: Path) -> None:
    report = build_acceptance_report(_fixture(case_dir), case_dir)
    gate = report["engineering_gate"]
    assert report["status"] == "PASS_DATA_CONTRACT_ONLY"
    assert gate["status"] == "PASS_PENDING_INDEPENDENT_REVIEW"
    assert gate["S3_allowed"] is False
    assert all(item["valid"] for item in gate["checks"].values())
    costs = gate["checks"]["development_strict_cost_lower"]["observed"]
    assert "communication_messages" in costs["strictly_lower_metrics"]


@pytest.mark.parametrize(("kwargs", "check"), [
    ({"utility_drop": True}, "development_global_utility_difference"),
    ({"on_time_regression": True}, "development_on_time_rate_difference"),
    ({"no_strict_cost": True}, "development_strict_cost_lower"),
    ({"local_zero": True}, "Periodic-G_effective_local_action"),
    ({"action_mismatch": True}, "Periodic-G_action_execution_binding"),
    ({"update_count": 0}, "paired_update_counts"),
    ({"update_count": 33}, "paired_update_counts"),
    ({"unknown_on_time": True}, "development_on_time_rate_difference"),
])
def test_engineering_gate_rejects_failed_criterion(case_dir: Path, kwargs: dict, check: str) -> None:
    report = build_acceptance_report(_fixture(case_dir, **kwargs), case_dir)
    gate = report["engineering_gate"]
    assert gate["status"] == "REPAIR_REQUIRED"
    assert gate["S3_allowed"] is False
    assert gate["checks"][check]["valid"] is False
    assert gate["checks"][check]["failreason"]


def test_engineering_gate_rejects_nonfinite_required_metric(case_dir: Path) -> None:
    fixture = _fixture(case_dir)
    fixture["variants"]["Event-G"]["8201"]["development"][0]["global_utility"] = float("nan")
    report = build_acceptance_report(fixture, case_dir)
    assert report["engineering_gate"]["status"] == "REPAIR_REQUIRED"
    assert report["engineering_gate"]["checks"]["development_global_utility_difference"]["valid"] is False
    assert report["pairs"][0]["variants"]["Event-G"]["metrics"]["direct"]["global_utility"] is None


def test_parent_split_contract_is_an_engineering_gate(case_dir: Path) -> None:
    fixture = _fixture(case_dir)
    fixture["paired_parent_metadata"][0]["split"] = "development"
    report = build_acceptance_report(fixture, case_dir)
    assert report["split_counts"] == {"train": 3, "development": 3}
    assert report["engineering_gate"]["checks"]["parent_split_contract"]["valid"] is False
