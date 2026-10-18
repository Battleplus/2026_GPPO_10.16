# N02 灾后动态再分配

本仓库保存 N02 从最小闭环到事件触发式重构的可审计工程版本。

## 当前节点

`archive/n02-full-event-trigger` 的 repair3 运行已通过 GPT-6.1 Sol High 独立只读复审：[`releases/n02-event-trigger-v1-repair3-100x100`](releases/n02-event-trigger-v1-repair3-100x100/)。其源码 release 为 `n02-event-trigger-v1-18f0ed76de7f433380d231b1dd28bb61`，manifest SHA-256 为 `fc769fb36295501018afe43d7732684a5f3a843c13f591c786ac99e8f2f6ba09`；正式 attempt 为 `n02-event-v1-d0e59d2f21264863990169fe0874e764`。新归档使用 tag `n02-event-trigger-v1-repair3`。

复审结论为 `ENGINEERING_PASS`，143/143 证据哈希匹配。M1 事件模式有 42 次触发，全部为全局重规划；周期诊断有 13 次局部修复和 77 次全局重规划触发。M2 的 24 个窗口均通过独立后果复算，M3 完成世界模型训练与恢复，M4 完成四组策略训练和 12 次 checkpoint 恢复。公开边界不含模型 checkpoint 和原始大日志。

科学效能仍为 `UNVERIFIED`。开发集只有两个父场景，比较结果仅作描述；Event-G-WM 同时改变触发策略和 critic 输入，未独立识别 critic 的因果效应。

## 历史节点

- [`releases/n02-event-trigger-v1-100x100`](releases/n02-event-trigger-v1-100x100/)：此前的正式运行归档，原目录与 tag 保留。
- [`releases/n02-minimal-closure-v1-100x100`](releases/n02-minimal-closure-v1-100x100/)：此前已归档的 100x100 最小工程闭环。
- `history/`：计划、失败证据和早期审核记录。

公开归档不包含密码、私钥、token、授权原文、私有服务器上下文、SQLite、原始控制台日志或模型权重文件。
