# UWM 下一窗口开发衔接说明

日期：2026-07-07

当前 Git 分支：

```text
feat/v12-extensible-platform
```

## 1. 当前 UWM 主线状态

UWM 城市宜居性分析已经完成传统方法页面和 UWM 世界模型页面的同场景对照实现，并在 UWM 侧进一步接入了真实数据 Graph-MDP 上的 model-based RL 与 GraphDQN 神经价值网络证据。

当前已具备的关键链路：

```text
renderer
-> multisource livability scene
-> data-calibrated simulator
-> spatial spillover kernel
-> graph-MDP planner replay
-> Dyna-Q tabular model-based RL
-> GraphDQN fitted Q/value network
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

## 3. 必须保持的 Claim Boundary

除非后续加入真实城市政策实施后的 observed outcome 数据，否则必须保持：

```text
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

当前可以说：

```text
同一真实数据基础、同一城市宜居性场景下，
UWM 的 simulator-grounded planner / RL / GraphDQN evidence
在离线反事实评估中优于传统静态基线。
```

当前不能说：

```text
UWM 已经证明真实城市治理政策实施后优于传统方法。
UWM 已经完成真实世界政策 outcome 闭环。
GraphDQN 等同于真实政策效果。
```

## 4. 最新验证记录

最近一次通过的测试和构建：

```text
uv run pytest data_agent/test_uwm_livability_graph_drl_training.py data_agent/test_uwm_livability_decision_package.py data_agent/test_uwm_livability_decision_routes.py data_agent/test_uwm_livability_data_catalog.py data_agent/test_uwm_livability_data_catalog_routes.py data_agent/test_uwm_livability_world_model_frontend_contract.py data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_traditional_vs_world_model_demo.py data_agent/test_uwm_track2_submission.py data_agent/test_uwm_track2_readiness_report.py -q
```

结果：

```text
24 passed
```

宽 UWM 回归：

```text
uv run pytest data_agent/test_uwm_livability_graph_drl_training.py data_agent/test_uwm_livability_graph_mdp_rl_training.py data_agent/test_uwm_data_calibrated_spatial_spillover_kernel.py data_agent/test_uwm_data_calibrated_mechanism_table.py data_agent/test_uwm_data_calibrated_planner_replay.py data_agent/test_uwm_spatial_spillover_planner_evaluator.py data_agent/test_uwm_livability_decision_package.py data_agent/test_uwm_livability_decision_routes.py data_agent/test_uwm_livability_data_catalog.py data_agent/test_uwm_livability_data_catalog_routes.py data_agent/test_uwm_livability_world_model_frontend_contract.py data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_track2_submission.py data_agent/test_uwm_track2_readiness_report.py data_agent/test_uwm_traditional_vs_world_model_demo.py data_agent/test_uwm_overall_system_superiority.py -q
```

结果：

```text
41 passed
```

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

核心目标：

```text
从 GraphDQN evidence
推进到 energy-regularized model-based action-sequence planner，
但继续保持 observed policy outcome claim boundary。
```

