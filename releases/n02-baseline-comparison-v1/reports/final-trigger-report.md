# N02 Event Trigger Comparison

Profile: `formal`; gate status: `RESEARCH_CRITERIA_FAILED`.

Paired mean differences are Event minus Periodic. Net utility is secondary and does not replace global utility.

## Event-GPPO vs Periodic-GPPO

Paired cells: 6; gate: `RESEARCH_CRITERIA_FAILED`.

| Criterion | Result |
|---|---|
| mean_global_utility_non_decrease | PASS |
| critical_failures_not_increased | PASS |
| completion_drop_within_0_02 | PASS |
| on_time_drop_within_0_02 | PASS |
| planning_invocations_lower | PASS |
| at_least_one_resource_or_reconstruction_metric_lower | FAIL |
| empty_scope_global_actions_zero | PASS |
| raw_local_repair_witness_present | PASS |

Empty-scope global actions: 0; raw local repair witnesses: 9.

## Event-GPPO-WM vs Periodic-GPPO-WM

Paired cells: 6; gate: `RESEARCH_CRITERIA_FAILED`.

| Criterion | Result |
|---|---|
| mean_global_utility_non_decrease | PASS |
| critical_failures_not_increased | PASS |
| completion_drop_within_0_02 | PASS |
| on_time_drop_within_0_02 | PASS |
| planning_invocations_lower | PASS |
| at_least_one_resource_or_reconstruction_metric_lower | FAIL |
| empty_scope_global_actions_zero | PASS |
| raw_local_repair_witness_present | PASS |

Empty-scope global actions: 0; raw local repair witnesses: 9.
