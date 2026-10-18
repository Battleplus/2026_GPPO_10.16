# Archive Branch Rules

The historical v1 release and N02 v2 GPU release are separate snapshots under `releases/`. The v2 archive does not replace or rewrite v1. Each release keeps its own validation outputs, inventory, identity, and evidence commitments.

For each release, the frozen private source-manifest SHA-256 and the public redacted-payload SHA-256 are distinct values. `PUBLIC_ARCHIVE_INVENTORY.json` records the frozen-source commitment and public-file hash separately for every staged payload file. Do not compare or substitute one hash for the other.

The v2 package documents GPU engineering closure as `PASS_ENGINEERING_CLOSURE` and the registered mechanism/utility/cost result as `REPAIR_REQUIRED`. It is an honest negative result and makes no scientific-success claim. The public result summary gives the evaluated scope, descriptive means, passed and failed registered criteria, and limitations.

Raw run logs, trajectories, receipts containing private provenance, and WM/PPO checkpoint files remain outside the public payload. Their original byte sizes and SHA-256 values may be recorded as digest-only evidence commitments. Never add the raw files, local or remote filesystem paths, connection endpoints, credentials, or private review originals to the public release.

Each release's own archive verifier must pass. A new release requires its own sanitized-staging consistency and privacy review before publication. Status documents must name the engineering and acceptance outcomes separately and must not imply publication before it occurs.
