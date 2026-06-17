# 国土空间世界模型落地设计

- **状态**：Draft（阶段决策：先作为 paper 验证底座，暂不进入完整产品化实现）
- **日期**：2026-06-15
- **范围**：面向国土空间规划实施监督与自然资源治理的地理空间世界模型第一阶段落地
- **来源要求**：`/Users/zhouning/Downloads/地理空间世界模型核心技术路线说明.docx`
- **数据需求**：`docs/superpowers/specs/2026-06-15-territorial-world-model-data-requirements.md`
- **关联现有能力**：
  - `data_agent/standards_platform/` 数据标准全生命周期智能化管理
  - `data_agent/fusion/semantic_product.py` MMFE 语义融合产品
  - `data_agent/world_model_v21.py` Paper9 World Model v2.1 适配器
  - `data_agent/data_catalog.py` 数据资产目录与血缘

## 0. 阶段决策：先验证，后产品化

2026-06-16 复盘后形成新的阶段共识：TWM 暂不直接进入完整系统级实现或产品化实现。原因是 TWM 的关键价值不在于规则筛查和数据审计本身，而在于“动态推演 + 多目标优化 + 方案比选”是否能在真实自然资源治理场景中产生稳定、可解释、优于简单 baseline 的结果。该部分仍需要后续多个 paper 的实验验证支撑。

因此，当前阶段的 TWM 定位调整为 **TWM validation scaffold**：

1. 保留 `S_t` 可计算状态、角色绑定、标准契约、MMFE 证据链、硬约束规则、审计追溯和优化数据夹具；
2. 优先把它作为后续 paper 的统一实验底座和评估框架；
3. 用同一套数据、硬约束、指标和审计口径比较不同动态推演/优化方法；
4. 暂不把 WorldModel、MPC、DRL 或任一 paper 方法包装成生产级 TWM 决策引擎；
5. 等关键 paper 验证通过后，再恢复 TWM 系统级实现和产品化推进。

恢复完整 TWM 实现前，至少需要回答：

- 动态推演是否显著优于 Markov、CA、启发式或简单规则 baseline；
- 多目标优化是否能在硬约束下稳定产生有意义的 Pareto 解；
- 方案结果是否具备跨区域泛化能力，而不是只适配 demo 数据；
- 指标改善是否能被自然资源治理业务解释和复核；
- 模型输出是否能完整进入“原始数据 -> 状态版本 -> 模型推演 -> 约束校验 -> 人工复核”的审计链。

在该决策未被新实验结果推翻前，本文档中的系统设计应被理解为 **候选目标架构和验证框架设计**，不是立即开工的产品实现承诺。

## 1. 设计结论

本项目应新增一个面向自然资源治理业务的 **Territorial Spatial World Model** 子域，工程命名建议为 `territory_world_model`，数据库前缀为 `twm_`。它不是替代现有 MMFE、标准平台或 Paper9 WorldModel，而是在三者之上组织出“国土空间可计算状态 + 规则约束推演 + 可审计证据链”。

第一阶段不应直接以深度强化学习或 MPC 作为主入口。路线说明里最关键的约束是“规则优先、模型辅助、人工复核、全程留痕、数据不出域”。因此 MVP 应先完成：

1. 从 MMFE 语义融合产品和数据目录资产构建空间状态 `S_t`。
2. 用版本化政策规则校验永久基本农田、生态红线、用途管制、规划分区等硬约束。
3. 输出图斑级风险命中、GIS 风险图层、规则命中清单和证据链。
4. 支持人工复核状态回写。
5. 在后续阶段把 Paper9 WorldModel v2.1 接入为“合法可行空间内的方案比选/优化器”，而不是审批结论生成器。

数据侧的现实约束是：当前已有璧山、东兴 DLTB-like 图斑、坡度增强数据、WorldModel v2.1 prepared/ONNX/MPC 输出，足以支撑工程 MVP；但缺少权威永久基本农田、生态保护红线、城镇开发边界、用途管制分区、审批和执法数据。P0-P2 可以使用明确标记的 synthetic 控制线和变化数据，生产落地必须替换为权威自然资源数据。

## 2. 与路线说明的逐层对齐

| 路线说明层级 | 落地模块 | 首阶段交付 |
|---|---|---|
| 数据底座层：空间基准、语义口径、时间版本统一 | MMFE 语义融合产品 + 数据目录 + `twm_layer_binding` | 读取 `.semantic.json`、融合输出、资产元数据，形成可追溯输入清单 |
| 状态表征层：对象-关系-规则图 | `twm_state_version`、`twm_state_object`、`twm_state_relation` | 把图层转成图斑、地块、边界、分区、项目等对象及叠置/包含/邻接关系 |
| 约束推演层：规则优先动态模拟 | `twm_policy_rule`、`RuleEvaluator` | 先做硬规则校验和风险识别；动态推演作为 P2/P3 |
| 决策比选层：风险、方案、影响评估 | `twm_scenario`、`twm_scenario_metric` | P1 输出基线风险；P2 增加方案对比；P3 接入 Paper9 MPC |
| 解释审计层：GIS 证据链 | `twm_rule_hit`、`twm_evidence_item`、`twm_review_task` | 每个命中追溯到源资产、源要素、规则版本、状态版本和人工复核 |

## 3. 当前 GIS Data Agent 能力基础

### 3.1 数据标准全生命周期平台

现有标准平台已经覆盖采集、分析、起草、审定、发布、派生，具备做“规则版本源”的基础：

- 标准业务层位于 `data_agent/standards_platform/`。
- 发布与派生通过 `std_document_version`、`std_derived_link` 和 Outbox 模式管理。
- 已有派生策略包括：
  - `to_semantic_hint`
  - `to_synonym`
  - `to_value_semantics`
  - `to_qc_rule`
  - `to_defect_code`
  - `to_data_model`
- `to_qc_rule` 已能把标准数据元派生为数据质量规则，但它解决的是数据质量，不是国土空间政策约束。

本设计建议新增派生策略 `to_spatial_policy_rule`，把标准条款、值域、术语和数据元映射为 `twm_policy_rule` 的候选规则。候选规则必须人工审定后才能启用，避免把标准文本自动解释为行政判断。

### 3.2 MMFE 语义融合产品

最新 MMFE 已经从文件级融合推进到语义融合产品：

- `data_agent/fusion/semantic_product.py` 会生成 `.semantic.json`。
- manifest 包含业务输出、来源、语义映射、派生字段、推理字段、特征语义、AI chunks、质量和血缘。
- `FusionResult` 已包含 `semantic_product_path`、`semantic_summary`、`derived_fields`、`inferred_fields`。
- `fuse_datasets()` 默认启用语义产品生成。

这正好可作为国土空间状态构建的输入契约。TWM 不需要重新做字段匹配、CRS 对齐、冲突摘要和语义 chunks，而是读取 MMFE 的 manifest，并把其中的字段契约映射到图斑、边界、用途分区、项目等业务对象类型。

### 3.3 Paper9 WorldModel v2.1

`data_agent/world_model_v21.py` 是对 Paper9 `arcgis-farmland-mpc` 的薄适配，已经具备：

- Tool 1 prepare：DLTB + DEM -> prepared_dir
- Tool 2 sample：prepared_dir -> transition/pairwise samples
- Tool 3 train：samples -> ONNX ensemble
- Tool 4 plan：ONNX ensemble -> MPC planning output
- `/api/world-model-v21/*` REST API 和 `WorldModelV21Toolset`

该能力适合放在后续“方案比选/优化”层。第一阶段不应把它作为世界模型主语义，因为路线说明要求的核心是法定规则和审计证据链。Paper9 应接收 TWM 产生的可行空间、硬约束 mask、风险权重和审计上下文，输出候选方案及指标变化。

## 4. 新增模块边界

建议新增包：

```text
data_agent/territory_world_model/
  __init__.py
  models.py              # Pydantic/dataclass 契约
  semantic_loader.py     # 读取 MMFE semantic product 和 catalog 元数据
  state_builder.py       # 构建 S_t 对象、关系、指标快照
  rule_dsl.py            # 规则 DSL 校验与解析
  rule_evaluator.py      # 空间谓词、阈值、指标规则执行
  evidence.py            # 证据链构建
  repository.py          # twm_* 表读写
  presentation.py        # 地图 payload、风险摘要、报告摘要
  world_model_adapter.py # P2/P3：接 Paper9 v2.1 方案比选
```

新增外部接口：

```text
data_agent/api/territory_world_model_routes.py
data_agent/toolsets/territory_world_model_tools.py
frontend/src/components/datapanel/TerritoryWorldModelTab.tsx
```

模块职责边界：

| 模块 | 负责 | 不负责 |
|---|---|---|
| MMFE | 多源融合、字段匹配、语义 manifest、质量与冲突摘要 | 政策规则命中和行政风险判断 |
| 标准平台 | 标准版本、条款、引用、发布、派生候选规则 | 自动解释法律文本并直接启用规则 |
| TWM | 空间状态、规则校验、证据链、复核闭环、方案对比 | 重写融合引擎或替代 Paper9 算法 |
| Paper9 v2.1 | 合法可行空间内的模拟/优化/方案搜索 | 生成审批结论或覆盖硬规则 |

## 5. 核心数据模型

第一阶段建议新增 migration `089_twm_core.sql`。字段可以在实现时微调，但表族边界应保持稳定。

### 5.1 项目与输入绑定

```sql
twm_project
├─ id uuid PK
├─ name text
├─ description text
├─ region_code text
├─ business_scenario text  -- planning_supervision | use_control | farmland | ecology
├─ owner_username text
├─ status text             -- draft | active | archived
├─ created_at timestamptz
└─ updated_at timestamptz

twm_layer_binding
├─ id uuid PK
├─ project_id uuid FK
├─ role text               -- parcel | annual_change | pbf | eco_redline | planning_zone | approval | enforcement
├─ asset_id int NULL       -- agent_data_assets.id
├─ file_path text NULL
├─ semantic_product_path text NULL
├─ layer_alias text
├─ object_type text        -- parcel | boundary | zone | project | event
├─ time_label text
├─ valid_from date NULL
├─ valid_to date NULL
├─ field_mapping jsonb     -- canonical field -> actual field
├─ quality_snapshot jsonb
└─ created_at timestamptz
```

设计要点：

- `role` 表达业务角色，不直接等同文件名或图层名。
- `semantic_product_path` 是 MMFE manifest 的入口。
- `field_mapping` 可以来自 MMFE `semantic_mappings`，也可由用户补充。
- 同一项目可绑定多个时间版本图层，支持“年度变更调查”等时序数据。

### 5.2 空间状态版本

```sql
twm_state_version
├─ id uuid PK
├─ project_id uuid FK
├─ state_time timestamptz
├─ label text
├─ source_manifest jsonb
├─ rule_set_id uuid NULL
├─ object_count int
├─ relation_count int
├─ quality_summary jsonb
├─ build_status text       -- building | ready | failed
├─ build_log jsonb
├─ created_by text
└─ created_at timestamptz

twm_state_object
├─ id uuid PK
├─ state_version_id uuid FK
├─ object_type text        -- parcel | admin_unit | control_line | planning_zone | project | sensitive_area
├─ object_code text
├─ source_asset_id int NULL
├─ source_feature_id text NULL
├─ source_role text
├─ attributes jsonb
├─ semantic_tags text[]
├─ quality_score numeric
├─ geom geometry(MultiPolygon, 4326)
└─ bbox geometry(Polygon, 4326)

twm_state_relation
├─ id uuid PK
├─ state_version_id uuid FK
├─ subject_object_id uuid FK
├─ predicate text          -- intersects | contains | within | adjacent | distance_lt | upstream_of
├─ object_object_id uuid FK
├─ metrics jsonb           -- overlap_area_m2, overlap_ratio, distance_m
├─ confidence numeric
└─ evidence jsonb
```

设计要点：

- `S_t = object + relation + attribute + rule + time_version`，`twm_state_version` 是 `S_t` 的版本锚点。
- `geom` 第一阶段统一存 4326，空间计算时可临时投影到项目 CRS 或由 PostGIS geography/transform 计算。
- `object_code` 优先使用 DLTB 的 BSM、项目编号、管控边界编号等业务稳定标识。
- `attributes` 保存标准化字段，不直接复制所有原始字段；原始字段通过 source asset 与 source feature 追溯。

### 5.3 规则集与政策规则

```sql
twm_rule_set
├─ id uuid PK
├─ name text
├─ version_label text
├─ source_std_version_id uuid NULL
├─ status text             -- draft | active | retired
├─ created_by text
├─ approved_by text NULL
├─ approved_at timestamptz NULL
└─ created_at timestamptz

twm_policy_rule
├─ id uuid PK
├─ rule_set_id uuid FK
├─ rule_code text
├─ title text
├─ category text           -- farmland | ecology | planning | use_control | approval | quality
├─ severity text           -- info | low | medium | high | critical
├─ rule_body jsonb         -- DSL body
├─ legal_basis jsonb       -- std clause ids, law/policy text refs, source URLs
├─ review_policy text      -- auto_pass | review_required | always_review
├─ enabled boolean
├─ std_derived_link_id uuid NULL
├─ created_at timestamptz
└─ updated_at timestamptz
```

### 5.4 命中、证据与复核

```sql
twm_rule_hit
├─ id uuid PK
├─ state_version_id uuid FK
├─ rule_id uuid FK
├─ subject_object_id uuid FK
├─ target_object_id uuid NULL
├─ hit_status text         -- open | reviewed_confirmed | reviewed_dismissed | mitigated
├─ severity text
├─ risk_score numeric
├─ metrics jsonb
├─ explanation text
├─ geom geometry(MultiPolygon, 4326)
├─ created_at timestamptz
└─ reviewed_at timestamptz NULL

twm_evidence_item
├─ id uuid PK
├─ rule_hit_id uuid FK
├─ evidence_type text      -- source_feature | rule_clause | spatial_calc | semantic_mapping | model_output | reviewer_note
├─ source_system text      -- data_catalog | mmfe | std_platform | twm | world_model_v21
├─ source_ref text
├─ payload jsonb
├─ checksum text NULL
└─ created_at timestamptz

twm_review_task
├─ id uuid PK
├─ rule_hit_id uuid FK
├─ assignee text NULL
├─ status text             -- pending | confirmed | dismissed | needs_more_data
├─ decision text
├─ comment text
├─ created_at timestamptz
└─ updated_at timestamptz
```

证据链必须覆盖路线说明中的链路：

```text
原始数据 -> 规则版本 -> 状态变化 -> 模型推演 -> 约束校验 -> 人工复核
```

第一阶段没有模型推演时，`model_output` 证据为空，但证据链结构保留；P2/P3 接入 Paper9 或时序模型后补齐。

### 5.5 方案与指标

```sql
twm_scenario
├─ id uuid PK
├─ project_id uuid FK
├─ base_state_version_id uuid FK
├─ name text
├─ scenario_type text      -- baseline | user_edit | model_candidate | policy_change
├─ input_changes jsonb
├─ source_model text NULL  -- world_model_v21 | manual | simulation
├─ status text
└─ created_at timestamptz

twm_scenario_metric
├─ id uuid PK
├─ scenario_id uuid FK
├─ metric_code text        -- pbf_overlap_area, ecology_overlap_area, cultivated_area_delta
├─ metric_name text
├─ value numeric
├─ unit text
├─ benchmark_value numeric NULL
├─ direction text          -- lower_better | higher_better | target
└─ explanation text
```

## 6. 规则 DSL 设计

规则必须是结构化 JSON/YAML，不使用 Python `eval` 或任意表达式执行。第一阶段只支持确定性空间规则和属性规则。

示例：永久基本农田硬约束。

```json
{
  "version": "1.0",
  "subject": {
    "object_type": "parcel",
    "where": {
      "land_use_change_type": ["construction_expansion", "non_agricultural"]
    }
  },
  "constraint": {
    "target_role": "pbf",
    "spatial_predicate": "intersects",
    "max_overlap_area_m2": 0
  },
  "metrics": [
    "overlap_area_m2",
    "overlap_ratio"
  ],
  "hit_when": {
    "overlap_area_m2": { "gt": 0 }
  },
  "evidence": {
    "require_source_feature": true,
    "require_rule_clause": true,
    "require_spatial_calc": true
  }
}
```

示例：生态保护红线触碰风险。

```json
{
  "version": "1.0",
  "subject": {
    "object_type": "project",
    "where": {
      "approval_status": ["proposed", "approved"]
    }
  },
  "constraint": {
    "target_role": "eco_redline",
    "spatial_predicate": "intersects",
    "max_overlap_area_m2": 0
  },
  "hit_when": {
    "overlap_area_m2": { "gt": 0 }
  },
  "review": {
    "policy": "always_review",
    "reason": "生态保护红线相关命中必须人工复核"
  }
}
```

第一阶段 DSL 支持范围：

| 能力 | 支持项 |
|---|---|
| 对象选择 | `object_type`、`source_role`、简单字段过滤 |
| 空间谓词 | `intersects`、`within`、`contains`、`overlap_area_gt`、`distance_lt` |
| 指标 | 面积、占比、距离、数量 |
| 条件 | `eq`、`in`、`gt`、`gte`、`lt`、`lte`、`exists` |
| 输出 | 严重级别、风险分、解释模板、复核策略 |

不在第一阶段支持：

- 任意自然语言规则直接执行。
- 复杂法律例外条款自动判断。
- 跨年度系统动力学模拟。
- 黑箱模型直接生成政策命中结论。

## 7. 状态构建流程

```text
选择项目和图层绑定
        ↓
读取 data catalog asset + MMFE semantic manifest
        ↓
解析字段契约、CRS、时间版本、质量摘要
        ↓
按 role 映射为 parcel / control_line / planning_zone / project / event
        ↓
生成 twm_state_object
        ↓
计算重点空间关系 intersects / contains / adjacent / distance
        ↓
生成 twm_state_relation
        ↓
写入 twm_state_version build summary
```

关键实现策略：

- 小数据集第一阶段可用 GeoPandas/Shapely；大数据集 P1 切 PostGIS `ST_Intersects`、`ST_Area`、`ST_Transform`。
- 不直接依赖 LLM 识别字段。字段标准化优先级为：
  1. 用户显式 `field_mapping`
  2. MMFE `semantic_mappings`
  3. 标准平台派生的 semantic hints/value semantics
  4. 受控启发式别名
- 构建状态时必须保留每个对象的 `source_asset_id` 和 `source_feature_id`。
- 质量分低于阈值的输入不阻止构建，但在 `quality_summary` 和证据链中标记。

## 8. 规则执行与证据链

规则执行流程：

```text
加载 active rule_set
        ↓
逐条解析 rule_body
        ↓
选择 subject objects
        ↓
按 target_role 查找约束对象
        ↓
执行空间谓词与指标计算
        ↓
生成 rule_hit
        ↓
生成 evidence_item
        ↓
必要时创建 review_task
        ↓
输出风险图层与清单
```

每个 `twm_rule_hit` 的证据至少包含：

| 证据类型 | 内容 |
|---|---|
| `source_feature` | subject 和 target 的源资产、源要素 ID、核心属性快照 |
| `rule_clause` | 规则版本、标准条款、法律依据或内部标准依据 |
| `spatial_calc` | 空间谓词、投影 CRS、面积/距离/占比、计算时间 |
| `semantic_mapping` | MMFE field contract、标准语义字段、置信度 |
| `reviewer_note` | 人工复核人、结论、备注、时间 |

有模型推演时追加：

| 证据类型 | 内容 |
|---|---|
| `model_output` | 模型名、版本、输入状态、参数、输出 artifact、指标变化、不确定性 |

## 9. 与标准平台的集成

新增派生策略：

```text
data_agent/standards_platform/derivation/strategies/spatial_policy_rule.py
```

策略名称：

```text
to_spatial_policy_rule
```

派生逻辑：

1. 从发布版本读取 `std_clause`、`std_data_element`、`std_value_domain`。
2. 识别与国土空间约束相关的条款和数据元，例如三条控制线、永久基本农田、用途管制分区、规划指标、面积阈值。
3. 生成 `twm_policy_rule` draft 候选，写入 `legal_basis` 和 `std_derived_link_id`。
4. 不自动启用。需要 `standard_reviewer` 或 admin 在 TWM 规则管理界面审定。
5. 版本重派生时沿用现有 stale 语义，旧规则不删除，标记为 stale/retired。

与 `to_qc_rule` 的边界：

- `to_qc_rule`：字段完整性、值域合法性、数据质量。
- `to_spatial_policy_rule`：空间对象对政策/规划/管控约束的命中。

## 10. 与 MMFE 的集成

TWM 的 `semantic_loader.py` 读取 MMFE manifest：

```json
{
  "product_type": "semantic_fusion_product",
  "business_output": { "path": "...", "crs": "EPSG:4326" },
  "semantic_mappings": [],
  "derived_fields": [],
  "inferred_fields": [],
  "quality": {},
  "lineage": {}
}
```

使用方式：

- `business_output.path` 作为待入模空间数据。
- `semantic_mappings` 生成 canonical field mapping。
- `derived_fields` 和 `inferred_fields` 作为对象属性的语义增强字段。
- `quality` 写入 `twm_layer_binding.quality_snapshot` 和 `twm_state_version.quality_summary`。
- `lineage` 进入证据链和 data catalog lineage。

新增 TWM 输出资产也应注册到 `agent_data_assets`：

- 风险图层：`creation.tool = "territory_world_model.evaluate_rules"`
- 状态快照 manifest：`creation.tool = "territory_world_model.build_state"`
- 审计报告：`creation.tool = "territory_world_model.audit_report"`

## 11. 与 WorldModel v2.1 的集成

P2/P3 才接入 Paper9 v2.1，接口定位为 `ScenarioOptimizerAdapter`：

```text
TWM baseline state
        ↓
hard constraints / risk masks / protected areas
        ↓
WorldModel v2.1 Tool 4 plan
        ↓
candidate scenario
        ↓
TWM re-evaluate rules
        ↓
scenario metrics + evidence chain
```

关键原则：

- Paper9 输出是候选方案，不是审批结论。
- 所有候选方案必须重新经过 `RuleEvaluator`。
- 模型参数、输入 prepared_dir、ensemble_dir、ONNX 成员、输出 shapefile/summary 都写入 `twm_evidence_item(model_output)`。
- 违反 hard constraint 的候选方案可以保留用于对比，但必须标为不可行。

## 12. REST API 设计

建议 API 前缀：`/api/twm`，便于前端和工具层简洁调用。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/twm/projects` | 项目列表 |
| `POST` | `/api/twm/projects` | 创建项目 |
| `GET` | `/api/twm/projects/{id}` | 项目详情 |
| `POST` | `/api/twm/projects/{id}/layer-bindings` | 添加输入图层绑定 |
| `GET` | `/api/twm/projects/{id}/layer-bindings` | 图层绑定列表 |
| `POST` | `/api/twm/projects/{id}/build-state` | 构建 `S_t` |
| `GET` | `/api/twm/states/{id}` | 状态摘要 |
| `POST` | `/api/twm/states/{id}/evaluate-rules` | 规则校验 |
| `GET` | `/api/twm/states/{id}/rule-hits` | 命中清单 |
| `GET` | `/api/twm/rule-hits/{id}` | 命中详情与证据 |
| `PATCH` | `/api/twm/rule-hits/{id}/review` | 人工复核 |
| `GET` | `/api/twm/states/{id}/risk-layer` | 风险图层 GeoJSON/pending map payload |
| `POST` | `/api/twm/scenarios` | 创建方案 |
| `POST` | `/api/twm/scenarios/{id}/compare` | 方案指标对比 |

错误语义沿用现有 API：

- `401` 未登录
- `400` 参数非法或 DSL 校验失败
- `404` 项目/状态/命中不存在
- `409` 规则版本或状态版本冲突
- `503` 数据库、输入资产或外部模型不可用

## 13. ADK Toolset 设计

新增 `TerritoryWorldModelToolset`，首阶段工具：

| 工具 | 用途 |
|---|---|
| `twm_create_project` | 创建国土空间世界模型项目 |
| `twm_bind_layer` | 绑定数据资产或 MMFE semantic product |
| `twm_build_state` | 构建空间状态 `S_t` |
| `twm_evaluate_rules` | 执行规则约束校验 |
| `twm_explain_rule_hit` | 输出图斑级证据链 |
| `twm_review_hit` | 写入人工复核结论 |
| `twm_generate_audit_report` | 生成审计报告摘要 |

Agent 回答必须明确“模型输出仅供风险识别和复核，不替代审批结论”。

## 14. 前端设计

新增 `TerritoryWorldModelTab`，建议放在 DataPanel 的世界模型或治理相关区域。界面应是操作型，而不是宣传型。

首屏四块：

1. **项目与输入**
   - 项目选择/创建
   - 业务场景
   - 图层绑定表：角色、资产、时间版本、质量分、语义产品路径

2. **状态构建**
   - 构建按钮
   - 对象数、关系数、CRS、时间版本
   - 数据质量和字段映射异常

3. **规则校验**
   - active rule set
   - 规则数量、命中数量、严重级别分布
   - 一键加入地图

4. **证据与复核**
   - 命中列表
   - 图斑证据抽屉
   - 确认/驳回/需补充数据

P2 增加“方案比选”子页，展示 baseline、人工方案、模型候选方案的指标差异和约束违背率。

## 15. MVP 验收标准

第一阶段完成后，应能演示以下闭环：

1. 选择一个 MMFE 语义融合输出或普通 DLTB-like 图层作为 parcel 输入。
2. 绑定永久基本农田或生态红线图层作为控制线输入。
3. 构建 `twm_state_version`，生成 `twm_state_object` 和必要空间关系。
4. 启用至少两条规则：
   - `TWM-FARM-001`：建设/非农变化图斑不得触碰永久基本农田。
   - `TWM-ECO-001`：建设项目不得触碰生态保护红线。
5. 输出 `twm_rule_hit`、GeoJSON 风险图层、证据链详情。
6. 人工复核一条命中，复核状态和备注可追溯。
7. 输出一个审计摘要，能说明数据来源、规则版本、空间计算结果和复核结论。

## 16. 测试策略

| 层级 | 测试 |
|---|---|
| 单元测试 | DSL 解析、字段映射、规则条件判断、证据 payload |
| 空间测试 | 小 GeoDataFrame 的 intersects/within/area/distance |
| 集成测试 | MMFE semantic manifest -> TWM state -> rule hits |
| API 测试 | 鉴权、参数校验、构建状态、规则校验、复核 |
| 回归测试 | 现有 MMFE、标准平台、WorldModel v2.1 测试不回退 |

地理空间测试运行时如遇 PROJ 数据缺失，可使用：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/python -m pytest ...
```

## 17. 风险与控制

| 风险 | 控制 |
|---|---|
| 政策规则被模型过度解释 | 标准派生只生成 draft，启用必须人工审定 |
| 字段口径不统一 | 优先使用 MMFE semantic product 和标准平台 semantic hints |
| 空间计算性能不足 | P0 GeoPandas，P1 PostGIS 空间索引和 pushdown |
| 证据链不完整 | `twm_rule_hit` 必须有 source/rule/spatial evidence 才可标为 complete |
| 模型候选方案误导业务 | Paper9 输出全部作为 scenario candidate，必须经规则重检 |
| 数据涉密与出域 | 所有计算在本地/内网运行，不把图层内容发给外部 LLM |

## 18. 开发排序建议

优先级顺序：

1. `twm_*` schema、models、repository。
2. `semantic_loader.py` 和 `state_builder.py`，打通 MMFE manifest 到 `S_t`。
3. `rule_dsl.py` 和 `rule_evaluator.py`，先实现两条硬约束。
4. `evidence.py`，确保每条命中可追溯。
5. REST API 和 ADK Toolset。
6. 前端风险清单和证据抽屉。
7. 标准平台 `to_spatial_policy_rule` 派生。
8. P2/P3 接入 WorldModel v2.1 方案比选。

这个顺序能最快形成符合路线说明的可信 MVP，同时避免把研发重心过早放到黑箱优化算法上。
