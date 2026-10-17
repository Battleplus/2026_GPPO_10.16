# GPU Final Snapshot Analysis Notes

This directory is a read-only analysis of the completed immutable snapshot.
It does not modify the frozen source, evidence, or training run and does not
issue an acceptance PASS.

Identity: attempt `n02-event-gpu-v1-c3cd21185f184855af2a8300bc3d572b`; source
manifest SHA-256 `7907ee2acd32dd2271a40c816bb7616fbe4427e5e84096c5ee2ffb193219235d`;
runtime verified 77 source files on RTX 2080 Ti / `cuda:0`. The remote evidence
hash manifest contains 144 files; local SHA-256 verification found 144/144
matching, with no missing or mismatched file. The manifest file SHA-256 is
`d1ec7285d2dbb4e222cfff9583ab0465561a75ba0662b34320de0e37b28649f0`.

The report has 24/24 method × seed × development-parent rows. Producer
cross-checks contain 171 exact matches and 21 `MISSING` entries for the three
independent mutation metrics in seven receipt-gap cells; no producer mismatch
was found. Exact independent effective counts remain `MISSING` in those cells.

The separate `mutation_gap_witnesses.csv` audit found 5 conservative
`ZERO_MUTATION_WITNESS` rows and 2 `MISSING_INCONCLUSIVE` rows. A witness requires
an undelivered communication-only event sequence, zero operational dispatches,
no owner/reorder mutation, complete platform queue coverage, and equal current
and next queue snapshots. The two inconclusive rows are Periodic-G-WM seed 8202
and 8203, environment parent, step 36: queues are complete and equal, but raw
events include a non-communication event, so no zero-mutation conclusion is
issued.

The exact Event-G versus Periodic-G independent effective contrast is +1.8333
per matched cell (6/6 valid), while trigger contrast is -2.6667 and reported
effective contrast is +1.8333. Thus the event method's lower trigger count did
not correspond to fewer actual effective reconstructions in this snapshot.
WM independent exact counts have missing denominators: Event-G-WM 3/6 valid,
Periodic-G-WM 2/6 valid. Their paired exact contrasts are reported with valid
N and lower/upper sensitivity bounds; they are not imputed point estimates.

GPU execution evidence reports status `complete`, 1,344 policy CUDA updates and
240 world-model CUDA updates. `SOL_HIGH_REVIEW.json` remains
`pending_independent_read_only_review`; this analysis therefore makes no
acceptance or significance claim.
