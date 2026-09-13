# UWM Simulator and Evaluation Gates

日期：2026-07-04；更新：2026-07-05

## 1. 目的

本文件记录 UWM 当前实现中“模拟器”和“相对传统方法证明”的工程边界。核心原则：

```text
UWM 不是静态宜居性指数。
UWM 必须消费 canonical observation，基于 action sequence 做 rollout，
并通过 evidence gate 限制可声明结论。
```

## 2. 当前实现

### 2.1 Simulator

模块：

```text
data_agent.uwm.simulator
```

入口：

```text
simulate_livability_rollout(observation, action_sequence, scenario)
```

输入：

- `UwmCanonicalObservation.v1`
- action sequence
- scenario
- 可由 `uwm.scene_state.v1` 派生的 scene-conditioned scenario controls

输出：

- `UwmRolloutTrace.v1`

当前后端：

```text
mechanistic_urban_livability_v0
```

该后端是透明机制型 simulator，不是经验预测模型。它用于证明世界模型结构：

- 干预行动会改变未来状态；
- 图邻接关系会产生溢出；
- 输出必须包含 simulator trace；
- 输出必须带 uncertainty interval；
- 输出必须继承 observation 的 claim boundary。

### 2.2 支持的行动机制

当前 v0 覆盖四类城市宜居性干预：

- `increase_green_infrastructure`：降低热风险和污染暴露，轻度改善服务与公平；
- `cool_roof` / `building_cooling_retrofit`：降低热风险；
- `traffic_emission_control` / `low_emission_zone`：降低空气污染暴露；
- `add_community_service` / `service_accessibility_improvement`：提升服务可达性和公平。

这些机制只用于受控 known-effect benchmark。参数需要后续由真实观测、文献或 Paper6/SCCA 证据门控校准。

### 2.3 Scene State Controls

模块：

```text
data_agent.uwm.scene_state
```

入口：

```text
build_scene_state_from_proxy_artifacts(...)
derive_simulator_scenario_from_scene_state(scene_state, scenario_id)
```

当前 `uwm.scene_state.v1` 将 renderer 输出的 GHSL-admin observation 与 Open-Meteo historical observation 融合为 simulator controls：

```text
heat_stress_multiplier
air_pollution_stress_multiplier
vulnerability_multiplier
```

这一步的理论作用是把 UWM 从“动作条件化机制表”推进到“状态条件化世界模型”：同一行动在不同热暴露、污染暴露和人口脆弱性场景下，rollout 响应不同。

## 3. Evaluation Gate

模块：

```text
data_agent.uwm.evaluation
```

入口：

```text
evaluate_dynamic_advantage_over_static_baseline(...)
```

对照方法：

```text
static_weighted_indicator_overlay
```

该传统 baseline 没有 action-conditioned transition，也没有 rollout trace。因此它在干预评估任务上的 `action_response_delta = 0`。

UWM evaluation 当前检查三项：

1. `dynamic_action_response`
   - UWM rollout 对干预产生正向宜居性增量；
   - 传统 static baseline 对同一行动没有动态响应。

2. `negative_control_stability`
   - no-op action 不应产生宜居性改善；
   - 用于防止 simulator 把所有 action 都机械地判为有益。

3. `trace_completeness`
   - rollout 必须包含 observation validation、action effect application、aggregate rollout delta。

## 3.1 Planner Gate

模块：

```text
data_agent.uwm.planner
```

入口：

```text
build_evidence_gated_plan(rollout_traces, planning_goal, constraints)
```

输入只能是：

```text
UwmRolloutTrace.v1
```

这条约束是 UWM 区别于传统规划打分器的核心：planner 不允许直接消费 raw action、静态指标表或主观权重表来形成推荐。候选行动必须先经过 simulator rollout，planner 才能评估。

当前 planner gate 包括：

- `validate_rollout_traces`：检查每个候选是否是有效 `UwmRolloutTrace.v1`；
- `apply_hard_constraints`：执行证据等级、公平、不确定性和最低收益约束；
- `rank_admissible_actions`：只对通过 gate 的候选排序；
- `rejected_actions`：所有失败候选必须记录拒绝原因；
- `human_review_required = True`：规划建议不能自动升级为政策执行命令。

当前 v0 打分函数：

```text
score = livability_delta + 0.50 * equity_delta - 0.10 * uncertainty_width
```

这个函数的目的不是声称最优政策偏好已经确定，而是把“宜居性收益、公平收益和不确定性惩罚”显式纳入 planner contract。后续可用真实 holdout、SCCA 或专家约束校准权重。

## 3.2 Planner Advantage Evaluation

模块：

```text
data_agent.uwm.evaluation
```

入口：

```text
evaluate_planner_advantage_over_static_heuristic(...)
```

该评估比较：

- 传统静态启发式行动：`decision_basis = static_indicator_priority`
- UWM planner 行动：`decision_basis = simulator_rollout_trace`

输出核心指标：

```text
known_effect_regret_reduction =
    UWM planner selected action livability_delta
    - static heuristic selected action livability_delta
```

若该值大于 0，并且 planner 通过 evidence gate，则当前可声明：

```text
known_effect_planner_advantage_over_static_heuristic
```

## 4. 当前可以声明的结论

如果三项 gate 通过，并且证据等级不是 `not_for_claim`，当前可以声明：

```text
known_effect_dynamic_advantage_over_static_baseline
```

若 observation 含 synthetic / exploratory 数据，只能声明：

```text
exploratory_known_effect_dynamic_advantage_only
```

当前测试 fixture 的可复现输出摘要：

```text
traditional baseline action_response_delta = 0.0
UWM action_response_delta = 0.033446
negative_control_delta = 0.0
supported_claim = known_effect_dynamic_advantage_over_static_baseline
empirical_superiority_claim = False
```

当前真实代理 scene-conditioned 输出摘要：

```text
scene_state = data/uwm_public_proxy/chongqing_central/uwm_scene_state_livability_2024_07.json
scenario = data/uwm_public_proxy/chongqing_central/uwm_simulator_scenario_livability_2024_07.json
scene_conditioned_rollout = data/uwm_public_proxy/chongqing_central/uwm_rollout_scene_conditioned_livability_2024_07.json
evaluation = data/uwm_public_proxy/chongqing_central/uwm_scene_conditioned_dynamic_advantage_2024_07.json
heat_stress_multiplier = 1.0857
air_pollution_stress_multiplier = 1.136285
vulnerability_multiplier = 1.088987
normal_air_delta = -0.08
scene_air_delta = -0.0909028
normal_livability_delta = 0.02225
scene_livability_delta = 0.02517592075
supported_claim = known_effect_dynamic_advantage_over_static_baseline
empirical_superiority_claim = False
```

解释：

```text
同一 traffic_emission_control 动作在 Open-Meteo/GHSL scene state 下产生更强的空气暴露改善和宜居性增量；
传统 static_weighted_indicator_overlay 的 action_response_delta 仍为 0；
该结果证明状态条件化 + 动作条件化链条成立，但仍不是 observed holdout empirical superiority。
```

当前 planner fixture 的可复现输出摘要：

```text
static heuristic action = static-heat-hotspot-action
UWM planner action = uwm-equity-service-action
known_effect_regret_reduction = 0.01
supported_claim = known_effect_planner_advantage_over_static_heuristic
empirical_superiority_claim = False
```

## 5. 当前不能声明的结论

当前实现强制：

```text
empirical_superiority_claim = False
```

原因：

- 还没有真实干预后观测结果的 holdout 对比；
- 还没有跨城市外部验证；
- 还没有 SCCA 或其它因果证据门控校准机制参数；
- planner 目前只通过 known-effect regret reduction，尚未通过真实政策结果 regret holdout。

## 5.1 Model-Based RL 边界修正

当前 v0 具备 world-model runtime 的基本契约：

```text
canonical observation
-> action-conditioned rollout
-> simulator trace
-> evidence-gated planner
-> known-effect benchmark
```

但它还不能称为完整的 model-based reinforcement learning。原因是当前 simulator 仍是透明机制表和 scene-conditioned scalar 组合，planner 仍是 evidence gate + candidate ranking，还没有：

- trajectory replay / offline RL dataset；
- learned latent state encoder；
- learned action-conditioned dynamics model；
- reward / value model；
- MPC / CEM / MCTS / policy improvement；
- observed policy outcome holdout 或 off-policy evaluation。

因此当前准确定位应是：

```text
model-based-RL-ready UWM scaffold
```

而不是：

```text
complete model-based RL Urban World Model
```

详细修正说明见：

```text
docs/reports/uwm_livability_theory_and_model_based_rl_gap_2026-07-05.md
```

## 6. 下一步

1. 用 Paper6 EPA Green Book benchmark 构造公开 known-effect / semi-synthetic 验证集。
2. 对重庆中心城区补齐 ERA5、空气污染代理、人口脆弱性和服务设施数据。
3. 将 simulator 参数从当前 scene-conditioned scalars 继续迁移为 data-calibrated mechanism table。
4. 将 planner 的 hard constraints 接入领域理论：热健康风险、公平底线、预算约束和服务可达性底线。
5. 建立 holdout 评估：预测干预方向、幅度区间、空间异质性、negative control 和 policy regret。
