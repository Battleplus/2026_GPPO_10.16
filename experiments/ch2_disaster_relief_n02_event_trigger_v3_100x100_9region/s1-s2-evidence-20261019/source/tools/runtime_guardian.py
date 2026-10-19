"""V3 S2 CUDA guardian, derived from the frozen v2 guardian (see provenance)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
try:
    import resource
except ImportError:  # The manifest verifier is also exercised on Windows.
    resource = None
import signal
import subprocess
import sys
import time
import uuid

_GUARDIAN_START = time.monotonic()
S1_SOURCE_MANIFEST_SHA256 = "b8a652b40756dd09db4a0a572b00ed786fc9a89dc5df759baa25e7ea56188f40"
S1_EVIDENCE_MANIFEST_SHA256 = "7c86cd18ef1a59edb7e0b823b50f39f5c97e9cc8d720389e125b8c39e630e622"
S1_INDEPENDENT_REVIEW_SHA256 = "979528c7b974d9815a0bb6df34f696ac4c84648bef426a2bc52928da2cdf52c2"


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


_SOURCE_AUXILIARY_FILES = {
    "SOURCE_MANIFEST.json", "REQUEST_CANDIDATE.json", "SHA256SUMS.txt",
    "FORMAL_REQUEST.json", "ATTEMPT.json", "AUTHORIZATION_BINDING.json",
}


def verify_source_manifest(source_root: Path) -> tuple[dict, str]:
    manifest_path = source_root / "SOURCE_MANIFEST.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("SOURCE_MANIFEST_FILES_REQUIRED")
    expected = set()
    for relative, expected_sha in files.items():
        path = PurePosixPath(str(relative))
        if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts) or "\\" in str(relative):
            raise RuntimeError(f"SOURCE_MANIFEST_UNSAFE_PATH:{relative}")
        if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
            raise RuntimeError(f"SOURCE_MANIFEST_INVALID_SHA256:{relative}")
        expected.add(path.as_posix())

    actual = set()
    for path in source_root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"SOURCE_MANIFEST_SYMLINK_NOT_ALLOWED:{path.relative_to(source_root).as_posix()}")
        if path.is_file():
            actual.add(path.relative_to(source_root).as_posix())
    expected_complete = expected | _SOURCE_AUXILIARY_FILES
    missing = sorted(expected_complete - actual)
    unexpected = sorted(actual - expected_complete)
    if missing or unexpected:
        raise RuntimeError(f"SOURCE_MANIFEST_INVENTORY_MISMATCH:missing={missing[:8]}:unexpected={unexpected[:8]}")
    for relative in sorted(expected):
        observed = hashlib.sha256((source_root / Path(*PurePosixPath(relative).parts)).read_bytes()).hexdigest()
        if observed != files[relative]:
            raise RuntimeError(f"Frozen source mismatch before execution: {relative}")
    return manifest, hashlib.sha256(manifest_bytes).hexdigest()


def verify_attempt_binding(source_root: Path, binding_path: Path, evidence_root: Path, manifest: dict, manifest_sha: str) -> tuple[dict, dict]:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    request_path = source_root / "FORMAL_REQUEST.json"
    attempt_path = source_root / "ATTEMPT.json"
    authorization_path = source_root / "AUTHORIZATION_BINDING.json"
    expected_files = {
        "FORMAL_REQUEST.json": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "ATTEMPT.json": hashlib.sha256(attempt_path.read_bytes()).hexdigest(),
        "AUTHORIZATION_BINDING.json": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
    }
    if binding.get("schema") != "n02-v3-publishing-binding/1" or binding.get("generated_files") != expected_files:
        raise RuntimeError("FORMAL_PUBLISHING_BINDING_HASH_MISMATCH")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if (request.get("schema") != "n02-v3-formal-request/1"
            or request.get("scope") != "S2"
            or request.get("release") != manifest.get("release")
            or request.get("manifest_sha256") != manifest_sha
            or request.get("config_sha256") != hashlib.sha256((source_root / "configs/V3_PILOT_CONFIG.json").read_bytes()).hexdigest()
            or request.get("preregistration_sha256") != hashlib.sha256((source_root / "configs/V3_PREREGISTRATION.json").read_bytes()).hexdigest()
            or request.get("execution_permission") != "S2_RUN_AUTHORIZED"):
        raise RuntimeError("FORMAL_REQUEST_SOURCE_BINDING_MISMATCH")
    if (attempt.get("schema") != "n02-v3-attempt/1"
            or attempt.get("attempt_id") != request.get("attempt_id")
            or attempt.get("run_id") != request.get("run_id")
            or attempt.get("release") != manifest.get("release")
            or not re.fullmatch(r"[0-9a-f]{32}", str(attempt.get("attempt_id", "")))
            or not re.fullmatch(r"[0-9a-f]{32}", str(attempt.get("run_id", "")))):
        raise RuntimeError("FORMAL_ATTEMPT_IDENTITY_MISMATCH")
    if request.get("one_time_token_id") != attempt.get("one_time_token_id") or request.get("one_time_token_id") != attempt.get("attempt_id"):
        raise RuntimeError("FORMAL_ONE_TIME_ATTEMPT_TOKEN_BINDING_MISMATCH")
    if (authorization.get("schema") != "n02-v3-authorization-binding/1"
            or authorization.get("request_sha256") != expected_files["FORMAL_REQUEST.json"]
            or authorization.get("attempt_sha256") != expected_files["ATTEMPT.json"]
            or authorization.get("attempt_id") != attempt["attempt_id"]
            or authorization.get("run_id") != attempt["run_id"]
            or authorization.get("release") != manifest.get("release")):
        raise RuntimeError("FORMAL_AUTHORIZATION_BINDING_MISMATCH")
    if (binding.get("release") != manifest.get("release")
            or binding.get("manifest_sha256") != manifest_sha
            or binding.get("attempt_id") != attempt["attempt_id"]
            or binding.get("run_id") != attempt["run_id"]):
        raise RuntimeError("FORMAL_PUBLISHING_IDENTITY_MISMATCH")
    evidence_files = binding.get("evidence_files")
    required_evidence = {"S1_REVIEW.json", "SOL_ENTRY_REPORT.json", "RUNTIME_PROBE_RECEIPT.json"}
    if not isinstance(evidence_files, dict) or set(evidence_files) != required_evidence:
        raise RuntimeError("FORMAL_ENTRY_EVIDENCE_SET_MISMATCH")
    evidence = {}
    for name in sorted(required_evidence):
        path = evidence_root / name
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if evidence_files.get(name) != observed:
            raise RuntimeError(f"FORMAL_ENTRY_EVIDENCE_HASH_MISMATCH:{name}")
        evidence[name] = json.loads(path.read_text(encoding="utf-8"))
    s1 = evidence["S1_REVIEW.json"]
    entry = evidence["SOL_ENTRY_REPORT.json"]
    runtime = evidence["RUNTIME_PROBE_RECEIPT.json"]
    if (s1.get("S1") != "PASS" or s1.get("verdict") != "PASS"
            or s1.get("S2_acceptance") != "NOT_RUN"
            or s1.get("release") != "n02-v3-s1-0786bcc9ae87435d813531361edf6c34"
            or s1.get("source_manifest_sha256") != S1_SOURCE_MANIFEST_SHA256
            or s1.get("evidence_manifest_sha256") != S1_EVIDENCE_MANIFEST_SHA256
            or evidence_files.get("S1_REVIEW.json") != S1_INDEPENDENT_REVIEW_SHA256):
        raise RuntimeError("FORMAL_S1_REVIEW_GATE_FAILED")
    if (entry.get("verdict") != "PASS" or entry.get("S1") != "PASS"
            or entry.get("source_manifest_sha256") != manifest_sha):
        raise RuntimeError("FORMAL_SOL_ENTRY_GATE_FAILED")
    if (request.get("s1_source_manifest_sha256") != S1_SOURCE_MANIFEST_SHA256
            or request.get("s1_evidence_manifest_sha256") != S1_EVIDENCE_MANIFEST_SHA256
            or request.get("s1_independent_review_sha256") != S1_INDEPENDENT_REVIEW_SHA256):
        raise RuntimeError("FORMAL_S1_REQUEST_IDENTITY_MISMATCH")
    if request.get("s1_review_sha256") != evidence_files["S1_REVIEW.json"]:
        raise RuntimeError("FORMAL_S1_REVIEW_REQUEST_HASH_MISMATCH")
    if request.get("sol_entry_report_sha256") != evidence_files["SOL_ENTRY_REPORT.json"]:
        raise RuntimeError("FORMAL_SOL_ENTRY_REQUEST_HASH_MISMATCH")
    if request.get("runtime_probe_receipt_sha256") != evidence_files["RUNTIME_PROBE_RECEIPT.json"]:
        raise RuntimeError("FORMAL_RUNTIME_PROBE_REQUEST_HASH_MISMATCH")
    if (runtime.get("status") != "FRESH_RUNTIME_PROBE_PASS_ONLY"
            or runtime.get("selected_physical_gpu_index") != 1
            or runtime.get("probe_native_exit_code") != 0
            or runtime.get("probe_witness", {}).get("mismatches") != {}
            or runtime.get("formal_run_or_checkpoint_created") is not False):
        raise RuntimeError("FORMAL_RUNTIME_PROBE_GATE_FAILED")
    return request, attempt


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
    parser.add_argument("--device")
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    runtime_config = config["runtime"]
    configured_device = str(runtime_config.get("device", config.get("ppo", {}).get("device", "cuda:0")))
    device = str(args.device or configured_device)
    if device != configured_device or str(config.get("ppo", {}).get("device", configured_device)) != device:
        raise RuntimeError("GUARDIAN_DEVICE_CLI_CONFIG_MISMATCH")
    os.sched_setaffinity(0, {0})
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = str(runtime_config["cuda_visible_devices"])
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    witness = runtime_witness(device)
    required = {"python": "3.11.16", "torch": "2.7.0+cu128", "numpy": "1.26.0", "cpu_affinity": [0], "torch_threads": 1, "cuda_visible_devices": str(runtime_config["cuda_visible_devices"]), "gpu_initialized": True, "training_device": "cuda:0", "kernel_witness_input_device": "cuda:0", "kernel_witness_parameter_device": "cuda:0", "kernel_witness_gradient_device": "cuda:0", "kernel_witness_finite": True}
    mismatches = {k: {"expected": v, "observed": witness[k]} for k, v in required.items() if witness[k] != v}
    if args.probe_only:
        print(json.dumps({"schema": "n02-event-runtime-witness/1", "runtime": witness, "mismatches": mismatches}, sort_keys=True), flush=True)
        return int(bool(mismatches))
    if mismatches:
        raise RuntimeError(f"Runtime contract mismatch: {mismatches}")
    manifest, manifest_sha = verify_source_manifest(args.source_root)
    if args.binding is None or args.evidence_root is None:
        raise RuntimeError("FORMAL_PUBLISHING_BINDING_AND_EVIDENCE_REQUIRED")
    request, attempt = verify_attempt_binding(args.source_root, args.binding, args.evidence_root, manifest, manifest_sha)
    request_path = args.source_root / "FORMAL_REQUEST.json"
    config_sha = hashlib.sha256(args.config.read_bytes()).hexdigest()
    if request["manifest_sha256"] != manifest_sha or request["config_sha256"] != config_sha:
        raise RuntimeError("Research request does not bind current source/config")
    if args.attempt != attempt["attempt_id"]:
        raise RuntimeError("FORMAL_ATTEMPT_CLI_MISMATCH")
    if not request.get("runtime_python_path") or os.path.realpath(request["runtime_python_path"]) != os.path.realpath(sys.executable):
        raise RuntimeError("FORMAL_PINNED_PYTHON_PATH_MISMATCH")
    runtime_limits = request.get("budget", {})
    if (runtime_limits.get("cpu_budget_seconds") != 7200
            or runtime_limits.get("wall_timeout_seconds") != 7200
            or runtime_limits.get("memory_max_bytes") != 8589934592
            or runtime_limits.get("cpu_affinity") != [0]
            or runtime_limits.get("threads") != 1):
        raise RuntimeError("FORMAL_BUDGET_BINDING_MISMATCH")
    if (runtime_config.get("cuda_visible_devices") != "1"
            or runtime_config.get("physical_gpu_index") != 1
            or runtime_config.get("cpu_affinity") != [0]
            or runtime_config.get("threads") != 1):
        raise RuntimeError("FORMAL_PHYSICAL_GPU_AND_CPU_MAPPING_MISMATCH")
    environment = json.loads((args.source_root / "configs/ENVIRONMENT_SPEC.json").read_text(encoding="utf-8"))
    if (environment.get("environment", {}).get("CUDA_VISIBLE_DEVICES") != "1"
            or environment.get("physical_gpu_index") != 1
            or environment.get("cpu_affinity") != [0]
            or environment.get("threads") != 1):
        raise RuntimeError("FORMAL_ENVIRONMENT_SPEC_MAPPING_MISMATCH")
    if args.verify_only:
        print(json.dumps({"status": "verified", "attempt_id": attempt["attempt_id"], "run_id": attempt["run_id"], "manifest_sha256": manifest_sha}, sort_keys=True))
        return 0
    # Formal runs are launched in a fresh transient unit. This counter covers
    # restore subprocesses as well as the main worker, unlike per-process rlimit.
    cgroup_cpu_start = cgroup_cpu_seconds()
    args.output.mkdir(parents=True, exist_ok=False)
    run_id = attempt["run_id"]
    write(args.output / "RUNTIME_IDENTITY.json", {"schema": "n02-event-runtime/1", "attempt": args.attempt, "run_id": run_id, "pid": os.getpid(), "systemd_invocation_id": os.environ.get("INVOCATION_ID"), "runtime": witness, "source_manifest_sha256": manifest_sha, "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "config_sha256": config_sha, "source_files_verified": len(manifest["files"])})
    command = [sys.executable, "-B", str(args.source_root / "package/civilian/region_pilot.py"), "--output", str(args.output / "pilot"), "--config", str(args.config), "--device", device]
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
    restore_receipts = []
    if code == 0:
        checkpoint_paths = sorted((args.output / "pilot").glob("*/seed_*/checkpoint.pt"))
        if len(checkpoint_paths) != 2:
            raise RuntimeError(f"FRESH_PROCESS_RESTORE_CHECKPOINT_SET_MISMATCH:{len(checkpoint_paths)}")
        for checkpoint in checkpoint_paths:
            restore_start = time.monotonic()
            restore_command = [
                sys.executable, "-B", str(args.source_root / "package/civilian/region_pilot.py"),
                "--restore", str(checkpoint), "--device", device,
            ]
            completed = subprocess.run(
                restore_command, cwd=args.source_root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            receipt = {
                "schema": "n02-v3-fresh-process-restore-receipt/1",
                "checkpoint": str(checkpoint),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "argv": restore_command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wall_seconds": time.monotonic() - restore_start,
            }
            restore_receipts.append(receipt)
            if completed.returncode != 0:
                raise RuntimeError(f"FRESH_PROCESS_RESTORE_FAILED:{checkpoint}")
        write(args.output / "FRESH_PROCESS_RESTORE_RECEIPTS.json", {
            "schema": "n02-v3-fresh-process-restore-settlement/1",
            "attempt": args.attempt, "run_id": run_id, "receipts": restore_receipts,
        })
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
    gpu_receipt_path = args.output / "pilot" / "GPU_EXECUTION_RECEIPT.json"
    if child.returncode == 0:
        if not gpu_receipt_path.is_file():
            raise RuntimeError("GPU_EXECUTION_RECEIPT_MISSING")
        gpu_receipt = json.loads(gpu_receipt_path.read_text(encoding="utf-8"))
        if (gpu_receipt.get("status") != "complete" or gpu_receipt.get("device") != "cuda:0"
                or gpu_receipt.get("peak_memory_allocated_bytes", 0) <= 0
                or gpu_receipt.get("policy_parameter_devices") != ["cuda:0"]
                or gpu_receipt.get("policy_optimizer_state_devices") != ["cuda:0"]):
            raise RuntimeError("GPU_EXECUTION_RECEIPT_DEVICE_AUDIT_FAILED")
    manifest = {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.rglob("*")) if p.is_file()}
    write(args.output / "REMOTE_EVIDENCE_HASHES.json", {"schema": "n02-event-evidence-hashes/1", "attempt": args.attempt, "files": manifest})
    print(json.dumps({"attempt": args.attempt, "run_id": run_id, "child_exit_code": code, "timed_out": timed_out, "output": str(args.output), "gpu_witness": witness}, sort_keys=True), flush=True)
    return guardian_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
