# 飞渡本体驱动空间智能底座材料与 GIS Data Agent 综合复核报告

日期：2026-08-14

最近更新：2026-08-18

## 1. 复核范围与结论

本次复核覆盖：

- 《飞渡科技本体驱动产品架构范式与关键技术的范式 V2.1》；
- 《飞渡科技本体驱动空间智能底座-建设任务体系 V3.0》；
- GIS Data Agent 当前源码、不可变本体包、测试与已有验收材料。

总体方向是合理的，但两份材料不能原样作为产品规格或验收依据。它们把产品范式、目标架构、当前实现、客户实施、行业应用和性能愿景混写，并包含概念绝对化、技术边界错误和内部矛盾。

GIS Data Agent 已有较强基础，但尚未完整实现文档蓝图。三个百分比必须分开理解：

| 评估对象 | 当前判断 | 正确含义 |
|---|---:|---|
| 合理需求的基础能力可复用度 | 约 75% | 已有组件和合同中可复用的比例，不代表这些组件已经组成生产闭环 |
| T1-T12 统一产品完成度 | 约 61%-65% | 统一查询、双时态实体、来源身份、精确实例 Link、实体沿革及带耐久重放入口的重庆全数据包增量已形成最小技术闭环；考虑 Action、安全和跨存储一致性的关键权重后下调 |
| 按材料完整蓝图生产就绪度 | 约 30%-35% | 距离真实客户环境中全量数据、全链路安全、SLO、运维和法定业务验收的程度 |

当前适合做的是有边界的样区试点和若干确定性查询/分析闭环，不适合按原文承诺完整生产交付，也不能替代法定审批或业务责任人。

## 2. 文档中正确且应保留的内容

以下内容方向正确，但应改写为可验收的产品合同：

1. 底座与“一张图”分层。底座提供数据、语义、查询、工具和治理合同；客户业务规则、法定流程和专用界面属于上层应用。
2. Object、Link、Action、Function、Interface 可作为产品元模型，但不要求全部存入 RDF，也不意味着本体本身承担事务、权限和工作流。
3. OWL、SHACL、SKOS、RDF 各司其职：语义、公理、形状校验、分类映射和交换投影不能混为一个“万能本体引擎”。
4. 空间计算应交给 PostGIS、GDAL、Rasterio、ArcPy 或其他确定性 GIS 引擎；LLM 负责意图理解、候选计划和结果解释。
5. Proposal Pattern 和人工审批适合高风险动作。只读查询可以自动执行，高风险写入必须经过策略、审批、幂等、事务/补偿和审计。
6. 稳定标识、标准编码、坐标参考、有效时间、记录时间、版本、来源、质量和血缘应进入数据合同。
7. 混合存储方向合理，但应按负载和权威边界引入 PostGIS、RDF/图投影、向量索引和对象存储，不能预设每个项目都必须部署 Neo4j、Milvus 和一组仿 Palantir 微服务。
8. 本体框架和行业实例分离是正确边界；客户规则、客户数据和国产化组合认证不应被算成通用产品已经完成。

## 3. 必须修正的错误、矛盾与高风险表述

### 3.1 明确错误或内部矛盾

| 原文问题 | 判断 | 建议改法 |
|---|---|---|
| Word 文件名为 V2.1，正文仍写 V2.0 | 版本控制错误 | 统一版本、日期、作者、审批状态、文档 ID 和变更记录 |
| 标题称“OAG 替代 RAG”，后文又称“本体与 LLM 互补而非替代” | 内部矛盾 | 改为 Ontology Query、RAG、受控 SQL、指标查询和 GIS 工具按问题类型协作 |
| “LLM 永远不生成 SQL”，同文工具路由又列 SQL 查询 | 内部矛盾且技术边界错误 | 允许 LLM 生成候选计划/SQL，但执行前必须做 schema grounding、AST 只读校验、参数化、权限、预算、超时和审计 |
| “本体不可导出，无开放标准可序列化” | 与文档采用 OWL/RDF/SHACL/SKOS 直接冲突 | 标准发布包、映射、校验报告应按合同导出；内部索引和商业实现可保持专有 |
| PDF 的“语义鸷沟”“鲮麓”“麒麺”“关系库兆底”等 | 明显编辑错误 | 全文术语校对；应为“语义鸿沟”“鲲鹏”“麒麟”“关系库兜底”等 |
| PDF 以核心实体类型数量作为主要阶段指标 | 价值口径不充分 | 改为按能力问题、业务覆盖、约束完整性和查询正确率验收；数量只能作为辅助规模指标 |

### 3.2 技术上不准确或过度承诺

| 原文问题 | 风险 | 正确边界 |
|---|---|---|
| 把 GB/T 40765-2021 直接当成可执行“首选上位本体” | 高 | 可作为建模参考和映射依据，项目仍需形成自己的 T-Box、映射、SHACL 和发布包；标准编号、名称、年份和现行状态应在签约前由标准管理员复核 |
| 网格码 + 不动产单元代码作为普适“一码管地”身份 | 高 | 网格码是空间索引，不是跨时间、尺度、来源都稳定的实体身份；应另设稳定 EntityId，并保留来源 ID、业务码、URI 和网格码 |
| URI/网格码自动支持跨库 JOIN | 高 | URI 只提供标识；还需版本化映射、实体解析、类型/坐标一致性、冲突处理和实际执行计划 |
| OWL-Time、双时态、事件溯源混为一谈 | 高 | 分别定义时间词汇、valid time、transaction time、事件账本、快照、更正和 as-of 查询 |
| “本体中不存在实体就不会幻觉” | 高 | 模型仍可能错读、错连或错误总结；结论必须绑定版本、查询计划、来源和可验证引用 |
| 复杂查询超时后自动简化 | 高 | 只有预注册且证明语义等价的降级可以自动执行；非等价降级必须停止并请求确认 |
| Action 写回/CDC 小于 300ms | 高 | 必须分别定义本地提交、外部回执、CDC 可见性，报告 p50/p95/p99、负载、数据量、网络、重复/丢失、积压和恢复 |
| Action 是绝对“唯一写路径” | 高 | 只能作为目标治理原则；还必须封禁数据库直连、管理员账号、批处理和外部系统旁路，并持续审计 |
| 安全/SHACL 采用“旁路校验而非准入阻塞”作为普遍原则 | 严重 | 低风险数据质量可隔离后入库；授权、密级、目的限制、阻断级 SHACL、高风险审批和审计必须 fail-closed |
| “目的声明快速通道”、审计异步不影响主流程 | 严重 | 目的不能由自由文本自行提权；高风险动作在关键审计不可持久化时必须阻断 |
| OWL 2 DL、任意 SPARQL、图数据库和全量在线推理默认生产可用 | 高 | 应使用有界推理、白名单/类型化查询、资源预算和可重建读投影；是否引入专用图存储取决于证据和规模 |
| Phase 1-3 固定 18-26 周即可形成生产 Agent | 高 | 只有功能罗列，没有数据规模、集成数量、安全等级、国产化组合、测试范围和人员假设，不能作为合同工期 |

## 4. GIS Data Agent 对 T1-T12 的实际支撑度

下表只评价 GIS Data Agent 的通用产品能力。百分比是工程估算，不是具体项目的合同验收结论。

| 任务 | 状态 | 支撑度 | 当前已有 | 主要缺口 |
|---|---|---:|---|---|
| T1 资产盘点与语义差距 | 已具备/受控试点 | 70% | 接入、目录、画像、质量、血缘、Semantic Source | 统一五维评分、持续差距视图、客户全量盘点 |
| T2 上位/领域本体 | 已具备/技术基线 | 80% | 版本化包、OWL/RDF/SHACL/SKOS、哈希、来源处置、能力问题；自然资源本体 2.3.0 已固定为当前开发基线 | 暂无领域专家签署，因此只能标记 `technical_baseline_unreviewed`；在线完整 OWL 2 DL 不具备；来源 warning 待治理 |
| T3 时空数据实体化 | 最小通用合同已实现/受控试点 | 84% | 空间接入、Schema/语义映射、几何/CRS、融合、数据产品版本、稳定 EntityRef、来源身份自然键及有效时间解析；通用 authority 支持每批 1..500 项原子写入，重庆 439 个地块实体和 16 个约束要素实体共 455 个实体/来源绑定已装载并全量重放；合并、拆分、替代及来源身份沿革已通过统一 REST/Capability/MCP 和真实 PostgreSQL 验收；全数据包 sealed plan 已联动实体校正/新增/激活/退役和来源版本证据，并发布耐久 REST/Capability/MCP reconciliation | 新 EntityRef 覆盖既有实体域、复杂多源冲突裁决、任意客户包适配、异步大任务规模验证和规模 SLO |
| T4 时空与业务关系 | 最小通用合同已实现/受控试点 | 88% | 类型化 Link、稳定端点、valid/recorded 双时间轴、撤回/恢复/校正、来源/置信度、租户 RLS、自环和基数门禁；重庆 472 次客户范围命中已确定性展开为 492 次逐要素相交观测并聚合为 486 个稳定 Link，目标以 `layer + BSM` 精确到约束要素；全数据包计划固定先撤回失效 Link，再写实体和来源，最后校正/恢复/新增 Link 并退役消失实体，支持无变化零写入、耐久计划预留和跨 REST/MCP 稳定重放 | 质量抽检、更多关系类型、全局单事务、异步大任务规模验证和规模 SLO |
| T5 时态与生命周期 | 最小通用合同已实现/受控试点 | 72% | 稳定 EntityRef、valid/recorded 双时间轴、append-only 事件、更正链、迟到事件、四类 as-of 查询和生命周期状态机；新增 `N->1` 合并、`1->N` 拆分、`1->1` 替代，原子退役源实体并保存沿革成员、传播证据和 SHA-256 | 更多业务域事件/来源适配、既有域迁移、归档、跨存储投影一致性和规模 SLO |
| T6 图谱与混合存储 | 受控试点 | 约 82% | PostgreSQL 权威、PostGIS、Fuseki RDF、pgvector、S3 对象和 Spark/Iceberg 湖仓投影均已接入统一目标观察、sealed repair plan、plan-bound checkpoint 与 PostgreSQL append-only authority；五类 provider 的 rebuild/delete/checkpoint、自动 authority 串联及 REST/Capability/MCP 均通过隔离真实环境验收；新增按 sealed plan 顺序推进的 federated recovery、PostgreSQL aggregate ledger，以及绑定重庆数据、本体 2.3.0 和源快照的补偿候选方案/只追加权威；对象与湖仓固定重庆客户包 `natural-resource-ontology-customer-demo-v1` 和自然资源本体 2.3.0 | 仍缺实体权限、向量索引/规模性能、五类真实 provider 联动故障、客户规则驱动的变更型自动补偿/对账执行、备份恢复、跨存储容量/SLO 证明 |
| T7 本体引擎与查询 | 已具备/受控试点 | 80% | `semantic.query.execute@4.1.0` 已统一 Ontology、Metric、NL2SQL、GIS、RAG 的类型化路由、版本固定、预算和证据 envelope | 自然语言自动生成类型化计划、跨通道答案融合、授权义务传播和质量评测 |
| T8 业务本体建模框架 | 受控试点 | 60% | 工作台、草稿命令、稳定 URI、append-only 变更、Diff、校验、review | 完整发布/回滚、多人协同、完整 OWL/SHACL 编辑、模板包和 SDK |
| T9 Action 注册与运行时 | 部分具备 | 45% | CapabilitySpec、PlatformRun、Policy、Approval、HITL、幂等、Outbox、审计、专项执行器 | 通用 ActionType、对象/本体绑定、外部回执、补偿/对账和所有写路径收口 |
| T10 安全与治理 | 部分具备 | 45% | RBAC、租户、SubjectContext、Purpose、PolicyDecision、部分字段/审批/审计 | 对象/行/列/空间/时间/目的在所有查询、工具、地图、报告和导出通道闭环 |
| T11 OAG 智能服务 | 受控试点 | 65% | 已形成“问题-确定性路由-版本资源-Policy-预算-证据”的只读查询合同；RAG 仅准入租户绑定、内容寻址的新文档 | 自动计划生成与澄清、跨通道答案融合、Proposal/Action 总线、跨通道质量/成本/延迟评测 |
| T12 标准和部署适配 | 产品基础 + 外部依赖 | 40% | 标准平台、开放格式、容器/Kubernetes、离线接入基础 | 国产 CPU/OS/数据库/中间件仍需逐组合认证；部署矩阵尚不完整 |

简单平均约 67%。T3/T4/T5 的身份、精确关系、时间、沿革和全数据包增量权威均已有真实 PostgreSQL 证据；由于 T9、T10 和跨存储一致性仍决定业务闭环是否可信，统一产品完成度仍应按 61%-65% 管理。

## 5. 两份飞渡文档中仍未完整实现的合理需求

答案是“有”，而且主要剩余项不是再增加几个工具，而是把已有组件收敛为可证明的生产闭环。

| 合理需求 | 当前状态 | 未实现或未证明的部分 | 建议优先级 |
|---|---|---|---|
| 双时态对象与生命周期 | 最小通用合同及 REST/Capability/MCP 已实现 | 核心权威已具备稳定 EntityRef、双时间轴、不可变更正、迟到事件、四类查询、原子批量；合并、拆分、替代、来源身份沿革和 Link 传播已通过真实数据库验收；仍缺既有实体域迁移、复杂冲突裁决、归档、规模 SLO 与跨存储投影闭环 | P1 |
| 实例关系治理 | 最小通用合同及 REST/Capability/MCP 已实现/重庆技术基线 | Link 的类型、端点、版本、本体包、双时间轴、撤回/恢复/校正、来源、置信度、租户、自环、基数、原子批量及沿革传播已有权威；重庆固定基线已精确到约束要素，并完成实体/来源/Link 联动的全数据包 sealed-plan 增量及耐久 REST/MCP 重放；仍缺质量评测、更多关系类型、全局单事务、异步大任务和规模 SLO | P1 |
| 全执行面安全闭环 | 部分实现 | Subject/Purpose/Policy 已有，尚未证明行、列、空间、时间和目的限制一致传播到缓存、地图、报告、下载、MCP 与 RAG | P0 |
| 通用 Proposal/Action 运行时 | 部分实现 | 缺统一 ActionType、本体对象绑定、外部副作用回执、补偿、对账，以及所有写路径收口证明 | P0 |
| 跨存储一致性 | PostGIS、pgvector、RDF、对象存储与湖仓五类执行面已实现，生产一致性待完成 | 已具备 source/target/checkpoint 三方对账、漂移 fail-closed、sealed rebuild/delete/checkpoint plan、计划绑定回执、append-only PostgreSQL history/current authority、租户 RLS、CAS 和幂等冲突拒绝；五类 provider 均只接受部署侧显式注册目标，RDF 固定自然资源本体 2.3.0，对象与湖仓固定重庆客户包，并分别绑定 S3 `VersionId`/delete marker 与 Iceberg snapshot；已有 federated coordinator、aggregate ledger、补偿候选方案和方案只追加权威；尚缺客户业务规则、变更型补偿自动选择/执行、备份恢复、真实多存储端到端故障注入和容量/SLO | P1 |
| 自动语义计划与跨通道融合 | 部分实现 | 五通道确定性执行已接通，但自然语言到类型化计划的自动生成/澄清、跨通道答案合并和冲突裁决尚未闭环 | P1 |
| 本体协作发布工作台 | 部分实现 | 草稿、Diff、校验已有，完整多人协同、审批发布、回滚、模板/SDK 和领域签署仍不完整 | P1 |
| 有界推理与规则运行治理 | 部分实现 | 已有 OWL-RL/SHACL 基础，尚缺按规则集的资源预算、增量推理、解释链、冲突处置和规模 SLO | P1 |
| 可观测性、评测与 SLO | 部分实现 | 缺统一问题集上的正确率、引用率、越权率、成本、p50/p95/p99、故障恢复与容量基线 | P1 |
| 部署组合认证 | 外部依赖 | 容器/Kubernetes 基础已有，但具体 CPU、OS、数据库、中间件和模型服务组合仍需逐项认证 | P2 |

其中统一受治理查询、双时态实体和实例 Link 的缺口已缩小：Ontology、Metric、NL2SQL、GIS 和 RAG 已共享同一请求、路由、Policy、预算和证据合同；实体、来源、Link、合并/拆分/替代沿革及重庆全数据包增量也已形成追加式技术闭环。但这不代表既有实体域迁移、任意客户包自动适配、复杂冲突裁决、Action、全执行面安全、跨存储一致性和生产规模已经完成。

## 6. 当前可直接复用、只能试点和不能支撑的边界

### 6.1 可直接进入产品基线的基础能力

- 数据目录、受治理接入、基本画像、质量和血缘框架；
- PostGIS 的确定性空间查询与基础算法；
- 受控 NL2Semantic2SQL 的 schema grounding、只读校验、预算和执行边界；
- 类型化/白名单本体查询和不可变本体包回退；
- `semantic.query.execute@4.1.0` 的五通道类型化路由、资源版本固定、预算和证据校验；
- 文档知识库、向量检索和 GraphRAG 的基础能力；
- 追加式双时态实体权威的核心合同：稳定 EntityRef、双时间轴、四类查询、更正链、生命周期状态机和删除墓碑；
- 来源身份和实例 Link 权威的核心合同：自然键到 EntityRef、固定本体包、类型化端点、撤回/恢复/校正、基数门禁、RLS 和最小权限；
- 重庆全数据包增量合同：sealed plan/receipt、实体校正/新增/激活/退役、来源版本证据、Link 撤回/校正/恢复/新增、分阶段幂等续跑和漂移 fail-closed；
- 跨存储 checkpoint 控制面合同：source/target/checkpoint 三方判断、sealed repair plan、计划绑定回执和 PostgreSQL append-only authority；写入强制首版为 1、严格 CAS/逐版本推进、租户 RLS 和网关无表直写；
- PostGIS、pgvector 与 RDF 受控投影执行合同：目标由部署侧显式注册，重建/删除/checkpoint 只接受 sealed plan，回执自动写入 checkpoint authority；pgvector 请求不能覆盖 schema、table 或 embedding dimension，RDF 请求不能覆盖本体包、Graph Store 端点、凭据、图标识或 RDF payload；
- CapabilitySpec、PlatformRun、PolicyDecision、Approval、审计等控制合同；
- 地图、GeoJSON、统计和报告等结果呈现基础。

### 6.2 只能按受控试点声明

- 自然资源本体 2.3.0：技术质量门通过且包已激活，当前作为不阻塞开发的 `technical_baseline_unreviewed` 基线；暂无专家签署，必须把“技术合格”和“领域批准”分开展示；
- 重庆客户实体/关系基线：固定客户 GeoJSON 和自然资源本体 2.3.0 的哈希，生成 439 个地块身份和 16 个 `layer + BSM` 约束要素身份；472 次客户范围命中确定性展开为 492 次逐要素相交观测并聚合为 486 个唯一 Link。452 次命中对应一个约束要素，20 次命中对应两个要素；双要素命中保留客户范围总面积但不伪造逐要素面积分配；
- 多步 GIS 语义工作流：两套注册模板已有模板感知的 Proposal、Preview、版本绑定 DAG、参数化只读 SQL、GeoJSON/统计/证据输出，并在隔离的 PostGIS 16/PostGIS 3.4 上通过两模板与 API 闭环；真实业务数据和生产负载性能仍未验收，现状为“受控试点”；
- 受治理 RAG：新入库文档已有租户、所有者、原文 SHA-256、内容寻址版本、分块 SHA-256 和稳定定位符；历史未版本化文档会 fail-closed，跨存储删除传播和外部不可变版本注册仍未完成；
- pgvector 投影修复：已具备受控结构化行、固定维度、事务 staging 替换、漂移拒绝、幂等重放、append-only checkpoint 和统一 REST/Capability/MCP；目前只在临时 PostgreSQL + pgvector 隔离环境验证，尚无向量索引参数、召回质量、并发容量、备份恢复或客户生产拓扑证明；
- RDF 投影修复：只接受部署注册的自然资源本体 2.3.0 不可变包和 Fuseki Graph Store 目标，已验证 537,245 条 triples 的 rebuild/checkpoint/delete、漂移拒绝、幂等重放和 append-only checkpoint；provider HTTP 写入与 PostgreSQL authority 不是分布式原子事务，且尚无客户生产拓扑、并发容量、备份恢复或 SLO 证明；
- 双时态实体：Python 权威与 PostgreSQL 迁移已通过四类查询、迟到事件、更正、墓碑、RLS、直接写入拒绝和批内原子回滚测试；重庆 455 个实体、455 个来源绑定和 486 个精确 Link 已通过 7 个批次完整装载并全量重放；合并、拆分、替代、来源身份重定向及 Link 沿革传播已接入 REST/Capability/MCP；全数据包增量又通过真实数据库验证实体校正、新增、退役、来源版本和 Link 撤回/新增联动；但既有实体域和生产负载仍未完成，因此只能声明最小技术合同；
- 高风险 Action：基础合同和专项执行器较强，但尚非覆盖所有业务域和外部写路径的通用运行时；
- 目的/资源策略：已有强类型合同和部分执行面，尚未证明所有查询、地图、报告、下载、缓存和工具一致执行。

### 6.3 当前不能作为现成能力承诺

- 覆盖既有实体域迁移、复杂多源冲突裁决、归档、跨存储投影和生产规模的完整双时态实体/关系平台；
- 把重庆客户约束命中或技术计算得到的逐要素 Link 自动提升为法定结论；
- 任意本体导入即用、完整在线 OWL 2 DL 推理或无界 SPARQL；
- 全通道、全对象、行、列、空间、时间、目的动态授权闭环；
- 通用 Action/Proposal 的事务、外部副作用、补偿、对账和唯一写路径；
- 跨 PostGIS、RDF/图、向量库、对象存储的生产一致性和规模 SLO；
- 固定小于 300ms 的端到端 CDC；
- 全套国产 CPU/OS/数据库/中间件组合兼容；
- 任一具体业务域的全量真实数据、权威规则、知识库质量、模型效果和生产环境；
- 代替法定审批、规划审查、执法认定或自然资源业务责任人。

## 7. 后续改进路线与退出门

### P0：先恢复可信基线

1. 继续做 GIS 工作流生产负载验收和前端 E2E：本轮已补齐 `template_id/group_by` 构造、按模板校验 DAG、算法注册表测试、规划区模板 SQL/结果契约，完成前端生产构建，并通过隔离的真实 PostGIS 两模板/API 验收；真实业务数据、浏览器 E2E 和性能仍是退出门。
2. 将本体运行时依赖纳入 CI 可复现环境：本轮已按锁文件安装 `rdflib/pyshacl/owlrl` 并通过运行时专项测试；同时固定 `segregation==2.5.3`，将锁文件中的 `numba/llvmlite` 更新到兼容 Python 3.11 的版本，`uv sync --all-extras --frozen` 已通过。下一步是把相同命令纳入 CI 并运行更宽的回归集。
3. 冻结 T1-T12 验收矩阵、客户前置条件、问题集、数据字典、环境清单、证据模板和停止条件。
4. 把本体“活动指针、技术质量门、领域批准、来源 warning”拆成四个独立状态；未获领域签署不得显示为已批准。
5. 统一所有能力状态为 `planned / in_progress / verified / blocked`，只有源码、真实后端、测试、运行产物和 owner 齐全才可标 `verified`。

退出门：相关专项回归清零；本体 full suite 可重复运行；每项能力声明可链接到版本化证据；缺失的业务数据和外部前提不被伪装成通用产品已交付。

### P1：形成最小生产闭环

1. 在已完成的统一 GovernedQuery 五通道合同上补自然语言到类型化计划的受控生成、澄清流程、跨通道融合和固定问题集评测；不得绕过现有确定性准入。
2. 建立通用 ActionType/Proposal 合同，精确绑定 CapabilitySpec、输入快照、Evidence、Policy、Approval、ChangeSet、幂等键、回执和补偿。
3. 统一 Subject-Purpose-Resource 策略，在查询、上下文、缓存、地图、报告、下载、MCP 和 Action 上实施相同义务；建设负向权限矩阵。
4. 在已完成的双时态对象、来源身份、精确实例 Link、关系及全数据包增量计划、合并/拆分/替代沿革、通用原子批量、REST/Capability/MCP、五类 provider、federated recovery/aggregate ledger 和补偿候选方案之上，补既有实体域迁移、复杂冲突裁决、客户规则驱动的变更型补偿执行、真实联动故障、归档、备份恢复与规模 SLO；不得绕过追加式权威和租户边界。
5. 以已固定的重庆客户数据为样区基线，补字段/代码/SRID/主键/几何质量全量报告、知识库条款引用和一个只读辅助预审闭环；不得等待专家签署才开始技术工作，也不得把技术结果表述为法定审批。

退出门：未授权读取/写入为 0；非等价降级必须确认；高风险动作未经审批为 0；查询和结果可按固定版本重放；更正不覆盖历史。

### P2：再做行业应用与规模化

1. 选择一个辅助审批或选址场景，完成 Proposal、人工复核、确定性 GIS、证据、报告和审计的端到端闭环。
2. 在现有两套受控 GIS 模板通过真实环境验收后增加第三个模板，再考虑通用规划器；自由代码探索必须独立沙箱、只读、限资源、静态检查和人工确认。
3. 按实际需求引入 RDF/图、对象存储和湖仓投影，并为现有 pgvector 增加索引/召回/容量验收；全部建立 checkpoint、重建、备份恢复和一致性对账，不按架构图先行堆数据库。
4. 在真实负载下分别认证查询、Action、外部回执和 CDC 的 p50/p95/p99、吞吐、错误率、积压和恢复。
5. 国产化按 CPU + OS + 数据库 + 中间件 + 模型服务的具体组合建立认证矩阵，不做泛化承诺。

退出门：至少一个行业闭环在真实授权数据和目标环境中通过；SLO 有负载与分位数；备份恢复、故障注入、升级回滚和运维移交完成。

## 8. 2026-08-14 复核证据

### 8.1 本体包

`natural_resource_one_map/2.3.0` 的不可变 manifest 已核实：

- 246 个领域类；
- 5,284 个概念；
- 6,588 个关系；
- 537,245 条 RDF triples；
- 8/8 competency questions 通过；
- SHACL 和有界 OWL-RL 质量门通过，不可满足命名类为 0；
- 2,397 条来源质量 warning；
- 完整性状态仍为 `open_pending_expert_review`。

这些数字证明本体不是空壳，但类数和三元组数不等于业务正确性、领域批准或生产就绪。

### 8.2 测试复跑

稳定治理/知识库/安全组：

```text
110 passed, 4 skipped
```

受治理查询/本体查询组：

```text
194 passed
```

GIS 分析与多步工作流组（含两模板单元、Proposal、路由和可选 PostGIS 集成）：

```text
57 passed
```

本轮修复了 8 个失败：`GISWorkflowIntent` 现在从提案携带 `template_id/group_by`；计划按模板声明的来源角色、必需字段和节点序列校验；规划区/现状用地模板有独立的 PostGIS CTE、统计模型和地图结果；算法注册表测试改为随枚举推导。随后在临时 `postgis/postgis:16-3.4` 容器中完成第一模板、第二模板和 Proposal→Preview→Execute API 三项真实数据库验收，结果为 `3 passed`；临时容器已停止并自动移除。

本体运行时专项：

```text
10 passed
```

本轮按 `uv.lock` 安装了 `rdflib==7.6.0`、`pyshacl==0.40.1`、`owlrl==7.6.2`，`data_agent/test_ontology_runtime.py` 已通过。首次执行 `uv sync --extra full --extra dev --frozen` 暴露 `segregation 2.5.4 -> numba 0.53.1 -> llvmlite 0.36.0` 与 Python 3.11 不兼容；将 `full` 固定到仓库 `requirements.txt` 已采用的 `segregation==2.5.3`，并把锁文件更新为 `numba==0.67.0`、`llvmlite==0.49.0` 后，`uv sync --all-extras --frozen` 通过。这证明安装链已恢复，不等于全仓测试或 PySAL 业务效果已验收。

前端：`frontend/npm run build` 通过；构建仍报告原项目的大 chunk 和 `spawn` 浏览器外部化警告。真实 PostGIS 集成已在本机隔离容器执行，浏览器 E2E 尚未执行。

### 8.3 统一查询与受治理 RAG 增量

本轮将统一查询能力升级为 `semantic.query.execute@4.1.0`：

- Ontology、Metric、NL2SQL、GIS、RAG 均使用同一严格输入/输出、服务端租户身份、角色/目的策略、资源版本、预算和证据 envelope；
- 新入库知识库文档记录租户、所有者、原文 SHA-256 和 `sha256-<digest>` 版本；每个分块记录独立 SHA-256 与 `kb:<kb_id>/documents/<doc_id>/chunks/<index>` 定位符；
- RAG 仅检索显式固定的文档版本，执行前重新计算原文和分块摘要；跨用户、跨租户、历史无版本、摘要不匹配、定位符不匹配和 embedding 不可用均 fail-closed；
- 修复显式传入无权访问的数字 `kb_id` 后退化为“搜索全部可访问知识库”的问题；补齐原先缺失的 `search_knowledge_base` 多知识库 API/GraphRAG 兼容入口；
- 补充 `geopy` 直接依赖并更新锁文件，MCP 能力入口可在可复现环境中导入。

相关专项回归结果：

```text
197 passed, 2 warnings
```

覆盖受治理 RAG、统一查询、知识库、GraphRAG、能力注册、HTTP/MCP 契约、GIS 和 NL2SQL。另一次包含上下文引擎的扩展回归为 `185 passed, 1 failed`；唯一失败是既有测试仍断言 6 个 provider，而当前源码已注册 7 个，属于独立的陈旧断言，不是本轮行为回归。

### 8.4 双时态实体权威增量

本轮新增 `gda.temporal-entity-assertion.v1` 和 `gda.temporal-entity-snapshot.v1`：

- 以稳定 `gda://{tenant}/entity/{id}` 为身份，独立保存业务有效时间 `valid_from/valid_to` 和系统知识时间 `recorded_at`；
- 事件表只追加，直接 UPDATE/DELETE 由触发器拒绝；更正通过 `supersedes_assertion_id` 建链，不覆盖原事实；
- 支持 `current`、`valid_at`、`known_at`、`as_of` 四种确定性查询，`known_at` 同时固定业务与知识时间；
- 生命周期为 `draft/active/suspended/retired/deleted`，迟到事件必须同时满足前驱和后继转换；删除以可查询墓碑表达；
- 网关只获表 SELECT 和安全写函数 EXECUTE，写函数强制租户上下文、稳定对象类型/owner、排序唯一来源、幂等摘要和并发锁。

专项合同测试结果：

```text
15 passed
```

另在临时 `postgres:16-alpine` 中执行 092、094、160 三个迁移，并使用非超级用户、`NOINHERIT` 网关成员完成真实数据库验收。结果证明：幂等重放返回同一 assertion；破坏后继状态的迟到事件被拒绝；更正前后 `as_of` 结果分别为原值和修正值；更正时间严格晚于目标；直接表 INSERT 被拒绝。临时容器已停止并自动移除。

### 8.5 重庆来源身份与实例 Link 权威增量

本轮以重庆客户数据和自然资源本体 2.3.0 继续推进，不等待专家签署：

- 客户输入固定为 `heping_changed_parcels.geojson` 和 `heping_constraints.geojson`，执行前校验客户 manifest 中的文件 SHA-256；本体固定为 `natural-resource-one-map:2.3.0:587915868b1221af`，内容 SHA-256 为 `587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019`，并校验包内全部工件哈希；
- 初始 v1 将 445 条变化地块记录解析为 439 个稳定地块身份，并按 `layer + sorted(names)` 将 472 次客户约束命中聚合为 466 个 Link；该聚合目标随后已由 8.9 节的精确要素 v2 取代；
- 新增来源身份自然键、来源版本、本体类 URI、类型化 Link、双时态撤回/恢复/校正、幂等摘要、自环限制、最大入度/出度、强制 RLS 和不可变触发器；
- 状态固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。这允许技术工作继续，但不表示专家批准、生产认证或法定审批结论。

专项合同测试结果：

```text
13 passed
```

另在空的临时 PostgreSQL 16 中顺序执行 092、094、160、161，并使用非超级用户、`NOINHERIT` 网关成员完成真实验收。幂等来源绑定和 Link 重放返回同一 ID；同一来源自然键映射不同实体被拒绝；端点类型和最大出度违规被拒绝；撤回、恢复和校正后的四类时间查询结果正确；跨租户查询为 0 行；直接 INSERT、UPDATE、DELETE 均返回 SQLSTATE `42501`。该阶段迁移目录为 161 项，catalog fingerprint 为 `35e2082d26150ac674d0f7e90232bfb5f92f4f0ecfea3400e7ef155104110683`，随后已由批量迁移 162 更新。

### 8.6 重庆固定基线完整装载与重放增量

本轮补齐了此前“只有确定性草案、尚未完整持久化”和“只能逐条事务写入”的缺口：

- 新增 `data_agent/migrations/162_entity_authority_batch_ingest.sql`，为实体断言、来源绑定、Link 类型和 Link 断言提供四个通用 JSONB 批量安全函数；每批限制 1..500 项，复用现有单条 authority 校验，任一项失败则该批全部回滚，网关仍只有 EXECUTE 权限；
- `data_agent/temporal_entity_authority.py` 和 `data_agent/entity_link_authority.py` 新增四类强类型 Python 批量方法；初始 v1 将 1,357 个逻辑写入压缩为 7 个原子批次，随后精确要素 v2 更新为 1,397 个逻辑写入和 1,396 个幂等键，批次数仍为 7；
- 初始不可变 `gda.chongqing-entity-link-load-receipt.v1` 已由 v2 取代；v2 额外封存约束要素数量、客户范围观测、精确相交观测、精度碎片排除数量和精度策略；
- 新增装载前数量/租户/唯一性门禁，以及批量上限、批内回滚、装载顺序、回执防篡改、全量重放、非幂等返回拒绝、中断后续跑和租户不匹配测试；相关单元回归为 `36 passed`；
- 在空的 `postgres:16-alpine` 中执行 092、094、160、161、162，以非超级用户、`NOINHERIT` 网关成员验证冲突批次整批回滚为 0 条残留；重庆首次装载和完整重放各 7 个批次，集成测试为 `1 passed`；
- v1 数据库独立核对结果为 `445/445/445/445/1/466/466`；当前 v2 已更新为 `455/455/455/455/1/486/486`。全量重放后数量不增加，472 次客户范围观测和 492 次逐要素相交观测保存在 486 个唯一 Link 的 evidence 中。
- 该阶段迁移目录为 162 项，最新迁移为 `162_entity_authority_batch_ingest`，catalog fingerprint 为 `2c54bb058cdb7b2953bf7c7d2e5dfbb855d79572cf95a074ca9d54277d863177`，两个开发部署 profile 已同步；随后已由沿革迁移 164 更新。

这使“重庆客户数据能否真实落入统一实体/关系权威”以及“authority 是否支持通用有界原子批量”均推进为已技术验证。该阶段之后已继续补齐对外 REST/Capability/MCP、实体沿革、逐约束要素精确关联、关系增量和实体/来源/Link 联动的全数据包增量；当前仍没有异步大任务、既有实体域迁移、任意客户包自动适配、并发容量或生产 SLO；本体仍为 `technical_baseline_unreviewed`，结果仍仅限辅助预审。

### 8.7 实体与 Link 批量 REST/MCP/Capability 增量

本轮将已经通过 PostgreSQL 验收的四类 authority 批量能力接入统一平台入口：

- 新增 `gda.entity-authority-batch-request.v1` 和 `gda.entity-authority-batch-response.v1`，由 `batch_type` 选择实体断言、来源身份绑定、Link 类型或 Link 断言；每个 item 仍使用原 authority 的强类型草案，禁止混合类型和混合租户；
- 新增 `entity.authority.batch.ingest@1.0.0`，REST 入口为 `POST /api/platform/v1/entity-authority/batches`，MCP 工具为 `ingest_entity_authority_batch`，最新 CapabilitySpec 指纹为 `8b8890fc9c2a7ce4db2558c0de3db2288b95c54764f9b7813783c37d08280d7a`；API/SDK/Agent/MCP 均标记为 `implemented`；
- 请求最多 5,000 个逻辑 item，按 `batch_size=1..500` 分块；批内继续由数据库 authority 保证原子性，跨批继续依靠 item 幂等键续跑，不伪装为跨批单事务；
- 网关只接受 `admin` 和 `platform_operator`，以认证主体租户为准，拒绝 body 租户冒充、`recorded_by/created_by` 冒充、Capability 指纹漂移及 Header/Body 幂等键不一致；路由不具备直接写表代码，只调用既有四个 Python authority 批量方法；
- MCP 工具从 `MCP_TENANT/MCP_ROLE/MCP_USER` 会话上下文取得租户、角色和 Agent 身份，拒绝租户/角色/身份冒充，并复用同一四类 authority 执行器；
- 响应返回逻辑操作数、批次数、四类计数、请求 SHA-256、authority 状态指纹、`authority_idempotency_enforced`，并固定携带 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。

平台网关、实体/Link authority、重庆 loader、REST/MCP/Capability 及能力注册相关回归结果：

```text
182 passed
```

另在一次性 `postgres:16-alpine` 临时数据库中，以非超级用户网关角色通过 REST 和 MCP 入口各重放四类重庆 authority item，真实验收为 `1 passed`；八次调用的状态指纹稳定，既有表计数不增加。临时容器和验收数据已删除。

因此，“缺少 authority 批量 REST/MCP/Capability”不再是剩余项。沿革、逐约束几何要素精确关联、关系 evidence 更新和全数据包增量也已在后续阶段补齐；全数据包 reconciliation 专用 REST/Capability/MCP 及耐久重放见 8.12。该阶段仍未完成异步大任务、既有实体域迁移与复杂冲突裁决、任意客户包适配、跨存储 checkpoint、全执行面授权和生产容量/SLO；其中 checkpoint PostgreSQL 权威已由后续 8.19 补齐，provider 执行和多存储验收仍未完成。该接口没有改变领域审定状态，也不能把重庆客户命中结果解释为法定审批结论。

### 8.8 实体合并、拆分、替代及 Link 沿革传播增量

本轮在既有双时态实体、来源身份和实例 Link 权威上补齐了通用沿革事务：

- 新增 `data_agent/entity_lineage_authority.py` 与 `data_agent/migrations/164_entity_lineage_authority.sql`，支持 `N -> 1` 合并、`1 -> N` 拆分和 `1 -> 1` 替代；迁移 163 已用于灌溉世界模型，因此本能力使用迁移 164；
- 一笔数据库事务会为全部源实体追加 `retired` 断言，撤回所有与源实体相连的有效 Link，按显式分配创建、去重或仅撤回新 Link，追加全部有效来源身份的重定向，并保存沿革事件、成员、传播证据和 SHA-256；Link 端点和来源自然键均不原地改绑；
- 拆分不会把旧 Link 自动广播到所有目标。每条有效旧 Link 和每个当前解析到源实体的来源身份必须逐项分配；遗漏、类型错误、自环、入度/出度、重复 Link 或有效时间冲突都会 fail-closed，并使整笔事务回滚；
- 新增 `entity.lineage.record@1.0.0`，CapabilitySpec 指纹为 `3bfe4b11a5f58c70bdea0f21252cb5ba79c6334cb3e4b80be7bba642503ef1aa`；REST 入口为 `POST /api/platform/v1/entity-authority/lineage-events`，MCP 工具为 `record_entity_lineage_event`，该阶段 MCP 工具总数为 52；
- 相关扩大回归为 `307 passed`；真实 PostgreSQL 16 联合验收为 `2 passed`，覆盖合并、显式单目标拆分、替代、REST/MCP 幂等重放、来源身份按有效时间解析、等价 Link 去重、遗漏分配失败关闭，以及在部分写入后发生重复新 Link 冲突时整笔回滚；当时重庆 v1 的 1,357 个逻辑写入和完整重放未回归，当前 v2 的 1,397 个逻辑写入另见 8.9 节；
- 该阶段迁移序列推进至 164，最新迁移为 `164_entity_lineage_authority`，两个开发部署 profile 的 Catalog fingerprint 已同步为 `73168e1765901e4e0343f15caf0b5f78607d83c929c129cb0c584744d91f63b9`；后续 reconciliation 耐久账本使用迁移 166。

该增量关闭了两份飞渡材料中“实体合并、拆分、替代及关系沿革传播没有通用实现”的缺口，但只证明受控技术合同和真实数据库事务语义。自然资源本体仍为 `technical_baseline_unreviewed`，沿革结果仍是 `assisted_precheck_not_for_production_decision`；没有专家审定不会阻塞技术推进，也不能被解释为领域批准或法定业务结论。

### 8.9 重庆约束关系精确到具体几何要素增量

本轮以精确要素基线 v2 取代 `layer + sorted(names)` 聚合目标，关闭“客户约束关系尚未精确到具体几何要素”的缺口：

- `gda.chongqing-entity-link-baseline.v2` 为 16 个约束几何要素全部注册稳定实体，约束自然键固定为 `layer + BSM`，对象类型为 `natural_resource.constraint_feature`；每个实体绑定来源要素索引、名称、几何类型/边界/几何 SHA-256、本体类 URI 和不可变客户包版本；
- 445 条地块记录对应 439 个稳定地块身份。472 次客户范围命中可确定性展开为 492 次正面积逐要素相交观测，聚合为 486 个稳定 `geosparql:sfIntersects` Link；452 次客户命中对应一个要素，20 次对应两个要素，实际 Link 涉及 5 个约束要素；
- 双要素命中只保存客户范围总面积，不伪造逐要素面积拆分。每条 observation 同时保存地块/约束/相交几何 SHA-256、来源记录和命中索引、候选要素集合、source CRS 相交面积、Shapely 版本及精度策略；
- 精度门固定为 `positive_intersection_area_gt_1e-15_source_crs_units`。唯一约 `2.9e-11` 公顷的浮点边界碎片不在客户证据中，显式记录为 1 个 excluded precision sliver，不提升为 Link；
- 构建器对缺失/重复 BSM、非法或非面几何、客户命中无法映射、一个精确相交映射多个客户 hit，以及无客户证据的正面积相交全部 fail-closed；约束几何即使同步修改 manifest SHA，也会因客户证据不一致而拒绝构建；
- loader v2 以 7 个批内原子批次写入 455 个实体、455 个来源绑定、1 个 Link 类型和 486 个 Link 断言，共 1,397 个 authority 操作、1,396 个幂等键；装载回执封存 472/492 两级观测、精度策略、状态指纹和回执 SHA-256；
- 精确基线、loader、失败恢复、批量 REST/MCP 合同的聚焦回归为 `32 passed`，Ruff 通过；一次性 PostgreSQL 16 真实验收为 `1 passed`，确认冲突批次整批回滚、非超级用户完成首次装载和完整重放、REST/MCP 指纹稳定，数据库计数为 `455/455/455/455/1/486/486`。临时容器已删除。

这项实现证明固定重庆数据包中的客户范围命中可被可复现地细化为具体约束几何要素，不能外推为任意客户数据自动适配，也不能把技术相交结果解释为领域批准、法定审批或行政决定。本体状态继续保持 `technical_baseline_unreviewed`，用途继续保持 `assisted_precheck_not_for_production_decision`。

### 8.10 重庆精确 Link 增量重算与 evidence 更新增量

本轮在精确要素 v2 之上新增关系级 append-only reconciliation，不原地覆盖 Link 或 evidence：

- 新增 `data_agent/chongqing_entity_link_reconciliation.py`，将前一基线、目标基线、当前 authority 断言和生效时间编译为不可变 `gda.chongqing-link-reconciliation-plan.v1`；计划封存前后基线 SHA-256、authority 输入状态 SHA-256、四类草案、无变化 Link 和自身 SHA-256；
- 同一稳定 Link 的 attributes、source versions、confidence 或 evidence 变化编译为 `correction` 并显式 `supersedes` 当前断言；目标基线缺失的 Link 编译为 `active -> retracted`，历史已撤回但重新出现的 Link 编译为恢复 transition，新 Link 编译为 initial；完全一致的 Link 不产生写入；
- 执行顺序固定为撤回、校正、恢复、新增，避免新增先触发基数门禁；每阶段按 1..500 项批内原子写入，跨批依靠由动作、Link、前态、目标态和生效时间共同派生的幂等键续跑；`gda.chongqing-link-reconciliation-receipt.v1` 封存计数、批次、authority 结果状态、记录时间窗和回执 SHA-256；
- 实体引用/类型集合、LinkType、稳定端点或 owner 变化会在任何写入前 fail-closed，明确要求先完成实体迁移；这避免关系增量掩盖实体属性、来源身份或对象生命周期变化；
- 单元测试覆盖 correction、retraction、restoration、addition 同时出现、零变化零写入、整份计划幂等重放、计划防篡改、authority 覆盖不全和实体集合漂移，专项为 `5 passed`；与基线、loader、Link authority 及批量入口联合回归为 `37 passed`，Ruff 通过；
- 一次性 PostgreSQL 16 真实验收先完整装载 486 个 Link，再追加 1 条 evidence correction、1 条 retraction 和 1 条 restoration，并分别完整重放计划；Link identity 保持 486，append-only assertion 从 486 增至 489，校正历史保留原证据，撤回/恢复历史为 `active -> retracted -> active`。真实验收 `1 passed`，临时容器已删除。

这关闭了“固定实体集合内没有关系增量重算/evidence 更新合同”的缺口。本阶段当时尚未覆盖实体属性/几何、来源版本绑定和实体新增/删除联动，后续 8.11 已补齐该全数据包技术合同，8.12 又发布专用 REST/Capability/MCP。状态和用途边界保持不变。

### 8.11 重庆实体、来源与 Link 全数据包增量

本轮把关系级 reconciliation 与双时态实体、来源身份权威联动，关闭“固定重庆数据包无法整体增量”的剩余技术缺口：

- 新增 `data_agent/chongqing_data_package_reconciliation.py`，把前后 `gda.chongqing-entity-link-baseline.v2`、实体/来源/Link 当前权威状态和生效时间编译为不可变 `gda.chongqing-data-package-reconciliation-plan.v1`；计划封存前后基线、三类 authority 输入状态、全部增量草案和自身 SHA-256；
- 支持实体 attributes/geometry 摘要/source versions correction、新实体 initial、`draft/suspended -> active`、`active/suspended -> retired`，以及新增来源身份和既有来源 identity 的新版本 evidence；已退役/删除实体重新出现、稳定实体类型或 owner 变化、来源自然键或实体映射变化均在写入前 fail-closed，必须走显式 lineage migration；
- 执行顺序固定为：撤回失效 Link，校正/新增/激活实体，追加来源绑定证据，校正/恢复/新增 Link，最后退役消失实体。每个非空阶段按 1..500 项批内原子写入，跨阶段依靠内容寻址幂等键续跑；这不是覆盖整份数据包的单一数据库事务；
- `gda.chongqing-data-package-reconciliation-receipt.v1` 精确封存九类阶段计数和批次数、前后基线 SHA-256、三类 authority 输入状态、三类输出状态、记录时间窗及自身 SHA-256；整份计划重放必须返回相同权威状态和记录时间；
- 单元专项覆盖实体校正/新增/`draft|suspended -> active`/退役、来源新增和新版本、Link 撤回/校正/恢复/新增、写入次序、零变化零写入、完整重放、防篡改、自然键/映射漂移和终态实体重现，共 `7 passed`；来源 binding history/双时间解析另有 2 个新增测试；相关联合回归为 `49 passed, 1 skipped`，Ruff 通过；
- 一次性 PostgreSQL 16 真实验收在完整重庆基线上执行 7 个增量操作和 6 个非空批次并完整重放。最终实体身份/断言为 `456/458`，来源身份/证据为 `456/457`，Link 身份/断言为 `487/491`；其中 Link 断言起点已包含 8.10 的 correction/retraction/restoration 三条历史。真实验收 `1 passed`，一次性容器及其验收数据已删除。

因此，实体/来源变化联动的全数据包增量不再是剩余需求。该阶段尚无专用入口，后续 8.12 已补齐固定重庆合同的 REST/Capability/MCP 和耐久重放。剩余边界是：尚未提供任意客户数据包自动适配；跨阶段不是全局单事务，尚无异步任务、并发容量、系统化故障注入和生产 SLO。来源 identity 和历史 binding 不原地删除，实体 lifecycle 与 Link retraction 决定当前有效状态。所有输出仍固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，技术相交或增量成功不等于领域批准、法定审批或行政决定。

### 8.12 重庆全数据包 reconciliation 统一耐久入口

本轮把 8.11 的高层 reconciliation 发布为一个统一、可验证的同步产品入口：

- 新增 `entity.data-package.reconcile@1.0.0`，CapabilitySpec 指纹为 `b75cb5bd0dc635885ac7d85a059c0edb94a423d663567611bde3a946f6e53d0e`；REST 为 `POST /api/platform/v1/entity-authority/reconciliations`，MCP 为 `reconcile_entity_data_package`，API/SDK/Agent 均投影同一请求/响应 JSON Schema；当前 MCP 工具总数为 53；
- 请求只允许提交认证租户、前后重庆 baseline、生效/评估时间、批大小、重放开关、幂等键和调用者。客户端不能提交实体、来源或 Link 的当前 authority 状态；服务内部读取权威状态并密封计划；
- REST 和 MCP 均只允许 `admin/platform_operator`，拒绝租户、调用者、Capability 指纹及 Header/Body 幂等键冒充。baseline 内部证据身份固定为 `agent:chongqing-baseline-builder`，调用者身份另行审计；
- 新增迁移 `166_chongqing_data_package_reconciliation.sql`。数据库在任何数据写入前预留 request SHA-256 和完整 sealed plan，完成后保存完整 receipt 及紧凑响应；中途失败后从原计划续跑，同一幂等键绑定不同请求会 fail-closed；
- 专项及联合回归为 `54 passed`；新增合同、网关和测试文件 Ruff 通过，MCP 注册表保留既有历史告警。真实 PostgreSQL 16 验收以非超级用户完成 REST 首次执行 7 个操作/6 个批次，再经 MCP 重放同一请求，三项 `plan_sha256`、`receipt_sha256`、`authority_state_sha256` 完全一致；最终实体/来源/Link 计数仍为 `456/458`、`456/457`、`487/491`，临时租户数据已清理。

因此，“固定重庆全数据包 reconciliation 缺少专用 REST/Capability/MCP 和跨请求稳定重放”不再是剩余需求。截至本节仍未完成的是任意客户包适配、跨阶段全局单事务、系统化并发与故障注入、跨存储 checkpoint 和生产 SLO；8.13 已补齐可恢复异步任务主路径，8.19 又补齐 checkpoint PostgreSQL 权威，但 provider 执行和多存储验收仍未完成。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

### 8.13 重庆全数据包 reconciliation 可恢复异步任务

本轮继续把同步入口之上的剩余运行面补齐为可恢复异步切片：

- 新增迁移 `167_chongqing_data_package_reconciliation_job.sql`、`data_agent/chongqing_data_package_reconciliation_job.py` 和可部署入口 `python -m data_agent.chongqing_data_package_reconciliation_worker`，以租户 + 幂等键绑定稳定 job UUID、原始 request SHA-256 和完整请求文档；队列状态、阶段、阶段进度、attempt、worker lease、取消证据、错误和最终响应均写入 PostgreSQL，RLS 与 SECURITY DEFINER 函数不向网关开放直写；
- 新增 `entity.data-package.reconcile-job.submit@1.0.0`、`entity.data-package.reconcile-job.get@1.0.0`、`entity.data-package.reconcile-job.cancel@1.0.0`，CapabilitySpec 指纹分别为 `7bd25cc41b7dbe6db378c240263c83b83195570f2aac1c3f036aeae90222d44b`、`998d1b9f2d709eea193d33b555bb85a48ff59f213cfff463f65c291d2798d10c`、`8f93b0b4e9af4a822786a87d1ee9b6e6b56f7f6c09f0db45a27600d2af752bdd`；REST 分别提供任务提交、状态查询和取消路径，MCP 分别提供 `submit_entity_data_package_reconciliation`、`get_entity_data_package_reconciliation_job`、`cancel_entity_data_package_reconciliation_job`；当前 MCP 工具总数为 56；
- worker 使用 `FOR UPDATE SKIP LOCKED` + lease claim，过期 lease 可重新领取；执行复用同一 sealed plan 和同步 ledger，不重新规划；每个 authority 原子批次之间写回 `planning/applying/finalizing/completed` 进度并续租，取消只在批次边界合作收敛；已经提交的批次不回滚，状态明确为 `cooperative_between_atomic_batches_no_rollback`；
- 同一 request 的重复提交返回同一 job；队列故障或 worker 中断后会从原始请求/原 sealed plan 继续，失败按有限 attempt 重试并最终 fail-closed；完成响应仍固定封存 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`；
- 异步 worker/合同专项 `5 passed`，REST 状态/取消专项通过，迁移目录已推进至 `167`，最新目录 fingerprint 为 `49d37ef4be3e7ef40078b20b35814452cefa76232094734e144be2a7a61f4188`；

因此，“固定重庆 reconciliation 没有可恢复异步任务、进度、取消和状态查询”不再是剩余需求。但这仍不是跨阶段全局单事务；该阶段还没有跨存储 checkpoint、真实部署故障注入、并发容量基准或客户生产 SLO，后续 8.19 仅补齐了 checkpoint PostgreSQL 权威。取消不是回滚，部分批次提交后必须按 sealed plan 继续或由人工按技术证据处理。任意客户包适配、既有实体域迁移和复杂多源冲突裁决仍未完成。

### 8.14 重庆 reconciliation 故障恢复与取消竞态验收

本轮继续收紧异步任务在异常边界上的行为，但把“契约级故障注入”与“客户生产级混沌/容量证明”明确区分：

- 新增迁移 `168_chongqing_data_package_reconciliation_cancel_race.sql`，保持 167 号迁移不可变；完成函数在持有有效 worker lease 的情况下重新锁定 job，若最后一次进度回写后已出现 `cancel_requested`，则在完成边界把任务收敛为 `cancelled`，阶段记录为 `cancelled_at_completion_boundary`，不保存成功响应，避免取消竞态被误报为成功；
- worker 对租约/领取冲突显式 fail-closed：旧 worker 不再调用 `fail` 覆盖新 worker 的 claim，而是丢弃本次 stale outcome，等待新 owner 继续原 sealed plan；普通执行异常仍按有限 attempt 重试，达到上限后最终失败；
- 新增可重复的故障矩阵测试，覆盖临时执行失败后的同请求重试、进度回写时租约丢失、完成阶段取消竞态、三类终态写回租约丢失和迁移合同检查；异步 worker/合同专项扩大到 `9 passed`，迁移/profile 回归为 `30 passed`，异步 REST/API 专项为 `10 passed`；目录推进至 `168`，最新 fingerprint 为 `4e7e06589393f9c2d9c9a55bbc61592f0c352f05d0072c16c4cb94e9d360840f`；

因此，“异步任务在已知取消竞态或旧租约异常下可能覆盖状态”的技术缺口已关闭。当前仍未证明的是 PostgreSQL 断连/进程硬杀/重复领取在真实部署中的故障注入结果、并发容量曲线、跨 PostgreSQL/对象存储/湖仓的 checkpoint 重建，以及客户生产拓扑和 SLO。跨阶段全局单事务、任意客户包适配、既有实体域迁移和复杂多源冲突裁决仍未完成。所有输出继续固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。

### 8.15 重庆 reconciliation 可重复故障 rehearsal 与编排层微基准

本轮把已知异常边界整理为可重复运行的技术证据，但没有把内存模拟结果冒充 PostgreSQL 或客户生产容量：

- 新增 `data_agent/chongqing_data_package_reconciliation_resilience.py` 和 CLI `python scripts/rehearse_chongqing_data_package_reconciliation_resilience.py`；报告合同为 `gda.chongqing-reconciliation-resilience-report.v1`，场景结果、事件序列、耗时、容量范围、用途状态和自身 SHA-256 均封存；
- rehearsal 覆盖 8 个场景：执行失败重试、进度回写租约丢失、成功/取消/失败三类终态租约丢失、批次边界取消、重复领取防护和最大 attempt fail-closed；专项测试 `2 passed`，CLI 运行 5 次迭代得到 `8/8` 场景通过；
- 容量字段强制标记 `in_memory_worker_orchestration_only` 和 `production_capacity_certified=false`，因此输出只能用于验证 Worker 状态机和编排开销，不能替代真实 PostgreSQL 并发、网络故障、对象存储故障、恢复时间和 p95/p99 SLO 验收；

这使“已知 Worker 状态机故障边界没有可重复证据”从未覆盖推进为受控技术基线。仍需在隔离 PostgreSQL 和目标部署拓扑中完成硬杀、断连、lease 过期、重复领取、跨存储写入失败、队列积压和容量曲线测试。

### 8.16 重庆 reconciliation 真实 PostgreSQL rehearsal 入口

新增 `data_agent/chongqing_data_package_reconciliation_postgres_rehearsal.py` 和 `python scripts/rehearse_chongqing_data_package_reconciliation_postgres.py --database-url ...`。工具只接受显式管理员 PostgreSQL URL，在临时数据库中执行 092/094/160/161/162/166/167/168 迁移，创建临时非超级用户运行角色，验证 enqueue 幂等、claim、取消完成竞态、lease 过期恢复、`SKIP LOCKED` 重复领取排除和最大 attempt fail-closed，最后强制清理临时数据库和角色。

### 8.17 重庆 reconciliation 真实 PostgreSQL rehearsal 实测

本轮在隔离的 PostgreSQL 16/PostGIS 容器中实际运行上述入口，关闭了“只有入口但没有真实数据库证据”的工程缺口：

- 7/7 检查通过：幂等入队、queued claim、`cancel_requested -> cancelled_at_completion_boundary`、过期 lease 重领、`FOR UPDATE SKIP LOCKED` 重复领取排除、`max_attempts -> failed`；封存报告为 `docs/reports/chongqing_reconciliation_postgres_rehearsal_2026-08-14.json`，SHA-256 为 `e3a852289ca0c6b095cce6d60f81e4839371d8812d97a78d61fd91f75271fca5`；
- 实测修复了两个验收工具缺陷：迁移文本中的 `%` 不能直接交给 psycopg2 参数绑定；设置 `max_attempts` 必须连接临时数据库而不是维护库；两项均已加入回归测试；
- 临时数据库、临时角色和验收数据均已清理。该证据的范围仍是 `temporary_database_only`，不等于客户生产拓扑认证。

因此，固定重庆 reconciliation 的 PostgreSQL 基础语义已具备真实隔离验收证据；仍未证明的是 PostgreSQL 断连、worker 硬杀、对象存储联动失败、队列积压、并发容量曲线、恢复时间、跨存储 provider rebuild/delete 和客户生产 SLO。checkpoint PostgreSQL 权威见后续 8.19。输出继续固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`。

### 8.18 跨存储投影一致性与 repair plan 确定性合同

本轮继续推进跨 PostGIS/RDF/向量/对象存储的一致性缺口，但只声明已经完成的合同层能力：

- 新增 `data_agent/cross_store_projection_consistency.py`，把 immutable source desired state、独立 target observation 和 last committed checkpoint 分离建模，支持 PostGIS、RDF、vector、object store 和 lakehouse 五类目标；
- 确定性 assessment 覆盖 aligned、checkpoint missing、source advanced、target missing、delete required、target drift、checkpoint state drift 和 desired content mismatch，输出 `noop/checkpoint/rebuild/delete/fail_closed`；未登记 checkpoint、无来源解释的目标漂移或未经计划的目标消失均不会被静默采纳；
- `gda.projection-repair-plan.v1` 封存前态 checkpoint、期望目标、观察证据、reason codes、下一 checkpoint version、幂等键和自身 SHA-256；只有回执同时绑定 `plan_sha256` 与 idempotency key，并复核内容 SHA-256、行数或删除状态完全一致，才能生成下一版 `gda.projection-checkpoint.v1`；
- 内存 ledger 支持同 checkpoint 幂等重放、版本逐一推进、stale predecessor 冲突和 append-only history；专项测试 `14 passed`，Ruff 通过。

这关闭了“跨存储一致性没有统一判断和重建计划合同”的缺口。该节形成时持久化和 provider 执行均未完成；后续 8.19 已补齐 PostgreSQL checkpoint authority，8.20-8.23 已补齐 PostGIS、pgvector 与 RDF 执行器和统一入口；当前仍缺对象存储、湖仓实际重建或删除、备份恢复和真实多存储验收，因此仍不能宣称生产跨存储一致性完成。状态和用途边界继续固定为 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

### 8.19 跨存储 checkpoint PostgreSQL authority 与真实验收

本轮把 8.18 的内存 checkpoint ledger 落为 PostgreSQL 控制面权威，但没有越界实现或虚构任何 provider 写入：

- 新增迁移 `169_cross_store_projection_checkpoint_authority.sql`，建立 append-only history 和 security-invoker current 视图；表启用并强制租户 RLS，gateway 只有读取和受控函数执行权限，没有 INSERT/UPDATE/DELETE 权限；
- 唯一写入口 `record_cross_store_projection_checkpoint(...)` 为 SECURITY DEFINER 函数，首版只能为 1，后续必须精确匹配 `previous_checkpoint_sha256` 且版本只加 1；目标提交证据必须同时绑定 repair `plan_sha256` 和 plan idempotency key；同证据重放返回既有 checkpoint，不同证据复用 checkpoint/plan 身份时 fail-closed；
- 新增 `PostgresProjectionCheckpointAuthority`，提供 `record/current/history`，运行时显式切换到 `gda_control_gateway` 并设置事务级 tenant context，数据库 SQLSTATE 映射为冲突、越权、校验或配置错误；
- 在本机隔离临时 PostgreSQL 数据库实际执行 092/094/169，10/10 检查通过：首版写入、幂等重放、不同幂等证据冲突拒绝、stale predecessor 拒绝、跳版本拒绝、append-only history/current、跨租户读取隐藏、跨租户写拒绝、gateway 表直写拒绝、history UPDATE 拒绝；临时数据库和角色已清理；
- 封存报告为 `docs/reports/cross_store_projection_checkpoint_postgres_rehearsal_2026-08-15.json`，报告 SHA-256 为 `167cc51f819a3b9f8d3f8d14eadf58042565a4b96c1df26b39daa21bef5fbad6`。迁移目录为 169 项，catalog fingerprint 为 `8bfa3657b4aa04dd6c51740908fb9442e3a2a6a45e375346f628e769b3918bd4`。

因此，“跨存储 checkpoint 只有内存账本、没有持久化权威和真实数据库证据”不再是剩余需求。8.20-8.23 已关闭 PostGIS、pgvector 与 RDF provider 的受控 rebuild/delete/checkpoint、自动 authority 串联和统一外发入口缺口，但不能外推到其他存储。仍未实现的是对象存储、湖仓 provider 执行器、备份恢复、跨五类存储的真实端到端故障恢复与一致性验收，以及客户生产容量/SLO。本轮结果继续固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

### 8.20 PostGIS plan-bound provider 执行器与外发入口

本轮在不虚构其他 provider 能力的前提下，完成了 PostGIS 执行面：

- 新增 `data_agent/postgis_projection_executor.py`，只接受 `ProjectionRepairPlan`，并要求租户、投影、`postgis://` 目标命中部署侧显式注册表；请求不能提交自由 SQL、schema/table DDL 或未注册目标；列类型、标识符、排序键和几何 SRID 均经过 allowlist 校验；
- `rebuild` 使用幂等键派生的 run-scoped staging table，在一个事务中执行结构化行写入、受控替换和最终观察；`delete` 只允许删除封存计划观察到的同一目标状态；`checkpoint` 只复核目标，不重建；提交回执包含 `plan_sha256`、幂等键、provider commit ref、目标内容 SHA-256、行数和目标存在性；
- 新增 `data_agent/postgis_projection_service.py`，部署侧通过 `GDA_POSTGIS_PROJECTION_TARGETS_JSON` 注册目标，通过 `DATABASE_URL` 连接数据库；新增 `POST /api/platform/v1/projections/postgis/repairs`、Capability `projection.postgis.repair@1.0.0` 和 MCP `execute_postgis_projection_repair`，三者复用同一请求/回执合同和租户、角色、Capability fingerprint、幂等键门禁；
- 新增单元测试 `data_agent/test_postgis_projection_executor.py`；第 8.20 节首次在临时 PostgreSQL 16 + PostGIS 数据库执行 6/6 provider 检查：几何列 rebuild、rebuild 幂等重放、封存观察漂移拒绝、checkpoint 无重建复核、delete 和 delete 幂等重放；后续 8.21 扩展为含 authority 串联的 11/11 演练。首次封存报告 SHA-256 为 `7cfd01c9515871dc811dbb53475d7134f64f2bf7e9ddd8f2cecd24b0fbc8e0ac`，当前报告见 8.21。

该节记录 PostGIS provider 和统一外发入口的首个增量。provider 回执与 checkpoint authority 的自动串联见后续 8.21，pgvector provider 见 8.22，RDF provider 见 8.23；对象存储、湖仓仍未实现，备份恢复、真实跨存储故障注入、一致性验收和生产容量/SLO 仍未完成。结果继续固定为 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`。

### 8.21 PostGIS provider receipt 自动 checkpoint 串联与 11/11 真实演练

本轮把 8.20 的 provider 事务与 PostgreSQL checkpoint authority 接成可重试的服务合同，但不宣称分布式原子事务：

- `PostGISProjectionRepairRequest` 增加 typed `checkpointed_by`；服务先读取 authority 当前 checkpoint 并校验 sealed plan predecessor，避免 stale plan 先修改 PostGIS 再在 authority 阶段失败；provider 成功后从 receipt 构造 `ProjectionTargetObservation`，生成 `ProjectionCheckpoint` 并通过 `PostgresProjectionCheckpointAuthority.record` 写入 append-only history/current；authority 暂时失败时可重试，重试会重新观察 PostGIS；
- 已存在同 plan checkpoint 时不会只凭幂等键返回，必须重新观察 PostGIS；内容、行数或删除状态漂移会拒绝重放。并发 checkpoint 冲突只有在读取到完全一致的 plan/target evidence 后才收敛为 replay；receipt 必须绑定 tenant、projection、target、action、plan SHA、幂等键和 `postgis` provider；
- Capability 输出升级为 `gda.postgis-projection-repair-result.v1`，同时返回 provider `receipt`、durable `checkpoint`、`checkpoint_created` 和固定用途状态；REST/MCP 强制 `checkpointed_by` 等于认证主体，禁止跨主体代写；
- 在临时 PostgreSQL 16 + PostGIS 数据库执行 092/094/169，11/11 检查通过：rebuild 自动 checkpoint、rebuild replay、封存观察漂移拒绝、已有 checkpoint 重放重新观察并拒绝漂移、checkpoint action 版本推进、stale predecessor 写前拒绝、delete 自动 checkpoint、delete replay、append-only history `1→2→3` 等；单测和联合回归为 `96 passed, 1 skipped`；
- 封存报告为 `docs/reports/postgis_projection_executor_rehearsal_2026-08-15.json`，报告 SHA-256 为 `eb99cd13b3bbf7a541ac115b7aa2e3d4a965988720044f908574ab70580671c1`，范围仍为 `temporary_database_only`。

因此，PostGIS provider receipt 自动落 authority 不再是剩余需求；pgvector 同类缺口已由后续 8.22 关闭，RDF 同类缺口由 8.23 关闭。当前仍不能外推到对象存储或湖仓；剩余需求包括这两类 provider 执行器、五类存储真实端到端故障恢复/一致性验收、备份恢复、全执行面权限、通用 Action/Proposal 生产运行时以及客户生产容量/SLO。所有结果继续固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

### 8.22 pgvector plan-bound provider、自动 checkpoint 与统一入口

本轮把向量投影从已有检索/写入组件推进为与 PostGIS 同类的受控 repair 执行面：

- 新增 `data_agent/vector_projection_executor.py`。租户、projection、`vector://host/schema.table`、schema/table 和 embedding dimension 必须命中部署侧显式注册表；请求只能提交结构化 `record_id/product_id/collection/content_text/embedding/metadata/source_manifest` 行，不能提交 SQL、DDL、任意表名或任意向量维度；
- `rebuild` 通过幂等键派生 staging/backup table，在单事务内创建固定 `VECTOR(n)` 表、写入、替换并重新观察内容；`delete` 只执行 sealed observation 对应目标，`checkpoint` 只复核不写入；内容 SHA-256 对行顺序无关但绑定 embedding dimension，非有限向量、维度漂移、目标漂移和非表关系均 fail-closed；
- 新增 `data_agent/vector_projection_service.py`，先校验 checkpoint authority predecessor，再执行 provider，并把 plan-bound receipt 自动写入 PostgreSQL append-only checkpoint authority；authority 暂时失败可重试，已有 checkpoint 重放必须重新观察 pgvector 目标，漂移时拒绝静默 replay；provider 与 authority 仍不是分布式原子事务；
- 新增 REST `POST /api/platform/v1/projections/vector/repairs`、Capability `projection.vector.repair@1.0.0` 和 MCP `execute_vector_projection_repair`，三者共享 `gda.vector-projection-repair-request/result.v1` 合同，强制认证租户、平台角色、Capability fingerprint、主体绑定和 sealed plan 幂等键；Capability 指纹为 `70cf73a1d07ad567300881d4d99b4f5c7613a0a7f32a3e5262157cbc8aa75d9d`，当前 MCP 工具总数为 58；
- 专项与联合回归为 `106 passed`。临时 PostgreSQL 16 + pgvector 0.8.2 数据库执行 092/094/169 后，11/11 检查通过：rebuild、自动 checkpoint、幂等重放、sealed drift 拒绝、checkpoint replay 重新观察、checkpoint action、stale predecessor 写前拒绝、delete、delete replay 和 append-only history `1→2→3`；临时数据库已删除；
- 封存报告为 `docs/reports/vector_projection_executor_rehearsal_2026-08-15.json`，报告 SHA-256 为 `88bc30950aca11c49ca0e9c6fafcb99f388c4e876f60ec56499961a6444aa9a6`，范围为 `temporary_database_only`。

因此，“向量 provider 没有 plan-bound rebuild/delete/checkpoint、没有自动 checkpoint authority、没有 REST/Capability/MCP”不再是剩余需求。RDF 同类缺口由后续 8.23 关闭；当前尚未完成的是 ANN 索引策略、召回质量和并发容量验收，以及对象存储、湖仓 provider、跨五类存储故障恢复/一致性验收、备份恢复和客户生产 SLO。所有结果继续固定为 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不代表领域批准、客户生产验收、法定审批或行政决定。

### 8.23 RDF/Fuseki plan-bound provider、自动 checkpoint 与隔离真实演练

本轮新增 `data_agent/rdf_projection_executor.py`、`data_agent/rdf_projection_service.py` 和统一外发入口。租户、projection、`rdf://` 目标、Graph Store endpoint、本体目录、ontology key、semantic version、package ID、package content SHA-256、RDF artifact SHA-256 和 triple count 都必须由部署侧显式注册；运行时进一步强制本体只能是 `natural-resource-one-map` 2.3.0。请求只能提交 sealed `ProjectionRepairPlan` 和认证主体，不能提交 RDF body、Fuseki endpoint、凭据、图标识或包目录。

`rebuild` 在写前用 `OntologyPackageReader(verify=True)` 校验不可变包和 RDF artifact，并以 PUT 替换注册图；`delete` 使用 DELETE，`checkpoint` 只复核。RDF 指纹对 triple 顺序无关并拒绝 blank node；sealed observation、已有 checkpoint 重放和并发冲突都会重新观察真实图，内容、triple count 或存在性漂移时 fail-closed。provider receipt 自动写入 PostgreSQL append-only checkpoint authority，但 Fuseki HTTP 提交与 authority 提交不是分布式原子事务，authority 暂时失败后的恢复依靠同一计划重试和重新观察，而不是宣称跨系统原子提交。

REST 为 `POST /api/platform/v1/projections/rdf/repairs`，Capability 为 `projection.rdf.repair@1.0.0`，MCP 为 `execute_rdf_projection_repair`；三者共享 `gda.rdf-projection-repair-request/result.v1`，强制认证租户、平台角色、Capability fingerprint、主体绑定和 sealed plan 幂等键。Capability 指纹为 `9487eb9d69430d5dfd10963c34b6bb4575dd553ea60b61e6ba0edfa1cd8c0b44`，当前 MCP 工具总数为 59。

RDF、pgvector、PostGIS、跨存储 authority/consistency、Capability、REST 和 MCP 联合回归为 `112 passed`。隔离真实演练使用一次性 Fuseki 5.5.0 容器、一次性卷和临时 PostgreSQL checkpoint 数据库，实际写入自然资源本体 2.3.0 的 537,245 条 triples。核心 11/11 检查覆盖 rebuild、自动 checkpoint、幂等 replay、sealed drift、checkpoint replay drift、checkpoint action、stale predecessor、delete、delete checkpoint、delete replay 和 history `1→2→3`；另有 3/3 清理检查，且二次核查容器、卷和临时数据库残留均为 0。封存报告为 `docs/reports/rdf_projection_executor_rehearsal_2026-08-15.json`，报告 SHA-256 为 `0346095387ddb9d3dae81cdba23a4453858d73f81b619c8844fe4ca4e6c65012`。

因此，RDF provider 的 plan-bound rebuild/delete/checkpoint、自动 authority 串联和 REST/Capability/MCP 不再是剩余需求。尚未完成的是对象存储与湖仓 provider、跨五类存储故障恢复/一致性验收、备份恢复、容量与生产 SLO；也不代表完整 OWL 2 DL 推理、任意 RDF 写入、领域批准、客户生产验收、法定审批或行政决定。状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

### 8.24 S3/MinIO 对象存储 plan-bound provider、自动 checkpoint 与隔离真实演练

本轮新增 `data_agent/object_projection_executor.py`、`data_agent/object_projection_service.py` 和 `data_agent/object_projection_executor_rehearsal.py`。租户、projection、`s3://` target、endpoint、region、bucket、key、bundle manifest 路径及 SHA-256、artifact 路径/SHA-256/字节数/media type、本体 package ID 与 package SHA-256 必须由部署侧显式注册；注册合同固定为重庆客户包 `natural-resource-ontology-customer-demo-v1` 1.0.0 和自然资源本体 `natural-resource-one-map` 2.3.0。调用请求只允许 sealed `ProjectionRepairPlan` 与认证主体，不能提交对象字节、endpoint、bucket、key、artifact 路径或凭据。

执行器要求目标 bucket 开启 S3 Versioning；每次观察都读取真实对象字节重新计算 SHA-256，并绑定不可变 `VersionId` 与 ETag。`rebuild` 只写入注册 manifest 已校验的 `heping_changed_parcels.geojson`，`delete` 必须返回不可变 delete marker，`checkpoint` 只复核。已有 checkpoint 重放除了核对内容/行数/存在性，还核对 `VersionId`、ETag、字节数或 delete marker，所以“内容相同但产生新版本”也按漂移 fail-closed。S3 提交与 PostgreSQL authority 提交不是分布式原子事务，恢复仍依靠同一 sealed plan、重新观察和幂等证据。

REST 为 `POST /api/platform/v1/projections/object-store/repairs`，Capability 为 `projection.object-store.repair@1.0.0`，MCP 为 `execute_object_projection_repair`；三者共享 `gda.object-projection-repair-request/result.v1` 并强制租户、平台角色、Capability fingerprint、主体绑定和幂等键。Capability 指纹为 `7af931f2e305fd617ce227b786b77cd353ca946ba72aebececc4b33998322908`，当前 MCP 工具总数为 60。部署参数 `GDA_OBJECT_PROJECTION_TARGETS_JSON`、独立 S3 凭据和 timeout 已进入环境示例、Compose 与 Kubernetes 配置。

对象存储入口联合回归为 `65 passed`。隔离真实演练使用一次性 MinIO 容器/卷/bucket 和临时 PostgreSQL checkpoint 数据库，实际写入客户 artifact `heping_changed_parcels.geojson`，SHA-256 为 `eb35068c4273fe25e07d99f822016f33b6fe29cd189b34aff037b9611e163bd3`，字节数为 `1,950,576`。核心 11/11 覆盖 Versioning、rebuild、自动 checkpoint、幂等 replay、同内容新版本漂移、checkpoint action、stale predecessor、delete marker、delete checkpoint、delete replay 和 history `1→2→3`；清理 4/4 覆盖 bucket、容器、卷和临时数据库。封存报告为 `docs/reports/object_projection_executor_rehearsal_2026-08-15.json`，内部报告指纹为 `40f90a0b86f09867fdb98f585a282c7f5f7e678d99a664202c87fc6224b803fb`，文件 SHA-256 为 `9c4f9272eb0660c93b3d65a7f0504a1de795f83b3f468bf8364d73c6c931ba18`。

因此，对象存储 provider 的 plan-bound rebuild/delete/checkpoint、不可变版本证据、自动 authority 串联和 REST/Capability/MCP 不再是剩余需求。当前剩余 provider 只有湖仓；跨五类存储端到端故障恢复/一致性验收、备份恢复、容量和客户生产 SLO 仍未完成。本节不代表专家审定、领域批准、客户生产验收、法定审批或行政决定，状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

### 8.25 Spark/Iceberg 湖仓 plan-bound provider、自动 checkpoint 与隔离真实演练

本轮新增 `data_agent/lakehouse_projection_executor.py`、`data_agent/lakehouse_projection_service.py`、`data_agent/lakehouse_projection_spark_provider.py` 和固定 Spark worker。部署注册表绑定租户、projection、`iceberg://` target、catalog/namespace/table、S3 warehouse、MinIO endpoint、重庆 bundle manifest/artifact 指纹、逻辑表指纹和自然资源本体 2.3.0 package；请求只接受 sealed plan 和认证主体，不能提交行数据、Spark 配置、warehouse/table、存储端点、凭据或本地路径。

客户 `heping_changed_parcels.geojson` 的事实不是“445 个唯一地块”：实际为 445 个 feature、439 个 `parcel_id`，其中 `62499` 与 `65599` 存在一地块多要素。湖仓行合同因此使用 `parcel_id + artifact feature index` 构成稳定 `feature_id`，并单独保留 `parcel_id`、geometry/properties canonical JSON 和 feature SHA-256；没有丢弃或错误合并客户记录。逻辑表指纹为 `8d5339abfd8b7015e894791f3198cbe3f097470a9292b6e019f9ceb030e46dfb`。

执行器通过固定 Spark 3.5/Iceberg 1.6.1 runtime 在 Hadoop catalog + MinIO warehouse 创建或替换 Iceberg v2 表；每次观察都回读全部受控行、重算逻辑指纹和行数，并读取当前 Iceberg `snapshot_id`。已有 checkpoint 重放同时核对内容与 snapshot，所以同内容新 snapshot 也按漂移 fail-closed。删除前先在注册 warehouse 写入 plan-bound tombstone，再执行 `DROP TABLE PURGE` 并重新观察表缺失；若 DROP 已成功而 PostgreSQL authority 写入失败，同一 sealed plan 可从 tombstone 恢复删除前 snapshot 和 drop evidence 后补写 checkpoint。该恢复机制仍不把 Iceberg DROP 与 PostgreSQL authority 宣称为分布式原子事务。

REST 为 `POST /api/platform/v1/projections/lakehouse/repairs`，Capability 为 `projection.lakehouse.repair@1.0.0`，MCP 为 `execute_lakehouse_projection_repair`；三者共享 `gda.lakehouse-projection-repair-request/result.v1`，强制认证租户、平台角色、Capability fingerprint、主体绑定和 sealed plan 幂等键。Capability 指纹为 `eb693f332b4174a6581c0ace02fec5b43a276a303211bc9128ef6dc9f263673f`，当前 MCP 工具总数为 61。部署参数进入环境示例、Compose 与 Kubernetes 禁用模板；当前默认执行适配器是受控 Docker Spark runtime，Kubernetes 集群仍需显式安装集群 Spark 执行边界，不能因接口存在就宣称集群部署完成。

五类 provider 与统一入口联合回归为 `122 passed`。隔离真实演练使用一次性 Docker 网络、MinIO 容器/卷/bucket、固定 Spark/Iceberg 镜像和临时 PostgreSQL checkpoint 数据库，核心 12/12 覆盖客户 feature/parcel 基数、rebuild、自动 checkpoint、幂等 replay、同内容新 snapshot、checkpoint replay 漂移、checkpoint action、stale predecessor、DROP 后 authority 间隙恢复、delete checkpoint、delete replay 与 history `1→2→3`；清理 5/5 覆盖 bucket、容器、卷、网络和临时数据库。封存报告为 `docs/reports/lakehouse_projection_executor_rehearsal_2026-08-15.json`，内部报告指纹为 `dd6e116bacd7d1bf853c4164ec5f2af7bbe2364acc8ffb9b9a6826b221f3c1d3`，文件 SHA-256 为 `a6f3a3542c16bf4df6403efda9a9ce22c918650a48782cea47440d9bd52530f3`。

因此，PostGIS、pgvector、RDF、对象存储和湖仓五类 plan-bound provider 均已有自动 checkpoint 与统一入口，单一 provider 缺失不再是剩余需求。当前剩余的是跨 provider 失败后的统一恢复/补偿编排、备份恢复、全执行面权限、真实多存储故障注入、容量和客户生产 SLO；本节不代表专家审定、领域批准、客户生产验收、法定审批或行政决定，状态继续固定为 `technical_baseline_unreviewed`，用途继续固定为 `assisted_precheck_not_for_production_decision`。

### 8.26 跨 Provider recovery state machine 与 authority 间隙故障矩阵

本轮新增 `data_agent/cross_store_projection_recovery.py`，把五类 provider 共享的“Provider 提交”和“PostgreSQL checkpoint authority 提交”边界显式建模为 append-only recovery state machine：

- 已知且已封存的 provider receipt 进入 `provider_committed -> authority_pending`，恢复时先重新观察目标，再只重试 authority，不重新执行 provider；目标内容、行数、存在性或目标身份漂移时进入 `reconciliation_required -> manual_compensation`，禁止静默推进 checkpoint；
- Provider 结果已知为未提交时进入 `provider_failed -> execute_provider`，允许按同一 sealed plan 重试；worker 硬杀、网络断连等结果未知时进入 `reconciliation_required -> reobserve_target`，没有 provider commit evidence 时不允许盲目重放或补写 checkpoint；
- recovery snapshot 和 event 都绑定 plan SHA-256、幂等键、Provider commit ref、checkpoint SHA-256、错误码和事件链指纹；新增 `cross_store_projection_recovery_rehearsal.py` 及 CLI，输出明确标记 `in_memory_recovery_orchestration_only` 和 `production_recovery_certified=false`；
- 故障矩阵 `known_provider_authority_gap`、`target_drift_requires_manual_compensation`、`unknown_provider_outcome_requires_reobservation`、`known_provider_failure_can_retry` 共 `4/4` 通过；专项测试 `7 passed`，Ruff 通过；封存报告为 `docs/reports/cross_store_projection_recovery_rehearsal_2026-08-15.json`，文件 SHA-256 为 `364b70b11dcd36c2224efa68aa125e3d596618bd5e3988f267703ed1f09b95d0`。

因此，“跨 Provider 失败后的恢复决策没有统一控制面合同”已推进到可测试技术基线，但尚未完成生产持久化 recovery ledger、自动补偿执行器、PostgreSQL 断连/worker 硬杀/网络故障注入、队列积压、恢复时间、跨五类存储端到端一致性和 SLO。该增量不宣称分布式原子事务、生产恢复认证、专家审定、客户生产验收或法定审批，状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`。

### 8.27 PostgreSQL 持久化 recovery ledger 与真实隔离验收

本轮新增迁移 `170_cross_store_projection_recovery_ledger.sql` 和 `PostgresProjectionRecoveryLedger`，将 8.26 的 recovery snapshot/event 从内存合同推进为 PostgreSQL append-only authority：

- snapshot history 和 event history 均启用租户 RLS、强制 RLS、不可变 UPDATE/DELETE trigger 和 gateway 无表直写权限；唯一写入口为 `SECURITY DEFINER` 函数，按 plan advisory lock 保证同一 sealed plan 的事件链顺序；
- 每次写入同时校验 tenant、projection、target engine/ref、plan SHA-256、幂等键、snapshot/event SHA-256 和事件链前缀；相同 snapshot 幂等重放返回原记录，跳事件、篡改事件、跨租户和直接表写入均 fail-closed；
- 新增 `cross_store_projection_recovery_postgres_rehearsal.py` 和 CLI，首次使用临时 PostgreSQL 16 数据库实际执行 092/094/169/170 迁移，ledger 基础检查 `8/8` 通过；该入口和同名报告随后已由 8.29 扩展到 171 号迁移与 durable job queue，当前检查数和哈希以 8.29 为准；
- 新增 `cross_store_projection_recovery_worker.py` 与 `RegisteredExecutorProjectionProvider`，统一适配 PostGIS、RDF/Fuseki、pgvector、S3/MinIO、Spark/Iceberg 五类已有 executor。worker 对已知 provider receipt 只做 authority retry，对未知结果只做 re-observation；没有显式 compensation callback 时保持 `await_operator`，不盲目重放。恢复专项回归为 `14 passed, 1 skipped`，Ruff 通过；
- 此阶段 migration catalog 为 `170`；当前目录已由 8.32 推进到 `172`，旧的报告哈希和目录指纹不再作为当前证据引用。

因此，“recovery ledger 只有内存实现”以及“没有统一 worker 决策合同”不再是剩余需求。仍未完成的是把各 Provider 服务的真实异常回执、目标观察器和补偿策略接入部署调度器，完成 PostgreSQL 断连、worker 硬杀、网络故障、队列积压、lease 过期、恢复时间、跨五类存储端到端一致性、备份/PITR/RPO/RTO 和真实生产 SLO 验收。当前仍不宣称分布式原子事务、生产灾备认证、专家审定、客户生产验收或法定审批。

### 8.28 五类 Provider durable recovery worker 接入合同

本轮在 8.26-8.27 的状态机和 PostgreSQL ledger 之上新增统一 `ProjectionRecoveryWorker`：

- `RegisteredExecutorProjectionProvider` 通过注册表解析目标，复用五类已有 plan-bound executor 的 `execute/observe`，PostGIS/pgvector 传递受控 rows，其余 provider 不接受客户端副作用参数；
- worker 进程重启后从 durable snapshot 继续：`provider_committed`/`authority_pending` 只重新观察目标并写 authority；已知未提交错误保留 `execute_provider`；未知错误转 `reobserve_target`，重新观察后仍无 commit evidence 则转 `manual_compensation`，默认不自动补偿；
- 只有调用方显式提供 plan-bound compensation callback，worker 才会执行补偿并再次验证目标/authority；补偿失败保持 `await_operator`，不会把“目标内容碰巧一致”当作已提交证据；
- 新增 `data_agent/test_cross_store_projection_recovery_worker.py`，覆盖首次执行、authority 失败后不重放 Provider、未知结果重新观察并等待补偿、显式补偿闭环及 executor adapter 行为；该实现仍是统一技术合同，不等于已在真实五类存储部署中注入故障或完成生产调度。

因此，跨 Provider recovery 的“统一动作选择、持久状态重载、authority-only retry、未知结果封闭和显式补偿入口”已推进为可测试技术基线；本节形成时尚无自动 worker 队列与 lease，后续 8.29 已补齐该数据库调度内核。仍缺五类 Provider 的真实异常回执部署接线、补偿/对账业务策略、长任务 heartbeat、断连/硬杀/网络/队列故障注入、备份恢复、容量/恢复时间和客户生产 SLO。所有输出继续为 `technical_baseline_unreviewed` 与 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、法定审批或行政决定。

### 8.29 跨 Provider durable recovery job queue、lease fencing 与真实 PostgreSQL 演练

本轮把 8.28 的单次 worker 合同推进为 PostgreSQL 持久任务队列，但范围仍限定在重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0` 技术基线，不引入宁夏或 Excel：

- 新增迁移 `171_cross_store_projection_recovery_job.sql` 和 `PostgresProjectionRecoveryJobRepository`。完整 sealed plan JSONB、plan SHA-256、幂等键、目标身份、attempt、状态、错误和最终 snapshot 证据均持久化；同租户 + 同 plan 只产生一个确定性 job，证据不一致时 fail-closed；
- claim 使用 `FOR UPDATE SKIP LOCKED`，同一时刻只允许一个 worker 持有任务；每次领取递增 `lease_generation`，续租和终态写必须同时匹配 worker ID、租约代次和未过期时间，因此即使新旧进程复用同一 worker ID，旧代结果也不能覆盖新租约；
- `waiting_operator` 不进入自动领取，只有显式 `resume` 才重新排队并保存 `resumed_by/resumed_at`；当原 `max_attempts` 已用尽时，resume 明确增加一次可用 attempt，而不是生成表面 queued、实际永远不能领取的任务；任务表启用并强制 RLS，gateway 只有 SELECT 和受控函数权限，没有表写权限；
- 新增 `ProjectionRecoveryJobWorker`，领取后从 PostgreSQL recovery ledger 和 checkpoint authority 恢复执行，结果未知仍沿用 `reobserve_target -> manual_compensation`，不会因为进入队列就放宽恢复策略；
- 临时 PostgreSQL 真实执行 092/094/169/170/171，`16/16` 检查通过，覆盖 ledger 原有 8 项以及幂等入队、单 owner、续租、同 worker ID 下的过期租约代次接管、stale generation 终态拒绝、人工等待不热重试、显式恢复追加一次 attempt/保存操作者证据和 gateway job 表直写拒绝；heartbeat、resolver 和 CLI/Compose 接线随后由 8.30 继续验证；
- 本节形成时的 `16/16` 报告哈希已由后续增量更新，当前报告以 8.32 所列的 `28/28` 检查及新哈希为准；migration catalog 已推进为 `172`，fingerprint 为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`。

因此，“durable recovery worker 没有持久队列、排他领取、lease 过期接管、旧 owner fencing 和人工恢复入口”不再是剩余需求。尚未完成的是把五类 Provider 的真实异常回执和 resolver 接入实际部署进程，为长任务增加周期 heartbeat，制定可授权的 compensation/reconciliation 业务策略，并完成 PostgreSQL 断连、worker 硬杀、网络故障、队列积压和五存储联动故障注入；备份/PITR、RPO/RTO、容量、p50/p95/p99、恢复时间、生产 SLO、全执行面权限、通用 Action/Proposal runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合仍是后续需求。本轮只形成 `technical_baseline_unreviewed`，用途仍是 `assisted_precheck_not_for_production_decision`。

### 8.30 长任务 heartbeat、五类 Provider resolver 与可运行部署接线

本轮继续把第 8.29 节的持久任务队列接到实际 worker 进程边界，范围仍限定为重庆客户数据和自然资源本体 `natural-resource-one-map 2.3.0`，不引入宁夏或 Excel：

- `ProjectionRecoveryJobLeaseHeartbeat` 在 Provider/authority 长时间执行期间按 lease 周期续租；heartbeat 丢失时先确认 lease 所有权，旧 owner 不得写入成功或失败终态。Provider 异常与 heartbeat 丢失同时发生时，以 heartbeat 丢失为准，保持 fail-closed；
- `ProjectionRecoveryProviderResolver` 按 `ProjectionEngine` 惰性解析服务端注册表和凭据，覆盖 PostGIS、pgvector、RDF/Fuseki、S3/MinIO、Spark/Iceberg 五类 executor。恢复任务只能引用服务端注册目标；PostGIS/pgvector rebuild 还必须提供绑定 `<plan_sha256>.json` 的服务端 row bundle，校验 tenant、projection、engine、target、plan SHA、幂等键、行数和 `rows_sha256`，缺失或篡改在 Provider 副作用前拒绝；
- 新增可运行入口 `python -m data_agent.cross_store_projection_recovery_job_worker`，支持租户、worker、lease、heartbeat、重试和 `--once` 参数，并对越界配置 fail-closed；Compose 新增显式 `projection-recovery` profile，默认不启用，挂载受控 row bundle 目录。湖仓 Docker provider 的 Docker socket 未自动授予，部署时仍需显式授权和独立审查；
- 本节形成时临时 PostgreSQL 演练实际执行 092/094/169/170/171，`20/20` 检查通过；除 `durable_worker_heartbeats_during_provider_execution=true` 外，新增未知 Provider 回执保持人工补偿、heartbeat 丢失阻止旧 owner 终态写入以及新 owner 接管三项检查；该报告随后由 8.32 扩展到精确 ApprovalCase 授权，当前检查数和哈希以 8.32 为准；
- 本节形成时的内部报告 SHA-256 `4ee827adcc908f4e0429dd1e2289a1d57164b7cd8ca189595a61d1e7cdae852f` 和文件 SHA-256 `5d5603031acb612794d3e6df92b5c51443260e1a4e7d878055c6279e82629db6` 已被 8.32 的新报告取代；数据库范围始终明确为 `temporary_database_only`。

因此，长任务 lease heartbeat、五类 Provider 的部署侧 resolver、服务端 row bundle 绑定和恢复 worker 的 Compose/CLI 接线已推进为可验证技术基线，不再作为“尚未写实现”的需求。它们仍不等于五类存储真实断连、网络分区、进程硬杀、不确定回执或五存储联动故障注入，也不等于生产部署、容量、恢复时间、备份/PITR、RPO/RTO 或客户 SLO 验收。湖仓 Docker 执行边界、全执行面权限、可授权的 compensation/reconciliation 策略、通用 Action/Proposal runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合仍是后续需求。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域批准、客户生产验收、法定审批或行政决定。

### 8.31 PostgreSQL recovery worker 受控故障注入与 lease fencing 实测

本轮在第 8.30 节基础上把两类容易误判的 worker 异常放入真实临时 PostgreSQL 队列和 recovery ledger，范围仍限定为重庆客户 sealed plan 与自然资源本体 `natural-resource-one-map 2.3.0`：

- 注入 Provider `outcome_known=false` 的超时回执。首次执行只记录 `reconciliation_required -> reobserve_target`；重新观察后没有 provider commit evidence 时进入 `manual_compensation -> await_operator`，不重放 Provider，也不写 checkpoint。该场景只使用测试 Provider 替身，未声称真实存储已发生不确定回执；
- 注入第二次 lease renew 失败的 heartbeat 丢失。旧 worker 不写 `succeeded`/`failed` 终态，任务仍保持 `running`，手工使租约过期后由新 worker 以递增 `lease_generation` 接管；
- 临时 PostgreSQL 实际执行 092/094/169/170/171，`20/20` 检查通过；新增检查名为 `unknown_provider_fault_stays_manual_after_reobserve`、`heartbeat_loss_blocks_terminal_write` 和 `heartbeat_loss_job_can_be_reclaimed`。封存报告内部报告 SHA-256 为 `4ee827adcc908f4e0429dd1e2289a1d57164b7cd8ca189595a61d1e7cdae852f`，文件 SHA-256 为 `5d5603031acb612794d3e6df92b5c51443260e1a4e7d878055c6279e82629db6`。

该增量关闭了 recovery worker 控制面中“未知结果可能被重放”和“heartbeat 丢失后旧 owner 可能写终态”的可测试缺口，但证据范围仍是 `temporary_database_only`，Provider 是故障注入替身，不是 PostGIS、pgvector、Fuseki、MinIO 或 Iceberg 的真实断连/网络/进程故障。五类存储真实故障注入、补偿/对账的实际业务规则、备份/PITR、RPO/RTO、容量和生产 SLO 仍未完成；补偿恢复的技术授权门禁已由 8.32 补齐。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表生产恢复认证、专家审定、客户验收或法定审批。

**当前状态更正（承接 8.30）**：第 8.29 节末尾列出的“resolver 接入实际部署进程”和“长任务周期 heartbeat”已由第 8.30 节补齐为受控技术实现；这里保留 8.29 形成时的历史缺口描述，不再把它们列为当前未实现项。补偿恢复的精确 ApprovalCase 技术授权由第 8.32 节补齐，仍未完成的是补偿/对账的实际业务规则与自动补偿实现、五类 Provider 真实断连/网络分区/进程硬杀/不确定回执/队列积压/联动故障注入、备份/PITR、RPO/RTO、容量、恢复时间、生产 SLO、全执行面权限、通用 Action/Proposal runtime，以及自动语义规划与 Ontology/Metric/NL2SQL/GIS/RAG 融合。状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`。

### 8.32 补偿恢复的精确 ApprovalCase 授权与一次性消费证据

本轮关闭了 `waiting_operator -> resume` 只凭操作者字符串即可重新入队的技术授权缺口，仍只使用重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增迁移 `172_projection_recovery_compensation_approval.sql`。job 保存 `resume_approval_case_ref`、`resume_reason` 和 `resume_snapshot_sha256`，并与 `resumed_by/resumed_at` 强制成组；新增 append-only `cross_store_projection_recovery_resume_event`，按 ApprovalCase 唯一约束记录授权消费，gateway 只有 SELECT，不能直接 INSERT/UPDATE/DELETE 或伪造消费证据；
- 删除 171 号迁移遗留的三参数 resume 函数。新函数要求 tenant、job、操作者、ApprovalCase 和理由，且数据库必须同时确认 ApprovalCase 为 `approved`、尚未过期、目标精确等于当前 recovery job URN、fingerprint 精确等于 job 当前等待快照、action 精确等于 `projection.recovery.compensate`；缺失、pending、rejected、跨租户、错误动作、错误快照或已消费审批均 fail-closed；
- `ProjectionRecoveryJob` 和 repository 同步要求完整审批证据，Pydantic 侧拒绝跨租户或非 `approval_case` 的引用。实际补偿后的 Provider/authority 处理仍沿用 sealed plan、lease generation 和 heartbeat fencing，不因获得授权而放宽幂等或一致性校验；
- 隔离临时 PostgreSQL 实际执行 092/094/102/103/169/170/171/172，演练由 `20/20` 扩展为 `28/28`。新增实测覆盖错误快照、错误动作、rejected、pending、跨租户、精确消费事件、一次性消费和 gateway 伪造拒绝；recovery/ApprovalCase/profile/migration 联合回归 `102 passed, 2 skipped`，Ruff 和 migration catalog 校验通过；
- 当前封存报告 `docs/reports/cross_store_projection_recovery_postgres_rehearsal_2026-08-15.json` 的内部报告 SHA-256 为 `5d18a504f3c66dcaf01fed3be5eac819b41f0b7a9db1aeb5900f70dbd999f43e`，文件 SHA-256 为 `9a39258382907e4f5920adc0ea1f36d7855d6064d14582af363983adc14520f2`，范围为 `temporary_database_only`。migration catalog 为 172 项，fingerprint 为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`。

因此，“没有真实 ApprovalCase 证据也能恢复人工补偿任务”和“同一审批可被静默重复消费”不再是未实现项。这里的 ApprovalCase 是技术授权合同，不是专家审定、领域规则批准、客户验收、法定审批或行政决定；系统仍没有替客户定义实际 compensation/reconciliation 业务规则，也没有自动生成补偿方案。当前剩余需求集中在实际补偿/对账策略与执行、全执行面安全闭环、通用 Proposal/Action runtime、五类 Provider 真实故障注入、备份/PITR/RPO/RTO、容量和生产 SLO，以及自动语义规划融合。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.33 经批准的原 sealed plan 受控重放执行器

本轮在 8.32 的 ApprovalCase 一次性授权之上，补齐了一个最小且默认关闭的技术补偿执行路径。范围仍只使用重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0`，不引入宁夏或 Excel：

- 新增 `cross_store_projection_recovery_compensation.py`。配置只允许 `disabled` 和 `approved_reapply_sealed_plan` 两个值，默认 `disabled`；配置入口只能选择策略，不能提交新 target、rows、credentials、endpoint 或任意代码；
- 唯一首期策略不创建新方案，只能调用当前 job 已封存的原 `ProjectionRepairPlan`。job worker 将同一个 plan、同一个部署侧 Provider 和同一个 durable ledger 实例绑定给补偿 callback，Provider 仍通过服务端 registry 解析目标；PostGIS/pgvector rows 仍来自原 plan SHA 绑定的服务端 bundle；
- 执行瞬间由 repository 重新查询并同时验证当前 job 租约和 `lease_generation`、完整 resume evidence、尚未过期且仍为 `approved` 的 ApprovalCase、精确 job URN/fingerprint/action、append-only 消费事件，以及 recovery ledger 当前 snapshot。原等待 snapshot、plan SHA-256、幂等键、projection、engine 或 target 任一漂移均 fail-closed；
- Provider 返回后继续使用原 coordinator 校验 receipt 与 commit ref 的 plan SHA-256 和 idempotency key，再观察目标并写 checkpoint authority。未绑定 receipt、registry 漂移、授权过期/变化、durable snapshot 漂移或 heartbeat lease 丢失都不会被写成成功；
- Compose 的 `projection-recovery` profile 新增 `GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY`，默认值明确为 `disabled`。`main-compose-dev` 规范化配置指纹更新为 `743220d848b7f6d4ccf655bbccd52e3b15133c0c0025a462762a481af2e0da0a`；migration catalog 没有新增 schema，仍为 172 项，fingerprint 仍为 `03eb949a733fc94c1406bd1656647f32ad1006d2ad206ef957f922c70c28ea76`；
- 隔离临时 PostgreSQL 16 演练仍实际执行 092/094/102/103/169/170/171/172，并由 `28/28` 扩展为 `31/31`。新增实测覆盖默认关闭不产生 callback、批准后只重放原 sealed plan、执行前重新核对数据库授权与 durable snapshot，并验证最终 checkpoint。联合回归为 `107 passed, 2 skipped`，Ruff 与 Compose 校验通过；报告内部 SHA-256 为 `38902fd18b3e9105a9a5ea788c07623f1a6084a6330f2fcf1b336bfe617d4bad`，文件 SHA-256 为 `fd7c2c72403819bf35a988fba152c421c582466a768fe45cc4ddbacae680618b`，数据库范围仍严格标记为 `temporary_database_only`。

因此，“已有精确批准但 recovery worker 完全没有可执行的技术补偿路径”不再是未实现项；当前实现的是受控技术补偿策略执行器，不是通用 Action runtime，也不是客户业务补偿规则。本节形成时尚未实现补偿候选生成；后续 8.43 已补齐绑定源快照的技术候选生成、只读对账推荐和 PostgreSQL 权威，但客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、变更型自动选择/执行、真实五类 Provider 联动故障、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面权限闭环、通用 Proposal/Action runtime 和自动语义融合仍未完成。该 ApprovalCase 仍只是技术授权合同；结果仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`，不代表专家审定、领域规则批准、生产恢复认证、客户生产验收、法定审批或行政决定。

### 8.34 补偿执行意图、持久 receipt 与 Provider/ledger 崩溃窗口封闭

8.33 已能在精确批准后执行原 sealed plan，但仍存在一个必须封闭的进程崩溃窗口：Provider 已提交、recovery ledger 尚未写入时，旧 worker 若立即退出，下一任 worker 不能仅凭原等待 snapshot 再次调用 Provider。本轮新增迁移 `173_projection_recovery_compensation_execution.sql` 处理该风险，范围仍限定为重庆客户数据和 `natural-resource-one-map 2.3.0`：

- 新增 append-only `cross_store_projection_compensation_event`。每个已消费 ApprovalCase 只能形成一个确定性 compensation attempt，事件 1 固定为 `started`，事件 2 只能是 `succeeded`、`failed_known` 或 `failed_unknown`；表启用租户 RLS、强制 RLS、不可变 UPDATE/DELETE trigger，gateway 只有 SELECT，不能直接 INSERT/UPDATE/DELETE；
- `begin_projection_recovery_compensation` 在 Provider 副作用前按 ApprovalCase advisory lock 重新核验 tenant、job、worker、有效 lease generation、resume event、原等待 snapshot、plan SHA-256、幂等键、当前 durable recovery snapshot 和策略。只有首次调用可写 `started`；若发现已有 `started` 但没有终态，返回 `indeterminate`，worker 进入人工对账，不自动重放；
- `finish_projection_recovery_compensation` 继续受当前 worker/lease generation 和 snapshot fencing。成功时持久保存最小 provider commit ref 及其 canonical receipt SHA-256；已知未提交错误和未知结果分别保存 `failed_known` / `failed_unknown`。同一终态仅允许完全相同的幂等重放，证据差异 fail-closed；
- 新 worker 在原 recovery snapshot 尚未推进但已存在 `succeeded` 时，只从 authority 恢复 plan-bound receipt，交给原 coordinator 写 `provider_committed -> authority_committed`，不会再次调用 Provider；`started-only`、失败终态、receipt 哈希不符、租约丢失或 snapshot 漂移都不能静默恢复为成功；
- 临时 PostgreSQL 16 演练实际执行 092/094/102/103/169/170/171/172/173，并由 `31/31` 扩展为 `33/33`。新增实测在 Provider 成功并写入 `started+succeeded` 后、recovery ledger 更新前模拟 worker 崩溃和 lease 过期；新 lease generation 完成 checkpoint，Provider 执行次数保持为 1。同时验证 gateway 不能伪造 compensation execution evidence。联合回归为 `111 passed, 2 skipped`，Ruff、Compose 与迁移 profile 校验通过；演练内部 SHA-256 为 `047fe05b598b7f76d754b2bfb4acca39abb0e317e6fd689fe0c4b1bfd336f6ac`，文件 SHA-256 为 `bb0bf81386e65f650579766a1a8f69601b4448b3d034da591055fad847429f1c`，范围仍为 `temporary_database_only`；migration catalog 为 173 项，fingerprint 为 `47c6f30fb304f68845accbc6ac7f38aa20a015a86cb9f12c9200871db9e64948`。

因此，“Provider 已成功但 ledger 未写时会被下一 worker 静默重复补偿”的控制面缺口已封闭；这依赖各 Provider 原有 plan-bound idempotency 和 commit receipt 合同，但不宣称跨五类存储分布式原子事务。`started-only` 仍需人工观察实际目标后，由新的 snapshot 和新的 ApprovalCase 决定下一步，系统不会代替客户做业务对账判断。剩余需求仍是领域化 rollback/delete/restore/corrective-forward/reconciliation 规则与方案选择、真实五类 Provider 故障及联动注入、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面权限、通用 Proposal/Action runtime，以及自动语义规划融合。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表专家审定、生产恢复认证、客户验收、法定审批或行政决定。

### 8.35 started-only 补偿的人工核对裁决与受控恢复

第 8.34 节已经阻止 `started-only` 尝试被下一任 worker 自动重放，但原状态此前只有“阻塞”出口。本轮新增迁移 `174_projection_recovery_compensation_reconciliation.sql` 和对应 Repository/契约，仍只使用重庆客户数据与 `natural-resource-one-map 2.3.0`：

- 新增租户隔离、append-only `cross_store_projection_compensation_reconciliation_event`。一次 started-only 尝试只能有一条核对裁决，裁决必须引用原 compensation attempt、原 ApprovalCase、原 job、等待 snapshot、plan SHA-256、幂等键及一个可追溯观察引用；gateway 只有 SELECT，不能直接写入或删除核对证据；迁移使用 `SECURITY DEFINER`、强制 RLS 和不可变 trigger；
- 新的核对 ApprovalCase action 分为 `projection.recovery.compensation.reconcile_committed` 与 `projection.recovery.compensation.reconcile_not_committed`，目标 URN 固定为该 compensation attempt，fingerprint 由原 attempt 证据计算。ApprovalCase request context 还必须绑定 attempt、原执行审批、观察人、观察引用、观察 SHA-256、裁决类型；提交回执时同时绑定 receipt SHA-256 和 plan/idempotency key；
- `provider_committed` 只能由人工观察后确认，数据库将原 `started` 封存为 `succeeded`、保存 plan-bound Provider receipt 并将 job 重新排队。恢复 worker 只从该持久 receipt 推进 recovery ledger，Provider 执行次数保持为 0；`provider_not_committed` 将原 attempt 封存为 `failed_known`，任务保持 `waiting_operator`，必须消费新的 `projection.recovery.compensate` ApprovalCase 才能创建下一次 sealed-plan 尝试；
- 受控 PostgreSQL 16 演练实际执行 092/094/102/103/169/170/171/172/173/174，新增检查后共 `37/37` 通过：started-only 不热重试、已提交核对零 Provider 重放、未提交核对必须新审批、gateway 不能伪造核对证据。专项联合回归 `122 passed, 2 skipped`，Ruff 与迁移 profile 校验通过；演练内部 SHA-256 为 `ffbd43f3822901a0f40ce63cf554775fa476e727e8079a98b24bdd56c33592dc`，文件 SHA-256 为 `d9439689317affbbbf46260379810f8f4f83ddb5f674d5085ec3c14492ec7050`，范围仍为 `temporary_database_only`；migration catalog 为 174 项，fingerprint 为 `2e948f44f691cd0f24500ceb89eeb1635abb04d5b40f010786226e512a634bcc`。

因此，“Provider 结果未知后只能无限阻塞、没有可审计人工核对出口”的控制面缺口已推进为受控技术基线；仍没有替客户定义实际业务 rollback/delete/restore/corrective-forward/reconciliation 规则，也没有宣称 Provider/ledger 分布式原子事务。人工裁决的 ApprovalCase 是技术授权合同，不代表专家审定、领域规则批准、生产恢复认证、客户生产验收、法定审批或行政决定。真实 PostGIS、pgvector、Fuseki、MinIO、Iceberg 故障及联动注入、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍是后续需求；状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.36 真实 PostGIS Provider receipt 与提交后故障恢复

本轮把此前主要由测试 Provider 替身覆盖的一个关键故障窗口推进到真实临时 PostgreSQL 16 + PostGIS。新增迁移 `175_postgis_projection_provider_receipt.sql`，在 PostGIS 目标表变更的同一数据库事务中写入租户隔离、append-only 的 Provider receipt，receipt 绑定 PostgreSQL transaction ID、sealed plan SHA-256、幂等键、目标内容哈希、行数和状态；receipt UPDATE/DELETE 被数据库 trigger 拒绝，gateway 不能读取该 Provider 账本。

executor、service 和 recovery worker 现在优先读取该 receipt：authority 写入失败或客户端在 Provider commit 后收到未知异常时，重启后的 worker 先验证 receipt 与当前目标完全一致，再只写 checkpoint authority，Provider 执行次数保持为 0；receipt 缺失、目标漂移、receipt 哈希或 plan 绑定不一致时，保持人工核对，不自动重放。数据库 backend 在 Provider 事务提交前被实际终止时，目标表和 receipt 均回滚。

临时 PostgreSQL 16 + PostGIS 演练实际执行 092/094/169/175，`17/17` 检查通过，覆盖同事务 receipt、receipt 不可变、gateway 隔离、真实数据库断连回滚、提交后未知异常重启零重放和 receipt/目标不一致人工阻断。专项单测与 recovery/queue 联合回归为 `138 passed, 2 skipped`；最新 PostGIS 演练内部 SHA-256 为 `acaf849cf1458516534a908af9074f877380c3292c44bd4149c3592877a4849d`，文件 SHA-256 为 `93a83c73006ebea4195d7a060609f753ec9735b3b8eafd72a0a970731dbd90b8`；跨存储 recovery 演练仍为 `37/37`，最新内部 SHA-256 为 `b0654d537b869a84eb122e5191573b90f8eb8d203a4727c827afe1c6e58ab188`，文件 SHA-256 为 `2fae2f0205a11f48280d0059d0ba0119808bf86b385da419c579740b6db6f87b`。两者范围均为 `temporary_database_only`；migration catalog 为 175 项，fingerprint 为 `7ed2f704ec12572f660700be38851a9c28e66293d6e05fa131060ce59c350b1c`。

这关闭了 PostGIS Provider 在“目标已提交但 authority 未落账/客户端结果未知”场景下缺少同事务证据和零重放恢复的技术缺口，但不等于五类存储已经完成真实故障联动验收。pgvector 的同类缺口已由 8.37 补齐；仍未完成的包括 Fuseki、MinIO/S3、Iceberg 的同类真实断连/网络分区/硬杀与 receipt 恢复，备份/PITR、RPO/RTO、容量、恢复时间、生产 SLO、客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、全执行面安全闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义融合。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

### 8.37 真实 pgvector Provider receipt 与提交后故障恢复

本轮把 8.22 中 pgvector 的普通事务执行和 checkpoint 串联，推进为与 PostGIS 相同的提交后零重放恢复技术基线。新增迁移 `176_pgvector_projection_provider_receipt.sql`，在重庆客户向量目标变更的同一 PostgreSQL 事务中写入租户隔离、append-only 的 Provider receipt。receipt 绑定 PostgreSQL transaction ID、sealed plan SHA-256、幂等键、目标内容哈希、行数和状态；数据库 trigger 拒绝 UPDATE/DELETE，`gda_control_gateway` 无读取权限。数据范围仍只使用重庆客户记录，本体固定为 `natural-resource-one-map 2.3.0`，未引入宁夏或 Excel。

`VectorProjectionRepairExecutor` 新增 plan-bound receipt 读取、指纹核验和目标一致性复核；`vector_projection_service` 在 authority 尚无 checkpoint 时先恢复 receipt，只有 receipt 不存在才执行 Provider。authority 首次写入失败或客户端在 Provider commit 后得到未知结果时，新进程会读取持久 receipt、复核当前向量目标并只补 checkpoint，Provider 执行次数保持为 0；receipt 缺失、plan 绑定不一致或目标漂移均转人工核对，不自动重放。

临时 PostgreSQL 16 + pgvector 0.8.2 演练实际执行 092/094/169/176，`17/17` 检查通过，覆盖同事务 receipt、receipt 不可变、gateway 隔离、提交后未知异常跨 executor 实例恢复且零 Provider 重放、receipt/目标漂移人工阻断，以及实际 `pg_terminate_backend` 导致目标和 receipt 同时回滚。封存报告 `docs/reports/vector_projection_executor_rehearsal_2026-08-15.json` 的内部 SHA-256 为 `9a207216330c5ae0a78474a56d7b43303328625e1f040d0ca243afa6295582b2`，文件 SHA-256 为 `f35a89f7c99ffd623ab9d03775511915abbdea1de794b7f907a98807c6b4b7ca`，范围为 `temporary_database_only`。五类 Provider、recovery、迁移和部署 profile 联合回归为 `146 passed, 2 skipped`；migration catalog 为 176 项，最新迁移为 `176_pgvector_projection_provider_receipt`，fingerprint 为 `c4f138dd367fc61f0479cb0fd97ff704e0ffc086af98331d5c2f3e82215a579d`。

因此，pgvector 在“目标已提交但 authority 未落账/客户端结果未知”场景下缺少同事务证据和自动重放风险不再是未实现需求。当前真实 receipt/故障恢复仍未覆盖 Iceberg，也没有完成多 Provider 联动故障、生产备份/PITR、RPO/RTO、容量、恢复时间或客户 SLO。客户业务补偿/对账规则、全执行面安全闭环、通用 Proposal/Action runtime 和自动语义规划融合仍需继续建设。状态保持 `technical_baseline_unreviewed`，用途保持 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

### 8.38 真实 Fuseki Provider receipt 与提交后未知异常零重放

本轮把 RDF/Fuseki 从“有 plan-bound Graph Store 执行和 checkpoint”推进为同一 Fuseki UpdateRequest 内的目标提交证据与零重放恢复。范围仍限定为重庆客户数据与固定自然资源本体 `natural-resource-one-map 2.3.0`，不引入宁夏或 Excel：

- RDF target 合同升级为 v2，注册表必须显式登记 `sparql_update_endpoint`，且它与 Graph Store endpoint 使用同一 origin；执行器拒绝客户端临时 endpoint、凭据或目标参数；
- rebuild 在 Fuseki staging named graph 写入本次 sealed plan 的完整三元组，再用单次 SPARQL UpdateRequest 原子执行 `COPY staging -> DEFAULT`、删除 staging 并写入 provider receipt named graph；delete 使用 `DROP DEFAULT` 与 receipt 写入的同一 UpdateRequest。receipt 绑定 tenant、projection、target、action、plan SHA-256、幂等键、目标内容哈希、三元组数及自身 SHA-256；checkpoint action 只写 receipt graph，不重建目标；
- service/worker 在 authority 没有 checkpoint 时先读取 Fuseki receipt graph，并重新观察当前 RDF 目标。receipt 与目标完全一致时只补 checkpoint；只有 receipt 不存在才调用 Fuseki Provider。客户端在 Fuseki commit 后收到未知异常、authority 首次失败或进程重启时，重建 executor 也不会重复执行 Provider；receipt 缺失、receipt/目标漂移或绑定不一致保持人工核对，不自动重放；
- 新增演练检查 staging graph 提交后清理、receipt 与目标同一 UpdateRequest 的原子性、authority 失败后的 receipt 恢复、delete receipt 证明目标缺失、提交后未知异常跨 executor 实例零重放，以及 receipt/目标漂移人工阻断；临时 PostgreSQL 和 Fuseki 容器/卷均在演练后删除；
- 真实隔离 Fuseki 演练 `20/20` 通过，实际装载 `537,245` 条自然资源本体三元组。报告 `docs/reports/rdf_projection_executor_rehearsal_2026-08-15.json` 的内部报告 SHA-256 为 `e951157dae0b514d655202d3ff9b7b14a9d3723a2e054a6e87a3092da0074a25`，文件 SHA-256 为 `00a3b36de97f0ab443ea8ccedc0a05810871d1bb0c537120a64ac663e98e5f2e`；范围为 `temporary_database_only` + `temporary_container_and_volume_only`，状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`。
- 五类 Provider/recovery/deployment profile 联合回归当前为 `163 passed, 2 skipped`；该回归包含 RDF 新增测试以及 PostGIS、pgvector、S3/MinIO、Spark/Iceberg、recovery、迁移和部署合同检查。

因此，Fuseki 在“目标已提交但 authority 未落账/客户端结果未知”场景下缺少原生 receipt、提交后恢复和零重放控制的技术缺口已关闭。当前剩余的同类 Provider receipt/真实故障恢复只包括 MinIO/S3 与 Iceberg；此外仍未完成多 Provider 联动故障、生产备份/PITR、RPO/RTO、容量、恢复时间、客户 SLO、客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、全执行面安全闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义规划融合。该演练不代表 Fuseki 生产部署、跨存储分布式原子事务、专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

### 8.39 真实 MinIO/S3 Provider receipt 与提交后未知异常零重放

本轮把对象存储从“VersionId/ETag/delete marker 只在调用返回值中可见”推进为可跨进程恢复的 Provider 原生证据，范围仍限定为重庆客户 artifact 与固定自然资源本体 `natural-resource-one-map 2.3.0`：

- rebuild 将 plan SHA-256、幂等键、action 和 receipt SHA-256 写入目标对象的 S3 user metadata；数据和这组 plan-bound receipt metadata 在同一个 `PutObject` 中提交，因此客户端在上传提交后收到未知异常时，重启 executor 可以直接从目标对象 metadata 恢复 receipt，不会再次上传对象；
- delete 先在同一版本化 bucket 写入 plan-bound intent object，再执行 `DeleteObject` 生成 delete marker。intent 绑定删除前 VersionId、ETag、内容哈希、大小、plan SHA-256 和幂等键；恢复时必须同时观察目标缺失、最新 delete marker 存在且删除前版本证据精确匹配，才构造已提交 receipt。若目标仍是删除前版本或版本链不一致，则保持人工核对，不自动重删；
- object service 改为 receipt-first：authority 没有 checkpoint 时先调用 `recover_receipt()`，receipt 与目标/版本证据一致才补 checkpoint，receipt 不存在才执行 Provider；目标内容碰巧一致但缺少 plan-bound receipt 时 fail-closed，不把“内容相同”当作提交证明；
- 新增真实临时 MinIO + PostgreSQL 演练检查 bucket versioning、rebuild metadata receipt、authority 失败后的 executor 重启零重放、same-content 新版本漂移、checkpoint action、stale predecessor、delete intent + marker 恢复、delete checkpoint/replay、append-only history 及资源清理；`19/19` 检查通过，客户 artifact 实际写入 `1,950,576` 字节；
- 封存报告 `docs/reports/object_projection_executor_rehearsal_2026-08-15.json` 为 schema v2，内部报告 SHA-256 为 `d76f5b8797f299b5edabbb6ad47f90bcbabdbe2557f4bf9702b7b298b1588023`，文件 SHA-256 为 `5c48325e8674b6f5f4579684cb1645a929bb8252f5685cd264debe7488ae8bf7`；范围为 `temporary_database_only` + `temporary_container_volume_and_bucket_only`，状态仍为 `technical_baseline_unreviewed`，用途仍为 `assisted_precheck_not_for_production_decision`；
- 五类 Provider/recovery/deployment profile 联合回归当前为 `166 passed, 2 skipped`。

因此，MinIO/S3 在“目标已提交但 authority 未落账/客户端结果未知”场景下缺少 provider-native receipt、delete 版本证据和零重放恢复的技术缺口已关闭。S3 的 rebuild receipt 与对象数据在单个 `PutObject` 内原子提交，但 delete intent、delete marker 和 PostgreSQL authority 仍不是跨对象/跨存储分布式事务；这不代表 MinIO 生产验收或灾备认证。当前同类 receipt/真实故障恢复只剩 Iceberg。另有多 Provider 联动故障、生产备份/PITR、RPO/RTO、容量、恢复时间、客户 SLO、客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、全执行面安全闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义规划融合仍未完成。

### 8.40 真实 Spark/Iceberg Provider receipt 与提交后未知异常零重放

本轮关闭五类 Provider 中最后一个“目标已提交但 checkpoint authority 未落账/客户端结果未知”时缺少原生提交证据的技术缺口，范围仍只使用重庆客户数据和固定本体 `natural-resource-one-map 2.3.0`：

- rebuild 将 plan SHA-256、幂等键、action 和 receipt SHA-256 写入 Iceberg 当前 snapshot summary，数据文件、表替换和 receipt 属于同一次 Iceberg commit；恢复时重新读取当前 snapshot summary、snapshot ID、目标内容指纹和行数，receipt 不绑定漂移后的 snapshot；
- delete 保留 warehouse 中的 plan-bound tombstone，并补充 receipt schema、action、plan、幂等键和 receipt SHA-256。只有表缺失、删除前 snapshot、drop evidence、tombstone 和 receipt 全部相符时才认定已提交；
- executor 提供 `recover_receipt()`，service 在 authority 无 checkpoint 时先恢复 Provider receipt，receipt 不存在才调用 Spark Provider。authority 首次失败或 executor 重启不会再次创建表；同内容但无本次 plan receipt 时 fail-closed；
- 真实隔离演练 `18/18` 通过，物化 445 个 feature、439 个 `parcel_id`，验证 receipt 跨 executor 恢复、零 Provider 重放、同内容新 snapshot 漂移拒绝、checkpoint、delete 恢复、append-only history 和临时资源清理。报告 `docs/reports/lakehouse_projection_executor_rehearsal_2026-08-15.json` schema v2，内部报告 SHA-256 为 `53fa9c2cf5edd5c95ff829e33e09ecef28ee8775ca3c0ca447464ffa09bffecd`，文件 SHA-256 为 `1d4acc49faff1c835ce8f5eaaff42eb8e5818fea351c53250de2cb4cd50a9a44`；范围为 `temporary_database_only` + `temporary_network_container_volume_bucket_and_table_only`；
- 本轮显式运行的 Provider/recovery/deployment profile 集合为 `147 passed, 2 skipped`，包括五类 Provider、recovery、迁移和部署合同；Iceberg 专项为 `7 passed`。

因此，PostGIS、pgvector、RDF/Fuseki、MinIO/S3 和 Spark/Iceberg 五类 plan-bound Provider 均已具备受控 receipt、checkpoint 串联和提交后未知结果零重放技术基线，单一 Provider 缺失不再是剩余需求。当前仍未完成的是多 Provider 真实联动故障与自动补偿/对账执行、客户定义的 rollback/delete/restore/corrective-forward/reconciliation 规则、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime，以及 Ontology/Metric/NL2SQL/GIS/RAG 自动语义规划融合。Iceberg commit 与 PostgreSQL authority 仍不是分布式原子事务；本轮不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.41 多 Provider 联动故障与恢复编排合同（内存 rehearsal）

本轮把第 8.40 节列出的“多 Provider 真实联动故障与自动补偿/对账执行”拆成一个可先行验证的编排合同，仍只使用重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0`，不引入宁夏或 Excel：

- 新增 `data_agent/cross_store_projection_federated_recovery.py`，定义 federated run、item、event、snapshot 和 append-only aggregate ledger。一个 run 绑定同租户、唯一且有序的 2-32 个 `ProjectionRepairPlan`，按 sealed plan 顺序复用现有 `ProjectionRecoveryWorker`，不复制单 Provider 状态机；已完成的前序 plan 记录在 `committed_plan_sha256s`，不宣称全局事务或自动回滚；
- authority 短暂失败只推进单 plan 的 authority retry，不重放 Provider；未知 Provider 结果先尝试精确 `recover_receipt()`，receipt 不存在或目标漂移则进入 `compensation_required`，后续 Provider 不会启动；明确已知未提交错误在 Provider attempt budget 耗尽后整体 `failed_closed`；
- durable per-plan recovery ledger resolver 是重启续跑前置条件。聚合 ledger 与每个 plan 的 worker snapshot SHA-256、item/event/snapshot 指纹、租户边界、plan 顺序、不可回退的 attempt counter 和 committed 状态均校验；状态机对 `RECOVERY_REQUIRED`、`COMPENSATION_REQUIRED`、`FAILED_CLOSED` 和完成游标 fail-closed；最近错误证据在后续成功事件后仍保留；
- 新增 `data_agent/test_cross_store_projection_federated_recovery.py`，`8/8` 通过：三个不同 Provider 顺序完成、authority fail-once 零 Provider 重放、未知结果 receipt 恢复、无 receipt 阻止第三个 Provider、已知未提交重试耗尽、相同 aggregate/per-plan ledger 重启续跑、跨租户/重复 plan/run identity 拒绝，以及 item/event/snapshot 指纹和状态合同篡改拒绝。Ruff 通过；显式 projection/recovery/provider 回归 `115 passed`，PostgreSQL rehearsal 合同 `5 passed, 2 skipped`；
- 本轮证据范围是 `in_memory_federated_orchestration_only`。尚未对 PostGIS、pgvector、Fuseki、MinIO/S3、Spark/Iceberg 同时实施网络分区、进程硬杀、未知回执、队列积压或真实跨存储联动注入；没有跨存储分布式事务、自动业务补偿、客户 reconciliation 规则、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO 证明。

因此，“多个已分别具备 receipt 的 Provider 能否按固定计划顺序安全停住、恢复和续跑”已经有可重复的技术合同和负向测试，未被实现的是五类真实存储的联动故障实验、领域化补偿/对账决策及生产运维认证。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

### 8.42 Federated aggregate ledger PostgreSQL 持久化与重启续跑

第 8.41 节的 aggregate ledger 只在内存中，本轮将其推进到真实临时 PostgreSQL 控制面，仍只使用重庆客户 sealed plan 和自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增迁移 `177_cross_store_projection_federated_recovery_ledger.sql`，建立租户隔离、append-only 的 federated event/snapshot history 和 current view。唯一写路径是 `SECURITY DEFINER` 函数，启用并强制 RLS，event/snapshot UPDATE/DELETE 被不可变 trigger 拒绝，gateway 只有 SELECT 和受控函数 EXECUTE，没有表 INSERT/UPDATE/DELETE；
- 新增 `PostgresFederatedProjectionRecoveryLedger`，按 tenant + run 读写 Pydantic 验证后的聚合快照。写入校验 2-32 个唯一 plan SHA-256、固定 plan 顺序、连续 event sequence、完整历史前缀、最新 event、snapshot/event 指纹和幂等重放；跨租户读取为空，跨租户写入在数据库访问前拒绝；
- 真实联动测试还发现并修复了 170 号单 plan ledger 的既有误冲突：`ProjectionRecoveryEvent` 指纹不包含 plan 身份，但数据库此前把 event SHA-256 设为 tenant 级唯一。177 号后继迁移把唯一键和查重范围改为 `tenant + plan + event_sha256`，两个 plan 在同一时间产生相同 `planned` 事件不再互相阻塞，同时同一 plan 内的 append-only/idempotency 约束保持不变；没有改写已冻结的 170 号迁移文件；
- 隔离临时 PostgreSQL 实测使用随机数据库和随机运行角色，结束后强制删除。测试先让第二个 plan 的 authority fail-once，在 aggregate/per-plan PostgreSQL ledger 中形成 `run_yielded`，再以新 repository/coordinator 实例重载并完成第三个 plan；第二个 Provider 执行次数保持为 1。同时验证 current/history、同快照幂等、跨租户隐藏和伪造 snapshot SHA 被 append-only 冲突拒绝；真实数据库文件 `4/4` 通过；
- 常规显式 projection/recovery/provider/migration/deployment profile 集合为 `148 passed, 1 skipped`，唯一跳过项是在未配置 `DATABASE_URL` 的常规进程中不运行真实数据库测试；单独配置本机临时 PostgreSQL 后该文件 `4 passed`。Ruff 和 migration/deployment profile 校验通过；迁移目录为 177 项，最新项为 `177_cross_store_projection_federated_recovery_ledger`，fingerprint 为 `538ad13052887026453a27a14f89a8009df47105e9b8ee15bb1ec6722f8a0c5c`。

因此，8.41 的 `in_memory_federated_orchestration_only` 已被 8.42 的 `temporary_database_federated_control_plane_only` 取代，aggregate ledger 不再是进程内状态。Provider 仍为测试替身，本轮没有同时操作真实 PostGIS、pgvector、Fuseki、MinIO/S3 和 Spark/Iceberg，也没有证明跨存储分布式事务、自动业务补偿、客户 reconciliation 规则、备份/PITR、RPO/RTO、容量/恢复时间或生产 SLO。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`，不代表生产恢复认证、客户验收、专家审定、法定审批或行政决定。

### 8.43 绑定源快照的补偿候选方案与 PostgreSQL 只追加权威

在没有领域专家即时审定、但研发不能停下的约束下，本轮把“补偿方案完全没有系统产物”推进为保守的技术预案能力。范围仍只使用重庆客户 sealed plan，并精确绑定自然资源本体 `natural-resource-one-map 2.3.0` 的 package/content SHA-256：

- 新增 `cross_store_projection_compensation_proposal.py`。输入只能是已阻塞的 federated snapshot 与其原始有序 sealed plan，输出绑定 tenant、run、源 snapshot SHA-256、阻塞位置、全部 plan/source content SHA-256、目标和本体包；同一证据生成相同 proposal SHA-256，生成器不调用 Provider；
- 候选集合有界为 3-6 项，覆盖 `reconcile_provider_outcome`、`approved_reapply_sealed_plan`、`corrective_forward`、`rollback_committed_prefix`、`delete_target` 和 `restore_target`。系统只自动推荐无副作用的 receipt/目标观察对账；原 sealed plan 重放明确要求 `provider_not_committed` 裁决、fresh ApprovalCase、durable worker snapshot 和目标身份一致，且不会被自动推荐；
- corrective-forward/rollback/delete/restore 在缺少客户规则时全部标为 `customer_rule_required`，并输出精确缺口 ID，例如 `customer.compensation.rollback.v1`。方案固定 `execution_allowed=false`、`automatic_mutating_selection_allowed=false`、`technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`；`failed_closed` 不生成任何系统推荐；
- 新增迁移 `178_cross_store_projection_compensation_proposal.sql` 和 `PostgresFederatedProjectionCompensationProposalStore`。proposal 以 federated snapshot 为数据库外键，同一 tenant/run/snapshot 只允许一个确定性方案；唯一写入口为 `SECURITY DEFINER`，强制 RLS、不可变 UPDATE/DELETE、gateway 无表写权限，并校验重庆数据范围、本体包、候选数量、推荐非变更性和审批边界；
- 专项合同与 authority 常规测试为 `9 passed, 1 skipped`；显式 projection/recovery/provider/migration/deployment profile 联合回归为 `167 passed, 4 skipped`。配置本机开发 PostgreSQL 后，authority 文件 `4 passed`，覆盖源快照外键、幂等重放、current/history、跨租户隐藏和伪造 `execution_allowed=true` 拒绝；随机临时数据库/角色清理后残留为 0。Ruff 与本轮文件 `diff --check` 通过；迁移目录为 178 项，最新项 `178_cross_store_projection_compensation_proposal`，fingerprint 为 `12a29037a5c568cce86a1eee2cf7e7092740213fe88abaf6ba576704e2251b91`。

因此，“系统完全不能生成、排序和持久化任何补偿候选”不再是准确描述；当前已经能生成审计型技术预案，并安全推荐先做只读对账。但这不是客户业务规则，也不是变更型补偿的自动选择或执行。仍未完成的是由客户确认的 rollback/delete/restore/corrective-forward/reconciliation 规则及版本、这些规则驱动的多 Provider 自动补偿执行、五类真实 Provider 联动故障注入、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全闭环、通用 Proposal/Action runtime，以及自动语义规划融合。本轮范围可表述为 `temporary_database_compensation_proposal_only`，不代表专家审定、客户生产验收、生产恢复认证、法定审批或行政决定。

### 8.44 补偿方案的受治理 REST、Capability 与 MCP 只读入口

第 8.43 节的确定性方案生成器和 PostgreSQL 只追加权威已经存在，但 GIS Data Agent 操作员和 Agent 尚无统一受治理入口。本轮将生成能力接入现有多表面合同，仍只接受重庆客户 sealed plan、federated recovery snapshot 和自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增严格请求合同 `FederatedProjectionCompensationProposalRequest`，只包含原始有序 plans 与 snapshot；plan 数量、顺序、SHA-256 和 tenant 必须与 snapshot 完全一致。请求不能额外提交 tenant、执行开关、候选选择、审批结论、Provider 目标或凭据，任何额外字段均被拒绝；
- 新增 `POST /api/platform/v1/projections/federated/compensation-proposals`。平台从认证主体取得 tenant 和 `admin/platform_operator` 角色，拒绝跨租户快照，并支持 `X-GDA-Capability-Fingerprint` 合同漂移检查。该路由只调用确定性生成器，返回标准 platform envelope，不持久化、不调用 Provider；
- 新增 CapabilitySpec `projection.federated.compensation-proposal@1.0.0`，声明 `QUERY`、`SideEffect.NONE`、同步返回、无需幂等键，并将同一 JSON Schema 投影到 HTTP 和 MCP；新增 MCP 工具 `generate_federated_projection_compensation_proposal`，tenant/role 只能来自 MCP context，工具标注 `readOnlyHint=true`、`destructiveHint=false`；
- REST/MCP/Capability 专项覆盖成功、租户覆盖、跨租户、角色不足、缺少 MCP tenant、能力指纹漂移、只读 annotation 和 Provider 零调用；五类投影、联邦恢复、补偿、能力注册与平台路由联合回归为 `198 passed, 2 skipped`。

因此，“补偿技术预案只能由内部代码生成，Agent/操作员没有受治理读取入口”不再是剩余需求。这里新增的是非执行型查询表面，不是补偿 Action：`execution_allowed=false`、`automatic_mutating_selection_allowed=false`、`technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision` 均保持不变。内部如需保存方案仍必须使用第 8.43 节的 PostgreSQL authority；公共查询入口不会隐式写入。客户规则版本、变更型候选的规则驱动选择/批准/执行、真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量和生产 SLO、全执行面 Subject-Purpose-Resource 安全、通用 Proposal/Action runtime 及自动语义规划融合仍未完成。

### 8.45 PostgreSQL 补偿方案权威的受治理 current/history 查询

第 8.44 节开放的是“根据 sealed evidence 即时生成但不持久化”的只读入口；第 8.43 节已经持久化的 authority current/history 仍只有内部 Python 方法。本轮补齐持久方案的受治理读取面，继续限定为重庆客户数据和自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增 `FederatedProjectionCompensationProposalReadRequest/Response`。请求只有 federated `run_id`，不能携带 tenant；响应强制 current 等于不可变 history 最后一项、history count 一致、全部 proposal 属于认证 tenant/run，且顶层和每项 `execution_allowed` 均为 false；
- `PostgresFederatedProjectionCompensationProposalStore.lookup()` 使用一条参数化 SQL 同时读取 current 与按 authority 顺序排列的完整 history，避免两个独立 READ COMMITTED 语句在并发写入时观察到不同时间点。查询继续通过 gateway role、`app.current_tenant`、RLS 和 security-invoker view，不新增迁移或表写权限；
- 新增 `GET /api/platform/v1/projections/federated/compensation-proposals/{run_id}` 和 CapabilitySpec `projection.federated.compensation-proposal.get@1.0.0`，声明 `QUERY + SideEffect.NONE`。路由 tenant/role 只来自认证主体，拒绝额外 query 参数和 Capability fingerprint 漂移；不存在返回 404，authority 配置/连接不可用返回 503，不能把数据库故障误报为“无方案”；
- 新增 MCP 工具 `get_federated_projection_compensation_proposal`，唯一参数是 `run_id`，tenant/role 只来自 MCP context；返回当前方案与完整历史，不记录、不选择、不批准或执行候选；
- REST/MCP/Capability/模型负向测试覆盖 current/history 一致性、tenant 参数注入、not-found 与 unavailable 区分、只读 annotation 和 authority 调用边界。五类投影、恢复、补偿、能力及平台路由联合回归为 `202 passed, 2 skipped`；配置本机临时 PostgreSQL 后 authority 专项 `4 passed`，覆盖真实 lookup、跨租户空结果和清理。

因此，“已持久化补偿方案无法由操作员或 Agent 通过受治理表面读取”不再是剩余需求。公共 POST 生成入口仍不写库，新增 GET/MCP 也只有 SELECT；系统仍没有公共 proposal 写入口，更没有变更型补偿执行入口。客户 rollback/delete/restore/corrective-forward/reconciliation 规则版本、规则驱动的候选选择/批准/执行、真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量和生产 SLO、全执行面安全、通用 Proposal/Action runtime 与自动语义规划融合仍未完成。状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.46 客户补偿规则版本合同与只读就绪度评估

在暂时没有专家现场审定、但研发仍需推进的约束下，本轮没有编造客户 rollback/delete/restore/corrective-forward/reconciliation 语义，而是先建立可由客户规则逐步填充的严格合同和只读评估面。范围继续固定为重庆客户数据与自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增 `cross_store_projection_compensation_rule_contract.py`，定义规则 ID、语义版本、补偿 action、重庆数据范围、精确本体 package/content SHA-256、适用 `ProjectionEngine + target_ref`、必需证据、是否变更 Provider、审批要求和规则生命周期。合同只接受 `draft_unreviewed`、`awaiting_customer_approval`、`customer_approved`；任何规则均固定 `automatic_mutating_selection_allowed=false` 和 `execution_allowed=false`；
- `customer_approved` 不能只靠一个状态字符串声明，必须附带绑定 rule ID/version/SHA-256 的客户权威主体、批准 artifact SHA-256、签名算法、key ID、公钥指纹、规范化签名载荷和 detached signature；合同会实际执行 Ed25519、ECDSA P-256 或 RSA-PSS 验签，失败即拒绝。当前仓库没有内置、播种或推定任何客户已批准规则，真实客户签署仍待提供；
- 新增确定性评估器，把 proposal 的每个 `missing_customer_rule_id` 映射为 `missing`、`draft_unreviewed`、`awaiting_customer_approval`、`approved_but_not_executable` 或 `invalid_or_drifted`。评估会核对规则覆盖的目标是否包含候选 sealed plan、是否越出 proposal 目标、所需证据是否完整；在签名验真且部署侧信任根匹配时，批准证据仍只得到 `approved_but_not_executable`，不会自动选择候选；信任根缺失或漂移的边界见 8.47；
- 新增 `POST /api/platform/v1/projections/federated/compensation-rule-assessments`、CapabilitySpec `projection.federated.compensation-rule.assess@1.0.0`（8.47 起为 `1.1.0`）和 MCP 工具 `assess_federated_projection_compensation_rules`。三者复用同一严格合同，tenant/role 仅来自认证或 MCP context，声明 `QUERY + SideEffect.NONE`，执行密码学验签但不持久化规则、不创建批准、不调用 Provider；
- 模型/API 专项 `15 passed`，相关 projection/recovery/provider/capability/MCP/platform 联合回归 `288 passed, 4 skipped`；本轮新增模块、API、Capability 和测试文件的 Ruff、全部受影响模块 Python 编译及 scoped `diff --check` 通过，MCP 注册模块也通过 `py_compile`。跳过项为未配置真实 PostgreSQL 的既有演练，本轮没有数据库迁移。

因此，“完全没有客户补偿规则的数据结构和差距评估入口”不再是剩余需求；当前可以在无专家现场参与时，把客户后续提交的规则逐条封存、核对并明确指出差距。但尚未完成的仍是客户实际签署的规则版本、规则 authority/current/history、规则驱动的变更候选选择、ApprovalCase 绑定及执行。真实五 Provider 联动故障注入、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面 Subject-Purpose-Resource 安全、通用 Proposal/Action runtime 和自动语义规划融合也仍未完成。本轮不代表客户批准、专家审定、生产验收、恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.47 客户审批密钥的部署侧信任根与 fail-closed 评估

第 8.46 节的密码学验签只能证明“提交的签名与提交的公钥匹配”，不能证明该公钥确实属于客户。本轮补上这一安全边界，仍只使用重庆客户数据与自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增 `cross_store_projection_compensation_trust.py`，定义部署侧不可变 trust anchor：tenant、customer authority ref、signature key ID、算法、公钥 SHA-256、`valid_from/valid_until`、`active/revoked` 状态和 anchor 指纹；注册表按 `(tenant, authority, key_id)` 唯一排序并带 registry 指纹，不能从 REST/MCP 请求体提交或覆盖；
- 服务端只从 `GDA_CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_JSON` 加载公钥指纹注册表。环境变量未配置时，缺失/草稿/待批准规则仍可正常评估；但带 `customer_approved` 的证据不能进入批准状态，而是 `invalid_or_drifted` 并返回 `customer_approval_trust_registry_missing`。JSON 损坏、锚点指纹漂移或冲突会返回明确的 trust-registry configuration error；仓库不预置真实客户 key，也不接受私钥；
- `customer_approved` 现在必须同时满足租户、客户 authority、key ID、算法、公钥指纹一致，签名时间和当前评估时间都在有效窗口内，且 key 未撤销。错 key 返回 `customer_approval_key_not_trusted`，撤销返回 `customer_approval_key_revoked`，超窗返回 `customer_approval_key_outside_validity`；任何失败均不选择候选、不调用 Provider；
- 评估输出合同升级为 `gda.federated-projection-compensation-rule-assessment.v2`，逐项显示 `customer_approval_trusted` 和匹配的 trust-anchor 指纹；Capability `projection.federated.compensation-rule.assess` 升为 `1.1.0`。REST/MCP 仍为 `QUERY + SideEffect.NONE`，配置只读、规则不落库、不创建批准；
- 新增 trust registry、未配置、错指纹、撤销、有效期、环境配置错误以及 REST/MCP 负向测试；规则合同/API/trust 专项共 `24 passed`，跨存储 projection/recovery/provider/capability/gateway 联合回归 `271 passed, 4 skipped`。本轮新增模块和受影响模块 Ruff、Python 编译通过；没有新增迁移。

这关闭的是“调用方可自带任意自签公钥并把它描述成客户批准”的技术缺口，不是客户身份认证或客户业务规则本身。仍需客户提供真实签署材料和由部署/安全责任方维护的实际 key 注册表，再建设规则 authority/current/history、规则驱动候选选择、ApprovalCase 绑定和变更执行。真实五 Provider 联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、全执行面安全和自动语义规划融合仍未完成；本轮不代表客户批准、专家审定、生产验收、恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.48 客户补偿规则 authority 的 PostgreSQL current/history 与只读查询

第 8.47 节留下的“规则只能由调用方提交、尚无租户隔离 rule authority/current/history”缺口已推进为技术基线。本轮仍严格限定重庆客户数据集和 `natural-resource-one-map 2.3.0`，不引入宁夏或 Excel：

- 新增 `179_cross_store_projection_compensation_rule_authority.sql` 和 `PostgresCustomerCompensationRuleAuthorityStore`。规则合同以 append-only 历史表保存，current view 从最新记录派生；写入只能通过 `SECURITY DEFINER` 受控函数，表启用 tenant RLS + FORCE RLS、不可变 UPDATE/DELETE trigger，`gda_control_gateway` 只有 SELECT 和受控函数 EXECUTE，没有表 INSERT/UPDATE/DELETE 权限；migration catalog fingerprint 为 `3375b3627aad1cf484c0911a118bf19774ac38dd90b9001509b072c6e1174d9c`，179 号迁移文件 SHA-256 为 `f8de8e0e3f4da177d06686ca49794914cdc00864c948ddbd290a4d944b522483`；
- 数据库函数和表约束再次检查 tenant、rule ID/SemVer、rule/contract SHA-256、重庆数据范围、自然资源本体 `2.3.0` package/content SHA-256、固定 review/intended-use、审批证据形态以及 `automatic_mutating_selection_allowed=false`、`execution_allowed=false`。状态只能按 `draft_unreviewed -> awaiting_customer_approval -> customer_approved` 前进，不能回退；同一 contract SHA-256 完全一致时幂等返回；
- `customer_approved` 写入前仍必须由 Python contract 完成 Ed25519/ECDSA P-256/RSA-PSS 验签，并由部署侧 trust registry 匹配 tenant、客户 authority、key、算法、公钥指纹、有效期和撤销状态。数据库不伪造密码学验签，也没有公开规则写入、批准或执行 API；
- 新增只读 `GET /api/platform/v1/projections/federated/compensation-rules`，可选 `rule_id` 只缩小查询范围；新增 Capability `projection.federated.compensation-rule.get@1.0.0` 和 MCP `get_federated_projection_compensation_rules`。tenant/role 只来自认证或 MCP context，current/history 只读，not-found 与 authority unavailable 分别返回 404/503，所有返回继续固定两个状态字段和执行开关 false；
- authority 专项测试为 `20 passed, 1 skipped`，REST/MCP/Capability 专项为 `4 passed`；与 proposal、规则合同、Capability、MCP 组合回归为 `40 passed, 1 skipped`，受影响模块 Python 编译、Ruff 和 `git diff --check` 通过。迁移目录当前为 179 项，真实 PostgreSQL 演练因本机未配置 `DATABASE_URL` 跳过，不能把本轮结果表述为真实生产数据库验收。

因此，“规则没有持久化 current/history 和受治理只读查询”不再是当前技术缺口；当前仍未实现的是客户真实规则材料、客户/专家对规则语义的确认、规则驱动的变更候选自动选择、ApprovalCase 绑定和变更执行。多 Provider 真实联动故障、备份/PITR、RPO/RTO、容量/恢复时间/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。该 authority 只记录技术基线证据，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或行政决定；状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.49 Proposal 派生规则技术基线装载与 authority current 直接评估

第 8.48 节虽然已有 rule authority，但首次使用时仍需调用方自行拼装完整规则合同；已有 proposal 与 authority current 的评估也必须重复上传两份文档。本轮关闭这两个操作性缺口，范围仍严格限定重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- 新增确定性技术基线构建器，从 sealed proposal 已有的 `missing_customer_rule_id`、action、目标绑定和 required evidence 派生 `1.0.0` 草案。它只生成 `draft_unreviewed`，不生成或推定 `awaiting_customer_approval/customer_approved`，不补写客户业务判断，两个执行开关保持 false；
- `PostgresCustomerCompensationRuleAuthorityStore.bootstrap_technical_baseline()` 对每个缺失规则使用与 authority 写函数相同的 PostgreSQL advisory lock，仅在该 rule ID 没有 current 时装载草案。重复执行幂等；若已有草案、待批准或已批准 current，均保留原记录而不覆盖，并在结果中分开报告 created、reused 和 `invalid_or_drifted`；
- 新增内部运维命令 `scripts/bootstrap_chongqing_compensation_rule_baseline.py --tenant-id ... --run-id ...`，从已持久化 proposal current 一次生成并装载所需草案。该命令不是公共写 API，也不能把草案推进为客户批准；
- `assess_current(run_id)` 在一个 PostgreSQL 事务的一条查询中同时读取认证租户的 proposal current 与 rule current，再复用同一严格评估器和部署侧 trust registry。新增只读 `GET /api/platform/v1/projections/federated/compensation-rule-assessments/{run_id}`、Capability `projection.federated.compensation-rule.assess-current@1.0.0` 和 MCP `assess_persisted_federated_projection_compensation_rules`；调用方只能提供 `run_id`，不能覆盖 tenant、proposal、规则或 trust anchor；
- 新增测试覆盖草案确定性、零批准、重复装载幂等、已有 current 不覆盖、目标漂移可见、单快照读取、REST/MCP tenant/role、not-found/outage 和只读声明。proposal/rule/Capability/MCP/migration/deployment/platform 相关回归为 `219 passed, 2 skipped`；跳过项仍是未配置 `DATABASE_URL` 的真实 PostgreSQL 演练。受影响合同、authority、Capability、路由、新测试和脚本 Ruff、Python 编译与 scoped diff 检查通过；未新增迁移，catalog 仍为 179。

因此，“没有专家就无法先建立任何规则目录”和“评估 authority 时必须由调用方重复上传完整合同”不再是技术缺口。系统现在能形成可追踪的未审定草案目录并持续报告 missing/drift，但草案内容仍只来自 sealed proposal 的技术证据，不是客户确认的 rollback/delete/restore/corrective-forward/reconciliation 业务语义。客户真实规则版本、签署材料和部署 trust anchor，规则驱动的变更候选选择、ApprovalCase 绑定与执行，以及多 Provider 真实联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、全执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。本轮不代表客户批准、专家审定、客户生产验收、生产恢复认证、法定审批或行政决定，状态继续为 `technical_baseline_unreviewed`，用途继续为 `assisted_precheck_not_for_production_decision`。

### 8.50 可信客户规则与补偿候选的 ApprovalCase 审查绑定

第 8.49 节已经能从同一 PostgreSQL 快照读取 proposal current、rule current 并评估规则状态，但还不能把操作员选中的变更候选与这组权威证据封装为待审案例。本轮继续只使用重庆客户数据和 `natural-resource-one-map 2.3.0`，补齐审查绑定而不实现补偿执行：

- 新增不可变 `FederatedProjectionCompensationApprovalBinding`。绑定包含 tenant/run、proposal、源 federated snapshot、候选、sealed plan、规则 assessment、客户规则合同、批准 artifact 和部署 trust anchor 的 SHA-256；任一字段漂移都会使绑定指纹校验失败；
- 只有操作员显式选择的 `corrective_forward`、`rollback_committed_prefix`、`delete_target` 或 `restore_target` 可以申请审查，且该候选所需规则必须在 authority current 中为 `customer_approved`、评估为 `approved_but_not_executable` 并匹配部署 trust anchor。缺失、草稿、待客户批准、漂移或不可信规则全部 fail-closed；只读 reconciliation 和原 sealed plan reapply 继续走各自独立流程；
- 由绑定确定性生成通用 `ApprovalCase`，action 固定为 `projection.federated.compensation.review`。tenant 和 requester 只来自认证上下文，案例目标指纹就是绑定指纹；同一绑定重复提交保持幂等。案例及响应固定 `automatic_mutating_selection_allowed=false`、`approval_case_is_execution_authority=false` 和 `execution_allowed=false`；创建 pending 案例不等于批准，即使以后由独立人工作出 approved 决定也不会在本入口调用 Provider；
- 新增 `POST /api/platform/v1/projections/federated/compensation-approval-cases`、Capability `projection.federated.compensation-approval.request@1.0.0` 和 MCP `request_federated_projection_compensation_approval`。三者复用同一请求/结果合同，要求正文幂等键，存在 `Idempotency-Key` header 时必须一致；Capability 如实声明 `COMMAND + CONTROL_WRITE + MEDIUM + REQUIRED idempotency`，MCP 标注非破坏且幂等；
- 核心/API 专项 `14 passed`，补偿与恢复组合回归 `119 passed, 3 skipped`，Capability/MCP/ApprovalCase 相关回归 `79 passed`，平台路由共 75 项；新增模块和测试 Ruff、编译、scoped `diff --check` 均通过。另增加真实 PostgreSQL 端到端用例，覆盖 proposal authority、rule authority、trust、ApprovalCase 创建和二次 `created=false`，但本机未配置 `DATABASE_URL`，本轮结果为 `1 skipped`，不能表述为真实数据库验收；未新增 migration，catalog 保持 179。

因此，“受信客户规则已经存在时，操作员仍无法把具体变更候选和权威证据提交到 ApprovalCase”不再是技术缺口。当前仓库仍没有真实客户签署的规则、批准 artifact 或生产 trust anchor，也没有专家/客户审定结论；技术基线草案不能通过该门禁。尚未实现的是 approved 案例到规则驱动多 Provider 执行之间的独立授权、一次性消费、执行策略和结果对账，以及真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/生产 SLO、完整 Subject-Purpose-Resource 安全、通用 Proposal/Action runtime 与自动语义规划融合。本节保持 `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或行政决定，也不宣称跨存储分布式事务。

### 8.51 补偿 review 与 execute 双 ApprovalCase 及一次性授权消费

第 8.50 节的 review ApprovalCase 明确不是执行权限。本轮继续把“候选证据审查”和“是否允许受控执行器消费一次授权”拆成两次独立人工裁决，范围仍只包含重庆客户数据集和自然资源本体 `natural-resource-one-map 2.3.0`：

- 新增 `FederatedProjectionCompensationExecutionBinding`。申请第二阶段案例时，系统不直接信任已批准 review 的字符串引用，而是重新读取 proposal current、rule authority current 和部署 trust registry，重建同一候选的 review binding；review 案例必须已由 `human:*` 批准、未过期、context/target/fingerprint 与当前绑定完全一致。execution 案例有效期不得超过 review 案例；
- 第二阶段创建独立 ApprovalCase，action 为 `projection.federated.compensation.execute`，target 从 proposal 改为精确 candidate，case ref 与 fingerprint 均独立于 review 案例。案例 context 和响应固定 `review_approval_is_execution_authority=false`、`execution_case_is_provider_execution=false`、`automatic_execution_allowed=false`、`provider_execution_performed=false`；创建案例本身不调用 Provider；
- 新增 migration `180_federated_compensation_execution_authorization.sql` 和内部 `PostgresFederatedCompensationExecutionAuthorizationAuthority`。只有 review 与 execution 两个案例均已批准、未过期、由不同 human 主体裁决，且 proposal/candidate/客户规则 current 仍与绑定完全一致时，受控执行器才可消费一次授权。消费表 append-only、tenant RLS/FORCE RLS、gateway 无表写权限；完全相同重放幂等返回，不同证据重放或同一 review 被另一 execution 消费会冲突；消费 receipt 明确 `authorization_consumed=true`、`provider_execution_performed=false`、`receipt_is_provider_execution_result=false`；
- 一次性消费函数没有 REST、Capability 或 MCP 公共入口，只保留给后续受控 executor。对外仅新增“申请第二个审批案例”的 REST POST `/api/platform/v1/projections/federated/compensation-execution-approval-cases`、Capability `projection.federated.compensation-execution-approval.request@1.0.0` 和 MCP `request_federated_projection_compensation_execution_approval`，声明 `COMMAND + CONTROL_WRITE`、中风险、强制幂等、非破坏；平台路由从 75 增至 76；
- proposal/rule/trust/双审批/联邦恢复/Capability/平台网关联合回归为 `199 passed, 7 skipped`；双审批与 authority 聚焦回归为 `104 passed, 1 skipped`。跳过项均为当前未配置 `DATABASE_URL` 的真实 PostgreSQL 用例，不能表述为真实数据库或生产验收。migration/deployment profile 专项为 `30 passed`；catalog 已更新为 180 项，最新迁移为 `180_federated_compensation_execution_authorization`，fingerprint 为 `6ea1a428838aeb3e5b5fd53cad4d6e10594419bc7c86ed0757695d6f3dc3147b`，180 号文件 SHA-256 为 `319fff2f669895ad7678b59d59f47b17631a78d85c3c284083f947459b41007d`。Ruff、MCP 语义检查、Python 编译和 scoped diff 检查通过。

因此，“review 批准会被直接当作执行权限”和“同一补偿授权可以被静默重复消费”已从当前代码缺口中移除。但本轮只建立了双审批门禁和一次性消费权威，没有实现消费后的 Provider 调用、按客户业务语义编排 corrective-forward/rollback/delete/restore、多 Provider 补偿策略、执行结果 receipt 对账或失败后的新一轮决策。仓库也没有真实客户签署规则、生产 trust anchor、专家审定或客户验收。真实五 Provider 联动故障、备份/PITR/RPO/RTO、容量/恢复时间/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合仍未完成。结果继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或行政决定，也不宣称跨存储分布式事务。

### 8.52 消费后 dispatch intent 的当前证据重绑定

第 8.51 节已经能一次性消费双审批授权，但 Provider adapter 仍不应直接相信消费时保存的 plan 或 target 列表。本轮增加消费后、Provider 前的最后一个纯技术边界，仍严格限定重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- 新增 `FederatedProjectionCompensationDispatchIntent`。它接收 execution binding、一次性消费 receipt 和当前 rule-authority evidence，重新查验 proposal current 中的 candidate、candidate action、候选所引用的 sealed plan、目标 engine/target_ref 及全部已批准规则合同；任何 proposal/rule drift、receipt hash/ref 不一致、未封存计划或非四类客户规则变更动作均 fail closed；
- intent 只携带 future Provider adapter 所需的有序 `CompensationProposalSourceBinding` 与规则合同身份，不携带 SQL、凭据、端点覆盖值或客户业务参数。状态固定为 `provider_adapter_pending`，`provider_dispatch_performed=false`、`execution_allowed=false`，不会导入或调用任何 Provider；
- 新增纯模型/负向测试，覆盖正常重绑定、执行 ApprovalCase ref 伪造、当前 proposal 漂移和目标/规则集合不一致。该层没有新增公共 REST、Capability 或 MCP surface，也没有新增数据库写入；它把“授权消费后到 Provider 调度前的证据重绑定”变成可测试合同，但不伪造客户 compensation 语义；
- 本轮 dispatch-intent 专项为 `22 passed, 1 skipped`。跳过项仍为未配置 `DATABASE_URL` 的真实 PostgreSQL 用例；Ruff、Python 编译和 scoped diff 检查通过。

因此，消费后的计划/目标/规则当前性校验已不再是未实现的纯代码缺口；仍未完成的是客户语义驱动的 Provider adapter、真实五类存储调用、执行 receipt/结果对账、失败后的 reconciliation 业务决策，以及备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。结果继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.53 Provider adapter 部署注册合同与 fail-closed 解析

第 8.52 节已经把授权消费后的当前证据重新封存，但还缺少一个不把 endpoint、凭据或客户语义带入请求的 Provider adapter 边界。本轮继续只使用重庆客户数据集和固定自然资源本体 `natural-resource-one-map 2.3.0`（package `natural-resource-one-map:2.3.0:587915868b1221af`，content SHA-256 `587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019`）：

- 新增 `cross_store_projection_compensation_provider_adapter.py`。部署侧 adapter definition 只登记 tenant、adapter ID/语义版本、精确 target engine + target_ref 集合、支持的四类客户规则 action 和五类既有 Provider receipt schema；definition 与 registry 都有 SHA-256 指纹，按身份唯一、排序且不可通过调用方请求体修改；
- adapter registry 只能从 `GDA_FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_JSON` 进入服务端，未配置时为空注册表。请求只携带 dispatch intent SHA-256、adapter ID/version/hash、registry hash 和 typed requester；Pydantic `extra=forbid` 会拒绝 endpoint、credentials、SQL、目标覆盖值或客户业务参数，resolver 也会重新验证 intent/request/registry 的封存指纹；
- resolver 要求 adapter 的 tenant、重庆数据范围、本体 package/content SHA-256、customer-rule action、target 集合和 receipt contract 与当前 dispatch intent 精确一致。未注册、版本/hash 漂移、目标漂移、动作不支持或 baseline 不一致均 fail closed；成功结果只为 `adapter_resolved_pending_execution`，固定 `provider_dispatch_performed=false`、`execution_allowed=false`，不导入、不连接、不调用任何 Provider；
- receipt contract 目前仅引用已有 PostGIS、pgvector、RDF/Fuseki、对象存储和 Spark/Iceberg receipt schema，不把这些 schema 误报为客户规则执行结果。没有新增 REST、Capability、MCP 或数据库迁移，避免在尚未完成真实 adapter 前扩大公共执行面；
- adapter/dispatch 专项 `8 passed`（其中本轮新增 adapter 注册/解析 `6 passed`）；Ruff、Python 编译和 scoped `git diff --check` 通过。当前没有 `DATABASE_URL`，因此本轮不声称真实 PostgreSQL 或生产执行验证。

因此，“消费后完全没有部署侧 adapter 身份和目标 allowlist”已不再是当前技术合同缺口；但真实 Provider adapter 实现尚未接线，仍未完成五类 Provider 的客户规则 mutation 调用、Provider-native receipt 内容/指纹验证、执行结果与 authority 对账、失败后的 reconciliation 业务决策、真实多存储联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。adapter 解析结果仍是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.54 Provider implementation artifact 与 mutation plan binding 基线

第 8.53 节的 adapter 注册只证明部署身份和目标 allowlist，仍缺少“每个源 plan 如何绑定到部署实现合同”的中间证据。本轮继续固定重庆客户数据集和自然资源本体 `natural-resource-one-map 2.3.0`：

- adapter definition 新增部署侧 `implementation_artifact_sha256`，并要求每个支持的 `customer action × target engine` 都有唯一、排序的 operation contract SHA-256；registry 不接受只登记 action 或只登记 engine 的半覆盖实现；
- 新增 `cross_store_projection_compensation_provider_plan.py`。它从当前 dispatch intent 和已解析 adapter resolution 逐一生成 `ProviderPlanBinding`，绑定源 plan SHA-256、source version/content、target engine/ref、客户 action、adapter/实现工件哈希、operation contract、既有 Provider receipt schema 和确定性 provider idempotency key；
- plan set 明确 `execution_material_state=deployment_payload_not_materialized`，不包含 SQL、endpoint、凭据、客户业务参数或 Provider payload。每次生成结果可确定性重放，源 plan、目标、adapter resolution 或 mutation contract 漂移都会拒绝；`provider_dispatch_performed=false`、`execution_allowed=false` 保持不变；
- 新增 plan binding/plan set 负向测试，adapter/plan/dispatch 专项共 `9 passed`；Ruff、Python 编译和 scoped diff 检查通过，没有新增公共 API、MCP、Capability 或数据库迁移。

因此，“adapter 已解析但没有按源 plan 绑定实现合同和幂等身份”已进入可验证技术基线；这仍不是 Provider 执行计划的客户业务语义，也不是实际 mutation payload。尚未完成的是由真实部署工件实现的五类 Provider mutation adapter、Provider-native receipt 内容/指纹校验、执行结果落账与 authority 对账、未知结果恢复和 reconciliation 业务决策，以及真实多存储联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证或跨存储分布式事务。

### 8.55 部署侧执行材料摘要绑定与 Provider 原生回执候选校验

第 8.54 节止于 `deployment_payload_not_materialized`。本轮继续使用重庆客户数据集和固定自然资源本体 `natural-resource-one-map 2.3.0`，补上 Provider 调用前后两个仍不执行、不落权威的合同层：

- 新增 `cross_store_projection_compensation_provider_materialization.py`。部署工作负载必须为 plan set 的每个位置恰好提供一个 projection ID 和 payload SHA-256；系统将其与 plan binding、target、deployment-selected provider action、receipt schema、provider idempotency key 和 implementation artifact 重新封存。集合缺项、重复位置、非 `workload:` 身份或封存哈希漂移均拒绝；
- materialization 只保存投影标识、摘要和受治理 URN，不保存实际 payload、SQL、endpoint 或凭据。状态推进为 `deployment_payload_materialized_pending_provider_dispatch`，但 `provider_dispatch_performed=false`、`execution_allowed=false`，模块本身既不定位私有材料也不调用 Provider；
- 新增 `cross_store_projection_compensation_provider_receipt.py`。它按 target engine 复用已有 PostGIS、pgvector、RDF/Fuseki、S3/对象存储和 Spark/Iceberg 原生 receipt 模型及其指纹函数，重新校验 receipt schema、tenant、projection、target、provider action、provider plan hash、idempotency key 和 Provider receipt SHA-256；任一漂移均 fail closed；
- 原始 receipt 仅存在于待校验 candidate，成功输出不携带原始 receipt，只保留被验证的身份、摘要、状态和观测值；结果固定为 `validated_not_authority_admitted`、`authority_write_allowed=false`、`provider_execution_performed=false`、`receipt_is_authority_record=false`，不会创建 checkpoint、标记补偿完成或触发 authority 写入；
- 重庆当前夹具的 PostGIS、RDF/Fuseki、Spark/Iceberg 三目标原生 receipt 成功路径均已验证，并覆盖材料位置缺失/重复、非法 materializer、私有字段注入、plan/idempotency/target 漂移、错误 receipt 指纹和错误 schema。新增专项 `11 passed`；补偿治理链宽回归为 `263 passed, 7 skipped, 1 warning`。7 个跳过项仍是未配置 `DATABASE_URL` 的真实 PostgreSQL 用例，warning 为既有 OpenTelemetry 弃用提示。

因此，“非执行 plan 之后没有部署材料摘要和回执候选验证边界”已不再是纯代码缺口。仍未实现的是保存/解析私有 Provider payload 的真实部署 adapter、真实 Provider mutation 调用、经授权的 receipt authority 接纳与 checkpoint/结果对账、未知结果下的 reconciliation 业务裁决，以及真实多存储联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、通用 Proposal/Action runtime 和自动语义规划融合。Vector 和对象存储已接入同一模型级校验器，但不冒充为本轮重庆三目标夹具实测。全部结果继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.56 完整 Provider receipt 集合与 authority admission 候选

第 8.55 节只能逐个验证 Provider receipt，单个成功回执仍可能被误当作整个联邦补偿已完成。本轮新增 `cross_store_projection_compensation_provider_receipt_set.py`，继续固定重庆客户数据集和自然资源本体 `natural-resource-one-map 2.3.0`：

- receipt validation set 重新验证并绑定 proposal/candidate、源恢复 snapshot、review/execute 双 ApprovalCase、已消费执行授权、dispatch intent、adapter resolution、provider plan set、implementation artifact 和 materialization set；任何上游封存哈希或身份漂移都会 fail closed；
- 每个 materialization binding 必须恰好出现一个经过校验的 receipt，缺失、重复、混入另一 materialization 的 receipt 或 target/plan/idempotency/schema 漂移均拒绝；集合顺序按材料化位置确定，不接受调用方用输入顺序改变集合身份；
- Provider receipt 的 `observed_at` 不得早于执行授权 `consumed_at`。逐回执校验同时新增 action/outcome 门禁：`checkpoint` 只接受 `checkpointed/replayed`，`rebuild` 只接受 `completed/replayed` 且目标必须存在，`delete` 只接受 `deleted/replayed` 且目标必须不存在；
- 成功集合状态为 `complete_provider_receipts_pending_authority_admission`。这里的 `provider_receipts_complete=true` 只表示相对于当前 materialization 的回执覆盖完整，不证明真实 Provider 被本模块调用；固定 `authority_admission_performed=false`、`authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`、`provider_invocation_performed_by_aggregator=false`；
- 聚合结果不携带原始 `receipt_document` 或 `provider_commit_ref`，没有新增 REST、Capability、MCP、数据库迁移或 authority 写入路径。materialization/receipt/set 专项 `19 passed`；补偿治理链宽回归 `271 passed, 7 skipped, 1 warning`，跳过项仍因未配置 `DATABASE_URL`，warning 仍为既有 OpenTelemetry 弃用提示。

因此，“一个回执可冒充多目标完成”和“授权前旧回执可进入后续接纳”的代码缺口已封闭。下一步仍需用原始 sealed repair plan、当前 checkpoint predecessor 和完整 receipt set 构造可写 checkpoint，建立独立的 authority admission/幂等写入与补偿完成判定；真实部署 adapter、Provider mutation 调用、未知结果 reconciliation、真实多存储联动故障及生产 SLO 也仍未完成。本层继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.57 Provider 期望目标状态与 checkpoint admission candidate

第 8.56 节的完整 receipt 集仍缺少“调用前承诺的目标结果”和“当前 checkpoint 前驱版本”两个输入。本轮继续固定重庆客户数据集与 `natural-resource-one-map 2.3.0`，补齐可写 authority 之前的最后一层证据准备：

- `FederatedProjectionCompensationProviderMaterializationInput` 新增 `expected_target_exists`、`expected_target_content_sha256`、`expected_target_row_count`，并将三者纳入 provider plan SHA-256。`rebuild` 必须预期目标存在，`delete` 必须预期目标不存在，缺失目标必须为零行；
- Provider receipt validator 不仅校验自身原生指纹，还必须与 materialization 中预先封存的目标内容摘要、存在性和行数完全一致。Provider 自身指纹正确但结果偏离预期时仍 fail closed；
- 新增 `cross_store_projection_compensation_checkpoint_candidate.py`。它要求每个目标提供 tenant、projection、target 和当前 predecessor SHA-256；初始 checkpoint 只能使用版本 1，无 predecessor，后继版本必须提供 predecessor 且至少为 2；位置缺失、重复、目标漂移或版本链错误均拒绝；
- 输出是 `checkpoint_candidates_pending_authority_admission` 的不可写候选集合，记录 source plan、provider plan、provider receipt、materialization、receipt set 和 predecessor 的摘要，但不构造可直接写入的 `ProjectionCheckpoint`，不调用 authority，不标记补偿完成；
- receipt/集合/checkpoint candidate 聚合专项 `21 passed`；补偿治理链宽回归 `277 passed, 7 skipped, 1 warning`。跳过项仍是未配置 `DATABASE_URL` 的真实 PostgreSQL 用例，warning 仍为既有 OpenTelemetry 弃用提示。

因此，调用前目标状态和 checkpoint 版本前驱已进入可验证技术基线。仍未完成的是将原始 sealed `ProjectionRepairPlan`、当前 authority predecessor 和该候选集合交由独立 admission 服务构造并幂等写入真实 checkpoint，以及真实 Provider mutation、结果 reconciliation、备份/PITR、RPO/RTO、生产 SLO 和执行面安全验证。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.58 原始 sealed repair plan admission preview

第 8.57 节的 candidate set 已经绑定每个目标的 predecessor 摘要，但还不能证明它确实对应原始 `ProjectionRepairPlan`。本轮新增只读的 `cross_store_projection_compensation_checkpoint_admission.py`，仍固定重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- `FederatedProjectionCompensationCheckpointAdmissionRequest` 接收完整 `ProjectionRepairPlan` 集合、Provider plan set、materialization set 和 checkpoint candidate set；输入先重新通过各自 sealed contract，再按 `source_plan_sha256` 要求每个候选恰好对应一个原始计划，拒绝缺失、重复或多余计划；
- admission 逐项复核 `plan_sha256`、source resource version/content、tenant/projection/target engine/target_ref、repair action、desired target existence/content/row count、Provider materialization 期望结果，以及 `previous_checkpoint_sha256` 和 `next_checkpoint_version`。原始计划 desired state 与 materialization 期望结果不一致时直接 fail closed，不生成 checkpoint；`fail_closed` 计划也不能进入该路径；
- `FederatedProjectionCompensationCheckpointAdmissionPreview` 只输出每个 plan/candidate 对的核验摘要、检查项和指纹，明确 predecessor 是部署提供的当前摘要，未宣称已查询或改变 authority。request/preview/item 均固定 `authority_admission_performed=false`、`authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`；模块不构造 `ProjectionCheckpoint`，不调用 `PostgresProjectionCheckpointAuthority`；
- 新增 admission 专项 `3 passed`；包含完整三目标成功重绑定、desired target drift 和 predecessor/version drift 负向用例。补偿链相关回归 `142 passed, 4 skipped, 1 warning`；跳过项仍为未配置 `DATABASE_URL` 的真实 PostgreSQL 用例，warning 为既有 OpenTelemetry 弃用提示，Ruff 与格式检查通过。

因此，“原始 sealed repair plan 与 candidate/materialization 之间没有反向 admission 校验”已进入可验证技术基线；仍未完成的是把 preview 交给 authority owner 做真实当前 predecessor 查询、权限检查、幂等 `ProjectionCheckpoint` 写入、冲突处理和补偿完成落账。真实 Provider mutation、未知结果 reconciliation、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、客户验收和专家审定仍未实现。本层继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.59 authority current predecessor 只读核对

在 8.58 的不可写 admission preview 之上，本轮新增 `cross_store_projection_compensation_checkpoint_authority_read.py`，把 authority 的实时读取纳入前置校验，但仍不打开写入口：

- 通过 `PostgresProjectionCheckpointAuthority.current()` 按 tenant、projection、target engine 和 target ref 读取每个目标的当前 checkpoint；测试使用同一只读协议替身，生产实现仍要求 PostgreSQL authority；
- 首版候选必须看到 authority 当前为空且版本为 0；后继候选必须看到 `current.checkpoint_sha256 == previous_checkpoint_sha256` 且 `next_checkpoint_version == current.checkpoint_version + 1`。返回错误身份、旧版本、跳版本或缺失 predecessor 均 fail closed；
- 输出 `FederatedProjectionCompensationCheckpointAuthorityReadPreview` 只保存当前 checkpoint 的身份摘要、版本和匹配指纹，不携带 `ProjectionCheckpoint` 写入对象；固定 `authority_current_read_performed=true`、`all_predecessors_match=true`，但仍保持 `authority_admission_performed=false`、`authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`，绝不调用 `record()`；
- 新增专项 `3 passed`，覆盖初始版本读空、live predecessor 漂移和非 PostgreSQL authority 配置拒绝；补偿链相关回归 `145 passed, 4 skipped, 1 warning`，Ruff 和格式检查通过。

因此，authority 当前状态与候选 predecessor 的只读一致性检查已进入技术基线；剩余的关键写入工作仍是经过权限/RLS 和并发校验后构造、幂等写入真实 checkpoint、处理冲突并记录补偿完成。该层不代表 authority admission 已完成，也不代表客户批准、专家审定、生产验收、生产恢复认证、法定审批或跨存储分布式事务。

### 8.60 checkpoint write intent（不可写）

在 8.59 的 authority current 只读核对之后，本轮新增 `cross_store_projection_compensation_checkpoint_write_intent.py`，把后续 authority `record()` 所需证据封装为不可写 intent：

- 每个 intent 固定 candidate、admission request、authority-read preview、原始 repair plan SHA-256 和幂等键、源版本/内容、projection/target、Provider action、Provider plan/idempotency/receipt 摘要、目标结果和 predecessor/version；
- `target_commit_ref` 采用固定结构，同时绑定原始 `plan_sha256`/`idempotency_key` 与 Provider receipt 摘要，拒绝调用方注入自由 commit ref；主体必须是 typed `human:`、`workload:` 或 `agent:`，时间戳必须带时区；
- intent/set 状态固定为 `checkpoint_write_intent_pending_authority_record`，不构造 `ProjectionCheckpoint`，不调用 authority `record()`，并保持 `authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`；
- 新增专项 `3 passed`；补偿链相关回归 `148 passed, 4 skipped, 1 warning`，Ruff 和格式检查通过。

因此，真实写入前的 evidence handoff 已具备确定性、可审计、不可写的输入合同。仍未完成的是由受控 writer 在权限/RLS、并发和最终目标观察通过后构造并幂等写入真实 `ProjectionCheckpoint`，以及写入后的补偿完成落账和失败重试；本层不代表 authority admission、客户批准、专家审定或生产验收已完成。

### 8.61 最终目标观察绑定的 checkpoint write request（仍不可写）

在 8.60 的 write intent 之后，本轮新增 `cross_store_projection_compensation_checkpoint_write_request.py`，补齐调用 authority `record()` 之前的最终目标实测绑定，范围继续固定为重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- builder 同时接收原始 admission request、authority-read preview、完整 write-intent set、每个目标最终的 `ProjectionTargetObservation` 以及 typed updater/带时区更新时间；最终观察按 tenant、projection、target engine 和 target ref 唯一匹配，缺失、重复或多余观察全部 fail closed；
- 每个目标重新核对存在性、内容 SHA-256、行数和观察时间，并把原始 `ProjectionRepairPlan` 的 `plan_sha256`、原始 `plan_idempotency_key`、Provider plan/idempotency/receipt 摘要及 live authority predecessor/version 重新绑定。内容漂移、行数漂移、身份漂移、旧 predecessor、跳版本或 checkpoint 时间早于最终观察均不能生成 request；
- 复用 `build_projection_checkpoint_from_repair()` 构造确定性 `ProjectionCheckpoint`，并再次复核 `projection_checkpoint_fingerprint()`。输出 `FederatedProjectionCompensationCheckpointWriteRequest/Set` 保存最终观察、checkpoint 和整条上游摘要，状态固定为 `checkpoint_write_request_pending_authority_record`；
- request 内含未来 writer 所需的精确 checkpoint 对象，但本模块没有 authority writer 依赖、不调用 `record()`、不处理数据库权限或并发，也不标记补偿完成；request/set 继续固定 `authority_admission_performed=false`、`authority_write_allowed=false`、`checkpoint_write_allowed=false`、`compensation_completion_allowed=false`；
- 新增专项 `5 passed`，覆盖重庆 PostGIS、RDF/Fuseki、Spark/Iceberg 三目标确定性生成、内容漂移、观察缺失/重复、时间倒退和所有不可写标志；candidate/admission/authority-read/write-intent/write-request 五层联合回归 `19 passed`，补偿治理链宽回归 `155 passed, 5 skipped, 1 warning`。跳过项仍为未配置真实 PostgreSQL 环境的用例，warning 仍为既有 OpenTelemetry 弃用提示；Ruff、格式和 Python 编译检查通过。

因此，“最终目标观察尚未与原始 plan、Provider receipt、live predecessor 和待写 checkpoint 绑定”已不再是纯代码缺口。当前真正未完成的是受控 writer 在真实 PostgreSQL tenant RLS、主体权限和并发 CAS 门禁下幂等调用 `PostgresProjectionCheckpointAuthority.record()`，处理相同重放/不同证据冲突，并只在全部 checkpoint 成功后记录补偿完成。真实客户规则驱动的 Provider mutation、未知结果 reconciliation、多 Provider 联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、正式客户批准与验收仍未完成。本层继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表 authority 已写入、客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

### 8.62 受控 checkpoint authority writer 与部分写入边界

在 8.61 的最终观察绑定 request 之后，本轮新增 `cross_store_projection_compensation_checkpoint_writer.py`，接入既有 `PostgresProjectionCheckpointAuthority.record()` 唯一写路径，不新增数据库表或旁路写入口：

- writer 只接受重新通过 sealed validation 的完整 write-request set，执行主体必须与 request 中 typed updater 完全一致；在第一次副作用前先对全部目标调用 authority `current()`，允许 live current 精确等于 predecessor，或精确等于本次 checkpoint 的幂等重放。任一目标出现身份、SHA-256 或版本漂移时，整批在零 `record()` 调用状态下 fail closed；
- 通过 preflight 后按固定 position 顺序调用 `record(checkpoint, previous_checkpoint_sha256=...)`。真实 PostgreSQL authority 继续负责 `SET LOCAL ROLE gda_control_gateway`、tenant context、RLS/FORCE RLS、SECURITY DEFINER、advisory lock、严格 CAS/逐版本加一、append-only 和同证据幂等；writer 不直接访问 history 表；
- 每个调用生成 sealed record item，区分 `created`、`idempotent_replay`、`conflict`、`forbidden`、`validation_rejected`、`authority_outcome_unknown` 和 `authority_response_mismatch`。authority 返回的 checkpoint 或 `created` 类型不可信时按 unknown 处理，不把响应直接当作成功；
- 三目标不是一个跨目标数据库事务。若第二个或后续目标发生并发冲突、权限错误、连接结果未知或响应不一致，writer 立即停止，保留已尝试前缀和未尝试位置，集合状态为 `checkpoint_authority_records_incomplete_pending_reconciliation`；不会继续写后续目标，也不会回滚或删除已提交的 append-only checkpoint；
- 全部目标成功时状态仅为 `checkpoint_authority_records_complete_pending_compensation_completion`。即使都是 `created` 或合法 replay，仍固定 `compensation_completion_allowed=false`、`compensation_completion_recorded=false`，由下一层重新读 authority current 后决定是否落账完成；
- 新增专项 `7 passed, 1 skipped`，覆盖三目标首次写入、幂等重放、preflight 零写入拒绝、部分冲突、RLS/权限拒绝、authority outcome unknown、错误响应和主体不一致。七层链与 authority 合同联合回归 `31 passed, 1 skipped`，补偿治理链宽回归 `162 passed, 6 skipped, 1 warning`；Ruff、格式和 Python 编译检查通过。新增真实 PostgreSQL/RLS/幂等用例因本机未配置 `DATABASE_URL` 而跳过，不能表述为本轮真实数据库验收；warning 仍为既有 OpenTelemetry 弃用提示。

因此，“checkpoint request 完全没有受控写入器”和“部分写入会被静默当作整批成功”已不再是代码缺口。当前下一项是建立独立 completion admission/append-only 落账：重新读取全部 authority current，证明其与完整 record set 精确一致，并对 partial/unknown 结果先 reconciliation，只有完整成功集合才能生成补偿完成记录。真实客户规则 Provider mutation、未知结果业务裁决、多 Provider 联动故障、备份/PITR、RPO/RTO、容量/生产 SLO、正式客户批准和验收仍未完成。本层不代表跨目标原子事务、跨存储分布式事务、生产恢复认证、客户批准或专家审定。

### 8.63 checkpoint 补偿完成 admission 与 append-only authority

在 8.62 的受控 writer 之后，本轮新增 `cross_store_projection_compensation_completion_authority.py` 和 migration 181，将“完整 checkpoint 写入集合”与“补偿完成已持久落账”分成两个独立阶段：

- completion admission 只接受重新通过 sealed validation 的完整 `CheckpointAuthorityRecordSet`。tenant、run、write-request set 摘要、逐 position request/record、checkpoint SHA-256、前序 checkpoint、版本和 created/replay 状态必须全部一致；partial、conflict、forbidden、validation rejected、unknown、response mismatch 或存在未尝试目标时，在任何 completion current read 之前拒绝；
- admission 对全部目标重新读取 checkpoint authority current，逐项要求与本批 checkpoint 完全相同，并生成确定性 completion target、idempotency key 和 request SHA-256。此处只是允许尝试落账，request 仍固定 `completion_recorded=false`、`provider_execution_performed_by_completion_authority=false`；
- PostgreSQL completion authority 只通过 `SECURITY DEFINER` 函数写入新 append-only 表；gateway 没有表级 INSERT/UPDATE/DELETE 权限。表启用 tenant RLS/FORCE RLS 和 UPDATE/DELETE 拒绝触发器，相同 run/idempotency/request 证据可幂等回放，不同证据冲突 fail closed；
- 数据库函数先按固定顺序取得所有 checkpoint target advisory lock，再在同一事务内重新核对 `cross_store_projection_checkpoint_current` 的 SHA-256 和版本后插入 completion。由此封闭“Python admission 通过后、数据库落账前 current 又被并发推进”的窗口；目标 JSON 同时要求 11 个明确标准键全部存在并拒绝未知键替换，不能只靠字段数量蒙混通过；
- durable receipt 明确记录 `checkpoint_compensation_completion_recorded=true`，同时永久保持 `provider_execution_performed_by_completion_authority=false`，并固定 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。completion authority 不调用 PostGIS、RDF/Fuseki、Spark/Iceberg 等 Provider，也不把三目标包装成跨存储分布式事务；
- 专项在隔离临时 PostgreSQL 中 `10 passed`，覆盖完整 admission、partial 零 current-read 拒绝、live-current 漂移、数据库返回篡改、严格布尔响应、append-only/RLS、同证据幂等、租户隔离、SQL 直调字段替换拒绝，以及 admission 后并发推进的数据库二次拒绝。migration/profile 合同 `49 passed`；projection consistency、checkpoint authority 与补偿治理链宽回归 `170 passed, 8 skipped, 1 warning`，跳过项为未注入外部运行环境的既有真实集成用例，warning 仍为既有 OpenTelemetry 弃用提示；Ruff、格式、Python 编译和 `git diff --check` 通过。

因此，“完整 checkpoint authority record set 之后没有独立完成落账”和“admission 到 insert 之间的 current 竞态未封闭”已不再是代码缺口。当前完成的是 checkpoint 技术证据链：`sealed plan → candidate → live predecessor → write intent → final observation-bound request → controlled authority writer → completion authority`。它证明指定 checkpoint 已成为落账瞬间的 authority current，并不证明真实客户规则驱动的 Provider mutation 由本层执行。剩余重点转为未知结果的业务 reconciliation/case closure、真实客户规则 Provider mutation 的端到端客户样例、跨 Provider 故障演练、备份/PITR/RPO/RTO、容量与生产 SLO，以及正式客户批准和验收；在没有专家审定时继续使用 `natural-resource-one-map 2.3.0` 技术基线推进，但不得改写为专家或客户已批准。

### 8.64 重庆数据范围的真实 PostGIS Provider mutation adapter

在 8.63 的 checkpoint completion authority 之后，本轮把“授权消费后的 Provider mutation”推进到一个真实、可回放的 PostGIS 目标样例。范围仍严格固定为重庆客户数据集语义范围和 `natural-resource-one-map 2.3.0`；本轮使用临时隔离 PostgreSQL/PostGIS 数据库验证技术链，不把样例写入客户生产库，也不把它解释为客户业务规则已批准或生产验收已完成：

- 新增 `cross_store_projection_compensation_postgis_adapter.py`。adapter 只接收完整的 dispatch intent、Provider plan set、materialization set、原始 `ProjectionRepairPlan`、显式注册的 `PostGISProjectionTarget` 和结构化 rows；在第一次 Provider 副作用前重新核对 tenant/run/position/target identity、source plan 与 provider binding、payload SHA-256、desired target content/row count 及 receipt schema；非 PostGIS source plan、目标漂移、payload 漂移和不完整 sealed chain 均 fail closed；
- adapter 生成 provider-local execution plan，将 executor 所需的 `plan_sha256` 绑定到 materialization 计算出的 `provider_plan_sha256`，并复用已有 allowlisted `PostGISProjectionRepairExecutor`。调用方不能传 SQL、endpoint、credentials 或自由目标覆盖值；executor 仍只从注册目标生成 DDL/DML，目标 mutation 和 `gda_provider.postgis_projection_repair_receipt` 写入在同一 PostgreSQL 事务中完成；
- 首次隔离库 rebuild 返回 `provider_mutation_committed`，相同 request 再放回 executor 返回 `provider_idempotent_replay`；真实 receipt 能被既有 Provider receipt candidate validator 接受，但 validator 仍只输出 `validated_not_authority_admitted`。adapter 结果永久标记 `checkpoint_authority_write_performed_by_adapter=false`、`compensation_completion_recorded_by_adapter=false`，并确认 checkpoint history 未被写入；
- 新增专项覆盖 request deterministic replay、payload drift 在零 Provider 调用前拒绝、非 PostGIS target 拒绝、SQL/credentials/endpoint 禁入、真实 PostGIS rebuild、幂等 replay、原生 receipt 校验及 authority 不写入。专项 `4 passed`（含 1 个真实临时 PostgreSQL 用例）；PostGIS executor + provider plan/materialization/receipt + adapter 相关回归 `46 passed`。不启用外部数据库的 compensation 宽回归为 `167 passed, 8 skipped, 1 warning`；启用本机 `DATABASE_URL` 的宽回归为 `172 passed, 3 failed, 1 warning`，3 个失败均来自本轮之前已被跳过的既有真实 authority 测试（ApprovalCase migration 前置依赖和规则 authority 回退检测），不归因于本 adapter；Ruff、Python 编译和格式检查通过；

因此，“授权消费后完全没有真实 Provider mutation 技术样例”已不再是纯代码缺口，但目前只完成 PostGIS 一个受控 adapter 和临时隔离库证据。仍未完成的是 RDF/Fuseki、Spark/Iceberg、对象存储等其他 Provider 的真实 mutation adapter；重庆客户真实数据表/字段映射和业务规则参数的部署材料；Provider receipt 的 authority admission、checkpoint/补偿完成对账；unknown 结果的业务 reconciliation/case closure；多 Provider 联动故障；备份/PITR、RPO/RTO、容量与生产 SLO；以及正式客户批准、专家审定和客户生产验收。当前状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.65 自然资源本体 2.3.0 的真实 RDF/Fuseki Provider mutation adapter

在 8.64 的 PostGIS adapter 之后，本轮按同一 sealed contract 增加 RDF/Fuseki adapter，并使用本机 `gisdataagent-ontology-fuseki:5.5.0-nr-2.3.0` 镜像启动临时容器，对仓库内正式 `natural-resource-one-map 2.3.0` RDF package 执行真实 Graph Store mutation。范围继续属于重庆客户数据/本体技术基线，不把临时容器结果解释为客户生产 Fuseki、客户规则批准或生产验收：

- 新增 `cross_store_projection_compensation_rdf_adapter.py`。builder 重新校验 dispatch intent、Provider plan set、materialization set、原始 RDF repair plan、projection/target identity、期望图内容/三元组数、receipt schema，以及 package ID/content SHA-256/RDF artifact SHA-256 的 payload 指纹；非 RDF source plan、package 漂移和 target 漂移均 fail closed；
- mutation request 只保留 sealed plan、target ref 和摘要，不包含 Graph Store endpoint、SPARQL Update endpoint、package 目录、用户名、密码、SPARQL 或 RDF payload。执行前 adapter 必须从 `RDFProjectionRepairExecutor` 的服务端 registry 重新解析 target 并复算 package payload；构建 request 后发生 registry/package 漂移时，在零 HTTP 调用前拒绝；
- provider-local execution plan 继续使用 materialization 的 `provider_plan_sha256` 和 provider idempotency key。首次 rebuild 由既有 executor 上传 staging graph，再用一次 Fuseki SPARQL Update 同时替换 default graph、删除 stage 并写入 plan-bound receipt graph；结果为 `provider_mutation_committed`。相同 request 从 receipt graph 恢复并返回 `provider_idempotent_replay`，不重复 mutation；
- 真实容器用例使用正式 2.3.0 package，核对目标图 fingerprint、三元组数、`provider_atomicity=single_fuseki_update_request`、receipt graph 回读和 replay，并在结束后确认临时 container/volume 均已删除。RDF adapter 专项 `4 passed`；PostGIS + RDF executor、provider plan/materialization/receipt 和两个 adapter 联合回归 `56 passed, 1 skipped`；不启用外部 PostgreSQL 的 compensation 宽回归 `178 passed, 8 skipped, 1 warning`。跳过项仍为既有真实 authority 用例，warning 为既有 OpenTelemetry 弃用提示；Ruff、Python 编译和格式检查通过；本轮没有新增 migration，catalog 仍为 181；

因此，PostGIS 与 RDF/Fuseki 两类 Provider 已有受控 mutation、原生 receipt 和幂等 replay 技术样例。当前仍未完成的是 Spark/Iceberg、对象存储、向量等其他 Provider adapter；将多个 adapter 按同一 federated run 串联后的真实故障、部分成功和 unknown reconciliation；重庆客户真实字段/业务参数与客户批准规则的部署材料；receipt authority admission 到 checkpoint/completion 的全链对账；备份/PITR、RPO/RTO、容量与生产 SLO；以及正式客户批准、专家审定和生产验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.66 重庆数据范围的真实 Spark/Iceberg Provider mutation adapter

在 8.65 的 RDF/Fuseki adapter 之后，本轮按同一 sealed contract 接入 Spark/Iceberg Lakehouse executor，并用重庆客户 GeoJSON bundle 在临时 MinIO + Spark/Iceberg 容器中完成真实 snapshot mutation：

- 新增 `cross_store_projection_compensation_lakehouse_adapter.py`。adapter 重新绑定 dispatch、Provider plan/materialization、原始 Lakehouse repair plan、注册目标、客户 bundle/artifact 摘要、desired target existence/content/row count 和 receipt schema；非 Lakehouse source plan、目标路由漂移、bundle/artifact payload 漂移和不完整 sealed chain 在零 Provider 调用前 fail closed；
- 外部 request 只包含逻辑 target ref、sealed execution-plan 摘要、provider plan/idempotency 摘要和固定状态标志，不暴露 endpoint、warehouse URI、bundle/artifact 路径、Docker network、凭证、实际行数据或 Spark 参数。执行时从服务端 registry 重新解析目标并复算 payload fingerprint，随后复用既有 `LakehouseProjectionRepairExecutor` 和固定 Docker Spark worker；
- 首次 rebuild 将 445 条客户要素（439 个 distinct parcel）写入 Iceberg，receipt 的 provider 标识为 `spark_iceberg`，atomicity 证据为 `single_iceberg_commit_with_snapshot_receipt`，同一 request 再执行从 snapshot-bound receipt 恢复为 `provider_idempotent_replay`，不重复 Spark commit；receipt candidate validator 可验证但仍只输出 `validated_not_authority_admitted`；
- 专项 `4 passed`（含真实临时 MinIO + Spark/Iceberg 容器 mutation、snapshot receipt、重启回读和 replay），Ruff、Python 编译和格式检查通过；本轮没有新增 migration，catalog 仍为 181。真实容器范围是临时网络、bucket、table 和 Spark worker，不代表客户生产 Lakehouse、跨存储原子事务或容量/SLO 验收；

因此，PostGIS、RDF/Fuseki 和 Spark/Iceberg 三类 Provider 已各有一个受控 mutation、原生 receipt 和幂等 replay 技术样例。当前仍未完成的是对象存储、向量等其他 adapter；多 Provider run 的部分成功/unknown/reconciliation 和 receipt 到 checkpoint/completion 的 authority 对账；重庆客户真实字段/业务参数与批准规则部署材料；真实多存储故障、备份/PITR、RPO/RTO、容量与生产 SLO；以及正式客户批准、专家审定和客户生产验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.67 重庆客户 bundle 的真实版本化对象存储 Provider mutation adapter

在 8.66 的 Spark/Iceberg adapter 之后，本轮按相同 sealed contract 接入 S3-compatible object executor，并使用临时版本化 MinIO bucket 对重庆客户 `heping_changed_parcels.geojson` 执行真实对象 mutation：

- 新增 `cross_store_projection_compensation_object_adapter.py`。adapter 在任何 S3 调用前重新绑定 dispatch intent、Provider plan/materialization、原始 object-store repair plan、注册 target、bundle/artifact/ontology 摘要、desired object state、receipt schema、`provider_plan_sha256` 和 provider idempotency key；非对象存储计划、target 路由漂移、artifact 漂移或 sealed chain 不完整均 fail closed；
- request 只保留逻辑 `s3://` target ref 与证据摘要，不携带 endpoint、bucket/key 独立覆盖字段、bundle/artifact 路径、access key、secret、对象 payload 或任意 S3 参数。执行前从服务端 registry 重新解析完整 target 并复算 payload fingerprint，调用方无法把已授权请求重定向到其他 bucket、endpoint 或文件；
- 真实 MinIO rebuild 把 1,950,576 字节重庆客户 GeoJSON 与 plan-bound receipt metadata 通过单次 `PutObject` 写入一个不可变对象版本，atomicity 证据严格为 `target_payload_and_plan_metadata_single_put_object`。新建 executor 后从对象 metadata 恢复相同 receipt，返回 `provider_idempotent_replay`，目标 key 仍只有一个版本；receipt validator 继续只输出 `validated_not_authority_admitted`，adapter 不写 checkpoint 或 completion authority；
- 删除合同继续保持既有 `versioned_intent_then_delete_marker_chain`：先写 plan-bound delete intent，再创建 delete marker，两步之间不是事务原子边界，unknown 结果必须走恢复/对账，不能表述成分布式事务或“删除一定同时完成”。专项 `4 passed`（含真实临时版本化 MinIO、重启恢复、单版本断言和资源清理）；Ruff、Python 编译和格式检查通过；本轮没有新增 migration，catalog 仍为 181；

因此，PostGIS、RDF/Fuseki、Spark/Iceberg 和版本化对象存储四类 Provider 已各有受控 mutation、原生 receipt 和幂等 replay 技术样例。当前尚缺的单 Provider adapter 主要是向量/pgvector；之后仍需完成多 Provider run 的部分成功/unknown/reconciliation、receipt 到 checkpoint/completion 的 authority 对账、重庆客户字段/业务规则部署材料、真实多存储故障、备份/PITR、RPO/RTO、容量与生产 SLO，以及正式客户批准、专家审定和客户生产验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.68 pgvector Provider mutation adapter 合同与真实数据库验收边界

在 8.67 的对象存储 adapter 之后，本轮补齐 pgvector 的补偿 adapter 接线；向量 rows 按现有 executor 合同作为受 materialization payload SHA-256 绑定的内部结构化输入，不开放为任意 SQL 或自由数据库操作：

- 新增 `cross_store_projection_compensation_vector_adapter.py`。adapter 重绑定 dispatch、Provider plan/materialization、原始 vector repair plan、allowlisted `VectorProjectionTarget`、embedding dimension、rows fingerprint、期望 content/row count、receipt schema、`provider_plan_sha256` 和 idempotency key。rows 的内容、顺序/哈希或维度、source plan、target engine/ref、plan/materialization 身份任一漂移均 fail closed；
- mutation request 采用 `extra=forbid`，不携带 SQL、database URL、endpoint、凭证或密码，也不允许调用方覆盖 executor registry；执行前从服务端 registry 重取 target 并用其 embedding dimension 复算 payload，避免 request 构建后 target 维度漂移才被 Provider 接受；
- adapter 复用既有 `VectorProjectionRepairExecutor` 的“目标表 mutation 与 `gda_provider.pgvector_projection_repair_receipt` 同一 PostgreSQL 事务”语义。result 仍固定 `checkpoint_authority_write_performed_by_adapter=false`、`compensation_completion_recorded_by_adapter=false`；receipt candidate 仅验证为 `validated_not_authority_admitted`，不提升为 authority record；
- adapter 专项本地验证了确定性 request、SQL/连接信息禁入、rows/source plan/registered dimension 漂移在零 Provider 调用前拒绝、同 transaction receipt 的幂等结果和 candidate validation；与向量 executor 回归合计 `16 passed, 1 skipped`。跳过项是新加入的真实 PostgreSQL/pgvector 临时数据库 mutation 用例：本机未配置 `DATABASE_URL`，故本轮不得宣称 pgvector adapter 已获得真实数据库执行验收。无新 migration，catalog 仍为 181；

因此，“缺少 pgvector adapter 代码和 sealed rows/receipt 绑定”已关闭为可测试技术合同；但“该 adapter 在临时真实 PostgreSQL/pgvector 中完成 transaction-bound mutation、重启 receipt recovery 与 replay”的环境证据仍是明确剩余项。再之后的重点是把五类 Provider 按同一 federated run 的实际部分成功/unknown/reconciliation 串联，完成 receipt 到 checkpoint/completion authority 的全链对账，补齐重庆客户真实字段/业务规则部署材料、真实多存储故障、备份/PITR、RPO/RTO、容量/生产 SLO，并获取正式客户批准、专家审定和客户生产验收。全部状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.69 pgvector 补偿 adapter 的真实 PostgreSQL 验收与测试时钟稳定化

在 8.68 记录环境缺口后，本轮复用本机运行中的隔离 PostgreSQL 16 + pgvector 容器，为 adapter 用例注入受控 `DATABASE_URL`。测试创建随机命名的临时数据库，执行既有 092/094/169/176 migration，结束后删除临时数据库；没有向客户生产库或固定业务库写入数据：

- 真实用例完成重庆技术 fixture 的 pgvector rebuild，目标 rows mutation 与 `gda_provider.pgvector_projection_repair_receipt` 在同一 PostgreSQL transaction 内提交；receipt 包含 provider transaction ID、Provider plan SHA-256、幂等键、目标内容指纹和 row count；
- 重新创建 `VectorProjectionRepairExecutor` 后，相同 sealed request 从持久 receipt 恢复并返回 `provider_idempotent_replay`，没有生成第二条 receipt；Provider receipt candidate 继续只进入 `validated_not_authority_admitted`，adapter 没有写 checkpoint 或 completion authority；
- 真实 mutation/restart/replay 专项为 `1 passed`；设置数据库连接后，vector adapter 与 executor 联合回归为 `17 passed`。不设置数据库连接时，vector adapter、executor 和 rule-contract 回归为 `30 passed, 1 skipped`，跳过项仅为明确需要真实数据库的用例；
- 回归同时发现测试信任锚只覆盖固定测试时间前后一天，运行时间跨过窗口后会把本应有效的 fixture 判为过期。非过期 fixture 已改为长期测试窗口，专门验证过期信任锚的负向用例保持不变；这只是测试时钟稳定化，不延长任何生产 trust anchor，也不构成客户规则批准；
- Ruff、Python 编译和 scoped `git diff --check` 通过；没有新增 migration，catalog 仍为 181。

因此，五类单 Provider 补偿 adapter 现在都已有受控 mutation、Provider-native receipt、重启恢复或幂等 replay 的隔离技术证据；“pgvector compensation adapter 缺少真实数据库 transaction evidence”不再是剩余需求。当前主缺口转为把 PostGIS、pgvector、RDF/Fuseki、版本化对象存储和 Spark/Iceberg 按同一 federated run 做真实部分成功、结果未知、恢复与 reconciliation 编排，并把完整 receipt set 接入 checkpoint/completion authority 对账。重庆客户字段与规则参数部署材料、真实多存储故障、备份/PITR、RPO/RTO、容量/生产 SLO、完整执行面安全、客户批准、专家审定和客户生产验收仍未完成。全部结果继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、法定审批或生产验收。

### 8.70 五类 Provider 联邦 mutation run 的分流合同

为承接五类 adapter 的 native result，本轮新增 `cross_store_projection_compensation_federated_run.py`。它只消费已 sealed 的 Provider plan/materialization，不接收 SQL、endpoint、凭证、实际 payload 或任意目标覆盖：

- `build_federated_compensation_run_bindings()` 逐位置重绑定 source plan、Provider plan、materialization、target、receipt schema 和幂等键；plan/materialization 位置或身份漂移在 Provider 调用前 fail closed；
- `execute_federated_compensation_run()` 按 0..N-1 顺序调用 adapter callback。只有 `provider_mutation_committed` 或 `provider_idempotent_replay` 才继续下一个位置；已知失败立即停止，已提交前缀进入 `partial_success_pending_reconciliation`，后续位置列为未尝试；
- unknown 结果和未分类异常统一按 `unknown_pending_reconciliation` 处理，即使 Provider 可能已经提交也不继续调用后续目标；全部位置成功或合法 replay 时才产生 `completed_pending_authority` 和 `admit_receipt_set` 下一动作；
- 结果只封存最小身份、状态、receipt SHA-256 和错误码，始终保持 `authority_admission_performed=false`、`checkpoint_authority_write_performed=false`、`compensation_completion_recorded=false`，不会伪装成跨存储事务；
- 专项覆盖五位置全成功/重放、部分成功后失败、unknown、未分类异常、未尝试位置和 Provider identity drift，共 `6 passed`；联邦 compensation 相关回归为 `183 passed, 12 skipped, 1 warning`；Ruff、Python 编译和 scoped diff 检查通过；无新 migration，catalog 仍为 181。

因此，“五类 Provider 没有统一的成功/失败/unknown/reconciliation 分流合同”已补齐为可测试技术基线，但还不是五类真实存储在同一 run 中的端到端执行验收。下一步仍需把五个具体 adapter 接入该 runner，在真实多存储环境注入部分成功、网络分区、进程硬杀和提交后未知结果，并将完成结果交给 receipt-set/checkpoint/completion authority；重庆客户规则部署、备份/PITR、RPO/RTO、容量/SLO、全执行面安全、专家审定和客户生产验收仍未完成。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.71 Provider-native result 归一化与五类 adapter 接线边界

在 8.70 的 run 分流合同之上，本轮新增 `build_federated_compensation_provider_outcome_from_native_result()`，为五类 adapter 提供唯一的结果归一化入口：

- 归一化前重新执行 native result 自身的 Pydantic sealed contract，并核对 tenant、run、position、materialization binding、Provider plan 和幂等键；调用方不能用普通字典绕过 Provider result schema；
- 只允许四类 Provider 状态映射：`provider_mutation_committed`、`provider_delete_committed`、`provider_checkpoint_recorded` → committed，`provider_idempotent_replay` → replayed；其他状态 fail closed；
- receipt SHA-256 必须从结构化 `receipt.provider_commit_ref.receipt_sha256` 读取，并与 tenant、Provider plan、幂等键一致；native result 声称已写 checkpoint 或 completion authority 时立即拒绝；
- 归一化只输出最小 outcome，不复制 rows、RDF、对象、Iceberg records、SQL 或连接信息。专项使用真实 vector adapter 的 native result 验证 committed 映射和 authority flag 篡改拒绝，联邦专项共 `7 passed`；本轮总回归为 `262 passed, 15 skipped, 1 warning`；Ruff、Python 编译和 scoped diff 检查通过；无新 migration，catalog 仍为 181。

因此，“五类 adapter 结果需要调用方自行拼装，可能把 Provider-specific 状态或 authority 写入误报为联邦成功”已关闭为统一技术合同。仍未完成的是为每个实际部署目标提供受控 callback/target registry，把五类真实 adapter 在同一 run 中执行，并将 normalized outcomes 组成完整 receipt set 后交给 checkpoint/completion authority；这些仍不代表跨存储分布式事务或生产验收。

### 8.72 五引擎受控回调注册表与 fail-closed 路由

在 8.71 的 Provider-native result 归一化边界之上，本轮在同一模块新增 `FederatedCompensationProviderInvokerRegistry` 和 `execute_federated_compensation_registered_run()`，使联邦 runner 不再由调用方为每个位置临时选择任意 callback：

- 注册表只接受 `postgis`、`vector`、`rdf`、`object_store`、`lakehouse` 五个 `ProjectionEngine` 的完整 allowlist；缺少任一引擎、未知引擎、重复项或不可调用值均拒绝，内部映射以只读 `MappingProxyType` 保存；
- 执行时先重新验证 sealed run binding，再只按其 `target_engine` 选择已注册的 native callback，并立即通过 8.71 的唯一归一化入口生成最小 outcome。callback 不能通过普通字典、自由引擎名或未注册 target 绕过身份、materialization、Provider plan、idempotency 和 receipt 校验；
- Provider 明确失败或结果未知时，runner 保持原有的停止语义：已提交前缀分别进入 `partial_success_pending_reconciliation` 或 `unknown_pending_reconciliation`，后续 Provider 不再被调用；原生 result 的配置或 sealed identity 违规则直接 fail closed，不被降级成可猜测的“未知成功”；
- 本轮 13 个联邦专项覆盖五引擎完整注册、缺失/未知引擎拒绝、按 sealed engine 路由、committed/replay 完成、known failure、unknown 停止和 native identity drift 拒绝。关闭外部数据库连接的补偿宽回归为 `268 passed, 15 skipped, 1 warning`；跳过项是未配置 `DATABASE_URL` 或不可用的外部容器镜像，warning 是既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `git diff --check` 均通过；本轮无新 migration，catalog 仍为 181；
- 这是 callback 选择和结果归一化的技术合同，不是把五类真实 adapter、重庆客户目标和真实外部存储放进同一 run 的端到端执行证据。注册表不写 receipt-set authority、checkpoint 或 completion，也不构造跨存储分布式事务。

因此，调用方可自由替换或误路由 Provider callback 的缺口已关闭为可测试基线；下一项仍是部署侧将五个已注册的真实 adapter request/executor 与其实际 target registry 接线，在隔离多存储环境演练 partial success、网络分区、硬杀、commit-after-timeout unknown、重启/reconciliation，并把完整 receipt set 受控提交至既有 checkpoint/completion authority。重庆字段映射、业务规则参数与版本、备份/PITR、RPO/RTO、容量/SLO、全执行面安全及客户/专家审批仍未完成。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

### 8.73 completed federated run 到 receipt-set 候选的指纹桥接

既有 receipt-set 会验证每个 Provider-native receipt，却不会自动证明这些回执正是本次联邦 run 的结果。本轮在 `cross_store_projection_compensation_provider_receipt_set.py` 增加 `build_federated_compensation_provider_receipt_validation_set_from_run()`：

- 只接受重新验证后处于 `completed_pending_authority` 的 sealed run；tenant、run、连续位置、已尝试位置、零未尝试位置和 `admit_receipt_set` 下一动作必须与 dispatch、Provider plan 和 materialization 全量一致；partial、failed 或 unknown run 在任何 receipt-set 生成前拒绝；
- 函数从 plan/materialization 重建每个 run binding，逐位置核对 binding SHA-256、source plan、Provider plan、idempotency key、成功/重放状态，以及 receipt validation 的 materialization/plan/target/projection/action identity；每个 `provider_receipt_sha256` 必须与 run outcome 精确相等；
- 通过后才调用既有 receipt-set builder，产物仍是 `complete_provider_receipts_pending_authority_admission`，保持全部 authority/checkpoint/completion 写入许可为 `false`，不持有 receipt document、SQL、连接信息或业务 payload，也不调用 Provider；
- 专项联合 run/receipt-set 测试为 `22 passed`，覆盖完整 run、合法 replay、回执 SHA-256 漂移和 incomplete run 拒绝。关闭外部数据库连接的补偿宽回归为 `271 passed, 15 skipped, 1 warning`；15 项跳过仍只因 `DATABASE_URL` 未配置或外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `git diff --check` 通过；无新 migration，catalog 仍为 181。

因此，“独立验证过的 receipt set 可被错误关联到另一联邦 run”已被关闭为可测试技术缺口。下一步仍是将此候选交给真实 receipt-set/checkpoint/completion authority 的受控 admission，并在五类真实 adapter 的同次运行中演练网络分区、硬杀、提交后 unknown、重启和 reconciliation。重庆字段映射和业务规则版本、备份/PITR、RPO/RTO、容量/SLO、完整执行面安全以及客户/专家批准仍未完成；状态继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表生产验收、法定审批或跨存储分布式事务。

### 8.74 注册联邦 run 的同次 native receipt 验证与候选生成

在 8.72 的五引擎回调注册表和 8.73 的指纹桥接之上，本轮新增 `cross_store_projection_compensation_federated_receipt_execution.py`。它把同一次受控 run 的 native result 与 receipt-set 候选连接起来，但不新开任何 authority 写路径：

- `FederatedCompensationProviderInvokerRegistry.invoke_native()` 仅按已重新验证的 sealed binding 调用对应引擎 callback；编排函数在本次调用内暂存 native Pydantic result，先生成最小 run outcome，避免为生成 receipt-set 再调用一次 Provider；
- 全部位置完成时，函数从内存中的 native `receipt` 生成候选、复用五类 Provider receipt validator，再调用 8.73 的 run-to-receipt-set 指纹桥接。最终输出只保留 sealed run 与 validation set，不保留 receipt document、SQL、endpoint、凭证或实际 payload；
- known failure、unknown 或未分类异常沿用 runner 的停止分流，输出 `reconciliation_or_operator_required` 且 `receipt_validation_set=null`。这阻止已提交前缀或未知结果被误报为完整、可 authority-admit 的 receipt set；
- 原生回执指纹被篡改时，回执 validator 在 receipt-set 生成前 fail closed。专项联合测试 `25 passed` 覆盖完整调用且每位置只调用一次、known failure 前缀停止、无 candidate 返回和回执篡改拒绝；关闭外部数据库连接的补偿宽回归为 `274 passed, 15 skipped, 1 warning`。跳过项仍只因 `DATABASE_URL` 未配置或外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `git diff --check` 均通过；无新 migration，catalog 仍为 181；
- 本层是单进程受控编排和回执证据衔接合同。测试使用重庆技术 fixture 的已密封三位置 materialization，同时注册表仍强制具备五引擎 allowlist；它不证明五类真实外部 Provider 已在同一部署 run 中执行，更不构成跨存储事务、checkpoint/completion authority admission 或生产验收。

因此，“同次 run 的 Provider callback 可能被重复调用，或 native receipt 与 outcome/receipt-set 仍需调用方手工拼接”的技术缺口已关闭。下一项仍是给五类实际部署 adapter request/executor 接线，并在隔离多存储环境中对 partial success、网络分区、进程硬杀、commit-after-timeout unknown、重启/reconciliation 做真实演练；之后才可将完整候选受控送入既有 checkpoint/completion authority。重庆字段映射和规则版本、备份/PITR、RPO/RTO、容量/SLO、全执行面安全及客户/专家审批继续是剩余需求。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.75 五类 Provider 的受密封部署回调工厂

在 8.74 的同次 receipt 编排之后，本轮新增 `cross_store_projection_compensation_provider_native_invokers.py`，将部署侧原本需要手工拼装的 request/executor callback 收口为五个显式、受类型约束的工厂，以及一个完整注册表 builder：

- PostGIS、pgvector、RDF/Fuseki、版本化对象存储和 Spark/Iceberg 各自只能接收对应的 sealed mutation request 与对应的 `ProjectionRepairExecutor`。错误 executor 在 callback 创建前按 configuration error 拒绝；模块不接收 SQL、endpoint、凭据、自由目标或 authority writer；
- 每次 native callback 调用均重新验证已捕获 request 和传入 `FederatedCompensationRunBinding`，逐项核对 tenant、run、position、projection、target engine/ref、source plan SHA-256、plan binding SHA-256、materialization binding SHA-256、Provider plan SHA-256 与 idempotency key；任一漂移在进入 adapter/executor 前按 `FederatedCompensationRunValidationError` 体系 fail closed；
- 只有全部身份链一致，才调用既有单 Provider adapter。因此它复用每个 adapter 的 target registry、payload 指纹、receipt 同事务/幂等与 authority-false 合同，不另建 Provider 副作用、checkpoint 或 completion 写路径；
- `build_federated_compensation_provider_native_invoker_registry()` 必须一次组装完整五引擎 allowlist，继续交由既有只读注册表根据 sealed engine 路由。专项 `3 passed` 覆盖真实内存 pgvector callback、篡改但重新封印的 run binding 在零额外执行前拒绝、错误 executor 拒绝和五类 typed callback 装配；补偿宽回归为 `277 passed, 15 skipped, 1 warning`。跳过项仍仅为未配置 `DATABASE_URL` 或不可用的固定外部容器镜像，warning 为既有 OpenTelemetry 弃用提示；Ruff 与 Python 编译检查通过。

这关闭了“五类 adapter 已存在但部署必须手工编写并信任 native callback”的接线缺口。测试中的五类 request 分别来自重庆技术 fixture，不能把它表述为五个真实外部存储已在同一 run 执行；同一重庆部署 run 的真实 target registry/request bundle、partial success/网络分区/硬杀/提交后超时 unknown/重启 reconciliation 演练，以及 receipt-set 到 checkpoint/completion authority 的真实 PostgreSQL/RLS admission 仍未完成。重庆字段映射、客户规则版本、备份/PITR、RPO/RTO、容量/SLO、全执行面安全和正式客户/专家审批也仍是剩余工作。状态继续固定为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表跨存储分布式事务、客户批准、专家审定、生产验收或法定审批。

### 8.76 重庆客户数据、字段映射与联邦部署绑定证据

本轮新增 `cross_store_projection_compensation_chongqing_deployment.py`，将“重庆客户数据集可用”从口头范围约束推进为可复核的只读部署证据包：

- `build_chongqing_federated_compensation_source_catalog()` 只读取仓库内客户提供的 `natural-resource-ontology-customer-demo-v1` bundle。它复用现有 bundle 校验，固定 `natural-resource-one-map:2.3.0:587915868b1221af` 与内容 SHA-256，输出 5 个交付工件摘要、10 条源记录角色/行数/内容摘要和 6 条源字段到自然资源本体术语的映射；不暴露客户源相对路径、几何、属性值、SQL、endpoint 或凭据；
- catalog 为每个工件、源记录和字段映射生成独立 SHA-256，并生成 field-mapping-set/catalog 总指纹。bundle ID/version、实体唯一性、排序、本体版本和技术基线用途均 fail closed；字段映射或任何 artifact 摘要漂移不能作为同一交付包继续使用；
- `build_chongqing_federated_compensation_deployment_binding()` 将该 catalog 与已 sealed 的 dispatch intent、Provider plan set 和 materialization set 逐位置绑定。它复核 tenant/run、dispatch/plan/materialization 摘要、recovery source snapshot、客户规则 ID/contract SHA-256、source plan、target engine/ref、Provider plan、idempotency key 和 materialization reference；输出仍固定为 `customer_catalog_bound_pending_provider_execution`，所有 Provider、checkpoint 与 completion 副作用标志均为 false；
- 新专项 `3 passed`，覆盖实际重庆 bundle 的本体/工件/源记录/字段映射目录、mapping fingerprint 漂移拒绝及 sealed run 绑定。与 8.75 联合后，补偿宽回归为 `280 passed, 15 skipped, 1 warning`；跳过项仍仅为未配置 `DATABASE_URL` 或不可用的固定外部容器镜像，warning 为既有 OpenTelemetry 弃用提示。Ruff 与 Python 编译检查通过。

这关闭了“重庆客户数据、字段映射、本体基线和具体联邦 run 之间没有可提交的部署证据”的技术缺口，但该 catalog 不是客户生产数据副本，也不证明任一 Provider 已执行。仍需以同一部署 target registry/request bundle 实测五个真实存储 run，演练 partial success、网络分区、硬杀、commit-after-timeout unknown 和重启 reconciliation，并将完整 receipt-set 在真实 PostgreSQL tenant RLS 下送入 checkpoint/completion authority。备份/PITR、RPO/RTO、容量/SLO、全执行面安全和正式客户/专家审批继续未完成；状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.77 重庆部署 catalog 的 registered run 执行前置校验

在 8.76 的只读部署证据之后，本轮新增 `cross_store_projection_compensation_chongqing_deployment_execution.py`，将 catalog 预检接到既有“同次 registered run + native receipt 验证 + receipt-set 候选”入口：

- `execute_chongqing_federated_compensation_deployment_with_receipt_set()` 先重新验证 customer catalog、deployment binding、dispatch intent、Provider plan set 和 materialization set，并重建当前 deployment binding；tenant/run、catalog/mapping 摘要、source snapshot、规则合同、逐位置 source plan/target/Provider plan/idempotency/materialization 必须完全一致；
- 只有当前重建结果与调用方提交的 deployment binding 完全相同，才转交现有 `execute_registered_federated_compensation_run_with_receipt_set()`。因此 catalog 或 binding 漂移在任何 Provider callback 前 fail closed；成功路径仍保证每个位置只调用一次 Provider，原生 receipt 仅在进程内用于既有校验，输出不包含客户原始数据、receipt document、SQL、endpoint 或凭据；
- 输出 `ChongqingFederatedCompensationDeploymentExecutionResult` 将 catalog/deployment 摘要与既有 registered execution 摘要再次密封，固定 `authority_admission_performed=false`、`checkpoint_authority_write_performed=false`、`compensation_completion_recorded=false`。它不会替代 receipt-set authority admission，也不把多目标调用声明为跨存储事务；
- 新专项 `2 passed`，覆盖重庆 catalog preflight 后的单次 registered run 以及 catalog binding 漂移在零 callback 前拒绝。该专项使用三位置重庆技术 fixture，而注册表本身仍要求五引擎 allowlist；补偿宽回归为 `282 passed, 15 skipped, 1 warning`，跳过项仍仅为未配置 `DATABASE_URL` 或固定外部容器镜像不可用，warning 为既有 OpenTelemetry 弃用提示。Ruff 与 Python 编译检查通过。

这关闭了“重庆部署证据虽已生成但可被绕过、直接进入 registered run”的应用层缺口。它不证明五个真实外部存储已经使用同一重庆 target registry/request bundle 执行；真实五存储 run、partial success/网络分区/硬杀/commit-after-timeout unknown/重启 reconciliation、receipt-set 的 PostgreSQL tenant RLS authority admission、备份/PITR、RPO/RTO、容量/SLO、安全及正式客户/专家审批仍未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.78 重庆客户源数据逐位置血缘与执行前置校验

第 8.77 节虽已将客户 catalog 作为 run 前置条件，但尚未能回答“某个 sealed Provider 位置本次明确选择了 catalog 中哪些客户源记录”。本轮新增 `cross_store_projection_compensation_chongqing_source_lineage.py` 与 `cross_store_projection_compensation_chongqing_source_lineage_execution.py`，继续固定重庆客户 bundle 与自然资源本体 2.3.0：

- `build_chongqing_federated_compensation_source_lineage_set()` 要求调用方为 deployment binding 的每一个 position 明确选择至少一个 catalog `source_role`；位置必须完整、唯一、有序，角色必须唯一有序且存在于已密封 catalog。每一项同时固定 deployment item、source plan/content、catalog/field-mapping 摘要，以及所选源记录的 role、content SHA-256 与 record SHA-256；不输出相对路径、原始记录、几何、属性、SQL、endpoint、凭据或 payload；
- lineage set 的 tenant/run、deployment binding、catalog、field mapping 和逐位置选择全部计入独立指纹，状态固定为 `customer_source_lineage_bound_pending_provider_execution`，Provider、checkpoint 和 completion 副作用标志均为 false；
- `execute_chongqing_federated_compensation_source_lineage_with_receipt_set()` 在任何 callback 前重新验证所有 sealed 输入，并从 lineage 内的 role selection 重建 set。任一 catalog、deployment、source plan/content、位置或角色摘要漂移都会在零 Provider callback 前 fail closed；通过后仅转交第 8.77 节既有入口，因此成功路径仍每个 fixture position 只调用一次 Provider，且不额外保存 native receipt；
- 新增源血缘及执行 preflight 专项 `7 passed`，覆盖完整三位置选择、缺失位置、未知/重复 role、摘要篡改和零 callback 拒绝；补偿宽回归为 `289 passed, 15 skipped, 1 warning`。15 个跳过项仍仅因未配置 `DATABASE_URL` 或固定外部镜像不可用，warning 为既有 OpenTelemetry 弃用提示；Ruff 通过。该专项仍是三位置重庆技术 fixture，五引擎 registry 的完整注册要求未变，不能表述为五个真实外部存储的同一 run。

这关闭了“catalog 与 run 已绑定但 source role 选择不可逐位置复核”的技术合同缺口。它不自动判断哪一种客户源组合在业务上正确，实际 selection 仍须由客户规则/部署配置形成可审计输入；也没有完成真实五存储 target registry/request bundle、故障注入与重启 reconciliation、receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority 的准入、备份/PITR、RPO/RTO、容量/SLO、安全和正式客户/专家审批。技术基线继续是 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

### 8.79 停止态联邦 run 的重庆源血缘 reconciliation case

partial success、明确失败或提交后超时的 unknown run 不能被重试掩盖，也不能丢失其对应的客户源角色。本轮新增 `cross_store_projection_compensation_chongqing_source_lineage_reconciliation.py`，把第 8.78 节的执行结果收口为只读对账案例：

- `build_chongqing_federated_compensation_source_lineage_reconciliation_case()` 只接受已密封且处于 `reconciliation_or_operator_required` 的 source-lineage execution。它重新复核 tenant/run、deployment binding、source-lineage set、catalog/field-mapping 摘要、内部 federated run 和逐位置 Provider outcome，完整成功 run 或已经形成 receipt-set 的 run 均拒绝进入此路径；
- 每个 position 都保留 deployment/lineage item、source/Provider plan、target 和 source role 摘要；状态严格归为 committed、replayed、unknown、failed 或 not-attempted，并固定下一步为保留已密封回执证据、先观察 Provider outcome、先检查失败或在前序位置对账前不得调用。案例不输出原始 receipt、provider commit reference、错误文本、客户路径、几何、属性、SQL、endpoint、凭据或 payload；
- 该模块不重试 Provider、不读取或修改 target、不写 checkpoint/completion authority。它只在已有一次停止的 run 后形成 `source_lineage_reconciliation_or_operator_required` 证据，使操作人员能够按源血缘和 run position 进行后续对账；
- 新专项 `3 passed`，覆盖 partial success、`provider_timeout_after_commit` unknown 和 completed run 误入 reconciliation 的拒绝；补偿宽回归为 `292 passed, 15 skipped, 1 warning`。跳过项仍仅为未配置 `DATABASE_URL` 或固定外部镜像不可用，warning 为既有 OpenTelemetry 弃用提示；Ruff 与 Python 编译检查通过。测试仍使用重庆三位置技术 fixture，不是五个真实外部 Provider 的故障证据。

这补齐了“停止的联邦 run 没有逐位置重庆客户源血缘对账材料”的技术缺口，但尚未执行实际 reconciliation 或任何自动重试。真实五存储 target registry/request bundle、网络分区、进程硬杀、提交后超时、重启恢复、真实 PostgreSQL tenant RLS receipt-set/checkpoint/completion authority、备份/PITR、RPO/RTO、容量/SLO、安全和正式客户/专家审批仍是未完成范围。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表生产故障演练、客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

### 8.80 重庆客户场景 source-selection profile 与强制覆盖

第 8.78 节允许调用方显式选择 catalog role，但仍可能把和平村与斑竹村场景混合，或遗漏客户 Demo 场景声明的关键源。本轮新增 `cross_store_projection_compensation_chongqing_source_selection_profile.py`，将客户提供的场景边界转成受限的技术基线：

- 从已校验的 `natural-resource-ontology-customer-demo-v1` bundle 读取场景 ID、标签和 layer 列表并只保留其 SHA-256 证据；现有 profile 固定为 `heping_review`（和平村规划地类、建设用地管制区、和平村重点项目台账及四类约束源）和 `banzhu_adjustment`（斑竹村规划地类、土地利用结构调整）。profile 仅保存角色、catalog 摘要、场景摘要和状态，不输出场景正文、路径、原始记录、几何、属性、SQL、endpoint、凭据或 payload；
- `build_chongqing_federated_compensation_profiled_source_lineage_binding()` 要求逐位置 source-lineage 的 role 并集与选定 scenario profile **完全相等**。缺失 profile role、混入另一场景 role、catalog/deployment/lineage/profile 任一摘要漂移均 fail closed，生成物仍不含 Provider、checkpoint 或 completion 副作用；
- `execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set()` 在 callback 前重新读取并构建 profile 与 binding，再转交既有 source-lineage preflight。通过路径仍每个技术 fixture 位置仅调用一次 Provider，所有 authority/checkpoint/completion 标志固定为 false；
- 新增 profile/binding/执行专项 `5 passed`，覆盖和平村完整覆盖、缺失/跨场景 role 拒绝、profile 摘要篡改、成功单次 run 和 binding drift 零 callback 拒绝；补偿宽回归为 `297 passed, 15 skipped, 1 warning`。跳过项仍仅因未配置 `DATABASE_URL` 或固定外部镜像不可用，warning 为既有 OpenTelemetry 弃用提示；Ruff 与 Python 编译检查通过。专项使用重庆三位置技术 fixture，仍不是五类真实外部 Provider 的同一 run。

该 profile 使客户提供的 Demo 场景成为可审计的技术输入，并不自动认定其 role 集合在所有业务条件下充分或正确；新增、变更或正式发布 profile 仍需由客户规则/部署治理确认。真实五存储 target registry/request bundle、故障/重启演练、receipt-set 到 PostgreSQL tenant RLS checkpoint/completion authority、备份/PITR、RPO/RTO、容量/SLO、安全及正式客户/专家审批仍未完成。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、生产验收、法定审批或跨存储分布式事务。

### 8.81 同一重庆请求束的五类真实 Provider 联动执行

第 8.80 节以前，五类 Provider 虽各自有真实 mutation/receipt/replay 证据，部署链也已能强制完整注册五引擎，但仍缺少“同一重庆 sealed request bundle 实际调用五个真实 Provider”的证据。本轮新增 `cross_store_projection_compensation_chongqing_five_provider_execution.py`，继续只使用重庆客户 bundle 和固定自然资源本体 `natural-resource-one-map 2.3.0`：

- `ChongqingFederatedCompensationFiveProviderRequestBundle` 要求同一 tenant/run、dispatch intent、Provider plan set、materialization set 和 deployment binding 中恰好包含 PostGIS、pgvector、RDF/Fuseki、版本化对象存储、Spark/Iceberg 五个位置，且位置连续、引擎不重复。请求束只保存 target/request/plan/materialization 的摘要和逻辑引用，不保存 endpoint、凭据、SQL、rows、客户原始记录、artifact path 或实际 receipt；
- `execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set()` 在第一个 Provider callback 前重新构建请求束并复核客户 catalog、场景 profile、逐位置 source lineage 和完整 invoker registry。请求、位置、引擎、部署或任一摘要漂移均 fail closed；成功路径复用既有同次 native receipt 验证，五个 Provider 各执行一次，形成 `COMPLETED_RECEIPT_SET_PENDING_AUTHORITY` 和 5/5 `validated` receipt-set；
- 真实联动使用两个随机临时 PostgreSQL 数据库、临时 Fuseki、两个隔离 MinIO 环境及 Spark/Iceberg worker。PostGIS、pgvector、RDF/Fuseki、版本化对象存储、Spark/Iceberg 均通过同一 sealed request bundle 调用；专项 `1 passed`，结束后临时数据库、bucket、容器、卷和网络均经断言清理。五类单 Provider 真实演练另为 `5 passed`；新五位置单元联动与 native invoker 回归为 `8 passed, 1 deselected`；
- 同时修复了 `cross_store_projection_compensation_provider_native_invokers.py` 对所有 request 无条件读取 `request.target` 的错误假设。RDF、对象存储和 Lakehouse request 只携带 `target_ref`，现已兼容两种受密封 request 合同并增加回归，仍要求逻辑 target 与 source plan 完全一致；
- 宽回归暴露的三个 PostgreSQL 测试问题也已修复：两个测试补齐 092/094/102/103 migration 依赖顺序；客户规则 authority 的 Python 写入口和新增 180 lifecycle guard migration 都会在数据库函数入口前拒绝 approved 后的旧草案重放，同状态重放仍幂等；gateway 直接 `INSERT` 按既有权限合同继续禁止。三个原失败用例定向为 `3 passed`，三个完整 PostgreSQL 模块为 `13 passed`；显式取消外部依赖后的 `test_cross_store_projection_compensation_*.py` 宽回归为 `211 passed, 13 skipped, 1 warning`，跳过项是数据库/外部 Provider 环境，warning 为既有 OpenTelemetry 弃用提示。

因此，“五类真实 Provider 从同一重庆请求束完成一次 5/5 receipt-set”已从剩余需求中移除。准确口径是：**在本机隔离环境中，五个真实 Provider 使用同一重庆五位置 sealed request bundle 执行，形成 5/5 validated receipt-set，停在 authority admission 之前。** 这不是跨存储事务，也不代表客户生产环境已经部署或验收。

当前仍未完成的是：网络分区、进程硬杀、commit-after-timeout unknown、重启后 reconciliation 等多存储故障演练；将完整 receipt-set 在真实部署 PostgreSQL 的 tenant RLS 下提交 checkpoint/completion authority；source-selection profile 的版本化发布、变更和回滚治理；备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO 与全执行面安全；以及客户正式确认、专家审定、法定审批和生产验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.82 五 Provider receipt-set 的 checkpoint 与 completion authority 落账

第 8.81 节的同一重庆请求束已经形成 5/5 validated receipt-set，但停在 authority admission 前。本轮新增 `cross_store_projection_compensation_chongqing_five_provider_authority.py`，将这一个已完成 Provider run 接入本机真实 PostgreSQL 的 tenant-RLS checkpoint 和 completion authority；数据范围继续只使用重庆客户 bundle，本体继续固定为 `natural-resource-one-map 2.3.0`：

- 编排入口重新验证 execution result、五 Provider request bundle、Provider plan/materialization、五个原始 `ProjectionRepairPlan` 和五个最终 target observation。它从嵌套 registered execution 中只接受 `COMPLETED_RECEIPT_SET_PENDING_AUTHORITY` 的完整 5/5 receipt-set，并按 position 重建 predecessor、candidate、admission request、authority-current read preview、write intent 和 exact checkpoint write request；request bundle、计划、物化、目标观察或摘要任一漂移都在首个 checkpoint 写入前 fail closed；
- writer 在任何副作用前先读取并核对全部五个 live predecessor，然后依 position 调用既有 `PostgresProjectionCheckpointAuthority`。首个 conflict、forbidden、validation rejection 或 outcome unknown 会立即停止，返回 `checkpoint_authority_records_incomplete_pending_reconciliation`，保留已尝试/未尝试 position，且 completion authority 零调用；只有五条 record 全部为 `created` 或 `idempotent_replay` 时才重新读取五个 current checkpoint 并允许 completion；
- 为支持整链幂等重放，authority read 现在显式区分 `candidate_predecessor` 与 `requested_checkpoint_replay`。已存在 current 只有在 source/target state、checkpoint version、repair-plan/idempotency 和 Provider plan/receipt commit evidence 全部一致，并且按同一 actor/time 重建出完全相同的 checkpoint SHA-256 后才作为 replay 接受；普通 current 漂移仍拒绝。若同一 run 的 completion 已存在，则必须再次匹配五个 checkpoint SHA-256、position、target identity、live current 和 `completed_by` 才复用，不生成第二条 completion；
- 本机运行中的 PostgreSQL 16 容器内创建随机临时数据库和随机最小权限角色，加载 092/094/169/181 migration。首次执行得到 5 条 checkpoint current、5 条 append-only history 和 1 条 completion；完整重放的五条 record 均为 `idempotent_replay`，completion 复用既有记录，数量保持 `5/5/1`。另一 tenant 读取五个 checkpoint 和 completion 均为空，证明 gateway role、`app.current_tenant` 和 RLS 隔离生效；测试结束后临时数据库和角色删除；
- 新专项在无数据库环境为 `3 passed, 1 skipped`，真实 PostgreSQL 定向用例为 `1 passed`；补偿链宽回归为 `217 passed, 11 skipped, 1 warning`。跳过项仍是未注入数据库或固定外部 Provider 环境的既有真实集成用例，warning 仍为既有 OpenTelemetry 弃用提示；Ruff 和 Python 编译通过。本轮复用 migration 169/181，没有新增 migration。

因此，“同一重庆 5/5 receipt-set 尚未接入真实 PostgreSQL tenant-RLS checkpoint/completion authority”已不再是代码与本机隔离验证缺口。准确口径是：**五个 Provider 已先完成各自 mutation 并形成 5/5 validated receipt-set，随后五个 checkpoint 逐条受控落账，全部 current 验证通过后再单独记录 completion。** Provider mutation、五次 checkpoint authority 调用和 completion 不是一个跨存储事务；部分或未知 checkpoint 结果仍必须 reconciliation，不能回滚或伪装成完成。

当前主要剩余需求转为：网络分区、进程硬杀、commit-after-timeout unknown 和重启后的真实多存储 reconciliation/案例关闭；在客户部署 PostgreSQL、账号和网络策略下复验同一 RLS 链；source-selection profile 与客户实际规则的版本化发布、变更和回滚治理；备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警和全执行面安全；以及客户正式确认、专家审定、法定审批与生产验收。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不得表述为客户批准、专家审定、法定审批、生产验收或分布式事务。

### 8.83 checkpoint authority 提交后响应丢失的 reconciliation

第 8.82 节已经保证 partial/unknown checkpoint record-set 不会写 completion，但仍缺少“数据库实际提交成功、调用方却因连接或响应丢失把结果记为 unknown”之后的显式恢复合同。本轮新增 `cross_store_projection_compensation_chongqing_five_provider_authority_reconciliation.py`，恢复范围仍绑定同一重庆五 Provider execution、5/5 receipt-set 和自然资源本体 `natural-resource-one-map 2.3.0`：

- reconciliation 只接受 `checkpoint_authority_records_incomplete_pending_reconciliation` 的先前 authority result；已经完成 completion 的 run 不能再次进入恢复。它重新验证 prior result、execution/request bundle、plan/materialization、五个 repair plan、五个 final observation，以及原 `prepared_by/prepared_at/updated_by/updated_at`。任一输入、actor 或时间戳变化都在新的 authority 写入前拒绝，不能借恢复改写 checkpoint；
- 恢复入口不接收 Provider registry、native mutation request、payload 或 executor，只重新调用 checkpoint/completion authority。输出明确保存 prior attempted/uncertain position、恢复时识别为 current replay 的 position、恢复 record-set 和 completion 状态，并固定 `provider_execution_repeated=false`、`cross_store_transaction_performed=false`；
- 内存故障注入在 position 0 先把 checkpoint 写入 ledger，再模拟连接响应丢失并抛出 authority configuration error。首次结果只有 `authority_outcome_unknown`，checkpoint 逻辑记录数为 0，completion 零调用；恢复重新读取 current，把 position 0 识别为 `requested_checkpoint_replay`，record 状态为 `idempotent_replay`，随后新建 position 1–4 并记录 completion，全程不重新执行五个 Provider；
- 真实 PostgreSQL 用例在随机临时库中先通过既有 tenant-RLS authority 提交 position 0，再故意丢弃成功响应。首次数据库状态为 `1 current / 0 completion`；reconciliation 通过新的正常连接读取该 current，最终得到 `5 current / 5 history / 1 completion`。恢复后 position 0 没有产生第二条 history，说明 commit-after-response-loss 被 current observation 收敛为幂等 replay；临时数据库和随机角色在测试后删除；
- reconciliation 专项在无数据库环境为 `2 passed, 1 skipped`，与第 8.82 节 authority 专项合并为 `5 passed, 2 skipped`，真实 PostgreSQL 定向恢复为 `1 passed, 2 deselected`；完整补偿链宽回归为 `219 passed, 12 skipped, 1 warning`。warning 仍为既有 OpenTelemetry 弃用提示；Ruff、Python 编译通过，无新 migration。

因此，“checkpoint authority 已提交但响应丢失后只能人工猜测或可能重复完成”已不再是代码与本机真实 PostgreSQL 验证缺口。系统会先停在 unknown，不写 completion；恢复时以 authority current 为准，对完全相同的 checkpoint 做幂等 replay，并只在五个 current 全部确认后完成案例。

该证据只覆盖 **checkpoint authority 层** 的 commit-after-response-loss，不等同于 PostGIS、pgvector、Fuseki、MinIO 或 Iceberg Provider mutation 自身的网络分区、进程硬杀和提交后超时恢复。剩余重点仍是五个外部 Provider 的真实 fault injection/restart reconciliation、客户部署环境复验、profile/客户规则版本治理、备份/PITR、RPO/RTO、容量与 SLO、安全及正式验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.84 PostGIS Provider 提交后响应丢失的重庆 unknown-outcome reconciliation

第 8.83 节只覆盖 checkpoint authority 已提交但响应丢失；Provider 自身 mutation 的 unknown outcome 仍需要先观察持久 receipt 和目标状态，不能把 authority 层恢复证据误写成 PostGIS 已恢复。本轮新增 `cross_store_projection_compensation_postgis_reconciliation.py`，范围仍限定为重庆客户 bundle、自然资源本体 `natural-resource-one-map 2.3.0` 和已有 source-lineage reconciliation case：

- `observe_federated_compensation_postgis_unknown_outcome()` 只接受原 PostGIS sealed mutation request、同一 `run_id/position` 的重庆停止态 case，并复核 source plan、Provider plan、materialization binding、target registry 和幂等键。它先调用受治理 executor 的 `recover_receipt()`，再观察当前目标；不接收 SQL、endpoint、凭据、自由 target 或 checkpoint/completion writer；
- receipt 存在且与当前 target/desired state 一致时，输出 `provider_commit_confirmed_from_persisted_receipt`，并生成可接回原 federated run binding 的最小 committed outcome；receipt 缺失且 target 仍等于原 sealed pre-mutation observation 时，才输出 `provider_not_committed_safe_to_resume`；receipt 缺失但 target 已变化，或 receipt/target 校验失败时，统一输出 `indeterminate_operator_required`，不猜测、不重做；
- `resume_federated_compensation_postgis_unknown_outcome()` 与观察 API 分离。它会再次实时观察，只有仍为 safe-to-resume 才调用原 PostGIS adapter；观察后 target 变化或 receipt 出现会拒绝续跑。执行结果只返回 Provider mutation result 和 normalized outcome，固定 `checkpoint_authority_write_performed=false`、`compensation_completion_recorded=false`、`cross_store_transaction_performed=false`；
- 真实 PostgreSQL 专项覆盖：未提交安全续跑、safe evidence 失效后的冲突拒绝、目标已出现但 receipt 缺失的 operator-required、mutation 与 receipt 同事务提交后调用方丢失响应的 receipt 确认，以及 receipt 保持 append-only。专项为 `3 passed`；Ruff、Python 编译通过。该演练只覆盖 PostGIS Provider，不代表 pgvector、Fuseki、MinIO 或 Iceberg 已完成同类故障演练；
- 同步在客户规则 authority Python 写入口和 180 migration database trigger 增加 lifecycle 等级前置保护：已 `customer_approved` 后重放历史 draft/awaiting 合同会 fail closed，同状态重放仍幂等。该保护不等于客户审批，也不把技术 baseline 变成生产授权。

因此，“PostGIS Provider 已提交但上层收到 timeout/unknown 后只能盲目重做”已关闭为 PostGIS 单 Provider 的可测试技术基线，并且可以把确认出的最小 outcome 接回重庆 source-lineage case。尚未关闭的是五个外部 Provider 各自的网络分区、进程硬杀、commit-after-timeout unknown、重启与真实 reconciliation；同一故障案例的五 Provider 联邦恢复和 authority 案例关闭；客户部署环境复验；profile/客户规则版本治理；备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全；以及客户正式确认、专家审定、法定审批和生产验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.85 pgvector Provider 提交后响应丢失的重庆 unknown-outcome reconciliation

第 8.84 节只完成了 PostGIS Provider 的 unknown-outcome 恢复。本轮新增 `cross_store_projection_compensation_vector_reconciliation.py`，把相同的三态判定原则落实到 pgvector，但判定证据严格采用 pgvector 自身的事务合同，而不是假定不同 Provider 的提交语义相同：

- pgvector executor 已将目标表替换和 `gda_provider.pgvector_projection_repair_receipt` 写入同一 PostgreSQL 事务。观察入口重新验证原 sealed vector mutation request、重庆 source-lineage reconciliation case 的 unknown position、source/Provider plan、materialization binding、目标注册、向量 payload 和幂等键，再分别调用 `recover_receipt()` 与实时 `observe()`；
- receipt 存在且仍与当前向量目标一致时，输出 `provider_commit_confirmed_from_persisted_receipt` 并形成可回接原 federated run 的最小 committed outcome；receipt 不存在且当前 target 与 sealed pre-mutation observation 完全相同时，才输出 `provider_not_committed_safe_to_resume`；目标已改变、receipt/target 校验失败或 receipt 后目标发生漂移时均为 `indeterminate_operator_required`；
- `resume_federated_compensation_vector_unknown_outcome()` 不信任先前的 safe 结论，会在 Provider 调用前重新读取 receipt 和 target。两次观察之间出现目标或 receipt 变化即拒绝续跑；只有 fresh live observation 仍安全时才调用既有 pgvector adapter。结果固定不写 checkpoint、不写 completion、不执行跨存储事务；
- 本机隔离 PostgreSQL/pgvector 真实专项覆盖未提交后的安全续跑、stale safe evidence 冲突、receipt 缺失但目标出现时转人工、目标与 receipt 同事务提交后调用方丢失响应的 receipt 恢复，以及 receipt 记录数保持 1。专项为 `2 passed`；与 PostGIS reconciliation、客户规则 lifecycle guard、五 Provider checkpoint/completion authority 及其恢复链联合为 `19 passed`；无外部连接的补偿宽回归为 `219 passed, 17 skipped, 1 warning`，warning 为既有 OpenTelemetry 弃用提示；Ruff 与 Python 编译通过，无新 migration；
- 此证据验证的是事务提交后**返回值丢失**和恢复后的重启式重新实例化，不等于已经完成真实网络分区或操作系统进程硬杀。它也没有替 RDF/Fuseki、版本化对象存储或 Spark/Iceberg 证明其各自的 receipt 原子性和安全续跑条件。

因此，PostGIS 与 pgvector 两类 Provider 已具备可测试的单位置 unknown-outcome 观察、判定、条件续跑和重庆 case outcome 回接；尚未完成同类 Provider-level reconciliation 的是 RDF/Fuseki、版本化对象存储和 Spark/Iceberg。之后仍需完成同一重庆五位置 case 的 `unknown → 观察 → 安全续跑 → 后续位置执行 → receipt-set 重建 → checkpoint/completion 对账 → case 关闭` 联邦编排，并补做真实网络分区、进程硬杀、客户部署环境复验、profile/客户规则版本治理、备份/PITR、RPO/RTO、容量/SLO、监控告警、全执行面安全和正式验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.86 RDF/Fuseki Provider 提交后响应丢失的重庆 unknown-outcome reconciliation

本轮将 Provider-neutral 的 unknown-outcome 证据判定抽成 `cross_store_projection_compensation_provider_reconciliation.py`，并新增 RDF/Fuseki typed wrapper `cross_store_projection_compensation_rdf_reconciliation.py`。RDF 的原子性口径严格按其自身 executor 合同处理：

- RDF executor 将目标图切换/删除与 receipt graph 的 `INSERT DATA` 组合成一次受治理的 Fuseki SPARQL update 请求；恢复入口先通过 `recover_receipt()` 解析并校验 receipt graph，再观察 Graph Store 当前图。报告把它称为“单请求原子性合同”，不把它描述为 PostgreSQL 事务或跨存储事务；
- wrapper 重新验证 RDF mutation request、重庆 source-lineage unknown position、source/Provider plan、materialization binding、target registry、ontology package 摘要、target ref 和幂等键。receipt 存在且当前图与 receipt 一致时确认提交；receipt 缺失且图仍为 sealed 前态时才允许续跑；其余状态转 `indeterminate_operator_required`；
- resume 在调用 RDF adapter 前重复一次 receipt/图观察，观察间出现图或 receipt 变化即拒绝调用；成功结果可回接原 federated run 的最小 committed/replayed outcome，观察与续跑都固定不写 checkpoint、不写 completion、不执行跨存储事务；
- RDF/Fuseki 合同专项 `2 passed` 覆盖空图安全续跑、目标图漂移冲突、receipt 缺失转人工、单请求提交后返回值丢失的 receipt 确认和错误 run case 拒绝；Ruff、Python 编译通过。通用核心不引入 migration，也不保存 endpoint、SPARQL、凭据或图 payload。

因此，PostGIS、pgvector 和 RDF/Fuseki 已分别具备单位置 unknown-outcome 的观察、三态判定、条件续跑和重庆 case outcome 回接；尚未完成同类 Provider-level reconciliation 的是版本化对象存储和 Spark/Iceberg。通用核心不改变各 Provider 的原子性边界，后续仍需同一重庆五位置 case 的联邦恢复编排、真实网络分区/进程硬杀/重启演练、客户部署复验、版本治理、备份/PITR、RPO/RTO、容量/SLO、监控安全和正式验收。状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准、专家审定、法定审批、生产验收或跨存储分布式事务。

### 8.87 五类 Provider 单位置 unknown-outcome reconciliation 技术基线收口

本轮继续复用 Provider-neutral 核心，为版本化对象存储和 Spark/Iceberg 增加 typed wrapper，至此五类 Provider 均有同一三态 reconciliation 形状，但每类仍保留自己的 receipt/原子性语义：

- 对象存储 wrapper 复核 S3 version、对象 metadata receipt 和 delete intent/delete-marker 证据；重建按“目标对象与 plan metadata 的单次 PutObject 合同”判定，删除按受密封 intent 链判定，不把两者写成无条件单请求事务；
- Lakehouse wrapper 复核 Iceberg snapshot、tombstone 和 provider receipt evidence；只在 snapshot-bound receipt 与当前 table observation 一致时确认提交，缺 receipt 且表仍为 sealed 前态时才允许续跑；
- 五个 wrapper 均绑定原 mutation request、重庆 source-lineage unknown case、source/Provider plan、materialization binding、target registry 和幂等键。每次 resume 都先做 fresh observation，任何目标/receipt 漂移均转 operator-required 或冲突拒绝；所有结果固定不写 checkpoint、不写 completion、不执行跨存储事务；
- 对象存储和 Spark/Iceberg 各新增 `2 passed` 内存/受控 Provider 专项，覆盖安全续跑、目标版本或 snapshot 漂移、receipt 缺失转人工、提交后返回值丢失后的 receipt 发现和 unknown case 绑定拒绝。此前 PostGIS、pgvector、RDF/Fuseki 各为 `3 passed`、`2 passed`、`2 passed`；通用核心、Ruff、Python 编译均通过，无新 migration。

准确口径是：**PostGIS、pgvector、RDF/Fuseki、版本化对象存储、Spark/Iceberg 五类 Provider 现在都有单位置 unknown-outcome 的观察、三态判定、条件续跑和最小 federated outcome 回接技术基线。** 其中只有 PostGIS/pgvector 在本机隔离 PostgreSQL 中做了真实数据库提交后响应丢失演练；RDF/Fuseki、对象存储、Iceberg 当前证据是受控 transport/memory，不是客户外部服务的网络分区、进程硬杀或生产验收。

因此剩余最大缺口已转为五位置联邦恢复编排：`unknown → 观察 → 安全续跑 → 后续位置继续执行 → receipt-set 重建 → checkpoint/completion 对账 → case 关闭`，以及客户部署 PostgreSQL/RLS、Fuseki、MinIO、Spark/Iceberg、账号和网络策略下的复验。备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警、全执行面安全、source-selection profile/客户规则版本发布与回滚、客户正式确认、专家审定、法定审批和生产验收仍未完成；状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，不代表客户批准或跨存储分布式事务。

### 8.88 同一重庆五位置 unknown-outcome 联邦恢复编排

本轮关闭了第 8.87 节留下的联邦层缺口：停止态 source-lineage case 不再只能停留在逐位置 triage，而可以在不重放已提交前缀的前提下重建完整证据链。

- 新增 `cross_store_projection_compensation_chongqing_federated_recovery.py`。入口同时绑定原 stopped five-provider execution、重庆 sealed request bundle、dispatch intent、Provider plan/materialization、source-lineage reconciliation case、五个 typed mutation request、五个 executor、五个 Provider recovery adapter、一次安全 observation 和后续 native invoker registry；任一 tenant/run、position、engine、plan、materialization、request 或 case 摘要漂移均 fail closed；
- 已提交前缀只通过各 Provider 的 `recover_receipt()` 重新取回并重新校验，不调用 Provider mutation；未知位置若 fresh observation 仍为 safe-to-resume，则只调用对应 typed `resume_*_unknown_outcome()` 一次；只有该位置确认完成后，才按原顺序调用后续未执行位置，后续 Provider 一旦 unknown/failed 即停止，不猜测其提交状态；
- 该流程把 prefix receipt、unknown commit/resume result 和 suffix native receipt 重新组合为新的 federated run result，复用既有 receipt validator 和 `build_federated_compensation_provider_receipt_validation_set_from_run()` 生成 5/5 candidate；完整时重建既有五 Provider execution result，直接交给既有 checkpoint/completion authority，且显式将 reconciliation case 标记为技术基线上的 closed。任何位置无法确认时不生成 receipt-set、不生成 completion；
- 新专项 `2 passed` 覆盖“position 0 已提交、position 1 unknown、position 2-4 未调用”恢复闭环和观察后目标变化停止；联同现有 federated/source-lineage/provider 回归定向为 `25 passed, 1 skipped`，补偿链宽回归为 `230 passed, 14 skipped, 1 warning`，warning 仍是既有 OpenTelemetry 弃用提示。新增结果和测试不写 authority、不保存原生 receipt document、不声明跨存储事务；

准确口径是：**GIS Data Agent 现在具备同一重庆五位置 run 的 unknown-position 观察、条件续跑、后续位置继续执行、receipt-set 重建和 authority 前对账闭环。** 这仍不是五个客户外部服务的网络分区、进程硬杀或重启实测；RDF/Fuseki、对象存储、Spark/Iceberg 的客户服务 fault injection、客户部署环境账号/网络策略复验、profile/客户规则版本治理、备份/PITR、RPO/RTO、容量与 SLO、监控安全、客户正式确认、专家审定、法定审批和生产验收继续未完成。状态保持 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.89 2026-08-18 联邦恢复异常边界与 authority 兼容复核

在第 8.88 节基础上继续收紧 resume 异常语义，仍只使用重庆客户数据集和 `natural-resource-one-map 2.3.0`：

- 当 Provider wrapper 的二次观察发现 safe-to-resume 证据已失效时，恢复结果返回 `unknown_operator_required`，并明确 `provider_invocation_performed=false`；该分支不执行未知位置的 Provider mutation，也不执行任何后续 suffix；
- 当 resume wrapper 抛出无法判断提交状态的异常，或返回无类型结果、缺失/无法重验 receipt 时，恢复结果返回新的 UNKNOWN run result，证据字段使用 `provider_invocation_performed=null` 表示“是否调用/提交不明”，不错误声称 Provider 已执行或未执行，同样停止后续 suffix；
- 两种异常都重新封存 position outcome、evidence 和 run fingerprint，保持不生成 receipt-set、不关闭 reconciliation case、不写 checkpoint/completion authority；安全成功路径仍只恢复未知位置一次，随后按原顺序继续未执行位置；
- 新增 3 条回归，覆盖 resume 异常、观察冲突和将完整恢复结果直接送入既有五 Provider authority 入口。专项恢复测试为 `5 passed`，五类 compensation 相关文件全量为 `233 passed, 14 skipped, 1 warning`；warning 仍为既有 OpenTelemetry 弃用提示，Ruff、编译和 scoped `diff --check` 均通过。

因此，联邦恢复技术闭环现在同时覆盖成功、观察冲突和“提交状态不明”的失败封存边界；这仍不是客户外部服务的网络分区、进程硬杀、真实提交后超时和重启实测。剩余需求为客户部署环境复验、RDF/Fuseki/MinIO/Spark-Iceberg fault injection、profile/客户规则版本发布与回滚、备份/PITR、RPO/RTO、容量与 SLO、监控告警、全执行面安全，以及客户正式确认、专家审定、法定审批和生产验收；不得表述为跨存储分布式事务。

### 8.90 2026-08-18 重庆客户数据聚合质量报告与失败关闭门

在客户数据固定使用重庆 bundle、本体固定使用 `natural-resource-one-map 2.3.0`、暂不等待专家审定的前提下，本轮补齐了可继续推进实施所需的数据质量技术基线：

- 新增 `chongqing_customer_data_quality.py`，先复用已封存的重庆 entity/link baseline 验证客户 manifest、两份 GeoJSON 和本体包哈希，再生成不含逐条客户记录、地块 ID 或几何正文的聚合报告；报告同时绑定 bundle manifest、两个 artifact、本体包、各 artifact profile、质量门和问题指纹，最终 `report_sha256` 可重建复核；
- 和平村变化地块共 445 条源记录、439 个稳定地块身份。`parcel_id` 有 2 个重复组、6 条附加源记录，按既有实体模型明确标记为 `allowed_identity_aggregation`，不错误当作主键质量事故；约束数据共 16 条，`(layer, BSM)` 为 16 个唯一身份并执行 `must_be_unique`；
- 地块几何为 444 个 Polygon、1 个 MultiPolygon，约束几何为 13 个 Polygon、3 个 MultiPolygon；空、非法和非面几何均为 0。两份 GeoJSON 均无旧式 `crs` member，按 RFC 7946 解释为 WGS84，经纬度 bounds 也在合法范围内；必需字段覆盖率为 100%，地类、审核状态、约束层、约束类型、严重性和本体类均封存代码域聚合计数；
- 与 entity/link baseline 对账得到 455 个实体、486 个 Link、492 个精确正面积相交观测和 472 个客户 constraint-hit 证据观测；另有 1 个低于已封存阈值的 precision sliver，作为 warning 记录并排除，不晋升为 Link；
- 质量合同不再无条件写 `passed`。artifact 哈希漂移、必需字段缺失/空值、空或非法/非面几何、超出 WGS84 范围、旧式显式 CRS、约束组合键重复、汇总计数或任一封存哈希被篡改时均失败关闭。专项 `7 passed`，Ruff、Python 编译、JSON 解析、运行时逐字段重建和 scoped `diff --check` 均通过；封存产物为 `chongqing_customer_data_quality_report_2026-08-18.json`，报告哈希为 `298957d8d820304d583ba224b3c9e07f12b1b26bcafba1fbd978cfb07d11211b`。

准确口径是：**重庆客户当前提供的两份数据可以作为 GIS Data Agent 继续实施的可追溯技术基线，当前聚合质量门通过并带 1 条精度排除警告。** 这只说明当前固定 bundle 在既定字段、几何、身份和 constraint evidence 规则下自洽，不说明任意客户数据包都能自动适配，也不替代客户业务规则确认、专家审定、法定审批或生产验收。报告固定 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`、`authority_write_performed=false`、`customer_approval_present=false`。

完成本项后，剩余真实需求主要是：在客户 RDF/Fuseki、MinIO、Spark/Iceberg 服务上做网络分区、进程硬杀、提交后超时与重启恢复；在客户 PostgreSQL/RLS、账号和网络策略下复验；建立 source-selection profile 和客户规则的版本发布、变更及回滚；实现客户规则驱动的动态补偿选择、执行与对账；扩展任意客户包适配、复杂实体冲突裁决、全执行面 Subject-Purpose-Resource 安全、自动语义规划及跨通道融合；并完成备份/PITR、RPO/RTO、容量、p95/p99、生产 SLO、监控告警和正式验收。

### 8.91 2026-08-18 数据质量哈希进入重庆部署前置合同

为避免“质量报告已经生成”与“部署证据仍引用另一份数据快照”之间出现断链，本轮继续收紧已有重庆 deployment contract：

- `ChongqingFederatedCompensationSourceCatalog` 现在强制携带 `customer_data_quality_report_sha256`；构建 catalog 时会重新生成当前 bundle 的聚合质量报告，并把报告指纹纳入 source catalog fingerprint；
- `ChongqingFederatedCompensationDeploymentBinding` 同步携带并复核同一个质量报告指纹。任何质量报告、客户 GeoJSON、manifest 或部署 catalog 漂移，均不能继续封存 deployment binding；该校验仍只读，不读取 Provider 凭据、不调用 Provider、不写 authority；
- 新增集成回归验证：修改客户副本并同步 manifest 后，即使基础 catalog 文件可读取，source catalog 也会因质量报告无法封存而失败；部署、source-selection、source-lineage 和质量测试合计 `18 passed`，五 Provider compensation 联合回归为 `241 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示。

准确口径是：**重庆客户质量报告现在是 deployment catalog 和 federated deployment binding 的强制前置证据，数据快照与部署证据不能脱钩。** 这仍不等于客户环境已经部署、Provider 已执行、客户规则已批准或生产验收已完成；状态继续为 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`。

### 8.92 2026-08-18 source-selection profile 技术发布与回滚治理

两份飞渡材料提出的“配置、规则和语义资产需要版本化、可追溯、可回滚”属于合理产品需求，但不能推导为技术版本一经发布就自动获得客户批准或生产执行权限。本轮只实现这一合理边界：

- 新增 `cross_store_projection_compensation_chongqing_source_selection_profile_release.py`，把既有 sealed source-selection profile 包装成不可变、连续的发布历史；每个 release 固定 profile、source catalog、场景证据、来源角色、前驱、全部祖先、事件类型、变更原因和 SHA-256，history 固定 active tail 与完整历史指纹；
- 初始发布只能是版本 1 且没有前驱；后续变更必须产生不同 profile 指纹并逐版本加 1；回滚不会改写历史，而是追加一个新 release，并且只能精确恢复同一历史中的较早祖先。no-op、跨场景变更、当前版本作为回滚目标、错误 rollback profile、active pointer 漂移、release 指纹或历史篡改均失败关闭；
- 所有 release/history 固定 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`、`customer_approval_present=false`、`production_execution_authorized=false`、`authority_write_performed=false`。模块不读取 Provider 凭据、不调用 Provider、不写 authority，也没有生产激活入口；
- 实际封存产物 `chongqing_source_selection_profile_release_history_2026-08-18.json` 只包含当前 `heping_review` profile 的真实 v1 技术基线，history SHA-256 为 `a2aab4fd2c794dba68f6f50ac24f18d80d959bd7bfdccc6d2f05cf86dd534fd1`。测试中的 v2 场景修订和 v3 回滚只在临时复制的 bundle 中演练，不写入该产物，也不表述为客户真实变更；
- 专项 `5 passed`，覆盖确定性与非授权发布、产物和当前运行时逐字段一致、连续变更、追加式回滚及负向篡改门禁；五类 Provider compensation 联合回归为 `246 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示。

准确口径是：**source-selection profile 的技术版本、变更和追加式回滚治理框架已经实现，当前只实际发布了 v1 技术基线。** 因此“完全没有 profile 版本治理”不再是缺口；客户实际 v2 规则内容、业务负责人批准、生产 promotion、真实回滚授权和部署环境激活仍未发生。客户规则驱动的动态补偿、真实外部 Provider fault injection、客户 PostgreSQL/RLS/账号/网络复验、任意客户包适配、全执行面安全、备份/PITR、RPO/RTO、容量/SLO、监控告警及正式验收继续是剩余合理需求。

### 8.93 2026-08-18 五 Provider 主执行入口绑定 active profile release

第 8.92 节完成了版本历史，但只有发布历史而没有执行绑定，仍可能让调用方拿旧 profile 发起执行。两份飞渡材料关于“运行时使用受控版本”的要求在这一边界上合理；它不能被扩大为技术 active release 自动取得客户批准或生产权限。本轮据此收紧现有重庆五 Provider 主执行入口：

- 新增 `ChongqingSourceSelectionProfileExecutionReleaseBinding`，把 tenant/run、deployment binding、source catalog、source-selection profile、profiled source-lineage binding、当前 active release 版本与指纹以及完整 release history 指纹封存为执行前证据；binding 固定 `customer_approval_present=false`、`production_execution_authorized=false`、`provider_dispatch_performed=false`、`authority_write_performed=false`；
- `execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set()` 现在强制接收 release history 和 execution release binding，并在任何 Provider callback 之前根据当前 sealed 输入重建 expected binding。跨租户 history、旧 active release、profile/deployment/lineage 漂移、binding 或 history 篡改均失败关闭，负向用例确认 Provider 调用计数保持 0；
- 五 Provider execution result 升级为 v2，嵌入完整 release binding，并明确 `profile_release_preflight_performed=true`。它仍处于 authority admission 之前，不写 checkpoint/completion，不增加 Provider 凭据、endpoint、payload 或新 authority，也不提供 production activation；
- 边界必须保留：底层 `execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set()` 仍是供受控编排复用的内部技术原语，本轮没有把它单独包装成新的外部生产入口。因此准确声明是“五 Provider 主执行入口受 active release 门禁约束”，不是“所有内部 helper 均已具备发布审批门禁”；
- release-binding 与五 Provider 专项合计 `19 passed, 2 skipped`；补偿链完整回归为 `248 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `diff --check` 通过。

准确口径是：**重庆五 Provider 主执行入口现在会在首个 Provider callback 前证明执行 profile 等于发布历史的当前 active 技术版本。** 这关闭了“版本历史与主执行入口脱节”的技术缺口，但不代表客户批准、生产 promotion、部署激活、authority 准入、真实外部 Provider 验收或跨存储分布式事务。后续仍需把客户真实规则审批与 production promotion 作为独立 authority 建模，决定内部 helper 的受支持调用边界，并完成客户环境 fault injection、权限/网络复验、备份/PITR、RPO/RTO、容量/SLO、监控安全及正式验收。

### 8.94 2026-08-18 五 Provider callback 前客户规则 current 绑定

第 8.93 节只解决了 profile release 的执行绑定；已有 dispatch 在生成时会重建客户规则，但 dispatch 生成后到首个 Provider callback 之间仍存在规则 current 变化窗口。两份飞渡材料关于“规则版本和运行时语义必须一致”的要求在这里合理，本轮继续收紧这一时点，不把它写成客户规则已经存在或生产授权已经完成：

- 新增 `FederatedProjectionCompensationDispatchRuleCurrentBinding`，只保留 tenant/run、dispatch/proposal/candidate、review binding、rule assessment、authority evidence 和每个已批准规则的版本/规则哈希/contract 哈希/批准 artifact 哈希/trust-anchor 哈希；不保存客户规则正文、公钥、签名或 Provider 凭据；binding 明确 `binding_grants_execution_authority=false`、`production_execution_authorized=false`、`provider_dispatch_performed=false`、`authority_write_performed=false`；
- `build_federated_projection_compensation_dispatch_rule_current_binding()` 在执行前重新验证 `FederatedProjectionCompensationRuleAuthorityAssessmentEvidence`，重新生成 review binding，并逐项比对 dispatch 的 candidate、plan、rule ID、contract 哈希和 assessment 哈希。批准规则从 `1.0.0` 变为 `1.0.1`、current evidence 缺失/不可信或 binding 指纹篡改均失败关闭；
- 五 Provider 主执行入口现在在 profile release preflight 之后、注册表和任何 Provider callback 之前执行 rule-current preflight。五 Provider result 升级为 v3，携带 rule-current binding 和 `customer_rule_current_preflight_performed=true`；负向测试确认 Provider 调用计数为 0；
- 该门禁只覆盖重庆五 Provider 主执行入口。底层 source-lineage helper 仍是内部技术原语；本轮没有新增公共执行 API、没有把 `execution_allowed=false` 改成生产许可，也没有写入 checkpoint/completion authority；
- 新增规则 current hash-only、已批准版本漂移、binding 篡改及主执行兼容回归；dispatch、五 Provider、authority、recovery 定向合计 `19 passed, 2 skipped`，补偿链完整回归为 `252 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `diff --check` 通过。

准确口径是：**当前主执行入口不会把已经生成的旧 dispatch 当作永远有效，而会在首个 Provider callback 前重新证明客户规则 current 与该 dispatch 一致。** 这关闭的是运行时规则漂移窗口，不代表仓库已有真实客户签署规则、客户生产 promotion、专家审定、法定审批或外部 Provider 运行证据。仍需客户提供真实规则和 trust anchor，建立独立 production promotion/部署 authority，明确所有内部 helper 的受支持入口，并在客户 PostgreSQL/RLS、Fuseki、MinIO、Spark/Iceberg、账号和网络策略下完成 fault injection、重启恢复、备份/PITR、RPO/RTO、容量/SLO、监控告警、全执行面安全和正式验收。

### 8.95 2026-08-18 callback 前 tenant-scoped 客户规则 live current read

第 8.94 节重新验证的是调用方提供的 evidence snapshot，尚未保证主入口主动调用 authority current reader。仓库已有 `PostgresCustomerCompensationRuleAuthorityStore.assessment_evidence_current()`，可在同一个 tenant-scoped PostgreSQL snapshot 中读取 proposal 与规则 current 并重新评估信任；本轮把这一既有能力接入主执行时点：

- 新增 `FederatedProjectionCompensationRuleAuthorityCurrentReader` 只读协议，要求 tenant 身份和 `assessment_evidence_current(run_id)`；现有 PostgreSQL authority store 结构上实现该协议，不新增写接口、migration 或公共执行 API；
- 五 Provider 主入口不再直接接收 rule evidence，而是强制接收 tenant-bound reader。在 profile release preflight 通过后、注册表验证和任何 Provider callback 之前，入口主动调用 reader；返回 `None`、租户不一致、接口缺失或 authority 读取异常均失败关闭；
- live read 返回的 evidence 仍需重新构建第 8.94 节的 rule-current binding，并与 sealed dispatch 和调用方提交的 binding 完全一致。execution result 升级为 v4，新增 `customer_rule_authority_live_read_performed=true`，但不保存规则正文、公钥、签名或 authority 查询结果；
- 新增 reader 调用和 authority outage 回归；outage 路径确认 reader 只调用一次、Provider 调用数为 0。dispatch、五 Provider、authority、recovery 定向为 `20 passed, 2 skipped`；补偿链完整回归为 `253 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示；Ruff、Python 编译和 scoped `diff --check` 通过；
- 边界必须保留：当前真实 PostgreSQL customer authority 演练因没有客户数据库与真实规则/trust anchor 而未执行，测试使用受控静态 reader。live read 与随后五个 Provider callback 也不处在同一数据库事务或分布式锁中，因此它是 callback 前的最新证据门禁，不是跨存储原子快照，也不能从理论上阻止 current 在读取后立即变化。

准确口径是：**五 Provider 主入口现在会主动执行 tenant-scoped rule-authority live read，再验证 rule current binding，失败时不调用 Provider。** “主入口只信任调用方携带的旧 evidence”不再是技术缺口；客户 PostgreSQL/RLS 实测、真实规则签名和 trust anchor、独立 production promotion authority、durable profile release authority 的 live current read、内部 helper 入口治理、外部 Provider fault injection、备份/PITR、RPO/RTO、容量/SLO、监控安全和正式验收仍未完成。

### 8.96 2026-08-18 callback 前 source-selection profile release live current read

第 8.93 节已把 active profile release 接入五 Provider 主执行入口，但此前 history 仍完全由调用方传入。版本发布后到 callback 之间同样存在 release 漂移窗口；本轮只补齐这个合理的运行时一致性门禁，不把技术 release 写成客户批准或生产 promotion：

- 新增 tenant-scoped、只读的 `ChongqingSourceSelectionProfileReleaseCurrentReader` 合同。五 Provider 主入口在 profile release preflight 后、首个 Provider callback 前按 profile/scenario 读取当前 history；reader 缺失、跨租户、返回空或抛出异常均失败关闭，Provider 调用数保持 0；
- live history 重新经过 sealed history 校验，并重新构建 execution release binding。它必须同时与调用方提交的 history、当前 profile、deployment binding、profiled source-lineage binding 和 execution binding 完全一致；历史指纹、active release 或绑定任一漂移都不能进入 callback；
- execution result 升级为 v5，新增 `profile_release_authority_live_read_performed=true`。该字段只证明 callback 前执行过一次 live read，不保存 history 正文，不写 checkpoint/completion authority，也不授予 production authorization；
- 新增成功、history 漂移、reader 空结果、reader outage、跨租户 reader 和篡改 history 六类回归。profile/five-provider 定向为 `7 passed`；扩大文件匹配、补齐此前漏掉的 recovery compensation 回归后，补偿相关全量校正为 `261 passed, 14 skipped, 1 warning`，warning 仍为既有 OpenTelemetry 弃用提示，Ruff、Python 编译和 scoped `diff --check` 通过；
- 当前测试使用受控静态 reader。协议接入不等于客户 PostgreSQL/RLS durable profile-release authority 已部署；live read 与五个 Provider callback 也不处于同一事务或分布式锁，不能阻止读取后立即发生的 release 变化。

准确口径是：**重庆五 Provider 主入口现在同时主动读取 tenant-bound 的 profile release current 和 customer-rule current，并在任一证据漂移时于 callback 前失败关闭。** 仍未完成的合理需求是：客户 PostgreSQL/RLS 中 profile release history 的 durable append-only authority、独立 production promotion/admission authority、客户真实规则与 trust anchor 接入、内部 helper 支持边界、客户五类 Provider 的 fault injection/重启复验、备份/PITR、RPO/RTO、容量与生产 SLO、全执行面安全、监控告警，以及客户正式确认、专家审定、法定审批和生产验收。不得将本项表述为客户批准、生产激活、跨存储原子快照或分布式事务。

### 8.97 2026-08-18 source-selection profile release durable authority

第 8.96 节只定义并消费了 current-reader 协议，测试 reader 仍是进程内静态对象，无法证明发布历史在重启后仍存在，也不能从 PostgreSQL/RLS 获得 tenant-bound current。两份飞渡材料关于“版本、变更、回滚和审计证据需要耐久保存”的要求在这一范围内合理；本轮实现耐久技术发布 authority，但继续把它与客户批准和生产 promotion 分离：

- 新增 migration `185_chongqing_source_selection_profile_release_authority.sql`，以完整 history snapshot 逐版本追加的方式保存技术发布历史，并提供 `security_invoker` current view；表和 current view 受 tenant RLS 约束，history 禁止 UPDATE/DELETE，gateway 只有 SELECT 和受控函数 EXECUTE，没有表 INSERT/UPDATE/DELETE 权限；
- `pyproject.toml` 的 package-data 增加 `migrations/*.sql`，避免 authority 在源码树可运行、安装 wheel 后却缺少迁移文件；无构建隔离的 wheel 已成功生成并核验包含 179、184 和新增 185 三个相关 migration；
- 新增 `PostgresChongqingSourceSelectionProfileReleaseAuthorityStore`。`record()` 只通过受控 SQL 函数追加 sealed history，`release_history_current(profile_id, scenario_id)` 直接实现第 8.96 节的 callback-time reader port，`history_snapshots()` 返回全部不可变快照；读取后仍重新执行 Pydantic 指纹与结构校验，存储损坏会失败关闭；
- SQL 入口按 tenant/profile/scenario 使用事务 advisory lock，首版必须为 v1 initial publication，后续必须逐版本加 1；新 history 删除最后一个 release 后必须与上一 current history 的完整 `releases` 数组逐字段相等，且新 tail 的 predecessor、ancestor、event kind 和 rollback target 必须一致。精确旧快照允许幂等重放但不会回退 current，竞争分支或改写旧历史会被拒绝；
- authority 仍只接受 `technical_history_active_unreviewed`、`customer_approval_present=false`、`production_execution_authorized=false` 的技术 history。数据库持久化行是 authority 写入证据，但它不改变原技术 publication 的审批状态，也没有生产激活、撤销或执行授权 API；
- 本机临时 PostgreSQL 16 真实演练为 `5 passed`，覆盖 v1 初始写入、幂等重放、v2 连续变更、v3 追加式回滚、旧快照重放不回退 current、竞争 v2 拒绝、跨租户读取隐藏和 gateway 表直写拒绝；临时数据库、角色和容器已清理。无数据库专项为 `4 passed, 1 skipped`；纳入新增文件后的补偿链全量为 `265 passed, 15 skipped, 1 warning`，唯一 warning 仍为既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 scoped `diff --check` 通过。

准确口径是：**profile release durable append-only authority 已有可部署实现，并能作为五 Provider callback 前的 current reader；本机 PostgreSQL 16 已验证，但客户 PostgreSQL/RLS 尚未部署或写入真实 history。** 因此“只有静态 reader、重启即丢失”不再是代码缺口。仍未完成的合理需求是：独立 production promotion/admission authority 及激活、撤销、回滚授权；客户数据库 migration/权限复验与显式 v1 bootstrap；客户真实规则和 trust anchor；内部 helper 调用边界；规则 action 到五类 Provider mutation 的业务映射与 reconciliation；外部 Provider fault injection/重启、备份/PITR、RPO/RTO、容量/SLO、全执行面 Subject-Purpose-Resource 安全、监控告警，以及客户、专家、法定审批和生产验收。不得将本项表述为客户批准、生产激活、跨存储原子快照或分布式事务。

### 8.98 2026-08-18 独立 production promotion/admission authority

第 8.97 节把技术 profile release 持久化，但 profile release 和 customer-rule current 都明确保持 `production_execution_authorized=false`；此前五 Provider 主入口即使验证了两类 current，也缺少第三个独立的生产准入 current。两份飞渡材料要求生产激活可审批、可撤销、可回滚且运行时绑定不得漂移，这一要求合理；本轮实现该 authority，同时不把技术基线、测试 fixture 或历史执行审批自动升级为生产许可：

- 新增 `ChongqingFiveProviderProductionAdmissionTarget`，封存 tenant、run、proposal/candidate、dispatch、plan set、materialization、deployment、五 Provider request bundle、active profile release/history、rule-current binding/assessment/evidence 和已批准 rule contract 哈希。target 保留 `technical_baseline_unreviewed`、`assisted_precheck_not_for_production_decision`，并固定 `technical_baseline_grants_production_authority=false`；构建 target 本身不产生 grant；
- 新增 append-only admission lifecycle。v1 只能是带明确到期时间的 `promotion`，且 `authorized_by` 必须为 `human:*`，同时封存 authorization artifact 和 trust-anchor 哈希；活动 grant 后只能追加 `revocation`，revoked 后才可追加新 promotion 或指向历史活动 grant 的 rollback。rollback 是新的有时效授权事件，不修改或复活旧行；缺失、未生效、到期和撤销 history 的 `authorizes()` 均返回 false；
- 新增 migration `187_chongqing_five_provider_production_admission_authority.sql` 和 `PostgresChongqingFiveProviderProductionAdmissionAuthorityStore`。数据库按 tenant/run 保存完整 history snapshot，强制版本连续、旧 events 前缀逐字段不变、predecessor/ancestor 连续、active→revocation→promotion/rollback 状态机及 rollback target 一致；表启用并强制 tenant RLS，UPDATE/DELETE 由不可变 trigger 拒绝，gateway 无直接 INSERT/UPDATE/DELETE 权限，只能 SELECT 或调用受控追加函数；
- 五 Provider execution result 升级为 v6，主入口在 registry 和任何 callback 之前依次实时读取 profile-release current、customer-rule current 和 production-admission current。admission history 必须与调用方 snapshot 相同，current event 的完整 target 必须由前两类 live current 和当前 sealed execution 重新构建且逐字段相等，并在 callback 时点处于有效期；authority 缺失/故障/跨租户、history 漂移、target 漂移、撤销或到期全部失败关闭，五类 Provider 调用数为 0；
- recovery reseal 已适配 v6 admission event 的 UTC 时间 canonicalization，unknown-position recovery 仍不重放已提交前缀，恢复后的 execution result 可继续进入既有 checkpoint/completion authority；
- 无数据库 production-admission authority 专项为 `7 passed, 1 skipped`；五 Provider 与 admission 合并专项在修复前置测试夹具后为 `27 passed, 2 skipped`。本机隔离 PostgreSQL 16 定向为 `1 passed`，覆盖 v1 promotion 幂等、revocation、rollback、current/history、竞争分支拒绝、跨租户隐藏和 gateway 表直写拒绝；临时数据库和角色已清理。完整补偿链最终回归为 `269 passed, 16 skipped, 1 warning`，唯一 warning 仍为既有 OpenTelemetry 弃用提示；Ruff、Python 编译、scoped `diff --check` 和 wheel migration 打包检查通过。

准确口径是：**仓库现已具备独立、耐久、可撤销和可追加回滚的五 Provider production admission authority，主入口默认无 grant，并在 callback 前强制 live-read current admission。** 仓库没有为任何客户签发真实 production grant，也没有部署 migration 187；测试使用的 `human:*`、artifact 和 trust-anchor 哈希是受控 fixture，不是客户身份认证、签名验证或审批证明。客户仍需在其控制面验证审批人权限与签名/trust anchor，部署 migration 185/187，显式 bootstrap release v1 并签发 admission v1，完成五类 Provider fault injection/重启、备份/PITR、RPO/RTO、容量/SLO、监控告警和正式验收。仓库侧剩余合理需求收敛为：内部 source-lineage helper 入口治理；客户规则 action 到五类 Provider mutation/reconciliation 的业务映射；全执行面 Subject-Purpose-Resource 权限、审计、监控和告警；以及任意客户包适配、复杂实体冲突裁决、自动语义规划、跨通道融合和双时态业务适配。客户、专家、法定审批和生产验收仍只能由相应责任方完成。

### 8.99 2026-08-18 内部 source-lineage mutation helper 入口治理

第 8.98 节只保证 v6 主入口具备三类 callback 前 live-current admission；deployment、source-lineage 和 profiled source-lineage 三层组合 helper 仍公开导出并可直接持有完整 Provider registry，内部调用方可能绕过主入口。两份飞渡材料关于“执行入口受控”的要求在这里合理，但不能把 Python 模块私有约定夸大为操作系统安全边界。本轮以默认失败关闭的进程内 permit 收紧支持面：

- 新增 `cross_store_projection_compensation_chongqing_internal_execution.py`。permit 不可序列化、不写入任何 result，精确绑定 tenant、run、dispatch 指纹和同一个 registry 对象；缺失、伪造、跨 run 或跨 registry 重放均在任何 Provider callback 前失败关闭；
- 三层低层 mutation helper 已从各自 `__all__` 移除，并增加默认值为 `None` 的 keyword-only permit 参数。函数名仍供模块内部显式组合，但不再是受支持的公共导出；只删除导出名并不足以治理，因此每一层入口都独立执行运行时 permit 校验，不能从中间层绕过；
- v6 `execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set()` 只在 profile-release current、customer-rule current、production-admission current、完整 target、有时效 grant 和五引擎 registry 全部通过后签发 governed permit。permit 再绑定 current admission event 哈希和 callback 评估时点；技术 release/rule binding 仍保持 `production_execution_authorized=false`，只有独立 admission current 决定是否进入生产 callback；
- 内部合同与 reconciliation fixture 只能显式使用 `technical_contract_test` 或 `reconciliation_fixture` permit，并强制声明 `production_execution_authorized=false`。新负向用例覆盖三层无 permit、技术 permit 冒充生产授权和跨 registry 重放，全部确认 Provider 调用数为 0；
- unknown-position recovery 不调用这三层 helper，也没有取得技术 permit。它继续要求已有受治理的 v6 停止态 result，只处理一个 unknown 位置和未尝试后缀，不重放已提交前缀；本轮未改变 recovery 算法、checkpoint/completion authority 或 Provider adapter；
- 新入口治理专项为 `8 passed`，三层 helper、source-lineage reconciliation 联合为 `17 passed`；v6、authority、五类 Provider reconciliation 和 recovery 联合为 `39 passed, 5 skipped`。完整补偿链为 `287 passed, 16 skipped, 1 warning`，唯一 warning 仍是既有 OpenTelemetry 弃用提示；Ruff、Python 编译、静态注册扫描和 scoped whitespace 检查通过。本轮无 migration，也没有新增 API、Capability 或 MCP mutation 入口。

准确口径是：**重庆五 Provider 生产执行的受支持入口已收敛到 v6 governed 主入口，低层 helper 默认无 permit 即失败关闭。** 这是防止误用和未受支持内部编排的进程内 capability boundary，不是对同一 Python 进程内恶意代码的沙箱，也不替代进程身份、Subject-Purpose-Resource 授权、签名验证或客户控制面。仓库仍没有真实客户 production grant，测试 permit、`human:*`、artifact/trust-anchor 哈希均不是客户认证或审批证据；live read 也不是跨存储原子快照或分布式事务。下一项仓库侧合理需求是客户规则 action 到五类 Provider mutation/reconciliation 的业务映射，其后仍需全执行面授权、审计、监控告警和更通用的数据/语义能力；客户环境的 migration、真实 grant、fault injection、备份/PITR、RPO/RTO、容量/SLO 和正式验收仍由相应责任方完成。

### 8.100 2026-08-18 客户规则 action 到五类 Provider 请求与 reconciliation 的可验证绑定

第 8.99 节收敛了受支持执行入口，但客户签名规则此前只绑定 action、适用目标和所需证据，仍不能证明部署 adapter 选择的逐位置 Provider operation、native request 和 unknown-outcome 处理就是客户批准的语义。本轮在不改变客户规则 JSON schema、不过度声称客户已签署的前提下，以既有 `approval_artifact_sha256` 绑定 proposal-specific action map：

- 新增 `cross_store_projection_compensation_customer_action_mapping.py`。`CustomerCompensationRuleProviderActionMap` 精确绑定 tenant/run、proposal/source snapshot、candidate/action/scope、客户规则 ID/版本/规则指纹，以及每个 position 的 plan、engine、target、Provider action；每项同时固定 `observe_receipt_and_target_then_resume_if_safe`、`committed_prefix_replay_allowed=false` 和 `unknown_position_resume_attempt_limit=1`。map 及其 execution binding 均固定 `production_execution_authorized=false`，不会替代第 8.98 节的独立 production admission；
- `CORRECTIVE_FORWARD` 只接受原 sealed plan operation；`DELETE_TARGET` 的客户语义固定映射为 `delete`，`RESTORE_TARGET` 固定映射为 `rebuild`。如果后续 plan/materialization/native request 没有实现同一 action，execution binding 在 callback 前拒绝，而不是把原 forward plan 偷换成客户动作。`ROLLBACK_COMMITTED_PREFIX` 在没有 customer-derived reverse plans 时不能生成 action map，明确失败关闭；
- callback-time execution binding 从同一次 live rule-authority evidence 取得当前 customer-approved contract，重新生成已签 action map，并逐位置连接 dispatch、Provider plan、materialization、native request 和 request bundle。它封存 source/plan/materialization/provider/idempotency/request/execution-plan 摘要；签名 artifact 不等于 action-map hash、规则 current 漂移、position/target/action/request 任一不一致均在 permit 签发和首个 Provider callback 前失败；
- 重庆五 Provider result 升级为 v7，携带完整 action map、execution binding 和五个 hash-only request item。result validator 将 proposal/candidate、rule contract/approval artifact、action-map item、request SHA、projection、source plan、plan/materialization、Provider plan、idempotency、execution plan 与 production-admission target 交叉验证，防止只重算外层 result hash 隐藏内部漂移；mapping evidence 仍为非生产证据，最终 `production_execution_authorized=true` 只来自独立且当前有效的 admission event；
- unknown-position recovery 现在重新验证 prior v7 中的 action map、execution binding、五个 request item 和逐位置 reconciliation policy；已提交前缀继续只读恢复 receipt、不重放 mutation，同一次 recovery invocation 最多进入一次 typed unknown resume。跨进程/重启后的 durable attempt-budget consumption 仍需要独立 current/ledger 或与 recovery-job CAS 的正式集成，本轮不把进程内结构夸大为全局 exactly-once；
- 新增测试覆盖 5/5 corrective-forward request 绑定、DELETE/RESTORE 映射、无 reverse plan 的 rollback 拒绝、签名 artifact 漂移、Provider action 漂移、plan-set 和 request/projection 重封装漂移，所有负向路径 Provider 调用数为 0。rule/approval/dispatch/action-map 基础联合为 `39 passed`；five-provider/authority/五类 reconciliation/recovery 扩大回归为 `80 passed, 4 skipped, 1 deselected`；完整 compensation 回归为 `294 passed, 16 skipped, 1 warning`，唯一 warning 仍是既有 OpenTelemetry 弃用提示。Ruff 和 Python 编译通过；没有新增 API、Capability、MCP mutation 入口或 migration。

准确口径是：**当前 customer-approved corrective-forward 规则已能在受治理主入口中证明其 action map 覆盖五类 Provider 的 5/5 native request，并绑定既有安全 reconciliation 语义；DELETE/RESTORE 的客户动作映射已显式建模，但只有部署链提供相符的客户派生 native plan 时才可执行；ROLLBACK 在 reverse plan 缺失时失败关闭。** 仓库仍无真实客户 production grant，测试 `human:*`、artifact 和 trust-anchor 哈希不是客户认证或签名证明；live current read 也不是跨存储原子快照或分布式事务。后续仓库侧重点是 durable recovery attempt ledger/CAS、全执行面 Subject-Purpose-Resource 权限、审计和监控告警，以及更通用的客户包、实体冲突、自动语义规划、跨通道融合和双时态适配；客户环境 migration、真实规则/签名/trust anchor、外部 Provider fault injection、备份/PITR、RPO/RTO、容量/SLO 和正式客户/专家/法定审批及生产验收仍未完成。

### 8.101 2026-08-18 unknown-position 恢复单次尝试的耐久 ledger/CAS

第 8.100 节已经把 action map 和逐位置 reconciliation policy 带入 recovery，但“同一次调用最多恢复一次”仍是进程内约束：进程重启或两个并发 worker 可能同时看到 `provider_not_committed_safe_to_resume`，从而重复进入同一 unknown 位置。本轮把这一剩余仓库需求实现为 callback 前的耐久单次准入，同时继续把它与 Provider 侧全局 exactly-once、跨存储事务和客户生产部署区分：

- 新增 sealed `ChongqingFederatedCompensationUnknownResumeAttemptRequest/Receipt`。request 精确绑定 tenant/run、prior v7 result、reconciliation case、request bundle、action map、action execution binding、position/engine/request、unknown outcome、fresh observation、attempt ID、actor 和时点，并固定 `expected_consumed_attempts=0`、`attempt_limit=1`、`committed_prefix_replay_allowed=false`、`provider_invocation_performed=false`、`production_execution_authorized=false`；receipt 固定 `attempt_number=1`、`authority_write_performed=true`、`cross_store_transaction_performed=false`；
- 新增 migration `188_chongqing_five_provider_unknown_resume_attempt_authority.sql` 与 tenant-bound `PostgresChongqingFiveProviderUnknownResumeAttemptAuthority`。PostgreSQL 以 tenant/run/request-bundle/position 为预算身份，在 transaction advisory lock 下执行 `0 -> 1` CAS；ledger 只追加，current view 使用 `security_invoker`，表启用并强制 tenant RLS，UPDATE/DELETE 由不可变 trigger 拒绝，gateway 只有 SELECT 和受控函数 EXECUTE，没有直接 INSERT/UPDATE/DELETE 权限；
- recovery 仅在 fresh observation 明确为 `provider_not_committed_safe_to_resume` 时消费 attempt；已由 persisted receipt 确认提交或需要 operator 的分支不消耗预算。CAS receipt 必须在 `resume_unknown()` callback 前成功并与 sealed request 完全相等；并发、重启后重试、重复调用、跨租户 authority、authority 故障或 stale predecessor 均失败关闭，不触碰 Provider；
- recovery position evidence 与 recovery result 升级为 v2，并把 receipt SHA 和完整 typed receipt 分别绑定到恢复位置及整体结果。成功 resume 或 resume 后结果再次不确定都保留已消费 receipt；已提交前缀始终只恢复既有 receipt、从不重放 mutation。若进程在 CAS 成功后、Provider 结果落证前崩溃，预算保持已消费，自动恢复继续失败关闭，必须人工核验 Provider 状态后走正式 reconciliation；
- migration catalog 已更新到 `188` 项，两个 deployment profile 的 catalog fingerprint 均为 `157e44785e9d6a7547ef78a8a794b8e00040d5fb9ce320a742127cd5b3b22a55`。wheel `gis_data_agent-23.0.0-py3-none-any.whl` 已核验包含两个新模块、更新后的 recovery、测试和 migration 188；
- recovery/attempt 定向为 `10 passed, 1 skipped`；隔离 PostgreSQL 16 真实 authority 演练为 `5 passed`，覆盖单次消费、两个并发消费者仅一个成功、RLS、无表直写和历史不可变；补偿前缀全量为 `286 passed, 20 skipped, 1 warning`，附加 recovery/federated recovery 为 `57 passed, 2 skipped`，migration runner/deployment profile 为 `30 passed`。这些套件有重叠，不能相加；唯一 warning 仍是既有 OpenTelemetry 弃用提示。Ruff、Python 编译和 `git diff --check` 通过，临时 PostgreSQL 16 容器已清理，未改变既有容器或连接。

准确口径是：**同一 tenant/run/request-bundle/unknown position 的自动 resume 预算现在会在 Provider callback 前由 PostgreSQL 原子地从 0 消耗为 1，并能跨 worker 与进程重启拒绝第二次自动尝试。** 这提供的是耐久 single-attempt admission，不是 Provider 侧全局 exactly-once：authority 写入与外部 Provider mutation 不在同一分布式事务中，CAS 后崩溃会保守转人工核验。仓库也未在客户环境部署 migration 188，未执行真实五 Provider 外部 fault injection，未获得客户 production grant、签名、trust anchor 或正式验收。后续仓库侧重点转为全执行面 Subject-Purpose-Resource 权限、审计和监控告警，以及更通用的客户包、复杂实体冲突、自动语义规划、跨通道融合和双时态适配；客户侧仍需 migration/权限部署复验、真实审批、Provider 故障与重启、备份/PITR、RPO/RTO、容量/SLO 和正式客户/专家/法定审批及生产验收。

### 8.102 2026-08-18 五 Provider 主执行与 unknown recovery 的 SPR live authorization

第 8.101 节解决了 resume attempt 的耐久单次预算，但 production admission 只回答“这一条技术执行链是否被独立 grant”，此前仍没有回答“哪个实际 workload、以何种受控 purpose、访问哪些 Provider 资源和动作”。仓库已有通用 `SubjectContext`，本轮将 Subject-Purpose-Resource 门禁接入重庆五 Provider 受支持主入口和其 unknown-position recovery；范围只覆盖这两个入口，不把它夸大为查询、地图、下载、RAG、MCP 等全通道安全已经完成：

- 新增 `cross_store_projection_compensation_chongqing_execution_security.py`。sealed security request 固定 purpose `cross_store_projection_compensation@v1`，要求 tenant-bound workload `SubjectContext`、trace ID 和可追踪 delegation identity，并绑定 run、operation、request bundle、action map/execution binding、production-admission event、评估时点及五个有序 Provider 资源；每项绑定 position、engine、target、Provider action、request、action-map item 和 action-execution item 摘要，不保存 endpoint、凭据或 payload；
- 新增 tenant-bound `ChongqingFederatedCompensationExecutionSecurityCurrentReader` port 和 sealed allow/deny decision。决策保存 policy ref/version、独立 workload evaluator、有效期和 obligation；入口只接受 exact request、当前有效的 `allow`、独立 evaluator 和空 obligation。跨租户 reader、读取故障、deny、过期、scope 漂移或当前未实现的 obligation 均失败关闭。安全 decision 固定 `decision_grants_production_admission=false`，不能替代第 8.98 节的独立 production admission；
- 五 Provider execution result 升级为 v8。主入口在 profile/rule/admission 三类 live current 通过后、内部 permit 签发和首个 Provider callback 前读取 SPR current；`SubjectContext` actor 必须等于五个 native request 的 `dispatched_by` workload。governed process-local permit 现在同时绑定 current admission event SHA 与 SPR decision SHA，低层 helper 不能只凭 admission 绕过该门禁；result 再逐位置交叉验证 security resource 与 v7 action/request binding；
- recovery result 升级为 v3。recovery 的独立 operation 绑定 prior v8 result、reconciliation case、fresh safe observation 和 unknown position；五资源中 committed prefix 标记为 `read_receipt`，unknown 及未尝试后缀标记为 `mutate`。recovery actor 必须等于 `reconciled_by`，SPR allow 必须先于任何 prefix receipt 读取、attempt CAS 或 Provider callback；拒绝路径确认 attempt ledger 未消费且 Provider callback 计数不增加；
- 负向基线覆盖错误 purpose、主体/dispatcher 不一致、deny、过期、未知 obligation、跨租户 reader、安全资源重封装以及 recovery deny，均在 Provider access 前失败关闭。主入口 SPR 定向为 `7 passed, 22 deselected`，recovery 为 `7 passed`，内部 permit/authority/reconciliation 为 `13 passed, 2 skipped`；完整 compensation 回归为 `296 passed, 17 skipped, 1 warning`，额外 federated recovery/recovery compensation 为 `21 passed, 1 skipped`。唯一 warning 仍为既有 OpenTelemetry 弃用提示；套件口径不同，不相加；
- 本轮无 migration，catalog 仍为 188 项，deployment profile fingerprint 不变；没有新增 API、Capability、MCP 或 app 注册。Ruff、Python 编译、`git diff --check` 和静态注册扫描通过；新建 wheel 已核验包含 execution-security、v8 main、v3 recovery、internal permit 和相关测试。

准确口径是：**重庆五 Provider 受支持主执行入口和其 unknown-position recovery 现在都要求 callback-time exact-scope SPR live allow；错误主体、purpose、资源、动作、有效期或 policy 状态不会进入 Provider access。** 这仍不是“全执行面安全已完成”：测试使用进程内 reader，尚无客户 policy engine/durable current adapter、受控 Purpose registry authority、policy decision ledger、审计写入失败关闭、Prometheus 指标/告警或跨 API/地图/下载/RAG/MCP 的统一负向矩阵；recovery 函数外部取得 initial safe observation 的调用面也不在本轮门禁内。仓库仍无真实客户 production grant、规则签名/trust anchor、客户部署或外部 Provider fault injection。下一仓库侧优先级是把 SPR decision 与既有 immutable security event ledger、operation receipt 和监控告警做 fail-closed 绑定，再扩展到 observation acquisition 及其他通道；客户侧仍需真实 policy/identity provider、migration/权限、备份/PITR、RPO/RTO、容量/SLO 和正式验收。

### 8.103 2026-08-19 SPR decision 与 immutable security audit/Prometheus fail-closed 绑定

第 8.102 节已经把 callback-time exact-scope SPR live allow 接入重庆五 Provider 主执行和 unknown recovery，但此前 SPR decision 仍未强制进入既有 immutable security event ledger，Provider 结果也没有统一的 outcome 账本闭环。本轮继续限定在这两个受支持 mutation 入口：

- 新增 `cross_store_projection_compensation_chongqing_security_audit.py`。审计适配层采用两阶段合同：Provider access 前必须记录 `admitted` 事件，Provider 结果生成后必须记录 `outcome` 事件；记录内容绑定 tenant/run、operation、controlled purpose、workload subject、request SHA、SPR decision SHA、policy ref/version 和完整五资源 scope 摘要，不保存 endpoint、凭据或 payload；
- 主 execution result 增加 typed security audit admission/outcome。admission 写入失败时在首个 Provider callback 前 fail closed；outcome 写入失败时不返回成功 execution result，即使五个 Provider 已完成也保留未闭合 admission，交由 reconciliation 处理；成功结果要求 outcome 为 `success` 且 `provider_invocations=5`；
- recovery result 同样绑定 typed admission/outcome。recovery admission 写入发生在 prefix receipt 读取、unknown attempt CAS 和任何 Provider callback 之前；成功 receipt-set 记录 `success`，观察冲突、operator-required 或提交状态不明记录 `unknown`，不允许把异常路径伪装成成功；
- 默认 durable adapter 复用既有 PostgreSQL tenant-RLS `SecurityEventLedger` 和 migration 110/111 的受控函数、append-only hash chain 与 operation-receipt 边界；内存 adapter 仅用于隔离合同测试，不等同于客户 durable current 或客户策略引擎；
- `observability.py` 新增 `agent_security_execution_audit_events_total{operation,phase,outcome}`。Prometheus 新增 `GovernedExecutionAuditFailure` 和 `GovernedExecutionAuditAdmissionWithoutOutcome`：失败/未知 outcome 触发 critical，admission 长时间高于 outcome 触发 warning，明确把未闭合执行交给 reconciliation；
- 新增审计合同、主执行 admission/outcome、主执行审计故障、recovery admission 故障、跨租户和告警规则负向覆盖。新增纯审计专项为 `3 passed`，本轮新增重庆审计负向为 `3 passed`，Ruff 与 Python 编译通过。现有全量回归需结合当前工作区其他改动重新执行，不能把本轮定向结果与历史套件机械相加；

准确口径是：**重庆五 Provider 受支持 execute/recovery 现在要求 SPR decision 先形成 immutable security admission event，结果再形成 immutable outcome event；账本或审计端口不可用时不会返回可继续送 authority 的成功结果。** 这仍不是全执行面审计完成：查询、地图、下载、RAG、MCP 和 observation acquisition 尚未接入同一矩阵；当前 policy reader 仍不是客户 policy engine/durable policy current，客户环境尚未部署 migration、真实 identity/purpose provider、外部 Provider fault injection、Prometheus production route、备份/PITR、RPO/RTO、容量/SLO 或正式客户/专家/法定审批。未闭合 admission 仅表示需要 reconciliation，不表示 Provider 全局 exactly-once、跨存储事务或生产验收。

### 8.104 2026-08-19 不完整 Provider run 的 failure/unknown 审计闭环

对第 8.103 节再做一次异常路径复核，重点修复“底层 run 已经返回 partial/unknown，但五 Provider 外层仍可能把结果写成 success”的合同缺口：

- 五 Provider 外层现在读取已封存的 registered execution state。只有完整 5/5 receipt set 才记录 `success`、evidence 为 request bundle SHA-256、`provider_invocations=5`；`failed_closed` 或 partial-success 记录 typed `failure`，unknown run 记录 typed `unknown`，evidence 绑定 federated run result SHA-256，调用次数绑定实际已执行 prefix；
- 非完整 run 不再被伪装为成功结果，但仍返回可供 recovery 使用的封存执行证据；它不包含 authority admission、checkpoint 或 completion 权限。这样 recovery 可以消费原始 unknown/failed run，而不会丢失 callback 前后的事实边界；
- recovery 生成新的恢复 operation audit。直接恢复成功记录 recovery `success`，观察冲突、operator-required 或提交状态不明记录 recovery `unknown`；恢复后的 `recovered_execution_result` 保留原始 execute audit 的 failure/unknown 事实，不把一次新的 recovery 事实改写成原始 execute success；
- 新增不完整 Provider run 的 typed failure 审计回归，三套核心专项当前完整运行结果为 `42 passed, 1 skipped`。Ruff、Python 编译和 scoped diff 检查通过；唯一跳过项仍为未配置 `DATABASE_URL` 的真实外部环境测试。

准确口径是：**五 Provider execute 现在对完整成功、已知失败和未知结果分别落账，recovery 不会覆盖原始 execute 审计事实。** 这仍不是全执行面生产审计、外部 Provider fault injection 或跨存储事务；客户 policy/identity provider、Prometheus production route、备份/PITR、RPO/RTO、容量/SLO、migration/权限部署和正式验收仍待完成。

### 8.105 2026-08-19 统一语义查询通道的 SPR live 门禁与不可变审计合同

在五 Provider mutation 审计闭环之后，本轮把同一安全边界扩展到统一 `semantic.query.execute@4.1.0` 查询入口，仍严格区分技术合同与客户生产控制面：

- 新增 `governed_query_security.py`，按 tenant、request、purpose、channel、adapter、资源版本和主体上下文构造 hash-bound SPR request；ontology、metric、NL2SQL、GIS、RAG 五类查询 adapter 调用前读取 live decision；
- decision 必须与 request 精确相等、当前有效、`allow` 且无未实现 obligation；reader 缺失、跨租户、异常、过期、scope 漂移或 admission audit 失败时，查询在 adapter access 前失败关闭；
- 查询返回前写 outcome audit：完成、计划或已准入结果记 `success`，adapter 错误或结果资源绑定不一致记 `failure`；outcome audit 写入失败不会返回成功响应；
- 提供隔离测试用内存 audit adapter，并提供复用 PostgreSQL tenant-scoped `SecurityEventLedger` 的 durable adapter；本轮无新增 migration，测试 reader 不是客户 policy engine；
- 新增查询安全专项，和既有查询回归合计 `25 passed, 1 warning`；Ruff、Python 编译和 scoped diff 检查通过。

准确口径是：**统一查询入口已具备 callback 前 exact-scope SPR live allow 和结果不可变审计的仓库技术合同。** 仍未完成客户真实 policy/identity/purpose provider、查询结果读取/缓存/地图/报告/下载/RAG/MCP 的全通道负向矩阵、Prometheus production route、客户部署、备份/PITR、RPO/RTO、容量/SLO 和正式验收；本节不代表全执行面安全、客户生产授权或跨存储事务。

### 8.106 2026-08-19 governed-query HTTP 入口的安全端口装配与生产 fail-closed

上一节的查询安全合同已经覆盖统一查询函数，但公共 HTTP 路由仍需明确“未配置客户安全控制面时不得悄悄降级”。本轮完成：

- 增加部署侧 tenant resolver，服务端按 tenant 取得 live policy reader 与 immutable audit port；请求不能提交 resolver、policy decision、audit adapter 或任何替代身份；admission 事实显式保存 `subject_ref`；
- 生产/staging Compose 固定 `GDA_GOVERNED_QUERY_SECURITY_REQUIRED=1`。开关开启时 resolver 缺失、异常、返回非法端口、跨租户或布尔值非法，API 在任何查询 adapter 调用前返回 `503`；本地开发只有显式保持 `0` 才允许兼容模式；
- `/ready` 同步检查该门禁，resolver 缺失时实例为 `not_ready`，避免安全依赖未装配却继续接收流量；
- 新增 HTTP 正向和负向回归，覆盖 allow、deny、无 resolver、resolver 异常、非法开关和 adapter 零调用；三套查询专项回归 `40 passed, 1 warning`，Ruff、编译、diff check 和 Compose config 解析通过。

准确口径是：**查询 API 的生产配置现在具备安全端口缺失即 fail-closed 的技术边界。** 该 resolver 仍需客户部署真实 policy/identity/purpose 控制面和 durable current；本轮不代表客户生产安全、全执行面矩阵、灾备/SLO 或正式验收已经完成。

### 8.107 2026-08-19 governed-query policy current authority（开发阶段）

本轮将查询安全的策略生命周期继续收敛到仓库内可验证的开发合同：新增 tenant-bound purpose 注册、不可变 policy version、追加式 revocation、最新版本 current 选择和默认 deny reader；匹配同时检查 evaluated-at 与当前时间，避免未来策略提前生效。同一 `policy_ref` 的新版本不会让旧版本回退，撤销/重复发布发生内容漂移时失败关闭。

新增 `data_agent/migrations/190_governed_query_policy_authority.sql`，定义 purpose、policy version、revocation 的 tenant-RLS 表、append-only trigger 和 gateway 只读权限；新增内存 authority/resolver 仅用于开发运行和合同测试。专项 `8 passed`，与统一查询、查询安全、HTTP、health 受影响专项合计 `75 passed, 1 warning`，Ruff 与编译通过。

准确边界是：**开发阶段已经具备可版本化、可撤销、tenant-bound 的 query policy current 技术合同。** 本节形成时 PostgreSQL 受控写入和应用启动装配尚未完成，现已由第 8.108 节补齐；地图/下载/报告/RAG/MCP/observation acquisition 的统一安全矩阵仍是后续仓库工作。

### 8.108 2026-08-19 durable query policy authority 与应用装配（开发阶段）

本轮继续完成仓库内闭环：migration 190 增加 purpose、policy version、revocation 三个 `SECURITY DEFINER` 追加函数，gateway 只有 SELECT 和受控 EXECUTE；`PostgresGovernedQueryPolicyAuthority` 在写入后重新校验 sealed record，并在同一 transaction timestamp 中读取 purpose、版本和撤销，执行 latest-version、时态、SPR scope 与 default-deny 判定。`PostgresGovernedQuerySecurityPortResolver` 将该 reader 与既有 immutable `SecurityEventLedger` audit port 组合；应用启动只在安全开关开启且没有显式 resolver 时自动安装，关闭开关的开发兼容模式不受影响。

隔离 PostgreSQL 16 真实开发演练 `1 passed`，覆盖幂等 purpose/policy/revocation、allow→revoke→deny、tenant isolation 和 gateway 禁止表直写，临时容器已清理。migration catalog 为 190 项，最新项 `190_governed_query_policy_authority`，fingerprint 为 `7ddc2ceafd9c94b0c7207907a3eee855cf82de907d959def72e0fc43abb285bc`，两个开发 deployment profile 已同步。联合回归 `113 passed, 1 skipped, 1 warning`；跳过的真实 PostgreSQL 用例已单独运行通过，warning 仍是既有 OpenTelemetry 弃用提示，Ruff、编译和 scoped diff check 通过。

准确边界是：**开发阶段的 governed-query 已具备 durable 策略生命周期、同事务 current read、不可变 outcome audit 和默认启动装配。** 下一步是策略管理 API/CLI、查询结果读取/缓存安全，以及地图、下载、报告、独立 RAG/MCP、observation acquisition 的统一矩阵；本节不依赖客户部署或正式验收。

### 8.109 2026-08-19 governed-query 策略管理 API（开发阶段）

本轮补齐第 8.108 节 durable authority 之上的受认证管理入口，并继续只按仓库开发合同推进：

- 新增 purpose 注册、policy version 发布和 policy revocation 三个 POST 路由，并在前端 API 聚合器完成挂载；
- 只有 `admin`/`platform_operator` 可调用。tenant、`human:<username>` actor、UTC 时间和 sealed fingerprint 均由服务端生成；请求体只接受业务字段，客户端提交 tenant、actor、发布时间、authority port 或 fingerprint 会因 `extra=forbid` 被拒绝；
- 策略请求完整表达 subject type/id、required role、purpose、channel、adapter、resource prefix、effect、priority、有效期和 obligation，随后由既有 builder 封印并交给 `PostgresGovernedQueryPolicyAuthority`，没有增加旁路表写；
- validation、forbidden、immutable conflict、configuration/unavailable 分别映射为 `400/403/409/503`；匿名、无 tenant、错误角色和身份伪造均在 authority 调用前失败；
- 独立路由正负向测试已加入联合回归，当前为 `163 passed, 1 skipped, 1 warning`。新增文件 Ruff、Python 编译和 scoped diff check 通过；warning 仍是既有 OpenTelemetry 弃用提示。无新增 migration，catalog 仍为 190 项。

准确边界是：**开发阶段已经能够通过受认证 API 管理 governed-query 的 purpose、不可变策略版本和追加式撤销，同时保持 tenant/actor/时间/hash 的服务端所有权。** 策略管理核心 API 已闭环，下一仓库优先级是查询结果读取/缓存/地图/下载/报告统一安全矩阵，再扩展独立 RAG、MCP 和 observation acquisition。

### 8.110 2026-08-19 指标/GIS 查询结果下载与 cache-hit 的 SPR 门禁（开发阶段）

本轮把第 8.109 节的策略 current 能力接入指标查询与 GIS 分析的结果消费出口：

- 新增独立 sealed result-access request/decision，绑定 `governed.query.result.access` operation、typed subject、受控 purpose、channel、adapter、run/artifact 资源、消费模式、TTL 和 payload hash；通过适配层复用既有 durable policy authority 的 current 匹配，但返回的 decision 重新绑定原始 result-access request；
- 指标与 GIS result-access 都在 Artifact authority 和 S3 访问前读取 live current，并先写 immutable `admitted`。当前 exact allow 且无 obligation 才继续 Artifact manifest、对象版本、元数据、字节 hash 和签名 URL 校验，成功后写 `outcome`；
- deny、过期、unsupported obligation、跨 tenant reader、reader 故障或 admission audit 故障均零 Artifact/S3 访问。指标 cache-hit Run 与普通成功 Run 使用相同门禁，不能因缓存命中绕过当前 policy；
- 两个 HTTP 请求增加 `purpose_code`，安全开关开启时 resolver 缺失返回 `503`。tenant、actor、reader、decision 和 audit port 保持服务端所有权；审计不保存对象 URI、签名 URL 或凭据；
- 专项 `46 passed`，受影响联合回归 `312 passed, 1 skipped, 1 warning`；Ruff、Python 编译和 scoped diff check 通过。无新增 migration，catalog 仍为 190 项。

准确边界是：**开发阶段的指标/GIS 结果下载，包括 cache-hit 结果，已经具备对象存储访问前的 exact-scope SPR current 和不可变 admission/outcome。** 下一批仍需覆盖地图投影、报告生成和通用 data-product/distribution 下载，再推进独立 RAG、MCP 与 observation acquisition；本节不等于全部结果消费通道或跨存储事务完成。

### 8.111 2026-08-19 地图、DataProduct、分发与报告交付安全矩阵（开发阶段）

本轮完成第 8.110 节明确列出的下一批结果出口，并继续按仓库开发阶段口径推进：

- 新增通用 result-delivery 执行器，在非 Run 出口统一完成 `governed.query.result.access` live current、immutable admission、下游调用和 success/failure outcome；policy deny、reader 故障或 admission audit 故障时下游调用为 0，success outcome 写入失败时不返回已读取结果；
- 已接入 authenticated map publication tile/feature、public DataProduct PostGIS features/STAC/GeoJSON、authenticated distribution ZIP 和 QC report generation。purpose 固定为服务端 `query_result_access`；human/agent subject、role 和 tenant 均由认证上下文或公开 DataProduct gateway 配置生成，不接受客户端安全端口或身份覆盖；
- Martin、PostGIS、Artifact/S3、本地文件和报告生成器均位于 admission 之后。DataProduct file/S3 字节继续按 Artifact size/SHA-256 校验；安全事件不记录 storage URI、文件路径、URL、凭据或业务 payload；
- 强制安全开关开启时 resolver 缺失或异常返回 `503`，未开启时保留开发兼容行为。跨出口与既有相关测试 `80 passed`，扩展联合回归 `439 passed, 3 skipped, 2 warnings`；warning 为既有依赖弃用提示。本轮结果安全矩阵无新增 migration；并行开发后的 catalog 为 192 项，最新项 `192_metric_observation_projection`，fingerprint 为 `8abee0cfc417474b5c538a4a838bfa57e869f7ed2de00766bc6f521dfa8c81d9`。

准确边界是：**当前计划中的普通/缓存查询结果、地图投影、DataProduct/STAC、分发 ZIP 和 QC 报告生成出口已形成统一的开发级 SPR 与审计矩阵。** 不能据此扩展为全部文件接口或所有通道已完成。当前剩余 6 类仓库需求是独立 RAG/MCP/observation acquisition 安全、通用 Proposal/Action runtime、自动语义规划/澄清/跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

### 8.112 2026-08-19 独立 RAG、MCP 与观测采集 external-access 安全（开发阶段）

本轮完成第 8.111 节列出的第一类剩余安全工作，并为非结果型外部访问建立独立合同：

- 新增 `governed.external.access` sealed request/decision 和同步/异步执行器，访问模式限定为 `retrieve/invoke/acquire`。合同绑定 tenant、typed subject、role、purpose、channel、adapter、资源引用和 payload SHA-256，通过既有 durable policy current reader 做 live exact-scope 判定，再重新封印原始 external-access decision；
- `/api/kb/search` 改为显式 immutable document pins 的 governed RAG，检索前准入，检索后保留 document/chunk hash、tenant/owner 和 locator 校验。旧 GraphRAG 公共搜索入口明确 `not_admitted`，不再作为无 pins 的 fallback；
- 本地 MCP registry、远程 MCP Hub 和 stdio bridge 均在工具调用前执行 `invoke` 门禁；远程 Hub 的 tool discovery 也位于 admission 之后。参数只参与请求 hash，不进入安全事件；
- SmartMakani allowlisted layer 下载作为本轮有界 observation acquisition 通道，在 snapshot、分页和恢复读取前执行 `acquire` 门禁。审计只保存逻辑 provider/layer scope，不保存 endpoint、凭据、观测 payload 或文件内容；该结论不扩展为全部 observation Provider；
- deny、reader 故障和 admission audit 故障均零下游；success/failure outcome audit 失败不返回结果。强制安全开关开启时 resolver 缺失继续返回/抛出不可用，未开启且未配置 resolver 时保留开发兼容路径；
- 新增合同及跨通道负向矩阵 `16 passed`，相关联合回归 `322 passed, 1 skipped, 4 warnings`；新增模块、API 与 stdio bridge Ruff、Python 编译和 scoped diff check 通过。无新增 migration，catalog 保持 192，fingerprint 保持 `8abee0cfc417474b5c538a4a838bfa57e869f7ed2de00766bc6f521dfa8c81d9`。

准确边界是：**开发阶段的不可变文档 RAG、本地/远程/stdio MCP invocation 和 SmartMakani 观测采集，已经具备独立 external-access SPR current 与不可变 admission/outcome。** 不能据此宣称全部 legacy RAG、所有观测 Provider、MCP 副作用跨存储事务或 Provider 全局 exactly-once 已完成。当前剩余 5 类仓库需求是通用 Proposal/Action runtime、自动语义规划/澄清/跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

### 8.113 2026-08-19 通用 Proposal/Action runtime 与 L1/L3 切片（开发阶段）

本轮完成第 8.112 节剩余清单中的通用 Proposal/Action runtime 开发切片：

- 新增统一 `ActionTypeDefinition`，精确固定既有 `CapabilitySpec` 版本、fingerprint、输入/输出 Schema、风险、副作用、Policy action、幂等、补偿和 reconciliation；定义可直接投影到既有 `PlatformDefinitionVersion(orchestration_class=action)`，没有并列创建 ActionDefinition/ActionVersion registry；
- 新增 immutable `ProposalArtifact`、`ChangeSet` 和 `ActionResult`。Proposal 只是建议并固定 `execution_authorized=false`；ChangeSet 保存对象 before/after 预期；ActionResult 保存实际变化、Provider receipt、结果 hash 和 `exact/out_of_bounds/not_observed` 比较结果；
- 一次执行继续使用 `PlatformRun`，`ActionOccurrence` 仅提供 Proposal/PlatformRun/可选 AgentRun/ToolCall correlation，不建立第三套 Action 调度状态机；
- ApprovalCase 复合绑定 Proposal、ActionType/Capability、对象版本、PolicyDecision、参数、ChangeSet、幂等键和 channel。未审批 L3、拒绝/过期审批、过期 Policy 和任一 binding 漂移均为 executor 零调用；
- L1 只读/临时派生与 L3 external write 已各有纵向切片。Web/API/MCP/Agent 进入同一 runtime；顺序或并发幂等重试不重复副作用；同 key 内容漂移返回冲突；未知外部结果、receipt/结果合同异常和超出 ChangeSet 的实际变化不得记录成功，进入 reconciliation；
- 内存 ledger 明确仅用于开发合同测试，并保存 canonical PlatformRun/ActionResult；它不是 PostgreSQL durable authority，也不构成跨存储事务或 Provider exactly-once 声明。

专项回归 `18 passed`；与 Platform contracts、Capability registry、PlatformGateway、ApprovalCase authority 和既有专项 compensation Proposal/Approval/Execution authority 联合为 `185 passed, 1 skipped, 1 warning`。跳过项与 warning 均为既有条件/依赖项；Ruff、Python 编译和 scoped diff check 通过。无新增 migration，catalog 仍为 192 项，最新项 `192_metric_observation_projection`，fingerprint 仍为 `8abee0cfc417474b5c538a4a838bfa57e869f7ed2de00766bc6f521dfa8c81d9`。

准确边界是：**开发阶段已具备通用 Proposal/Action 业务合同、复用 PlatformRun 的 L1/L3 执行切片，以及审批漂移、并发幂等和未知结果负向矩阵。** 尚未完成所有 Capability 的 Action 接入、Proposal/ChangeSet/ActionResult 的 PostgreSQL durable API 或跨 Provider 原子执行。当前剩余 4 类仓库需求是自动语义规划/澄清/跨通道融合、复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

### 8.114 2026-08-19 自动语义规划、结构化澄清与证据级融合（开发阶段）

本轮完成第 8.113 节剩余清单中的自动语义编排开发切片：

- 新增统一 `SemanticPlanningRequest`、模型版本绑定、候选 DAG、执行计划、澄清请求/确认和融合结果合同。所有合同均不可变并带 canonical SHA-256，固定 tenant、SubjectContext、purpose、调用面、允许通道、不可变资源 pins 和节点/通道/调用/Token/成本预算；
- proposer 只能返回候选结构，不能获得 executor/tool callback。每个节点必须是现有五通道 typed request，并重新通过 `plan_query_route()`；同时固定 `semantic.query.execute` Capability ID/version/fingerprint、输出 Schema fingerprint 和 evaluator ref。模型绑定缺失/漂移、资源/purpose/能力/evaluator 漂移、循环或未知依赖、无融合规则及预算越界均失败关闭；
- Web/API 合同复用 HTTP API 投影，MCP/Agent 合同复用 Agent/MCP 投影。该能力当前是共享 planner runtime 合同，不是四套状态机，也没有新增 planner HTTP/MCP endpoint；
- 澄清原因和选项结构化，确认必须来自 `human:*` 并精确绑定 request/prior plan/clarification/option。replan 会真实再次调用 proposer，revision 必须加一并 supersede 旧计划；代理确认、缺项、未知选项和旧计划重放均被拒绝；
- 执行层按 DAG 调用现有 governed query executor，重新检查 request、subject、Capability、route admission、节点状态、EvidenceBundle 和 citation。上游证据失败时 dependent node 零调用；融合只保留已验证 claim/evidence，等值陈述可 corroborate，差异陈述显式 conflict，缺失证据进入 clarification，不生成无法追溯的自由文本综合结论；
- prompt injection 和写意图在模型前阻断。模型不可用时仅允许一个显式 typed deterministic seed，经相同准入后执行；`AUTO`/多 seed 不会降级放行。

专项回归 `19 passed`；与 governed query、安全、routes、GIS workflow proposal 和 Capability registry 联合为 `98 passed, 1 warning`。warning 是既有 OpenTelemetry 依赖弃用提示；Ruff 和 Python 编译通过。无新增 migration、Capability 或外部 endpoint。

准确边界是：**开发阶段已具备模型只提候选、确定性能力重新准入的复合语义计划，具备人类绑定的结构化澄清和真实 replan，并能在 claim/citation 粒度融合多通道证据、保留冲突和缺失。** 尚未接入真实模型 Provider，未冻结 MIX-01 至 MIX-04 正式 fixture/质量阈值，也未把 planner 暴露为新的 Web/API/MCP endpoint；这些属于后续集成与评测，不应写成已完成。当前顶层剩余 3 类仓库需求是复杂实体冲突/双时态/既有域迁移、跨存储投影与失败恢复扩展，以及开发级备份/PITR/容量/p95-p99/SLO/国产化组合兼容测试。

### 8.115 2026-08-19 复杂实体冲突与旧域迁移编排（开发阶段）

本轮完成第 8.114 节剩余清单中的复杂实体冲突、双时态与既有域迁移开发切片：

- 新增统一迁移请求、候选、冲突、决议、计划和分阶段执行结果合同。请求固定 tenant、旧域 Resource、来源快照、mapping contract 版本/hash、effective time、预算和候选；候选直接复用现有双时态实体断言、SourceIdentity 绑定和 merge/split/replacement 沿革合同，没有创建第二套 Entity、Link 或时态 authority；
- 仅唯一、满置信度、`INITIAL` 的 authoritative identifier/composite key 候选可自动准入。同一来源多目标、spatial/reviewed/低置信候选、历史 correction/transition、目标状态冲突和所有 lineage 变化均要求 `human:*` 决议，并精确绑定 request、prior plan、conflict、option 和决议时间；
- 重规划不是一次性选项替换：解决来源身份歧义后可在下一 revision 暴露目标状态冲突，再次要求人审；revision 必须连续并 supersede 旧计划。决议缺失、旧计划重放、未知选项或绑定漂移均失败关闭；
- 未决计划不包含 authority write payload，entity assertion、source binding 和 lineage executor 均零调用。同目标同状态的多来源只形成一个实体断言，同时保存所有来源绑定；
- 已决计划分 entity assertions、source bindings、lineage events 三阶段调用现有 authority。阶段失败停止后续写入并返回 `reconciling`；明确 `cross_stage_atomic=false`，重放只依赖既有 authority 幂等，不把该编排描述为跨阶段事务、跨存储原子性或 exactly-once；
- 专项回归 `14 passed`，相关实体 authority/API/重庆 reconciliation 联合回归 `73 passed, 1 skipped`。跳过项是未配置 `DATABASE_URL` 的 PostgreSQL 条件测试；Ruff、格式化和 Python 编译通过。无新增 migration、Capability 或外部 endpoint。

准确边界是：**开发阶段已在现有双时态实体、来源绑定和沿革 authority 之上建立冲突可见、人类决议绑定、多轮 replan、未决零写入和阶段失败 reconciliation 的旧域迁移编排。** 尚未自动生成任意客户 mapping contract，未提供跨阶段原子事务，也未完成大规模迁移性能验证。当前顶层剩余 2 类仓库需求是跨存储投影与失败恢复扩展，以及开发级备份/PITR、容量、p95/p99、SLO 与国产化组合兼容测试。

### 8.116 2026-08-19 跨存储投影 cohort 准入与失败恢复扩展（开发阶段）

本轮完成第 8.115 节剩余清单中的跨存储投影与失败恢复扩展：

- 新增通用 projection cohort 合同，固定 tenant、不可变 source resource version/content hash、唯一目标、Provider mutation budget 和 typed actor；复用既有五类目标的 desired state、observation、checkpoint、repair plan，不新增第二套 projection authority；
- 规划阶段对所有目标执行确定性 assessment。任何 fail-closed 目标、source mismatch 或预算超限都会使 cohort 为 blocked，且不输出可执行 repair payload；ready cohort 才会暴露 plan set，并以 request/plan SHA-256 封存；
- Provider callback 前增加 source snapshot current 与每目标 checkpoint current 的全量 admission。source 漂移、predecessor/version 漂移、已提交证据不一致、reader 异常或类型错误均零 Provider 调用；checkpoint 写入仍只发生在既有 per-target recovery worker 内；
- 复用既有 federated recovery coordinator。unknown outcome 的中间目标会保留已提交前缀、停止后缀并进入 `reconciling`；重复执行只做 current 复核，不重放前缀，也不启动未准入后缀。通用 coordinator 保留多源联邦兼容性，同源约束只属于新 cohort 入口；coordinator 现在也会重新校验 sealed repair plan；
- 合同明确 `cross_target_atomic=false` 和 `checkpoint_write_performed=false`，因此不宣称跨存储事务或 Provider exactly-once。新增专项 `15 passed`；完整跨存储投影/恢复/补偿/五 Provider 套件 `388 passed, 20 skipped, 1 warning`。跳过项是既有 `DATABASE_URL`/可选集成条件测试，warning 为既有 OpenTelemetry 弃用提示；Ruff、编译和 diff check 通过。无新增 migration、Capability 或 endpoint。

准确边界是：**开发阶段显式同源 projection cohort 已具备 all-target current 门禁、未决零写入、unknown 前缀保留、后缀停止和重复恢复不重放的通用合同；既有多源联邦 run 未被强行改写。** 尚未完成跨存储全局原子事务、Provider 全局 exactly-once、客户环境 fault injection 或大规模容量性能验证。当前顶层剩余 1 类仓库需求：开发级备份/PITR、容量、p95/p99、SLO 与国产化组合兼容测试。

### 8.117 2026-08-19 开发可靠性、容量、分位数与组合兼容基线（开发阶段）

本轮完成第 8.116 节最后一类顶层开发需求：

- 新增统一 development reliability baseline，引用并封印 backup、PITR 和 recovery SLI 三类证据 identity，同时固定 profile 与 compose 配置 identity；缺证据、跨 profile/config 漂移或未来时间证据均失败关闭，引用合同不会重新证明原证据未覆盖的结论；
- 延迟观测保存至少 5 个正样本并可重现计算 p50/p95/p99；容量观测固定并发、持续时间、完成/失败数和队列深度并可重现计算吞吐与错误率，零请求不作为有效容量样本；
- 开发 SLO threshold 固定 p95/p99、吞吐和错误率边界，latency/capacity/threshold 必须按唯一 operation 精确配对。阈值比较结果是 `observed_not_approved`，基线始终保持 `rpo_status=not_defined`、`rto_status=not_approved` 和 `promotion_ready=false`；
- 五维兼容矩阵覆盖 CPU、OS、数据库、中间件和模型服务，状态限定为 `passed/failed/untested`，通过行要求证据。测试矩阵显式保留鲲鹏、麒麟、openGauss、TongWeb、Qwen 组合为 `untested`，没有用文档声明替代兼容测试；
- 基线及全部子合同使用 canonical SHA-256，验证器可重新绑定 profile、证据、观测、阈值和矩阵并重建 baseline。专项 `8 passed`，Ruff、格式和 Python 编译通过；既有可靠性回归 `51 passed, 3 xfailed`，另有 1 个历史 recovery SLI fixture 因旧 compose fingerprint 与当前开发 profile 漂移而失败，未改写历史证据。无新增 migration、Capability 或 endpoint。

准确边界是：**开发阶段已形成备份/PITR/recovery evidence reference、p95/p99、容量、阈值判定和国产化候选组合状态的统一可复现基线合同。** 该合同不等于正式 SLO、RPO/RTO、容量认证或国产化认证，测试 fixture 数值也不是实际性能声明。至此，本评估连续追踪的顶层开发需求清单剩余 **0 类**；后续实测数据积累与更多组合矩阵扩展沿用本合同，不构成当前清单中尚未实现的另一项核心能力。

### 8.118 2026-08-19 Proposal/ChangeSet/ActionResult durable artifact authority（开发阶段）

本轮继续推进第 8.113 节保留的 Action runtime 持久化切片：

- 新增 migration `196_action_artifact_authority` 与 PostgreSQL authority，统一持久化 `proposal`、`change_set`、`action_result` 三类 sealed artifact；tenant + kind + SHA-256 是不可变主身份，重复相同内容幂等，identity 内容漂移失败关闭；
- Proposal 的 `execution_authorized` 在数据库约束中固定为 `false`；ChangeSet 与 ActionResult 分别绑定 idempotency/PlatformRun run_id、对应 hash 和完整 JSON 文档，读回后再由 Python Pydantic model 重验；
- RLS + FORCE RLS 固定 tenant 隔离，表无直接写权限，仅允许 `SECURITY DEFINER` record 函数；immutable trigger 拒绝 UPDATE/DELETE。该 authority 只保存工件，不创建 ActionRun 或新调度状态机，运行状态仍由既有 PlatformRun 负责；
- deployment profile catalog 已同步到 `196`，fingerprint 为 `712abbc8fd2e5bbb221166c39e03878e6327d13528d980cd76d4e17eeafc4768`。本地隔离 PostgreSQL 16 专项 `4 passed`，覆盖三类工件、幂等重放、同 scope 内容漂移冲突、RLS、gateway 无表直写和临时库清理；Action runtime 与 migration/profile 联合 `48 passed`，Ruff、格式和编译通过。本轮没有新增 HTTP/MCP endpoint。

准确边界是：**开发阶段 Proposal/ChangeSet/ActionResult 已具备可重放、tenant-bound、append-only 的 PostgreSQL artifact authority。** 这不等于所有 Capability 已接入、不等于跨 Provider exactly-once 或跨存储事务，也不把 artifact persistence 表述为客户环境部署或正式验收。

### 8.119 2026-08-19 受认证语义规划 HTTP 调用面（开发阶段）

本轮继续推进第 8.114 节保留的 planner HTTP 集成项：

- 新增计划创建、结构化澄清/replan、ready plan 执行三个受认证 REST 入口；全部复用现有 `AutomaticSemanticPlanner`、`SemanticPlanExecutor`、Capability/route admission 和 governed-query executor，没有新增第二套 planner、DAG executor 或业务状态机；
- tenant、SubjectContext、角色、API surface、planner binding、proposer、executor 和 repository 均由服务端装配。请求 `extra=forbid`，客户端不能覆盖 tenant/subject/model callback/security reader/executor；匿名、无 tenant、错误角色和伪造字段均在 proposer/executor 前拒绝；
- 创建只接受 deterministic channels、immutable resource content pins 和有上限预算。注入/写意图继续在模型前阻断；默认开发 proposer 未接真实模型，无 seed 明确 `not_admitted`，单个显式 typed seed 才能使用既有 deterministic fallback；plan-only 从不调用 executor；
- server-owned 开发仓库按 tenant + plan SHA-256 保存已封印计划，澄清和执行不接受客户端 plan 文档。跨 tenant 读取为 `404`；执行前重新核对认证 subject、planner binding、Capability/version/fingerprint、输出 Schema、evaluator、purpose、资源 pins 和 route admission，binding drift 或非 ready 状态为 `409` 且 executor 零调用；
- clarification body 只含 requirement/option，`confirmed_by=human:<authenticated username>` 与确认时间由服务端生成并绑定 prior plan。缺项、重复项、未知选项或已有 successor 的旧计划不会触发 replan；successor 与新计划在 repository 同一临界区提交，并发兄弟 revision 不会同时成为 current。错误稳定映射为 `400/404/409/503` 且不泄露 Provider/端口异常正文；
- 专项 `19 passed`，planner runtime、governed query/routes/policy、Capability registry 联合回归 `89 passed, 1 warning`；新增文件 Ruff、格式化、Python 编译和 `git diff --check` 通过。无新增 migration/Capability，catalog 仍为 `196`，fingerprint 仍为 `712abbc8fd2e5bbb221166c39e03878e6327d13528d980cd76d4e17eeafc4768`。

准确边界是：**开发阶段 semantic plan、human clarification/replan 和 evidence fusion 已形成受认证、tenant-bound、服务端 resolver 装配的 HTTP 生命周期。** 真实模型 Provider、MCP planner endpoint 和 durable plan repository 仍是后续开发增强；当前内存 repository 只用于开发进程，不应被描述为持久化权威。原顶层开发需求清单仍为剩余 **0 类**，本节不重新制造新的顶层缺口。

## 9. 建议的采购与决策口径

建议把范围拆为三类：

1. 通用产品基础：接入、Catalog、Ontology、受控查询、GIS、知识库、证据、基础 Policy/HITL；
2. 可选增强：统一 Agentic 路由、通用 Action、双时态业务适配与规模化、图谱/向量规模化、更多 GIS 模板；
3. 业务实施与外部依赖：具体业务数据、规则、知识语料、案例、部署组合、性能和运维。

合同不应写“全部支持”或只写一个完成百分比。每项使用“通过、有条件通过、不通过、待客户提供证据”，并绑定输入数据、版本、环境、用例、预期结果、日志、运行产物和签署人。

最终建议是：保留材料的本体治理、确定性 GIS、Proposal 和分层思想；删除“OAG 替代 RAG”“不可导出”“网格码统一身份”“URI 自动跨库 JOIN”“固定 300ms”“旁路安全校验”等绝对化表述；以 GIS Data Agent 现有能力为基础，先做可信、受控、可审计的样区闭环，再重点建设自动语义计划与融合、Action、安全、双时态业务适配与规模化，以及跨存储一致性。
