# TWM 动作条件化多头状态转移的理论来源与依据

“动作条件化的多头状态转移”不是一个单一原创理论名词，而是 TWM 对几类成熟理论的工程组合：

```text
state_t + action_t
    -> future_state_{t+1}
    -> constraint_risk
    -> planning_utility
    -> uncertainty
    -> evidence/action-mask status
```

## 1. MDP 与 Model-Based Reinforcement Learning

最基础依据是马尔可夫决策过程（Markov Decision Process, MDP）：

```text
P(s_{t+1} | s_t, a_t)
```

也就是未来状态不是只由当前状态决定，而是由“当前状态 + 动作”共同决定。强化学习和模型式规划里，agent 学一个 dynamics model，再用它做 rollout 或 planning。Sutton 的 Dyna 架构、Sutton & Barto 的 RL 框架、后来的 model-based RL 都是这个方向。

TWM 对应关系是：

```text
s_t = 当前国土治理状态
a_t = inspect / protect / convert / restore 等治理动作
s_{t+1} = 动作后的潜在国土状态
```

参考：

- Sutton & Barto, *Reinforcement Learning: An Introduction*
- Sutton, “Dyna, an Integrated Architecture for Learning, Planning, and Reacting”
- Moerland et al., “Model-based Reinforcement Learning: A Survey”, https://arxiv.org/abs/2006.16712

## 2. World Model

World model 的核心是：系统内部学习或维护一个环境模型，用来预测环境如何随动作变化，从而支持规划。Ha & Schmidhuber 的 World Models、MuZero 都体现了这个思想。

尤其 MuZero 的思想和 TWM 很接近：不必完整还原世界全部细节，而是学习对规划有用的预测量。MuZero 预测 reward、value、policy；TWM 预测 constraint risk、planning utility、uncertainty、evidence gate。

TWM 的对应关系是：

```text
不是预测所有 GIS 细节
而是预测业务决策需要的状态变化和风险/收益头
```

参考：

- Ha & Schmidhuber, “Recurrent World Models Facilitate Policy Evolution”, https://arxiv.org/abs/1809.01999
- Schrittwieser et al., “Mastering Atari, Go, chess and shogi by planning with a learned model”, https://arxiv.org/abs/1911.08265

## 3. Action-Conditioned Prediction

“动作条件化”本身在视觉预测、机器人、游戏环境中已有明确先例。例如 Action-Conditional Video Prediction 的问题就是：未来帧取决于过去观测和控制动作。

TWM 不预测图像帧，而是预测结构化 GIS 状态：

```text
video frame prediction:
past frames + action -> future frames

TWM:
current GIS state + governance action -> future latent territorial state
```

参考：

- Oh et al., “Action-Conditional Video Prediction using Deep Networks in Atari Games”, https://arxiv.org/abs/1507.08750

## 4. 多任务学习与多头输出

“多头”来自 multi-task / multi-output learning。一个共享状态表示同时服务多个相关预测任务：

```text
shared representation
    -> transition head
    -> risk head
    -> utility head
    -> uncertainty head
    -> action-mask/evidence head
```

这样做的理论依据是：这些任务不是独立的。国土业务里，状态变化、约束风险、规划收益、证据完备性本来相互关联。多头输出能让模型避免只优化一个指标，例如只追求高规划收益，却忽略硬约束风险。

参考：

- Caruana, “Multitask Learning”, *Machine Learning*, 1997

## 5. 约束 MDP 与 Safe Reinforcement Learning

国土空间规划不是普通 reward maximization。很多约束是硬约束，例如永久基本农田、生态红线、审批证据缺失。

所以 TWM 不能只做：

```text
maximize utility
```

而要做：

```text
maximize planning utility
subject to hard constraints, evidence gates, action feasibility
```

这对应 constrained MDP / safe RL 的思想：奖励之外显式建模约束或安全条件。

参考：

- Altman, *Constrained Markov Decision Processes*
- Wachi & Sui, “Safe Reinforcement Learning in Constrained Markov Decision Processes”, https://arxiv.org/abs/2008.06626

## 6. 因果推断与反事实推演

TWM 里的 action 不应只是普通特征，而应尽量接近干预：

```text
P(outcome | action observed)
```

和

```text
P(outcome | do(action))
```

不是一回事。导师如果追问严谨性，这一点很关键。

当前 TWM 还不能完全证明 `do(action)` 因果效应，但把 action-conditioned rollout、causal calibration、SCCA evidence gate 分开，是为了避免把相关性误称为因果。

参考：

- Pearl, “The Do-Calculus Revisited”, https://arxiv.org/abs/1210.4852
- Pearl, *Causality: Models, Reasoning, and Inference*

## 对 TWM 的严谨表述

较严谨的表述是：

> TWM 的“动作条件化多头状态转移”来源于 MDP/model-based RL 的 action-conditioned transition model，结合 world model 的内部预测表示、多任务学习的共享表示多头输出、constrained MDP/safe RL 的硬约束门控，以及因果推断中对 intervention/counterfactual 的审慎区分。它在国土空间业务中的转译，是用一个结构化 GIS object-relation-rule-evidence state 表示当前状态，并在给定治理动作后，同时预测未来状态、约束风险、规划效用、不确定性和证据门控。

不应表述为：

> 我们提出了全新的理论。

更合适的研究定位是：

> 理论基础是成熟的，但 TWM 的研究问题在于：这些理论能否在国土空间治理场景中，通过 GIS 对象-关系-规则-证据状态和业务基线验证，解决现有工具未充分解决的“动作后果、硬约束、证据链、规划选择”一体化问题。

## 当前项目中的实现边界

目前代码中已经实现了这个框架的工程原型：

- `forecast`：状态 + 动作 -> 多头 forecast；
- `counterfactual_rollout`：baseline action vs intervention action；
- `beam_plan`：用 utility/risk/confidence 排序候选动作；
- `action_mask_report`：硬约束和复核门控；
- `dynamics_readiness` / `dynamics_evaluation` / `train_dynamics_candidate`：为未来 trainable dynamics 做数据合同；
- `baseline_comparison_report`：把主张放回 baseline 和证据门里评估。

但目前仍主要是 deterministic scaffold + synthetic fixtures。真实理论有效性要靠真实/脱敏历史、同案 baseline、action labels、holdout validation 来证明。
