from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import baseline_metrics
import baseline_runner


def test_nonnoop_natural_queue_pop_is_not_effective_reconstruction() -> None:
    row = json.loads((Path(__file__).parent / "fixtures" / "baseline_action_receipt_v1.json").read_text(encoding="utf-8"))
    assert row["requested_nonnoop"] is False
    assert row["queues_before"] != row["queues_after"]
    assert baseline_metrics.effective_reconstruction(row) is False


def test_effective_reconstruction_requires_action_operation_or_bound_delivery() -> None:
    requested_noop = {"requested_nonnoop": True, "operation_receipts": [], "command_effects": []}
    assert baseline_metrics.effective_reconstruction(requested_noop) is False
    inserted = {
        "operation_receipts": [{"operation": {"op": "insert", "from_platform": "u1", "to_platform": "u1"},
                                "before_queues": {"u1": ["a", "b"]},
                                "after_queues": {"u1": ["b", "a"]}}],
    }
    assert baseline_metrics.effective_reconstruction(inserted) is True
    unbound = {"command_effects": [{"delivered": True, "owner_changed": True}]}
    assert baseline_metrics.effective_reconstruction(unbound) is False
    delayed = {"command_effects": [{"originating_action_id": "a1", "delivered": True,
                                    "owner_changed": True}]}
    assert baseline_metrics.effective_reconstruction(delayed) is True


def test_pilot003_unrelated_completion_queue_changes_do_not_count() -> None:
    # At t=11 a pending dispatch was delivered while unrelated tasks completed
    # on other platforms. The global queue diff was not a reconstruction.
    row = {
        "owner_change_count": 0,
        "queue_reorder_count": 0,
        "queues_before": {"u1": ["task-09"], "u2": ["part-01-1"]},
        "queues_after": {"u1": [], "u2": []},
        "raw_events": [{"type": "logical_task_completed", "task_id": "task-09"}],
        "command_effects": [{"originating_action_id": "ppo:t10", "delivered": True,
                              "owner_changed": False, "queue_order_changed": True}],
    }
    assert baseline_metrics.effective_reconstruction(row) is False


def test_pilot003_reverted_transfer_queue_change_does_not_count() -> None:
    # The transfer receipt changed its intermediate queue snapshots, but the
    # same-tick dispatch restored the task's prior endpoint owner.
    row = {
        "owner_change_count": 0,
        "queue_reorder_count": 0,
        "operation_receipts": [{
            "operation": {"op": "transfer", "from_platform": "u3", "to_platform": "u4",
                          "task_id": "part-01-2"},
            "before_queues": {"u3": ["part-01-2"], "u4": []},
            "after_queues": {"u3": [], "u4": ["part-01-2"]},
        }],
        "command_effects": [{"originating_action_id": "ppo:t11", "delivered": True,
                              "owner_changed": False, "queue_order_changed": True}],
    }
    assert baseline_metrics.effective_reconstruction(row) is False


def test_canonical_endpoint_counters_and_bound_legacy_fallback() -> None:
    assert baseline_metrics.effective_reconstruction({"owner_change_count": 1, "queue_reorder_count": 0}) is True
    assert baseline_metrics.effective_reconstruction({"owner_change_count": 0, "queue_reorder_count": 1}) is True
    transfer_only = {"operation_receipts": [{
        "operation": {"op": "transfer", "from_platform": "u1", "to_platform": "u2"},
        "before_queues": {"u1": ["task"], "u2": []},
        "after_queues": {"u1": [], "u2": ["task"]},
    }]}
    assert baseline_metrics.effective_reconstruction(transfer_only) is False


def test_runner_queue_order_receipt_is_bound_to_same_platform_insert() -> None:
    transfer = {
        "operation": {"op": "transfer", "from_platform": "u1", "to_platform": "u2"},
        "before_queues": {"u1": ["task"], "u2": []},
        "after_queues": {"u1": [], "u2": ["task"]},
    }
    reorder = {
        "operation": {"op": "insert", "from_platform": "u1", "to_platform": "u1"},
        "before_queues": {"u1": ["task-a", "task-b"]},
        "after_queues": {"u1": ["task-b", "task-a"]},
    }
    assert baseline_runner._operation_queue_order_changed(transfer) is False
    assert baseline_runner._operation_queue_order_changed(reorder) is True


def test_root_level_outcomes_exclude_split_children_and_separate_protocol_cost() -> None:
    initial = [
        {"id": "root-a", "priority": 6.0, "deadline": 10},
        {"id": "root-b", "priority": 4.0, "deadline": 5},
    ]
    final = [
        {"id": "root-a", "status": "completed", "completed_at": 12, "split_mode": "cooperate", "subtask_ids": ["a.1", "a.2"]},
        {"id": "root-b", "status": "cancelled", "cancelled_at": 7},
    ]
    steps = [{"reward": 2.0, "rule_protocol_message_count": 3, "raw_events": [{"type": "task_cancelled", "task_id": "root-b", "time": 7}],
              "reward_primitives": {"energy_units": 5.0, "switch_count": 1}}]
    result = baseline_metrics.summarize_episode(initial_tasks=initial, final_tasks=final, steps=steps,
                                                horizon=60, protocol_message_weight=0.01)
    assert result["original_root_task_count"] == 2
    assert result["completion_rate"] == 0.5
    assert result["on_time_rate"] == 0.0
    assert result["mean_delay_minutes"] == 2.0
    assert result["critical_failure_count_priority_ge_5"] == 0
    assert result["environment_utility"] == 2.0
    assert result["net_utility"] == 1.97
    assert result["energy_units"] == 5.0
    assert result["task_switch_count"] == 1


def test_frozen_profiles_bind_nine_methods_and_r8_source() -> None:
    pilot, _, _ = baseline_runner.load_profile("pilot")
    formal, _, _ = baseline_runner.load_profile("formal")
    assert len(pilot["methods"]) == 9
    assert pilot["data_reuse"]["gate1_freeze_manifest_sha256"] == formal["data_reuse"]["gate1_freeze_manifest_sha256"]
    assert pilot["training"]["max_updates_per_learning_method"] == 32
    assert formal["training"]["max_updates_per_learning_method"] == 128
    assert pilot["evaluation"]["development_parent_count"] == 2
    assert formal["evaluation"]["development_parents_only"] is True
