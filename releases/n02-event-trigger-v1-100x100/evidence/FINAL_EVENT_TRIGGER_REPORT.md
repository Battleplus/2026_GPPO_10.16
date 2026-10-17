# N02 Event-Trigger Experiment Report

Stage status: m0=complete, m1=complete, m2=complete, m3=complete, m4=complete.
M2: complete; train diversity 16/16; gate passed True.
M2 development samples: 8/8.
M2 all-window diversity: 24/24 (development diversity is report-only).
World-model ensemble: complete; hash: 2d2e67bf2042cf5bbff7f0116725654c6f3eddb78f1dd0cdfbbac8bf6fe2a3f2.
Policy training: complete; paired updates per seed/method: 112.
Independent Sol High review: pending.

Development summaries are descriptive for two held-out parents and do not support a broad superiority claim.
Event-G-WM versus Event-G combines model-assisted trigger and auxiliary critic effects; the critic effect is not isolated.
Configured reward targets are recomputed from raw trace primitives and checked against recorded step rewards.
World-model development metrics are held out from fitting and threshold calibration.

M1 diagnostic episodes: not available.
Resource totals: {"branches": 253, "cpu_seconds": 3997.8898072760003, "environment_steps": 21602, "optimizer_updates": 1584, "policy_forwards": 112080, "wall_seconds": 4005.7329710000195, "world_model_forwards": 20514}.
