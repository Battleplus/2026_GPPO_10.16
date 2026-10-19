"""Rebuild and export CPU-only S1 event mechanism evidence for independent review."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "package" / "civilian"
sys.path.insert(0, str(PACKAGE))

from region_scenarios import CONDITIONS, build_s1_regional_support_witness, build_scenario_set
from run_v3_mechanism import export_branches


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _communication_receipt_from_records(condition: str, wrapper: dict,
                                        raw_rows: list[dict], detection: dict) -> dict | None:
    event_rows = [row for row in wrapper["event_tape"] if row.get("kind") == "communication_drop"]
    if not event_rows:
        return None
    noop = next((row for row in raw_rows
                 if row["candidate"]["full_environment_action"].get("noop") is True), None)
    if noop is None:
        raise ValueError("communication receipt requires the raw NOOP branch")
    observed = [event for audit in noop["action_audit"] for event in audit.get("raw_events", [])
                if event.get("type") == "communication_changed"]
    detected = copy.deepcopy(detection.get("event_details", {}).get("communication_edge_changes", []))
    detected_pairs = {
        frozenset((str(row.get("source")), str(row.get("target")))) for row in detected
    }
    raw_ids = {str(event.get("event_id")) for event in observed if event.get("event_id") is not None}
    raw_pairs = {
        frozenset((str(link.get("source")), str(link.get("target"))))
        for event in observed for link in event.get("links", [])
        if link.get("source") is not None and link.get("target") is not None
    }
    observed_rows = []
    observed_ids = set()
    observed_pairs = set()
    for event in event_rows:
        event_id = str(event.get("event_id"))
        links = [link for link in event.get("links", [])
                 if len(link) == 2 and frozenset(map(str, link)) in detected_pairs | raw_pairs]
        if event_id in raw_ids or links:
            observed_rows.append({**copy.deepcopy(event), "links": links})
            observed_ids.add(event_id)
            observed_pairs.update(frozenset(map(str, link)) for link in links)
    if not observed_ids:
        return None
    observed_detected = [row for row in detected
                         if frozenset((str(row.get("source")), str(row.get("target")))) in observed_pairs]
    observed_raw = [row for row in observed if str(row.get("event_id")) in observed_ids]
    return {
        "schema": "s1-communication-event-receipt/1",
        "status": "observed_in_current_snapshot_or_branch_horizon",
        "condition": condition,
        "event_tape_events": observed_rows,
        "detected_public_link_changes": observed_detected,
        "raw_noop_branch_events": observed_raw,
        "event_ids_observed": sorted(observed_ids),
        "link_change_count": len(observed_pairs),
        "source": "raw NOOP branch action audit; producer record pending independent review",
    }


def _communication_receipt(case_root: Path, condition: str, wrapper: dict) -> dict | None:
    evidence_dirs = sorted(path for path in case_root.glob("mechanism-*") if path.is_dir())
    if len(evidence_dirs) != 1:
        raise ValueError("expected exactly one mechanism evidence directory")
    raw_rows = json.loads((evidence_dirs[0] / "BRANCH_EVIDENCE.json").read_text(encoding="utf-8"))
    detection = json.loads((evidence_dirs[0] / "TRIGGER_DETECTION.json").read_text(encoding="utf-8"))
    return _communication_receipt_from_records(condition, wrapper, raw_rows, detection)


def run_suite(output_root: str | Path, *, tape_seed: int = 8201,
              max_minutes: int = 8) -> dict:
    if not 1 <= int(max_minutes) <= 30:
        raise ValueError("max_minutes must be between 1 and 30")
    root = Path(output_root)
    run_root = root / f"s1-cpu-{uuid.uuid4().hex}"
    run_root.mkdir(parents=True, exist_ok=False)
    scenarios = build_scenario_set(4, 4, tape_seed=tape_seed)
    support_index = next(index for index, row in enumerate(scenarios)
                         if row["condition"] == "regional_support")
    scenarios[support_index] = build_s1_regional_support_witness(
        scenario_id=f"{run_root.name}-regional-support", seed_variant=tape_seed + support_index,
    )
    seen: set[str] = set()
    case_summaries = []
    for index, wrapper in enumerate(scenarios):
        condition = str(wrapper["condition"])
        if condition in seen:
            raise ValueError(f"duplicate S1 coverage condition {condition}")
        seen.add(condition)
        case_root = run_root / f"{wrapper['split']}-{index + 1:02d}-{condition}"
        case_root.mkdir(parents=True, exist_ok=False)
        wrapper_path = case_root / "SCENARIO_INPUT.json"
        _write_json(wrapper_path, wrapper)
        event_time = min(int(row["time"]) for row in wrapper["event_tape"])
        summary = export_branches(wrapper_path, case_root, event_time=event_time,
                                  max_minutes=int(max_minutes))
        receipt = _communication_receipt(case_root, condition, wrapper)
        if receipt is not None:
            _write_json(case_root / "COMMUNICATION_RECEIPT.json", receipt)
        has_communication_event = any(row.get("kind") == "communication_drop"
                                      for row in wrapper["event_tape"])
        case_summaries.append({
            "split": wrapper["split"], "condition": condition,
            "parent_id": wrapper["parent_id"], "event_time": event_time,
            "event_tape_id": wrapper["event_tape_id"],
            "evidence_root": summary["evidence_root"],
            "triggered": summary["triggered"],
            "decision_scope": summary["decision_scope"],
            "identified_scope": summary["identified_scope"],
            "legal_candidate_count": summary["legal_candidate_count"],
            "legal_nonnoop_local_candidate_count": summary["legal_nonnoop_local_candidate_count"],
            "label_recompute": summary["label_recompute"],
            "communication_receipt": str(case_root / "COMMUNICATION_RECEIPT.json") if receipt else None,
            "communication_status": (
                "observed" if receipt else
                "not_observed_within_horizon" if has_communication_event else "not_applicable"
            ),
        })
    if set(CONDITIONS) != seen:
        raise ValueError("S1 suite did not cover all preregistered conditions")
    manifest = {
        "schema": "n02-v3-s1-cpu-suite/1",
        "run_id": run_root.name,
        "device": "cpu",
        "world_model": False,
        "ppo": False,
        "coverage_conditions": list(CONDITIONS),
        "train_count": sum(row["split"] == "train" for row in case_summaries),
        "development_count": sum(row["split"] == "development" for row in case_summaries),
        "independent_review_status": "pending; producer evidence only",
        "cases": case_summaries,
    }
    _write_json(run_root / "S1_CPU_SUITE.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--tape-seed", type=int, default=8201)
    parser.add_argument("--max-minutes", type=int, default=8)
    args = parser.parse_args(argv)
    print(json.dumps(run_suite(args.output_root, tape_seed=args.tape_seed,
                              max_minutes=args.max_minutes), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
