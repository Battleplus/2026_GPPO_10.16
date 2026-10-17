# N02 灾后动态再分配

本仓库保存 N02 从最小闭环到事件触发式重构的可审计工程版本。

## 当前节点

`archive/n02-full-event-trigger`：100x100 事件触发 V1 工程闭环已通过 GPT-6.1 Sol High 独立只读复审。发布目录为 [`releases/n02-event-trigger-v1-100x100`](releases/n02-event-trigger-v1-100x100/)。

复审结论：`ENGINEERING_PASS`。M0、M2、M3、M4 通过；完整证据快照 142/142 哈希一致；96 个策略 JSONL 全部解析并满足预期行数；世界模型恢复和 12 个策略 checkpoint 恢复通过。

科学效能结论仍为 `UNVERIFIED`。开发集和 G/G-WM 比较属于首轮描述性诊断，不能支持算法优越性或独立的辅助 critic 因果结论。

## 历史节点

- [`releases/n02-minimal-closure-v1-100x100`](releases/n02-minimal-closure-v1-100x100/)：此前已归档的 100x100 最小工程闭环。
- `history/`：计划、失败证据和早期审核记录。

公开归档不包含密码、私钥、token、授权原文、私有服务器上下文、SQLite、原始控制台日志或无关旧模型。
