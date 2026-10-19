# N02 v3 S0 Public Archive Candidate

This is an unpublished, sanitized candidate prepared for independent Sol review. The frozen R5 source and evidence manifests were verified before selected files were staged. `PUBLIC_HASH_MAPPING.json` distinguishes original source hashes from public hashes; redacted JSON/reports are derived copies and do not claim byte identity. Unredacted source and raw evidence retain their original bytes.

The independent R5 review records S0 A/B PASS only, with a provisional same-family review scope. R3 and R4 REPAIR history is preserved in the report set. The reviewed scope is the 30/45/9 contract/public C1 boundary plus a 6-platform/12-task S0 diagnostic. It does not establish S1 acceptance, spatial 2x2 causality, 30-platform event execution, GPU training, a world model, PPO, scientific acceptance, or publication readiness. S1 is in progress and its evidence is not included in this S0 archive; S1 acceptance is NOT_ESTABLISHED. S2 and S3 are NOT_RUN. This is not a completed research closure.

S0 raw JSON retains the frozen evidence path semantics for public boundary inputs, mechanism observations/history, candidate identities, selection plan, action chain, and producer labels. REQUEST files, local test logs, execution logs, credentials, host connection details, absolute paths, bytecode, and checkpoints are excluded. S1 evidence is not included in this S0 archive. The historical R5 audit script is path-redacted; it is included as an audit artifact, not represented as a fresh rerun.

Build from the repository root with:

```powershell
python development/n02_v3_public_archive_20261019/build_public_archive.py build --freeze-root development/ch2_disaster_relief_n02_event_trigger_v3_100x100_9region/releases/s0-frozen-20261019-r5 --sol-root development/n02_v3_sol_review_20261019 --output development/n02_v3_public_archive_20261019/candidate-final
```

`PUBLIC_ARCHIVE_INVENTORY.json` records every staged file. `PUBLIC_ARCHIVE_INVENTORY.sha256` seals the inventory bytes. A successful local verification means only that the candidate is internally consistent and passed the static privacy scan; it does not grant publication approval.
