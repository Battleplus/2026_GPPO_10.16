import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import event_models
import event_policy


def test_v3_region_nodes_and_regional_scope_are_encoded() -> None:
    observation = {
        "map": {"rows": 100, "cols": 100, "grid_cells": 10000, "grid_contract": "relief-grid-100x100-v1"},
        "time": 0, "horizon": 60, "region_contract": "relief-regions-3x3-v1",
        "regions": [{"region_id": f"r{r}{c}", "center": [16.5 + 33 * c, 16.5 + 33 * r]} for r in range(3) for c in range(3)],
        "platforms": [], "tasks": [], "environment": [], "communication": [], "queues": {},
    }
    rows, types, edges = event_models._node_features(observation)
    assert sum(node_type == event_models.NODE_TYPES["region"] for node_type in types) == 9
    assert any(relation == 7 for _, _, relation in edges) is False
    candidate = {"candidate_key": "regional", "candidate_scope": "regional", "legal": True,
                 "full_environment_action": {"scope": "REGIONAL_REPLAN", "action_type": "reconstruct", "noop": False,
                                              "queue_operations": [], "dispatches": []}}
    assert event_policy._candidate_scope(candidate) == "REGIONAL_REPLAN"
    mask, _ = event_policy._scope_masks([{
        "candidate_key": "noop", "candidate_scope": "noop", "legal": True,
        "full_environment_action": {"scope": "NOOP", "noop": True},
    }, candidate], {"NOOP": True, "LOCAL_REPAIR": False, "REGIONAL_REPLAN": True, "GLOBAL_REPLAN": False}, None)
    assert mask == [True, False, True, False]


def test_v3_pilot_config_is_frozen_to_two_variants() -> None:
    config_path = Path(__file__).parents[2] / "configs" / "V3_PILOT_CONFIG.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["seed"] == 8201
    assert config["variants"] == ["Periodic-G", "Event-G"]
    assert config["world_model"] is False
    assert config["training_parents"] == 4 and config["development_parents"] == 2
    assert config["rounds"] == 1 and config["max_optimizer_updates"] <= 32
