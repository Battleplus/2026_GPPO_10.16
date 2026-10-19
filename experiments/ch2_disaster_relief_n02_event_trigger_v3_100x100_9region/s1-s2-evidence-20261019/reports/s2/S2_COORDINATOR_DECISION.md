# S2 coordinator decision

Status: `REPAIR_REQUIRED` following Sol High's independent `S2 FAIL` review. S3 is blocked and has not run.

The original v3 specification and the user's frozen tolerance govern this decision: development arithmetic-mean utility difference must be >= 0, on-time-rate difference >= -0.02, and at least one actual planning, communication or reconstruction cost must decrease. Successful process termination alone cannot satisfy these gates.

## Frozen real trial

- Release: `n02-v3-s2-bd8054b27c114c9fafffd77734b7ee8d`.
- Attempt: `99a7e67bc1684fcb94a231e8c72a728e`.
- Run: `eb5fee7ed88c43068f5796944727e031`.
- Result freeze: `n02-v3-s2-result-99a7e67bc1684fcb94a231e8c72a728e-5e7ee1c3`.
- Result manifest SHA-256: `21bbcd8769810d2988ed1edf79976107c8d8696b15cdd4565677cc748aa0d35a` (146 listed files).
- Real GPU execution: physical GPU 1, exposed as logical CUDA device 0; both variants completed 28 optimizer updates and fresh-process checkpoint restoration.

## Observed acceptance failures

| Development arithmetic mean | Periodic-G | Event-G | Event minus Periodic |
|---|---:|---:|---:|
| Global utility | 30.999399337653514 | 30.732515438337757 | -0.26688389931575784 |
| On-time rate | 0.8 | 0.8 | 0 |
| Planning calls | 60 | 60 | 0 |
| Communication messages | 36 | 38 | 2 |
| Reconstruction size | 0 | 1 | 1 |

Sol High independently confirms the utility and cost failures, zero effective local training actions in both variants, and the earliest trigger/mask/catalog failures. Periodic-G's actor has zero gradients throughout and identical initial/final parameter digests; its critic updates do not establish actor learning. Event-G's actor changes, but no legal local candidate appears along its recorded training trajectory.

The final report verifies 146/146 frozen file hashes, 32 byte-identical original run inputs, all 104 source-manifest entries, both checkpoint tensor/optimizer/probe identities and 28 optimizer steps, and their recorded fresh-process restore bindings. It reports the 14 required metrics and utility normalization. Decision latency and unobserved environmental risk remain unknown. Cross-region communication is zero for both variants under an explicitly stated geographic-position definition; fixed affiliation is unavailable for global helicopters.

Independent report: `development/n02_v3_sol_review_20261019/s2_result_audit/S2_RESULT_REVIEW.json`, SHA-256 `40e7fdb32582f20f8f17a177fd85f360d93e513b0656241212ab761e6b06a470`; Markdown SHA-256 `77bc3a140787c03f57c9c52171d25b2e5f0ca742e0c470d2beb462aa20b031b0`. The review is same-family independent-context assurance within its enumerated checks, not external certification.

Coordinator conclusion: preserve the failed pilot as `REPAIR_REQUIRED`; do not enter S3. No selection of a replacement seed, evaluation result, or later candidate can turn this frozen trial into a PASS.

## Execution boundary

The user-reported network restoration was verified with native Windows OpenSSH: the server returned the expected hostname. The completed systemd unit's journal was read back into `S2_TERMINAL_JOURNAL_SUPPLEMENT.txt`; this is a separately retained supplement, outside the immutable result freeze. It records 9min 16.871s of CPU consumption. It is not a new trial or a replacement resource ledger.

No trial restart, replacement seed, development tuning, new evaluation or S3 work is authorized by this failure diagnosis. Any repaired experiment would require a separately disclosed new version and preregistration; it must preserve the failed trial and development observations. World-model and G/G-WM results are absent for this v3 trial.

## Remaining failure-path delivery

The independent result review and first-zero diagnosis are complete. Prepare a sanitized S1/S2 failure archive and publish only after independent privacy and identity review. The existing S0 tag and historical v2 remain unchanged. Resource figures retain their measurement boundaries: the settlement wall interval includes restoration, child RSS is not a whole-cgroup peak, and final journal CPU is a separately retained supplement.
