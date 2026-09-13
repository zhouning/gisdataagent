# UWM 空间因果问题与 Estimand Registry 实现记录

日期：2026-07-09

## 1. 本轮实现目标

本轮补上 UWM 从 `do(action)` 到可审计因果问题的中间契约层：

```text
production action catalog
-> spatial causal question registry
-> estimand contract
-> required authoritative governance tables
-> claim boundary
```

这一步不是把当前 simulator 结果包装成真实因果效果，而是把每个当前可搜索治理动作必须回答的因果问题机器化，明确 treatment、outcome、adjustment set、mediator、testable implications、所需权威表和当前可声明上限。

## 2. 新增代码与产物

新增模块：

```text
data_agent/uwm/spatial_causal_question_registry.py
```

新增构建脚本：

```text
scripts/build_uwm_spatial_causal_question_registry.py
```

新增测试：

```text
data_agent/test_uwm_spatial_causal_question_registry.py
```

生成产物：

```text
data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json
data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/snapshot_manifest.json
```

## 3. 当前 registry 摘要

当前 registry 读取现有真实构建产物：

```text
production_action_catalog_2026_07_08
production_governance_data_contract_2026_07_08
causal_policy_evidence_2026_07_06
data_foundation_evidence_gate_2026_07_05
```

产物摘要：

```text
production_action_type_count = 57
currently_bound_action_type_count = 3
currently_bound_feasible_action_count = 1137
active_causal_question_count = 3
authoritative_required_table_count = 5
ready_authoritative_table_count = 0
identified_policy_effect_question_count = 0
underidentified_policy_effect_question_count = 3
```

当前 3 个 active causal questions 对应：

```text
increase_green_infrastructure
traffic_emission_control
add_community_service
```

## 4. 三类动作的因果问题

### 4.1 增绿基础设施

```text
P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)
```

核心含义：在具体行政单元实施增绿动作后，热风险和宜居性是否发生由该动作导致的变化。

当前 primary outcome：

```text
heat_risk
```

核心 adjustment set 包括：

```text
baseline_heat_risk
baseline_green_access
building_density
population_density_proxy
impervious_surface_proxy
topography
neighbor_heat_risk
geographic_similarity_cluster
```

### 4.2 交通排放治理

```text
P(air_pollution_exposure, livability | do(traffic_emission_control), spatial_context)
```

核心含义：交通排放治理动作是否导致空气污染暴露和宜居性变化。

当前 primary outcome：

```text
air_pollution_exposure
```

核心 adjustment set 包括：

```text
baseline_air_pollution_exposure
road_density
traffic_activity_proxy
population_density_proxy
meteorology
topography
neighbor_air_pollution_exposure
```

### 4.3 社区服务补点

```text
P(service_accessibility, livability | do(add_community_service), spatial_context)
```

核心含义：新增社区服务是否导致服务可达性、宜居性和公平性改善。

当前 primary outcome：

```text
service_accessibility
```

核心 adjustment set 包括：

```text
baseline_service_accessibility
population_need
population_density_proxy
road_accessibility
existing_service_capacity_proxy
urban_density
land_availability_proxy
neighbor_service_accessibility
```

## 5. Claim Boundary

当前 registry 明确禁止：

```text
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
production_readiness_claim = false
```

当前最大声明级别：

```text
spatial_causal_question_contract_only
```

这意味着当前 UWM 已经能把现有动作表达成可审计的空间因果问题和 estimand contract，但仍不能声称真实政策效果已经被识别。

## 6. 仍需补齐的真实权威数据

每个 active causal question 都要求以下 5 张权威治理表：

```text
policy_project_history
action_constraint_cost_model
observed_outcome_validation_panel
causal_effect_calibration_panel
human_governance_review_log
```

当前这些表的 ready count 仍为 0，所以所有 policy effect question 均保持：

```text
underidentified_for_observed_policy_effect
```

## 7. 验证

本轮验证结果：

```text
uv run pytest data_agent/test_uwm_spatial_causal_question_registry.py
3 passed

uv run pytest data_agent/test_uwm_spatial_causal_question_registry.py data_agent/test_uwm_causal_policy_evidence.py data_agent/test_uwm_production_action_catalog.py data_agent/test_uwm_production_governance_data_contract.py data_agent/test_uwm_production_governance_planner_binding_gate.py
12 passed

uv run pytest data_agent/test_uwm_*.py
第一次独立 registry 实现后：253 passed
```

## 8. 2026-07-09 追加：接入主证据链

registry 已进一步接入主 evidence/readiness 链路：

```text
spatial_causal_question_registry
-> data_foundation_evidence_gate.evidence_slices.spatial_causal_question_registry
-> world_model_evidence_readiness.architecture_evidence.spatial_causal_questions
```

主 data foundation gate 已重建：

```text
data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json
```

重建输出中的关键状态：

```text
spatial_causal_question_registry_ready = true
spatial_causal_active_question_count = 3
spatial_causal_underidentified_question_count = 3
observed_policy_outcome_superiority_claim = false
```

这表示 UWM 的主证据门现在已经能把 planner 方案背后的因果问题契约作为架构证据暴露出来，同时仍保持真实政策 outcome claim 阻断。

新增验证：

```text
uv run pytest data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_world_model_evidence_readiness.py
3 passed

uv run pytest data_agent/test_uwm_*.py
254 passed
```

## 9. 下一步

## 9. 2026-07-09 追加：接入 API 与前端契约

registry 已进一步暴露到 UWM 宜居性决策 API：

```text
GET /api/uwm/livability-decision
```

新增返回字段：

```text
spatial_causal_question_registry_evidence
world_model_evidence_readiness.architecture_evidence.spatial_causal_questions
```

前端 `LivabilityWorldModelTab` 已新增“空间因果问题契约”面板，展示：

```text
spatial_causal_question_registry_ready
active_causal_question_count
underidentified_policy_effect_question_count
identified_policy_effect_question_count
ready_authoritative_table_count
policy_outcome_claim
```

API/前端新增验证：

```text
uv run pytest data_agent/test_uwm_livability_decision_routes.py data_agent/test_uwm_livability_world_model_frontend_contract.py
6 passed

uv run pytest data_agent/test_uwm_*.py
255 passed

npm run build
passed
```

`npm run build` 仍出现既有 Vite 大 chunk / loaders.gl browser external warning，但 TypeScript 和 Vite build 均成功。

## 10. 下一步

下一步应把该 registry 继续接入：

```text
full_admin_livability_decision_package
-> planner recommendation explanation
-> per-action causal question drilldown
```

同时继续保持硬边界：没有真实 policy history、observed outcome 和 causal calibration 前，planner 可以做 conditional simulation 和 bounded replay comparison，但不能升级为真实政策 outcome superiority。
