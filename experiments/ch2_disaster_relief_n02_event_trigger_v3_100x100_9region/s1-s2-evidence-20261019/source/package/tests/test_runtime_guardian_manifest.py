from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from runtime_guardian import verify_source_manifest


WORK_ROOT = Path(__file__).resolve().parents[3] / "n02_v3_runtime_probe_20261019" / "s2-implementation" / "f91970c7-90cd-4585-b68e-bee7c3082b90" / "unit-tests"


def _case_dir() -> Path:
    path = WORK_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


def _source_tree(root: Path | None = None) -> Path:
    root = root or _case_dir()
    source = root / "source"
    source.mkdir()
    payload = b"immutable source bytes\n"
    (source / "payload.py").write_bytes(payload)
    manifest = {
        "schema": "test-source-manifest/1",
        "files": {"payload.py": hashlib.sha256(payload).hexdigest()},
    }
    (source / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "REQUEST_CANDIDATE.json").write_text("{}\n", encoding="utf-8")
    (source / "SHA256SUMS.txt").write_text("test\n", encoding="ascii")
    for name in ("FORMAL_REQUEST.json", "ATTEMPT.json", "AUTHORIZATION_BINDING.json"):
        (source / name).write_text("{}\n", encoding="utf-8")
    return source


def test_manifest_verification_checks_bytes_and_complete_inventory() -> None:
    source = _source_tree()
    manifest, digest = verify_source_manifest(source)
    assert manifest["files"].keys() == {"payload.py"}
    assert digest == hashlib.sha256((source / "SOURCE_MANIFEST.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("unexpected", ["omitted.py", "nested/extra.json"])
def test_manifest_verification_rejects_unlisted_source_files(unexpected: str) -> None:
    source = _source_tree()
    path = source / unexpected
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unlisted", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SOURCE_MANIFEST_INVENTORY_MISMATCH"):
        verify_source_manifest(source)


def test_manifest_verification_rejects_source_byte_mismatch() -> None:
    source = _source_tree()
    (source / "payload.py").write_bytes(b"modified\n")
    with pytest.raises(RuntimeError, match="Frozen source mismatch"):
        verify_source_manifest(source)
