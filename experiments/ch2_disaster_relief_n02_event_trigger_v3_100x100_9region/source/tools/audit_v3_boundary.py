"""Produce replayable boundary evidence for v3 scenario and public C1 inputs."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "package"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from civilian.chapter1_adapter import generate_public_c1_initial_assignment
from civilian.region_scenarios import build_scenario
from civilian.scenario_schema import validate_region_event_scenario
from civilian.stable_identity import key_digest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _membership(position: list[float]) -> str:
    x, y = map(float, position)
    col = 0 if x < 33 else 1 if x < 66 else 2
    row = 0 if y < 33 else 1 if y < 66 else 2
    return f"r{row}{col}"


def _source_hashes() -> dict[str, str]:
    relative_paths = (
        "package/civilian/chapter1_adapter.py",
        "package/civilian/baselines.py",
        "package/civilian/region_scenarios.py",
    )
    return {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in relative_paths}


def _variant_wrapper(wrapper: dict, name: str) -> dict:
    result = copy.deepcopy(wrapper)
    base = result["base_scenario"]
    if name == "hidden_task_change":
        hidden = next(task for task in base["tasks"] if not task["known_initial"])
        hidden["priority"] = 4.25
    elif name == "future_event_tape_change":
        event = next(row for row in result["event_tape"] if row["kind"] == "task_arrival")
        event["time"] += 1
        result["event_tape_id"] = key_digest(result["event_tape"])
    elif name == "preset_snapshot_queue_change":
        task = next(task for task in base["tasks"] if task["known_initial"] and task["kind"] == "inspection")
        platform = next(platform for platform in base["platforms"]
                        if platform["type"] == "uav" and "inspect" in platform["capabilities"])
        base["chapter1_snapshot"]["source"] = "synthetic_initial_assignment"
        base["chapter1_snapshot"].pop("assignment_receipt", None)
        base["chapter1_snapshot"]["queues"] = {row["id"]: [] for row in base["platforms"]}
        base["chapter1_snapshot"]["queues"][platform["id"]] = [task["id"]]
    elif name == "public_priority_control":
        task = next(task for task in base["tasks"] if task["known_initial"])
        task["priority"] = 1000.0
    else:
        raise ValueError(f"unknown variant {name}")
    if name != "preset_snapshot_queue_change" and name != "hidden_task_change" and name != "future_event_tape_change":
        base["chapter1_snapshot"]["source"] = "synthetic_initial_assignment"
        base["chapter1_snapshot"].pop("assignment_receipt", None)
    result["queue_plan"] = copy.deepcopy(base["chapter1_snapshot"]["queues"])
    return result


def produce(output_root: Path) -> Path:
    evidence_id = uuid.uuid4().hex
    evidence_dir = output_root / evidence_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    source_hashes_before = _source_hashes()
    wrapper = build_scenario(scenario_id="n02-v3-boundary-audit", split="development",
                             condition="new_arrival", seed_variant=8201)
    _write_json(evidence_dir / "SCENARIO_WRAPPER.json", wrapper)

    tasks = wrapper["base_scenario"]["tasks"]
    task_evidence = [{
        "index": index,
        "id": task["id"],
        "known_initial": task["known_initial"],
        "position": copy.deepcopy(task["position"]),
        "declared_region_id": task["region_id"],
        "region_id_recomputed_from_position": _membership(task["position"]),
    } for index, task in enumerate(tasks)]
    _write_json(evidence_dir / "TASK_COORDINATES_AND_REGIONS.json", {
        "schema": "v3-boundary-task-coordinate-evidence/1",
        "coordinate_source": "SCENARIO_WRAPPER.json:base_scenario.tasks",
        "membership_rule": "x,y in [0,100); column cut points 33 and 66; row cut points 33 and 66",
        "tasks": task_evidence,
    })

    cases = []
    for name in ("baseline", "hidden_task_change", "future_event_tape_change",
                 "preset_snapshot_queue_change", "public_priority_control"):
        variant = copy.deepcopy(wrapper) if name == "baseline" else _variant_wrapper(wrapper, name)
        validate_region_event_scenario(variant)
        assignment = generate_public_c1_initial_assignment(variant["base_scenario"], seed=8201,
                                                           schedule_backlog=True)
        actual = {
            "public_input_sha256": key_digest(assignment["public_input"]),
            "queues_sha256": key_digest(assignment["queues"]),
        }
        variant_dir = evidence_dir / name
        _write_json(variant_dir / "SCENARIO_WRAPPER.json", variant)
        _write_json(variant_dir / "C1_PUBLIC_INPUT.json", assignment["public_input"])
        _write_json(variant_dir / "C1_QUEUES.json", assignment["queues"])
        cases.append({
            "variant": name,
            "scenario_wrapper": f"{name}/SCENARIO_WRAPPER.json",
            "public_input": f"{name}/C1_PUBLIC_INPUT.json",
            "queues": f"{name}/C1_QUEUES.json",
            "recomputed_hashes": actual,
        })

    source_hashes_after = _source_hashes()
    _write_json(evidence_dir / "REPLAY_INDEX.json", {
        "schema": "v3-boundary-replay-evidence/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_id": evidence_id,
        "producer": "tools/audit_v3_boundary.py",
        "replay_command": "python -B tools/audit_v3_boundary.py --output-root evidence/a-boundary",
        "interpretation": "Raw producer inputs and outputs for independent inspection; this file does not assert audit approval.",
        "c1_call": "civilian.chapter1_adapter.generate_public_c1_initial_assignment(base_scenario, seed=8201, schedule_backlog=True)",
        "source_hashes_before": source_hashes_before,
        "source_hashes_after": source_hashes_after,
        "cases": cases,
        "expected_relations_for_reviewer": {
            "noninterference_pairs": [
                ["baseline", "hidden_task_change"],
                ["baseline", "future_event_tape_change"],
                ["baseline", "preset_snapshot_queue_change"],
            ],
            "control_pair": ["baseline", "public_priority_control"],
        },
    })
    return evidence_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT / "evidence" / "a-boundary")
    args = parser.parse_args()
    path = produce(args.output_root)
    print(path)


if __name__ == "__main__":
    main()
