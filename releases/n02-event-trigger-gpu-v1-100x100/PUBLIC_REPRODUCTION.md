# Public GPU source reproduction guide

This guide operates on a private local copy of the published source snapshot. It never uses the original formal GPU release identity.

## Create a fresh public identity

The public source snapshot contains 76 manifest-verified files. Their bytes are unchanged. `protocols/RUNTIME_INVOCATION.md` is excluded because it contains private runtime-context and deployment procedure details. The original `SOURCE_MANIFEST.json`, `REQUEST.json`, and local hash bundle are also excluded. Therefore, first create a new freeze and request in your own copy:

```powershell
$sourceRoot = "<path-to-your-copy-of-public-staging-repro>\source"
$evidenceRoot = "<private-local-evidence-directory>"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
& python -B (Join-Path $sourceRoot "tools/freeze_source.py") --root $sourceRoot
```

The command must report `files: 76`. It creates a new random release, `SOURCE_MANIFEST.json`, `REQUEST.json`, `SHA256SUMS.txt`, and a static-only local report in that copy. This newly generated request binds the copied source and config; it is not research authorization, Sol review, formal-run approval, or scientific acceptance. Obtain those approvals through the applicable process before launching any formal run. Do not substitute the original GPU manifest digest or attempt identity.

## Target runtime

Use the provisioned Linux runtime with Python `3.11.16`, PyTorch `2.7.0+cu128`, and NumPy `1.26.0`. Training must use `cuda:0` with GPU 0 visible; environment simulation stays on CPU. The runtime contract uses CPU affinity `[0]` and one thread for Torch, OpenMP, MKL, OpenBLAS, and NumExpr. The repository's local Python environment is not a substitute for this target contract. The target must have the pinned dependencies and native systemd user services already available.

`probe` runs the guardian's finite 8x8 CUDA forward/backward witness and runtime-contract checks. It does not run project training. `tools/gpu_smoke.py` is a separate synthetic engineering exercise of CUDA world-model/PPO paths and fresh-process restore; its receipt is not project training or scientific evidence.

## Native Windows OpenSSH route

Run these commands from PowerShell on Windows with native OpenSSH available and the target's public-key login configured. Fill the placeholders locally. Keep the deployment state and retrieved evidence in a private directory. The GUID state filename is new for each reproduction.

```powershell
$sourceRoot = "<path-to-your-copy-of-public-staging-repro>\source"
$evidenceRoot = "<private-local-evidence-directory>"
$hostTarget = "<user>@<host>"
$remoteRoot = "<remote-root>"
$remotePython = "<remote-python-path>"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$statePath = Join-Path $evidenceRoot ("state-" + [guid]::NewGuid().ToString("N") + ".json")
$runner = Join-Path $sourceRoot "tools/native_remote.py"

# Create a new deployment attempt, package the freshly frozen 76 files, and verify remote hashes.
& python -B $runner stage --host $hostTarget --remote-root $remoteRoot --python $remotePython --source $sourceRoot --state $statePath

# Check the target CUDA runtime and kernel witness. This does not launch the project.
& python -B $runner probe --host $hostTarget --remote-root $remoteRoot --python $remotePython --source $sourceRoot --state $statePath

# Launch the formal pipeline exactly once, after separate research authorization and review.
& python -B $runner launch --host $hostTarget --remote-root $remoteRoot --python $remotePython --source $sourceRoot --state $statePath --stage all

# Observe the same run as needed; status does not relaunch it.
& python -B $runner status --host $hostTarget --remote-root $remoteRoot --python $remotePython --source $sourceRoot --state $statePath

# Retrieve after completion. Incomplete recovery remains explicitly incomplete.
& python -B $runner retrieve --host $hostTarget --remote-root $remoteRoot --python $remotePython --source $sourceRoot --state $statePath
```

The `stage` operation creates a unique attempt and remote directory. `probe`, `launch`, `status`, and `retrieve` use the private state file produced by `stage`. Launch only once; use `status` to observe progress. For the referenced attempt, the retrieved evidence passed integrity verification and aggregate descriptive results are in `FINAL_RESULTS_SUMMARY.md`. Independent final review and scientific acceptance remain pending; do not treat this reproduction guide as an acceptance decision.

The event-scope interpretation and descriptive limits are documented in `FINAL_RESULTS_SUMMARY.md`. Aggregate results do not establish broad superiority or isolate the Event-G-WM critic effect.
