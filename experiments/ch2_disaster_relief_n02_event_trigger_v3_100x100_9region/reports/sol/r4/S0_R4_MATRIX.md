# S0 R4 independent review

**Decision: REPAIR. A PASS; all seven S0 execution links pass, but R4 full selection-plan queue projection disagrees with execution. S1 entry remains blocked; S2/S3 blocked.**

Same-family independent-context Sol High review, provisional for S0 only; not external certification. Reviewed source and evidence unchanged. No training. Label recomputation uses the reviewer's script and never calls the producer oracle.

| Requirement | Result | Evidence / independent verification |
|---|---|---|
| Immutable bytes | PASS | 93 source and 42 evidence entries verified before/after; expected source manifest digest |
| Intended R3→R4 code diff | PASS | Only run_v3_mechanism.py and test_v3_mechanism_evidence.py changed among source manifest entries |
| A: 30/45/9 contract | PASS | Five wrappers; hidden coordinates, region metadata/neighbors, 24 UAV matrix, global six helicopters, map, IDs |
| A: actual backlog C1 five-variant replay | PASS | Exact frozen public-input and queue equality; no hidden/future/preset interference |
| A: public positive control | PASS with scope limit | Priority changes public input/hash; queue unchanged. This demonstrates input sensitivity, not output reordering. |
| B1–B5 | PASS | Eligibility, trigger, 2 legal locals, public preplanned selector requests local, repair keeps complete action |
| B6 actual selected mutation | PASS | task05 owner UAV1→UAV2; source/destination queues change |
| B7 labels | PASS | All 3×30 steps replay; all 12 task labels, 8 heads and NOOP deltas recomputed with unknown masks, energy endpoint checks, raw reward sums |
| R4 public-only projection inputs | PASS | Static helper dependency audit and isolated helper replay without env/labels/private state |
| R4 selection before branch outcomes | PASS with assurance limit | Plan write, bound REQUEST write, rule write precede first branch loop; candidate selection not reassigned by branch results |
| R4 key/catalog/branch retention | PASS | Same 3 catalog keys and raw trajectories as R3; repeat dispatch retained and false |
| R4 projected owners | PASS | Projected task05 owner matches actual UAV2 |
| R4 complete projected queue order | **FAIL** | Projected UAV2 [05,06] versus raw/replayed [06,05] |
| C/S1 | NOT_RUN / entry blocked | Requires B repair and new immutable acceptance |
| 2×2 spatial causality | NOT_RUN | Priority fixture has no patch-on/off pair |
| S2/S3 | BLOCKED | No GPU or world-model/PPO evidence in this freeze |

## Blocking finding

SELECTION_PLAN.json `/candidate_projections/2/projected_owner_queue_state/queues/n02-uav-2` records `[n02-task-05,n02-task-06]`. SELECTED_ACTION_CHAIN.json `/action_audit/0/owner_queue_after/queues/n02-uav-2` and the time-4 raw `queue_operation.after_queues` both record `[n02-task-06,n02-task-05]`. The independent environment replay reproduces the latter.

The projector inserts every dispatched task at queue head. Runtime transfer appends task05, and explicit dispatch starts its mission without reordering that persistent queue. The selected owner mutation and global physical difference are real; this resolves the R3 execution defect. The new full queue projection remains inaccurate, and a queue-only dispatch could therefore receive a false mutation flag. Repair the public projector/predicate against runtime semantics in a new immutable attempt, including an already-owned non-head dispatch witness. Do not modify R3 or R4.

| Branch | Energy | Utility | Owner changes | Switches |
|---|---:|---:|---:|---:|
| event-action-e8d2b24cc155ee9ac0690317 | 8.907168495594 | 3.811256863573 | 0 | 0 |
| event-action-96db627bb448c071b82454be | 8.907168495594 | 3.811256863573 | 0 | 0 |
| event-action-e7ec1b562b5056f65f3012a0 | 8.940553549137 | 3.690505699868 | 1 | 1 |

Selected versus NOOP energy delta: 0.03338505354221333; utility delta: -0.12075116370469985. Physical movement differs even after removing task IDs. This demonstrates a real consequence, not improved utility or spatial-patch causality.

## Scope and provenance limits

Tasks09–12 remain unresolved at t34; on-time/delay masks stay invalid. Final R4 log contains 111 passed, 3 skipped, 2 cache permission warnings (33.24s). R3's reported initial collection-failure stdout remains lost and was not reconstructed; the R3 REPAIR report is unchanged. Mojibake path strings in REQUEST/logs are presentation limits; wrapper bytes bind by the verified SHA256. Static file-write ordering is not external trusted timestamp evidence.

## Hashes

- Source manifest: `7589449038fbfe8c5ae7601f27fd94c5064f04eac6fc924bdb282c3723f3cb75`
- Evidence manifest: `32693d6d23ff619e24778679dd1811b5c36f251039fc5a0f7cfe190b644c4b4a`
- Review script: `c7b5426bf26d418a9b681987dcfa60e1599ddc21960f2e7ba856209ef8feb397`
- R3→R4 source diff: `0d4db7aeb90b21adb6e3df90676c7b2a41d3d88c8f837fa3103dfdf8f1bab88c`

| Evidence | SHA256 |
|---|---|
| input-01/mechanism-d225db2ae58d4d32845981685791215c/SELECTION_PLAN.json | `7d8d524b35ab04819784464e6fd4240f488f948678a4016d7398517a530b7031` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/REQUEST.json | `8bd4f9f2f30ae7937a529be7baec051d7baba3d0a763f6b3264e3a7a0302cd5d` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/SELECTION_RULE.json | `316b35bef8d0609c003707839c0353d25bc1235dd7ccbbaa0e9f42809b02b252` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/SELECTED_ACTION_CHAIN.json | `28558ed0957dbd6cd37d9a54907515961787ed3aa89a966f8ebc316b4393e579` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/WINDOW.json | `820f02f4d4f419a06f012343008dd80e7cba0c0924f426f72e15dbf25b2133a1` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/BRANCH_EVIDENCE.json | `309b0529535694370e922284af68e3086fca7f15a980a9ef87edeff62229b570` |
| input-01/mechanism-d225db2ae58d4d32845981685791215c/PRODUCER_LABELS_FOR_REVIEW.json | `730c68af6328046ddefc08dd3b0c09ea1273a63a7cfeff181b10d13cabdeacc3` |
| input-02/fc9b25025ecf4d788492b998ab64bdf7/REPLAY_INDEX.json | `8baa49dd0d700851342dd6358bd86a5cd4dba489f39a1660d78f60760985cd54` |
| input-00/pytest.log | `757d9b59c87eb68ee2a29d42be72b59aa7b08d55eebb2b8a5d32911d54104aa1` |

Full checks: S0_R4_REVIEW.json. Independent raw values: INDEPENDENT_RAW_RECOMPUTATION.json. Audit script and final stdout are retained beside reviews/.
