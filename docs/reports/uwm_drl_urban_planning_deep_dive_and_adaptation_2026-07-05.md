# UWM 对 DRL Urban Planning 论文与代码的深读及适配说明

日期：2026-07-05

## 1. 参考材料核验

本说明参考但不照搬以下材料：

- 本地论文 PDF：`/Users/zhouning/Downloads/77681512-6436-11ee-84fe-0242ac120002.pdf`
- 论文：Zheng et al. 2023. *Spatial planning of urban communities via deep reinforcement learning*. Nature Computational Science. DOI: `10.1038/s43588-023-00503-5`
- GitHub：`https://github.com/tsinghua-fib-lab/DRL-urban-planning`
- Zenodo：`https://doi.org/10.5281/zenodo.8175420`
- 已下载并核验的 Zenodo 包：`/private/tmp/DRL-urban-planning-v0.1.zip`
- Zenodo MD5：`5b1e1fc019a19eb052160b8bbd199b6d`，本机核验一致。

论文场景是社区空间规划，核心动作是土地利用和道路布局生成；UWM 场景是城市宜居性世界模型，核心动作是热风险、空气污染、公共服务、公平性等干预方案。因此只能迁移技术架构思想，不能迁移奖励函数、动作定义或实验结论。

## 2. 论文和开源代码中的关键技术结构

### 2.1 Graph-MDP 状态

论文把社区规划表述为动态城市连通图上的序列决策问题。开源实现中，`urban_planning/envs/observation_extractor.py` 组织了：

- numerical planning requirement features；
- node features；
- edge index；
- current node features；
- node/edge masks；
- land-use action mask；
- road action mask；
- stage indicator。

这说明“世界状态”不是单张静态图，而是图结构、当前对象、阶段、需求满足度和可行动作掩码的组合。

### 2.2 GNN 状态编码器

`urban_planning/models/state_encoder.py` 的 `SGNNStateEncoder` 用 node encoder、edge MLP、edge-to-node scatter、self-attention 和 numerical feature encoder 形成共享状态表征，并输出三类下游表征：

- land-use policy head input；
- road policy head input；
- value network input。

这给 UWM 的启发是：livability 不能只用表格排序。UWM 需要把行政单元、邻接关系、热暴露、空气污染、服务可达性、公平性和场景压力编码到同一个图状态中，再让 policy/value 共享该状态。

### 2.3 Action Mask

`urban_planning/models/policy.py` 将非法动作位置的 logits 替换为接近负无穷的 padding，再构造 categorical distribution。这个机制很关键，因为城市规划动作有强约束：地块、道路或 UWM 干预不应在不可行动对象上被采样。

UWM 当前已实现规则版 action mask：`data_agent/uwm/model_based_rl.py::build_graph_mdp_state` 根据 heat risk、air pollution、service accessibility 阈值生成可行动作。下一步学习式 policy 必须继续使用 mask，而不是把无效动作交给模型自己学。

### 2.4 Replay 和 PPO 训练

论文代码用 agent 采样序列轨迹，并以 reward、transition、value、policy log-prob 等训练 PPO。其本质不是“有一个模拟器就够了”，而是：

```text
state -> masked action -> environment/world-model transition -> delayed reward
      -> trajectory/replay -> value/policy update -> new policy
```

UWM 当前已经完成 Graph-MDP state、masked action、simulator rollout、replay tuple、exact beam search、offline value model v0、action-conditioned reward+dynamics world model v0、conservative offline policy improvement v0，以及 learned dynamics multi-step rollout planner v0。它还没有在线 PPO、GNN policy/value network 或 observed policy outcome OPE，因此不能宣称完整深度强化学习。

## 3. UWM 已完成的适配实现

### 3.1 Graph-MDP scaffold

已实现文件：

- `data_agent/uwm/model_based_rl.py`
- `data_agent/test_uwm_model_based_rl.py`

当前能力：

- 将 `uwm.canonical_observation.v1` 转换为 `uwm.graph_mdp_state.v1`；
- 输出 nodes、edges、graph statistics；
- 输出 action masks 和 available actions；
- 通过 UWM simulator 进行 action-conditioned rollout；
- 输出 `uwm.graph_mdp_replay_dataset.v1`，包含 state、action、reward、next_state_delta、transition；
- 用 2-step beam search 做 model-based graph search；
- 与静态单步启发式 baseline 比较。

这是真正的 model-based RL 边界雏形，但不是完整 DRL。

### 3.2 本轮新增：真实行政空间邻接图

新增文件：

- `data_agent/uwm/admin_spatial_graph.py`
- `scripts/build_uwm_admin_spatial_graph.py`

新增 artifact：

- `data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json`
- `data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_model_based_graph_search_admin_livability_spatial_graph_proxy.json`
- `data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_value_model_admin_livability_spatial_graph_proxy.json`

真实生成结果：

```text
source_feature_count = 1017
node_count = 1017
edge_count = 2847
isolated_node_count = 0
selected_unit_count = 36
selected_spatial_edge_count = 96
replay_transition_count = 355
best_sequence_reward = 0.012346806
static_single_step_reward = 0.001439757
advantage = 0.010907049
empirical_superiority_claim = false
supported_claim = known_effect_model_based_graph_search_advantage
offline_value_model_holdout_mae = 0.000165326
offline_value_model_train_mean_baseline_mae = 0.002418188
offline_value_model_supported_claim = offline_replay_value_model_beats_train_mean_baseline
```

这里的 1017 是你提供/挂载的重庆乡镇街道行政单元子集全量；36 是当前 livability target panel 的候选行政单元；8 是上一版 Graph-MDP proxy search 的 top-k 规划样本，不是你提供的数据量。

### 3.3 数据基础清单更新

已加入 manifest：

- `chongqing_admin_spatial_adjacency_graph_2026_07_05`
- `uwm_model_based_graph_search_admin_livability_spatial_graph_proxy`

新增角色：

- `spatial_adjacency_graph`

该角色服务于 simulator、planner 和 model_based_rl。它不等于 road/mobility graph，也不能替代交通网络或通勤数据。

## 4. UWM 不能照搬论文的部分

### 4.1 动作不能照搬

论文动作是土地利用分配和道路生成。UWM 的动作应该是：

- 增绿或蓝绿基础设施；
- cool roof 或建筑降温改造；
- 交通排放控制或低排放区；
- 社区服务补点；
- 面向弱势人群的公平性优先干预。

这些动作必须受数据、规划政策和可实施性约束，不能把 land-use/road action head 直接套过来。

### 4.2 奖励不能照搬

论文奖励围绕服务、生态、交通等规划目标。UWM livability reward 应该围绕：

- heat risk reduction；
- air pollution exposure reduction；
- service accessibility improvement；
- equity gain；
- uncertainty penalty；
- policy feasibility penalty；
- claim-boundary gate。

当前 UWM reward 是透明机制版，用于可审计 rollout 和 known-effect 验证；未来需要用观测 holdout 或准实验数据校准。

### 4.3 结论不能照搬

论文证明的是其 DRL 方法在社区空间规划任务上相对启发式和优化基线的表现。UWM 当前只能说：

- 在已知效应 simulator 和 proxy target panel 中，2-step model-based graph search 优于静态单步启发式；
- OpenAQ temporal benchmark 证明动态状态更新强于静态时间基线；
- 尚不能证明真实政策干预 outcome 上优于传统城市模型或传统规划方法。

## 5. 仍然缺的核心技术

### 5.1 Learned Value / Policy

本轮已基于 spatial Graph-MDP replay 完成第一个离线 value model scaffold：

```text
graph_mdp_state + masked_action_sequence -> predicted rollout reward
```

当前做到的是：

- ridge value model 训练于 355 条 simulator replay transitions；
- 固定 holdout split 上 MAE 为 0.000165326；
- train-mean baseline MAE 为 0.002418188；
- `empirical_superiority_claim = false`。

当前又新增了 action-conditioned reward+dynamics world model 和 2-step learned rollout planner：

```text
selected_sequence = increase_green_infrastructure-江北区|观音桥街道|653 -> add_community_service-九龙坡区|谢家湾街道|785
imagined_conservative_score = 0.011528613
static_imagined_score = 0.00124898
one_step_learned_policy_imagined_score = 0.002012933
```

下一步合格标准不是“能训练”，而是：

- held-out replay 上 value ranking 能把高回报 action sequence 排在静态 baseline 前；
- 对 shuffled graph 或 shuffled temporal controls 性能下降；
- policy/value 的结论仍受 claim boundary 限制。

### 5.2 Learned Dynamics

当前已有线性 ridge action-conditioned learned dynamics，但训练和验证来自 simulator replay，不是观测城市动力学。下一步需要：

- 从 OpenAQ temporal benchmark 学污染物动态；
- 从 Open-Meteo/GEE ERA5 学气象驱动；
- 从 GHSL/OSM/admin panel 学空间异质性；
- 将 learned dynamics 与 mechanistic simulator 做 ensemble 或 residual correction。

### 5.3 真实 Outcome Holdout

目前最大证据缺口仍是：

- 空气污染有 OpenAQ 时间序列 holdout，但不是政策干预 outcome；
- 气象是上下文驱动，不是政策 outcome；
- 服务可达性是 OSM bbox 样本，不是完整网络出行时间面；
- 没有真实干预前后或准实验 policy outcome 数据。

所以 empirical_superiority_claim 必须保持 false。

## 6. 下一阶段 UWM 技术路线

1. 固化 `uwm.admin_spatial_adjacency_graph.v1` 合同和 validator。
2. 把空间图纳入 `UwmCanonicalObservation.v1` 的正式数据基础页面。
3. 扩展 replay：多 scenario、多 action intensity、多 horizon、多随机 stress multiplier。
4. 为 offline value model 增加 negative controls：shuffled edges、shuffled target scores、static one-step、greedy current-deficit。
5. 将 ridge scaffold 升级为图结构 dynamics / masked policy scorer，并增加 uncertainty-calibrated MPC/CEM/MCTS rollout。
6. 只有在 observed holdout 或准实验 outcome 到位后，才允许把 claim boundary 从 known-effect proxy 推进到 empirical superiority。

## 7. 当前结论

本轮 UWM 已从“代理优先级图”推进到“全量重庆行政边界空间邻接图 + Graph-MDP 规划回放”。这补上了世界模型/RL 架构中图状态和空间转移的一块硬基础。

但严格来说，UWM 现在仍是：

```text
model-based RL-ready scaffold + exact graph search + offline replay value model + action-conditioned learned dynamics + conservative offline policy improvement + learned multi-step rollout planner + proxy known-effect evidence
```

还不是：

```text
trained deep RL policy/value model with observed policy outcome superiority
```

这个边界必须继续写在报告、HTML 数据基础页和任何对外材料里。
