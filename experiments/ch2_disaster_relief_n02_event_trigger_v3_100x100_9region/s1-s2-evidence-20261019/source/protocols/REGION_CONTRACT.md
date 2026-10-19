# N02 v3 Region Contract

The v3 scenario uses `relief-engineering/2` with `relief-regions-3x3-v1`. The map remains the existing 100 by 100 grid with 10,000 cells. Region assignment uses global coordinates and half-open bounds `[0,33)`, `[33,66)`, and `[66,100)` on each axis. Region IDs are `r00` through `r22`; adjacency is eight-connected, including diagonal neighbors.

The UAV region matrix is fixed and is not rotated by seed:

```text
2 3 3
3 2 3
3 3 2
```

There are 24 UAVs and six helicopters. Helicopters sit at the centers of the six non-diagonal regions, use `region_id: null`, and have `support_scope: "global"`. Platforms and tasks carry `region_id` and `region_center`; `local` remains a compatibility field and does not define v3 ownership or C1 eligibility.

Each region contains four public initial tasks and one hidden task, for 36 public tasks and 9 hidden tasks total. Public C1 may use only initial tasks and public platform, capability, distance, time, energy, capacity, and stock information. The C1 receipt includes the global queue, per-region task and UAV distributions, unassigned task reasons, source identity, public-input hash, and output hash. Hidden tasks and event tape are outside the C1 input.

`region_contract.build_region_contract()` returns the canonical region records. `region_contract.region_id_for_position(position)` maps a global coordinate to its canonical region. `region_scenarios.build_scenario(...)` returns an event wrapper with `base_scenario`, `queue_plan`, `event_tape`, `event_tape_id`, parent identity, split, condition, and seed variant. `build_scenario_set()` creates at least four training and two development parents. The event tape is deterministic and can be supplied to `build_scenario` to pair policy or environment comparisons. Spatial events remain 2 by 2 patches fully inside the named macro region.
