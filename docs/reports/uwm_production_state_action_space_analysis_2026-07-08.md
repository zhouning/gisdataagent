# UWM 城市宜居性状态空间与动作空间生产化分析

日期：2026-07-08

## 结论

按生产实用目标看，当前 UWM 的状态空间和动作空间还只是“可证伪闭环”，不是完整城市治理生产空间。尤其动作空间只有 3 类，明显不足以覆盖真实城市宜居治理。

## 1. 业务理论决定状态空间不能只是 5 个指标

UWM 的城市宜居性理论基础不是“静态宜居分数”，而是：

```text
环境暴露 + 机会可达 + 人口脆弱性 + 空间公平 + 城市形态 + 交通活动 + 治理约束
在干预动作和外部情景下的动态状态变化
```

所以生产级状态空间至少应包含这些层：

1. 空间对象层：行政单元、社区、街区、建筑、道路、POI/AOI、绿地水体、土地利用图斑、规划管控单元。当前 UWM 已有 1017 个乡镇/街道行政单元、2847 条行政邻接边、5085 条地理配置相似边；缺口是还没有形成真正多尺度对象图，建筑/道路/地块/服务设施还没有全部成为可推演节点。

2. 环境暴露层：热风险、PM2.5/NO2、噪声、道路暴露、极端天气、蓝绿冷源。当前已有 OpenAQ、TAP、CHAP、NOAA、Open-Meteo、GEE/CAMS/Paper6 UHI 等证据；缺口是缺全城长期站点校准、街区级热环境、交通噪声、污染源和真实政策 outcome。

3. 服务可达层：医疗、教育、养老、托育、文化、体育、公园、商业、社区服务、公共交通。当前已有 Gaode POI 1,194,351 点、OSM roads 50,366 条，并做了 1017 单元 service accessibility surface；缺口是服务容量、服务等级、营业时间、真实网络出行时间、公交可达、服务需求人群仍不足。

4. 人口与公平层：人口密度、年龄结构、低收入、老人儿童、健康脆弱性、就业机会、住房压力。当前已有区县人口统计、GHSL、人口下推 proxy、联通通勤 2120 rows；缺口是乡镇/社区级权威人口、脆弱人群细分、收入/住房/健康数据、真实 OD 几何。

5. 城市形态与活动层：建筑密度、高度/楼层、街道连通性、土地利用混合度、开发强度、活动热度。当前已有建筑 107,452、AOI 26,292、道路、CLCD、DEM、百度搜索指数等；缺口是完整楼栋属性、建设年代、地块容积率、更新潜力、街道尺度慢行环境。

6. 治理约束层：法定规划、土地权属、项目储备、预算、建设周期、审批规则、保护区、红线、政策可行性。当前只有局部规划样例和璧山/村规数据。这是生产级 UWM 最大缺口之一。

7. 动态状态层：当前状态、历史状态、动作历史、预算消耗、项目进度、政策版本、外部情景。当前 UWM 更多是 same-scene simulator replay，不是真实城市多年状态转移。生产必须变成时序状态空间，而不是单时点状态图。

## 2. 当前已实现状态空间

当前 full-admin UWM 实际状态空间可以概括为：

```text
1017 个行政单元节点
+ 7932 条图边
  = 2847 行政邻接边 + 5085 地理配置相似边
+ 每个节点的 heat_risk / air_pollution_exposure / service_accessibility / equity / livability
+ service surface、geographic similarity、PM2.5 uncertainty、mechanism table
+ simulator / planner / GraphDQN / learned rollout 的 replay 状态
```

这比传统静态评价强，因为它已经有图结构、动作、模拟器、规划器、风险惩罚和证据门控。但它还不是生产级完整状态空间，因为很多真实治理变量没有进入状态。

## 3. 当前动作空间为什么不够

当前动作空间只有：

```text
increase_green_infrastructure
traffic_emission_control
add_community_service
```

它们对应热风险、空气暴露、服务可达三个核心机制，所以适合做第一版可验证闭环。但真实城市治理动作远不止这些。

生产级动作空间至少应扩展成下面几组：

1. 蓝绿基础设施与热风险治理：新增绿地、街道树冠、口袋公园、蓝绿廊道、透水铺装、遮阴设施、冷屋顶、建筑降温改造、海绵城市设施。

2. 空气污染与交通治理：低排放区、货运限行、公交优先、慢行优先、停车调控、道路降速、信号优化、拥堵治理、机动车减排、充电设施、污染源治理。

3. 公共服务补短板：新增/扩容医疗、教育、养老、托育、文体、公园、社区食堂、便民商业、15 分钟生活圈设施。这类动作必须有容量、服务半径、服务对象、建设周期和运营成本。

4. 交通可达与慢行改善：新增公交站点、调整公交线路、提高班次、步行连通、过街设施、自行车道、无障碍改造、道路微循环。

5. 城市更新与建成环境改造：老旧小区改造、街区微更新、建筑节能改造、公共空间提升、街道断面优化、混合用地调整、低效用地再开发。

6. 住房与空间公平政策：保障性住房、租赁住房、社区照护、弱势群体服务、适老化改造、儿童友好设施。

7. 规划与管控动作：用地调整、容积率控制、开发时序、保护区管控、城市更新单元划定、项目准入/暂缓/替代方案。

8. 韧性与应急动作：避暑中心、应急供水、极端天气响应、洪涝韧性设施、风险人群预警和服务调度。

## 4. 生产级动作不能只是 action_type

## 4.1 2026-07-08 新增：Production Action Catalog

当前已新增机器可读 artifact：

```text
data/uwm_public_proxy/chongqing_central/production_action_catalog_2026_07_08/uwm_production_action_catalog.json
```

它的作用不是扩大战果表述，而是把“未来不推倒重来”的动作空间接口固定下来：

```text
schema = uwm.production_action_catalog.v1
production_action_family_count = 8
production_action_type_count = 57
currently_bound_action_type_count = 3
currently_bound_feasible_action_count = 1137
unbound_production_action_type_count = 54
current_candidate_binding_count = 1137
```

每类生产动作都必须满足统一参数契约：

```text
target_geometry
intensity
capacity_change
budget_cost
implementation_time
maintenance_cost
responsible_department
legal_feasibility
land_constraint
population_served
expected_mechanism
uncertainty
evidence_level
```

每类动作进入 planner 前必须通过证据层：

```text
state_variable_support
constraint_cost_model
historical_policy_project_log
observed_outcome_panel
causal_effect_calibration
human_governance_review
```

当前 1137 条候选绑定来自已有 full-admin action inventory，而不是抽样：

```text
increase_green_infrastructure = 81
traffic_emission_control = 77
add_community_service = 979
```

其余 54 类生产目标动作保留为 `production_target_unbound`，不能进入 planner search。这样后续拿到真实权威数据时，应新增对应 adapter、constraint/cost evidence、policy history 和 outcome panel，再把动作从 `production_target_unbound` 提升到可搜索动作；不需要推倒现有 renderer-simulator-planner-evidence gate 架构。

边界必须保持：

```text
production_readiness_claim = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
claim_boundary.max_claim_level = contract_and_current_bounded_action_binding
```

## 4.2 2026-07-08 新增：Production Governance Data Contract

在动作契约之后，当前又新增生产治理数据契约：

```text
data/uwm_public_proxy/chongqing_central/production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json
```

这个 artifact 把“生产动作能否进入治理 planner”所需真实数据拆成 5 张表：

```text
policy_project_history
action_constraint_cost_model
observed_outcome_validation_panel
causal_effect_calibration_panel
human_governance_review_log
```

当前状态是：

```text
production_action_type_count = 57
currently_bound_feasible_action_count = 1137
required_governance_table_count = 5
ready_governance_table_count = 0
planning_sample_source_count = 15
planner_governance_binding_ready = false
```

这意味着 UWM 架构已经预留真实政策项目、约束成本、观测结果、因果校准和人工治理审核的接入位，但当前还没有权威表数据可以支撑生产治理 claim。局部规划样例只能作为规划资料范围证据，不能替代真实 intervention log，也不能替代 observed outcome panel。

## 4.3 2026-07-08 新增：Production Governance Data Adapter Readiness

治理数据契约之后，当前已新增实际 adapter readiness audit：

```text
data/uwm_public_proxy/chongqing_central/production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json
```

它不再只是描述需要什么表，而是实际检查预期输入目录中是否存在 5 张权威 CSV 表，并执行字段、行级权威性和业务语义校验。当前结果：

```text
expected_table_count = 5
ready_table_count = 0
missing_source_table_count = 5
accepted_authoritative_row_count = 0
planner_governance_binding_ready = false
```

这一步的意义是把未来权威治理数据接入变成可运行 adapter，而不是重新设计 UWM。只要后续把真实 `policy_project_history.csv`、`action_constraint_cost_model.csv`、`observed_outcome_validation_panel.csv`、`causal_effect_calibration_panel.csv` 和 `human_governance_review_log.csv` 放入约定目录，adapter 会按现有契约校验；未通过前，production planner claim 会继续被 gate 阻断。当前 adapter 会拒绝 `planning_sample` / `synthetic` / `template` 行，也会拒绝字段齐全但业务值无效的 `real + verified` 行，例如 unsupported action_type、日期倒置、负预算、非法审批状态、非法因果诊断状态或空项目/文档 ID。

## 4.4 2026-07-08 新增：Production Governance Input Templates

当前已进一步生成权威治理输入模板包：

```text
data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/uwm_production_governance_input_templates.json
data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/templates/
```

模板包包含 5 张空表头 CSV，共 54 个必需字段，并保留字段映射模板。当前结果：

```text
template_count = 5
required_field_count = 54
allowed_action_type_count = 57
adapter_ready_table_count = 0
adapter_missing_source_table_count = 5
template_dir_is_adapter_input_dir = false
authoritative_input_claim = false
```

这一步确保后续真实权威数据可以按固定表头和字段映射接入；同时模板目录与 adapter 输入目录分离，避免空模板被误认为真实政策项目、约束成本或 observed outcome 数据。模板包当前还输出 57 类 `allowed_action_types`、字段 `allowed_values` 和各表 `business_validation_rules`，使生产数据接入方明确知道哪些业务值会被 adapter 拒绝。

## 4.5 2026-07-08 新增：Production Governance Linkage Audit

模板和 adapter 之后，当前已进一步新增跨表闭环审计产物：

```text
data/uwm_public_proxy/chongqing_central/production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json
```

它检查真实政策项目是否能同时连到动作约束成本、观测 outcome、因果效果校准和人工治理审核。当前结果：

```text
expected_table_count = 5
present_table_count = 0
missing_table_count = 5
linked_project_count = 0
unlinked_project_count = 0
all_required_tables_present = false
governance_linkage_ready = false
planner_governance_binding_ready = false
```

这一步的意义是把“有表”继续推进到“表之间能闭环”。未来拿到真实权威数据后，只有项目历史、约束成本、observed outcome、causal effect 和 human review 能以 `project_id`、`action_type`、`target_geometry` 等键联通，生产 planner 才有可能进入下一道治理绑定 gate。当前 5 张表仍全部缺失，所以它只是审计能力，不是生产治理数据。

## 4.6 2026-07-08 新增：Production Governance Planner Binding Gate

跨表审计之后，当前已新增生产治理 planner binding 硬门控：

```text
data/uwm_public_proxy/chongqing_central/production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json
```

它不直接读取散乱 raw data，而是消费 `production_action_catalog`、`production_governance_data_contract`、`production_governance_data_adapter_readiness` 和 `production_governance_linkage_audit` 四个已审计 artifact。当前结果：

```text
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

这一步把“不能继续堆 demo”落实成代码门控：当前只有动作契约和治理数据契约通过，真实权威表、每表非零权威行、跨表闭环、observed outcome、causal effect 和 human review 都没有通过，所以生产治理 planner binding 被硬阻断。后续拿到权威数据后，也必须先通过这 9 项，再进入更高层的 observed policy outcome gate。

该 gate 已被 full-admin final decision package 消费，而不是停留在孤立审计报告：

```text
data/uwm_public_proxy/chongqing_central/full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json

source_schemas.production_governance_planner_binding_gate = uwm.production_governance_planner_binding_gate.v1
production_governance_binding_evidence.production_governance_binding_gate_ready = true
production_governance_binding_evidence.planner_governance_binding_ready = false
production_governance_binding_evidence.production_planner_binding_blocked = true
production_governance_binding_evidence.blocking_gate_count = 7
planner_governance_binding_ready = false
remaining_gates includes production_governance_planner_binding_gate_required
```

因此当前 final decision package 可以继续作为 same-scene simulator-grounded 决策证据包，但不能升级为生产治理执行包。换句话说，`1017` 个状态节点和 `1137` 个 feasible action candidates 已经进入世界模型闭环；生产项目绑定、预算约束、真实 outcome 与人工审核没有进入闭环，且已经被 gate 阻断。

真实动作应该是参数化对象：

```text
action = {
  action_type,
  target_geometry,
  intensity,
  capacity_change,
  budget_cost,
  implementation_time,
  maintenance_cost,
  responsible_department,
  legal_feasibility,
  land_constraint,
  population_served,
  expected_mechanism,
  uncertainty,
  evidence_level
}
```

例如 `add_community_service` 在当前 UWM 里只是一个抽象动作；生产中必须拆成“新增社区卫生服务站”“扩容养老服务点”“新增托育点”“新增口袋公园”“调整服务运营时间”等不同动作，因为它们的成本、周期、服务对象和效果完全不同。

## 5. 复杂度会急剧上升

当前是：

```text
1017 nodes × 3 action types = 3051 raw candidates
mask 后 1137 feasible actions
```

如果扩展到生产级，例如：

```text
1017 nodes × 30 action types × 3 intensity levels ≈ 91,530 raw candidates
```

再考虑多目标、多期、多部门预算和动作依赖，horizon=3 就会进入亿级到十亿级组合空间。生产级 UWM 不能靠平铺枚举，必须用：

- 分层规划：城市级预算分配 -> 区域级策略 -> 项目级动作；
- action mask：法规、土地、预算、容量、风险、部门权限；
- 候选生成器：先生成合理项目池；
- learned dynamics + causal effect model；
- constrained RL / MPC / multi-objective planner；
- human-in-the-loop 审核。

## 6. 生产化目标

当前 UWM 的状态空间和动作空间可以证明“世界模型闭环正在形成”，但不能说已经达到真实生产治理。

生产级目标应该是：

```text
多尺度城市状态
+ 参数化治理动作库
+ 真实项目/政策历史
+ 预算与约束
+ 时序观测 outcome
+ 因果效果校准
+ 分层规划器
+ 证据门控
```

下一步不能只是继续优化这 3 类动作，而应该正式建设：

```text
UWM Production State Ontology
UWM Production Action Ontology
UWM Policy/Project History Schema
UWM Constraint & Cost Model
UWM Governance Linkage Audit
UWM Governance Planner Binding Gate
UWM Causal Effect Calibration Layer
```

当前代码已经把 `UWM Governance Planner Binding Gate` 接入 final decision package 和 evidence gate。后续真正要推进的是把 5 张权威治理表填入并通过 adapter/linkage/binding gate，而不是继续扩大没有权威来源的动作候选数量。

否则 UWM 会停留在“比传统静态评价强的研究闭环”，但走不到真实城市治理生产系统。
