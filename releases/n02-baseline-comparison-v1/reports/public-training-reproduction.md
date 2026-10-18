# Public Training Reproduction

This guide separates replaying the released evaluation evidence from starting
a new training run. The public stage contains the scientific runner, configs,
and `data/gate1-r8`; it excludes the private `RUN_IDENTITY.json` used for the
original execution. A new run therefore needs a fresh workspace and a new
minimal data provenance record. It cannot claim the original private execution
identity or prove that the original private launch was reproduced exactly.

## Replay Released Evidence

From the final repository root, replay the archived evaluation artifacts with
the repository's verifier:

```powershell
python -B releases/n02-baseline-comparison-v1/measurement-tools/recompute_public_archive.py `
  --stage releases/n02-baseline-comparison-v1 `
  --manifest reports/evaluation-manifest.json `
  --oracle measurement-tools/independent_baseline_oracle_delivery_release_v2.py `
  --report new/out.json
```

Choose a new report path that does not already exist. This checks the published
archive and its evaluation evidence; it does not start training or grant formal
execution authorization.

## Prepare Fresh Training

Copy `releases/n02-baseline-comparison-v1/source` into a fresh workspace. Keep
the release stage unchanged. In that copy, create
`data/gate1-r8/RUN_IDENTITY.json` with exactly the following provenance fields:

```json
{
  "schema": "n02-public-reproduction-provenance/1",
  "manifest_sha256": "00c9631e9265bd72254a846d34e1ea997fb46f777cb9adb0d9fab45dbc197def",
  "purpose": "fresh public reproduction; not original private execution identity"
}
```

This record binds the fresh workspace to the published Gate1 data origin. The
new file's SHA256 becomes the new data binding. It does not reconstruct or
replace the private identity used in the original run. The public runner's
`_r8_binding` checks the manifest digest, 16 training records, 8 development
records, `source_split` set to `train`, and
`frozen_before_development_evaluation` set to `true`.

Use Python 3.11.16, PyTorch 2.7.0+cu128, NumPy 1.26.0, CUDA 12.8 when a
compatible GPU is available, and one CPU thread. The following commands are
issued from the fresh workspace root; all output directories must be new:

```powershell
python -B package/civilian/baseline_runner.py --profile formal --phase freeze-wm --output NEW_WM
python -B package/civilian/baseline_runner.py --profile formal --phase train --world-model-dir NEW_WM --output NEW_TRAIN
python -B package/civilian/baseline_runner.py --profile formal --phase evaluate --world-model-dir NEW_WM --checkpoint-dir NEW_TRAIN --output NEW_EVAL
```

Replace `NEW_WM`, `NEW_TRAIN`, and `NEW_EVAL` with distinct, unused paths.
Archived graph and world-model checkpoint bytes remain available in the public
stage, but their original strict identity bindings differ from those in a new
workspace. Do not bypass identity checks or relabel archived bytes as newly
trained outputs.

The private guardian and transport controls are not included in the public
stage. Operators must supply appropriate resource limits and local execution
controls before running these commands. The commands above document the runner
interface only; no GPU launch is claimed as tested here, and this guide does
not report a new training run.

## Scientific Scope

The rules baseline is candidate-constrained CBBA-lite, not full CBBA. WM uses a
critic-only update. The reported evaluation has three seeds and two development
scenarios, so the results are descriptive. These scope notes do not substitute
for reviewing the actual run outputs and their provenance.
