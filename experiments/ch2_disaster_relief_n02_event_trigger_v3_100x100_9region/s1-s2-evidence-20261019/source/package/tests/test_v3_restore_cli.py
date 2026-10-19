from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civilian"))

import region_pilot


def test_restore_cli_needs_only_checkpoint_and_cuda_device(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["region_pilot.py", "--restore", "checkpoint.pt", "--device", "cuda:0"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(region_pilot.torch.cuda, "is_available", return_value=True),
        patch.object(region_pilot.torch.cuda, "device_count", return_value=1),
        patch.object(region_pilot, "verify_policy_checkpoint", return_value={"status": "complete", "device": "cuda:0"}) as verify,
        patch.object(region_pilot, "run_pilot", side_effect=AssertionError("restore must not train")),
    ):
        region_pilot.main()

    verify.assert_called_once_with(Path("checkpoint.pt"), device="cuda:0")
    assert json.loads(capsys.readouterr().out) == {"device": "cuda:0", "status": "complete"}


@pytest.mark.parametrize("argv", [
    ["region_pilot.py"],
    ["region_pilot.py", "--output", "out"],
    ["region_pilot.py", "--config", "config.json"],
])
def test_training_cli_requires_output_and_config(argv: list[str]) -> None:
    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
        region_pilot.main()
    assert exc.value.code == 2


def test_restore_cli_rejects_non_cuda_device_before_checkpoint_verification() -> None:
    argv = ["region_pilot.py", "--restore", "checkpoint.pt", "--device", "cpu"]
    with patch.object(sys, "argv", argv), patch.object(region_pilot, "verify_policy_checkpoint") as verify:
        with pytest.raises(SystemExit) as exc:
            region_pilot.main()
    assert exc.value.code == 2
    verify.assert_not_called()


def test_restore_cli_rejects_unavailable_cuda_index() -> None:
    argv = ["region_pilot.py", "--restore", "checkpoint.pt", "--device", "cuda:1"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(region_pilot.torch.cuda, "is_available", return_value=True),
        patch.object(region_pilot.torch.cuda, "device_count", return_value=1),
        patch.object(region_pilot, "verify_policy_checkpoint") as verify,
        pytest.raises(RuntimeError, match="V3_S2_CONFIGURED_CUDA_DEVICE_UNAVAILABLE"),
    ):
        region_pilot.main()
    verify.assert_not_called()

