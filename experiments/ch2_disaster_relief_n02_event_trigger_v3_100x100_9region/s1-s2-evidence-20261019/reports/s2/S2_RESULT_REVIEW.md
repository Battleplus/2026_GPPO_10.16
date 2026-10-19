# S2 实际 GPU 结果独立审查

结论：**S2 FAIL / REPAIR_REQUIRED；S3 BLOCKED**。进程 exit 0 与研究门禁通过是两个结论。审查为 same-family 独立上下文，语义保证 provisional；可重复的哈希、算术、记录与张量检查已核实，不构成外部认证。

冻结结果：`[REDACTED_LOCAL_PATH] SHA256 `21bbcd8769810d2988ed1edf79976107c8d8696b15cdd4565677cc748aa0d35a`；原始 source manifest `1a36e8d2f8eed88e43dc352ac1082eb3351041d3d5eb3b950ac85e98786cd9de`；attempt `99a7e67bc1684fcb94a231e8c72a728e`；run `eb5fee7ed88c43068f5796944727e031`。最终 146/146 文件哈希和精确清单一致（source 107、evidence 39），其中 source manifest 的 104 项均匹配；原始重算的 32 个输入与最终 evidence/run 字节一致。

## 原注册门禁

- 两算法各 360/360 动作完成 candidate/key/mask/repair/执行与原始操作绑定，共 720；各 240 train、120 development transitions。
- train 有效局部动作均 **0**，原门禁要求每算法至少 1：FAIL。
- development Event−Periodic utility **−0.26688389931575784**，原要求 ≥0：FAIL。
- on-time 差 **0**，原要求 ≥−0.02：PASS。
- planning calls 60/60、消息 36/38、重构规模 0/1（Periodic/Event）：没有一个允许的成本严格降低，FAIL。
- 各 28 实际 optimizer steps，配对一致且在原范围 [1,32]；六 parent 分割及配对初态一致：PASS。

没有增加验收条件。以下是 14 个报告指标，计数纠正不改变门禁。

| development 两 parent 均值 | Periodic-G | Event-G |
|---|---:|---:|
| 完成率 | 0.8 | 0.8 |
| 按时率 | 0.8 | 0.8 |
| 平均延迟/min | 1.6 | 1.6 |
| 局部重构 | 0 | 0 |
| 区域重构 | 0 | 0 |
| 全局重构 | 0 | 1 |
| 局部动作成功率 | null | null |
| 通信消息 | 36 | 38 |
| 跨区消息（地理口径） | 0 | 0 |
| 重构规模 | 0 | 1 |
| owner 变化 | 0 | 1 |
| 任务切换 | 0 | 1 |
| 决策耗时/s | null | null |
| 全局回退比例 | null | 1 |

原始 utility：30.9993993376535 / 30.7325154383378。按原始任务归一：0.688875540836745 / 0.682944787518617；按已完成任务：0.861094426045931 / 0.853680984398271；按通信消息：0.861094426045931 / 0.808750406272046。每 parent 原始任务45、完成36、按时36，均按 parent 先计算后取均值；不以预测分布归一。

平均延迟是所有原始任务的终点迟延，未完成任务使用 terminal_time，并非仅已完成任务的迟延。局部成功率分母为执行的非 NOOP local 动作，均为0，所以 null；Periodic 的全局回退分母也为0。决策耗时无逐决策计时，null，不能拿训练总 wall 代替。跨区消息用发送前 observation 的端点位置按冻结半开区域 bounds 映射；两算法均0，全部端点可映射。Periodic 全部 self；Event 每 parent 唯一非 self 是 t1 heli5→uav19，端点同属 r20。直升机固定 region_id=null，因此此项只支持地理口径。

**安全风险仍为 null**：raw move 缺 environmental_risk。奖励重算遵循冻结公式的缺字段按0语义，但这不支持安全风险为0的结论。原始事件独立重算的奖励、终点完成/按时/能耗、owner/queue 变化和生产汇总相符。

## 局部失败及 actor 诊断

Periodic train 的唯一 legal local catalog 出现在 new_arrival parent 的 t10（task-r01-hidden），两候选对应 uav04/uav03；gamma 0.015283209327996657 < threshold 0.023214151451484255，t10 非 periodic tick，前一触发 t8。high mask [true,false,false,false]，candidate mask [true,false,false]，最终 NOOP；无有效局部执行。

Event train 全程没有 legal local catalog。同一 t10 的 affected scope 已是 GLOBAL_REPLAN，catalog 为 NOOP+8 global；gamma 0.021439616177142073 <同阈值，below_threshold 后 NOOP。前序轨迹已分叉，不能将其归为与 Periodic 完全相同的局部 mask 故障。

28/28 全参数摘要均改变且链连续，loss/gradient 有限，更新记录 tensor device 为 cuda:0。**Periodic actor 梯度非零 0/28，初末 actor 摘要完全相同；其更新来自 critic，不能称 actor 学习成功。** Event actor 非零梯度13/28，actor 摘要改变。CPU weights_only 只读计算的 model/actor、optimizer steps、update-log、config/scenario/threshold/probe 哈希均与保存内容、最终更新行及远端新进程 restore 回执一致。远端各恢复进程 exit0，cuda:0，actor/critic 各 forward1；本审查未重跑。

## 身份、资源与证据边界

request/attempt/authorization/publishing/native/runtime/handoff/restore/settlement/formal receipt/ledger 的正式身份和哈希一致；entry、S1、GPU probe 输入逐项哈希吻合。wrapper 的 `e99814d3f5284fceaef163ef97b43475` 是独立的本地包装层 ID，正式 attempt 是 `99a7e67bc1684fcb94a231e8c72a728e`，不能混同。authorization 文件明确只是 machine_scope_identity_only_no_human_authorization；它本身不证明人类授权。

RTX2080Ti，物理 GPU1→逻辑 cuda:0，Python3.11.16/torch2.7.0+cu128/numpy1.26.0；affinity[0]，1 thread。GPU receipt peak allocated470402048B，参数和 Adam moments cuda:0。whole cgroup settlement CPU556.183671s；guardian 起点1.125332s，区间差555.058339s。guardian+child552.290893s不含全部 restore descendants，不能代替 whole cgroup。child启动至restore后结算的 wall555.486283s，guardian total556.610748s；前者不是纯child wall。child max RSS2418944KiB；whole-cgroup memory peak未记录，null，不能用child RSS冒充。冻结launcher配置CPUQuota100%、MemoryMax8GiB和RuntimeMaxSec7260；guardian仅在主child运行时主动轮询7200s CPU/wall，restore无单独timeout。这是执行边界限制；本次实际CPU/wall均低于7200s，回执未记录timeout/超限。范围为本次正式 cgroup，排除上传、本地测试、审查及其他 attempt；GPU allocated memory不是 GPU计算时间。账本仅stage/formal exit两行，数值资源来自 GUARDIAN_SETTLEMENT。外部补充 journal 未进入冻结 manifest，其相同attempt的终点systemd CPU为556.871s，与结算采样时点不同，单列path/hash作为旁证；本结论不依赖它。

## 完整性检查 A–F 与可支持声明

A PASS：结果来自模拟 raw_truth 与事件，不由模型预测生成参考。B PASS：原始分数及真实任务/消息分母同时报告。C PASS：文件、字段和注册门禁数值核实。D WARN：逐决策计时未记录；局部成功分母0；安全字段缺失，均诚实保留 null。E WARN：仅一 seed、四 train/two development parents，不支持全面、稳健、held-out或真实世界优越性。F：simulation_only。

支持“实际 GPU 进程运行、配对记录和 checkpoint 恢复证据存在”；不支持“S2通过”“Event优于Periodic”“两算法actor均学习”“安全风险为0”。修复须另行授权并建立新冻结身份；本审查没有训练、模拟重放、策略推理、S3或更改冻结证据。

详见同目录 RAW_RECOMPUTATION、RESULT_FREEZE_VERIFICATION、IDENTITY_CHAIN_VERIFICATION、CHECKPOINT_VERIFICATION、CROSS_REGION_RECOMPUTATION、RESOURCE_RECONCILIATION 的 JSON。审查脚本仅写此目录。
