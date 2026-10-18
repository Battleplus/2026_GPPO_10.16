from __future__ import annotations

import copy
import hashlib
import json

import pytest

from tools.analyze_baseline_results import METHODS, REQUIRED_METRICS, analyze


def _fixture(profile: str = "formal"):
    seeds = [8201] if profile == "pilot" else [8201, 8202, 8203]
    parents = ["dev-a", "dev-b"]
    episodes = []
    actions = []
    for seed in seeds:
        for parent in parents:
            for method in METHODS:
                metrics = {name: 0 for name in REQUIRED_METRICS}
                metrics.update({"schema": "baseline-production-metrics/1", "global_utility": 10.0,
                                "net_utility": 9.0, "completion_rate": 0.8, "on_time_rate": 0.7,
                                "trigger_count": 0 if method.startswith("Event-") else 1,
                                "planning_invocation_count": 0 if method.startswith("Event-") else 1,
                                "actionable_catalog_planning_count": 0,
                                "nonempty_planning_invocation_count": 0,
                                "environment_action_delivery_message_count": 0 if method.startswith("Event-") else 1})
                if method.startswith("Periodic-"):
                    metrics.update({"effective_reconstruction_count": 2, "reconstruction_size": 2})
                elif method.startswith("Event-"):
                    metrics.update({"effective_reconstruction_count": 1, "reconstruction_size": 1})
                episodes.append({
                    "method_id": method, "parent_id": parent, "seed": seed,
                    "event_tape_id": f"tape-{parent}", "initial_c1_assignment": {"queues": {"p1": ["t1"]}},
                    "tick_count": 1, "metrics": metrics,
                    "independent_seed_sample": method not in {"Greedy", "Auction", "CBBA-lite"},
                })
                raw_state = {"leaf_tasks": [{"id": "t1", "assignee": "p1"}], "leaf_task_specs": [],
                             "root_task_specs": [], "split_manifests": [], "root_mapping": {"t1": "t1"},
                             "leaf_platforms": [], "platform_specs": [], "queues": {"p1": ["t1"]}, "time": 0}
                action = {
                    "schema": "baseline-action-receipt/1", "method_id": method, "parent_id": parent,
                    "seed": seed, "event_tape_id": f"tape-{parent}", "time": 0,
                    "action_id": f"{method}:{seed}:{parent}",
                    "raw_state_before": copy.deepcopy(raw_state),
                    "raw_state_after": copy.deepcopy(raw_state),
                    "affected_scope": {"affected_task_ids": ["t1"], "affected_platform_ids": ["p1"]},
                    "selected_scope": "NOOP", "requested_nonnoop": False,
                    "operation_receipts": [], "command_effects": [],
                }
                if method.startswith("Event-"):
                    action.update({"selected_scope": "LOCAL_REPAIR", "requested_nonnoop": True,
                                   "operation_receipts": [{"originating_action_id": action["action_id"],
                                                           "before_queues": {"p1": ["t1"]},
                                                           "after_queues": {"p1": ["t2", "t1"]}}]})
                actions.append(action)
    manifest = {"status": "complete", "phase": "evaluate", "profile": profile,
                "methods": METHODS, "seeds": seeds, "development_parent_ids": parents,
                "episode_count": len(episodes), "paired_cells": len(episodes)}
    return episodes, manifest, actions, seeds, parents


def _oracle(episodes):
    alias = {
        "critical_failures": "critical_failure_count_priority_ge_5",
        "requested_nonnoop": "requested_nonnoop_count",
        "local_invocation_count": "local_repair_invocation_count",
        "global_invocation_count": "global_replan_invocation_count",
        "owner_change_count": "task_owner_change_count",
    }
    rows = []
    for episode in episodes:
        metrics = episode["metrics"]
        recomputed = dict(metrics)
        for oracle_name, metric_name in alias.items():
            recomputed[oracle_name] = metrics.get(metric_name)
        rows.append({"key": [episode["method_id"], episode["parent_id"], episode["event_tape_id"], episode["seed"]],
                     "recomputed": recomputed})
    return {"schema": "independent-baseline-oracle-report/1", "status": "PASS", "mismatch": [], "missing": [], "episodes": rows}


def _set_metric(episodes, method, name, value):
    for episode in episodes:
        if episode["method_id"] == method:
            episode["metrics"][name] = value


def test_negative_scientific_gate_is_reported_without_changing_completion():
    episodes, manifest, actions, _, _ = _fixture()
    _set_metric(episodes, "Event-GPPO", "global_utility", 9.0)
    result = analyze(episodes, manifest, actions, [], "formal", _oracle(episodes))
    assert result["scientific_gate"] == "RESEARCH_CRITERIA_FAILED"
    assert result["engineering_completion"] == "INCOMPLETE_OR_MISSING"
    assert result["event_gate_pairs"][0]["criteria"]["mean_global_utility_non_decrease"] is False
    assert result["event_gate_pairs"][1]["scientific_gate"] == "PASS"


def test_resource_fields_remain_missing_and_scope_is_explicit():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    result = analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))
    settlement = result["resource_settlement"]
    assert settlement["accounting_scope"] == "MISSING"
    assert settlement["wall_seconds_total"] == "MISSING"
    assert settlement["cpu_seconds_total"] == "MISSING"
    assert result["scientific_gate"] == "PILOT_DESCRIPTIVE_ONLY"


def test_failed_phase_resource_receipt_still_contributes_to_measured_totals(tmp_path):
    success = {"schema": "n02-baseline-guardian-settlement/1", "resource_budget_scope": "per_phase",
               "guardian_exit_code": 0, "runtime_error": None, "wall_seconds": 2.0,
               "cgroup_cpu_seconds_at_start": 1.0, "cgroup_cpu_seconds_at_settlement": 3.0}
    failed = {"schema": "n02-baseline-guardian-settlement/1", "resource_budget_scope": "per_phase",
              "guardian_exit_code": 1, "runtime_error": "stage failed", "wall_seconds": 4.0,
              "cgroup_cpu_seconds_at_start": 3.0, "cgroup_cpu_seconds_at_settlement": 7.0}
    paths = []
    for name, receipt in (("success.json", success), ("failed.json", failed)):
        path = tmp_path / name
        path.write_text(json.dumps(receipt), encoding="utf-8")
        paths.append(path)
    episodes, manifest, actions, _, _ = _fixture("pilot")
    result = analyze(episodes, manifest, actions, paths, "pilot", _oracle(episodes))
    settlement = result["resource_settlement"]
    assert settlement["guardian_cgroup_cpu_seconds"] == 6.0
    assert settlement["wall_seconds_total"] == 6.0
    assert settlement["engineering_settlement"] == "INCOMPLETE_OR_MISSING"


def _write_guardian_receipt(directory, name, *, phase, attempt, status, wall, cpu_start, cpu_end):
    receipt = {
        "schema": "n02-baseline-guardian-settlement/1", "resource_budget_scope": "per_phase",
        "profile": "pilot", "phase": phase, "attempt": attempt, "run_id": "pilot-run",
        "guardian_exit_code": 0 if status == "complete" else 1,
        "runtime_error": None if status == "complete" else "serialization failed",
        "source_config_unchanged": True, "wall_seconds": wall,
        "cgroup_cpu_seconds_at_start": cpu_start,
        "cgroup_cpu_seconds_at_settlement": cpu_end,
    }
    path = directory / name
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_explicit_phase_replacement_closes_failure_and_keeps_its_cost(tmp_path):
    paths = {}
    hashes = {}
    for phase in ("freeze-wm", "train", "evaluate"):
        paths[phase], hashes[phase] = _write_guardian_receipt(
            tmp_path, f"{phase}-success.json", phase=phase, attempt=f"{phase}-active",
            status="complete", wall=2.0, cpu_start=1.0, cpu_end=3.0,
        )
    failed_path, failed_hash = _write_guardian_receipt(
        tmp_path, "train-failed.json", phase="train", attempt="train-failed",
        status="failed", wall=4.0, cpu_start=3.0, cpu_end=7.0,
    )
    active = {
        phase: {"attempt": f"{phase}-active", "receipt_path": str(paths[phase]), "receipt_sha256": hashes[phase]}
        for phase in paths
    }
    resolution = {
        "schema": "n02-baseline-attempt-resolution/1", "profile": "pilot",
        "active_phases": active,
        "supersessions": [{
            "phase": "train", "failed_attempt": "train-failed", "failed_receipt_path": str(failed_path),
            "failed_receipt_sha256": failed_hash, "successful_attempt": "train-active",
            "successful_receipt_path": str(paths["train"]), "successful_receipt_sha256": hashes["train"],
        }],
    }
    episodes, manifest, actions, _, _ = _fixture("pilot")
    result = analyze(episodes, manifest, actions, [*paths.values(), failed_path], "pilot",
                     _oracle(episodes), attempt_resolution=resolution)
    settlement = result["resource_settlement"]
    assert settlement["engineering_settlement"] == "COMPLETE_WITH_MISSING_HISTORICAL_FIELDS"
    assert settlement["required_successful_phase_chain_complete"] is True
    assert settlement["attempt_resolution_valid"] is True
    assert settlement["wall_seconds_total"] == 10.0
    assert settlement["cpu_seconds_total"] == 10.0
    assert settlement["receipt_count"] == 4
    assert result["engineering_completion"] == "COMPLETE"


def test_attempt_resolution_with_missing_required_phase_stays_incomplete(tmp_path):
    paths, hashes = {}, {}
    for phase in ("freeze-wm", "train"):
        paths[phase], hashes[phase] = _write_guardian_receipt(
            tmp_path, f"{phase}.json", phase=phase, attempt=f"{phase}-active",
            status="complete", wall=1.0, cpu_start=0.0, cpu_end=1.0,
        )
    resolution = {
        "schema": "n02-baseline-attempt-resolution/1", "profile": "pilot",
        "active_phases": {
            phase: {"attempt": f"{phase}-active", "receipt_path": str(path), "receipt_sha256": hashes[phase]}
            for phase, path in paths.items()
        },
        "supersessions": [],
    }
    episodes, manifest, actions, _, _ = _fixture("pilot")
    result = analyze(episodes, manifest, actions, list(paths.values()), "pilot",
                     _oracle(episodes), attempt_resolution=resolution)
    assert result["resource_settlement"]["required_successful_phase_chain_complete"] is False
    assert result["resource_settlement"]["engineering_settlement"] == "INCOMPLETE_OR_MISSING"


def test_missing_independent_oracle_cannot_pass_raw_global_gate():
    episodes, manifest, actions, _, _ = _fixture("formal")
    result = analyze(episodes, manifest, actions, [], "formal")
    assert result["scientific_gate"] == "EVIDENCE_MISSING"
    assert result["event_gate_pairs"][0]["criteria"]["mean_global_utility_non_decrease"] == "MISSING"


def test_missing_event_scope_proof_is_reported_as_missing():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    next(row for row in actions if row["method_id"] == "Event-GPPO").pop("affected_scope")
    result = analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))
    pair = result["event_gate_pairs"][0]
    assert pair["criteria"]["empty_scope_global_actions_zero"] == "MISSING"
    assert pair["event_empty_scope_global_action_count"] == "MISSING"


def test_action_bound_dispatch_owner_change_is_local_witness():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    action = next(row for row in actions if row["method_id"] == "Event-GPPO")
    action["operation_receipts"] = []
    action["raw_state_after"]["leaf_tasks"][0]["assignee"] = "p2"
    action["command_effects"] = [{"originating_action_id": action["action_id"], "delivered": True,
                                   "task_id": "t1", "platform_id": "p2", "owner_changed": True,
                                   "queue_order_changed": False}]
    result = analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))
    witnesses = result["event_gate_pairs"][0]["event_local_repair_witnesses"]
    assert any(row["action_id"] == action["action_id"] for row in witnesses)


def test_duplicate_cell_fails_closed():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    episodes.append(copy.deepcopy(episodes[0]))
    with pytest.raises(ValueError, match="EPISODE_COUNT_INCOMPLETE|DUPLICATE_EPISODE_CELL"):
        analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))


def test_tape_or_initial_assignment_mismatch_fails_closed():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    other_method = next(row for row in episodes if row["method_id"] == "GPPO")
    other_method["initial_c1_assignment"] = {"queues": {"p1": ["different"]}}
    with pytest.raises(ValueError, match="TAPE_OR_INITIAL_C1_PAIRING_MISMATCH"):
        analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))


def test_rule_seed_repeats_are_descriptive_and_not_significance():
    episodes, manifest, actions, _, _ = _fixture()
    for row in episodes:
        if row["method_id"] in {"Greedy", "Auction", "CBBA-lite"}:
            row["independent_seed_sample"] = False
    result = analyze(episodes, manifest, actions, [], "formal", _oracle(episodes))
    assert result["statistical_significance_claim"] is False
    assert all(row["independent_training_seeds"] == 0 for row in result["rule_seed_repeats"])
    assert all("descriptive" in row["label"] for row in result["rule_seed_repeats"])


def test_missing_metric_fails_closed_and_missing_local_raw_is_marked():
    episodes, manifest, actions, _, _ = _fixture("pilot")
    del episodes[0]["metrics"]["net_utility"]
    with pytest.raises(ValueError, match="METRIC_MISSING:net_utility"):
        analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))

    episodes, manifest, actions, _, _ = _fixture("pilot")
    event_action = next(row for row in actions if row["method_id"] == "Event-GPPO")
    event_action.pop("raw_state_before")
    result = analyze(episodes, manifest, actions, [], "pilot", _oracle(episodes))
    assert result["event_gate_pairs"][0]["criteria"]["raw_local_repair_witness_present"] == "MISSING"
