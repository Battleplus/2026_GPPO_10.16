# Hash Provenance

These values identify different artifacts or representations and must not be substituted for one another.

| Artifact | Hash form | SHA-256 | Meaning |
| --- | --- | --- | --- |
| Frozen development candidate `SOURCE_MANIFEST.json` | Raw file bytes | `eabed7233c40ddf3964e7a9af158f53e0b3677af408dc8c60f1ded05c618e229` | Original local manifest file identity; candidate source is not copied into this archive |
| Frozen development candidate manifest | Canonical manifest summary | `872913e33758055c5f36a1b7f4c6eafc7dd3b039c2eec384eddba0602eda7c73` | Canonical content identity from the manifest generator |
| Frozen development candidate hash bundle | Canonical bundle summary | `9450ec2efe8a864708636349b2f3c2627adc7aa5966df7775d99ed6977ce4d13` | Canonical package hash-bundle identity |
| Original Sol Gate A review Markdown | Raw file bytes | `8839f33ba487f0649b2c9f0ed7283680545190c1ada9fff6513a46398a43860a` | Original local review record, not the de-identified public summary |
| Original Sol Gate A review JSON | Raw file bytes | `2bd1266d5dc5c0014f519baef01748816845090270dffeb689c201d903683d90` | Original local review record, not the de-identified public summary |
| Original Sol B diagnostic review Markdown | Raw file bytes | `6a12234da9a5b0f15cdc34cf2c0f448fc5bb61e7969fca7b1554d2ae4fb58006` | Original local diagnostic review record |
| Original Sol B diagnostic review JSON | Raw file bytes | `2df9f06a04361efd64b9df19e298da32ee6305ec787c71555416c3b7e1f2f73c` | Original local diagnostic review record |
| Original prior-cost parser replay result | Raw file bytes | `e8d011803290a9010a0a18def5e798c661a1a8ac92f52199b297a2e7176376db` | Original parser-replay record for the measured diagnostic receipt |
| Measured same-unit prior-cost receipt | Receipt identity | `ff2fbcbef7fc3d04acfb087018121d1a07a34156e668f1ba58669c15d562ab30` | Receipt accepted by parser replay; wall 2.391625 s, CPU 0.821315 s |

The public Gate A and B summaries have distinct file-byte hashes computed by the allowlist checker. They do not replace the original review hashes above. The full source package and operational evidence remain outside this archive; no public-sanitized source-package hash exists. The public-sanitized inventory hash is separately computed over the exact allowlisted preparation snapshot and recorded outside that snapshot to avoid self-reference.
