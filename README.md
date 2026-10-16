# N02 Minimal Closure Archive Preparation

This directory prepares a de-identified public archive for `Battleplus/2026_GPPO_10.16`. It records the five core checks, reviewed local Gate A evidence, bounded server diagnostics, remaining work, and archive privacy rules. Candidate source and raw operational evidence remain outside this directory pending independent publication review.

## Current state

The frozen development candidate is `ch2_disaster_relief_n02_minimal_closure_v1_100x100_bhook_20261016`. Sol independently passed Gate A with 19 local tests and verified the first three synthetic core checks. A bounded server diagnostic completed successfully for its expected success, normal-failure, and guardian-kill cases. Sol's independent review passed bounded Node B diagnostics and the measured receipt. The measured prior-cost receipt replay was accepted by the package parser; it records 2.391625 seconds wall and 0.821315 seconds CPU for that same diagnostic unit only.

Formal real-data consequence collection, world-model training and new-process recovery, and real PPO updates have not run. No formal authorization has been created. These are the remaining minimum-closure gates; this preparation does not claim research efficacy or a complete engineering closure.

## Five core checks

1. C1-derived public-information civilian initial assignment with recorded algorithm provenance; this is not a claim to have run the original Chapter 1 MILP.
2. Synthetic causal 2x2 spatial perturbation with delayed public reporting and boundary checks.
3. NOOP-referenced, independently recomputed consequences including a non-target order.
4. Actual consequences, world-model training and strict restore, and paired G/G-WM PPO updates, all still pending as real runs.
5. Sol independent review of the evidence and proposed archive; local Gate A passed, while bounded Node B passed; publication review remains pending.

## Review records

- [STATUS.md](STATUS.md): evidence and remaining boundaries.
- [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md): five checks and their current states.
- [history/gate-a-review/SOL_GATE_A_REPAIR1_SUMMARY.md](history/gate-a-review/SOL_GATE_A_REPAIR1_SUMMARY.md): de-identified Gate A result and provenance.
- [history/server-diagnostics/SOL_B_DIAGNOSTIC_SUMMARY.md](history/server-diagnostics/SOL_B_DIAGNOSTIC_SUMMARY.md): de-identified bounded diagnostic and accounting result.
- [ROADMAP.md](ROADMAP.md): minimum-closure route; later full-study work is explicitly future work.
- [ARCHIVE_RULES.md](ARCHIVE_RULES.md): public branch, tag, and content conditions.

The allowlist checker audits only files listed in [PUBLIC_ALLOWLIST.txt](PUBLIC_ALLOWLIST.txt). A clean scan is a privacy-policy result for the staged snapshot; it does not replace scientific review, complete Gate B, or authorize publication.
