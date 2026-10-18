# Sol High Gate3 — FORMAL001

**Verdict: PASS (engineering and publication readiness). Scientific outcome: RESEARCH_CRITERIA_FAILED.**

This decision was authored by the independent Sol High reviewer `/root/sol61_gate2_pilot005`. It applies to frozen input index `7cb329580ab1130840ccba1414fcb7775db67becd83fe03fc0acee157e4067c7` and public inventory `f83eef737cae71fdac1e1f06e1deb086c58e851298cd44b5b6d156d09b169acb`. All work wrote only into reviews; no server, GPU training, publication, or new CUDA restore was performed.

Verified evidence:

- All 9 entry files, 258 private inventory files, 6 assembled outputs, 102 frozen source payloads, and 162 public payloads match their hashes and sizes. Public file set is exactly 164 including inventory sidecars. Final recheck remained unchanged.
- The original frozen oracle independently reproduces FAIL: 66 mismatches and 28 missing items. The disclosed external revision reproduces PASS: zero mismatches or missing items. Public replay also passes, and raw/private versus projected/public oracle reports match exactly. Standardized per-cell and method metrics also match.
- The revision proves 7 delayed-dispatch tasks across 6 rows and 22 environment road releases. Every released root changes only its corresponding leaf. Environment releases do not enter reconstruction causality. Sixteen supplied tamper tests pass with independently archived stdout; 202 real-data chain mutations are rejected, and all 29 end-to-end episode mutations fail closed.
- Raw evidence contains 240 WM CUDA updates, 2304 policy CUDA updates, 288 training episodes, and 17280 training action rows. All 18 method/seed groups have 128 updates and 16 episodes. All 69120 optimizer physical transition rows match actual actor decision masks; 1152 short tail minibatches are retained and critic-only updates leave actors unchanged. Genuine public C1 generation matches all 342 training/evaluation initial queues, owners, and tapes.
- Evaluation covers 54 cells and 3240 ticks, exactly 60 per cell. All 3 WM and 18 policy serialized model/optimizer/RNG digests match archived recovery receipts; two policy evaluation receipts per checkpoint agree. Distinct archived process identities support fresh recovery. This is CPU artifact verification of archived GPU evidence, not a new CUDA recovery claim.
- WM remains frozen, outside optimizers, with no gradients. Six boundary records preserve actor logits while the auxiliary critic responds to WM features. Public text and metadata of 18 unchanged small checkpoints pass the independent privacy scan; tensor contents are outside that text-scan claim.

The scientific failure is preserved. Event-GPPO improves mean utility by 0.6375457 and completion by 0.0694444 while using 8.3333 fewer planning calls, but reconstruction count, messages, and reconstruction size worsen. Event-GPPO-WM improves utility by only 0.0227255 with 8.5 fewer planning calls while the required resource/reconstruction costs remain equal. Neither pair meets the fixed research gate. Each event method has 9 unique local action witnesses and zero empty-domain global actions. No significance or general method advantage is established.

Explicit nonblocking errata, with frozen bytes retained:

1. `episodes.record_count=16` in the training-consistency report and public copy is a per-group count mislabeled as a total. Independently parsed raw JSONL has **288 episodes**, 18 groups of 16; the manifest and executive workload total already report 288. This review is the correction, not a rewrite of evidence.
2. Candidate range **1–7 concerns the two event methods**; all nine methods span **1–8**. Neither reaches configured cap 16. Root result-index wording needs that scope when summarized.
3. “Nine local witnesses each” means distinct witness actions. The frozen verifier returns 11 and 12 raw evidence records because some actions have both queue and owner evidence.

The public archive includes 94 executed source files and 18 small checkpoints; 8 private operational/identity source files, raw training actions, and 3 large flat PPO checkpoints remain excluded with commitments. Public training instructions describe a fresh run with new provenance and explicitly do not claim a tested GPU rerun or permit bypassing original checkpoint identity.

Three seeds and two development scenarios support descriptive findings only. Traditional controls are candidate-constrained; CBBA-lite is not full CBBA. PPO/GPPO are not parameter matched. WM is auxiliary-critic-only. These limits and the negative research result must remain visible.

The unchanged frozen stage is ready for the already-authorized negative-result publication with this review and errata linked from root README/STATUS. Frozen PENDING labels describe the pre-review freeze; the external review records the final Gate3 decision. There are no blocking findings.

The companion JSON records exact source/config identities and SHA256 bindings for all independently generated replay, mutation, training, C1, checkpoint/privacy, and final-hash artifacts.
