# UWM Renderer / Simulator / Planner: Theory and Architecture

日期：2026-07-04

## 1. 为什么记录这份文档

这份文档固化 UWM（Urban World Model）中 renderer、simulator、planner 的理论依据和技术架构，避免后续实现时把三者降级成“地图展示、预测脚本、优化器”。

结论先行：

```text
Renderer = 城市观测算子
Simulator = 动作条件城市动力学模型
Planner = 证据门控的城市干预搜索器
```

如果三者没有统一的状态、动作、轨迹、证据和回放 trace，就不是 UWM，只是普通宜居性分析系统。

## 2. 总体世界模型闭环

UWM runtime 应满足：

```text
MMFE / raw data
-> Renderer: UwmCanonicalObservation
-> Simulator: UwmRolloutTrace
-> Planner: UwmPlanPackage
-> Evidence Gate
-> Research Report / Urban Cup Track 2 materials
```

最关键的纪律：

```text
planner 只能消费 simulator trace
simulator 只能消费 renderer observation
renderer 必须保留数据证据和合成边界
```

如果 planner 自己生成收益，或者 simulator 直接读原始散乱数据，或者 renderer 只服务前端地图，都不合格。

## 3. Renderer: 城市观测算子

### 3.1 理论定位

UWM renderer 不是前端地图渲染器，而是 POMDP / world model 里的 observation model 或 measurement operator：

```text
raw urban data -> canonical urban observation O_t
```

它把真实世界中的多源城市数据，转成 simulator 可消费的城市观测状态。

### 3.2 理论依据

#### 3.2.1 GIScience 的 object-field duality

城市状态同时包含对象和场：

- object：建筑、道路、POI、AOI、公共服务设施、街区、行政边界；
- field：LST、NDVI、NDBI、PM2.5、NO2、O3、AlphaEarth embedding、人口栅格、气象栅格。

Renderer 不能把所有数据压成一个 flat table，也不能只保留图层列表。它必须把 object 和 field 同时表达为可计算城市状态。

#### 3.2.2 多尺度城市系统理论

城市状态天然跨尺度：

```text
building -> parcel / block -> grid -> district -> city
```

UWM 需要处理 MAUP、尺度偏差和聚合误差。Renderer 必须显式记录空间单元、尺度、聚合方法和时间窗口。

#### 3.2.3 城市复杂系统与网络理论

城市不是独立网格集合，而是图：

- 空间邻接；
- 道路连通；
- 功能相似；
- 通勤 OD；
- 环境传播邻近；
- 服务可达性网络。

Renderer 必须构建城市图，而不是只输出空间 join 后的表。

#### 3.2.4 Provenance / evidence theory

UWM 的状态不是纯净事实，而是带来源和证据边界的数据声明。每个状态单元和字段都应有：

- 来源；
- 时间；
- CRS；
- 数据质量；
- synthetic / semi_synthetic / restricted_expected / public_proxy 标记；
- 是否允许用于生产 claim；
- 证据链；
- 质量告警。

### 3.3 技术架构

Renderer 的技术链路：

```text
raw data / MMFE semantic product
-> data manifest
-> spatial unit builder
-> layer role binding
-> feature extraction
-> graph construction
-> quality and provenance sidecar
-> UwmCanonicalObservation.v1
```

MMFE 在这里不是旁路工具，而是 renderer 的数据融合前级和语义对齐引擎。UWM 应通过 `mmfe.uwm_state_input.v1` 接收 MMFE 产出的角色绑定、字段绑定、质量 sidecar 和语义关系。

### 3.4 输入

Renderer 输入包括：

- 重庆建筑高度、建筑轮廓；
- 道路网络；
- POI / AOI；
- DEM / CLCD；
- LST / NDVI / NDBI；
- AlphaEarth / GeoFM 表征；
- 人口与脆弱性代理；
- 通勤 OD；
- 空气污染或污染代理；
- 气象；
- 规划约束；
- MMFE semantic product；
- 数据 manifest。

### 3.5 输出契约

Renderer 输出不应是图片，而应是：

```text
UwmCanonicalObservation.v1 = {
  spatial_units,
  object_layers,
  raster_features,
  graph_edges,
  temporal_index,
  action_masks,
  quality_flags,
  synthetic_flags,
  provenance,
  claim_boundary,
  renderer_trace
}
```

关键字段：

- `spatial_units`：250m/500m grid、街区、建筑等；
- `object_layers`：建筑、道路、POI、AOI、设施；
- `raster_features`：LST、NDVI、AlphaEarth、污染、气象；
- `graph_edges`：邻接、道路、功能、OD、传播关系；
- `action_masks`：可实施动作的空间约束；
- `quality_flags`：缺失、时间错配、CRS 风险、覆盖不足；
- `synthetic_flags`：真实、公开代理、合成、半合成、受限预期；
- `renderer_trace`：记录所有融合、聚合、投影、重采样和图构建步骤。

### 3.6 验收标准

Renderer 必须通过：

- 能输出 simulator 可消费的 canonical observation；
- 能记录 CRS、时间、来源、质量、合成边界；
- 能构建城市图；
- 能暴露错误数据、缺失数据和合成数据；
- 能复现 feature extraction 和 spatial aggregation；
- 不能只输出前端 visual subset。

如果只输出地图或 dashboard，就是失败。

## 4. Simulator: 动作条件城市动力学模型

### 4.1 理论定位

Simulator 是 UWM 的 transition model：

```text
P(z_t+1, y_t+k | z_t, a_t, e_t, G)
```

它不是“预测未来宜居性分数”，而是模拟城市状态在干预动作和外部情景下如何变化。

### 4.2 理论依据

#### 4.2.1 Model-based RL / World Model

世界模型的核心是：

```text
当前状态 + 动作 -> 未来状态
```

UWM 中：

- `z_t`：当前城市状态；
- `a_t`：城市治理或规划干预；
- `e_t`：外部情景；
- `G`：城市图；
- `z_t+1`：干预后的潜在城市状态。

没有 action-conditioned transition，就不是 simulator。

#### 4.2.2 城市土地利用-交通-环境耦合

城市宜居性由多个子系统耦合形成：

- 城市形态影响热环境和通风；
- 道路活动影响污染和噪声；
- 绿地水体影响热风险和服务可达性；
- 公共服务设施影响生活便利；
- 人口脆弱性影响风险暴露；
- 交通和通勤联系影响实际可达性。

Simulator 必须预测多目标后果，不能只输出一个综合分。

#### 4.2.3 Urban climate / exposure science

热暴露和空气污染不是装饰变量，而是城市宜居性机制的一部分。Simulator 应表达：

- 绿地对热风险的影响；
- 建筑密度/高度对热环境和通风的影响；
- 道路交通对污染暴露的影响；
- 气象情景对污染扩散和热风险的调制；
- 脆弱人群对暴露变化的敏感性。

#### 4.2.4 Spatial causal inference

反事实干预不能直接从相关性推出。Simulator 输出如果要升级为因果或政策 claim，必须经过 SCCA 或其它空间因果证据门控。

#### 4.2.5 Uncertainty quantification

UWM 不能只给点预测。Simulator 必须输出：

- 不确定性区间；
- ensemble / stochastic rollout；
- scenario branching；
- negative control arms；
- evidence grade。

### 4.3 技术架构

Simulator 的技术链路：

```text
UwmCanonicalObservation
-> State Encoder
-> Action Encoder
-> Scenario Encoder
-> Dynamics Core
-> Multi-head Decoder
-> Evidence Gate
-> UwmRolloutTrace.v1
```

核心接口：

```text
encode_state(observation)
predict_next(encoded_state, action, scenario)
rollout(initial_state, action_sequence, scenario)
score_transition(prediction, truth)
```

### 4.4 输入

Simulator 输入：

```text
encoded_state z_t
+ action a_t
+ scenario e_t
+ graph G
+ evidence_context
+ claim_boundary
```

动作 `a_t` 必须是可解释城市干预：

- 增加绿地或树冠覆盖；
- 降低道路交通强度或排放；
- 增设公共服务设施；
- 调整建筑密度或高度；
- 改善慢行或公共交通可达性；
- 组合干预。

外部情景 `e_t` 包括：

- 高温日；
- 静稳天气；
- 人口增长；
- 通勤需求变化；
- 极端气候压力测试。

### 4.5 输出契约

Simulator 输出：

```text
UwmRolloutTrace.v1 = {
  initial_state_ref,
  action_sequence,
  scenario,
  backend,
  future_state_delta,
  heat_risk_delta,
  air_pollution_exposure_delta,
  service_accessibility_delta,
  equity_delta,
  livability_delta,
  uncertainty_interval,
  evidence_grade,
  claim_boundary,
  diagnostics,
  simulator_trace
}
```

其中 multi-head 输出至少包括：

- `future_state_delta`；
- `heat_risk_delta`；
- `air_pollution_exposure_delta`；
- `service_accessibility_delta`；
- `equity_delta`；
- `livability_delta`；
- `uncertainty_interval`；
- `evidence_grade`。

### 4.6 可分阶段 backend

Simulator 可以逐步演进，但必须标注能力边界：

```text
baseline heuristic backend        -> 只能 smoke test
empirical/statistical backend     -> 可做弱预测
graph/spatiotemporal backend      -> UWM 主体
AlphaEarth-enhanced backend       -> 遥感状态先验
SCCA-calibrated backend           -> 因果证据校准
EPA benchmark backend             -> UWM-Air 公开验证
```

Paper58 / AlphaEarth 的定位：

- 可作为遥感语义状态和 allocation prior；
- 不能被宣传为完整 UWM simulator；
- 必须与城市活动、环境暴露、公共服务和人口脆弱性数据结合。

Paper6 / SCCA 的定位：

- 不直接负责全部 dynamics；
- 负责把反事实和干预效果进行因果证据校准和降级。

EPA benchmark 的定位：

- 作为 UWM-Air 的公开验证；
- 不是重庆空气污染观测替代物。

### 4.7 验收标准

Simulator 必须通过：

- 有 action 输入；
- 能 rollout；
- 能输出 simulator trace；
- 能做 scenario branching；
- 能输出不确定性；
- 能接 evidence gate；
- 能区分真实、公开代理、合成数据；
- 能用 holdout / negative control / benchmark 被证伪。

如果只有静态指数，不是 simulator。

如果没有 action-conditioned transition，不是 simulator。

如果没有 trace，planner 和 benchmark 都无法证明它不是 facade。

## 5. Planner: 证据门控的城市干预搜索器

### 5.1 理论定位

Planner 是 constrained MDP / model predictive control / safe planning 中的策略搜索器。

它的问题不是“哪里宜居性低”，而是：

```text
在预算、规划约束、数据证据和不确定性边界内，
选择哪些城市干预动作，使未来宜居性和空间公平改善最大，
同时风险和证据不足最小。
```

### 5.2 理论依据

#### 5.2.1 Constrained MDP / Safe Planning

城市干预不是自由动作空间。动作必须满足：

- 规划约束；
- 预算约束；
- 空间可实施性；
- 设施服务半径；
- 环境承载；
- 不伤害脆弱群体；
- 数据证据完整性。

硬约束应是 action mask，而不是后验扣分。

#### 5.2.2 Model Predictive Control

Planner 应使用 simulator 做多步 rollout：

```text
state -> action -> predicted state -> next action -> ...
```

这才是 model-based planning。如果只对当前宜居性分数排序，就是传统 GIS 决策支持。

#### 5.2.3 多目标城市决策

城市宜居性不是单目标最大化。Planner 需要同时考虑：

- 平均宜居性增益；
- 低宜居区域改善；
- 脆弱人群受益；
- 热风险下降；
- 污染暴露下降；
- 服务可达性改善；
- 实施成本；
- 不确定性；
- 证据等级；
- 空间公平。

### 5.3 技术架构

Planner 技术链路：

```text
planning goal
-> action candidate generator
-> hard constraint / feasibility mask
-> simulator-coupled rollout
-> multi-objective scoring
-> evidence gate
-> ranked intervention package
```

核心接口：

```text
generate_candidates(observation, goal, constraints)
filter_feasible(candidates, action_masks)
evaluate_candidate(candidate, simulator)
rank_candidates(candidate_traces, objectives)
select_plan(ranked_candidates, evidence_gate)
```

### 5.4 输入

Planner 输入：

- planning goal；
- UwmCanonicalObservation；
- candidate action library；
- budget / feasibility constraints；
- simulator；
- evidence gate；
- value function；
- user or expert priorities。

### 5.5 目标函数

Planner 的目标函数不能只有平均宜居性：

```text
V = mean_livability_gain
  + vulnerable_population_gain
  + low_livability_area_gain
  - heat_risk
  - pollution_exposure
  - implementation_cost
  - uncertainty_penalty
  - evidence_penalty
```

实际实现中应保留多目标分解，而不是只给一个 opaque scalar。

### 5.6 输出契约

Planner 输出：

```text
UwmPlanPackage.v1 = {
  planning_goal,
  recommended_actions,
  rejected_actions,
  rollout_traces,
  expected_benefits,
  equity_effects,
  risk_flags,
  evidence_grade,
  data_gaps,
  human_review_required,
  claim_boundary,
  planner_trace
}
```

必须解释：

- 为什么推荐；
- 为什么拒绝；
- 触发了哪些硬约束；
- 缺少什么证据；
- 需要谁复核；
- 哪些结论只能 exploratory；
- 哪些结论可以进入 Track 2 报告。

### 5.7 验收标准

Planner 必须通过：

- 必须调用 simulator；
- 必须消费 simulator trace；
- 硬约束必须是 action mask；
- 输出推荐和拒绝理由；
- 输出证据等级；
- 输出人类复核需求；
- 合成数据驱动结果只能 exploratory。

如果不调用 simulator，只按当前分数排序，就是传统 GIS 决策支持。

如果硬约束只是扣分项，而不是 action mask，不合格。

如果不能解释为什么拒绝方案，不合格。

如果不能输出证据等级，不合格。

## 6. Renderer / Simulator / Planner 的强边界

### 6.1 Renderer 不做的事

Renderer 不负责：

- 选择规划方案；
- 编造未来效果；
- 产生最终宜居性结论；
- 绕过 MMFE 做不可追踪临时融合。

Renderer 只负责把城市世界观测成 canonical observation。

### 6.2 Simulator 不做的事

Simulator 不负责：

- 自己选择最优方案；
- 忽略动作直接给宜居性排名；
- 把相关性说成因果；
- 隐藏不确定性；
- 混淆真实数据和合成数据。

Simulator 只负责在给定动作和情景下做状态转移、风险、收益、不确定性和证据输出。

### 6.3 Planner 不做的事

Planner 不负责：

- 绕过 simulator 直接打分；
- 用高收益覆盖硬约束；
- 把证据不足的方案升级为强结论；
- 把合成数据结果包装成真实城市发现。

Planner 只负责在 simulator trace、硬约束和 evidence gate 下搜索可解释的干预方案。

## 7. 防糊弄判据

后续任何 UWM 实现，如果缺少以下任意核心契约，都不能声称为完整 UWM：

1. `UwmCanonicalObservation.v1`
2. `mmfe.uwm_state_input.v1`
3. `state-action-next_state-outcome` 轨迹
4. action-conditioned rollout
5. simulator trace
6. planner consumes simulator trace only
7. evidence gate
8. uncertainty interval
9. synthetic / restricted / public proxy 标记
10. claim boundary
11. traditional livability baseline
12. holdout / negative control / benchmark

最短判断：

```text
有没有 canonical observation？
有没有 state-action-next_state 轨迹？
有没有 action-conditioned rollout？
有没有 simulator trace？
有没有 evidence gate？
有没有 claim boundary？
```

没有这些，就不能叫 UWM。

## 8. 与 UWM-Livability 的关系

本文档是 `uwm-livability-track2-design-2026-07-04.md` 的架构补充。

UWM-Livability 的业务目标是城市宜居性分析，但 renderer / simulator / planner 的职责不能被业务场景弱化：

- Renderer 负责观测城市；
- Simulator 负责模拟干预后城市；
- Planner 负责选择证据可接受的干预；
- Evidence Gate 负责决定结论能否升级为 Track 2 报告中的可信发现。

这套边界必须在后续 spec、实现计划、代码、报告和提交材料中持续保持。
