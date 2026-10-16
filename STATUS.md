# N02 Current Status

Last updated: 2026-10-16

## 中文状态摘要

Sol 冻结版本 Gate A 初审为 `REPAIR`，不得进入 B。Repair 1 正在完成用户批准的 C1 民用初始分配器及 2x2 空间扰动、L1 图策略、单一 protocol 与 NOOP/非目标订单全局后果补证。L1 和统一 protocol 修复第一步的 6 项定向测试已通过，但尚未由 Sol 复审，不等于 Gate A 通过；冻结候选原有 10 项本地测试通过也不等于 A 通过。

GitHub 目标仓库已确认是 public、empty、admin；本地仅有归档准备文档和工具，未复制源码、未 push、未建分支或打标签。服务器网络已恢复，但加密 SSH 私钥仍待用户解锁；目标 CPU runtime witness 为 `UNMEASURED`。

## Current gate

The frozen Stage 0/A candidate received Sol's initial Gate A verdict `REPAIR`; Stage B is not authorized. Repair 1 is in progress. The user approved adapting the existing public-information C1 allocator as a civilian initial-assignment generator and documenting its provenance. This is not the original Chapter 1 MILP. The local archive-preparation directory contains documents and privacy/runtime tools only; no candidate source was copied here.

The frozen local report records 46 package files, a 100x100 contract (`10,000` cells), 11 registered maps checked, 4 synthetic candidates, 0 bytecode candidates, and 10 local tests passing in 2.95 seconds. The candidate also records a synthetic auxiliary-gradient probe of `14.2723015`, actor-head gradient maximum `0`, and world-model gradient maximum `0` with the world model frozen. These are local synthetic/static observations, not server or training evidence.

The initial review identifies local Stage A repair items A1, A2, A3, A5, and A7: generate the initial assignment from the approved C1-derived civilian allocator; implement an actual 2x2 spatial state perturbation; use and exercise the L1 graph policy in training/recovery/evaluation construction; align the stage protocol across identity and runtime components; and add NOOP-referenced, independently recomputed global consequences including a non-target third order. The scope addendum assigns prior-cost runtime measurement to B, real PPO updates to F, and world-model training/recovery to E. These later-stage artifacts are not Stage A prerequisites.

Explicit evidence limits in the frozen candidate remain:

- The frozen candidate has only a synthetic initial-assignment handoff; its optimizer was not run. The approved C1 adaptation is still in repair and must be named as C1-derived, not as the original Chapter 1 MILP.
- The 2x2 block is contract-checked only; dynamic spatial perturbation causality was not simulated.
- The local test result does not prove Stage A. Sol's review returned `REPAIR`; A1/A2/A3/A5/A7 remain open while repair 1 is underway.
- The actual G/G-WM L0MLP integration needs repair. The synthetic critic gradient probe does not close that issue.
- No collected consequence data, world-model training, checkpoint recovery, or real PPO update has been completed for this candidate.

## Server and prior attempt

Server network access has recovered, but the local SSH private key is encrypted and awaits user unlock. No server connection or preflight has been made from this archive-preparation task. No `.aris/compute` ledger evidence exists yet. The public CPU runtime protocol is `UNMEASURED`; a separate agent must execute it, capture a witness and resource ledger, and have those receipts reviewed before declaring the environment ready. Successful imports alone do not pass this gate. The protocol schema is separate from, and does not replace, the package's existing runtime contract.

The prior v5 formal-run attempt was rejected by the running process guardian at the prior-cost gate before the research worker started, because measured prior resource cost was missing. No world-model or PPO updates occurred. Its request, attempt, authorization, and run identity are historical and cannot be reused. A de-identified summary is in `history/prior-v5-failure/FAILURE_SUMMARY.md`.

## Identity and publication boundary

The frozen local candidate `SOURCE_MANIFEST.json` raw-byte SHA-256 is `a88b75ff4b9b5b21d18267c9eeda8b726c559ca93ddf2ca398f2b08ba91d6f2a`. Its embedded canonical manifest SHA-256 is `32c526ce2e626bbc4f88a172a2ac09adf1a508acffbbe17cf31a16e0f6f30f6d`. These are different hash forms for different representations. Neither is a public-sanitized source hash or release approval. The public-sanitized inventory hash produced by `tools/public_archive_check.py` covers only the files in `PUBLIC_ALLOWLIST.txt`; it is a separate artifact identity and must never be substituted for the local source hash.

No formal token or authorization has been created for the new candidate. No GitHub push, branch, or tag has been made from this directory. The GitHub repository remains an empty/admin destination. A success branch or tag is not eligible while Gate A is `REPAIR`; after correction, Sol must pass the gate and the main coordinator must authorize publication.
