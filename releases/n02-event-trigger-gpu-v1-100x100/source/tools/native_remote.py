"""Native Windows OpenSSH deployment, execution and evidence retrieval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import uuid

SSH = Path("C:/Windows/System32/OpenSSH/ssh.exe")
SCP = Path("C:/Windows/System32/OpenSSH/scp.exe")


def call(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, check=False, capture_output=True, encoding="utf-8", errors="replace", **kwargs)
    if result.returncode:
        # Keep the actual OpenSSH/remote diagnostic, not only CalledProcessError.
        raise RuntimeError(f"native command exit={result.returncode}: {result.stderr.strip()} {result.stdout.strip()}")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["stage", "probe", "launch", "status", "retrieve"])
    p.add_argument("--host", required=True)
    p.add_argument("--remote-root", required=True)
    p.add_argument("--python", required=True)
    p.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--stage", default="all")
    a = p.parse_args()
    if not SSH.is_file() or not SCP.is_file():
        raise FileNotFoundError("Windows bundled OpenSSH ssh.exe and scp.exe required")
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "PreferredAuthentications=publickey", "-o", "PasswordAuthentication=no"]
    def remote(argv: list[str], **kwargs) -> str:
        kwargs.setdefault("timeout", 60)
        result = call([str(SSH), *options, a.host, shlex.join(argv)], **kwargs)
        return result.stdout
    if a.operation == "stage":
        attempt = "n02-event-gpu-v1-" + uuid.uuid4().hex
        stage = a.remote_root.rstrip("/") + "/" + attempt
        source = a.source.resolve()
        inventory = json.loads((source / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))["files"]
        files = list(inventory) + ["SOURCE_MANIFEST.json", "SHA256SUMS.txt", "REQUEST.json"]
        archive = a.state.parent / (attempt + ".tar.gz")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tf:
            for relative in sorted(files):
                tf.add(source / relative, arcname=relative, recursive=False)
        remote(["mkdir", "-p", stage])
        call([str(SCP), *options, str(archive), a.host + ":" + stage + "/source.tar.gz"], timeout=180)
        extract = "import tarfile,sys,pathlib; p=pathlib.Path(sys.argv[1]); tarfile.open(p/'source.tar.gz').extractall(p/'source',filter='data')"
        remote([a.python, "-B", "-c", extract, stage])
        verify = "import json,hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); d=json.loads((p/'SOURCE_MANIFEST.json').read_text()); bad=[x for x,h in d['files'].items() if hashlib.sha256((p/x).read_bytes()).hexdigest()!=h]; assert not bad,bad; print(json.dumps({'verified_files':len(d['files']),'manifest_sha256':hashlib.sha256((p/'SOURCE_MANIFEST.json').read_bytes()).hexdigest()}))"
        verified = json.loads(remote([a.python, "-B", "-c", verify, stage + "/source"]))
        runtime = json.loads((source / "configs/EVENT_TRIGGER_CONFIG.json").read_text(encoding="utf-8"))["runtime"]
        state = {"schema": "n02-event-native-deployment/1", "attempt": attempt, "stage_root": stage, "source_root": stage + "/source", "output": stage + "/result", "unit": attempt + ".service", "runtime_limits": runtime, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), **verified}
        a.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(state), flush=True)
        return
    state = json.loads(a.state.read_text(encoding="utf-8"))
    source = state["source_root"]
    guard = [a.python, "-B", source + "/tools/runtime_guardian.py", "--source-root", source, "--output", state["output"], "--config", source + "/configs/EVENT_TRIGGER_CONFIG.json", "--attempt", state["attempt"]]
    if a.operation == "probe":
        print(remote([*guard, "--probe-only"]), end="")
    elif a.operation == "launch":
        # Unique transient unit, no shell command concatenation, no inherited old runs.
        memory_limit = str(int(state["runtime_limits"]["memory_max_bytes"]))
        visible_devices = str(state["runtime_limits"]["cuda_visible_devices"])
        command = ["systemd-run", "--user", "--unit", state["unit"], "--property", "Type=exec", "--property", "MemoryMax=" + memory_limit, "--property", "RuntimeMaxSec=7260", "--property", "CPUQuota=100%", "--property", "CPUAffinity=0", "--property", "KillMode=control-group", "--setenv", "CUDA_VISIBLE_DEVICES=" + visible_devices, "--setenv", "OMP_NUM_THREADS=1", "--setenv", "OPENBLAS_NUM_THREADS=1", "--setenv", "MKL_NUM_THREADS=1", "--setenv", "NUMEXPR_NUM_THREADS=1", "--setenv", "PYTHONDONTWRITEBYTECODE=1", *guard, "--stage", a.stage]
        print(remote(command), end="")
        handoff = remote(["systemctl", "--user", "show", state["unit"], "--property=InvocationID,MainPID,ActiveState,SubState,ExecMainStatus,Result,LoadState"])
        state["launch_handoff"] = dict(line.split("=", 1) for line in handoff.splitlines() if "=" in line)
        a.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(handoff, end="")
    elif a.operation == "status":
        try:
            print(remote(["systemctl", "--user", "show", state["unit"], "--property=InvocationID,MainPID,ActiveState,SubState,ExecMainStatus,Result,LoadState,CPUUsageNSec,MemoryPeak"]), end="")
        except RuntimeError as error:
            # A completed transient unit may have been garbage-collected. Its
            # persisted guardian receipts and journal are still authoritative.
            print(json.dumps({"unit_query_error": str(error), "unit": state["unit"]}))
        print(remote(["journalctl", "--user", "-u", state["unit"], "--no-pager", "-n", "12", "-o", "cat"]), end="")
        probe = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); print((p/'GUARDIAN_SETTLEMENT.json').read_text() if (p/'GUARDIAN_SETTLEMENT.json').exists() else 'GUARDIAN_PENDING'); print((p/'console.log').read_text()[-5000:] if (p/'console.log').exists() else 'NO_CONSOLE_YET')"
        print(remote([a.python, "-B", "-c", probe, state["output"]]), end="")
    elif a.operation == "retrieve":
        destination = a.state.parent / (state["attempt"] + "-result")
        destination.mkdir(exist_ok=True)
        remote_archive = state["stage_root"] + "/result-evidence.tar.gz"
        archive_code = "import pathlib,tarfile,sys; root=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); with_open=False; tf=tarfile.open(out,'w:gz',compresslevel=1); [tf.add(p,arcname=p.relative_to(root).as_posix(),recursive=False) for p in sorted(root.rglob('*')) if p.is_file()]; tf.close()"
        remote([a.python, "-B", "-c", archive_code, state["output"], remote_archive], timeout=3600)
        archive_local = a.state.parent / (state["attempt"] + "-result.tar.gz")
        call([str(SCP), *options, a.host + ":" + remote_archive, str(archive_local)], timeout=3600)
        with tarfile.open(archive_local, "r:gz") as tf:
            root = destination.resolve()
            members = tf.getmembers()
            if any(Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members):
                raise ValueError("REMOTE_EVIDENCE_ARCHIVE_PATH_TRAVERSAL")
            tf.extractall(destination, filter="data")
        hash_path = destination / "REMOTE_EVIDENCE_HASHES.json"
        if not hash_path.is_file():
            # Preserve evidence after systemd/OOM kills even if the guardian
            # did not reach settlement. Hash the current remote snapshot and
            # explicitly label it incomplete; never turn it into a PASS.
            snapshot_code = "import json,hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(json.dumps({'schema':'n02-event-incomplete-recovery-hashes/1','files':{f.relative_to(p).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file()}}))"
            manifest = json.loads(remote([a.python, "-B", "-c", snapshot_code, state["output"]]))
            for relative, expected in manifest["files"].items():
                if not (destination / relative).is_file() or hashlib.sha256((destination / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError(f"Incomplete evidence changed during recovery: {relative}")
            (destination / "INCOMPLETE_RECOVERY_RECEIPT.json").write_text(json.dumps({"status": "INCOMPLETE_NO_ACCEPTANCE", "attempt": state["attempt"], **manifest}, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"destination": str(destination), "matched_files": len(manifest["files"]), "attempt": state["attempt"], "status": "INCOMPLETE_NO_ACCEPTANCE"}), flush=True)
            return
        manifest = json.loads(hash_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            actual = hashlib.sha256((destination / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Downloaded evidence hash mismatch: {relative}")
        print(json.dumps({"destination": str(destination), "matched_files": len(manifest["files"]), "attempt": state["attempt"]}), flush=True)


if __name__ == "__main__":
    main()
