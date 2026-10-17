# N02 event-trigger V1 — 100x100 public engineering release

This release archives the independently reviewed N02 disaster-relief event-trigger run. It contains the frozen source/configuration contract, sanitized evidence summaries, consequence labels, world-model checkpoints and four-policy checkpoint sets.

## Result

GPT-6.1 Sol High reviewed the complete formal snapshot for attempt `n02-event-v1-310d73fcbd4044709ef1f6cb8e7f3a91` and returned `ENGINEERING_PASS`. The remote evidence manifest had 142 entries; all 142 were retrieved and matched. All 96 policy JSONL streams parsed with their expected row counts.

The engineering chain passed M0, M2, M3 and M4. M2 had two legal candidates with distinct physical outcomes in all 16 training windows and all 24 planned windows. M3 completed three world-model trainings and fresh-process restores. M4 completed Event-G, Event-G-WM, Periodic-G and Periodic-G-WM for seeds 8201–8203 with 112 paired updates per seed/method and 12/12 policy restores.

The development comparison is descriptive only. It does not establish superiority, isolate the auxiliary-critic effect, or replace a full statistical paper experiment. Scientific efficacy claims remain `UNVERIFIED`.

## Verification

Run `python -B verify_public_snapshot.py` from this directory to verify the exact `PUBLIC_ARCHIVE_INVENTORY.json` boundary. Formal staging and retrieval used Windows bundled OpenSSH executables (`C:\Windows\System32\OpenSSH\ssh.exe` and `scp.exe`). No private key, password, token, authorization payload, server credential, SQLite database, or private runtime context is included.
