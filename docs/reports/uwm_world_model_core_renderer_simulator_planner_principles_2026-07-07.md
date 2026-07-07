# UWM 世界模型核心能力实现原则

日期：2026-07-07

本文档用于约束后续 UWM（Urban World Model，城市世界模型）在城市宜居性分析任务中的开发方向，避免把 UWM 退化成传统指标大屏、静态综合评价或任意 smoke 实验。

## 核心判断

UWM 的核心不是“多源指标融合”本身，也不是“更漂亮的大屏”。世界模型的核心能力在于：

```text
Renderer:  D -> s_t
Simulator: (s_t, a_t) -> s_{t+1}, r, uncertainty
Planner:   search over a_{1:H} to maximize validated objective
```

也就是：

- 渲染器把真实城市数据变成可计算的世界状态；
- 模拟器预测“如果采取动作，城市状态会怎样变”；
- 规划器在模拟器中搜索行动序列，输出比传统静态策略更好的方案。

## Renderer：状态构造器，不是可视化大屏

这里的 renderer 不是前端可视化，而是“状态构造器”。

它要把空气质量、服务设施、人口、建筑形态、道路网络、空间邻接、公平暴露等真实数据，统一成 UWM 可用的状态 `s_t`。

Renderer 的关键不是展示，而是：

- 状态变量是否完整；
- 空间单元是否对齐；
- 数据来源是否可追溯；
- 不确定性和缺失是否显式保留；
- 状态是否能被 simulator 和 planner 使用。

当前 UWM renderer 已经具备：

- 36 个重庆中心城区行政单元状态；
- 空气质量、服务点、GHSL、OSM、2.5D 建筑楼层等多源状态；
- 行政空间邻接图；
- source coverage 和 claim boundary。

但当前 renderer 仍然不是完整 3D 城市状态，也不是高频动态城市状态。后续不能把 2.5D 楼层形态误说成完整 3D mesh/BIM/point-cloud 城市模型。

## Simulator：世界模型的核心

Simulator 是 UWM 区别于传统方法的核心部分。

传统方法通常只能回答：

```text
当前哪里差？
```

Simulator 必须回答：

```text
如果我采取某个行动，未来城市状态会怎么变化？
```

形式上是：

```text
s_{t+1} = T(s_t, a_t)
```

在城市宜居性场景中，simulator 至少应输出：

- heat risk delta；
- air exposure delta；
- service accessibility delta；
- equity delta；
- livability delta；
- neighbor spillover；
- uncertainty penalty。

当前 UWM 已有 data-calibrated planner replay 和 risk-adjusted rollout，但仍需继续增强：

- transition model 需要更强的数据校准；
- action-effect 不能长期停留在半机制假设；
- 需要更多真实 observed outcome 或准实验验证；
- 需要支持多场景 stress test；
- 需要避免把离线 replay 误说成真实政策 outcome。

## Planner：从静态排序到行动序列搜索

Planner 是 UWM 和传统方法最根本的差异之一。

传统方法通常是：

```text
按指标排序 -> 人根据经验决定先治理哪里
```

UWM 应该是：

```text
在模拟器中搜索行动序列 -> 输出最优或稳健行动组合
```

形式上是：

```text
π* = argmax E[ Σ r(s_t, a_t) ]
```

Planner 的最终输出不能只是“高风险区域排名”，而要输出：

- 动作序列；
- 目标行政单元；
- 预期状态变化；
- 空间外溢；
- 风险调整收益；
- 多端点权衡；
- 与传统 baseline 的比较证据。

当前 UWM 决策包已经开始做到这一点：它输出 2 步 action sequence，并证明优于 static heuristic、355 个 single-action baselines、风险调整 baseline 和空间外溢 baseline。

## UWM 超越传统方法的真正含义

UWM 超越传统方法，不应只理解为“同一指标上 MAE 小一点”。更关键的是，UWM 能输出传统方法无法形成的结果。

传统城市信息化和指标大屏通常输出：

- 当前状态指标；
- 静态排名；
- 单指标或综合指数；
- 红黄绿风险标识；
- 供管理者凭经验判断的材料。

它们本质上回答的是：

```text
现在哪里有问题？
```

UWM 应输出传统方法无法直接获得的反事实决策结果：

1. 如果采取某个行动组合，未来状态会怎样变化；
2. 哪个行动序列更优，而不是哪个地方当前指标最高；
3. 行动会产生哪些空间外溢；
4. 在不确定性下是否仍然值得做；
5. 结果是否对端点权重稳健；
6. 相比传统静态策略，为什么这个方案更好。

因此，UWM 的最终成果应是：

```text
城市宜居性反事实决策包
```

而不是一张指标排名表。

## 后续开发硬约束

后续每一个 UWM 开发任务，都必须回答以下问题：

1. 是否增强 renderer 的城市状态表达？
2. 是否增强 simulator 的动作条件转移能力？
3. 是否增强 planner 的搜索、优化、稳健决策能力？
4. 是否让最终输出变成传统方法无法得到的反事实决策结果？
5. 是否基于同一城市、同一数据、同一宜居性场景验证？
6. 是否明确 claim boundary，避免把离线 replay 说成真实政策 outcome？

如果一个新增功能不能服务于 renderer、simulator 或 planner 的核心能力，也不能增强最终反事实决策包，那么它只是堆指标，不应作为 UWM 核心开发任务。

## 当前 UWM 可支持的 bounded claim

当前 UWM 可以支持的说法是：

> 在重庆中心城区 36 个行政单元的真实准备数据基础上，UWM 已经能输出传统静态指标方法无法直接获得的反事实决策包；该决策包在验证端点、离线规划回放、风险调整、空间外溢、单动作 replay baseline 和端点权重敏感性上表现优于传统 baseline。

但当前 UWM 不能支持的说法是：

> UWM 已经在真实政策实施 outcome 上证明优于传统治理方法。

原因是当前仍缺少真实政策干预后的 observed outcome 或准实验级政策效果验证。
