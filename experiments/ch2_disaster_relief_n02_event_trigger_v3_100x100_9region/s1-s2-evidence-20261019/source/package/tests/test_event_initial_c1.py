import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"civilian"))
from event_scenarios import build_event_scenarios
from chapter1_adapter import generate_public_c1_initial_assignment
from stable_identity import key_digest
from event_environment import EventReliefEnv


def test_executed_initial_queues_are_fully_recomputed_from_public_c1():
    for scenario in build_event_scenarios():
        base=scenario["base_scenario"]
        computed=generate_public_c1_initial_assignment(base,seed=scenario["seed_variant"],schedule_backlog=True)
        assert scenario["queue_plan"] == computed["queues"] == base["chapter1_snapshot"]["queues"]
        receipt=base["chapter1_snapshot"]["assignment_receipt"]
        assert receipt["assignments"] == computed["queues"]
        assert receipt["assignment_output_sha256"] == key_digest(computed["queues"])
        assert receipt["queue_planning_trace_sha256"] == key_digest(receipt["queue_planning_trace"])
        assert receipt["feasibility"]["assigned_task_count"] == 8
        assert not receipt["feasibility"]["unassigned_known_task_reasons"]
        assert EventReliefEnv(scenario).reset()["queues"] == computed["queues"]


def test_backlog_has_no_task_id_special_cases_and_ignores_hidden_tasks():
    scenario=build_event_scenarios()[0]
    base=copy.deepcopy(scenario["base_scenario"])
    original=generate_public_c1_initial_assignment(base,seed=8201,schedule_backlog=True)
    for task in base["tasks"]:
        if not task["known_initial"]:
            task["priority"]=10000
            task["position"]=[0.,99.]
    changed=generate_public_c1_initial_assignment(base,seed=8201,schedule_backlog=True)
    assert changed == original
    rename={task["id"]:"public-"+task["id"] for task in base["tasks"]}
    for task in base["tasks"]:
        task["id"]=rename[task["id"]]
    renamed=generate_public_c1_initial_assignment(base,seed=8201,schedule_backlog=True)
    assert renamed["queues"] == {p:[rename[t] for t in q] for p,q in original["queues"].items()}


def test_backlog_public_identity_binds_planning_horizon():
    base=build_event_scenarios()[0]["base_scenario"]
    before=generate_public_c1_initial_assignment(base,seed=8201,schedule_backlog=True)
    altered=copy.deepcopy(base)
    altered["horizon"] = 1
    after=generate_public_c1_initial_assignment(altered,seed=8201,schedule_backlog=True)
    assert before["receipt"]["public_input_sha256"] != after["receipt"]["public_input_sha256"]
    assert before["queues"] != after["queues"]
