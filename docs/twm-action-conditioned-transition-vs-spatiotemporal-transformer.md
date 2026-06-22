# 动作条件化多头状态转移与 Spatiotemporal Transformer 的关系

一句话概括：

> “动作条件化的多头状态转移”是 TWM 要解决的建模任务和输出合同；`spatiotemporal transformer` 是可能用来学习这个状态转移函数的一种神经网络实现。

二者不是同一个层级的东西。

```text
动作条件化多头状态转移 = 问题定义 / 预测任务 / 训练目标
spatiotemporal transformer = 一种可选模型架构 / backend
```

## 1. TWM 的状态转移任务

TWM 要建模的是：

```text
current GIS state + action + scenario + evidence context
    -> future latent state
    -> constraint violation probability
    -> planning utility delta
    -> uncertainty
    -> action mask / evidence gate
```

这个整体就是“动作条件化的多头状态转移”。

其中：

- `current GIS state` 是当前国土治理状态；
- `action` 是 `inspect` / `protect` / `convert` / `restore` 等治理动作；
- `scenario` 是业务场景；
- `evidence context` 是规则、证据、审计、复核等约束上下文；
- 输出不是单一状态，而是多个与业务决策相关的预测头。

## 2. Spatiotemporal Transformer 的定位

Spatiotemporal transformer 可以作为其中的 `fθ(...)`：

```text
fθ(state_t, action_t, time, spatial tokens)
    -> multi-head outputs
```

也就是说，spatiotemporal transformer 是学习该状态转移函数的一种候选 backend。

在当前 TWM 项目中，dynamics backend 有多种候选：

- deterministic scaffold；
- neural multi-head MLP；
- hierarchical graph dynamics；
- spatiotemporal transformer dynamics。

所以 spatiotemporal transformer 不是 TWM 的全部，也不是 TWM 的理论本体。它只是 trainable dynamics backend 的一个候选实现。

项目代码中也把它标成 candidate，而不是最终生产级模型：

- `data_agent/territory_world_model/neural_dynamics.py`
- `data_agent/territory_world_model/service.py`

## 3. 为什么 Spatiotemporal Transformer 适合这个任务

Spatiotemporal transformer 的优势在于：

1. 能用 attention 建模远距离空间关系，例如项目地块和生态红线、永久基本农田、规划分区之间的非局部影响。
2. 能把 parcel / block / township / county 等层级 token 放进统一序列或分组 token 表示。
3. 能结合时间状态、历史变化、动作类型，学习跨期变化。
4. 多头输出天然可以连接 transition、risk、utility、uncertainty、action-mask 等任务头。

也就是说，它适合承担 TWM 中“复杂空间-时间-动作交互”的可学习部分。

## 4. 为什么它不能替代整个 TWM

Spatiotemporal transformer 只能回答：

```text
给定状态和动作，模型如何预测多头结果？
```

它不能单独解决：

- 业务场景是否真实存在未满足需求；
- 规则证据是否可审计；
- baseline 是否被打败；
- 数据是否能支持生产声明；
- 预测结果是否能越过 evidence gate；
- 硬约束方案是否应该被阻断。

这些是 TWM 的治理闭环问题，不是 transformer 架构本身能解决的。

## 5. 严谨表述

可以这样表述：

> TWM 的核心建模对象是动作条件化的多头状态转移；spatiotemporal transformer 是实现这一状态转移函数的候选神经架构之一。它通过空间-时间 token attention 学习国土对象、管控边界、规划分区、历史状态和治理动作之间的交互，并输出未来状态、约束风险、规划效用、不确定性和动作可行性等多头结果。但在缺少真实时序样本、动作标签和同案 baseline 验证前，它只能是实验性 backend，不能作为 TWM 有效性的独立证明。

## 6. 面对“技术堆砌”质疑时的回答重点

如果直接说“我们用了 spatiotemporal transformer”，容易被认为是技术堆砌。

更好的说法是：

```text
我们的问题不是“要不要用 transformer”，
而是“国土治理动作导致的状态、约束和规划后果能否被可靠建模”。

Transformer 只是候选实现。
能不能用，取决于它是否在真实/脱敏历史、同案 baseline、holdout validation 上证明比 simpler baseline 更有效。
```

当前项目里已经保留了这个边界：

- `dynamics_readiness` 检查数据是否足够训练 dynamics；
- `dynamics_backend_report` 检查 backend 是否 action-conditioned、multi-head、forecast-consumable；
- `training_objective_report` 检查 transition、constraint、ranking、calibration、uncertainty、evidence consistency 等 loss contract；
- `baseline_comparison_report` 把 TWM 主张放回 named baseline 和 evidence gate 中评估。

因此，TWM 的严谨路线不是“用了 spatiotemporal transformer，所以先进”，而是：

```text
先定义业务问题和状态转移任务；
再定义多头输出和证据门控；
再选择合适 backend；
最后用真实同案 baseline 和 holdout validation 判断 backend 是否值得保留。
```
