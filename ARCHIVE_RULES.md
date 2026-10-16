# Public Archive Rules

Target repository: `Battleplus/2026_GPPO_10.16`.

## Current publication boundary

The current preparation snapshot may contain only the exact files in `PUBLIC_ALLOWLIST.txt`. It is a de-identified record of local Gate A evidence, bounded diagnostics, their limits, and pending work. Candidate source and raw operational evidence remain excluded pending independent publication review.

Sol passed the local synthetic Gate A review. The completed server unit was a bounded unauthorized diagnostic, and its prior-cost receipt replay was accepted. The independent final B gate review and independent publication review are pending. Do not present this snapshot as a formal run, completed minimum closure, research result, or source approval.

## Content and privacy checks

Before proposing any public snapshot, run `tools/public_archive_check.py` against the explicit allowlist. Reject private keys, credentials, authorization contents, personal absolute paths, private host/IP/user values, raw operational logs, SQLite files, bytecode, model artifacts, and unreviewed source. Do not copy candidate source into this archive unless source and configuration have passed separate review and privacy checks.

Keep original evidence hashes, canonical identities, public summary-file hashes, and the public inventory hash in separate fields. A hash of a redacted summary does not replace the original evidence hash. The inventory hash covers the exact allowlisted file bytes and is recorded outside the snapshot to avoid self-reference.

## Branches and tags

No branch name, commit, or tag is authorized by this preparation document. A proposed preparation commit must contain only the allowlisted snapshot and must receive independent publication review before publication. Do not create a success tag while the final B review and C4 real-run evidence are pending. Any later public node must be reviewed and frozen as its own snapshot; never rewrite a prior snapshot to imply evidence that was not present then.

Full paper experiments, additional scales, multiple seeds, and confirmation studies are outside the current five-check minimal-closure scope. They are future work and are not authorized by this archive preparation.
