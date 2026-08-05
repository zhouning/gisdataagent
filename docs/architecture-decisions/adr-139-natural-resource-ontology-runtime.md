# ADR-139: 自然资源本体的权威模型、开放语义投影与运行时集成

**Status**: Accepted

**Date**: 2026-08-04

**Decision owners**: Data Platform, Data Governance, GIS Engineering, Cognitive Runtime

**Related decisions**: [ADR-089 标准版本绑定的智能落标合同](adr-089-standard-version-bound-application-contract.md)

> **Semantic modeling amendment**: ADR-140 supersedes the source-shaped class
> projection implied by this decision. ADR-139 remains authoritative for the
> package, publication and runtime architecture; ADR-140 is authoritative for
> class/individual boundaries and domain semantics.

## Context

GIS Data Agent 已有语义目录、XMI 浏览和知识图谱能力，但尚无 Cognitive Runtime 设计要求的版本化领域本体。自然资源“一张图”标准与 Enterprise Architect 仓库分别提供规范语义和项目模型，两者存在重复、缺项、命名漂移、断裂关系及字段类型问题，不能把任一来源直接当成可执行本体。

本体必须同时满足完整浏览、Agent 概念解析、字段对齐、关系遍历、约束验证、来源追踪、版本锁定、发布回滚和开放标准互操作。全国地块、栅格、轨迹及高频观测仍由 PostGIS、GeoParquet/COG 和对象存储承载。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| RDF Store 作为唯一写模型 | RDF/SPARQL 原生 | 审批、版本、事务和现有 Standards 权威形成双写 | 不选 |
| Neo4j 属性图作为唯一模型 | 浏览和多跳直观 | 开放语义、SHACL、标准交换及事务权威不足 | 不选 |
| PostgreSQL 权威模型 + 不可变包 + RDF 读投影 | 复用事务治理，兼容 RDF/SHACL，投影可重建 | 需要编译、对账和发布流程 | **选择** |

## Decision

### 1. 权威与版本

`gda_ontology` PostgreSQL schema 保存 ontology version、source、concept、property、relation、mapping、validation result 和 immutable package 元数据。发布版本及其内容不可更新或删除；回滚只切换 active package pointer。EA 仓库始终只读，不成为运行时依赖。

### 2. 编译和形式语义

编译器从只读 EA PostgreSQL 或受控 CSV export、标准 DOCX/ZIP 及人工维护 core vocabulary 产生确定性 JSONL/GZIP package、Turtle、SHACL 和 JSON-LD context。稳定 ID 不依赖中文标签；EA 对象保留 `ea_guid`、object id 和 package path，标准对象保留文档 digest、册号、章节和原始表代码。

RDFLib 负责确定性构建，pySHACL 负责发布门验证，OWL-RL 仅允许在离线编译阶段做有界物化。使用 SKOS、PROV-O、OWL、SHACL、GeoSPARQL 和 OWL-Time；LLM 相似度不能生成 `owl:sameAs`，严格代码/别名映射使用有方向、带来源的 SKOS mapping。

### 3. 运行时与查询

应用优先读取 PostgreSQL 已发布版本；数据库未配置或投影故障时，降级到仓库内固定且 hash 校验通过的 immutable package。Semantic Query Gateway 提供受认证、分页、预算受限的概念搜索、详情、字段、关系遍历和图视图，不向 LLM 或浏览器开放无界 SPARQL。

Apache Jena Fuseki/TDB2 是可选但生产就绪的只读 SPARQL 投影，通过独立 Compose profile 部署。它不接受业务事实写入，也不影响 PostgreSQL authority。投影 checkpoint 必须绑定 package hash，失败时运行时保持固定包只读能力。

### 4. Agent 和产品界面

Cognitive Runtime 通过只读 OntologyToolset 执行概念发现、稳定 ID 解析、关系遍历、字段对齐和约束检查。每个结果返回 ontology version、mapping 状态、来源和证据路径。

GIS Data Agent 工作台新增“本体模型”视图，按领域、来源和类型浏览完整模型，并提供检索、图遍历、字段/关系/溯源详情、映射覆盖率、发布校验和开放格式导出。大模型采用服务端分页和有界子图，前端不一次渲染全部节点。

### 5. 空间边界

RDF 保存 FeatureType、geometry kind、CRS 约束、空间关系语义和真实对象引用。批量 geometry、拓扑、空间连接、栅格计算和模型推演继续在 PostGIS、ArcPy、GeoParquet/COG 和 TWM 执行。

## Consequences

### Positive

- 标准条目、EA GUID、字段和关系可在同一稳定版本中追踪，但保留各自来源权威。
- Runtime、UI、SHACL 和 SPARQL 使用同一 immutable package hash，避免 prompt-only 语义漂移。
- RDF/Fuseki 可替换或重建，不形成第二个可写真值源。

### Negative

- 编译和发布增加了存储、CI 时间、投影对账与领域审定责任。
- 标准草案缺字段、同码不同定义和 EA 断裂引用仍需人工治理，不能由形式化工具自动消除。

### Mitigation

- 发布门拒绝重复稳定 ID、悬空关系、非法类型、hash 漂移和 SHACL 失败。
- 不确定映射保持 `candidate` 或 `conflict`，只有严格匹配及人工审定项可成为 `confirmed`。
- API 强制分页、遍历深度、节点数和查询超时预算。

## Revisit Triggers

- 跨组织 SPARQL federation、动态对象级策略或 OWL-RL 在线推理形成稳定 SLO。
- 单包规模超过 PostgreSQL FTS/trigram 或固定包 fallback 的容量基准。
- 多应用需要独立 Ontology SDK 和独立发布组织。
