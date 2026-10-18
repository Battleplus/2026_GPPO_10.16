"""Fresh-run CUDA training guardian with CPU-only environment simulation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import uuid

_GUARDIAN_START = time.monotonic()


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def cgroup_cpu_seconds() -> float:
    """Measure this transient systemd unit including guardian and descendants."""
    membership = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    relative = next(line.split(":", 2)[2] for line in membership if line.startswith("0::"))
    values = dict(line.split() for line in (Path("/sys/fs/cgroup") / relative.lstrip("/") / "cpu.stat").read_text(encoding="utf-8").splitlines())
    return int(values["usage_usec"]) / 1_000_000.0


def runtime_witness(device: str = "cuda:0") -> dict:
    import numpy as np
    import torch
    torch.set_num_threads(1)
    torch.manual_seed(8201)
    training_device = torch.device(device)
    if training_device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("GPU_RUNTIME_REQUIRED_CUDA0_UNAVAILABLE")
    torch.cuda.set_device(training_device)
    torch.cuda.reset_peak_memory_stats(training_device)
    x = torch.randn(8, 8, device=training_device, requires_grad=True)
    weight = torch.nn.Parameter(torch.eye(8, device=training_device))
    y = (x @ weight).square().mean()
    y.backward()
    return {
        "python": sys.version.split()[0], "torch": torch.__version__, "numpy": np.__version__,
        "cpu_affinity": sorted(os.sched_getaffinity(0)), "torch_threads": torch.get_num_threads(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "gpu_initialized": torch.cuda.is_initialized(), "seed": 8201,
        "training_device": str(training_device),
        "gpu_name": torch.cuda.get_device_name(training_device),
        "gpu_capability": list(torch.cuda.get_device_capability(training_device)),
        "kernel_witness_shape": list(x.shape), "kernel_witness_finite": bool(torch.isfinite(y) and torch.isfinite(weight.grad).all()),
        "kernel_witness_input_device": str(x.device), "kernel_witness_parameter_device": str(weight.device),
        "kernel_witness_gradient_device": str(weight.grad.device),
        "kernel_witness_sha256": hashlib.sha256(x.grad.detach().cpu().numpy().tobytes() + weight.grad.detach().cpu().numpy().tobytes()).hexdigest(),
        "probe_peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(training_device)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--stage", default="all")
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    runtime_config = config["runtime"]
    os.sched_setaffinity(0, {0})
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = str(runtime_config["cuda_visible_devices"])
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    witness = runtime_witness(str(runtime_config["device"]))
    required = {"python": "3.11.16", "torch": "2.7.0+cu128", "numpy": "1.26.0", "cpu_affinity": [0], "torch_threads": 1, "cuda_visible_devices": str(runtime_config["cuda_visible_devices"]), "gpu_initialized": True, "training_device": "cuda:0", "kernel_witness_input_device": "cuda:0", "kernel_witness_parameter_device": "cuda:0", "kernel_witness_gradient_device": "cuda:0", "kernel_witness_finite": True}
    mismatches = {k: {"expected": v, "observed": witness[k]} for k, v in required.items() if witness[k] != v}
    if args.probe_only:
        print(json.dumps({"schema": "n02-event-runtime-witness/1", "runtime": witness, "mismatches": mismatches}, sort_keys=True), flush=True)
        return int(bool(mismatches))
    if mismatches:
        raise RuntimeError(f"Runtime contract mismatch: {mismatches}")
    manifest_path = args.source_root / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        observed = hashlib.sha256((args.source_root / relative).read_bytes()).hexdigest()
        if observed != expected:
            raise RuntimeError(f"Frozen source mismatch before execution: {relative}")
    request_path = args.source_root / "REQUEST.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    config_sha = hashlib.sha256(args.config.read_bytes()).hexdigest()
    if request["manifest_sha256"] != manifest_sha or request["config_sha256"] != config_sha:
        raise RuntimeError("Research request does not bind current source/config")
    # Formal runs are launched in a fresh transient unit. This counter covers
    # restore subprocesses as well as the main worker, unlike per-process rlimit.
    cgroup_cpu_start = cgroup_cpu_seconds()
    args.output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    write(args.output / "RUNTIME_IDENTITY.json", {"schema": "n02-event-runtime/1", "attempt": args.attempt, "run_id": run_id, "pid": os.getpid(), "systemd_invocation_id": os.environ.get("INVOCATION_ID"), "runtime": witness, "source_manifest_sha256": manifest_sha, "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "config_sha256": config_sha, "source_files_verified": len(manifest["files"])})
    command = [sys.executable, "-B", str(args.source_root / "package/civilian/event_runner.py"), args.stage, "--output", str(args.output), "--config", str(args.config)]
    start = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    def child_limits():
        budget = int(runtime_config["cpu_budget_seconds"])
        resource.setrlimit(resource.RLIMIT_CPU, (budget, budget + 5))
    with (args.output / "console.log").open("wb") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=args.source_root, start_new_session=True, preexec_fn=child_limits)
        write(args.output / "PROCESS_HANDOFF.json", {"schema": "n02-event-process-handoff/1", "attempt": args.attempt, "run_id": run_id, "guardian_pid": os.getpid(), "child_pid": child.pid, "command": command, "start_unix": time.time(), "systemd_invocation_id": os.environ.get("INVOCATION_ID")})
        timed_out = False
        cpu_budget_exceeded = False
        while child.poll() is None:
            timed_out = time.monotonic() - start >= min(args.timeout, int(runtime_config["wall_timeout_seconds"]))
            cpu_budget_exceeded = cgroup_cpu_seconds() >= int(runtime_config["cpu_budget_seconds"])
            if timed_out or cpu_budget_exceeded:
                break
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if timed_out or cpu_budget_exceeded:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                code = child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                code = child.wait()
        else:
            code = child.wait()
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    guardian_exit_code = 152 if cpu_budget_exceeded else 124 if timed_out else code if code >= 0 else 128 - code
    write(args.output / "GUARDIAN_SETTLEMENT.json", {
        "schema": "n02-event-guardian-settlement/1", "attempt": args.attempt, "run_id": run_id,
        "child_pid": child.pid, "child_exit_code": code, "timed_out": timed_out,
        "cpu_budget_exceeded": cpu_budget_exceeded,
        "guardian_exit_code": guardian_exit_code,
        "cgroup_cpu_seconds_at_guardian_start": cgroup_cpu_start,
        "cgroup_cpu_seconds_at_settlement": cgroup_cpu_seconds(),
            "cpu_budget_enforcement_scope": "whole fresh systemd cgroup, including guardian and restore descendants; CUDA compute is separately recorded by the GPU execution receipt",
        "wall_seconds": time.monotonic() - start,
        "child_cpu_seconds": (usage_after.ru_utime + usage_after.ru_stime) - (usage_before.ru_utime + usage_before.ru_stime),
        "child_max_rss_kib": usage_after.ru_maxrss,
        "guardian_total_wall_seconds": time.monotonic() - _GUARDIAN_START,
        "guardian_self_cpu_seconds": self_usage.ru_utime + self_usage.ru_stime,
        "guardian_plus_child_cpu_seconds": self_usage.ru_utime + self_usage.ru_stime + usage_after.ru_utime + usage_after.ru_stime,
        "systemd_invocation_id": os.environ.get("INVOCATION_ID"),
        "includes": "This guardian child process tree only; excludes upload, local tests, review and other attempts.",
    })
    gpu_receipt_path = args.output / "GPU_EXECUTION_RECEIPT.json"
    if child.returncode == 0:
        if not gpu_receipt_path.is_file():
            raise RuntimeError("GPU_EXECUTION_RECEIPT_MISSING")
        gpu_receipt = json.loads(gpu_receipt_path.read_text(encoding="utf-8"))
        if (gpu_receipt.get("status") != "complete" or gpu_receipt.get("device") != "cuda:0"
                or gpu_receipt.get("peak_memory_allocated_bytes", 0) <= 0
                or gpu_receipt.get("world_model_parameter_devices") != ["cuda:0"]
                or gpu_receipt.get("policy_parameter_devices") != ["cuda:0"]
                or gpu_receipt.get("world_model_optimizer_state_devices") != ["cuda:0"]
                or gpu_receipt.get("policy_optimizer_state_devices") != ["cuda:0"]):
            raise RuntimeError("GPU_EXECUTION_RECEIPT_DEVICE_AUDIT_FAILED")
    manifest = {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.rglob("*")) if p.is_file()}
    write(args.output / "REMOTE_EVIDENCE_HASHES.json", {"schema": "n02-event-evidence-hashes/1", "attempt": args.attempt, "files": manifest})
    print(json.dumps({"attempt": args.attempt, "run_id": run_id, "child_exit_code": code, "timed_out": timed_out, "output": str(args.output), "gpu_witness": witness}, sort_keys=True), flush=True)
    return guardian_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
