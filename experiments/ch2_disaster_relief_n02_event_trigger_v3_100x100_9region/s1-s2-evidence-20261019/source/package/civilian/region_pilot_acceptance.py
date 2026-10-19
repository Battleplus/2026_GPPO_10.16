"""Independent paired-data contract report for completed S2 pilot outputs."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from typing import Any


REQUIRED_METRICS = ("global_utility", "on_time_rate", "energy_used", "safety_risk")
EXPECTED_VARIANTS = ("Periodic-G", "Event-G")
ENGINEERING_COSTS = ("planning_calls", "communication_messages", "reconstruction_size")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _finite_or_none(value: Any) -> float | int | None:
    return value if _finite(value) else None


def _sanitize_nonfinite(value: Any) -> tuple[Any, bool]:
    if isinstance(value, float) and not math.isfinite(value):
        return None, True
    if isinstance(value, dict):
        cleaned = {}
        found = False
        for key, item in value.items():
            cleaned_item, item_found = _sanitize_nonfinite(item)
            cleaned[key] = cleaned_item
            found = found or item_found
        return cleaned, found
    if isinstance(value, list):
        cleaned = []
        found = False
        for item in value:
            cleaned_item, item_found = _sanitize_nonfinite(item)
            cleaned.append(cleaned_item)
            found = found or item_found
        return cleaned, found
    return value, False


def _action_binding(row: dict[str, Any], candidates: list[Any], index: int) -> tuple[bool, str | None]:
    if index < 0 or index >= len(candidates) or not isinstance(candidates[index], dict):
        return False, "selected_candidate_missing"
    candidate = candidates[index]
    if candidate.get("legal") is not True or row.get("selected_candidate_legal") is not True:
        return False, "selected_candidate_not_legal"
    candidate_key = str(candidate.get("candidate_key", candidate.get("id", index)))
    selected = candidate.get("full_environment_action")
    if not isinstance(selected, dict) or row.get("candidate_key") != candidate_key:
        return False, "selected_candidate_identity_mismatch"
    keys = row.get("candidate_keys")
    if not isinstance(keys, list) or index >= len(keys) or keys[index] != candidate_key:
        return False, "candidate_key_index_mismatch"
    if row.get("selected_action") != selected:
        return False, "selected_action_candidate_mismatch"
    receipt = row.get("repair_receipt")
    executed = row.get("executed_action")
    if not isinstance(receipt, dict) or not isinstance(executed, dict):
        return False, "repair_or_execution_receipt_missing"
    if receipt.get("legal_before") is not True or receipt.get("postrepair_legal") is not True:
        return False, "repair_receipt_not_legal"
    if receipt.get("repaired") is not False or executed != selected:
        return False, "executed_action_differs_from_selected_candidate"
    observation = row.get("observation") or {}
    provenance = observation.get("provenance") or {}
    if receipt.get("public_snapshot_hash") != provenance.get("snapshot_hash"):
        return False, "repair_snapshot_identity_mismatch"
    if receipt.get("event_tape_id") != provenance.get("event_tape_id"):
        return False, "repair_event_tape_identity_mismatch"
    operation_receipts = row.get("operation_receipts")
    operations = executed.get("queue_operations", [])
    if not isinstance(operation_receipts, list) or len(operation_receipts) != len(operations):
        return False, "operation_receipt_count_mismatch"
    if any(not isinstance(item, dict) or item.get("operation") != operation
           or not isinstance(item.get("before_queues"), dict)
           or not isinstance(item.get("after_queues"), dict)
           for item, operation in zip(operation_receipts, operations)):
        return False, "operation_receipt_binding_mismatch"
    raw_events = row.get("raw_events")
    if not isinstance(raw_events, list):
        return False, "raw_action_events_missing"
    receipt_operations = [event.get("operation") for event in raw_events
                          if isinstance(event, dict) and event.get("type") == "queue_operation"]
    if receipt_operations != operations:
        return False, "raw_queue_operations_do_not_match_execution"
    return True, None


def _effective_local_evidence(row: dict[str, Any], candidates: list[Any], index: int) -> bool:
    if not 0 <= index < len(candidates) or not isinstance(candidates[index], dict):
        return False
    action = row.get("executed_action") or {}
    if action.get("scope") != "LOCAL_REPAIR" or action.get("noop") is True:
        return False
    scope_ids = _region_ids(row)
    observation = row.get("observation") or {}
    task_regions = {str(task.get("id")): str(task.get("region_id"))
                    for task in observation.get("tasks", []) if isinstance(task, dict)}
    platform_regions = {str(platform.get("id")): str(platform.get("region_id"))
                        for platform in observation.get("platforms", []) if isinstance(platform, dict)}
    before, after = row.get("assignment_before"), row.get("assignment_after")
    queues_before, queues_after = row.get("queues_before"), row.get("queues_after")
    events = row.get("raw_events")
    if not all(isinstance(value, dict) for value in (before, after, queues_before, queues_after)) or not isinstance(events, list):
        return False
    owner_diffs = {str(task_id) for task_id in set(before) | set(after)
                   if before.get(task_id) != after.get(task_id)
                   and (not scope_ids or task_regions.get(str(task_id)) in scope_ids)}
    raw_owner_diffs = {str(event.get("task_id")) for event in events
                       if isinstance(event, dict) and event.get("type") == "task_owner_change"}
    action_task_ids = {str(row.get("task_id")) for row in action.get("dispatches", []) if row.get("task_id") is not None}
    for operation in action.get("queue_operations", []):
        action_task_ids.update(str(operation[key]) for key in ("task_id", "other_task_id")
                               if operation.get(key) is not None)
    owner_witness = bool(owner_diffs & raw_owner_diffs & action_task_ids)
    queue_platform_diffs = {str(platform_id) for platform_id in set(queues_before) | set(queues_after)
                            if queues_before.get(platform_id) != queues_after.get(platform_id)
                            and platform_regions.get(str(platform_id)) is not None
                            and (not scope_ids or str(platform_regions.get(str(platform_id))) in scope_ids)}
    queue_witness = any(platform_id == str(event.get("platform_id"))
                        for platform_id in queue_platform_diffs
                        for event in events if isinstance(event, dict) and event.get("type") == "queue_reorder"
                        and str(event.get("task_id")) in action_task_ids
                        and (not scope_ids or task_regions.get(str(event.get("task_id"))) in scope_ids))
    # Raw owner or reorder events must agree with the public before/after mutation.
    return owner_witness or (bool(queue_platform_diffs) and queue_witness)


def _raw_costs(rows: list[dict[str, Any]]) -> tuple[dict[str, float | int | None], str | None]:
    planning_calls = len(rows)
    communication_messages = 0
    reconstruction_size = 0
    for row in rows:
        events = row.get("raw_events")
        before, after = row.get("assignment_before"), row.get("assignment_after")
        queues_before, queues_after = row.get("queues_before"), row.get("queues_after")
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            return {"planning_calls": planning_calls, "communication_messages": None,
                    "reconstruction_size": None}, "raw_events_missing_or_invalid"
        if not all(isinstance(item, dict) for item in (before, after, queues_before, queues_after)):
            return {"planning_calls": planning_calls, "communication_messages": None,
                    "reconstruction_size": None}, "action_projection_missing"
        for event in events:
            if event.get("type") == "communication_tx":
                count = event.get("message_count")
                if not _finite(count) or float(count) < 0:
                    return {"planning_calls": planning_calls, "communication_messages": None,
                            "reconstruction_size": None}, "communication_event_count_invalid"
                communication_messages += int(count)
        changed_owners = {str(event.get("task_id")) for event in events
                          if event.get("type") == "task_owner_change" and event.get("task_id") is not None}
        actual_owner_diffs = {str(task_id) for task_id in set(before) | set(after)
                              if before.get(task_id) != after.get(task_id)}
        # Filter raw event owner changes to those confirmed by assignment projections.
        if not changed_owners <= actual_owner_diffs:
            return {"planning_calls": planning_calls, "communication_messages": None,
                    "reconstruction_size": None}, "raw_owner_events_do_not_match_projection"
        reorder_events = [event for event in events if event.get("type") == "queue_reorder"]
        for event in reorder_events:
            platform_id = str(event.get("platform_id"))
            if (queues_before.get(platform_id) == queues_after.get(platform_id)
                    or not isinstance(event.get("before_queues"), list)
                    or not isinstance(event.get("after_queues"), list)):
                return {"planning_calls": planning_calls, "communication_messages": None,
                        "reconstruction_size": None}, "raw_queue_reorder_not_confirmed"
        reconstruction_size += len(changed_owners) + len(reorder_events)
    return {"planning_calls": planning_calls, "communication_messages": communication_messages,
            "reconstruction_size": reconstruction_size}, None


def _gate_item(observed: Any, expected: Any, valid: bool, fail_reason: str | None = None) -> dict[str, Any]:
    return {"observed": observed, "expected": expected, "valid": bool(valid),
            "failreason": None if valid else (fail_reason or "criterion_not_met")}


def _engineering_gate(
    result: dict[str, Any], metadata_by_parent: dict[str, dict[str, Any]],
    summaries: dict[str, dict[str, dict[str, Any]]],
    rollout_rows: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    train_ids = sorted(parent for parent, row in metadata_by_parent.items() if row.get("split") == "train")
    development_ids = sorted(parent for parent, row in metadata_by_parent.items() if row.get("split") == "development")
    split_counts = {
        "unique_parent_count": len(metadata_by_parent),
        "train": len(train_ids),
        "development": len(development_ids),
    }
    split_valid = split_counts == {"unique_parent_count": 6, "train": 4, "development": 2}
    checks["parent_split_contract"] = _gate_item(
        split_counts, {"unique_parent_count": 6, "train": 4, "development": 2},
        split_valid, "requires_six_unique_parents_split_4_train_2_development",
    )

    dev_means: dict[str, dict[str, float | None]] = {}
    for variant in EXPECTED_VARIANTS:
        dev_means[variant] = {}
        for metric in ("global_utility", "on_time_rate"):
            values = [summaries[variant].get(parent, {}).get(metric) for parent in development_ids]
            valid_values = [float(value) for value in values if _finite(value)]
            valid = len(development_ids) == 2 and len(valid_values) == 2
            dev_means[variant][metric] = sum(valid_values) / len(valid_values) if valid else None
    for metric, threshold, comparator in (
        ("global_utility", 0.0, "greater_than_or_equal"),
        ("on_time_rate", -0.02, "greater_than_or_equal"),
    ):
        periodic = dev_means["Periodic-G"][metric]
        event = dev_means["Event-G"][metric]
        difference = event - periodic if periodic is not None and event is not None else None
        valid = _finite(difference) and difference >= threshold - 1e-12
        checks[f"development_{metric}_difference"] = _gate_item(
            {"Periodic-G_mean": periodic, "Event-G_mean": event, "Event-G_minus_Periodic-G": difference},
            {"aggregation": "mean_of_two_development_parents", "operator": comparator,
             "minimum_difference": threshold, "numerical_comparison_tolerance": 1e-12},
            valid, "missing_or_nonfinite_development_metric" if difference is None else f"{metric}_difference_below_threshold",
        )

    cost_means: dict[str, dict[str, float | int | None]] = {variant: {} for variant in EXPECTED_VARIANTS}
    cost_error: str | None = None
    for variant in EXPECTED_VARIANTS:
        per_parent: dict[str, dict[str, float | int | None]] = {}
        for parent in development_ids:
            values, error = _raw_costs(rollout_rows[variant].get(parent, []))
            if error:
                cost_error = f"{parent}.{variant}.{error}"
            per_parent[parent] = values
        for metric in ENGINEERING_COSTS:
            values = [per_parent[parent].get(metric) for parent in development_ids]
            if len(values) == 2 and all(_finite(value) for value in values):
                cost_means[variant][metric] = sum(float(value) for value in values) / 2.0
            else:
                cost_means[variant][metric] = None
    lower = [metric for metric in ENGINEERING_COSTS
             if _finite(cost_means["Periodic-G"].get(metric))
             and _finite(cost_means["Event-G"].get(metric))
             and float(cost_means["Event-G"][metric]) < float(cost_means["Periodic-G"][metric])]
    costs_complete = len(development_ids) == 2 and all(
        _finite(cost_means[variant].get(metric))
        for variant in EXPECTED_VARIANTS for metric in ENGINEERING_COSTS
    )
    checks["development_strict_cost_lower"] = _gate_item(
        {"mean_by_variant": cost_means, "strictly_lower_metrics": lower},
        {"aggregation": "mean_of_two_development_parents", "metrics": list(ENGINEERING_COSTS),
         "condition": "Event-G is strictly lower for at least one metric"},
        costs_complete and bool(lower), cost_error or ("nonfinite_or_missing_raw_cost_evidence" if not costs_complete else "no_cost_metric_strictly_lower"),
    )

    binding_counts: dict[str, dict[str, int]] = {}
    local_counts: dict[str, int] = {}
    for variant in EXPECTED_VARIANTS:
        variant_rows = [row for parent in metadata_by_parent for row in rollout_rows[variant].get(parent, [])]
        bound = sum(_action_binding(row, row.get("candidates") if isinstance(row.get("candidates"), list) else [],
                                    row.get("candidate_index") if isinstance(row.get("candidate_index"), int) else -1)[0]
                    for row in variant_rows)
        binding_counts[variant] = {"transition_count": len(variant_rows), "fully_bound_legal_execution_count": bound}
        checks[f"{variant}_action_execution_binding"] = _gate_item(
            binding_counts[variant], ["all_transitions_bound_to_legal_candidate_repair_receipt_execution_and_raw_action"],
            bool(variant_rows) and bound == len(variant_rows), "candidate_repair_execution_or_raw_action_binding_failed",
        )
        train_rows = [row for parent in train_ids for row in rollout_rows[variant].get(parent, [])]
        local_counts[variant] = sum(
            _effective_local_evidence(row, row.get("candidates") if isinstance(row.get("candidates"), list) else [],
                                      row.get("candidate_index") if isinstance(row.get("candidate_index"), int) else -1)
            and _action_binding(row, row.get("candidates") if isinstance(row.get("candidates"), list) else [],
                                row.get("candidate_index") if isinstance(row.get("candidate_index"), int) else -1)[0]
            for row in train_rows
        )
        checks[f"{variant}_effective_local_action"] = _gate_item(
            {"training_effective_local_action_count_with_raw_owner_or_queue_witness": local_counts[variant]},
            {"minimum": 1, "source_split": "train"}, local_counts[variant] > 0,
            "no_bound_effective_local_action_with_raw_projection_witness",
        )

    update_counts = {}
    for variant in EXPECTED_VARIANTS:
        training = result.get("variants", {}).get(variant, {}).get("8201", {}).get("training", {})
        update_counts[variant] = training.get("optimizer_updates")
    update_values_valid = all(_finite(value) and int(value) == value and 0 < int(value) <= 32
                              for value in update_counts.values())
    paired_updates = len(set(update_counts.values())) == 1 if update_values_valid else False
    checks["paired_update_counts"] = _gate_item(
        update_counts, {"each_variant_seed_8201": "integer in [1, 32]", "paired_equal": True},
        update_values_valid and paired_updates,
        "update_count_must_be_positive_at_most_32_and_equal_across_variants",
    )
    all_valid = all(check["valid"] for check in checks.values())
    return {
        "schema": "n02-v3-s2-engineering-gate/1",
        "status": "PASS_PENDING_INDEPENDENT_REVIEW" if all_valid else "REPAIR_REQUIRED",
        "S3_allowed": False,
        "checks": checks,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"S2_ACCEPTANCE_JSONL_ROW_NOT_OBJECT:{path.name}:{line_number}")
            rows.append(row)
    return rows


def _summary_by_parent(result: dict[str, Any], variant: str) -> dict[str, dict[str, Any]]:
    seed = result.get("variants", {}).get(variant, {}).get("8201", {})
    training = seed.get("training", {}).get("episodes", [])
    development = seed.get("development", [])
    rows = [*training, *development]
    return {str(row["parent_id"]): row for row in rows if isinstance(row, dict) and row.get("parent_id") is not None}


def _region_ids(row: dict[str, Any]) -> set[str]:
    affected = row.get("affected_scope") or {}
    raw = affected.get("affected_region_ids", affected.get("direct_region_ids", []))
    if isinstance(raw, str):
        return {raw}
    return {str(value) for value in raw if value is not None} if isinstance(raw, list) else set()


def _rollout_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps: list[str] = []
    legal_candidate_count = 0
    illegal_candidate_count = 0
    selected_candidate_count = 0
    selected_candidate_legal_count = 0
    local_owner_change_count = 0
    local_queue_reorder_count = 0
    requested_local_action_count = 0
    effective_local_action_count = 0
    raw_event_count = 0

    for index, row in enumerate(rows):
        candidates = row.get("candidates")
        candidate_index = row.get("candidate_index")
        if not isinstance(candidates, list) or not candidates:
            gaps.append(f"transition[{index}].candidates")
            candidates = []
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("legal"), bool):
                legal_candidate_count += int(candidate["legal"])
                illegal_candidate_count += int(not candidate["legal"])
            else:
                gaps.append(f"transition[{index}].candidate_legal")
        if isinstance(candidate_index, int) and 0 <= candidate_index < len(candidates):
            selected_candidate_count += 1
            if candidates[candidate_index].get("legal") is True:
                selected_candidate_legal_count += 1
            else:
                gaps.append(f"transition[{index}].selected_candidate_illegal")
        else:
            gaps.append(f"transition[{index}].candidate_index")

        scope_ids = _region_ids(row)
        observation = row.get("observation") or {}
        task_regions = {
            str(task.get("id")): str(task.get("region_id"))
            for task in observation.get("tasks", [])
            if isinstance(task, dict) and task.get("id") is not None and task.get("region_id") is not None
        }
        before, after = row.get("assignment_before"), row.get("assignment_after")
        if isinstance(before, dict) and isinstance(after, dict):
            local_owner_change_count += sum(
                before.get(task_id) != after.get(task_id)
                and (not scope_ids or task_regions.get(task_id) in scope_ids)
                for task_id in set(before) | set(after)
            )
        else:
            gaps.append(f"transition[{index}].assignment_before_after")

        queues_before, queues_after = row.get("queues_before"), row.get("queues_after")
        platforms = {
            str(platform.get("id")): platform.get("region_id")
            for platform in observation.get("platforms", [])
            if isinstance(platform, dict) and platform.get("id") is not None
        }
        if isinstance(queues_before, dict) and isinstance(queues_after, dict):
            local_queue_reorder_count += sum(
                queues_before.get(platform_id) != queues_after.get(platform_id)
                and (not scope_ids or str(platforms.get(platform_id)) in scope_ids)
                for platform_id in set(queues_before) | set(queues_after)
            )
        else:
            gaps.append(f"transition[{index}].queues_before_after")

        action = row.get("executed_action") or {}
        if action.get("scope") == "LOCAL_REPAIR" and not action.get("noop"):
            requested_local_action_count += 1
            effective_local_action_count += int(int(row.get("effective_reconstruction_count", 0)) > 0)
        raw_events = row.get("raw_events")
        if isinstance(raw_events, list):
            raw_event_count += len(raw_events)
        else:
            gaps.append(f"transition[{index}].raw_events")

    return {
        "transition_count": len(rows),
        "legal_candidate_count": legal_candidate_count,
        "illegal_candidate_count": illegal_candidate_count,
        "selected_candidate_count": selected_candidate_count,
        "selected_candidate_legal_count": selected_candidate_legal_count,
        "local_owner_change_count": local_owner_change_count,
        "local_queue_reorder_count": local_queue_reorder_count,
        "requested_local_action_count": requested_local_action_count,
        "effective_local_action_count": effective_local_action_count,
        "raw_event_count": raw_event_count,
        "evidence_gaps": gaps,
    }


def _metric_evidence(summary: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    environment = summary.get("environment_metrics")
    metrics = environment.get("metrics") if isinstance(environment, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    raw = {}
    gaps = []
    for name, metric in metrics.items():
        if isinstance(metric, dict):
            safe_metric, had_nonfinite = _sanitize_nonfinite(dict(metric))
            raw[name] = safe_metric
            if had_nonfinite:
                gaps.append(f"{name}.nonfinite")
            if metric.get("valid") is not True or metric.get("value") is None or not _finite(metric.get("value")):
                gaps.append(name)
        else:
            safe_metric, had_nonfinite = _sanitize_nonfinite(metric)
            raw[name] = {"value": safe_metric, "valid": metric is not None and not had_nonfinite}
            if metric is None or had_nonfinite or not _finite(metric):
                gaps.append(name)
    direct = {
        "global_utility": _finite_or_none(summary.get("global_utility")),
        "on_time_rate": _finite_or_none(summary.get("on_time_rate")),
        "energy_used": _finite_or_none(environment.get("energy_used")) if isinstance(environment, dict) else None,
        "safety_risk": _finite_or_none(environment.get("safety_risk")) if isinstance(environment, dict) else None,
    }
    for name in REQUIRED_METRICS:
        if direct[name] is None and name not in gaps:
            gaps.append(name)
    cost = {
        "energy_used": direct["energy_used"],
        "safety_risk": direct["safety_risk"],
        "reward_component_totals": _sanitize_nonfinite(environment.get("reward_component_totals"))[0] if isinstance(environment, dict) else None,
        "task_switch_count": _finite_or_none(environment.get("task_switch_count")) if isinstance(environment, dict) else None,
        "operational_dispatch_count": _finite_or_none(summary.get("operational_dispatch_count")),
        "communication_message_count": _finite_or_none(summary.get("communication_message_count")),
    }
    for name, value in cost.items():
        if value is None:
            gaps.append(f"cost.{name}")
    return {"raw_metrics": raw, "direct": direct, "cost": cost}, sorted(set(gaps))


def build_acceptance_report(result: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Pair every configured parent and report raw outcome and legality evidence."""
    root = Path(output_dir)
    metadata_rows = result.get("paired_parent_metadata", [])
    metadata_by_parent = {
        str(row["parent_id"]): row for row in metadata_rows
        if isinstance(row, dict) and row.get("parent_id") is not None
    }
    if len(metadata_by_parent) != 6:
        raise ValueError("S2_ACCEPTANCE_REQUIRES_SIX_UNIQUE_PAIRED_PARENTS")
    if set(result.get("variants", {})) != set(EXPECTED_VARIANTS):
        raise ValueError("S2_ACCEPTANCE_VARIANTS_MISMATCH")
    summaries = {variant: _summary_by_parent(result, variant) for variant in EXPECTED_VARIANTS}
    rollout_rows_by_variant: dict[str, dict[str, list[dict[str, Any]]]] = {variant: {} for variant in EXPECTED_VARIANTS}
    pairs = []
    required_gaps = []

    for parent_id in sorted(metadata_by_parent):
        metadata = metadata_by_parent[parent_id]
        variant_evidence = {}
        for variant in EXPECTED_VARIANTS:
            summary = summaries[variant].get(parent_id)
            if summary is None:
                required_gaps.append(f"{parent_id}.{variant}.summary")
                summary = {}
            metric_data, metric_gaps = _metric_evidence(summary)
            training = result["variants"][variant]["8201"].get("training", {})
            actor_init = training.get("initial_actor_digest")
            if not actor_init:
                required_gaps.append(f"{parent_id}.{variant}.actor_initialization")
            log_name = (
                f"development_{parent_id}.jsonl" if metadata.get("split") == "development"
                else "rollouts.jsonl"
            )
            rollout_path = root / variant / "seed_8201" / log_name
            rollout_rows = [row for row in _read_jsonl(rollout_path) if str(row.get("parent_id")) == parent_id]
            rollout_rows_by_variant[variant][parent_id] = rollout_rows
            rollout_data = _rollout_evidence(rollout_rows)
            raw_trajectory_path = None
            raw_trajectory_sha256 = None
            if metadata.get("split") == "development":
                raw_trajectory_path = root / variant / "seed_8201" / f"development_{parent_id}_trajectory.json"
                if raw_trajectory_path.is_file():
                    raw_bytes = raw_trajectory_path.read_bytes()
                    raw_trajectory_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                    artifact = json.loads(raw_bytes.decode("utf-8"))
                    if (
                        artifact.get("parent_id") != parent_id
                        or artifact.get("variant") != variant
                        or artifact.get("event_tape_id") != metadata.get("event_tape_id")
                        or artifact.get("actor_initialization_sha256") != actor_init
                    ):
                        required_gaps.append(f"{parent_id}.{variant}.raw_trajectory_identity")
                else:
                    required_gaps.append(f"{parent_id}.{variant}.raw_trajectory")
            if not rollout_rows:
                required_gaps.append(f"{parent_id}.{variant}.rollout_log")
            if rollout_data["selected_candidate_count"] != rollout_data["selected_candidate_legal_count"]:
                required_gaps.append(f"{parent_id}.{variant}.selected_action_legality")
            if rollout_data["evidence_gaps"]:
                required_gaps.extend(f"{parent_id}.{variant}.{item}" for item in rollout_data["evidence_gaps"])
            required_gaps.extend(
                f"{parent_id}.{variant}.metric.{item}"
                for item in metric_gaps if item in REQUIRED_METRICS or item.startswith("cost.")
            )
            variant_evidence[variant] = {
                "metrics": metric_data,
                "metric_gaps": metric_gaps,
                "actor_initialization_sha256": actor_init,
                "event_tape_id": metadata.get("event_tape_id"),
                "rollout": rollout_data,
                "rollout_log": str(rollout_path),
                "raw_trajectory_path": str(raw_trajectory_path) if raw_trajectory_path else None,
                "raw_trajectory_sha256": raw_trajectory_sha256,
            }

        actor_ids = {variant_evidence[v]["actor_initialization_sha256"] for v in EXPECTED_VARIANTS}
        if len(actor_ids) != 1 or None in actor_ids:
            required_gaps.append(f"{parent_id}.paired_actor_initialization")
        tape_id = metadata.get("event_tape_id")
        if not isinstance(tape_id, str) or not tape_id:
            required_gaps.append(f"{parent_id}.event_tape_identity")
        if any(variant_evidence[v]["event_tape_id"] != tape_id for v in EXPECTED_VARIANTS):
            required_gaps.append(f"{parent_id}.paired_event_tape_identity")
        for identity_key in ("initial_owner_queue_sha256", "public_reset_prefix_sha256", "scenario_wrapper_sha256"):
            if not isinstance(metadata.get(identity_key), str) or not metadata[identity_key]:
                required_gaps.append(f"{parent_id}.{identity_key}")
        pairs.append({
            "parent_id": parent_id,
            "split": metadata.get("split"),
            "event_tape_id": tape_id,
            "initial_owner_queue_sha256": metadata.get("initial_owner_queue_sha256"),
            "public_reset_prefix_sha256": metadata.get("public_reset_prefix_sha256"),
            "scenario_wrapper_sha256": metadata.get("scenario_wrapper_sha256"),
            "actor_initialization_sha256": next(iter(actor_ids)) if len(actor_ids) == 1 else None,
            "variants": variant_evidence,
        })

    engineering_gate = _engineering_gate(result, metadata_by_parent, summaries, rollout_rows_by_variant)
    return {
        "schema": "n02-v3-s2-paired-acceptance-evidence/1",
        "status": "PASS_DATA_CONTRACT_ONLY" if not required_gaps else "FAIL_DATA_CONTRACT",
        "claim_scope": "paired evidence completeness and action legality only; no performance superiority claim",
        "world_model_enabled": False,
        "parent_count": len(pairs),
        "split_counts": {
            "train": sum(row.get("split") == "train" for row in metadata_by_parent.values()),
            "development": sum(row.get("split") == "development" for row in metadata_by_parent.values()),
        },
        "required_gaps": sorted(set(required_gaps)),
        "metric_gap_count": sum(
            len(item["variants"][variant]["metric_gaps"])
            for item in pairs
            for variant in EXPECTED_VARIANTS
        ),
        "engineering_gate": engineering_gate,
        "pairs": pairs,
    }
