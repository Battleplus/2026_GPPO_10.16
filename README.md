# N02 v2 九方法正式实验

本轮使用 100×100 地图、4 UAV + 2 helicopter、12 个任务、4 个训练父场景和 2 个开发父场景。八个主方法外，增加 Periodic-GPPO-WM 辅助配对对照。三 seed 的 54 个开发评价单元已实际完成。

研究结论为 **RESEARCH_CRITERIA_FAILED**。Event-GPPO 相比 Periodic-GPPO 的平均规划调用从 15 降到 6.67，完成率从 80.56% 升到 87.50%，全局效用从 5.0029 升到 5.6404；实际重构从 2.5 增到 4，环境动作消息从 13 增到 16。预设的通信、有效重构次数或重构规模至少一项下降的门槛未通过。WM 配对也未通过该门槛。

世界模型完成 240 次 CUDA 更新，六种学习方法合计完成 2,304 次 PPO 更新、288 个训练 episode。3 个世界模型和 18 个策略有新进程严格恢复收据。正式评价包含 3,240 个环境 tick。两个事件方法各有 9 个真实局部修复实例，空影响域的全局重构为零。

关键限制：事件方法实际合法候选数为 1～7，全九方法为 1～8（配置上限 16）；WM 只用于冻结辅助 critic，并非 actor 的候选规划器；传统方法受统一候选目录约束，CBBA-lite 不是完整 CBBA；PPO/GPPO 参数量不匹配；三 seed 与两个开发场景只支持描述性比较。规则方法的 seed 重复不是独立训练样本。

旧独立复算器漏识别延迟通信指令和道路阻断释放。原失败报告保留；新增外部测量器要求完整因果证据链，原始算法、奖励、轨迹和阈值不变。修订复算器零差异、零缺项，最终解释以 Sol Gate3 审核为准。

公开内容包括冻结源码、配置、后果训练样本、脱敏评价重放数据、训练更新收据、较小的图策略和世界模型 checkpoint、哈希、报告与独立审核。3 个大体积 Flat PPO checkpoint 和 1.44 GB 原始训练动作日志仅保留私有证据及公开哈希，不声称完整原始训练日志均已发布。历史资源账本中未测量的传输和 RSS 等字段保持 MISSING，不作外推。

详细报告及复算入口位于 `releases/n02-baseline-comparison-v1/`。本文件在最终审核前生成，工程验收与发布状态请查看同一提交的 `STATUS.md` 和 Gate3 收据。

工程审核：GPT-6.1 Sol High Gate1、Gate2、Gate3 均 PASS。研究门槛：FAILED。

- [正式源码、报告和数据](releases/n02-baseline-comparison-v1/)
- [Gate3 独立审核](reviews/n02-baseline-comparison-v1/SOL_HIGH_GATE3_FORMAL001_REVIEW.md)
- [公开数据重放](releases/n02-baseline-comparison-v1/reports/public-training-reproduction.md)
- [此前仓库索引](history/pre-n02-baseline-comparison-v1/README.md)

勘误：原训练协调器审计摘要的 `episodes.record_count=16` 是单组计数误标；Sol 对原始逐行记录核验为 18 组、288 个 episode。冻结报告保留原样，详见 Gate3 收据。
