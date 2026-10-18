# N02 Baseline Method Comparison

Profile: `formal`; run status: `FORMAL_COMPLETE`; scientific gate: `RESEARCH_CRITERIA_FAILED`.

Cells: 54 / 54. Results are paired descriptive observations; no statistical significance claim is made.

Method means use production summaries after oracle cross-check when available. Frozen global utility gates use the independent oracle only; absent oracle evidence is `MISSING`.

| Method | Global utility | Net utility | Completion | On time | Planning invocations |
|---|---:|---:|---:|---:|---:|---|
| Greedy | 9.8452 | 9.8452 | 0.9583 | 0.9583 | 60.00 |
| Auction | 9.8452 | 9.6902 | 0.9583 | 0.9583 | 60.00 |
| CBBA-lite | 9.8452 | 7.7152 | 0.9583 | 0.9583 | 60.00 |
| PPO | 5.2765 | 5.2765 | 0.8194 | 0.8194 | 60.00 |
| GPPO | 6.7812 | 6.7812 | 0.9028 | 0.9028 | 60.00 |
| Periodic-GPPO | 5.0029 | 5.0029 | 0.8056 | 0.8056 | 15.00 |
| Event-GPPO | 5.6404 | 5.6404 | 0.8750 | 0.8750 | 6.67 |
| Event-GPPO-WM | 5.6404 | 5.6404 | 0.8750 | 0.8750 | 6.50 |
| Periodic-GPPO-WM | 5.6177 | 5.6177 | 0.8750 | 0.8750 | 15.00 |

Rule methods use the candidate-constrained implementations specified by the protocol. Repeated deterministic rule trajectories are descriptive repeats, not independent training seeds.

An unsuccessful scientific threshold is reported as `RESEARCH_CRITERIA_FAILED`; it does not change the engineering completion status.
