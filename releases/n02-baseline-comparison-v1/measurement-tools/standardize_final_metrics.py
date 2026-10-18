#!/usr/bin/env python3
"""Standardize final formal-pilot metrics from an independent oracle report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class MetricsError(ValueError):
    pass


SOURCE_METRICS = {
    "completion_rate": "completion_rate",
    "on_time_rate": "on_time_rate",
    "mean_delay": "mean_delay",
    "global_utility": "global_utility",
    "trigger_count": "trigger_count",
    "planning_invocation_count": "planning_invocation_count",
    "effective_reconstruction_count": "effective_reconstruction_count",
    "reconstruction_size": "reconstruction_size",
    "local_invocation_count": "local_repair_count",
    "global_invocation_count": "global_replan_count",
    "requested_nonnoop": "requested_non_noop_count",
    "energy_units": "energy_used",
    "task_switch_count": "task_switch_count",
    "environment_action_delivery_message_count": "environment_action_delivery_message_count",
    "rule_protocol_message_count": "rule_protocol_message_count",
    "planning_latency_seconds": "total_planning_seconds",
    "policy_response_seconds": "total_policy_response_seconds",
}
CELL_KEY_FIELDS = ("method_id", "seed", "parent_id", "event_tape_id")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MetricsError(f"oracle metric {field} must be a finite number")
    return float(value)


def read_jsonl(path: Path):
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                raise MetricsError(f"blank action row at line {line_no}")
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise MetricsError(f"invalid action JSONL at line {line_no}") from exc
            if not isinstance(row, dict):
                raise MetricsError(f"action row {line_no} is not an object")
            yield row


def key_from_action(row: dict[str, Any]) -> tuple[str, int, str, str]:
    method, seed, parent, tape = (row.get("method_id"), row.get("seed"), row.get("parent_id"), row.get("event_tape_id"))
    if not isinstance(method, str) or type(seed) is not int or not isinstance(parent, str) or not isinstance(tape, str):
        raise MetricsError("action row is missing method/seed/parent/tape identity")
    return method, seed, parent, tape


def key_from_episode(row: dict[str, Any]) -> tuple[str, int, str, str]:
    raw = row.get("key")
    if not isinstance(raw, list) or len(raw) != 4:
        raise MetricsError("oracle episode key must be [method_id,parent_id,event_tape_id,seed]")
    method, parent, tape, seed = raw
    if not isinstance(method, str) or not isinstance(parent, str) or not isinstance(tape, str) or type(seed) is not int:
        raise MetricsError("oracle episode key has invalid types")
    return method, seed, parent, tape


def standard_metrics(source: dict[str, Any], positive_violation_ticks: int) -> dict[str, float | int]:
    if not isinstance(source, dict):
        raise MetricsError("oracle episode has no recomputed metric object")
    values = {target: require_finite_number(source[field], field) for field, target in SOURCE_METRICS.items()}
    planning_count = values["planning_invocation_count"]
    if planning_count < 0 or planning_count != int(planning_count):
        raise MetricsError("planning_invocation_count must be a nonnegative integer")
    values["response_time"] = values["total_planning_seconds"] / max(1, int(planning_count))
    values["communication_messages"] = (values["environment_action_delivery_message_count"]
                                        + values["rule_protocol_message_count"])
    values["constraint_violation_rate"] = positive_violation_ticks / 60
    values.pop("total_planning_seconds")
    values.pop("total_policy_response_seconds")
    values.pop("environment_action_delivery_message_count")
    values.pop("rule_protocol_message_count")
    return values


def standardize(oracle_path: Path, actions_path: Path) -> dict[str, Any]:
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    if (not isinstance(oracle, dict) or oracle.get("schema") != "independent-baseline-oracle-report/1"
            or oracle.get("status") != "PASS" or oracle.get("mismatch") != [] or oracle.get("missing") != []):
        raise MetricsError("oracle report must have the expected schema, PASS status, and empty mismatch/missing lists")
    episode_rows = oracle.get("episodes")
    if not isinstance(episode_rows, list) or len(episode_rows) != 54:
        raise MetricsError("oracle report must contain exactly 54 recomputed episode cells")
    episodes = {}
    for row in episode_rows:
        if not isinstance(row, dict):
            raise MetricsError("oracle episode record is malformed")
        key = key_from_episode(row)
        if key in episodes:
            raise MetricsError("oracle report contains duplicate episode cells")
        episodes[key] = row

    tick_sets: dict[tuple[str, int, str, str], set[int]] = defaultdict(set)
    positive_violation_ticks: dict[tuple[str, int, str, str], set[int]] = defaultdict(set)
    for row in read_jsonl(actions_path):
        key = key_from_action(row)
        tick = row.get("time")
        if type(tick) is not int or not 0 <= tick < 60:
            raise MetricsError("action row time must be an integer tick in [0, 59]")
        if tick in tick_sets[key]:
            raise MetricsError(f"duplicate action tick for cell {key}")
        tick_sets[key].add(tick)
        violations = row.get("constraint_violations")
        if type(violations) is not int or violations < 0:
            raise MetricsError("constraint_violations must be a nonnegative integer on every action row")
        if violations > 0:
            positive_violation_ticks[key].add(tick)

    if set(tick_sets) != set(episodes):
        missing = sorted(set(episodes) - set(tick_sets))
        extra = sorted(set(tick_sets) - set(episodes))
        raise MetricsError(f"action/oracle cell sets differ: missing_action_cells={len(missing)}, extra_action_cells={len(extra)}")
    if any(len(ticks) != 60 for ticks in tick_sets.values()):
        raise MetricsError("each formal action cell must contain exactly 60 distinct ticks")

    by_cell = {}
    by_method_cells: dict[str, list[dict[str, float | int]]] = defaultdict(list)
    for key, row in sorted(episodes.items()):
        metrics = standard_metrics(row.get("recomputed"), len(positive_violation_ticks.get(key, set())))
        cell_name = f"{key[0]}|{key[1]}|{key[2]}|{key[3]}"
        by_cell[cell_name] = {
            "method_id": key[0], "seed": key[1], "parent_id": key[2], "event_tape_id": key[3],
            "positive_constraint_violation_ticks": len(positive_violation_ticks.get(key, set())),
            "ticks": 60, "metrics": metrics,
        }
        by_method_cells[key[0]].append(metrics)
    if len(by_method_cells) != 9 or any(len(cells) != 6 for cells in by_method_cells.values()):
        raise MetricsError("formal cells must cover nine methods with six seed-parent cells per method")
    all_seeds = {key[1] for key in episodes}
    all_parents = {key[2] for key in episodes}
    if len(all_seeds) != 3 or len(all_parents) != 2:
        raise MetricsError("formal cells must contain exactly three seeds and two development parents")
    expected_pairs = {(seed, parent) for seed in all_seeds for parent in all_parents}
    for method in by_method_cells:
        method_pairs = {(key[1], key[2]) for key in episodes if key[0] == method}
        if method_pairs != expected_pairs:
            raise MetricsError(f"method {method} does not cover the full seed-parent pairing")

    metric_names = sorted(next(iter(by_cell.values()))["metrics"])
    per_method = {}
    for method, cells in sorted(by_method_cells.items()):
        per_method[method] = {metric: sum(float(cell[metric]) for cell in cells) / len(cells) for metric in metric_names}

    definitions = {
        "completion_rate": "oracle recomputed completion_rate, unchanged",
        "on_time_rate": "oracle recomputed on_time_rate, unchanged",
        "mean_delay": "oracle recomputed mean_delay, unchanged",
        "global_utility": "oracle recomputed global_utility, unchanged",
        "trigger_count": "oracle recomputed trigger_count, unchanged",
        "planning_invocation_count": "oracle recomputed planning_invocation_count, unchanged",
        "requested_nonnoop": "oracle recomputed requested_nonnoop, unchanged",
        "effective_reconstruction_count": "oracle recomputed effective_reconstruction_count, unchanged",
        "reconstruction_size": "oracle recomputed reconstruction_size, unchanged",
        "local_repair_count": "oracle local_invocation_count; a non-NOOP local-scope invocation count, not effective local repair",
        "global_replan_count": "oracle global_invocation_count; a non-NOOP global-scope invocation count",
        "communication_messages": "environment_action_delivery_message_count + rule_protocol_message_count",
        "energy_used": "oracle recomputed energy_used, unchanged",
        "requested_non_noop_count": "oracle recomputed requested_nonnoop, unchanged",
        "task_switch_count": "oracle recomputed task_switch_count, unchanged",
        "constraint_violation_rate": "number of the cell's 60 ticks with constraint_violations > 0, divided by 60; zero violations yields 0.0",
        "response_time": "planning_latency_seconds / max(1, planning_invocation_count); zero planned calls therefore retain a zero numerator and denominator 1",
    }
    return {
        "schema": "n02-standardized-final-metrics/1",
        "scope": "formal_simulation_metrics_only_no_review_verdict",
        "oracle_status": oracle["status"],
        "cell_count": len(by_cell),
        "by_cell": by_cell,
        "per_method_mean_over_six_cells": per_method,
        "definitions": definitions,
        "auxiliary_source_metrics": {
            "total_planning_seconds": "planning_latency_seconds, retained as source audit field",
            "total_policy_response_seconds": "policy_response_seconds, retained as source audit field",
            "requested_non_no_op_count": "oracle recomputed requested_non_no_op_count, retained as a source and standardized metric",
        },
        "repeat_seed_note": "For the three deterministic rule-based methods, repeated seed labels identify deterministic paired repeats rather than independent random seeds. This note does not characterize the learning methods.",
        "input_identity": {
            "oracle_report": {"path": str(oracle_path.resolve()), "bytes": oracle_path.stat().st_size, "sha256": file_sha256(oracle_path)},
            "actions": {"path": str(actions_path.resolve()), "bytes": actions_path.stat().st_size, "sha256": file_sha256(actions_path)},
            "standardizer": {"path": str(Path(__file__).resolve()), "bytes": Path(__file__).stat().st_size,
                             "sha256": file_sha256(Path(__file__).resolve())},
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-report", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        oracle_path = args.oracle_report.expanduser().resolve(strict=True)
        actions_path = args.actions.expanduser().resolve(strict=True)
        report = standardize(oracle_path, actions_path)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"status": "STANDARDIZED", "cells": report["cell_count"],
                          "methods": len(report["per_method_mean_over_six_cells"]), "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (MetricsError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
