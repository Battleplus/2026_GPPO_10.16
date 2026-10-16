# N02 灾后动态再分配：最小工程闭环

2026-10-16：五项核心检查通过，独立审核结论为 **ENGINEERING_PASS**。完整论文实验尚未开展。

100×100 民用仿真场景使用公开信息 C1 生成初始分配，执行真实 2×2 空间扰动，采集 44 条候选分支，独立复算标签，完成世界模型 2 次更新及新进程恢复，以及 G/G-WM 各 8 次 PPO 更新。开发评价的三项主要指标差值均为 0，不能据此声称 G-WM 更优。数据是实际执行仿真生成的结果，不是现场观测数据。

- [源码、测试、数据、checkpoint 和运行说明](releases/n02-minimal-closure-v1-100x100/README.md)
- [验收状态](releases/n02-minimal-closure-v1-100x100/STATUS.md)
- [运行结果、失败历史及资源结算](releases/n02-minimal-closure-v1-100x100/RUN_SUMMARY.md)
- [独立审核公开副本](releases/n02-minimal-closure-v1-100x100/provenance/review/)
- [公开文件清单及原始/脱敏哈希](releases/n02-minimal-closure-v1-100x100/PUBLIC_ARCHIVE_INVENTORY.json)

在发布目录执行 `python -B tools/verify_public_snapshot.py` 可校验公开文件。原始版本身份与脱敏公开副本的摘要分别记录；私有凭据、授权原文、SQLite 和原始运行日志未公开。

仓库的 `history/` 及旧文档保留早期节点记录；当前结论以本次 release 为准。
