"""Create a fresh, hash-bound baseline source and data bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


LEGACY_CONTRACT_FIXTURES = (
    "package/civilian/runtime-spec.json",
    "package/civilian/PRIOR_RESOURCE_COST.json",
    "package/civilian/registered_data/input_registry.json",
    "package/civilian/registered_data/data/development/n02-development-carrier_competition-00-f4a66619d2e7d832.json",
    "package/civilian/registered_data/data/train/n02-train-base-00-0b08674536871cd5.json",
    "package/civilian/registered_data/data/train/n02-train-carrier_competition-01-bcda9d83aea81125.json",
    "package/civilian/registered_data/fixtures/causal_allocation_case.json",
    "package/civilian/fixtures/combined.json",
    "package/civilian/fixtures/control.json",
    "package/civilian/fixtures/energy_change.json",
    "package/civilian/fixtures/external_commitment.json",
    "package/civilian/fixtures/failure.json",
    "package/civilian/fixtures/report_delay.json",
    "package/civilian/fixtures/stock_loss.json",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _bundle_inputs(root: Path) -> list[tuple[Path, str, str]]:
    inputs: dict[str, tuple[Path, str]] = {}

    def add(path: Path, kind: str = "source", relative: str | None = None) -> None:
        if not path.is_file():
            raise ValueError(f"BASELINE_BUNDLE_INPUT_MISSING:{path}")
        name = relative or path.relative_to(root).as_posix()
        prior = inputs.get(name)
        if prior and prior[0] != path:
            raise ValueError(f"BASELINE_BUNDLE_PATH_COLLISION:{name}")
        inputs[name] = (path, kind)

    for path in sorted((root / "package" / "civilian").glob("*.py")):
        add(path)

    explicit = [
        "configs/BASELINE_PILOT_CONFIG.json",
        "configs/BASELINE_FORMAL_CONFIG.json",
        "configs/ENVIRONMENT_SPEC.json",
        "configs/EVENT_TRIGGER_CONFIG.json",
        "protocols/BASELINE_COMPARISON_CONTRACT.md",
        "protocols/INDEPENDENT_BASELINE_ORACLE.md",
        "protocols/BASELINE_PROVENANCE.json",
        "protocols/BASELINE_ANALYSIS_RESULT_SCHEMA.md",
        "tools/freeze_baselines.py",
        "tools/baseline_guardian.py",
        "tools/baseline_remote.py",
        "tools/baseline_cuda_smoke.py",
        "tools/analyze_baseline_results.py",
        "tools/gpu_smoke.py",
        "tools/independent_baseline_oracle.py",
        "tools/audit_gate1_replay.py",
        "tools/verify_baseline_pilot.py",
        "RUN_BASELINE.md",
    ]
    for name in explicit:
        add(root / Path(name))

    for name in LEGACY_CONTRACT_FIXTURES:
        add(root / Path(name), kind="legacy-contract-test-fixture")

    for directory in (root / "package" / "tests", root / "tools" / "tests"):
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.suffix == ".py" or "fixtures" in path.relative_to(directory).parts:
                    add(path)

    return [(path, relative, kind) for relative, (path, kind) in sorted(inputs.items())]


def freeze(profile: str, bundle_root: str | Path, repository_root: str | Path | None = None) -> dict:
    if profile not in {"pilot", "formal"}:
        raise ValueError("BASELINE_PROFILE")
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    bundle = Path(bundle_root).resolve()
    if bundle.exists() and any(bundle.iterdir()):
        raise ValueError("BASELINE_BUNDLE_MUST_BE_FRESH")
    bundle.mkdir(parents=True, exist_ok=True)

    config_rel = Path("configs") / f"BASELINE_{profile.upper()}_CONFIG.json"
    config = json.loads((root / config_rel).read_text(encoding="utf-8"))
    if config.get("profile") != profile:
        raise ValueError("BASELINE_CONFIG_PROFILE_MISMATCH")
    configured_r8 = root / config["data_reuse"]["gate1_evidence"]
    portable_r8 = root / "data" / "gate1-r8"
    r8 = configured_r8 if (configured_r8 / "RUN_IDENTITY.json").is_file() else portable_r8
    gate1_identity = json.loads((r8 / "RUN_IDENTITY.json").read_text(encoding="utf-8"))
    if gate1_identity.get("manifest_sha256") != config["data_reuse"]["gate1_freeze_manifest_sha256"]:
        raise ValueError("BASELINE_GATE1_R8_MANIFEST_MISMATCH")

    data_paths = [r8 / config["data_reuse"]["training_samples"],
                  r8 / config["data_reuse"]["development_samples"],
                  r8 / config["data_reuse"]["threshold_manifest"], r8 / "RUN_IDENTITY.json"]
    if r8 == portable_r8:
        source_manifest_path = root / "BASELINE_SOURCE_MANIFEST.json"
        if not source_manifest_path.is_file():
            raise ValueError("BASELINE_PORTABLE_SOURCE_MANIFEST_MISSING")
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        expected_hashes = {row.get("path"): row.get("sha256") for row in source_manifest.get("files", [])
                           if isinstance(row, dict)}
        for source in data_paths:
            relative = source.relative_to(root).as_posix()
            expected_hash = expected_hashes.get(relative)
            if not expected_hash or _sha(source) != expected_hash:
                raise ValueError(f"BASELINE_PORTABLE_DATA_HASH_MISMATCH:{relative}")
    inputs = _bundle_inputs(root)

    records = []
    for source, relative, kind in inputs:
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append({"path": relative, "sha256": _sha(target), "size_bytes": target.stat().st_size, "kind": kind})
    data_records = []
    for source in data_paths:
        if source.name == config["data_reuse"]["training_samples"]:
            relative = "data/gate1-r8/M2_MODEL_SAMPLES.jsonl"
        elif source.name == config["data_reuse"]["development_samples"]:
            relative = "data/gate1-r8/M2_DEVELOPMENT_MODEL_SAMPLES.jsonl"
        elif source.name == "RUN_IDENTITY.json":
            relative = "data/gate1-r8/RUN_IDENTITY.json"
        else:
            relative = "data/gate1-r8/THRESHOLD_MANIFEST.json"
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        row = {"path": relative, "sha256": _sha(target), "size_bytes": target.stat().st_size, "kind": "accepted-r8-data"}
        records.append(row)
        data_records.append(row)

    config_target = bundle / config_rel
    source_manifest = {
        "schema": "n02-baseline-source-manifest/1", "profile": profile,
        "gate1_r8_manifest_sha256": gate1_identity["manifest_sha256"],
        "files": sorted(records, key=lambda row: row["path"]),
    }
    _write(bundle / "BASELINE_SOURCE_MANIFEST.json", source_manifest)
    source_manifest_hash = _sha(bundle / "BASELINE_SOURCE_MANIFEST.json")
    request = {
        "schema": "n02-baseline-request/1", "request_id": f"baseline-{profile}-{uuid.uuid4().hex}",
        "attempt_id": f"baseline-{profile}-attempt-{uuid.uuid4().hex}",
        "created_utc": datetime.now(timezone.utc).isoformat(), "profile": profile,
        "config_path": config_rel.as_posix(), "config_sha256": _sha(config_target),
        "source_manifest_path": "BASELINE_SOURCE_MANIFEST.json", "source_manifest_sha256": source_manifest_hash,
        "gate1_r8_manifest_sha256": gate1_identity["manifest_sha256"],
        "dataset_sha256": {row["path"]: row["sha256"] for row in data_records
                            if row["path"] != "data/gate1-r8/RUN_IDENTITY.json"},
        "gate1_r8_identity_path": "data/gate1-r8/RUN_IDENTITY.json",
        "target_phases": ["freeze-wm", "train", "evaluate"],
        "runtime": config["runtime"],
        "resource_budget": config["resource_budget"],
        "resource_budget_scope": "per_phase",
        "output_namespace": f"n02-baseline-{profile}-{uuid.uuid4().hex}",
    }
    _write(bundle / "BASELINE_REQUEST.json", request)
    return {"status": "complete", "bundle_root": str(bundle), "profile": profile,
            "request_id": request["request_id"], "source_manifest_sha256": source_manifest_hash,
            "file_count": len(records), "dataset_sha256": request["dataset_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("pilot", "formal"), required=True)
    parser.add_argument("--bundle-root", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(freeze(args.profile, args.bundle_root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
