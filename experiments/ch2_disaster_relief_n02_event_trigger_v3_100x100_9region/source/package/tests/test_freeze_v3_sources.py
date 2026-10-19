from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("freeze_v3", ROOT / "tools" / "freeze_v3.py")
FREEZE_V3 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FREEZE_V3)


class FreezeV3SourceSelectionTests(unittest.TestCase):
    def test_old_run_evidence_and_bytecode_are_excluded(self):
        self.assertTrue(FREEZE_V3._excluded_directory(".pytest_cache"))
        self.assertTrue(FREEZE_V3._excluded_directory("tmp-evidence-new"))
        self.assertTrue(FREEZE_V3._excluded_directory("smoke-run-01"))
        self.assertTrue(FREEZE_V3._excluded_directory("S0-old-run"))
        with TemporaryDirectory(dir=ROOT.parent) as temporary:
            source_root = Path(temporary)
            for directory in FREEZE_V3.DIRECTORIES:
                (source_root / directory).mkdir(parents=True)
            files = (
                "package/civilian/region_scenarios.py",
                "package/tests/test_v3_regions.py",
                "tools/freeze_v3.py",
                "configs/V3_PREREGISTRATION.json",
                "protocols/EXECUTION_AND_ACCEPTANCE.md",
                "BASELINE_PROVENANCE.json",
            )
            for name in files:
                path = source_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            (source_root / "package" / "tmp-evidence-old").mkdir()
            (source_root / "package" / "smoke-run-01").mkdir()
            (source_root / "package" / "civilian" / "__pycache__").mkdir()
            (source_root / "package" / "civilian" / "__pycache__" / "old.pyc").write_bytes(b"bytecode")
            (source_root / "package" / ".pytest_cache").mkdir()

            selected = {path.relative_to(source_root).as_posix()
                        for path in FREEZE_V3.selected_files(source_root)}
            self.assertFalse(any(path.startswith("package/tmp-evidence") for path in selected))
            self.assertFalse(any(path.startswith("package/smoke-run") for path in selected))
            self.assertFalse(any("/__pycache__/" in path or path.endswith(".pyc") for path in selected))
            self.assertFalse(any("/.pytest_cache/" in path for path in selected))
            self.assertIn("package/civilian/region_scenarios.py", selected)
            self.assertIn("package/tests/test_v3_regions.py", selected)
            self.assertIn("tools/freeze_v3.py", selected)
            self.assertIn("configs/V3_PREREGISTRATION.json", selected)
            self.assertTrue(any(path.startswith("protocols/") for path in selected))

    def test_unexcluded_directory_symlink_is_rejected(self):
        walk_rows = [(str(ROOT / "package"), ["linked-source"], [])]
        real_is_symlink = Path.is_symlink

        def is_symlink(path: Path) -> bool:
            return path.name == "linked-source" or real_is_symlink(path)

        with patch.object(FREEZE_V3.os, "walk", return_value=iter(walk_rows)), \
                patch.object(Path, "is_symlink", is_symlink):
            with self.assertRaisesRegex(ValueError, "symlink forbidden"):
                FREEZE_V3.selected_files(ROOT)


if __name__ == "__main__":
    unittest.main()
