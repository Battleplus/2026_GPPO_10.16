"""Freeze reviewable v3 bytes without reusing prior run identities or secrets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".py", ".json", ".md", ".txt", ".ps1", ".cmd"}
DIRECTORIES = ("package", "configs", "protocols", "tools")
EXCLUDED_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox"}


def _excluded_directory(name: str) -> bool:
    lowered = name.lower()
    return name in EXCLUDED_DIRECTORY_NAMES or lowered.startswith("tmp-evidence") or lowered.startswith("smoke-") or lowered.startswith("s0-")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.write_bytes(encode(value))


def selected_files(root: Path) -> list[Path]:
    files = []
    for directory in DIRECTORIES:
        start = root / directory
        if start.is_symlink():
            raise ValueError(f"symlink forbidden in source: {start.relative_to(root)}")
        for current, dirs, names in os.walk(start, topdown=True, followlinks=False):
            current_path = Path(current)
            included_dirs = []
            for name in sorted(dirs):
                child = current_path / name
                if child.is_symlink():
                    raise ValueError(f"symlink forbidden in source: {child.relative_to(root)}")
                if not _excluded_directory(name):
                    included_dirs.append(name)
            dirs[:] = included_dirs
            for name in sorted(names):
                path = current_path / name
                if path.is_symlink():
                    raise ValueError(f"symlink forbidden in source: {path.relative_to(root)}")
                if path.suffix.lower() == ".pyc":
                    continue
                if path.suffix.lower() in SUFFIXES:
                    files.append(path)
    files.append(root / "BASELINE_PROVENANCE.json")
    return sorted(files)


def freeze(stage: str, evidence: list[Path], output: Path | None = None) -> dict:
    identity = "n02-v3-" + stage.lower() + "-" + uuid.uuid4().hex
    release_root = output or ROOT / "releases" / identity
    release_root.mkdir(parents=True, exist_ok=False)
    source = release_root / "source"
    source.mkdir()
    before = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in selected_files(ROOT)}
    for relative, expected in before.items():
        src, dst = ROOT / relative, source / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if digest(dst.read_bytes()) != expected:
            raise ValueError(f"source changed while freezing: {relative}")
    after = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in selected_files(ROOT)}
    if before != after:
        write_json(release_root / "STALE.json", {"before": before, "after": after})
        raise ValueError("source changed during freeze")
    config_relative = "configs/V3_PREREGISTRATION.json"
    manifest = {
        "schema": "n02-v3-source-manifest/1", "release": identity,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage, "files": before,
        "exclusions": ["old checkpoints", "prior identities", "private runtime context", "credentials", "evidence", "bytecode"],
    }
    write_json(source / "SOURCE_MANIFEST.json", manifest)
    manifest_sha = digest((source / "SOURCE_MANIFEST.json").read_bytes())
    checksums = "".join(f"{sha}  {relative}\n" for relative, sha in before.items())
    (source / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8", newline="\n")
    request = {
        "schema": "n02-v3-request/1", "request_id": "request-" + uuid.uuid4().hex,
        "release": identity, "manifest_sha256": manifest_sha,
        "config_sha256": before[config_relative], "scope": stage,
        "execution_permission": "not_a_launch_authorization; independent gates still apply",
    }
    write_json(source / "REQUEST_CANDIDATE.json", request)
    evidence_files = {}
    for index, original in enumerate(evidence):
        original = original.resolve()
        candidates = sorted(p for p in original.rglob("*") if p.is_file()) if original.is_dir() else [original]
        for path in candidates:
            if path.is_symlink():
                raise ValueError("evidence symlink forbidden")
            relative = Path(f"input-{index:02d}") / (path.relative_to(original) if original.is_dir() else path.name)
            dst = release_root / "evidence" / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            raw = path.read_bytes()
            dst.write_bytes(raw)
            evidence_files[relative.as_posix()] = digest(raw)
            if path.read_bytes() != raw:
                raise ValueError("evidence changed while copying")
    write_json(release_root / "EVIDENCE_MANIFEST.json", {
        "schema": "n02-v3-evidence-manifest/1", "release": identity,
        "source_manifest_sha256": manifest_sha, "files": evidence_files,
    })
    result = {"release": identity, "review_root": str(release_root), "manifest_sha256": manifest_sha,
              "source_file_count": len(before), "evidence_file_count": len(evidence_files),
              "status": "FROZEN_PENDING_INDEPENDENT_REVIEW"}
    write_json(release_root / "FREEZE_RECEIPT.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=["S0", "S1", "S2", "S3", "final"])
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze(args.stage, args.evidence, args.output), ensure_ascii=True))


if __name__ == "__main__":
    main()
