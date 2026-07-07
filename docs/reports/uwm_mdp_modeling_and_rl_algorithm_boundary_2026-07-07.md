# UWM MDP 建模与 RL 算法边界说明

日期：2026-07-07

## 1. 当前 UWM 中 MDP 是如何建模的

目前 UWM 的 MDP 是一个真实数据 Graph-MDP，不是抽象 toy MDP。对应实现主要位于：

- `data_agent/uwm/livability_graph_mdp_env.py`
- `data_agent/uwm/livability_rl_training.py`
- `data_agent/uwm/model_based_rl.py`

当前 MDP 面向同一个城市宜居性分析场景，使用同一套重庆中心城区 UWM 数据基础。

## 2. MDP 组成要素

### 2.1 状态 S

状态来自 renderer 生成的 `uwm.canonical_observation.v1`，再转成 Graph-MDP state。

当前状态包含：

- 36 个重庆宜居性候选行政单元节点；
- 96 条 induced 行政边界邻接边；
- 每个节点的特征：`heat_risk`、`air_pollution_exposure`、`service_accessibility`、`equity`、`livability`；
- episode 内部状态：`step_index`、`remaining_horizon`、已选择 action 序列、累计 reward；
- 训练用 state key：`(step_index, selected_action_indices)`。

因此，当前不是图神经网络 embedding，而是显式 graph state + tabular state key + aggregate state vector。

### 2.2 动作 A

动作是经过 mask 的行政单元干预动作，目前有 3 类：

- `increase_green_infrastructure`
- `traffic_emission_control`
- `add_community_service`

动作格式包括：

- `action_id`
- `action_type`
- `target_units`
- `intensity = 1.0`
- `mask_reason`

动作空间当前为 60 个可行动作。mask 规则来自阈值，例如 heat risk 高才允许 green/cooling 类动作，污染暴露高才允许 traffic emission control，服务可达性低才允许 add community service。

### 2.3 状态转移 P(s'|s,a)

当前转移不是靠真实政策 outcome 估计的概率转移，而是由 UWM simulator 给出：

```text
s, a -> simulate_livability_rollout(...) -> future_state_delta -> s'
```

转移模型使用：

- data-calibrated mechanism table；
- data-calibrated spatial spillover kernel；
- scenario stress multipliers；
- 行政邻接传播；
- PM2.5 uncertainty context。

所以它是 model-based 的模拟器转移模型，不是 model-free 只从环境采样学习。

### 2.4 奖励 R(s,a,s')

reward 是风险校正后的增量收益：

```text
risk_adjusted_score =
  livability_delta
  + 0.50 * equity_delta
  - 0.10 * uncertainty_interval_width
  - PM2.5 uncertainty_penalty
```

每一步 reward 是当前累计 risk-adjusted score 减去上一步 score。

这点很重要：不是所有动作都被硬编码为正收益。某些交通治理动作虽然改善污染暴露，但扣除 PM2.5 不确定性和风险后，单步 reward 可以是负的。

### 2.5 初始状态、终止条件、折扣因子

当前设置：

- 初始状态：`reset()` 后 step=0、未选择任何 action；
- horizon：2 步；
- done：达到 horizon 或无可用 action；
- discount factor：`0.9`；
- training episodes：`160`。

### 2.6 策略 pi

训练过程中采用 epsilon-greedy：

- `epsilon_start = 0.75`
- `epsilon_end = 0.05`

最终策略是 trained Q-values 上的 greedy policy。

## 3. 当前选择的 RL / DRL 算法

严格说，当前没有使用深度强化学习 DRL 网络模型。

当前实现的是：

```text
Dyna-Q tabular model-based RL
```

也就是说：

- Q-learning 负责学习 `Q(s,a)`；
- epsilon-greedy 负责探索；
- replay_model 存储 `(state, action) -> reward, next_state, done`；
- planning updates 使用模型回放更新 Q；
- final full model backup 使用 simulator 做模型备份；
- 最终策略是 greedy policy from trained Q-values。

因此当前算法边界应描述为：

- 是 model-based；
- 不是纯 model-free；
- 不是严格意义上的 DRL；
- 没有使用 PPO / DQN / SAC / Actor-Critic 神经网络；
- 更准确叫法是：tabular model-based RL / Dyna-Q over real-data Graph-MDP。

## 4. 当前训练结果

当前训练报告为：

```text
data/uwm_public_proxy/chongqing_central/livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json
```

关键结果：

- `episode_count = 160`
- `algorithm = dyna_q_tabular_model_based_rl`
- `learned_policy_reward = 0.001923762`
- `traditional_static_reward = -0.003208192`
- `advantage_over_traditional_static = 0.005131954`

## 5. 证据边界

当前结果不能被表述为 observed policy outcome，也不能被表述为完整城市级神经世界模型。

当前可支持的说法是：

```text
UWM 已经具备基于真实数据 Graph-MDP 的 simulator-grounded model-based RL training evidence。
```

当前不能支持的说法是：

```text
UWM 已经训练完成城市级 DRL policy/value network。
UWM 已经在真实城市干预 outcome 上证明政策优越性。
```

## 6. 下一步升级方向

如果要升级成真正 DRL，需要在当前 UWM-RL-1 基础上继续增加：

- graph policy/value network，例如 GNN + PPO、DQN、SAC 或 Actor-Critic；
- 更大规模 episode 训练；
- 更高维状态表示，包括完整 graph embedding；
- 真实干预日志或可信 counterfactual off-policy evaluation；
- 更严格的 observed policy outcome holdout；
- 更完整的城市级 multi-agent / multi-objective / constrained planning。

在这些能力完成之前，必须继续保留当前 claim boundary。
