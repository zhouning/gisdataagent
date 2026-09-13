# UWM 下一窗口开发衔接说明

日期：2026-07-07；状态刷新：2026-07-08

当前 Git 分支：

```text
feat/v12-extensible-platform
```

## 1. 当前 UWM 主线状态

UWM 城市宜居性分析已经完成传统方法页面和 UWM 世界模型页面的同场景对照实现，并在 UWM 侧进一步接入了真实数据 Graph-MDP 上的 model-based RL、GraphDQN 神经价值网络、full-admin learned world-model rollout、full-admin final decision package 和 full-admin energy-regularized conservative planner 证据。

当前已具备的关键链路：

```text
renderer
-> multisource livability scene
-> data-calibrated simulator
-> spatial spillover kernel
-> graph-MDP planner replay
-> Dyna-Q tabular model-based RL
-> GraphDQN fitted Q/value network
-> full-admin graph planner replay / learned dynamics rollout
-> full-admin livability decision package
-> full-admin feasible action inventory
-> production state/action space assessment
-> full-admin energy-regularized planner
-> energy-regularized planner
-> livability decision package
-> traditional-vs-UWM demo
-> data catalog / evidence gate / Track2 readiness
-> frontend UWM tab
```

## 2. 最新 GraphDQN 证据

核心报告：

```text
data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json
```

关键结果：

```text
algorithm = graph_dqn_fitted_q_model_based_rl
training_sample_count = 3600
real_data_graph_node_count = 36
real_data_graph_edge_count = 96
real_data_available_action_count = 60
spatial_spillover_directional_edge_count = 227
holdout_q_return_mae = 0.000109541
train_mean_return_mae = 0.000741536
graph_dqn_policy_cumulative_reward = 0.001923762
traditional_static_cumulative_reward = -0.003208192
advantage_over_traditional_static = 0.005131954
```

这支持的是：

```text
simulator_grounded_graph_drl_training_advantage_not_observed_policy_outcome
```

不是 observed policy outcome superiority。

## 2.0 最新 Full-Admin Service Accessibility Surface 证据

本窗口已修正旧 bbox 服务样本只能覆盖少量行政单元的问题，新增全量行政单元服务可达性 surface：

```text
data/uwm_public_proxy/chongqing_central/full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json
```

关键结果：

```text
schema = uwm.full_admin_service_accessibility_surface.v1
experiment_scope = full_admin_graph
admin_unit_count = 1017
source_feature_counts.admin_units = 1017
source_feature_counts.poi_points = 1194351
source_feature_counts.roads = 50366
service_missing_admin_count = 0
admin_units_with_accessibility_score = 1017
admin_units_with_road_context = 982
total_service_point_count = 1194284
total_essential_service_count = 78113
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

它支持：

```text
full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets
```

同时新增 full-admin service surface quality audit：

```text
data/uwm_public_proxy/chongqing_central/full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json
```

关键结果：

```text
schema = uwm.full_admin_service_surface_quality_audit.v1
admin_unit_count = 1017
endpoint_count = 2
ready_endpoint_count = 2
essential_service_count_proxy.model_mae = 16.728755
essential_service_count_proxy.best_baseline_mae = 57.472199
estimated_nearest_essential_travel_time_proxy.model_mae = 2.17547
estimated_nearest_essential_travel_time_proxy.best_baseline_mae = 2.192174
target_rotation_negative_controls_passed = true
observed_trip_time_claim = false
observed_policy_outcome_superiority_claim = false
```

它支持：

```text
full_admin_service_surface_proxy_quality_beats_static_and_negative_controls
```

边界必须明确：这是基于本地 Gaode POI 和 OSM roads 的 service capacity / nearest essential service distance / road-speed travel-time proxy，不是观测出行时间、不是权威服务清册，也不是 observed policy outcome。

## 2.1 最新 Full-Admin GraphDQN 证据

本窗口已修正“36-node 训练证据不能代表全量数据”的问题，并新增全量行政图 GraphDQN/value training：

```text
data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json
```

关键结果：

```text
algorithm = graph_dqn_fitted_q_model_based_rl
experiment_scope = full_admin_graph
full_data_guard.passed = true
real_data_graph_node_count = 1017
real_data_graph_edge_count = 7932
admin_boundary_edge_count = 2847
geographic_similarity_edge_count = 5085
geographic_similarity_non_adjacent_edge_count = 4835
real_data_available_action_count = 1137
action_sampling_strategy = stratified_priority
training_sample_count = 1248
holdout_q_return_mae = 0.0000954
train_mean_return_mae = 0.000994236
graph_dqn_policy_cumulative_reward = -0.00644243
traditional_static_cumulative_reward = -0.007255052
advantage_over_traditional_static = 0.000812622
```

这里的动作训练 replay 是从 1137 个真实可行动作中确定性分层抽取，不是全动作 pair 穷举；状态图仍是 1017 个行政单元的 full-admin graph，并且 adjacency 已同时包含行政邻接和地理配置相似边。该证据支持：

```text
full_admin_graph_dqn_value_network_improves_same_scene_static_livability_baseline
```

它仍然不是 observed policy outcome superiority，也不解除服务可达性代理、真实干预日志/OPE/因果验证 gates。

## 2.2 最新 Full-Admin Risk-Calibrated Planner 证据

本窗口同时修正 full-admin planner replay 未接入 PM2.5 uncertainty context 的问题。核心报告仍为：

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json
```

关键结果：

```text
experiment_scope = full_admin_graph
graph_node_count = 1017
graph_edge_count = 7932
available_action_count = 1137
transition_count = 6817
advantage_over_static_single_step = 0.001436437
air_quality_uncertainty_calibration_ready = true
risk_calibrated_planner_replay_ready = true
risk_adjusted_advantage_over_static_single_step = 0.0013756
geographic_similarity_edge_count = 5085
observed_policy_outcome_superiority_claim = false
```

这支持：

```text
full_admin_graph_risk_calibrated_planner_replay_advantage_over_static_heuristic
```

但它使用的是 scene-aligned gridded PM2.5 split-conformal uncertainty，不是站点校准政策 outcome，也不解除 observed policy outcome gate。

## 2.3 最新 Full-Admin Learned World-Model Rollout 证据

本窗口继续把 full-admin planner replay 推进为 action-conditioned learned dynamics head，并用 learned rollout planner 做多步 imagined planning。核心报告为：

```text
data/uwm_public_proxy/chongqing_central/learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json
```

关键结果：

```text
schema = uwm.offline_world_model_rollout_planner_report.v1
experiment_scope = full_admin_graph
full_data_guard.passed = true
source_graph_node_count = 1017
source_graph_edge_count = 7932
source_available_action_count = 1137
transition_count = 6817
holdout_reward_mae = 0.000033499
train_mean_reward_mae = 0.00222562
imagined_advantage_over_static_single_step = 0.00121167
imagined_advantage_over_one_step_policy = 0.000900135
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

该模型使用 compact replay aggregate dynamics 训练，五个 dynamics targets 的 holdout MAE 均优于 train-mean baseline。它支持：

```text
full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines
```

边界必须明确：这是 full-admin simulator replay / imagined rollout 上的 learned world-model evidence，不是观察到的真实政策实施效果，也不解除真实干预日志、OPE、因果验证和 station-calibrated scene AQ holdout gates。

## 2.3.1 最新 Full-Admin Livability Decision Package 证据

本窗口已经把 full-admin planner replay、GraphDQN、learned rollout、geographic similarity kernel、service accessibility surface、service surface quality audit 和 production governance planner binding gate 汇总为一个全量最终决策包：

```text
data/uwm_public_proxy/chongqing_central/full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json
```

关键结果：

```text
schema = uwm.full_admin_livability_decision_package.v1
experiment_scope = full_admin_graph
full_admin_decision_package_ready = true
full_data_guard.passed = true
graph_node_count = 1017
graph_edge_count = 7932
admin_boundary_edge_count = 2847
geographic_similarity_edge_count = 5085
non_adjacent_similarity_edge_count = 4835
available_action_count = 1137
transition_count = 6817
service_surface_admin_unit_count = 1017
service_surface_missing_admin_count = 0
planner_advantage_over_static = 0.001436437
planner_risk_adjusted_advantage_over_static = 0.0013756
graph_dqn_advantage_over_static = 0.000812622
learned_rollout_advantage_over_static = 0.00121167
learned_rollout_advantage_over_one_step_policy = 0.000900135
planner_governance_binding_ready = false
production_governance_binding_gate_ready = true
production_governance_binding_blocking_gate_count = 7
production_governance_binding_passed_gate_count = 2
production_governance_binding_missing_table_count = 5
production_governance_binding_authoritative_row_count = 0
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

它支持：

```text
full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines
```

边界必须明确：这是 1017-node full-admin graph 上的 same-scene simulator replay / learned rollout / value-network 汇总证据，不是真实政策实施后的观测结果；该包已经把生产治理数据闭包作为阻断条件，但当前 `planner_governance_binding_ready = false`，所以不能把 final decision package 写成生产治理 planner 已可用，也不能写成 `observed_policy_outcome_superiority_claim` 或广义 `empirical_superiority_claim`。

## 2.3.1.1 最新 Full-Admin Feasible Action Inventory

为了避免把 `1137` 个动作只作为 env 内部数字，本窗口新增了完整动作清单：

```text
data/uwm_public_proxy/chongqing_central/full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json
```

关键结果：

```text
schema = uwm.full_admin_action_inventory.v1
experiment_scope = full_admin_graph
graph_node_count = 1017
graph_edge_count = 7932
available_action_count = 1137
candidate_action_mask_trace_count = 3051
increase_green_infrastructure = 81
traffic_emission_control = 77
add_community_service = 979
heat_risk_above_threshold = 81
air_pollution_exposure_above_threshold = 77
service_accessibility_below_threshold = 979
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

动作含义和触发规则：

```text
increase_green_infrastructure: heat_risk >= 0.7
traffic_emission_control: air_pollution_exposure >= 0.6
add_community_service: service_accessibility <= 0.5
```

每条动作记录包含 `action_id`、`action_type`、`target_unit_id`、区县/街镇拆分、`mask_reason`、`intensity = 1.0` 和目标单元状态特征。示例：

```text
increase_green_infrastructure-沙坪坝区|覃家岗街道|973
increase_green_infrastructure-沙坪坝区|歌乐山镇|800
add_community_service-涪陵区|蔺市镇|498
```

边界必须明确：这是 full-admin Graph-MDP 的 feasible action inventory，不是历史政策项目库，也不是 observed policy intervention log。下一步如果要做真正 behavior prior，必须接入真实政策/项目时空日志，而不能把这份清单当成历史行为数据。

## 2.3.1b 最新 Production State/Action Space Assessment

本窗口已把“当前 3 类动作的可证伪闭环”和“生产级城市宜居治理状态/动作空间”拆开落盘，避免继续把 v0 action inventory 误认为生产动作全集：

```text
data/uwm_public_proxy/chongqing_central/production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json
```

关键结果：

```text
schema = uwm.production_state_action_space_assessment.v1
experiment_scope = full_admin_graph
graph_node_count = 1017
graph_edge_count = 7932
available_action_count = 1137
implemented_action_type_count = 3
production_action_type_target_count = 57
state_space_blocking_gap_count = 7
action_space_blocking_gap_count = 5
production_readiness_claim = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

该 assessment 明确列出 7 个生产状态层：空间对象、环境暴露、服务可达、人口公平、城市形态活动、治理约束、时序政策 outcome；同时列出 8 个生产动作族：蓝绿热风险治理、空气污染与交通排放、公共服务补短板、交通可达与慢行、城市更新、住房公平、规划管控、韧性应急。当前只覆盖其中 3 个动作族的一部分，剩余动作族和参数化动作、成本约束、政策历史、因果效果校准仍是生产化硬缺口。

## 2.3.1c 最新 Production Action Catalog

本窗口进一步把 assessment 中的 57 类生产目标动作转成机器可读动作契约，并把当前 full-admin action inventory 的 1137 条候选逐条绑定到 3 类已实现动作：

```text
data/uwm_public_proxy/chongqing_central/production_action_catalog_2026_07_08/uwm_production_action_catalog.json
```

关键结果：

```text
schema = uwm.production_action_catalog.v1
experiment_scope = full_admin_graph
production_action_family_count = 8
production_action_type_count = 57
currently_bound_action_type_count = 3
currently_bound_feasible_action_count = 1137
unbound_production_action_type_count = 54
current_candidate_binding_count = 1137
action_catalog_contract_ready = true
planner_production_action_ready = false
constraint_cost_model_ready = false
policy_project_history_ready = false
observed_policy_outcome_panel_ready = false
production_readiness_claim = false
observed_policy_outcome_superiority_claim = false
```

动作契约强制每类生产动作提供 `target_geometry`、`intensity`、`capacity_change`、`budget_cost`、`implementation_time`、`maintenance_cost`、`responsible_department`、`legal_feasibility`、`land_constraint`、`population_served`、`expected_mechanism`、`uncertainty` 和 `evidence_level`。未绑定的 54 类目标动作不能进入 planner search。后续拿到权威数据时，应新增 adapter/evidence slice 并通过 planner binding gates，而不是重写现有 action inventory、simulator 或 planner 接口。

## 2.3.1d 最新 Production Governance Data Contract

本窗口继续把生产动作进入 planner 前必须具备的真实治理数据做成独立契约 artifact：

```text
data/uwm_public_proxy/chongqing_central/production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json
```

关键结果：

```text
schema = uwm.production_governance_data_contract.v1
experiment_scope = full_admin_graph
production_action_type_count = 57
currently_bound_feasible_action_count = 1137
required_governance_table_count = 5
ready_governance_table_count = 0
planning_sample_source_count = 15
planner_governance_binding_ready = false
policy_project_history_ready = false
constraint_cost_model_ready = false
observed_outcome_panel_ready = false
production_readiness_claim = false
observed_policy_outcome_superiority_claim = false
```

5 张生产必需表为：

```text
policy_project_history
action_constraint_cost_model
observed_outcome_validation_panel
causal_effect_calibration_panel
human_governance_review_log
```

这个 artifact 的核心价值是把“局部规划样例不能冒充真实政策历史”机器化。当前 15 个 planning sample 只证明存在规划样例数据源，不证明有项目实施日志、成本约束、审批规则或实施后 outcome。后续接入上海/重庆等权威数据时，应按这 5 张表走 adapter，不应绕过 governance gate 直接把 57 类动作放进生产 planner。

## 2.3.1e 最新 Production Governance Data Adapter Readiness

本窗口继续把治理数据契约落到实际 adapter readiness audit：

```text
data/uwm_public_proxy/chongqing_central/production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json
```

它检查预期权威输入目录：

```text
data/uwm_public_proxy/chongqing_central/authoritative_governance_inputs_2026_07_08
```

关键结果：

```text
schema = uwm.production_governance_data_adapter_readiness.v1
expected_table_count = 5
ready_table_count = 0
missing_source_table_count = 5
accepted_authoritative_row_count = 0
planner_governance_binding_ready = false
observed_policy_outcome_superiority_claim = false
```

adapter 会按 CSV 表名读取 `policy_project_history.csv`、`action_constraint_cost_model.csv`、`observed_outcome_validation_panel.csv`、`causal_effect_calibration_panel.csv`、`human_governance_review_log.csv`，并按契约校验字段、行数和 `synthetic_status` / `quality_flag`。当前 adapter 已进一步加入表感知业务语义校验：`policy_project_history` 会拒绝空 project_id、unsupported action_type、空 target_geometry、start/end 日期倒置、非法 implementation/approval 状态、负预算、空责任部门和空来源文档；constraint/outcome/causal/review 表也会校验非负成本/周期、数值 outcome、datetime、因果诊断枚举和 review decision 枚举。`planning_sample`、`sample`、`synthetic`、`template` 等行会被拒绝，字段齐全但业务值无效的 `real + verified` 行也会被拒绝。当前没有创建任何假表或假行。

## 2.3.1f 最新 Production Governance Input Templates

本窗口进一步生成权威治理输入模板包：

```text
data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/uwm_production_governance_input_templates.json
data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/templates/
```

关键结果：

```text
schema = uwm.production_governance_input_templates.v1
template_count = 5
required_field_count = 54
allowed_action_type_count = 57
adapter_ready_table_count = 0
adapter_missing_source_table_count = 5
template_dir_is_adapter_input_dir = false
authoritative_input_claim = false
```

模板包写出了 5 张空表头 CSV，但模板目录与 adapter 的权威输入目录分离。它的作用是给后续真实权威数据填报和字段映射提供稳定表头，不会改变 adapter readiness，也不能作为政策历史、约束成本或 observed outcome 数据。当前模板包已同步输出 `business_validation_rules`、`allowed_values` 和 57 类 `allowed_action_types`，使填报方能看到必须满足的业务语义约束，而不是只看到 CSV header。

## 2.3.1g 最新 Production Governance Linkage Audit

本窗口继续把 5 张权威治理表之间的 project/action/outcome/causal/review 闭环检查做成独立审计产物：

```text
data/uwm_public_proxy/chongqing_central/production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json
```

关键结果：

```text
schema = uwm.production_governance_linkage_audit.v1
expected_table_count = 5
present_table_count = 0
missing_table_count = 5
linked_project_count = 0
unlinked_project_count = 0
all_required_tables_present = false
governance_linkage_ready = false
planner_governance_binding_ready = false
observed_policy_outcome_superiority_claim = false
```

这个 artifact 不创建任何治理数据。它只在真实 `policy_project_history.csv` 能同时连到 `action_constraint_cost_model.csv`、`observed_outcome_validation_panel.csv`、`causal_effect_calibration_panel.csv` 和 `human_governance_review_log.csv` 时，才会把 `governance_linkage_ready` 置为 true；即使 linkage 审计通过，`planner_governance_binding_ready` 仍需后续 policy outcome gate 才能解除。

## 2.3.1h 最新 Production Governance Planner Binding Gate

本窗口继续把生产治理数据能否进入 planner search 做成统一硬门控：

```text
data/uwm_public_proxy/chongqing_central/production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json
```

关键结果：

```text
schema = uwm.production_governance_planner_binding_gate.v1
required_gate_count = 9
passed_gate_count = 2
blocking_gate_count = 7
missing_table_count = 5
accepted_authoritative_row_count = 0
linked_project_count = 0
authoritative_governance_data_closure_ready = false
planner_governance_binding_ready = false
observed_policy_outcome_superiority_claim = false
```

当前通过的只有 `action_catalog_contract_ready` 和 `governance_data_contract_ready`。其余 7 项分别被权威治理表缺失、每表 0 authoritative rows、跨表 linkage 未闭环、observed outcome panel 缺失、causal effect calibration 缺失和 human review 缺失阻断。这个 artifact 的作用是防止后续 planner 在没有真实治理数据闭包时被误放行；它不是 demo，也不是生产治理 ready claim。

## 2.3.2 最新 Full-Admin Energy-Regularized Planner 证据

本窗口已把 conservative energy-regularized planner 从旧 36-node Graph-MDP 推进到 1017-node full-admin Graph-MDP，并单独纳入 data catalog 和 evidence gate：

```text
data/uwm_public_proxy/chongqing_central/energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json
```

关键结果：

```text
schema = uwm.full_admin_energy_regularized_action_sequence_planner.v1
experiment_scope = full_admin_graph
full_admin_energy_regularized_planner_ready = true
full_data_guard.passed = true
graph_node_count = 1017
graph_edge_count = 7932
available_action_count = 1137
geographic_similarity_edge_count = 5085
non_adjacent_similarity_edge_count = 4835
evaluated_sequence_count = 2256
candidate_action_count = 1137
selected_sequence_reward = -0.006181695
traditional_static_cumulative_reward = -0.007255052
advantage_over_traditional_static = 0.001073357
selected_sequence_energy = 0.319954059
energy_threshold = 0.518719419
planner_exploitation_guard_passed = true
search_value_alignment_ready = true
full_admin_graph_dqn_alignment_ready = true
supported_claim = full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

这里的 behavior prior 是 full-admin feasible-action geometry、行政邻接、相似地理配置边和 action type 形成的 conservative prior，不是历史政策干预日志 prior。它支持：

```text
full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static
```

边界必须明确：这是 full-admin simulator rollout search / search-value alignment evidence，不是真实政策实施后的 observed outcome；不能把它写成历史干预先验、off-policy evaluation 或因果政策效果验证。

## 2.4 最新 Energy-Regularized Planner 证据

本窗口已在 GraphDQN 证据之上继续推进：

```text
real-data Graph-MDP
-> simulator rollout sequence evaluation
-> behavior-prior energy
-> OOD action drift guard
-> GraphDQN search-value alignment audit
-> conservative energy-regularized action-sequence planner
```

核心报告：

```text
data/uwm_public_proxy/chongqing_central/energy_regularized_planner_2026_07_07/uwm_energy_regularized_planner_report.json
```

关键结果：

```text
algorithm = energy_regularized_model_based_action_sequence_planner
real_data_graph_node_count = 36
real_data_graph_edge_count = 96
real_data_available_action_count = 60
spatial_spillover_directional_edge_count = 227
evaluated_sequence_count = 756
selected_sequence_reward = 0.001923762
traditional_static_cumulative_reward = -0.003208192
advantage_over_traditional_static = 0.005131954
selected_sequence_energy = 0.325094162
energy_threshold = 0.580014124
planner_exploitation_guard_passed = true
search_value_alignment_ready = true
supported_claim = energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

这支持的是：

```text
simulator_grounded_energy_regularized_planner_advantage_not_observed_policy_outcome
```

不是 observed policy outcome superiority。

## 3. 必须保持的 Claim Boundary

除非后续加入真实城市政策实施后的 observed outcome 数据，否则必须保持：

```text
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

当前可以说：

```text
同一真实数据基础、同一城市宜居性场景下，
UWM 的 simulator-grounded planner / RL / GraphDQN / learned rollout evidence
在离线反事实评估中优于传统静态基线。
```

当前不能说：

```text
UWM 已经证明真实城市治理政策实施后优于传统方法。
UWM 已经完成真实世界政策 outcome 闭环。
GraphDQN 或 learned rollout 等同于真实政策效果。
```

## 4. 最新验证记录

最近一次 UWM 范围回归：

```text
uv run pytest data_agent/test_uwm_admin_livability_targeting.py data_agent/test_uwm_model_based_rl.py data_agent/test_uwm_geographic_similarity_kernel.py data_agent/test_uwm_full_admin_livability_target_panel.py data_agent/test_uwm_full_admin_graph_planner_replay.py data_agent/test_uwm_full_admin_graph_drl_training.py data_agent/test_uwm_full_admin_learned_world_model_rollout.py data_agent/test_uwm_full_admin_service_accessibility_surface.py data_agent/test_uwm_full_admin_service_surface_quality.py data_agent/test_uwm_full_admin_livability_decision_package.py data_agent/test_uwm_full_admin_action_inventory.py data_agent/test_uwm_production_state_action_space.py data_agent/test_uwm_production_action_catalog.py data_agent/test_uwm_production_governance_data_contract.py data_agent/test_uwm_production_governance_data_adapter.py data_agent/test_uwm_production_governance_input_templates.py data_agent/test_uwm_production_governance_linkage_audit.py data_agent/test_uwm_production_governance_planner_binding_gate.py data_agent/test_uwm_full_admin_energy_regularized_planner.py data_agent/test_uwm_energy_regularized_planner.py data_agent/test_uwm_livability_graph_drl_training.py data_agent/test_uwm_livability_graph_mdp_rl_training.py data_agent/test_uwm_data_calibrated_spatial_spillover_kernel.py data_agent/test_uwm_data_calibrated_mechanism_table.py data_agent/test_uwm_data_calibrated_planner_replay.py data_agent/test_uwm_spatial_spillover_planner_evaluator.py data_agent/test_uwm_livability_decision_package.py data_agent/test_uwm_livability_decision_routes.py data_agent/test_uwm_livability_data_catalog.py data_agent/test_uwm_livability_data_catalog_routes.py data_agent/test_uwm_livability_world_model_frontend_contract.py data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_track2_submission.py data_agent/test_uwm_track2_readiness_report.py data_agent/test_uwm_traditional_vs_world_model_demo.py data_agent/test_uwm_overall_system_superiority.py -q
```

2026-07-08 当前窗口重新验证结果：

```text
99 passed in 28.91s
```

治理绑定/最终包 focused 验证：

```text
uv run pytest data_agent/test_uwm_livability_decision_routes.py data_agent/test_uwm_livability_world_model_frontend_contract.py data_agent/test_uwm_livability_data_catalog.py data_agent/test_uwm_livability_data_catalog_routes.py data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_full_admin_livability_decision_package.py data_agent/test_uwm_production_governance_planner_binding_gate.py -q
```

结果：

```text
24 passed in 3.54s
```

最新 evidence gate 构建：

```text
uv run python scripts/build_uwm_data_foundation_evidence_gate.py
```

关键输出：

```text
full_admin_learned_world_model_rollout_ready = true
full_admin_service_accessibility_surface_ready = true
full_admin_service_surface_admin_unit_count = 1017
full_admin_service_surface_poi_point_count = 1194351
full_admin_service_surface_road_count = 50366
full_admin_service_surface_missing_admin_count = 0
full_admin_service_surface_quality_audit_ready = true
full_admin_service_quality_essential_model_mae = 16.728755
full_admin_service_quality_travel_time_model_mae = 2.17547
geographic_similarity_kernel_ready = true
geographic_similarity_edge_count = 5085
geographic_similarity_non_adjacent_edge_count = 4835
geographic_similarity_rotated_control_passed = true
production_action_catalog_ready = true
production_action_type_count = 57
production_action_catalog_bound_action_count = 1137
production_governance_data_contract_ready = true
production_governance_ready_table_count = 0
production_governance_planning_sample_source_count = 15
production_governance_adapter_ready_table_count = 0
production_governance_adapter_missing_table_count = 5
production_governance_input_template_count = 5
production_governance_input_templates_are_data = false
production_governance_linkage_ready = false
production_governance_linkage_missing_table_count = 5
production_governance_linked_project_count = 0
production_governance_binding_gate_passed_gate_count = 2
production_governance_binding_gate_blocking_gate_count = 7
production_governance_binding_ready = false
full_admin_decision_package_planner_governance_binding_ready = false
full_admin_decision_package_production_governance_binding_blocking_gate_count = 7
full_admin_learned_world_model_rollout_reward_mae = 0.000033499
full_admin_learned_world_model_rollout_advantage = 0.00121167
full_admin_energy_regularized_planner_ready = true
full_admin_energy_regularized_graph_node_count = 1017
full_admin_energy_regularized_available_action_count = 1137
full_admin_energy_regularized_evaluated_sequence_count = 2256
full_admin_energy_regularized_planner_advantage = 0.001073357
full_admin_energy_regularized_exploitation_guard_passed = true
full_admin_energy_regularized_search_value_alignment_ready = true
observed_policy_outcome_superiority_claim = false
```

`/api/uwm/livability-decision` 已同步暴露 `full_admin_decision_package`、`production_governance_binding_evidence`、`planner_governance_binding_ready = false` 和 `active_decision_package_scope = full_admin_graph`。`LivabilityWorldModelTab.tsx` 已新增 “Full-admin 最终决策包” 与 “生产治理绑定门控” 面板，前端直接显示 1017 节点、7932 边、1137 动作、7 个 blocking gates、5 张缺失权威表和 0 authoritative rows，避免只显示 world-model advantage 而隐藏生产治理阻断。

前端构建：

```text
npm --prefix frontend run build
```

结果：通过。存在既有 loaders.gl `spawn` browser external 和 chunk size warning。

Docker：

```text
docker-compose build app
docker-compose up -d app
curl -I http://localhost:8000/
```

结果：

```text
HTTP/1.1 200 OK
```

容器内 payload 验证：

```text
graph_drl_ready = True
graph_drl_algorithm = graph_dqn_fitted_q_model_based_rl
graph_drl_training_sample_count = 3600
catalog_graph_drl_completed = True
catalog_graph_value_network = True
planning_mode = trained_graph_dqn_value_network_over_real_data_graph_mdp
observed_policy_claim = False
```

当前访问路径：

```text
http://localhost:8000
```

## 5. 重要新增/更新文档

```text
docs/reports/uwm_world_model_rl_mpc_relationship_2026-07-07.md
docs/reports/uwm_mbdpo_paper_inspiration_2026-07-07.md
docs/reports/uwm_next_window_handoff_2026-07-07.md
```

其中 MBDPO 论文启发文档明确了下一阶段 planner 升级方向：

```text
Energy-Regularized / Diffusion-Style Model-Based Planner
```

## 6. 下一步建议

下一窗口继续 UWM 主线时，建议不要再重复做数据目录或静态页面，而应推进：

```text
1. search-value alignment test
2. OOD action drift / planner exploitation 检查
3. behavior prior / implicit energy model
4. KL trust-region 或 conservative planner constraint
5. UWM diffusion-style action-sequence planner 的最小可行实现
6. 与 traditional baseline、graph search、Dyna-Q、GraphDQN 在同一数据场景下比较
```

其中 1-4 的 36-node 最小可行版本已经通过 `energy_regularized_planner_2026_07_07` 落地，full-admin 版本已经通过 `energy_regularized_planner_full_admin_graph_2026_07_08` 落地；full-admin learned dynamics rollout 已经通过 `learned_world_model_rollout_full_admin_graph_2026_07_08` 落地；full-admin final decision package 已经通过 `full_admin_livability_decision_package_2026_07_08` 落地。下一步不应重复做同一层证据包装，应推进：

```text
1. 扩大 action-sequence horizon / top-k search，检查 reward-energy trade-off 曲线
2. 引入显式历史规划/政策文本 prior，替换当前 feasible-action geometry prior
3. 训练真正的 diffusion-style discrete action-sequence generator
4. 做跨城市或跨时段 holdout，验证 conservative planner 是否稳定优于传统方法
5. 收集真实政策干预后的 observed outcome 数据，才可能提升 claim ceiling
6. 将当前 full-admin service travel-time / capacity proxy 升级为观测出行时间或权威服务清册校准版本
```

核心目标：

```text
从 GraphDQN / full-admin learned dynamics / full-admin decision package evidence
推进到带真实 policy prior、跨时空 holdout 和 observed outcome gate 的 model-based action-sequence planner，
但继续保持 observed policy outcome claim boundary。
```
