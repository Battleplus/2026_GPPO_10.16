# Sol B Diagnostic Evidence Summary

Review date: 2026-10-16  
Diagnostic unit: `70b6495fa8b74135872bbf6b961ae9c2`  
Scope: bounded unauthorized target diagnostics and same-unit prior-cost receipt.

## Completed diagnostic cases

The diagnostic unit completed with systemd result `success`, exit status 0, and zero restarts. Its scoped cases recorded:

| Case | Result | Child status |
| --- | --- | ---: |
| Expected success | Accepted | 0 |
| Controlled normal failure | Expected failure | 1 |
| Guardian kill | Expected guardian kill | -9 |

The guardian-kill case recorded the expected input-admission wall-budget reason. Sol's bounded evidence review found the scenario results, journals, and accounting consistent.

The same-unit measured prior-cost receipt replayed successfully in the package parser. It records **2.391625 seconds wall time** and **0.821315 seconds CPU time**. The receipt SHA-256 is `ff2fbcbef7fc3d04acfb087018121d1a07a34156e668f1ba58669c15d562ab30`. Earlier failed units are separately indexed and excluded from this successful-unit total. SSH, transfers, and separate probes are also outside it.

## Evidence boundary

These results establish bounded diagnostics only. No formal authorization or formal research run was created. They do not establish consequence collection, world-model training or recovery, PPO updates, or research efficacy. Sol independently passed bounded Node B diagnostics and the measured receipt. The separate runtime probe is not a formal-worker runtime receipt.

The original local review and parser-replay records are identified by these hashes:

| Original evidence artifact | Hash form | SHA-256 |
| --- | --- | --- |
| B diagnostic review Markdown | Raw file bytes | `6a12234da9a5b0f15cdc34cf2c0f448fc5bb61e7969fca7b1554d2ae4fb58006` |
| B diagnostic review JSON | Raw file bytes | `2df9f06a04361efd64b9df19e298da32ee6305ec787c71555416c3b7e1f2f73c` |
| Package parser replay result | Raw file bytes | `e8d011803290a9010a0a18def5e798c661a1a8ac92f52199b297a2e7176376db` |

These hashes identify original local evidence bytes, not this de-identified summary. The original operational files remain outside the public archive; public summary hashes are calculated independently by the archive inventory checker.
