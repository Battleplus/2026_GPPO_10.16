# Seeded CPU Kernel Witness

State: `UNMEASURED`.

This protocol records the target runtime contract for independent server preflight. It is not evidence that the environment has been measured. It uses a public schema separate from the package's existing `runtime-spec.json`; it does not replace or rewrite that package contract.

## Required environment

The witness requires Python 3.11.16, PyTorch 2.7.0+cu128, NumPy 1.26.0, CPU affinity exactly `[0]`, one Torch thread, an explicitly empty `CUDA_VISIBLE_DEVICES`, and an uninitialized GPU. The target environment is Linux because the check reads process affinity with `os.sched_getaffinity`.

## Invocation

From the reviewed archive root, an independent agent should run:

```sh
CUDA_VISIBLE_DEVICES= python -B tools/cpu_runtime_witness.py --output cpu-runtime-witness.json
```

The tool exits nonzero if any version or runtime constraint differs. On success it writes a receipt with the versions, affinity, thread count, seed, tensor operation, and matching repeat hashes. It does not connect to a server, initialize CUDA, train a model, or create a formal run identity.

## Readiness decision

The independent agent must execute this witness, capture the measured runtime identity, validate the resource ledger and package hashes, and attach those receipts to Stage B review. Until then the environment remains `UNMEASURED`; imports or unit tests alone do not make it ready.
