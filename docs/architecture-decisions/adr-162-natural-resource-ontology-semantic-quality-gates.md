# ADR-162: 自然资源本体空间单元分离与语义质量发布门

**Status**: Accepted

**Date**: 2026-08-05

**Decision owners**: Natural Resource Domain Owner, Data Governance, GIS Engineering

**Related decisions**: [ADR-140 策划型自然资源领域本体与来源映射分层](adr-140-curated-natural-resource-domain-ontology.md)

## Context

V2.0.1 已将策划领域类与 EA、数据库和应用制品分开，但仍把`地块`直接建模为`土地`
的子类，使土地分类树同时混入资源类别与空间管理单元。模型也只有存在性约束，缺少逆属性、
函数属性、限定基数、逐概念来源处置、可执行能力问题和不可满足类报告。因此运行时可用并不
等于语义模型已经达到可审定、可解释的发布质量。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 保持 V2.0.1 类层级，只增加更多类 | 变更小 | 延续资源类别与空间单元混淆，新增类不能解决公理和来源缺口 | 不选 |
| 将每个来源表或标准条目提升为领域类 | 来源覆盖看似完整 | 来源结构继续污染领域层级，无法给出可靠推理 | 不选 |
| 分离资源、空间单元、状态、主体/角色、规则、限制和证据，并设置编译期质量门 | 语义边界清楚，公理和证据可执行验证 | 需要语义次版本和下游发布包重建 | **选择** |

## Decision

1. `Land` 的直接分类子类仅为 `AgriculturalLand`、`ConstructionLand` 和 `UnusedLand`。
2. `LandParcel`、行政区、规划单元、登记单元和管控边界归入独立的 `SpatialUnit` 层级；
   地块通过 `spatiallyRepresents` 连接土地，不再通过 `subClassOf` 混同二者。
3. 现状与规划状态、主体与角色、规则与限制、证据类型分别建模，并对互斥上位类声明
   `owl:disjointWith`。
4. 对象属性显式声明 `owl:inverseOf` 和适用的 `owl:FunctionalProperty`；关键业务关系使用
   OWL 2 限定基数约束，SHACL 继续负责实例记录完整性和允许的转换组合。
5. 每个策划类必须记录匹配到的标准/EA 证据，或显式记录证据缺口。所有来源候选必须进入
   accepted、mapped、deprecated 或 rejected 处置清单。
6. 不可变发布包必须包含可执行 SPARQL 能力问题、OWL 2 RL 策划核心推理报告、评审处置清单
   和完整性报告。任一自动质量门失败时禁止生成可发布包。
7. 这次概念边界调整发布为 `2.1.0`。语义未改变的概念继续使用稳定 IRI；版本信息通过
   `owl:versionIRI` 和 `owl:versionInfo` 表达。

## Trade-offs

- 接受 `LandParcel` 的父类变化会改变依赖旧层级的查询；调用方应通过空间表征属性连接土地。
- 接受 OWL 2 RL 发布门不是完整 OWL 2 DL 专家推理审定，完整性报告必须保留这一已知缺口。
- 接受来源精确标签匹配只能产生可追踪证据和映射候选，不能自动替代领域负责人确认。

## Consequences

- 土地分类问题不再把地块误计为第四类土地，空间单元可以独立扩展。
- Agent 和 SPARQL 客户端可区分现实/规划状态、主体/角色以及规则/限制/证据。
- 发布包能直接说明能力问题是否通过、是否存在不可满足类、哪些概念没有来源证据。
- V2.1.0 发布必须同步重建 PostgreSQL 权威源、Fuseki 投影、Protege 导出、OKF 引用和演示包。

## Revisit Triggers

- 领域负责人批准与当前分类或主体/角色边界冲突的新国家或地方标准。
- 外部 OWL 2 DL 推理器报告当前 OWL 2 RL 门未发现的不一致。
- 时态状态或空间规则需要引入 SOSA/SSN、OWL-Time 或 GeoSPARQL 的正式对齐公理。
