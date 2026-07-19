# Apache OSSIE 对 GIS Data Agent 语义层建设的意义与价值评估

**评估日期**：2026-07-19<br>
**评估对象**：Apache OSSIE Core Specification、Ontology Specification、Roadmap、Expression Language、Geospatial Proposals<br>
**项目范围**：GIS Data Agent 统一语义层、统一元数据中心、空间运营本体、Agent Context 与 GWM 语义边界<br>
**资料获取方式**：通过本机 `127.0.0.1:7897` 代理访问 Apache OSSIE 官网、GitHub 仓库、Roadmap 和社区讨论。

---

## 1. 执行结论

Apache OSSIE 对 GIS Data Agent 的战略价值很大，但当前不适合作为 GIS Data Agent 内部唯一语义模型。最合适的定位是：

> 将 OSSIE 作为 GIS Data Agent 的开放语义交换标准和生态兼容层；内部仍保留更完整的 GIS Canonical Semantic Model、运营本体、治理合同和 GWM 语义。

综合评价如下：

| 维度 | 价值判断 |
|---|---:|
| 长期战略价值 | 9/10 |
| 当前语义体系收束价值 | 8/10 |
| 跨平台交换与生态价值 | 9/10 |
| 当前 GIS 语义完整度 | 4/10 |
| 直接替换内部权威模型 | 3/10 |
| 参与并影响标准的机会 | 9/10 |

一句话判断是：

> **必须跟进、应该接入、值得参与标准制定，但不能直接押注用它替换内部权威语义模型。**

如果 GIS Data Agent 仅将 OSSIE 当作一种 import/export 格式，价值约为 7～8 分；如果主动参与其地理空间扩展，形成空间语义 profile、双向转换器、conformance suite 和自然资源 domain pack，战略价值接近 9 分。

---

## 2. OSSIE 当前是什么

### 2.1 项目定位

Apache OSSIE 原名 Open Semantic Interchange，目标是在 Analytics、AI 和 BI 平台之间建立厂商中立的语义模型交换标准，使 Dataset、Field、Relationship、Metric 和 AI Context 可以跨工具复用，减少同一指标、维度和业务定义在不同平台中的重复定义与语义漂移。

它主要解决的是：

- 不同数据平台和 BI 工具使用不同语义模型格式；
- 同一个指标在多个系统中存在不同计算口径；
- AI Agent 缺少统一、结构化、可交换的业务语义上下文；
- 平台迁移和跨平台协作时，业务定义难以移植；
- 每个厂商都形成自己的 semantic lock-in。

### 2.2 当前成熟度

截至 2026-07-19：

- OSSIE 已于 2026-07-10 进入 Apache Incubator；
- 已发布稳定版本为 `0.1.1`，发布日期为 2025-12-11；
- 当前 core spec 为尚未发布的 `0.2.0.dev0`；
- `0.2.0.dev0` 明确标记为 draft，schema 在正式发布前可能变化；
- Ontology Specification 也处于 `0.2.0.dev0`；
- Expression Language 于 2026-07-15 标记为 Proposed Final；
- 项目已有 validator、JSON Schema、CLI 和多种语义格式转换器；
- 项目仍处于孵化和快速演进阶段，不能把 draft schema 直接固化为生产内部数据模型。

### 2.3 Core Specification 的主要对象

OSSIE Core Specification 当前主要包含：

```text
SemanticModel
  -> Dataset
      -> Field
  -> Relationship
  -> Metric
  -> AI Context
  -> Custom Extension
```

核心能力包括：

- 逻辑数据集及其物理 table/view/query 来源；
- primary key 和 composite unique key；
- 数据集之间的简单或复合外键关系；
- 可分组、过滤和参与指标表达式的字段；
- 业务指标及其计算表达式；
- ANSI SQL、Snowflake、Databricks、BigQuery、Tableau、MDX、MAQL 等方言；
- 面向 Agent 的 instructions、synonyms 和 examples；
- 厂商自定义扩展。

### 2.4 Ontology Specification 的意义

OSSIE 的 Ontology 草案已经超出普通 BI semantic model，开始定义：

- `EntityType`：人员、组织、地块、项目等现实对象类型；
- `ValueType`：带业务语义的字符串、整数、日期、金额、编码等；
- concept inheritance；
- binary 和 n-ary relationship；
- relationship multiplicity；
- entity identification；
- `derived_by` 派生规则；
- `requires` 业务约束；
- 从逻辑字段到 ontology object/link 的 concept mapping。

这意味着 OSSIE 的长期方向不仅是交换 BI 指标，还可能形成：

```text
Physical/Logical Data
 -> Analytical Semantic Model
 -> Conceptual Ontology
 -> AI/BI Consumption
```

这与 GIS Data Agent 正在建设的标准语义、领域本体、物理字段映射和 Agent Context 有直接关系。

### 2.5 当前生态信号

从官网、仓库和工作组可以看到以下生态参与者或转换对象：

- Snowflake；
- Databricks；
- Salesforce/Tableau；
- dbt Labs；
- CARTO；
- Denodo；
- GoodData；
- Omni；
- Honeydew；
- Apache Polaris；
- RelationalAI、ThoughtSpot、Starburst、Lightdash 等表达式工作组参与者。

CARTO 已公开表示，正在把 OSSIE 用于 BigQuery、Snowflake 和 Databricks 之上的 AI Agent 生产语义层。这说明 OSSIE 不只是概念规范，已经出现真实 Agentic GIS 使用场景。

---

## 3. OSSIE 当前没有解决的问题

OSSIE Roadmap 明确承认当前仍需要补齐：

- metric grain、aggregation semantics 和 metric dependency；
- relationship cardinality 和复杂关系；
- 逻辑 Dataset 与物理 table/view/query 的进一步解耦；
- reusable dataset、relationship 和跨模型组合；
- 标准语义查询语言；
- semantic query 到 execution plan/SQL 的 reference compiler；
- 稳定 identifier 和 semantic version；
- governance、certification、validation 和 access control；
- dimension hierarchy、calendar 和完整时间语义；
- unit、currency、PII、confidentiality 等类型信息；
- 正式进入核心规范的地理空间字段、空间关系和地理层级。

因此，OSSIE 当前是一个具有重要生态潜力的开放语义交换规范，而不是完整的企业语义平台、统一元数据中心、Ontology Runtime 或语义查询执行引擎。

---

## 4. GIS Data Agent 当前语义体系的现实情况

GIS Data Agent 不是没有语义能力，而是同时存在多种语义模型和权威来源。

### 4.1 MetricFlow-compatible Semantic Model

`data_agent/semantic_model.py` 已经定义 MetricFlow-compatible GIS 扩展模型，包括：

- entities；
- categorical/time/spatial dimensions；
- measures；
- metrics；
- source table；
- SRID 和 geometry type；
- 从 PostGIS information schema 自动生成草稿模型。

但当前实现存在以下局限：

- `source_table` 仍是物理字符串，不是稳定 ResourceURN/Version 引用；
- relationships 没有成为主要模型对象；
- validation 只覆盖少量枚举和必填字段；
- 更新时覆盖原 YAML，仅把整数 version 加一；
- 没有保存不可变版本历史；
- 没有统一模型 diff、compatibility、promotion、release 和 rollback；
- 与独立 semantic registry、metric registry 和 ontology package 没有统一写权威。

### 4.2 Spatial Semantic Registry

`data_agent/semantic_layer.py` 和相关 migration 又维护：

- table/source description；
- table/column aliases；
- semantic domain；
- unit；
- geometry type 和 SRID；
- value semantics；
- semantic hints；
- region groups；
- spatial operation synonyms；
- metric templates；
- natural-language semantic resolution。

这套能力对 NL2SQL 和 Agent grounding 有直接价值，但与 `agent_semantic_models` 存在字段、指标和语义上下文重叠。

### 4.3 独立指标注册表

`agent_semantic_metrics` 又单独保存：

- metric name；
- definition；
- domain；
- description；
- unit；
- aliases；
- owner。

因此同一指标可能同时存在于：

```text
semantic_catalog.yaml metric_templates
agent_semantic_metrics
agent_semantic_models.metrics
MMFE optimization objectives
GWM/TWM metrics
```

如果没有统一 identity/version/authority，长期必然产生指标口径漂移。

### 4.4 MMFE Semantic Ontology Package

`data_agent/fusion/semantic_ontology.py` 已经形成更丰富的 MMFE ontology package，包括：

- standard roles；
- object types；
- fields；
- semantic keys；
- value domains；
- standard sources；
- relation types；
- rules；
- optimization objectives；
- governance contract；
- consumption contract；
- TWM state requirements 和 runtime bindings。

它在标准来源、规则、目标和 GWM/TWM 消费方面明显超出 OSSIE Core，但目前又形成了一个独立 schema。

### 4.5 核心问题

当前真正的问题不是缺少语义功能，而是：

> MetricFlow YAML、semantic registry、metric registry、static catalog、standards ontology、MMFE ontology 和 GWM contracts 之间没有统一的 canonical identity、不可变版本和 projection 关系。

OSSIE 的最大价值正是在这里：它可以成为统一语义交换面和外部兼容合同，帮助内部模型收束，但不能直接承担全部内部语义。

---

## 5. OSSIE 对 GIS Data Agent 的主要价值

### 5.1 统一分析语义交换合同

Dataset、Field、Relationship、Metric 和 AI Context 可以成为以下消费者之间的共同语言：

- SQL/NL2SQL；
- Notebook；
- BI 与 Dashboard；
- Data API；
- Agent 和 MCP tool；
- 数据资产门户；
- 外部云数据平台；
- 数据产品和 Agent Context projection。

这样可以避免每个消费者分别定义一套字段、指标、join 和别名。

### 5.2 降低多引擎和多平台锁定

GIS Data Agent 的目标架构需要支持：

- MinIO + Iceberg；
- Spark/Sedona；
- Flink；
- PostGIS；
- DuckDB/Spatial；
- Azure 等云平台能力；
- 未来其它云仓和 BI 平台。

OSSIE 的多方言表达式和 converter 机制，可以让同一业务指标和逻辑字段投影到不同执行环境，减少把业务语义绑定在某个计算引擎或 BI 工具中的风险。

### 5.3 为 Agent 提供结构化、可移植的上下文

当前很多 Agent 系统通过 prompt 临时拼接 schema、别名和指标解释。OSSIE 可以让 Agent 消费发布后的结构化语义模型：

```text
User Question
 -> authorized semantic model selection
 -> dataset/field/relationship/metric resolution
 -> verified semantic plan
 -> engine-specific execution plan
 -> SQL/PostGIS/DuckDB/Spark execution
 -> evidence-bound answer
```

但是 `ai_context` 只能作为使用提示，不能成为以下内容的权威来源：

- 权限；
- 业务规则；
- 法规结论；
- 数据质量；
- 模型适用范围；
- 高风险 Action 授权。

这些必须由 Metadata、Policy、Standards、Evidence 和 Runtime Control Plane 提供。

### 5.4 连接分析语义与领域本体

OSSIE Ontology 的 Concept、Relationship、Requires、DerivedBy 和 Concept Mapping 与 GIS Data Agent 的需求高度契合：

- 一个物理表字段可以映射到标准概念；
- 一个现实对象可以由多个字段或关系识别；
- 物理 schema 可以变化，领域概念保持稳定；
- 不同城市、部门或数据源的同义概念可以映射到共同 ontology；
- Agent 可以从业务概念导航到正确 Dataset、Field、Metric 和 Relationship。

这对地块、项目、行政区、规划分区、生态红线、耕地、遥感观测和治理事件的跨源融合具有直接价值。

### 5.5 提供标准影响力机会

OSSIE 的 geospatial support 尚未固化，而 GIS Data Agent 已经积累了：

- geometry 和 CRS；
- topology 和 spatial relationship；
- vector/raster/remote sensing；
- spatial hierarchy；
- natural-resource standards；
- spatial rules 和 evidence；
- MMFE；
- GWM/TWM state/action semantics。

这使 GIS Data Agent 不仅能采用 OSSIE，还可能成为其地理空间语义扩展的重要贡献者。

---

## 6. OSSIE 与 GIS Data Agent 语义层的覆盖关系

| GIS Data Agent 语义层次 | OSSIE 当前覆盖 | 判断 |
|---|---|---|
| 物理/技术元数据 | Dataset source、Field expression 局部覆盖 | 不替代统一元数据中心 |
| 分析语义 | Dataset、Field、Relationship、Metric | 主要复用价值 |
| AI grounding | `ai_context`、synonym、example | 可作为 context projection，不是权威规则 |
| 领域本体 | `0.2` Ontology draft 有 Concept/Relation/Rule/Mapping | 值得跟进和试验 |
| GIS 空间语义 | Roadmap/Discussion 阶段 | 当前必须扩展 |
| 数据标准与值域 | 可通过 Concept/ValueType/Requires 部分表达 | 标准版本、来源和证据仍需内部合同 |
| Governance/Policy/Lineage | Roadmap hook，非完整能力 | 由 Metadata Control Plane 负责 |
| Operational Ontology | 无 Object State/Action/Function/ChangeSet 完整合同 | 必须由 GIS Data Agent 扩展 |
| DataOps/AgentOps | 不覆盖 | 由平台运营层负责 |
| GWM | 不覆盖 State/Action/Transition/Outcome | 必须保持独立 GWM contract |

---

## 7. 推荐目标架构

```text
GIS Data Agent Metadata Control Plane
ResourceURN + Immutable ResourceVersion + Authority
                       |
                       v
GIS Data Agent Canonical Semantic Model
Dataset / Field / Metric / Relationship
Concept / ValueDomain / Rule / Standard / Evidence
SpatialDescriptor / TemporalDescriptor
Operational Object / Action / Policy
GWM State / Action / Transition Binding
                       |
            versioned read projections
                       |
       +---------------+----------------+
       |               |                |
       v               v                v
 OSSIE Profile   Agent Context     Catalog/SDK/API
 import/export   MCP/NL2SQL/BI     Search/Lineage
       |
       v
dbt / Snowflake / Databricks / CARTO / external platforms
```

### 7.1 权威边界

- PostgreSQL Metadata Control Plane 继续作为资源身份、版本、owner、policy、quality、lineage 和 lifecycle 的唯一写权威；
- Canonical Semantic Model 是 GIS Data Agent 内部的语义写权威；
- OSSIE 文档是从 canonical model 生成的版本化 projection；
- OSSIE import 必须先解析、验证、生成 changeset，再进入 canonical model；
- OSSIE、MetricFlow、dbt、STAC、MCP schema 和 Agent Context 都不能成为第二个自由写权威；
- 外部导入无法完整表达的内容必须进入 loss report，禁止静默丢失。

### 7.2 为什么不能直接以 OSSIE YAML 为内部权威

1. `0.2.0.dev0` schema 尚未稳定；
2. stable identifier、immutable version 和 governance 仍在 Roadmap；
3. GIS 类型和关系仍处于讨论阶段；
4. `custom_extensions.data` 是 JSON string，不适合作为内部强类型模型；
5. OSSIE 不包含 DataContract、Quality、Lineage、Policy、SLO、Evidence 和 Action；
6. OSSIE 没有 GWM 的 State/Action/Transition/Outcome；
7. 直接采用会让 GIS Data Agent 的语义上限受制于一个仍在快速演化的交换规范。

---

## 8. GIS 空间语义扩展建议

### 8.1 OSSIE 社区当前提案

CARTO 推动的讨论已经包含：

- `point`、`line`、`polygon`、`raster`、`spatial_index`；
- SRID；
- H3、Quadbin、S2、Geohash；
- spatial index resolution 和 rollup resolution；
- geographic level 和 geographic hierarchy；
- `ST_CONTAINS`、`ST_INTERSECTS`、`ST_DWITHIN` 等空间 join；
- 空间层级聚合方法。

这些方向与 GIS Data Agent 高度一致，应该积极支持。

### 8.2 GIS Data Agent 应补充的内容

建议 GIS Data Agent 提议一套 OGC-aligned spatial profile，至少增加：

- MultiPoint、MultiLineString、MultiPolygon、GeometryCollection；
- Z/M dimensionality；
- geometry/geography 区分；
- CRS authority/code/WKT2；
- axis order；
- horizontal/vertical CRS；
- coordinate epoch 和 dynamic CRS；
- linear/angular/area unit；
- DE-9IM relationship；
- distance predicate 和 distance unit；
- CRS transform requirement；
- geometry validity 和 topology constraint；
- raster band、nodata、resolution、grid alignment 和 overview；
- point cloud、mesh、trajectory 和 moving object；
- observation time、valid time 和 transaction time；
- spatial accuracy、resolution、scale 和 applicable extent；
- OGC API、GeoSPARQL、STAC、GeoParquet、COG 和 3D Tiles 映射。

### 8.3 临时扩展策略

在 OSSIE spatial proposal 进入稳定 core 之前，可以定义：

```yaml
custom_extensions:
  - vendor_name: GIS_DATA_AGENT
    data: '{
      "profile": "gda.spatial.v1",
      "resource_urn": "urn:gda:dataset:land_parcel",
      "resource_version": "...",
      "spatial_data": {
        "type": "multipolygon",
        "crs": {"authority": "EPSG", "code": 4490},
        "dimensions": "XY",
        "validity_rule": "OGC_SIMPLE_FEATURES"
      }
    }'
```

内部不能直接保存这段自由 JSON string，而应使用强类型 `SpatialDescriptorVersion`，仅在 OSSIE serializer 中转换为上述格式。

---

## 9. OSSIE 与 GWM 的边界

OSSIE 可以为 GWM 提供：

- Dataset 和 Field 语义；
- Metric 和单位；
- 领域 Concept；
- Relationship；
- Logical-to-Ontology Mapping；
- Agent 可用的语义上下文。

但 OSSIE 不能表达完整 GWM：

```text
State
Action
Transition
Exogenous Context
Constraint
Uncertainty
Rollout
Objective
Evidence Grade
Outcome
```

正确关系应是：

```text
OSSIE-compatible Semantic Product
 -> GIS Canonical Concepts and Spatial Bindings
 -> GWM State Builder
 -> GWM State/Action/Transition Contract
 -> Scenario/Planner/Outcome
```

OSSIE 是 GWM 上游的开放语义入口之一，不是 GWM 内核。

---

## 10. 分阶段实施建议

### 阶段 1：Crosswalk 与 ADR

新增架构决策：

> `OSSIE as Semantic Interchange Profile, not Canonical Authority`

建立当前对象到 canonical model 和 OSSIE 的 crosswalk：

| 当前对象 | Canonical Object | OSSIE Projection |
|---|---|---|
| `agent_semantic_models` | SemanticModelVersion | SemanticModel |
| source table | LogicalDatasetVersion + PhysicalBinding | Dataset.source |
| entities | Entity/KeyDefinition | Dataset primary/unique key、Ontology Concept |
| dimensions | FieldDefinition | Field |
| measures/metrics | MetricDefinitionVersion | Metric |
| semantic registry | FieldAnnotationVersion | Field description/ai_context/extension |
| semantic hints | Guidance/RuleVersion | ai_context 或 extension |
| GIS metadata | SpatialDescriptorVersion | spatial proposal/extension |
| MMFE ontology | OntologyPackageVersion | Ontology + Mapping，部分投影 |
| operational action | ActionTypeVersion | 无直接映射 |
| GWM binding | GWMProjectionVersion | 无直接映射 |

### 阶段 2：最小双向转换 PoC

选择一个真实地类图斑 DataProductVersion，完成：

```text
Current MetricFlow YAML
 -> Canonical Semantic Model
 -> OSSIE 0.1.1 Profile
 -> OSSIE Validator
 -> Round-trip Import
 -> Structural/Semantic Loss Report
```

PoC 必须覆盖：

- dataset identity；
- composite key；
- categorical/time/spatial field；
- relationship；
- area/count/ratio metric；
- unit；
- synonym/AI context；
- SRID 和 geometry type extension；
- PostGIS 和 DuckDB 两种执行 projection。

### 阶段 3：Conformance 与 CI

在 CI 中增加：

- JSON Schema validation；
- unique name 和 reference validation；
- key/relationship consistency；
- expression parsing；
- dialect selection；
- round-trip loss test；
- metric result equivalence；
- PostGIS/DuckDB/Spark SQL compile test；
- policy-aware export；
- backward compatibility；
- OSSIE spec version matrix。

### 阶段 4：Agent 消费

不要直接把完整 OSSIE YAML 塞入 prompt。应编译为受权限控制的 Agent Context：

```text
Published SemanticModelVersion
 -> permission/filter
 -> task-relevant dataset/field/metric subgraph
 -> verified query/tool schema
 -> Agent Context Bundle
```

Agent 的执行仍必须走 typed query plan、policy、approved engine adapter、Run、Artifact 和 Audit。

### 阶段 5：社区参与

建议参与：

- Geospatial discussion #69；
- Spatial dimension discussion #114；
- Ontology & Semantic Interoperability working group；
- Catalog Integration working group；
- AI-native semantic layer working group；
- Governance/Identity/Validation working group。

对社区贡献的优先级：

1. OGC-aligned spatial descriptor；
2. spatial relationship 和 predicate semantics；
3. geographic hierarchy 与 aggregation behavior；
4. CRS、raster 和 accuracy；
5. natural-resource domain example；
6. PostGIS/DuckDB/Sedona converter；
7. spatial conformance test suite。

---

## 11. 采用决策

### 应立即开展

- OSSIE architecture spike；
- canonical-to-OSSIE crosswalk；
- 一个真实 GIS 数据产品的双向 converter；
- typed GIS extension；
- validator 和 loss report；
- 社区 geospatial proposal 参与。

### 暂时不应开展

- 用 OSSIE YAML 直接替换 PostgreSQL Metadata Control Plane；
- 将 `0.2.0.dev0` schema 作为内部稳定数据库结构；
- 一次性迁移所有 semantic registry 和 MMFE ontology；
- 把 `ai_context` 当作业务规则或安全策略；
- 因为 OSSIE 有 ontology 草案就取消 GIS Operational Ontology；
- 让 OSSIE 直接定义 GWM 内核合同。

### 正式扩大采用的触发条件

- OSSIE `0.2` 或后续版本稳定发布；
- stable identifier/version/governance 语义明确；
- geospatial core/profile 形成社区共识；
- converter round-trip 没有不可接受的语义损失；
- 至少两个外部平台的真实互操作能证明业务价值；
- GIS Data Agent canonical model 和 metadata authority 已稳定。

---

## 12. 最终判断

OSSIE 不会替 GIS Data Agent 自动建好统一语义层，但它可能成为未来数据平台、BI、数据产品和 Agent 之间最重要的开放语义交换标准之一。

对 GIS Data Agent 而言，它的意义不只是减少一种 YAML 格式转换，而是提供了三个长期机会：

1. 把内部已有但分散的 Dataset、Field、Metric、Relationship 和 AI Context 收束成稳定 canonical model；
2. 让语义资产在 PostGIS、DuckDB、Spark、云数据平台、BI 和 Agent 之间可移植；
3. 利用 GIS Data Agent 已有的空间语义、标准、本体、MMFE 和 GWM 积累，影响开放地理空间语义标准的形成。

GIS Data Agent 的长期护城河仍然是：

- 受治理时空数据产品；
- 空间领域与运营本体；
- 标准、规则和证据；
- Object-Action-Capability；
- DataOps/AgentOps；
- action-conditioned GWM；
- 真实 action-outcome 数据。

OSSIE 的角色是让这些能力的“公共分析语义部分”可以与外部世界交换，而不是降低 GIS Data Agent 的内部语义上限。

最终建议是：

> **采用 OSSIE 作为外部标准，建设 GIS Data Agent Canonical Semantic Model 作为内部权威，并主动推动 OSSIE 的地理空间扩展。**

---

## 13. 资料来源

### Apache OSSIE

- 官网：https://ossie.apache.org/
- GitHub：https://github.com/apache/ossie
- Core Specification：https://github.com/apache/ossie/blob/main/core-spec/spec.md
- Roadmap：https://github.com/apache/ossie/blob/main/ROADMAP.md
- Ontology Specification：https://github.com/apache/ossie/blob/main/ontology/ontology.md
- Expression Language：https://github.com/apache/ossie/blob/main/core-spec/expression_language.md
- Geospatial Support Discussion #69：https://github.com/apache/ossie/discussions/69
- Spatial Dimension Discussion #114：https://github.com/apache/ossie/discussions/114

### GIS Data Agent 本地证据

- `data_agent/semantic_model.py`
- `data_agent/semantic_layer.py`
- `data_agent/semantic_catalog.yaml`
- `data_agent/fusion/semantic_ontology.py`
- `data_agent/standards/gis_ontology.yaml`
- `data_agent/migrations/009_create_semantic_registry.sql`
- `data_agent/migrations/010_create_semantic_domains.sql`
- `data_agent/migrations/011_create_semantic_metrics.sql`
- `data_agent/migrations/055_semantic_models.sql`
- `data_agent/migrations/069_semantic_hints_and_value_semantics.sql`
- `docs/architecture-decisions/adr-002-unified-metadata-control-plane.md`

### 证据边界

- OSSIE `0.2.0.dev0` 属于 draft，不能作为稳定生产承诺；
- OSSIE Ontology 和 Geospatial 能力仍在演进；
- CARTO 的生产采用表述来自其 OSSIE 社区公开讨论；
- 本报告评估的是架构意义和采用策略，不代表已完成 GIS Data Agent 与 OSSIE 的代码集成或兼容认证。
