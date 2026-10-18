#!/usr/bin/env python3
"""Fail-closed paired analysis and resource accounting for N02 baseline runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


METHODS = [
    "Greedy", "Auction", "CBBA-lite", "PPO", "GPPO", "Periodic-GPPO",
    "Event-GPPO", "Event-GPPO-WM", "Periodic-GPPO-WM",
]
RULE_METHODS = {"Greedy", "Auction", "CBBA-lite"}
REQUIRED_METRICS = [
    "global_utility", "net_utility", "completion_rate", "on_time_rate",
    "critical_failure_count_priority_ge_5", "trigger_count", "planning_invocation_count",
    "detector_event_edge_count", "scope_nonempty_planning_count", "actionable_catalog_planning_count",
    "nonempty_planning_invocation_count", "requested_nonnoop_count", "effective_reconstruction_count",
    "reconstruction_size", "local_repair_invocation_count", "global_replan_invocation_count",
    "task_owner_change_count", "queue_reorder_count", "environment_action_delivery_message_count",
    "rule_protocol_message_count", "effective_reconstruction_count",
]
COUNT_METRICS = {
    "critical_failure_count_priority_ge_5", "trigger_count", "planning_invocation_count",
    "detector_event_edge_count", "scope_nonempty_planning_count", "actionable_catalog_planning_count",
    "nonempty_planning_invocation_count", "requested_nonnoop_count", "local_repair_invocation_count",
    "global_replan_invocation_count", "task_owner_change_count", "queue_reorder_count",
    "environment_action_delivery_message_count", "rule_protocol_message_count",
    "effective_reconstruction_count", "reconstruction_size", "empty_scope_global_action_count",
}
REDUCTION_METRICS = [
    "environment_action_delivery_message_count", "rule_protocol_message_count",
    "effective_reconstruction_count", "reconstruction_size",
]
GATE_PAIRS = [
    ("Event-GPPO", "Periodic-GPPO"),
    ("Event-GPPO-WM", "Periodic-GPPO-WM"),
]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"NONFINITE_OR_INVALID:{name}")
    return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
        rows.append(row)
    return rows


def _cell_key(row: dict[str, Any]) -> tuple[int, str, str]:
    seed = row.get("seed")
    parent = row.get("parent_id")
    tape = row.get("event_tape_id")
    if type(seed) is not int or not isinstance(parent, str) or not parent or not isinstance(tape, str) or not tape:
        raise ValueError("EPISODE_IDENTITY_MISSING")
    return seed, parent, tape


def _metrics(row: dict[str, Any]) -> dict[str, float]:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict) or metrics.get("schema") != "baseline-production-metrics/1":
        raise ValueError("PRODUCTION_METRICS_SCHEMA_REQUIRED")
    result = {}
    for name in REQUIRED_METRICS:
        if name not in metrics:
            raise ValueError(f"METRIC_MISSING:{name}")
        value = _finite(metrics[name], name)
        if name in COUNT_METRICS and (value < 0 or not value.is_integer()):
            raise ValueError(f"COUNT_METRIC_INVALID:{name}")
        if name in {"completion_rate", "on_time_rate"} and not 0 <= value <= 1:
            raise ValueError(f"RATE_OUT_OF_RANGE:{name}")
        result[name] = value
    if result["trigger_count"] != result["planning_invocation_count"]:
        raise ValueError("TRIGGER_PLANNING_COUNT_MISMATCH")
    if result["actionable_catalog_planning_count"] != result["nonempty_planning_invocation_count"]:
        raise ValueError("ACTIONABLE_LEGACY_ALIAS_MISMATCH")
    return result


def _scope_ids(receipt: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    scope = receipt.get("affected_scope")
    if not isinstance(scope, dict):
        raise ValueError("RAW_AFFECTED_SCOPE_MISSING")
    tasks, platforms = scope.get("affected_task_ids"), scope.get("affected_platform_ids")
    if not isinstance(tasks, list) or not isinstance(platforms, list):
        raise ValueError("RAW_AFFECTED_SCOPE_IDS_MISSING")
    return tasks, platforms


def _real_local_effect(receipt: dict[str, Any]) -> bool | None:
    if receipt.get("selected_scope") != "LOCAL_REPAIR" or not receipt.get("requested_nonnoop"):
        return False
    before, after = receipt.get("raw_state_before"), receipt.get("raw_state_after")
    required_raw = {"leaf_tasks", "leaf_task_specs", "root_task_specs", "split_manifests", "root_mapping", "leaf_platforms", "platform_specs", "queues", "time"}
    if not isinstance(before, dict) or not isinstance(after, dict) or not required_raw.issubset(before) or not required_raw.issubset(after):
        return None
    operations = receipt.get("operation_receipts")
    if not isinstance(operations, list):
        return None
    for op in operations:
        if not isinstance(op, dict) or not isinstance(op.get("before_queues"), dict) or not isinstance(op.get("after_queues"), dict):
            return None
        if op.get("originating_action_id") != receipt.get("action_id"):
            continue
        if _canonical(op["before_queues"]) != _canonical(op["after_queues"]):
            return True
    effects = receipt.get("command_effects")
    if not isinstance(effects, list):
        return None
    before_owners = {str(row.get("id")): row.get("assignee") for row in before.get("leaf_tasks", []) if isinstance(row, dict)}
    after_owners = {str(row.get("id")): row.get("assignee") for row in after.get("leaf_tasks", []) if isinstance(row, dict)}
    for effect in effects:
        if not isinstance(effect, dict) or effect.get("originating_action_id") != receipt.get("action_id") or effect.get("delivered") is not True:
            continue
        task_id = str(effect.get("task_id", ""))
        if effect.get("owner_changed") is True and task_id in before_owners and task_id in after_owners and before_owners[task_id] != after_owners[task_id]:
            return True
        if effect.get("queue_order_changed") is True and isinstance(effect.get("operation"), dict):
            return True
    return False


def _oracle_index(report: dict[str, Any] | None, index: dict) -> dict | None:
    if not isinstance(report, dict) or report.get("schema") != "independent-baseline-oracle-report/1" or report.get("status") != "PASS":
        return None
    rows = report.get("episodes")
    if not isinstance(rows, list):
        return None
    result = {}
    for row in rows:
        key = row.get("key") if isinstance(row, dict) else None
        calculated = row.get("recomputed") if isinstance(row, dict) else None
        if not isinstance(key, list) or len(key) != 4 or not isinstance(calculated, dict):
            return None
        method, parent, tape, seed = key
        cell = (method, int(seed), parent)
        if cell not in index or index[cell].get("event_tape_id") != tape or cell in result:
            return None
        for name in ("global_utility", "completion_rate", "on_time_rate", "critical_failure_count_priority_ge_5"):
            if name not in calculated:
                return None
            _finite(calculated[name], "oracle." + name)
        result[cell] = calculated
    return result if set(result) == set(index) else None


def _crosscheck_oracle_metrics(index: dict, oracle: dict) -> None:
    aliases = {
        "global_utility": "global_utility", "net_utility": "net_utility",
        "completion_rate": "completion_rate", "on_time_rate": "on_time_rate",
        "critical_failure_count_priority_ge_5": "critical_failures",
        "trigger_count": "trigger_count", "planning_invocation_count": "planning_invocation_count",
        "detector_event_edge_count": "detector_event_edge_count",
        "scope_nonempty_planning_count": "scope_nonempty_planning_count",
        "actionable_catalog_planning_count": "actionable_catalog_planning_count",
        "nonempty_planning_invocation_count": "nonempty_planning_invocation_count",
        "requested_nonnoop_count": "requested_nonnoop", "effective_reconstruction_count": "effective_reconstruction_count",
        "reconstruction_size": "reconstruction_size", "local_repair_invocation_count": "local_invocation_count",
        "global_replan_invocation_count": "global_invocation_count", "task_owner_change_count": "owner_change_count",
        "queue_reorder_count": "queue_reorder_count",
        "environment_action_delivery_message_count": "environment_action_delivery_message_count",
        "rule_protocol_message_count": "rule_protocol_message_count",
    }
    for cell, episode in index.items():
        metrics = episode["_analysis_metrics"]
        recomputed = oracle[cell]
        for metric_name, oracle_name in aliases.items():
            if oracle_name not in recomputed or abs(metrics[metric_name] - _finite(recomputed[oracle_name], "oracle." + oracle_name)) > 1e-8:
                raise ValueError(f"PRODUCTION_ORACLE_METRIC_MISMATCH:{cell}:{metric_name}")


def _validate_inputs(episodes: list[dict[str, Any]], manifest: dict[str, Any], profile: str):
    if manifest.get("status") != "complete" or manifest.get("phase") != "evaluate" or manifest.get("profile") != profile:
        raise ValueError("EVALUATION_MANIFEST_PROFILE_OR_STATUS_INVALID")
    if manifest.get("methods") != METHODS:
        raise ValueError("EVALUATION_MANIFEST_METHODS_INVALID")
    seeds = manifest.get("seeds")
    expected_seeds = [8201] if profile == "pilot" else [8201, 8202, 8203]
    if seeds != expected_seeds:
        raise ValueError("EVALUATION_MANIFEST_SEEDS_INVALID")
    parents = manifest.get("development_parent_ids")
    if not isinstance(parents, list) or len(parents) != 2 or any(not isinstance(x, str) or not x for x in parents) or len(set(parents)) != 2:
        raise ValueError("DEVELOPMENT_PARENT_SET_INVALID")
    expected = len(METHODS) * len(expected_seeds) * len(parents)
    if manifest.get("episode_count") != expected or manifest.get("paired_cells") != expected:
        raise ValueError("EPISODE_COUNT_INCOMPLETE")
    index: dict[tuple[str, int, str], dict[str, Any]] = {}
    signatures: dict[tuple[int, str], str] = {}
    parents_set = set(parents)
    for row in episodes:
        method = row.get("method_id")
        if method not in METHODS:
            raise ValueError("UNKNOWN_METHOD")
        seed, parent, tape = _cell_key(row)
        if seed not in expected_seeds or parent not in parents_set:
            raise ValueError("UNEXPECTED_EPISODE_CELL")
        key = (method, seed, parent)
        if key in index:
            raise ValueError("DUPLICATE_EPISODE_CELL")
        assignment = row.get("initial_c1_assignment")
        if assignment is None:
            raise ValueError("INITIAL_C1_ASSIGNMENT_MISSING")
        signature = _canonical({"tape": tape, "initial_c1_assignment": assignment})
        cross_key = (seed, parent)
        if cross_key in signatures and signatures[cross_key] != signature:
            raise ValueError("TAPE_OR_INITIAL_C1_PAIRING_MISMATCH")
        signatures[cross_key] = signature
        row["_analysis_metrics"] = _metrics(row)
        index[key] = row
    expected_keys = {(method, seed, parent) for method in METHODS for seed in expected_seeds for parent in parents}
    if len(episodes) != expected:
        raise ValueError("EPISODE_COUNT_INCOMPLETE")
    if set(index) != expected_keys:
        raise ValueError("EXPECTED_CELL_SET_MISMATCH")
    return index, expected_seeds, parents


def _resource_settlement(paths: list[Path], profile: str, attempt_resolution: dict[str, Any] | None = None) -> dict[str, Any]:
    records = []
    for path in paths:
        receipt = _read_json(path)
        scope = receipt.get("resource_budget_scope")
        status = receipt.get("status")
        if status is None and receipt.get("schema") == "n02-baseline-guardian-settlement/1":
            status = "complete" if receipt.get("guardian_exit_code") == 0 and receipt.get("runtime_error") is None else "failed"
        wall = receipt.get("wall_seconds")
        cpu = None
        if "cgroup_cpu_seconds_at_start" in receipt and "cgroup_cpu_seconds_at_settlement" in receipt:
            start = _finite(receipt["cgroup_cpu_seconds_at_start"], "cgroup_cpu_seconds_at_start")
            end = _finite(receipt["cgroup_cpu_seconds_at_settlement"], "cgroup_cpu_seconds_at_settlement")
            if end < start:
                raise ValueError(f"CPU_COUNTER_DECREASE:{path}")
            cpu = end - start
        records.append({
            "path": str(path), "schema": receipt.get("schema", "MISSING"),
            "status": status if isinstance(status, str) else "MISSING", "phase": receipt.get("phase", "MISSING"),
            "profile": receipt.get("profile", "MISSING"), "attempt": receipt.get("attempt", "MISSING"),
            "run_id": receipt.get("run_id", "MISSING"),
            "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_config_unchanged": receipt.get("source_config_unchanged", "MISSING"),
            "resource_budget_scope": scope if isinstance(scope, str) else "MISSING",
            "wall_seconds": _finite(wall, "wall_seconds") if wall is not None else "MISSING",
            "cpu_seconds": cpu if cpu is not None else "MISSING",
            "peak_memory_bytes": receipt.get("peak_memory_allocated_bytes", "MISSING"),
        })
    scopes = {row["resource_budget_scope"] for row in records}
    scope_status = "per_phase" if records and scopes == {"per_phase"} else "MISSING"
    wall_vals = [r["wall_seconds"] for r in records]
    cpu_vals = [r["cpu_seconds"] for r in records]
    guardian_records = [row for row in records if row["schema"] == "n02-baseline-guardian-settlement/1"]
    guardian_cpu = [row["cpu_seconds"] for row in guardian_records]
    guardian_wall = [row["wall_seconds"] for row in guardian_records]
    measured_cpu = [value for value in cpu_vals if isinstance(value, float)]
    measured_wall = [value for value in wall_vals if isinstance(value, float)]
    resolution_valid = False
    active_phases: dict[str, str] = {}
    superseded_hashes: set[str] = set()
    if isinstance(attempt_resolution, dict) and attempt_resolution.get("schema") == "n02-baseline-attempt-resolution/1" and attempt_resolution.get("profile") == profile:
        by_hash = {row["receipt_sha256"]: row for row in records}
        active = attempt_resolution.get("active_phases")
        supersessions = attempt_resolution.get("supersessions")
        if isinstance(active, dict) and isinstance(supersessions, list):
            active_ok = True
            for phase in ("freeze-wm", "train", "evaluate"):
                binding = active.get(phase)
                row = by_hash.get(binding.get("receipt_sha256")) if isinstance(binding, dict) else None
                if not row or row["path"] != binding.get("receipt_path") or row["schema"] != "n02-baseline-guardian-settlement/1" or row["phase"] != phase or row["profile"] != profile or row["attempt"] != binding.get("attempt") or row["status"] != "complete" or row["source_config_unchanged"] is not True:
                    active_ok = False
                    break
                active_phases[phase] = row["attempt"]
            supersession_ok = True
            for item in supersessions:
                if not isinstance(item, dict):
                    supersession_ok = False
                    break
                failed = by_hash.get(item.get("failed_receipt_sha256"))
                successful = by_hash.get(item.get("successful_receipt_sha256"))
                phase = item.get("phase")
                if (not failed or not successful or failed["schema"] != "n02-baseline-guardian-settlement/1"
                        or failed["path"] != item.get("failed_receipt_path") or successful["path"] != item.get("successful_receipt_path")
                        or failed["profile"] != profile or failed["status"] != "failed" or failed["phase"] != phase
                        or failed["attempt"] != item.get("failed_attempt") or successful["phase"] != phase
                        or successful["status"] != "complete" or successful["attempt"] != item.get("successful_attempt")
                        or active_phases.get(phase) != successful["attempt"]
                        or active.get(phase, {}).get("receipt_sha256") != item.get("successful_receipt_sha256")
                        or failed["receipt_sha256"] in superseded_hashes):
                    supersession_ok = False
                    break
                superseded_hashes.add(failed["receipt_sha256"])
            failed_receipts_closed = all(row["status"] != "failed" or row["receipt_sha256"] in superseded_hashes for row in records)
            resolution_valid = active_ok and supersession_ok and failed_receipts_closed
    required_phases_present = set(active_phases) == {"freeze-wm", "train", "evaluate"}
    phase_chain_complete = required_phases_present and all(active_phases.get(phase) for phase in ("freeze-wm", "train", "evaluate"))
    settlement_complete = bool(records and scope_status == "per_phase" and guardian_records and phase_chain_complete and resolution_valid)
    return {
        "schema": "n02-baseline-resource-settlement/1", "profile": profile,
        "accounting_scope": scope_status,
        "accounting_rule": "sum every explicitly supplied probe, smoke, launch, and phase receipt, including failed attempts; per-phase budgets are never treated as a single cumulative budget",
        "receipt_count": len(records), "receipts": records,
        "wall_seconds_total": sum(wall_vals) if records and all(isinstance(x, float) for x in wall_vals) else "MISSING",
        "cpu_seconds_total": sum(cpu_vals) if records and all(isinstance(x, float) for x in cpu_vals) else "MISSING",
        "measured_wall_seconds_subtotal": sum(measured_wall) if measured_wall else "MISSING",
        "measured_cpu_seconds_subtotal": sum(measured_cpu) if measured_cpu else "MISSING",
        "guardian_cgroup_wall_seconds": sum(guardian_wall) if guardian_wall and all(isinstance(x, float) for x in guardian_wall) else "MISSING",
        "guardian_cgroup_cpu_seconds": sum(guardian_cpu) if guardian_cpu and all(isinstance(x, float) for x in guardian_cpu) else "MISSING",
        "historical_transport_cpu_seconds": "MISSING",
        "missing_wall_receipt_count": sum(x == "MISSING" for x in wall_vals),
        "missing_cpu_receipt_count": sum(x == "MISSING" for x in cpu_vals),
        "attempt_resolution_schema": attempt_resolution.get("schema", "MISSING") if isinstance(attempt_resolution, dict) else "MISSING",
        "attempt_resolution_valid": resolution_valid,
        "active_phase_attempts": active_phases,
        "superseded_failed_receipt_sha256": sorted(superseded_hashes),
        "required_successful_phase_chain_complete": phase_chain_complete,
        "engineering_settlement": (
            "MISSING" if not records else
            "COMPLETE_WITH_MISSING_HISTORICAL_FIELDS"
            if settlement_complete
            else "INCOMPLETE_OR_MISSING"
        ),
    }


def analyze(episodes: list[dict[str, Any]], manifest: dict[str, Any], actions: list[dict[str, Any]],
            resource_paths: list[Path], profile: str, oracle_report: dict[str, Any] | None = None,
            attempt_resolution: dict[str, Any] | None = None) -> dict[str, Any]:
    index, seeds, parents = _validate_inputs(episodes, manifest, profile)
    oracle = _oracle_index(oracle_report, index)
    if oracle is not None:
        _crosscheck_oracle_metrics(index, oracle)
    resource_result = _resource_settlement(resource_paths, profile, attempt_resolution)
    action_by_cell: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for receipt in actions:
        if receipt.get("schema") != "baseline-action-receipt/1":
            raise ValueError("ACTION_RECEIPT_SCHEMA_INVALID")
        seed, parent, _ = _cell_key(receipt)
        key = (receipt.get("method_id"), seed, parent)
        if key not in index:
            raise ValueError("ACTION_RECEIPT_UNMATCHED_EPISODE")
        if receipt.get("event_tape_id") != index[key].get("event_tape_id"):
            raise ValueError("ACTION_EPISODE_TAPE_MISMATCH")
        action_by_cell[key].append(receipt)
    for key, episode in index.items():
        rows = action_by_cell.get(key, [])
        if len(rows) != episode.get("tick_count") or not rows:
            raise ValueError("ACTION_RECEIPTS_INCOMPLETE")
        ordered = sorted(rows, key=lambda row: row.get("time", -1))
        if len({row.get("time") for row in ordered}) != len(ordered):
            raise ValueError("DUPLICATE_ACTION_TICK")
        if [row.get("time") for row in ordered] != list(range(episode["tick_count"])):
            raise ValueError("ACTION_TICKS_INCOMPLETE")
        for row in ordered:
            if "time" not in row:
                raise ValueError("ACTION_TICK_IDENTITY_MISSING")
    method_summary = {}
    for method in METHODS:
        rows = [index[(method, seed, parent)]["_analysis_metrics"] for seed in seeds for parent in parents]
        method_summary[method] = {name: sum(row[name] for row in rows) / len(rows) for name in REQUIRED_METRICS}

    pair_reports = []
    for event_method, periodic_method in GATE_PAIRS:
        diffs: dict[str, list[float]] = defaultdict(list)
        event_empty_global = 0
        empty_scope_evidence_complete = True
        local_evidence_complete = True
        local_witnesses = []
        raw_global_differences: list[float] = []
        for seed in seeds:
            for parent in parents:
                event_row = index[(event_method, seed, parent)]
                periodic_row = index[(periodic_method, seed, parent)]
                for name in REQUIRED_METRICS:
                    diffs[name].append(event_row["_analysis_metrics"][name] - periodic_row["_analysis_metrics"][name])
                if oracle is not None:
                    raw_global_differences.append(oracle[(event_method, seed, parent)]["global_utility"] - oracle[(periodic_method, seed, parent)]["global_utility"])
                for action in action_by_cell[(event_method, seed, parent)]:
                    try:
                        tasks, platforms = _scope_ids(action)
                    except ValueError:
                        empty_scope_evidence_complete = False
                        tasks, platforms = [], []
                    if action.get("selected_scope") == "GLOBAL_REPLAN" and not tasks and not platforms:
                        if empty_scope_evidence_complete:
                            event_empty_global += 1
                    witness = _real_local_effect(action)
                    if witness is None:
                        local_evidence_complete = False
                    elif witness:
                        local_witnesses.append({"seed": seed, "parent_id": parent, "time": action.get("time"), "action_id": action.get("action_id")})
        means = {name: sum(values) / len(values) for name, values in diffs.items()}
        raw_global_mean = sum(raw_global_differences) / len(raw_global_differences) if raw_global_differences else None
        reductions = {name: means[name] < 0 for name in REDUCTION_METRICS}
        criteria = {
            "mean_global_utility_non_decrease": (raw_global_mean >= 0) if raw_global_mean is not None else "MISSING",
            "critical_failures_not_increased": means["critical_failure_count_priority_ge_5"] <= 0,
            "completion_drop_within_0_02": means["completion_rate"] >= -0.02,
            "on_time_drop_within_0_02": means["on_time_rate"] >= -0.02,
            "planning_invocations_lower": means["planning_invocation_count"] < 0,
            "at_least_one_resource_or_reconstruction_metric_lower": any(reductions.values()),
            "empty_scope_global_actions_zero": (event_empty_global == 0) if empty_scope_evidence_complete else "MISSING",
            "raw_local_repair_witness_present": bool(local_witnesses) if local_evidence_complete else "MISSING",
        }
        pair_reports.append({
            "event_method": event_method, "periodic_method": periodic_method,
            "paired_cell_count": len(seeds) * len(parents), "paired_mean_event_minus_periodic": means,
            "independent_raw_paired_mean_global_utility_difference": raw_global_mean,
            "independent_oracle_status": "PASS" if oracle is not None else "MISSING",
            "reduction_checks": reductions, "event_empty_scope_global_action_count": event_empty_global if empty_scope_evidence_complete else "MISSING",
            "event_local_repair_witnesses": local_witnesses,
            "criteria": criteria, "scientific_gate": (
                "EVIDENCE_MISSING" if any(value == "MISSING" for value in criteria.values()) else
                "PILOT_DESCRIPTIVE_ONLY" if profile == "pilot" else
                "PASS" if all(value is True for value in criteria.values()) else "RESEARCH_CRITERIA_FAILED"
            ),
            "net_utility_is_secondary": True,
        })
    paired_descriptive = []
    descriptive_pairs = [("PPO", "GPPO"), ("Greedy", "Auction"), ("Greedy", "CBBA-lite"), ("Auction", "CBBA-lite")]
    for left, right in descriptive_pairs:
        paired_descriptive.append({
            "left": left, "right": right, "paired_cell_count": len(seeds) * len(parents),
            "mean_left_minus_right": {
                name: sum(index[(left, s, p)]["_analysis_metrics"][name] - index[(right, s, p)]["_analysis_metrics"][name]
                          for s in seeds for p in parents) / (len(seeds) * len(parents))
                for name in REQUIRED_METRICS
            }, "interpretation": "paired descriptive observations only; no significance claim",
        })
    rule_repeats = []
    for method in sorted(RULE_METHODS):
        for parent in parents:
            rows = [index[(method, seed, parent)] for seed in seeds]
            if len(rows) > 1 and all(row.get("independent_seed_sample") is False for row in rows):
                rule_repeats.append({"method": method, "parent_id": parent, "seed_repeats": len(rows), "independent_training_seeds": 0, "label": "descriptive deterministic repeat"})
    return {
        "schema": "n02-baseline-final-comparison/1", "profile": profile,
        "run_status": "PILOT_COMPLETE" if profile == "pilot" else "FORMAL_COMPLETE",
        "scientific_gate": "PILOT_DESCRIPTIVE_ONLY" if profile == "pilot" else ("PASS" if all(row["scientific_gate"] == "PASS" for row in pair_reports) else ("EVIDENCE_MISSING" if any(row["scientific_gate"] == "EVIDENCE_MISSING" for row in pair_reports) else "RESEARCH_CRITERIA_FAILED")),
        "engineering_completion": "COMPLETE" if resource_result["engineering_settlement"] == "COMPLETE_WITH_MISSING_HISTORICAL_FIELDS" else "INCOMPLETE_OR_MISSING",
        "cell_count": len(index), "expected_cell_count": 18 if profile == "pilot" else 54,
        "methods": METHODS, "development_parent_ids": parents, "seeds": seeds,
        "method_summary_source": "baseline-production-metrics/1; raw global utility gate uses only the independent oracle",
        "method_means": method_summary, "event_gate_pairs": pair_reports,
        "other_paired_descriptive_comparisons": paired_descriptive,
        "rule_seed_repeats": rule_repeats,
        "statistical_significance_claim": False,
        "resource_settlement": resource_result,
    }


def _write_outputs(result: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "FINAL_METHOD_COMPARISON.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    method_rows = [f"| {method} | {values['global_utility']:.4f} | {values['net_utility']:.4f} | {values['completion_rate']:.4f} | {values['on_time_rate']:.4f} | {values['planning_invocation_count']:.2f} |" for method, values in result["method_means"].items()]
    report = ["# N02 Baseline Method Comparison", "", f"Profile: `{result['profile']}`; run status: `{result['run_status']}`; scientific gate: `{result['scientific_gate']}`.", "", f"Cells: {result['cell_count']} / {result['expected_cell_count']}. Results are paired descriptive observations; no statistical significance claim is made.", "", "Method means use production summaries after oracle cross-check when available. Frozen global utility gates use the independent oracle only; absent oracle evidence is `MISSING`.", "", "| Method | Global utility | Net utility | Completion | On time | Planning invocations |", "|---|---:|---:|---:|---:|---:|---|"] + method_rows
    report += ["", "Rule methods use the candidate-constrained implementations specified by the protocol. Repeated deterministic rule trajectories are descriptive repeats, not independent training seeds.", "", "An unsuccessful scientific threshold is reported as `RESEARCH_CRITERIA_FAILED`; it does not change the engineering completion status."]
    (out_dir / "FINAL_BASELINE_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    trigger_lines = ["# N02 Event Trigger Comparison", "", f"Profile: `{result['profile']}`; gate status: `{result['scientific_gate']}`.", "", "Paired mean differences are Event minus Periodic. Net utility is secondary and does not replace global utility."]
    for pair in result["event_gate_pairs"]:
        trigger_lines += ["", f"## {pair['event_method']} vs {pair['periodic_method']}", "", f"Paired cells: {pair['paired_cell_count']}; gate: `{pair['scientific_gate']}`.", "", "| Criterion | Result |", "|---|---|"]
        trigger_lines += [f"| {key} | {value if isinstance(value, str) else ('PASS' if value else 'FAIL')} |" for key, value in pair["criteria"].items()]
        witness_count = len(pair["event_local_repair_witnesses"]) if pair["criteria"]["raw_local_repair_witness_present"] != "MISSING" else "MISSING"
        trigger_lines += ["", f"Empty-scope global actions: {pair['event_empty_scope_global_action_count']}; raw local repair witnesses: {witness_count}."]
    (out_dir / "FINAL_TRIGGER_REPORT.md").write_text("\n".join(trigger_lines) + "\n", encoding="utf-8")
    (out_dir / "FINAL_RESOURCE_SETTLEMENT.json").write_text(json.dumps(result["resource_settlement"], ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True, help="raw EVALUATION_ACTION_RECEIPTS.jsonl")
    parser.add_argument("--oracle-report", type=Path, help="PASS report from independent_baseline_oracle.py; without it raw utility gate is MISSING")
    parser.add_argument("--profile", choices=("pilot", "formal"), required=True)
    parser.add_argument("--resource-receipt", type=Path, action="append", default=[], help="repeat for every probe, smoke, launch, and phase settlement receipt")
    parser.add_argument("--attempt-resolution", type=Path, help="explicit hash-bound active phase attempts and failed-attempt supersessions")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    oracle_report = _read_json(args.oracle_report) if args.oracle_report else None
    attempt_resolution = _read_json(args.attempt_resolution) if args.attempt_resolution else None
    result = analyze(_read_jsonl(args.episodes), _read_json(args.manifest), _read_jsonl(args.actions), args.resource_receipt, args.profile, oracle_report, attempt_resolution)
    _write_outputs(result, args.output_dir)
    print(json.dumps({"status": result["run_status"], "scientific_gate": result["scientific_gate"], "cell_count": result["cell_count"], "output_dir": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
