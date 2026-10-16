# Acceptance Matrix

| Area | Result | Evidence |
|---|---|---|
| Seven-stage repair-2 execution | Pass | Sanitized run summary; final live ledger recorded |
| Independent final review | Pass, 66/66 checks | `provenance/review/final-review.json`; source digest recorded there |
| Training collection | 8 windows, 32 branches | `data/repair2/training_windows.json.gz`; `training_branches.jsonl.gz` |
| Development collection | 4 windows, 12 branches | `data/repair2/development_windows.json.gz` |
| Independent oracle | 32 training branches replayed; 944 environment steps | Run summary; 944 is not a qualifying-step count |
| Model training and restore | Pass | World-model checkpoint and two policy checkpoints in `data/repair2/models/` |
| Development comparison | Diagnostic only; all paired differences reported as zero | No efficacy superiority claim |
| Public privacy and hashes | Pass when verifier succeeds | `PRIVACY_REPORT.md`; `PUBLIC_ARCHIVE_INVENTORY.json` |
| Formal server execution from archive | Not authorized | Private runtime evidence is omitted; cost file is a no-measurement placeholder |
