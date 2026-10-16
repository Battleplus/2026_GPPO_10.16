# Public Preparation Scan Result

Scope: files explicitly listed in `PUBLIC_ALLOWLIST.txt` in this local archive-preparation directory. Candidate source and operational evidence are not included in this scan.

Frozen pre-review scan facts for 2026-10-16: the synthetic scanner self-check returned `PASS`; the archive policy scan returned `PASS_POLICY_SCAN` for 14 allowlisted files with zero findings. These are scan results for the preparation snapshot before it was frozen. They do not mean Sol approved Stage 0/A, the candidate source is ready for publication, the target runtime is measured, or a research gate passed.

The final scan receipt, including the per-file hashes and public-sanitized inventory hash, is recorded outside this directory in the review handoff. This file is part of the 14-file inventory, so the inventory hash is kept only in that external receipt rather than embedded here; embedding it would change the scanned bytes and invalidate the receipt.

This result excludes the candidate source and all operational server evidence. The public-sanitized inventory hash is distinct from local source and original artifact hashes.
