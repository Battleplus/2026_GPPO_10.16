# Public Archive Rules

This repair-2 snapshot supersedes the earlier docs-only publication profile for the paths in `PUBLIC_ALLOWLIST.txt`. The approved scientific payload includes reviewed simulator source, package tests, synthetic scenario-derived windows and branches, paired diagnostic rollouts, and the three selected checkpoints. Each included file must appear in `PUBLIC_ARCHIVE_INVENTORY.json` with its public SHA-256 and size.

The inventory is the exact release boundary. The snapshot verifier rejects missing, changed, or unlisted files. Structured data are gzip-compressed deterministically; their raw source hashes and compressed public hashes are both recorded. Checkpoint hashes are the hashes of the included model files.

Do not add raw logs, SQLite databases, authorization or identity-consumption documents, private server/runtime paths, measured operational cost receipts, `TASKBOOK.md`, or unreviewed outputs. The original release-2 identity sidecars are retained as provenance and do not validate the sanitized derivative tree. `PRIOR_RESOURCE_COST.json` is a portable no-measurement placeholder and cannot authorize execution.

The previous `tools/public_archive_check.py` remains a historical docs-only utility. It does not define the allowlist for this scientific snapshot; use `tools/verify_public_snapshot.py` to verify the exact inventoried payload.
