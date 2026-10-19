# S0 R3 independent review

**Decision: REPAIR. A PASS; B stops at link 6. S1 entry blocked; S2/S3 blocked.**

Read-only independent context within the GPT-6.1 Sol family; this is not external certification. No reviewed source edits or training. The reviewer never calls event_oracle.recompute_consequence_labels.

| Node / requirement | Result | Independently checked evidence |
|---|---|---|
| Immutable source/evidence | PASS | All 93 source and 42 evidence manifest entries hash verified before/after |
| A: 30 platforms, 45 tasks, 9 regions | PASS | All five wrappers: 24 UAV matrix, 6 global helicopters, 36 initial + 9 hidden coordinates, half-open membership, unique IDs, neighbors, map |
| A: actual backlog C1 boundary | PASS | All five frozen public inputs and queues exactly regenerate with schedule_backlog=True |
| A: noninterference / public control | PASS | Hidden-task, future-tape and preset-queue variants preserve public input + queues; public priority changes input digest while queue stays equal |
| B1: local eligibility | PASS | Replayed t4 scope local_eligible=true |
| B2: event trigger | PASS | Frozen threshold 0 diagnostic, public priority change, triggered=true |
| B3: legal local candidates | PASS with limitation | 2 nominal legal local candidates; only 1 creates effective mutation |
| B4: policy request local | PASS (diagnostic only) | Frozen first-legal-local selector requests LOCAL_REPAIR; no trained actor claim |
| B5: repair preserves request | PASS | Requested/repaired/executed full actions equal, all steps postrepair legal |
| B6: selected owner/queue changes | **FAIL** | Selected key 96db627bb448c071b82454be: owner_changes={}, queue_changes={}; same owner dispatch |
| B7: raw independent labels | PASS as diagnostic computation | Every branch replayed 30 steps; all 12 task labels, eight model heads, NOOP deltas, raw rewards, energy endpoints, unknown masks compared with producer |
| C / S1 9-region executed mechanism | NOT_RUN / BLOCKED | S0 is 6-platform/12-task diagnostic; A is contract/C1 only |
| 2x2 spatial causal witness | NOT_RUN | S0 event tape is priority_change only; no paired patch-on/off evidence |
| S2 / S3 | BLOCKED | Require repaired B plus executed C and later independent gates |

## Blocking finding

Frozen selection picks event-action-96db627bb448c071b82454be, which dispatches n02-task-05 to its existing owner n02-uav-1. The first raw owner/queue before/after states are equal. The selected branch has zero owner-change and switch events, and exactly the NOOP energy, utility and physical movement path after removing task IDs. The unselected third candidate has one real owner change and different global energy, but cannot replace the selected result after execution. Preserve R3 as failed; repair in a new immutable attempt.

| Candidate | Energy | Utility | Owner changes | Switches |
|---|---:|---:|---:|---:|
| event-action-e8d2b24cc155ee9ac0690317 | 8.907168495594 | 3.811256863573 | 0 | 0 |
| event-action-96db627bb448c071b82454be | 8.907168495594 | 3.811256863573 | 0 | 0 |
| event-action-e7ec1b562b5056f65f3012a0 | 8.940553549137 | 3.690505699868 | 1 | 1 |

The third candidate has a different physical path after removing task IDs and increases global energy by 0.03338505354221333. Thus the catalog contains a real physical alternative, while the frozen selected chain still fails link 6.

## Unknowns and test-log limitation

At t34 tasks n02-task-09 through n02-task-12 are unresolved. Their on-time and delay values remain unknown; all-task on-time and mean-delay labels are invalid. The observed on-time value 1.0 is a partial value and must not be advertised as a fully valid all-task metric. Recomputed raw reward sums and endpoint energy agree for all three branches.

The retained final pytest log hash and literal result verify 111 passed, 3 skipped (21.68s). The executor reports that an earlier invocation without PYTHONPATH failed collection and its stdout was overwritten by the final log. Original failure stdout is unavailable. The external correction note is a provenance disclosure, not a reconstructed original log, and is outside the frozen R3 bytes.

## Hashes

- Source manifest: `8edae5fb9e414e5cd94f2083ecc339a815ee2139357e0c03a0b466985307070d`
- Evidence manifest: `d21096f019ac4db3a4f7edcd73e2cab29a43115616ca1be8fea20a38e96e92f8`
- External correction note: `542f9452c2db204cf8b2f734d5f9c7b30b6d4b736eaccf48579f7d7be75a073a`
- Audit script: `ce7c988b059cc8c56bac87574ad101be1a819cef25516eaccf2e20e94c92d7ba`

| Evidence | SHA256 |
|---|---|
| input-01/SELECTION_RULE.json | `eb91d8c6916897f043ce5e922594a49769badd331301254aa6ba68aca2452578` |
| input-01/SELECTED_ACTION_CHAIN.json | `b8c9154d78c64e56dd8e9955708cc6143b1823d67305f554b1840a93aa6883f3` |
| input-01/WINDOW.json | `820f02f4d4f419a06f012343008dd80e7cba0c0924f426f72e15dbf25b2133a1` |
| input-01/BRANCH_EVIDENCE.json | `309b0529535694370e922284af68e3086fca7f15a980a9ef87edeff62229b570` |
| input-01/PRODUCER_LABELS_FOR_REVIEW.json | `730c68af6328046ddefc08dd3b0c09ea1273a63a7cfeff181b10d13cabdeacc3` |
| input-02/REPLAY_INDEX.json | `bbe5b969ec47e42f45848db04763572040c42b3633a5d2e81947e734776cbc74` |
| input-03/pytest.log | `0d59aed521e575d86681c1b1615fb1537fd527de3584b1f5a43f457f4401611a` |

Full per-item checks are in S0_R3_REVIEW.json; raw independent values are in INDEPENDENT_RAW_RECOMPUTATION.json. The successful diagnostic recomputation does not retroactively erase prior failed attempts or authorize S1.
