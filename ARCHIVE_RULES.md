# GitHub Archive Rules

Target repository: `Battleplus/2026_GPPO_10.16`.

## Branches

| Branch | Creation condition |
| --- | --- |
| `main` | Main coordinator accepts the repository-wide state after independent review; it must not imply a success beyond the reviewed nodes |
| `archive/n02-gate-a-repair-20261016` | Sol reviews the de-identified Gate A `REPAIR` summary and archive-preparation documents; this branch contains no candidate source and receives no success tag |
| `archive/n02-local-100x100-20261016` | Stage 0/A passes Sol review after A1/A2/A3/A5/A7 repairs; source and reports are privacy-scanned and their public hashes are generated |
| `archive/n02-server-preflight-20261016` | Stage B receipts pass Sol review, including measured CPU witness and prior resource-cost receipt |
| `archive/n02-consequence-data-20261016` | Stage D collection, replay, label recomputation, split, and settlement pass Sol review |
| `archive/n02-world-model-20261016` | Stage E training, checkpoint, recovery, and metrics pass Sol review |
| `archive/n02-g-gwm-20261016` | Stage F actual G/G-WM PPO, L1 graph-policy wiring, gradient/parameter, fairness, and checkpoint audits pass Sol review |
| `archive/n02-minimal-closure-20261016` | Stage G returns `ENGINEERING_PASS` for the complete minimum closure |
| `archive/n02-full-event-trigger` | Stage I full experiment and independent confirmation review pass |

If a node receives `REPAIR` or `STOP`, preserve reviewed sanitized failure evidence on a clearly named failure/repair branch, for example `archive/n02-gate-a-repair-20261016`. Do not add the node's success tag. Never rewrite an earlier branch to make it appear that a later repair was present in the old snapshot.

## Tags

Create a tag only after the corresponding node has passed independent review and the main coordinator has authorized publication:

- `n02-local-v1`: Stage 0/A accepted.
- `n02-preflight-v1`: Stage B accepted.
- `n02-consequence-v1`: Stage D accepted.
- `n02-world-model-v1`: Stage E accepted.
- `n02-g-gwm-v1`: Stage F accepted.
- `n02-minimal-closure-v1`: Stage G returns `ENGINEERING_PASS`.
- `n02-paper-experiment-v1`: Stage I and its confirmation review pass.

No branch or tag is authorized by this preparation directory. Current Gate A is `REPAIR`, so no success branch or tag is eligible yet. A failure/repair branch may preserve only reviewed, sanitized evidence.

## Public content and identity

Use an explicit file allowlist and run `tools/public_archive_check.py` before every proposed archive snapshot. Reject private keys, actual high-entropy credentials, credential paths/configuration, personal absolute paths, private host/IP/user values, SQLite files, bytecode, large raw logs, and unreviewed or incompatible weights. Generic prose that says `token` is not itself a secret. Reviewed SHA-256 values, unauthorized request candidates, and literal placeholders may be published when each file is explicitly allowlisted. The checker skips only root `.git` metadata; nested Git metadata remains disallowed.

Keep the original local artifact hash and each public-sanitized artifact hash in distinct fields. A redacted report hash never replaces the original source hash, and a local source hash is not evidence that the source is cleared for publication. Recompute public manifests after redaction. Do not copy source into this archive until the independent source review and privacy review pass. If runnable configuration contains private paths, separate that configuration from public source or publish a reviewed template as a distinct artifact with its own public hash. Never describe a path-redacted source copy as the source that produced the original run; preserve the original byte hash and the public sanitized/template hash as separate identities.
