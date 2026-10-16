# N02 Repair-2 Public Scientific Snapshot

This snapshot contains the reviewed N02 civilian simulator, tests, selected synthetic simulator outputs, and model checkpoints for repair-2. All scenario-derived data are synthetic simulator output. The development evaluation is diagnostic only; it does not establish efficacy or superiority.

Repair-2 completed all seven stages and passed the final independent review: 66 of 66 scoped checks passed, with no must-fix findings. The independent oracle replay covered 944 environment steps; that is not a qualifying-step count. Repair-1's earlier formal attempt failed during final cleanup and remains disclosed in [RUN_SUMMARY.md](RUN_SUMMARY.md).

The portable `PRIOR_RESOURCE_COST.json` is a no-measurement placeholder. Formal server execution requires private runtime evidence and a locally configured runtime. The archive does not contain raw logs, SQLite ledgers, authorization documents, operational cost evidence, or `TASKBOOK.md`.

Run the included package tests from this directory with `python -B -m pytest -p no:cacheprovider core/tests core/civilian`. Verify the frozen public payload with `python tools/verify_public_snapshot.py`.

`tools/public_archive_check.py` is a historical docs-only checker from the earlier source-only snapshot. Use `tools/verify_public_snapshot.py` for this repair-2 snapshot.
