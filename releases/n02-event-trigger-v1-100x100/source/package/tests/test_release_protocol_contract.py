from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CIVILIAN_ROOT = PACKAGE_ROOT / "civilian"
sys.path.insert(0, str(CIVILIAN_ROOT))

from package_layout import PACKAGE_RELEASE_ID  # noqa: E402
from phase_handshake import StageServer  # noqa: E402
from protocol_contract import (  # noqa: E402
    N2_STAGE_ORDER,
    PROTOCOL_ID,
    STAGE_PROTOCOL_ID,
    validate_protocol_contract,
)
from resource_supervisor import build_work_call_request  # noqa: E402


def test_release_protocol_is_bound_across_local_contract_files() -> None:
    request = build_work_call_request()
    runtime = json.loads((CIVILIAN_ROOT / "runtime-spec.json").read_text(encoding="utf-8"))
    prior = json.loads((CIVILIAN_ROOT / "PRIOR_RESOURCE_COST.json").read_text(encoding="utf-8"))
    registry = json.loads((CIVILIAN_ROOT / "registered_data" / "input_registry.json").read_text(encoding="utf-8"))

    for item in (build_work_call_request(), runtime, prior, registry):
        validate_protocol_contract(
            package_release=item.get("package_release"),
            protocol_id=item.get("protocol_id"),
            stage_protocol=item.get("stage_protocol"),
            stage_order=item.get("stage_order", N2_STAGE_ORDER),
        )
    assert PACKAGE_RELEASE_ID == request["package_release"]
    assert request["stage_order"] == list(N2_STAGE_ORDER)


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_id", "n02-integration-smoke-v4-100x100"),
        ("stage_protocol", "n02-integration-smoke-v4/seven-stage"),
        ("stage_order", ["settlement_and_export"]),
    ],
)
def test_stage_server_rejects_cross_component_protocol_mismatch(field: str, value: object) -> None:
    request = build_work_call_request()
    request[field] = value
    with pytest.raises(ValueError, match="N02_PROTOCOL_CONTRACT_MISMATCH"):
        StageServer(Path("stage.sock"), request, tree_reader=lambda: ())


def test_shared_contract_is_release_specific() -> None:
    validate_protocol_contract(
        package_release=PACKAGE_RELEASE_ID,
        protocol_id=PROTOCOL_ID,
        stage_protocol=STAGE_PROTOCOL_ID,
        stage_order=N2_STAGE_ORDER,
    )
