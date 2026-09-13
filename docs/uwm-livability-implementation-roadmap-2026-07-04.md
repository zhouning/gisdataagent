# UWM-Livability Implementation Roadmap for Urban Cup 2026 Track 2

日期：2026-07-04；状态刷新：2026-07-08

## 1. 文档目的

这份文档记录 UWM-Livability 的实施路线图。它不是代码计划，也不是 UI 设计稿，而是后续实现前必须遵守的路线约束。

核心目标：

```text
以实现一个 Urban World Model 为目标，
用 UWM 解决城市宜居性分析问题，
并在全过程中形成 Urban Cup 2026 Track 2 可提交材料。
```

必须吸取 TWM 早期教训：不能先做一个能展示的 demo，再补理论、补数据边界和补验证。UWM 的路线必须先立领域理论、数据契约、世界模型契约和证据门控，再逐步实现交互入口、runtime 和提交材料。

### 1.1 2026-07-08 状态刷新

本次刷新基于 `docs/` 下 UWM 命名 Markdown 文档、UWM 报告子目录、上海权威数据需求包、UWM superpowers specs/plans，以及当前本地 evidence artifacts。结论是：UWM-Livability 已经从路线设计推进到可复现的世界模型闭环，但 claim ceiling 仍必须严格受证据门控约束。

当前总体状态：

- 已完成从 data foundation、MMFE state input、canonical renderer、传统 baseline、data-calibrated simulator、spatial spillover、planner、model-based RL、GraphDQN、full-admin learned dynamics rollout、full-admin final decision package、full-admin energy-regularized conservative planner、production governance planner binding gate 到 frontend/API decision package 的闭环；
- 当前最强系统级结论是 `bounded_final_system_superiority_claim = true`，不是 observed policy outcome superiority；
- 当前证据等级上限是 `bounded_support`，原因是 planner 与 RL 证据来自同一真实数据 Graph-MDP、校准机制表、空间外溢核和 holdout endpoint，而不是真实政策实施后的观测结果；
- 不能声明 `observed_policy_outcome_superiority_claim`，不能声明广义 `empirical_superiority_claim`，不能把 synthetic/public_proxy 场景包装成权威城市政策效果。

当前最强可支持 claims：

- `uwm_bounded_final_endpoint_and_planner_advantage_over_traditional_methods`；
- `uwm_final_livability_endpoint_suite_beats_traditional_baselines`；
- `uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk`；
- `full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines`；
- `full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static`；
- `full_admin_graph_dqn_value_network_improves_same_scene_static_livability_baseline`；
- `full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines`；
- `graph_dqn_value_network_improves_same_scene_static_livability_baseline`；
- `trained_model_based_q_agent_improves_same_scene_static_livability_baseline`；
- `energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static`；
- `full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets`；
- `full_admin_service_surface_proxy_quality_beats_static_and_negative_controls`；
- `data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients`；
- `data_calibrated_planner_replay_advantage_over_static_heuristic`；
- `full_admin_graph_risk_calibrated_planner_replay_advantage_over_static_heuristic`；
- `geographic_similarity_configuration_kernel_ready`；
- `risk_calibrated_planner_replay_advantage_over_static_heuristic`；
- `spatial_spillover_planner_replay_advantage_over_static_heuristic`；
- `scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines`；
- `scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline`；
- `historical_station_aligned_tap_pm25_beats_static_station_baselines`；
- `observed_temporal_state_prediction_advantage_over_static_baseline_suite`；
- `tap_external_temporal_dynamics_advantage_without_spatial_claim`。

当前关键证据摘要：

- full-admin service accessibility surface 已从旧 bbox 服务样本推进到全量本地 POI/道路 surface：1017 个行政单元、1,194,351 个本地 Gaode POI 点、50,366 条 OSM roads，`service_missing_admin_count = 0`，`admin_units_with_accessibility_score = 1017`；该 surface 支持全量状态覆盖，但最近服务 travel time 仍是 OSM-speed network proxy，不是观测出行时间或权威服务清册；
- full-admin service surface quality audit 已基于 1017 个行政单元做 leave-one-admin-out 和 target-rotation negative control；`essential_service_count_proxy` 的 model MAE 为 `16.728755`，优于 best baseline `57.472199`，`estimated_nearest_essential_travel_time_proxy` 的 model MAE 为 `2.17547`，优于 best baseline `2.192174`，两个 target-rotation negative controls 均通过；该证据说明代理 surface 不是随意填满，但仍不是观测出行时间或政策结果；
- geographic similarity kernel 已补齐“相似地理配置”链路：基于 1017 个 full-admin livability rows 的服务、道路、暴露和宜居需求配置生成 5085 条 kNN 相似边，其中 4835 条不是行政边界邻接；rotated-target negative control 通过；该 kernel 不使用经纬度作为相似特征，也不声称政策 outcome；
- full-admin GraphDQN 已从 36-node 候选单元推进到 `full_admin_graph`：1017 个 graph nodes、7932 条 graph edges（2847 条行政邻接边 + 5085 条相似配置边）、1137 个可行动作；训练采用从全动作空间确定性分层抽取的 1248 个 simulator-grounded Q-return samples，保持全量状态图输入，不把动作训练样本子集冒充数据子集；holdout `q_return_mae = 0.0000954`，优于 train-mean baseline 的 `0.000994236`，同全量图同场景相对传统静态启发式优势为 `0.000812622`；
- full-admin planner replay 已接入 scene-aligned gridded PM2.5 split-conformal uncertainty context 和 geographic similarity kernel，`risk_calibrated_planner_replay_ready = true`，同一 PM2.5 uncertainty penalty 下相对 static single-step 的 risk-adjusted advantage 为 `0.0013756`；这仍是 gridded state uncertainty，不是 station-calibrated policy outcome；
- full-admin learned world-model rollout 已基于 1017-node、7932-edge、1137-action、6817-transition compact planner replay 训练 action-conditioned dynamics head；holdout `reward_mae = 0.000033499`，优于 train-mean reward baseline 的 `0.00222562`，五个 dynamics targets 均优于 train-mean baseline；learned rollout planner 的 imagined advantage 相对 static single-step 为 `0.00121167`，相对 one-step policy 为 `0.000900135`；这仍是 simulator replay / imagined rollout 证据，不是 observed policy outcome；
- full-admin livability decision package 已作为 1017 节点最终汇总包落地：`full_data_guard.passed = true`，`graph_node_count = 1017`，`graph_edge_count = 7932`，`available_action_count = 1137`，`transition_count = 6817`，`geographic_similarity_edge_count = 5085`；它同时汇总 full-admin planner replay、GraphDQN、learned rollout、geographic similarity kernel、service accessibility surface、service quality audit 和 production governance planner binding gate，支持 `full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines`；其中 planner advantage 为 `0.001436437`，risk-adjusted planner advantage 为 `0.0013756`，GraphDQN advantage 为 `0.000812622`，learned rollout advantage 为 `0.00121167`；包内 `production_governance_binding_evidence.planner_governance_binding_ready = false`，`blocking_gate_count = 7`，`missing_table_count = 5`，`accepted_authoritative_row_count = 0`，所以生产治理 planner binding 被明确阻断；这仍是 same-scene simulator replay / learned rollout 证据，不是 observed policy outcome；
- full-admin action inventory 已把 `1137` 个可行动作从 Graph-MDP 中显式落盘到 `full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json`：其中 `increase_green_infrastructure = 81`，触发规则为 `heat_risk >= 0.7`；`traffic_emission_control = 77`，触发规则为 `air_pollution_exposure >= 0.6`；`add_community_service = 979`，触发规则为 `service_accessibility <= 0.5`。每条动作记录包含 action_id、目标行政单元、触发原因和目标单元状态特征；这是一份 feasible action inventory，不是历史政策项目库；
- production state/action space assessment 已把“当前可运行闭环”和“生产级城市宜居治理空间”显式分开：产物为 `production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json`，读取 data foundation evidence gate、full-admin action inventory 和 full-admin livability decision package，确认当前已实现 1017 个节点、7932 条边、1137 个可行动作、3 个动作类型，同时给出 7 个状态层阻塞缺口、5 个未实现生产动作族和 57 个生产目标动作类型。该产物只支持 gap-analysis，不支持 production readiness claim、observed policy outcome superiority 或 empirical superiority；
- full-admin energy-regularized planner 已从旧 36-node 图推进到 1017-node full-admin Graph-MDP：`graph_node_count = 1017`，`graph_edge_count = 7932`，`available_action_count = 1137`，`geographic_similarity_edge_count = 5085`，`non_adjacent_similarity_edge_count = 4835`；在 horizon=2、top-k=16 下评估 `2256` 条 action sequences，selected sequence reward 为 `-0.006181695`，传统静态累计 reward 为 `-0.007255052`，优势为 `0.001073357`；selected sequence energy 为 `0.319954059`，低于 energy threshold `0.518719419`，GraphDQN search-value alignment 和 exploitation guard 均通过；该 prior 是 feasible-action geometry / boundary / similarity-edge prior，不是历史政策干预日志 prior，也不是 observed policy outcome；
- Graph-MDP 基于真实数据场景构建：36 个 graph nodes、96 条 graph edges、60 个可行动作、227 条 directional spillover edges；
- GraphDQN 在 3,600 个 simulator-grounded training samples 上训练，holdout 514 个样本，`q_return_mae = 0.000109541`，优于 train-mean baseline 的 `0.000741536`，同图同场景相对传统静态启发式优势为 `0.005131954`；
- decision package 已就绪，endpoint-aligned score 相对传统静态启发式提升 `0.0007457`，risk-adjusted reward 提升 `0.012777213`，planner 使 13 个单元受益而静态启发式为 6 个单元；
- energy-regularized planner 已完成 horizon=2、top-k search、756 个 action sequences 评估，selected sequence 的 raw reward 为 `0.001923762`，相对传统静态启发式优势为 `0.005131954`，并显式记录 behavior energy 与 OOD drift；
- evidence gate 当前写明 `bounded_final_system_superiority_claim = true`，并已纳入 full-admin livability decision package slice、full-admin energy-regularized planner slice 和 production governance binding 字段；同时仍保持 `production_governance_binding_ready = false`、`observed_policy_outcome_superiority_claim = false`，`empirical_superiority_claim = false`。

剩余 gates：

- `observed_policy_outcome_required`；
- `scene_aligned_station_calibrated_air_quality_holdout_required`；
- `synthetic_proxy_boundary_must_remain_visible`。

## 2. 路线选择

可选路线有三种。

### 2.1 快速 demo 路线

特点：

- 先做页面；
- 先出地图；
- 先算静态宜居性指数；
- 后补模型解释。

判断：

```text
不推荐。
```

原因：这条路线最容易把 UWM 做成传统宜居性 dashboard，无法证明是 world model。

### 2.2 契约化 UWM runtime 路线

特点：

- 先定义数据契约；
- 先定义 renderer / simulator / planner；
- 先做 baseline 和证据门控；
- 再做 UWM tab 和可视化；
- 赛道材料同步沉淀。

判断：

```text
推荐。
```

原因：这是避免糊弄、避免 facade、避免静态指数冒充 UWM 的稳妥路线。

### 2.3 平台化大系统路线

特点：

- 一开始做完整平台；
- 同时做数据湖、模型注册、前端、仿真、报告和提交系统。

判断：

```text
暂不推荐。
```

原因：范围太大，容易失控。UWM v0 应先围绕 Track 2 和城市宜居性形成可证伪闭环。

## 3. 城市宜居性分析的领域理论体系

UWM 只是技术实现。城市宜居性分析本身必须有领域理论支撑，否则模型输出没有城市科学意义。

### 3.1 宜居性的基本定义

在 UWM-Livability 中，宜居性不应定义为单个综合分，而应定义为：

```text
特定人群在特定城市空间中，
获得健康、安全、便利、舒适、机会和公平生活条件的能力状态。
```

这意味着宜居性至少包含三层：

1. **环境暴露层**
   - 热风险；
   - 空气污染；
   - 噪声或交通暴露；
   - 绿地、水体、冷岛资源；
   - 极端天气压力。

2. **机会可达层**
   - 教育；
   - 医疗；
   - 公园绿地；
   - 商业生活服务；
   - 公共交通；
   - 慢行可达性；
   - 就业和活动机会。

3. **公平与脆弱性层**
   - 老年人、儿童、低收入或高暴露群体；
   - 低宜居区域是否被持续边缘化；
   - 干预收益是否被已有高资源区吸收；
   - 平均改善是否掩盖空间不公平。

因此，UWM 的宜居性不是：

```text
指标加权叠加后的静态排名
```

而是：

```text
环境风险、机会可达、人口脆弱性和治理干预共同作用下的动态城市状态。
```

### 3.2 理论来源 1: 人本需求与能力方法

宜居性首先是以人为中心的城市状态。它关心居民是否具备实现基本生活功能的能力：

- 是否能健康生活；
- 是否能方便获得服务；
- 是否能避免过高环境风险；
- 是否能公平分享城市资源；
- 是否能在极端气候或治理变化中保持基本生活质量。

对 UWM 的约束：

- 不能只看土地或设施；
- 必须引入人口和脆弱性；
- 必须评价不同群体的受益差异；
- 不能只优化全市平均值。

### 3.3 理论来源 2: 环境健康与暴露-风险-脆弱性框架

城市宜居性与健康风险密切相关。热暴露、空气污染、交通暴露等不是普通指标，而是影响健康和生活质量的风险机制。

可表达为：

```text
risk = exposure × sensitivity × adaptive_capacity
```

对 UWM 的约束：

- `exposure`：LST、PM2.5、NO2、道路活动、热岛；
- `sensitivity`：老人、儿童、人口密度、健康脆弱性代理；
- `adaptive_capacity`：绿地、医疗、公服、避暑空间、交通可达性。

UWM 需要模拟干预如何改变 exposure、sensitivity 或 adaptive capacity。

### 3.4 理论来源 3: 可达性与时间地理学

宜居性不是设施数量，而是居民能否在合理时间和成本内获得服务。

可达性至少包括：

- 距离可达；
- 网络时间可达；
- 步行/公交可达；
- 服务容量可达；
- 不同人群的可达差异。

对 UWM 的约束：

- POI 不能只做密度；
- 应构建服务可达性；
- 有条件时应引入道路网络和通勤 OD；
- 公共服务补点动作必须通过可达性变化来评价。

### 3.5 理论来源 4: 空间公平与环境正义

宜居性必须回答“谁受益、谁受损、谁长期暴露于风险”。

空间公平至少包括：

- 低宜居区域是否集中于特定空间；
- 高风险暴露是否叠加低服务可达；
- 干预是否优先改善弱势区域；
- 总体均值提升是否伴随差距扩大。

对 UWM 的约束：

- 输出必须有 equity delta；
- planner 不能只最大化平均宜居性；
- 必须报告低宜居区域和脆弱群体收益；
- 必须警惕绿色绅士化或资源再集中。

### 3.6 理论来源 5: 城市复杂系统与韧性

城市宜居性是多系统耦合结果：

```text
城市形态
-> 活动与交通
-> 环境暴露
-> 健康与舒适
-> 服务可达
-> 空间公平
```

韧性要求模型考虑外部冲击：

- 极端高温；
- 静稳天气；
- 人口增长；
- 交通需求变化；
- 公共服务压力；
- 气候适应情景。

对 UWM 的约束：

- 不能只做当前状态评价；
- 必须支持情景压力测试；
- 必须支持干预前后对比；
- 必须输出不确定性和证据边界。

### 3.7 UWM 中的宜居性价值函数

宜居性价值函数不应是单一 opaque score，而应是可分解的多目标函数：

```text
V_livability =
  health_comfort
  + service_accessibility
  + green_blue_benefit
  + mobility_convenience
  + vulnerable_group_gain
  + low_livability_area_gain
  - heat_exposure
  - air_pollution_exposure
  - implementation_cost
  - uncertainty_penalty
  - evidence_penalty
```

并保留各分项，不能只展示总分。

## 4. 总体实施原则

1. **先领域理论，再技术实现。**
   - UWM 服务城市宜居性理论，不替代理论。

2. **先契约，再代码。**
   - 没有 `UwmCanonicalObservation.v1`、`UwmRolloutTrace.v1`、`UwmPlanPackage.v1`，不进入 runtime 声明。

3. **先数据 manifest，再融合。**
   - 没有来源、时间、CRS、质量、合成边界的数据不能进 UWM。

4. **先传统 baseline，再 UWM。**
   - 必须证明 UWM 相对传统静态宜居性评价的增量。

5. **先 trace，再 planner。**
   - planner 必须消费 simulator trace，不能自己编效果。

6. **先证据边界，再强结论。**
   - 反事实结论必须经过 evidence gate。

7. **从第一天记录 Track 2 材料。**
   - 研究日志、AI 协作、数据说明、实验命令必须持续沉淀。

## 5. Roadmap

### Phase 0: 设计门禁

目标：先把不能糊弄的边界立住。

当前状态（2026-07-08）：已完成。设计 spec、renderer/simulator/planner 契约、claim boundary、synthetic/public_proxy/restricted_expected 标记规则、城市宜居性理论框架和 Track 2 研究日志均已沉淀。后续不再把 Phase 0 当作待做项，而是作为所有新增实现的门禁。

交付物：

- `UWM-Livability Track 2 Design Spec`；
- `mmfe.uwm_state_input.v1` 草案；
- `UwmCanonicalObservation.v1` 草案；
- `UwmRolloutTrace.v1` 草案；
- `UwmPlanPackage.v1` 草案；
- claim boundary 规则；
- synthetic / public_proxy / restricted_expected 标记规则；
- 城市宜居性理论框架说明。

通过标准：

- 明确 UWM 与传统宜居性指数的区别；
- 明确 renderer / simulator / planner 输入输出；
- 明确城市宜居性的领域理论；
- 明确哪些数据能做事实结论，哪些只能 exploratory。

### Phase 1: 数据基础盘点与 manifest

目标：把已有数据、公开数据、受限预期数据、合成数据统一管理。

当前状态（2026-07-08）：当前重庆 public/proxy/local 场景的数据 foundation 已完成，可支撑现有 bounded_support 结论；上海权威数据需求包已经形成需求说明、inventory、traceability matrix 和 evidence pack。未完成的是客户/城市权威生产数据落地，尤其是状态历史、干预历史、政策结果验证历史、交通/人口/空气质量权威时序。

交付物：

- `docs/reports/uwm_data_foundation_manifest.csv`；
- `docs/reports/uwm_data_foundation_manifest.md`；
- 重庆中心城区数据资产清单；
- Paper6 / Paper58 / EPA benchmark 资产清单；
- 合成数据占位策略。

数据层级：

- 已有真实数据：建筑、道路、POI/AOI、DEM、CLCD、人口、通勤线索；
- 公开补充：OSM、ERA5、Sentinel/Landsat/MODIS、WorldPop/GHSL、CAMS/MAIAC/OpenAQ；
- 受限预期：未来客户数据库中的权威空气质量、人口、交通、规划数据；
- 合成/半合成：流程验证、压力测试、已知效应 benchmark。

通过标准：

- 每个数据集都有来源、时间、空间范围、CRS、许可证、质量和 claim boundary；
- 没有 manifest 的数据不能进 UWM。

### Phase 2: MMFE 接入与完善

目标：让 MMFE 成为 UWM 数据基础主通道，而不是手写临时 join。

当前状态（2026-07-08）：部分完成。`mmfe.uwm_state_input`、data catalog projection、shadow catalog、agent data assets 与质量边界已经进入当前闭环；但完整 managed MMFE/lakehouse 注册、生产级 curated state tables、versioned outcome history 仍未完成。后续新增模型不得绕开 MMFE/catalog 边界直接读取散乱 raw data。

交付物：

- `mmfe.uwm_state_input.v1` builder；
- 城市 POI/AOI 语义分类规则；
- 栅格-矢量-点-OD 融合流程；
- MMFE quality sidecar；
- 城市图构建产物。

需要完善 MMFE：

- 城市服务设施本体：教育、医疗、公园、交通、商业、养老；
- 时空对齐：年份、月份、日尺度数据对齐；
- 图结构输出：空间邻接、道路邻接、功能相似、通勤联系；
- 合成数据标记：字段级和图层级 synthetic flags；
- 质量诊断：CRS、时间错配、空间覆盖、字段匹配置信度。

通过标准：

- UWM 不直接消费散乱 raw data，而消费 MMFE state-input；
- 每次融合都有 trace 和质量报告。

### Phase 3: 传统宜居性 baseline

目标：建立传统方法对照，证明 UWM 不是换名指标体系。

当前状态（2026-07-08）：已完成并被后续 planner/RL/decision package 反复复用。传统静态 baseline 不再只是地图展示，而是作为同数据、同场景、同约束下的对照组，用于量化 UWM 的 endpoint、risk-adjusted、spillover 和 action-sequence 增量。

交付物：

- 静态宜居性指数 baseline；
- 指标权重方案；
- 敏感性分析；
- baseline 地图；
- baseline 局限性报告。

候选指标：

- 热环境；
- 空气污染或污染代理；
- 绿地可达性；
- 公共服务可达性；
- 交通可达性；
- 建筑密度；
- 人口密度；
- 脆弱性。

通过标准：

- baseline 能跑通；
- UWM 后续明确在哪些方面超过 baseline：动态、反事实、证据门控、公平性、不确定性。

### Phase 4: Renderer 实现

目标：实现城市观测算子。

当前状态（2026-07-08）：已完成 2D/2.5D 重庆 admin-unit scene 的 canonical observation、空间单元、图结构、renderer trace 和质量边界。当前不应声称 full 3D city world model；3D/BIM/point-cloud agent 是后续增强，不是当前系统级 claim 的必要前提。

交付物：

- `UwmCanonicalObservation.v1`；
- spatial unit builder：250m/500m grid + 街区/建筑补充层；
- object-field feature extraction；
- graph builder；
- renderer trace；
- 数据质量和合成边界输出。

通过标准：

- 输出能被 simulator 消费；
- 不是地图，不是 dashboard；
- 每个状态字段可追溯。

### Phase 5: Simulator v0

目标：实现动作条件城市动力学。v0 不要求一开始很强，但契约必须正确。

当前状态（2026-07-08）：已超过 v0。系统已经接入 data-calibrated mechanism table、scene uncertainty、spatial spillover kernel、risk-calibrated replay 和 endpoint-aligned evaluation。当前缺口不是“有没有 simulator”，而是缺少真实政策实施后的 observed outcome dynamics 与因果验证数据。

交付物：

- state encoder；
- action encoder；
- scenario encoder；
- baseline dynamics backend；
- AlphaEarth-enhanced state prior；
- `UwmRolloutTrace.v1`。

动作集合：

- 当前 full-admin Graph-MDP 实际启用三类 action candidates：`increase_green_infrastructure`、`traffic_emission_control`、`add_community_service`；
- 当前 full-admin action inventory 中共有 `1137` 个动作：81 个增绿动作、77 个交通减排动作、979 个公共服务补点动作；
- 当前动作均是单行政单元、`intensity = 1.0` 的 feasible action candidate；
- 建筑强度调整、慢行/公交可达性改善、极端高温/静稳天气压力测试目前属于路线图方向或 scenario pressure，不应声称已经进入 1137 个实际 action candidates。

输出头：

- `heat_risk_delta`；
- `air_pollution_exposure_delta`；
- `service_accessibility_delta`；
- `equity_delta`；
- `livability_delta`；
- `uncertainty_interval`；
- `evidence_grade`。

通过标准：

- 必须有 action-conditioned rollout；
- 必须有 simulator trace；
- 没有 trace 的结果不能给 planner 用。

### Phase 6: Evidence Gate

目标：防止把相关性和模拟结果包装成强因果结论。

当前状态（2026-07-08）：已完成并成为当前 claim ceiling 的核心依据。`uwm_data_foundation_evidence_gate.json` 已给出 `bounded_final_system_superiority_claim = true`，同时明确 `observed_policy_outcome_superiority_claim = false` 和 `empirical_superiority_claim = false`。所有新增强结论必须先通过这个 gate。

交付物：

- Paper6 SCCA 接入方案；
- 热风险案例 evidence gate；
- UWM-Air EPA benchmark 接入；
- placebo / residual Moran / spatial bootstrap 记录；
- evidence grade 表。
- machine-readable world-model evidence readiness claim ladder。

证据等级：

- `core_support`；
- `bounded_support`；
- `fragile`；
- `exploratory_only`；
- `not_for_claim`。

通过标准：

- 每个干预结论都有证据等级；
- 重庆空气污染若只用代理或合成校准，必须降级；
- EPA 只作为公开验证，不冒充重庆观测。
- Track 2 readiness 必须明确 allowed claims、forbidden claims 和 remaining gates。

### Phase 7: Planner v0

目标：让 UWM 能推荐干预方案，但 planner 必须消费 simulator trace。

当前状态（2026-07-08）：已超过 v0。当前已包含 graph search、data-calibrated planner replay、risk-calibrated replay、spatial spillover planner evaluator、decision package、Dyna-Q model-based RL、GraphDQN value network、full-admin action-conditioned learned dynamics rollout、full-admin final decision package，以及 full-admin energy-regularized conservative action-sequence planner。未完成的是基于真实历史干预日志训练的 behavior/policy prior、diffusion-style/discrete action sequence generator、更长 horizon 与跨时间/跨城市 holdout。

交付物：

- action candidate generator；
- hard constraint mask；
- simulator-coupled rollout ranking；
- multi-objective scoring；
- `UwmPlanPackage.v1`。

目标函数包括：

- 平均宜居性改善；
- 低宜居区域改善；
- 脆弱人口受益；
- 热风险下降；
- 污染暴露下降；
- 服务可达性提升；
- 成本；
- 不确定性惩罚；
- 证据惩罚。

通过标准：

- planner 不能绕过 simulator；
- 硬约束必须是 mask，不是扣分项；
- 推荐和拒绝都要有理由。

### Phase 8: GIS Data Agent 独立 UWM Tab

目标：在 GIS Data Agent 中新增独立 UWM 交互入口，而不是挤在 TWM 或旧 WorldModel tab 里。

当前状态（2026-07-08）：已完成基础独立入口和 world-model workflow console。当前实现以 `LivabilityWorldModelTab.tsx`、`DataPanel` 的 `uwm_livability` tab、`/api/uwm/livability-decision`、`/api/uwm/livability-data-catalog` 和 `/api/uwm/livability-data-catalog/sync` 为主，已展示 renderer/simulator/planner、decision package、GraphDQN/Dyna-Q 训练证据、空间外溢、风险校正收益和数据治理边界。`/api/uwm/livability-decision` 现在同时返回 36-node same-scene 对照包和 1017-node `full_admin_decision_package`，并把 `production_governance_binding_evidence`、`planner_governance_binding_ready = false` 暴露到顶层；前端已新增“Full-admin 最终决策包”和“生产治理绑定门控”面板，显示 1017 节点、7932 边、1137 动作、7 个 blocking gates、5 张缺失权威表和 0 authoritative rows。后续重点是强化可复现实验入口、证据矩阵导出和生产数据接入状态，而不是再做静态 dashboard。

当前前端入口：

```text
frontend/src/components/datapanel/LivabilityWorldModelTab.tsx
DataPanel tab key: uwm_livability
Tab label: 城市宜居性分析（UWM）
```

UWM tab 的职责不是普通 dashboard，而是 UWM workflow console：

1. **Data Foundation**
   - 展示数据 manifest；
   - 区分真实、公开代理、受限预期、合成；
   - 展示 MMFE 融合质量。

2. **Livability Theory and Baseline**
   - 展示传统宜居性 baseline；
   - 展示领域理论维度；
   - 展示 baseline 局限性。

3. **Renderer**
   - 展示 canonical observation；
   - 展示空间单元、图结构、质量 flags；
   - 展示 renderer trace。

4. **Simulator**
   - 选择动作和情景；
   - 运行 rollout；
   - 展示 `UwmRolloutTrace.v1`；
   - 展示不确定性和证据边界。

5. **Planner**
   - 生成候选干预；
   - 运行 simulator-coupled ranking；
   - 展示推荐和拒绝理由；
   - 展示 equity delta 和 evidence grade。

6. **Track 2 Package**
   - 展示研究日志；
   - 展示数据说明；
   - 展示 AI 协作记录；
   - 展示可复现实验命令；
   - 导出提交材料清单。

当前已接入和后续应补齐的 API 形态：

```text
GET  /api/uwm/livability-decision
GET  /api/uwm/livability-data-catalog
POST /api/uwm/livability-data-catalog/sync
GET  /api/uwm/manifest
POST /api/uwm/mmfe/build-state-input
GET  /api/uwm/observation
POST /api/uwm/baseline/run
POST /api/uwm/renderer/build
POST /api/uwm/simulator/rollout
POST /api/uwm/evidence/evaluate
POST /api/uwm/planner/rank
GET  /api/uwm/track2/package
```

通过标准：

- UWM tab 是独立入口；
- 能看到数据、理论、baseline、renderer、simulator、planner、evidence、Track 2 材料；
- 不允许只做地图展示；
- 不允许隐藏数据边界和证据等级。

### Phase 9: Track 2 研究材料闭环

目标：从实现第一天开始为赛道提交留痕。

当前状态（2026-07-08）：部分完成。研究日志、readiness、demo understanding、传统 vs world model、data foundation、handoff、理论/边界文档和可复现实验产物已经形成；但最终 submission package 仍未关闭，尤其要补齐 observed policy outcome gate、station-calibrated scene air-quality holdout、权威数据授权与可审计的实验脚本/图表包。

交付物：

- `docs/reports/uwm_track2_research_log.md`；
- 数据说明；
- 可复现实验命令；
- AI 协作记录；
- 研究报告草稿；
- 图表和可视化；
- failure memory；
- claim boundary appendix。

通过标准：

- 每个结论能追到数据、代码、实验、证据等级；
- 每次 AI 参与都有记录；
- 最终不是“系统介绍”，而是一份城市科学研究成果。

## 6. 里程碑

### M0: 契约冻结

状态（2026-07-08）：已完成。

当前完成：

- UWM 数据契约；
- 状态契约；
- trace 契约；
- planner 契约；
- 城市宜居性理论框架。

### M1: 数据基础 v0

状态（2026-07-08）：已完成当前 public/proxy/local 场景；生产权威数据仍待接入。

当前完成：

- 现有重庆数据入 manifest；
- Paper6 / Paper58 / EPA 资产入 manifest；
- 公开数据候选入 manifest；
- 合成边界入 manifest。

### M2: MMFE-UWM State Input

状态（2026-07-08）：部分完成。state-input、catalog projection 和质量边界已服务当前闭环；完整 managed MMFE/lakehouse 与 versioned history 仍待完成。

当前完成：

- MMFE 产出第一版 UWM state-input；
- 城市图结构初版；
- 数据质量 sidecar。

### M3: 传统 baseline

状态（2026-07-08）：已完成，并已成为 UWM planner/RL/evidence gate 的固定对照组。

完成：

- 静态宜居性评价；
- 敏感性分析；
- baseline 局限性说明。

### M4: Renderer + Simulator v0

状态（2026-07-08）：已完成并推进到 data-calibrated simulator、spatial spillover、risk/uncertainty 和 endpoint-aligned replay。

完成：

- `UwmCanonicalObservation.v1`；
- `UwmRolloutTrace.v1`；
- action-conditioned rollout。

### M5: Evidence-Gated Planner

状态（2026-07-08）：已完成并超过 v0，已接入 graph search、decision package、Dyna-Q、GraphDQN、full-admin learned dynamics rollout、full-admin final decision package 和 full-admin energy-regularized planner。

完成：

- planner 消费 simulator trace；
- 推荐方案、拒绝理由和证据等级；
- hard constraint mask。

当前边界：

- learned rollout planner 已支持 `learned_world_model_rollout_improves_imagined_static_and_one_step_baselines`；
- full-admin learned world-model rollout 已支持 `full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines`，其训练输入为全量行政图 compact replay 的 6817 条 simulator transitions；
- livability decision package 已达到 `bounded_support`，支持 `uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk`；
- full-admin livability decision package 已达到 `bounded_support`，支持 `full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines`，其证据范围是 1017-node full-admin graph 的 planner replay、GraphDQN 和 learned rollout 汇总；该包已消费 `production_governance_planner_binding_gate`，并暴露 `production_governance_binding_evidence`，当前 `planner_governance_binding_ready = false`、`blocking_gate_count = 7`，因此生产治理 planner binding 被阻断；
- full-admin energy-regularized planner 已达到 `bounded_support`，支持 `full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static`，其证据范围是 1017-node full-admin graph 的 conservative simulator rollout search；
- production action catalog 已生成 `data/uwm_public_proxy/chongqing_central/production_action_catalog_2026_07_08/uwm_production_action_catalog.json`，把 57 类生产目标动作转为版本化动作契约，并把当前 1137 条 full-admin feasible action candidates 绑定到其中 3 类已实现动作；
- production governance data contract 已生成 `data/uwm_public_proxy/chongqing_central/production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json`，定义真实政策/项目历史、约束成本、观测结果、因果校准和人工治理审核 5 张生产必需表；当前 ready table count 为 0，明确阻止把局部规划样例伪装为政策历史；
- production governance data adapter readiness 已生成 `data/uwm_public_proxy/chongqing_central/production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json`，实际审计预期权威输入目录；当前 5 张表均未发现，accepted authoritative rows 为 0，planner governance binding 继续为 false；adapter 已加入表感知业务语义校验，会拒绝字段齐全但 action_type、日期、预算、审批状态、因果诊断或 review decision 等业务值无效的伪权威行；
- production governance input templates 已生成 `data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/uwm_production_governance_input_templates.json` 和 5 张空表头 CSV；模板目录与 adapter 权威输入目录分离，模板本身不改变 ready table count，也不构成权威输入；模板包已输出 57 类 `allowed_action_types`、字段 `allowed_values` 和各表 `business_validation_rules`，使后续权威数据接入遵守同一套机器可读语义约束；
- production governance linkage audit 已生成 `data/uwm_public_proxy/chongqing_central/production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json`，检查 5 张治理表能否按 project/action/outcome/causal/review 闭环联通；当前 present table count 为 0、missing table count 为 5、linked project count 为 0，planner governance binding 继续为 false；
- production governance planner binding gate 已生成 `data/uwm_public_proxy/chongqing_central/production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json`，把 action catalog、governance contract、adapter readiness 和 linkage audit 汇总成 9 项硬门控；当前只通过 action catalog contract 和 governance data contract 2 项，其余 7 项因权威表缺失、0 authoritative rows、0 linked projects 被阻断，planner governance binding 仍为 false；
- GraphDQN、Dyna-Q 和 energy-regularized planner 均只能声明 same-scene / simulator-grounded / not-policy-outcome 的 bounded advantage；
- 不能声明 observed policy outcome superiority。

### M5.5: World-Model Evidence Readiness

状态（2026-07-08）：已完成当前 bounded final system evidence gate，但不能越过 policy outcome gate。

完成：

- data foundation evidence gate 已接入 Track 2 readiness；
- 已生成 `docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_matrix.json`；
- 当前 evidence gate 支持 `bounded_final_system_superiority_claim = true`；
- 当前 system-level claim 应表述为 `uwm_bounded_final_endpoint_and_planner_advantage_over_traditional_methods`；
- allowed claims 已从 OpenAQ/TAP/learned rollout 扩展到 endpoint suite、decision package、data-calibrated simulator、spatial spillover planner、Dyna-Q、GraphDQN、full-admin service accessibility surface、full-admin service surface quality audit、full-admin learned world-model rollout、full-admin livability decision package、full-admin energy-regularized planner、production action catalog、production governance contract/adapter/templates/linkage audit/planner binding gate 和 36-node energy-regularized planner；
- production action catalog 的 claim ceiling 是 `contract_and_current_bounded_action_binding`，只能证明“动作契约完整且当前 3 类动作绑定了全量 Graph-MDP 候选”，不能证明生产项目可实施或政策结果优越；
- production governance data contract 的 claim ceiling 是 `governance_data_contract_gap_only`，只能证明“真实治理数据接入契约和缺口已机器化”，不能证明已经有真实政策/项目历史、约束成本或观测 outcome；
- production governance data adapter readiness 的 claim ceiling 是 `adapter_readiness_audit_only`，只能证明“权威治理表 adapter 当前是否可读取并通过字段/行级权威性检查”，不能替代权威数据本身；
- production governance input templates 的 claim ceiling 是 `input_template_contract_only`，只能证明“权威表头模板和字段映射契约存在”，不能证明存在权威输入；
- production governance linkage audit 的 claim ceiling 是 `governance_linkage_audit_only`，只能证明“跨表闭环审计器已经能检查项目、动作约束、观测结果、因果校准和人工审核是否联通”，不能证明当前已有联通的权威治理数据；
- production governance planner binding gate 的 claim ceiling 是 `planner_governance_binding_gate_only`，只能证明“planner search 前的生产治理数据闭包硬门控已经机器化并正在阻断缺失权威数据的路径”，不能证明生产 planner 已可用或政策 outcome 优越；该 gate 已进入 full-admin final decision package 和 data foundation evidence gate，作为最终推荐包的生产治理阻断条件；
- forbidden claims 仍包括 observed policy outcome superiority、TAP spatial attribution、overall empirical policy superiority。

剩余：

- station-calibrated observed air-quality holdout；
- observed policy outcome validation data；
- causal policy effect validation；
- authoritative production city data and versioned intervention/outcome history；
- synthetic/public_proxy boundary must remain visible。

### M6: 独立 UWM Tab

状态（2026-07-08）：已完成基础独立 UWM 宜居性入口；后续应增强实验复现、证据矩阵导出和生产数据接入状态。

完成：

- GIS Data Agent 独立 UWM 入口；
- workflow console；
- Track 2 材料入口。

### M7: Track 2 Submission Package

状态（2026-07-08）：部分完成。已有研究日志、readiness、data foundation、demo scripts、handoff 和 evidence artifacts；最终提交包尚未关闭。

目标交付物（当前部分完成，最终提交包未关闭）：

- 研究报告；
- 数据说明；
- 可复现代码；
- AI 协作日志；
- 图表；
- 证据边界。

## 7. 第一批建议创建的文件

状态（2026-07-08）：本节是 2026-07-04 的初始创建建议，当前大部分已经完成或被实际实现路径替代。后续阅读本节时，应以当前代码和 artifacts 为准，不应把它误读为仍未启动。

建议第一批创建：

```text
docs/reports/uwm_data_foundation_manifest.csv
docs/reports/uwm_data_foundation_manifest.md
docs/reports/uwm_track2_research_log.md
docs/superpowers/specs/2026-07-04-uwm-livability-track2-design.md
data_agent/uwm/contracts.py
data_agent/uwm/manifest.py
data_agent/uwm/mmfe_state_input.py
```

实际替代前端和 API 路径：

```text
frontend/src/components/datapanel/LivabilityWorldModelTab.tsx
data_agent/api/uwm_livability_decision_routes.py
data_agent/api/world_model_v11_routes.py
```

这些文件已经不再是“后续创建”状态。后续应围绕真实数据接入、生产级 MMFE/lakehouse、observed policy outcome validation、station-calibrated AQ holdout 和更强 planner/RL evidence 迭代。

## 8. 防糊弄检查表

后续每个阶段都要检查：

1. 有没有领域理论支撑？
2. 有没有传统 baseline？
3. 有没有数据 manifest？
4. 有没有 MMFE trace？
5. 有没有 canonical observation？
6. 有没有 action-conditioned rollout？
7. 有没有 simulator trace？
8. planner 是否只消费 simulator trace？
9. 有没有 evidence gate？
10. 有没有 claim boundary？
11. 合成数据是否明确标记？
12. Track 2 材料是否同步记录？

如果某阶段不能回答这些问题，就不能进入下一阶段。

## 9. 后续工作重点

### 9.1 权威城市数据与真实政策结果

最高优先级是补齐真实城市生产数据，而不是继续堆叠 demo 功能。上海/真实城市 P0 数据应至少包括：

- authoritative urban state history：行政单元/网格级设施、道路、建筑、绿地、水体、人口、服务、暴露、交通与环境状态历史；
- intervention policy history：真实政策干预、工程项目、治理动作、时间、空间范围、强度、预算、约束与审批记录；
- outcome validation history：干预后空气质量、热环境、服务可达、出行、健康/投诉/感知等可验证结果；
- action feasibility and constraints：用地、规划、工程、财政、管制、既有项目库和不可行动区域；
- population vulnerability：老年人、儿童、低收入、健康脆弱性和高暴露群体空间分布；
- mobility/travel-time evidence：道路网络、公交/轨交、OD、出行时间、服务容量；
- station-calibrated air-quality evidence：站点观测、时空对齐、scene-level holdout 和源归因边界。

### 9.2 从 feasible-action prior 走向真实 behavior/policy prior

当前 full-admin energy-regularized planner 使用的是 feasible action geometry、行政邻接、相似地理配置边和 action type 的 conservative prior。下一步必须把它升级为真实行为/政策先验：

- 当前已通过 `production_action_catalog` 把 57 类生产动作、13 个参数字段、6 类证据层和 planner binding gates 固化为机器可读契约；后续拿到权威数据时应新增 adapter 和 evidence slice，而不是改写 planner/action inventory 的核心接口；
- 当前已通过 `production_governance_data_contract` 固化政策项目历史、约束成本、观测结果、因果校准和人工审核 5 张必需表；没有这些表时，planner 仍只能做 bounded-support 反事实搜索，不能进入生产治理 claim；
- 当前已通过 `production_governance_data_adapter` 固化字段、权威标记和业务语义三层校验：即使行声明为 `real + verified`，只要存在 unsupported action_type、日期倒置、负预算、非法实施/审批状态、非法因果诊断或缺少项目/文档 ID，也不能成为 accepted authoritative row；
- 当前已通过 `production_governance_linkage_audit` 固化跨表闭环检查：只有当真实项目历史能同时连到约束成本、observed outcome、causal effect 和 human review 时，后续 planner governance binding 才有进入下一道 evidence gate 的数据基础；
- 当前已通过 `production_governance_planner_binding_gate` 固化 planner 前置硬门控：9 项门控当前 2 项通过、7 项阻断，后续只有权威表、非零权威行、跨表闭环、observed outcome、causal effect 和 human review 同时通过时，才允许进入生产治理 planner binding；
- 从历史干预日志学习 action type、目标单元、强度、预算和时序分布；
- 把硬约束、审批规则、规划边界和不可行动区做成 mask；
- 对 OOD action sequence 加入可解释的惩罚；
- 用 observed policy history 做 cross-time holdout，而不是只在同一场景 replay。

### 9.3 更强 planner 与 action-sequence world model

当前 GraphDQN、Dyna-Q、full-admin learned dynamics rollout、full-admin livability decision package 和 full-admin energy-regularized planner 已经证明 same-scene bounded advantage，但仍要向真正可外推、可验证的 action-sequence world model 推进：

- 训练 diffusion-style 或 discrete action-sequence generator；
- 扩展 horizon、top-k、budget constraints 和 multi-objective Pareto frontier；
- 加入 policy prior、uncertainty penalty、evidence penalty 和 equity guard；
- 做跨时间、跨城区、跨城市 holdout，避免只证明同一场景 replay advantage；
- 保留 search-value alignment audit，防止 planner 利用 simulator bias。

### 9.4 生产级 MMFE/Lakehouse

当前 shadow catalog 与 state-input 已能支撑研发闭环，但生产系统需要：

- 把城市资产注册到 catalog/lakehouse；
- 建立 curated admin/grid state tables；
- 建立 versioned observation、action、outcome history；
- 为每个字段保留 source、license、CRS、time、quality、synthetic flag 和 claim boundary；
- 让 frontend/API 只消费 cataloged assets，不消费临时文件。

### 9.5 Observed policy outcome 与因果门控

要把当前 bounded system claim 推进到更强事实结论，必须完成：

- treatment-control / matched control 设计；
- spatial and temporal holdout；
- negative controls、placebo、residual Moran、spatial bootstrap；
- off-policy evaluation 与 policy counterfactual validation；
- station-calibrated AQ 与其他 outcome endpoints 的独立校验；
- causal effect claim 与 simulator replay claim 分离报告。

### 9.6 2.5D/3D 与规模化

3D/BIM/point cloud 可以增强表达和机制，但当前不能让 3D 反过来稀释世界模型闭环。正确顺序是：

- 保持 2D/2.5D renderer-simulator-planner-evidence loop 稳定；
- 先把 building-floor morphology、街区形态和微环境暴露纳入 2.5D endpoint；
- 再接 BIM/点云/3D tiles；
- 每次 3D 增强都必须说明它改进了哪个 state、mechanism、action feasibility 或 validation endpoint，而不是只改视觉效果。
