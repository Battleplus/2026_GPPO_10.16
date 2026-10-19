from __future__ import annotations

import copy
import unittest

from civilian.region_contract import REGION_IDS, build_region_contract, region_id_for_position, validate_region_contract
from civilian.region_scenarios import build_scenario, build_scenario_set
from civilian.scenario_schema import validate_region_event_scenario


class RegionContractTests(unittest.TestCase):
    def test_boundaries_and_diagonal_eight_neighbors(self):
        self.assertEqual(region_id_for_position([0, 0]), "r00")
        self.assertEqual(region_id_for_position([33, 32.99]), "r01")
        self.assertEqual(region_id_for_position([66, 66]), "r22")
        self.assertEqual(build_region_contract()[0]["neighbors"], ["r01", "r10", "r11"])
        self.assertEqual(len(build_region_contract()[4]["neighbors"]), 8)
        with self.assertRaises(ValueError):
            region_id_for_position([100, 50])

    def test_v3_fixed_platform_and_task_allocation(self):
        scenario = build_scenario(scenario_id="contract", split="train", condition="new_arrival", seed_variant=8201)
        base = scenario["base_scenario"]
        validate_region_contract(base)
        self.assertEqual(base["schema_version"], "relief-engineering/2")
        self.assertEqual(base["region_contract"], "relief-regions-3x3-v1")
        self.assertEqual(len(base["platforms"]), 30)
        self.assertEqual(sum(p["type"] == "uav" for p in base["platforms"]), 24)
        self.assertEqual(sum(p["type"] == "helicopter" for p in base["platforms"]), 6)
        self.assertEqual(len(base["tasks"]), 45)
        self.assertEqual(sum(t["known_initial"] for t in base["tasks"]), 36)
        self.assertTrue(all(p["region_id"] is None and p["support_scope"] == "global"
                            for p in base["platforms"] if p["type"] == "helicopter"))
        heli_centers = {tuple(p["position"]) for p in base["platforms"] if p["type"] == "helicopter"}
        self.assertEqual(heli_centers, {tuple(row["center"]) for row in base["regions"]
                                        if row["region_id"] not in {"r00", "r11", "r22"}})
        validate_region_event_scenario(scenario)

    def test_validator_rejects_wrong_global_helicopter_metadata_or_position(self):
        scenario = build_scenario(scenario_id="heli-check", split="train", condition="new_arrival", seed_variant=8203)
        heli = next(p for p in scenario["base_scenario"]["platforms"] if p["type"] == "helicopter")
        heli["position"] = [16.5, 16.5]
        from civilian.region_contract import validate_region_contract
        with self.assertRaisesRegex(ValueError, "non-diagonal"):
            validate_region_contract(scenario["base_scenario"])

    def test_spatial_patch_is_a_real_two_by_two_patch_inside_region(self):
        scenario = build_scenario(scenario_id="patch", split="development", condition="environment_perturbation", seed_variant=8202)
        event = next(row for row in scenario["event_tape"] if row["kind"] == "environment_perturbation")
        self.assertEqual(event["patch"][2:], [2, 2])
        validate_region_event_scenario(scenario)
        bad = copy.deepcopy(scenario)
        bad_event = next(row for row in bad["event_tape"] if row["kind"] == "environment_perturbation")
        bad_event["patch"] = [32, 32, 2, 2]
        from civilian.stable_identity import key_digest
        bad["event_tape_id"] = key_digest(bad["event_tape"])
        with self.assertRaisesRegex(ValueError, "inside"):
            validate_region_event_scenario(bad)

    def test_minimum_train_development_parent_counts(self):
        scenarios = build_scenario_set()
        self.assertEqual(sum(row["split"] == "train" for row in scenarios), 4)
        self.assertEqual(sum(row["split"] == "development" for row in scenarios), 2)
        self.assertEqual(len({row["event_tape_id"] for row in scenarios}), len(scenarios))


if __name__ == "__main__":
    unittest.main()
