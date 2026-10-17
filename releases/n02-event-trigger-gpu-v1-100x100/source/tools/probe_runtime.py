"""Run the documented runtime witness through Windows bundled OpenSSH."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--context", type=Path, required=True, help="Private local host/interpreter JSON; never publish it")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    context = json.loads(a.context.read_text(encoding="utf-8"))
    source = Path(__file__).with_name("runtime_guardian.py").read_bytes()
    argv = [context["python"], "-B", "-", "--source-root", "/tmp", "--output", "/tmp", "--config", "/tmp", "--attempt", "runtime-witness-only", "--probe-only"]
    command = ["C:/Windows/System32/OpenSSH/ssh.exe", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "PreferredAuthentications=publickey", "-o", "PasswordAuthentication=no", context["host"], shlex.join(argv)]
    result = subprocess.run(command, input=source, capture_output=True, timeout=60, check=True)
    receipt = json.loads(result.stdout)
    if receipt["mismatches"]:
        raise RuntimeError(receipt["mismatches"])
    receipt["probe_source_sha256"] = hashlib.sha256(source).hexdigest()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
