# 世界模型、事件触发与 Critic 数据流

## 结论

同一个时间步、同一组候选动作只进行一次世界模型 ensemble 预测。预测结果被两个位置复用：

1. **事件触发器**：使用 NOOP 候选的预测效用和候选预测不确定性，形成 `d_degradation`、`d_uncertainty` 并参与触发指标 `Γt`。它不直接从候选动作中选最大价值动作。
2. **Auxiliary critic**：使用这次预测得到的均值和方差特征，与当前图状态特征拼接，输出辅助价值；该值与普通 GPPO critic value 相加。

```text
当前状态 + 候选动作集
          │
          ▼
世界模型 ensemble（一次）
          │
          ├── 每候选后果均值/方差
          │       └── NOOP效用 + 不确定性 → Γt → 是否触发重构
          │
          └── 均值/方差特征 → auxiliary critic
                                  │
                                  └── 普通critic + auxiliary critic
                                          │
                                          ▼
                                   GPPO actor选动作
```

## Event-G-WM 与 Periodic-G-WM 的区别

- `Event-G-WM`：世界模型摘要参与事件阈值判断，同时预测结果进入 auxiliary critic。
- `Periodic-G-WM`：预测结果进入 auxiliary critic；触发时机由周期规则控制，因此世界模型不负责替代周期触发器。
- 每到新的时间步，若状态或候选集发生变化，则重新进行一次新的预测。

## 边界

当前 actor logits 没有直接接收世界模型特征。世界模型通过触发器和 auxiliary critic 间接影响策略训练与价值估计；最终动作仍由 GPPO actor 在合法动作掩码下选择。当前实验已验证这条数据流运行，但尚未证明世界模型单独带来了开发集性能优势。
