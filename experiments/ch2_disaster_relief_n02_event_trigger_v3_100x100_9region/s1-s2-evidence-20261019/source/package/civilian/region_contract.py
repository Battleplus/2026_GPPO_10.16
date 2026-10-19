"""Fixed 3x3 spatial contract used by N02 v3 scenarios."""

from __future__ import annotations

from typing import Any

REGION_CONTRACT = "relief-regions-3x3-v1"
REGION_IDS = tuple(f"r{row}{col}" for row in range(3) for col in range(3))
REGION_EDGES = (0, 33, 66, 100)
UAV_COUNTS = ((2, 3, 3), (3, 2, 3), (3, 3, 2))


def region_id_for_position(position: list[float] | tuple[float, float]) -> str:
    if len(position) != 2:
        raise ValueError("position must contain x and y")
    x, y = float(position[0]), float(position[1])
    if not (0 <= x < 100 and 0 <= y < 100):
        raise ValueError("position must lie in [0, 100) x [0, 100)")
    col = 0 if x < 33 else 1 if x < 66 else 2
    row = 0 if y < 33 else 1 if y < 66 else 2
    return f"r{row}{col}"


def region_bounds(region_id: str) -> list[int]:
    if region_id not in REGION_IDS:
        raise ValueError(f"unknown region_id: {region_id!r}")
    row, col = int(region_id[1]), int(region_id[2])
    return [REGION_EDGES[col], REGION_EDGES[row], REGION_EDGES[col + 1], REGION_EDGES[row + 1]]


def region_center(region_id: str) -> list[float]:
    x0, y0, x1, y1 = region_bounds(region_id)
    return [(x0 + x1) / 2, (y0 + y1) / 2]


def region_neighbors(region_id: str) -> list[str]:
    if region_id not in REGION_IDS:
        raise ValueError(f"unknown region_id: {region_id!r}")
    row, col = int(region_id[1]), int(region_id[2])
    return [f"r{r}{c}" for r in range(max(0, row - 1), min(2, row + 1) + 1)
            for c in range(max(0, col - 1), min(2, col + 1) + 1)
            if (r, c) != (row, col)]


def build_region_contract() -> list[dict[str, Any]]:
    return [{
        "region_id": region_id,
        "bounds": region_bounds(region_id),
        "center": region_center(region_id),
        "neighbors": region_neighbors(region_id),
    } for region_id in REGION_IDS]


def validate_region_contract(scenario: dict) -> None:
    if scenario.get("region_contract") != REGION_CONTRACT:
        raise ValueError(f"region_contract must be {REGION_CONTRACT!r}")
    regions = scenario.get("regions")
    expected = build_region_contract()
    if regions != expected:
        raise ValueError("regions do not match the fixed 3x3 bounds, centers, and 8-neighbor topology")
    for group_name in ("platforms", "tasks"):
        group = scenario.get(group_name, [])
        for index, item in enumerate(group):
            path = f"{group_name}[{index}]"
            position = item.get("position", ())
            try:
                x, y = float(position[0]), float(position[1])
            except (TypeError, ValueError, IndexError):
                raise ValueError(f"{path}.position must contain finite x/y coordinates") from None
            if not (0 <= x < 100 and 0 <= y < 100):
                raise ValueError(f"{path}.position must lie in [0, 100)")
            rid = item.get("region_id")
            if item.get("type") == "helicopter" and rid is None:
                if item.get("support_scope") != "global" or item.get("region_center") is not None:
                    raise ValueError(f"{path} global helicopter metadata is invalid")
                continue
            if rid not in REGION_IDS:
                raise ValueError(f"{path}.region_id is invalid")
            if region_id_for_position(item.get("position", ())) != rid:
                raise ValueError(f"{path}.position does not belong to {rid}")
            if item.get("region_center") != region_center(rid):
                raise ValueError(f"{path}.region_center does not match {rid}")
    platforms = scenario.get("platforms", [])
    uavs = [p for p in platforms if p.get("type") == "uav"]
    if len(platforms) != 30 or len(uavs) != 24 or sum(p.get("type") == "helicopter" for p in platforms) != 6:
        raise ValueError("v3 requires 24 UAVs and 6 helicopters")
    helicopter_centers = {tuple(region_center(rid)) for rid in REGION_IDS if rid not in {"r00", "r11", "r22"}}
    helicopters = [p for p in platforms if p.get("type") == "helicopter"]
    if {tuple(map(float, p["position"])) for p in helicopters} != helicopter_centers:
        raise ValueError("the six helicopters must occupy the six non-diagonal region centers")
    counts = {rid: sum(p.get("type") == "uav" and p.get("region_id") == rid for p in platforms) for rid in REGION_IDS}
    expected_counts = {f"r{r}{c}": UAV_COUNTS[r][c] for r in range(3) for c in range(3)}
    if counts != expected_counts:
        raise ValueError("UAV region counts do not match the fixed 2/3/3 matrix")
    tasks = scenario.get("tasks", [])
    if len(tasks) != 45 or sum(t.get("known_initial") is True for t in tasks) != 36 or sum(t.get("known_initial") is False for t in tasks) != 9:
        raise ValueError("v3 requires 36 initial and 9 hidden tasks")
    for rid in REGION_IDS:
        if sum(t.get("region_id") == rid and t.get("known_initial") is True for t in tasks) != 4:
            raise ValueError(f"region {rid} must have exactly four initial tasks")
        if sum(t.get("region_id") == rid and t.get("known_initial") is False for t in tasks) != 1:
            raise ValueError(f"region {rid} must have exactly one hidden task")
