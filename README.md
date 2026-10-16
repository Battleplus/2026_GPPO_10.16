# N02 Disaster Relief Reallocation Archive

This directory prepares a public archive for `Battleplus/2026_GPPO_10.16`. It records the N02 execution plan, current evidence boundaries, public archive rules, and privacy checks.

## 中文状态摘要

Sol 对冻结候选的 Gate A 初审结论为 `REPAIR`，当前不得进入 Stage B。Repair 1 正在进行：用户已批准将公开信息 C1 分配器改造成民用初始分配生成器，需明确算法来源且不能称为原 Chapter 1 MILP；同时修复 2x2 空间扰动、L1 图策略和 protocol 一致性，并补充 NOOP 与非目标订单的全局后果证据。Repair 1 的 L1/统一 protocol 首步已有 6 项定向测试通过，但尚未由 Sol 复审，不代表 Gate A 通过。冻结候选原有 10 项本地测试通过也不等于 A 通过。

目标 GitHub 仓库已确认为 public、empty、admin；本地目录只准备文档和工具，尚无源码，也未执行 push、建分支或打标签。B 的网络已恢复，但加密 SSH 私钥仍待用户解锁；目标运行时规格保持 `UNMEASURED`。

**Current state:** Sol's initial Gate A verdict is `REPAIR`; Stage B is not authorized. Repair 1 is underway. The public archive contains preparation documents and tools only; it does not contain the candidate source package. No GitHub branch, tag, or push has been created from this directory.

The 10 passing local tests are evidence for a local synthetic engineering candidate. They do not establish Stage A acceptance, dynamic 2x2 perturbation causality, a measured server runtime, world-model training, or real PPO updates. The user approved adapting the existing public-information C1 allocator as a civilian initial-assignment generator with explicit provenance; this must not be described as the original Chapter 1 MILP. The actual G/G-WM L0MLP integration also needs repair.

Start with:

- [ROADMAP.md](ROADMAP.md): full execution sequence and gates.
- [STATUS.md](STATUS.md): current evidence and blockers.
- [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md): evidence required at each gate.
- [ARCHIVE_RULES.md](ARCHIVE_RULES.md): public branch and tag conditions.
- [history/gate-a-review/SOL_GATE_A_SUMMARY.md](history/gate-a-review/SOL_GATE_A_SUMMARY.md): de-identified review and phase-scope addendum.
- [protocols/CPU_KERNEL_WITNESS.md](protocols/CPU_KERNEL_WITNESS.md): target CPU runtime witness protocol.
- [history/prior-v5-failure/FAILURE_SUMMARY.md](history/prior-v5-failure/FAILURE_SUMMARY.md): de-identified failed-attempt record.

The allowlist checker audits only files explicitly listed in [PUBLIC_ALLOWLIST.txt](PUBLIC_ALLOWLIST.txt). A clean scan means the staged files passed that policy scan; it does not replace Sol review or the scientific acceptance gates.
