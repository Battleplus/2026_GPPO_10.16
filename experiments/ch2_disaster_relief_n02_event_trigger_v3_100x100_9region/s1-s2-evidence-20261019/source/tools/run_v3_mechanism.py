"""Export auditable raw branch evidence for a disclosed event wrapper."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "package" / "civilian"
sys.path.insert(0, str(PACKAGE))
SELECTION_RULE = (
    "first legal non-NOOP LOCAL_REPAIR candidate in deterministic producer catalog order "
    "whose public-observation projection changes planned task owners or queue order"
)

from event_environment import EventReliefEnv, generate_reconstruction_candidates, repair_action
from event_oracle import recompute_consequence_labels
from event_runner import _private_simulator_state_sha256, _window_trajectory
from event_trigger import TriggerEngine, identify_affected_scope
from chapter1_adapter import generate_public_c1_initial_assignment


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _source_hashes() -> dict[str, str]:
    paths = sorted([
        *PACKAGE.rglob("*.py"),
        *[p for p in (ROOT / "configs").glob("*.json")],
        *[p for p in (ROOT / "tools").rglob("*.py")],
    ])
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if "__pycache__" not in path.parts}


def _noop() -> dict[str, Any]:
    return {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
            "queue_operations": [], "dispatches": []}


def _owner_queues(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "owners": {row["id"]: row.get("assignee") for row in observation.get("tasks", [])},
        "queues": copy.deepcopy(observation.get("queues", {})),
    }


def _project_owner_queues(observation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Project planned ownership and queues using only public state and the full action."""
    state = _owner_queues(observation)
    owners = state["owners"]
    queues = state["queues"]
    operations = action.get("queue_operations", [])
    dispatches = action.get("dispatches", [])
    for operation in operations:
        op = operation.get("op")
        task_id = operation.get("task_id")
        if op in {"transfer", "insert"}:
            target = operation.get("to_platform")
            for queue in queues.values():
                while task_id in queue:
                    queue.remove(task_id)
            destination = queues.setdefault(target, [])
            anchor = operation.get("before_task_id") if op == "insert" else None
            if anchor in destination:
                destination.insert(destination.index(anchor), task_id)
            else:
                destination.append(task_id)
            owners[task_id] = target
        elif op == "swap":
            other_id = operation.get("other_task_id")
            for queue in queues.values():
                for index, queued_id in enumerate(queue):
                    if queued_id == task_id:
                        queue[index] = other_id
                    elif queued_id == other_id:
                        queue[index] = task_id
            owners[task_id], owners[other_id] = owners.get(other_id), owners.get(task_id)
        else:
            return {"supported": False, "reason": "unsupported_queue_operation", "planned_state": None}
    for dispatch in dispatches:
        task_id = dispatch.get("task_id")
        platform_id = dispatch.get("platform_id")
        for queued_platform, queue in queues.items():
            if queued_platform != platform_id and task_id in queue:
                queue.remove(task_id)
        # Runtime sync preserves the current order and appends newly owned tasks.
        target_queue = queues.setdefault(platform_id, [])
        if task_id not in target_queue:
            target_queue.append(task_id)
        owners[task_id] = platform_id
    return {"supported": True, "reason": None, "planned_state": state}


def _selection_plan(observation: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    baseline = _owner_queues(observation)
    projections = []
    selected = None
    for candidate in candidates:
        action = candidate["full_environment_action"]
        projection = _project_owner_queues(observation, action)
        planned_state = projection["planned_state"]
        effective = bool(
            projection["supported"] and planned_state != baseline
        )
        row = {
            "candidate_key": candidate["candidate_key"],
            "legal": candidate.get("legal") is True,
            "scope": action.get("scope"),
            "projection_supported": projection["supported"],
            "projection_reason": projection["reason"],
            "projected_owner_queue_state": planned_state,
            "effective_planned_mutation": effective,
        }
        projections.append(row)
        if (selected is None and row["legal"] and not action.get("noop")
                and action.get("scope") == "LOCAL_REPAIR" and effective):
            selected = candidate
    return selected, projections


def _advance_to_event(env: EventReliefEnv, event_time: int, trigger: TriggerEngine) -> tuple[list[dict], dict, dict, dict]:
    previous = copy.deepcopy(env.public_observation())
    history = [copy.deepcopy(previous)]
    detection = decision = affected = None
    while env.time < event_time:
        _, noop_receipt = repair_action(env, _noop())
        if not noop_receipt["postrepair_legal"]:
            raise ValueError("MECHANISM_NOOP_NOT_LEGAL")
        current, _, terminated, truncated, _ = env.step(_noop())
        history.append(copy.deepcopy(current))
        detection = trigger.detect(previous, current, history=history[-4:])
        if int(current["time"]) == event_time:
            affected = identify_affected_scope(current, detection)
            decision = trigger.decide(detection, event_time, mode="event", affected_scope=affected)
        previous = copy.deepcopy(current)
        if terminated or truncated:
            raise ValueError("MECHANISM_EPISODE_ENDED_BEFORE_EVENT")
    if detection is None or decision is None or affected is None:
        raise ValueError("MECHANISM_EVENT_SNAPSHOT_NOT_REACHED")
    return history[-4:], detection, decision, affected


def export_branches(wrapper_path: str | Path, output_root: str | Path, *, event_time: int | None = None,
                    max_minutes: int = 30) -> dict[str, Any]:
    wrapper_path = Path(wrapper_path).resolve(strict=True)
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    if not isinstance(wrapper, dict):
        raise ValueError("MECHANISM_WRAPPER_OBJECT_REQUIRED")
    tape = wrapper.get("event_tape")
    if not isinstance(tape, list) or not tape:
        raise ValueError("MECHANISM_EVENT_TAPE_REQUIRED")
    selected_time = int(event_time if event_time is not None else min(int(row["time"]) for row in tape))
    if selected_time not in {int(row["time"]) for row in tape}:
        raise ValueError("MECHANISM_EVENT_TIME_NOT_IN_TAPE")
    if not 1 <= int(max_minutes) <= 30:
        raise ValueError("MECHANISM_WINDOW_LIMIT")

    output_base = Path(output_root)
    evidence_root = output_base / f"mechanism-{uuid.uuid4().hex}"
    evidence_root.mkdir(parents=True, exist_ok=False)
    hashes_before = _source_hashes()
    _write_json(evidence_root / "SOURCE_HASHES_BEFORE.json", hashes_before)
    _write_json(evidence_root / "SCENARIO_WRAPPER.json", wrapper)
    base_scenario = wrapper.get("base_scenario", {})
    c1_snapshot = base_scenario.get("chapter1_snapshot", {})
    c1_assignment = generate_public_c1_initial_assignment(
        base_scenario, seed=int(wrapper.get("seed_variant", 8201)), schedule_backlog=True,
    )
    if c1_snapshot.get("assignment_receipt") != c1_assignment["receipt"]:
        raise ValueError("MECHANISM_C1_RECEIPT_DOES_NOT_REGENERATE")
    if wrapper.get("queue_plan") != c1_assignment["queues"]:
        raise ValueError("MECHANISM_C1_QUEUE_PLAN_DOES_NOT_REGENERATE")
    _write_json(evidence_root / "C1_PUBLIC_INPUT.json", c1_assignment["public_input"])
    _write_json(evidence_root / "C1_RECEIPT.json", c1_assignment["receipt"])
    _write_json(evidence_root / "REQUEST.json", {
        "schema": "n02-v3-mechanism-request/1", "wrapper_path": str(wrapper_path),
        "wrapper_sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
        "event_time": selected_time, "max_minutes": int(max_minutes),
        "selection_rule": SELECTION_RULE,
        "branch_rule": "every legal candidate in deterministic generator order; each branch starts from identical deep-copied snapshot; first action is candidate and every continuation action is NOOP",
        "created_utc": datetime.now(timezone.utc).isoformat(),
    })

    trigger = TriggerEngine(
        {"trigger": {"threshold": 0.0, "hysteresis_margin": 0.0, "warmup_steps": 0,
                      "persistence_steps": 1, "delta_min": 0}},
        {"threshold": 0.0, "hysteresis_margin": 0.0, "warmup_steps": 0,
         "persistence_steps": 1, "delta_min": 0},
    )
    trigger_config = {"trigger": {"threshold": 0.0, "hysteresis_margin": 0.0, "warmup_steps": 0,
                                  "persistence_steps": 1, "delta_min": 0}}
    threshold_config = {"threshold": 0.0, "hysteresis_margin": 0.0, "warmup_steps": 0,
                        "persistence_steps": 1, "delta_min": 0}
    _write_json(evidence_root / "TRIGGER_CONFIG_AND_THRESHOLD.json", {
        "purpose": "S0 disclosed diagnostic only",
        "trigger_config": trigger_config, "threshold_manifest": threshold_config,
        "threshold_used": 0.0,
    })
    env = EventReliefEnv(wrapper)
    initial_public = env.reset()
    history, detection, decision, affected = _advance_to_event(env, selected_time, trigger)
    observation = copy.deepcopy(env.public_observation())
    snapshot_env = copy.deepcopy(env)
    snapshot_sha256 = _private_simulator_state_sha256(snapshot_env)
    tape_sha256 = _digest(wrapper["event_tape"])
    catalog = generate_reconstruction_candidates(observation, affected, env=env)
    _write_json(evidence_root / "INITIAL_PUBLIC_OBSERVATION.json", initial_public)
    _write_json(evidence_root / "PUBLIC_OBSERVATION.json", observation)
    _write_json(evidence_root / "PUBLIC_HISTORY.json", history)
    _write_json(evidence_root / "TRIGGER_DETECTION.json", detection)
    _write_json(evidence_root / "TRIGGER_DECISION.json", decision)
    _write_json(evidence_root / "AFFECTED_SCOPE.json", affected)
    _write_json(evidence_root / "CANDIDATE_CATALOG_PRODUCER.json", catalog)

    legal_candidates = [copy.deepcopy(row) for row in catalog if row.get("legal") is True]
    if not any(row["full_environment_action"].get("noop") is True for row in legal_candidates):
        raise ValueError("MECHANISM_CATALOG_NO_NOOP")
    local_nonnoop = [row for row in legal_candidates
                     if not row["full_environment_action"].get("noop")
                     and row["full_environment_action"].get("scope") == "LOCAL_REPAIR"]
    if len(local_nonnoop) < 2:
        _write_json(evidence_root / "CATALOG_DIAGNOSTIC.json", {
            "status": "insufficient_local_candidates", "legal_noop_present": True,
            "legal_nonnoop_local_candidate_count": len(local_nonnoop),
        })
    selection_candidate, candidate_projections = _selection_plan(observation, legal_candidates)
    selection_plan = {
        "schema": "n02-v3-mechanism-selection-plan/1",
        "rule": SELECTION_RULE,
        "projection_inputs": ["PUBLIC_OBSERVATION.json", "CANDIDATE_CATALOG_PRODUCER.json"],
        "projection_scope": "owners and queue order from public observation; apply complete candidate queue operations then dispatches",
        "private_simulator_truth_read": False,
        "catalog_order_keys": [row["candidate_key"] for row in legal_candidates],
        "candidate_projections": candidate_projections,
        "selected_candidate_key": selection_candidate["candidate_key"] if selection_candidate else None,
    }
    _write_json(evidence_root / "SELECTION_PLAN.json", selection_plan)
    request = json.loads((evidence_root / "REQUEST.json").read_text(encoding="utf-8"))
    request["selection_plan"] = {
        "path": "SELECTION_PLAN.json",
        "sha256": hashlib.sha256((evidence_root / "SELECTION_PLAN.json").read_bytes()).hexdigest(),
        "selected_candidate_key": selection_plan["selected_candidate_key"],
    }
    request["projection_rule"] = selection_plan["projection_scope"]
    _write_json(evidence_root / "REQUEST.json", request)
    _write_json(evidence_root / "SELECTION_RULE.json", {
        "rule": SELECTION_RULE,
        "rule_frozen_before_branch_execution": True,
        "catalog_order_keys": [row["candidate_key"] for row in legal_candidates],
        "selection_plan_sha256": hashlib.sha256((evidence_root / "SELECTION_PLAN.json").read_bytes()).hexdigest(),
        "selected_candidate_key": selection_candidate["candidate_key"] if selection_candidate else None,
        "selected_action": copy.deepcopy(selection_candidate["full_environment_action"]) if selection_candidate else None,
    })
    planned_end = selected_time + min(int(max_minutes), int(observation.get("horizon", selected_time + max_minutes)) - selected_time)
    branches = []
    producer_rows = []
    selected_action_chain = None
    noop_action = _noop()
    for producer_candidate in legal_candidates:
        candidate = copy.deepcopy(producer_candidate)
        branch_env = copy.deepcopy(snapshot_env)
        if branch_env.public_observation() != observation:
            raise ValueError("MECHANISM_BRANCH_PUBLIC_SNAPSHOT_MISMATCH")
        branch_initial_sha256 = _private_simulator_state_sha256(branch_env)
        if branch_initial_sha256 != snapshot_sha256:
            raise ValueError("MECHANISM_BRANCH_PRIVATE_SNAPSHOT_MISMATCH")
        receipts: list[dict] = []
        action_audit = []
        start = selected_time
        for index in range(planned_end - start):
            requested = producer_candidate["full_environment_action"] if index == 0 else noop_action
            before = copy.deepcopy(branch_env.public_observation())
            repaired, receipt = repair_action(branch_env, copy.deepcopy(requested))
            after_repair_legal = bool(receipt.get("postrepair_legal"))
            executed, _, terminated, truncated, info = branch_env.step(copy.deepcopy(repaired))
            receipts.append(copy.deepcopy(receipt))
            before_state = _owner_queues(before)
            after_state = _owner_queues(executed)
            action_audit.append({
                "time": start + index, "requested_action": copy.deepcopy(requested),
                "repaired_action": copy.deepcopy(repaired), "repair_receipt": copy.deepcopy(receipt),
                "executed_action": copy.deepcopy(branch_env.export_trajectory()["steps"][-1]["full_environment_action"]),
                "owner_queue_before": before_state, "owner_queue_after": after_state,
                "owner_queue_diff": {
                    "owner_changes": {task_id: {"before": before_owner, "after": after_state["owners"].get(task_id)}
                                      for task_id, before_owner in before_state["owners"].items()
                                      if before_owner != after_state["owners"].get(task_id)},
                    "queue_changes": {
                        platform_id: {"before": before_state["queues"].get(platform_id, []),
                                      "after": after_state["queues"].get(platform_id, [])}
                        for platform_id in sorted(set(before_state["queues"]) | set(after_state["queues"]))
                        if before_state["queues"].get(platform_id, []) != after_state["queues"].get(platform_id, [])
                    },
                },
                "raw_events": copy.deepcopy(info.get("raw_events", [])),
            })
            if not after_repair_legal:
                raise ValueError("MECHANISM_REPAIR_FAILED_TO_PRODUCE_LEGAL_ACTION")
            if terminated or truncated:
                break
        actual_end = start + len(receipts)
        trajectory = _window_trajectory(branch_env, start, actual_end, producer_candidate, receipts)
        binding = {"simulator_snapshot_sha256": branch_initial_sha256,
                   "event_tape_sha256": tape_sha256}
        branch_row = {"candidate_key": candidate["candidate_key"],
                      "candidate": candidate,
                      "trajectory": trajectory, "private_binding": binding}
        branches.append(branch_row)
        producer_rows.append({
            "candidate_key_producer": producer_candidate["candidate_key"],
            "candidate": producer_candidate, "action_audit": action_audit,
            "trajectory": trajectory, "private_binding": binding,
        })
        if selection_candidate is not None and producer_candidate["candidate_key"] == selection_candidate["candidate_key"]:
            selected_action_chain = copy.deepcopy(producer_rows[-1])

    candidates = copy.deepcopy(legal_candidates)
    window = {
        "window_id": f"{wrapper['parent_id']}-t{selected_time:02d}",
        "parent_id": wrapper["parent_id"], "split": wrapper["split"],
        "window_start": selected_time, "window_end": planned_end,
        "event_tape_id": wrapper["event_tape_id"], "public_observation": observation,
        "private_binding": {"simulator_snapshot_sha256": snapshot_sha256,
                            "event_tape_sha256": tape_sha256},
        "history": history, "candidates": candidates, "branches": branches,
        "reward_weights": copy.deepcopy(env.reward_config),
    }
    _write_json(evidence_root / "WINDOW.json", window)
    _write_json(evidence_root / "BRANCH_EVIDENCE.json", producer_rows)
    if selected_action_chain is not None:
        _write_json(evidence_root / "SELECTED_ACTION_CHAIN.json", selected_action_chain)
    else:
        _write_json(evidence_root / "SELECTED_ACTION_CHAIN.json", {
            "status": "no_legal_local_candidate_selected_by_frozen_rule",
            "action_chain": None,
        })
    try:
        labels = recompute_consequence_labels(window)
        _write_json(evidence_root / "PRODUCER_LABELS_FOR_REVIEW.json", labels)
        label_status = {"status": "recomputed_for_independent_review", "self_certified_pass": False}
    except Exception as error:
        _write_json(evidence_root / "PRODUCER_LABEL_RECOMPUTE_ERROR.json", {
            "error_type": type(error).__name__, "error": str(error),
            "self_certified_pass": False,
        })
        label_status = {"status": "recompute_error_for_independent_review", "self_certified_pass": False}

    hashes_after = _source_hashes()
    _write_json(evidence_root / "SOURCE_HASHES_AFTER.json", hashes_after)
    summary = {
        "schema": "n02-v3-mechanism-evidence/1", "evidence_id": evidence_root.name,
        "evidence_root": str(evidence_root), "parent_id": wrapper["parent_id"],
        "condition": wrapper.get("condition"), "event_time": selected_time,
        "triggered": decision.get("triggered"), "decision_scope": decision.get("high_level_action"),
        "identified_scope": affected.get("scope"),
        "legal_candidate_count": len(legal_candidates),
        "legal_noop_count": sum(bool(row["full_environment_action"].get("noop")) for row in legal_candidates),
        "legal_nonnoop_local_candidate_count": len(local_nonnoop),
        "selection_rule": SELECTION_RULE, "window_start": selected_time,
        "planned_window_end": planned_end, "branch_count": len(branches),
        "source_hashes_unchanged": hashes_before == hashes_after,
        "label_recompute": label_status,
    }
    _write_json(evidence_root / "SUMMARY.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", required=True, help="serialized event wrapper JSON")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--event-time", type=int)
    parser.add_argument("--max-minutes", type=int, default=30)
    args = parser.parse_args(argv)
    print(json.dumps(export_branches(args.wrapper, args.output_root, event_time=args.event_time,
                                     max_minutes=args.max_minutes), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
