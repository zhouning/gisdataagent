# GIS Data Agent 产品能力需求分析与推进建议

日期：2026-08-13

最近更新：2026-08-18

本文同时记录从飞渡需求直接落入 GIS Data Agent 的产品增量。当前推进重点是可执行能力、合同和验证，不再扩充题库，也不分析宁夏 Excel。

## 1. 分析范围

本报告只分析以下两份文档及其对 GIS Data Agent 通用产品的要求：

- 《飞渡科技本体驱动产品架构范式与关键技术的范式 V2.1》
- 《飞渡科技本体驱动空间智能底座-建设任务体系 V3.0》

本报告不分析宁夏 Excel，不讨论项目报价、客户现场验收或宁夏数据适配，也不把客户实施工作当作 GIS Data Agent 已有产品能力。

评估状态统一使用四种口径：

- **已具备**：已有通用代码、稳定合同和测试，可进入产品基线；不等于已在任意客户环境完成生产验证。
- **受控试点**：主链路存在，但仍受后端、配置、数据、规模或局部治理边界限制。
- **计划建设**：有 ADR、局部实现或专项能力，但尚未形成统一产品合同。
- **外部依赖**：依赖客户数据、标准授权、基础设施或第三方系统，不应计入产品本体完成度。

## 2. 总结论

两份文档的方向大体正确，但不是可以直接照抄的产品规格。它们把 Palantir 产品范式、W3C 本体技术、数据平台能力、AI Agent、客户实施任务和性能愿景混在了一起。GIS Data Agent 应吸收其中的治理思想，不应复制其服务命名和绝对化技术结论。

对 GIS Data Agent 的实际判断如下：

| 评估口径 | 当前判断 | 含义 |
|---|---:|---|
| 文档中合理需求的基础能力可复用度 | **约 75%** | 本体、语义目录、受控查询、PostGIS/GIS、RAG/GraphRAG、双时态实体、精确实例 Link、实体沿革、带耐久入口的全数据包增量、版本、血缘、审批和运行审计已有较多基础 |
| T1-T12 作为统一产品能力的完成度 | **约 61%-65%** | 统一查询、双时态实体、来源身份、精确实例 Link、实体沿革和重庆全数据包增量已形成最小技术闭环；Action、全执行面安全和跨存储一致性仍未闭环 |
| 按文档完整蓝图达到生产级的就绪度 | **约 30%-35%** | 全局双时态、通用 Action runtime、全通道动态授权、混合存储一致性和规模 SLO 仍未闭环 |

因此，当前最重要的不是“再建一套本体”或“引入更多数据库”，而是把已有能力收口成四条产品主线：

1. **受治理的语义查询与证据编排**；
2. **通用 Action/Proposal 运行时**；
3. **统一 Subject-Purpose-Resource 安全执行面**；
4. **实体生命周期、沿革与双时态合同的业务域扩展**。

## 3. 文档中正确、但需要产品化改写的需求

### 3.1 应保留的产品原则

| 原文方向 | 判断 | GIS Data Agent 的正确产品表述 |
|---|---|---|
| 本体连接数据、逻辑、动作和安全 | **方向正确** | 本体负责稳定语义合同；动作、事务和安全由独立运行时实现并引用本体版本，不能把 RDF/OWL 本身说成操作系统 |
| Object、Link、Action、Function、Interface 五基元 | **适合作为产品元模型** | 应落为版本化定义和 SDK/API 合同；不要求所有内容都存入 RDF，也不要求复刻 Palantir 内部实现 |
| 空间运算交给确定性工具 | **正确** | LLM 负责理解和编排，PostGIS、GDAL、ArcPy、栅格/优化引擎负责可复现计算 |
| Proposal Pattern 和人工审批 | **正确** | 高风险变更由 AI 提案，人确认，受治理 Action 执行；低风险只读查询不必强制走人工审批 |
| OWL + SHACL + SKOS + RDF | **正确但各司其职** | OWL 表达领域语义，SHACL 做形状门禁，SKOS 管分类映射，RDF/JSON-LD 用于交换和读投影；运行时不默认做无界 OWL 2 DL 推理 |
| 混合路径建模 | **正确** | 核心域由专家策划，来源 Schema 和文档可由工具/LLM 产生候选，只有校验和审定后才能进入发布版本 |
| 权限、版本、血缘、审计从设计开始 | **正确且必须 P0** | 每次查询和 Action 均绑定主体、租户、目的、资源版本、策略决定和证据；关键策略故障 fail-closed |
| 本体框架与业务实例分离 | **正确** | 产品提供模型、查询、Action 和策略框架；行业包是可版本化扩展，客户业务规则不是底座硬编码 |

### 3.2 应调整的需求定位

PDF 的 T1-T12 不是同一层级的十二个“产品模块”，应重新分类：

| 类型 | 原任务 | 产品处理方式 |
|---|---|---|
| 产品核心 | T2、T5、T7、T8、T9、T10、T11 | 纳入 GIS Data Agent 产品路线图和版本合同 |
| 数据平台基础 | T1、T3、T4、T6 | 复用 Catalog、Ingest、Semantic、PostGIS、Ontology、Lineage 等底座能力，补齐产品入口 |
| 行业/部署适配 | T12 | 作为适配包和兼容性认证，不应混入核心产品完成度 |

Word 中的六个模块和 PDF 的 T1-T12 也有大量重叠。建议 GIS Data Agent 不建立六套相互独立的微服务项目，而采用三层产品架构：

```text
Agent 交互层
  意图理解 / 查询规划 / Proposal / 结果解释 / Evals
                     |
治理控制面
  Catalog / Ontology / Semantic Metric / Action Definition / Policy / Version
                     |
确定性执行面
  PostGIS / Lakehouse / GIS Tools / RDF Read Projection / RAG Evidence / External Systems
```

## 4. 文档中不准确或有风险的内容

| 原文表述 | 问题 | 建议修订 |
|---|---|---|
| “OAG 替代 RAG” | 本体查询不能替代非结构化文档证据；RAG 也不能表达可靠类层级、关系方向和写事务 | 改为本体查询、RAG、受控 SQL、指标查询和 GIS 工具按问题类型协作 |
| “LLM 永远不生成 SQL” | 与 GIS Data Agent 的 NL2Semantic2SQL 路线冲突，也混淆“生成候选”和“授权执行” | 允许生成候选 SQL，但必须经过 Schema grounding、AST 只读校验、参数化、权限、超时、行数和审计护栏 |
| “本体不可导出” | 与 OWL/RDF/SHACL/SKOS 标准路线直接冲突，形成不合理锁定 | 发布包、映射和校验结果应按合同可导出；运行时索引和商业实现可以保留内部细节 |
| 将 GB/T 40765-2021 作为可直接引用的首选上位本体 | 标准可指导建模，但不是拿来即用的企业上位本体运行包 | 作为标准依据和映射目标，由领域负责人设计项目 T-Box 和约束 |
| 网格码 + 不动产代码形成普适“一码管地”身份 | 网格是空间索引，不稳定表达跨时间、跨尺度和跨源实体身份；不动产代码也只覆盖特定对象 | 使用独立稳定实体 ID，保留源 ID、业务代码和网格索引为不同标识维度 |
| URI 支持跨库 JOIN | URI 只解决标识，不解决实体解析、数据类型、坐标、映射质量和执行计划 | 跨源连接必须有版本化映射、匹配证据、冲突处理和实际查询执行器 |
| OWL-Time、双时态和 Event Sourcing 混用 | 三者解决的问题不同，不能互相替代 | 分别定义时间语义词汇、valid/transaction time、事件账本、快照、更正和 as-of 查询 |
| 复杂查询超时后自动简化 | 可能静默改变问题语义并给出错误答案 | 只有预注册且证明语义等价的投影才可自动替代；非等价降级必须返回原因并让用户确认 |
| 写回 `<300ms` | 没有负载、数据量、网络、p95/p99、重复/丢失和故障恢复口径 | 定义分通道 SLO；事务提交、外部写回和 CDC 可见性应分别计时 |
| Action 七阶段中“事务副作用”和“写回源系统”分离不清 | 外部系统通常不能与本地事务原子提交，容易形成伪事务承诺 | 使用准入、幂等、事务/Outbox、外部副作用、回执、补偿/对账和审计状态机 |
| “权限动态传播”作为自然结果 | 血缘存在不代表策略会自动正确传播 | 必须定义策略继承规则、资源范围、冲突优先级、缓存失效和负向权限测试 |
| 任意开放 SPARQL 端点 | 无界查询、注入、资源耗尽和越权风险高 | Agent/浏览器使用类型化查询合同和白名单模板；开发者端点也要认证、预算和只读隔离 |
| “先建本体，再做 AI”作为绝对顺序 | 容易形成长期建模而没有用户价值验证 | 以高价值问题集驱动最小本体、查询和 Action 闭环，再迭代扩展 |
| “本体中不存在实体就不会幻觉” | LLM 仍可能误读、错连或错误总结已有事实 | 输出必须带版本、来源、查询计划、结果证据和不确定性；用 Evals 验证而不是口号保证 |

文档本身还有版本和编辑问题：Word 文件名是 V2.1，正文仍写 V2.0；PDF 出现“语义鸷沟”“鲮麓”“麒麺”等错字、国产 OS 行重复。发布产品需求前应先统一版本、术语和变更记录。

## 5. T1-T12 产品能力矩阵

下表评价的是通用产品能力，不评价任何特定客户项目。百分比是基于现有代码、ADR 和测试证据的工程估算，不是合同验收结果。

| 任务 | 当前产品状态 | 支撑度 | 已有证据 | 真正缺口 |
|---|---|---:|---|---|
| T1 资产盘点与语义差距 | **已具备/受控试点** | **70%** | 数据目录、接入、画像、质量、Semantic Source、血缘和标准平台已有实现 | 缺少统一的五维语义成熟度产品评分、组合视图和持续差距跟踪 |
| T2 上位/领域本体设计 | **已具备/技术基线** | **80%** | PostgreSQL 权威模型、不可变包、OWL/RDF/SHACL/SKOS、来源处置、能力问题和版本哈希；自然资源本体 2.3.0 已固定为开发基线 | 暂无专家签署，只能标记 `technical_baseline_unreviewed`；完整 OWL 2 DL 不是在线能力；来源 warning 要持续治理 |
| T3 时空数据实体化 | **最小通用合同已实现/受控试点** | **84%** | 空间接入、Schema/语义映射、几何与 CRS、融合、数据产品版本、稳定 EntityRef、来源身份自然键及有效时间解析；通用 authority 已支持原子批量，重庆 439 个地块实体和 16 个约束要素实体共 455 个实体/绑定已装载重放；合并、拆分、替代及来源身份沿革已接入统一 REST/Capability/MCP；全数据包 sealed plan 已联动实体校正/新增/激活/退役和来源版本证据，并发布耐久 REST/Capability/MCP reconciliation | 既有实体域迁移、复杂多源冲突裁决、任意客户包适配、异步大任务规模验证和规模 SLO |
| T4 时空与业务关系 | **最小通用合同已实现/受控试点** | **88%** | 类型化 Link、稳定端点、双时间轴、撤回/恢复/校正、来源/置信度、RLS、自环、基数及原子批量；重庆 472 次客户范围命中已展开为 492 次逐要素相交观测并聚合为 486 个稳定 Link，目标以 `layer + BSM` 精确到约束要素；全数据包计划先撤回失效 Link，再写实体/来源，最后校正/恢复/新增 Link 并退役消失实体，支持零变化、耐久计划预留和跨 REST/MCP 稳定重放 | 质量评测、更多关系类型、全局单事务、异步大任务规模验证和规模 SLO |
| T5 时态与生命周期 | **最小通用合同已实现/受控试点** | **72%** | 稳定 EntityRef、valid/recorded 双时间轴、append-only 事件、更正链、迟到事件、四类 as-of 查询和生命周期；新增 `N->1` 合并、`1->N` 拆分、`1->1` 替代，原子退役源实体并保存沿革成员、传播证据和 SHA-256 | 更多业务域适配、既有域迁移、归档、投影一致性和规模 SLO |
| T6 图谱与混合存储 | **受控试点** | **约 82%** | PostgreSQL 权威本体、PostGIS、Fuseki RDF、pgvector、S3 对象和 Spark/Iceberg 湖仓投影均已接入 source/target/checkpoint assessment、sealed repair plan、plan-bound checkpoint 与 PostgreSQL append-only authority；五类 provider 的 rebuild/delete/checkpoint、自动 authority 串联及 REST/Capability/MCP 均通过隔离真实环境验收；新增跨 Provider recovery state machine、federated coordinator、PostgreSQL aggregate ledger，以及绑定重庆数据、本体 2.3.0 和源快照的补偿候选方案/只追加权威；对象与湖仓绑定不可变版本/snapshot 证据 | 仍缺实体级权限、向量索引/召回/容量 SLO、五类真实 Provider 联动故障、客户规则驱动的变更型自动补偿/对账执行、备份恢复和真实多存储生产验收；不应默认要求 Neo4j/Milvus |
| T7 本体引擎与查询 | **已具备/受控试点** | **80%** | `semantic.query.execute@4.1.0` 已统一 Ontology、Metric、NL2SQL、GIS、RAG 的类型化路由、版本固定、预算和证据 envelope | 自然语言自动生成类型化计划、跨通道答案融合、授权义务传播和质量评测 |
| T8 业务本体建模框架 | **受控试点** | **60%** | 本体工作台、草稿命令、稳定 URI、append-only 变更、Diff、结构校验和 in-review 提交 | 草稿到完整发布/回滚尚未自动闭环；完整 OWL/SHACL 编辑、多人协同、模板包治理和 SDK 仍不足 |
| T9 Action 注册与运行时 | **部分具备** | **45%** | CapabilitySpec、PlatformRun、PolicyDecision、Approval、HITL、幂等、Outbox、审计和专项执行器已有较强基础 | 缺少面向所有业务域的 ActionDefinition/ActionVersion 注册、输入输出本体绑定、规则注入和统一回执/补偿合同 |
| T10 安全与治理 | **部分具备** | **45%** | RBAC、租户、SubjectContext、Purpose、PolicyDecision、字段脱敏、审批和审计已有实现 | 目的、标记、对象/行/列策略尚未覆盖每个查询/工具/导出通道；策略传播和负向测试不统一 |
| T11 OAG 智能服务 | **受控试点** | **65%** | 已形成“问题 -> 确定性路由 -> 版本资源 -> Policy -> 预算 -> 证据”的五通道只读查询合同；RAG 仅准入租户绑定、内容寻址的新文档 | 自动计划生成与澄清、跨通道答案融合、Proposal/Action 总线、跨通道质量/成本/延迟评测 |
| T12 标准与部署适配 | **产品基础 + 外部依赖** | **40%** | 标准平台、开放格式、容器/Kubernetes/离线接入等基础存在 | 国产 CPU/OS/数据库/中间件需要逐项兼容认证；不能通过文档声明视为已支持 |

简单平均约为 **66%**。考虑 T9、T10 和跨存储一致性对最终产品闭环的权重更高，统一产品完成度仍应按 **61%-65%** 管理，而不是按已有模块数量宣称 70% 以上。

## 6. 现阶段已有优势

GIS Data Agent 与两份文档的匹配点，不只是“有一个知识图谱”：

1. **本体权威和运行边界已经比较清楚。** PostgreSQL 是事务权威，不可变包用于发布/恢复，RDF/Fuseki 是可重建读投影；批量 geometry 留在 PostGIS，这比“所有数据进入图数据库”更合理。
2. **自然资源本体不是空壳，但发布状态需要对账。** 当前活动指针已绑定 2.3.0 包及内容哈希；该包包含 246 个领域类、5,284 个概念、6,588 个关系、537,245 条 RDF triples，8/8 能力问题通过。2,397 条来源 warning 需要治理，但不等同于本体逻辑错误。与此同时，2.3.0 的完整性报告仍标记领域专家审定待完成，产品不能把“活动版本”自动表述为“领域已批准版本”。
3. **结构化智能问数路线正确。** NL2Semantic2SQL 已有 Schema grounding、空间语义、AST 只读检查、LIMIT/预算和执行引擎边界，应该继续治理，而不是因文档一句“LLM 不生成 SQL”而删除。
4. **RAG 已存在且应保留明确边界。** 知识库支持 Word/PDF/文本切块、embedding、权限范围和 GraphRAG。它适合文档证据，不应成为 Catalog、Ontology 或业务事实的新权威。
5. **高风险动作底座不是从零开始。** PlatformRun、CapabilitySpec、PolicyDecision、Approval、幂等、事务性 Outbox、HITL 和审计可以成为通用 Action runtime 的底座。
6. **本体建模已经进入治理阶段。** 草稿基线、append-only 命令、稳定 URI、Diff、校验和 review 状态已实现；下一步是完成发布闭环，不是重写编辑器。

## 7. 需要推进的四条产品主线

### P0-A：统一语义查询与证据编排

目标不是创造“OAG”新孤岛，而是给现有 Ontology、Metric、NL2Semantic2SQL、GIS 和 RAG 一个共同的产品入口。

应形成的产品合同：

- 输入：用户问题、租户、主体、角色、目的、时间/空间范围和预算；
- 输出：选定通道、路由理由、版本绑定、权限决定、执行计划、证据引用、结果置信边界和降级说明；
- 原则：本体回答概念和关系，指标服务回答治理口径聚合，NL2Semantic2SQL 查询结构化明细，GIS 工具执行空间计算，RAG 提供文档证据；
- 禁止：超时后静默换通道或放宽语义；非等价替代必须让用户确认；
- 评测：路由准确率、答案正确率、引用完整率、权限泄漏率、p95 延迟、单次成本和失败可解释率。

完成定义：同一问题集可稳定说明“为什么走这个通道”，每个事实能回到资源版本和真实证据。

### P0-B：通用 Action/Proposal Runtime

复用现有 CapabilitySpec 和 PlatformRun，增加产品级业务 Action 合同：

- `ActionDefinition/Version`：输入/输出对象、前置条件、副作用、风险、策略、审批、幂等和补偿声明；
- `Proposal`：问题、输入快照、证据、候选动作、风险和不确定性；
- `ActionRun`：准入、策略决定、审批、执行、外部回执、补偿/对账和最终证据；
- Action 与本体稳定 ID/版本绑定，但执行状态和事务不写入 OWL；
- 先选一个低风险只读/派生 Action 和一个需审批的写 Action 做纵向闭环，再扩展行业模板。

完成定义：同一 Action 可由 Web/API/MCP/Agent 调用同一合同；重试不重复副作用；策略或审计不可用时关键动作被阻断。

### P0-C：统一安全执行面

把现有局部安全能力提升为所有通道共用的执行前置条件：

- 统一 `SubjectContext`：租户、用户/Agent/工作负载、角色、目的、委托链和 trace；
- 统一资源范围：数据产品版本、本体版本、字段、空间范围、时间范围、知识库和 Action；
- 策略输出允许/拒绝、行列过滤、脱敏、审批义务、结果上限和有效期；
- 查询、下载、地图、报告、工具和 Action 使用同一策略语义；
- 建立负向测试矩阵，重点验证跨租户、错误目的、隐藏字段、空间越界、策略服务故障和审计故障。

完成定义：任何 Agent 不能获得超过其代表用户的权限；策略故障不会退化为放行。

### P1：扩展实体生命周期与双时态

在已建立的最小通用时间与沿革合同上继续扩展，不把所有历史能力都称为 Event Sourcing：

- 稳定实体 ID 与来源身份已经分离，合并、拆分、替代和身份沿革已有通用权威；下一步迁移既有实体域并补复杂冲突裁决；
- 事实记录 `valid_from/valid_to` 与 `recorded_at/superseded_at`；
- 生命周期事件包含原因、依据、操作者、来源版本和更正关系；
- 提供 current、valid-at、known-at 和双条件 as-of 查询；
- 明确迟到数据、更正、撤销、重放、快照和空间几何版本策略。

完成定义：同一测试对象能回答“当时现实是什么”和“系统在当时知道什么”，且更正不会覆盖原始证据。

## 8. 后续产品增量

四条主线稳定后，再推进以下能力：

| 增量 | 建议内容 | 不应提前做的事 |
|---|---|---|
| Ontology Studio 完整发布链 | 草稿审阅、完整 SHACL/能力问题/OWL-RL/来源门禁、SemVer 发布、回滚和影响分析 | 不开放浏览器直接修改活动本体 |
| Entity/Relation Service | 稳定 ID、匹配候选、人工审定、关系版本、质量和来源证据 | 不把网格码当主键，不让 LLM 自动产生 `owl:sameAs` |
| RAG Evidence Projection | 文档版本、ACL、删除传播、混合检索、引用验证和离线评测 | 不把向量库升级为第二权威系统 |
| Tool Registry | GIS/统计/优化工具的版本、参数 Schema、资源预算、确定性声明和结果证明 | 不把所有工具都称为 Action；只读计算与业务写动作要区分 |
| SDK 与行业包 | 从同一 OpenAPI/CapabilitySpec 生成 SDK；行业本体/Action/Policy 包独立版本 | 不先承诺完整 TypeScript/Java OSDK 再补服务合同 |
| 规模与部署认证 | 按真实负载验证 PostGIS、RDF 投影、向量检索、CDC、备份和恢复 | 不以单个 `<300ms` 数字替代分位数和恢复指标 |

## 9. 建议的产品版本顺序

### 近期：收口已有能力

- 继续扩展统一查询/证据 envelope；当前 Ontology、Metric、NL2SQL、GIS 已接入，RAG 因缺少版本化文档 locator 仍 fail-closed；
- 扩展已落地的 PostGIS 类型化操作和真实引擎集成回归；
- 统一 SubjectContext、Purpose 和资源版本引用；当前 GIS Run 已绑定租户、主体、目的、不可变来源版本和两个 source fingerprint；
- 盘点 CapabilitySpec/PlatformRun 与业务 ActionDefinition 的字段差距；
- 对账本体 2.3.0 的活动指针与领域审定状态；在产品界面分别呈现技术质量门、领域批准状态、来源 warning 和发布证据。

### 中期：形成两个完整闭环

- 完成查询编排闭环：计划、准入、执行、证据、回答、审计和评测；
- 完成 Action 闭环：Proposal、策略、审批、幂等执行、回执和补偿；
- 让所有查询和工具接入统一安全执行面；
- 扩展已实现的双时态对象、as-of API 和沿革事务，用更多真实变化数据验证既有域迁移、归档及跨存储投影。

### 后期：扩展和规模化

- 完成本体草稿到不可变发布的自动化门禁；
- 扩展行业包、SDK、关系实例服务和 RAG Evidence Projection；
- 在明确负载和部署拓扑后认证国产环境、CDC、并发、备份和灾备 SLO。

## 10. 当前不建议立项的内容

- 不重建自然资源本体；应继续治理和消费现有 2.3.0 权威包。
- 不以“对标 Palantir”为由拆出 OMS、OSS、Funnel 等同名微服务。
- 不强制引入 Neo4j、JanusGraph、ArangoDB 或 Milvus；先用问题集证明现有存储不满足需求。
- 不取消 RAG，也不让 RAG 接管结构化事实和本体权威。
- 不停止 NL2Semantic2SQL；应继续增强候选生成后的治理和证据。
- 不先做六套完整行业本体模板；先验证模板发布、继承、兼容和升级机制。
- 不承诺任意 SPARQL、完整在线 OWL 2 DL 推理或固定 `<300ms` 写回。
- 不把客户数据盘点、国产化现场适配和具体业务规则算作核心产品已经完成。

## 11. 决策建议

GIS Data Agent 的下一阶段产品定位建议为：

> 一个以 Catalog、Ontology、Semantic Metric 和版本化数据产品为事实基础，以 PostGIS/GIS、受控查询和文档证据为确定性执行面，以 Proposal、Policy、Approval、ActionRun 和 Evidence 为操作闭环的受治理 GIS Agent 平台。

这比“本体替代 RAG”更准确，也比“复制一个 Palantir Ontology”更符合现有代码资产。产品推进的核心指标不应是本体类数量、三元组数量或 Agent 工具数量，而应是：固定业务问题能否被正确路由、正确授权、确定性执行、引用真实证据，并在高风险动作中得到可恢复、可审计的结果。

## 12. 主要代码与架构证据

- `docs/architecture-decisions/adr-139-natural-resource-ontology-runtime.md`：PostgreSQL 权威、不可变包、RDF 读投影和空间边界；
- `docs/architecture-decisions/adr-153-ontology-conversation-semantic-gateway-okf.md`：类型化本体查询、白名单 SPARQL、版本和证据；
- `docs/architecture-decisions/adr-162-natural-resource-ontology-semantic-quality-gates.md`：领域边界和发布质量门；
- `docs/architecture-decisions/adr-185-governed-ontology-model-drafting.md`：草稿、Diff、结构校验和发布边界；
- `data_agent/ontology/`、`data_agent/api/ontology_routes.py`：本体包、查询引擎、读投影和 API；
- `data_agent/nl2sql_grounding.py`、`data_agent/sql_postprocessor.py`：受控 NL2Semantic2SQL；
- `data_agent/metric_query.py`：治理指标定义和确定性投影选择；
- `data_agent/knowledge_base.py`、`data_agent/graph_rag.py`：文档 RAG 与 GraphRAG；
- `data_agent/capability_registry.py`、`data_agent/platform_contracts.py`、`data_agent/platform_gateway.py`：能力、运行、策略、审批、幂等和证据底座；
- `data_agent/hitl_approval.py`、`data_agent/audit_logger.py`：高风险人工确认和审计；
- `data_agent/temporal_entity_authority.py`、`data_agent/entity_link_authority.py`、`data_agent/entity_lineage_authority.py`：追加式双时态实体、来源身份、实例 Link、实体沿革及关系传播权威；
- `data_agent/chongqing_entity_link_baseline.py`：重庆客户数据与自然资源本体 2.3.0 的版本锁定关系基线；
- `data_agent/migrations/162_entity_authority_batch_ingest.sql`：四类 1..500 项有界、批内原子、网关最小权限批量函数；
- `data_agent/migrations/164_entity_lineage_authority.sql`：合并、拆分、替代、Link 传播和来源身份重定向的原子、追加式数据库合同；
- `data_agent/chongqing_entity_link_loader.py`：固定基线的 7 批原子装载、跨批续跑、全量幂等重放和不可变装载回执；
- `data_agent/entity_authority_batch.py`、`data_agent/api/platform_gateway_routes.py`：四类强类型 authority 批量的统一 REST/Capability、租户/身份/指纹门禁和状态指纹响应；
- `docs/analysis/gis-data-agent-rag-boundary.md`：RAG 作为 Evidence Projection 的边界。

## 13. 本轮已落地的 GIS 执行增量

本轮不是文字层面的规划，已形成以下可执行产品切片：

| 飞渡需求映射 | 已落地能力 | 当前边界 |
|---|---|---|
| T7 时空查询、T11 Agent 工具编排 | 统一 `semantic.query.execute@4.1.0` 支持五通道类型化请求，确定性路由至 Ontology、Metric、NL2SQL、GIS 或 RAG adapter | 自动计划、跨通道答案融合及统一质量评测仍不完整 |
| 确定性空间计算 | 正式 Algorithm Registry 管理版本锁定的 PostGIS 基础算法；新增受控五节点工作流，串联 `intersection`、`buffer`、`spatial_filter`、`area_filter`、`spatial_group_by`，输出 GeoJSON、行政区统计和执行证据 | 当前仅注册一个多步模板；尚无栅格、网络分析和通用空间统计模板 |
| T3/T4 版本化实体与关系计算 | 输入绑定 active immutable ResourceVersion、geometry column、SRID、authority/physical fingerprint；稳定 EntityRef、来源身份、双时态 Link、四类原子批量和统一 REST/Capability/MCP 已落地；新增合并、拆分、替代及 Link/来源身份沿革事务；重庆固定基线已精确到约束要素，并完成实体/来源/Link 联动的全数据包增量、耐久同步入口和可恢复异步任务；跨存储 checkpoint、五类 provider、federated recovery/aggregate ledger 和补偿候选方案已落地 | 尚缺既有实体域迁移、复杂冲突裁决、任意客户包适配、跨阶段全局单事务、客户规则驱动的变更型补偿执行、真实联动故障和规模 SLO |
| T9 可运行能力 | `PlatformRun`、execution-plan Artifact、transactional outbox、provider receipts、result Artifact，以及运行中 PostGIS backend cancellation 和 reconciliation | `not_found/unknown` fail-closed 进入 `reconciling`；自动对账只追加观察，不推断取消成功；有限重试后创建 DataIncident/Alertmanager 告警，并支持可信 provider 终态或平台运维人工 fail-closed 处置 |
| T10 安全与治理 | 租户/主体/角色/目的、owner 边界、精确 PostGIS workload 身份、预算、repeatable-read 只读事务、结果审计 | 尚未覆盖所有 GIS 算法和所有导出通道的统一策略 |
| 可部署执行面 | 独立 GIS command worker，支持执行/取消/对账三条独立消费通道、租约恢复、配置校验、PostGIS/结果存储探针、health/liveness 和优雅停止 | 未在客户生产拓扑部署，不代表生产 SLO 已认证 |
| 结果可信访问 | 验证 Run、Observation、Artifact、immutable S3 version 和结果字节后签发短期 URL | 本地结果存储仅用于轻量环境，不开放为 API 下载路径 |

对应主要实现为：

- `data_agent/gis_algorithm_registry.py`：不可变算法发布规格、生命周期、默认版本、输入角色、参数/预算合同和 registry/spec fingerprint；
- `data_agent/gis_analysis_execution.py`：类型化计划、精确算法版本绑定、immutable source binding、Run 准入、provider receipt、pre-start cancel 和运行中取消证据合同；
- `data_agent/migrations/158_gis_analysis_run_authority.sql`：GIS Run、Artifact、执行/取消 outbox、精确 backend binding、取消回执、RLS 和预算数据库门禁；
- `data_agent/migrations/159_gis_analysis_reconciliation_authority.sql`：append-only 对账观察、有限重试/deadline、统一 DataIncident/通知 outbox、迟到终态收敛和人工 fail-closed 处置；
- `data_agent/gis_analysis_command_consumer.py`：read-only PostGIS provider、结果预算、原子 backend cancellation、回执重放和可恢复 command delivery；
- `data_agent/gis_analysis_command_worker.py`：可部署 worker、独立 cancel/reconciliation monitor、执行/取消账号隔离和依赖探针；
- `data_agent/api/gis_analysis_routes.py`：算法发现、Run/结果访问和人工 reconciliation resolution API；
- `data_agent/gis_analysis_result_access.py`：immutable S3 结果验证、短期签名访问和 security ledger；
- `data_agent/governed_query.py`、`data_agent/mcp_tool_registry.py`：统一查询和 MCP GIS 请求入口；
- `data_agent/capability_registry.py`：`gis.analysis.execute@1.2.0` 可取消长任务能力合同。
- `data_agent/gis_workflow_proposal.py`：真实 LLM 语义提案、严格 JSON 合同、原问题数值 grounding、歧义确认和 HMAC 证明；
- `data_agent/gis_workflow_algorithm_registry.py`、`data_agent/gis_workflow.py`：五节点 DAG、算法版本指纹、数据源/字段/CRS grounding、只读 PostGIS 编译与结果证据；
- `frontend/src/components/datapanel/GisWorkflowTab.tsx`：需求输入、模型证据、歧义确认、DAG 预览、执行和证据下载的用户闭环。

本轮已在本机 PostGIS 3.4 容器的隔离临时数据库中从零执行全部 159 个 migration，最终 catalog/database fingerprint 均为 `553f3ed35d77a91f5bc71dbbd8071c5a2b5a7078e9e81e78ba382d209f2b7012`；并实际执行 buffer、clip、intersection，验证 canonical GeoJSON 和只读事务。运行中取消专项验证使用长时间 `pg_sleep` 会话：错误 application/backend binding 返回 `NOT_FOUND` 且不影响目标查询，完整 binding 返回 `SIGNALLED`，目标连接收到 SQLSTATE `57014 user request`，旁路连接保持可用。reconciliation 专项又验证了 5 次 append-only 对账后 Run 仍为 `reconciling`、command 超时升级为 `failed`、统一 DataIncident 及 Alertmanager 打开通知被创建；平台运维人工处置后 Run fail-closed 为 `failed`、incident 关闭并产生关闭通知。该结果证明小数据正确性、精确取消和对账闭环语义，不代表客户生产拓扑、并发规模或 SLO 已认证。

这使 T7/T11 中“Agent 调用确定性 GIS 工具”的一部分从受控试点推进为 durable slice，并补齐了 T9 的运行中取消与 reconciliation 主路径，但不能据此上调 T1-T12 整体完成度。下一批应优先推进规模/故障注入基准和更多受控工作流模板，再基于 Algorithm Registry 扩展栅格、网络和空间统计分析。

## 14. 2026-08-14 多步 GIS 语义工作流验收

本次继续落实了飞渡文档中合理的“自然语言理解、工具编排、确定性空间计算、人工确认和证据输出”要求，但没有采用“LLM 直接自由生成并执行代码”的生产路线。正式链路为：

```text
自然语言需求
  -> LLM 产生受限语义 Proposal
  -> 原问题数值/单位重新 grounding
  -> 人工确认三项结果敏感语义
  -> 数据源、字段、CRS 和不可变版本 grounding
  -> 版本锁定的确定性 DAG
  -> repeatable-read / read-only PostGIS
  -> GeoJSON、分组统计、地图更新和证据哈希
```

当前已注册模板为 `parcel-redline-road-admin-summary.v1`，覆盖“生态红线内、道路距离门槛、面积门槛、按行政区汇总”的完整五节点工作流。LLM Proposal 不允许包含物理表名、字段名、SQL、Python、任意工具调用或未注册操作；模型输出即使伪造距离或面积单位，也会被原始问题重新约束。红线关系、面积计算对象和道路距离判定对象若未明确，必须由用户确认后才能生成可执行 DAG。

工程验收结果：

- 已真实调用配置的 Gemini 模型完成语义 Proposal，记录 provider、model、请求/响应摘要和延迟；
- 已覆盖模型成功、模型超时降级、畸形模型输出、提示注入、证明伪造、问题替换、数据源缺失、字段缺失和 stale plan fingerprint；
- Proposal 证明改为调用时读取共享密钥，生产/预发布环境没有稳定密钥时 fail-closed，避免多 worker 或重启后证明失效；
- 已在独立临时 PostGIS 3.4 容器执行 Proposal API -> 人工语义确认 -> Preview API -> Execute API，未运行项目 migration，也未访问现有 `gis_agent` 数据库；
- 样例结果为 1 宗合格地块，按相交面积分配至 2 个行政区；执行证据确认 `transaction_read_only=true`、隔离级别为 `repeatable read`，并绑定 Proposal、问题、计划、算法和四个来源版本指纹；
- 集成测试结束后自动删除四张样例表，临时容器可整体销毁。

这一增量证明“LLM 负责语义候选、系统负责受控执行”的产品路线已经可运行，而不是文字设计。但边界必须保持清楚：目前只有一个正式工作流模板，尚未形成通用多模板规划器；没有多轮 Proposal 持久化、transport-level JSON Schema 强制、Proposal 缓存/重放服务，也没有隔离的自由代码探索通道。下一步应增加第二个受控模板和模板注册/发现合同，再单独建设带沙箱、静态检查、只读权限、资源预算和人工确认的代码探索通道。

## 15. 2026-08-14 重庆实体与关系基线增量

后续开发采用重庆客户数据和自然资源本体 2.3.0，不等待专家审定；本体状态显式记录为 `technical_baseline_unreviewed`，使用边界为“辅助预审，不替代法定审批或行政决定”。新增证据如下：

- `data_agent/entity_link_authority.py` 与 `data_agent/migrations/161_entity_link_authority.sql`：来源身份、类型化实例 Link、双时态查询、撤回/恢复/校正、来源版本、置信度、RLS、不可变表和最大入度/出度门禁；
- `data_agent/chongqing_entity_link_baseline.py`：固定客户文件和本体包工件哈希，生成 439 个地块身份和 16 个 `layer + BSM` 约束要素身份；472 次客户范围命中展开为 492 次逐要素相交观测并聚合为 486 个稳定 Link；
- `data_agent/test_entity_link_authority.py`：13 个契约测试通过；空的 PostgreSQL 16 真实验收通过幂等、跨租户、端点类型、基数、撤回/恢复、校正和直接写入拒绝；
- `data_agent/migrations/162_entity_authority_batch_ingest.sql` 及 Python authority 批量方法：实体、来源绑定、Link 类型、Link 断言均支持 1..500 项批内原子写入，仍强制租户、RLS、幂等和单条业务门禁；
- `data_agent/chongqing_entity_link_loader.py`：以 7 个原子批次持久化 455 个实体、455 个来源绑定、1 个 Link 类型和 486 个 Link 断言，跨批失败可依 1,396 个幂等键续跑；v2 回执额外封存 472/492 两级观测、精度策略和精度碎片排除数量；
- 精确基线与 loader 聚焦回归 `32 passed`，Ruff 通过；真实 PostgreSQL 16 证明冲突批次 0 条残留，并以非超级用户完成 7 批首次写入和 7 批全量重放，独立表计数为 `455/455/455/455/1/486/486`，REST/MCP 重放不增加记录；
- 两个开发部署 profile 在该阶段同步到迁移目录 162 项及 catalog fingerprint `2c54bb058cdb7b2953bf7c7d2e5dfbb855d79572cf95a074ca9d54277d863177`；随后已由沿革迁移 164 更新。

本增量把 T3/T4 从“缺少统一身份和实例关系合同”推进到“有最小技术合同、通用有界批量和重庆固定基线真实装载/重放证据”。批内是数据库原子事务，跨批依靠幂等续跑。后续又新增 `entity.authority.batch.ingest@1.0.0`、`POST /api/platform/v1/entity-authority/batches` 和 MCP `ingest_entity_authority_batch`，完成统一 REST/Capability/MCP、租户/执行身份/指纹门禁、最多 5,000 项分块和稳定状态指纹；合并/拆分/替代、Link 沿革、逐约束要素精确关联、关系增量和实体/来源/Link 联动的全数据包增量也已补齐。仍不能承诺既有实体域迁移、复杂冲突裁决、任意客户包自动适配、生产规模 SLO、领域批准或法定审批。

## 16. 2026-08-14 实体沿革权威增量

本轮关闭了飞渡合理需求中“实体合并、拆分、替代及 Link 沿革传播没有通用实现”的缺口：

- 新增 `data_agent/entity_lineage_authority.py` 和 `data_agent/migrations/164_entity_lineage_authority.sql`，支持 `N -> 1` 合并、`1 -> N` 拆分、`1 -> 1` 替代；迁移 163 已用于灌溉世界模型，因此沿革能力使用迁移 164；
- 事务会原子退役全部源实体、撤回其所有有效 Link、按显式分配创建/去重/仅撤回新 Link，并重定向全部有效来源身份；事件成员、传播证据和 SHA-256 均追加保存，Link 端点和来源自然键不原地改绑；
- 每条旧 Link 和每个来源身份都必须逐项分配。拆分不自动广播关系；遗漏、类型、自环、基数、重复 Link 或有效时间冲突均 fail-closed，任何部分写入都会整笔回滚；
- 对外能力为 `entity.lineage.record@1.0.0`，CapabilitySpec 指纹 `3bfe4b11a5f58c70bdea0f21252cb5ba79c6334cb3e4b80be7bba642503ef1aa`，REST 为 `POST /api/platform/v1/entity-authority/lineage-events`，MCP 为 `record_entity_lineage_event`；该阶段 MCP 工具总数 52；
- 扩大回归为 `307 passed`，真实 PostgreSQL 16 联合验收为 `2 passed`，覆盖合并、显式单目标拆分、替代、REST/MCP 幂等重放、来源身份按有效时间解析、等价 Link 去重、遗漏分配失败关闭和部分写入后的冲突整笔回滚；当时重庆 v1 的 1,357 个逻辑写入未回归，当前精确 v2 为 1,397 个逻辑写入；
- 该阶段迁移序列推进至 164，最新迁移 `164_entity_lineage_authority`，两个开发部署 profile 的 Catalog fingerprint 为 `73168e1765901e4e0343f15caf0b5f78607d83c929c129cb0c584744d91f63b9`；后续 reconciliation 耐久账本使用迁移 166。

本能力继续固定重庆客户数据和自然资源本体 2.3.0；状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`。没有专家签署不会阻塞研发，但实现完成也不等于领域批准、客户生产验收或法定审批结论。精确逐约束几何目标、关系级 evidence 更新和全数据包增量已经完成；后续第 20 节补齐 reconciliation 专用耐久入口，第 27 节又补齐跨存储 checkpoint PostgreSQL 权威。下一步应把开发资源转向既有实体域迁移、任意客户包适配、跨存储 provider 重建/删除、归档、全执行面授权，以及容量和生产 SLO。

## 17. 2026-08-14 重庆精确约束要素 Link 增量

精确基线 v2 已用 `layer + BSM` 约束实体取代旧的 `layer + sorted(names)` 聚合目标。16 个约束要素全部注册为实体；445 条地块记录形成 439 个稳定地块身份。472 次客户范围命中可确定性展开为 492 次逐要素正面积相交观测，并聚合为 486 个稳定 Link；452 次命中对应一个要素，20 次对应两个要素。双要素命中不伪造逐要素面积分配。

每条 Link evidence 保存地块、约束要素和相交几何 SHA-256、来源记录/命中/要素索引、候选要素集合、source CRS 相交面积、Shapely 版本和固定精度策略。唯一约 `2.9e-11` 公顷且不在客户证据中的浮点边界碎片按 `positive_intersection_area_gt_1e-15_source_crs_units` 显式排除。构建器对客户证据与精确几何不一致、缺失/重复 BSM、非法几何和无客户证据相交全部 fail-closed。

loader v2 在一次性 PostgreSQL 16 中以非超级用户完成 455 个实体、455 个来源绑定、1 个 Link 类型和 486 个 Link 的首次装载及全量重放，数据库计数为 `455/455/455/455/1/486/486`；聚焦回归 `32 passed`，真实验收 `1 passed`，Ruff 通过，临时容器已删除。该证据只适用于固定重庆数据包的辅助预审技术基线，不代表领域批准、客户生产验收、法定审批或行政决定。

## 18. 2026-08-14 重庆精确 Link 增量 reconciliation

新增 `data_agent/chongqing_entity_link_reconciliation.py`，将前后重庆精确基线和当前 authority 状态编译为自校验 sealed plan。同一 Link 的 attributes/source versions/confidence/evidence 变化使用 correction 并显式 supersedes；缺失关系追加 retraction，重新出现的历史关系追加 restoration，新关系追加 initial，无变化关系零写入。计划固定按撤回、校正、恢复、新增分阶段批量执行，并由动作、Link、前态、目标态和生效时间共同派生幂等键，整份计划可安全重放。

实体集合、LinkType、端点或 owner 漂移在写入前 fail-closed，因此这项能力不会把实体迁移伪装成关系更新。单元专项 `5 passed`，相关联合回归 `37 passed`，Ruff 通过；真实 PostgreSQL 16 在完整 486-Link 基线上追加 correction、retraction、restoration 并重放，Link identity 保持 486，append-only assertion 增至 489，历史分别保留原证据和 `active -> retracted -> active` 链，真实验收 `1 passed`，临时容器已删除。

当前章节完成的是同一实体集合内的关系增量；后续第 19 节已补齐实体属性/几何摘要、来源版本、新增/退役实体及其关系的全数据包联动，第 20 节再发布专用 REST/Capability/MCP。所有结果仍为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。

## 19. 2026-08-14 重庆全数据包增量 reconciliation

新增 `data_agent/chongqing_data_package_reconciliation.py`，把前后重庆精确 baseline、实体/来源/Link 当前 authority 状态和生效时间编译为自校验 sealed plan。它支持实体 attributes/geometry 摘要/source versions correction、新实体 initial、暂停实体激活、消失实体退役、新来源 binding、既有来源 identity 的新版本 evidence，以及 Link 撤回/校正/恢复/新增。稳定实体类型或 owner、来源自然键/实体映射、终态实体重现、LinkType 或稳定端点发生漂移时均 fail-closed，要求使用显式 lineage migration。

写入次序固定为“Link 撤回 -> 实体校正/新增/激活 -> 来源证据 -> Link 校正/恢复/新增 -> 实体退役”。每阶段按 1..500 项批内原子，跨阶段依靠内容寻址幂等键续跑，不宣称整包单事务。plan/receipt 封存前后 baseline、三类 authority 输入/输出状态、九类阶段计数、批次数、时间窗和 SHA-256；完整重放必须返回同一权威状态和记录时间。

单元专项 `7 passed`，覆盖 `draft|suspended -> active`；来源 binding history/双时间解析新增 2 个测试，相关联合回归 `49 passed, 1 skipped`，Ruff 通过。一次性 PostgreSQL 16 真实验收执行 7 个增量操作、6 个非空批次并完整重放，最终实体身份/断言 `456/458`、来源身份/证据 `456/457`、Link 身份/断言 `487/491`，真实验收 `1 passed`；临时容器及验收数据已删除。

这项能力关闭了固定重庆数据包内“实体、来源和 Link 不能整体增量”的缺口，但不代表任意客户数据可自动适配。该阶段尚无专用入口，后续第 20 节已补齐固定重庆合同的 REST/Capability/MCP 和耐久重放；仍没有异步大任务、全局单事务、并发容量和生产 SLO。来源 identity 和历史 binding 保持不可变；实体 lifecycle 与 Link retraction 决定当前有效状态。技术相交和增量成功不能解释为领域批准、法定审批或行政决定。

## 20. 2026-08-14 重庆全数据包 reconciliation 统一耐久入口

新增 `data_agent/chongqing_data_package_reconciliation_service.py`，把第 19 节的高层增量发布为同一同步合同：请求包含认证租户、前后重庆 baseline、生效/评估时间、批大小、重放开关、幂等键和调用者；客户端不能提交实体、来源或 Link 当前 authority 状态，服务内部解析权威状态并密封计划。响应返回请求、计划、回执、前后 baseline 和最终 authority 状态 SHA-256，以及九类操作计数和固定技术用途状态。

对外能力为 `entity.data-package.reconcile@1.0.0`，CapabilitySpec 指纹 `b75cb5bd0dc635885ac7d85a059c0edb94a423d663567611bde3a946f6e53d0e`；REST 为 `POST /api/platform/v1/entity-authority/reconciliations`，MCP 为 `reconcile_entity_data_package`，API/SDK/Agent 共享同一 JSON Schema。REST/MCP 均只允许 `admin/platform_operator`，拒绝租户、调用者、Capability 指纹和幂等键冒充；baseline 内部证据身份固定为 `agent:chongqing-baseline-builder`。

迁移 `166_chongqing_data_package_reconciliation.sql` 在任何 authority 写入前预留 request SHA-256 和完整 sealed plan，成功后保存完整 receipt 和紧凑响应。进程中断后从原计划续跑；已完成请求直接返回原响应；同一幂等键绑定不同请求会 fail-closed。这避免了首次成功后重新规划成“零变更计划”而导致跨请求哈希漂移。

专项与联合回归为 `54 passed`；新增合同、网关和测试文件 Ruff 通过，MCP 注册表保留既有历史告警。真实 PostgreSQL 16 验收以非超级用户经 REST 首次执行 7 个操作/6 个批次，再经 MCP 重放同一请求，`plan_sha256`、`receipt_sha256` 和 `authority_state_sha256` 完全一致；最终实体身份/断言 `456/458`、来源身份/证据 `456/457`、Link 身份/断言 `487/491`，临时租户记录清理为 0。

因此，“固定重庆全数据包 reconciliation 缺少专用 REST/Capability/MCP 和稳定跨请求重放”不再是剩余需求。截至第20节仍未完成的是任意客户包适配、可恢复异步任务及进度/取消、跨阶段全局单事务、系统化并发/故障注入、跨存储 checkpoint 和生产 SLO；第21节补齐异步任务主路径，第27节又补齐 checkpoint PostgreSQL 权威，但 provider 执行和多存储验收仍未完成。技术状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`。

## 21. 2026-08-14 重庆全数据包 reconciliation 可恢复异步任务

在同步耐久入口之上，本轮新增 PostgreSQL job queue 和可恢复 worker：

- 迁移 `167_chongqing_data_package_reconciliation_job.sql` 保存 request 文档、request SHA-256、sealed plan 所对应的同步 ledger 幂等键、阶段/进度、attempt、worker lease、取消证据、错误和最终响应；`python -m data_agent.chongqing_data_package_reconciliation_worker` 提供可部署 worker loop；网关只能调用受控函数，不能直写队列表；
- 提交、查询、取消三个能力分别是 `entity.data-package.reconcile-job.submit@1.0.0`、`entity.data-package.reconcile-job.get@1.0.0`、`entity.data-package.reconcile-job.cancel@1.0.0`，对应 REST 路径和 MCP 工具均已注册。指纹分别为 `7bd25cc41b7dbe6db378c240263c83b83195570f2aac1c3f036aeae90222d44b`、`998d1b9f2d709eea193d33b555bb85a48ff59f213cfff463f65c291d2798d10c`、`8f93b0b4e9af4a822786a87d1ee9b6e6b56f7f6c09f0db45a27600d2af752bdd`；MCP 工具总数为 56；
- worker 通过 `SKIP LOCKED` 领取任务，lease 过期后可恢复；规划、逐批应用和回执持久化均更新可验证进度，取消只在批次边界生效；已提交批次不回滚，明确为 `cooperative_between_atomic_batches_no_rollback`；
- 专项测试为 `5 passed`，覆盖 job identity、进度、完成、取消、REST 提交/查询/取消和 capability fingerprint 门禁。迁移目录为 167 项，Catalog fingerprint 为 `49d37ef4be3e7ef40078b20b35814452cefa76232094734e144be2a7a61f4188`；

这使固定重庆数据包的“异步任务、进度、取消、状态查询、worker lease 恢复”进入受控技术基线，但不等于全局事务、跨存储一致性、容量/SLO 或生产部署证明。部分批次已经写入时取消不会撤销事实，后续必须复用原 sealed plan 继续或进入人工 fail-closed 处置。任意客户包适配、既有实体域迁移和复杂多源冲突裁决仍是下一批产品工作。

## 22. 2026-08-14 重庆 reconciliation 故障恢复与取消竞态验收

在第 21 节的异步主路径之上，本轮补齐了两个容易产生错误结论的异常边界：

- 新增迁移 `168_chongqing_data_package_reconciliation_cancel_race.sql`，不修改已封存的 167 号迁移。完成动作会在有效 lease 内重新锁定任务；如果任务已经进入 `cancel_requested`，则在最终边界收敛为 `cancelled`，写入 `cancelled_at_completion_boundary`，清除成功响应，不把取消竞态伪装成成功；
- worker 遇到 lease/claim conflict 时只放弃 stale outcome，不向新 owner 写入失败；普通执行异常沿用有限重试和最终 fail-closed。测试覆盖临时执行失败后的同 request 重试、进度回写租约丢失、三类终态写回租约丢失和完成阶段取消竞态，专项 `9 passed`；迁移/profile 回归 `30 passed`，异步 REST/API `10 passed`；迁移目录为 168 项，Catalog fingerprint 为 `4e7e06589393f9c2d9c9a55bbc61592f0c352f05d0072c16c4cb94e9d360840f`；

这使异步任务在已知取消和租约竞态下的状态语义进入受控技术基线，但仍不是生产混沌工程或容量认证。下一阶段应在隔离 PostgreSQL 和目标部署拓扑中注入数据库断连、worker 硬杀、lease 过期、重复领取、取消竞态和对象存储写入失败，记录恢复时间、重复写入数、队列积压和 p95/p99；第27节已补齐跨存储 checkpoint 权威，后续应建设 provider rebuild/delete 和统一外发授权。任意客户包适配、既有实体域迁移、复杂多源冲突裁决、跨阶段全局单事务和客户生产 SLO 仍未完成。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

## 23. 2026-08-14 重庆 reconciliation 可重复故障 rehearsal 与编排层微基准

新增 `data_agent/chongqing_data_package_reconciliation_resilience.py` 与 `scripts/rehearse_chongqing_data_package_reconciliation_resilience.py`，复用真实 Worker 状态机，以受控内存 repository 注入已知故障。报告合同 `gda.chongqing-reconciliation-resilience-report.v1` 封存场景事件序列、结果、耗时、容量范围、技术用途和自身 SHA-256。

当前覆盖 8 个场景：执行失败重试、进度租约丢失、成功/取消/失败三类终态租约丢失、批次边界取消、重复领取防护和最大 attempt fail-closed。专项测试 `2 passed`，CLI 5 次迭代结果为 `8/8` 场景通过。

该报告强制标记 `capacity_scope=in_memory_worker_orchestration_only`、`production_capacity_certified=false`，所以它只证明 Worker 编排层的可重复状态语义，不证明 PostgreSQL 并发、网络/对象存储故障恢复或客户生产 p95/p99。下一步仍需在隔离 PostgreSQL 和目标部署拓扑中完成真实故障注入、恢复时间、重复写入、队列积压和容量曲线验收。

## 24. 2026-08-14 重庆 reconciliation 真实 PostgreSQL rehearsal 入口

新增 `data_agent/chongqing_data_package_reconciliation_postgres_rehearsal.py` 与 `scripts/rehearse_chongqing_data_package_reconciliation_postgres.py`。工具只接受显式管理员 PostgreSQL URL，在临时数据库中执行 092/094/160/161/162/166/167/168 迁移，创建临时非超级用户运行角色，验证 enqueue 幂等、claim、取消完成竞态、lease 过期恢复、`SKIP LOCKED` 重复领取排除和最大 attempt fail-closed，最后强制清理临时数据库和角色。

## 25. 2026-08-14 重庆 reconciliation 真实 PostgreSQL rehearsal 实测

在隔离的 PostgreSQL 16/PostGIS 容器中实际运行入口，7/7 项检查全部通过：幂等入队、queued claim、`cancel_requested -> cancelled_at_completion_boundary`、过期 lease 重领、`FOR UPDATE SKIP LOCKED` 重复领取排除和 `max_attempts -> failed`。封存报告为 `docs/reports/chongqing_reconciliation_postgres_rehearsal_2026-08-14.json`，SHA-256 为 `e3a852289ca0c6b095cce6d60f81e4839371d8812d97a78d61fd91f75271fca5`。

实测同时修复了两个验收工具缺陷：迁移文本中的 `%` 不能直接交给 psycopg2 参数绑定；设置 `max_attempts` 必须连接临时数据库而不是维护库。两项均已加入回归测试，临时数据库、角色和验收数据已清理。

这关闭了“固定重庆 reconciliation 只有验收入口、没有真实 PostgreSQL 基础语义证据”的工程缺口，但证据范围仍为 `temporary_database_only`。PostgreSQL 断连、worker 硬杀、对象存储联动失败、队列积压、并发容量、恢复时间、跨存储 provider rebuild/delete 和客户生产 SLO 仍未完成；checkpoint PostgreSQL 权威见后续第 27 节。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 26. 2026-08-14 跨存储投影一致性与 repair plan 合同

新增 `data_agent/cross_store_projection_consistency.py`，把 immutable source desired state、独立 target observation 和 last committed checkpoint 分离建模，统一支持 PostGIS、RDF、vector、object store 和 lakehouse 目标。确定性 assessment 覆盖 aligned、checkpoint missing、source advanced、target missing、delete required、target drift、checkpoint state drift 和 desired content mismatch，并输出 `noop/checkpoint/rebuild/delete/fail_closed`。

`gda.projection-repair-plan.v1` 封存前态 checkpoint、期望目标、观察证据、reason codes、下一 checkpoint version、幂等键和自身 SHA-256。只有修复回执同时绑定 `plan_sha256` 与 idempotency key，并复核目标内容 SHA-256、行数或删除状态完全一致，才能生成下一版 `gda.projection-checkpoint.v1`。内存 ledger 支持幂等重放、逐版本推进、stale predecessor 冲突和 append-only history；专项测试 `14 passed`，Ruff 通过。

该增量关闭的是统一判断、repair plan 和 checkpoint 提交门合同缺口，不是生产多存储一致性。该节形成时尚无 PostgreSQL 持久化；后续第 27 节已补齐 checkpoint authority，第 28-31 节已补齐 PostGIS、pgvector 与 RDF 实际执行器和入口；当前仍缺对象存储、湖仓执行器、备份恢复和真实多存储验收。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 27. 2026-08-15 跨存储 checkpoint PostgreSQL authority 与真实验收

新增迁移 `169_cross_store_projection_checkpoint_authority.sql` 和 `PostgresProjectionCheckpointAuthority`。数据库保存 append-only history，并提供受租户 RLS 约束的 current 视图；gateway 没有表写权限，只能调用 SECURITY DEFINER 写函数。首版强制为 1，后续严格匹配 `previous_checkpoint_sha256` 并逐版本推进；目标提交必须绑定 repair `plan_sha256` 和 plan idempotency key；相同证据幂等重放，不同证据复用同一身份时 fail-closed。

在本机隔离临时 PostgreSQL 数据库实际执行 092/094/169，10/10 项检查通过：首版写入、幂等重放、不同幂等证据冲突拒绝、stale predecessor 拒绝、跳版本拒绝、append-only history/current、跨租户读取隐藏、跨租户写拒绝、gateway 表直写拒绝和 history UPDATE 拒绝。封存报告为 `docs/reports/cross_store_projection_checkpoint_postgres_rehearsal_2026-08-15.json`，SHA-256 为 `167cc51f819a3b9f8d3f8d14eadf58042565a4b96c1df26b39daa21bef5fbad6`；迁移 catalog 为 169 项，fingerprint 为 `8bfa3657b4aa04dd6c51740908fb9442e3a2a6a45e375346f628e769b3918bd4`。

因此，checkpoint PostgreSQL 持久化权威不再是剩余需求。第 28-31 节已关闭 PostGIS、pgvector 与 RDF provider 的受控 rebuild/delete/checkpoint、自动 authority 串联和统一外发入口缺口，但不能外推到对象存储或湖仓。仍未完成的是这两类 provider、备份恢复、真实多存储端到端故障恢复/一致性验收和客户生产容量/SLO。所有结果仍为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

## 28. 2026-08-15 PostGIS plan-bound provider 执行器与统一外发入口

本轮新增 `data_agent/postgis_projection_executor.py` 和 `data_agent/postgis_projection_service.py`。执行器只接受 sealed `ProjectionRepairPlan`，要求租户/投影/`postgis://` 目标命中部署侧显式注册表；不接受自由 SQL、schema/table DDL 或未注册目标。列类型、标识符、排序键和几何 SRID 采用 allowlist；rebuild 通过幂等键派生的 staging table 在单事务中受控替换，delete 只允许对封存计划观察到的目标状态执行，checkpoint 只复核不写入。回执包含 plan SHA-256、幂等键、provider commit ref、目标内容 SHA-256、行数和存在性。

REST `POST /api/platform/v1/projections/postgis/repairs`、Capability `projection.postgis.repair@1.0.0` 和 MCP `execute_postgis_projection_repair` 复用同一请求/回执合同，并强制租户、角色、Capability fingerprint 和幂等键校验。部署侧通过 `GDA_POSTGIS_PROJECTION_TARGETS_JSON` 注册目标、通过 `DATABASE_URL` 连接数据库。

专项单测已通过；第 28 节首次在临时 PostgreSQL 16 + PostGIS 数据库完成 6/6 provider 验收：几何列 rebuild、rebuild 重放、封存观察漂移拒绝、checkpoint 复核、delete 和 delete 重放。第 29 节扩展为含 authority 串联的 11/11 演练；首次报告 SHA-256 为 `7cfd01c9515871dc811dbb53475d7134f64f2bf7e9ddd8f2cecd24b0fbc8e0ac`，当前报告见第 29 节。

该节记录 PostGIS provider 和统一外发入口的首个增量。provider 回执与 checkpoint authority 的自动串联见第 29 节，pgvector provider 见第 30 节，RDF provider 见第 31 节；对象存储、湖仓仍未实现，备份恢复、跨存储故障注入与一致性验收以及客户生产容量/SLO 仍未完成。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

## 29. 2026-08-15 PostGIS provider receipt 自动 checkpoint 串联与 11/11 真实演练

本轮把第 28 节的 PostGIS provider 回执接入第 27 节的 PostgreSQL checkpoint authority，但明确不宣称 provider 与 authority 是分布式原子事务。服务先读取 authority 当前 checkpoint 并校验 sealed plan predecessor，防止 stale plan 先修改 PostGIS；provider 成功后把 receipt 转换为 plan-bound observation/checkpoint 并写入 authority。authority 暂时失败可重试，重试会重新观察 PostGIS；已有同 plan checkpoint 也必须复核目标内容、行数和删除状态，漂移则拒绝静默 replay；并发写冲突只有在证据完全一致时才返回既有 checkpoint。

请求新增 typed `checkpointed_by`，REST、Capability 和 MCP 均绑定认证主体；输出从单一 receipt 升级为 `gda.postgis-projection-repair-result.v1`，同时返回 receipt、durable checkpoint、是否新建 checkpoint 以及固定技术用途状态。该状态始终为 `technical_baseline_unreviewed`，用途始终为 `assisted_precheck_not_for_production_decision`。

在临时 PostgreSQL 16 + PostGIS 数据库执行 092/094/169，11/11 检查通过：rebuild 自动 checkpoint、重放复核、目标漂移拒绝、checkpoint action 版本推进、stale predecessor 写前拒绝、delete 自动 checkpoint、delete replay 和 append-only history `1→2→3`。联合回归为 `96 passed, 1 skipped`，封存报告 `docs/reports/postgis_projection_executor_rehearsal_2026-08-15.json` 的 SHA-256 为 `eb99cd13b3bbf7a541ac115b7aa2e3d4a965988720044f908574ab70580671c1`，范围为 `temporary_database_only`。

这关闭了 PostGIS provider receipt 持久化/自动 checkpoint 串联缺口；pgvector 同类缺口由第 30 节关闭，RDF 同类缺口由第 31 节关闭。对象存储、湖仓仍未实现。剩余需求包括这两类 provider 执行器、五类存储真实端到端故障恢复与一致性验收、备份恢复、全执行面权限、通用 Action/Proposal 生产运行时和客户生产容量/SLO；不代表领域批准、客户生产验收、法定审批或行政决定。

## 30. 2026-08-15 pgvector plan-bound provider、自动 checkpoint 与统一入口

新增 `data_agent/vector_projection_executor.py` 和 `data_agent/vector_projection_service.py`。目标的租户、projection、`vector://host/schema.table`、schema/table 和 embedding dimension 必须由部署侧显式注册；请求只能提交结构化向量行，不能提交 SQL、DDL、任意表名或任意维度。内容指纹对行顺序无关但绑定维度；非有限向量、维度漂移、目标漂移和非表目标全部 fail-closed。

`rebuild` 采用单事务 staging/backup 替换，`delete` 只执行 sealed observation 对应目标，`checkpoint` 只复核不写入。服务在 provider 写入前校验 PostgreSQL checkpoint authority predecessor，成功后把 plan-bound receipt 自动写入 append-only history；已有 checkpoint 重放会重新观察 pgvector 目标，漂移时拒绝静默 replay。provider 与 authority 仍不是分布式原子事务。

REST `POST /api/platform/v1/projections/vector/repairs`、Capability `projection.vector.repair@1.0.0` 和 MCP `execute_vector_projection_repair` 共用 `gda.vector-projection-repair-request/result.v1`，并强制认证租户、平台角色、Capability fingerprint、主体和 sealed plan 幂等键。Capability 指纹为 `70cf73a1d07ad567300881d4d99b4f5c7613a0a7f32a3e5262157cbc8aa75d9d`，当前 MCP 工具总数为 58。

专项与联合回归为 `106 passed`。临时 PostgreSQL 16 + pgvector 0.8.2 数据库执行 092/094/169 后完成 11/11 检查，覆盖 rebuild、自动 checkpoint、幂等重放、sealed drift 拒绝、checkpoint replay 重新观察、checkpoint action、stale predecessor 写前拒绝、delete、delete replay 和 append-only history `1→2→3`。封存报告为 `docs/reports/vector_projection_executor_rehearsal_2026-08-15.json`，SHA-256 为 `88bc30950aca11c49ca0e9c6fafcb99f388c4e876f60ec56499961a6444aa9a6`；临时数据库已删除，范围为 `temporary_database_only`。

因此，pgvector 的 plan-bound provider、自动 checkpoint 和统一外发入口不再是剩余需求。RDF 同类缺口由第 31 节关闭；尚未完成的是 ANN 索引策略、召回质量、并发容量、备份恢复，以及对象存储、湖仓 provider、跨五类存储真实故障恢复/一致性验收和客户生产 SLO。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

## 31. 2026-08-15 RDF/Fuseki plan-bound provider、自动 checkpoint 与隔离真实演练

新增 `data_agent/rdf_projection_executor.py` 和 `data_agent/rdf_projection_service.py`。租户、projection、`rdf://` target、Fuseki Graph Store endpoint、本体目录、ontology key、semantic version、package ID、package content SHA-256、RDF artifact SHA-256 和 triple count 必须由部署侧显式注册；注册合同和运行时包校验共同限制为 `natural-resource-one-map` 2.3.0。调用请求不能提交 RDF body、Fuseki endpoint、凭据、图标识或包目录，因而不能把该入口当作任意 RDF 写 API。

执行器使用 `OntologyPackageReader(verify=True)` 在写前核对不可变包和 artifact；RDF 图指纹对 triple 顺序无关且拒绝 blank node。`rebuild` 使用 Graph Store PUT，`delete` 使用 DELETE，`checkpoint` 只复核；执行前校验 sealed observation，已有 checkpoint 重放也会重新 GET 目标，内容、triple count 或存在性漂移时 fail-closed。服务在 provider 写前校验 checkpoint predecessor，成功后自动写入 PostgreSQL append-only authority。Fuseki HTTP 提交和 PostgreSQL authority 提交不是分布式原子事务，authority 暂时失败时只能依靠同一计划重试、重新观察和幂等证据恢复。

REST `POST /api/platform/v1/projections/rdf/repairs`、Capability `projection.rdf.repair@1.0.0` 和 MCP `execute_rdf_projection_repair` 共用 `gda.rdf-projection-repair-request/result.v1`，并强制认证租户、平台角色、Capability fingerprint、主体和 sealed plan 幂等键。Capability 指纹为 `9487eb9d69430d5dfd10963c34b6bb4575dd553ea60b61e6ba0edfa1cd8c0b44`，当前 MCP 工具总数为 59。

RDF、pgvector、PostGIS、跨存储 authority/consistency、Capability、REST 和 MCP 联合回归为 `112 passed`。隔离真实演练使用 Fuseki 5.5.0 一次性容器/卷和临时 PostgreSQL checkpoint 数据库，实际写入固定本体包的 537,245 条 triples。核心 11/11 检查覆盖 rebuild、自动 checkpoint、幂等 replay、sealed drift、checkpoint replay drift、checkpoint action、stale predecessor、delete、delete checkpoint、delete replay 和 history `1→2→3`；另有容器、卷、临时数据库清理 3/3，二次残留核查均为 0。封存报告 `docs/reports/rdf_projection_executor_rehearsal_2026-08-15.json` 的 SHA-256 为 `0346095387ddb9d3dae81cdba23a4453858d73f81b619c8844fe4ca4e6c65012`。

因此，RDF provider 的 plan-bound rebuild/delete/checkpoint、自动 checkpoint authority 和统一外发入口不再是剩余需求。当前仍缺对象存储与湖仓 provider、跨五类存储故障恢复/一致性验收、备份恢复、容量与客户生产 SLO；也不代表完整 OWL 2 DL 推理、任意 RDF 写入、领域批准、客户生产验收、法定审批或行政决定。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

## 32. 2026-08-15 S3/MinIO 对象存储 provider、自动 checkpoint 与真实演练

新增 `data_agent/object_projection_executor.py`、`data_agent/object_projection_service.py` 和隔离演练模块。部署注册表固定租户、projection、`s3://` target、endpoint、bucket/key、重庆 bundle manifest 与 artifact 指纹，以及自然资源本体 `natural-resource-one-map` 2.3.0 package；请求只接受 sealed plan 和认证主体，不能提交对象内容、端点、bucket/key、本地路径或凭据。

执行器强制 bucket 开启 Versioning，观察时读取真实对象字节计算 SHA-256，并将 `VersionId`、ETag、字节数或 delete marker 纳入 provider receipt 和 checkpoint 重放校验。同内容新版本也视为漂移；`rebuild` 只允许写入已核验的 `heping_changed_parcels.geojson`，`delete` 必须产生不可变 delete marker，`checkpoint` 只复核。S3 提交和 PostgreSQL authority 提交不是分布式原子事务。

REST `POST /api/platform/v1/projections/object-store/repairs`、Capability `projection.object-store.repair@1.0.0` 和 MCP `execute_object_projection_repair` 共用 `gda.object-projection-repair-request/result.v1`，并强制认证租户、平台角色、Capability fingerprint、主体绑定和 sealed plan 幂等键。Capability 指纹为 `7af931f2e305fd617ce227b786b77cd353ca946ba72aebececc4b33998322908`，MCP 工具总数为 60；部署参数已进入环境示例、Compose 和 Kubernetes。

对象存储入口联合回归为 `65 passed`。真实演练在一次性 MinIO 容器/卷/bucket 和临时 PostgreSQL authority 中写入重庆客户 artifact `heping_changed_parcels.geojson`（SHA-256 `eb35068c4273fe25e07d99f822016f33b6fe29cd189b34aff037b9611e163bd3`，`1,950,576` bytes），核心 11/11 与清理 4/4 全部通过。封存报告 `docs/reports/object_projection_executor_rehearsal_2026-08-15.json` 的内部指纹为 `40f90a0b86f09867fdb98f585a282c7f5f7e678d99a664202c87fc6224b803fb`，文件 SHA-256 为 `9c4f9272eb0660c93b3d65a7f0504a1de795f83b3f468bf8364d73c6c931ba18`。

因此，对象存储 plan-bound provider、不可变版本证据、自动 checkpoint 与统一入口不再是剩余需求。当前只剩湖仓 provider 尚未实现；备份恢复、跨五类存储端到端故障恢复/一致性验收、并发容量与客户生产 SLO 仍未完成。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域批准、客户生产验收、法定审批或行政决定。

## 33. 2026-08-15 Spark/Iceberg 湖仓 provider、自动 checkpoint 与真实演练

新增湖仓 projection executor/service、Docker Spark provider 和固定 worker。部署注册表固定 Iceberg catalog/namespace/table、S3 warehouse、客户 bundle/artifact、逻辑表指纹和自然资源本体 2.3.0；请求只能提交 sealed plan 与认证主体，不能提交行数据、Spark 配置、warehouse/table、存储端点、凭据或本地路径。

客户 artifact 实际包含 445 个 feature、439 个 `parcel_id`，湖仓行键采用 `parcel_id + artifact feature index`，避免错误把一地块多要素合并为一行。Spark/Iceberg v2 表观察会回读受控行、重算逻辑指纹/行数并绑定当前 `snapshot_id`；同内容新 snapshot 在 checkpoint replay 时按漂移拒绝。删除前在 warehouse 写入 plan-bound tombstone，再执行 `DROP TABLE PURGE` 并观察表缺失；DROP 成功但 authority 写入失败时，同一 sealed plan 可从 tombstone 恢复删除前 snapshot 和 drop evidence。Iceberg commit 与 PostgreSQL authority 仍不是分布式原子事务。

REST `POST /api/platform/v1/projections/lakehouse/repairs`、Capability `projection.lakehouse.repair@1.0.0` 和 MCP `execute_lakehouse_projection_repair` 共用 `gda.lakehouse-projection-repair-request/result.v1`。Capability 指纹为 `eb693f332b4174a6581c0ace02fec5b43a276a303211bc9128ef6dc9f263673f`，MCP 工具总数为 61。当前 Docker Spark 适配器已完成隔离验收；Kubernetes 配置默认禁用，集群 Spark 执行边界仍需单独安装和验收。

五类 provider 联合回归为 `122 passed`。真实演练在一次性 Docker 网络、MinIO 容器/卷/bucket、Spark/Iceberg runtime 和临时 PostgreSQL authority 中物化 445 行，并验证 DROP 已成功但 authority 尚未提交时的 tombstone 恢复；核心 12/12、清理 5/5 全部通过。报告 `docs/reports/lakehouse_projection_executor_rehearsal_2026-08-15.json` 的内部指纹为 `dd6e116bacd7d1bf853c4164ec5f2af7bbe2364acc8ffb9b9a6826b221f3c1d3`，文件 SHA-256 为 `a6f3a3542c16bf4df6403efda9a9ce22c918650a48782cea47440d9bd52530f3`。

因此，五类 provider 均已形成受控技术执行面，剩余需求不再是“再补一个 provider”，而是跨 provider 恢复/补偿编排、备份恢复、全执行面权限、真实多存储故障注入、容量和客户生产 SLO。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域批准、客户生产验收、法定审批或行政决定。

## 34. 2026-08-15 跨 Provider recovery state machine 与 authority 间隙故障矩阵

新增 `data_agent/cross_store_projection_recovery.py`，统一记录 sealed plan 周围的 Provider/authority 两阶段边界。已知 provider receipt 允许重新观察目标后只重试 authority；已知未提交失败允许重新执行同一 sealed plan；Provider 结果未知时转入 `reconciliation_required -> reobserve_target`；目标漂移时转入 `manual_compensation`，禁止盲目写 checkpoint。recovery snapshot/event 绑定 plan SHA-256、幂等键、commit ref、checkpoint SHA-256、错误码和 append-only 事件指纹。

新增 `data_agent/cross_store_projection_recovery_rehearsal.py` 和 `scripts/rehearse_cross_store_projection_recovery.py`。故障矩阵 `known_provider_authority_gap`、`target_drift_requires_manual_compensation`、`unknown_provider_outcome_requires_reobservation`、`known_provider_failure_can_retry` 共 `4/4` 通过，专项测试 `7 passed`，Ruff 通过。封存报告为 `docs/reports/cross_store_projection_recovery_rehearsal_2026-08-15.json`，文件 SHA-256 为 `364b70b11dcd36c2224efa68aa125e3d596618bd5e3988f267703ed1f09b95d0`。

该增量只证明 `in_memory_recovery_orchestration_only`，强制 `production_recovery_certified=false`。生产持久化 recovery ledger、自动补偿执行器、PostgreSQL 断连/worker 硬杀/网络故障注入、队列积压、恢复时间、跨五类存储端到端一致性和生产 SLO 仍未完成；不能宣称分布式原子事务、客户生产验收或领域/法定批准。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 35. 2026-08-15 PostgreSQL 持久化 recovery ledger 与真实隔离验收

新增迁移 `170_cross_store_projection_recovery_ledger.sql` 和 `PostgresProjectionRecoveryLedger`，把 8.26 recovery snapshot/event 从内存 ledger 推进为 PostgreSQL append-only authority。snapshot/event history 启用租户 RLS、强制 RLS、不可变 UPDATE/DELETE trigger 和 gateway 无表直写权限；唯一写入口为 `SECURITY DEFINER` 函数，并按 sealed plan 使用 advisory lock 保证事件链顺序。重复 snapshot 幂等返回原记录，跨租户、跳事件、篡改事件和直接写表均 fail-closed。

新增 `cross_store_projection_recovery_postgres_rehearsal.py` 和 CLI，首次在临时 PostgreSQL 16 中执行 092/094/169/170，ledger 基础检查 `8/8` 通过。该入口和同名报告随后由第 37 节扩展到 171 号迁移和 durable job queue，当前检查数、哈希、catalog count 与 fingerprint 以第 37 节为准。

新增 `cross_store_projection_recovery_worker.py` 与 `RegisteredExecutorProjectionProvider`，统一适配 PostGIS、RDF/Fuseki、pgvector、S3/MinIO、Spark/Iceberg 五类已有 executor。worker 对已知 provider receipt 只做 authority retry，对未知结果只做 re-observation；没有显式 compensation callback 时保持 `await_operator`，不盲目重放。恢复专项回归为 `14 passed, 1 skipped`，Ruff 通过。

因此，“recovery ledger 只有内存实现”和“没有统一 worker 决策合同”不再是剩余需求。五类 Provider 的真实异常回执、目标观察器和补偿策略尚未全部接入部署调度器；PostgreSQL 断连、worker 硬杀、网络故障、队列积压、lease 过期、恢复时间、跨存储一致性、备份/PITR/RPO/RTO、容量和生产 SLO 仍未完成。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表分布式原子事务、客户生产验收或领域/法定批准。

## 36. 2026-08-15 五类 Provider durable recovery worker 接入合同

本轮在第 34-35 节基础上新增统一 `ProjectionRecoveryWorker`。worker 从 durable snapshot 选择唯一动作：已知 provider receipt 或 `authority_pending` 只重新观察目标并写 PostgreSQL authority；已知未提交错误可按同一 sealed plan 重试；未知结果先 `reobserve_target`，没有 plan-bound commit evidence 时进入 `manual_compensation`，默认 `await_operator`，不把同内容目标推断成已提交。显式 compensation callback 返回合法 provider receipt 后，worker 才允许继续 authority recovery。

`RegisteredExecutorProjectionProvider` 从部署注册表解析目标并复用五类 executor 的既有 `execute/observe` 合同；PostGIS/pgvector 仅接受受控 rows，RDF/Fuseki、S3/MinIO 和 Spark/Iceberg 不从恢复事件接收新的目标或凭据。新增专项测试覆盖首次执行、authority 失败后的 authority-only retry、未知结果重新观察、显式补偿闭环和 adapter 行为。

该增量将“统一 recovery 动作选择和 durable state 重载”推进为可测试技术基线。本节形成时还没有自动调度/lease/队列，第 37 节已补齐数据库调度内核；真实五类存储异常回执部署接线、长任务 heartbeat、补偿与对账业务规则、断连/硬杀/网络故障注入、备份恢复、容量、恢复时间或生产 SLO 仍未完成。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

## 37. 2026-08-15 durable recovery job queue、lease fencing 与 PostgreSQL 实测

新增迁移 `171_cross_store_projection_recovery_job.sql`、`PostgresProjectionRecoveryJobRepository` 和 `ProjectionRecoveryJobWorker`。队列持久保存完整 sealed plan、双重计划身份、目标身份、attempt、lease、错误和 snapshot 证据；同租户同 plan 幂等入队，`FOR UPDATE SKIP LOCKED` 排他领取，每次 claim 递增 `lease_generation`，续租和终态写同时按 worker ID、租约代次及过期时间 fencing。即使进程复用同一 worker ID，旧代也不能覆盖新租约。`waiting_operator` 不热重试，显式 resume 在原 attempt 用尽时只追加一次可用 attempt 并保存 `resumed_by/resumed_at`；任务表强制 RLS，gateway 不能直接写表。

临时 PostgreSQL 实际执行 092/094/169/170/171，`16/16` 通过：除原 ledger 8 项外，新增验证幂等入队、单 owner、续租、同 worker ID 下按代次过期接管、stale generation 终态拒绝、人工等待不热重试、显式恢复追加 attempt/保存操作者证据和 gateway job 表直写拒绝；heartbeat、resolver 和 CLI/Compose 接线随后由第 38 节继续验证。当前报告以第 40 节更新后的 `28/28` 检查和新哈希为准；migration catalog 已推进为 `172`，fingerprint 为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`。

这关闭了 durable recovery worker 的持久队列、排他领取、lease 接管、旧 owner fencing 和人工恢复入口缺口；长任务 heartbeat、五类 Provider resolver 及 CLI/Compose 部署接线由第 38 节补齐，但不等于生产恢复服务已经部署。仍需完成断连、硬杀、网络、积压和五存储联动故障注入，确定 compensation/reconciliation 业务策略，以及备份/PITR、RPO/RTO、容量、p50/p95/p99、恢复时间和生产 SLO；湖仓 Docker 执行边界仍需显式部署授权，全执行面权限、通用 Action/Proposal runtime 和自动语义融合也未完成。数据范围仍是重庆客户数据，本体仍固定 `natural-resource-one-map 2.3.0`，结果仍是 `technical_baseline_unreviewed` / `assisted_precheck_not_for_production_decision`。

## 38. 2026-08-15 长任务 heartbeat、五类 Provider resolver 与可运行部署接线

第 37 节的持久队列现已接入可运行 worker 进程，仍只使用重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0`：

- `ProjectionRecoveryJobLeaseHeartbeat` 在 Provider/authority 执行期间按 lease 周期续租；heartbeat 丢失先检查所有权，旧 owner 不写任何终态。与 Provider 异常并发时仍按 heartbeat 丢失 fail-closed；
- `ProjectionRecoveryProviderResolver` 惰性加载服务端注册表和凭据，覆盖 PostGIS、pgvector、RDF/Fuseki、S3/MinIO、Spark/Iceberg。PostGIS/pgvector rebuild 必须读取与 `<plan_sha256>.json` 同名的服务端 row bundle，并校验租户、投影、引擎、目标、计划哈希、幂等键、行数和 `rows_sha256`；其他 provider 不接收客户端凭据或副作用参数；
- 新增 `python -m data_agent.cross_store_projection_recovery_job_worker` 入口，支持租户/worker、lease、heartbeat、重试、轮询和 `--once`；Compose 新增默认关闭的 `projection-recovery` profile，并固定挂载 `/app/data_agent/uploads/projection-recovery-rows`。湖仓 Docker socket 仍不自动挂载，必须在部署覆盖中显式授权；
- 本节形成时临时 PostgreSQL 实测执行 092/094/169/170/171，`20/20` 通过，新增未知 Provider 回执保持人工补偿、heartbeat 丢失阻止旧 owner 终态写入以及新 owner 接管三项故障注入检查；该报告随后由第 40 节扩展到精确 ApprovalCase 授权，当前检查数和哈希以第 40 节为准，范围始终为 `temporary_database_only`。

该增量关闭了“长任务没有周期 heartbeat”“恢复 worker 不能按服务端注册表解析五类 Provider”“没有可运行部署入口”的实现缺口，但只形成部署技术基线。仍不能据此宣称五类存储真实故障注入、生产恢复认证、Docker Spark/Iceberg 集群已部署、容量或客户 SLO 已验收；备份/PITR、RPO/RTO、跨存储一致性、业务授权的 compensation/reconciliation、全执行面权限、通用 Action/Proposal runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合仍未完成。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域批准、客户生产验收、法定审批或行政决定。

## 39. 2026-08-15 PostgreSQL recovery worker 受控故障注入与 lease fencing 实测

在第 38 节部署接线之上，本轮把 worker 控制面的两类异常放入真实临时 PostgreSQL 队列和 recovery ledger：

- 对 `outcome_known=false` 的 Provider 超时，第一次只进入 `reobserve_target`，第二次观察后进入 `manual_compensation`/`await_operator`，Provider 执行次数保持为 1，且没有 checkpoint；
- 对第二次 heartbeat renew 注入失败，旧 worker 不写终态，任务保持 `running`；租约过期后，新 worker 以递增 `lease_generation` 接管；
- 092/094/169/170/171 临时 PostgreSQL 演练 `20/20` 通过。新增检查为 `unknown_provider_fault_stays_manual_after_reobserve`、`heartbeat_loss_blocks_terminal_write`、`heartbeat_loss_job_can_be_reclaimed`；报告内部 SHA-256 为 `4ee827adcc908f4e0429dd1e2289a1d57164b7cd8ca189595a61d1e7cdae852f`，文件 SHA-256 为 `5d5603031acb612794d3e6df92b5c51443260e1a4e7d878055c6279e82629db6`。

该增量关闭了 worker 控制面中未知结果重放和 heartbeat 丢失旧 owner 写终态的技术缺口，但仍不是五类 Provider 的真实存储故障注入。真实断连、网络分区、硬杀、不确定回执、跨存储联动、补偿/对账实际业务规则、备份/PITR、RPO/RTO、容量和客户生产 SLO 仍未完成；补偿恢复的技术授权门禁由第 40 节补齐。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表生产恢复认证、专家审定、客户验收或法定审批。

## 40. 2026-08-15 补偿恢复的精确 ApprovalCase 授权与一次性消费

新增迁移 `172_projection_recovery_compensation_approval.sql`，把 `waiting_operator -> resume` 从“记录操作者字符串”收紧为数据库强制的精确授权。旧三参数 resume 函数已删除；新入口必须提交 ApprovalCase 和理由，并逐项校验 tenant、`approved` 状态、有效期、当前 recovery job URN、当前等待 snapshot fingerprint 以及固定 action `projection.recovery.compensate`。任一证据缺失、pending、rejected、跨租户、错误动作或错误快照均 fail-closed。

job 保存完整 resume evidence；新的 append-only `cross_store_projection_recovery_resume_event` 记录审批消费，并以 ApprovalCase 唯一约束阻止同一批准重复授权第二次补偿。gateway 只有 SELECT，不能直接伪造 job 审批字段或消费事件。`ProjectionRecoveryJob` 和 repository 也同步要求完整证据，跨租户和错误资源类型在 Python 合同层拒绝。

隔离临时 PostgreSQL 实际执行 092/094/102/103/169/170/171/172，演练扩展为 `28/28`：新增覆盖错误快照、错误动作、rejected、pending、跨租户、精确 append-only 消费证据、一次性消费和 gateway 伪造拒绝。recovery/ApprovalCase/profile/migration 联合回归 `102 passed, 2 skipped`，Ruff 与迁移目录校验通过。报告 `docs/reports/cross_store_projection_recovery_postgres_rehearsal_2026-08-15.json` 的内部 SHA-256 为 `5d18a504f3c66dcaf01fed3be5eac819b41f0b7a9db1aeb5900f70dbd999f43e`，文件 SHA-256 为 `9a39258382907e4f5920adc0ea1f36d7855d6064d14582af363983adc14520f2`；catalog 为 172 项，fingerprint 为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`。

这关闭了“无真实 ApprovalCase 即可恢复”和“审批可静默重复消费”的技术缺口，但没有替客户定义 compensation/reconciliation 业务规则，也没有证明真实五类存储故障或生产恢复。ApprovalCase 仅是技术授权合同，不代表专家审定、领域批准、客户生产验收、法定审批或行政决定。剩余项仍包括实际补偿/对账策略与自动执行、全执行面安全闭环、通用 Proposal/Action runtime、真实多存储故障注入、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`。

## 41. 2026-08-16 经批准的原 sealed plan 受控重放

在第 40 节一次性 ApprovalCase 授权之上，新增默认关闭的 `approved_reapply_sealed_plan` 技术补偿策略。策略配置只允许 `disabled` 或该固定值，不能携带 target、rows、credentials、endpoint 或任意代码；执行器不生成新计划，只能重用 recovery job 内原 `ProjectionRepairPlan`，并绑定 job worker 已解析的同一个 Provider 和同一个 durable ledger。

执行前会重新查询数据库并核验：当前租约/`lease_generation`、完整 resume evidence、ApprovalCase 当前仍为 `approved` 且未过期、精确 job URN、原等待 snapshot fingerprint、固定 action `projection.recovery.compensate`、append-only 消费事件和 recovery ledger 当前 snapshot。plan SHA-256、幂等键、projection、engine、target 或 snapshot 任一漂移均拒绝。Provider 仍只能通过服务端 registry 解析目标；执行后的 receipt/commit ref 仍必须绑定原 plan SHA-256 和 idempotency key，之后才允许观察目标并写 checkpoint authority。Compose 变量 `GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY` 默认保持 `disabled`。

隔离临时 PostgreSQL 16 演练实际执行 092/094/102/103/169/170/171/172，并扩展为 `31/31`：新增验证默认关闭、只执行原 sealed plan、数据库授权与 durable snapshot 运行时再核验以及最终 checkpoint。联合回归为 `107 passed, 2 skipped`，Ruff 与 Compose 校验通过。报告内部 SHA-256 为 `38902fd18b3e9105a9a5ea788c07623f1a6084a6330f2fcf1b336bfe617d4bad`，文件 SHA-256 为 `fd7c2c72403819bf35a988fba152c421c582466a768fe45cc4ddbacae680618b`，范围仍为 `temporary_database_only`。migration catalog 仍为 172 项，fingerprint 仍为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`；`main-compose-dev` 配置指纹更新为 `743220d848b7f6d4ccf655bbccd52e3b15133c0c0025a462762a481af2e0da0a`。

这关闭的是“精确批准后仍没有任何可执行技术补偿路径”，不是通用业务补偿。本节形成时尚未实现补偿候选生成；后续第 51 节已补齐绑定源快照的技术候选生成、只读对账推荐和 PostgreSQL 权威，但客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、变更型自动选择/执行、通用 Proposal/Action runtime、五类真实 Provider 故障与联动注入、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环和自动语义融合仍未完成。ApprovalCase 仍只是技术授权合同；状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域规则批准、生产恢复认证、客户生产验收、法定审批或行政决定。

## 42. 2026-08-16 补偿执行 crash gap 与持久 receipt 恢复

第 41 节的原 sealed plan 重放已增加执行前授权核验，但 Provider 成功与 recovery ledger 落账仍是两个持久化边界。本轮新增迁移 `173_projection_recovery_compensation_execution.sql`：每个已消费 ApprovalCase 形成唯一、append-only 的补偿执行事件链，事件 1 为 `started`，事件 2 只能是 `succeeded`、`failed_known` 或 `failed_unknown`。事件表强制租户 RLS、不可变 UPDATE/DELETE，gateway 仅有 SELECT；开始和完成只能通过两个 `SECURITY DEFINER` 函数，并持续校验 job、worker、lease generation、resume event、原 snapshot、plan SHA-256、幂等键和 durable recovery snapshot。

Provider 调用前必须先写 `started`。只有 `started` 而没有终态时，后续 worker 将其视为结果未知并等待人工对账，不能再次执行 Provider。成功终态持久保存最小 plan-bound provider commit ref 和 canonical receipt SHA-256；如果进程在此后、recovery ledger 更新前退出，新 worker 从数据库恢复该 receipt，继续写 recovery ledger/checkpoint，不再触发 Provider。失败终态、receipt 篡改、snapshot 漂移或 lease 丢失均 fail-closed。

隔离临时 PostgreSQL 16 实际执行 092/094/102/103/169/170/171/172/173，演练扩展为 `33/33`。实测在 Provider 成功、执行终态已持久但 recovery ledger 尚未更新时模拟 worker 崩溃和 lease 过期；新 lease generation 最终写入 checkpoint，而 Provider 执行次数仍为 1；另验证 gateway 不能伪造执行证据。联合回归 `111 passed, 2 skipped`，Ruff、Compose 和迁移 profile 校验通过。演练内部 SHA-256 为 `047fe05b598b7f76d754b2bfb4acca39abb0e317e6fd689fe0c4b1bfd336f6ac`，文件 SHA-256 为 `bb0bf81386e65f650579766a1a8f69601b4448b3d034da591055fad847429f1c`，范围仍为 `temporary_database_only`；catalog 为 173 项，fingerprint 为 `47c6f30fb304f68845accbc6ac7f38aa20a015a86cb9f12c9200871db9e64948`。

这封闭的是补偿 Provider/ledger 之间的重复执行控制面风险，不是跨存储分布式事务或业务对账完成。`started-only` 必须先观察真实 Provider 状态，再用新的 recovery snapshot 和 ApprovalCase 决策；系统仍未替客户定义 rollback/delete/restore/corrective-forward/reconciliation 规则。真实五类 Provider 故障与联动、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义融合仍未完成。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、生产恢复认证、客户验收、法定审批或行政决定。

## 43. 2026-08-16 started-only 人工核对裁决与受控恢复

第 42 节将 started-only 置为人工等待；本轮新增迁移 `174_projection_recovery_compensation_reconciliation.sql`，为该等待状态提供一个受控、一次性的核对出口。新增 append-only 核对事件表强制租户 RLS、不可变 UPDATE/DELETE 和 gateway 只读；`SECURITY DEFINER` 函数逐项校验原 attempt、原执行 ApprovalCase、job、等待 snapshot、plan SHA-256、幂等键和核对目标 fingerprint。核对 ApprovalCase 只允许两个固定 action：`projection.recovery.compensation.reconcile_committed` 或 `projection.recovery.compensation.reconcile_not_committed`，并在 request context 中绑定观察人、观察引用、观察 SHA-256、裁决类型和（已提交时）receipt SHA-256。

人工确认 Provider 已提交时，原 started-only attempt 被封存为 `succeeded`，job 重新排队；恢复 worker 读取持久化、plan-bound receipt，继续 authority/checkpoint，Provider 不再执行。人工确认未提交时，原 attempt 被封存为 `failed_known`，job 仍保持人工等待；只有新的 `projection.recovery.compensate` ApprovalCase 消费后，才允许新 attempt 重试原 sealed plan。未知状态本身仍不会自动推断为未提交或已提交。

临时 PostgreSQL 16 演练实际执行 092/094/102/103/169/170/171/172/173/174，`37/37` 检查通过，覆盖 started-only 不热重试、已提交核对零 Provider 重放、未提交核对必须新审批和 gateway 伪造拒绝。专项联合回归为 `122 passed, 2 skipped`；演练内部 SHA-256 为 `ffbd43f3822901a0f40ce63cf554775fa476e727e8079a98b24bdd56c33592dc`，文件 SHA-256 为 `d9439689317affbbbf46260379810f8f4f83ddb5f674d5085ec3c14492ec7050`；migration catalog 为 174 项，fingerprint 为 `2e948f44f691cd0f24500ceb89eeb1635abb04d5b40f010786226e512a634bcc`。

这推进的是恢复控制面审计与人工裁决，不是客户业务对账规则、分布式事务或生产恢复认证。尚未实现的需求仍包括真实五类 Provider 断连/网络分区/硬杀/联动故障注入，客户定义的 rollback/delete/restore/corrective-forward/reconciliation 方案，备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面权限闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义规划融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域批准、生产恢复认证、客户生产验收、法定审批或行政决定。

## 44. 2026-08-16 PostGIS Provider receipt 与提交后未知异常零重放

新增迁移 `175_postgis_projection_provider_receipt.sql`，把 PostGIS 目标变更与 Provider receipt 放入同一事务。receipt 是租户隔离、append-only 的数据库证据，绑定 PostgreSQL transaction ID、plan SHA-256、幂等键、目标内容哈希和行数；receipt 不允许更新/删除，gateway 不能读取。executor/service/recovery worker 在 authority 中断或客户端提交后未知异常时，优先重读并验证 receipt；目标和 receipt 一致时只补 authority/checkpoint，Provider 不再执行，目标或 receipt 不一致则转人工核对。旧 checkpoint 仍可读取，但没有新 receipt 的未知结果不被自动推断为已提交。

临时 PostgreSQL 16 + PostGIS 真实演练 `17/17` 通过：同事务 receipt、数据库 backend 断连回滚、提交后未知异常重启零重放、receipt/目标漂移人工阻断、receipt 不可变和 gateway 隔离均有检查。最新 PostGIS 报告内部 SHA-256 为 `acaf849cf1458516534a908af9074f877380c3292c44bd4149c3592877a4849d`，文件 SHA-256 为 `93a83c73006ebea4195d7a060609f753ec9735b3b8eafd72a0a970731dbd90b8`；跨存储 recovery PostgreSQL 演练最新仍为 `37/37`，内部 SHA-256 为 `b0654d537b869a84eb122e5191573b90f8eb8d203a4727c827afe1c6e58ab188`，文件 SHA-256 为 `2fae2f0205a11f48280d0059d0ba0119808bf86b385da419c579740b6db6f87b`。专项联合回归为 `138 passed, 2 skipped`，范围均为 `temporary_database_only`；migration catalog 为 175 项，fingerprint 为 `7ed2f704ec12572f660700be38851a9c28e66293d6e05fa131060ce59c350b1c`。

该增量只关闭 PostGIS Provider 的真实提交证据和零重放技术缺口；pgvector 的同类能力已由第 45 节补齐。仍不宣称 Fuseki、MinIO/S3、Iceberg 已具备同等真实故障恢复能力，也不宣称跨存储分布式事务、生产灾备认证或客户验收。剩余项仍包括三类 Provider 的同类 receipt/故障注入、客户业务 rollback/delete/restore/corrective-forward/reconciliation 规则、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime 及自动语义规划融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`。

## 45. 2026-08-16 pgvector Provider receipt 与提交后未知异常零重放

新增迁移 `176_pgvector_projection_provider_receipt.sql`，把重庆客户 pgvector 目标变更与 Provider receipt 放入同一 PostgreSQL 事务。receipt 绑定 transaction ID、sealed plan SHA-256、幂等键、目标内容哈希、行数和状态，并由租户 RLS、append-only trigger 和 gateway 权限隔离保护。数据仍只来自重庆客户，本体仍固定为 `natural-resource-one-map 2.3.0`。

vector executor 可按 sealed plan 恢复并验证 receipt；service 在 authority 没有 checkpoint 时先查 receipt，存在且与当前目标完全一致就只补 checkpoint，不再次执行 Provider。客户端在 commit 后结果未知、进程重启或 authority 首次不可用都不会触发自动重建；receipt 缺失、篡改或目标漂移保持人工核对。

临时 PostgreSQL 16 + pgvector 0.8.2 真实演练执行 092/094/169/176，`17/17` 通过：同事务 receipt、receipt 不可变、gateway 无读取权限、提交后未知异常重启零重放、receipt/目标漂移人工阻断，以及实际终止数据库 backend 后目标和 receipt 同时回滚。报告内部 SHA-256 为 `9a207216330c5ae0a78474a56d7b43303328625e1f040d0ca243afa6295582b2`，文件 SHA-256 为 `f35a89f7c99ffd623ab9d03775511915abbdea1de794b7f907a98807c6b4b7ca`，范围为 `temporary_database_only`。五类 Provider、recovery、迁移和 deployment profile 联合回归为 `146 passed, 2 skipped`；migration catalog 为 176 项，最新迁移为 `176_pgvector_projection_provider_receipt`，fingerprint 为 `c4f138dd367fc61f0479cb0fd97ff704e0ffc086af98331d5c2f3e82215a579d`。

该增量关闭 pgvector 的真实同事务提交证据和零重放恢复技术缺口，不代表生产故障验收或多存储分布式事务。仍缺 Iceberg 的同类 receipt 与真实故障注入，以及多 Provider 联动、客户业务补偿/对账规则、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

## 46. 2026-08-16 真实 Fuseki Provider receipt 与提交后未知异常零重放

RDF/Fuseki 现已补齐与 PostGIS、pgvector 同等级别的 Provider 原生提交证据，范围仍只使用重庆客户数据和 `natural-resource-one-map 2.3.0`：

- RDF target v2 强制注册 `sparql_update_endpoint`，并要求与 Graph Store endpoint 同源；执行器不接受客户端 endpoint、凭据或目标替换；
- rebuild 先写 staging named graph，再用一个 Fuseki SPARQL UpdateRequest 同时完成 staging 到 default graph 的复制、staging 清理和 receipt named graph 写入；delete 在同一 UpdateRequest 中执行 `DROP DEFAULT` 与 receipt 写入。receipt 绑定 tenant、projection、target、action、plan SHA-256、幂等键、目标内容哈希、三元组数和自身 SHA-256；checkpoint action 只写 receipt graph；
- service/worker receipt-first：authority 没有 checkpoint 时先读 Fuseki receipt 并观察目标，一致则只补 checkpoint，receipt 不存在才执行 Provider。提交后客户端未知异常、authority 首次失败或 executor 重启均不会重放；receipt 缺失、目标漂移或绑定错误转人工核对；
- 临时真实 Fuseki 演练 `20/20` 通过，实际装载 `537,245` 条自然资源本体三元组，并验证 staging 清理、receipt/目标同一 UpdateRequest 原子性、authority 失败恢复、delete absence receipt、跨 executor 未知提交零重放、receipt/目标漂移阻断和容器/卷清理。报告内部 SHA-256 为 `e951157dae0b514d655202d3ff9b7b14a9d3723a2e054a6e87a3092da0074a25`，文件 SHA-256 为 `00a3b36de97f0ab443ea8ccedc0a05810871d1bb0c537120a64ac663e98e5f2e`，范围为 `temporary_database_only` + `temporary_container_and_volume_only`。
- 五类 Provider/recovery/deployment profile 联合回归当前为 `163 passed, 2 skipped`，包含 RDF 新增测试、PostGIS、pgvector、S3/MinIO、Spark/Iceberg 以及 recovery/迁移合同检查。

这关闭的是 Fuseki Provider “目标已提交但 authority 未落账/客户端结果未知”时缺少原生 receipt 和零重放恢复的技术缺口，不代表 Fuseki 生产验收、跨存储分布式事务或生产灾备认证。当前同类 receipt/真实故障恢复仍缺 Iceberg；其余剩余项包括多 Provider 联动故障、客户定义的 rollback/delete/restore/corrective-forward/reconciliation、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`。

## 47. 2026-08-16 真实 MinIO/S3 Provider receipt 与提交后未知异常零重放

对象存储 Provider 现已补齐可跨 executor 恢复的 plan-bound receipt，范围仍只使用重庆客户 artifact 和 `natural-resource-one-map 2.3.0`：

- rebuild 将 plan SHA-256、幂等键、action 和 receipt SHA-256 写入目标对象 user metadata；数据和 receipt metadata 同属一个 `PutObject`，提交后未知异常重启时可从目标对象恢复，不再次上传；
- delete 先写版本化、plan-bound intent object，再执行 `DeleteObject` 生成 delete marker。intent 绑定删除前 VersionId、ETag、内容哈希、大小、plan SHA-256 和幂等键；恢复必须同时验证目标缺失、最新 marker 和删除前版本证据，版本链不一致则人工核对，不自动重删；
- service receipt-first：authority 无 checkpoint 时先恢复 receipt；仅当 receipt 不存在才执行 Provider。目标内容碰巧一致但缺少 plan-bound receipt 时 fail-closed；
- 真实临时 MinIO + PostgreSQL 演练 `19/19` 通过，覆盖 versioning、metadata receipt、authority 失败后 executor 重启零重放、same-content 新版本漂移、checkpoint、stale predecessor、delete intent/marker 恢复、delete replay、history 和清理。artifact 为 `1,950,576` 字节；报告内部 SHA-256 为 `d76f5b8797f299b5edabbb6ad47f90bcbabdbe2557f4bf9702b7b298b1588023`，文件 SHA-256 为 `5c48325e8674b6f5f4579684cb1645a929bb8252f5685cd264debe7488ae8bf7`，schema 为 v2。
- 五类 Provider/recovery/deployment profile 联合回归当前为 `166 passed, 2 skipped`。

这关闭的是 MinIO/S3 Provider “目标已提交但 authority 未落账/客户端结果未知”时缺少原生 receipt 和零重放恢复的技术缺口，不代表跨对象/跨存储分布式事务、MinIO 生产验收或灾备认证。当前同类 receipt/真实故障恢复只剩 Iceberg；其余剩余项包括多 Provider 联动故障、客户定义的 rollback/delete/restore/corrective-forward/reconciliation、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`。

## 48. 2026-08-16 真实 Spark/Iceberg Provider receipt 与提交后未知异常零重放

本轮关闭五类 Provider 中最后一个“目标已提交但 authority 未落账/客户端结果未知”时缺少原生 receipt 的技术缺口，范围仍限定为重庆客户 artifact 与 `natural-resource-one-map 2.3.0`：

- rebuild 将 plan SHA-256、幂等键、action 和 receipt SHA-256 写入当前 Iceberg snapshot summary；数据文件、表替换和这组 plan-bound receipt 属于同一次 Iceberg commit。receipt 指纹不把提交后才产生的 snapshot ID 当作可重放输入，但恢复时必须重新观察当前 snapshot、内容指纹和行数，并核对 snapshot summary 的 receipt 绑定；同内容的新 snapshot 或 receipt 漂移均 fail-closed；
- delete 继续使用 warehouse 中的 plan-bound tombstone，新增 receipt schema、action、plan、幂等键和 receipt SHA-256。恢复必须同时看到表缺失、删除前 snapshot、drop evidence、tombstone 和 receipt 全部精确匹配，不能仅凭表缺失推断删除已提交；
- lakehouse executor 新增 `recover_receipt()`，service 在 authority 没有 checkpoint 时先恢复 Iceberg receipt，只有 receipt 不存在才调用 Spark Provider。重启 executor 或 authority 首次写入失败不会重复创建表或生成新的 snapshot；目标内容碰巧一致但没有本次 sealed plan receipt 时保持人工核对；
- 真实隔离演练 `18/18` 检查通过：445 个 feature、439 个 `parcel_id`，验证 snapshot receipt 跨 executor 恢复、零 Provider 重放、同内容新 snapshot 漂移拒绝、checkpoint action、delete tombstone/receipt 恢复、append-only history 和临时资源清理。报告 `docs/reports/lakehouse_projection_executor_rehearsal_2026-08-15.json` 为 schema v2，内部报告 SHA-256 为 `53fa9c2cf5edd5c95ff829e33e09ecef28ee8775ca3c0ca447464ffa09bffecd`，文件 SHA-256 为 `1d4acc49faff1c835ce8f5eaaff42eb8e5818fea351c53250de2cb4cd50a9a44`；范围为 `temporary_database_only` + `temporary_network_container_volume_bucket_and_table_only`；
- 本轮显式运行的 Provider/recovery/deployment profile 集合为 `147 passed, 2 skipped`，包括 PostGIS、pgvector、Fuseki、MinIO/S3、Spark/Iceberg、recovery、迁移和部署合同；Iceberg 专项为 `7 passed`。

因此，五类 plan-bound Provider 均已具备受控 receipt、checkpoint 串联和提交后未知结果零重放的技术基线；“再补一个 Provider”不再是当前需求。仍未完成的是多 Provider 真实联动故障与自动补偿/对账执行、客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义规划融合。Iceberg commit 与 PostgreSQL authority 仍不是分布式原子事务，演练不代表生产部署、灾备认证、专家审定、客户生产验收或法定审批；状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 49. 2026-08-16 多 Provider 联动故障与恢复编排合同（内存 rehearsal）

在五类 Provider 已分别具备 plan-bound receipt 后，本轮新增一个不宣称分布式事务的 federated recovery 合同，范围仍限定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- `FederatedProjectionRecoveryCoordinator` 将同租户、唯一且有序的 2-32 个 sealed `ProjectionRepairPlan` 组成一个 run，按顺序复用既有单 Provider worker；聚合 append-only ledger 记录 run/item/event/snapshot，前序已提交 plan 只作为证据，不自动回滚或伪造全局原子提交；
- 中间 authority 短暂失败只重试 authority；未知 Provider 结果先查精确 plan-bound receipt，找不到 receipt、目标漂移或缺少补偿规则即 `compensation_required`，后续 Provider 保持 pending；已知 no-commit 达到 provider retry budget 后 `failed_closed`；
- 重启时要求 durable per-plan recovery ledger resolver，校验 worker snapshot、item/event/snapshot 指纹、租户、plan 顺序、游标、attempt counter 和不可回退状态；`RECOVERY_REQUIRED`、`COMPENSATION_REQUIRED`、`FAILED_CLOSED` 均有明确状态合同，聚合错误证据不会被成功事件清空；
- 专项 `data_agent/test_cross_store_projection_federated_recovery.py` `8/8` 通过，覆盖三 Provider 完成、authority fail-once 零重放、未知结果 receipt 恢复、无 receipt 阻止后继 Provider、重试预算耗尽、durable ledger 重启续跑、run/tenant/duplicate plan 拒绝和三层指纹篡改拒绝。现有 projection/recovery/provider 显式回归 `115 passed`，PostgreSQL rehearsal 合同 `5 passed, 2 skipped`，Ruff 通过；
- 这仍是 `in_memory_federated_orchestration_only`，不是 PostGIS、pgvector、Fuseki、MinIO/S3、Spark/Iceberg 五存储同时断连、网络分区、进程硬杀、未知回执、队列积压或补偿执行的真实验收。跨存储分布式事务、客户业务 rollback/delete/restore/corrective-forward/reconciliation 规则、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO 和生产认证仍未完成。

结论是：多 Provider 的“按 sealed plan 顺序推进、故障停住、receipt 恢复、durable ledger 续跑”已形成可测技术基线，但真实联动故障和业务补偿决策仍是后续需求。该合同不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 50. 2026-08-16 Federated aggregate ledger PostgreSQL 持久化

第 49 节的内存 aggregate ledger 已推进为真实临时 PostgreSQL 控制面，范围仍限定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 迁移 `177_cross_store_projection_federated_recovery_ledger.sql` 新增 federated event/snapshot append-only history 和 current view；唯一写路径使用 `SECURITY DEFINER`，强制租户 RLS、不可变 trigger 和 gateway 最小权限，不开放表写入；
- `PostgresFederatedProjectionRecoveryLedger` 按 tenant + run 持久化聚合快照，校验 plan 列表和顺序、连续 event、历史前缀、最新 event、三层指纹及幂等重放。重启 coordinator 必须同时解析 aggregate PostgreSQL ledger 和各 plan PostgreSQL recovery ledger；
- 联动实测发现 170 号单 plan ledger 的 event hash 曾被错误设为 tenant 级唯一，而事件指纹本身不含 plan。177 号后继迁移将唯一性和函数查重范围收紧为 `tenant + plan + event_sha256`，允许不同 plan 在同一时刻产生相同状态事件，同时保持 plan 内 append-only；没有修改冻结的旧迁移；
- 隔离临时 PostgreSQL 以随机数据库/角色验证：第二个 plan authority fail-once 后持久化 yield，新 repository/coordinator 重载完成后续 plan，Provider 执行次数仍为 1；另验证 current/history、幂等、跨租户隐藏和伪造 snapshot SHA 拒绝。真实数据库测试文件 `4/4` 通过；常规 projection/recovery/provider/migration/deployment profile 显式集合 `148 passed, 1 skipped`，Ruff 通过；
- migration catalog 为 177 项，最新项 `177_cross_store_projection_federated_recovery_ledger`，fingerprint 为 `538ad13052887026453a27a14f89a8009df47105e9b8ee15bb1ec6722f8a0c5c`。

因此，当前边界从 `in_memory_federated_orchestration_only` 升级为 `temporary_database_federated_control_plane_only`。尚未完成的仍是五类真实 Provider 同时参与的网络分区、进程硬杀、未知回执和队列积压联动注入，以及客户定义的 rollback/delete/restore/corrective-forward/reconciliation、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。本轮不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

## 51. 2026-08-16 补偿候选方案技术基线与 PostgreSQL 权威

本轮在 federated recovery/aggregate ledger 之上增加非执行型补偿方案层，继续固定重庆客户数据与 `natural-resource-one-map 2.3.0`：

- 方案精确绑定 tenant、run、源 federated snapshot、阻塞 plan、全部 sealed plan/source content 和本体 package/content SHA-256；生成过程确定性且不会调用 Provider；
- 候选覆盖对账、批准后重放原 plan、corrective-forward、rollback、delete 和 restore。只有无副作用的 `reconcile_provider_outcome` 可以成为系统推荐；任何变更型候选均要求 ApprovalCase，客户规则缺失的候选进一步固定为 `customer_rule_required`，不能执行；
- 输出始终为 `execution_allowed=false` 和 `automatic_mutating_selection_allowed=false`。`failed_closed` 没有系统推荐；这允许没有专家在场时先生成可审计预案和缺口清单，但不把技术排序冒充客户业务决定；
- 迁移 178 以 federated snapshot 为外键持久化唯一方案，提供 RLS、不可变记录、受控函数写入、current/history、租户隔离、幂等和伪造可执行状态拒绝。真实临时 PostgreSQL authority 测试 `4 passed`，随机数据库/角色清理后残留 0；常规相关回归 `167 passed, 4 skipped`，专项常规测试 `9 passed, 1 skipped`；
- migration catalog 为 178 项，最新项 `178_cross_store_projection_compensation_proposal`，fingerprint 为 `12a29037a5c568cce86a1eee2cf7e7092740213fe88abaf6ba576704e2251b91`。

这关闭的是“没有任何补偿候选生成、排序和持久化技术产物”，不是客户业务补偿闭环。仍需客户确认 rollback/delete/restore/corrective-forward/reconciliation 规则及版本，再实现规则驱动的变更型候选选择和多 Provider 执行；真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。证据范围为 `temporary_database_compensation_proposal_only`，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

## 52. 2026-08-16 补偿方案 REST/Capability/MCP 只读表面

第 51 节的方案生成与只追加权威已接入 GIS Data Agent 的受治理调用面，范围继续固定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 新请求合同只接受 sealed plans 和其精确 federated snapshot；数量、顺序、plan SHA-256 与 tenant 不一致即拒绝，也不允许 body 额外提交 tenant、执行开关、选择结果、Provider 目标或凭据；
- REST 路由 `/api/platform/v1/projections/federated/compensation-proposals` 从认证上下文取得 tenant/角色，执行 Capability fingerprint 检查，只返回确定性 proposal，不持久化或调用 Provider；
- CapabilitySpec `projection.federated.compensation-proposal@1.0.0` 真实声明为 `QUERY + SideEffect.NONE`；MCP 工具 `generate_federated_projection_compensation_proposal` 使用相同输入/输出合同，tenant 与角色只取 MCP context，read-only/destructive annotation 分别为 true/false；
- 专项负向用例覆盖 tenant override、跨 tenant、缺少 MCP tenant、非 operator、合同指纹漂移和 Provider 零调用；相关联合回归 `198 passed, 2 skipped`。

这关闭的是“Agent 和操作员没有受治理入口查看补偿候选”，不是“Agent 可以执行补偿”。公共入口不会隐式调用第 51 节的 authority 写路径，输出仍固定 `execution_allowed=false`、`automatic_mutating_selection_allowed=false`、`technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。客户业务规则版本、变更型候选选择/批准/执行、真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成；本轮不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

## 53. 2026-08-16 持久补偿方案 current/history 受治理查询

第 52 节的公共 POST 只即时生成方案，不会写入 authority。本轮进一步开放第 51 节已持久化记录的只读 current/history 查询，仍固定重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 读请求只有 federated `run_id`，tenant 只能来自认证或 MCP context；响应校验 current 必须是 history 最后一项，所有记录必须同 tenant/run，history count 必须一致，且执行开关始终为 false；
- PostgreSQL store 以单条参数化 SQL 同时读取 current 与完整有序 history，继续受 gateway role、tenant session context、RLS 和 security-invoker view 约束，不新增迁移或写权限；
- 新增 REST GET `/api/platform/v1/projections/federated/compensation-proposals/{run_id}`、CapabilitySpec `projection.federated.compensation-proposal.get@1.0.0` 和 MCP 工具 `get_federated_projection_compensation_proposal`，均声明只读；not-found 与 authority unavailable 分别返回 404/503 或对应 MCP 错误；
- 相关联合回归 `202 passed, 2 skipped`；真实临时 PostgreSQL authority 专项 `4 passed`，包含 current/history lookup、跨租户空结果和资源清理。

这关闭的是“持久方案只有内部代码可读”，不是 proposal 写入或补偿执行。公共生成入口仍不持久化，新增查询入口只有 SELECT；客户业务规则、变更型候选的选择/批准/执行、真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。状态固定为 `technical_baseline_unreviewed`，用途固定为 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

## 54. 2026-08-16 客户补偿规则合同与只读就绪度评估

本轮在补偿 proposal 缺口 ID 之上增加严格、版本化但不执行的客户规则合同，范围继续固定为重庆客户数据与 `natural-resource-one-map 2.3.0`：

- 规则合同绑定 rule ID、SemVer、action、重庆数据范围、精确本体 package/content SHA-256、适用 Provider/target、必需证据和 mutation 声明；支持 reconciliation、corrective-forward、rollback、delete、restore，sealed-plan reapply 继续走独立 ApprovalCase，不伪装成客户规则；
- 生命周期只有 `draft_unreviewed`、`awaiting_customer_approval` 和带显式签名证据的 `customer_approved`。批准证据必须绑定规则 ID/version/SHA-256、客户权威主体、批准 artifact、算法、key、公钥指纹和规范化签名载荷；合同实际执行 Ed25519、ECDSA P-256 或 RSA-PSS 验签，仓库没有播种任何已批准客户规则；
- 确定性评估将 proposal 所需规则逐条分类为 `missing`、`draft_unreviewed`、`awaiting_customer_approval`、`approved_but_not_executable` 或 `invalid_or_drifted`，并检查 sealed target 覆盖与证据完整性。所有分类始终 `execution_allowed=false`、`automatic_mutating_selection_allowed=false`；部署侧信任根的进一步约束见第 55 节；
- REST `POST /api/platform/v1/projections/federated/compensation-rule-assessments`、Capability `projection.federated.compensation-rule.assess@1.0.0`（第 55 节升级为 `1.1.0`）和 MCP `assess_federated_projection_compensation_rules` 均为 `QUERY + SideEffect.NONE`，tenant/role 只取上下文，执行密码学验签但不持久化、不批准、不选择、不调用 Provider；
- 模型/API 专项 `15 passed`，联合回归 `288 passed, 4 skipped`；本轮新增模块、API、Capability 和测试文件的 Ruff、全部受影响模块编译及 scoped diff 检查通过，MCP 注册模块也通过 `py_compile`；没有新增迁移。

这关闭的是规则合同与只读差距评估能力，不是客户业务规则本身。下一步仍需客户提供真实签署的 rollback/delete/restore/corrective-forward/reconciliation 规则版本，再建设租户隔离 rule authority、规则驱动选择、ApprovalCase 绑定和实际执行。五 Provider 联动故障、备份/PITR/RPO/RTO、容量/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。本轮不代表客户批准、专家审定、生产验收、恢复认证、法定审批或行政决定，状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`。

## 55. 2026-08-16 客户审批密钥部署侧信任注册表

上一节已实现签名算法验真，但“提交的公钥能验签”不等于“公钥属于客户”。本轮在同一重庆数据集和 `natural-resource-one-map 2.3.0` 范围内补齐部署侧信任根：

- `cross_store_projection_compensation_trust.py` 将 tenant、客户 authority、key ID、签名算法、公钥指纹、有效期、撤销状态和 anchor SHA-256 封装为不可变注册表；同一 key 可覆盖多条规则，但同一身份不能存在冲突锚点；
- REST/MCP 只接受调用方提交的规则与签名证据，信任注册表只能由 `GDA_CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_JSON` 进入服务端。未配置时普通缺口评估仍可用，只有 `customer_approved` 被降为 `invalid_or_drifted`；配置 JSON 错误单独返回 authority/configuration error；
- 只有 authority、key、算法、公钥指纹、签名时间、当前时间和 active 状态全部匹配，才返回 `approved_but_not_executable`。缺失、未信任、撤销和超窗分别输出明确 reason code；不自动选择、不执行、不调用 Provider；
- 评估输出合同升为 v2，新增 trust-anchor 指纹和 `customer_approval_trusted`；Capability 升为 `1.1.0`，仍为只读查询。trust/规则/API 专项 `24 passed`，显式联合回归 `271 passed, 4 skipped`，Ruff 和 Python 编译通过，没有新增 migration。

这关闭的是“自带公钥即可宣称客户批准”的边界缺口，不代表客户已经提供真实 key、签署规则、专家审定、生产验收或法定审批。下一步仍需部署侧安全责任方维护真实 key 注册表，客户提供规则版本，再实现 rule authority/current/history、规则驱动的变更候选选择、ApprovalCase 绑定及执行；多 Provider 真实联动故障、备份/PITR/RPO/RTO、容量/生产 SLO、全执行面安全和自动语义规划融合仍未完成。状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`。

## 56. 2026-08-16 客户补偿规则 authority current/history 与受治理只读入口

第 55 节留下的 rule authority/current/history 缺口已推进为可验证的 PostgreSQL 技术基线，仍只使用重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 新增 migration `179_cross_store_projection_compensation_rule_authority.sql` 与 `PostgresCustomerCompensationRuleAuthorityStore`。规则合同采用 append-only history + current view，唯一写入路径是 `SECURITY DEFINER` 受控函数；tenant RLS/FORCE RLS、不可变 UPDATE/DELETE trigger 和 gateway 最小权限生效，gateway 没有表直写权限。migration catalog fingerprint 为 `3375b3627aad1cf484c0911a118bf19774ac38dd90b9001509b072c6e1174d9c`，179 号迁移文件 SHA-256 为 `f8de8e0e3f4da177d06686ca49794914cdc00864c948ddbd290a4d944b522483`；
- 数据库层校验租户、规则 ID、SemVer、rule/contract hash、重庆数据范围、本体 package/content SHA-256、固定 review/intended-use 和两个执行开关；新增 contract 的生命周期禁止从 approved 回退，完全相同 contract 幂等返回。Python 写入口另行阻止已 approved 后对历史 draft/awaiting contract 的幂等重放；Python 层继续先做签名验真和部署 trust registry 匹配，数据库不冒充密码学验签；
- 新增 `GET /api/platform/v1/projections/federated/compensation-rules`、Capability `projection.federated.compensation-rule.get@1.0.0` 和 MCP `get_federated_projection_compensation_rules`。可选 `rule_id` 只缩小查询，tenant/role 只能来自认证或 MCP context；读结果包含 current/history，执行开关保持 false，不提供写入、批准、候选选择或执行入口；
- authority 单测 `20 passed, 1 skipped`，REST/MCP/Capability 专项 `4 passed`，相关组合回归 `40 passed, 1 skipped`；Python 编译、Ruff 和 scoped `diff --check` 通过，迁移目录当前为 179 项。真实 PostgreSQL 演练因未配置 `DATABASE_URL` 跳过，不能表述为生产数据库验收。

这关闭的是“客户规则只能随评估请求临时提交、没有持久 current/history 和受治理读取面”的产品技术缺口。仍未完成的是客户实际规则版本和业务语义确认、规则驱动变更候选选择、ApprovalCase 绑定与变更执行，以及多 Provider 真实联动故障、备份/PITR/RPO/RTO、容量/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。该能力仍只是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision` 的非生产决策证据，不代表客户批准、专家审定、客户生产验收、生产恢复认证或法定审批。

## 57. 2026-08-16 Proposal 派生技术基线规则与 authority current 评估

第 56 节的 rule authority 已可持久化和读取，但初始化仍依赖人工拼装规则合同，在线评估仍要求调用方重复提交 proposal 和规则。本轮继续固定重庆客户数据与 `natural-resource-one-map 2.3.0`，补齐内部草案装载和只读 current 评估：

- 技术基线构建器只从 sealed proposal 的规则缺口、action、目标和 required evidence 生成确定性 `1.0.0` 草案；状态只能是 `draft_unreviewed`，不生成客户批准、不补写客户业务语义，执行开关始终为 false；
- authority bootstrap 对每个 rule ID 加与受控写函数一致的 advisory lock，仅在没有 current 时写入。重复执行幂等，已有 draft/awaiting/approved 均不被覆盖；返回 created、reused 和 drift 清单。内部脚本可按 tenant/run 从已持久化 proposal 自动完成这一流程，但未开放公共规则写 API；
- `assess_current(run_id)` 在同一 PostgreSQL 事务和一条查询中读取 proposal current 与 rule current，避免调用方上传或替换权威证据。新增 GET `/api/platform/v1/projections/federated/compensation-rule-assessments/{run_id}`、Capability `projection.federated.compensation-rule.assess-current@1.0.0` 和 MCP `assess_persisted_federated_projection_compensation_rules`，均为 `QUERY + SideEffect.NONE`；
- 测试覆盖草案确定性、零批准、幂等、已有 current 不覆盖、漂移报告、单快照读取、认证 tenant/role、not-found/outage 和 MCP/REST 只读合同。相关回归 `219 passed, 2 skipped`；真实 PostgreSQL 演练因未配置 `DATABASE_URL` 跳过。未新增 migration，catalog 保持 179。

这使团队在暂无专家审定时仍可推进规则目录和缺口治理，但不能把 proposal 派生草案当成客户确认规则。剩余需求是客户真实 rollback/delete/restore/corrective-forward/reconciliation 规则版本、签署材料和真实 trust anchor，随后才可推进规则驱动候选选择、ApprovalCase 绑定和变更执行。真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/生产 SLO、全执行面 Subject-Purpose-Resource 安全、通用 Proposal/Action runtime 和自动语义规划融合也仍未完成。状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、恢复认证或法定审批。

## 58. 2026-08-16 可信客户规则驱动的补偿候选 ApprovalCase 审查入口

第 57 节留下的“规则 current 已就绪但无法与具体候选形成待审案例”已推进为受治理控制面，范围仍固定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 新的审查 binding 将 tenant/run、proposal、源 snapshot、操作员选定候选、sealed plan、rule assessment、客户规则合同、批准 artifact 和部署 trust anchor 的 SHA-256 密封为单一指纹；候选或任一权威证据变化都会拒绝旧绑定；
- 仅允许 corrective-forward、rollback、delete、restore 四类客户规则治理的变更候选，且所需规则必须同时满足 authority current `customer_approved`、评估 `approved_but_not_executable`、部署 trust anchor 匹配。missing、draft、awaiting、drifted 或 untrusted 状态均不能创建案例；reconciliation 与 sealed-plan reapply 不混入该入口；
- 创建的通用 `ApprovalCase` action 固定为 `projection.federated.compensation.review`，tenant/requester 只取认证上下文，同一 binding 确定性幂等。`automatic_mutating_selection_allowed=false`、`approval_case_is_execution_authority=false`、`execution_allowed=false` 被同时写入 binding、case context 和响应；本入口不会调用 Provider；
- 对外新增 REST POST `/api/platform/v1/projections/federated/compensation-approval-cases`、Capability `projection.federated.compensation-approval.request@1.0.0` 和 MCP `request_federated_projection_compensation_approval`。Capability 为 `COMMAND + CONTROL_WRITE`、中风险、强制幂等，MCP 为非破坏且幂等的控制写；
- 核心/API 专项 `14 passed`，补偿/恢复组合 `119 passed, 3 skipped`，Capability/MCP/ApprovalCase 组合 `79 passed`；Ruff、编译和 scoped diff 检查通过。真实 PostgreSQL 端到端测试已加入，但当前没有 `DATABASE_URL`，结果为 `1 skipped`，不能声称真实数据库或生产验收；未新增 migration，catalog 仍为 179。

这关闭的是“技术上不能申请审查”，不是“客户已经批准”或“系统可以执行补偿”。仓库当前没有真实客户签署规则、批准材料和生产 trust anchor，也没有专家审定；proposal 派生的 `draft_unreviewed` 不会越过门禁。剩余工作是建立 approved 案例到规则驱动执行的独立授权和一次性消费链路、实现多 Provider 补偿/对账策略及真实故障验证，并完成备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。结果保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、恢复认证、法定审批或行政决定，也不代表跨存储分布式事务。

## 59. 2026-08-16 补偿双审批门禁与一次性执行授权消费

第 58 节的 review-only 案例与执行授权现已从合同、数据库和对外申请表面三层分离，范围继续固定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 第二阶段申请会从 proposal/rule authority current 重新构建候选，不把 review approved 状态直接当作权限。review 必须已批准、未过期并与当前 binding 完全一致；新的 ApprovalCase 使用 `projection.federated.compensation.execute`、独立 candidate target、独立 ref 和 fingerprint，有效期不超过 review；
- migration 180 提供 append-only、tenant RLS/FORCE RLS 的一次性消费权威。消费前同时检查两个案例均 approved/未过期、两个 human 决策者不同、proposal/candidate/approved rule current 未漂移；相同请求幂等，不同重放或 review 二次消费冲突。receipt 只证明授权已消费，固定 `provider_execution_performed=false`，不是 Provider 执行结果；
- 消费 API 不向 REST/MCP 公开。对外只提供 POST `/api/platform/v1/projections/federated/compensation-execution-approval-cases`、Capability `projection.federated.compensation-execution-approval.request@1.0.0` 和 MCP `request_federated_projection_compensation_execution_approval`，均为非破坏、强制幂等的 `COMMAND + CONTROL_WRITE`；路由共 76 条；
- 联合回归 `199 passed, 7 skipped`，聚焦回归 `104 passed, 1 skipped`，migration/deployment profile `30 passed`。真实 PostgreSQL 用例因无 `DATABASE_URL` 跳过。migration catalog 为 180 项，fingerprint `6ea1a428838aeb3e5b5fd53cad4d6e10594419bc7c86ed0757695d6f3dc3147b`；Ruff、编译、MCP 语义检查和 diff 检查通过。

这关闭了“review 批准即执行”和“授权可重复消费”的技术缺口，但没有实现 Provider 调用、多 Provider 客户补偿策略、执行 receipt 对账、失败后的后续决策或生产故障验证。真实客户规则/签署材料/trust anchor、专家或客户审定、备份/PITR/RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍是剩余需求。状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`；不代表客户批准、专家审定、生产验收、恢复认证、法定审批或跨存储分布式事务。

## 60. 2026-08-16 消费后 Provider dispatch intent 证据重绑定

双审批授权消费后，系统新增一个仍不执行 Provider 的 dispatch-intent 层：

- `FederatedProjectionCompensationDispatchIntent` 重新绑定当前 proposal、候选 action、sealed plan/source target、已批准规则合同、两个 ApprovalCase ref 和消费 receipt；proposal/rule drift、伪造 ref/hash、未封存 plan 和错误 action 均拒绝；
- intent 不接收 SQL、凭据、Provider endpoint 或客户业务参数，状态为 `provider_adapter_pending`，固定 `provider_dispatch_performed=false`、`execution_allowed=false`；没有新增公共 API 或数据库写路径；
- 专项 `22 passed, 1 skipped`，真实 PostgreSQL 仍因没有 `DATABASE_URL` 跳过；Ruff、编译和 diff 检查通过。

这使“授权消费后到 Provider 调度前缺少当前证据重绑定”进入可验证技术基线，但不等于 Provider 已执行。剩余工作仍是客户规则驱动的 adapter、真实 PostGIS/pgvector/RDF/对象存储/Iceberg 调用、执行回执与结果对账、reconciliation 业务决策、备份/PITR/RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收或跨存储分布式事务。

## 61. 2026-08-16 Provider adapter 部署注册与解析基线

在 dispatch intent 之后新增一层部署侧 adapter contract，仍固定重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- adapter definition/registry 以 tenant、adapter ID、SemVer、精确 target engine/target_ref 集合、四类客户规则 action 和五类既有 receipt schema 建立不可变 allowlist，并用 definition/registry SHA-256 防止版本或内容漂移；
- registry 只从 `GDA_FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_JSON` 加载，未配置就是空注册表。解析请求只能选择部署身份和 hash，不能提交 endpoint、凭据、SQL、目标覆盖或客户业务参数；
- resolver 重新验证 dispatch intent、请求和 registry，并精确比较重庆范围、本体 package/content、候选 action、target 集合和 receipt contract。未注册、漂移、不支持或 baseline 不一致均拒绝；成功状态仍是 `adapter_resolved_pending_execution`，`provider_dispatch_performed=false`、`execution_allowed=false`；
- 本轮不新增公共表面和 migration，也不导入/调用真实 Provider；新增 adapter/dispatch 专项 `8 passed`，Ruff、编译和 diff 检查通过。

产品状态因此从“缺少 adapter 身份边界”推进到“已有部署 allowlist 和 fail-closed resolver”，但不应把它计入 Provider 已执行能力。剩余需求是分别接线 PostGIS、pgvector、RDF/Fuseki、对象存储和 Spark/Iceberg 的客户规则 mutation adapter，建立各自 receipt 内容/指纹验证与统一结果对账，再进行真实多存储故障、备份/PITR、RPO/RTO、容量/生产 SLO 和完整 Subject-Purpose-Resource 安全验证。规则语义、客户批准、专家审定和生产验收仍是外部证据；本层继续保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

## 62. 2026-08-16 Provider implementation artifact 与 mutation plan binding

在 adapter resolver 之后增加非执行型 plan binding：

- 部署注册必须提供 `implementation_artifact_sha256`，并为每个支持的客户 action 与 target engine 组合登记 operation contract SHA-256；不允许只声明一部分实现范围；
- `ProviderPlanBinding` 将 dispatch intent 的每个源 plan 绑定到 adapter resolution、目标、operation contract、receipt schema 和确定性 provider idempotency key；plan set 可重放且拒绝 resolution、目标或合同漂移；
- plan set 的执行材料状态固定为 `deployment_payload_not_materialized`，不接受 SQL、endpoint、凭据、客户业务参数或 Provider payload，`provider_dispatch_performed=false`、`execution_allowed=false`；
- adapter/plan/dispatch 专项共 `9 passed`，无新增公共 API、Capability、MCP 或 migration。

这补齐的是 Provider 接线前的实现身份、范围覆盖和幂等证据，不是实际 Provider 调用。剩余需求仍是五类真实 mutation adapter、receipt 内容/指纹验证、执行结果对账、未知结果恢复、reconciliation 业务规则以及真实多存储故障和生产 SLO 验证；客户规则、专家审定和生产验收仍未被推定。状态继续保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

## 63. 2026-08-17 部署材料摘要与 Provider receipt 候选校验

在非执行型 Provider plan set 之后增加两个受控合同层，继续固定重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- materialization set 要求部署工作负载对每个 plan position 恰好提交一个 projection ID 与 payload SHA-256，并重新绑定 target、provider action、receipt schema、provider plan hash 和 idempotency key；它不保存 payload、SQL、endpoint 或凭据，也不负责定位私有材料；
- materialization 状态为 `deployment_payload_materialized_pending_provider_dispatch`，但仍固定 `provider_dispatch_performed=false`、`execution_allowed=false`；
- receipt candidate validator 复用五类既有 Provider 原生 receipt 模型及各自指纹函数，校验 schema、tenant、projection、target、action、plan、idempotency 和 receipt SHA-256。成功输出不携带原始 receipt，状态为 `validated_not_authority_admitted`，且 `authority_write_allowed=false`、`receipt_is_authority_record=false`；
- 重庆夹具中的 PostGIS、RDF/Fuseki、Spark/Iceberg 三目标成功路径和 fail-closed 漂移路径已覆盖。新增专项 `11 passed`，相关宽回归 `263 passed, 7 skipped, 1 warning`；因没有 `DATABASE_URL`，本轮不声称真实 PostgreSQL 验证。

产品状态由“只有非执行 plan binding”推进到“具备部署材料摘要和 Provider 回执候选校验边界”，但真实 Provider adapter、mutation 调用、receipt authority 接纳、checkpoint/结果对账与 reconciliation 业务裁决仍未实现。Vector 和对象存储只有同一模型级校验能力，不属于本轮重庆三目标实测。真实多存储故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全和客户验收仍是后续工作；状态保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

## 64. 2026-08-17 完整 Provider receipt 集与 authority admission 候选

在逐个 receipt 校验之后新增完整集合门禁：

- receipt set 重新绑定 proposal/candidate、源 snapshot、双 ApprovalCase、已消费执行授权、dispatch、adapter plan、implementation artifact 和 materialization；
- 重庆 PostGIS、RDF/Fuseki、Spark/Iceberg 三个 materialization binding 必须各有且仅有一个校验回执，拒绝缺失、重复、跨 materialization 混入和 plan/target/idempotency/schema 漂移；
- 回执观测时间不得早于授权消费时间；`checkpoint/rebuild/delete` 还必须与 `checkpointed/completed/deleted` 或合法 replay 状态及目标存在性一致；
- 成功状态仅为 `complete_provider_receipts_pending_authority_admission`。集合不携带原始 receipt/commit ref，且 `authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`；它不调用 Provider，也不写 authority；
- materialization/receipt/set 专项 `19 passed`，相关宽回归 `271 passed, 7 skipped, 1 warning`。没有 `DATABASE_URL`，因此不声称真实 PostgreSQL 验证。

产品已具备“完整回执集才能进入后续接纳决策”的代码边界，但还没有用原始 sealed repair plan 与当前 checkpoint predecessor 构造/写入 checkpoint，也没有 authority admission、补偿完成落账或真实 Provider mutation。真实多存储故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全和客户验收仍未完成；状态保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

## 65. 2026-08-17 期望目标状态与 checkpoint admission candidate

继续把 Provider 调用前后的结果边界封存：

- materialization 现在必须保存期望目标是否存在、目标内容 SHA-256 和行数，并将这些字段纳入 provider plan 身份；`rebuild`/`delete` 的期望存在性也有明确门禁；
- receipt validator 要求 Provider 原生回执与上述期望结果完全一致，正确 receipt 指纹不能掩盖结果漂移；
- 新增 checkpoint candidate set，要求每个目标给出当前 checkpoint predecessor 摘要和下一版本号。初始版本必须是 1，后继版本必须带 predecessor 并递增；
- candidate set 只记录 source/provider/receipt/materialization/predecessor 的摘要，状态为 `checkpoint_candidates_pending_authority_admission`，不构造 `ProjectionCheckpoint`、不写 authority、不标记补偿完成；
- 相关专项 `21 passed`，宽回归 `277 passed, 7 skipped, 1 warning`。没有 `DATABASE_URL`，因此不声称真实 PostgreSQL 验证。

产品现在具备从“完整回执”到“可供 authority 审查的 checkpoint 候选”的非写入边界。仍需独立 admission 服务拿到原始 sealed repair plan 和真实 predecessor 后构造、幂等写入 checkpoint，并继续完成真实 Provider mutation、reconciliation、生产故障、备份/PITR、RPO/RTO、SLO 和客户验收。

## 66. 2026-08-17 原始 sealed repair plan admission preview

在 checkpoint candidate 之后增加只读 admission 输入与 preview 合同：

- `FederatedProjectionCompensationCheckpointAdmissionRequest` 接收完整原始 `ProjectionRepairPlan` 集合，并按 `plan_sha256` 将其与 candidate、Provider plan binding、materialization binding 逐项重绑定；
- 每个目标都会复核 source resource version/content、projection identity、target engine/ref、repair action、desired target existence/content/row count、materialization 期望结果，以及 predecessor SHA-256 和下一 checkpoint 版本。任何 desired state 与 materialization 不一致，或计划集合缺失/重复/漂移，都会 fail closed；`fail_closed` 原始计划不能生成 admission preview；
- preview 只输出摘要、通过的固定检查项和指纹，标记 predecessor 来源为部署提供的当前摘要，不把它写成已从 authority 实时读取。request/item/preview 全部保持 `authority_admission_performed=false`、`authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`，不构造 `ProjectionCheckpoint`，不调用真实 authority；
- 新增专项 `3 passed`；补偿链相关回归 `142 passed, 4 skipped, 1 warning`，Ruff 和格式检查通过。真实 PostgreSQL 仍因未配置 `DATABASE_URL` 跳过。

产品能力因此从“checkpoint candidate 待 authority admission”推进到“原始 sealed repair plan 与 candidate 的不可写反向 admission preview”。剩余关键需求是 authority owner 的真实 predecessor 查询、tenant/RLS/权限门禁、幂等 checkpoint 写入、并发冲突和补偿完成判定；真实五类 Provider mutation、结果 reconciliation、备份/PITR、RPO/RTO、生产 SLO、完整执行面安全、客户规则批准和客户/专家验收仍未完成。状态保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

## 67. 2026-08-17 authority current predecessor 只读核对

在 admission preview 之后增加 authority current 的只读核对：

- 新模块按每个目标调用 `PostgresProjectionCheckpointAuthority.current()`，读取当前 checkpoint 的 tenant、projection、target、checkpoint SHA-256 和版本；
- 首版候选必须与 authority 空状态/版本 0 匹配，后继候选必须精确匹配当前 checkpoint SHA-256，并且下一版本只允许加 1；live predecessor 漂移、旧版本和非 PostgreSQL authority 配置都会拒绝；
- 输出仅为不可写 read preview，不构造 checkpoint，不调用 `record()`，所有 authority/checkpoint/compensation 写入标志继续为 false；
- 新增专项 `3 passed`，补偿链回归 `145 passed, 4 skipped, 1 warning`，Ruff 和格式检查通过。

产品能力现已具备“sealed plan → candidate → authority current predecessor”三段只读核对链。剩余下一步是经过 RLS、权限和并发门禁后执行真实 checkpoint 幂等写入，并在写入成功后记录补偿完成；真实客户规则驱动的变更执行、多 Provider 联动故障、备份恢复、生产 SLO 和正式客户验收仍未完成。

## 68. 2026-08-17 checkpoint write intent（不可写）

在 authority current 只读核对之后增加不可写的 `CheckpointWriteIntent`：

- intent/set 固定原始 plan SHA-256、原始幂等键、authority-read preview、Provider plan/idempotency/receipt 摘要、目标状态和 predecessor/version，生成结果可确定性重放；
- `target_commit_ref` 使用受限 canonical 结构，主体和时间戳均经过门禁，不能由调用方注入任意 Provider commit 信息；
- intent 只是未来 `record()` 的输入 handoff，不构造 `ProjectionCheckpoint`，不写 authority，不标记补偿完成；
- 新增专项 `3 passed`，补偿链回归 `148 passed, 4 skipped, 1 warning`。

产品现在具备“sealed plan → candidate → live authority predecessor → checkpoint write intent”的不可写证据链。剩余下一步是实现真实 writer 的最终目标观察、RLS/权限和并发校验、幂等 `record()` 写入、冲突处理和补偿完成落账；真实客户规则驱动执行、跨 Provider 联动故障、备份恢复、生产 SLO 和客户验收仍未完成。

## 69. 2026-08-17 最终目标观察绑定的 checkpoint write request（仍不可写）

在 write intent 之后增加最后一层目标实测绑定，范围继续固定为重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- builder 要求 PostGIS、RDF/Fuseki、Spark/Iceberg 三个目标各提供且只提供一个最终 `ProjectionTargetObservation`，并按 tenant、projection、engine、target ref 逐一匹配；缺失、重复、多余或错误身份全部拒绝；
- 最终观察的存在性、内容 SHA-256、行数和时间必须与原始 repair plan、write intent 及 Provider receipt 期望结果一致；同时复核 plan SHA-256/原始幂等键、live authority predecessor SHA-256 和严格加一版本；
- 使用现有 `build_projection_checkpoint_from_repair()` 生成确定性 `ProjectionCheckpoint`，再复核 checkpoint fingerprint。输出 request/set 可作为未来受控 writer 的精确输入，但状态仍为 `checkpoint_write_request_pending_authority_record`；
- 模块不持有 authority writer、不调用 `record()`、不标记补偿完成，全部 authority/checkpoint/compensation 写入标志保持 false；
- 新增专项 `5 passed`，五层联合回归 `19 passed`，补偿治理链宽回归 `155 passed, 5 skipped, 1 warning`；跳过项仍为未配置真实 PostgreSQL 环境的用例，warning 为既有 OpenTelemetry 弃用提示。Ruff、格式和 Python 编译检查通过。

产品能力现已推进为“sealed plan → candidate → live predecessor → write intent → final observation-bound checkpoint write request”。仍未实现的是在真实 PostgreSQL RLS、主体权限和并发 CAS 门禁下幂等执行 `record()`、处理重放与冲突，并在完整写入后落账补偿完成；真实客户规则 Provider mutation、未知结果 reconciliation、多 Provider 联动故障、备份/PITR/RPO/RTO、容量/生产 SLO 和正式客户验收也仍是剩余需求。该 request 不是已写入 checkpoint，不代表 authority admission、客户批准、专家审定、生产验收或跨存储分布式事务。

## 70. 2026-08-17 受控 checkpoint authority writer

最终观察绑定 request 之后已增加受控 writer，继续复用现有 PostgreSQL checkpoint authority，不新增表直写入口：

- writer 在任何写入前先对三目标执行 authority-current preflight；live current 必须是 sealed predecessor 或本次 checkpoint 的精确幂等重放。任一目标漂移会在零 `record()` 调用时拒绝整批；
- 通过后按 position 调用唯一 `record()` 路径，由数据库继续执行 gateway role、tenant RLS、advisory lock、CAS、append-only 和幂等门禁；同证据重放返回 `idempotent_replay`；
- 结果明确区分 created/replay、冲突、权限拒绝、validation reject、结果未知和 authority 响应不一致。失败后立即停止，保存已尝试前缀与未尝试位置，状态为 `checkpoint_authority_records_incomplete_pending_reconciliation`；
- 三目标写入不是跨目标原子事务，writer 不删除已提交 checkpoint。完整成功也只进入 `checkpoint_authority_records_complete_pending_compensation_completion`，补偿完成标志仍为 false；
- 新增专项 `7 passed, 1 skipped`，七层链与 authority 合同联合回归 `31 passed, 1 skipped`，补偿治理链宽回归 `162 passed, 6 skipped, 1 warning`；Ruff、格式和编译检查通过。真实 PostgreSQL/RLS 用例已加入，但因无 `DATABASE_URL` 当前跳过，不能视为真实数据库验收。

产品链已推进为“final observation-bound request → controlled authority record → complete 或 partial/unknown 明确分流”。下一项是独立 completion authority：重新核对全部 current checkpoint，只对完整 record set 幂等落账补偿完成，partial/unknown 必须先 reconciliation。真实客户规则 Provider mutation、多 Provider 联动故障、备份/PITR/RPO/RTO、容量/生产 SLO 和正式客户验收仍未完成；本层不代表跨目标原子事务、跨存储分布式事务或生产验收。

## 71. 2026-08-17 checkpoint 补偿完成 authority

受控 writer 之后已增加独立 completion admission 和 PostgreSQL append-only authority：

- 只接受完整且 sealed 的 checkpoint authority record set；partial、失败、unknown、response mismatch 和未尝试位置均在 completion current read 前拒绝；
- 对全部目标重新读取 live current，逐项绑定 write request、authority record item、checkpoint SHA-256 和版本，生成确定性 completion request；
- 数据库写入仅经 tenant-bound `SECURITY DEFINER` 函数完成，表启用 RLS/FORCE RLS、append-only trigger，gateway 无表级写权限；相同证据幂等回放，不同证据冲突；
- SQL 按规范顺序取得所有 checkpoint target lock，并在 insert 前再次读取 current，拒绝 admission 后发生的并发推进；目标 JSON 必须包含全部 11 个标准键，未知键替换不能绕过校验；
- receipt 只声明 `checkpoint_compensation_completion_recorded=true`，同时固定 `provider_execution_performed_by_completion_authority=false`，不把 checkpoint 落账伪装成真实 Provider mutation；
- 隔离临时 PostgreSQL 专项 `10 passed`，migration/profile 合同 `49 passed`，projection consistency、authority 与补偿链宽回归 `170 passed, 8 skipped, 1 warning`；Ruff、格式、编译和差异检查通过。

至此，产品已有“sealed plan → candidate → live predecessor → write intent → final observation-bound request → controlled writer → completion authority”的 checkpoint 技术闭环。剩余需求转为重庆客户数据上的真实客户规则 Provider mutation 样例、unknown/reconciliation 的业务结案、多 Provider 故障演练、备份/PITR/RPO/RTO、容量与生产 SLO、正式客户批准和验收。`natural-resource-one-map 2.3.0` 可继续作为当前技术基线推进，但状态仍是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表专家审定、客户批准、法定审批、生产验收或跨存储分布式事务。

## 72. 2026-08-17 重庆数据范围的真实 PostGIS Provider mutation adapter

在 completion authority 之后，产品增加了第一个真实 Provider mutation 技术闭环，仍只使用重庆客户数据范围和自然资源本体 `natural-resource-one-map 2.3.0`。本轮的“真实”是临时隔离 PostgreSQL/PostGIS 中的受控目标 mutation，不是客户生产数据写入、客户业务决定或生产验收：

- 新增 `cross_store_projection_compensation_postgis_adapter.py`，把 dispatch intent、Provider plan/materialization、原始 sealed repair plan、allowlisted PostGIS target 和结构化 rows 重新绑定。adapter 在 Provider 调用前核对 tenant/run/position、target identity、provider plan/materialization binding、payload SHA-256、desired state、row count 和 receipt schema；漂移在零 Provider 调用前拒绝；
- provider-local execution plan 使用 materialization 生成的 `provider_plan_sha256` 和 provider idempotency key，避免将原始 repair plan SHA 与部署侧 Provider plan SHA 混用。请求模型 `extra=forbid`，不接受 SQL、endpoint、credentials 或调用方目标覆盖；
- 复用既有 `PostGISProjectionRepairExecutor` 和显式 target registry。PostGIS 目标替换、内容观察、provider receipt insert 在同一 PostgreSQL 事务内完成；首次执行返回 `provider_mutation_committed`，同一 idempotency request 返回 `provider_idempotent_replay`；既有 receipt candidate validator 可继续验证该 receipt，但不把它提升为 checkpoint 或 completion authority；
- adapter 结果明确 `provider_execution_performed_by_adapter=true`，同时 `checkpoint_authority_write_performed_by_adapter=false`、`compensation_completion_recorded_by_adapter=false`。真实临时 PostgreSQL 专项 `4 passed`；PostGIS executor 与 provider 相关回归 `46 passed`；不启用数据库的 compensation 宽回归 `167 passed, 8 skipped, 1 warning`。启用本机数据库的宽回归为 `172 passed, 3 failed, 1 warning`，失败是本轮前已存在且之前被跳过的 ApprovalCase migration 前置依赖/规则 authority 回退检测问题，不能用来否定本 adapter 的专项结果；

产品因此从“Provider mutation 仍只有合同层”推进到“PostGIS 单目标、结构化 payload、receipt 同事务、幂等 replay”的可重复技术样例。剩余需求仍包括 RDF/Fuseki、Spark/Iceberg、对象存储等 Provider adapter；重庆真实客户字段/业务参数的部署材料和规则映射；receipt authority admission 与 checkpoint/completion 对账；unknown/reconciliation 业务结案；多 Provider 联动故障；备份/PITR、RPO/RTO、容量/生产 SLO；完整执行面安全；以及正式客户批准、专家审定和客户生产验收。当前仍保持 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

## 73. 2026-08-17 自然资源本体 2.3.0 的真实 RDF/Fuseki mutation adapter

在 PostGIS adapter 之后增加同接口的 RDF/Fuseki adapter，并用临时 Fuseki 容器和仓库内正式 `natural-resource-one-map 2.3.0` package 完成真实 Graph Store mutation：

- adapter 重新绑定 dispatch、Provider plan/materialization、原始 RDF repair plan、target identity、期望图内容/三元组数和 package/artifact SHA-256。request 不携带 Graph Store/SPARQL endpoint、package 路径、凭据、SPARQL 或 RDF payload；
- 执行前从服务端 RDF registry 重新解析 target 并复算 payload fingerprint，request 构建后发生 package/registry 漂移时在零 HTTP 调用前拒绝；provider-local plan 使用 materialization 的 provider plan SHA-256 和幂等键；
- 首次 rebuild 通过 staging graph 和一次 SPARQL Update 同时提交 default graph 与 receipt graph，返回 `provider_mutation_committed`；相同 request 从 receipt graph 恢复，返回 `provider_idempotent_replay` 且不重复 update；receipt candidate validator 继续只给出 `validated_not_authority_admitted`；
- 临时容器用例核对正式 package 的 target fingerprint、三元组数、`single_fuseki_update_request` 原子性声明、receipt graph 回读和资源清理。RDF adapter 专项 `4 passed`；PostGIS + RDF adapter 联合回归 `56 passed, 1 skipped`；compensation 宽回归 `178 passed, 8 skipped, 1 warning`。本轮无新 migration，catalog 保持 181；

产品现在具备 PostGIS 与 RDF/Fuseki 两个真实单 Provider mutation 技术样例。剩余需求收敛为 Spark/Iceberg、对象存储、向量等其他 adapter，多 Provider run 的部分成功/unknown/reconciliation，重庆真实字段和客户业务规则部署材料，receipt 到 checkpoint/completion 的 authority 对账，备份/PITR、RPO/RTO、容量与生产 SLO，以及正式客户批准、专家审定和生产验收。状态仍为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

## 74. 2026-08-17 重庆数据范围的真实 Spark/Iceberg mutation adapter

在 PostGIS 和 RDF/Fuseki 之后，产品已接入第三个真实单 Provider mutation 样例，目标仍固定为重庆客户数据范围和 `natural-resource-one-map 2.3.0`：

- `cross_store_projection_compensation_lakehouse_adapter.py` 将 dispatch intent、Provider plan/materialization、原始 Lakehouse repair plan、注册的 Iceberg target 和客户 bundle 摘要重新绑定；provider-local execution plan 使用 materialization 的 `provider_plan_sha256` 与幂等键，拒绝自由 SQL、endpoint、warehouse、凭证、artifact 路径、Docker 参数和实际 records；
- request 构建及执行前都重新校验服务端 target registry，并复算包含 bundle、artifact、ontology、Iceberg 路由和期望结果的 payload fingerprint。任何 target/package/engine drift 在第一次 Spark 调用前拒绝；
- 临时 MinIO + Spark/Iceberg 容器中真实写入 445 条 GeoJSON 要素、439 个 distinct parcel，回执带 `spark_iceberg` 和 `single_iceberg_commit_with_snapshot_receipt`；同一 request replay 只回读已有 snapshot receipt，不产生第二次 replace；原生 receipt 仍只能进入 `validated_not_authority_admitted`，adapter 不写 checkpoint 或 completion authority；
- 专项 `4 passed`（包括真实容器），无新 migration，catalog 仍为 181；本轮只证明临时隔离环境的技术基线，不证明客户生产 Lakehouse、跨存储事务、容量或 SLO。

产品现已具备 PostGIS、RDF/Fuseki、Spark/Iceberg 三类单 Provider mutation 技术样例。剩余需求是对象存储、向量 adapter，多 Provider run 的部分成功/unknown/reconciliation、receipt 到 checkpoint/completion 的权威对账、重庆真实字段和客户规则部署材料、真实故障/备份/PITR/RPO/RTO/容量/SLO，以及正式客户批准、专家审定和生产验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

## 75. 2026-08-17 重庆客户 bundle 的真实版本化对象存储 mutation adapter

产品已接入第四个真实单 Provider mutation 样例，仍固定使用重庆客户 bundle 与 `natural-resource-one-map 2.3.0`：

- `cross_store_projection_compensation_object_adapter.py` 重新绑定 dispatch、Provider plan/materialization、原始 object-store plan、注册 target、artifact/ontology 摘要和期望对象状态，provider-local plan 使用 materialization 的 Provider plan SHA-256 与幂等键；
- mutation request 不暴露 endpoint、bucket/key 独立字段、artifact 路径、凭证或对象 payload。执行前必须从服务端 registry 重新解析 target 并复算 payload fingerprint，target/endpoint/artifact/engine drift 在零 S3 调用前拒绝；
- 临时版本化 MinIO 中真实写入 1,950,576 字节重庆 GeoJSON，payload 与 plan receipt metadata 由一次 `PutObject` 形成一个不可变版本，回执 atomicity 为 `target_payload_and_plan_metadata_single_put_object`；重建 executor 后同一 request 从 metadata 恢复为 replay，目标 key 没有第二个版本；
- delete 保持 `versioned_intent_then_delete_marker_chain` 两步恢复合同，不宣称两步原子。adapter receipt 仍只是 `validated_not_authority_admitted`，不会写 checkpoint/completion。专项 `4 passed`（含真实 MinIO），无新 migration，catalog 仍为 181。

产品现已具备 PostGIS、RDF/Fuseki、Spark/Iceberg、版本化对象存储四类单 Provider mutation 技术样例。单 Provider 接线主要还缺向量/pgvector adapter；其后仍需多 Provider 部分成功/unknown/reconciliation、receipt authority 对账、重庆客户规则部署材料、真实故障和备份恢复、容量/SLO，以及正式客户批准、专家审定和生产验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

## 76. 2026-08-17 pgvector mutation adapter 合同与真实数据库边界

产品已新增第五类 Provider 的补偿 adapter 代码，但真实 PostgreSQL/pgvector 验收仍由环境缺口明确阻断：

- `cross_store_projection_compensation_vector_adapter.py` 将 dispatch、Provider plan/materialization、原始 vector plan、allowlisted target、embedding dimension 和 rows fingerprint 重新绑定。rows 是既有 vector executor 所需的受密封 payload SHA-256 绑定的内部结构化输入，并非自由 SQL 或外部写接口；
- request 禁止 SQL、database URL、endpoint、凭证、密码和自由 registry 覆盖。执行前重新解析服务端 target 并按当前 dimension 复算 rows payload，payload/source plan/target drift 在第一次 Provider 调用前拒绝；
- 成功执行时复用既有 pgvector “目标 mutation + provider receipt 同 PostgreSQL transaction”合同，结果不写 checkpoint/completion；receipt 只能成为 `validated_not_authority_admitted`。本地 adapter + vector executor 回归 `16 passed, 1 skipped`；
- 跳过的 1 项是新增真实临时 PostgreSQL/pgvector mutation/replay/receipt recovery 用例，原因是本机未配置 `DATABASE_URL`。因此不能把本节写成真实 pgvector Provider 已验收，也不应把两条重庆语义向量技术 fixture 表述为客户生产 embedding 交付；无新 migration，catalog 仍为 181。

产品状态从“pgvector 没有 compensation adapter”推进到“adapter、sealed rows、target revalidation 和 receipt 验证已实现”，但真实数据库 transaction evidence 仍待环境接线。后续主线是补齐该用例的运行环境，并编排五类 Provider 的部分成功、unknown、reconciliation 和 authority 对账；重庆客户字段/规则部署材料、真实故障/备份恢复、容量/SLO、客户批准、专家审定和生产验收也仍未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 77. 2026-08-17 pgvector compensation adapter 真实数据库验收

第 76 节的环境缺口已经关闭。复用本机隔离 PostgreSQL 16 + pgvector 容器后，测试为每次运行创建并删除随机临时数据库，执行既有 092/094/169/176 migration，不触碰客户生产库：

- 重庆技术 fixture 的 vector rows 与 plan-bound provider receipt 在同一 PostgreSQL transaction 内提交；receipt 绑定 Provider plan、幂等键、transaction ID、目标内容指纹和 row count；
- 新 executor 实例从持久 receipt 恢复相同 sealed request，返回 `provider_idempotent_replay`，receipt 表仍只有一条；candidate validation 仍是 `validated_not_authority_admitted`，adapter 不写 checkpoint/completion authority；
- 真实专项 `1 passed`；启用数据库的 vector adapter + executor 回归为 `17 passed`。无数据库的 adapter + executor + rule-contract 回归为 `30 passed, 1 skipped`；
- 修复了测试签名信任锚的固定一天有效窗口，避免测试随墙上时钟跨日失效；专门的过期锚负向测试保持不变。该修复不改变生产 trust anchor 或客户审批语义；
- 无新 migration，catalog 保持 181；代码仍固定 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

至此，PostGIS、pgvector、RDF/Fuseki、版本化对象存储和 Spark/Iceberg 五类单 Provider compensation adapter 均已有隔离真实 mutation 与原生 receipt/replay 技术证据。剩余主线不再是补单 Provider adapter，而是五类 Provider 在同一 federated run 中的真实部分成功、unknown、reconciliation、receipt set 到 checkpoint/completion authority 全链对账，以及重庆客户字段/规则部署材料、多存储故障、备份/PITR、RPO/RTO、容量/SLO、完整执行面安全和正式客户验收。这里仍不宣称跨存储分布式事务、专家审定、客户批准、法定审批或生产验收。

## 78. 2026-08-17 五类 Provider 联邦 mutation run 分流合同

为把五类 Provider adapter 的 native result 接入同一受控 run，本轮新增 `cross_store_projection_compensation_federated_run.py`：

- runner 只接受已 sealed 的 plan/materialization binding，逐位置绑定 source plan、Provider plan、materialization、target、receipt schema 和幂等键；不接受 SQL、endpoint、凭证、实际数据或自由目标覆盖；
- runner 严格按位置顺序调用 Provider callback。`provider_mutation_committed` 和 `provider_idempotent_replay` 才能继续；已知失败停止并形成 `partial_success_pending_reconciliation`，后续位置明确标记为未尝试；
- unknown 以及未分类异常都进入 `unknown_pending_reconciliation`，不继续调用后续 Provider；全量成功/合法 replay 才进入 `completed_pending_authority`，下一动作仅为 `admit_receipt_set`；
- aggregate result 只记录身份、状态、receipt SHA-256、错误码和分流状态，固定不写 authority、checkpoint 或 completion，也不宣称跨存储分布式事务；
- 专项 `6 passed`；联邦 compensation 相关回归 `183 passed, 12 skipped, 1 warning`；无新 migration，catalog 仍为 181。

这关闭了“各 Provider 已有结果模型但没有统一的部分成功/unknown/reconciliation 分流合同”这一技术缺口，但尚未完成五个真实 adapter 在同一次 federated run 中的端到端接线和故障注入。后续仍需完成 receipt-set 到 checkpoint/completion authority 对账、重庆客户规则部署、多存储恢复演练、备份/PITR、RPO/RTO、容量/SLO、全执行面安全以及正式客户验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 79. 2026-08-17 Provider-native result 归一化

新增 `build_federated_compensation_provider_outcome_from_native_result()`，把五类 Provider 的 native result 接入 78 节 runner：

- 归一化前重新验证 native Pydantic contract、tenant/run/position、materialization binding、Provider plan 和幂等键；禁止调用方直接传自由字典；
- `provider_mutation_committed`、`provider_delete_committed`、`provider_checkpoint_recorded` 统一映射为 committed，`provider_idempotent_replay` 映射为 replayed，未列入白名单的状态拒绝；
- receipt SHA-256 只能从结构化 Provider receipt 读取，并须匹配 Provider plan 和幂等键；任何 checkpoint/completion authority 已写入标记都会 fail closed；
- 使用真实 vector adapter native result 验证 committed 归一化及篡改 flag 拒绝，联邦专项 `7 passed`；总回归 `262 passed, 15 skipped, 1 warning`；无新 migration，catalog 保持 181。

这关闭了“Provider-specific result 由调用方自由拼接”的技术缺口，但还没有完成五类真实 adapter 的 callback/target registry 部署接线、同一 run 端到端执行、故障注入和 receipt-set 到 checkpoint/completion authority 的真实对账。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 80. 2026-08-17 五引擎 Provider callback 注册表

在第 79 节的 native result 归一化之后，产品新增五引擎受控回调注册表：

- `FederatedCompensationProviderInvokerRegistry` 必须同时登记 PostGIS、pgvector、RDF/Fuseki、版本化对象存储和 Spark/Iceberg 五个 `ProjectionEngine`；未知、缺失、重复或非 callable 配置在执行前拒绝，注册项保存在只读映射中；
- `execute_federated_compensation_registered_run()` 仅按 sealed `target_engine` 路由到对应 native callback，并在 callback 返回后复用统一的 Pydantic/identity/receipt/authority-flag 校验；调用方不能以自由 callback、自由 engine 或普通字典伪造联邦 outcome；
- 已知失败与 unknown 仍立即停止，后续引擎不会调用；原生 result 的 sealed identity 或注册配置违规直接 fail closed，而不是被误记成可继续的 Provider unknown；
- 联邦专项增至 `13 passed`，覆盖完整五引擎 routing、缺失/未知配置、known failure、unknown、合法 replay 和 native identity drift；补偿宽回归为 `268 passed, 15 skipped, 1 warning`，其中跳过项仅为未配置 PostgreSQL 或外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。无新 migration，catalog 仍为 181。

这使五类单 Provider adapter 有了统一、不可自由替换的联邦调用选择边界，但尚未完成五个真实 adapter request/executor 在同一重庆运行中的部署接线，也没有进行多存储 partial success、网络分区、进程硬杀、提交后超时 unknown 和重启/reconciliation 演练。完整 receipt set 仍未被该模块提交到 checkpoint/completion authority；产品继续不宣称跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 81. 2026-08-17 run-to-receipt-set 指纹桥接

产品已把完成的联邦 run 与既有 Provider receipt-set 候选受控关联：

- `build_federated_compensation_provider_receipt_validation_set_from_run()` 只接受完整、sealed、`completed_pending_authority` 的 run；partial/failed/unknown 结果在生成 receipt-set 前被拒绝；
- 函数从 plan/materialization 重新建立逐位置 binding，并把 run outcome 的 binding SHA、source/Provider plan、idempotency、成功或 replay 状态、receipt SHA-256 与已验证 receipt 的 materialization/target/projection/action 身份逐项比对；任一回执 SHA-256 漂移均 fail closed；
- 成功产物仍是既有的只读 `complete_provider_receipts_pending_authority_admission`，不保留实际 receipt document，不调用 Provider，不写 receipt-set/checkpoint/completion authority；
- run 与 receipt-set 联合专项为 `22 passed`，补偿宽回归为 `271 passed, 15 skipped, 1 warning`；跳过项仍是未配置 PostgreSQL 或外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。无新 migration，catalog 保持 181。

这关闭了“完成 run 与 receipt-set 可被错误拼接”的合同缺口，但未完成五个真实 adapter 在同一重庆 run 的部署接线和多存储故障演练，也没有把 receipt-set candidate 实际提交给 checkpoint/completion authority。备份/PITR、RPO/RTO、容量/SLO、全执行面安全及正式客户/专家审批继续是剩余需求。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表生产验收、法定审批或跨存储分布式事务。

## 82. 2026-08-17 注册联邦 run 的同次回执验证

产品新增 `execute_registered_federated_compensation_run_with_receipt_set()`，把一个受控注册表 run 与 receipt-set 候选生成收敛为一次调用：

- callback 仍只按 sealed binding/engine 路由；native Pydantic result 仅在本次调用内保留，用于产生 outcome、验证原生 receipt 并构造 receipt-set，避免为聚合回执再次执行 Provider；
- 完整成功时输出 `completed_receipt_set_pending_authority`，其中只有 sealed run 和已验证 receipt set；不保留 receipt document、SQL、endpoint、凭证或 payload，所有 authority/checkpoint/completion 写入标记仍为 false；
- partial、known failure、unknown 或未分类异常返回 `reconciliation_or_operator_required`，不生成 receipt-set candidate；native receipt 指纹篡改在候选生成前 fail closed；
- 联合专项 `25 passed`，补偿宽回归 `274 passed, 15 skipped, 1 warning`；跳过项仍是未配置 PostgreSQL 或外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。无新 migration，catalog 保持 181。

这消除了“同次 run 后需手工拼接 native receipt/receipt-set，且可能重复 Provider 调用”的合同缺口。当前仍未完成五类真实外部 Provider 在同一重庆运行中的部署接线和故障恢复演练，也没有进行 checkpoint/completion authority 的真实受控 admission。产品继续不宣称跨存储分布式事务、客户批准、专家审定、生产验收或法定审批；状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 83. 2026-08-17 五引擎受密封 native invoker 部署装配

产品已把五类 Provider 的部署侧 callback 装配从调用方手工代码收口到 `cross_store_projection_compensation_provider_native_invokers.py`：

- PostGIS、pgvector、RDF/Fuseki、对象存储和 Spark/Iceberg 各有一个 typed factory，只接收自身 sealed mutation request 与相应 governed executor；错误 executor 在创建回调前拒绝，模块不接收 SQL、endpoint、凭据、自由目标或任何 authority writer；
- callback 每次执行都会重新验证 request 和 sealed run binding，要求 tenant、run、position、projection、engine/target、source plan、plan/materialization binding、Provider plan 和 idempotency key 全部一致。篡改后重新计算过 binding 指纹的跨 run 请求也会在任何 adapter/executor 调用前 fail closed；
- 单一 builder 必须组成完整五引擎 `FederatedCompensationProviderInvokerRegistry`，仍由 registry 依 sealed `target_engine` 路由；通过后才进入既有 adapter 的 registry/payload/receipt/replay 验证，且 checkpoint/completion authority 相关标志始终为 false；
- 新专项 `3 passed`，包括真实内存 pgvector callback、零额外执行的 binding drift 拒绝、ungoverned executor 拒绝和五类 callback 完整装配；补偿宽回归为 `277 passed, 15 skipped, 1 warning`。跳过项仍限于无 `DATABASE_URL` 或固定外部镜像不可用，warning 为既有 OpenTelemetry 弃用提示；无新 migration，catalog 保持 181。

产品现在具备可复用的五引擎部署接线合同，但这不等同于五类真实外部 Provider 已在同一重庆 run 执行。剩余重点是用同一重庆 target registry/request bundle 做真实 run，覆盖 partial success、网络分区、进程硬杀、commit-after-timeout unknown、重启/reconciliation，并将完整 receipt-set 在部署 PostgreSQL tenant RLS 下受控送入 checkpoint/completion authority。重庆字段/规则版本材料、备份/PITR、RPO/RTO、容量/SLO、全执行面安全和正式客户/专家审批也仍未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。

## 84. 2026-08-17 重庆客户数据部署 catalog 与 run 绑定

产品已把重庆客户 bundle、字段映射和本体基线接入联邦补偿部署准备链：

- `build_chongqing_federated_compensation_source_catalog()` 使用已校验的客户 `natural-resource-ontology-customer-demo-v1` bundle，固定 `natural-resource-one-map 2.3.0` 包与 SHA-256；输出 5 个交付工件摘要、10 条源记录角色/行数/摘要和 6 条 field mapping，并分别计算 item、mapping-set 与 catalog 指纹；不输出客户源相对路径、几何、属性值、SQL、endpoint 或凭据；
- `build_chongqing_federated_compensation_deployment_binding()` 将该 catalog 与 sealed dispatch、Provider plan set、materialization set 逐位置绑定，复核 tenant/run、snapshot、规则合同、source plan、target、Provider plan、idempotency 及 materialization reference。结果只是 `customer_catalog_bound_pending_provider_execution`，Provider、checkpoint 和 completion 标志全部为 false；
- 新专项 `3 passed`，覆盖真实重庆 bundle 清单、字段映射 drift 拒绝与 sealed run 绑定；补偿宽回归为 `280 passed, 15 skipped, 1 warning`。跳过项仍限于无 `DATABASE_URL` 或固定外部镜像不可用，warning 为既有 OpenTelemetry 弃用提示；无新 migration，catalog 保持 181。

这完成了“客户数据与字段/本体版本可随 run 复核”的部署准备合同，不代表复制客户生产数据、更不代表五个 Provider 已联动执行。下一项仍是同一重庆 target registry/request bundle 的真实五存储 run 与 fault injection/restart reconciliation，随后才是 receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority 的真实准入。备份/PITR、RPO/RTO、容量/SLO、安全和正式客户/专家审批保持未完成；状态继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 85. 2026-08-17 重庆部署 preflight 接入 registered run

产品已将第 84 节的重庆 catalog 从准备产物接入实际 registered run 入口：

- `execute_chongqing_federated_compensation_deployment_with_receipt_set()` 在 Provider callback 前重新校验 catalog、deployment binding、dispatch、Provider plan、materialization，并重建 binding；catalog/mapping 摘要、source snapshot、规则合同及逐位置 source/target/Provider plan/idempotency/materialization 任一漂移都会 fail closed；
- preflight 通过后才调用既有同次 registered run + native receipt + receipt-set 工作流；成功路径不二次调用 Provider，输出只保留密封的 catalog/deployment 摘要和既有 registered execution 结果，不保留客户原始数据、receipt document、SQL、endpoint 或凭据；authority/checkpoint/completion 标志固定为 false；
- 新专项 `2 passed`，覆盖 preflight 后的单次 run 与 deployment binding drift 零 callback 拒绝；补偿宽回归为 `282 passed, 15 skipped, 1 warning`。专项使用三位置重庆技术 fixture，且五引擎 registry 仍被强制注册；这不是五个真实外部存储的同一 run 证据。无新 migration，catalog 保持 181。

产品现在能把客户数据/字段映射/本体/规则版本的部署证据作为 registered run 的强制前置条件，但真实五存储 target registry/request bundle、故障注入和重启 reconciliation 仍待部署环境。receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority 的真实准入、备份/PITR、RPO/RTO、容量/SLO、安全及客户/专家审批也未完成；状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 86. 2026-08-17 重庆客户源数据逐位置血缘 preflight

产品已在 deployment catalog 之上增加逐位置客户源选择的可验证合同：

- `cross_store_projection_compensation_chongqing_source_lineage.py` 的 builder 要求每一个 sealed deployment position 显式选择至少一个重庆 catalog `source_role`。它逐项密封 deployment item、source plan/content、catalog/field-mapping set，以及所选 source role 的 content/record SHA-256；position 必须完整、唯一、有序，role 必须唯一、有序且属于 catalog；输出不含客户路径、原始记录、几何、属性、SQL、endpoint、凭据或 payload；
- `cross_store_projection_compensation_chongqing_source_lineage_execution.py` 在任何 Provider callback 前重新验证 dispatch/plan/materialization/catalog/deployment/lineage，并由密封 role selection 重建 lineage set。catalog、deployment、source plan/content、position、role 或摘要漂移均在零 callback 前 fail closed；通过后才委托既有重庆 deployment registered run，成功路径不重复调用 Provider，authority/checkpoint/completion 标志仍为 false；
- 新专项 `7 passed`，覆盖三位置选择、缺失 position、未知或重复 role、lineage 指纹漂移、成功单次 callback 和漂移零 callback；补偿宽回归为 `289 passed, 15 skipped, 1 warning`。跳过项仍限于未配置 `DATABASE_URL` 或固定外部镜像不可用，warning 是既有 OpenTelemetry 弃用提示；Ruff 通过，无新 migration，catalog 仍为 181。

这让“本次 run 选择了哪些客户 catalog 源记录”可以逐位置复核，但不把 role selection 的业务正确性伪装成自动推理或客户批准。当前选择只是由部署规则显式提交的技术输入；仍需基于真实重庆 target registry/request bundle 执行五个外部 Provider，并完成 partial success、网络分区、硬杀、commit-after-timeout unknown、重启 reconciliation、receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority、备份/PITR、RPO/RTO、容量/SLO、安全及正式客户/专家审批。状态继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。

## 87. 2026-08-17 重庆源血缘停止态 reconciliation case

产品已将 source-lineage 关联到部分成功、明确失败和 unknown 的联邦 run 停止状态：

- `cross_store_projection_compensation_chongqing_source_lineage_reconciliation.py` 只接受 sealed 且 `reconciliation_or_operator_required` 的 source-lineage execution，复核 tenant/run、deployment、lineage、catalog/field-mapping、run result 和逐位置 outcome；completed run 或已有 receipt-set 的结果不能被误标为对账案例；
- case 对所有 position 输出 deployment/lineage/plan/target 与客户 source role 摘要，将结果受限为 committed、replayed、unknown、failed、not-attempted，并固定后续动作为保留已密封回执证据、先观察 outcome、先检查失败或在前序对账前不得继续调用。它不保存原始 receipt、commit reference、错误文本、客户原始数据、SQL、endpoint 或凭据；
- 此能力仅准备 `source_lineage_reconciliation_or_operator_required` 的只读操作证据，不重试 Provider、不读写 target、不写 checkpoint 或 completion authority；专项 `3 passed` 覆盖 partial success、commit-after-timeout unknown 和 completed run 拒绝，补偿宽回归为 `292 passed, 15 skipped, 1 warning`，Ruff 与 Python 编译通过。跳过项仍限于未配置 `DATABASE_URL` 或固定外部镜像不可用；无新 migration，catalog 仍为 181。

这补齐了停止态 run 的客户源血缘交接，不等同于真实 multi-store reconciliation 或故障演练。仍需同一重庆 target registry/request bundle 的五 Provider 外部运行、网络分区/硬杀/重启恢复、receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority、备份/PITR、RPO/RTO、容量/SLO、安全以及正式客户/专家审批；状态继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。

## 88. 2026-08-17 重庆客户场景 source-selection profile

产品已将客户 Demo 的两个场景编译为不会跨场景混用的 source-role 技术 profile：

- `build_chongqing_federated_compensation_source_selection_profile()` 读取已校验重庆 bundle 的场景 ID、label/layers 并仅固定其证据 SHA-256；`heping_review` profile 限定和平村规划、建设用地管制、重点项目和四类约束源，`banzhu_adjustment` profile 限定斑竹村规划与土地利用结构调整源。profile 不暴露场景正文、路径、原始记录、空间数据、SQL、endpoint、凭据或 payload，状态固定为 `customer_scenario_technical_baseline_unreviewed`；
- `build_chongqing_federated_compensation_profiled_source_lineage_binding()` 强制 source-lineage 所有 position 的 role 并集与选定 profile 完全相等。遗漏 role、混入另一场景 role 或 catalog/deployment/lineage/profile 漂移均 fail closed；
- profile-bound execution 在任何 Provider callback 前重新构建 profile 和 binding，之后才调用既有 source-lineage/deployment preflight。成功路径不重复 Provider，authority/checkpoint/completion 均继续为 false；新专项 `5 passed` 覆盖 profile 完整覆盖、跨场景拒绝、摘要漂移、成功单次 run 和 binding drift 零 callback。补偿宽回归为 `297 passed, 15 skipped, 1 warning`，跳过项仍限于未配置 `DATABASE_URL` 或固定外部镜像不可用；Ruff 与 Python 编译通过，无新 migration，catalog 保持 181。

这使重庆客户场景的源选择不再只是自由 role 列表，但它只是客户 Demo 的可验证技术配置，不自动替代客户规则、专家审定或生产部署确认。真实五 Provider target registry/request bundle、故障/重启演练、receipt-set 的 PostgreSQL tenant RLS authority 准入、备份/PITR、RPO/RTO、容量/SLO、安全和正式客户/专家审批仍未完成；状态继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。

## 89. 2026-08-17 同一重庆请求束的五 Provider 真实联动

产品已把五类真实 Provider 从“各自可执行、统一注册”推进到同一重庆 sealed request bundle 下的单次联动执行：

- 新增 `cross_store_projection_compensation_chongqing_five_provider_execution.py`。请求束必须在同一 tenant/run、dispatch intent、Provider plan set、materialization set 和 deployment binding 中恰好绑定 PostGIS、pgvector、RDF/Fuseki、版本化对象存储、Spark/Iceberg 五个连续位置；输出仅保留逻辑 target 和请求/计划/物化摘要，不保存 endpoint、凭据、SQL、rows、artifact path、客户原始记录或 native receipt；
- 执行入口在任何 callback 前重建请求束并复核重庆 customer catalog、自然资源本体 `natural-resource-one-map 2.3.0`、场景 profile、逐位置 source lineage、部署 binding 及完整 native invoker registry。请求、位置、引擎或摘要漂移会在零 Provider callback 前 fail closed；
- 本机隔离实测使用两个临时 PostgreSQL 数据库、Fuseki、两个 MinIO 环境和 Spark/Iceberg worker。五个真实 Provider 各执行一次并形成 5/5 validated receipt-set，状态为 `COMPLETED_RECEIPT_SET_PENDING_AUTHORITY`；专项 `1 passed`，临时数据库、bucket、容器、卷和网络均经断言清理。五类单 Provider 真实演练为 `5 passed`，五位置单元链与 native invoker 回归为 `8 passed, 1 deselected`；
- 修复了 native invoker 无条件读取 `request.target` 的兼容缺陷：RDF、对象存储、Lakehouse 的 hash-only request 现在通过 `target_ref` 校验，PostGIS/pgvector 继续校验 typed target；三类 hash-only request 均增加回归；
- 随后修复三个 PostgreSQL 宽回归问题：补齐 102→103 等 migration 依赖顺序；rule authority 的 Python 写入口和 180 lifecycle guard migration 在数据库函数前拒绝 lifecycle regression，同状态幂等重放继续允许；gateway 直接写 rule 表继续按最小权限拒绝。三个原失败用例定向为 `3 passed`，三个完整真实临时 PostgreSQL 模块为 `13 passed`；无外部依赖的补偿链宽回归为 `211 passed, 13 skipped, 1 warning`，跳过项是数据库/外部 Provider 环境，warning 为既有 OpenTelemetry 弃用提示。

产品当前可以准确声明：**在本机隔离环境中，五个真实 Provider 使用同一重庆五位置 sealed request bundle 执行，形成 5/5 validated receipt-set，停在 authority admission 之前。** 不得把它表述为跨存储分布式事务、客户生产运行、客户批准、专家审定、法定审批或生产验收。

剩余需求集中在四组：一是网络分区、进程硬杀、commit-after-timeout unknown、重启 reconciliation；二是 receipt-set 在真实部署 PostgreSQL tenant RLS 下进入 checkpoint/completion authority；三是 source-selection profile 的版本化治理以及客户实际规则/部署确认；四是备份/PITR、RPO/RTO、容量、p95/p99、SLO、全执行面安全和正式验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 90. 2026-08-17 五 Provider checkpoint/completion authority 闭环

产品已将第 89 节的同一重庆 5/5 validated receipt-set 接入本机真实 PostgreSQL tenant-RLS authority：

- 新增 `cross_store_projection_compensation_chongqing_five_provider_authority.py`。入口只接受完整的五 Provider pre-admission execution result，并重新绑定 request bundle、Provider plan/materialization、五个原始 repair plan 与五个最终 observation；它依次构造 predecessor/candidate、admission、live-current preview、write intent 和 exact checkpoint request。任何 bundle、计划、物化、target state 或摘要漂移均在零 checkpoint 写入前拒绝；
- 五个 checkpoint 由既有 authority 按 position 顺序记录。writer 会在首个副作用前读取全部 predecessor；中途 conflict、forbidden、validation rejection 或 unknown 会返回明确的 `pending_reconciliation` record-set，后续 position 不再尝试，completion authority 不被调用。只有 5/5 checkpoint 全部记录且再次成为 live current 后，才允许既有 completion authority 单独落账；
- 整链重放新增严格的 `requested_checkpoint_replay` 识别：只有 source/target、version、repair plan/idempotency、Provider plan/receipt commit evidence 以及最终重建 checkpoint SHA-256 完全相等才接受。已存在 completion 也必须匹配五个 checkpoint SHA-256、position、target identity、current 和完成主体才复用；这解决了重复运行误判 predecessor drift，同时不放宽真实漂移拒绝；
- 本机 PostgreSQL 16 容器的随机临时库加载 092/094/169/181 migration。首次执行形成 5 条 current、5 条 history 和 1 条 completion；完整重放五条均为 `idempotent_replay`，completion 不重复，记录数保持 `5/5/1`。另一 tenant 对 checkpoint 与 completion 均不可见；临时数据库和随机角色在测试后删除；
- 新专项无数据库运行 `3 passed, 1 skipped`，真实 PostgreSQL 定向 `1 passed`；补偿链宽回归 `217 passed, 11 skipped, 1 warning`，warning 是既有 OpenTelemetry 弃用提示；Ruff、Python 编译通过，无新 migration。

产品现在可以准确声明：**同一重庆 sealed request bundle 的五个 Provider 形成 5/5 receipt-set 后，已在真实隔离 PostgreSQL 中完成 tenant-RLS checkpoint 逐条落账与 completion 单独落账，并支持不重复记录的完整重放。** 这不是一个跨 PostGIS、pgvector、Fuseki、MinIO、Iceberg 与 PostgreSQL authority 的分布式事务；部分或未知结果不会写 completion，仍需对账。

剩余重点是多存储网络分区、硬杀、commit-after-timeout unknown、重启 reconciliation 和案例关闭；在客户部署数据库/账号/网络策略下复验；profile 与客户实际规则的版本发布和回滚；备份/PITR、RPO/RTO、容量、p95/p99、SLO、监控告警、全执行面安全及正式验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批或生产验收。

## 91. 2026-08-17 checkpoint authority unknown 结果恢复

产品已为第 90 节的 checkpoint partial/unknown 状态增加显式 reconciliation，而不是要求调用方盲目重跑或手工修改数据库：

- `reconcile_chongqing_five_provider_authority()` 只接受未完成的 prior authority result，强制复用同一 execution/request bundle、Provider plan/materialization、repair plan、final observation、actor 和时间戳；已完成 run 或任一证据漂移在零新写入前拒绝；
- 恢复模块没有 Provider registry、native payload 或 executor 依赖，不能再次执行 PostGIS、pgvector、RDF/Fuseki、对象存储或 Spark/Iceberg。它只重新观察 checkpoint current、幂等提交 exact request，并在 5/5 current 后调用 completion authority；结果记录 prior uncertain position、current replay position 和最终案例状态；
- 内存和真实 PostgreSQL 均注入“position 0 已提交、成功响应随后丢失”。首次调用返回 `authority_outcome_unknown` 且 completion 不执行；恢复把 position 0 收敛为 `idempotent_replay`，补齐 position 1–4，完成后数据库保持 `5 current / 5 history / 1 completion`，没有为 position 0 追加重复 history；
- reconciliation 专项为 `2 passed, 1 skipped`，与五 Provider authority 合并为 `5 passed, 2 skipped`；真实 PostgreSQL 恢复定向 `1 passed, 2 deselected`；补偿链宽回归 `219 passed, 12 skipped, 1 warning`，Ruff 和 Python 编译通过，无新 migration。

产品现在可以准确声明：**checkpoint authority 在提交后响应丢失时先保持 unknown 且不写 completion，恢复流程以 live current 为准，把完全相同的 checkpoint 收敛为幂等 replay，并在五个 checkpoint 全部确认后关闭 completion。** 它仍不是跨存储事务，也没有重新执行 Provider。

尚未关闭的是五个外部 Provider 自身的网络分区、进程硬杀、commit-after-timeout unknown、重启与真实 reconciliation；另外仍需客户部署环境复验、profile/客户规则版本治理、备份/PITR、RPO/RTO、容量/SLO、监控安全和正式验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批或生产验收。

## 92. 2026-08-18 PostGIS Provider unknown outcome 观察、续跑与重庆 case 回接

产品已把第 91 节的 authority 层响应丢失恢复与 Provider 层 unknown outcome 区分开：本轮只新增 PostGIS Provider 的真实、受密封观察和受控续跑，不把五 Provider 的故障演练写成全部完成。

- `observe_federated_compensation_postgis_unknown_outcome()` 绑定原 PostGIS mutation request、重庆 source-lineage reconciliation case 的 unknown position、source/Provider plan、materialization binding、target registry 和幂等键；先读同事务持久 receipt，再读当前目标，输出三种明确结论：`provider_commit_confirmed_from_persisted_receipt`、`provider_not_committed_safe_to_resume`、`indeterminate_operator_required`；
- receipt 已存在且 target 一致时，输出可回接 federated run 的最小 committed outcome；receipt 缺失且 target 等于 sealed pre-mutation state 时才允许下一步；receipt 缺失但 target 改变、receipt 校验失败或目标在观察后变化时 fail closed，保留 operator-required 证据；
- `resume_federated_compensation_postgis_unknown_outcome()` 只有在一次新的 live observation 仍为 safe-to-resume 时才调用既有 PostGIS adapter；它不写 checkpoint、不写 completion、不执行跨存储事务，并能把 adapter result 归一化为原 run binding 可消费的 committed/replayed outcome；
- 本机随机临时 PostgreSQL 实测覆盖安全续跑、stale observation 冲突、receipt 缺失的目标变化、提交后响应丢失后的 receipt 确认以及 append-only receipt；专项 `3 passed`，Ruff/编译通过。客户规则 authority 的 Python 写入口和 180 migration trigger 同时增加 lifecycle regression 保护，approved 后旧 draft 重放会拒绝，同状态重放仍幂等。

准确口径是：**GIS Data Agent 已具备 PostGIS Provider 单位置 unknown-outcome 的只读 reconciliation 与条件续跑技术基线，并能回接重庆 source-lineage case。** 这不等同于 pgvector、RDF/Fuseki、对象存储、Spark/Iceberg 已完成同类 fault injection，也不等同于五 Provider 联邦恢复、客户部署验收、客户批准、专家审定、法定审批或跨存储分布式事务。

剩余需求仍包括：五个实际 Provider 的网络分区/硬杀/commit-after-timeout/restart reconciliation；同一重庆五位置 case 的部分成功与 unknown 继续执行、receipt-set/checkpoint/completion authority 对账和案例关闭；客户部署数据库/账号/网络策略复验；source-selection profile 与实际客户规则的版本发布、变更和回滚；备份/PITR、RPO/RTO、容量、p95/p99、SLO、监控告警、全执行面安全；以及正式客户/专家审批和生产验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

## 93. 2026-08-18 pgvector Provider unknown outcome 观察、续跑与重庆 case 回接

产品已在 PostGIS 之后补齐 pgvector 单位置的 Provider-level unknown-outcome 技术基线：

- 新增 `observe_federated_compensation_vector_unknown_outcome()`，绑定原 vector mutation request、重庆 source-lineage unknown case、source/Provider plan、materialization binding、target registry、向量 payload 与幂等键。pgvector 目标 mutation 和 Provider receipt 位于同一 PostgreSQL 事务，因此 receipt 存在且当前 target 一致可确认提交；receipt 缺失且 target 仍为 sealed 前态才允许续跑；其他状态一律转 `indeterminate_operator_required`；
- 新增 `resume_federated_compensation_vector_unknown_outcome()`，在实际调用 pgvector adapter 前强制执行第二次 live observation。stale safe evidence、目标漂移或新出现的 receipt 都会阻断盲目重试；成功结果可归一化为原 federated run 可消费的 committed/replayed outcome；
- 观察和续跑结果均明确 `checkpoint_authority_write_performed=false`、`compensation_completion_recorded=false`、`cross_store_transaction_performed=false`。该模块不持有自由 SQL、数据库连接串或凭据，也不绕过既有 target registry 和 Provider adapter；
- 本机隔离 PostgreSQL/pgvector 专项 `2 passed`，覆盖安全续跑、两次观察间漂移拒绝、receipt 缺失目标漂移、提交后返回值丢失恢复和 receipt 唯一性；与 PostGIS、客户规则 lifecycle guard 和五 Provider authority/reconciliation 联合为 `19 passed`；补偿宽回归 `219 passed, 17 skipped, 1 warning`，Ruff 和 Python 编译通过，无新 migration。

准确口径是：**PostGIS 与 pgvector 已分别具备单位置 unknown outcome 的只读观察、三态判定、条件续跑和重庆 case outcome 回接。** 当前演练证明的是提交后返回值丢失，不应写成真实网络分区或操作系统进程硬杀已经完成。

剩余 Provider-level 缺口已收缩为 RDF/Fuseki、版本化对象存储和 Spark/Iceberg；联邦层仍缺少同一五位置 case 的后续位置继续执行、receipt-set 重建、checkpoint/completion 对账与案例关闭。客户部署环境复验、source-selection profile/客户规则的版本发布与回滚、备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全及正式客户/专家审批和生产验收仍未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

## 94. 2026-08-18 RDF/Fuseki Provider unknown outcome 观察、续跑与重庆 case 回接

产品已将 Provider-neutral reconciliation 核心接入 RDF/Fuseki，同时保留 RDF 与其他 Provider 不同的原子性边界：

- 新增 `cross_store_projection_compensation_provider_reconciliation.py` 作为只负责三态证据判定的通用核心，RDF typed wrapper 位于 `cross_store_projection_compensation_rdf_reconciliation.py`。wrapper 绑定 RDF mutation request、重庆 source-lineage unknown case、source/Provider plan、materialization binding、target registry、ontology package 摘要、target ref 和幂等键；
- Fuseki executor 的目标图和 receipt graph 由一次受治理的 SPARQL update 请求提交。receipt 存在且当前图一致时确认提交；receipt 缺失且图仍为 sealed 前态时才允许续跑；receipt 校验失败、目标图改变或观察间出现变化时转 `indeterminate_operator_required` 或拒绝续跑；
- `resume_federated_compensation_rdf_unknown_outcome()` 在调用 RDF adapter 前强制执行 fresh live observation，结果可以归一化回原 federated run 的 committed/replayed outcome，并固定 `checkpoint_authority_write_performed=false`、`compensation_completion_recorded=false`、`cross_store_transaction_performed=false`；
- RDF/Fuseki 专项 `2 passed`，覆盖安全续跑、目标漂移冲突、receipt 缺失目标变化、单请求提交后返回值丢失恢复和 unknown case 绑定拒绝；无新 migration，Ruff 与 Python 编译通过。

准确口径是：**PostGIS、pgvector 与 RDF/Fuseki 已分别具备单位置 unknown outcome 的只读观察、三态判定、条件续跑和重庆 case outcome 回接。** RDF 的“同请求原子性”不应表述为 PostgreSQL 事务或跨存储分布式事务；当前演练仍主要证明提交后返回值丢失，不等于网络分区或进程硬杀已完成。

剩余 Provider-level 缺口收缩为版本化对象存储和 Spark/Iceberg；联邦层仍缺同一五位置 case 的后续位置执行、receipt-set 重建、checkpoint/completion 对账与案例关闭。客户部署环境复验、source-selection profile/客户规则版本发布与回滚、备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全及正式客户/专家审批和生产验收仍未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

## 95. 2026-08-18 五类 Provider 单位置 unknown-outcome reconciliation 收口

产品已将五类 Provider 的单位置未知结果恢复合同全部补齐：

- PostGIS 和 pgvector 使用各自的 PostgreSQL receipt/target 同事务 executor；RDF/Fuseki 使用一次受治理 SPARQL update 请求；版本化对象存储使用 object metadata/version 或 delete intent/delete-marker；Spark/Iceberg 使用 snapshot-bound receipt/tombstone。任何 Provider 都不被通用核心强行套用另一个存储的事务假设；
- `cross_store_projection_compensation_provider_reconciliation.py` 只负责 receipt 存在/缺失、sealed 前态、目标漂移、operator-required、fresh observation 和 outcome 指纹等共性判定；typed wrapper 保留各 Provider 的 request、executor、receipt 和 adapter 验证边界；
- 五类 wrapper 都能把确认或续跑结果回接原重庆 source-lineage case 的最小 committed/replayed outcome，且明确不写 checkpoint、不写 completion、不做跨存储分布式事务。新增对象存储专项 `2 passed`、Lakehouse 专项 `2 passed`；加上 PostGIS `3`、pgvector `2`、RDF `2` 的 Provider reconciliation 专项，单位置专项合计 `11 passed`；
- 真实外部证据仍分层：PostGIS/pgvector 在本机隔离 PostgreSQL 做了提交后返回值丢失、目标漂移和 receipt 恢复；RDF/Fuseki、对象存储、Spark/Iceberg 当前是受控 transport/memory，尚未在客户服务实例中完成网络分区、进程硬杀和重启演练。

准确口径是：**五类 Provider 的单位置 unknown outcome 技术基线已具备。** 本轮已继续完成同一重庆五位置 case 的恢复编排，详见第 96 节。客户部署环境复验、source-selection profile/实际规则的版本发布/变更/回滚、备份/PITR、RPO/RTO、容量与 SLO、监控告警、全执行面安全、客户正式确认、专家审定、法定审批和生产验收仍未完成；状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准或跨存储事务。

## 96. 2026-08-18 同一重庆五位置 unknown-outcome 联邦恢复闭环

产品已把第 95 节的五类单位置 reconciliation 接入同一重庆五位置 run 的恢复编排：

- 新增 `cross_store_projection_compensation_chongqing_federated_recovery.py`，显式绑定 stopped execution、重庆 sealed request bundle、source-lineage case、五个 typed request/executor/adapter、safe observation 和后续 native invoker registry；
- 已提交前缀只做 persisted receipt recovery 和再次 receipt validation，绝不重复调用；未知位置只有在 fresh observation 仍为 safe-to-resume 时才调用对应 Provider resume 一次，确认后才允许继续位置 2-4 等后续 suffix；观察到目标漂移、receipt 不一致或后续 Provider unknown/failed 时立即停在 reconciliation，不创建完整 receipt-set；
- 完成路径重新生成完整 federated run、5/5 validated receipt-set 和 authority-admissible 的五 Provider execution result，可复用既有 checkpoint/completion authority；输出只保留指纹和 typed validation，不暴露 receipt document、SQL、endpoint、凭据或 payload，也不声称跨存储事务；
- 新专项 `2 passed`；与既有联邦/source-lineage/provider 定向回归合计 `25 passed, 1 skipped`，补偿链宽回归为 `230 passed, 14 skipped, 1 warning`，warning 仍是既有 OpenTelemetry 弃用提示。代码和测试均保持 authority admission 前的 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

因此，**联邦层“unknown -> 观察 -> 安全续跑 -> 后续位置 -> receipt-set -> authority 对账”技术闭环已具备**。尚未完成的是在客户真实 RDF/Fuseki、MinIO、Spark/Iceberg 服务上做网络分区、进程硬杀、提交后超时和重启实测；客户部署数据库/账号/网络策略复验；source-selection profile 与实际规则的版本发布、变更和回滚；备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全，以及客户正式确认、专家审定、法定审批和生产验收。不能将该闭环表述为分布式事务或客户生产验收。

## 97. 2026-08-18 联邦恢复异常边界与 authority 兼容复核

在第 96 节的五位置恢复编排上继续补齐异常边界，范围仍固定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- fresh observation 冲突时返回 `unknown_operator_required`，证据明确 `provider_invocation_performed=false`，不调用未知位置 Provider，也不触碰后续 suffix；
- resume wrapper 抛出异常，或结果/receipt 无法验证时，不再向调用方抛出执行异常掩盖 stopped case，而是封存新的 UNKNOWN run result；`provider_invocation_performed=null` 表示调用或提交状态不明，避免错误宣称 Provider 已执行或未执行；
- 只有 receipt 与状态全部可验证的成功路径才生成 5/5 receipt-set；异常路径保持 reconciliation open，既不写 checkpoint/completion authority，也不增加新的 authority 写入路径；
- 专项恢复测试从 2 条扩为 5 条，新增异常、观察冲突和既有 authority 兼容回归；五类 compensation 相关文件全量为 `233 passed, 14 skipped, 1 warning`，Ruff、Python 编译和 scoped `diff --check` 通过。

产品当前可以准确声明：**同一重庆五位置 run 的恢复编排已经覆盖成功续跑、观察冲突和提交状态不明三类封存路径，并能把完整成功结果交给既有 authority 入口。** 这仍不是客户外部服务的网络分区、进程硬杀、真实提交后超时或重启验收，也不是跨存储分布式事务。尚未完成的是客户部署环境复验、三类外部 Provider 的 fault injection、source-selection profile/客户规则版本治理、备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全以及客户正式确认、专家审定、法定审批和生产验收。

## 98. 2026-08-18 重庆客户数据聚合质量基线

产品已把“重庆客户数据可以使用”从口头前提收敛为可重建、可失败关闭的聚合质量合同，仍不把技术检查写成客户批准或专家审定：

- `build_chongqing_customer_data_quality_report()` 复用 sealed entity/link baseline，强制绑定客户 manifest、和平村变化地块与约束 GeoJSON 哈希，以及 `natural-resource-one-map:2.3.0:587915868b1221af`；输出仅含聚合计数、代码域、bounds 和哈希，不输出逐条地块 ID、客户原始记录或几何；
- 实测为 445 条地块源记录、439 个地块身份、16 个唯一约束身份、455 个实体和 486 个 Link。地块 `parcel_id` 的 2 个重复组、6 条附加记录按 `allowed_identity_aggregation` 处理；约束 `(layer, BSM)` 强制唯一；
- 两份数据共 461 个面要素，空、非法和非面几何均为 0，必需字段均非空；GeoJSON 无旧式 `crs` member，并按 RFC 7946 使用 WGS84。492 个精确相交观测与 472 个客户证据观测已对账，1 个 precision sliver 被记录为 warning 并排除；
- 模型在反序列化时复核 artifact profile、gate、issue 和最终 report 哈希。哈希漂移、缺字段、错误 CRS、非法几何、唯一键冲突或汇总篡改均不能生成通过报告；专项 `7 passed`，Ruff、编译、JSON 解析和运行时逐字段重建通过；实际封存 JSON 的 `report_sha256` 为 `298957d8d820304d583ba224b3c9e07f12b1b26bcafba1fbd978cfb07d11211b`。

产品现在可以准确声明：**当前固定的重庆客户 bundle 已具备可追溯的数据质量技术基线，可继续支撑既有实体/Link、规则预检和五 Provider 补偿技术链。** 它不证明任意客户数据包自动适配，也不代表客户业务口径、专家判断或生产部署已经确认。状态固定为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，并明确 `authority_write_performed=false`、`customer_approval_present=false`。

剩余需求集中在真实外部 Provider fault injection 与重启恢复、客户 PostgreSQL/RLS/账号/网络策略复验、source-selection profile 和客户规则版本治理、客户规则驱动的动态补偿、任意客户包适配与复杂冲突裁决、全执行面安全、自动语义规划和跨通道融合，以及备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警和正式客户/专家审批与生产验收；仍不得宣称跨存储分布式事务。

## 99. 2026-08-18 质量证据与部署证据绑定

产品继续收紧重庆部署前置合同：source catalog 不再只绑定客户 bundle、字段映射和本体，而是强制绑定 `chongqing_customer_data_quality_report_2026-08-18.json` 的 `report_sha256`；deployment binding 继续传递并校验同一指纹。

这使“质量报告和部署材料来自不同快照”成为可检测错误：客户 artifact 或 manifest 发生漂移、质量报告无法封存、source catalog 指纹变化时，部署 binding 在 Provider 调用前失败关闭。新增集成用例验证了这一点；相关专项 `18 passed`，compensation 联合回归 `241 passed, 14 skipped, 1 warning`。本项仍是只读技术基线，不代表客户环境部署、规则批准、Provider 执行、跨存储事务或生产验收。

剩余需求仍是客户实际五 Provider 环境的 fault injection/restart、PostgreSQL/RLS/账号/网络策略复验、客户规则和 source-selection profile 版本治理、动态补偿业务决策、任意客户包适配、备份/PITR/RPO/RTO、容量与生产 SLO、监控安全，以及客户/专家正式确认和生产验收。

## 100. 2026-08-18 source-selection profile 技术版本治理

产品已实现 source-selection profile 的不可变发布、连续变更和追加式回滚合同，但没有把技术版本发布扩大为客户规则批准：

- release 固定 profile、source catalog、场景证据、来源角色、前驱、全部祖先、事件类型、变更原因和 SHA-256；history 固定连续版本、active tail 和完整历史指纹；
- v1 必须无前驱，后续版本必须逐一追加；回滚只能恢复较早祖先并产生新版本。no-op、跨场景变更、当前版本回滚、错误 target profile、active pointer 或 release/history 篡改均失败关闭；
- 当前实际证据只发布 `heping_review` v1，history SHA-256 为 `a2aab4fd2c794dba68f6f50ac24f18d80d959bd7bfdccc6d2f05cf86dd534fd1`。v2 变更和 v3 回滚使用临时复制 bundle 验证，不写成客户真实历史；
- 每个版本固定 `customer_approval_present=false`、`production_execution_authorized=false`、`authority_write_performed=false`。专项 `5 passed`，compensation 联合回归 `246 passed, 14 skipped, 1 warning`。

因此，**profile 技术版本/变更/回滚框架已完成，实际客户规则的后续版本、审批、promotion 和生产激活尚未完成。** 后续仍需客户规则驱动的动态补偿、客户真实 Provider/权限/网络环境复验、通用客户包适配、生产运维和安全，以及正式客户/专家验收；本项不代表客户批准、生产授权或跨存储分布式事务。

## 101. 2026-08-18 五 Provider 执行绑定 active profile release

产品已把第 100 节的 profile 发布历史接入重庆五 Provider 主执行入口，避免运行时绕过当前 active 技术版本：

- 新 execution release binding 同时固定 tenant/run、deployment、source catalog、profile、profiled source-lineage、active release 和 release history 指纹，并保持 `customer_approval_present=false`、`production_execution_authorized=false`；
- 五 Provider 主执行入口在首个 Provider callback 前按当前 sealed 输入重建并比对 binding。跨租户 history、stale active release、profile/deployment/lineage 漂移和证据篡改均失败关闭，且不会调用任何 Provider；
- execution result 升级为 v2，携带 binding 和 `profile_release_preflight_performed=true`，但仍不写 checkpoint/completion authority，不新增生产激活或跨存储事务；
- 底层 source-lineage helper 仍是内部技术原语，本轮准确覆盖的是五 Provider 主入口，不能表述为所有内部调用面都已完成生产发布门禁；
- 专项为 `19 passed, 2 skipped`，补偿链完整回归为 `248 passed, 14 skipped, 1 warning`；Ruff、Python 编译和 scoped `diff --check` 通过。

因此，**五 Provider 主执行入口已受 active profile release 门禁约束。** 这只证明当前重庆技术基线的执行版本一致性，不代表客户批准、生产 promotion/activation、authority 准入、客户环境验收或分布式事务。客户真实规则审批与生产 promotion authority、内部 helper 的支持边界、外部 Provider fault injection、部署权限与网络复验、生产运维安全和正式验收仍需继续完成。

## 102. 2026-08-18 五 Provider callback 前 customer-rule current 门禁

产品继续收紧第 101 节留下的 dispatch-to-callback 时间窗口：

- 新增 hash-only `DispatchRuleCurrentBinding`，绑定 dispatch、proposal、candidate、review binding、rule assessment、authority evidence 及每条已批准规则的版本和指纹；不携带客户规则正文、公钥、签名或 Provider 私密材料，也不授予执行 authority；
- 五 Provider 主入口在 profile release preflight 后重新验证调用方提供的 authority current evidence 并重建 review binding。已批准规则版本变化、规则 current 缺失或不可信、租户/候选/plan/contract 哈希漂移和 binding 篡改均在首个 Provider callback 前失败关闭；
- execution result 升级为 v3，包含 rule-current binding 和 `customer_rule_current_preflight_performed=true`。底层 source-lineage helper 仍是内部技术原语，本轮不宣称所有内部调用面都有同等生产门禁；
- 新增 4 条规则 current/漂移/篡改回归；dispatch、五 Provider、authority、recovery 定向为 `19 passed, 2 skipped`，补偿链完整回归为 `252 passed, 14 skipped, 1 warning`，Ruff、编译和 scoped `diff --check` 通过。

因此，**五 Provider 主入口现在同时受 active profile release 和 customer-rule current 两道 callback 前门约束。** 这只证明技术基线的证据一致性，不代表真实客户规则、客户生产 promotion、专家审定、法定审批、外部服务 fault injection、分布式事务或生产验收已经完成。剩余工作仍包括客户真实规则/trust anchor 接入、独立 production promotion authority、内部 helper 支持边界、客户部署权限与网络复验、五类 Provider 重启/fault injection、备份/PITR、RPO/RTO、容量/SLO、监控安全和正式验收。

## 103. 2026-08-18 callback 前 rule-authority live current read

产品已把第 102 节从“验证调用方 evidence snapshot”推进到“主入口主动调用 tenant-bound authority reader”：

- 新只读 reader 协议与现有 `PostgresCustomerCompensationRuleAuthorityStore.assessment_evidence_current()` 对齐；五 Provider 主入口在任何 Provider callback 前按 run ID 获取 authority current evidence；
- reader 缺失、跨租户、返回空或读取异常均失败关闭；live evidence 还必须重新生成 rule-current binding 并与 dispatch 完全一致。execution result 升级为 v4，记录 `customer_rule_authority_live_read_performed=true`；
- authority outage 回归确认 reader 调用一次、Provider 调用为 0。相关定向为 `20 passed, 2 skipped`，补偿链完整回归为 `253 passed, 14 skipped, 1 warning`，Ruff、编译和 scoped `diff --check` 通过；
- 当前测试使用受控静态 reader，尚未在客户 PostgreSQL/RLS 和真实规则/trust anchor 下执行。live read 与五个 Provider callback 也不是同一事务或分布式锁，不应表述为跨存储原子快照。

因此，**主入口现在主动执行 rule-authority live current read，而非只信任调用方旧快照。** 剩余重点是客户 PostgreSQL/RLS 实测、真实规则与 trust anchor、独立 production promotion authority、durable profile release authority 的 live read、内部 helper 入口治理、外部 Provider fault injection、备份/PITR、RPO/RTO、容量/SLO、全执行面安全和正式验收。

## 104. 2026-08-18 callback 前 profile release current 门禁

产品已把第 101 节的 active profile binding 从“只校验调用方携带 history”推进到“主入口主动读取当前 history”，但仍保持技术基线与生产授权分离：

- 新增 tenant-scoped 只读 `ChongqingSourceSelectionProfileReleaseCurrentReader`；五 Provider 主入口按 profile/scenario 获取当前 release history。reader 缺失、跨租户、空结果或异常时，首个 Provider callback 前失败关闭；
- live history 重新校验 sealed history、active tail、profile、deployment、source-lineage 和 execution binding，并与调用方 history/binding 完全相等。active release/history 漂移或哈希篡改均不允许执行；
- execution result 升级为 v5，记录 `profile_release_authority_live_read_performed=true`，但不保存 release 正文、不写 authority、不授予 production execution；
- 新增六类 live-reader 正负向回归；profile/five-provider 定向 `7 passed`；扩大文件匹配、补齐此前漏掉的 recovery compensation 回归后，compensation 相关全量校正为 `261 passed, 14 skipped, 1 warning`。当前 reader 仍为受控静态实现，不是客户 PostgreSQL/RLS durable authority；live read 与 Provider callback 也不是同一事务或分布式锁。

产品可以准确声明：**主执行入口现在对 profile release 和 customer rule 都执行 callback 前的 tenant-bound current read。** 尚未完成的是客户环境中的 durable append-only release authority、production promotion/admission authority、真实规则/trust anchor、内部 helper 调用边界、五类外部 Provider fault injection/重启恢复、备份/PITR、RPO/RTO、容量/SLO、监控告警、全执行面安全，以及客户、专家和法定审批与生产验收；本项不代表客户批准、生产激活或跨存储分布式事务。

## 105. 2026-08-18 profile release durable authority

产品已把第 104 节的静态 reader port 推进为可部署的 PostgreSQL append-only authority，同时保留技术发布与生产授权之间的硬边界：

- migration 185 新增 tenant-RLS release-history table 和 `security_invoker` current view；gateway 不能直接 INSERT/UPDATE/DELETE，只能读取或调用受控追加函数，历史 UPDATE/DELETE 由不可变 trigger 拒绝；
- wheel package-data 已加入 `migrations/*.sql`，构建产物实查包含相关 migration 179、184 和新增 185，避免安装包缺少 authority DDL；
- `PostgresChongqingSourceSelectionProfileReleaseAuthorityStore` 提供 governed `record()`、callback-time `release_history_current()` 和完整 `history_snapshots()`；它直接满足五 Provider 主入口现有 reader contract，数据库返回内容仍重新校验 sealed history；
- SQL 入口强制 v1 initial、版本连续、旧 history 前缀逐字段不变、新 tail predecessor/ancestor/event/rollback 一致；旧快照可幂等重放但不会回退 current，竞争分支被拒绝；
- authority 只保存 `technical_history_active_unreviewed` 且 `customer_approval_present=false`、`production_execution_authorized=false` 的技术发布，不提供 promotion、activation 或 Provider 执行授权；
- 本机临时 PostgreSQL 16 真实验证 `5 passed`，覆盖 v1→v2→v3 追加式回滚、幂等、current 不回退、分叉拒绝、跨租户隐藏和 gateway 直写拒绝；无数据库专项 `4 passed, 1 skipped`，纳入新增文件后的补偿链全量 `265 passed, 15 skipped, 1 warning`，唯一 warning 仍为既有 OpenTelemetry 弃用提示；临时数据库、角色和容器已清理。

产品现在可以准确声明：**profile release 已具备 durable append-only authority 的代码和 PostgreSQL 实测基线，并可直接支撑 callback 前 current read。** 客户数据库 migration/权限复验与 v1 bootstrap 尚未发生；production promotion/admission authority、真实规则/trust anchor、内部 helper 入口治理、规则到 Provider mutation/reconciliation、外部 Provider fault injection、备份/PITR、RPO/RTO、容量/SLO、全执行面安全、监控告警和正式审批验收仍未完成。本项不代表客户批准、生产激活、跨存储原子快照或分布式事务。

## 106. 2026-08-18 独立 production promotion/admission authority

产品已在技术 release current 和 customer-rule current 之外增加第三类独立 authority，避免“技术基线通过即自动进入生产”：

- 新 production-admission target 精确绑定 tenant、run/candidate、dispatch、plan/materialization、deployment、五 Provider request bundle、profile release current 和 customer-rule current 指纹；target 本身固定 `technical_baseline_grants_production_authority=false`，不能自动产生 grant；
- admission history 采用 append-only promotion/revocation/rollback 生命周期。首个 promotion 和每次 rollback 都必须是显式 `human:*` 决策、携带 authorization artifact/trust-anchor 哈希并设置到期时间；活动 grant 必须先撤销才能重新 promotion，rollback 只能指向历史活动 grant 且会追加新版本；
- migration 187 提供 tenant-RLS table、`security_invoker` current view、不可变 trigger 和受控追加函数；gateway 无表直写权限。Python store 提供 governed `record()`、callback-time `admission_history_current()` 和完整 `history_snapshots()`；
- 五 Provider result 升级为 v6。主入口在任何 Provider callback 前实时读取 profile release、customer rule 和 production admission 三类 current，重新构建完整 admission target，并检查 history 未漂移、grant 已生效且未到期/撤销。缺失、故障、跨租户或任一指纹漂移均失败关闭，Provider 调用数为 0；
- recovery 路径已兼容 admission event 的 UTC canonicalization。无数据库 admission 专项 `7 passed, 1 skipped`，admission/五 Provider 合并专项 `27 passed, 2 skipped`；隔离 PostgreSQL 16 定向 `1 passed`，覆盖 promotion→revocation→rollback、幂等、分叉拒绝、RLS 和无表直写；完整补偿链最终为 `269 passed, 16 skipped, 1 warning`，唯一 warning 是既有 OpenTelemetry 弃用提示。Ruff、编译、差异与 wheel migration 检查通过。

产品现在可以准确声明：**独立 production admission authority 已有可部署实现，且主入口默认无 grant、callback 前强制读取 current admission。** 不能声明客户已生产激活：仓库没有真实客户 grant，测试身份、artifact 和 trust-anchor 哈希不是客户认证或签名证明，migration 187 也尚未部署到客户环境。下一步仓库侧应治理内部 helper 入口、完成客户规则 action 到五类 Provider mutation/reconciliation 映射，并扩展全执行面 Subject-Purpose-Resource 权限、审计、监控告警及更通用的数据包/实体冲突/语义规划/跨通道/双时态能力；客户侧仍需真实审批人与 trust anchor、migration 185/187 和 v1 bootstrap、外部 Provider fault injection/重启、备份/PITR、RPO/RTO、容量/SLO、客户/专家/法定审批和生产验收。

## 107. 2026-08-18 内部 source-lineage helper 支持边界

产品已关闭第 106 节留下的内部绕行面，同时保留技术测试、对账夹具和 unknown-position recovery 的明确边界：

- deployment、source-lineage 和 profiled source-lineage 三层 mutating helper 已移出 `__all__`，并在每层入口要求 process-local permit；无 permit、伪造、跨 run 或跨 registry 重放均在零 Provider callback 前拒绝；
- permit 精确绑定 tenant、run、dispatch、registry 和用途，不进入持久模型或对外响应。v6 主入口只在三类 live current、完整 admission target、有时效 grant 和完整五引擎 registry 通过后签发 governed permit，并绑定 current admission event 哈希；
- 技术合同测试和 reconciliation fixture 使用独立用途并固定 `production_execution_authorized=false`，不能把 profile/rule 技术基线升级为生产许可。unknown-position recovery 不消费该技术 permit，而是继续要求受治理的 v6 停止态结果，只续跑 unknown 位置和未尝试后缀；
- 没有新增 API、Capability、MCP mutation 入口或 migration。入口治理专项 `8 passed`，三层 helper/source-lineage 联合 `17 passed`，v6/authority/五类 reconciliation/recovery 联合 `39 passed, 5 skipped`；完整补偿链 `287 passed, 16 skipped, 1 warning`，唯一 warning 是既有 OpenTelemetry 弃用提示，Ruff、编译和静态注册扫描通过。

产品现在可以准确声明：**五 Provider 生产 mutation 的受支持入口已收敛到 v6 governed 主入口，低层 helper 默认失败关闭。** 该 permit 是同一 Python 进程内用于防误用的支持边界，不是恶意代码沙箱，也不替代 Subject-Purpose-Resource 权限、客户身份认证、签名/trust-anchor 验证或外部控制面；仓库仍无真实客户 production grant，callback 前 live read 也不构成跨存储原子快照或分布式事务。下一项仓库侧重点是客户规则 action 到五类 Provider mutation/reconciliation 的业务映射，随后仍需全执行面权限、审计、监控告警，以及任意客户包、复杂实体冲突、自动语义规划、跨通道融合和双时态适配；客户环境部署、真实审批、fault injection、备份/PITR、RPO/RTO、容量/SLO 和正式验收仍未完成。

## 108. 2026-08-18 客户规则 action 到五类 Provider execution/reconciliation 绑定

产品已把第 107 节后的首项仓库需求落实为 callback-time 可验证合同，而不是继续依赖 deployment adapter 的单方面 action 声明：

- customer action map 绑定 proposal/candidate、当前 approved rule contract 和逐位置 plan/engine/target/Provider action，并以客户批准证据中的 `approval_artifact_sha256` 等于 map SHA-256 作为签名关系；map 固定非生产、未 dispatch、未写 authority；
- `CORRECTIVE_FORWARD` 保持 sealed operation，`DELETE_TARGET` 映射 `delete`，`RESTORE_TARGET` 映射 `rebuild`；plan/materialization/native request 与客户动作不一致时零 callback 拒绝。没有 customer-derived reverse plans 的 `ROLLBACK_COMMITTED_PREFIX` 不能生成 action map；
- 五 Provider 主入口从 live rule authority 重建 signed map，再把它与 dispatch、plan set、materialization、五个 native request 和 request bundle 逐位置绑定，随后才允许进入 production-admission permit 签发。签名 artifact、action、target、request 或任一摘要漂移均失败关闭；
- execution result 升级为 v7，保存 action map、execution binding 和五个 hash-only request item，并交叉验证 rule/admission、source/Provider plan、materialization、idempotency、request 和 execution-plan 摘要。mapping binding 始终 `production_execution_authorized=false`，最终生产许可继续只来自独立 admission current；
- recovery 读取并校验同一 v7 mapping policy，已提交前缀继续只恢复 receipt，不重放 mutation；单次调用只允许一次 typed unknown resume。跨进程 attempt budget 的 durable ledger/CAS 仍是后续项，当前不声称全局 exactly-once；
- 新增 5/5 正向和 artifact/action/request/result 重封装负向测试。跨模块回归 `80 passed, 4 skipped, 1 deselected`，完整 compensation 回归 `294 passed, 16 skipped, 1 warning`；warning 仍为既有 OpenTelemetry 弃用提示。Ruff、编译通过，无新增 API、Capability、MCP mutation 或 migration。

产品现在可以准确声明：**customer-approved corrective-forward action 已在受治理 v7 主入口中与五类 Provider 的 5/5 request 和安全 reconciliation policy 完整绑定；DELETE/RESTORE 有明确客户语义映射但仍要求相符的客户派生 native plan；ROLLBACK 无 reverse plan 时失败关闭。** 这不是客户真实签署、生产 grant、专家/法定审批、跨存储事务或生产验收。后续优先级转为 durable recovery attempt ledger/CAS、全执行面 Subject-Purpose-Resource 权限与审计监控，以及客户真实规则/trust anchor、部署、fault injection、备份/PITR、RPO/RTO、容量/SLO 和正式验收。

## 109. 2026-08-18 unknown-position 自动恢复的耐久单次准入

产品已关闭第 108 节保留的跨进程 attempt-budget 缺口，并把“只自动恢复一次”从调用内约定提升为 callback 前 PostgreSQL authority：

- sealed attempt request 绑定 prior v7 result、reconciliation case、request bundle、action map/execution binding、unknown position、engine/request、unknown outcome、fresh observation、actor、attempt ID 和时点；attempt receipt 明确记录预算已在 Provider callback 前从 `expected_consumed_attempts=0` 消耗为 `attempt_number=1`，同时保持非生产证据和非跨存储事务声明；
- migration 188 提供 tenant RLS/FORCE RLS、append-only ledger、current view、不可变历史、gateway 无表直写和 advisory-lock CAS。并发 worker、进程重启或重复调用对同一 tenant/run/request-bundle/position 只允许一个消费者进入 Provider callback，其余全部失败关闭；
- 只有 `provider_not_committed_safe_to_resume` 消耗预算；persisted receipt 已确认提交和 operator-required 分支不消耗。已提交前缀仍只读恢复、从不重放；CAS 后若进程崩溃或 Provider 结果仍不确定，receipt 保留且自动重试被禁止，后续必须人工核验和正式 reconciliation；
- recovery result/position evidence 升级为 v2，并绑定 typed attempt receipt。migration catalog 为 `188`，两个 deployment profile fingerprint 均为 `157e44785e9d6a7547ef78a8a794b8e00040d5fb9ce320a742127cd5b3b22a55`；wheel 已核验包含 migration 188 和全部新模块；
- recovery/attempt 定向 `10 passed, 1 skipped`，隔离 PostgreSQL 16 authority `5 passed`，补偿前缀全量 `286 passed, 20 skipped, 1 warning`，附加 recovery `57 passed, 2 skipped`，migration/profile `30 passed`；套件有重叠不相加。Ruff、编译和差异检查通过，临时数据库容器已清理。

产品现在可以准确声明：**unknown-position 自动恢复具备耐久 single-attempt admission，能跨并发 worker 和重启阻止第二次自动尝试。** 不能声明 Provider 全局 exactly-once、跨存储原子事务或客户生产就绪：CAS authority 与外部 Provider mutation 不是同一事务，仓库未部署客户 migration 188、未完成真实五 Provider fault injection，也没有客户 production grant、签名、trust anchor 或正式验收。下一优先级是全执行面 Subject-Purpose-Resource 权限、审计与监控告警，以及客户真实部署、故障恢复、备份/PITR、RPO/RTO、容量/SLO 和正式审批验收。

## 110. 2026-08-18 五 Provider execute/recovery 的 SPR live 门禁

产品已把第 109 节之后的安全优先级推进到两个受支持 mutation 入口，但保持范围准确，不把局部闭环写成全通道安全完成：

- 新增 hash-only SPR request/decision/current-reader 合同。受控 purpose 固定为 `cross_store_projection_compensation@v1`，subject 必须是 tenant-bound workload 并携带 trace；资源范围逐位置绑定五类 Provider 的 engine、target、action、request、action-map 和 execution-binding 摘要；
- live decision 必须 exact-scope、当前有效、`allow`、由独立 workload evaluator 产生且不带未实现 obligation。deny、过期、跨租户、reader 故障、主体或 scope 漂移均在 Provider access 前失败关闭；该 decision 明确不签发 production admission，仍需独立且当前有效的 production grant；
- 主 execution result 升级为 v8。实际 SubjectContext actor 必须与五个 native request 的 dispatcher workload 相同；process-local governed permit 同时绑定 production-admission event 和 SPR decision，随后才允许首个 callback；
- recovery result 升级为 v3，并重新读取独立 recovery policy。committed prefix 的权限标记为 `read_receipt`，unknown 和 suffix 标记为 `mutate`；allow 发生在 prefix receipt 读取、attempt CAS 和 Provider callback 之前，recovery deny 不消费 attempt；
- 完整 compensation 回归 `296 passed, 17 skipped, 1 warning`，额外 recovery `21 passed, 1 skipped`；唯一 warning 为既有 OpenTelemetry 弃用提示。Ruff、编译、差异、注册扫描和 wheel 内容检查通过；无新 migration、API、Capability、MCP 或 app 入口。

产品现在可以准确声明：**五 Provider 受支持 execute/recovery 已具备 callback-time exact-scope Subject-Purpose-Resource live allow。** 不能声明客户策略控制面或全通道安全已就绪：当前测试 reader 不是客户 policy engine，也没有 durable policy current、Purpose registry authority、immutable audit/operation receipt 强制写入、Prometheus 告警、外部 observation acquisition 门禁或 API/地图/下载/RAG/MCP 统一负向矩阵。下一优先级是把 SPR decision 与既有安全事件账本、操作回执和监控告警做 fail-closed 绑定，再扩展剩余通道与客户真实身份/策略部署。

## 111. 2026-08-19 SPR decision 与 immutable security audit/Prometheus fail-closed 绑定

产品已把第 110 节的 SPR live 门禁接到既有安全事件账本，但范围继续限定为重庆五 Provider execute/recovery 两个 mutation 入口：

- 新增两阶段 typed audit contract：callback 前记录 `admitted`，Provider 结果后记录 `outcome`。审计记录绑定 tenant/run、controlled purpose、workload subject、request SHA、decision SHA、policy ref/version 和五资源 scope 摘要，避免把仅有 policy decision 的内存对象误认为不可变审计事实；
- 主执行和 recovery result 都保存 typed admission/outcome。admission 写入失败在 Provider access 前失败关闭；outcome 写入失败不返回成功结果。recovery 的 prefix receipt 读取、unknown-position attempt CAS 和 suffix callback 均发生在 admission audit 之后；成功恢复记录 `success`，未知或人工分支记录 `unknown`；
- durable adapter 复用现有 tenant-RLS PostgreSQL `SecurityEventLedger`，不新增 migration；内存 adapter 只用于本地合同测试。账本由既有 append-only hash chain、受控函数和 immutable operation-receipt 机制提供持久边界；
- 新增 `agent_security_execution_audit_events_total` 指标，并加入 `GovernedExecutionAuditFailure`、`GovernedExecutionAuditAdmissionWithoutOutcome` 两条 Prometheus 告警。告警把 failure/unknown 和 admission 未闭合显式交给 reconciliation，不把异常路径标记为成功；
- 审计合同专项 `3 passed`，主执行/recovery 审计负向 `3 passed`，Ruff 与编译通过。当前工作区存在大量其他历史改动，完整 compensation 回归需单独复跑，不能与历史 `296 passed` 结果直接相加；

产品现在可以准确声明：**重庆五 Provider execute/recovery 的 SPR allow 已与 immutable security admission/outcome audit 和基础监控告警形成 fail-closed 绑定。** 不能声明全通道安全或客户生产审计已就绪：当前 reader 仍不是客户 policy engine/durable current，其他 API、地图、下载、RAG、MCP、查询和 observation acquisition 未统一接入；客户 migration、真实 identity/purpose provider、Prometheus production route、外部故障注入、备份/PITR、RPO/RTO、容量/SLO 和正式验收仍待完成。

## 112. 2026-08-19 不完整 Provider run 的 failure/unknown 审计闭环

本轮对第 111 节的异常路径进行收口，修复“底层 Provider run 已返回 partial/unknown，但外层结果仍可形成 success audit”的风险：

- 只有完整 5/5 receipt set 才写 `success`；`failed_closed`/partial-success 写 `failure`，unknown 写 `unknown`，并把 evidence 绑定 federated run result SHA-256、调用次数绑定实际 prefix；
- 非完整 execute 仍保留为可供 recovery 使用的封存证据，不可直接送 authority。recovery 生成自己的 operation audit，恢复后的 execution result 保留原始 execute failure/unknown，不篡改 immutable 事实；
- 新增不完整 run 审计回归；五 Provider execute、unknown recovery 与 security audit 三套核心套件本轮为 `42 passed, 1 skipped`。Ruff、Python 编译和 scoped diff 检查通过，跳过项仍是未配置 `DATABASE_URL` 的真实环境用例。

产品现在可以准确声明：**execute/recovery 已区分 success、known failure 和 unknown，并保持原始 execute 审计与 recovery 审计的事实边界。** 这仍不代表客户生产审计、全通道安全、外部故障注入、跨存储事务或正式验收；客户 policy/identity provider、Prometheus production route、备份/PITR、RPO/RTO、容量/SLO 和部署验收仍待完成。

## 113. 2026-08-19 统一语义查询通道的 SPR live 门禁与不可变审计合同

本轮将安全边界从重庆五 Provider 的 mutation execute/recovery 扩展到统一 `semantic.query.execute@4.1.0` 查询入口，范围仍限定为仓库技术合同：

- 新增 `governed_query_security.py`，以 tenant、request、purpose、channel、adapter、资源版本和主体上下文构造 hash-bound SPR request；查询入口在任何 ontology、metric、NL2SQL、GIS 或 RAG adapter 调用前读取 live decision。
- decision 必须与 request 精确相等、当前有效、`allow` 且无未实现 obligation；reader 缺失、跨租户、异常、过期、scope 漂移或 audit admission 失败均在 adapter callback 前失败关闭，adapter 调用数为 0。
- 查询结果在返回前要求 outcome audit。正常完成/计划/已准入结果记录 `success`，适配器错误或资源绑定不一致记录 `failure`；不可变 outcome audit 写入失败不返回成功响应。
- 提供内存合同 adapter 供隔离测试；生产实现应接入既有 tenant-scoped PostgreSQL `SecurityEventLedger`。本轮没有新增 migration，也没有把测试 reader 当成客户 policy engine。
- 专项查询安全回归与既有查询回归合计 `25 passed, 1 warning`；Ruff 与 Python 编译通过。

这关闭了“统一查询通道只有角色检查、没有 callback 前 live SPR 和 outcome audit”这一仓库技术缺口。仍未完成的是客户真实 policy/identity/purpose provider、查询结果读取/缓存/地图/报告/下载/RAG/MCP 的全通道负向矩阵、Prometheus production route、真实客户部署、备份/PITR、RPO/RTO、容量/SLO 和正式验收；本节不代表全执行面安全、客户生产授权或跨存储事务。

## 114. 2026-08-19 governed-query HTTP 入口的安全端口装配与生产 fail-closed

第 113 节只在 `execute_governed_query()` 支持可选安全端口，HTTP 路由仍可能在没有部署 policy/audit 端口时走开发兼容路径。本轮把这一边界推进到公共 API：

- 新增 deployment-owned `GovernedQuerySecurityPortResolver`。resolver 只按服务端 tenant 解析 live policy reader 与 immutable audit port，客户端 body/header 不能提供或覆盖任何安全端口；admission audit 现在还显式保存 `subject_ref`，便于账本检索；
- `GDA_GOVERNED_QUERY_SECURITY_REQUIRED=1` 时，`/api/governed-query` 没有 resolver、resolver 抛错、布尔配置非法、端口不匹配或端口结构错误，统一在 adapter access 前返回 `503 query_security_unavailable`；`0` 只保留本地开发兼容行为；
- `docker-compose.prod.yml` 和 `docker-compose.staging.yml` 已将该开关固定为 `1`。`.env.example` 与 `data_agent/.env.example` 已写出 resolver、策略和审计端口由部署侧接入的前置条件；
- `/ready` 现在同时检查该安全门：生产/staging 开关开启但 resolver 尚未装配时，实例保持 `not_ready`，不会被服务发现继续送流量；安全开关关闭的本地开发模式仍显示 `disabled` 而不阻断 readiness；
- 路由正向、deny、无 resolver、resolver 故障、非法开关和 adapter 零调用回归已覆盖；查询 route/security/query 三套专项为 `40 passed, 1 warning`，Ruff、编译、diff check 和 Compose 配置解析通过。

准确口径是：**生产/staging 公共查询 API 已具备“安全端口未装配就不可用”的 fail-closed 装配边界。** 仓库仍没有客户真实 policy/identity/purpose resolver、durable policy current 或 production Prometheus route；本轮不代表客户生产安全已部署。后续仍需客户控制面实现 resolver、真实身份/目的注册、查询结果读取/缓存/地图/报告/下载/RAG/MCP 全通道矩阵、备份/PITR、RPO/RTO、容量/SLO 和正式验收。

## 115. 2026-08-19 governed-query policy current authority（开发阶段）

本轮继续在仓库内补齐查询安全策略生命周期，不以客户环境或正式部署作为完成条件：

- 新增 `governed_query_policy_authority.py`，提供 tenant-bound purpose registration、不可变 policy version、追加式 revocation 和 callback-time current reader；未注册 purpose、过期/未来策略、主体/角色/通道/adapter/资源范围不匹配时统一默认 deny；
- 同一 `policy_ref` 只取最新发布版本，旧版本不会在新版本不匹配时回退生效；重复但内容不同的注册、版本或撤销均报告 immutable conflict；
- 新增 `InMemoryGovernedQueryPolicyAuthority` 与 tenant resolver，用于开发运行和合同测试，并复用既有查询安全 request/decision/audit port；该 adapter 明确是开发期 authority，不冒充外部客户策略引擎；
- 新增 migration `190_governed_query_policy_authority.sql`，定义 purpose、policy version、revocation 三张 tenant-RLS 表，版本/撤销不可变 trigger 及 gateway 只读权限边界；
- 新增策略 authority 专项 `8 passed`，与统一查询、查询安全、HTTP、health 受影响专项合计 `75 passed, 1 warning`；Ruff、Python 编译通过。唯一 warning 仍为既有 OpenTelemetry 弃用提示。

当前开发阶段可准确声明：**查询入口已有可版本化、可撤销、tenant-bound 的 policy current authority 合同，能够替代随意注入的静态 allow reader。** 本节形成时 PostgreSQL 受控写入和启动装配尚未完成，现已由第 116 节补齐；后续重点转为管理 API 与查询之外地图、下载、报告、RAG、MCP、observation acquisition 的统一矩阵。

## 116. 2026-08-19 durable query policy authority 与启动装配（开发阶段）

第 115 节完成了策略模型和内存 current reader，本轮将其推进为可由开发环境直接运行的 PostgreSQL authority：

- migration 190 新增 purpose registration、policy version、revocation 三个 `SECURITY DEFINER` 受控追加函数；gateway 只有表 SELECT 与函数 EXECUTE，没有表 INSERT/UPDATE/DELETE，重复相同内容可幂等重放，immutable identity 内容漂移返回冲突；
- 新增 `PostgresGovernedQueryPolicyAuthority`，写入后重新读取并校验 sealed model；current decision 在单个 transaction timestamp 内 join 读取 purpose、全部版本和撤销，再执行与内存 authority 相同的 latest-version、时态、SPR scope 和 default-deny 规则；
- 新增 `PostgresGovernedQuerySecurityPortResolver`，同时提供 PostgreSQL policy reader 与既有 `SecurityEventLedger` audit port。应用启动时仅在安全开关开启、且未显式配置 resolver 时安装该默认 durable resolver；开关关闭不改变开发兼容模式，非 PostgreSQL 配置失败关闭；
- 隔离 PostgreSQL 16 真实开发演练 `1 passed`，覆盖 purpose/policy/revocation 幂等、allow→revoke→deny、跨租户默认拒绝和 gateway 禁止表直写；临时容器已清理；
- migration catalog 当前为 190 项，最新项为 `190_governed_query_policy_authority`，fingerprint 为 `7ddc2ceafd9c94b0c7207907a3eee855cf82de907d959def72e0fc43abb285bc`；两个开发 deployment profile 已同步；
- 查询、策略、HTTP、health、migration 和 deployment profile 联合回归 `113 passed, 1 skipped, 1 warning`。跳过项是常规无 `DATABASE_URL` 进程中的同一 PostgreSQL 演练，已单独实跑通过；warning 仍为既有 OpenTelemetry 弃用提示。Ruff、编译和 scoped diff check 通过。

当前开发阶段可准确声明：**governed-query 已具备 durable purpose/policy/revocation authority、同事务 current read、不可变审计 port 和应用默认装配。** 后续仓库需求是增加策略管理 API/CLI、查询结果读取与缓存安全，并把同一 Subject-Purpose-Resource 矩阵扩展到地图、下载、报告、独立 RAG/MCP 和 observation acquisition；不以客户部署或正式验收作为本节条件。

## 117. 2026-08-19 governed-query 策略管理 API（开发阶段）

第 116 节已经提供 durable authority，但此前 purpose、policy version 和 revocation 还没有受认证的应用层写入口。本轮补齐仓库内开发 API：

- 新增 `governed_query_policy_routes.py`，提供 `POST /api/governed-query-policy/purposes`、`POST /api/governed-query-policy/versions` 和 `POST /api/governed-query-policy/revocations` 三个追加式写接口，并在 `frontend_api.py` 完成注册；
- 三个接口只允许 `admin` 或 `platform_operator`。tenant 来自服务端认证上下文，actor 固定封装为 `human:<username>`，注册/发布/撤销时间取服务端 UTC；客户端不能提交 tenant、actor、authority port、时间或任何 fingerprint 字段；
- 请求模型采用 `extra=forbid`，策略作用域显式包含 subject type/id、required role、purpose、channel、adapter、resource prefix 和 obligation。服务端调用既有 builder 生成 content/record/revocation SHA-256，再交给 `PostgresGovernedQueryPolicyAuthority` 的受控函数写入；
- 错误边界稳定映射为 validation `400`、tenant/authority forbidden `403`、immutable conflict `409`、configuration/unavailable `503`。匿名、无 tenant、错误角色和客户端伪造 authority 字段均在数据库调用前拒绝；
- 新增独立路由正负向测试并纳入查询、策略、HTTP、health、migration、deployment profile 和 CapabilitySpec 联合回归，结果为 `163 passed, 1 skipped, 1 warning`。跳过项仍是常规进程未配置 `DATABASE_URL` 的真实 PostgreSQL 用例；该用例此前已单独实跑通过。唯一 warning 仍为既有 OpenTelemetry 弃用提示；新增文件 Ruff、Python 编译和 scoped diff check 通过。

当前开发阶段可准确声明：**受控查询的 purpose 注册、不可变 policy version 发布和追加式撤销已有 tenant-bound、角色受限、服务端封印的 HTTP 管理入口。** 本轮没有新增 migration，catalog 仍为 190 项。策略管理核心 API 已完成；后续优先级转为查询结果读取与缓存，以及地图、下载、报告、独立 RAG/MCP、observation acquisition 的统一 Subject-Purpose-Resource 与审计矩阵。

## 118. 2026-08-19 指标/GIS 查询结果消费的 SPR current 门禁（开发阶段）

第 117 节完成策略写入口后，本轮将 durable current reader 接到两个已有的结果下载边界，先关闭查询完成后通过签名 URL 消费 Artifact 时的策略旁路：

- 新增 `governed_query_result_access_security.py`，定义独立的 sealed result-consumption request/decision，operation 固定为 `governed.query.result.access`，不把下载行为伪装成原始 `semantic.query.execute`；请求绑定 tenant、typed subject、受控 purpose、channel、adapter、消费模式、TTL、run/artifact 资源引用和请求 payload SHA-256；
- 专用 evaluator 将 result-consumption scope 映射到既有 durable policy current reader 的 purpose/subject/role/channel/adapter/resource 规则，再把 allow 重新封印为 exact original-request decision。deny、过期、跨 tenant reader、scope 漂移、reader 异常或未实现 obligation 均失败关闭；
- `MetricQueryResultAccessService` 和 `GISAnalysisResultAccessService` 的顺序统一为：owner/operator 与成功 Run 检查 → live SPR current → immutable `admitted` → Artifact authority → 对象版本/字节完整性校验与短时签名 → immutable `outcome`。SPR deny、reader 故障或 admission audit 故障时 Artifact/S3 调用数均为 0；
- 两个 HTTP result-access 请求新增受控 `purpose_code`，并复用应用 tenant resolver。安全开关开启但 resolver 缺失或异常时返回 `503`；客户端仍不能传 reader、decision、audit port、tenant 或 actor；
- 指标 cache-hit Run 与普通 Run 走同一门禁，cache status 不构成 policy bypass。安全审计只保存 run/artifact 引用、request/decision SHA、policy ref/version 和结果摘要，不写对象 URI、签名 URL 或凭据；
- 专用合同与结果访问定向回归 `46 passed`；查询、policy、指标、GIS、health、migration/profile 联合回归 `312 passed, 1 skipped, 1 warning`。跳过项仍是未配置 `DATABASE_URL` 的真实 PostgreSQL 用例，warning 仍是既有 OpenTelemetry 弃用提示；Ruff、Python 编译和 scoped diff check 通过。

当前开发阶段可准确声明：**指标查询结果与 GIS 分析结果的普通/缓存命中下载，在 Artifact 和对象存储访问前都要求 callback-time exact-scope SPR allow 和不可变 admission/outcome 审计。** 本轮没有新增 migration，catalog 仍为 190 项；尚未覆盖地图投影、报告生成以及通用 data-product/distribution 下载，也不代表所有结果消费通道或跨存储事务已完成。

## 119. 2026-08-19 地图、数据产品、分发与报告结果交付 SPR 矩阵（开发阶段）

第 118 节完成指标/GIS Run 结果后，本轮关闭当时明确列出的地图投影、报告生成和通用 data-product/distribution 交付缺口：

- 新增 `governed_query_result_delivery.py`，复用独立 `governed.query.result.access` sealed request/decision，为非 Run 型结果出口统一执行 live current、不可变 `admitted`、下游调用和不可变 success/failure `outcome`；deny audit 自身故障不会放行，admission 或 success outcome 写入故障会阻止结果返回；
- 地图 publication 的 MVT tile 和单 feature、DataProduct 的 PostGIS features、STAC 与 GeoJSON download、distribution ZIP download、QC report generation 均已接入。受控目的固定由服务端提供为 `query_result_access`，客户端不能提交 tenant、actor、reader、decision、audit port 或 purpose 覆盖值；
- 认证地图/分发/报告入口使用认证上下文生成 `human:<username>`、role 和 tenant；公开 DataProduct 入口固定使用 `agent:public-data-product-gateway`、`public_reader` 与服务端 `PUBLIC_TENANT`，策略需要显式匹配该 agent scope，不把匿名请求伪装为 human；
- current allow 和 admission 均发生在 Martin、PostGIS、Artifact authority、S3、本地 ZIP/GeoJSON 字节读取和报告生成器之前。DataProduct 的 S3/file 下载继续校验 Artifact size/SHA-256；本地文件改为读完并校验后再记录 outcome 和返回，不在实际读取前把 `FileResponse` 视作成功；
- 安全账本只保存资源引用、purpose/role/channel/adapter/消费模式、request/decision SHA-256 和 policy ref/version；不保存对象 URI、文件路径、签名 URL、凭据、tile/feature 字节或报告 payload。下游异常只记录异常类型，不记录可能含敏感路径的异常正文；
- `GDA_GOVERNED_QUERY_SECURITY_REQUIRED=1` 时 resolver 缺失/异常在下游前返回 `503`；未开启强制开关且未配置 resolver 时保留既有开发兼容路径。跨出口 deny/reader/admission/outcome 故障矩阵和既有接口回归为 `80 passed`；governed-query、metric/GIS、health、migration/profile、地图、DataProduct 和 distribution 联合回归为 `439 passed, 3 skipped, 2 warnings`。跳过项为既有可选集成测试，warning 为既有 Starlette/httpx 与 OpenTelemetry 弃用提示；新增文件及 map/data-product/distribution 相关文件 Ruff、Python 编译和 scoped diff check 通过，历史 `quality_routes.py` 仅执行本轮相关未定义/未使用导入检查与编译。

当前开发阶段可准确声明：**第 118 节列出的普通/缓存结果、地图投影、DataProduct/STAC、分发 ZIP 和 QC 报告生成出口，已统一具备可强制开启的 exact-scope SPR current 与 admission/outcome 失败关闭边界。** 本轮结果安全矩阵没有新增 migration；并行开发后的当前 catalog 为 192 项，最新项 `192_metric_observation_projection`，fingerprint 为 `8abee0cfc417474b5c538a4a838bfa57e869f7ed2de00766bc6f521dfa8c81d9`。这不代表 ontology/offline diagnostics 等仓库全部文件接口、独立 RAG/MCP/observation acquisition 或所有执行通道已经覆盖，也不代表跨存储事务。按当前开发需求清单，结果消费矩阵这一类的约定范围已完成，剩余为 6 类：独立 RAG/MCP/observation acquisition 安全、通用 Proposal/Action runtime、自动语义规划与跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展、开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

## 120. 2026-08-19 独立 RAG、MCP 与观测采集 external-access 安全（开发阶段）

第 119 节完成结果交付后，本轮补齐当时剩余清单中的第一类非结果型外部访问，并与 `governed.query.result.access` 保持合同隔离：

- 新增 `governed_external_access_security.py` 与 `governed_external_access.py`。operation 固定为 `governed.external.access`，访问模式严格限定为 `retrieve`、`invoke`、`acquire`；请求绑定 tenant、typed subject、role、服务端 purpose、channel、adapter、稳定资源引用、payload SHA-256 和评估时间。evaluator 将该范围交给既有 durable SPR current reader，再把 allow 重新封印到原始 external-access request；deny、过期、scope 漂移、跨 tenant reader、reader 异常和未实现 obligation 均失败关闭；
- 公共 `POST /api/kb/search` 现在只接受明确的 `kb_ids` 与不可变 `document_pins`，在 embedding 和知识库数据库访问前完成 current allow 与 admission。检索结果继续重算 document/chunk SHA-256、验证 tenant/owner 元数据并返回稳定 locator。旧 `/api/kb/{id}/graph-search` 不再直接调用 legacy GraphRAG，而是明确返回 `legacy_graph_rag_not_admitted`，没有静默 fallback；
- 本地 MCP tool registry、远程 `MCPHub.call_tool` 和旧 stdio bridge 均接入 `invoke` 门禁。远程 Hub 在 tool discovery/session/call 之前准入；本地与 stdio 使用 MCP 上下文生成 `agent:<id>`、role 和 tenant。MCP 参数只参与内存 canonical hash，不写入安全账本；
- observation acquisition 本轮选择已有可恢复、可注入 connector 的 SmartMakani ArcGIS 采集入口作为有界真实通道：每个 allowlisted layer 的 snapshot freeze、分页读取和恢复下载均位于 `acquire` admission 之后。资源引用使用逻辑 provider/layer identity，不把 endpoint URL、凭据、bbox payload、观测值或下载结果写入审计。该接入证明 SmartMakani 路径，不外推为所有观测 Provider；
- 三类通道统一先写 immutable `admitted`，操作异常写 failure outcome，成功结果在 success outcome 写入完成后才返回。policy deny、reader 故障或 admission audit 故障时 operation 调用数为 0；failure/success outcome 审计故障不会返回下游结果。账本只保存 request/decision/policy hash、范围元数据、异常类型和操作调用数，不保存查询正文、工具参数、URL、凭据或业务 payload；
- `GDA_GOVERNED_QUERY_SECURITY_REQUIRED=1` 且 resolver 缺失/异常时继续失败关闭；未开启强制模式且没有 resolver 时保留本地开发兼容行为。本轮新增合同/跨通道负向矩阵 `16 passed`；与 governed-query、policy、结果访问、RAG、KB/GraphRAG、MCP、MCP asset bridge 和 SmartMakani 既有测试联合回归为 `322 passed, 1 skipped, 4 warnings`。跳过项为既有条件测试，warning 为既有依赖弃用/实验特性提示；新增模块、API 与 stdio bridge Ruff、Python 编译和 scoped diff check 通过。

当前开发阶段可准确声明：**不可变文档 RAG、GIS Data Agent 本地/远程/stdio MCP invocation，以及 SmartMakani 观测采集入口，已形成独立 `governed.external.access` 的 SPR current 与 admission/outcome 失败关闭矩阵。** 本轮没有新增 migration，catalog 仍为 192 项，最新项 `192_metric_observation_projection`，fingerprint 仍为 `8abee0cfc417474b5c538a4a838bfa57e869f7ed2de00766bc6f521dfa8c81d9`。这不代表内部 legacy RAG 自动晋级、所有 observation Provider 已覆盖、MCP 工具副作用与账本具备跨存储事务，或 Provider 全局 exactly-once。按当前开发清单，该类约定范围完成后剩余 5 类：通用 Proposal/Action runtime、自动语义规划/澄清/跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

## 121. 2026-08-19 通用 Proposal/Action runtime 合同与 L1/L3 纵向切片（开发阶段）

本轮完成剩余清单中的通用 Proposal/Action runtime 开发切片，并严格复用现有产品权威边界：

- 新增 `data_agent/action_runtime.py`，产品规范名统一为 `ActionTypeDefinition`。定义固定绑定一个现有 `CapabilitySpec` 的 ID、版本、fingerprint、operation、risk、side effect、policy action、幂等、补偿和 reconciliation 声明；参数/结果 Schema 与 CapabilitySpec 精确一致，发生漂移即失败关闭；
- `ActionTypeDefinition.to_platform_definition()` 投影为既有 `PlatformDefinitionVersion(orchestration_class=action)`；一次 Action occurrence 只关联既有 `PlatformRun`，没有增加 `ActionRun` 调度器或第三套执行状态权威。Agent 通道可附加 `AgentRun/ToolCall` correlation，但不能替代 PlatformRun；
- 新增不可变 `ProposalArtifact`、`ChangeSet`、`ActionResult`。Proposal 明确 `execution_authorized=false`，固定对象版本、参数 hash、Capability/ActionType fingerprint、证据、预期变化和 proposed run；ChangeSet 表达 derive/create/update/delete 的 before/after；ActionResult 保存实际变化、结果 hash、外部 receipt 和机器可比较的 `exact/out_of_bounds/not_observed`；
- ApprovalCase 的复合 target binding 同时固定 Proposal、ActionType/Capability、当前对象版本、参数、ChangeSet、PolicyDecision、幂等键和调用通道。未审批 L3、拒绝/过期审批、deny/过期 Policy、Proposal/参数/ChangeSet/对象版本/Policy 漂移均在 executor 前失败，执行调用数为 0；
- L1 切片覆盖只读/临时派生产物且无需强制审批；L3 切片覆盖明确对象版本的 external write、人工审批、幂等、Provider receipt、实际变化比较、补偿和 reconciliation。Web、API、MCP、Agent 只改变 invocation channel，均进入同一个 runtime，不各自持有业务状态机；
- 顺序与并发同 idempotency key 均只允许一次副作用；同 key 不同 immutable intent 返回冲突。外部结果未知、executor/receipt 合同异常或已发生的实际变化超出 ChangeSet 时不得记录 success，进入 `PlatformRun.reconciling`；
- `DevelopmentPlatformActionLedger` 只是隔离开发测试 adapter，保存的仍是 canonical PlatformRun 和 ActionResult，不冒充 PostgreSQL durable authority。后续接 durable Artifact/ResourceVersion/PlatformGateway 时不改变上述业务合同。

新增专项 `18 passed`；与 Platform contracts、Capability registry、PlatformGateway、ApprovalCase authority 及既有专项 compensation Proposal/Approval/Execution authority 的联合回归为 `185 passed, 1 skipped, 1 warning`。跳过项是既有条件型 PostgreSQL 测试，warning 是既有 OpenTelemetry 弃用提示；Ruff、Python 编译和 scoped diff check 通过。本轮无新增 migration，catalog 保持 192 项，最新项和 fingerprint 不变。

当前开发阶段可准确声明：**通用 ActionType/Proposal/ChangeSet/ActionResult 合同，以及复用 PlatformRun 的 L1/L3 执行纵向切片已经形成；审批漂移、并发幂等、外部未知结果和超界变化具备失败关闭测试。** 不能据此宣称 Proposal/Action 工件已完成 PostgreSQL durable API、所有 Capability 已接入、Provider 全局 exactly-once 或跨存储原子事务。按当前顶层开发清单，剩余 4 类：自动语义规划/澄清/跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

## 122. 2026-08-19 自动语义规划、结构化澄清与跨通道证据融合（开发阶段）

本轮完成第 121 节剩余清单中的自动语义编排开发切片，并保持模型建议与确定性执行分离：

- 新增 `data_agent/semantic_query_orchestration.py`。`SemanticPlanningRequest` 固定 tenant、SubjectContext、purpose/purpose code、调用面、允许通道、不可变资源版本、节点/通道/工具调用/Token/成本预算，以及 provider/model/model version/prompt version；请求、模型绑定、候选、执行计划、澄清和融合结果均为不可变 hash-sealed 合同；
- 模型只实现 `SemanticCandidateProposer`，没有 executor 或 tool callback。候选 DAG 的每个节点都必须是显式 Ontology/Metric/NL2SQL/GIS/RAG typed request，并重新通过现有 `plan_query_route()`；节点固定绑定 `semantic.query.execute` 的 ID、版本、Capability fingerprint、输出 Schema fingerprint 和独立 evaluator ref。模型绑定缺失或漂移、虚构资源版本、purpose 漂移、未注册通道、循环/未知依赖、融合 selector 漂移和预算超限均不准入；
- Web/API 在合同层复用现有 HTTP API 执行投影，MCP/Agent 复用现有 Agent/MCP 投影，不创建四套 planner 或业务状态机。当前只是统一 invocation-surface 合同与投影校验，没有新增 Web、REST 或 MCP planner endpoint；
- `ClarificationRequirement` 提供歧义概念、指标、空间关系、时间范围、非等价降级、冲突和资源版本等结构化原因与有界选项；`ClarificationResolution` 必须由 `human:*` 确认，并绑定 request、prior plan、clarification 和选项。`replan()` 会真实第二次调用 proposer，要求 revision 连续且 `supersedes_plan_sha256` 指向前一计划，不接受旧计划或未知选项重放；
- `SemanticPlanExecutor` 按 DAG 执行已准入节点，并重新校验 request、subject、Capability、route admission、成功状态、EvidenceBundle 完整性和 claim citation。上游证据无效时依赖节点零调用；融合只输出 citation-verified claim variants 与全局 evidence 引用，不生成自由文本答案。相同陈述可标记 corroborated，不同陈述保留 conflicted，缺证据进入 needs clarification，不静默选择一个结论；
- prompt injection/写意图在 proposer 前阻断。模型不可用时，只允许一个已经类型化、显式通道且仍可重新准入的 deterministic seed；`AUTO` seed、多 seed 或不满足版本/目的/能力约束的 seed 不会借降级执行。

新增专项回归 `19 passed`；与五通道 governed query、安全、route、GIS workflow proposal 和 Capability registry 的联合回归为 `98 passed, 1 warning`。warning 是既有 OpenTelemetry 依赖弃用提示；Ruff、Python 编译通过。本轮没有新增 migration、Capability 或外部 endpoint。

当前开发阶段可准确声明：**自然语言候选规划现在有受限、版本绑定的复合 DAG 准入合同，歧义会形成可审计的人类澄清并真实重规划，多通道结果只按已验证 claim/citation 融合且显式保留冲突与缺失。** 这不代表已接入某个真实模型 Provider、模型能直接调用工具、MIX-01 至 MIX-04 正式 fixture/质量基线已冻结、所有新通道均已接线，或跨存储事务已经完成。按当前顶层开发清单，该类约定范围完成后剩余 3 类：复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

## 123. 2026-08-19 复杂实体冲突、双时态与既有域迁移编排（开发阶段）

本轮完成第 122 节剩余清单中的复杂实体冲突与既有域迁移开发切片，直接复用现有实体权威边界，不创建并行身份或时态真相源：

- 新增 `data_agent/entity_domain_migration.py`，以 `EntityDomainMigrationRequest` 固定 tenant、旧域 Resource、不可变来源快照、mapping contract 版本与 SHA-256、effective time、候选集合和预算。候选直接复用 `TemporalEntityAssertionDraft`、`EntitySourceBindingDraft` 与 `EntityLineageRequest`，写入目标仍分别由现有双时态实体断言、来源绑定和实体沿革 authority 负责；
- 自动准入只允许唯一的 `authoritative_identifier` 或 `authoritative_composite_key` 候选，且置信度必须为 10000、时态模式必须为 `INITIAL`。同一 SourceIdentity 多目标、spatial/reviewed/低置信候选、correction/transition、多来源目标状态冲突，以及 merge/split/replacement 均形成显式 conflict，必须由 `human:*` 提交绑定 request、prior plan、conflict、option 和时间的决议；
- 支持真实多轮 `replan`：第一轮可解决来源身份歧义，重新规划后再暴露目标状态冲突；plan revision 必须连续，且新计划通过 `supersedes_plan_sha256` 指向旧计划。未知选项、旧计划、代理决议或绑定漂移均不准入；
- 任何冲突未决时，计划不暴露 authority write payload，三个 authority executor 调用数均为 0。同一目标、同一状态的多来源候选会合并为一个实体断言，同时保留全部 SourceBinding 证据，避免重复断言又不丢来源；
- 执行按 entity assertions、source bindings、lineage events 分阶段调用既有 authority。任一阶段失败即停止后续阶段并进入 `reconciling`；合同明确 `cross_stage_atomic=false`，恢复依赖既有 authority 的幂等重放，不宣称跨阶段原子事务、全局 exactly-once 或跨存储事务；
- 新增专项回归 `14 passed`；与 temporal entity、entity link、entity lineage、entity batch/API、lineage API、重庆 Link reconciliation 和条件型 PostgreSQL lineage 测试的联合回归为 `73 passed, 1 skipped`。唯一跳过项是未配置 `DATABASE_URL` 的 PostgreSQL 条件测试；Ruff、格式化和 Python 编译通过。

本轮没有新增 migration、Capability 或外部 endpoint。当前开发阶段可准确声明：**已有双时态、来源绑定与实体沿革 authority 之上，已经形成保留冲突、要求人类决议、支持多轮重规划且未决零写入的旧域迁移编排，并能把阶段失败明确送入 reconciliation。** 这不代表系统会自动生成任意客户映射合同，不代表跨 authority 阶段原子事务，也不代表大规模旧域迁移性能已经完成。按当前顶层开发清单，剩余 2 类：跨存储投影与失败恢复扩展；开发级备份/PITR、容量、p95/p99、SLO 与国产化组合兼容测试。

## 124. 2026-08-19 跨存储投影 cohort 准入与失败恢复扩展（开发阶段）

本轮完成第 123 节剩余清单中的跨存储投影与失败恢复扩展，定位为现有五类 Provider/checkpoint/recovery 合同之上的通用 cohort 层，不重建底层 authority：

- 新增 `data_agent/cross_store_projection_cohort.py`，提供 `ProjectionCohortPlanningRequest`、目标级 assessment、cohort plan、source snapshot evidence、checkpoint current admission、execution admission 和 execution result。cohort 请求固定 tenant、同一 `source_resource_version_ref`/source content SHA-256、唯一目标集合、Provider mutation budget 和 typed actor；任一目标 fail-closed 或预算超限时，不暴露任何 executable repair plan；
- cohort 规划继续复用 `ProjectionDesiredState`、`ProjectionTargetObservation`、`ProjectionCheckpoint` 和 `ProjectionRepairPlan`。执行前先读取并封存 source snapshot current，再逐目标读取 checkpoint current，确认 predecessor/version 或已提交 checkpoint 与 federated cursor 一致；source 漂移、checkpoint 漂移、reader 异常或证据类型错误均在首个 Provider callback 前失败关闭；
- 执行层复用既有 `FederatedProjectionRecoveryCoordinator`、单目标 recovery ledger 和五类 Provider adapter。中间目标出现 unknown outcome 时，已提交前缀保持只读已提交证据，后缀不启动并进入 `reconciling`；重复调用只复核 current，不重放已提交前缀或未准入后缀。通用 coordinator 仍允许既有多源联邦场景，同源限制只对显式 cohort 合同生效；入口新增 sealed plan 重校验，防止未封印 plan 进入 run；
- 合同显式 `cross_target_atomic=false`、`checkpoint_write_performed=false`，不把全目标 preflight 描述为跨存储事务或 exactly-once。实际 checkpoint 写入和 Provider mutation 仍由已有各目标 authority/adapter 完成，cohort 层只提供 callback 前证据门；
- 新增专项回归 `15 passed`；跨存储一致性、单目标恢复、联邦恢复、五 Provider 补偿、checkpoint、recovery job/authority 全量套件为 `388 passed, 20 skipped, 1 warning`。跳过项为既有未配置 `DATABASE_URL` 或可选集成的条件测试；warning 为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 `git diff --check` 通过。

本轮没有新增 migration、Capability 或外部 endpoint。当前开发阶段可准确声明：**显式同源跨存储 cohort 已具备 all-target current preflight、未决零 Provider 调用、阶段失败 reconciliation、unknown 前缀保留和重复恢复不重放的通用开发合同；既有多源联邦 run 仍按原 coordinator 语义运行。** 这不代表跨存储全局原子事务、Provider 全局 exactly-once、客户生产故障注入或大规模容量性能已完成。当前顶层剩余 1 类仓库需求：开发级备份/PITR、容量、p95/p99、SLO 与国产化组合兼容测试。

## 125. 2026-08-19 开发可靠性、容量、分位数与组合兼容基线（开发阶段）

本轮完成第 124 节最后一类顶层开发需求，并把已有恢复证据与新增观测合同组合为统一、不可冒充正式目标的基线：

- 新增 `data_agent/platform_runtime/development_reliability.py`。`ReliabilityEvidenceReference` 分别绑定 backup、PITR、recovery SLI 的证据 SHA-256、profile、compose 配置 SHA-256、观测时间和 `technical_pass=true`；它引用已有证据，不重新伪造或扩大原证据结论。三类证据缺失、profile/config 漂移或证据晚于基线时间均拒绝封印；
- `LatencyObservation` 要求至少 5 个正延迟样本，保存完整样本并按 nearest-rank 可重现计算 p50/p95/p99；`CapacityObservation` 固定 concurrency、duration、完成/失败数和最大队列深度，可重现派生吞吐与错误率，零请求不能形成容量观测；
- `ReliabilitySLOThresholds` 固定同一 operation 的 p95/p99、最小吞吐和最大错误率阈值，拒绝低于 p95 的 p99 阈值。latency、capacity 和 threshold operation 集合必须精确相同且各自唯一，`evaluate_development_slo()` 只返回逐阈值观测结果，不把通过值升级为正式 SLO；
- `ReliabilityCompatibilityMatrix` 以 CPU、OS、数据库、中间件、模型服务五维记录 `passed/failed/untested`。`passed` 必须绑定证据；组合不可重复，组件标签拒绝路径、换行和常见敏感字段。开发 fixture 包含现有 arm64/Linux/PostgreSQL/MinIO/OpenAI-compatible 通过行，以及 `kunpeng920-arm64 + kylin-v10 + opengauss-6 + tongweb-8 + qwen3-compatible` 的 `untested` 候选行，后者明确不构成国产化兼容结论；
- `DevelopmentReliabilityBaseline` 仅接受 `dev/test` profile，统一封印 compose identity、三类恢复证据、延迟/容量/阈值和兼容矩阵；治理状态固定为 `slo_status=observed_not_approved`、`rpo_status=not_defined`、`rto_status=not_approved`、`promotion_ready=false`。验证器会逐项检查外部输入绑定并重建 baseline fingerprint；
- 新增专项回归 `8 passed`，Ruff、格式化和 Python 编译通过。既有 PITR/recovery/SLO 回归为 `51 passed, 3 xfailed`，另有 1 个既有历史 recovery SLI fixture 失败：其封存的 compose SHA-256 与当前已修改开发 profile 不同；本轮保留历史证据，不通过刷新旧 fixture 掩盖漂移。无新增 migration、Capability 或外部 endpoint。

当前开发阶段可准确声明：**仓库已具备将 backup/PITR/recovery 证据、可重现 p95/p99、容量观测、开发阈值判定和五维组合兼容状态封印到同一开发基线的严格合同，并能显式保留国产候选组合的 `untested` 状态。** 这不是正式 SLO、RPO/RTO、容量认证或国产化认证，也没有把测试 fixture 数值表述为实际系统性能。至此，本报告连续推进的顶层开发需求清单剩余 **0 类**；后续新增实测样本或扩充矩阵属于基于该合同的持续集成与评测，不是当前清单中未实现的另一套产品能力。

## 126. 2026-08-19 Proposal/ChangeSet/ActionResult durable artifact authority（开发阶段）

本轮继续推进第 121 节明确保留的 Action runtime 持久化缺口：

- 新增 migration `196_action_artifact_authority` 和 `data_agent/action_artifact_authority.py`。同一 tenant 下以 `proposal`、`change_set`、`action_result` 三类和对应 SHA-256 作为不可变工件身份；重复相同 identity/content 幂等返回，identity 相同但内容漂移返回冲突；
- Proposal 只能保存 `execution_authorized=false` 的建议，ChangeSet 保存 idempotency key 和预期对象变化，ActionResult 保存 PlatformRun correlation、provider outcome、变化比较、receipt/result hash、失败/对账状态。数据库 JSONB 约束会重新检查 tenant 与对应工件 hash，Python 端再做完整 Pydantic sealed model 校验；
- 表启用并强制 RLS，gateway 只有 SELECT 和受控 `SECURITY DEFINER` record 函数执行权限，禁止表直接写入，更新/删除由 immutable trigger 拒绝。该 authority 不创建 ActionRun、Action scheduler 或第二套执行状态，PlatformRun 仍是唯一运行状态权威；
- 增加开发配置 migration catalog 到 `196`，fingerprint 为 `712abbc8fd2e5bbb221166c39e03878e6327d13528d980cd76d4e17eeafc4768`；新增 authority 在本地隔离 PostgreSQL 16 临时数据库中专项 `4 passed`，覆盖三类工件、幂等、内容漂移冲突、RLS、gateway 无表直写和临时库清理；Action runtime 与 migration/profile 联合 `48 passed`。Ruff、格式化和 Python 编译通过。

当前开发阶段可准确声明：**Proposal、ChangeSet、ActionResult 已具备 tenant-bound、append-only、幂等重放和内容漂移冲突的 PostgreSQL durable artifact API，且不旁路既有 PlatformRun。** 仍未宣称所有 Capability 已接入 Action runtime、跨 Provider 全局 exactly-once 或跨存储原子事务；本轮也没有新增外部 endpoint。

## 127. 2026-08-19 受认证语义规划、澄清与证据融合 HTTP API（开发阶段）

本轮继续推进第 122 节保留的 planner 外部调用面，并直接复用既有 `AutomaticSemanticPlanner`、`SemanticPlanExecutor`、`SubjectContext`、`CapabilityRegistry`、`plan_query_route()` 和 governed-query executor：

- 新增 `POST /api/semantic-plans`、`POST /api/semantic-plans/{plan_sha256}/clarifications` 和 `POST /api/semantic-plans/{plan_sha256}/execute`。三个入口分别负责创建计划、提交结构化选项并真实 replan、执行 ready DAG 与返回 citation-verified fusion result，没有复制 planner 状态机或增加第二套节点 executor；
- tenant、subject id/type、roles、trace、invocation surface、planner model binding、proposer、governed-query executor 和计划仓库均由服务端认证上下文与 port resolver 装配。请求采用 `extra=forbid`；客户端伪造 tenant、SubjectContext、binding 或 executor 字段在 resolver/proposer 前返回 `400`；匿名、无 tenant 和无允许角色分别在所有 runtime port 前返回 `401/403`；
- 创建请求只接受显式 deterministic channels、不可变 resource version/content SHA-256 pins 和有上限的节点/通道/工具调用/Token/成本预算。prompt injection/写意图继续在 proposer 前阻断；plan-only 入口不会调用 executor；模型不可用时，无 seed 返回 `not_admitted`，只有单个显式 typed seed 能进入既有 deterministic fallback；
- 计划不由客户端回传后直接执行。开发期 server-owned repository 按 `(tenant_id, plan_sha256)` 保存已封印计划，澄清和执行只按 path hash 读取；跨 tenant 统一表现为 `404`。执行前重新绑定认证 SubjectContext、API surface、planner binding、当前 Capability ID/version/fingerprint、输出 Schema fingerprint、evaluator、purpose、资源 pins 和 deterministic route admission；漂移或非 ready 计划在 executor 前返回 `409`；
- 澄清请求只允许提交 clarification/option 对，确认人由服务端固定为认证 `human:<username>`，精确绑定 request/prior plan；缺项、重复项、未知选项或已经产生 successor 的旧计划不会调用 proposer。successor 记录与新计划在内存 repository 同一临界区提交，并发兄弟 revision 发生冲突而不会同时成为 current。错误响应不返回 resolver、Provider 或下游异常正文，稳定映射为 validation `400`、not found `404`、plan conflict `409`、service unavailable `503`；
- 应用默认开发装配明确为 seed-only：proposer 未连接真实模型时主动不可用，既有 governed-query executor 仍负责节点执行和可选 SPR 安全端口。内存计划仓库只服务当前开发进程，不冒充 durable plan authority。新增 HTTP 专项 `19 passed`；与 planner runtime、governed query/routes/policy 和 Capability registry 联合回归 `89 passed, 1 warning`，warning 为既有 OpenTelemetry 弃用提示；新增文件 Ruff、格式化、Python 编译和 `git diff --check` 通过。

当前开发阶段可准确声明：**语义计划创建、结构化人类澄清/replan 和证据融合执行已经具备受认证、tenant-bound、服务端端口装配的 REST 调用面，负向路径可证明 proposer/executor 零调用。** 仍未接入真实模型 Provider，未新增 MCP planner endpoint，也未将进程内计划仓库表述为 PostgreSQL durable authority；本轮无新增 migration 或 Capability，catalog 保持 `196`，fingerprint 保持 `712abbc8fd2e5bbb221166c39e03878e6327d13528d980cd76d4e17eeafc4768`。原顶层开发需求清单仍为剩余 **0 类**；本节是对已明确保留开发增强项的继续集成。
