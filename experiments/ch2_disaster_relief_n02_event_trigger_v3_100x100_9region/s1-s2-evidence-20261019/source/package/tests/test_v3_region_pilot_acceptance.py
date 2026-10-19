from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from region_pilot import _parent_paired_metadata, run_pilot
from region_pilot_acceptance import EXPECTED_VARIANTS, build_acceptance_report
from region_scenarios import build_scenario

WORK_ROOT = Path(__file__).resolve().parents[3] / "n02_v3_runtime_probe_20261019" / "s2-implementation" / "f91970c7-90cd-4585-b68e-bee7c3082b90" / "unit-tests"


def _case_dir() -> Path:
    path = WORK_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


def _summary(parent_id: str) -> dict:
    metric = lambda value: {"value": value, "valid": True, "denominator": 1}
    return {
        "parent_id": parent_id,
        "global_utility": 2.5,
        "on_time_rate": 0.75,
        "operational_dispatch_count": 1,
        "communication_message_count": 2,
        "environment_metrics": {
            "energy_used": 4.0,
            "safety_risk": 0.0,
            "task_switch_count": 0,
            "reward_component_totals": {"completion": 2.5},
            "metrics": {
                "global_utility": metric(2.5),
                "on_time_rate": metric(0.75),
                "energy_used": metric(4.0),
                "safety_risk": metric(0.0),
            },
        },
    }


def _transition(parent_id: str, *, legal: bool = True) -> dict:
    return {
        "parent_id": parent_id,
        "candidates": [{"legal": legal}],
        "candidate_index": 0,
        "observation": {
            "tasks": [{"id": "t1", "region_id": "r00"}],
            "platforms": [{"id": "p1", "region_id": "r00"}],
        },
        "affected_scope": {"affected_region_ids": ["r00"]},
        "assignment_before": {"t1": "p1"},
        "assignment_after": {"t1": "p1"},
        "queues_before": {"p1": ["t1"]},
        "queues_after": {"p1": ["t1"]},
        "executed_action": {"scope": "NOOP", "noop": True},
        "effective_reconstruction_count": 0,
        "raw_events": [],
    }


def _fixture(tmp_path: Path, *, illegal_parent: str | None = None) -> dict:
    metadata = []
    variants = {}
    parents = [(f"train-{index}", "train") for index in range(4)] + [
        (f"dev-{index}", "development") for index in range(2)
    ]
    for parent_id, split in parents:
        metadata.append({
            "parent_id": parent_id,
            "scenario_id": parent_id,
            "split": split,
            "event_tape_id": f"tape-{parent_id}",
            "initial_owner_queue_sha256": f"owners-{parent_id}",
            "public_reset_prefix_sha256": f"reset-{parent_id}",
            "scenario_wrapper_sha256": f"wrapper-{parent_id}",
            "actor_initialization_sha256_by_variant": {variant: "actor-init" for variant in EXPECTED_VARIANTS},
        })
    for variant in EXPECTED_VARIANTS:
        seed_root = tmp_path / variant / "seed_8201"
        seed_root.mkdir(parents=True)
        train_rows = []
        training_summaries = []
        development_summaries = []
        for parent_id, split in parents:
            row = _transition(parent_id, legal=parent_id != illegal_parent)
            if split == "train":
                train_rows.append(row)
                training_summaries.append(_summary(parent_id))
            else:
                (seed_root / f"development_{parent_id}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
                artifact = {
                    "schema": "n02-v3-s2-development-raw-trajectory/1",
                    "parent_id": parent_id,
                    "variant": variant,
                    "event_tape_id": f"tape-{parent_id}",
                    "actor_initialization_sha256": "actor-init",
                    "trajectory": {"parent_id": parent_id, "steps": [row]},
                }
                (seed_root / f"development_{parent_id}_trajectory.json").write_text(
                    json.dumps(artifact), encoding="utf-8"
                )
                development_summaries.append(_summary(parent_id))
        (seed_root / "rollouts.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in train_rows), encoding="utf-8"
        )
        variants[variant] = {
            "8201": {
                "training": {"initial_actor_digest": "actor-init", "episodes": training_summaries},
                "development": development_summaries,
            }
        }
    return {"paired_parent_metadata": metadata, "variants": variants}


def test_paired_parent_metadata_binds_tapes_owner_queues_and_actor_init() -> None:
    scenarios = [build_scenario(scenario_id="p1", split="train", condition="new_arrival", seed_variant=8201)]
    result = {
        "variants": {
            variant: {"8201": {"training": {"initial_actor_digest": "same-init"}}}
            for variant in EXPECTED_VARIANTS
        }
    }
    row = _parent_paired_metadata(scenarios, result)[0]
    assert row["event_tape_id"] == scenarios[0]["event_tape_id"]
    assert row["initial_owner_queue_sha256"]
    assert row["public_reset_prefix_sha256"]
    assert row["scenario_wrapper_sha256"]
    assert set(row["actor_initialization_sha256_by_variant"].values()) == {"same-init"}


def test_acceptance_recomputes_paired_metric_legality_and_local_change_counts() -> None:
    tmp_path = _case_dir()
    result = _fixture(tmp_path)
    report = build_acceptance_report(result, tmp_path)
    assert report["status"] == "PASS_DATA_CONTRACT_ONLY"
    assert report["split_counts"] == {"train": 4, "development": 2}
    dev_pair = next(row for row in report["pairs"] if row["split"] == "development")
    for variant in EXPECTED_VARIANTS:
        evidence = dev_pair["variants"][variant]
        assert evidence["metrics"]["direct"] == {
            "global_utility": 2.5, "on_time_rate": 0.75, "energy_used": 4.0, "safety_risk": 0.0
        }
        assert evidence["rollout"]["selected_candidate_legal_count"] == 1
        assert evidence["rollout"]["legal_candidate_count"] == 1
        assert evidence["rollout"]["local_owner_change_count"] == 0
        assert evidence["rollout"]["local_queue_reorder_count"] == 0
        assert evidence["raw_trajectory_sha256"]
        assert evidence["metric_gaps"] == []


def test_acceptance_fails_when_any_selected_action_was_illegal() -> None:
    tmp_path = _case_dir()
    report = build_acceptance_report(_fixture(tmp_path, illegal_parent="train-0"), tmp_path)
    assert report["status"] == "FAIL_DATA_CONTRACT"
    assert "train-0.Event-G.selected_action_legality" in report["required_gaps"]


def test_pilot_rejects_cli_device_mismatch_before_creating_output() -> None:
    tmp_path = _case_dir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"runtime": {"device": "cuda:0"}, "ppo": {"device": "cuda:0"}}), encoding="utf-8")
    output = tmp_path / "must-not-exist"
    with patch("region_pilot.torch.cuda.is_available", return_value=True):
        with pytest.raises(ValueError, match="V3_S2_DEVICE_CLI_CONFIG_MISMATCH"):
            run_pilot(output, config, device_override="cuda:1")
    assert not output.exists()


def test_pilot_rejects_cpu_without_creating_output() -> None:
    tmp_path = _case_dir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"runtime": {"device": "cpu"}, "ppo": {"device": "cpu"}}), encoding="utf-8")
    output = tmp_path / "must-not-exist"
    with patch("region_pilot.torch.cuda.is_available", return_value=False):
        with pytest.raises(RuntimeError, match="V3_S2_CUDA_REQUIRED_NO_CPU_FALLBACK"):
            run_pilot(output, config)
    assert not output.exists()
