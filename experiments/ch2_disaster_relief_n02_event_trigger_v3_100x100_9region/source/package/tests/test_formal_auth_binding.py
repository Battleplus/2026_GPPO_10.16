from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "civilian"))

from execution_gate import (  # noqa: E402
    AUTHORIZATION_SCHEMA,
    FORMAL_BUDGET,
    FORMAL_SCOPE,
    FORMAL_UPGRADE_SCHEMA,
    CANDIDATE_SCOPE,
    digest_json,
    validate_authorization_document,
)
from package_layout import PACKAGE_RELEASE_ID  # noqa: E402


def _binding() -> dict:
    return {
        "package_release": PACKAGE_RELEASE_ID,
        "release_manifest_sha256": "a" * 64,
        "hash_bundle_sha256": "b" * 64,
        "candidate_request_identity_sha256": "c" * 64,
        "candidate_attempt_identity_sha256": "d" * 64,
        "authorized": False,
        "request_frozen": False,
        "request_scope": CANDIDATE_SCOPE,
        "budget": None,
    }


def _authorization(binding: dict) -> dict:
    attempt_id = "n02-local-formal-auth-binding-test"
    attempt_body = {
        "attempt_id": attempt_id,
        "candidate_attempt_identity_sha256": binding["candidate_attempt_identity_sha256"],
        "candidate_request_identity_sha256": binding["candidate_request_identity_sha256"],
        "release_manifest_sha256": binding["release_manifest_sha256"],
        "hash_bundle_sha256": binding["hash_bundle_sha256"],
    }
    authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "state": "authorized",
        "one_time": True,
        "release_manifest_sha256": binding["release_manifest_sha256"],
        "hash_bundle_sha256": binding["hash_bundle_sha256"],
        "scope": FORMAL_SCOPE,
        "budget": copy.deepcopy(FORMAL_BUDGET),
        "attempt": {
            "id": attempt_id,
            "candidate_identity_sha256": binding["candidate_attempt_identity_sha256"],
            "identity_sha256": digest_json(attempt_body),
        },
        "request": {
            "identity_sha256": binding["candidate_request_identity_sha256"],
            "scope": FORMAL_SCOPE,
            "budget": copy.deepcopy(FORMAL_BUDGET),
        },
        "formal_upgrade": {
            "schema": FORMAL_UPGRADE_SCHEMA,
            "state": "approved",
            "authorized": True,
            "request_frozen": True,
            "candidate_request_identity_sha256": binding["candidate_request_identity_sha256"],
            "candidate_attempt_identity_sha256": binding["candidate_attempt_identity_sha256"],
            "release_manifest_sha256": binding["release_manifest_sha256"],
            "hash_bundle_sha256": binding["hash_bundle_sha256"],
            "scope": FORMAL_SCOPE,
            "budget": copy.deepcopy(FORMAL_BUDGET),
        },
        "preflight": {
            "engineering_id": "n02-local-preflight-test",
            "path": "/tmp/n02-local-preflight-test/preflight_receipt.json",
            "sha256": "e" * 64,
        },
    }
    authorization["authorization_sha256"] = digest_json(authorization)
    return authorization


def _resign(document: dict) -> dict:
    document["authorization_sha256"] = digest_json(
        {key: value for key, value in document.items() if key != "authorization_sha256"}
    )
    return document


def test_candidate_static_binding_accepts_explicit_formal_upgrade() -> None:
    binding = _binding()
    result = validate_authorization_document(_authorization(binding), binding)
    assert result["authorized"] is True
    assert result["request_frozen"] is True
    assert result["request_scope"] == FORMAL_SCOPE
    assert result["budget"] == FORMAL_BUDGET


@pytest.mark.parametrize(
    "field, value",
    [
        ("release_manifest_sha256", "f" * 64),
        ("scope", "n02-v5-wrong-scope"),
    ],
)
def test_formal_upgrade_rejects_hash_or_scope_mismatch(field: str, value: str) -> None:
    binding = _binding()
    authorization = _authorization(binding)
    authorization["formal_upgrade"][field] = value
    if field == "release_manifest_sha256":
        authorization[field] = value
    else:
        authorization[field] = value
        authorization["request"][field] = value
    with pytest.raises(PermissionError):
        validate_authorization_document(_resign(authorization), binding)


def test_formal_upgrade_rejects_budget_mismatch() -> None:
    binding = _binding()
    authorization = _authorization(binding)
    altered_budget = copy.deepcopy(FORMAL_BUDGET)
    altered_budget["ppo_updates"] += 1
    authorization["budget"] = altered_budget
    authorization["request"]["budget"] = altered_budget
    authorization["formal_upgrade"]["budget"] = altered_budget
    with pytest.raises(PermissionError):
        validate_authorization_document(_resign(authorization), binding)


def test_formal_upgrade_rejects_mutated_static_candidate_binding() -> None:
    binding = _binding()
    mutated = dict(binding, authorized=True)
    with pytest.raises(PermissionError):
        validate_authorization_document(_authorization(binding), mutated)
