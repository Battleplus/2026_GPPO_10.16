# N02 GPU event-trigger archive

This archive contains the reviewed public source subset, reproducibility tools, sanitized descriptive analysis, hash commitments, and an explicit research-gate status for the completed GPU run.

- Engineering execution completed on RTX 2080 Ti (`cuda:0`): 240 world-model CUDA updates and 1,344 PPO CUDA updates.
- The final snapshot contains 24/24 development cells, 3 world-model checkpoints, 12 policy checkpoints, and 144/144 verified evidence hashes.
- Event-G had fewer triggers than Periodic-G (12.33 vs 15.00 per six-cell mean) but more independently verified effective reconstructions (4.00 vs 2.17; paired difference +1.83). Therefore the Event-G reconstruction reduction criterion fails on this descriptive set.
- Five mutation gaps have conservative zero-mutation witnesses; two remain inconclusive. Exact missing values remain missing.
- This branch is an engineering/result archive. Expanded paper baselines are not claimed complete. The final external Sol High review receipt is pending because the local review relay did not return a completed artifact.

Private evidence, checkpoints, credentials, server paths, raw trajectories and authorization text are excluded. See `releases/n02-event-trigger-gpu-v1-100x100/README.md` for reproduction and identity details.
