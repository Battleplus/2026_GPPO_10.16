#!/usr/bin/env python3
"""Replay public-stage baseline artifacts using the original audit_data oracle.

This tool verifies the staged archive byte-for-byte, reconstructs labeled JSONL
exports, and invokes the supplied original audit module. It does not alter the
stage or any scientific source files. The report is written to a new path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class ReplayError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayError(f"cannot read {label}: {path}: {exc}") from exc


def safe_stage_path(stage: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ReplayError(f"{label} must be a non-empty relative path")
    # Stage paths use POSIX separators in the archive contract on every OS.
    pure = PurePosixPath(raw)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise ReplayError(f"unsafe relative path in {label}: {raw!r}")
    if "\\" in raw or (len(raw) >= 2 and raw[1] == ":"):
        raise ReplayError(f"unsafe platform path in {label}: {raw!r}")
    candidate = stage.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(stage.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReplayError(f"{label} escapes stage or is missing: {raw!r}") from exc
    # Reject symlinks anywhere in the path, even if they resolve inside stage.
    cursor = stage
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReplayError(f"symlink is not allowed in {label}: {raw!r}")
    if not resolved.is_file():
        raise ReplayError(f"{label} is not a file: {raw!r}")
    return resolved


def verify_archive(stage: Path) -> dict[str, Any]:
    inventory_path = safe_stage_path(stage, "PUBLIC_ARCHIVE_INVENTORY.json", "inventory")
    inventory = load_json(inventory_path, "public archive inventory")
    if not isinstance(inventory, dict):
        raise ReplayError("public archive inventory must be a JSON object")
    inventory_hash_path = safe_stage_path(
        stage, "PUBLIC_ARCHIVE_INVENTORY.sha256", "inventory checksum"
    )
    expected_inventory_hash = inventory_hash_path.read_text(encoding="ascii").strip().split()[0]
    actual_inventory_hash = sha256_file(inventory_path)
    if expected_inventory_hash.lower() != actual_inventory_hash:
        raise ReplayError("PUBLIC_ARCHIVE_INVENTORY.json SHA256 mismatch")
    files = inventory.get("files")
    if not isinstance(files, list):
        raise ReplayError("inventory.files must be a list")
    if inventory.get("file_count") != len(files):
        raise ReplayError("inventory file_count does not match files list")
    expected_paths: set[str] = set()
    verified: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ReplayError("inventory file entries must be objects")
        rel = entry.get("path")
        if rel in expected_paths:
            raise ReplayError(f"duplicate inventory path: {rel!r}")
        expected_paths.add(rel)
        file_path = safe_stage_path(stage, rel, "inventory path")
        actual_size = file_path.stat().st_size
        actual_sha = sha256_file(file_path)
        if entry.get("bytes") != actual_size:
            raise ReplayError(f"size mismatch for {rel!r}")
        if entry.get("exported_sha256") != actual_sha:
            raise ReplayError(f"SHA256 mismatch for {rel!r}")
        verified.append({"path": rel, "bytes": actual_size, "sha256": actual_sha})
    actual_paths: set[str] = set()
    for root, dirs, names in os.walk(stage, followlinks=False):
        root_path = Path(root)
        for directory in dirs:
            if (root_path / directory).is_symlink():
                raise ReplayError(f"symlink directory in public stage: {root_path / directory}")
        for name in names:
            path = root_path / name
            if path.is_symlink():
                raise ReplayError(f"symlink file in public stage: {path}")
            rel = path.relative_to(stage).as_posix()
            if rel not in ("PUBLIC_ARCHIVE_INVENTORY.json", "PUBLIC_ARCHIVE_INVENTORY.sha256"):
                actual_paths.add(rel)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unlisted = sorted(actual_paths - expected_paths)
        raise ReplayError(f"inventory exact-file-set mismatch; missing={missing}, unlisted={unlisted}")
    return {
        "inventory_path": str(inventory_path),
        "inventory_sha256": actual_inventory_hash,
        "file_count": len(verified),
        "files": verified,
    }


def reconstruct_label(stage: Path, manifest: Mapping[str, Any], label: str) -> tuple[bytes, dict[str, Any]]:
    entries = manifest.get("jsonl")
    if not isinstance(entries, list):
        raise ReplayError("REPRODUCTION_ARTIFACT_MANIFEST.json jsonl must be a list")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("label") == label]
    if len(matches) != 1:
        raise ReplayError(f"expected exactly one JSONL manifest entry for {label!r}, found {len(matches)}")
    entry = matches[0]
    chunks = entry.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ReplayError(f"JSONL entry {label!r} must contain chunks")
    if entry.get("chunk_count") != len(chunks):
        raise ReplayError(f"chunk_count mismatch for {label!r}")
    payload = bytearray()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise ReplayError(f"invalid chunk entry for {label!r}")
        path = safe_stage_path(stage, chunk.get("public_path"), f"{label} chunk")
        data = path.read_bytes()
        if chunk.get("bytes") != len(data):
            raise ReplayError(f"chunk size mismatch: {chunk.get('public_path')!r}")
        if chunk.get("sha256") != hashlib.sha256(data).hexdigest():
            raise ReplayError(f"chunk SHA256 mismatch: {chunk.get('public_path')!r}")
        payload.extend(data)
    result = bytes(payload)
    if hashlib.sha256(result).hexdigest() != entry.get("exported_sha256"):
        raise ReplayError(f"reconstructed exported SHA256 mismatch for {label!r}")
    original_sha = entry.get("original_sha256")
    if (
        not isinstance(original_sha, str)
        or len(original_sha) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in original_sha)
    ):
        raise ReplayError(f"invalid original_sha256 for {label!r}")
    return result, {"label": label, "sha256": hashlib.sha256(result).hexdigest(), "bytes": len(result)}


def import_audit_data(script: Path):
    oracle_dir = str(script.parent)
    if oracle_dir not in sys.path:
        sys.path.insert(0, oracle_dir)
    spec = importlib.util.spec_from_file_location("original_public_audit", script)
    if spec is None or spec.loader is None:
        raise ReplayError(f"cannot import audit module: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    audit = getattr(module, "audit_data", None)
    if not callable(audit):
        raise ReplayError(f"original audit module has no callable audit_data: {script}")
    return audit


def jsonl_objects(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReplayError(f"{label} JSONL is not UTF-8") from exc
    objects: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplayError(f"invalid {label} JSONL at line {number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReplayError(f"{label} JSONL line {number} must contain an object")
        objects.append(value)
    return objects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path, help="evaluation manifest in public stage")
    parser.add_argument("--oracle", required=True, type=Path, help="independent_baseline_oracle.py in public stage")
    parser.add_argument("--actions-label", default="evaluation-actions")
    parser.add_argument("--episodes-label", default="evaluation-episodes")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        stage = args.stage.resolve(strict=True)
        if not stage.is_dir():
            raise ReplayError("--stage must be a directory")
        manifest_path = safe_stage_path(stage, args.manifest.as_posix(), "evaluation manifest")
        oracle_path = safe_stage_path(stage, args.oracle.as_posix(), "oracle")
        archive = verify_archive(stage)
        artifact_manifest_path = safe_stage_path(stage, "REPRODUCTION_ARTIFACT_MANIFEST.json", "artifact manifest")
        artifact_manifest = load_json(artifact_manifest_path, "reproduction artifact manifest")
        if not isinstance(artifact_manifest, dict):
            raise ReplayError("reproduction artifact manifest must be a JSON object")
        manifest_sha = sha256_file(manifest_path)
        oracle_sha = sha256_file(oracle_path)
        manifest_data = load_json(manifest_path, "evaluation manifest")
        if not isinstance(manifest_data, dict):
            raise ReplayError("evaluation manifest must be a JSON object")
        actions_data, actions_info = reconstruct_label(stage, artifact_manifest, args.actions_label)
        episodes_data, episodes_info = reconstruct_label(stage, artifact_manifest, args.episodes_label)
        audit_data = import_audit_data(oracle_path)
        result = audit_data(
            jsonl_objects(actions_data, "actions"),
            jsonl_objects(episodes_data, "episodes"),
            manifest_data,
        )
        if not isinstance(result, dict):
            raise ReplayError("audit_data must return a JSON-serializable result object")
        status = str(result.get("status", "")).upper()
        if status != "PASS" or not isinstance(result.get("mismatch"), list) or not isinstance(result.get("missing"), list):
            raise ReplayError("public replay oracle report must contain status PASS and mismatch/missing lists")
        if result["mismatch"] or result["missing"]:
            raise ReplayError(f"public replay audit failed requirements: mismatch={result['mismatch']!r}, missing={result['missing']!r}")
        report = {
            "schema": "n02-public-archive-replay-report/1",
            "scope": "simulated_public_evidence_only",
            "archive": archive,
            "evaluation_manifest": {"path": str(manifest_path), "sha256": manifest_sha},
            "oracle": {"path": str(oracle_path), "sha256": oracle_sha},
            "reconstructed": {"actions": actions_info, "episodes": episodes_info},
            "oracle_report": result,
            "status": "PASS",
        }
        output = args.report.resolve()
        try:
            output.relative_to(stage)
        except ValueError:
            pass
        else:
            raise ReplayError("report must be written outside the public stage")
        if output.exists():
            raise ReplayError(f"report path already exists; refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (ReplayError, OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
