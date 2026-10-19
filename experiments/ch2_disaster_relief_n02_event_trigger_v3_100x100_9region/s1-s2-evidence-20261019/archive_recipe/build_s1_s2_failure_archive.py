#!/usr/bin/env python3
"""Build an unpublished, sanitized S1/S2 failure archive candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


HERE = Path(__file__).resolve().parent
ARCHIVE_ROOT = HERE.parent
BUILDER_PATH = ARCHIVE_ROOT / "build_public_archive.py"
SOURCE_MANIFEST_SHA256 = "1a36e8d2f8eed88e43dc352ac1082eb3351041d3d5eb3b950ac85e98786cd9de"
RESULT_MANIFEST_SHA256 = "21bbcd8769810d2988ed1edf79976107c8d8696b15cdd4565677cc748aa0d35a"
RESULT_RELEASE = "n02-v3-s2-bd8054b27c114c9fafffd77734b7ee8d"
ATTEMPT_ID = "99a7e67bc1684fcb94a231e8c72a728e"
RUN_ID = "eb5fee7ed88c43068f5796944727e031"
OMITTED_SOURCE = {
    "tools/native_v3_remote.py": "deployment helper omitted from public package; contains server connection and deployment details"
}


def load_builder():
    spec = importlib.util.spec_from_file_location("s0_public_archive_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the existing public archive builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_result_manifest(builder, freeze_root: Path) -> dict:
    raw = (freeze_root / "RESULT_MANIFEST.json").read_bytes()
    if builder.sha256(raw) != RESULT_MANIFEST_SHA256:
        raise builder.ArchiveError("frozen result manifest SHA-256 mismatch")
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("release") != RESULT_RELEASE or manifest.get("attempt_id") != ATTEMPT_ID or manifest.get("run_id") != RUN_ID:
        raise builder.ArchiveError("frozen result identity mismatch")
    if manifest.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256 or manifest.get("status") != "FROZEN_REAL_RUN_PENDING_INDEPENDENT_REVIEW":
        raise builder.ArchiveError("frozen source identity or result status mismatch")
    for rel, expected in manifest.get("files", {}).items():
        path = freeze_root.joinpath(*PurePosixPath(rel).parts)
        if not path.is_file() or path.is_symlink() or hash_file(path) != expected:
            raise builder.ArchiveError(f"frozen result file mismatch: {rel}")
    if len(manifest.get("files", {})) != manifest.get("evidence_file_count", -1) + manifest.get("source_file_count_including_auxiliary", -1):
        raise builder.ArchiveError("frozen result file counts do not reconcile")
    return manifest


def add_public(builder, stage: Path, mapping: list[dict], rel: str, source: Path, transform: str) -> None:
    builder.add_public_file(stage, mapping, rel, source, transform=transform)


def add_text_derivative(builder, stage: Path, mapping: list[dict], rel: str, source: Path, replacements: list[tuple[str, str]]) -> None:
    original = source.read_bytes()
    text = original.decode("utf-8")
    for pattern in builder.PATH_PATTERNS:
        text = pattern.sub(builder.REDACTED, text)
    for before, after in replacements:
        if before not in text:
            raise builder.ArchiveError(f"expected public-copy text not found in {source.name}")
        text = text.replace(before, after)
    public = text.encode("utf-8")
    builder.validate_text(rel, public)
    write(stage.joinpath(*PurePosixPath(rel).parts), public)
    mapping.append({
        "public_path": rel,
        "source_sha256": builder.sha256(original),
        "public_sha256": builder.sha256(public),
        "source_bytes": len(original),
        "public_bytes": len(public),
        "transformation": "text_paths_redacted_with_public_reference_updates",
    })


def build(output: Path, freeze_root: Path, sol_root: Path, decision: Path, diagnosis_root: Path) -> dict:
    builder = load_builder()
    freeze_root = freeze_root.resolve()
    sol_root = sol_root.resolve()
    decision = decision.resolve()
    diagnosis_root = diagnosis_root.resolve()
    output = output.resolve()
    if not output.is_relative_to(HERE) or output.exists() or output in freeze_root.parents or freeze_root in output.parents:
        raise builder.ArchiveError("output must be a new directory under this preparation workspace and disjoint from frozen input")

    source_root = freeze_root / "source"
    source_manifest, source_raw = builder.checked_manifest(
        source_root,
        "SOURCE_MANIFEST.json",
        expected_release=RESULT_RELEASE,
        allowed_unmanifested={"SOURCE_MANIFEST.json", "SHA256SUMS.txt", "REQUEST_CANDIDATE.json"},
    )
    if builder.sha256(source_raw) != SOURCE_MANIFEST_SHA256:
        raise builder.ArchiveError("frozen source manifest SHA-256 mismatch")
    result_manifest = check_result_manifest(builder, freeze_root)
    evidence_root = freeze_root / "evidence"
    engineering_gate = evidence_root / "run/output/pilot/S2_ENGINEERING_GATE.json"
    gate = load_json(engineering_gate)
    if gate.get("schema") != "n02-v3-s2-engineering-gate/1" or gate.get("status") != "REPAIR_REQUIRED" or gate.get("S3_allowed") is not False:
        raise builder.ArchiveError("producer gate does not bind the expected failed S2 state")

    s1_review_path = sol_root / "s1_audit/S1_REVIEW.json"
    s1_review = load_json(s1_review_path)
    if s1_review.get("S1") != "PASS" or s1_review.get("S2_acceptance") != "NOT_RUN":
        raise builder.ArchiveError("S1 review identity/status changed")
    decision_raw = decision.read_bytes()
    decision_text = decision_raw.decode("utf-8")
    if "s2 fail" not in decision_text.lower() or "s3 is blocked" not in decision_text.lower():
        raise builder.ArchiveError("coordinator decision no longer records the independent S2 failure")
    s2_review_json = sol_root / "s2_result_audit/S2_RESULT_REVIEW.json"
    s2_review_md = sol_root / "s2_result_audit/S2_RESULT_REVIEW.md"
    s2_review = load_json(s2_review_json)
    if s2_review.get("S2") != "FAIL" or s2_review.get("S3") != "BLOCKED" or s2_review.get("S3_allowed") is not False:
        raise builder.ArchiveError("independent S2 review does not record the expected failure")
    diagnosis_json = diagnosis_root / "FIRST_ZERO_DIAGNOSIS.json"
    diagnosis_md = diagnosis_root / "DIAGNOSIS.md"
    diagnosis_addendum = diagnosis_root / "ADDENDUM_FINAL_REVIEW_METRICS.md"
    diagnosis_code = diagnosis_root / "reproduce_first_zero.py"

    temporary = output.with_name(output.name + ".building-" + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    mapping: list[dict] = []
    try:
        omitted = []
        recipe_path = Path(__file__).resolve()
        add_public(builder, temporary, mapping, "archive_recipe/build_s1_s2_failure_archive.py", recipe_path, "copy")
        for rel in sorted(source_manifest["files"]):
            source = source_root.joinpath(*PurePosixPath(rel).parts)
            if rel in OMITTED_SOURCE:
                omitted.append({"source_path": rel, "source_sha256": hash_file(source), "reason": OMITTED_SOURCE[rel]})
                continue
            transform = "copy"
            if source.suffix.lower() in {".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini", ".patch", ".py"}:
                raw = source.read_bytes()
                text = raw.decode("utf-8")
                if any(pattern.search(text) for pattern in builder.PATH_PATTERNS):
                    transform = "json_redacted" if source.suffix.lower() == ".json" else "text_paths_redacted"
            add_public(builder, temporary, mapping, f"source/{rel}", source, transform)
        add_public(builder, temporary, mapping, "source/SOURCE_MANIFEST.json", source_root / "SOURCE_MANIFEST.json", "json_redacted")

        add_public(builder, temporary, mapping, "reports/s1/S1_PUBLIC_REVIEW_SUMMARY.md", sol_root / "s1_audit/S1_PUBLIC_REVIEW_SUMMARY.md", "text_paths_redacted")
        add_public(builder, temporary, mapping, "reports/s1/S1_REVIEW.json", s1_review_path, "json_redacted")
        add_public(builder, temporary, mapping, "reports/s2/S2_COORDINATOR_DECISION.md", decision, "text_paths_redacted")
        add_public(builder, temporary, mapping, "evidence/s2/S2_ENGINEERING_GATE.json", engineering_gate, "json_redacted")
        add_public(builder, temporary, mapping, "reports/s2/S2_RESULT_REVIEW.md", s2_review_md, "text_paths_redacted")
        add_public(builder, temporary, mapping, "reports/s2/S2_RESULT_REVIEW.json", s2_review_json, "json_redacted")
        add_text_derivative(builder, temporary, mapping, "reports/s2/FIRST_ZERO_DIAGNOSIS.md", diagnosis_md, [
            (
                "Run `python reproduce_first_zero.py` from this directory. It validates the frozen manifest digest and extracts `FIRST_ZERO_DIAGNOSIS.json` from the existing audit output; it does not load the simulator or execute a policy.",
                "The original `reproduce_first_zero.py` helper is valid only within its original private preparation directory because it embeds machine-specific input and output roots, and it is excluded from this public archive. The included diagnosis JSON is the derived read-only result; no simulator or policy was run to produce this summary.",
            ),
        ])
        add_public(builder, temporary, mapping, "reports/s2/FIRST_ZERO_DIAGNOSIS.json", diagnosis_json, "json_redacted")
        add_text_derivative(builder, temporary, mapping, "reports/s2/ADDENDUM_FINAL_REVIEW_METRICS.md", diagnosis_addendum, [
            ("`DIAGNOSIS.md`", "`FIRST_ZERO_DIAGNOSIS.md`"),
        ])
        correction_source_hash = hash_file(diagnosis_json)
        correction_text = (
            "# Public Correction: Episode Count\n\n"
            "The included `FIRST_ZERO_DIAGNOSIS.json` preserves its source field `paired_development_episode_count: 6` and its source hash mapping. That field is misleadingly named: the value counts all six reviewed episodes across splits, not six development episodes. The final review contains 2 development episodes and 4 training episodes. The development gate means are computed over the 2 development episodes only. This correction clarifies the field without changing the source artifact or its mapping.\n"
        ).encode("utf-8")
        builder.validate_text("reports/s2/FIRST_ZERO_DIAGNOSIS_PUBLIC_CORRECTION.md", correction_text)
        write(temporary / "reports/s2/FIRST_ZERO_DIAGNOSIS_PUBLIC_CORRECTION.md", correction_text)
        mapping.append({
            "public_path": "reports/s2/FIRST_ZERO_DIAGNOSIS_PUBLIC_CORRECTION.md",
            "source_sha256": correction_source_hash,
            "public_sha256": builder.sha256(correction_text),
            "source_bytes": diagnosis_json.stat().st_size,
            "public_bytes": len(correction_text),
            "transformation": "generated_public_correction_from_mapped_source_json",
        })
        omitted.append({
            "source_path": "s2_first_zero_diagnosis/reproduce_first_zero.py",
            "source_sha256": hash_file(diagnosis_code),
            "reason": "analysis helper has machine-specific absolute input/output roots; its derived JSON and human-readable diagnosis are included",
        })

        identity = {
            "schema": "n02-v3-s1-s2-failure-archive-identity/1",
            "release": RESULT_RELEASE,
            "attempt_id": ATTEMPT_ID,
            "run_id": RUN_ID,
            "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "evidence_manifest_sha256": None,
            "result_manifest_sha256": RESULT_MANIFEST_SHA256,
            "producer_gate": "REPAIR_REQUIRED",
            "S1": "PASS_CPU_MECHANISM_GATE_ONLY",
            "S2": "FAIL_REPAIR_REQUIRED_INDEPENDENT_REVIEW_PROVISIONAL",
            "S3": "NOT_RUN",
            "S3NOTRUN": True,
            "S3_allowed": False,
            "noWM": True,
            "world_model": "NOT_PRESENT_IN_THIS_TRIAL",
            "periodic_actor": "UNCHANGED",
            "builder_public_sha256": next(item["public_sha256"] for item in mapping if item["public_path"] == "archive_recipe/build_s1_s2_failure_archive.py"),
            "publication": "NOT_APPROVED_PENDING_SOL_REVIEW",
            "source_omissions": omitted,
            "builder_sha256": hash_file(Path(__file__).resolve()),
        }
        write(temporary / "PUBLIC_ARCHIVE_IDENTITY.json", canonical_json(identity))

        hash_mapping = {
            "schema": "n02-v3-public-hash-mapping/1",
            "source_file_mappings": sorted(mapping, key=lambda item: item["public_path"]),
            "excluded_source_files": omitted,
            "notes": [
                "source_sha256 identifies original frozen/audit bytes; public_sha256 identifies staged bytes.",
                "copy preserves bytes exactly; json_redacted and text_paths_redacted are derived public copies.",
                "The S2 gate JSON is the compact registered producer gate evidence; it does not assert independent review completion.",
                "Generated metadata has no single source file and is separately identified by generated_metadata in the inventory.",
                "The archived build recipe is byte-identical to the script used for this build; builder_sha256 must equal its source_sha256 and builder_public_sha256.",
            ],
        }
        write(temporary / "PUBLIC_HASH_MAPPING.json", canonical_json(hash_mapping))
        write(temporary / "PUBLIC_EXCLUSIONS.json", canonical_json({
            "schema": "n02-v3-public-archive-exclusions/1",
            "excluded_frozen_result_files": [
                {"path": "evidence/run/output/pilot/Event-G/seed_8201/checkpoint.pt", "reason": "checkpoint binary excluded"},
                {"path": "evidence/run/output/pilot/Periodic-G/seed_8201/checkpoint.pt", "reason": "checkpoint binary excluded"},
                {"path": "evidence/run/output/**/console.log, *.jsonl, *trajectory.json", "reason": "large/raw execution logs and trajectories excluded from compact public candidate"},
                {"path": "evidence/run/AUTHORIZATION_BINDING.json", "reason": "authorization/binding original excluded"},
                {"path": "evidence/control/PUBLISHING_BINDING.json", "reason": "publishing binding original excluded"},
                {"path": "evidence/control/**", "reason": "private control and entry artifacts excluded"},
            ],
            "excluded_source_files": omitted,
            "disclosure": "All excluded source/result files remain preserved in their original frozen locations; this archive candidate does not modify them.",
        }))

        write(temporary / "PUBLIC_ARCHIVE_STATUS.json", canonical_json({
            "schema": "n02-v3-public-archive-status/1",
            "candidate_state": "PENDING_SOL_REVIEW",
            "S1": "PASS_CPU_MECHANISM_GATE_ONLY",
            "S1_scope_limitations": "No PPO, learned-trigger, world-model, research-performance, or policy-selected regional-replanning acceptance; all 45 paired task outcomes identical within observed horizon.",
            "S2": "REPAIR_REQUIRED",
            "S2_independent_review": "FAIL_PROVISIONAL_SAME_FAMILY",
            "S2_failure_summary": "utility and strict-cost gates fail; effective local training action count is zero for both variants; on-time gate passes",
            "S3": "NOT_RUN",
            "S3NOTRUN": True,
            "S3_allowed": False,
            "noWM": True,
            "world_model": "NOT_PRESENT_IN_THIS_TRIAL",
            "Periodic_actor": "UNCHANGED",
            "scientific_acceptance": "NOT_ESTABLISHED",
            "environment_scope": "Standalone N02 simulation/source; does not use Isaac Sim traces and does not describe the user's later Isaac scenario work.",
            "publication_approval": "PENDING_SOL_REVIEW",
        }))

        readme = (
            "# N02 v3 S1/S2 Failure Archive Candidate\n\n"
            "Unpublished, sanitized candidate prepared for independent review. The frozen S2 source and result manifests were hash-checked before staging. "
            "`PUBLIC_HASH_MAPPING.json` records source and public hashes for every included input file, with the transformation used. `PUBLIC_ARCHIVE_INVENTORY.json` is the complete manifest of staged files.\n\n"
            "S1 was independently reviewed as PASS for the CPU mechanism gate only. It does not establish PPO, learned-trigger, world-model, research-performance, or research acceptance. The reviewer found all 45 paired task outcomes identical within the observed horizon; forecast completion estimates do not demonstrate an actual completion improvement.\n\n"
            "The real S2 run completed on GPU, and the same-family independent review records S2 `FAIL / REPAIR_REQUIRED` with S3 blocked. Event-G minus Periodic-G development utility is -0.26688389931575784 (required >= 0); on-time difference is 0 (required >= -0.02); no planning, communication, or reconstruction cost strictly decreased; and effective local training actions are zero for both variants. S3 is `NOT_RUN` and `S3_allowed=false`. The Periodic actor is unchanged; no world-model result exists for this trial. The S1/S2 artifacts describe the standalone N02 environment and do not use Isaac Sim traces or describe later Isaac scenario work. The review remains provisional same-family assurance, not external certification.\n\n"
            "Checkpoint binaries, large raw trajectories/logs, authorization and publishing binding originals, private control artifacts, and the native remote deployment helper are excluded and listed in `PUBLIC_EXCLUSIONS.json`. The deployment helper can be supplied separately after endpoint/privacy review; the public package retains the model, policy, environment, protocol, tests, and local audit tools.\n"
        )
        write(temporary / "README.md", readme.encode("utf-8"))

        scan = builder.scan_tree(temporary)
        scan["scanned_files"] += 3
        write(temporary / "PUBLIC_ARCHIVE_SCAN.json", canonical_json({"schema": "n02-v3-public-archive-scan/1", **scan}))
        inventory = builder.inventory(temporary, mapping, identity)
        inventory["archive_state"] = "S1_S2_FAILURE_CANDIDATE_PENDING_SOL_REVIEW"
        inventory["release"] = RESULT_RELEASE
        inventory["source_manifest_sha256"] = SOURCE_MANIFEST_SHA256
        inventory["evidence_manifest_sha256"] = RESULT_MANIFEST_SHA256
        raw_inventory = canonical_json(inventory)
        write(temporary / "PUBLIC_ARCHIVE_INVENTORY.json", raw_inventory)
        write(temporary / "PUBLIC_ARCHIVE_INVENTORY.sha256", f"{builder.sha256(raw_inventory)}  PUBLIC_ARCHIVE_INVENTORY.json\n".encode("ascii"))
        verified = builder.verify(temporary)
        os.replace(temporary, output)
        return {
            **verified,
            "output": output.as_posix(),
            "source_mappings": len(mapping),
            "source_files_omitted": len(omitted),
            "frozen_result_manifest_sha256": RESULT_MANIFEST_SHA256,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-root", type=Path, required=True)
    parser.add_argument("--sol-root", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--diagnosis-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, args.freeze_root, args.sol_root, args.decision, args.diagnosis_root), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
