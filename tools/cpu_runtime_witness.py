#!/usr/bin/env python3
"""Measure the frozen N02 CPU runtime contract with a seeded CPU kernel witness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

EXPECTED_PYTHON = (3, 11, 16)
EXPECTED_TORCH = "2.7.0+cu128"
EXPECTED_NUMPY = "1.26.0"
SEED = 8201


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    import numpy as np
    import torch

    failures: list[str] = []
    python_version = tuple(sys.version_info[:3])
    if python_version != EXPECTED_PYTHON:
        failures.append(f"Python version mismatch: {python_version}")
    if torch.__version__ != EXPECTED_TORCH:
        failures.append(f"PyTorch version mismatch: {torch.__version__}")
    if np.__version__ != EXPECTED_NUMPY:
        failures.append(f"NumPy version mismatch: {np.__version__}")

    if not hasattr(os, "sched_getaffinity"):
        failures.append("process CPU affinity query is unavailable")
        affinity: list[int] = []
    else:
        affinity = sorted(os.sched_getaffinity(0))
        if affinity != [0]:
            failures.append(f"CPU affinity mismatch: {affinity}")
    threads = torch.get_num_threads()
    if threads != 1:
        failures.append(f"Torch thread count mismatch: {threads}")
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible != "":
        failures.append("CUDA_VISIBLE_DEVICES must be explicitly empty")
    gpu_initialized = torch.cuda.is_initialized()
    if gpu_initialized:
        failures.append("CUDA was initialized before or during the witness")

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)

    def kernel_digest() -> str:
        generator = torch.Generator(device="cpu").manual_seed(SEED)
        left = torch.randn((64, 64), generator=generator, dtype=torch.float64, device="cpu")
        right = torch.randn((64, 64), generator=generator, dtype=torch.float64, device="cpu")
        output = torch.mm(left, right).contiguous()
        return hashlib.sha256(output.numpy().tobytes()).hexdigest()

    first_hash = kernel_digest()
    repeat_hash = kernel_digest()
    if first_hash != repeat_hash:
        failures.append("seeded CPU kernel repeat hashes differ")

    receipt = {
        "schema": "n02-seeded-cpu-kernel-witness/1",
        "status": "MEASURED_PASS" if not failures else "MEASURED_FAIL",
        "python": ".".join(str(part) for part in python_version),
        "pytorch": torch.__version__,
        "numpy": np.__version__,
        "device": "cpu",
        "cpu_affinity": affinity,
        "torch_threads": threads,
        "CUDA_VISIBLE_DEVICES": cuda_visible,
        "gpu_initialized": gpu_initialized,
        "seed": SEED,
        "operation": "torch.mm(float64, 64x64, cpu)",
        "kernel_sha256": first_hash,
        "repeat_kernel_sha256": repeat_hash,
        "failures": failures,
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
