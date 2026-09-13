# UWM 实现城市宜居性分析的理论基础与 Model-Based RL 缺口

日期：2026-07-05

## 1. 一句话结论

UWM 做城市宜居性分析的理论基础，不是“指标加权打分”，而是把宜居性定义为人在城市空间中获得健康、安全、便利、舒适、机会和公平生活条件的动态能力状态；技术上再用世界模型闭环把它实现成：

```text
观测 -> 状态 -> 干预 -> 转移 -> 结果 -> 证据门控
```

但需要明确修正一点：当前 UWM v0 的 simulator / planner 起点主要是透明机制型 simulator、证据门控 planner 和 known-effect benchmark。2026-07-05 本轮已补上 Graph-MDP replay、offline value model、action-conditioned reward+dynamics world-model policy v0 和 learned dynamics multi-step rollout planner v0；它已经具备 model-based RL 的关键切片，但训练和验证仍来自 simulator replay，不是 observed policy outcome。因此，仍不能把当前 v0 说成完整的、已在真实政策结果上验证的 model-based RL UWM。

## 2. 城市宜居性分析的理论基础

UWM-Livability 当前采用三层宜居性定义：

1. 环境暴露层：热风险、空气污染、交通暴露、绿地水体、极端天气压力。
2. 机会可达层：教育、医疗、商业、公园、公交通勤、慢行、就业和活动机会。
3. 公平与脆弱性层：老人、儿童、低收入、高暴露群体，以及干预收益是否真正流向低宜居区域。

这不是单个分数，而是动态城市状态。项目文档里已经明确：宜居性不是“指标加权叠加后的静态排名”，而是“环境风险、机会可达、人口脆弱性和治理干预共同作用下的动态城市状态”。

理论上对应几个框架：

- 人本需求与能力方法：看居民能不能健康生活、获得服务、避免风险、公平分享资源。
- 环境健康的暴露-风险-脆弱性框架：`risk = exposure x sensitivity x adaptive_capacity`。
- 可达性与时间地理学：不是设施数量，而是不同人群在合理时间/成本内能否到达服务。
- 空间公平与环境正义：必须回答谁受益、谁受损、低宜居区域是否持续被边缘化。
- 城市复杂系统与韧性：城市形态、交通活动、环境暴露、服务供给、人口脆弱性是耦合系统，要能做高温、静稳天气、人口变化等情景压力测试。

所以 UWM 的形式化不是传统：

```text
指标 -> 标准化 -> 加权 -> 排名
```

而是：

```text
O_t -> z_t -> a_t -> z_t+1 -> y_t+k -> V
```

也就是：城市观测、城市状态、干预动作、状态转移、多目标结果、证据约束价值函数。形式化表达为：

```text
z_t = Encoder(O_t, G)
z_t+1 = Dynamics(z_t, a_t, e_t, G)
y_t+k = Decoder(z_t+k)
V = Livability(y, equity, uncertainty, evidence)
```

其中：

- `O_t`：遥感、建筑、道路、POI、AOI、人口、通勤、气象、LST、PM2.5/NO2/O3、规划约束等观测；
- `G`：城市空间图，包括空间邻接、道路网络邻接、功能相似邻接、通勤联系；
- `z_t`：城市世界状态，不是单个指数，而是形态、环境暴露、活动强度、服务供给、脆弱性共同构成的状态表示；
- `a_t`：可解释规划干预，例如增绿、降低交通排放、公共服务补点、建筑强度调整、慢行网络优化；
- `e_t`：外生情景，例如高温日、静稳天气、人口增长、交通需求变化；
- `y_t+k`：热风险、空气污染暴露、服务可达性、空间公平和综合宜居性；
- `V`：多目标价值函数，不能只看平均分，必须包含弱势群体和低宜居区域是否改善。

## 3. UWM 技术架构如何实现宜居性分析

### 3.1 Urban Data Foundation / MMFE

所有建筑、DEM、CLCD、道路、POI/AOI、GHSL、Open-Meteo、OpenAQ、GEE ERA5/CAMS 等数据都必须进入 manifest，标清真实、公开代理、半合成、合成、许可、时间、空间范围和 claim boundary。没有来源和证据边界的数据不允许进入模型。

MMFE 的作用不是旁路工具，而是 UWM 数据融合前级：负责 profiling、assessment、alignment、execution、validation，并产出 `mmfe.uwm_state_input.v1`。

### 3.2 Renderer: 城市观测算子

Renderer 不是地图显示，而是城市观测算子：

```text
raw urban data / MMFE semantic product
-> data manifest
-> spatial unit builder
-> layer role binding
-> feature extraction
-> graph construction
-> quality and provenance sidecar
-> UwmCanonicalObservation.v1
```

它必须表达 object-field duality：

- object：建筑、道路、POI、AOI、公共服务设施、街区、行政边界；
- field：LST、NDVI、NDBI、PM2.5、NO2、O3、AlphaEarth embedding、人口栅格、气象栅格。

输出必须包含：

```text
spatial_units
object_layers
raster_features
graph_edges
temporal_index
quality_flags
synthetic_flags
provenance
claim_boundary
renderer_trace
```

### 3.3 State / Graph Layer

UWM 把城市表达为 `O_t + G`，不是一张静态表。`G` 包括：

- 空间邻接；
- 道路连通；
- 功能相似；
- 通勤/OD；
- 环境传播邻近；
- 服务可达性网络。

这样才能表达干预影响的空间溢出，而不是只做行政区排名。

### 3.4 Simulator: 当前实现

当前入口：

```text
data_agent.uwm.simulator.simulate_livability_rollout(
    observation,
    action_sequence,
    scenario
)
```

它消费 canonical observation、action sequence 和 scenario，输出 `UwmRolloutTrace.v1`。当前 v0 支持的动作包括：

- `increase_green_infrastructure`：降低热风险和污染暴露，轻度改善服务与公平；
- `cool_roof` / `building_cooling_retrofit`：降低热风险；
- `traffic_emission_control` / `low_emission_zone`：降低空气污染暴露；
- `add_community_service` / `service_accessibility_improvement`：提升服务可达性和公平。

输出不是一个分数，而是多头结果：

```text
heat_risk_delta
air_pollution_exposure_delta
service_accessibility_delta
equity_delta
livability_delta
uncertainty_interval
evidence_grade
simulator_trace
```

当前 v0 的宜居性变化是透明机制函数：

```text
livability_delta =
  -0.35 * heat_risk_delta
  -0.25 * air_pollution_exposure_delta
  +0.25 * service_accessibility_delta
  +0.15 * equity_delta
```

这说明当前实现是可审计的机制型 simulator，不是黑箱预测器，也不是已经完成真实政策校准的因果模型。

### 3.5 Planner: 当前实现

当前入口：

```text
data_agent.uwm.planner.build_evidence_gated_plan(
    rollout_traces,
    planning_goal,
    constraints
)
```

Planner 不能直接看静态低分区域排序，只能消费 simulator trace。它按证据等级、公平约束、最低收益、不确定性宽度做 hard gate，再排序候选干预。

当前 v0 打分为：

```text
score = livability_delta + 0.50 * equity_delta - 0.10 * uncertainty_width
```

这体现了 UWM 的城市宜居性决策逻辑：不只追求平均宜居性改善，还要考虑公平收益和不确定性惩罚。

### 3.6 Evaluation / Evidence Gate

传统 baseline 当前定义为：

```text
static_weighted_indicator_overlay
```

它没有 action-conditioned transition、没有 rollout、没有 simulator trace。UWM 通过 dynamic advantage evaluation 比较“动态动作响应”和“静态指标叠加”的差异，并用 negative control 防止 simulator 把任何动作都判成有益。

当前可以声明：

```text
UWM 架构已经能把城市宜居性从静态评分推进到状态条件化、动作条件化、带 trace 和 evidence gate 的反事实推演。
```

当前不能声明：

```text
UWM planner 已经在真实政策 outcome 上证明优于传统方法。
```

原因是仍缺真实干预 outcome holdout、因果校准和外部验证。当前实证最强的是 OpenAQ 时间序列状态预测层，不是完整政策效果证明。

## 4. 你指出的问题：当前 simulator / planner 缺少 model-based RL 的影子

这个判断是成立的。

当前 v0 的实现更像：

```text
canonical observation
-> transparent mechanistic transition table
-> rollout trace
-> evidence-gated planner
-> known-effect benchmark
```

它有世界模型 runtime 的基本边界，但还不等于 model-based RL。严格的 model-based RL 至少还应包含：

1. **Trajectory Dataset**
   - 真实或代理轨迹：`(O_t, z_t, a_t, r_t, O_t+1, y_t+k)`；
   - 支持 temporal split、holdout、negative control；
   - 支持 replay buffer 或 offline RL dataset。

2. **Learned State Encoder**
   - `z_t = E_theta(O_t, G)`；
   - 可以融合遥感 embedding、图结构、环境状态、POI/AOI、人口脆弱性；
   - 不应只是 hand-crafted indicator vector。

3. **Learned Dynamics Model**
   - `z_t+1 = f_theta(z_t, a_t, e_t, G)`；
   - 支持 action-conditioned prediction；
   - 支持 spatial spillover、scenario branching、uncertainty ensemble；
   - 用 holdout transition loss 评估，而不是只靠机制表。

4. **Reward / Value Model**
   - `r_t = R_phi(z_t, a_t, z_t+1)`；
   - `V_psi(z_t)` 或 `Q_psi(z_t, a_t)`；
   - reward 必须可解释为 health、accessibility、equity、risk、cost、evidence penalty 的组合。

5. **Policy / Planner Improvement**
   - 不能只是一次性排序；
   - 应使用 model predictive control、CEM、MCTS、trajectory optimization 或 offline policy improvement；
   - 输出 `pi(a | z)` 或至少输出经过 rollout search 的 action sequence。

6. **Model-Based Evaluation**
   - world model rollout 与真实 holdout 对比；
   - policy regret 与传统 heuristic 对比；
   - OPE / off-policy evaluation；
   - placebo / negative control；
   - uncertainty calibration；
   - causal evidence gate。

## 5. 应补的 Model-Based RL 版 UWM 架构

后续如果要让 UWM 真正体现“有模型的强化学习”，架构应升级为：

```text
Trajectory Dataset D
  = {(O_t, G_t, a_t, e_t, O_t+1, y_t+k, evidence_t)}

Renderer:
  O_t = Render(raw_data_t, MMFE_t)

Encoder:
  z_t = E_theta(O_t, G_t)

World Model / Dynamics:
  z_t+1_hat = f_theta(z_t, a_t, e_t, G_t)
  y_t+k_hat = g_theta(z_t+k)

Reward / Value:
  r_t = R_phi(y_t+k_hat, equity, cost, uncertainty, evidence)
  V_psi(z_t), Q_psi(z_t, a_t)

Planner / Policy:
  a_0:H = argmax rollout_sum(R_phi) subject to constraints
  or pi_omega(a | z) improved by model rollouts

Evidence Gate:
  downgrade or reject claims when holdout / causal / uncertainty gates fail
```

技术上可分三步推进：

### Step 1: 从机制表升级为可学习 dynamics

已完成 v0：

```text
train_offline_world_model_policy(...)
target = reward + heat_risk_delta + air_pollution_exposure_delta
       + service_accessibility_delta + equity_delta + livability_delta
holdout_reward_mae = 0.000165324
train_mean_baseline_mae = 0.002418188
```

它保留 transparent simulator 作为 replay 生成器和基线，并新增 action-conditioned reward+dynamics 学习。下一步仍要补图神经 dynamics、directional accuracy、uncertainty calibration 和 negative-control 结果。

### Step 2: 从排序 planner 升级为 learned rollout planner

已完成 v0：

```text
plan_with_offline_world_model_rollouts(...)
selected_sequence = increase_green_infrastructure-江北区|观音桥街道|653
                 -> add_community_service-九龙坡区|谢家湾街道|785
imagined_conservative_score = 0.011528613
static_imagined_score = 0.00124898
one_step_learned_policy_imagined_score = 0.002012933
```

Planner 不再只比较单步候选，而是用 learned reward+dynamics 比较多步 action sequence 的 cumulative reward、risk reduction、service gain、equity gain 和 uncertainty penalty。下一步应从固定 beam search 升级为 uncertainty-calibrated MPC / CEM / MCTS。

### Step 3: 从 known-effect benchmark 升级为 offline policy evaluation

已完成 v0：

```text
static_indicator_policy = static single-step heuristic
uwm_model_based_policy = conservative world-model policy
selected_action_replay_mean_reward = 0.009041181
static_heuristic_replay_mean_reward = 0.007839757
replay_reward_advantage = 0.001201424
learned_rollout_imagined_advantage_over_static = 0.010279633
learned_rollout_imagined_advantage_over_one_step = 0.00951568
synthetic_policy_outcome_learned_advantage_over_static = 0.010907049
synthetic_policy_outcome_claim_boundary = exploratory_only
```

synthetic policy outcome scaffold 只能让 OPE/negative-control 管线先运行，不能替代 observed intervention outcome。下一步仍需要真实或准真实 outcome 评估：

```text
policy_regret
value_improvement
equity_gain
constraint_violation_rate
uncertainty_calibration
evidence_grade
```

只有这一步通过，才可以把 claim 从“架构优势 / known-effect advantage”升级到“真实或准真实 holdout 上优于传统方法”。

## 6. 当前文档和代码中应保持的诚实边界

当前能说：

```text
UWM v0 已有 canonical observation、action-conditioned rollout、simulator trace、evidence-gated planner、traditional baseline 和 negative control。
UWM v0 已补 Graph-MDP replay、offline value model、action-conditioned learned reward+dynamics、conservative policy improvement 和 learned multi-step imagined rollout planner。
```

当前不能说：

```text
UWM v0 已经是完整 model-based RL 系统。
```

更准确的说法应是：

```text
UWM v0 是 model-based RL-ready 的世界模型契约和机制型 simulator/planner scaffold；
当前已补 trajectory dataset、offline value model、action-conditioned reward+dynamics、conservative policy improvement 和 learned multi-step rollout planner v0；
下一阶段必须补 observed/quasi-observed policy outcome、图结构 dynamics、uncertainty calibration 和 OPE/causal gate，
才能把 claim 从 simulator replay advantage 推进到真实或准真实 empirical superiority。
```
