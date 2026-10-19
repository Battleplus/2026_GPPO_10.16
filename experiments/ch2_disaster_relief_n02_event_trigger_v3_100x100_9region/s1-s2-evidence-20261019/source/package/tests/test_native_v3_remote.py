from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import runtime_guardian
from runtime_guardian import verify_attempt_binding

WORK_ROOT = Path(__file__).resolve().parents[3] / "n02_v3_runtime_probe_20261019" / "s2-implementation" / "f91970c7-90cd-4585-b68e-bee7c3082b90" / "unit-tests"


def _case_dir() -> Path:
    path = WORK_ROOT / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value: object) -> bytes:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return data


def _binding_fixture(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict, str]:
    source = root / "source"
    evidence = root / "evidence"
    source.mkdir()
    evidence.mkdir()
    (source / "configs").mkdir()
    config = {"runtime": {"device": "cuda:0", "cuda_visible_devices": "1", "physical_gpu_index": 1}}
    prereg = {"S2": {"cpu_training_fallback": False}}
    config_bytes = _write(source / "configs" / "V3_PILOT_CONFIG.json", config)
    prereg_bytes = _write(source / "configs" / "V3_PREREGISTRATION.json", prereg)
    manifest = {"release": "n02-v3-s2-unit", "files": {
        "configs/V3_PILOT_CONFIG.json": _sha(config_bytes),
        "configs/V3_PREREGISTRATION.json": _sha(prereg_bytes),
    }}
    manifest_bytes = _write(source / "SOURCE_MANIFEST.json", manifest)
    manifest_sha = _sha(manifest_bytes)
    attempt_id, run_id = uuid.uuid4().hex, uuid.uuid4().hex
    evidence_values = {
        "S1_REVIEW.json": {
            "S1": "PASS", "verdict": "PASS", "S2_acceptance": "NOT_RUN",
            "release": "n02-v3-s1-0786bcc9ae87435d813531361edf6c34",
            "source_manifest_sha256": "b8a652b40756dd09db4a0a572b00ed786fc9a89dc5df759baa25e7ea56188f40",
            "evidence_manifest_sha256": "7c86cd18ef1a59edb7e0b823b50f39f5c97e9cc8d720389e125b8c39e630e622",
        },
        "SOL_ENTRY_REPORT.json": {"verdict": "PASS", "S1": "PASS", "source_manifest_sha256": manifest_sha},
        "RUNTIME_PROBE_RECEIPT.json": {
            "status": "FRESH_RUNTIME_PROBE_PASS_ONLY", "selected_physical_gpu_index": 1,
            "probe_native_exit_code": 0, "probe_witness": {"mismatches": {}},
            "formal_run_or_checkpoint_created": False,
        },
    }
    evidence_hashes = {name: _sha(_write(evidence / name, value)) for name, value in evidence_values.items()}
    monkeypatch.setattr(runtime_guardian, "S1_INDEPENDENT_REVIEW_SHA256", evidence_hashes["S1_REVIEW.json"])
    request = {
        "schema": "n02-v3-formal-request/1", "scope": "S2", "release": manifest["release"],
        "manifest_sha256": manifest_sha,
        "config_sha256": _sha(config_bytes), "preregistration_sha256": _sha(prereg_bytes),
        "s1_review_sha256": evidence_hashes["S1_REVIEW.json"],
        "s1_source_manifest_sha256": "b8a652b40756dd09db4a0a572b00ed786fc9a89dc5df759baa25e7ea56188f40",
        "s1_evidence_manifest_sha256": "7c86cd18ef1a59edb7e0b823b50f39f5c97e9cc8d720389e125b8c39e630e622",
        "s1_independent_review_sha256": evidence_hashes["S1_REVIEW.json"],
        "sol_entry_report_sha256": evidence_hashes["SOL_ENTRY_REPORT.json"],
        "runtime_probe_receipt_sha256": evidence_hashes["RUNTIME_PROBE_RECEIPT.json"],
        "execution_permission": "S2_RUN_AUTHORIZED", "attempt_id": attempt_id, "run_id": run_id,
        "one_time_token_id": attempt_id,
    }
    attempt = {"schema": "n02-v3-attempt/1", "attempt_id": attempt_id, "run_id": run_id,
               "release": manifest["release"], "one_time_token_id": attempt_id}
    request_sha = _sha(_write(source / "FORMAL_REQUEST.json", request))
    attempt_sha = _sha(_write(source / "ATTEMPT.json", attempt))
    authorization = {"schema": "n02-v3-authorization-binding/1", "request_sha256": request_sha,
                    "attempt_sha256": attempt_sha, "attempt_id": attempt_id, "run_id": run_id,
                    "release": manifest["release"]}
    authorization_sha = _sha(_write(source / "AUTHORIZATION_BINDING.json", authorization))
    binding = {"schema": "n02-v3-publishing-binding/1", "release": manifest["release"],
               "manifest_sha256": manifest_sha, "attempt_id": attempt_id, "run_id": run_id,
               "generated_files": {"FORMAL_REQUEST.json": request_sha, "ATTEMPT.json": attempt_sha,
                                   "AUTHORIZATION_BINDING.json": authorization_sha},
               "evidence_files": evidence_hashes}
    binding_path = root / "PUBLISHING_BINDING.json"
    _write(binding_path, binding)
    return source, binding_path, manifest, manifest_sha


def test_generated_attempt_binding_requires_exact_reports_and_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _case_dir()
    source, binding_path, manifest, manifest_sha = _binding_fixture(root, monkeypatch)
    request, attempt = verify_attempt_binding(source, binding_path, root / "evidence", manifest, manifest_sha)
    assert request["one_time_token_id"] == attempt["attempt_id"]


def test_attempt_binding_rejects_tampered_generated_request(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _case_dir()
    source, binding_path, manifest, manifest_sha = _binding_fixture(root, monkeypatch)
    (source / "FORMAL_REQUEST.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="FORMAL_PUBLISHING_BINDING_HASH_MISMATCH"):
        verify_attempt_binding(source, binding_path, root / "evidence", manifest, manifest_sha)
