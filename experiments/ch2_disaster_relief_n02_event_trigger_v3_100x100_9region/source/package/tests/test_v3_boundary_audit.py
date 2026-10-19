from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class V3BoundaryAuditTests(unittest.TestCase):
    def test_producer_keeps_replayable_inputs_and_recomputed_outputs(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools" / "audit_v3_boundary.py")],
            cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        evidence_dir = Path(completed.stdout.strip())
        if not evidence_dir.is_absolute():
            evidence_dir = ROOT / evidence_dir
        wrapper = json.loads((evidence_dir / "SCENARIO_WRAPPER.json").read_text(encoding="utf-8"))
        task_evidence = json.loads((evidence_dir / "TASK_COORDINATES_AND_REGIONS.json").read_text(encoding="utf-8"))
        index = json.loads((evidence_dir / "REPLAY_INDEX.json").read_text(encoding="utf-8"))

        self.assertEqual(len(wrapper["base_scenario"]["tasks"]), 45)
        self.assertEqual(sum(not row["known_initial"] for row in wrapper["base_scenario"]["tasks"]), 9)
        self.assertEqual(len(task_evidence["tasks"]), 45)
        self.assertEqual(sum(not row["known_initial"] for row in task_evidence["tasks"]), 9)
        self.assertTrue(all(row["declared_region_id"] == row["region_id_recomputed_from_position"]
                            for row in task_evidence["tasks"]))

        by_name = {row["variant"]: row for row in index["cases"]}
        for name in ("hidden_task_change", "future_event_tape_change", "preset_snapshot_queue_change"):
            self.assertEqual(by_name["baseline"]["recomputed_hashes"], by_name[name]["recomputed_hashes"])
            self.assertTrue((evidence_dir / by_name[name]["scenario_wrapper"]).is_file())
            self.assertTrue((evidence_dir / by_name[name]["public_input"]).is_file())
            self.assertTrue((evidence_dir / by_name[name]["queues"]).is_file())
        self.assertNotEqual(by_name["baseline"]["recomputed_hashes"]["public_input_sha256"],
                            by_name["public_priority_control"]["recomputed_hashes"]["public_input_sha256"])
        self.assertIn("does not assert audit approval", index["interpretation"])
        self.assertIn("schedule_backlog=True", index["c1_call"])
        self.assertEqual(index["source_hashes_before"], index["source_hashes_after"])
        self.assertEqual(len(index["source_hashes_before"]), 3)


if __name__ == "__main__":
    unittest.main()
