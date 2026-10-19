"""Export a fresh public-C1 local arrival/control-treatment evidence pair."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "package" / "civilian"))

from event_environment import EventReliefEnv
from region_scenarios import build_s1_arrival_perturbation_pair
from run_v3_mechanism import _write_json, export_branches


def _noop() -> dict[str, Any]:
    return {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
            "queue_operations": [], "dispatches": []}


def _physical_metrics(wrapper: dict, task_id: str, platform_ids: set[str]) -> dict[str, dict[str, float]]:
    env = EventReliefEnv(wrapper)
    observation = env.reset()
    for _ in range(11):
        observation, _, _, _, _ = env.step(_noop())
    target = next(row for row in observation["tasks"] if row["id"] == task_id)
    if target["status"] != "pending":
        raise ValueError("S1 paired arrival task must remain pending at snapshot t=11")
    rows = {row["platform_id"]: row for row in env.candidate_dispatches()
            if row["task_id"] == task_id and row["platform_id"] in platform_ids}
    if set(rows) != platform_ids:
        raise ValueError("S1 paired candidates differ across physical comparison")
    return {platform_id: {key: float(rows[platform_id][key]) for key in
                          ("estimated_completion", "required_energy", "environmental_risk")}
            for platform_id in sorted(platform_ids)}


def _segment_intersects_rect(start: list[float], end: list[float], rect: list[int]) -> bool:
    x0, y0, width, height = map(float, rect)
    dx, dy = end[0] - start[0], end[1] - start[1]
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, start[0] - x0), (dx, x0 + width - start[0]),
                 (-dy, start[1] - y0), (dy, y0 + height - start[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def run_pair(output_root: str | Path, *, scenario_id: str = "s1-arrival-pair-final",
             seed_variant: int = 8201, max_minutes: int = 8) -> dict[str, Any]:
    base = Path(output_root)
    identity = uuid.uuid4().hex
    pair_root = base / identity
    pair_root.mkdir(parents=True, exist_ok=False)
    control, treatment = build_s1_arrival_perturbation_pair(
        scenario_id=scenario_id, split="development", seed_variant=seed_variant,
    )
    _write_json(pair_root / "CONTROL_WRAPPER.json", control)
    _write_json(pair_root / "TREATMENT_WRAPPER.json", treatment)
    control_summary = export_branches(pair_root / "CONTROL_WRAPPER.json", pair_root / "control",
                                      event_time=11, max_minutes=max_minutes)
    treatment_summary = export_branches(pair_root / "TREATMENT_WRAPPER.json", pair_root / "treatment",
                                        event_time=11, max_minutes=max_minutes)
    _write_json(pair_root / "control.stdout.json", control_summary)
    _write_json(pair_root / "treatment.stdout.json", treatment_summary)

    control_evidence = Path(control_summary["evidence_root"])
    treatment_evidence = Path(treatment_summary["evidence_root"])
    control_catalog = json.loads((control_evidence / "CANDIDATE_CATALOG_PRODUCER.json").read_text(encoding="utf-8"))
    treatment_catalog = json.loads((treatment_evidence / "CANDIDATE_CATALOG_PRODUCER.json").read_text(encoding="utf-8"))
    legal_control = [row for row in control_catalog if row.get("legal") is True
                     and not row["full_environment_action"].get("noop")]
    legal_treatment = [row for row in treatment_catalog if row.get("legal") is True
                       and not row["full_environment_action"].get("noop")]
    control_platforms = {row["full_environment_action"]["dispatches"][0]["platform_id"] for row in legal_control}
    treatment_platforms = {row["full_environment_action"]["dispatches"][0]["platform_id"] for row in legal_treatment}
    if control_platforms != treatment_platforms or len(control_platforms) < 2:
        raise ValueError("S1 pair requires the same two or more legal local alternatives")

    task_id = "task-r01-hidden"
    physical_control = _physical_metrics(control, task_id, control_platforms)
    physical_treatment = _physical_metrics(treatment, task_id, treatment_platforms)
    deltas = {platform_id: {
        key: round(physical_treatment[platform_id][key] - physical_control[platform_id][key], 9)
        for key in physical_control[platform_id]
    } for platform_id in sorted(control_platforms)}
    task = next(row for row in control["base_scenario"]["tasks"] if row["id"] == task_id)
    depot = next(row for row in control["base_scenario"]["depots"] if row["id"] == task["depot_id"])
    patch = control["event_tape"][1]["patch"]
    common_skeleton = [(row["time"], row["kind"], row["event_id"], row.get("patch"))
                       for row in control["event_tape"]]
    treatment_skeleton = [(row["time"], row["kind"], row["event_id"], row.get("patch"))
                          for row in treatment["event_tape"]]
    c1_control = json.loads((control_evidence / "C1_RECEIPT.json").read_text(encoding="utf-8"))
    c1_treatment = json.loads((treatment_evidence / "C1_RECEIPT.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "s1-arrival-pair-manifest/1",
        "scenario_id": scenario_id,
        "seed_variant": seed_variant,
        "split": "development",
        "control_event_tape_id": control["event_tape_id"],
        "treatment_event_tape_id": treatment["event_tape_id"],
        "common_tape": control["event_tape"],
        "event_identity_time_kind_skeleton_common": common_skeleton == treatment_skeleton,
        "difference_disclosure": "Only the four environment_perturbation strength fields differ; event IDs, times, kind, 2x2 patch, task arrival, C1 base, and seed are shared.",
        "control_physical_strength": {key: control["event_tape"][1][key] for key in
                                      ("wind_vector", "risk_delta", "speed_factor", "energy_per_km_factor")},
        "treatment_physical_strength": {key: treatment["event_tape"][1][key] for key in
                                        ("wind_vector", "risk_delta", "speed_factor", "energy_per_km_factor")},
        "c1_queues_identical": control["queue_plan"] == treatment["queue_plan"],
        "c1_receipts_identical": c1_control == c1_treatment,
        "c1_receipt": c1_control,
    }
    physical = {
        "schema": "s1-arrival-pair-physical-comparison/1",
        "snapshot_time": 11,
        "target_task_id": task_id,
        "patch": patch,
        "segment_endpoints": {"depot": depot["position"], "task": task["position"]},
        "patch_on_actual_depot_task_segment": _segment_intersects_rect(depot["position"], task["position"], patch),
        "same_semantic_alternatives": True,
        "catalog_legal_alternatives_each": len(control_platforms),
        "candidate_pairs": {"control": physical_control, "treatment": physical_treatment, "deltas": deltas},
        "interpretation": "Treatment changes the public mission estimates for both legal alternatives; control keeps neutral speed, energy, wind, and risk settings.",
    }
    if not all(manifest[key] for key in ("c1_queues_identical", "c1_receipts_identical",
                                          "event_identity_time_kind_skeleton_common")):
        raise ValueError("S1 pair control and treatment do not share their declared public inputs")
    if not physical["patch_on_actual_depot_task_segment"]:
        raise ValueError("S1 perturbation patch does not intersect the public depot-task segment")
    if not all(delta["estimated_completion"] > 0 and delta["required_energy"] > 0
               and delta["environmental_risk"] > 0 for delta in deltas.values()):
        raise ValueError("S1 treatment did not raise every expected public mission estimate")
    _write_json(pair_root / "PAIR_MANIFEST.json", manifest)
    _write_json(pair_root / "PAIR_PHYSICAL_COMPARISON.json", physical)
    return {"pair_id": identity, "pair_root": str(pair_root),
            "control": control_summary, "treatment": treatment_summary,
            "manifest": str(pair_root / "PAIR_MANIFEST.json"),
            "physical_comparison": str(pair_root / "PAIR_PHYSICAL_COMPARISON.json")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--scenario-id", default="s1-arrival-pair-final")
    parser.add_argument("--seed-variant", type=int, default=8201)
    parser.add_argument("--max-minutes", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run_pair(args.output_root, scenario_id=args.scenario_id,
                              seed_variant=args.seed_variant,
                              max_minutes=args.max_minutes), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
