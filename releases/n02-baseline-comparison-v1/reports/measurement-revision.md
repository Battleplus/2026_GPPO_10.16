# Measurement Revision

## Scope and Result

The frozen independent oracle remains unchanged and returns `FAIL`, with 66
mismatches and 28 missing items. A reviewed external measurement helper was
added separately to the public stage; it does not replace or edit the frozen
oracle, scientific algorithm, raw evaluation data, or source configuration.
The revised independent report returns `PASS`, with zero mismatches, zero
missing items, and 29 proofs. Sixteen tamper tests passed.

The 28 affected rows comprise six delayed rows supported by seven task proofs,
and 22 environment-route release rows. The helper requires the complete
origin/raw-send/current-delivery/assignment/endpoint/effect evidence chain.
An environment route release, a failed release that remains nonterminal, a
report, or a before-owner-to-none transition alone is not counted as a
reconstruction.

## Integrity Boundary

The frozen source manifest remained at SHA256
`53171ce5e2e01717d467e136efc14cf7586a5688d052c6f66ff4269f739ea268`; the
configuration remained at SHA256
`409d538427490df49f308287aa1ef1b5b1eaabb83f7bb9d3c4f6a3222f90e7d5`. The
measurement revision is external measurement code. It changes neither the
algorithm nor raw evidence and does not rewrite the frozen oracle's FAIL.

The revised measurement report and tamper-test results remain subject to Sol
Gate3 review. This document does not claim Gate3 approval, independent
scientific acceptance, or completion of the final archive.
