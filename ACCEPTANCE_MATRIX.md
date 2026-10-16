# Five-Check Minimal Closure Matrix

| Check | Required evidence | Current state | Scope limit |
| --- | --- | --- | --- |
| C1 public initial assignment | C1-derived civilian generator, explicit algorithm provenance, valid allocation, public-input responsiveness, and hidden-future invariance | PASS, independently reviewed in local synthetic Gate A | Not the original Chapter 1 MILP and not real-data evidence |
| C2 causal 2x2 disturbance | Truth-state change in a local 2x2 area, delayed public update, and boundary/nonlocal rejection | PASS, independently reviewed in local synthetic Gate A | Synthetic environment only |
| C3 NOOP/non-target oracle | Shared-state NOOP comparison, legal dispatch, a non-target order, and independent recomputation of labels and global consequences | PASS, independently reviewed in local synthetic Gate A | Synthetic consequence only; no collection run |
| C4 actual consequence, WM restore, and G/G-WM PPO | Authorized consequence collection, actual WM optimizer updates, strict new-process restore, paired real PPO updates, and accounting | NOT RUN | No formal authorization, data collection, WM checkpoint, or PPO update exists |
| C5 independent review | Sol review of the exact evidence state and proposed public content | Gate A PASS; bounded Node B PASS; publication review PENDING | Bounded diagnostics are not formal research approval |

## Additional bounded diagnostic evidence

Diagnostic unit `70b6495fa8b74135872bbf6b961ae9c2` completed expected success, controlled normal-failure, and guardian-kill cases. The measured prior-cost receipt replay was accepted by the package parser at 2.391625 seconds wall and 0.821315 seconds CPU for that diagnostic unit. Sol independently passed bounded Node B diagnostics and the measured receipt.

The local Gate A review records 19 tests passing. Those tests support local synthetic acceptance only; they do not establish C4 or research efficacy. Hashes of the source review records and the de-identified public summaries are tracked as separate identities in [HASH_PROVENANCE.md](HASH_PROVENANCE.md) and the public inventory receipt.
