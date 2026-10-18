"""Public-information Greedy, Auction, and candidate-constrained CBBA-lite rules.

All rules rank only legal rows from the supplied shared catalogue. Pair utility
is frozen as ``(1 + priority) * urgency - 0.08*distance - 0.12*energy -
0.20*risk - 0.15*delay - 0.50*switch``. Candidate net utility is the change
in this same public utility for touched tasks between the current owner/queue
and the candidate-simulated owner/queue; NOOP is the current allocation (net
utility zero). Thus reassignment does not earn the task's existing priority a
second time, and an equivalent head dispatch has zero gain. Urgency is
``1 + 1/(1+slack)``;
distance is public straight-line route distance (including a visible depot
stop for unstarted deliveries), energy is estimated from public platform
rates, risk is the public risk at the task location times distance, delay is
estimated completion beyond the visible deadline, and switch is one for a
change of owner or non-head queue placement.  No weights are fitted.

Auction uses synchronous coordinator rounds: each eligible platform offers
its best remaining public platform-task pair, the coordinator awards the
highest bid with stable ID ties, and rounds continue until no bids remain or
the explicit watchdog is reached.  CBBA-lite builds greedy per-platform
bundles and propagates winner vectors over connected public communication
neighbors until stable or its explicit watchdog.  This is a constrained,
catalogue-projected approximation, not full CBBA and not a convergence claim.
"""

from __future__ import annotations

import copy
import json
import math
from collections import deque
from typing import Any, Iterable, Sequence


_COORDINATOR = "n02-uav-1"
_DEFAULT_AUCTION_WATCHDOG = 64
_DEFAULT_CBBA_WATCHDOG = 64
_EPS = 1e-12


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _xy(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        return _number(value.get("x")), _number(value.get("y"))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _number(value[0]), _number(value[1])
    return 0.0, 0.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _noop(row: dict) -> bool:
    action = _mapping(row.get("full_environment_action"))
    return bool(action.get("noop")) or str(action.get("action_type", "")).lower() == "noop" or str(action.get("scope", "")).upper() == "NOOP"


def _action_edges(row: dict) -> list[tuple[str, str]]:
    """Return only platform-task pairs explicitly represented by this action."""
    action = _mapping(row.get("full_environment_action"))
    edges: set[tuple[str, str]] = set()
    for dispatch in _rows(action.get("dispatches")):
        if dispatch.get("platform_id") is not None and dispatch.get("task_id") is not None:
            edges.add((str(dispatch["platform_id"]), str(dispatch["task_id"])))
    for op in _rows(action.get("queue_operations")):
        task = op.get("task_id")
        target = op.get("to_platform")
        if task is not None and target is not None and str(op.get("op", "")).lower() != "swap":
            edges.add((str(target), str(task)))
        if str(op.get("op", "")).lower() == "swap":
            other = op.get("other_task_id")
            source = op.get("from_platform")
            if task is not None and target is not None:
                edges.add((str(target), str(task)))
            if other is not None and source is not None:
                edges.add((str(source), str(other)))
    return sorted(edges)


def _scope_nonempty(context: dict) -> bool:
    if context.get("no_eligible_scope") is True:
        return False
    scope = context.get("affected_scope")
    if isinstance(scope, dict):
        domain = scope.get("affected_task_ids", scope.get("affected_platform_ids"))
        if domain is not None and not domain:
            return False
    return True


def _legal_indices(candidates: Sequence[dict], context: dict) -> list[int]:
    mask = context.get("candidate_mask")
    if mask is not None and len(mask) != len(candidates):
        raise ValueError("candidate_mask length must match candidates")
    return [i for i, row in enumerate(candidates)
            if isinstance(row, dict) and bool(row.get("legal", True)) and (mask is None or bool(mask[i]))]


def _fallback_noop(candidates: Sequence[dict], legal: Sequence[int]) -> int:
    for i in legal:
        if _noop(candidates[i]):
            return i
    raise ValueError("shared legal candidate catalogue must include NOOP")


def _public_tables(observation: dict) -> tuple[dict[str, dict], dict[str, dict], dict[str, list[str]]]:
    platforms = {str(row["id"]): row for row in _rows(observation.get("platforms")) if row.get("id") is not None}
    tasks = {str(row["id"]): row for row in _rows(observation.get("tasks")) if row.get("id") is not None}
    queues = {str(key): [str(item) for item in value] for key, value in _mapping(observation.get("queues")).items() if isinstance(value, list)}
    return platforms, tasks, queues


def _risk_at_task(observation: dict, task: dict) -> float:
    tx, ty = _xy(task.get("position"))
    cells = []
    positioned = []
    for row in _rows(observation.get("environment")):
        risk = max(0.0, _number(row.get("risk_level", row.get("risk", 0.0))))
        if isinstance(row.get("grid_cell"), (list, tuple)) and len(row["grid_cell"]) >= 2:
            cells.append((tuple(int(_number(value)) for value in row["grid_cell"][:2]), risk))
        elif row.get("position") is not None:
            x, y = _xy(row["position"])
            positioned.append((math.hypot(x - tx, y - ty), risk))
    if cells:
        cell_km = max(1e-9, _number(_mapping(observation.get("map")).get("cell_km"), 1.0))
        target_cell = (math.floor(tx / cell_km), math.floor(ty / cell_km))
        matching = [risk for cell, risk in cells if cell == target_cell]
        if matching:
            return max(matching)
    if positioned:
        return min(positioned, key=lambda item: item[0])[1]
    return max(0.0, _number(task.get("risk_level", 0.0)))


def _pair_utility(observation: dict, platforms: dict[str, dict], tasks: dict[str, dict], platform_id: str, task_id: str, *, owner: str | None, queue_position: int | None) -> float:
    platform, task = platforms.get(platform_id), tasks.get(task_id)
    if not platform or not task or platform.get("failed"):
        return -math.inf
    required = "inspect" if task.get("kind") == "inspection" else "deliver"
    if required not in {str(value) for value in platform.get("capabilities", [])}:
        return -math.inf
    px, py = _xy(platform.get("position"))
    tx, ty = _xy(task.get("position"))
    distance = math.hypot(px - tx, py - ty)
    phase = str(task.get("phase", ""))
    depot = None
    if task.get("kind") == "delivery" and phase not in {"in_transit", "to_delivery_site", "unloading", "delivery_confirmed"}:
        depot = next((row for row in _rows(observation.get("depots")) if str(row.get("id")) == str(task.get("depot_id"))), None)
        if depot:
            dx, dy = _xy(depot.get("position"))
            distance = math.hypot(px - dx, py - dy) + math.hypot(dx - tx, dy - ty)
    service = _number(task.get("service_minutes")) if task.get("kind") != "delivery" else _number(task.get("load_minutes"), 1.0) + _number(task.get("unload_minutes"), 1.0)
    completion = _number(observation.get("time")) + distance / max(1e-6, _number(platform.get("speed_km_min", platform.get("speed")), 1.0)) + service
    deadline = _number(task.get("deadline"), _number(observation.get("horizon"), completion))
    slack = max(0.0, deadline - _number(observation.get("time")))
    urgency = 1.0 + 1.0 / (1.0 + slack)
    priority = max(0.0, _number(task.get("priority")))
    energy = distance * max(0.0, _number(platform.get("energy_per_km"))) + service * max(0.0, _number(platform.get("service_energy_per_min")))
    risk = distance * _risk_at_task(observation, task)
    delay = max(0.0, completion - deadline)
    switch = float(owner is not None and str(owner) != platform_id) + float(queue_position is not None and queue_position > 0)
    return (1.0 + priority) * urgency - 0.08 * distance - 0.12 * energy - 0.20 * risk - 0.15 * delay - 0.50 * switch


def _candidate_net_score(row: dict, observation: dict, platforms: dict[str, dict], tasks: dict[str, dict], queues: dict[str, list[str]]) -> tuple[float, list[tuple[str, str]], str | None]:
    action = _mapping(row.get("full_environment_action"))
    edges = _action_edges(row)
    operations = _rows(action.get("queue_operations"))
    if any(str(op.get("op", "")).lower() in {"split", "cooperate"} for op in operations):
        return -math.inf, edges, "unsupported_split_or_cooperate_projection"
    touched = {task for _, task in edges}
    for op in operations:
        for field in ("task_id", "other_task_id"):
            if op.get(field) is not None:
                touched.add(str(op[field]))
    if not touched:
        return 0.0, edges, None
    current_owners: dict[str, str | None] = {}
    current_queues = {pid: list(queue) for pid, queue in queues.items()}
    for task_id in touched:
        task = tasks.get(task_id, {})
        owner = task.get("assignee")
        if owner is None:
            owner = next((pid for pid, queue in current_queues.items() if task_id in queue), None)
        current_owners[task_id] = str(owner) if owner is not None else None
    after_owners = dict(current_owners)
    after_queues = {pid: list(queue) for pid, queue in current_queues.items()}
    for op in operations:
        name = str(op.get("op", "")).lower()
        task_id = str(op.get("task_id", ""))
        if name == "swap":
            other_id = str(op.get("other_task_id", ""))
            left_owner, right_owner = after_owners.get(task_id), after_owners.get(other_id)
            for queue in after_queues.values():
                for index, queued in enumerate(queue):
                    if queued == task_id:
                        queue[index] = other_id
                    elif queued == other_id:
                        queue[index] = task_id
            after_owners[task_id], after_owners[other_id] = right_owner, left_owner
            touched.update((other_id, task_id))
            continue
        target = str(op.get("to_platform", ""))
        for queue in after_queues.values():
            while task_id in queue:
                queue.remove(task_id)
        destination = after_queues.setdefault(target, [])
        anchor = op.get("before_task_id") if name == "insert" else None
        if anchor in destination:
            destination.insert(destination.index(anchor), task_id)
        else:
            destination.append(task_id)
        after_owners[task_id] = target
    for dispatch in _rows(action.get("dispatches")):
        task_id, platform_id = str(dispatch.get("task_id", "")), str(dispatch.get("platform_id", ""))
        for queue in after_queues.values():
            while task_id in queue:
                queue.remove(task_id)
        after_queues.setdefault(platform_id, []).insert(0, task_id)
        after_owners[task_id] = platform_id
        touched.add(task_id)

    def state_utility(task_id: str, owner: str | None, state_queues: dict[str, list[str]]) -> float:
        if owner is None:
            return 0.0
        queue = state_queues.get(owner, [])
        position = queue.index(task_id) if task_id in queue else None
        value = _pair_utility(observation, platforms, tasks, owner, task_id, owner=owner, queue_position=position)
        # A currently infeasible owner is public evidence of an unserved allocation,
        # not an infinite negative score that can make a legal rescue non-finite.
        return value if math.isfinite(value) else 0.0

    before = sum(state_utility(task_id, current_owners.get(task_id), current_queues) for task_id in touched)
    after = sum(state_utility(task_id, after_owners.get(task_id), after_queues) for task_id in touched)
    return after - before, edges, None


def _candidate_score(row: dict, observation: dict, pair_scores: dict[tuple[str, str], float], tasks: dict[str, dict], platforms: dict[str, dict], queues: dict[str, list[str]]) -> tuple[float, list[tuple[str, str]]]:
    score, edges, _reason = _candidate_net_score(row, observation, platforms, tasks, queues)
    return score, edges


def _candidate_tie(row: dict, index: int) -> tuple[str, int]:
    return (str(row.get("candidate_key", row.get("id", index))), index)


def _candidate_coverage(candidates: Sequence[dict], legal: Sequence[int]) -> dict:
    unsupported: dict[str, list[str]] = {}
    for index in legal:
        action = _mapping(candidates[index].get("full_environment_action"))
        for operation in _rows(action.get("queue_operations")):
            name = str(operation.get("op", "")).lower()
            if name in {"split", "cooperate"}:
                unsupported.setdefault(name, []).append(str(candidates[index].get("candidate_key", index)))
    unsupported_keys = sorted({key for values in unsupported.values() for key in values})
    count = len(legal)
    return {
        "legal_candidate_count": count,
        "supported_legal_candidate_count": count - len(unsupported_keys),
        "unsupported_legal_candidate_count": len(unsupported_keys),
        "supported_legal_candidate_fraction": (count - len(unsupported_keys)) / count if count else 1.0,
        "unsupported_candidate_types": {name: sorted(set(keys)) for name, keys in sorted(unsupported.items())},
    }


def _project(candidates: Sequence[dict], legal: Sequence[int], desired: dict[str, str], pair_scores: dict[tuple[str, str], float], observation: dict, tasks: dict[str, dict], platforms: dict[str, dict], queues: dict[str, list[str]], tie_ids: list[str]) -> tuple[int, dict]:
    ranked = []
    unsupported = []
    for i in legal:
        row = candidates[i]
        if _noop(row):
            continue
        score, edges, unsupported_reason = _candidate_net_score(row, observation, platforms, tasks, queues)
        if unsupported_reason:
            unsupported.append(unsupported_reason)
            continue
        coverage = sum(desired.get(task) == platform for platform, task in edges)
        conflict = sum(task in desired and desired[task] != platform for platform, task in edges)
        physical = bool(edges or _rows(_mapping(row.get("full_environment_action")).get("queue_operations")))
        ranked.append((-coverage, conflict, -score, not physical, _candidate_tie(row, i), i, score, edges))
    if not ranked or not desired:
        noop_index = _fallback_noop(candidates, legal)
        status = "unsupported_candidate_projection" if unsupported and not ranked else "no_desired_assignment"
        return noop_index, {"matched_pairs": [], "desired_pairs": sorted((platform, task) for task, platform in desired.items()), "projection_status": status, "projection_reason": sorted(set(unsupported))}
    ranked.sort(key=lambda item: item[:6])
    chosen = ranked[0]
    matched = sorted((platform, task) for platform, task in chosen[7] if desired.get(task) == platform)
    if not matched:
        noop_index = _fallback_noop(candidates, legal)
        return noop_index, {"matched_pairs": [], "desired_pairs": sorted((platform, task) for task, platform in desired.items()), "projection_status": "candidate_projection_miss", "projection_reason": "no catalogue action represents a desired pair", "tie_break_ids": list(tie_ids)}
    if chosen[6] <= _EPS:
        noop_index = _fallback_noop(candidates, legal)
        return noop_index, {"matched_pairs": matched, "desired_pairs": sorted((platform, task) for task, platform in desired.items()), "projection_status": "nonpositive_incremental_public_utility", "score": chosen[6], "tie_break_ids": list(tie_ids)}
    index = chosen[5]
    status = "matched"
    return index, {"matched_pairs": matched, "desired_pairs": sorted((platform, task) for task, platform in desired.items()), "projection_status": status, "candidate_key": str(candidates[index].get("candidate_key", index)), "score": chosen[6], "tie_break_ids": list(tie_ids)}


def _neighbors(observation: dict, platforms: dict[str, dict]) -> dict[str, list[str]]:
    graph = {pid: set() for pid in platforms}
    for link in _rows(observation.get("communication")):
        left, right = str(link.get("source", "")), str(link.get("target", ""))
        quality = _number(link.get("quality"))
        if left in graph and right in graph and left != right and bool(link.get("connected", quality >= 0.3)) and quality > 0.0:
            graph[left].add(right)
            graph[right].add(left)
    return {key: sorted(value) for key, value in graph.items()}


def _coordinator_reachable(neighbors: dict[str, list[str]], platform_id: str) -> bool:
    if platform_id == _COORDINATOR:
        return True
    if _COORDINATOR not in neighbors:
        return False
    seen, queue = {_COORDINATOR}, deque([_COORDINATOR])
    while queue:
        node = queue.popleft()
        for nxt in neighbors.get(node, []):
            if nxt not in seen:
                if nxt == platform_id:
                    return True
                seen.add(nxt)
                queue.append(nxt)
    return False


def _eligible_pairs(candidates: Sequence[dict], legal: Sequence[int], platforms: dict[str, dict], tasks: dict[str, dict], queues: dict[str, list[str]], observation: dict, reachable: set[str] | None = None) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for i in legal:
        if _noop(candidates[i]):
            continue
        row = candidates[i]
        net, edges, unsupported = _candidate_net_score(row, observation, platforms, tasks, queues)
        if unsupported or not edges or not math.isfinite(net) or net <= _EPS:
            continue
        value = net / len(edges)
        for platform_id, task_id in edges:
            if reachable is not None and platform_id not in reachable:
                continue
            pair = (platform_id, task_id)
            result[pair] = max(result.get(pair, -math.inf), value)
    return result


def _greedy(pair_scores: dict[tuple[str, str], float], candidates: Sequence[dict], legal: Sequence[int], observation: dict, tasks: dict[str, dict], platforms: dict[str, dict], queues: dict[str, list[str]]) -> tuple[int, dict, dict]:
    ordered = sorted(pair_scores.items(), key=lambda item: (-item[1], item[0][1], item[0][0]))
    desired: dict[str, str] = {}
    used_platforms: set[str] = set()
    for (platform, task), _score in ordered:
        if task not in desired and platform not in used_platforms:
            desired[task] = platform
            used_platforms.add(platform)
    index, projection = _project(candidates, legal, desired, pair_scores, observation, tasks, platforms, queues, [pid for pid in used_platforms])
    scores = {f"{platform}|{task}": value for (platform, task), value in sorted(pair_scores.items())}
    return index, projection, scores


def _auction(pair_scores: dict[tuple[str, str], float], candidates: Sequence[dict], legal: Sequence[int], observation: dict, tasks: dict[str, dict], platforms: dict[str, dict], queues: dict[str, list[str]], context: dict) -> tuple[int, dict, dict]:
    watchdog = max(1, int(context.get("auction_watchdog_rounds", _DEFAULT_AUCTION_WATCHDOG)))
    remaining = dict(pair_scores)
    assigned: dict[str, str] = {}
    used_platforms: set[str] = set()
    bids_receipt = []
    rounds = 0
    converged = False
    while rounds < watchdog:
        offers = []
        for platform in sorted({platform for platform, _ in remaining} - used_platforms):
            options = [(score, task) for (pid, task), score in remaining.items() if pid == platform and task not in assigned]
            if options:
                score, task = sorted(options, key=lambda item: (-item[0], item[1]))[0]
                offers.append({"platform_id": platform, "task_id": task, "bid": score})
        rounds += 1
        bids_receipt.append(offers)
        if not offers:
            converged = True
            break
        winner_by_task: dict[str, dict] = {}
        for offer in offers:
            prior = winner_by_task.get(offer["task_id"])
            if prior is None or (-offer["bid"], offer["platform_id"]) < (-prior["bid"], prior["platform_id"]):
                winner_by_task[offer["task_id"]] = offer
        awards = sorted(winner_by_task.values(), key=lambda row: (row["task_id"], row["platform_id"]))
        awarded_platforms = set()
        for award in awards:
            if award["platform_id"] in awarded_platforms:
                continue
            assigned[award["task_id"]] = award["platform_id"]
            awarded_platforms.add(award["platform_id"])
        used_platforms.update(awarded_platforms)
        # Unsuccessful bidders withdraw this task and may bid again next round.
        for offer in offers:
            if assigned.get(offer["task_id"]) != offer["platform_id"]:
                remaining.pop((offer["platform_id"], offer["task_id"]), None)
        if not ({platform for platform, _ in remaining} - used_platforms):
            converged = True
            break
    else:
        rounds = watchdog
    receipts = {"bids": bids_receipt, "awards": [[task, assigned[task]] for task in sorted(assigned)]}
    payload_bytes = sum(len(_canonical_bytes(offer)) for offers in bids_receipt for offer in offers) + len(_canonical_bytes(receipts["awards"]))
    # Bid vector is one packet per participating platform and round; awards are a single batch packet.
    message_count = sum(len(offers) for offers in bids_receipt) + (1 if assigned else 0)
    tie_ids = sorted({row["platform_id"] for offers in bids_receipt for row in offers} | set(assigned.values()))
    index, projection = _project(candidates, legal, assigned, pair_scores, observation, tasks, platforms, queues, tie_ids)
    return index, projection, {"bids": receipts, "rounds": rounds, "conflicts": sum(max(0, sum(1 for offer in offers if offer["task_id"] == task) - 1) for offers in bids_receipt for task in {offer["task_id"] for offer in offers}), "converged": converged, "message_count": message_count, "payload_bytes": payload_bytes, "tie_break_ids": tie_ids}


def _cbba_lite(pair_scores: dict[tuple[str, str], float], candidates: Sequence[dict], legal: Sequence[int], observation: dict, tasks: dict[str, dict], platforms: dict[str, dict], queues: dict[str, list[str]], context: dict) -> tuple[int, dict, dict]:
    watchdog = max(1, int(context.get("cbba_watchdog_rounds", _DEFAULT_CBBA_WATCHDOG)))
    neighbors = _neighbors(observation, platforms)
    nodes = sorted(platforms)
    bundle_capacity = max(1, min(len(tasks) or 1, int(context.get("cbba_bundle_capacity", max(1, len(tasks))))))
    bundles: dict[str, list[tuple[str, float]]] = {pid: [] for pid in nodes}
    known: dict[str, dict[str, tuple[str, float]]] = {pid: {} for pid in nodes}
    rounds = 0
    converged = False
    conflicts = 0
    message_count = 0
    payload_bytes = 0

    def marginal(platform: str, task: str, bundle: list[tuple[str, float]]) -> float:
        base = pair_scores.get((platform, task), -math.inf)
        if not math.isfinite(base):
            return -math.inf
        if not bundle:
            return base
        previous_task = tasks.get(bundle[-1][0], {})
        next_task = tasks.get(task, {})
        ax, ay = _xy(previous_task.get("position"))
        bx, by = _xy(next_task.get("position"))
        platform_row = platforms.get(platform, {})
        extra_distance = math.hypot(ax - bx, ay - by)
        extra_energy = extra_distance * max(0.0, _number(platform_row.get("energy_per_km")))
        return base - 0.08 * extra_distance - 0.12 * extra_energy

    def resolve(entries: Iterable[tuple[str, tuple[str, float]]]) -> dict[str, tuple[str, float]]:
        result: dict[str, tuple[str, float]] = {}
        for task, candidate in entries:
            incumbent = result.get(task)
            if incumbent is None or (-candidate[1], candidate[0]) < (-incumbent[1], incumbent[0]):
                result[task] = candidate
        return result

    # Each node greedily extends an ordered bundle by positive public marginal gain.
    for platform in nodes:
        while len(bundles[platform]) < bundle_capacity:
            used = {task for task, _ in bundles[platform]}
            options = [(marginal(platform, task, bundles[platform]), task)
                       for pid, task in pair_scores if pid == platform and task not in used]
            options = [item for item in options if item[0] > _EPS]
            if not options:
                break
            gain, task = sorted(options, key=lambda item: (-item[0], item[1]))[0]
            bundles[platform].append((task, gain))
        known[platform] = {task: (platform, bid) for task, bid in bundles[platform]}

    # Synchronous neighbor exchange, suffix release after a lost conflict, then greedy rebuild.
    while rounds < watchdog:
        rounds += 1
        prior_bundles = {pid: list(bundle) for pid, bundle in bundles.items()}
        prior_known = {pid: dict(vector) for pid, vector in known.items()}
        next_bundles: dict[str, list[tuple[str, float]]] = {}
        next_known: dict[str, dict[str, tuple[str, float]]] = {}
        round_conflicts = 0
        for platform in nodes:
            advertised = dict(prior_known.get(platform, {}))
            for neighbor in neighbors.get(platform, []):
                for task, value in prior_known.get(neighbor, {}).items():
                    incumbent = advertised.get(task)
                    if incumbent is None or (-value[1], value[0]) < (-incumbent[1], incumbent[0]):
                        advertised[task] = value
            # Detect conflicting claims visible to this platform before resolution.
            claims: dict[str, set[str]] = {}
            for sender in [platform, *neighbors.get(platform, [])]:
                for task, (owner, _bid) in prior_known.get(sender, {}).items():
                    claims.setdefault(task, set()).add(owner)
            round_conflicts += sum(len(owners) > 1 for owners in claims.values())
            bundle = list(prior_bundles[platform])
            lost = next((index for index, (task, _bid) in enumerate(bundle)
                         if task in advertised and advertised[task][0] != platform), None)
            if lost is not None:
                bundle = bundle[:lost]
            # Release own claims from the removed suffix before rebuilding.
            owned = {task for task, _bid in bundle}
            advertised = {task: value for task, value in advertised.items()
                          if value[0] != platform or task in owned}
            while len(bundle) < bundle_capacity:
                used = {task for task, _bid in bundle}
                options = []
                for pid, task in pair_scores:
                    if pid != platform or task in used:
                        continue
                    incumbent = advertised.get(task)
                    if incumbent is not None and incumbent[0] != platform:
                        continue
                    gain = marginal(platform, task, bundle)
                    if gain > _EPS:
                        options.append((gain, task))
                if not options:
                    break
                gain, task = sorted(options, key=lambda item: (-item[0], item[1]))[0]
                bundle.append((task, gain))
            next_bundles[platform] = bundle
            own_awards = {task: (platform, bid) for task, bid in bundle}
            for task, value in own_awards.items():
                incumbent = advertised.get(task)
                if incumbent is None or (-value[1], platform) < (-incumbent[1], incumbent[0]):
                    advertised[task] = value
            next_known[platform] = advertised
        changed = next_bundles != prior_bundles or next_known != prior_known
        bundles, known = next_bundles, next_known
        directed_edges = [(left, right) for left in nodes for right in neighbors.get(left, []) if right in nodes]
        message_count += len(directed_edges)
        payload_bytes += sum(
            len(_canonical_bytes([[task, value[0], value[1]] for task, value in sorted(known[left].items())]))
            for left, _right in directed_edges
        )
        conflicts += round_conflicts
        if not changed:
            converged = True
            break
    coordinator = _COORDINATOR if _COORDINATOR in platforms else (sorted(platforms)[0] if platforms else None)
    if coordinator is not None:
        component = {coordinator}
        frontier = deque([coordinator])
        while frontier:
            current = frontier.popleft()
            for neighbor in neighbors.get(current, []):
                if neighbor not in component:
                    component.add(neighbor)
                    frontier.append(neighbor)
        # Only the coordinator's received consensus vector is available for projection.
        winner = known.get(coordinator, {})
    else:
        component = set()
        winner = {}
    assigned = {task: platform for task, (platform, _score) in winner.items() if platform in component}
    tie_ids = sorted({platform for platform, _task in pair_scores})
    index, projection = _project(candidates, legal, assigned, pair_scores, observation, tasks, platforms, queues, tie_ids)
    return index, projection, {"protocol": "candidate_constrained_bundle_consensus_lite/1", "bundle_constraint": f"ordered public candidate edges, capacity={bundle_capacity}; conflict loss releases suffix and greedily rebuilds", "bundles": {pid: [[task, bid] for task, bid in rows] for pid, rows in sorted(bundles.items())}, "winner_vector": [[task, platform, score] for task, (platform, score) in sorted(winner.items())], "coordinator_id": coordinator, "coordinator_component_platform_ids": sorted(component), "rounds": rounds, "conflicts": conflicts, "converged": converged, "message_count": message_count, "payload_bytes": payload_bytes, "tie_break_ids": tie_ids, "connected_neighbors": neighbors}


def select_rule(method_id: str, observation: dict, candidates: Sequence[dict], context: dict | None = None) -> dict:
    """Select one legal shared catalogue row using public inputs only.

    ``context`` may carry ``candidate_mask``, public scope metadata, and
    watchdog limits. No environment object or private event/label field is
    accepted or inspected. Protocol message counts are separate from simulator
    command-delivery messages already reflected in environment reward.
    """
    if not isinstance(observation, dict) or not isinstance(candidates, Sequence):
        raise TypeError("observation and candidates are required")
    context = _mapping(context)
    method = str(method_id).lower().replace("-", "_")
    aliases = {"greedy": "greedy", "auction": "auction", "cbba_lite": "cbba_lite", "cbbalite": "cbba_lite"}
    if method not in aliases:
        raise ValueError("method_id must be greedy, auction, or cbba_lite")
    method = aliases[method]
    legal = _legal_indices(candidates, context)
    noop_index = _fallback_noop(candidates, legal)
    platforms, tasks, queues = _public_tables(observation)
    neighbors = _neighbors(observation, platforms)
    reachable = {pid for pid in platforms if _coordinator_reachable(neighbors, pid)}
    pair_scores = _eligible_pairs(candidates, legal, platforms, tasks, queues, observation,
                                  reachable if method == "auction" else None)
    tie_ids: list[str] = []
    rounds = conflicts = messages = payload_bytes = 0
    converged: bool | None = True
    details: dict[str, Any]
    if not pair_scores or not _scope_nonempty(context):
        selected_index = noop_index
        projection = {"projection_status": "no_eligible_reconstruction_scope" if not _scope_nonempty(context) else "no_feasible_candidate_pairs", "matched_pairs": [], "desired_pairs": []}
        details = {}
        decision_reason = projection["projection_status"]
    elif method == "greedy":
        selected_index, projection, details = _greedy(pair_scores, candidates, legal, observation, tasks, platforms, queues)
        tie_ids = list(projection.get("tie_break_ids", []))
        decision_reason = "highest_public_immediate_utility_projection"
        converged = None
    elif method == "auction":
        selected_index, projection, details = _auction(pair_scores, candidates, legal, observation, tasks, platforms, queues, context)
        rounds, conflicts, messages, payload_bytes = details["rounds"], details["conflicts"], details["message_count"], details["payload_bytes"]
        tie_ids = details["tie_break_ids"]
        converged = details["converged"]
        decision_reason = "multi_round_public_auction_projection" if projection.get("projection_status") == "matched" else "auction_candidate_projection_miss"
    else:
        selected_index, projection, details = _cbba_lite(pair_scores, candidates, legal, observation, tasks, platforms, queues, context)
        rounds, conflicts, messages, payload_bytes = details["rounds"], details["conflicts"], details["message_count"], details["payload_bytes"]
        tie_ids = details["tie_break_ids"]
        converged = details["converged"]
        decision_reason = "cbba_lite_neighbor_consensus_projection" if projection.get("projection_status") == "matched" else "cbba_lite_candidate_projection_miss"
    if selected_index not in legal:
        selected_index = noop_index
        decision_reason = "projection_not_legal_noop_fallback"
    selected = candidates[selected_index]
    receipt = {
        "schema": "public-rule-selector/1", "method_id": method,
        "formula": "(1+priority)*(1+1/(1+slack))-0.08*distance-0.12*energy-0.20*risk-0.15*delay-0.50*switch",
        "candidate_count": len(candidates), "legal_candidate_count": len(legal),
        "candidate_coverage": _candidate_coverage(candidates, legal),
        "eligible_pair_count": len(pair_scores), "candidate_key": str(selected.get("candidate_key", selected.get("id", selected_index))),
        "selected_from_catalogue": True,
    }
    protocol = details if method != "greedy" else {"pair_scores": details, "tie_break_ids": tie_ids}
    return {
        "method_id": method,
        "candidate_index": int(selected_index),
        "candidate_key": receipt["candidate_key"],
        "selected_candidate_key": receipt["candidate_key"],
        "full_environment_action": copy.deepcopy(selected.get("full_environment_action")),
        "selected_full_environment_action": copy.deepcopy(selected.get("full_environment_action")),
        "decision_reason": decision_reason,
        "score": protocol.get("pair_scores", protocol.get("bids", protocol.get("winner_vector"))),
        "candidate_score_or_bid": protocol.get("pair_scores", protocol.get("bids", protocol.get("winner_vector"))),
        "bids": protocol.get("bids", {}),
        "rule_protocol_message_count": int(messages),
        "communication_messages": int(messages),
        "protocol_payload_bytes": int(payload_bytes),
        "rounds": int(rounds), "conflicts": int(conflicts), "converged": converged,
        "tie_break_ids": tie_ids,
        "projection_receipt": projection,
        "rule_receipt": receipt,
        "protocol_receipt": protocol,
    }


__all__ = ["select_rule"]
