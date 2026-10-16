from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "PUBLIC_ARCHIVE_INVENTORY.json"
SIDECAR = ROOT / "PUBLIC_ARCHIVE_INVENTORY.sha256"
EXCLUDED = {"PUBLIC_ARCHIVE_INVENTORY.json", "PUBLIC_ARCHIVE_INVENTORY.sha256"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify() -> list[str]:
    errors: list[str] = []
    inventory_bytes = INVENTORY.read_bytes()
    expected_inventory_hash = SIDECAR.read_text(encoding="ascii").split()[0]
    if hashlib.sha256(inventory_bytes).hexdigest() != expected_inventory_hash:
        errors.append("inventory SHA-256 sidecar mismatch")
    inventory = json.loads(inventory_bytes)
    expected: dict[str, dict] = {}
    for item in inventory.get("files", []):
        name = item.get("path", "")
        rel = PurePosixPath(name)
        if not name or rel.is_absolute() or ".." in rel.parts or name in EXCLUDED:
            errors.append(f"invalid inventory path: {name!r}")
            continue
        expected[name] = item
    if inventory.get("file_count") != len(expected):
        errors.append("inventory file_count does not match its file entries")
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.relative_to(ROOT).as_posix() not in EXCLUDED
    }
    for name in sorted(expected.keys() - actual):
        errors.append(f"missing: {name}")
    for name in sorted(actual - expected.keys()):
        errors.append(f"unlisted: {name}")
    for name in sorted(expected.keys() & actual):
        path = ROOT.joinpath(*PurePosixPath(name).parts)
        item = expected[name]
        if path.stat().st_size != item.get("size_bytes"):
            errors.append(f"size mismatch: {name}")
        if sha256(path) != item.get("public_sha256"):
            errors.append(f"SHA-256 mismatch: {name}")
    return errors


if __name__ == "__main__":
    failures = verify()
    if failures:
        print("PUBLIC SNAPSHOT INVALID")
        print("\n".join(failures))
        sys.exit(1)
    print("PUBLIC SNAPSHOT VERIFIED")
