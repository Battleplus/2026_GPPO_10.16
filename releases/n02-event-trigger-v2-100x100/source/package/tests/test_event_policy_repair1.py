from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_policy


def _noop_candidate(key: str = "noop") -> dict:
    return {
        "candidate_key": key,
        "candidate_scope": "noop",
        "legal": True,
        "full_environment_action": {
            "action_type": "reconstruct", "scope": "NOOP", "noop": True,
            "queue_operations": [], "dispatches": [],
        },
    }


def _global_candidate(key: str = "global") -> dict:
    return {
        "candidate_key": key,
        "candidate_scope": "global",
        "legal": True,
        "full_environment_action": {
            "action_type": "reconstruct", "scope": "GLOBAL_REPLAN", "noop": False,
            "queue_operations": [], "dispatches": [{"platform_id": "u1", "task_id": "t1"}],
        },
    }


def test_empty_public_impact_does_not_promote_local_fallback_to_global_replan() -> None:
    candidates = [
        {"candidate_scope": "noop", "full_environment_action": {"noop": True, "scope": "NOOP"}},
        {"candidate_scope": "global", "full_environment_action": {"noop": False, "scope": "GLOBAL_REPLAN"}},
    ]
    affected = {
        "affected_task_ids": [],
        "affected_platform_ids": [],
        "local_eligible": True,
        "global_eligible": False,
        "scope": "LOCAL_REPAIR",
        "reasons": ["connected_local_impact"],
    }
    adjusted, receipt = event_policy._catalog_scope_fallback(affected, candidates)
    assert receipt["status"] == "no_affected_public_entities"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert adjusted["scope"] == "NOOP"
    assert "no_affected_public_entities" in adjusted["reasons"]


def test_empty_public_impact_forces_noop_even_when_global_is_eligible() -> None:
    adjusted, receipt = event_policy._catalog_scope_fallback(
        {
            "affected_task_ids": [], "affected_platform_ids": [],
            "local_eligible": True, "global_eligible": True,
            "scope": "GLOBAL_REPLAN", "reasons": ["strong_event"],
        },
        [_noop_candidate(), _global_candidate()],
    )
    assert receipt["code"] == "no_affected_public_entities"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert adjusted["scope"] == "NOOP"
    assert "no_affected_public_entities" in adjusted["reasons"]


def test_empty_public_impact_policy_catalog_is_noop_only() -> None:
    calls: list[object] = []

    def generate(_env, *, scope, max_candidates):
        calls.append(scope)
        assert scope == "NOOP"
        return [_noop_candidate(), _global_candidate("rogue-global")]

    catalog = event_policy._generate_policy_catalog(
        None, generate, 4,
        {
            "affected_task_ids": [], "affected_platform_ids": [],
            "local_eligible": False, "global_eligible": True,
            "scope": "GLOBAL_REPLAN", "reasons": [],
        },
    )
    assert len(catalog) == 1
    assert event_policy._is_noop(catalog[0])
    assert calls == ["NOOP"]


def test_nonempty_local_scope_stays_local_when_a_local_candidate_exists() -> None:
    adjusted, receipt = event_policy._catalog_scope_fallback(
        {
            "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
            "local_eligible": True, "global_eligible": False,
            "scope": "LOCAL_REPAIR", "reasons": [],
        },
        [
            _noop_candidate(),
            {
                "candidate_key": "local", "candidate_scope": "local", "legal": True,
                "full_environment_action": {
                    "action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                    "queue_operations": [], "dispatches": [{"platform_id": "u1", "task_id": "t1"}],
                },
            },
        ],
    )
    assert receipt["status"] == "available"
    assert adjusted["local_eligible"] is True
    assert adjusted["global_eligible"] is False
    assert adjusted["scope"] == "LOCAL_REPAIR"


def test_nonempty_scope_with_no_eligible_repair_level_forces_noop() -> None:
    adjusted, receipt = event_policy._catalog_scope_fallback(
        {
            "affected_task_ids": ["t1"], "affected_platform_ids": ["u1"],
            "local_eligible": False, "global_eligible": False,
            "scope": "NOOP", "reasons": [],
        },
        [_noop_candidate(), _global_candidate()],
    )
    assert receipt["code"] == "no_eligible_reconstruction_scope"
    assert adjusted["local_eligible"] is False
    assert adjusted["global_eligible"] is False
    assert adjusted["scope"] == "NOOP"
