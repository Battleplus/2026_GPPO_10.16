"""CPU-only raw evidence runner for v3 region mechanism diagnostics."""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")


def dependency_inventory() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    targets = sorted((root / "package").rglob("*.py"))
    targets.append(root / "configs" / "V3_PREREGISTRATION.json")
    result: dict[str, str] = {}
    for path in targets:
        rel = path.relative_to(root).as_posix()
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "MISSING"
    return result


def _noop_action(candidates: list[dict]) -> dict:
    return next((row for row in candidates if row.get("legal") and row.get("full_environment_action", {}).get("noop")), {
        "candidate_key": "NOOP", "legal": True, "scope": "NOOP",
        "full_environment_action": {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
                                     "queue_operations": [], "dispatches": []},
    })


def _owner_map(observation: dict) -> dict[str, Any]:
    return {str(row["id"]): row.get("assignee") for row in observation.get("tasks", [])}


def _first_event_time(wrapper: dict, diagnostic_event_kind: str | None = None) -> int | None:
    allowed = {"platform_failure", "energy_drop", "communication_drop", "environment_perturbation", "task_arrival"}
    if diagnostic_event_kind is not None:
        allowed = {diagnostic_event_kind}
    times = [int(row["time"]) for row in wrapper.get("event_tape", []) if row.get("kind") in allowed]
    return min(times) if times else None


def run_attempt(wrapper: dict, output_root: str | Path, *, stage: str, mode: str = "event",
                threshold: dict | None = None, config: dict | None = None,
                stop_on_first_zero: bool = False, diagnostic_event_kind: str | None = None) -> dict:
    """Run an event wrapper and save raw public, candidate, action, and outcome traces.

    A fresh UUID directory is created for each call. Inventory drift during the
    attempt changes its status to STALE, which is never reported as a pass.
    """
    try:
        from .event_environment import EventReliefEnv, generate_reconstruction_candidates, repair_action
        from .event_trigger import TriggerEngine, identify_affected_scope
        from .chapter1_adapter import generate_public_c1_initial_assignment
        from .scenario_schema import validate_region_event_scenario
    except ImportError:
        from event_environment import EventReliefEnv, generate_reconstruction_candidates, repair_action
        from event_trigger import TriggerEngine, identify_affected_scope
        from chapter1_adapter import generate_public_c1_initial_assignment
        from scenario_schema import validate_region_event_scenario
    validate_region_event_scenario(wrapper)
    root = Path(output_root)
    run_id = uuid.uuid4().hex
    attempt_dir = root / f"{stage}-{run_id}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    before_inventory = dependency_inventory()
    prereg_path = Path(__file__).resolve().parents[2] / "configs" / "V3_PREREGISTRATION.json"
    if prereg_path.is_file():
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    else:
        prereg = None
    threshold = copy.deepcopy(threshold or {"threshold": 0.0, "world_model_used": False, "source_split": "train"})
    if config is None:
        config_path = Path(__file__).resolve().parents[2] / "configs" / "EVENT_TRIGGER_CONFIG.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
    config = copy.deepcopy(config)
    trigger_config = config.get("trigger") if isinstance(config.get("trigger"), dict) else {}
    raw_weights = trigger_config.get("weights")
    if isinstance(raw_weights, list) and len(raw_weights) == 4:
        trigger_config["weights"] = dict(zip(("d_state", "d_degradation", "d_margin", "d_uncertainty"), map(float, raw_weights)))
    config["trigger"] = trigger_config
    public_c1 = generate_public_c1_initial_assignment(wrapper["base_scenario"],
        seed=int(threshold.get("seed", wrapper.get("seed_variant", 8201))), schedule_backlog=True)
    request = {
        "schema": "v3-region-run-request/1", "run_id": run_id, "stage": stage, "mode": mode,
        "parent_id": wrapper["parent_id"], "split": wrapper["split"], "condition": wrapper["condition"],
        "scenario_sha256": _digest(wrapper["base_scenario"]), "event_tape_id": wrapper["event_tape_id"],
        "queue_plan_sha256": _digest(wrapper["queue_plan"]),
        "c1_public_input_sha256": _digest(public_c1["public_input"]),
        "threshold": threshold, "pre_registration_sha256": None if prereg is None else _digest(prereg),
        "dependency_inventory_sha256": _digest(before_inventory),
        "stop_on_first_zero": bool(stop_on_first_zero), "diagnostic_event_kind": diagnostic_event_kind,
        "execution_device": "cpu",
    }
    _write_json(attempt_dir / "REQUEST.json", request)
    _write_json(attempt_dir / "SOURCE_HASHES_BEFORE.json", before_inventory)
    _write_json(attempt_dir / "C1_PUBLIC_INPUT.json", public_c1["public_input"])
    _write_json(attempt_dir / "C1_RECEIPT.json", public_c1["receipt"])
    _write_json(attempt_dir / "ATTEMPT.json", {"schema": "v3-region-run-attempt/1", "run_id": run_id, "status": "running"})

    env = EventReliefEnv(wrapper)
    observation = env.reset()
    previous = copy.deepcopy(observation)
    history = [copy.deepcopy(observation)]
    # TriggerEngine accepts the full config and resolves its nested trigger settings.
    engine = TriggerEngine(config, threshold)
    logs: list[dict] = []
    requested_event_time = _first_event_time(wrapper, diagnostic_event_kind)
    stop_reason = None
    terminated = truncated = False
    while not (terminated or truncated):
        now = int(observation.get("time", env.time))
        detection = engine.detect(previous, observation, history=history[-4:])
        decision = engine.decide(detection, now, mode=mode)
        affected = identify_affected_scope(observation, detection)
        if decision.get("triggered"):
            decision["high_level_action"] = affected.get("scope", "NOOP")
            decision["affected_scope"] = copy.deepcopy(affected)
        # A first-zero diagnostic stops at the first scheduled public event that
        # reached the observation without triggering reconstruction.
        if stop_on_first_zero and requested_event_time is not None and now >= requested_event_time and not decision.get("triggered"):
            logs.append({
                "time": now, "triggered": False, "first_zero": True, "detection": detection,
                "decision": decision, "affected_scope": affected, "candidate_request": None,
                "candidates": [], "repair_receipt": None, "selected_action": None,
                "raw_events_previous_step": copy.deepcopy(logs[-1].get("raw_events", [])) if logs else [],
                "owner_map": _owner_map(observation), "queues": copy.deepcopy(observation.get("queues", {})),
                "branch_trace": [{"branch": "trigger_gate", "result": "first_zero_stop"}],
                "label_ledger": {"affected_task_ids": affected.get("affected_task_ids", []),
                                 "affected_platform_ids": affected.get("affected_platform_ids", []),
                                 "noop_present": False, "non_target_task_ids": []},
            })
            stop_reason = "FIRST_ZERO_TRIGGER_AT_EXTERNAL_EVENT"
            break
        scope_arg = affected if decision.get("triggered") else "NOOP"
        candidates = generate_reconstruction_candidates(
            observation, scope_arg, int(config.get("collection", {}).get("max_candidates", 16)), env=env
        )
        candidates = copy.deepcopy(candidates)
        noop = _noop_action(candidates)
        requested_scope = str(decision.get("high_level_action", "NOOP")) if decision.get("triggered") else "NOOP"
        selected = next((row for row in candidates if row.get("legal") and row is not noop
                         and row.get("full_environment_action", {}).get("scope") == requested_scope), noop)
        action, repair_receipt = repair_action(env, copy.deepcopy(selected["full_environment_action"]))
        if repair_receipt.get("postrepair_legal") is not True or action != selected["full_environment_action"]:
            selected = noop
            action, repair_receipt = repair_action(env, copy.deepcopy(noop["full_environment_action"]))
        before_owner = _owner_map(observation)
        before_queues = copy.deepcopy(observation.get("queues", {}))
        next_observation, reward, terminated, truncated, info = env.step(action)
        after_owner = _owner_map(next_observation)
        owner_diff = {task_id: {"before": before_owner.get(task_id), "after": after_owner.get(task_id)}
                      for task_id in sorted(set(before_owner) | set(after_owner))
                      if before_owner.get(task_id) != after_owner.get(task_id)}
        after_queues = copy.deepcopy(next_observation.get("queues", {}))
        noop_present = any(row.get("full_environment_action", {}).get("noop") for row in candidates)
        affected_task_ids = set(affected.get("affected_task_ids", []))
        non_target = sorted(set(before_owner) - affected_task_ids)
        logs.append({
            "time": now, "triggered": bool(decision.get("triggered")), "first_zero": False,
            "detection": detection, "decision": decision, "affected_scope": affected,
            "candidate_request": {"affected_scope": copy.deepcopy(scope_arg), "max_candidates": int(config.get("collection", {}).get("max_candidates", 16))},
            "candidates": candidates, "selected_candidate_key": selected.get("candidate_key"),
            "selected_action": action, "repair_receipt": repair_receipt, "reward": float(reward),
            "raw_events": copy.deepcopy(info.get("raw_events", [])),
            "operation_receipts": copy.deepcopy(info.get("operation_receipts", [])),
            "owner_map_before": before_owner, "owner_map_after": after_owner, "owner_diff": owner_diff,
            "queues_before": before_queues, "queues_after": after_queues,
            "effective_reconstruction_count": info.get("effective_reconstruction_count", 0),
            "branch_trace": [
                {"branch": "trigger_gate", "result": "triggered" if decision.get("triggered") else "not_triggered"},
                {"branch": "scope_gate", "result": requested_scope, "eligible": affected.get("local_eligible", False) if requested_scope == "LOCAL_REPAIR" else affected.get("regional_eligible", False) if requested_scope == "REGIONAL_REPLAN" else affected.get("global_eligible", False) if requested_scope == "GLOBAL_REPLAN" else True},
                {"branch": "candidate_selection", "result": selected.get("candidate_key"), "candidate_count": len(candidates)},
                {"branch": "environment_execution", "result": "effective" if info.get("effective_reconstruction_count", 0) else "noop"},
            ],
            "label_ledger": {"affected_task_ids": sorted(affected_task_ids),
                             "affected_platform_ids": sorted(affected.get("affected_platform_ids", [])),
                             "non_target_task_ids": non_target, "noop_present": bool(noop_present),
                             "owner_changed_task_ids": sorted(owner_diff)},
            "snapshot_hash": observation.get("provenance", {}).get("snapshot_hash"),
            "public_prefix_hash": observation.get("provenance", {}).get("public_prefix_hash"),
        })
        engine.record_reconstruction(now, effective=int(info.get("effective_reconstruction_count", 0)) > 0)
        previous, observation = copy.deepcopy(observation), next_observation
        history.append(copy.deepcopy(observation))
        history = history[-4:]
    trajectory = env.export_trajectory()
    after_inventory = dependency_inventory()
    inventory_stable = before_inventory == after_inventory
    status = "STALE" if not inventory_stable else "FAIL" if stop_reason else "COMPLETE"
    event_trigger_count = sum(row["triggered"] for row in logs)
    summary = {
        "schema": "v3-region-run-summary/1", "run_id": run_id, "stage": stage,
        "parent_id": wrapper["parent_id"], "split": wrapper["split"], "condition": wrapper["condition"],
        "event_tape_id": wrapper["event_tape_id"], "tick_count": len(logs),
        "trigger_count": event_trigger_count,
        "local_repair_count": sum(row.get("effective_reconstruction_count", 0) > 0 and row.get("selected_action", {}).get("scope") == "LOCAL_REPAIR" for row in logs),
        "regional_replan_count": sum(row.get("effective_reconstruction_count", 0) > 0 and row.get("selected_action", {}).get("scope") == "REGIONAL_REPLAN" for row in logs),
        "global_replan_count": sum(row.get("effective_reconstruction_count", 0) > 0 and row.get("selected_action", {}).get("scope") == "GLOBAL_REPLAN" for row in logs),
        "effective_mutations": sum(int(row.get("effective_reconstruction_count", 0) > 0) for row in logs),
        "owner_change_count": sum(len(row.get("owner_diff", {})) for row in logs),
        "communication_message_count": sum(int(event.get("message_count", 0)) for row in logs for event in row.get("raw_events", []) if event.get("type") == "communication_tx"),
        "stop_reason": stop_reason, "environment_summary": env.episode_metrics(),
        "trajectory_sha256": _digest(trajectory), "dependency_inventory_stable": inventory_stable,
        "status": status,
    }
    _write_jsonl(attempt_dir / "DECISIONS.jsonl", logs)
    _write_json(attempt_dir / "TRAJECTORY.json", trajectory)
    _write_json(attempt_dir / "SUMMARY.json", summary)
    _write_json(attempt_dir / "SOURCE_HASHES_AFTER.json", after_inventory)
    _write_json(attempt_dir / "ATTEMPT.json", {"schema": "v3-region-run-attempt/1", "run_id": run_id,
        "status": status, "stop_reason": stop_reason, "dependency_inventory_stable": inventory_stable})
    return {"attempt_dir": str(attempt_dir), "run_id": run_id, "status": status, "summary": summary}
