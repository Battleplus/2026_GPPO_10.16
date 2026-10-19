# Addendum: Final S2 Geographic Communication Metric

This addendum supplements the earlier first-zero diagnosis with the metric published in Sol's final `S2_RESULT_REVIEW`. It does not alter or replace `FIRST_ZERO_DIAGNOSIS.json`, `reproduce_first_zero.py`, or their recorded hashes.

The preliminary `RAW_RECOMPUTATION.json` left `cross_region_messages` null because it had not yet applied a geographic endpoint mapping. The final review added a separate, explicitly defined geographic measure: for each `communication_tx`, map the source and target platform positions from the **pre-action observation** into the frozen half-open `regions.bounds`, then count the message as cross-region only if the two mapped endpoint regions differ. Each development episode has zero unmapped messages, and the final development means are 0 for both Periodic-G and Event-G. This means the geographic endpoint metric was computable and is zero; the earlier null was a preliminary reporting state, not the final result.

The final raw extension reports 36 Periodic-G messages and 38 Event-G messages per development parent. Periodic-G's transmissions are all self-transmissions. Event-G has one non-self transmission per parent, at t=1 from `n02-heli-5` to `n02-uav-19`; both endpoint positions map to `r20`. Thus the geographic cross-region count is 0/36 for Periodic-G and 0/38 for Event-G in each parent. These results are descriptive reporting metrics, not additional acceptance gates.

This position-based result does **not** establish fixed platform affiliation. The helicopter has `region_id=null`, so a fixed-region assignment for the helicopter remains unknown. Interpret the result only under the geographic endpoint-at-send-time definition, not as evidence that every platform has a known fixed region.

Evidence references:

- Final review: `[REDACTED_LOCAL_PATH] and `S2_RESULT_REVIEW.json`.
- Geographic recomputation: `[REDACTED_LOCAL_PATH] (SHA-256 `c574aa010af0143cb34620de8f7bd57d80970478cfda4ea7dd0eb4cccb924310`).
- Frozen geographic contract reference: `source/package/civilian/region_contract.py:14` within the release identified in `FIRST_ZERO_DIAGNOSIS.md`.
- Final review identifies this as a reporting extension that supersedes the preliminary null only for geographic endpoint semantics; fixed affiliation remains unknown for helicopters.
