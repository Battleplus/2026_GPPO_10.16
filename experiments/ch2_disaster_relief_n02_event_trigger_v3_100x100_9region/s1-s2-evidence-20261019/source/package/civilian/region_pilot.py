"""S2 v3 Periodic-G/Event-G pilot entry point (GPU only, no world model)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import torch
from torch import nn

try:
    from .event_models import WorldModelEnsemble
    from .event_policy import train_four_variants, verify_policy_checkpoint
    from .event_trigger import calibrate_threshold
    from .event_environment import EventReliefEnv
    from .region_pilot_acceptance import build_acceptance_report
    from .region_scenarios import build_scenario_set
except ImportError:
    from event_models import WorldModelEnsemble
    from event_policy import train_four_variants, verify_policy_checkpoint
    from event_trigger import calibrate_threshold
    from event_environment import EventReliefEnv
    from region_pilot_acceptance import build_acceptance_report
    from region_scenarios import build_scenario_set


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _frozen_placeholder_ensemble(device: torch.device) -> WorldModelEnsemble:
    """Provide an inert frozen ensemble object for the no-WM S2 policy path."""
    models = [nn.Linear(1, 1, bias=False).to(device).eval() for _ in range(3)]
    for model in models:
        model.requires_grad_(False)
    return WorldModelEnsemble(models=models, metadata=[{"variant": "S2-no-world-model"}] * 3,
                              ensemble_hash="s2-no-world-model")


def _noop_action() -> dict[str, Any]:
    return {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
            "queue_operations": [], "dispatches": []}


def _calibrate_training_threshold(scenarios: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    training_scenarios = [row for row in scenarios if row.get("split") == "train"]
    expected_parent_ids = sorted(str(row["parent_id"]) for row in training_scenarios)
    if len(training_scenarios) != 4 or len(set(expected_parent_ids)) != 4:
        raise ValueError("V3_S2_TRAINING_PARENT_CALIBRATION_SET")

    sequences = []
    for scenario in training_scenarios:
        env = EventReliefEnv(scenario)
        observation = env.reset()
        observations = [observation]
        for _ in range(int(scenario.get("horizon", 60))):
            observation, _, terminated, truncated, _ = env.step(_noop_action())
            observations.append(observation)
            if terminated or truncated:
                break
        sequences.append({
            "parent_id": str(scenario["parent_id"]),
            "split": "train",
            "observations": observations,
            "event_tape_id": scenario["event_tape_id"],
        })

    trigger = dict(config.get("trigger", {}))
    calibration_config = {
        "quantile": float(trigger.get("threshold_quantile", 0.75)),
        "hysteresis_margin": float(trigger.get("hysteresis_margin", 0.05)),
        "delta_min": int(trigger.get("delta_min", 4)),
        "weights": dict(trigger.get("weights", {"d_state": 0.35, "d_degradation": 0.30, "d_margin": 0.25, "d_uncertainty": 0.10})),
    }
    manifest = calibrate_threshold(sequences, calibration_config)
    manifest.update({
        "source_split": "train",
        "source_parent_ids": expected_parent_ids,
        "pre_model_threshold": float(manifest["threshold"]),
        "world_model_used": False,
        "wm_summaries_used": False,
        "initial_threshold_sha256": manifest["training_input_sha256"],
        "runtime_trigger_config": {
            "delta_min": int(calibration_config["delta_min"]),
            "periodic_interval": int(trigger.get("periodic_interval", calibration_config["delta_min"])),
            "warmup_steps": int(trigger.get("warmup_steps", 0)),
            "persistence_steps": int(trigger.get("persistence_steps", 1)),
            "hysteresis_margin": float(calibration_config["hysteresis_margin"]),
            "threshold": float(manifest["threshold"]),
            "threshold_high": float(manifest["threshold_high"]),
            "threshold_low": float(manifest["threshold_low"]),
            "weights": dict(calibration_config["weights"]),
        },
    })
    return manifest


def _parent_paired_metadata(scenarios: list[dict[str, Any]], result: dict[str, Any]) -> list[dict[str, Any]]:
    variants = result.get("variants", {})
    actor_digests = {
        variant: rows.get("8201", {}).get("training", {}).get("initial_actor_digest")
        for variant, rows in variants.items()
    }
    if len(actor_digests) != 2 or len(set(actor_digests.values())) != 1 or not next(iter(actor_digests.values()), None):
        raise ValueError("V3_S2_PAIRED_ACTOR_INITIALIZATION_IDENTITY")
    metadata = []
    for scenario in scenarios:
        snapshot = scenario.get("base_scenario", {}).get("chapter1_snapshot", {})
        queue_plan = scenario.get("queue_plan", {})
        reset_observation = EventReliefEnv(scenario).reset()
        reset_prefix = reset_observation.get("chapter1_snapshot")
        if not isinstance(reset_prefix, dict):
            raise ValueError("V3_S2_PUBLIC_C1_RESET_PREFIX_REQUIRED")
        identity_payload = {"snapshot": snapshot, "queue_plan": queue_plan}
        owner_queue_sha256 = hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        public_reset_prefix_sha256 = hashlib.sha256(
            json.dumps(reset_prefix, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        scenario_wrapper_sha256 = hashlib.sha256(
            json.dumps(scenario, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        metadata.append({
            "parent_id": str(scenario["parent_id"]),
            "scenario_id": str(scenario.get("scenario_id", scenario["parent_id"])),
            "split": str(scenario["split"]),
            "event_tape_id": str(scenario["event_tape_id"]),
            "initial_owner_queue_sha256": owner_queue_sha256,
            "public_reset_prefix_sha256": public_reset_prefix_sha256,
            "scenario_wrapper_sha256": scenario_wrapper_sha256,
            "actor_initialization_sha256_by_variant": dict(actor_digests),
        })
    return metadata


def run_pilot(output: Path, config_path: Path, *, device_override: str | None = None) -> dict[str, Any]:
    config = _json(config_path)
    runtime = dict(config.get("runtime", {}))
    configured_device = str(runtime.get("device", config.get("ppo", {}).get("device", "cuda:0")))
    device_name = str(device_override or configured_device)
    if device_name != configured_device or str(config.get("ppo", {}).get("device", configured_device)) != device_name:
        raise ValueError("V3_S2_DEVICE_CLI_CONFIG_MISMATCH")
    if not device_name.startswith("cuda:") or not torch.cuda.is_available():
        raise RuntimeError("V3_S2_CUDA_REQUIRED_NO_CPU_FALLBACK")
    device = torch.device(device_name)
    if device.index is not None and device.index >= torch.cuda.device_count():
        raise RuntimeError("V3_S2_CONFIGURED_CUDA_DEVICE_UNAVAILABLE")
    torch.cuda.set_device(device)
    torch.manual_seed(8201)
    scenarios = build_scenario_set(int(config.get("training_parents", 4)), int(config.get("development_parents", 2)), tape_seed=8201)
    if len(scenarios) != 6 or any(row.get("base_scenario", {}).get("region_contract") != "relief-regions-3x3-v1" for row in scenarios):
        raise ValueError("V3_S2_REGION_SCENARIOS_REQUIRED")
    ppo = dict(config.get("ppo", {})); ppo["device"] = device_name; ppo["seeds"] = [8201]; ppo["variants"] = ["Periodic-G", "Event-G"]
    train_config = {"ppo": ppo, "collection": dict(config.get("collection", {}))}
    threshold = _calibrate_training_threshold(scenarios, config)
    train_config["trigger"] = dict(threshold["runtime_trigger_config"])
    output.mkdir(parents=True, exist_ok=False)
    ensemble = _frozen_placeholder_ensemble(device)
    result = train_four_variants(scenarios, ensemble, threshold, output, train_config)
    result["s2_config"] = config
    result["device"] = device_name
    result["paired_parent_metadata"] = _parent_paired_metadata(scenarios, result)
    result["world_model"] = {"enabled": False, "reason": "S2 preregistration disables world model; inert frozen interface is unused by both variants"}
    for variant, seeds in result.get("variants", {}).items():
        seed_result = seeds.get("8201", {})
        actor_digest = seed_result.get("training", {}).get("initial_actor_digest")
        for summary in seed_result.get("development", []):
            trajectory = summary.pop("raw_trajectory", None)
            if not isinstance(trajectory, dict):
                raise ValueError("V3_S2_DEVELOPMENT_RAW_TRAJECTORY_REQUIRED")
            parent_id = str(summary["parent_id"])
            artifact = {
                "schema": "n02-v3-s2-development-raw-trajectory/1",
                "variant": variant,
                "seed": 8201,
                "parent_id": parent_id,
                "event_tape_id": next(row["event_tape_id"] for row in scenarios if str(row["parent_id"]) == parent_id),
                "actor_initialization_sha256": actor_digest,
                "trajectory": trajectory,
            }
            trajectory_path = output / variant / "seed_8201" / f"development_{parent_id}_trajectory.json"
            trajectory_bytes = (json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
            trajectory_path.write_bytes(trajectory_bytes)
            summary["raw_trajectory_path"] = trajectory_path.relative_to(output).as_posix()
            summary["raw_trajectory_sha256"] = hashlib.sha256(trajectory_bytes).hexdigest()
    acceptance = build_acceptance_report(result, output)
    result["acceptance"] = acceptance
    (output / "S2_ACCEPTANCE_REPORT.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    engineering_gate = acceptance.get("engineering_gate")
    if not isinstance(engineering_gate, dict):
        raise ValueError("V3_S2_ENGINEERING_GATE_REPORT_REQUIRED")
    (output / "S2_ENGINEERING_GATE.json").write_text(
        json.dumps(engineering_gate, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    result_path = output / "S2_PILOT_RESULT.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    if torch.cuda.is_available():
        torch.cuda.synchronize(device)
    receipt = {
        "schema": "n02-v3-s2-gpu-execution-receipt/1", "status": "complete", "device": device_name,
        "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "policy_parameter_devices": sorted({str(p.device) for variant in result["variants"].values() for seed in variant.values() for p in []}),
        "optimizer_steps": int(result.get("paired_optimizer_updates_per_seed_method", 0)),
        "result_sha256": __import__("hashlib").sha256(result_path.read_bytes()).hexdigest(),
    }
    # Derive device evidence from the serialized training records.
    receipt["policy_parameter_devices"] = sorted({device for variant in result["variants"].values() for row in variant.values() for device in row["training"].get("model_parameter_devices", [])})
    receipt["policy_optimizer_state_devices"] = sorted({device for variant in result["variants"].values() for row in variant.values() for device in row["training"].get("optimizer_state_devices", [])})
    (output / "GPU_EXECUTION_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--device")
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore:
        restore_device = str(args.device or "cuda:0")
        if not restore_device.startswith("cuda:"):
            parser.error("--restore requires an indexed CUDA device, such as cuda:0")
        try:
            device = torch.device(restore_device)
        except (TypeError, RuntimeError) as exc:
            parser.error(f"invalid --device for --restore: {exc}")
        if device.type != "cuda" or device.index is None or device.index < 0:
            parser.error("--restore requires an indexed CUDA device, such as cuda:0")
        if not torch.cuda.is_available():
            raise RuntimeError("V3_S2_CUDA_REQUIRED_NO_CPU_FALLBACK")
        if device.index >= torch.cuda.device_count():
            raise RuntimeError("V3_S2_CONFIGURED_CUDA_DEVICE_UNAVAILABLE")
        report = verify_policy_checkpoint(args.restore, device=restore_device)
        print(json.dumps(report, sort_keys=True))
        return
    if args.output is None or args.config is None:
        parser.error("--output and --config are required unless --restore is used")
    result = run_pilot(args.output, args.config, device_override=args.device)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))


if __name__ == "__main__":
    main()
