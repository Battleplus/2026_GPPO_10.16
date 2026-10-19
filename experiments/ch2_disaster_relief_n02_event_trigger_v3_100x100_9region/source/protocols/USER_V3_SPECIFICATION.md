# N02 v3：9区域、24 UAV + 6直升机的事件触发式区域重构

## 总体方案

保留 100×100 地图和已经冻结的 v2 作为 C0 历史基线，新建：

```text
development/ch2_disaster_relief_n02_event_trigger_v3_100x100_9region/
```

新版本采用：

- 3×3 宏区域，共 9 个区域；
- 24 架 UAV；
- 6 架直升机，作为全局支援池；
- 每个区域 4 个初始任务、1 个动态到达任务，共 45 个任务；
- 第一章先进行全局公开信息初始分配；
- 第二章采用“本区优先 → 一跳邻区支援 → 全局重构兜底”；
- 每次事件最多生成 16 个候选动作；
- 先完成 CPU 机制验证，再进行 GPU、世界模型和 G/G-WM PPO。

区域边界固定为：

```text
x,y = [0,33), [33,66), [66,100)
```

区域编号为 `r00` 至 `r22`。UAV 分布固定为：

```text
2  3  3
3  2  3
3  3  2
```

总数为 24，且每行、每列均有 8 架 UAV。6 架直升机不绑定区域，初始位置位于六个非对角区域中心，字段为：

```text
region_id = null
support_scope = global
```

## 需要修改的接口

### 场景合同

新场景合同使用 `relief-engineering/2`，保留原有 100×100 地图合同，并增加：

```json
{
  "region_contract": "relief-regions-3x3-v1",
  "regions": [
    {
      "region_id": "r00",
      "bounds": [0, 0, 33, 33],
      "center": [16.5, 16.5],
      "neighbors": ["r01", "r10", "r11"]
    }
  ]
}
```

平台和任务增加：

```text
region_id
region_center
```

旧的 `local` 字段只作为兼容字段，区域归属以 `region_id` 和坐标校验为准。

新的场景校验必须确认：

- 平台和任务坐标属于其 `region_id`；
- 每个区域有 2 或 3 架 UAV；
- 总平台数为 30；
- 初始任务数为 36；
- 隐藏动态任务数为 9；
- 所有任务、平台和区域 ID 唯一；
- 100×100、10000 网格合同仍然成立。

### C1 初始分配

保留现有公开信息 C1 分配器，但移除旧的单一区域布尔匹配限制：

```text
bool(platform.local) == bool(task.local)
```

C1 只使用：

- 已公开的平台状态；
- 已公开的 36 个初始任务；
- 能力；
- 距离；
- 时间；
- 能量；
- 载荷；
- 库存。

C1 不读取隐藏动态任务、未来事件或第二章标签。输出必须包括：

```text
全局队列
区域任务分布
平台区域分布
未分配任务及原因
C1算法来源
公开输入哈希
分配结果哈希
```

### 事件作用域

`identify_affected_scope()` 输出：

```json
{
  "direct_region_ids": [],
  "affected_region_ids": [],
  "affected_task_ids": [],
  "affected_platform_ids": [],
  "neighbor_region_ids": [],
  "communication_components": [],
  "local_eligible": true,
  "regional_eligible": false,
  "global_eligible": true,
  "scope": "LOCAL_REPAIR",
  "reason": []
}
```

作用域规则固定为：

- 单区域、单通信连通分量、局部资源仍可行：`LOCAL_REPAIR`；
- 本区资源不足或一跳邻区支援必要：`REGIONAL_REPLAN`；
- 多区域故障、网络分裂、关键平台失效或局部/区域修复无解：`GLOBAL_REPLAN`；
- 没有受影响实体时禁止生成全局重构。

每个空间环境扰动仍然使用真实 2×2 patch，但 patch 必须位于某个宏区域内部，并记录其 `region_id`。

### 候选动作

候选生成器统一改为：

```python
generate_reconstruction_candidates(
    observation,
    affected_scope,
    max_candidates=16
)
```

候选类型固定为：

```text
NOOP
LOCAL_TRANSFER
LOCAL_SWAP
LOCAL_INSERT
REGIONAL_SUPPORT
GLOBAL_REPLAN
```

每个候选必须包含：

```text
candidate_key
action_type
scope
region_ids
platform_ids
task_ids
full_environment_action
communication_cost
switch_cost
reconstruction_size
legal
rejection_reason
public_prefix_hash
snapshot_hash
```

生成器必须接收真实的 `affected_scope` 字典，禁止把非 NOOP 动作传成字符串 `"NOOP"`。候选选择和环境执行统一使用同一个完整动作对象，避免出现“策略选择了局部动作、环境实际执行成 NOOP”的问题。

候选目录必须包含：

- 一个 NOOP；
- 至少两个合法局部动作；
- 能够产生不同任务所有者或队列变化的局部动作；
- 必要时包含一跳邻区动作；
- 全局动作只能在作用域允许时出现。

## 执行阶段

### S0：冻结 v2 并做机制诊断

保持当前 v2 不变，作为 C0。先用现有 4 UAV + 2 helicopter、12任务场景做 CPU 验证。

依次确认：

1. `local_eligible=true`；
2. 事件确实触发；
3. 合法局部候选数量大于零；
4. 策略请求 `LOCAL_REPAIR`；
5. repair 后作用域仍为局部；
6. 环境中的任务所有者或队列真实变化；
7. 独立后果计算器能够复算 NOOP 和非目标任务标签。

任何一步首次归零就停止，记录为接口问题，不进入大规模训练。

### S1：9区域 CPU 场景验证

使用 9区域、24 UAV、6直升机、45任务，但暂时关闭世界模型和 PPO。

覆盖：

- 单区域 2×2 环境扰动；
- 新任务到达；
- UAV 能量下降；
- 平台故障；
- 通信质量下降；
- 一跳邻区支援；
- 多区域混合事件；
- 全局 fallback。

至少准备：

```text
1个训练父场景
1个开发父场景
1个单区域局部 witness
1个跨区域 witness
```

通过标准：

- C1 公开初始分配成功；
- 9个区域的任务和平台归属正确；
- 单区域事件只影响目标区域及必要邻区；
- 至少两个合法局部候选；
- 局部动作真实改变 owner 或 queue；
- 一跳支援产生通信记录；
- 不可行时能够进入区域或全局重构；
- 2×2扰动的独立因果复算通过；
- NOOP 和非目标任务标签复算通过。

### S2：GPU pilot

先关闭世界模型，只比较：

```text
Periodic-G
Event-G
```

配置固定为：

```text
seed = 8201
4个训练父场景
2个开发父场景
1轮训练
最多32次 PPO 更新
相同事件 tape、相同 episode、相同开发场景
```

必须报告：

```text
任务完成率
按时完成率
平均延迟
局部重构次数
区域级重构次数
全局重构次数
局部动作成功率
通信消息数
跨区域消息数
重构规模
任务所有者变化数
任务切换数
决策延迟
全局 fallback 比例
```

S2 通过条件：

- 所有动作 100% 合法；
- 至少一个被独立审计的有效局部 witness；
- `LOCAL_REPAIR` 不再系统性归零；
- Event-G 相对 Periodic-G 在效用和按时率上不低于预注册容差；
- 至少一项规划、通信或重构成本下降。

如果局部链路通过但策略仍不选择局部动作，问题归因于 actor、mask 或 ranking；如果候选本身为空，问题归因于场景或候选生成器。

### S3：正式世界模型和 G/G-WM

只有 S2 通过后进入正式实验。

世界模型：

```text
训练数据：真实9区域分支轨迹
seed：8201、8202、8203
候选上限：16
平台槽位：30
任务槽位：45
区域槽位：9
```

checkpoint 必须记录：

```text
地图合同
区域合同
平台数量
任务数量
区域数量
候选身份
数据哈希
模型配置
优化器状态
seed
训练更新数
```

执行：

- forward；
- loss；
- backward；
- optimizer update；
- 新进程恢复；
- 恢复前后预测一致性；
- global/task 预测误差；
- unknown 比例；
- 每个区域的标签覆盖率。

G/G-WM 使用同一批训练 episode 和开发场景：

```text
G：普通图 GPPO
G-WM：冻结世界模型 + auxiliary critic
```

必须证明：

- G 和 G-WM 都完成真实 PPO 更新；
- G-WM auxiliary critic 梯度有限且非零；
- auxiliary 参数真实变化；
- 世界模型参数变化为零；
- actor logits 没有被世界模型直接修改；
- 两组 checkpoint 可恢复；
- 所有更新数量和资源账本一致。

## Sol High 审核节点

Sol High 只读审核以下节点：

- A：新场景合同、区域划分和 C1 边界；
- B：S0 局部动作链；
- C：S1 9区域 CPU 机制；
- D：S2 GPU pilot；
- E：世界模型训练与恢复；
- F：G/G-WM PPO 和开发评价；
- G：最终哈希、Manifest、Request、Attempt、资源账本和信息泄漏。

旧 v2 归档不覆盖。新版本必须独立生成：

```text
Manifest
SHA256SUMS
Request
Attempt
Authorization binding
Checkpoint
Resource ledger
GitHub branch
GitHub tag
```

## 选型规则

最终只按预注册门槛决定采用哪种规模：

- 如果 9区域版本通过 S2 和 S3，则作为第二章主实验；
- 如果 9区域工程通过但效果不稳定，而 S0/S1 局部机制通过，则论文表述为“基于第一章全局分配的区域内动态任务重构”，把大规模结果作为扩展实验；
- 如果 9区域候选、作用域或执行链失败，保留失败证据，先修复工程接口；
- 不把单次 pilot 当作显著性结论；
- 不把绝对效用直接跨规模比较，统一报告按任务、按完成任务和单位通信成本归一化指标。

该方案可以支持约 30 架平台，但当前代码不能直接运行这一规模。真正的第一步是完成区域合同、C1 全局分配边界、作用域传递和候选执行链，然后才扩大 GPU 训练。
