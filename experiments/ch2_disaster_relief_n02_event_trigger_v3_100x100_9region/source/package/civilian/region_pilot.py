"""S2 v3 Periodic-G/Event-G pilot entry point (GPU only, no world model)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import torch
from torch import nn

try:
    from .event_models import WorldModelEnsemble
    from .event_policy import train_four_variants, verify_policy_checkpoint
    from .region_scenarios import build_scenario_set
except ImportError:
    from event_models import WorldModelEnsemble
    from event_policy import train_four_variants, verify_policy_checkpoint
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


def run_pilot(output: Path, config_path: Path) -> dict[str, Any]:
    config = _json(config_path)
    runtime = dict(config.get("runtime", {}))
    device_name = str(runtime.get("device", config.get("ppo", {}).get("device", "cuda:0")))
    if not device_name.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("V3_S2_CUDA_REQUIRED_NO_CPU_FALLBACK")
    device = torch.device(device_name)
    torch.manual_seed(8201)
    scenarios = build_scenario_set(int(config.get("training_parents", 4)), int(config.get("development_parents", 2)), tape_seed=8201)
    if len(scenarios) != 6 or any(row.get("base_scenario", {}).get("region_contract") != "relief-regions-3x3-v1" for row in scenarios):
        raise ValueError("V3_S2_REGION_SCENARIOS_REQUIRED")
    ppo = dict(config.get("ppo", {})); ppo["device"] = device_name; ppo["seeds"] = [8201]; ppo["variants"] = ["Periodic-G", "Event-G"]
    train_config = {"ppo": ppo, "collection": dict(config.get("collection", {}))}
    threshold = {"threshold": 0.5, "pre_model_threshold": 0.5, "source_split": "train",
                 "source_parent_ids": [row["parent_id"] for row in scenarios if row.get("split") == "train"],
                 "quantile": "train_only", "weights": {}}
    output.mkdir(parents=True, exist_ok=False)
    ensemble = _frozen_placeholder_ensemble(device)
    result = train_four_variants(scenarios, ensemble, threshold, output, train_config)
    result["s2_config"] = config
    result["device"] = device_name
    result["world_model"] = {"enabled": False, "reason": "S2 preregistration disables world model; inert frozen interface is unused by both variants"}
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
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore:
        report = verify_policy_checkpoint(args.restore, device="cuda:0")
        print(json.dumps(report, sort_keys=True))
        return
    result = run_pilot(args.output, args.config)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))


if __name__ == "__main__":
    main()
