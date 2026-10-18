from __future__ import annotations

import copy

from tools.independent_baseline_oracle import audit_data, canonical_digest


WEIGHTS = {"completion": 1.0, "delay": 0.2, "energy": 0.01, "risk": 0.25,
           "communication": 0.01, "switch": 0.05, "reconstruction": 0.05,
           "reconstruction_scale": 0.01, "global_scope": 0.02}
FORMULA = {"schema": "event-relief-reward/1", "weights": WEIGHTS}


def _state(time=0, *, owner="p1", queue=None, energy=0.0, statuses=None):
    statuses = statuses or {}
    return {
        "time": time,
        "leaf_tasks": [{"id": f"r{i}", "assignee": owner if i == 0 else None,
                        "status": statuses.get(i, "pending"), "completed_at": time if statuses.get(i) == "completed" else None}
                       for i in range(12)],
        "leaf_task_specs": [{"id": f"r{i}", "parent_task_id": f"r{i}"} for i in range(12)],
        "root_task_specs": [{"id": f"r{i}", "deadline": 100, "priority": 5.0 if i == 0 else 1.0}
                            for i in range(12)],
        "split_manifests": [], "root_mapping": {f"r{i}": f"r{i}" for i in range(12)},
        "leaf_platforms": [{"id": "p1", "energy_used": energy}],
        "platform_specs": [{"id": "p1", "energy_initial": 10.0}],
        "queues": {"p1": list(queue or [])},
    }


def _fixture(events=None, *, before=None, after=None, action=None, operation_receipts=None,
             command_receipts=None, terms=None, reward=0.0):
    before = before or _state(0, queue=["r0"])
    after = after or _state(1, queue=["r0"])
    action = action or {"action_type": "reconstruct", "scope": "NOOP", "noop": True,
                        "queue_operations": [], "dispatches": []}
    terms = terms or {"completion": 0.0, "delay": 0.0, "energy": 0.0, "risk": 0.0,
                      "communication": 0.0, "switch": 0.0, "reconstruction": 0.0,
                      "reconstruction_scale": 0.0, "global_scope": 0.0}
    receipt = {
        "schema": "baseline-action-receipt/1", "method_id": "Greedy", "parent_id": "parent-a",
        "split": "train", "event_tape_id": "tape-a", "seed": 8201, "time": 0,
        "action_id": "Greedy:parent-a:8201:0", "decision_clock": {"planned": False, "explicit_noop": True},
        "full_environment_action": action, "raw_state_before": before, "raw_state_after": after,
        "raw_events": events or [], "operation_receipts": operation_receipts or [],
        "command_application_receipts": command_receipts or {"causal_change_events": []},
        "reward_formula": FORMULA, "reward_terms": terms, "reward": reward,
        "reward_primitives": {"completion_count": 0, "delay_minutes": 0.0, "energy_units": 0.0,
                              "risk_units": 0.0, "communication_messages": 0, "switch_count": 0,
                              "reconstruction_count": 0, "reconstruction_size": 0},
        "rule_protocol_message_count": 0, "effective_reconstruction_count": 0,
        "reconstruction_size": 0, "owner_change_count": 0, "queue_reorder_count": 0,
    }
    episode = {"method_id": "Greedy", "parent_id": "parent-a", "event_tape_id": "tape-a", "seed": 8201,
               "initial_c1_assignment": {"p1": ["r0"]}, "horizon_minutes": 60,
               "metrics": {"completion_rate": 0.0, "on_time_rate": 0.0, "mean_delay_minutes": 0.0,
                           "critical_failure_count_priority_ge_5": 1, "failed_root_task_count": 0,
                           "cancelled_root_task_count": 0, "original_root_task_count": 12,
                           "environment_utility": 0.0, "global_utility": 0.0, "net_utility": 0.0, "protocol_cost": 0.0,
                           "trigger_count": 0, "planning_invocation_count": 0, "nonempty_planning_invocation_count": 0,
                           "scope_nonempty_planning_count": 0, "actionable_catalog_planning_count": 0,
                           "detector_event_edge_count": 0, "requested_nonnoop_count": 0, "effective_reconstruction_count": 0,
                           "reconstruction_size": 0, "local_repair_invocation_count": 0,
                           "global_replan_invocation_count": 0, "task_owner_change_count": 0,
                           "queue_reorder_count": 0, "environment_action_delivery_message_count": 0,
                           "rule_protocol_message_count": 0, "planning_latency_seconds": 0.0,
                           "policy_response_seconds": 0.0, "constraint_violations": 0, "energy_units": 0.0,
                           "task_switch_count": 0}}
    return receipt, episode


def test_root_completion_summary_tamper_is_detected():
    receipt, episode = _fixture()
    episode["metrics"]["completion_rate"] = 1 / 12
    report = audit_data([receipt], [episode])
    assert report["status"] == "FAIL"
    assert any(row["code"] == "EPISODE_METRIC_MISMATCH" for row in report["mismatch"])


def test_natural_queue_head_pop_is_not_reconstruction():
    before = _state(0, queue=["r0", "r1"])
    after = _state(1, queue=["r1"])
    receipt, episode = _fixture(before=before, after=after)
    report = audit_data([receipt], [episode])
    assert report["status"] == "PASS"
    assert report["episodes"][0]["recomputed"]["effective_reconstruction_count"] == 0


def test_delayed_delivery_is_attributed_to_originating_action():
    before, after = _state(0), _state(1, owner="p2")
    action = {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
              "queue_operations": [], "dispatches": [{"task_id": "r0", "platform_id": "p2"}]}
    events = [{"time": 1, "type": "communication_delivered", "task_id": "r0", "platform_id": "p2",
               "origin_action_id": "Greedy:parent-a:8201:0"},
              {"time": 0, "type": "task_owner_change", "task_id": "r0",
               "previous_owners": ["p1"], "new_owners": ["p2"]},
              {"time": 0, "type": "task_switch", "task_id": "r0"}]
    cause = {"causal_change_events": [events[1]]}
    terms = {"completion": 0.0, "delay": 0.0, "energy": 0.0, "risk": 0.0,
             "communication": 0.0, "switch": -0.05, "reconstruction": -0.05,
             "reconstruction_scale": -0.01, "global_scope": 0.0}
    receipt, episode = _fixture(events, before=before, after=after, action=action,
                                command_receipts=cause, terms=terms, reward=sum(terms.values()))
    receipt["reward_primitives"].update({"switch_count": 1, "reconstruction_count": 1, "reconstruction_size": 1})
    receipt.update({"effective_reconstruction_count": 1, "reconstruction_size": 1, "owner_change_count": 1})
    episode["metrics"].update({"environment_utility": -0.11, "global_utility": -0.11, "net_utility": -0.11,
                               "effective_reconstruction_count": 1, "reconstruction_size": 1,
                               "requested_nonnoop_count": 1, "local_repair_invocation_count": 1,
                               "task_owner_change_count": 1, "task_switch_count": 1})
    report = audit_data([receipt], [episode])
    assert not any(row["code"] == "DELAYED_DELIVERY_ATTRIBUTION_MISSING" for row in report["missing"])
    assert report["episodes"][0]["recomputed"]["effective_reconstruction_count"] == 1


def test_unattributed_delayed_delivery_is_missing_evidence():
    receipt, episode = _fixture(events=[{"time": 1, "type": "communication_delivered", "task_id": "r0"}])
    report = audit_data([receipt], [episode])
    assert any(row["code"] == "DELAYED_DELIVERY_ATTRIBUTION_MISSING" for row in report["missing"])


def test_energy_and_reward_tampering_are_detected():
    before, after = _state(0, energy=0.0), _state(1, energy=2.0)
    receipt, episode = _fixture(events=[{"time": 0, "type": "move", "energy": 1.0, "environmental_risk": 0.0}],
                               before=before, after=after)
    report = audit_data([receipt], [episode])
    codes = {row["code"] for row in report["mismatch"]}
    assert "ENERGY_EVENT_ENDPOINT_MISMATCH" in codes
    assert "REWARD_MISMATCH" in codes


def test_platform_failed_alias_and_platform_failure_count_once():
    events = [{"time": 1, "type": "platform_failed", "platform_id": "p1", "disturbance_id": "d1"},
              {"time": 1, "type": "platform_failure", "platform_id": "p1", "event_id": "d1"}]
    terms = {"completion": 0.0, "delay": 0.0, "energy": 0.0, "risk": -0.25,
             "communication": 0.0, "switch": 0.0, "reconstruction": 0.0,
             "reconstruction_scale": 0.0, "global_scope": 0.0}
    receipt, episode = _fixture(events=events, terms=terms, reward=-0.25)
    receipt["reward_primitives"]["risk_units"] = 1.0
    episode["metrics"].update({"environment_utility": -0.25, "global_utility": -0.25, "net_utility": -0.25})
    report = audit_data([receipt], [episode])
    assert report["status"] == "PASS"
    assert report["episodes"][0]["recomputed"]["utility"] == -0.25


def test_legal_nonnoop_catalog_counts_even_when_selected_action_is_noop_and_c1_falls_back_to_raw_queues():
    receipt, episode = _fixture()
    noop = receipt["full_environment_action"]
    dispatch = {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
                "queue_operations": [], "dispatches": [{"task_id": "r0", "platform_id": "p1"}]}
    catalog = [{"candidate_key": "dispatch", "legal": True, "full_environment_action": dispatch},
               {"candidate_key": "noop", "legal": True, "full_environment_action": noop}]
    receipt.update({"decision_clock": {"planned": True, "explicit_noop": False},
                    "candidate_catalog": catalog, "candidate_catalog_sha256": canonical_digest(catalog),
                    "selected_candidate": {"candidate_index": 1, "candidate_key": "noop"}})
    episode["initial_c1_assignment"] = None
    episode["metrics"].update({"trigger_count": 1, "planning_invocation_count": 1,
                               "nonempty_planning_invocation_count": 1, "actionable_catalog_planning_count": 1,
                               "scope_nonempty_planning_count": 0})
    report = audit_data([receipt], [episode])
    assert report["status"] == "PASS"
    assert report["episodes"][0]["recomputed"]["nonempty_planning_invocation_count"] == 1


def test_raw_queue_c1_fallback_is_compared_across_methods():
    first_receipt, first_episode = _fixture()
    second_receipt, second_episode = copy.deepcopy(first_receipt), copy.deepcopy(first_episode)
    second_receipt["method_id"] = "Auction"
    second_receipt["action_id"] = "Auction:parent-a:8201:0"
    second_episode["method_id"] = "Auction"
    second_episode["initial_c1_assignment"] = None
    second_receipt["raw_state_before"]["queues"]["p2"] = ["r1"]
    report = audit_data([first_receipt, second_receipt], [first_episode, second_episode])
    assert any(row["code"] == "C1_PAIRING_MISMATCH" for row in report["mismatch"])


def test_immediate_dispatch_with_delivery_and_raw_assignment_is_effective_without_delivery_event():
    before = _state(20, owner=None, queue=[])
    after = _state(21, owner="p2", queue=["r0"])
    action = {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
              "queue_operations": [], "dispatches": [{"task_id": "r0", "platform_id": "p2"}]}
    events = [{"time": 20, "type": "assignment", "task_id": "r0", "reason": "learned_new_task",
               "initial": False, "previous_assignee": None, "new_assignee": "p2"},
              {"time": 20, "type": "communication_tx", "reason": "dispatch", "task_id": "r0",
               "target": "p2", "delivered": True, "message_count": 1},
              {"time": 20, "type": "task_owner_change", "task_id": "r0",
               "previous_owners": [], "new_owners": ["p2"]}]
    terms = {"completion": 0.0, "delay": 0.0, "energy": 0.0, "risk": 0.0,
             "communication": -0.01, "switch": 0.0, "reconstruction": -0.05,
             "reconstruction_scale": -0.01, "global_scope": 0.0}
    receipt, episode = _fixture(events, before=before, after=after, action=action,
                                terms=terms, reward=sum(terms.values()))
    receipt["communication_receipts"] = [{"reason": "dispatch", "task_id": "r0", "target": "p2",
                                          "delivered": True, "delay_minutes": 0}]
    catalog = [{"candidate_key": "dispatch-r0-p2", "legal": True, "full_environment_action": action}]
    receipt.update({"decision_clock": {"planned": True, "explicit_noop": False},
                    "candidate_catalog": catalog, "candidate_catalog_sha256": canonical_digest(catalog),
                    "selected_candidate": {"candidate_index": 0, "candidate_key": "dispatch-r0-p2"}})
    receipt["reward_primitives"].update({"communication_messages": 1, "reconstruction_count": 1,
                                         "reconstruction_size": 1})
    receipt.update({"requested_nonnoop": True, "effective_reconstruction_count": 1,
                    "reconstruction_size": 1, "owner_change_count": 1})
    receipt["owners_before"], receipt["owners_after"] = {"r0": None}, {"r0": "p2"}
    episode["metrics"].update({"environment_utility": -0.07, "global_utility": -0.07, "net_utility": -0.07,
                               "effective_reconstruction_count": 1, "reconstruction_size": 1,
                               "requested_nonnoop_count": 1, "local_repair_invocation_count": 1,
                               "task_owner_change_count": 1, "environment_action_delivery_message_count": 1,
                               "trigger_count": 1, "planning_invocation_count": 1,
                               "actionable_catalog_planning_count": 1, "nonempty_planning_invocation_count": 1})
    report = audit_data([receipt], [episode])
    assert report["status"] == "PASS"
    assert report["episodes"][0]["recomputed"]["effective_reconstruction_count"] == 1
    assert report["episodes"][0]["recomputed"]["owner_change_count"] == 1


def test_bound_same_owner_queue_head_dispatch_is_not_reconstruction():
    before, after = _state(3, owner="p1", queue=["r0"]), _state(4, owner="p1", queue=["r0"])
    action = {"action_type": "reconstruct", "scope": "LOCAL_REPAIR", "noop": False,
              "queue_operations": [], "dispatches": [{"task_id": "r0", "platform_id": "p1"}]}
    events = [{"time": 3, "type": "communication_tx", "reason": "queue_head_dispatch", "task_id": "r0",
               "target": "p1", "delivered": True, "message_count": 1}]
    receipt, episode = _fixture(events, before=before, after=after, action=action)
    receipt["communication_receipts"] = [{"reason": "queue_head_dispatch", "task_id": "r0", "target": "p1",
                                          "delivered": True, "delay_minutes": 0}]
    catalog = [{"candidate_key": "dispatch-r0-p1", "legal": True, "full_environment_action": action}]
    receipt.update({"decision_clock": {"planned": True, "explicit_noop": False},
                    "candidate_catalog": catalog, "candidate_catalog_sha256": canonical_digest(catalog),
                    "selected_candidate": {"candidate_index": 0, "candidate_key": "dispatch-r0-p1"}})
    receipt["reward_primitives"]["communication_messages"] = 1
    terms = {"completion": 0.0, "delay": 0.0, "energy": 0.0, "risk": 0.0,
             "communication": -0.01, "switch": 0.0, "reconstruction": 0.0,
             "reconstruction_scale": 0.0, "global_scope": 0.0}
    receipt["reward_terms"], receipt["reward"] = terms, -0.01
    episode["metrics"].update({"environment_utility": -0.01, "global_utility": -0.01, "net_utility": -0.01,
                               "requested_nonnoop_count": 1, "local_repair_invocation_count": 1,
                               "environment_action_delivery_message_count": 1, "trigger_count": 1,
                               "planning_invocation_count": 1, "actionable_catalog_planning_count": 1,
                               "nonempty_planning_invocation_count": 1})
    report = audit_data([receipt], [episode])
    assert report["status"] == "PASS"
    assert report["episodes"][0]["recomputed"]["effective_reconstruction_count"] == 0
