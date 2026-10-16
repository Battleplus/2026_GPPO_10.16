# Hash Provenance

These values identify different artifacts or representations and must not be substituted for one another.

| Artifact | Hash form | SHA-256 | Meaning |
| --- | --- | --- | --- |
| Local candidate `SOURCE_MANIFEST.json` | Raw file bytes | `a88b75ff4b9b5b21d18267c9eeda8b726c559ca93ddf2ca398f2b08ba91d6f2a` | Original local file-byte identity; not a public release hash |
| Local candidate `SOURCE_MANIFEST.json` | Embedded canonical manifest summary | `32c526ce2e626bbc4f88a172a2ac09adf1a508acffbbe17cf31a16e0f6f30f6d` | Canonical content identity defined by the manifest generator |
| De-identified prior-v5 failure summary | Public file bytes | `2e43a04e1be541147124b3afd2a945f7d3e0037fa57d6fe5eaf53294e4e74b57` | Public hash for the sanitized summary file only; not a sanitized source hash |

The source package has not been copied into this archive, so no public-sanitized source-package hash exists yet. `tools/public_archive_check.py` separately emits a public-sanitized inventory hash for the current allowlisted preparation snapshot. Each future source/template artifact must retain its original byte hash and receive a distinct public hash after privacy review and any configuration separation or sanitization.
