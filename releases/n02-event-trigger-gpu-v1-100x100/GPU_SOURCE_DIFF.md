# GPU versus CPU source changes

This summary compares the manifest-verified CPU repair-3 source with the independently frozen GPU source. The GPU variant changes execution plumbing for CUDA training; the simulation environment remains on CPU. The experiment design and source baseline are declared unchanged. This source comparison does not establish formal GPU completion or scientific acceptance.

The CPU manifest contains 73 files and the GPU manifest contains 77 files. The GPU manifest adds 4 paths, removes 0 paths, and changes the bytes of 10 shared paths. The full path-by-path SHA-256 mapping is retained in the private comparison receipt.

Key reviewed GPU-specific changes include:

- `configs/ENVIRONMENT_SPEC.json`: Adds GPU execution parameters while preserving CPU environment simulation.
- `configs/EVENT_TRIGGER_CONFIG.json`: Binds the event run to the GPU execution profile while retaining the public event experiment configuration.
- `package/civilian/event_models.py`: Provides device-aware model construction, training, and checkpoint restoration for the event world model.
- `package/civilian/event_policy.py`: Provides device-aware actor/critic training and restore paths for the event policies.
- `package/civilian/event_runner.py`: Runs the configured CUDA training path and records device witnesses while keeping the simulator on CPU.
- `package/civilian/runtime-spec.json`: Declares CUDA model training with CPU environment simulation and the M0-M4 event protocol.
- `package/tests/test_event_runner_metrics.py`: Updates event runner checks for the GPU-aware model loader interface.
- `tools/freeze_source.py`: Records the GPU execution profile and declared GPU-only source variation in the frozen identity.
- `tools/native_remote.py`: Stages, probes, launches, observes, and retrieves runs through the native Windows OpenSSH route with fresh identities.
- `tools/runtime_guardian.py`: Checks the CUDA runtime witness and validates training model/optimizer devices while preserving CPU simulation.

The public runtime contract requires world-model and PPO training on `cuda:0`, GPU 0 visible, and environment simulation on CPU. Model parameters, optimizer moments, and fresh-process restore paths are checked for device placement. The separate kernel probe is not a project-training result; the synthetic GPU smoke is engineering evidence only.

Added GPU-specific source paths are `configs/GPU_ENV_SPEC.json`, `package/tests/test_gpu_training_path.py`, `protocols/GPU_BRANCH_MODIFICATIONS.json`, and `tools/gpu_smoke.py`. The CPU repair-3 PASS does not certify GPU behavior. Formal GPU results, integrity replay, and independent final review remain pending.
