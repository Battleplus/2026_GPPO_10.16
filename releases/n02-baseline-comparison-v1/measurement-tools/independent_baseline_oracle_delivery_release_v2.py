#!/usr/bin/env python3
"""Independent stdlib-only audit of N02 baseline action receipts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


_proof_path = Path(__file__).with_name("causal_receipt_proofs.py")
_proof_spec = importlib.util.spec_from_file_location("n02_causal_receipt_proofs", _proof_path)
if _proof_spec is None or _proof_spec.loader is None:
    raise ImportError("Missing independent causal receipt proof module")
_proof_module = importlib.util.module_from_spec(_proof_spec)
_proof_spec.loader.exec_module(_proof_module)


WEIGHT_KEYS = {
    "completion", "delay", "energy", "risk", "communication", "switch",
    "reconstruction", "reconstruction_scale", "global_scope",
}
EVENT_TYPES = {"task_owner_change", "queue_reorder", "queue_operation", "communication_delivered"}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _number(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    return float(value)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-7)
    return a == b


def _issue(report: dict, severity: str, code: str, where: str, detail: str) -> None:
    report[severity].append({"code": code, "where": where, "detail": detail})


def _root_map(state: dict) -> dict[str, str]:
    mapping = state.get("root_mapping")
    if isinstance(mapping, dict):
        return {str(k): str(v) for k, v in mapping.items()}
    specs = state.get("leaf_task_specs")
    if isinstance(specs, list):
        return {str(row["id"]): str(row.get("parent_task_id", row["id"])) for row in specs if isinstance(row, dict) and row.get("id") is not None}
    return {}


def _owners_by_root(state: dict) -> dict[str, tuple[str, ...]]:
    mapping = _root_map(state)
    groups: dict[str, set[str]] = defaultdict(set)
    for row in state.get("leaf_tasks", []):
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        owner = row.get("assignee")
        if owner is not None:
            groups[mapping.get(str(row["id"]), str(row["id"]))].add(str(owner))
    return {key: tuple(sorted(value)) for key, value in groups.items()}


def _roots_from_state(state: dict, initial_specs: dict[str, dict], horizon: int,
                      cancellation_times: dict[str, float]) -> dict[str, dict]:
    leaves = {str(row.get("id")): row for row in state.get("leaf_tasks", []) if isinstance(row, dict) and row.get("id") is not None}
    mapping = _root_map(state)
    manifests = {str(row.get("parent_task_id", row.get("root_task_id", row.get("task_id", "")))): row
                 for row in state.get("split_manifests", []) if isinstance(row, dict)}
    result: dict[str, dict] = {}
    for root_id, spec in initial_specs.items():
        manifest = manifests.get(root_id, {})
        child_ids = manifest.get("child_ids") or [leaf_id for leaf_id, root in mapping.items() if root == root_id]
        if not child_ids:
            child_ids = [root_id]
        children = [leaves.get(str(child_id)) for child_id in child_ids]
        if any(row is None for row in children):
            continue
        complete = all(row.get("status") == "completed" for row in children)
        completion_times = [float(row["completed_at"]) for row in children if _number(row.get("completed_at")) is not None]
        completed_at = max(completion_times) if complete and len(completion_times) == len(children) else None
        status = ("completed" if complete else "cancelled" if any(row.get("status") == "cancelled" for row in children)
                  else "failed" if any(row.get("status") == "failed" for row in children) else "incomplete")
        result[root_id] = {"status": status, "completed_at": completed_at,
                           "deadline": spec.get("deadline"), "priority": spec.get("priority"),
                           "cancelled_at": cancellation_times.get(root_id)}
    return result


def _endpoint_energy(state: dict) -> float | None:
    rows = state.get("leaf_platforms")
    if not isinstance(rows, list) or not rows:
        return None
    values = [_number(row.get("energy_used")) for row in rows if isinstance(row, dict)]
    if len(values) != len(rows) or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _reward_formula(row: dict) -> tuple[dict | None, dict | None]:
    formula = row.get("reward_formula")
    if not isinstance(formula, dict) or formula.get("schema") != "event-relief-reward/1":
        return None, None
    weights = formula.get("weights")
    if not isinstance(weights, dict) or not WEIGHT_KEYS.issubset(weights):
        return formula, None
    if any(_number(weights.get(key)) is None for key in WEIGHT_KEYS):
        return formula, None
    return formula, weights


def _step_primitives(row: dict, report: dict, where: str) -> dict | None:
    before, after = row.get("raw_state_before"), row.get("raw_state_after")
    events = row.get("raw_events")
    if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(events, list):
        _issue(report, "missing", "RAW_STEP_EVIDENCE_MISSING", where, "raw_state_before/after or raw_events absent")
        return None

    completion_before = _roots_from_state(before, {str(x.get("id")): x for x in before.get("root_task_specs", []) if isinstance(x, dict) and x.get("id") is not None},
                                          int(after.get("time", row.get("time", 0))), {})
    completion_after = _roots_from_state(after, {str(x.get("id")): x for x in after.get("root_task_specs", []) if isinstance(x, dict) and x.get("id") is not None},
                                         int(after.get("time", row.get("time", 0))), {})
    completed_now = sum(v.get("status") == "completed" and completion_before.get(k, {}).get("status") != "completed"
                        for k, v in completion_after.items())
    delay_events = [event for event in events if isinstance(event, dict) and event.get("type") == "delay_accrued"]
    if any(_number(event.get("minutes")) is None for event in delay_events):
        _issue(report, "missing", "DELAY_EVENT_VALUE_MISSING", where, "delay_accrued event has no finite minutes")
        return None
    delay = sum(float(event["minutes"]) for event in delay_events)
    energy_before, energy_after = _endpoint_energy(before), _endpoint_energy(after)
    if energy_before is None or energy_after is None:
        _issue(report, "missing", "ENERGY_ENDPOINT_MISSING", where, "raw platform energy_used endpoints are incomplete")
        return None
    energy_delta = energy_after - energy_before
    event_energy = 0.0
    for event in events:
        if isinstance(event, dict) and event.get("type") in {"move", "service"}:
            value = _number(event.get("energy"))
            if value is None:
                _issue(report, "missing", "ENERGY_EVENT_MISSING", where, "move/service event has no finite energy")
                return None
            event_energy += value
    if not _eq(energy_delta, event_energy):
        _issue(report, "mismatch", "ENERGY_EVENT_ENDPOINT_MISMATCH", where,
               f"event sum={event_energy}, endpoint energy_used delta={energy_delta}")

    risk = 0.0
    communication = 0
    switches: set[str] = set()
    event_owners: dict[str, tuple[Any, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            _issue(report, "missing", "RAW_EVENT_INVALID", where, "raw_events contains a non-object")
            return None
        kind = event.get("type")
        if kind == "move":
            val = _number(event.get("environmental_risk"))
            if val is None:
                _issue(report, "missing", "RISK_EVENT_MISSING", where, "move event has no finite environmental_risk")
                return None
            risk += val
        elif kind in {"task_failed", "platform_failure"}:
            risk += 1.0
        elif kind == "communication_tx":
            count = event.get("message_count")
            if type(count) is not int or count < 0:
                _issue(report, "missing", "COMMUNICATION_EVENT_MISSING", where, "communication_tx has no nonnegative integer message_count")
                return None
            communication += count
        elif kind == "task_switch":
            switches.add(str(event.get("task_id")))
        elif kind == "task_owner_change":
            event_owners[str(event.get("task_id"))] = (event.get("previous_owners"), event.get("new_owners"))
    owners_before, owners_after = _owners_by_root(before), _owners_by_root(after)
    endpoint_owner_changes = {key for key in set(owners_before) | set(owners_after)
                              if owners_before.get(key, ()) != owners_after.get(key, ())}
    # Owner changes are charged only when the command application receipt corroborates causality.
    operation_receipts = row.get("operation_receipts", [])
    causal = set()
    reorder = 0
    for receipt in operation_receipts if isinstance(operation_receipts, list) else []:
        if not isinstance(receipt, dict):
            continue
        if receipt.get("owners_before") != receipt.get("owners_after"):
            causal.add(str(receipt.get("task_id", receipt.get("operation", {}).get("task_id", ""))))
        op = receipt.get("operation", {})
        if isinstance(op, dict) and op.get("op") == "insert" and op.get("from_platform") == op.get("to_platform"):
            bq, aq = receipt.get("before_queues", {}), receipt.get("after_queues", {})
            platform = str(op.get("to_platform"))
            if isinstance(bq, dict) and isinstance(aq, dict) and bq.get(platform) != aq.get(platform):
                reorder += 1
    delivery_events = [e for e in events if isinstance(e, dict) and e.get("type") == "communication_delivered"]
    attributed_delivery = [e for e in delivery_events if e.get("originating_action_id") or e.get("origin_action_id")
                          or e.get("action_id") or e.get("command_action_id")]
    if delivery_events and len(attributed_delivery) != len(delivery_events):
        _issue(report, "missing", "DELAYED_DELIVERY_ATTRIBUTION_MISSING", where,
               "communication_delivered lacks originating action id and application endpoint evidence")
    command_receipts = row.get("command_application_receipts", {})
    for event in command_receipts.get("causal_change_events", []) if isinstance(command_receipts, dict) else []:
        if isinstance(event, dict) and event.get("type") == "task_owner_change":
            causal.add(str(event.get("task_id", "")))
    for effect in row.get("command_effects", []) if isinstance(row.get("command_effects"), list) else []:
        if isinstance(effect, dict) and effect.get("owner_changed") is True and isinstance(effect.get("operation"), dict):
            causal.add(str(effect["operation"].get("task_id", "")))
    # An immediate dispatch is causally effective only when its same-tick
    # delivered communication receipt and raw assignment event bind task/owner.
    action = row.get("full_environment_action", {})
    dispatches = action.get("dispatches", []) if isinstance(action, dict) else []
    comm_rows = row.get("communication_receipts", [])
    assignments = [event for event in events if event.get("type") == "assignment"]
    for dispatch in dispatches if isinstance(dispatches, list) else []:
        if not isinstance(dispatch, dict):
            continue
        task_id, platform_id = str(dispatch.get("task_id")), str(dispatch.get("platform_id"))
        delivered = any(isinstance(receipt, dict) and receipt.get("reason") == "dispatch"
                        and str(receipt.get("task_id")) == task_id
                        and str(receipt.get("target")) == platform_id
                        and receipt.get("delivered") is True
                        and int(receipt.get("delay_minutes", -1)) == 0 for receipt in comm_rows)
        assigned = any(str(event.get("task_id")) == task_id
                       and str(event.get("new_assignee")) == platform_id
                       and event.get("previous_assignee") != platform_id for event in assignments)
        if delivered and assigned:
            causal.add(task_id)
    delayed_tasks, delayed_proofs = _proof_module.validated_delayed_dispatches(
        row, report.get("_causal_action_index", {}))
    causal.update(delayed_tasks)
    release_roots, release_proofs = _proof_module.validated_environment_releases(row)
    report.setdefault("causal_extension_proofs", []).extend(delayed_proofs + release_proofs)
    root_mapping = _root_map(after)
    causal_roots = {root_mapping.get(task_id, task_id) for task_id in causal}
    owner_change_count = len(endpoint_owner_changes & causal_roots)
    # Explicit causal owner-change events are required for attributable switches.
    unexplained_owner_changes = endpoint_owner_changes - causal_roots - release_roots
    if unexplained_owner_changes:
        _issue(report, "missing", "OWNER_CHANGE_CAUSALITY_MISSING", where,
               "raw endpoint owner sets changed without operation/delivery causal receipt")
    reconstruction_size = owner_change_count + reorder
    switch_count = len(switches)
    # Use endpoint energy as the reward primitive; events independently cross-check it.
    return {"completion_count": int(completed_now), "delay_minutes": delay,
            "energy_units": energy_delta, "risk_units": risk,
            "communication_messages": communication, "switch_count": switch_count,
            "reconstruction_count": int(reconstruction_size > 0),
            "reconstruction_size": reconstruction_size,
            "owner_change_count": owner_change_count, "queue_reorder_count": reorder,
            "effective_reconstruction_count": int(reconstruction_size > 0),
            "requested_nonnoop": int(isinstance(row.get("full_environment_action"), dict) and not row["full_environment_action"].get("noop", False)),
            "local_invocation_count": int(row.get("full_environment_action", {}).get("scope") == "LOCAL_REPAIR" and not row.get("full_environment_action", {}).get("noop", False)),
            "global_invocation_count": int(row.get("full_environment_action", {}).get("scope") == "GLOBAL_REPLAN" and not row.get("full_environment_action", {}).get("noop", False))}


def _audit_step(row: dict, report: dict, where: str) -> dict | None:
    action = row.get("full_environment_action")
    if not isinstance(action, dict):
        _issue(report, "missing", "ACTION_MISSING", where, "full_environment_action absent")
        return None
    noop = action.get("noop") is True and action.get("scope") == "NOOP" and not action.get("queue_operations") and not action.get("dispatches")
    clock = row.get("decision_clock", {})
    if isinstance(clock, dict) and clock.get("planned") is False and not noop:
        _issue(report, "mismatch", "NONDECISION_NOT_NOOP", where, "non-decision tick carries a non-NOOP action")
    catalog = row.get("candidate_catalog")
    if catalog is not None:
        digest = canonical_digest(catalog)
        if row.get("candidate_catalog_sha256") != digest:
            _issue(report, "mismatch", "CATALOG_DIGEST_MISMATCH", where, f"recomputed {digest}")
        selected = row.get("selected_candidate", {})
        index = selected.get("candidate_index") if isinstance(selected, dict) else None
        if type(index) is not int or index < 0 or index >= len(catalog):
            _issue(report, "missing", "SELECTED_CANDIDATE_BINDING_MISSING", where, "selected candidate index is not bound to catalogue")
        else:
            item = catalog[index]
            if item.get("candidate_key") != selected.get("candidate_key"):
                _issue(report, "mismatch", "SELECTED_CANDIDATE_KEY_MISMATCH", where, "selected key differs from ordered catalogue entry")
            selected_action = item.get("full_environment_action")
            if selected_action is not None and selected_action != action:
                _issue(report, "mismatch", "SELECTED_ACTION_MISMATCH", where, "full action differs from selected catalogue action")
    primitives = _step_primitives(row, report, where)
    if primitives is None:
        return None
    formula, weights = _reward_formula(row)
    if weights is None:
        _issue(report, "missing", "REWARD_FORMULA_MISSING", where, "frozen event-relief reward weights absent or invalid")
        return primitives
    formula_digest = canonical_digest(formula)
    if row.get("reward_formula_sha256") and row.get("reward_formula_sha256") != formula_digest:
        _issue(report, "mismatch", "REWARD_FORMULA_DIGEST_MISMATCH", where, f"recomputed {formula_digest}")
    terms = {
        "completion": weights["completion"] * primitives["completion_count"],
        "delay": -weights["delay"] * primitives["delay_minutes"],
        "energy": -weights["energy"] * primitives["energy_units"],
        "risk": -weights["risk"] * primitives["risk_units"],
        "communication": -weights["communication"] * primitives["communication_messages"],
        "switch": -weights["switch"] * primitives["switch_count"],
        "reconstruction": -weights["reconstruction"] * primitives["reconstruction_count"],
        "reconstruction_scale": -weights["reconstruction_scale"] * primitives["reconstruction_size"],
        "global_scope": -weights["global_scope"] * primitives["global_invocation_count"],
    }
    received = row.get("reward_terms")
    if not isinstance(received, dict) or set(received) != set(terms):
        _issue(report, "missing", "REWARD_TERMS_MISSING", where, "reward_terms do not contain the complete frozen formula")
    else:
        for key, expected in terms.items():
            if not _eq(received.get(key), expected):
                _issue(report, "mismatch", "REWARD_TERM_MISMATCH", where, f"{key}: expected {expected}, received {received.get(key)}")
    total = sum(terms.values())
    if not _eq(row.get("reward"), total):
        _issue(report, "mismatch", "REWARD_MISMATCH", where, f"expected {total}, received {row.get('reward')}")
    claimed = row.get("reward_primitives")
    if isinstance(claimed, dict):
        for key in ("completion_count", "delay_minutes", "energy_units", "risk_units", "communication_messages", "switch_count", "reconstruction_count", "reconstruction_size"):
            if key in claimed and not _eq(claimed[key], primitives[key]):
                _issue(report, "mismatch", "REWARD_PRIMITIVE_MISMATCH", where, f"{key}: expected {primitives[key]}, received {claimed[key]}")
    else:
        _issue(report, "missing", "REWARD_PRIMITIVES_MISSING", where, "reward_primitives absent")
    for key in ("effective_reconstruction_count", "reconstruction_size", "owner_change_count", "queue_reorder_count"):
        if key in row and not _eq(row[key], primitives[key]):
            _issue(report, "mismatch", "ACTION_METRIC_MISMATCH", where, f"{key}: expected {primitives[key]}, received {row[key]}")
    return {**primitives, "utility": total,
            "net_utility": total - 0.01 * int(row.get("rule_protocol_message_count", 0))}


def _episode_metrics(rows: list[dict], summary: dict, report: dict, key: str) -> dict:
    initial = rows[0].get("raw_state_before") if rows else None
    final = rows[-1].get("raw_state_after") if rows else None
    horizon = int(summary.get("horizon_minutes", 60))
    if not isinstance(initial, dict) or not isinstance(final, dict):
        _issue(report, "missing", "EPISODE_ENDPOINTS_MISSING", key, "episode has no raw first/last endpoint")
        return {}
    specs = initial.get("root_task_specs")
    if not isinstance(specs, list) or not specs:
        _issue(report, "missing", "ROOT_SPECS_MISSING", key, "initial raw root_task_specs absent")
        return {}
    root_specs = {str(row.get("id")): row for row in specs if isinstance(row, dict) and row.get("id") is not None}
    if len(root_specs) != 12:
        _issue(report, "mismatch", "ROOT_DENOMINATOR_MISMATCH", key, f"expected 12 initial roots, found {len(root_specs)}")
    cancels: dict[str, float] = {}
    root_map = _root_map(final)
    for row in rows:
        for event in row.get("raw_events", []) if isinstance(row.get("raw_events"), list) else []:
            if isinstance(event, dict) and event.get("type") in {"task_cancelled", "task_cancel"}:
                leaf = str(event.get("task_id", ""))
                root = root_map.get(leaf, leaf)
                time = _number(event.get("time"))
                if time is not None:
                    cancels[root] = time
    roots = _roots_from_state(final, root_specs, horizon, cancels)
    if len(roots) != len(root_specs):
        _issue(report, "missing", "ROOT_LEAF_AGGREGATION_INCOMPLETE", key,
               f"aggregated {len(roots)} of {len(root_specs)} roots from raw leaves")
        return {}
    completed = [r for r in roots.values() if r["status"] == "completed" and r["completed_at"] is not None and r["completed_at"] <= horizon]
    on_time = sum(float(r["completed_at"]) <= float(r["deadline"]) for r in completed if _number(r.get("deadline")) is not None)
    delays = []
    critical_failures = 0
    for root_id, root in roots.items():
        deadline = _number(root.get("deadline"))
        if deadline is None:
            _issue(report, "missing", "ROOT_DEADLINE_MISSING", key, f"root {root_id} has no initial deadline")
            continue
        if root["status"] == "completed" and root["completed_at"] is not None:
            delays.append(max(0.0, float(root["completed_at"]) - deadline))
        elif root["status"] == "cancelled":
            cancel_time = root.get("cancelled_at")
            if cancel_time is None:
                _issue(report, "missing", "CANCELLATION_TIME_MISSING", key, f"root {root_id} cancelled without raw cancellation time")
                delays.append(0.0)
            else:
                delays.append(max(0.0, float(cancel_time) - deadline))
        else:
            delays.append(max(0.0, float(horizon) - deadline))
        if _number(root.get("priority")) is not None and float(root["priority"]) >= 5.0 and root["status"] != "completed":
            critical_failures += 1
    tick_metrics = [_audit_step(row, report, f"{key}/tick-{row.get('time')}") for row in rows]
    valid = [item for item in tick_metrics if item is not None]
    totals = defaultdict(float)
    for item in valid:
        for name in ("utility", "net_utility", "energy_units", "effective_reconstruction_count", "reconstruction_size",
                     "requested_nonnoop", "local_invocation_count", "global_invocation_count", "owner_change_count", "queue_reorder_count"):
            totals[name] += float(item[name])
    cancelled_count = sum(root["status"] == "cancelled" for root in roots.values())
    failed_count = sum(root["status"] == "failed" for root in roots.values())
    trigger_count = sum(isinstance(row.get("decision_clock"), dict) and row["decision_clock"].get("planned") is True for row in rows)
    planning_invocations = trigger_count
    scope_nonempty_planning = sum(isinstance(row.get("decision_clock"), dict)
                                  and row["decision_clock"].get("planned") is True
                                  and isinstance(row.get("affected_scope"), dict)
                                  and bool(row["affected_scope"].get("affected_task_ids") or row["affected_scope"].get("affected_platform_ids"))
                                  for row in rows)
    nonempty_planning_invocations = 0
    for row in rows:
        if not isinstance(row.get("decision_clock"), dict) or row["decision_clock"].get("planned") is not True:
            continue
        catalog = row.get("candidate_catalog")
        if not isinstance(catalog, list):
            _issue(report, "missing", "PLANNED_CATALOGUE_MISSING", f"{key}/tick-{row.get('time')}",
                   "planned tick has no ordered candidate catalogue")
            continue
        if any(isinstance(candidate, dict) and candidate.get("legal") is True
               and isinstance(candidate.get("full_environment_action"), dict)
               and candidate["full_environment_action"].get("noop") is not True for candidate in catalog):
            nonempty_planning_invocations += 1
    detector_edges = sum(row.get("detector_event_edge") is True or
                         (row.get("detector_event_edge") is None and isinstance(row.get("detection"), dict)
                          and row["detection"].get("event_edge") is True) for row in rows)
    delivery_messages = sum(int(event.get("message_count", 0)) for row in rows for event in row.get("raw_events", [])
                            if isinstance(event, dict) and event.get("type") == "communication_tx")
    protocol_messages = sum(int(row.get("rule_protocol_message_count", 0)) for row in rows)
    planning_latency = sum(float(row.get("planning_latency_seconds", 0.0)) for row in rows if _number(row.get("planning_latency_seconds")) is not None)
    policy_response = sum(float(row.get("policy_response_seconds", 0.0)) for row in rows if _number(row.get("policy_response_seconds")) is not None)
    constraints = sum(int(row.get("constraint_violations", 0)) for row in rows)
    switches = sum(int(item["switch_count"]) for item in valid)
    utility = float(totals.get("utility", 0.0))
    return {"root_count": len(root_specs), "completed_count": len(completed), "completion_rate": len(completed) / max(1, len(root_specs)),
            "on_time_count": int(on_time), "on_time_rate": int(on_time) / max(1, len(root_specs)),
            "mean_delay": sum(delays) / max(1, len(root_specs)), "critical_failures": critical_failures,
            "failed_root_task_count": failed_count, "cancelled_root_task_count": cancelled_count,
            "trigger_count": trigger_count, "planning_invocation_count": planning_invocations,
            "scope_nonempty_planning_count": scope_nonempty_planning,
            "actionable_catalog_planning_count": nonempty_planning_invocations,
            "nonempty_planning_invocation_count": nonempty_planning_invocations,
            "detector_event_edge_count": detector_edges, "environment_action_delivery_message_count": delivery_messages,
            "rule_protocol_message_count": protocol_messages, "planning_latency_seconds": planning_latency,
            "policy_response_seconds": policy_response, "constraint_violations": constraints,
            "protocol_cost": 0.01 * protocol_messages,
            "task_switch_count": switches,
            "global_utility": utility,
            **dict(totals)}


def audit_data(receipts: list[dict], episodes: list[dict], manifest: dict | None = None) -> dict:
    report: dict[str, Any] = {"schema": "independent-baseline-oracle-report/1", "status": "PASS", "mismatch": [], "missing": [], "episodes": []}
    action_index = {}
    for row in receipts:
        if not isinstance(row, dict) or not isinstance(row.get("action_id"), str):
            _issue(report, "missing", "CAUSAL_ACTION_ID_MISSING", "action_index", "action id is required for cross-tick attribution")
            continue
        if row["action_id"] in action_index:
            _issue(report, "mismatch", "CAUSAL_DUPLICATE_ACTION_ID", row["action_id"], "ambiguous origin identity")
        action_index[row["action_id"]] = row
    report["_causal_action_index"] = action_index
    grouped: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
    for index, row in enumerate(receipts):
        if not isinstance(row, dict):
            _issue(report, "missing", "RECEIPT_INVALID", str(index), "receipt is not an object")
            continue
        required = ("method_id", "parent_id", "event_tape_id", "seed", "time")
        if any(row.get(field) is None for field in required):
            _issue(report, "missing", "RECEIPT_IDENTITY_MISSING", str(index), "method/parent/tape/seed/time identity incomplete")
            continue
        grouped[(str(row["method_id"]), str(row["parent_id"]), str(row["event_tape_id"]), int(row["seed"]))].append(row)
    ep_index = {(str(e.get("method_id")), str(e.get("parent_id")), str(e.get("event_tape_id")), int(e.get("seed", -1))): e
                for e in episodes if isinstance(e, dict)}
    if episodes and set(grouped) != set(ep_index):
        _issue(report, "mismatch", "EPISODE_RECEIPT_PAIRING_MISMATCH", "evaluation", "receipt episode keys differ from episode summary keys")
    for key, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["time"]))
        label = "/".join(map(str, key))
        for a, b in zip(rows, rows[1:]):
            if int(b["time"]) != int(a["time"]) + 1:
                _issue(report, "mismatch", "TICK_SEQUENCE_GAP", label, f"ticks {a['time']} then {b['time']}")
            if a.get("raw_state_after") != b.get("raw_state_before"):
                _issue(report, "mismatch", "RAW_ENDPOINT_CHAIN_MISMATCH", label, f"tick {a['time']} after != tick {b['time']} before")
        episode = ep_index.get(key, {})
        calculated = _episode_metrics(rows, episode, report, label)
        claimed_metrics = episode.get("metrics", {}) if isinstance(episode, dict) else {}
        aliases = {"completed_count": ("completed_count",), "completion_rate": ("completion_rate",), "on_time_count": ("on_time_count",),
                   "on_time_rate": ("on_time_rate",), "mean_delay": ("mean_delay_minutes", "mean_delay"),
                   "critical_failures": ("critical_failure_count_priority_ge_5", "critical_failure_count"),
                   "utility": ("environment_utility", "utility"), "global_utility": ("global_utility",),
                   "net_utility": ("net_utility",), "energy_units": ("energy_units", "energy_used"),
                   "root_count": ("original_root_task_count",), "failed_root_task_count": ("failed_root_task_count",),
                   "cancelled_root_task_count": ("cancelled_root_task_count",),
                   "effective_reconstruction_count": "effective_reconstruction_count", "reconstruction_size": "reconstruction_size",
                   "requested_nonnoop": ("requested_nonnoop_count", "requested_reconstruction_count"),
                   "local_invocation_count": ("local_repair_invocation_count", "local_invocation_count"),
                   "global_invocation_count": ("global_replan_invocation_count", "global_invocation_count"),
                   "owner_change_count": ("task_owner_change_count", "owner_change_count"),
                   "queue_reorder_count": ("queue_reorder_count",), "trigger_count": ("trigger_count",),
                   "planning_invocation_count": ("planning_invocation_count",),
                   "scope_nonempty_planning_count": ("scope_nonempty_planning_count",),
                   "actionable_catalog_planning_count": ("actionable_catalog_planning_count",),
                   "nonempty_planning_invocation_count": ("nonempty_planning_invocation_count",),
                   "detector_event_edge_count": ("detector_event_edge_count",), "protocol_cost": ("protocol_cost",),
                   "environment_action_delivery_message_count": ("environment_action_delivery_message_count",),
                   "rule_protocol_message_count": ("rule_protocol_message_count",),
                   "planning_latency_seconds": ("planning_latency_seconds",), "policy_response_seconds": ("policy_response_seconds",),
                   "constraint_violations": ("constraint_violations",), "switch_count": ("task_switch_count", "switch_count")}
        required_summary = ("completion_rate", "on_time_rate", "mean_delay_minutes",
                            "critical_failure_count_priority_ge_5", "environment_utility", "net_utility",
                            "global_utility", "original_root_task_count", "failed_root_task_count", "cancelled_root_task_count",
                            "trigger_count", "planning_invocation_count", "scope_nonempty_planning_count",
                            "actionable_catalog_planning_count", "nonempty_planning_invocation_count", "detector_event_edge_count",
                            "requested_nonnoop_count", "effective_reconstruction_count", "reconstruction_size",
                            "local_repair_invocation_count", "global_replan_invocation_count", "task_owner_change_count",
                            "queue_reorder_count", "environment_action_delivery_message_count", "rule_protocol_message_count",
                            "protocol_cost", "planning_latency_seconds", "policy_response_seconds", "constraint_violations", "energy_units", "task_switch_count")
        if episodes and isinstance(episode, dict):
            for field in required_summary:
                if field not in claimed_metrics:
                    _issue(report, "missing", "EPISODE_SUMMARY_FIELD_MISSING", label, f"required production summary field {field} absent")
        for computed_key, summary_keys in aliases.items():
            if isinstance(summary_keys, str):
                summary_keys = (summary_keys,)
            found = next((summary_key for summary_key in summary_keys if summary_key in claimed_metrics), None)
            if found is not None and computed_key in calculated and not _eq(claimed_metrics[found], calculated[computed_key]):
                _issue(report, "mismatch", "EPISODE_METRIC_MISMATCH", label,
                       f"{found}: recomputed {calculated[computed_key]}, received {claimed_metrics[found]}")
        report["episodes"].append({"key": list(key), "recomputed": calculated})
    # Pairing contract: each parent/seed has one tape identity and one initial C1 binding across methods.
    pair_rows: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    for key, episode in ep_index.items():
        assignment = episode.get("initial_c1_assignment")
        if assignment is None:
            action_rows = grouped.get(key, [])
            first_state = action_rows[0].get("raw_state_before") if action_rows else None
            queues = first_state.get("queues") if isinstance(first_state, dict) else None
            mapping = _root_map(first_state) if isinstance(first_state, dict) else {}
            if isinstance(queues, dict) and mapping:
                assignment = {str(platform): [mapping.get(str(task), str(task)) for task in tasks]
                              for platform, tasks in sorted(queues.items())}
            else:
                _issue(report, "missing", "C1_PAIRING_BINDING_MISSING", "/".join(map(str, key)),
                       "summary assignment and first raw queue/root mapping are absent")
        if assignment is not None:
            pair_rows[(key[1], key[3])].add((key[2], canonical_digest(assignment)))
    for pair, values in pair_rows.items():
        if len(values) > 1:
            _issue(report, "mismatch", "C1_PAIRING_MISMATCH", str(pair), "methods differ in event tape or initial C1 assignment")
    if manifest is not None:
        expected = manifest.get("episode_count")
        if type(expected) is int and expected != len(ep_index):
            _issue(report, "mismatch", "MANIFEST_EPISODE_COUNT_MISMATCH", "manifest", f"manifest={expected}, summaries={len(ep_index)}")
    report.pop("_causal_action_index", None)
    report["measurement_revision"] = {
        "id": "delayed-dispatch-and-environment-release-v2",
        "parent_frozen_oracle_sha256": "ae7785acad7ccce0c0013ecdb04640d3d2578e520087795d27c90c4c0b70d4af",
        "proof_module_sha256": hashlib.sha256(_proof_path.read_bytes()).hexdigest(),
        "oracle_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_data_or_algorithms_modified": False,
        "scope": "strict raw causal evidence extension; original frozen oracle failure retained separately",
    }
    report["status"] = "FAIL" if report["mismatch"] or report["missing"] else "PASS"
    return report


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(value)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", required=True, type=Path, help="EVALUATION_ACTION_RECEIPTS.jsonl")
    parser.add_argument("--episodes", required=True, type=Path, help="EVALUATION_EPISODES.jsonl")
    parser.add_argument("--manifest", type=Path, help="BASELINE_EVALUATION_MANIFEST.json")
    parser.add_argument("--output", type=Path, help="write JSON audit report here")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    report = audit_data(_read_jsonl(args.actions), _read_jsonl(args.episodes), manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
