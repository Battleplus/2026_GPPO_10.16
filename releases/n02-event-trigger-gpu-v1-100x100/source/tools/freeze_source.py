"""Freeze explicit source/config/tool inputs without prior data or credentials."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import uuid


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    inventory = {}
    counts = {"python_ast_files": 0, "json_parsed_files": 0}
    map_contracts = []
    def inspect_maps(value, origin, location="$"):
        if isinstance(value, dict):
            if isinstance(value.get("map"), dict):
                grid = value["map"]
                if "rows" in grid or "cols" in grid:
                    valid = grid.get("rows") == 100 and grid.get("cols") == 100 and grid.get("grid_cells", 10000) == 10000
                    map_contracts.append({"file": origin, "json_path": location + ".map", "rows": grid.get("rows"), "cols": grid.get("cols"), "valid": valid})
                    if not valid:
                        raise ValueError(f"Non-100x100 map in {origin}:{location}.map")
            for key, item in value.items():
                inspect_maps(item, origin, location + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                inspect_maps(item, origin, location + f"[{index}]")
    for directory in ("package", "configs", "protocols", "tools"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Source symlink is not allowed: {path.relative_to(root)}")
            if path.is_dir():
                if path.name == "__pycache__":
                    raise ValueError(f"Source bytecode directory is not allowed: {path.relative_to(root)}")
                continue
            if path.is_symlink() or path.suffix in {".pyc", ".pyo", ".pt", ".sqlite", ".db"} or "__pycache__" in path.parts:
                raise ValueError(f"Unsupported source file: {path.relative_to(root)}")
            if path.name.startswith("."):
                raise ValueError(f"Unexpected hidden source file: {path.relative_to(root)}")
            raw = path.read_bytes()
            if path.suffix == ".py":
                ast.parse(raw, filename=str(path))
                counts["python_ast_files"] += 1
            if path.suffix == ".json":
                parsed = json.loads(raw)
                counts["json_parsed_files"] += 1
                inspect_maps(parsed, path.relative_to(root).as_posix())
            inventory[path.relative_to(root).as_posix()] = digest(raw)
    provenance = json.loads((root / "protocols/BASELINE_PROVENANCE.json").read_bytes())
    gpu_modifications = json.loads((root / "protocols/GPU_BRANCH_MODIFICATIONS.json").read_bytes())
    allowed_baseline_changes = gpu_modifications.get("baseline_derived_changes", {})
    baseline_mismatches = []
    for relative, expected in provenance["files"].items():
        observed = inventory.get("package/" + relative)
        if observed == expected:
            continue
        declared = allowed_baseline_changes.get(relative)
        if not isinstance(declared, dict) or declared.get("baseline_sha256") != expected:
            baseline_mismatches.append(relative)
    if baseline_mismatches:
        raise ValueError(f"Archived baseline bytes changed: {baseline_mismatches}")
    manifest = {"schema": "n02-event-source-manifest/1", "release": "n02-event-trigger-gpu-v1-" + uuid.uuid4().hex, "baseline_commit": "1ca6ddc0df21bc0c54e7ff8cb5ac7a6960229cba", "execution_profile": "cuda-training-cpu-environment", "files": inventory}
    manifest_raw = canonical(manifest)
    config_raw = (root / "configs/EVENT_TRIGGER_CONFIG.json").read_bytes()
    request = {"schema": "n02-event-research-request/1", "request_id": "event-gpu-request-" + uuid.uuid4().hex, "release": manifest["release"], "manifest_sha256": digest(manifest_raw), "config_sha256": digest(config_raw), "user_specification_sha256": inventory["protocols/USER_SPECIFICATION.md"], "scope": "Full first-round event-trigger V1, M0-M5; six parents, 100x100, three seeds, four PPO methods; world model and PPO train on CUDA device cuda:0, environment remains CPU", "fresh_initialization": True, "old_tokens_authorizations_attempts_runs_checkpoints_reused": False, "runtime": json.loads(config_raw)["runtime"]}
    (root / "SOURCE_MANIFEST.json").write_bytes(manifest_raw)
    (root / "SHA256SUMS.txt").write_text("".join(f"{sha}  {name}\n" for name, sha in sorted(inventory.items())), encoding="ascii")
    (root / "REQUEST.json").write_bytes(canonical(request))
    (root / "LOCAL_STATIC_REPORT.json").write_bytes(canonical({"schema": "n02-event-static-source-report/1", "status": "PASS_STATIC_ONLY", "source_manifest_sha256": digest(manifest_raw), "source_files": len(inventory), **counts, "json_map_contracts": map_contracts, "baseline_files_verified": len(provenance["files"]), "baseline_mismatches": baseline_mismatches, "declared_gpu_branch_modifications": sorted(allowed_baseline_changes), "bytecode_check": "absent", "scope": "AST/JSON/map fields/baseline provenance/source asset hygiene; CUDA tests require the target GPU runtime and Sol review remains independent"}))
    print(json.dumps({"release": manifest["release"], "files": len(inventory), "manifest_sha256": digest(manifest_raw), "request_sha256": digest(canonical(request))}))


if __name__ == "__main__":
    main()
