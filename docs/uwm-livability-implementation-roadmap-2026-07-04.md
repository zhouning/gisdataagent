# UWM-Livability Implementation Roadmap for Urban Cup 2026 Track 2

日期：2026-07-04

## 1. 文档目的

这份文档记录 UWM-Livability 的实施路线图。它不是代码计划，也不是 UI 设计稿，而是后续实现前必须遵守的路线约束。

核心目标：

```text
以实现一个 Urban World Model 为目标，
用 UWM 解决城市宜居性分析问题，
并在全过程中形成 Urban Cup 2026 Track 2 可提交材料。
```

必须吸取 TWM 早期教训：不能先做一个能展示的 demo，再补理论、补数据边界和补验证。UWM 的路线必须先立领域理论、数据契约、世界模型契约和证据门控，再逐步实现交互入口、runtime 和提交材料。

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

交付物：

- state encoder；
- action encoder；
- scenario encoder；
- baseline dynamics backend；
- AlphaEarth-enhanced state prior；
- `UwmRolloutTrace.v1`。

动作集合：

- 增绿；
- 交通减排；
- 公共服务补点；
- 建筑强度调整；
- 慢行/公交可达性改善；
- 极端高温/静稳天气压力测试。

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

建议前端入口：

```text
frontend/src/components/datapanel/UrbanWorldModelTab.tsx
DataPanel tab key: uwm
Tab label: UWM / 城市世界模型
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

建议后端 API 形态：

```text
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

完成：

- UWM 数据契约；
- 状态契约；
- trace 契约；
- planner 契约；
- 城市宜居性理论框架。

### M1: 数据基础 v0

完成：

- 现有重庆数据入 manifest；
- Paper6 / Paper58 / EPA 资产入 manifest；
- 公开数据候选入 manifest；
- 合成边界入 manifest。

### M2: MMFE-UWM State Input

完成：

- MMFE 产出第一版 UWM state-input；
- 城市图结构初版；
- 数据质量 sidecar。

### M3: 传统 baseline

完成：

- 静态宜居性评价；
- 敏感性分析；
- baseline 局限性说明。

### M4: Renderer + Simulator v0

完成：

- `UwmCanonicalObservation.v1`；
- `UwmRolloutTrace.v1`；
- action-conditioned rollout。

### M5: Evidence-Gated Planner

完成：

- planner 消费 simulator trace；
- 推荐方案、拒绝理由和证据等级；
- hard constraint mask。

当前边界：

- learned rollout planner 已支持 `learned_world_model_rollout_improves_imagined_static_and_one_step_baselines`；
- livability intervention package 仍是 `exploratory_only`；
- 不能声明 observed policy outcome superiority。

### M5.5: World-Model Evidence Readiness

完成：

- data foundation evidence gate 已接入 Track 2 readiness；
- 已生成 `docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_matrix.json`；
- `system_level_superiority_summary = bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority`；
- allowed claims 包括 OpenAQ observed temporal state、TAP external temporal transition、learned rollout；
- forbidden claims 包括 observed policy outcome superiority、TAP spatial attribution、overall empirical policy superiority。

剩余：

- station-calibrated observed air-quality holdout；
- observed policy outcome validation data；
- causal policy effect validation；
- external observed holdout。

### M6: 独立 UWM Tab

完成：

- GIS Data Agent 独立 UWM 入口；
- workflow console；
- Track 2 材料入口。

### M7: Track 2 Submission Package

完成：

- 研究报告；
- 数据说明；
- 可复现代码；
- AI 协作日志；
- 图表；
- 证据边界。

## 7. 第一批建议创建的文件

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

前端和 API 后续创建：

```text
frontend/src/components/datapanel/UrbanWorldModelTab.tsx
data_agent/api/uwm_routes.py
```

这些文件不应一次性全部实现。应按 Phase 0 -> Phase 1 -> Phase 2 顺序推进。

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
