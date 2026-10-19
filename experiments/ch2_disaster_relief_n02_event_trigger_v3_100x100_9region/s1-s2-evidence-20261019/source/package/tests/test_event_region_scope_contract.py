from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

from event_environment import EventReliefEnv, _action_within_local_domain, generate_reconstruction_candidates
from event_trigger import identify_affected_scope
from region_scenarios import (
    build_scenario, build_s1_arrival_perturbation_pair, build_s1_regional_support_witness,
)


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

    assert scope["local_eligible"] is False
    assert scope["regional_eligible"] is True
    assert scope["scope"] == "REGIONAL_REPLAN"
    assert coordinator in scope["affected_platform_ids"]
    assert scope["candidate_platform_ids"]
    catalog = generate_reconstruction_candidates(observation, scope, env=env)
    regional = [row for row in catalog if row["legal"] is True
                and not row["full_environment_action"].get("noop")]
    assert len(regional) >= 2
    assert all(row["full_environment_action"]["scope"] == "REGIONAL_REPLAN" for row in regional)


def test_public_c1_arrival_pair_has_two_effective_local_alternatives() -> None:
    control, treatment = build_s1_arrival_perturbation_pair(
        scenario_id="s1-arrival-pair", split="development", seed_variant=8201,
    )
    assert control["queue_plan"] == treatment["queue_plan"]
    assert control["base_scenario"]["chapter1_snapshot"] == treatment["base_scenario"]["chapter1_snapshot"]
    control_tape, treatment_tape = control["event_tape"], treatment["event_tape"]
    assert [(row["time"], row["kind"], row["event_id"]) for row in control_tape] == [
        (row["time"], row["kind"], row["event_id"]) for row in treatment_tape
    ]
    assert control_tape[1]["patch"] == treatment_tape[1]["patch"]
    assert control_tape[1]["speed_factor"] == 1.0
    assert treatment_tape[1]["speed_factor"] < 1.0

    env = EventReliefEnv(treatment)
    observation = env.reset()
    for _ in range(11):
        observation, _, _, _, _ = env.step(_noop())
    target = next(row for row in observation["tasks"] if row["id"] == "task-r01-hidden")
    assert target["status"] == "pending"
    assert target["assignee"] is None
    scope = identify_affected_scope(observation, {
        "affected_task_ids": [target["id"]], "affected_platform_ids": [],
        "direct_region_ids": ["r01"], "event_details": {"category_count": 1},
        "strong_event": False,
    })
    assert scope["scope"] == "LOCAL_REPAIR"
    assert scope["local_eligible"] is True
    catalog = generate_reconstruction_candidates(observation, scope, env=env)
    alternatives = [row for row in catalog if row["legal"] is True
                    and not row["full_environment_action"].get("noop")]
    assert len(alternatives) >= 2
    assert len({row["full_environment_action"]["dispatches"][0]["platform_id"]
                for row in alternatives}) >= 2
    assert all(row["full_environment_action"]["scope"] == "LOCAL_REPAIR" for row in alternatives)

    control_env = EventReliefEnv(control)
    control_observation = control_env.reset()
    for _ in range(11):
        control_observation, _, _, _, _ = control_env.step(_noop())
    control_metrics = {
        row["platform_id"]: row for row in control_env.candidate_dispatches()
        if row["task_id"] == target["id"] and row["platform_id"] in {"n02-uav-03", "n02-uav-04"}
    }
    treatment_metrics = {
        row["platform_id"]: row for row in env.candidate_dispatches()
        if row["task_id"] == target["id"] and row["platform_id"] in {"n02-uav-03", "n02-uav-04"}
    }
    assert set(control_metrics) == set(treatment_metrics) == {"n02-uav-03", "n02-uav-04"}
    for platform_id in control_metrics:
        assert treatment_metrics[platform_id]["estimated_completion"] > control_metrics[platform_id]["estimated_completion"]
        assert treatment_metrics[platform_id]["required_energy"] > control_metrics[platform_id]["required_energy"]
        assert treatment_metrics[platform_id]["environmental_risk"] > control_metrics[platform_id]["environmental_risk"]


def test_active_task_is_not_a_dispatch_repair_candidate() -> None:
    scenario = build_scenario(scenario_id="scope-active-task", split="development",
                              condition="new_arrival", seed_variant=8201)
    env = EventReliefEnv(scenario)
    observation = env.reset()
    for _ in range(8):
        observation, _, _, _, _ = env.step(_noop())
    active = next(row for row in observation["tasks"] if row["id"] == "task-r01-4")
    assert active["status"] == "active"
    assert all(row["task_id"] != active["id"] for row in env.candidate_dispatches())
    owner = active["assignee"]
    assert owner is not None
    reasons = env._dispatch_legality(
        observation, {"platform_id": owner, "task_id": active["id"]},
        {(owner, active["id"]): {}},
    )
    assert "task_not_reassignable" in reasons


def test_isolated_regional_support_uses_one_hop_neighbor_candidates() -> None:
    scenario = build_s1_regional_support_witness(
        scenario_id="s1-regional-support-witness", seed_variant=8306,
    )
    assert len(scenario["event_tape"]) == 1
    assert scenario["event_tape"][0]["kind"] == "task_arrival"
    env = EventReliefEnv(scenario)
    observation = env.reset()
    for _ in range(8):
        observation, _, _, _, _ = env.step(_noop())
    arriving = next(row for row in observation["tasks"] if row["id"] == "task-r00-hidden")
    scope = identify_affected_scope(observation, {
        "affected_task_ids": [arriving["id"]], "affected_platform_ids": [],
        "direct_region_ids": ["r00"], "event_details": {"category_count": 1},
        "strong_event": False,
    })
    catalog = generate_reconstruction_candidates(observation, scope, env=env)
    alternatives = [row for row in catalog if row["legal"] is True
                    and not row["full_environment_action"].get("noop")]

    assert scope["local_eligible"] is False
    assert scope["regional_eligible"] is True
    assert scope["scope"] == "REGIONAL_REPLAN"
    assert scope["resource_feasibility"]["local"][arriving["id"]]["reasons"] == ["platform_busy_or_failed"]
    assert scope["resource_feasibility"]["regional"][arriving["id"]]["feasible"] is True
    assert len(alternatives) >= 2
    assert all(row["full_environment_action"]["scope"] == "REGIONAL_REPLAN" for row in alternatives)
    region_by_platform = {row["id"]: row["region_id"] for row in observation["platforms"]}
    assert all(region_by_platform[dispatch["platform_id"]] in scope["neighbor_region_ids"]
               for row in alternatives for dispatch in row["full_environment_action"]["dispatches"])


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
