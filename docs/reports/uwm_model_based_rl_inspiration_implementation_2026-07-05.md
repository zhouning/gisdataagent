# UWM Graph-MDP / Model-Based RL Scaffold Implementation

日期：2026-07-05

## 1. 论文启发边界

参考论文：

```text
Spatial planning of urban communities via deep reinforcement learning
Nature Computational Science, 2023
DOI: 10.1038/s43588-023-00503-5
Local PDF: /Users/zhouning/Downloads/77681512-6436-11ee-84fe-0242ac120002.pdf
```

本文档只记录对 UWM 的工程启发，不照抄论文实现。

论文对 UWM 最有价值的启发是：

1. 城市规划不能只做静态评价，应转为图上的 sequential MDP。
2. 城市空间不是规则网格，应用 graph 表示不规则地块、道路、节点及其 contiguity。
3. 动作空间必须通过 action mask 缩小，否则规划动作组合不可解。
4. 策略网络和价值网络应共享图状态编码器。
5. 每一步规划应记录 state、action、reward、transition，形成可训练/可回放的 trajectory dataset。
6. 与传统规则、遗传算法、人类方案比较时，必须使用相同初始条件和客观指标。

## 2. 本轮 UWM 实现内容

新增模块：

```text
data_agent/uwm/model_based_rl.py
data_agent/uwm/admin_spatial_graph.py
data_agent/uwm/offline_value_model.py
```

新增测试：

```text
data_agent/test_uwm_model_based_rl.py
```

新增真实代理数据输出：

```text
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_model_based_graph_search_admin_livability_proxy.json
data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_model_based_graph_search_admin_livability_spatial_graph_proxy.json
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_value_model_admin_livability_spatial_graph_proxy.json
```

## 3. 新增技术能力

### 3.1 Graph-MDP State

新增：

```text
build_graph_mdp_state(...)
```

它把 `UwmCanonicalObservation.v1` 转成：

```text
uwm.graph_mdp_state.v1
```

包括：

- graph nodes；
- graph edges；
- node features；
- available actions；
- action mask trace；
- claim boundary。

当前 state encoder 标记为：

```text
graph_feature_encoder_v0
```

注意：这还不是 learned GNN encoder，只是为后续 learned GNN / policy-value network 留出状态契约。

### 3.2 Admin Livability Proxy -> Graph Observation

新增：

```text
build_admin_livability_graph_observation(...)
```

它把：

```text
uwm.admin_livability_target_panel.v1
```

映射成可供 Graph-MDP 使用的：

```text
uwm.canonical_observation.v1
```

映射规则：

- `exposure_norm` -> `heat_risk`
- `exposure_priority_score` -> `air_pollution_exposure`
- `1 - service_gap_norm` -> `service_accessibility`
- `livability_need_score` -> `equity`
- `1 - livability_need_score` -> `livability`

旧版限制：

```text
graph_edges 如果不传入 admin_spatial_graph，则仍是 proxy_priority_similarity_not_spatial_adjacency
```

本轮已新增 `admin_spatial_graph` 参数。传入由行政边界派生的空间图时，observation 使用诱导出的 `admin_boundary_adjacency` 子图；这解决了“完全看不到空间图”的问题，但它仍只是行政边界拓扑，不是道路网络或交通/mobility 图。

### 3.3 Action Mask

当前 action mask 将规划动作约束为：

- `increase_green_infrastructure`：只允许作用于 `heat_risk` 超阈值单元；
- `traffic_emission_control`：只允许作用于 `air_pollution_exposure` 超阈值单元；
- `add_community_service`：只允许作用于 `service_accessibility` 低于阈值单元。

这对应论文中的关键思想：不要在巨大动作空间里盲搜，而是通过领域约束把动作空间压到可解范围。

### 3.4 Model-Based Graph Search

新增：

```text
plan_with_model_based_graph_search(...)
```

当前 backend：

```text
graph_mdp_beam_search_v0
```

它不是 PPO，也不是完整 DRL。它是第一版 model-based planning scaffold：

```text
masked graph actions
-> simulator rollout
-> reward evaluation
-> beam search over action sequences
-> best sequence
-> replay transitions
```

每个 transition 记录：

```text
state
action
reward
next_state_delta
transition
```

输出 replay dataset：

```text
uwm.graph_mdp_replay_dataset.v1
```

这一步的意义是把 UWM 从“单步候选排序”推进到“可回放的 state-action-reward-transition 轨迹”，为后续 learned dynamics、value model、offline RL 和 MPC/CEM planner 打基础。

## 4. 当前真实代理数据运行结果

### 4.1 旧版 proxy-priority Graph-MDP 报告

输入数据：

```text
data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json
```

设置：

```text
max_units = 8
horizon = 2
beam_width = 5
scenario_id = admin_livability_graph_mdp_proxy_2026_07_05
heat_stress_multiplier = 1.2
air_pollution_stress_multiplier = 1.15
vulnerability_multiplier = 1.1
```

输出：

```text
best_sequence_reward = 0.025056312
static_single_step_reward = 0.007987516
advantage_over_static_single_step = 0.017068797
replay_transition_count = 109
supported_claim = known_effect_model_based_graph_search_advantage
empirical_superiority_claim = false
```

最佳序列：

```text
1. increase_green_infrastructure -> 南岸区|南坪镇|299
2. increase_green_infrastructure -> 渝北区|龙溪街道|696
```

传统静态单步启发式：

```text
increase_green_infrastructure -> 九龙坡区|九龙镇|77
```

### 4.2 本轮新增 spatial Graph-MDP 报告

输入空间图：

```text
data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json
```

空间图事实：

```text
source_feature_count = 1017
node_count = 1017
edge_count = 2847
isolated_node_count = 0
edge_rule = polygon_boundary_touch_or_shared_boundary_v0
```

Graph-MDP 设置：

```text
max_units = 36
horizon = 2
beam_width = 5
selected_spatial_edge_count = 96
```

输出：

```text
best_sequence_reward = 0.012346806
static_single_step_reward = 0.001439757
advantage_over_static_single_step = 0.010907049
replay_transition_count = 355
supported_claim = known_effect_model_based_graph_search_advantage
empirical_superiority_claim = false
```

这个结果说明 UWM 已经从“代理相似图”推进到“真实行政边界邻接图上的 known-effect model-based search”。但它仍然不是 learned PPO/DRL，也不是真实政策 outcome superiority。

### 4.3 本轮新增 offline value model 报告

输入：

```text
355 条 spatial Graph-MDP simulator replay transitions
```

输出：

```text
holdout_mae = 0.000165326
train_mean_baseline_mae = 0.002418188
supported_claim = offline_replay_value_model_beats_train_mean_baseline
empirical_superiority_claim = false
```

这补上了“replay 能否被 value model 学习”的第一层证据，但它仍不是 PPO policy，也不是真实政策 outcome。

### 4.4 本轮新增 offline world-model policy 报告

输入：

```text
355 条 spatial Graph-MDP simulator replay transitions
```

输出：

```text
backend = ridge_action_conditioned_world_model_policy_v0
target = reward + heat_risk_delta + air_pollution_exposure_delta + service_accessibility_delta + equity_delta + livability_delta
holdout_reward_mae = 0.000165324
train_mean_baseline_mae = 0.002418188
selected_conservative_policy_action = increase_green_infrastructure-江北区|观音桥街道|653
selected_action_replay_mean_reward = 0.009041181
static_heuristic_replay_mean_reward = 0.007839757
replay_reward_advantage = 0.001201424
supported_claim = offline_world_model_policy_improves_replay_static_baseline
empirical_superiority_claim = false
```

这一步补上了 UWM 过去最明显的缺口之一：它不再只是 replay value fitting，而是显式训练 action-conditioned reward + dynamics 模型，并用该模型做 conservative policy ranking。它仍然不是在线 PPO，也不是真实政策 outcome，但已经具备更清晰的 model-based RL 技术形态：

```text
Graph-MDP state
-> action mask
-> replay dataset
-> learned reward+dynamics model
-> conservative policy improvement
-> replay/static heuristic comparison
-> evidence gate
```

### 4.5 本轮新增 learned world-model rollout planner 报告

新增产物：

```text
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json
```

真实运行指标：

```text
backend = multi_step_action_conditioned_learned_rollout_v0
training_transitions = 355
holdout_reward_mae = 0.000165324
train_mean_baseline_mae = 0.002418188
selected_sequence = increase_green_infrastructure-江北区|观音桥街道|653 -> add_community_service-九龙坡区|谢家湾街道|785
imagined_conservative_score = 0.011528613
static_imagined_score = 0.00124898
one_step_learned_policy_imagined_score = 0.002012933
supported_claim = learned_world_model_rollout_improves_imagined_static_and_one_step_baselines
empirical_superiority_claim = false
```

这一步把 UWM 从“一步 learned policy ranking”推进到了“学习模型驱动的多步想象规划”：每一步用 action-conditioned reward+dynamics 模型预测 reward 和 `heat_risk / air_pollution / service_accessibility / equity / livability` delta，再把 delta 写回目标单元 latent state，继续评估下一步动作。它仍然不是在线 PPO，也不是真实政策 outcome，但已经具备 model-based RL 中“learned world model -> imagined rollout -> action sequence improvement”的核心形态。

### 4.6 本轮新增 synthetic policy outcome scaffold

新增产物：

```text
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_synthetic_policy_outcome_benchmark_admin_livability_spatial_graph.json
```

真实运行指标：

```text
synthetic_status = synthetic
quality_status = synthetic_policy_outcome_not_observed
learned_rollout_synthetic_reward = 0.006346806
static_single_step_synthetic_reward = -0.004560243
learned_rollout_advantage_over_static = 0.010907049
claim_boundary = exploratory_only
empirical_superiority_claim = false
```

这一步只解决“没有真实 policy outcome 时，OPE/negative-control 管线如何先跑起来”的工程缺口。它不能证明真实政策效果，也不能解除 observed policy outcome gate。

### 4.7 本轮新增 livability intervention package

新增产物：

```text
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json
```

真实运行指标：

```text
schema = uwm.livability_intervention_package.v1
synthetic_status = synthetic
claim_boundary = exploratory_only
supported_claim = business_theory_aligned_learned_rollout_beats_static_proxy_baseline
empirical_superiority_claim = false
low_livability_unit_count = 10
multi_step_action_count = 2
predicted_heat_risk_delta = -1.027807246
predicted_air_pollution_exposure_delta = -0.411081019
predicted_service_accessibility_delta = 0.965080014
predicted_equity_delta = 0.552991953
predicted_livability_delta = 0.786721588
equity_status = equity_improves
```

这一步不是新造一个静态评分表，而是把世界模型的 learned rollout 输出转成城市宜居性理论要求的业务结果形态：

```text
low-livability area identification
-> mechanism explanation
-> intervention suitability map
-> multi-step action sequence
-> before/after indicator delta
-> equity conclusion
-> evidence boundary
```

它补上了用户指出的关键缺口：模拟器/规划器不能只停留在技术指标上，而必须输出“证据门控的城市干预方案包”。但边界仍然严格保留：方案包依赖 learned rollout、synthetic policy outcome scaffold 和 TAP-like PM2.5 v2，不是 observed intervention outcome，也不能证明真实政策效果优于传统方法。

### 4.8 本轮新增 data-foundation evidence gate

新增产物：

```text
data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json
```

真实运行指标：

```text
manifest_row_count = 63
accepted_synthetic_statuses = real + public_proxy + fitted_proxy + semi_synthetic + synthetic + restricted_expected
openaq_observed_observations = 600
openaq_holdout_count = 180
openaq_dynamic_wins_vs_static_train_mean = 150
openaq_holdout_win_rate = 0.833333
pm25_dynamic_mae = 2.4
pm25_best_static_mae = 9.466667
observed_state_prediction_superiority_claim = true
observed_policy_outcome_superiority_claim = false
```

这一步落实了“完整数据基础都可以用”的原则：UWM 不只读取 `real` 标签，而是读取 manifest 中已准备、可审计的所有数据资产。但每类数据进入不同证据层：

```text
real / observed public proxy -> 可支撑对应范围的 observed holdout 结论
public_proxy -> 可支撑 bounded proxy 结论
fitted_proxy -> 可支撑 simulator/planner scaffold
semi_synthetic / synthetic -> 可支撑开发、压力测试和负控
restricted_expected -> 只能作为待补缺口
```

因此 evidence gate 不是为了缩窄数据使用范围，而是防止把 synthetic、smoke 或 proxy 越界说成真实政策 outcome。

### 4.9 本轮新增 graph-aware action-conditioned world model

新增产物：

```text
data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_graph_aware_world_model_admin_livability_spatial_graph_proxy.json
```

真实运行指标：

```text
backend = ridge_graph_aware_action_conditioned_dynamics_v0
spatial_nodes = 36
spatial_edges = 96
training_transitions = 355
holdout_count = 71
graph_aware_reward_mae = 0.000103937
target_only_reward_mae = 0.000844982
train_mean_reward_mae = 0.002418188
reward_win_rate_vs_target_only = 0.957746479
supported_claim = graph_aware_world_model_beats_target_only_and_train_mean_baselines
empirical_superiority_claim = false
```

这一层把 UWM 从“只看目标单元状态的 action-conditioned dynamics”推进到“带空间消息的 action-conditioned dynamics”。模型特征包含：

```text
target state features
neighbor mean features
target-neighbor risk/gap contrasts
action x neighborhood pressure
```

这比 target-only baseline 更符合城市世界模型的基本假设：城市干预不是孤立作用于一个行政单元，热风险、污染暴露、服务可达性和宜居性都存在空间邻接溢出和上下文依赖。本轮结果在 prepared spatial Graph-MDP replay holdout 上给出了事实优势，但仍不是 observed policy outcome。

## 5. 能声明什么，不能声明什么

可以声明：

```text
UWM 已新增 Graph-MDP / model-based rollout search scaffold。
在 admin livability proxy known-effect benchmark 上，
2-step graph rollout search 的机制 reward 高于传统静态单步启发式。
本轮新增的 spatial Graph-MDP 使用 1,017 个全量行政单元派生的 2,847 条边界邻接边，
并在 36 个 livability 候选单元上形成 96 条真实空间邻接边。
本轮新增的 offline value model 在 simulator replay holdout 上优于 train-mean baseline。
本轮新增的 offline world-model policy 学习了 action-conditioned reward+dynamics，
并在 simulator replay 中让 conservative learned policy 高于静态启发式。
本轮新增的 learned world-model rollout planner 使用 learned dynamics 做 2-step imagination，
imagined conservative score 高于静态单步和一步 learned policy baseline。
本轮新增 synthetic policy outcome scaffold 只用于 OPE/negative-control 管线联调，
不支撑 empirical superiority claim。
本轮新增 livability intervention package 能把世界模型输出组织为城市宜居性业务理论要求的方案包，
但该方案包仍是 exploratory/proxy scaffold。
本轮新增 data-foundation evidence gate 读取完整 UWM 数据基础和实际产物，
明确 observed OpenAQ temporal state prediction 优于传统静态 baseline，
同时阻止 synthetic/smoke/proxy 冒充 observed policy outcome。
本轮新增 graph-aware action-conditioned world model，
在 spatial Graph-MDP replay holdout 上显著优于 target-only dynamics baseline。
```

不能声明：

```text
UWM 已经在真实政策 outcome 上优于传统方法。
UWM 已经训练出完整在线 deep reinforcement learning / PPO policy。
行政空间邻接图可以替代道路网络、交通流、OD 或 travel-time accessibility。
```

原因：

- 当前已有 learned reward+dynamics v0，但训练和验证都来自 simulator replay，不是 observed transition outcome；
- 当前 graph-aware world model 证明了空间消息能提升 prepared replay dynamics holdout，但仍不是真实政策干预结果；
- 当前 search 是 beam/MPC scaffold；offline world-model policy 和 learned rollout planner 是保守离线策略改进，不是 PPO/CEM/MCTS 完整训练；
- 当前 livability intervention package 是对 learned rollout 与 synthetic scaffold 的业务组织，不是客户权威数据验证后的政策方案；
- 新增 admin graph 是 polygon/admin-boundary adjacency，但不是 road/mobility graph；
- 当前优势是 known-effect reward advantage，不是 observed policy outcome superiority。

## 6. 下一步必须做的核心突破

### 6.1 更完整的城市图

已完成：

```text
admin boundary adjacency
```

还需要继续构造：

```text
road-network adjacency
service-accessibility graph
environmental exposure propagation graph
```

并保留旧版 proxy 图只作为 fallback：

```text
proxy_priority_similarity_not_spatial_adjacency
```

### 6.2 Learned Dynamics

已完成 v0：

```text
train_offline_world_model_policy(...)
```

它基于 Graph-MDP replay 训练 reward + state-delta 多目标 ridge world model。

下一步要从 ridge 升级为图结构模型：

```text
z_t = E_theta(O_t, G)
z_t+1 = f_theta(z_t, a_t, e_t, G)
reward = R_phi(z_t, a_t, z_t+1)
```

### 6.3 Policy / Value Network

当前已有 offline value model v0、conservative offline world-model policy v0 和 learned dynamics multi-step rollout planner v0。下一步应从线性 ridge scaffold 升级为：

```text
graph neural value model
edge/node policy scorer with action mask
uncertainty-calibrated MPC/CEM/MCTS rollout
offline policy evaluation with observed/quasi-observed holdout
```

### 6.4 真实评估闭环

必须建立：

```text
static heuristic policy
UWM model-based policy
observed or quasi-observed holdout
policy regret
negative control
causal evidence gate
```

只有这一层完成，才能把 claim 从 known-effect advantage 推进到真实或准真实经验优势。
