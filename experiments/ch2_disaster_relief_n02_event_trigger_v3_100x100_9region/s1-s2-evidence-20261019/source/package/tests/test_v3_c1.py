from __future__ import annotations

import unittest

from civilian.chapter1_adapter import generate_public_c1_initial_assignment
from civilian.region_scenarios import _base_scenario
from civilian.stable_identity import key_digest


class RegionC1Tests(unittest.TestCase):
    def test_public_c1_is_global_and_receipts_are_complete(self):
        scenario = _base_scenario("c1-global", 8201)
        # A v3 public C1 assignment must ignore the legacy bool locality fields.
        first_platform = scenario["platforms"][0]
        first_task = next(t for t in scenario["tasks"] if t["known_initial"] and t["region_id"] != first_platform["region_id"])
        first_platform["local"] = False
        first_task["local"] = True
        assignment = generate_public_c1_initial_assignment(scenario, seed=8201, schedule_backlog=True)
        receipt = assignment["receipt"]
        self.assertEqual(receipt["public_input_sha256"], key_digest(assignment["public_input"]))
        self.assertEqual(len(assignment["public_input"]["single_step_input"]["known_tasks"]), 36)
        self.assertFalse(any("hidden" in row["id"] for row in assignment["public_input"]["single_step_input"]["known_tasks"]))
        self.assertEqual(receipt["region_task_distribution"], {f"r{r}{c}": 4 for r in range(3) for c in range(3)})
        self.assertEqual(receipt["platform_region_distribution"], {
            "r00": 2, "r01": 3, "r02": 3, "r10": 3, "r11": 2, "r12": 3, "r20": 3, "r21": 3, "r22": 2,
        })
        self.assertEqual(receipt["assignments"], assignment["queues"])
        self.assertEqual(receipt["assignment_output_sha256"], key_digest(assignment["queues"]))
        self.assertEqual(receipt["algorithm_source"], "package/civilian/baselines.py:C1/choose_step_c1_actions")
        self.assertEqual(receipt["known_task_ids"], sorted(t["id"] for t in scenario["tasks"] if t["known_initial"]))
        hidden_ids = {t["id"] for t in scenario["tasks"] if not t["known_initial"]}
        self.assertTrue(hidden_ids.isdisjoint(receipt["known_task_ids"]))
        self.assertTrue(all(tid not in hidden_ids for queue in assignment["queues"].values() for tid in queue))
        cross_region = any(
            next(p for p in scenario["platforms"] if p["id"] == pid)["region_id"] !=
            next(t for t in scenario["tasks"] if t["id"] == tid)["region_id"]
            for pid, queue in assignment["queues"].items() for tid in queue
            if next(p for p in scenario["platforms"] if p["id"] == pid)["type"] == "uav"
        )
        self.assertTrue(cross_region)


if __name__ == "__main__":
    unittest.main()
