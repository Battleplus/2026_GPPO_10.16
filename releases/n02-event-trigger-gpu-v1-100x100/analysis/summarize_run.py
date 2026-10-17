#!/usr/bin/env python3
"""Independent, read-only summary of an N02 final evidence snapshot.

Uses only Python's standard library. It never imports the producer package or
executes training/simulation code. Missing measurements are emitted as MISSING.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
from pathlib import Path

METHODS = ("Periodic-G", "Event-G", "Periodic-G-WM", "Event-G-WM")
SEEDS = (8201, 8202, 8203)
PARENTS = (
    "n02-event-development-05-environment_perturbation",
    "n02-event-development-06-mixed_events",
)
METRICS = (
    "completion", "on_time", "delay", "unmet", "critical_fail", "utility",
    "reported_effective_reconstruction_count", "independently_verified_effective_count",
    "independently_verified_effective_count_lower_bound", "independently_verified_effective_count_upper_bound",
    "reported_local_effective_count", "reported_global_effective_count",
    "concrete_nonnoop_action_count", "requested_reconstruction_count", "trigger_count",
    "transition_requested_count", "transition_trigger_count",
    "independently_verified_local_effective_count", "independently_verified_global_effective_count",
    "producer_local_scope_selected_count", "producer_global_scope_selected_count",
    "communication", "compute_time",
    "energy", "constraint_violations", "platform_load", "risk",
)
SUMMARY_METRICS = (
    "trigger_count", "reported_effective_reconstruction_count",
    "independently_verified_effective_count", "independently_verified_effective_count_lower_bound",
    "independently_verified_effective_count_upper_bound", "communication", "completion",
    "on_time", "delay", "unmet", "critical_fail", "utility",
)
CONTRASTS = (
    ("Event-G minus Periodic-G", "Event-G", "Periodic-G"),
    ("Event-G-WM minus Event-G", "Event-G-WM", "Event-G"),
    ("Event-G-WM minus Periodic-G", "Event-G-WM", "Periodic-G"),
    ("Periodic-G-WM minus Periodic-G", "Periodic-G-WM", "Periodic-G"),
)

ALIASES = {
    "completion": ("completion_rate", "task_completion_rate", "completion", "completed_tasks"),
    "on_time": ("on_time_rate", "on_time_completion_rate", "on_time", "tasks_on_time"),
    "delay": ("mean_delay", "average_delay", "delay", "total_delay"),
    "unmet": ("unmet_demand", "unmet", "unmet_quantity"),
    "critical_fail": ("critical_failure_rate", "critical_failures", "critical_fail"),
    "utility": ("global_utility", "utility", "episode_utility", "return"),
    "communication": ("communication_cost", "communication", "communication_bytes", "comm_bytes"),
    "compute_time": ("compute_time", "decision_time", "elapsed_seconds", "runtime_seconds"),
    "energy": ("energy_used", "energy_consumption", "energy", "total_energy"),
    "constraint_violations": ("constraint_violations", "violation_count", "violations"),
    "platform_load": ("platform_load_balance", "load_balance", "platform_load"),
    "risk": ("safety_risk", "risk", "risk_score"),
}


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path):
    rows = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def nested_values(obj, aliases):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in aliases and isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append(float(value))
            else:
                found.extend(nested_values(value, aliases))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(nested_values(value, aliases))
    return found


def first_present(row, keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def requested(row):
    value = row.get("requested_non_noop_decision")
    if value is not None:
        return bool(value)
    decision = row.get("decision") or {}
    action = row.get("selected_action") or {}
    return bool(decision.get("triggered") and not action.get("noop", False))


def triggered(row):
    decision = row.get("decision") or {}
    if "triggered" in decision:
        return bool(decision["triggered"])
    return bool(first_present(row, ("triggered", "event_triggered")))


def action_scope(row):
    action = row.get("selected_action") or {}
    scope = (action.get("scope") or row.get("scope") or "").upper()
    if scope in ("LOCAL_REPAIR", "LOCAL") or "LOCAL" in scope:
        return "local"
    if scope in ("GLOBAL_REPLAN", "GLOBAL") or "GLOBAL" in scope:
        return "global"
    return ""


def concrete_nonnoop(row):
    action = row.get("selected_action") or {}
    receipt = row.get("repair_receipt") or {}
    if action.get("noop") is True or not action or not requested(row):
        return False
    if receipt and receipt.get("postrepair_legal") is False:
        return False
    return bool(action.get("dispatches") or action.get("queue_operations"))


def verified_allocation_change(row):
    """Verify allocation changes from owner-change or queue-order receipts."""
    action = row.get("selected_action") or row.get("executed_action") or {}
    if action.get("noop") is True or not requested(row):
        return False
    info = row.get("info") or {}
    events = list(info.get("raw_events") or [])
    operation_receipts = info.get("operation_receipts")
    if operation_receipts is None:
        operation_receipts = []
    confirmed = False
    observed_receipt = False
    for receipt in operation_receipts:
        before, after = receipt.get("before_queues"), receipt.get("after_queues")
        if isinstance(before, dict) and isinstance(after, dict):
            observed_receipt = True
            if before != after:
                confirmed = True
    for event in events:
        event_type = event.get("type")
        if event_type == "task_owner_change":
            previous = event.get("previous_owners")
            new = event.get("new_owners")
            if isinstance(previous, list) and isinstance(new, list):
                observed_receipt = True
                confirmed = confirmed or sorted(previous) != sorted(new)
        elif event_type == "queue_reorder":
            before, after = event.get("before_queues"), event.get("after_queues")
            # event_environment emits the affected platform's queue as two
            # ordered lists; order itself is the allocation mutation here.
            if (isinstance(before, list) and isinstance(after, list)
                    and all(isinstance(task, str) for task in before + after)
                    and isinstance(event.get("platform_id"), str)):
                observed_receipt = True
                confirmed = confirmed or before != after
    if observed_receipt:
        return confirmed
    return None


def summarize_transitions(rows):
    out = {"trigger_count": sum(triggered(r) for r in rows),
           "requested_reconstruction_count": sum(requested(r) for r in rows),
           "concrete_nonnoop_action_count": sum(concrete_nonnoop(r) for r in rows),
           "reported_effective_reconstruction_count": 0,
           "independently_verified_effective_count": 0,
           "independently_verified_effective_known": True,
           "independently_verified_effective_count_lower_bound": 0,
           "independently_verified_effective_count_upper_bound": 0,
           "independently_verified_effective_unknown_actions": 0,
           "independently_verified_local_effective_count": 0,
           "independently_verified_global_effective_count": 0,
           "producer_local_scope_selected_count": 0,
           "producer_global_scope_selected_count": 0,
           "transition_requested_count": 0,
           "transition_trigger_count": 0,
           "receipt_gap_rows": [],
           "recomputed_transitions": len(rows)}
    for row in rows:
        out["transition_requested_count"] += int(requested(row))
        out["transition_trigger_count"] += int(triggered(row))
        info = row.get("info") or {}
        receipt_value = row.get("effective_reconstruction_count", info.get("effective_reconstruction_count"))
        if receipt_value is not None:
            out["reported_effective_reconstruction_count"] += int(receipt_value)
        scope = action_scope(row)
        if scope == "local":
            out["producer_local_scope_selected_count"] += 1
        elif scope == "global":
            out["producer_global_scope_selected_count"] += 1
        change = verified_allocation_change(row)
        if change is None:
            out["independently_verified_effective_known"] = False
            out["independently_verified_effective_unknown_actions"] += 1
            out["receipt_gap_rows"].append({
                "step": row.get("step", "MISSING"),
                "scope": scope or "MISSING",
                "concrete_nonnoop_action": concrete_nonnoop(row),
                "reason": "selected/requested action has no valid owner-change, queue-reorder, or before/after queue receipt",
            })
        elif change:
            out["independently_verified_effective_count"] += 1
            if scope == "local":
                out["independently_verified_local_effective_count"] += 1
            elif scope == "global":
                out["independently_verified_global_effective_count"] += 1
    out["independently_verified_effective_count_lower_bound"] = out["independently_verified_effective_count"]
    out["independently_verified_effective_count_upper_bound"] = (
        out["independently_verified_effective_count"] + out["independently_verified_effective_unknown_actions"]
    )
    if not out["independently_verified_effective_known"]:
        out["independently_verified_effective_count"] = "MISSING"
        out["independently_verified_local_effective_count"] = "MISSING"
        out["independently_verified_global_effective_count"] = "MISSING"
    return out


def locate_transition_files(root: Path):
    found = {}
    for path in root.rglob("*.jsonl"):
        parts = path.parts
        method = next((m for m in METHODS if m in parts), None)
        seed = next((int(re.search(r"820[123]", p).group()) for p in parts if re.search(r"820[123]", p)), None)
        parent = next((p for p in PARENTS if p in path.name), None)
        if method and seed and parent and path.name.endswith((".jsonl",)):
            rows = read_jsonl(path)
            if rows and any(str(r.get("schema", "")).startswith("n02-event-policy-transition") for r in rows):
                found[(method, seed, parent)] = (path, rows)
    return found


def load_producer_evaluation(root: Path):
    data = read_json(root / "DEVELOPMENT_EVALUATION.json")
    result = {}
    if not isinstance(data, dict):
        return result
    for method, episodes in (data.get("episodes") or {}).items():
        for episode in episodes if isinstance(episodes, list) else []:
            result[(method, int(episode.get("seed", -1)), episode.get("parent_id"))] = episode
    return result


def producer_metric(episode, metric):
    if not isinstance(episode, dict):
        return "MISSING"
    env = episode.get("environment_metrics") or {}
    trajectory = episode.get("trajectory_summary") or {}
    violations = env.get("constraint_violations")
    mapping = {
        "completion": env.get("completion_rate"), "on_time": env.get("on_time_rate"),
        "delay": env.get("mean_delay", env.get("mean_delay_minutes", episode.get("mean_delay"))),
        "unmet": env.get("unmet_demand", episode.get("unmet_demand")),
        "critical_fail": env.get("critical_failure_rate"),
        "utility": env.get("global_utility", episode.get("total_reward")),
        "communication": env.get("communication_messages"), "compute_time": episode.get("wall_seconds"),
        "energy": env.get("energy_used"),
        "constraint_violations": sum(violations.values()) if isinstance(violations, dict) else None,
        "platform_load": env.get("load_balance"), "risk": env.get("safety_risk"),
        "trigger_count": episode.get("trigger_count"),
        "requested_reconstruction_count": episode.get("requested_non_noop_decision_count", episode.get("requested_reconstruction_count")),
        "reported_effective_reconstruction_count": episode.get("effective_reconstruction_count", trajectory.get("effective_reconstruction_count")),
        "reported_local_effective_count": (trajectory.get("effective_scope_counts") or {}).get("LOCAL_REPAIR"),
        "reported_global_effective_count": (trajectory.get("effective_scope_counts") or {}).get("GLOBAL_REPLAN"),
        "producer_local_scope_selected_count": (trajectory.get("scope_counts") or {}).get("LOCAL_REPAIR"),
        "producer_global_scope_selected_count": (trajectory.get("scope_counts") or {}).get("GLOBAL_REPLAN"),
    }
    value = mapping.get(metric)
    return value if value is not None else "MISSING"


def same_value(left, right):
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return left == right


def numeric_or_none(value):
    try:
        if value == "MISSING" or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def metric_unit(metric):
    if metric == "delay":
        return "minutes per original task (source mean_delay)"
    if metric in ("completion", "on_time", "critical_fail"):
        return "fraction"
    if metric == "utility":
        return "reward units"
    if metric in ("trigger_count", "reported_effective_reconstruction_count",
                  "independently_verified_effective_count", "independently_verified_effective_count_lower_bound",
                  "independently_verified_effective_count_upper_bound", "communication"):
        return "count"
    if metric == "unmet":
        return "source units"
    return "source units"


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def artifact_inventory(root: Path):
    patterns = re.compile(r"world.?model|g.?gwm|resource|settlement|ledger|receipt|restore|uncert|ranking|critic|gradient|freeze", re.I)
    key_pattern = re.compile(r"world|model|uncert|rank|regret|unknown|gradient|freeze|restore|cuda|gpu|energy|time|communication|ledger|receipt|update", re.I)
    inventory = []
    for path in root.rglob("*"):
        if not path.is_file() or not patterns.search(path.name):
            continue
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            size = path.stat().st_size
        except OSError:
            continue
        values = []
        if path.suffix.lower() == ".json":
            data = read_json(path)
            def walk(obj, prefix=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        name = f"{prefix}.{key}" if prefix else str(key)
                        if key_pattern.search(str(key)) and not isinstance(value, (dict, list)):
                            values.append(f"{name}={value}")
                        walk(value, name)
                elif isinstance(obj, list):
                    for index, value in enumerate(obj):
                        walk(value, f"{prefix}[{index}]")
            walk(data)
        inventory.append({"artifact": str(path.relative_to(root)), "bytes": size,
                          "sha256": digest.hexdigest(),
                          "selected_fields_json": json.dumps(values[:200], ensure_ascii=False) if values else "MISSING"})
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Read-only final snapshot directory")
    parser.add_argument("--output", required=True, type=Path, help="New report directory")
    parser.add_argument("--example-label", default=None, help="Label non-GPU examples, e.g. CPU-example")
    args = parser.parse_args()
    root = args.input.resolve()
    out = args.output.resolve()
    if not root.is_dir():
        parser.error(f"input directory does not exist: {root}")
    if out.exists() and any(out.iterdir()):
        parser.error(f"output directory must be new or empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    located = locate_transition_files(root)
    producer_rows = load_producer_evaluation(root)
    rows_out = []
    producer_checks = []
    receipt_gaps = []
    expected = 0
    for method in METHODS:
        for seed in SEEDS:
            for parent in PARENTS:
                expected += 1
                item = located.get((method, seed, parent))
                producer_episode = producer_rows.get((method, seed, parent))
                base = {"method": method, "seed": seed, "development_parent": parent,
                        "evidence_file": "MISSING", "n_transitions": 0,
                        "producer_mismatch_count": "MISSING", "producer_mismatches_json": "MISSING"}
                for metric in METRICS:
                    base[metric] = producer_metric(producer_episode, metric)
                if item:
                    path, transitions = item
                    base.update({"evidence_file": str(path.relative_to(root)), "n_transitions": len(transitions)})
                    counts = summarize_transitions(transitions)
                    for gap in counts["receipt_gap_rows"]:
                        receipt_gaps.append({"method": method, "seed": seed, "development_parent": parent, **gap})
                    for key, value in counts.items():
                        if key not in ("recomputed_transitions", "independently_verified_effective_known",
                                       "trigger_count", "requested_reconstruction_count", "receipt_gap_rows"):
                            base[key] = value
                    comparisons = [
                        ("trigger_count", counts["transition_trigger_count"], producer_metric(producer_episode, "trigger_count")),
                        ("requested_reconstruction_count", counts["transition_requested_count"], producer_metric(producer_episode, "requested_reconstruction_count")),
                        ("reported_effective_reconstruction_count", counts["reported_effective_reconstruction_count"], producer_metric(producer_episode, "reported_effective_reconstruction_count")),
                        ("producer_local_scope_selected_count", counts["producer_local_scope_selected_count"], producer_metric(producer_episode, "producer_local_scope_selected_count")),
                        ("producer_global_scope_selected_count", counts["producer_global_scope_selected_count"], producer_metric(producer_episode, "producer_global_scope_selected_count")),
                        ("independently_verified_local_effective_count", counts["independently_verified_local_effective_count"], producer_metric(producer_episode, "reported_local_effective_count")),
                        ("independently_verified_global_effective_count", counts["independently_verified_global_effective_count"], producer_metric(producer_episode, "reported_global_effective_count")),
                    ]
                    mismatches = []
                    for metric_name, independent, producer in comparisons:
                        match = "MISSING" if independent == "MISSING" or producer == "MISSING" else same_value(independent, producer)
                        if match is False:
                            mismatches.append({"metric": metric_name, "transition_recount": independent,
                                               "producer_development_evaluation": producer})
                        producer_checks.append({"method": method, "seed": seed, "development_parent": parent,
                                                "metric": metric_name, "transition_recount": independent,
                                                "producer_development_evaluation": producer, "match": match})
                    producer_checks.append({"method": method, "seed": seed, "development_parent": parent,
                                            "metric": "independently_verified_effective_count",
                                            "transition_recount": counts["independently_verified_effective_count"],
                                            "producer_development_evaluation": producer_metric(producer_episode, "reported_effective_reconstruction_count"),
                                            "match": "MISSING" if counts["independently_verified_effective_count"] == "MISSING" else same_value(counts["independently_verified_effective_count"], producer_metric(producer_episode, "reported_effective_reconstruction_count"))})
                    base["producer_mismatch_count"] = len(mismatches)
                    base["producer_mismatches_json"] = json.dumps(mismatches, ensure_ascii=False)
                rows_out.append(base)

    fields = ["method", "seed", "development_parent", "evidence_file", "n_transitions"] + list(METRICS) + [
        "producer_mismatch_count", "producer_mismatches_json"]
    write_csv(out / "paired_comparison.csv", rows_out, fields)
    method_summaries = []
    for method in METHODS:
        method_rows = [row for row in rows_out if row["method"] == method]
        for metric in SUMMARY_METRICS:
            values = [value for row in method_rows if (value := numeric_or_none(row.get(metric))) is not None]
            method_summaries.append({"method": method, "metric": metric,
                                     "unit": metric_unit(metric),
                                     "mean": statistics.mean(values) if values else "MISSING",
                                     "valid_cells": len(values), "missing_cells": len(method_rows) - len(values),
                                     "total_cells": len(method_rows), "interpretation": "descriptive mean across available method×seed×parent cells; not DEVELOPMENT_EVALUATION.descriptive_means"})
    write_csv(out / "method_summary.csv", method_summaries,
              ["method", "metric", "unit", "mean", "valid_cells", "missing_cells", "total_cells", "interpretation"])

    paired_contrasts = []
    by_cell = {(row["method"], row["seed"], row["development_parent"]): row for row in rows_out}
    for label, method_a, method_b in CONTRASTS:
        for metric in SUMMARY_METRICS:
            differences = []
            missing_cells = []
            for seed in SEEDS:
                for parent in PARENTS:
                    left = by_cell.get((method_a, seed, parent), {}).get(metric, "MISSING")
                    right = by_cell.get((method_b, seed, parent), {}).get(metric, "MISSING")
                    left_num, right_num = numeric_or_none(left), numeric_or_none(right)
                    if left_num is None or right_num is None:
                        missing_cells.append(f"seed={seed}|parent={parent}")
                    else:
                        differences.append(left_num - right_num)
            paired_contrasts.append({"contrast": label, "method_a": method_a, "method_b": method_b,
                                     "metric": metric,
                                     "unit": metric_unit(metric),
                                     "mean_paired_difference_a_minus_b": statistics.mean(differences) if differences else "MISSING",
                                     "mean_difference_lower_bound": "MISSING",
                                     "mean_difference_upper_bound": "MISSING",
                                     "valid_pairs": len(differences), "missing_pairs": len(missing_cells),
                                     "total_matched_pairs": len(SEEDS) * len(PARENTS),
                                     "missing_pair_cells_json": json.dumps(missing_cells),
                                     "interpretation": "descriptive paired difference only; no significance test"})
            if metric == "independently_verified_effective_count":
                lower_differences, upper_differences = [], []
                for seed in SEEDS:
                    for parent in PARENTS:
                        left = by_cell.get((method_a, seed, parent), {})
                        right = by_cell.get((method_b, seed, parent), {})
                        left_low = numeric_or_none(left.get("independently_verified_effective_count_lower_bound"))
                        left_high = numeric_or_none(left.get("independently_verified_effective_count_upper_bound"))
                        right_low = numeric_or_none(right.get("independently_verified_effective_count_lower_bound"))
                        right_high = numeric_or_none(right.get("independently_verified_effective_count_upper_bound"))
                        if None not in (left_low, left_high, right_low, right_high):
                            lower_differences.append(left_low - right_high)
                            upper_differences.append(left_high - right_low)
                paired_contrasts[-1]["mean_difference_lower_bound"] = statistics.mean(lower_differences) if lower_differences else "MISSING"
                paired_contrasts[-1]["mean_difference_upper_bound"] = statistics.mean(upper_differences) if upper_differences else "MISSING"
    write_csv(out / "paired_contrasts.csv", paired_contrasts,
              ["contrast", "method_a", "method_b", "metric", "unit", "mean_paired_difference_a_minus_b",
               "mean_difference_lower_bound", "mean_difference_upper_bound",
               "valid_pairs", "missing_pairs", "total_matched_pairs", "missing_pair_cells_json", "interpretation"])
    write_csv(out / "producer_crosscheck.csv", producer_checks,
              ["method", "seed", "development_parent", "metric", "transition_recount",
               "producer_development_evaluation", "match"])
    write_csv(out / "receipt_gaps.csv", receipt_gaps,
              ["method", "seed", "development_parent", "step", "scope", "concrete_nonnoop_action", "reason"])
    artifacts = artifact_inventory(root)
    write_csv(out / "audit_artifacts.csv", artifacts,
              ["artifact", "bytes", "sha256", "selected_fields_json"])

    report = {
        "report_type": "independent_descriptive_summary",
        "input_snapshot": str(root),
        "label": args.example_label or "UNSPECIFIED: GPU completion status requires external receipt",
        "expected_method_seed_parent_cells": expected,
        "transition_cells_found": len(located),
        "method_summary_rows": len(method_summaries),
        "paired_contrast_rows": len(paired_contrasts),
        "producer_evaluation_cells_found": len(producer_rows),
        "transition_rows_without_allocation_receipts": len(receipt_gaps),
        "relevant_audit_artifacts_found": len(artifacts),
        "all_24_cells_present": len(located) == expected,
        "methods": list(METHODS), "seeds": list(SEEDS), "development_parents": list(PARENTS),
        "counts_source": "raw n02-event-policy-transition JSONL; no producer computation modules imported",
        "missing_policy": "Missing source field or artifact is the literal string MISSING; never inferred as zero.",
        "interpretation_limits": [
            "Trigger, requested reconstruction, concrete non-NOOP action count, reported effective count, and receipt-verified effective count are separate.",
            "Concrete non-NOOP actions are not presumed effective; verification requires task-owner-change, queue-reorder, or valid before/after queue receipts.",
            "Local/global scope selection is not proof of effective local/global allocation change.",
            "No significance or broad superiority claim is made from three seeds and two development parents.",
            "Event-G-WM changes trigger and critic together, so critic effects are not isolated.",
            "A lower trigger count alone is not evidence of fewer actual reconstructions or better task outcomes.",
            "A completed GPU run requires matching attempt/source identity and an external review receipt."
        ]
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# N02 Run Summary", "", f"Input snapshot: `{root}`", "",
             f"Label: **{report['label']}**", "",
             f"Raw transition cells found: {len(located)}/{expected}.", "",
             "The paired table has one row per method × seed × development parent. See `paired_comparison.csv`; `MISSING` means the input snapshot did not provide a source value.", "",
             "Trigger count, requested reconstruction, concrete non-NOOP action count, producer-reported effective count, and independently receipt-verified effective count are separate. Verification uses task-owner-change, queue-reorder, or valid before/after queue receipts. Missing confirmation stays `MISSING`.", "",
             "Outcome and reported values come from `DEVELOPMENT_EVALUATION.json`. `producer_crosscheck.csv` compares raw-transition recounts with that producer summary and marks each match or mismatch. `paired_comparison.csv` includes per-cell mismatch details.", "",
             "`method_summary.csv` reports descriptive means and available/missing cell counts. `paired_contrasts.csv` reports mean matched-cell differences for four predefined contrasts; each metric has valid and missing pair denominators. Independent effective counts are never filled from producer-reported counts.", "",
             "Method means are recomputed from the six explicit method×seed×development-parent episode rows (three seeds × two parents), not the producer's aggregate `descriptive_means`. Delay uses the episode `environment_metrics.mean_delay` value in its source unit of minutes per original task.", "",
             "In this snapshot `environment_metrics.safety_risk` is present but null and its validity mask is false; the risk metric is therefore reported as `MISSING`, not zero. Other mapped task/resource fields are read from their matching episode `environment_metrics` keys.", "",
             "For effective reconstruction, exact means use only cells with complete mutation receipts and show that valid N. Cells with receipt gaps retain `MISSING` exact counts; separate lower/upper-bound means and paired contrast intervals give a sensitivity range without imputing a point value.", "",
             f"Rows that requested an action but lacked valid allocation mutation receipts are listed in `receipt_gaps.csv` ({len(receipt_gaps)} rows). Missing independent counts therefore remain `MISSING`; a selected dispatch alone does not qualify.", "",
             "`audit_artifacts.csv` inventories relevant model, restore, receipt, resource, gradient and ledger artifacts with hashes and selected scalar fields. Missing artifacts are absent from this inventory; absent report metrics remain `MISSING`.", "",
             "## Required Interpretation", "",
             "- Treat results as descriptive for three seeds and two development parents; do not claim statistical significance or general superiority.",
             "- Event-G-WM changes both trigger and critic, so this comparison cannot isolate the critic effect.",
             "- A reduction in triggers does not establish a reduction in actual reconstructions; use the reported and receipt-verified effective metrics.",
             "- GPU completion and acceptance require matching attempt/source identity and an external review receipt; this tool does not issue a PASS."
             ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "cells": len(located), "expected": expected,
                      "paired_rows": len(rows_out), "crosscheck_rows": len(producer_checks),
                      "audit_artifacts": len(artifacts)}, indent=2))


if __name__ == "__main__":
    main()
