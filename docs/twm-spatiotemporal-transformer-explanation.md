# TWM Spatiotemporal Transformer 说明

更新时间：2026-06-21

## 一句话结论

TWM 中的 `spatiotemporal transformer` 是一个轻量级、GIS 语义 token 化的行动条件时空动态模拟器候选后端。它用于学习“当前国土空间状态 + 规划行动 + 场景上下文 -> 未来状态、风险、效用、不确定性和行动可行性”的映射。

它不是通用大模型，也不是最终生产级模型；它是 TWM 当前研究验证闭环中的一个可训练 simulator 后端。

## 它具体是什么

代码中的实现名称主要是：

- `torch_spatiotemporal_transformer`
- `train_spatiotemporal_transformer_dynamics`
- `_SpatiotemporalTransformerDynamicsModel`

核心代码位置：

- `data_agent/territory_world_model/neural_dynamics.py`
- `scripts/run_twm_synthetic_experiment.py`

它会把一个 TWM 训练样本拆成一组固定语义 token：

| Token | 含义 |
|---|---|
| `parcel` | 地块/宗地层级状态 |
| `block` | 片区/项目/规划区层级状态 |
| `township` | 镇街/行政单元层级状态 |
| `county` | 区县/全局汇总状态 |
| `relations` | 空间关系、层级关系、变化关系 |
| `temporal` | 时间索引、历史状态、变化代理特征 |
| `action` | 当前要评估的规划/治理行动 |
| `scenario` | 场景上下文 |
| `context` | 规则、风险、行动掩码相关上下文 |

每类 token 先经过线性层、归一化和非线性变换编码到统一 hidden dimension，然后进入 PyTorch `TransformerEncoderLayer` 做 self-attention 融合。

当前实现是固定语义 token 上的轻量 transformer，不是全量地块图上的大规模时空图 transformer。

## 它在 TWM 中发挥什么作用

它在 TWM 中承担的是 simulator / dynamics model 角色，即动态模拟器角色。

给定：

- 当前国土空间状态；
- 一个候选行动；
- 场景上下文；
- 规则/风险/时间信息；

它预测：

1. 未来潜在状态：`future_latent_state.area_total`
2. 约束违规概率：`constraint_violation_probability`
3. 规划效用变化：`planning_utility_delta`
4. 不确定性置信度：`uncertainty.confidence`
5. 校准效用：`calibration.calibrated_utility_delta`
6. 行动是否允许：`action_mask.allowed`

这些输出被 planner、beam search 和 counterfactual rollout 消费。也就是说，planner 不是 TWM 的核心世界模型；planner 是这个 simulator 输出的下游消费者。

## 为什么叫 spatiotemporal

“spatial” 来自 TWM 对国土空间对象的层级和关系建模：

- parcel / block / township / county；
- object counts；
- relation counts；
- area、quality、risk summary；
- 空间层级关系和变化关系。

“temporal” 来自时间和动态变化特征：

- time index；
- observed next area proxy；
- baseline state score；
- baseline risk score；
- temporal transition / history delta。

这些空间层级 token、关系 token、时间 token 与 action / scenario / context token 一起进入 self-attention，因此它被命名为 `spatiotemporal transformer`。

## 理论来源和基础

它的理论基础不是单一论文，而是几条成熟方法线在 TWM 业务语义中的组合。

### 1. Transformer / Self-Attention

基础思想来自 Transformer 的 self-attention：不同 token 之间可以学习相互影响关系。

在 TWM 中，attention 不是处理自然语言词语，而是处理 GIS 语义 token。例如：

- 行动 token 会影响风险 token；
- temporal token 会影响未来状态预测；
- context token 会影响行动是否允许；
- parcel / block / township / county token 共同决定空间层级状态。

### 2. 时空建模

TWM 不是只看某一时刻的静态图层，而是关心国土空间状态如何随行动和时间变化。因此它引入了时空动态建模思想：

```text
state_t + action + scenario + context -> state_{t+1}, risk, utility, action_mask
```

### 3. World Model / Action-Conditioned Dynamics

它属于行动条件动态模型。核心问题不是“分类一个地块是什么”，而是：

> 如果采取某个行动，未来状态、风险、效用和可行性会怎样变化？

这正是 world model 中 simulator 的作用。

### 4. 多任务学习

它不是只训练一个目标，而是同时学习多个头：

- 状态转移；
- 风险；
- 效用；
- 置信度；
- 校准效用；
- 行动可行性。

这些多头输出共同构成 TWM 的模拟器合同。

## 它算不算 TWM 的原生创新产物

需要分层判断。

### Transformer 架构本身不是 TWM 原创

Self-attention、Transformer encoder、多头预测、dropout、weight decay、AdamW 等都不是 TWM 原创。这些是机器学习领域已有的通用技术。

因此不能说：

> TWM 发明了 Transformer。

也不能说：

> TWM 的 spatiotemporal transformer 是一个从零发明的新神经网络范式。

### TWM 的创新在组合方式和业务语义落点

更准确的说法是：

> TWM 的 spatiotemporal transformer 是一个 TWM 原生设计的 GIS 语义世界模型后端，它把通用 Transformer 技术嵌入到国土空间行动条件模拟器中。

它的创新点主要体现在：

1. **GIS 语义 token 化**
   - 不是把所有特征压成普通平面向量；
   - 而是把 parcel / block / township / county / relations / temporal / action / scenario / context 分成固定语义 token。

2. **行动条件动态模拟**
   - 它不是静态分类器；
   - 它预测某个规划行动作用后的状态、风险、效用和可行性。

3. **与 TWM 证据链绑定**
   - 输出必须进入 readiness、backend、objective、validation、claim ladder 等证据门；
   - 不能因为模型指标局部变好就直接声称生产可用。

4. **多头 simulator 合同**
   - 同时输出未来状态、约束风险、效用、不确定性和 action mask；
   - 这些输出可被 planner 和 counterfactual rollout 消费。

5. **风险头和可行性头的 TWM 化设计**
   - `constraint_risk_head` 支持 `shared`、`context_residual`、`context_direct`；
   - `action_mask_feasibility_head` 支持 `context_residual`；
   - 风险和可行性头显式读取 action / context / temporal token。

### 推荐对外表述

推荐说法：

> TWM 的 spatiotemporal transformer 不是对 Transformer 基础架构的原创发明，而是 TWM 原生的国土空间世界模型后端设计。它将 GIS 层级对象、空间关系、时间状态、规划行动和规则上下文组织成固定语义 token，并通过 attention 学习行动条件下的状态转移、风险、效用和可行性。这种面向国土空间规划/治理的 simulator 合同、证据门控和 planner 消费闭环，是 TWM 的系统性创新点。

不推荐说法：

> TWM 发明了一种全新的 Transformer。

不推荐说法：

> TWM 的 transformer 已经是生产级国土空间预测模型。

## 当前证据状态

当前实现已经具备：

- MLP / hierarchical graph / spatiotemporal transformer 三类可训练候选后端；
- transformer risk head probe；
- raw learned risk-head promotion gate；
- seed reproducibility gate；
- epoch seed-stability probe；
- hyperparameter seed-stability probe；
- planner holdout 和 rollout matrix 消费验证；
- false_allow / false_block 行动安全诊断。

最近已经找到第一个双 seed 稳定合成配置：

- effective transformer epoch budget: `100`
- learning rate: `0.008`
- weight decay: `0.004`
- dropout: `0.0`
- contextual risk weight: `3.8`
- risk weights: `1.0,1.1,1.2,1.3,1.4`
- seeds: `19,23`
- 两个 seed 都通过 raw learned-head promotion gate
- 两个 seed 的 raw selected false_allow 都为 `0`

但这仍然只是合成数据上的双 seed 证据。它还不能支持生产级结论。

## 当前边界

当前不能声称：

- 它已经在真实国土空间业务中证明准确可靠；
- 它可以直接替代人工规划审批判断；
- 它已经可以默认替代 affine risk calibration；
- 它是完整大规模时空图 transformer；
- 它已经通过真实 observed-history、跨区域、跨时序验证。

当前可以声称：

- 它是 TWM 内部可训练 simulator 后端；
- 它以 GIS 语义 token 和 action-conditioned dynamics 为核心；
- 它已经能在 synthetic foundation 上跑通严格验证闭环；
- 它已经具备 seed / epoch / hyperparameter 稳定性诊断；
- 它是 TWM 系统创新的一部分，但不是 Transformer 架构本身的原创。

## 后续验证方向

下一步应继续：

1. 扩大 seed 集，例如 `19,23,29,31,37`；
2. 接入真实非合成 approval / review observed-history；
3. 做跨区域 holdout 和时序 holdout；
4. 与 MLP、hierarchical graph、GeoFM 增强后端继续做 downstream planner lift 对比；
5. 只有在真实数据和更宽稳定性验证通过后，才考虑把 raw learned risk-head 配置升级为默认。
