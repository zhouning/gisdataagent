# UWM 城市宜居性 S2 用地性质变更与地块级 Geospatial Kernel 设计

**日期：** 2026-07-11  
**状态：** 待用户文件级确认  
**适用项目：** GIS Data Agent  
**首版区域：** 重庆市璧山区福禄镇和平村、斑竹村

## 1. 背景与目标

S2 需求关注真实规划地块由用途类别 A 变更为用途类别 B 后，对目标地块、周边空间关系和村域宜居性上下文可能产生的影响，并要求提供可审计的辅助判断。

该需求不能通过“修改地类字段后重新统计设施覆盖率”完成。静态重算只能表达行动前后的 GIS 指标差异，不能表达行动条件化状态转移、影响传播、反事实轨迹、跨尺度聚合和不确定性边界。

本设计的目标是在 GIS Data Agent 中建立第一套可复用的、地块中心的跨尺度异构图 Geospatial World Model Kernel，并以此实现 S2 首版。首版不是审批系统，不输出未经证据支持的政策效果、人口变化、房价变化、设施容量或确定性宜居性提升结论。

## 2. 已确认范围

### 2.1 首版包含

- 使用和平村、斑竹村已有真实规划地块和规划资源。
- 支持真实地块土地用途类别 A → B 的受控变更。
- 支持 `no_change` 基线动作。
- 建立地块、规划资源、设施、村域和行政背景组成的跨尺度状态图。
- 执行 `t0_current → t1_post_change → t2_neighborhood_adaptation` 三阶段 rollout。
- 比较同一数据快照下的基线、干预和可选替代用途轨迹。
- 输出直接状态差异、空间传播信号、约束、潜在冲突、机会、数据缺口、不确定性和人工复核要求。

### 2.2 首版不包含

- 新建设施类型、建设规模、容量和施工周期动作。
- 人口迁移、居住需求诱发和居民行为预测。
- 房价、地价、开发收益或财务效果预测。
- 交通流量、通勤时间或步行可达性变化。
- 固定一年、三年、五年的精确数值预测。
- 规划审批通过概率或自动审批结论。
- 未经历史干预结果校准的学习型因果效果。

这些能力不得以占位数值或规则分数伪实现，必须在结果中列为 `unavailable_prediction`，并说明所需数据基础。

## 3. 技术路线决策

采用“地块中心的跨尺度异构图 Kernel”。

不采用以下方案作为主架构：

1. **规则驱动地块状态机：** 可作为内部静态 GIS 审计基线，但缺少真实图状态依赖和跨尺度传播。
2. **纯地块同构图：** 能表达地块传播，但无法自然容纳设施、规划资源、村域和行政上下文，后续扩展成本高。

现有行政单元 Graph-MDP 和 `spatial_spillover_kernel.py` 保留原语义，只作为上层上下文，不能直接包装成地块用途变更模型，也不能把行政级代理权重下放为地块政策效果。

## 4. 总体架构

```text
真实数据适配与快照构建
  → 地块中心跨尺度异构状态图
  → 受控动作与转换矩阵
  → 直接状态转移
  → 关系感知空间传播
  → 基线/干预/替代反事实 rollout
  → 证据门控与结论边界
  → S2 应用服务
  → API 与前端交互
```

Kernel 必须独立于 React、HTTP 请求格式和具体村庄名称。和平村、斑竹村通过业务适配层接入，保证 kernel 后续可复用于设施建设、城市更新、韧性干预和多步规划。

## 5. 状态图契约

### 5.1 `parcel` 节点

保存：

- `parcel_id`：由权威源属性和几何摘要生成或沿用现有稳定 ID。
- `geometry`、`area_m2`、`perimeter_m`、`compactness`。
- `current_land_use_class`：当前可观测用途。
- `planned_land_use_class`：规划意图，不得与当前状态混用。
- `candidate_land_use_class`：当前 rollout 候选用途。
- `source_land_use_code`：原始编码，模型不得覆盖。
- `village_id`、`admin_context_id`。
- `constraint_flags`、`evidence_refs`、`observability`、`state_time`。

### 5.2 `planning_resource` 节点

复用 S4/S6 已构建的真实规划资源，保留：

- 稳定资源 ID、原始名称、类别及原始字段。
- 与目标地块的包含、相交和邻近关系。
- 相交面积比例。
- 用途相容状态。
- 权威类别映射状态和人工复核状态。

未映射资源必须保留在图中，不得因语义分类失败而丢弃。

### 5.3 `facility` 节点

复用现有设施库存，表达设施类别、位置、映射状态、数据完整性以及与目标地块的空间和相容关系。

在缺少可靠容量、服务人口和 FP/FPP 时，设施节点不得产生服务能力增量或覆盖率改善结论。

### 5.4 `village_context` 与 `admin_context`

`village_context` 聚合地块变化形成的村域结构代理量；`admin_context` 连接现有行政单元 UWM，提供上层空间背景、邻接关系和已有代理指标。

聚合方向以地块向村域、村域向行政摘要为主。行政平均值不得反向推断地块真实效果。

### 5.5 关系类型

- `parcel_adjacent_parcel`
- `parcel_near_parcel`
- `parcel_contains_resource`
- `parcel_near_facility`
- `parcel_within_village`
- `village_within_admin`
- `functional_compatibility`
- `cross_scale_context`

所有边必须包含关系来源、空间计算依据、证据级别和版本信息。

## 6. 时间状态设计

### 6.1 `t0_current`

当前可观测状态，包括当前用途、规划用途、邻接地块、周边设施、规划资源、村域与行政背景。

### 6.2 `t1_post_change`

动作执行后的直接状态。只更新动作契约允许变化的字段和直接关系，不加入邻域传播结果。

### 6.3 `t2_neighborhood_adaptation`

空间传播和跨尺度聚合后的状态。该阶段表达规划决策阶段的邻域适应代理，不对应固定自然年，也不表示建设已完成或社会经济效果已经发生。

## 7. 动作契约

首版动作：

```text
no_change(parcel_id)

change_land_use_class(
    parcel_id,
    from_land_use_class,
    to_land_use_class,
    rationale,
    actor
)
```

每个动作必须绑定：

- 稳定地块 ID。
- 声明的源用途和目标用途。
- 数据快照摘要。
- 服务端绑定的登录用户。
- 行动理由和请求时间。
- 转换矩阵、字典和 evidence contract 版本。

若 `from_land_use_class` 与快照当前状态不一致，或客户端快照摘要过期，kernel 必须拒绝 rollout。

## 8. 用途转换矩阵

转换判断分为三层：

1. **数据有效性：** 地块、源地类、目标地类、快照和变化请求是否一致且有效。
2. **技术转换矩阵：** 返回 `allowed`、`conditionally_allowed`、`prohibited` 或 `unresolved`。
3. **人工决策门：** `allowed` 仅表示允许进入技术推演，不表示审批许可；`conditionally_allowed` 和 `unresolved` 必须人工复核。

大模型不得自由生成转换关系。没有完整权威规则时，除明确的同类保持或已经接入的权威规则外，不得自动标记 `allowed`，其余应 fail-closed 为 `unresolved`。

## 9. 空间传播 Kernel

### 9.1 传播证据层级

- `deterministic_geometry`：由拓扑、距离、相交等可复算几何事实支持。
- `authoritative_rule`：由权威规划规则或相容矩阵支持。
- `bounded_proxy`：有空间依据但未经真实干预结果校准。
- `learned_calibrated`：仅在未来具备历史状态—行动—结果数据后启用。
- `unavailable`：当前不能传播或预测。

第一阶段只启用前三类，不得把规则或代理权重描述为学习所得效果。

### 9.2 直接转移

```text
S(t1) = T_constrained(S(t0), action)
```

直接更新目标地块用途和相关关系，不自动更新人口、价格、交通、设施容量、建设完成状态、满意度或综合宜居性分数。

### 9.3 邻接地块传播

`parcel_adjacent_parcel` 可表达用途相容性变化、边界冲突、功能连续性、破碎化或聚集机会。

可观测输入包括共享边界长度、共享边界占源/目标地块周长比例、地块面积、形态和权威相容关系。这些量不得解释为真实社会经济效果。

### 9.4 距离地块传播

`parcel_near_parcel` 使用分析距离带：

- 0–50 米：近邻暴露。
- 50–150 米：局部关联。
- 150–300 米：弱上下文关联。
- 大于 300 米：首版停止局部传播。

距离在适合目标区域的投影 CRS 中计算。距离带是 `proxy_distance_band`，不得称为步行圈或法定控制线。

### 9.5 规划资源和设施传播

`parcel_contains_resource` 返回资源相容、潜在冲突、未映射、缺规则和人工复核信息；相交比例只说明证据构成，不自动决定资源处置。

`parcel_near_facility` 返回敏感设施邻近、潜在冲突、功能协同和数据缺口。没有路网和入口数据时，不得声称步行可达性变化。

### 9.6 跨尺度传播

`parcel_within_village` 聚合用地面积结构、功能混合、资源冲突、未解决复核事项、局部破碎化等代理量。

`village_within_admin` 只上传受影响面积比例、变化集中度、潜在冲突数量和跨村邻接风险摘要。到达行政摘要层后不继续沿现有行政图扩散。

### 9.7 消息契约

每条传播消息至少保存：

```text
message_id
source_node_id
target_node_id
relation_type
effect_type
direction
raw_evidence
normalization_basis
propagation_stage
support_level
uncertainty
claim_level
kernel_version
```

Kernel 返回分解证据向量，不合成无依据的统一宜居性影响分。界面需要排序时只能使用透明的 `review_priority`，推荐顺序为：明确规则冲突、条件性冲突、未映射对象、高邻接暴露、中低距离暴露。

### 9.8 多跳与停止条件

- 第 0 跳：目标地块自身。
- 第 1 跳：相邻地块、300 米内地块、关联设施和规划资源。
- 第 2 跳：村域聚合及直接相邻村域上下文。
- 第 3 层：行政摘要，不再继续扩散。

满足以下任一条件时停止：超出空间范围、边不支持该效应、证据退化为无来源推断、数据不完整且方向不可界定、到达摘要层、路径循环、重复消息不增加新证据或状态差异。

## 10. 反事实 Rollout

每次请求至少运行：

```text
baseline:     t0_current → no_change → t1_baseline → t2_baseline_context
intervention: t0_current → change_land_use_class → t1_post_change → t2_neighborhood_adaptation
```

可选替代轨迹必须来自受控地类字典和转换矩阵，不得由 LLM 自由编造。

轨迹比较仅表达同一快照下的地块状态、关系激活或失效、冲突与机会信号、村域结构代理量、数据缺口和不确定性差异，不表达真实政策实施效果。

## 11. Kernel 输出契约

每次 rollout 至少返回：

- `baseline_state`
- `intervention_state`
- 可选 `alternative_states`
- `direct_state_delta`
- `spillover_state_delta`
- `constraint_violations`
- `potential_conflicts`
- `opportunity_signals`
- `unavailable_effects`
- `uncertainty`
- `claim_boundary`
- `review_required`

效果等级：

- `observed_state_change`
- `rule_supported_effect`
- `geometry_supported_signal`
- `unresolved_effect`
- `unavailable_prediction`

首版最高结论等级为 `bounded_action_conditioned_spatial_scenario`，不得升级为经验证的政策效果、审批建议、确定性宜居性提升、真实居民行为或因果效果。

## 12. Kernel 与应用层边界

### 12.1 Kernel 负责

- 图、节点、边、消息和证据契约。
- 三阶段状态推进。
- 动作验证和快照一致性。
- 转换矩阵和受约束直接转移。
- 有限多跳传播、去重、循环检测和停止。
- 反事实 rollout。
- observability、uncertainty、evidence gate 和 claim boundary。
- 显式关闭不支持的预测头。

### 12.2 应用层负责

- 村庄、地块和目标地类选择。
- 地图图层、阶段切换和差异展示。
- 表单校验、人工确认和运行历史。
- 报告导出和证据浏览。
- 和平村、斑竹村数据适配。
- 用户权限和审计日志。

API 和前端不得重新计算或提升 kernel 结论。

## 13. 建议代码结构

```text
data_agent/uwm/geospatial_kernel/
    contracts.py
    state_graph.py
    land_use_action.py
    transition_matrix.py
    direct_transition.py
    spatial_message.py
    spatial_propagation.py
    counterfactual_rollout.py
    evidence_gate.py
    validation.py

data_agent/uwm/livability_s2/
    fulu_adapter.py
    state_builder.py
    scenario_service.py
    product.py
```

现有行政区 kernel 保持兼容，不通过语义重写破坏已有测试和产品。

## 14. 数据产品

建议构建：

```text
data/uwm/livability_s2/fulu/
    parcels.geojson
    planning_resources.geojson
    facilities.geojson
    graph_nodes.json
    graph_edges.json
    land_use_dictionary.json
    transition_matrix.json
    evidence_manifest.json
    build_report.json
```

构建报告必须包含源文件摘要和修改时间、图层和字段映射、CRS、要素与几何统计、稳定 ID 方法、地类编码、节点和边数量、未映射对象、距离带定义、完整性声明、canonical SHA-256、构建脚本与 schema 版本。

首版不得生成合成地块填补真实数据空白。

## 15. API 设计

```text
GET  /api/uwm/livability/s2/catalog
GET  /api/uwm/livability/s2/parcels
GET  /api/uwm/livability/s2/parcels/{parcel_id}
POST /api/uwm/livability/s2/validate-action
POST /api/uwm/livability/s2/rollout
GET  /api/uwm/livability/s2/runs/{run_id}
```

`validate-action` 只判断能否进入技术推演，不表达审批许可。`rollout` 请求至少包含地块 ID、源用途、目标用途、快照摘要、行动理由和是否包含替代轨迹。

响应必须包含动作验证、三阶段基线和干预状态、直接变化、传播消息、受影响节点、约束、冲突、机会、不可用效果、不确定性、人工复核、快照和 kernel 版本。登录用户由服务端绑定，客户端不得提交可信 actor。

## 16. 前端产品设计

在 UWM 城市宜居性页面新增“S2 用地性质变更推演”，不新增重复的传统方法页面。

### 16.1 行动配置区

- 村庄和真实地块选择。
- 当前与规划用途只读展示。
- 受控目标地类选择。
- 转换状态、前置条件和行动理由。
- 数据快照与完整性提示。
- 人工确认后执行 rollout。

### 16.2 地图区

支持 `t0`、`t1`、`t2` 和基线/干预差异切换，显示目标地块、一跳邻接、50/150/300 米代理距离带、规划资源、设施、冲突、机会、未映射对象和传播边。

### 16.3 审计结果区

按动作状态、直接变化、邻域传播、村域聚合、约束与冲突、不可预测效果、不确定性、人工复核和证据链分组。禁止生成无依据的综合提升分数。

## 17. 验证与验收

### 17.1 契约测试

- 当前、规划和候选用途不混淆。
- 源状态或摘要不一致时拒绝执行。
- 未知地类不能绕过受控字典。
- 缺权威规则时不自动返回 `allowed`。
- 不支持预测头保持关闭。
- API 和前端不能提升 claim boundary。

### 17.2 空间测试

- 节点和边引用完整。
- 包含、邻接和距离关系正确。
- 投影 CRS 距离计算正确。
- 第 0、1、2 跳和行政摘要传播符合设计。
- 300 米外不发生首版局部传播。
- 循环路径不重复累计消息。

### 17.3 状态转移测试

- `no_change` 保持用途状态。
- 干预只改变契约允许字段。
- `t0` 不可变。
- `t1` 只含直接变化。
- `t2` 才含邻域传播。
- 基线与干预共享同一快照。
- 同一输入和版本得到确定性一致结果。

### 17.4 真实数据验收

和平村、斑竹村分别选择存在邻接关系、关联规划资源以及转换状态为 `unresolved` 的真实地块；若存在权威条件性转换规则，再增加对应地块。

逐项核查稳定 ID、原始属性、地图位置、空间关系、状态差异、传播路径、未映射对象保留、不可用效果关闭和同快照重跑摘要一致性。

## 18. 完成标准

只有同时满足以下条件，S2 首版才可标记完成：

- 使用两村真实地块、规划资源和现有设施数据。
- 建成可复用的 parcel/cross-scale geospatial kernel。
- 实现 action-conditioned 三阶段状态转移。
- 实现基线和干预反事实轨迹。
- 实现关系感知、有限多跳传播。
- 每条信号可追溯到关系、证据和版本。
- 不支持效果显式 unavailable。
- API 和界面不突破 kernel 的结论边界。
- 自动化测试和真实数据验证通过。
- 形成独立验证报告，明确数据缺口和生产限制。

## 19. 设计自审结论

- 无待填充占位符。
- 首版动作范围、时间语义和不实现项明确。
- 传统 GIS 基线与 UWM 产品职责不重复。
- Kernel 与应用层职责明确。
- 权威规则、几何事实、代理传播和学习效果边界明确。
- 当前数据不足不会被隐式分数或默认权重掩盖。
- 设计与现有 S1/S4/S6/S7 数据产品和行政单元 UWM 保持兼容。

