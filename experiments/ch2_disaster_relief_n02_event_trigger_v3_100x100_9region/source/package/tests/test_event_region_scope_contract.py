from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from event_environment import EventReliefEnv, _action_within_local_domain
from event_trigger import identify_affected_scope
from region_scenarios import build_scenario


def _noop() -> dict:
    return {
        "action_type": "reconstruct", "scope": "NOOP", "noop": True,
        "queue_operations": [], "dispatches": [],
    }


def test_unowned_v3_arrival_uses_public_coordinator_for_candidate_domain() -> None:
    scenario = build_scenario(scenario_id="scope-arrival", split="development",
                              condition="new_arrival", seed_variant=8201)
    env = EventReliefEnv(scenario)
    observation = env.reset()
    for _ in range(8):
        observation, _, _, _, _ = env.step(_noop())

    coordinator = observation["coordinator_id"]
    arriving = next(row for row in observation["tasks"] if row["id"] == "task-r00-hidden")
    assert arriving["assignee"] is None
    scope = identify_affected_scope(observation, {
        "affected_task_ids": [arriving["id"]], "affected_platform_ids": [],
        "event_details": {"category_count": 1}, "strong_event": False,
    })

    assert scope["local_eligible"] is True
    assert coordinator in scope["affected_platform_ids"]
    assert scope["candidate_platform_ids"]


def test_local_repair_excludes_neighbor_region_platforms_even_if_affected() -> None:
    scenario = build_scenario(scenario_id="scope-local-region", split="development",
                              condition="new_arrival", seed_variant=8202)
    env = EventReliefEnv(scenario)
    observation = env.reset()
    target = next(row for row in observation["tasks"] if row.get("region_id") == "r11")
    owner = target["assignee"]
    same_region = next(row["id"] for row in observation["platforms"]
                       if row.get("region_id") == "r11" and row["id"] != owner)
    neighbor = next(row["id"] for row in observation["platforms"] if row.get("region_id") == "r10")
    scope = {
        "affected_task_ids": [target["id"]],
        "affected_platform_ids": [owner, same_region, neighbor],
        "affected_region_ids": ["r11"],
    }

    def transfer(to_platform: str) -> dict:
        return {
            "action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
            "queue_operations": [{
                "op": "transfer", "task_id": target["id"],
                "from_platform": owner, "to_platform": to_platform,
            }],
            "dispatches": [{"platform_id": to_platform, "task_id": target["id"]}],
        }

    assert _action_within_local_domain(env, transfer(same_region), scope) is True
    assert _action_within_local_domain(env, transfer(neighbor), scope) is False
