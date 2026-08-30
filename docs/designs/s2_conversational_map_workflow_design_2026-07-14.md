# S2左侧对话与地图双向交互设计

日期：2026-07-14

## 1. 结论

S2可以并且应该支持从左侧对话框调用。对话入口更符合业务人员的使用方式，但不能简单地把现有S2 REST接口交给通用大模型自由调用。推荐采用“自然语言入口 + 确定性对话状态机 + 结构化业务卡片 + 双向地图选择协议 + 既有S2服务”的架构。

右侧S2页面继续作为完整工作台和高级审计入口；左侧对话承担快速发起、补齐参数、地图选地、确认、执行、解释和追问。两者共享同一个S2运行服务、快照、业务规则和持久审计记录。

## 2. 现有基础

### 2.1 已具备的能力

- `ChatPanel`能够读取助手消息的`metadata.map_update`并调用`onMapUpdate`。
- 助手响应完成后，前端会轮询`/api/map/pending`，补取工具运行期间产生的地图更新。
- `App`已经在聊天和地图之间共享`mapLayers`、中心点和缩放级别。
- `App`暴露了`window.__handleMapUpdate`，右侧数据页也能更新中间地图。
- `ChatPanel`已经支持Chainlit action按钮和AskUser交互。
- `MapPanel`已经支持要素点击、弹窗和跨图层关联高亮。
- S2已经具备真实地块检索、动作校验、覆盖评估、UWM推演、地图证据和持久运行记录。

### 2.2 当前缺口

- 地图点击只做本地高亮，不能把选中的地块回传给左侧对话。
- `handleMapUpdate`当前直接替换全部图层，不支持合并、移除、事务和选择模式。
- 通用聊天意图路由中没有专用S2入口和状态机。
- 聊天消息主要渲染Markdown，没有S2业务结果卡、参数卡和覆盖对比卡。
- 多轮对话没有保存S2草稿参数、快照和确认状态。

## 3. 总体架构

```text
用户自然语言 / @S2
        ↓
S2入口识别器
        ↓
S2ConversationOrchestrator（确定性状态机）
        ↓
参数提取层（LLM仅做候选提取）
        ↓
服务端枚举、ID、快照和规则校验
        ↓
现有S2 catalog / parcel / project / validate / rollout服务
        ↓
结构化聊天卡片 + map_update.v2
        ↓
中间地图选择、定位、图层对比
        ↓
选择事件回传S2状态机
```

核心原则：LLM可以理解用户语言，但不能决定最终地块ID、用途代码、设施类别、服务半径证据等级或同意结论。所有参数必须经过S2服务端校验，结论只能来自确定性GIS、版本化规则和UWM运行结果。

## 4. 对话入口

支持三种入口：

1. 显式入口：`@S2`、`@宜居性S2`。
2. 自然语言入口：包含“用地性质变更”“新增学校后覆盖”“移除公园是否同意”等明确S2语义。
3. 地图入口：用户在地图工具栏选择“用于S2分析”，然后点击地块。

建议增加`MentionLivabilityS2`，同时在通用消息处理前增加轻量确定性检测。进入S2后，本轮会话保持在S2状态机中，直到用户点击“结束S2”或明确切换任务。

## 5. 对话状态机

### 5.1 状态

- `idle`：尚未进入S2。
- `collecting_parcel`：需要地块ID、搜索条件或地图选地。
- `collecting_action`：需要仅变更用途、新增设施或移除设施。
- `collecting_transition`：需要目标用途和可选替代用途。
- `collecting_facility`：需要设施类别、真实设施记录或规划项目来源。
- `collecting_radius`：需要服务半径和证据来源。
- `ready_for_validation`：参数齐全，等待校验。
- `validation_failed`：存在快照、转换、设施或参数阻断项。
- `awaiting_confirmation`：校验通过，等待人工确认。
- `running`：执行覆盖计算和UWM反事实推演。
- `completed`：展示业务结论、地图和解释。
- `adjusting`：用户修改半径、目标用途或设施动作后重新评估。

### 5.2 会话草稿

```json
{
  "schema": "uwm.livability_s2.conversation_draft.v1",
  "conversation_id": "...",
  "actor_id": "admin",
  "snapshot_digest": "...",
  "state": "collecting_radius",
  "parcel_id": "parcel_79bb3178da33949459fc",
  "action_type": "add_facility",
  "from_land_use_class": "village_residential_land",
  "to_land_use_class": "village_public_service_land",
  "facility_class": "eldercare.station",
  "planning_project_id": "planning_project_...",
  "service_radius_m": null,
  "radius_evidence_source": null,
  "rationale": "...",
  "confirmed": false,
  "validation_digest": null,
  "run_id": null
}
```

草稿必须绑定操作人和快照。快照变化、地块变化或关键参数变化后，已有确认和校验摘要必须自动失效。

## 6. 推荐交互流程

### 6.1 完整自然语言输入

用户：

> 帮我判断地块 parcel_79bb3178da33949459fc 改成公共服务用地并新增养老服务站是否同意。

系统行为：

1. 精确查询地块并在地图定位。
2. 识别`add_facility`和`eldercare.station`。
3. 自动推荐真实规划项目“养老服务站”作为动作来源证据，但明确项目表不是设施现状坐标。
4. 发现缺少服务半径，展示按钮：`300米情景`、`500米情景`、`输入其他半径`、`选择权威标准`。
5. 参数齐全后展示确认卡。
6. 用户点击“确认并推演”。
7. 返回建议、覆盖变化、规则解释和地图图层。

### 6.2 地图选地

用户：

> 我想在地图上选择一个地块新增学校。

系统行为：

1. 对话进入`collecting_parcel`。
2. 地图加载候选地块图层并进入单选模式。
3. 地图顶部显示“正在为S2选择目标地块，点击一个地块；Esc取消”。
4. 用户点击地块后地图高亮，并在左侧出现地块确认卡。
5. 用户点击“使用该地块”，状态机继续收集目标用途和服务半径。

不要在普通地图浏览状态下自动把每一次点击都发送给聊天，避免误触和消息污染。只有S2状态机显式申请地图选择时才自动接收。

## 7. 聊天业务卡片

建议新增`S2ConversationCard`，由消息metadata中的结构化载荷渲染，而不是把所有内容输出成Markdown。

### 7.1 地块卡

- 地块ID。
- 村庄。
- 原始地类、当前用途、规划用途。
- 面积。
- 按钮：`地图定位`、`换一个地块`、`查看规划重叠证据`。

### 7.2 动作参数卡

- 业务动作。
- 目标用途。
- 设施类别。
- 规划项目来源。
- 服务半径和证据来源。
- 关键设施规则来源。
- 按钮：`修改`、`验证动作`。

### 7.3 校验与确认卡

- 用途转换状态。
- 业务预判。
- 阻断项和完整性警告。
- 当前快照和规则版本。
- 明确提示不是规划许可。
- 按钮：`确认并推演`、`调整参数`、`取消`。

### 7.4 结果卡

- 建议：同意、有条件同意、不同意、证据不足。
- 证据等级。
- 基线覆盖、干预覆盖和变化百分点。
- 新增覆盖/失去覆盖地块数。
- 触发规则。
- 规划项目来源和原表行号。
- UWM的t0、行动、t1、t2和覆盖重算链条。
- 运行ID和评估摘要。
- 按钮：`地图对比`、`只看新增覆盖`、`只看失去覆盖`、`调整半径重算`、`打开右侧完整工作台`、`查看高级审计`。

## 8. 地图双向协议

### 8.1 Chat到Map

建议升级为`map_update.v2`：

```json
{
  "schema": "map_update.v2",
  "operation": "merge",
  "transaction_id": "s2:conversation:123:step:parcel",
  "layers": [],
  "viewport": {"fit_layer_ids": ["s2_target_parcel"]},
  "interaction": {
    "mode": "select_one",
    "purpose": "s2_target_parcel",
    "accepted_layer_roles": ["s2_parcel_candidate"],
    "id_property": "parcel_id"
  }
}
```

`operation`至少支持：

- `replace`：替换整个分析场景。
- `merge`：保留底图和已有证据，增加或更新图层。
- `remove`：移除指定图层。
- `focus`：只调整视口和高亮。

### 8.2 Map到Chat

新增`map_feature_selection.v1`：

```json
{
  "schema": "map_feature_selection.v1",
  "interaction_id": "...",
  "purpose": "s2_target_parcel",
  "layer_id": "s2_parcel_candidates",
  "feature_id": "parcel_79bb3178da33949459fc",
  "properties": {
    "parcel_id": "parcel_79bb3178da33949459fc",
    "planning_area_id": "fulu_heping",
    "current_land_use_class": "village_residential_land"
  }
}
```

实现方式建议通过React props而不是全局window事件：

- `MapPanel`增加`onFeatureSelect`。
- `App`保存当前`mapInteraction`和`selectedMapFeature`。
- `ChatPanel`接收选择事件。
- 如果存在活动S2选择请求，调用S2 conversation endpoint提交选择。
- 如果没有活动请求，仅显示“地图上下文”小标签，不自动发送消息。

## 9. 后端实现

建议新增：

- `data_agent/uwm/livability_s2/conversation_orchestrator.py`
- `data_agent/api/uwm_livability_s2_conversation_routes.py`
- `data_agent/toolsets/uwm_livability_s2_tools.py`
- `MentionLivabilityS2`

推荐接口：

- `POST /api/uwm/livability/s2/conversations`：创建S2草稿。
- `POST /api/uwm/livability/s2/conversations/{id}/turns`：提交自然语言或结构化动作。
- `POST /api/uwm/livability/s2/conversations/{id}/map-selection`：提交地图选择。
- `POST /api/uwm/livability/s2/conversations/{id}/validate`：确定性校验。
- `POST /api/uwm/livability/s2/conversations/{id}/confirm`：绑定确认摘要。
- `POST /api/uwm/livability/s2/conversations/{id}/run`：调用现有rollout。
- `GET /api/uwm/livability/s2/conversations/{id}`：恢复状态。

初期草稿可以存入当前用户会话；生产阶段应进入数据库或摘要校验的持久存储。

## 10. 自然语言与确定性边界

LLM允许做：

- 从文本中提取地块关键词、动作候选、设施类别候选和用户意图。
- 生成简明业务解释。
- 识别“调整为800米”“换成养老站”等自然语言修改。

LLM禁止直接做：

- 猜测不存在的地块ID。
- 把“公共服务用地”自动等同于某种设施。
- 自行给出法定服务半径。
- 自行认定设施清单完整。
- 根据空间消息数量计算覆盖。
- 自行生成同意/不同意结论。
- 绕过人工确认执行推演。

## 11. 用户体验细节

- 用户输入完整时一次解析，不机械地逐项提问。
- 缺什么只问什么，并优先使用按钮和选择卡，不要求用户记代码值。
- 同时显示中文业务名称和内部代码，但内部代码默认弱化。
- 地图选择模式必须有明显状态条、取消按钮和选中反馈。
- 执行过程中显示阶段：锁定快照、验证动作、重算基线、构建干预世界、UWM传播、执行规则、生成地图。
- 结果先给业务结论，再给覆盖数值，再给“为什么”，最后才是技术审计。
- 用户追问“为什么”时引用当前运行ID和规则，不重新调用模型编造解释。
- 用户修改任何关键参数后明确提示旧结论失效，并产生新运行ID。

## 12. 分阶段实施

### 第一阶段

- 新增`@S2`确定性入口。
- 支持精确地块ID的完整对话调用。
- 使用现有Chainlit action按钮补齐半径和确认。
- 聊天结果自动更新地图。

### 第二阶段

- 新增`S2ConversationCard`结构化卡片。
- 新增地图选地模式和Map到Chat回传。
- 支持规划项目来源选择。

### 第三阶段

- `map_update.v2`支持merge/remove/focus。
- 支持基线/干预图层开关和覆盖变化筛选。
- 支持修改参数后快速重算和方案对比。

### 第四阶段

- 对话草稿和确认进入持久数据库。
- 支持审批复核意见、方案收藏和历史运行恢复。
- 与右侧完整S2工作台双向同步。

## 13. 验收标准

- 用户仅通过左侧对话完成一个真实S2运行，不进入右侧页面。
- 用户可输入精确地块ID，也可在地图点击选择。
- 地图选择结果必须回到同一个S2会话草稿。
- 缺少设施动作时返回证据不足，不能给虚假同意。
- 新增设施情景使用真实地块几何计算覆盖。
- 结果地图同时包含目标地块、基线范围、干预范围、新增覆盖和失去覆盖。
- 结果卡展示规则版本、快照、运行ID和证据边界。
- 修改关键参数后旧确认自动失效。
- 容器重启后已完成运行仍可恢复。

## 14. 推荐决策

建议实施。左侧对话不应替代右侧工作台，而应成为S2的业务入口和逐步引导层；中间地图承担空间选择和证据对比；右侧页面承担完整配置与高级审计。三者共享同一S2服务和运行记录，避免形成三套逻辑。

优先落地第一阶段和第二阶段：`@S2`确定性入口、结构化业务卡片、地图单选回传。这三项完成后，用户无需理解内部代码或手动搜索长地块ID，也能完成真实S2业务闭环。
