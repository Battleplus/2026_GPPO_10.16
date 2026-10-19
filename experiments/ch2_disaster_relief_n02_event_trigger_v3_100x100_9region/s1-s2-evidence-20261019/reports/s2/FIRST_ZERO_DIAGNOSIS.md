# S2 First-Zero Diagnosis

**Result:** the earliest demonstrated failure is upstream of actor preference. In the `Periodic-G` training witness, two legal local-repair candidates exist at `n02-v3-train-02-new_arrival`, t=10, but the trigger is false and the high-level mask exposes only `NOOP`. No local candidate can reach the actor as a selectable action. Separately, the `Event-G` training trajectories contain no legal local-repair candidate at all. The two conditions must not be collapsed into one explanation.

## Observed evidence

- Frozen run identity: attempt `99a7e67bc1684fcb94a231e8c72a728e`, release `n02-v3-s2-bd8054b27c114c9fafffd77734b7ee8d`, status `FROZEN_REAL_RUN_PENDING_INDEPENDENT_REVIEW`. The frozen `RESULT_MANIFEST.json` SHA-256 is `21bbcd8769810d2988ed1edf79976107c8d8696b15cdd4565677cc748aa0d35a`, matching the freeze receipt.
- `Periodic-G`, training parent `n02-v3-train-02-new_arrival`, t=10: the raw audit found 2 legal `LOCAL_REPAIR` candidates. Trigger gamma is approximately `0.0152832093`, below threshold `0.0232141515`; `triggered=false`. The high-level mask is `[true,false,false,false]`, and the candidate mask is `[true,false,false]` (NOOP plus the two legal local candidates). The selected action is NOOP; effective local repair count is zero. Thus the witness and legal catalog exist, but trigger/mask gating blocks both candidates before actor choice.
- `Periodic-G` actor evidence: 28 PPO updates executed, but 0 nonzero actor gradients; the actor did not change and initial/final actor digests are identical (`5c712452...ac48f`). This establishes no observed actor learning in the audited run. It is downstream context, not the earliest failure for this witness.
- `Event-G`: its actual training rollout records contain 0 legal local candidates. At the same train parent/time snapshot, gamma is `0.0214396162`, below `0.0232141515`; trigger is false, the high-level mask is `[true,false,false,false]`, and the executed scope is NOOP. The run therefore supplies no actor-level comparison among local alternatives. A static scenario/witness available outside this recorded trajectory is not evidence that the sampled training rollout contained a legal local choice.
- The two development episodes are paired on initial public observation, initial owner/queue state, and event tape. Recomputed means: utility is `30.7325154383` for Event-G versus `30.9993993377` for Periodic-G (difference `-0.2668838993`); on-time rate is `0.8` for both; planning calls are 60 for both; communication messages are 38 versus 36; reconstruction size is 1 versus 0. Event-G has one global reconstruction; Periodic-G has none. The existing audit verdict is provisional FAIL, with utility and cost gates failing, while on-time and paired-update checks pass.
- Metric coverage is incomplete: safety risk is null because raw move records omit risk values, and decision latency is null because transitions have no per-decision timer. Null is unknown, not zero. The audit also marks cross-region counts and local-action success as unavailable/null in the means. Do not infer a safety comparison from these artifacts.

## Failure localization

For the Periodic-G repair witness, the earliest observed inaccessible layer is **trigger eligibility / high-level action masking**. Scenario and catalog generation produced legal candidates; trigger evaluation made them ineligible; the mask then removed access before actor selection. The actor's zero-gradient evidence is a separate training-path defect or degenerate objective signal, but it cannot explain why these two candidates were unavailable at this decision.

For Event-G, the earliest observed absence is **training trajectory/catalog opportunity**: no legal local candidate appears in the recorded training rollout. At t=10, the trigger is also false. These observations do not establish whether the upstream cause is event scope classification, scenario sampling, or another data-generation condition. The run cannot support a claim about Event-G's learned local-repair preference because no legal local alternative was available in its training trajectory.

## Facts versus causal hypotheses

Facts above are values reported by Sol's read-only raw recomputation and its provenance checks. A causal explanation for Periodic-G's all-zero actor gradients is not established here. Possible causes such as loss masking, an all-NOOP action distribution, or an optimizer/gradient wiring issue remain hypotheses until traced against frozen training code and update records. Likewise, the Event-G rollout's lack of local candidates is an observation, not proof that the static scenario itself is infeasible or that a particular scope classifier is defective.

## Next-version recommendation (proposal only)

Before the next run, preregister a repair-opportunity contract that requires a known legal local candidate to remain represented through trigger eligibility, high-level and candidate masks, actor sampling, and effective execution. Separately preregister an actor-gradient/update invariant requiring a nonzero gradient and changed actor parameters on a controlled batch with at least two selectable legal actions. Include an explicit Event-G training sample with a legal local opportunity, while retaining the no-op and global alternatives. Fix thresholds and acceptance checks before inspecting the next development results. This is a proposed validation design; no repair, retuning, replay, or retraining was performed for this diagnosis, and no future repair is claimed effective.

## Reproduction and sources

The original `reproduce_first_zero.py` helper is valid only within its original private preparation directory because it embeds machine-specific input and output roots, and it is excluded from this public archive. The included diagnosis JSON is the derived read-only result; no simulator or policy was run to produce this summary.

- Frozen release receipt: `[REDACTED_LOCAL_PATH]
- Frozen manifest: same release directory, `RESULT_MANIFEST.json` (SHA-256 above).
- Sol raw recomputation: `[REDACTED_LOCAL_PATH] (SHA-256 `b04bc7cc26a32e71a8d0c3408bb760f6f128c0e997f8d15f3e56f14db2dadcc9`).
- Sol read-only audit implementation: `[REDACTED_LOCAL_PATH] (SHA-256 `fa02e9e881c050be93a0946c60f9a6b02b59b045e3705351c96bc1ce82338357`).

The raw audit explicitly reports that it did not replay the simulation or perform policy inference, and that legal binding validates recorded candidate/action/mask provenance rather than independently simulating feasibility. This note is a bounded diagnosis of those recorded artifacts, not an independent Sol review.
