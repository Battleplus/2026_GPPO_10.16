#!/usr/bin/env python3
"""Audit an archive tree against an explicit allowlist and privacy policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 5 * 1024 * 1024
BLOCKED_SUFFIXES = {
    ".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".db3", ".wal", ".shm",
    ".pem", ".p12", ".pfx", ".key", ".pt", ".pth", ".ckpt", ".safetensors",
    ".onnx", ".bin", ".log", ".pickle", ".pkl", ".zip", ".tar", ".gz", ".7z", ".rar",
}
BLOCKED_PATH_PARTS = {
    ".git", ".ssh", "__pycache__", ".pytest_cache", "credentials", "secrets",
    "private_keys", "private-keys",
}
BLOCKED_NAMES = re.compile(
    r"(?i)(^|[._-])(id_rsa|id_ed25519|known_hosts|ssh_config|access_token|private_key|auth_binding|authorization)([._-]|$)"
)
WINDOWS_ABSOLUTE = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"'<>|]+")
BACKSLASH = chr(92)
UNC_ABSOLUTE = re.compile(BACKSLASH * 2 + r"[^" + BACKSLASH + r"\s]+" + BACKSLASH + r"[^" + BACKSLASH + r"\s]+")
PERSONAL_POSIX_PATH = re.compile(r"(?i)(?<![A-Za-z0-9_])/(?:home|users)/[^/\s\"'<>]+(?:/[^\s\"'<>]*)?")
IPV4_LITERAL = re.compile(
    r"(?<![0-9])(?:25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])){3}(?![0-9])"
)
SSH_CONFIG_LINE = re.compile(r"(?im)^\s*(?:HostName|IdentityFile|ProxyCommand)\s+\S+")
PRIVATE_ENDPOINT_FIELD = re.compile(
    r"(?im)^\s*[\"']?(?:host_name|hostname|server_host|server_ip|ssh_user|username)[\"']?\s*[:=]\s*"
    r"[\"']?(?!<|placeholder\b|redacted\b|pending\b|unknown\b|not[-_ ]?set\b)([^\s,;\"']+)"
)
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")
KNOWN_TOKEN = re.compile(
    r"(?i)(?:\bgh[pousr]_[A-Za-z0-9_]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bhf_[A-Za-z0-9]{24,}|\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bASIA[0-9A-Z]{16}\b|\bxox[baprs]-[A-Za-z0-9-]{20,}|"
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?im)[\"']?([A-Za-z0-9_.-]*(?:token|secret|password|api[_-]?key|private[_-]?key|credential)"
    r"[A-Za-z0-9_.-]*)[\"']?\s*[:=]\s*[\"']?([^\s,;\"']+)"
)
PLACEHOLDER = re.compile(
    r"(?i)^(?:<[^>]+>|\[[^]]+\]|redacted|placeholder|pending|not[-_ ]?set|"
    r"not[-_ ]?(?:authorized|created)|unavailable|null|none|false|)$"
)
SENSITIVE_JSON_FIELDS = {
    "host", "hostname", "host_name", "server", "server_host", "server_ip",
    "ssh_host", "ssh_user", "username", "user_name", "ip", "ip_address",
}
SECRET_JSON_FIELDS = {
    "token", "access_token", "api_key", "password", "private_key", "credential",
    "authorization", "authorization_binding",
}
TRUE_ONLY_DENY_FIELDS = {"authorized", "authorization_created", "execution_started", "attempt_started", "request_frozen"}


def entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def normalized_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def validate_allowlist(path: Path) -> list[str]:
    entries: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = PurePosixPath(line.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
            raise ValueError(f"invalid allowlist path: {line}")
        entries.append(candidate.as_posix())
    if len(entries) != len(set(entries)):
        raise ValueError("duplicate allowlist entries")
    return sorted(entries)


def path_findings(relative: str) -> list[str]:
    path = PurePosixPath(relative)
    findings: list[str] = []
    if any(part.casefold() in BLOCKED_PATH_PARTS for part in path.parts):
        findings.append("blocked credential/cache path")
    if path.suffix.casefold() in BLOCKED_SUFFIXES:
        findings.append("blocked sensitive or binary file type")
    if path.name.casefold().endswith(("-wal", "-shm")):
        findings.append("blocked SQLite sidecar")
    if BLOCKED_NAMES.search(path.name):
        findings.append("blocked credential or authorization filename")
    if path.suffix.casefold() in {".jsonl", ".ndjson"} and "evidence" not in path.parts:
        findings.append("raw line-oriented data requires explicit reviewed evidence scope")
    return findings


def content_findings(data: bytes) -> list[str]:
    findings: list[str] = []
    if b"SQLite format 3\x00" in data[:32]:
        findings.append("SQLite database signature")
    if b"\x00" in data:
        findings.append("binary or non-text content")
        return findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["content is not UTF-8 text"]

    checks = (
        (WINDOWS_ABSOLUTE, "absolute Windows path"),
        (UNC_ABSOLUTE, "absolute network path"),
        (PERSONAL_POSIX_PATH, "personal POSIX path"),
        (IPV4_LITERAL, "IP address literal"),
        (SSH_CONFIG_LINE, "SSH configuration directive"),
        (PRIVATE_ENDPOINT_FIELD, "host, IP, or user field with a concrete value"),
        (PRIVATE_KEY_BLOCK, "private key block"),
        (KNOWN_TOKEN, "known high-entropy credential pattern"),
    )
    for pattern, label in checks:
        if pattern.search(text):
            findings.append(label)

    for match in SECRET_ASSIGNMENT.finditer(text):
        key, value = match.groups()
        if re.search(r"(?i)(sha.?256|hash|digest|fingerprint)", key):
            continue
        if PLACEHOLDER.fullmatch(value):
            continue
        if len(value) >= 20 and entropy(value) >= 3.3:
            findings.append("high-entropy value assigned to a credential field")
            break

    return findings


def structured_findings(relative: str, data: bytes) -> list[str]:
    if PurePosixPath(relative).suffix.casefold() != ".json":
        return []
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["invalid JSON document"]

    findings: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = re.sub(r"[^a-z0-9]", "", str(raw_key).casefold())
                active_value = child is True or child == 1 or (
                    isinstance(child, str) and child.strip().casefold() in {"true", "yes", "1", "active", "enabled"}
                )
                if key in TRUE_ONLY_DENY_FIELDS and active_value:
                    findings.append("formal authorization or execution state is active")
                if key in SENSITIVE_JSON_FIELDS and child not in (None, False, 0, ""):
                    if not (isinstance(child, str) and PLACEHOLDER.fullmatch(child.strip())):
                        findings.append("host, IP, or user value in structured data")
                if key in SECRET_JSON_FIELDS and child not in (None, False, 0, ""):
                    if isinstance(child, str) and PLACEHOLDER.fullmatch(child.strip()):
                        pass
                    elif re.search(r"(?i)(sha.?256|hash|digest|fingerprint)", key):
                        pass
                    else:
                        findings.append("credential or authorization value in structured data")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return sorted(set(findings))


def self_check() -> list[str]:
    benign = (
        b"Documentation mentions token and secret as policy terms.\n",
        b'{"candidate_sha256":"' + (b"a" * 64) + b'","authorized":false}\n',
        b"schema: n02-public-sanitized-inventory/1\n",
        b'candidate_id = "n02_candidate_identity_seed_8201_v1"\n',
        b'pattern = r"[A-Z]:[\\\\/]"\n',
    )
    failures = ["benign content was falsely flagged" for sample in benign if content_findings(sample)]
    generated_credential = "".join(chr(ord("A") + index) for index in range(26)) + "0123456789"
    detected = content_findings(("api_key=" + generated_credential).encode("utf-8"))
    if "high-entropy value assigned to a credential field" not in detected:
        failures.append("synthetic high-entropy credential was not detected")
    candidate = b'{"authorized":false,"request_frozen":false,"source_sha256":"' + (b"b" * 64) + b'"}'
    if structured_findings("REQUEST_CANDIDATE.json", candidate):
        failures.append("unauthorized request candidate was falsely rejected")
    active = b'{"authorized":true}'
    if "formal authorization or execution state is active" not in structured_findings("request.json", active):
        failures.append("active authorization state was not rejected")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allowlist", type=Path, default=None)
    parser.add_argument("--self-check", action="store_true", help="check policy handling with synthetic values only")
    args = parser.parse_args()

    if args.self_check:
        failures = self_check()
        print(json.dumps({"status": "PASS" if not failures else "FAIL", "findings": failures}, indent=2))
        return 0 if not failures else 1

    root = args.root.resolve()
    allowlist_path = (args.allowlist or (root / "PUBLIC_ALLOWLIST.txt")).resolve()
    if not root.is_dir() or not allowlist_path.is_file():
        print(json.dumps({"status": "BLOCKED", "findings": ["root or allowlist is missing"]}))
        return 2

    try:
        allowed = validate_allowlist(allowlist_path)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "findings": [str(exc)]}))
        return 2

    findings: list[dict[str, str]] = []
    actual_paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        for dir_name in list(directory_names):
            directory_path = current / dir_name
            relative_directory = normalized_relative(directory_path, root)
            if current == root and dir_name.casefold() == ".git":
                directory_names.remove(dir_name)
                continue
            if directory_path.is_symlink():
                findings.append({"path": relative_directory, "reason": "symbolic link"})
                directory_names.remove(dir_name)
                continue
            if dir_name.casefold() == ".git" or dir_name.casefold() in BLOCKED_PATH_PARTS:
                findings.append({"path": relative_directory, "reason": "blocked metadata or credential/cache directory"})
                directory_names.remove(dir_name)

        for file_name in file_names:
            if current == root and file_name.casefold() == ".git":
                continue
            item = current / file_name
            relative = normalized_relative(item, root)
            if item.is_symlink():
                findings.append({"path": relative, "reason": "symbolic link"})
                continue
            actual_paths.append(item)
            if relative not in allowed:
                findings.append({"path": relative, "reason": "not present in explicit allowlist"})
            for reason in path_findings(relative):
                findings.append({"path": relative, "reason": reason})
            try:
                size = item.stat().st_size
                if size > MAX_FILE_BYTES:
                    findings.append({"path": relative, "reason": "file exceeds 5 MiB review limit"})
                    continue
                data = item.read_bytes()
            except OSError:
                findings.append({"path": relative, "reason": "file could not be read"})
                continue
            for reason in content_findings(data):
                findings.append({"path": relative, "reason": reason})
            for reason in structured_findings(relative, data):
                findings.append({"path": relative, "reason": reason})

    actual = {normalized_relative(path, root) for path in actual_paths}
    for missing in sorted(set(allowed) - actual):
        findings.append({"path": missing, "reason": "allowlisted file is missing"})

    records = []
    for item in sorted(actual_paths, key=lambda path: normalized_relative(path, root)):
        relative = normalized_relative(item, root)
        try:
            data = item.read_bytes()
        except OSError:
            continue
        records.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result = {
        "schema": "n02-public-sanitized-inventory/1",
        "status": "PASS_POLICY_SCAN" if not findings else "BLOCKED",
        "allowlisted_file_count": len(allowed),
        "scanned_file_count": len(actual_paths),
        "findings": findings,
        "public_sanitized_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": records,
        "review_boundary": "Policy scan only; independent scientific and release review remain required.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
