# GIS Data Agent — Roadmap

**Last updated**: 2026-07-18 &nbsp;|&nbsp; **Current release line**: v25.21-twm-demo &nbsp;|&nbsp; **Package metadata**: v23.0.0（待对齐） &nbsp;|&nbsp; **Next platform gate**: NDP-0 Product Charter + Governance/Contract Freeze -> Baseline CI 绿色 -> Agentic Governance Runtime first slice -> Trusted Data Product first slice -> MMFE/Data for AI -> GWM Kernel & Dual-Engine validation &nbsp;|&nbsp; **Executable ADK dependency**: 2.3.0（旧文档 1.27.x 待清理）

> 参照标杆：SeerAI Geodesic、OpenClaw、Frontier、CoWork、**DeerFlow v2.0（ByteDance 通用 Agent Harness）**、**SIGMOD 2026 Data Agent Levels（L0-L5 自主性分级）**、**AgentArts（华为云企业级智能体平台）**、**Datus.ai（上下文工程 + 反馈飞轮）**、**Hermes Agent（通用 Agent Runtime）**、**Atlan / Alation / Ataccama（Agentic Governance + Active Metadata）**、**DataWorks / Dataphin（数据开发治理一体化 + Agent）**、**袋鼠云（多模态数据中台）**
>
> 核心战略：建设优先面向**自然资源与城市场景**、同时支持空间与非空间多类型数据的 **Geospatial-Native & Agentic-Native Data Platform（地理空间原生、智能体原生的新一代数据平台）**。即使不部署 GWM，平台也必须凭借严格的数据治理、MMFE 语义融合、可信数据产品和 Human/Agent/AI 一致消费而独立成立。
>
> 特有内核：**Geospatial World Model（GWM）是 GIS Data Agent 的特有空间世界认知内核和核心差异化能力，而不是基础数据治理成立的前提。**带有 GWM 的 GIS Data Agent 由 LLM 与 GWM 双引擎共同支撑：LLM 负责语义、知识、意图、解释与治理编排，GWM 负责多尺度空间世界状态、地理过程、行动条件推演、不确定性和证据边界；二者共同把治理后的数据产品转化为可理解、可推演、可规划、可审计的空间智能。
>
> 创新命题：目标形成一个具有世界级原创性的 `LLM + GWM + Agentic Data Platform` 产品范式。该命题必须通过先行技术检索、可重复 benchmark，以及 LLM-only、GWM-only、规则/传统基线与 LLM+GWM 的同题消融验证，不以内部命名或功能数量直接宣称“全球首创”。
>
> **等级口径**：v25.0 的 **L4 — Agentic Governance** 仅保留为领域治理路线标签，不再作为当前整个 Agent Runtime 已达到 L4 的结论。统一 Runner、真实质量回跳、checkpoint/resume、跨入口策略一致性、租户隔离和认知失败基准通过前，整体自主等级保持“待基准评定”。

---

## Strategic Program — Next-Generation Data Platform（产品章程与主路线，2026-07-18）

### 产品本体：无 GWM 也成立，有 GWM 形成独特跃迁

GIS Data Agent 必须同时满足两个独立验收层级：

| 产品层级 | 成立条件 | 不能依赖 |
|---|---|---|
| **Core Data Platform** | 完成地理空间原生、智能体原生的数据治理、数据工程、MMFE 语义融合、数据产品化，以及人/Agent/AI 一致消费 | 不依赖 GWM、TWM、UWM、DRL 或真实 Action-Outcome 数据才能完成标准、模型、质量、安全、汇聚、开发和发布 |
| **GWM-Enhanced GIS Data Agent** | 在同一治理数据产品上增加共享 GWM Kernel、TWM/UWM 领域实例、LLM+GWM 协同推理、状态推演、规划和证据审计 | 不得把 simulator 输出冒充 observed outcome，不得让 GWM 绕过数据权限、质量门禁和发布权威 |

> **基础平台的价值主张**：以 Agentic-native 的方式生产可信、版本化、可消费的数据成果。**GWM 增强产品的价值主张**：在此基础上，让 LLM 不只“读懂数据”，还能够与 GWM 一起理解空间世界状态、推演受约束的未来并形成证据有界的决策支持。

统一数据产品的消费模型：

```text
Geo / non-Geo Sources
          |
          v
Agentic Governance + Data Engineering + MMFE
          |
          v
Canonical DataProductVersion
data + semantics + spatial/temporal context + quality + security
     + lineage + policy + evidence + version + owner + SLA
          |
          +----------------------+----------------------+----------------------+
          |                      |                      |                      |
          v                      v                      v                      v
 HumanViewProjection    AgentContextProjection  AIDatasetProjection  GWMObservationProjection
 map/table/report/API   resource/tool/schema     train/eval/infer      state/action/evidence input
          |                      |                      |                      |
          +----------------------+----------------------+----------+-----------+
                                                                  |
                                      feedback + trace + error + DataDemand
                                      + optional Action/Outcome evidence
                                                                  |
                                                         next product version
```

平台必须完成四个主闭环；第五个 GWM 闭环是特有增强而非基础平台前置条件：

1. **AI for Data**：治理事件 -> Agent 发现/理解 -> 标准/策略约束 -> 工具执行 -> 独立评价 -> HITL/自动门禁 -> ChangeSet -> 新版本。
2. **Data for Human/Agent**：可信数据产品 -> 人直接使用或委托 Agent 使用 -> 查询/分析/反馈 -> 改进语义、视图、质量规则和产品契约。
3. **Data for AI**：DataProductVersion -> DatasetVersion -> 训练/评测/推理 -> ModelVersion -> 误差/漂移/DataDemand -> 下一数据产品版本。
4. **MMFE 语义学习闭环**：融合候选 -> 置信度/冲突 -> 人工纠正和下游任务效果 -> 改进标准、模型、领域语义包和融合策略。
5. **GWM 空间世界闭环（增强）**：GWMObservationProjection -> State/Transition -> TWM/UWM 推演/规划 -> 证据边界 -> 新观测/误差/可选 Action-Outcome -> 校准 GWM 与数据产品。

### 严格的数据治理定义

数据治理不等于功能清单。平台统一采用：

```text
Data Governance = Governance Domain × Data Lifecycle Stage × Control Contract
```

| 维度 | 必须覆盖的内容 |
|---|---|
| **Governance Domain** | 数据标准、数据模型、元数据/目录、主数据/参考数据、语义/本体、数据质量、数据安全/隐私/分类分级、血缘/影响、生命周期/版本、数据资产/产品、合规/审计、使用反馈/价值 |
| **Data Lifecycle Stage** | 发现登记 -> 采集汇聚 -> Profiling -> 标准映射/建模 -> 语义融合 -> 清洗转换/开发 -> 质量安全验证 -> 审批发布 -> 产品/服务 -> 使用监控 -> 变更归档/销毁 |
| **Control Contract** | Governed Object、Authority、Owner/Steward、Trigger、Agent Action、Capability/Tool、Policy、Evaluator、HITL、ChangeSet、Version、Evidence、KPI |

每一个治理过程必须可回答：治理什么对象、依据哪个权威版本、谁负责、谁可以做什么、Agent 调用什么工具、由谁验证、何时需要审批、产生什么版本、保留什么证据、用什么 KPI 判断改进。无法回答者不得称为生产级 Agentic Governance。

Agentic-native 的最低执行纪律：

```text
GovernanceEvent
 -> typed GovernanceTask / TaskGraph
 -> standard/model/policy-aware planning
 -> deterministic and AI-assisted capabilities
 -> independent evaluator
 -> policy-based auto gate or HITL
 -> auditable ChangeSet
 -> versioned DataProduct publication
 -> feedback and governance memory
```

LLM 可以理解、规划、解释和生成候选；标准、模型、权限、质量门禁和发布权威必须由版本化 Authority、Policy、Evaluator 与审批流程控制。

### 数据范围：Spatial-native，不是 Spatial-only

| 数据家族 | 首要类型 |
|---|---|
| **地理空间数据** | 矢量/PostGIS、栅格/COG、遥感影像、点云/LiDAR、3D/BIM/CityGML、CAD/测绘成果、路网/空间网络、轨迹/时空事件、时空立方体、传感器/实时流、WMS/WFS/STAC/OGC API |
| **非地理空间数据** | 关系表/业务库、指标/统计/时间序列、文档/PDF/Office/法规标准、图片/音频/视频、日志/消息/事件、API/SaaS 对象、图/RDF、模型特征/标签/轨迹/评测集 |

非空间数据可以独立治理，也可以绑定到空间对象、时间窗口、业务对象和证据链；不得为了“GIS 化”强行生成虚假 geometry。

### MMFE：数据产品生产主线中的多模态智能语义融合引擎

MMFE 不是旁路工具、普通格式转换器或只为 TWM 准备输入的前处理。它消费标准、数据模型、领域语义包、质量和安全策略，执行现有五阶段生命周期：

```text
Profiling -> Assessment -> Alignment -> Execution -> Validation
```

并将空间与非空间多模态数据加工为版本化 `SemanticFusionProductVersion`：

```text
canonical objects + role/field/value bindings
+ entity resolution + spatial/temporal alignment + semantic relations
+ derived features + conflicts/resolutions + unresolved ambiguities
+ confidence + quality/security sidecar + provenance + applicable authorities
```

MMFE 必须同时完成 Schema、对象、空间、时间、特征和证据六类融合。执行策略采用“确定性优先、AI 处理歧义、人工控制高风险”：规则/标准精确匹配 -> embedding/retrieval 候选 -> 空间/统计证据评分 -> LLM/VLM 歧义裁决 -> HITL；支持 content hash、增量融合、缓存、分区/流式执行和不必要时的语义视图/联邦引用，避免无意义物理合并。

MMFE 的产品门不能只看流程通过，至少评测字段映射 P/R、实体解析、空间/时间对齐、冲突识别、置信度校准、人工修正率、吞吐/成本，以及对下游质量、查询和 AI/GWM 任务的增益。

### 平台核心、GeoCore、领域包与 GWM 的边界

不建设一个无边界巨型本体，也不让 GWM 侵入基础治理依赖：

```text
PlatformCore
├── governance / engineering / fusion / product / consumption contracts
├── non-spatial and generic multimodal data support
└── GeoCore
    ├── spatial identity / geometry / CRS / scale / spatial-temporal relations
    ├── NaturalResourceDomainPack
    └── UrbanDomainPack

GWM Kernel（特有、可插拔）
├── versioned geospatial state graph
├── canonical action / transition / uncertainty / evidence claim ledger
├── TWM Adapter -> Territory World Model
└── UWM Adapter -> Urban World Model
```

`PlatformCore` 保证无 GWM 的 Data Platform 独立成立；`GeoCore` 让空间成为一等公民；Domain Pack 保留行业标准、对象、规则、指标和生命周期；GWM Kernel 消费治理后投影并提供空间世界认知，不成为数据标准、质量、安全、MMFE 和数据产品发布的强依赖。

### 四个契约族

| 契约族 | 代表契约 | 平台职责 | 当前缺口 |
|---|---|---|---|
| **Governance Authority Contracts** | `StandardVersion`、`DataModelVersion`、`SemanticPackVersion`、`PolicyVersion`、`QualityRuleVersion`、`SecurityPolicyVersion` | 定义权威语义、规则、责任、适用范围和版本 | 现有 Standards/Policy/语义能力尚未统一成 Authority Resolver |
| **Data Production & Fusion Contracts** | `DataAssetVersion`、`PipelineRun`、`SemanticFusionProductVersion`、`QualityAssessment`、`LineageEvent`、`DataIssue`、`GovernanceTask`、`ChangeSet` | 承载汇聚、开发、治理、MMFE、评价、修复和可回放生产过程 | 生命周期对象分散，Agent 过程尚未以同一治理状态机闭环 |
| **Data Product & Consumption Contracts** | `DataProductVersion`、`HumanViewProjection`、`AgentContextProjection`、`AIDatasetProjection`、`DatasetVersion` | 将同一权威成果安全、一致地交给人、Agent 与各类 AI 使用 | 缺平台级聚合根、投影一致性、订阅/消费审计和 SLA 门禁 |
| **AI/GWM Feedback Contracts** | `ModelVersion`、`DataDemand`；GeoCore/GWM 扩展 `SpatialObject`、`StateSnapshot`、`CanonicalAction`、`CanonicalTransition`、`ActionEvent`、`OutcomeObservation`、`EvidenceClaimLedger` | 管理 AI 谱系、误差反馈及 GWM 状态/转移/证据；不把 GWM 特有对象强加给所有数据产品 | GWM 共享 Kernel 尚未抽取；真实 Action-Outcome 不足只限制强因果/决策 claim，不阻塞基础平台 |

所有新表、API、Agent、工具和前端视图必须映射到契约族或明确的支持对象。若无法说明权威来源、Owner、生命周期阶段、Agent/人工权限、Evaluator、输出版本、消费者和业务 KPI，不进入主路线。

### LLM + GWM 双智能引擎

| 引擎 | 主要职责 | 不得承担 |
|---|---|---|
| **LLM / Cognitive Runtime** | 自然语言与多模态意图理解、标准/模型/规则检索、治理任务分解、工具编排、解释、知识与 Agent 协作 | 不作为数据权威、权限引擎、质量真值或不可审计的生产控制器 |
| **GWM Runtime Kernel** | 多尺度地理状态图、空间关系和作用场、状态转移来源、情景/行动条件推演、不确定性、证据/claim 边界、TWM/UWM 适配 | 不替代基础治理、MMFE、数据产品权威，也不在弱证据下输出真实政策效果 |
| **双引擎协同** | LLM 将问题转为受标准/策略约束的世界状态查询与方案；GWM 返回证据有界的状态、未来、风险与不可判断项；LLM 形成可追溯解释和 DataDemand | 不允许 LLM 用语言补齐 GWM 缺失证据，也不允许 GWM 结果绕过 Policy/HITL 写回权威数据 |

双引擎创新必须做四路同题比较：传统/规则基线、LLM-only、GWM-only、LLM+GWM。至少分别评估治理正确性、空间状态/转移质量、规划约束违规、证据引用、拒答/降级正确率、人工修正、成本和时延；只有组合在关键任务上产生稳定增益，才能支持产品原创性主张。

### 当前基线判断

| 验收维度 | 当前状态 | 结论 |
|---|---|---|
| 严格数据治理 | Standards Platform、数据模型派生、质检、安全、目录、血缘、反馈等能力丰富 | **领域能力较强，尚未形成 Governance Domain × Lifecycle × Control Contract 的统一过程模型** |
| 数据汇聚/开发/服务 | PostGIS、ArcPy、连接器、工作流、分布式任务、地图/API/导出能力已存在 | **技术面较宽，尚未围绕 DataProductVersion 收束** |
| 空间与非空间多类型数据 | 空间数据能力强，表格/文档/图像/流等局部具备 | **Spatial-native 基础强，统一多类型数据生命周期和安全/质量契约不足** |
| MMFE | 已有五阶段流水线、时空对齐、语义增强、冲突消解和 TWM/UWM 消费经验 | **重要基础；融合效果 benchmark、非空间扩展、增量产品化和 Authority 绑定仍不足** |
| Agentic-native 治理 | 多 Agent、Workflow、Policy/标准、工具和 HITL/反馈 first slice 已存在 | **组件具备，治理状态机、独立评价和跨入口 Runtime 未统一** |
| 人直接消费 | 地图、表格、目录、标准、治理、报告和决策工作台已存在 | **已具备，待按数据产品收束** |
| 人通过 Agent 消费 | Chat、CLI/TUI、MCP、A2A、NL2SQL 和专业工具已存在 | **入口具备，跨入口 Runtime/权限未统一** |
| AI 消费 | eval set、状态快照、trajectory、replay、holdout 和模型实验存在 | **局部具备，缺 DatasetVersion/ModelVersion 平台** |
| 统一 Data Product | 只有 data asset、标准市场和局部 UWM 产品 | **未完成** |
| GWM/TWM/UWM | TWM/UWM 领域实现与局部 geospatial kernel/DAM-GK 证据丰富 | **GWM 范式和领域实例存在；平台级共享 `data_agent/geospatial_world_model/` Runtime Kernel 尚未抽取** |
| LLM + GWM | LLM Agent 与 TWM/UWM 能力同时存在 | **尚无统一双引擎协议和四路消融证据** |
| 真实 Action-Outcome | UWM/TWM 能表达行动和模拟结果，且保留 claim boundary | **不足；限制真实行动效果与决策优势 claim，但不阻塞 Data Platform、状态模型和条件模拟** |
| Cognitive Runtime | 正式设计已冻结 | **尚未实施；是 Agentic Governance 控制面的关键依赖** |

因此当前项目已具备下一代平台和 GWM 创新产品的强技术基础，但尚未完成统一治理过程、可信数据产品、MMFE 产品化、共享 GWM Kernel 或 LLM+GWM 双引擎验证，不得以局部模块替代整体完成声明。

### 交付路线与退出门

| 顺序 | 阶段 | 状态 | 核心交付 | 强制退出门 |
|---:|---|---|---|---|
| 0 | **NDP-0 Product Charter, Governance Taxonomy & Contract Freeze** | **当前优先** | 冻结“无 GWM 也成立、有 GWM 高差异化”的产品章程；治理三维模型、数据类型矩阵、PlatformCore/GeoCore/Domain Pack/GWM 边界、四契约族、Authority/ID/版本策略；盘点现有表/API/schema | 核心资产完成“保留/适配/合并/搁置”映射；每个治理域和生命周期阶段有 Owner/Authority/Action/Evaluator/Version；双试点同时定义 Core Platform 与 GWM-enhanced 验收 |
| 1 | **NDP-1 Agentic Governance Runtime & Trusted Data Product** | 规划中 | 先按既定计划完成 RuntimeIdentity/RunnerFactory/RunWorkspace/策略一致性 first slice；落地治理事件/任务/ChangeSet/评价/审批状态机；串联标准、模型、元数据、质量、安全、血缘、生命周期和 DataProductVersion | 不调用 GWM 也能完成一次“发现/汇聚 -> 治理 -> 评价 -> 审批 -> 发布 -> Human/Agent/AI 消费”闭环；语义、ACL、质量、证据和 hash 在投影间一致；越权、质量不达标和无审批变更无法发布 |
| 2 | **NDP-2 MMFE Semantic Fusion & Data for AI Factory** | 规划中 | 将 MMFE 前移为主线：空间/非空间多模态 semantic fusion、SemanticFusionProductVersion、增量/缓存/流式执行、融合 benchmark；DatasetVersion、EvaluationSet、ModelVersion、DataDemand 和 AI/GWM 投影 | 至少一个跨空间/非空间多类型产品通过融合效果、人工修正、吞吐/成本和下游增益门；`DataProductVersion -> DatasetVersion -> ModelVersion` 可重放；质量/权限不合格数据不能进入 AI/GWM |
| 3 | **NDP-3 GWM Kernel & LLM+GWM Dual-Engine Intelligence** | 规划中；特有增强 | 抽取共享 GWM Runtime Kernel：状态图、CanonicalAction/Transition、uncertainty、EvidenceClaimLedger、TWM/UWM adapters；定义 LLM↔GWM 双引擎协议、DataDemand 和地图审计；保留领域 simulator/planner | Core Platform 在关闭 GWM 时继续通过全部基础验收；同一产品版本可进入 TWM/UWM adapter；transition origin/claim 自动推导；传统、LLM-only、GWM-only、LLM+GWM 四路同题评测证明组合增益，否则不得升级原创性主张 |
| 4 | **NDP-4 Operational Learning, Federation & Ecosystem** | 条件规划 | Prospective Action/Outcome capture、Operational Object/Action、审批/补偿/回滚、observed/proxy/synthetic 分级；湖仓/联邦、STAC/OGC API/MCP/A2A、跨组织数据空间、隐私计算、SDK 和规模运维 | 无真实数据时保持 state dynamics/conditional simulation claim；有真实或准真实证据后再升级局部行动效果；跨组织权限、来源、版本、退出和审计通过联合演练；无第二权威写源 |

实施顺序约束：NDP-0 完成后，第一份代码实施计划仍只覆盖 **Agentic Governance/Cognitive Runtime Kernel first slice**；Data Product first slice、MMFE 产品化和 GWM Kernel 抽取不得混成一次大改。`Runtime` 一词必须带限定：Cognitive Runtime 控制 Agent 行为，Data Platform Runtime 控制治理/生产过程，GWM Runtime 控制空间世界状态/转移/证据；三者共享身份、权限、版本和审计，但职责不同。

### 双试点

| 试点 | Core Platform（不依赖 GWM） | MMFE / Data for AI | GWM 增强 | 独立退出门 |
|---|---|---|---|---|
| 自然资源：地类图斑/规划管控治理产品 | 多源汇交、标准/模型映射、质量安全、血缘版本、地图/表格/API、Agent 治理与成果发布 | 图斑/项目/规则/遥感/文档语义融合；输出 Human/Agent/AI/GWM 投影 | TWM 消费治理状态，提供地类状态预测、规则约束、条件情景、风险和证据审计 | 关闭 TWM 后数据产品全链路仍通过；启用后在同题 benchmark 上相对规则与 LLM-only 有可重复增益 |
| 城市：设施供给与宜居性状态产品 | 设施/人口/道路/环境数据汇聚治理、质量安全、地图/报告/API、Agent 查询与数据产品发布 | 建筑/路网/POI/人口/环境/文本多模态对齐；输出 DatasetVersion 与城市观测投影 | UWM 消费城市状态图，提供热/污染/服务/公平状态、空间外溢和证据有界规划 | 关闭 UWM 后仍是可交付城市数据平台产品；启用后完成 LLM-only/GWM-only/组合消融和 claim boundary 验证 |

### 架构决策与非目标

1. **一份权威产品，多种可重建投影**：Human/Agent/AI 视图不得各自维护语义、权限或版本真值。
2. **GWM 特有但可插拔**：它是 GIS Data Agent 的核心差异化内核和重点产品能力，但 Core Data Platform 不得以 GWM 可用性作为标准、模型、质量、安全、MMFE、发布和消费的运行前提。
3. **LLM + GWM，不是 LLM 或 GWM 单引擎垄断**：LLM 负责语义/编排，GWM 负责空间世界状态/转移/证据，Policy/Evaluator/HITL 保持生产控制权。
4. **MMFE 是主线能力**：多模态语义融合在 NDP-2 完成产品化，不推迟到生态阶段，也不只服务 TWM/UWM。
5. **PostgreSQL/PostGIS 与 Standards Platform 保持权威边界**：搜索、向量、图、RDF、STAC 和缓存均为投影或交换接口。
6. **生产探索分离**：探索任务可采用 Agentic Mode；生产任务必须固化为版本化 Workflow、Policy、Capability 和 Evaluator。
7. **模块化单体优先**：没有独立扩缩容、故障隔离和团队边界证据前，不按名词拆微服务；GWM Kernel 首期以 contracts/ledger/adapters 抽取，不重写 TWM/UWM。
8. **空间原生而非空间排他**：空间语义是一等公民，同时完整治理非空间数据；不为非空间事实强造 geometry。
9. **不把 synthetic 当 observed**：仿真和 replay 可用于工程验证与候选评测，但不能替代真实 Action-Outcome 证据；缺真实数据限制 claim，不阻塞基础平台和条件模拟。
10. **不建设无边界泛化平台**：优先服务自然资源和城市场景，不与通用湖仓、BI、GIS 编辑器或通用 Agent Harness 正面复制。
11. **不继续以新增 Tab 代表产品进度**：前端逐步收敛为 Data Workspace、Data Product Studio、Operations & Decision Center，以及证据有界的 GWM World/Scenario Workspace。

---

## Strategic Program — GIS Data Agent Cognitive Runtime（设计已冻结，实施暂缓，2026-07-15）

> **目标**：为 GIS Data Agent 建设一个模型无关、证据驱动、数据标准感知、Capability 驱动的“智能体大脑”。该大脑以强类型工作状态和确定性策略控制知识检索、规划、专业工具执行、独立评价、HITL、记忆和受控自我进化；LLM 是可替换的推理提供者，不是运行控制本身。
>
> **当前决策**：本轮只完成正式设计和 roadmap 刷新，不对现有应用代码进行大规模改造。必须等 UWM 城市适宜性需求开发与 ArcPy MCP 集成稳定完成并合并、基线测试恢复稳定后，才创建独立 worktree 和第一份 Runtime Kernel 实施计划。

正式设计与证据：

- [Cognitive Runtime 正式设计 Markdown](designs/gis_data_agent_cognitive_runtime_2026-07-15/GIS_Data_Agent_Cognitive_Runtime_详细设计说明书.md)
- [Cognitive Runtime 正式设计 Word](designs/gis_data_agent_cognitive_runtime_2026-07-15/GIS_Data_Agent_Cognitive_Runtime_详细设计说明书.docx)
- [用户确认的总体架构规格](superpowers/specs/2026-07-15-gis-data-agent-cognitive-runtime-design.md)
- [当前实现审计](designs/gis_data_agent_cognitive_runtime_2026-07-15/design-doc-audit.md)
- [证据包](designs/gis_data_agent_cognitive_runtime_2026-07-15/evidence-pack.md) / [追踪矩阵](designs/gis_data_agent_cognitive_runtime_2026-07-15/traceability-matrix.md) / [可编辑架构图](designs/gis_data_agent_cognitive_runtime_2026-07-15/diagrams/README.md)
- [重型本体生产架构分析与技术选型](reports/gis-data-agent-heavy-ontology-production-architecture-2026-07-15.md)
- [GIS Data Agent 与 DeerFlow 客观对比分析](reports/gis-data-agent-vs-deerflow-objective-comparison-2026-07-15.md)

### DeerFlow 对比结论与执行决策（2026-07-15）

> 对比采用两个独立目标函数，禁止用一个混合总分掩盖产品定位差异：DeerFlow 是成熟的通用 Super Agent Harness；GIS Data Agent 是领域能力深但运行时尚未统一收束的专业 GIS 平台。

| 评估视角 | DeerFlow | GIS Data Agent | Roadmap 含义 |
|---|---:|---:|---|
| 通用 Agent Harness | 9.1 / 10 | 5.5 / 10 | 优先补 Runtime Kernel、Sandbox、Run/Event/Checkpoint 和跨入口一致性 |
| GIS 业务交付 | 3.5 / 10 | 8.7 / 10 | 保留 Standards、PostGIS、ArcPy、NL2GeoSQL、DRL、TWM/UWM 和专业地图，不做通用化重写 |
| 当前工程可信度 | 9.2 / 10 | 5.2 / 10 | 新增功能不得越过绿色基线、契约测试和真实发布 gate |
| 目标架构严谨性 | 7.8 / 10 | 9.0 / 10 | Cognitive Runtime 继续作为目标架构，但设计项不得记为已交付能力 |

评分是代码/测试/仓库证据支持的诊断性序数值，不是统计显著性结果。当前没有同模型、同硬件、同任务集的端到端对照实验。

当前可重复基线：

- 本地工作区位于 `feat/v12-extensible-platform@1421e00`，相对已配置同名远端领先 102 commits；评估时有 38 个已修改和 131 个未跟踪条目，不能作为发布快照。
- 抽取的 360 个核心后端测试中 357 通过、3 个失败；失败归并为 2 个根因：CostGuard 配置优先级漂移、API route 数量契约漂移。
- `npm run build` 通过；主 JS 约 4.36 MB、gzip 后约 1.28 MB，需代码分割；前端尚无独立 unit/lint/typecheck script。
- task decomposition 路径导入不存在的 `data_agent.pipeline_runner.run_pipeline`，已直接复现 `ImportError`。
- GitHub `CI` workflow 最近 100 条历史记录均为 failure；当前功能分支可见的最近 20 条 staging workflow 记录均为 failure。该历史信号不代替目标 commit 的 CI，但证明现阶段没有可信绿色发布基线。
- README 声明 MIT，但仓库未发现 `LICENSE`，GitHub API 未识别许可证。

执行决策：

1. **不迁移成 DeerFlow，不全面切换 LangGraph**：Google ADK 是否替换只能由同任务 benchmark 和明确的框架阻塞证据决定。
2. **不继续横向扩张通用 Agent 功能**：先完成 Phase 0 和 Runtime Truthfulness P0。
3. **吸收 DeerFlow 工程机制**：统一 Harness/App 边界、RunnerFactory、Run/Thread/Event/Artifact、Sub-Agent budgets、provider Sandbox、request-scoped secrets、read-before-write、contract replay、blocking-IO 和真实 smoke/rollback。
4. **保留 GIS 执行面**：现有领域模块作为 Capability 后端接入统一 Runtime，不复制、不降级、不暴露给一个巨型 FrontDoor Agent。
5. **自我进化保持 review-only**：CI、评测、隔离、版本和 rollback gate 完成前不得扩大自动 promotion。

Runtime Kernel 实施计划的新增进入门：

- 目标基线 commit 的后端、前端和契约 CI 全绿；
- 版本、ADK、API route、schema、migration 和 License 口径一致；
- UWM/ArcPy 并行改动已合并或从 Runtime worktree 隔离；
- 至少 50 个正向、负向、缺数据、越权和工具故障 GIS 任务冻结；
- 双用户/双租户的工具、文件、KB、memory 和 cache 隔离测试通过；
- Docker health/smoke 与 rollback rehearsal 执行真实命令，不再只输出说明文本。

### 总体交付顺序与状态

| 顺序 | 子项目 | 状态 | 核心范围 | 启动条件 | 退出门 |
|---:|---|---|---|---|---|
| 0 | **Baseline & Contract Freeze** | 文档完成；工程基线待建立 | 50-100 个真实/脱敏治理任务；正向、负向、缺数据、越权和工具故障集；冻结 prompt/model/tool/standard 版本；不可变安全集 | UWM 与 ArcPy MCP 并行工作稳定合并 | 能分别识别检索、理解、规划、工具、产物和结果错误；形成当前成功率、人工修正、成本与延迟基线 |
| 1 | **Runtime Kernel** | 规划中；暂缓实施 | `RuntimeIdentity`、mandatory `RunnerFactory`、`RunWorkspace`、事件流、Attention Router v1、`TaskFrame`、`TaskGraph`、`QualityVerdict`、checkpoint/resume、真实质量回跳 | Phase 0 基线完成；独立 worktree；只为本子项目创建实施计划 | 所有入口执行同一 RuntimePolicy；revise/replan 真实重跑；可恢复 checkpoint；跨租户上下文、记忆和工具泄露为零 |
| 2 | **Standards Knowledge Brain** | 规划中；依赖 Runtime Kernel | `StandardKnowledgePack`、Domain/Operational Ontology Authority Store/Compiler/Package/Resolver、Object/Property/Link/Action/Function/Interface contracts、动态安全语义、`EvidenceBundle`、Hybrid Retrieval | Runtime Kernel 身份、Workspace、Policy 和隔离契约验收通过 | 本体包/版本/投影一致性 100%；Object/Action schema 可验证；未授权对象/属性/关系/Action 返回为 0；正确标准/条款召回和引用指标达标 |
| 3 | **Governance Pilot** | 规划中；依赖知识大脑 | ActionType↔Capability↔Tool/Evaluator 绑定、窄工具 Specialist、typed Python/TypeScript/REST/MCP/A2A contracts、ChangeSet/ActionResult、治理对象行动闭环、lineage、HITL、写回/回滚 | Runtime、Evidence、Domain/Operational Ontology 契约稳定；确定首个真实或脱敏治理数据集 | 至少一个治理场景通过对象发现、Action 规划、动态授权、审批、执行、评价、版本化写回和回滚；所有实际变更均能与 ChangeSet 对账 |
| 4 | **Memory and Experience** | 规划中；依赖稳定运行事件 | Memory Write Gate、episodic/procedural memory、经验检索评测、压缩、保留、纠错和删除 | 治理试点产生稳定的 run event、evaluator verdict 和人工反馈 | 经验命中能够可测地改进计划；错误经验可撤回；过期、越权和跨租户记忆不可见 |
| 5 | **Controlled Evolution** | 规划中；保持 review-only | `EvolutionEvent`、Candidate Registry、failure attribution、regression/replay/holdout、shadow、canary、Evolution Governor、promotion/rollback | 前四个子项目的 trace、评测、版本和回滚语义稳定 | 候选可自动生成和离线验证；安全/权限回归为零；先演练 rollback；仅 L0-L2 低风险对象允许受控自动晋级 |

### 实施纪律

1. **模块化单体优先**：第一阶段继续使用 PostgreSQL、pgvector、现有任务队列、对象存储和 OTel；本体以 PostgreSQL 权威写模型和不可变 JSON Package 起步。Stage 2 再增加 SKOS/SHACL/RDF 构建验证，只有容量、SLO 或互操作基准证明必要时，Stage 3 才引入 Fuseki/TDB2、OpenSearch、专用向量库或属性图读投影。
2. **顺序子项目**：不得把五个子项目合并为一次大改；每个子项目必须独立产生可部署、可测试价值，并通过退出门后再启动下一项。
3. **第一份实施计划只覆盖 Runtime Kernel**：不得提前把 Standards Knowledge Brain、Memory 或 Controlled Evolution 混入同一代码改造。
4. **现有领域能力不重写**：GIS、PostGIS、ArcPy、Standards、NL2SQL、TWM、DRL 和报表能力作为 Execution Plane 接入统一 Runtime，不复制新的平行“大脑”。
5. **RAG 不是控制器**：RAG 只承担证据获取；标准原文、结构化定义、可执行规则和实时工具事实共同进入 `EvidenceBundle`，Evaluator 决定结论是否得到支持。
6. **高风险变更保留 HITL**：写库、覆盖、删除、发布标准、修改权限、晋级候选等操作必须服从 side-effect policy、审批、审计和 rollback。
7. **自我进化以证据晋级**：候选不能评价自己；未通过不可变安全集、回归集、未见 holdout、shadow/canary 和回滚门的改动不得进入生产。

### Palantir 标杆吸收项（规划中，实施暂缓）

> 对比报告：[GIS Data Agent 智能体大脑与 Palantir 技术体系客观对比分析](reports/gis-data-agent-brain-vs-palantir-objective-comparison-2026-07-15.md)。吸收重点是 operational ontology、动态安全、对象行动闭环、typed SDK 和变更生命周期；不建设通用 Foundry，不削弱 GIS/TWM 垂直能力。

| 工作包 | 归属子项目 | 状态 | 范围 | 验收门 |
|---|---|---|---|---|
| **Operational Object Model** | Standards Knowledge Brain | 规划中；暂缓 | ObjectType、PropertyType、LinkType、ObjectInstanceRef、对象状态机和稳定版本引用 | 首批治理对象 schema 通过版本、来源、ACL、link 完整性和兼容性评测；不复制业务事实 |
| **Action/Function/Interface Model** | Standards Knowledge Brain | 规划中；暂缓 | ActionType、FunctionType、InterfaceType、参数、前置条件、证据、权限、副作用、幂等、补偿和 Evaluator | ActionType 不能绕过 RuntimePolicy；breaking change 必须 major version + impact analysis |
| **Object-Action-Capability Binding** | Governance Pilot | 规划中；依赖前两项 | ActionType→CapabilityDefinition→Specialist Tool Manifest→Evaluator 固定版本绑定 | Planner 只选择合法 Action；工具替换不能扩大 Action 权限、参数和副作用 |
| **Dynamic Object Security** | Runtime Kernel 契约 + Knowledge/Governance 执行 | 规划中；分阶段 | 对象、属性、关系遍历、Action、ActionResult、产物和 AI context 的统一 Policy Decision | 跨租户泄露为 0；deny/requires-approval 不可被 Agent 或 Tool 绕过；策略版本进入 trace |
| **Typed Consumption Layer** | Governance Pilot | 规划中；暂缓 | 统一 Python、TypeScript、OpenAPI、MCP/A2A、UI form/approval 和 Evaluator schema | 同一 Action 的参数、结果和错误语义跨入口一致；SDK 兼容性测试通过 |
| **Ontology/Action Release Lifecycle** | Controlled Evolution | 规划中；保持 review-only | dev namespace、diff、impact、regression、review、shadow、canary、activate、rollback | 未通过安全/权限/兼容性门不得晋级；权威对象/Action/规则变更保留 HITL |

明确非目标：

- 不以“成为通用 Palantir/Foundry”作为产品目标；
- 不把全部 GIS 要素复制进本体、RDF Store 或属性图；
- 不允许 RDF/图/向量/搜索投影成为第二权威写源；
- 不因增加 Operational Ontology 而重写 PostGIS、ArcPy、Standards、NL2SQL 或 TWM；
- 不在 Runtime Kernel 完成前启动 Action 写回和 SDK 大规模改造。

### Heavy Ontology Platform（条件路线，未启动）

> 定位：企业级 Semantic + Operational Ontology Platform 的远期条件路线。它不替换当前 PostgreSQL/PostGIS、Standards Platform、轻量 OntologyPackage 或 Cognitive Runtime，也不因文档设计完成而自动启动。当前状态统一为“规划中；未启动”。

| 阶段 | 状态 | 依赖 | 核心范围 | 进入门 | 退出门 |
|---|---|---|---|---|---|
| **H0 — Business/Architecture Entry Gate** | 规划中；未启动 | Runtime/Knowledge Brain 设计基线；轻量 Stage 1/2 的代表性任务与测量能力 | 30-50 个 competency questions；跨组织/跨版本/空间适用性/动态安全场景；容量、SLO 候选、三年 TCO、团队和供应商评估 | UWM 与 ArcPy MCP 并行工作稳定；owner 指定业务 sponsor；可获得真实/脱敏工作负载 | 证明至少两项稳定重型需求且轻量路线无法合理满足；owner 批准业务价值、SLO、TCO、组织和继续/停止 ADR |
| **H1 — Ontology Governance & Model Registry** | 规划中；未启动 | H0 go 决策；领域/标准 owner 和 Ontology Engineer 到位 | Ontology Studio/Governance、namespace、稳定 URI、Canonical Model Registry、provenance、ACL、review、diff、impact、签名包和 rollback | H0 退出门通过；不与 Runtime Kernel 首项实施混合 | 模型发布/回滚/历史重放可审计；LLM 候选不能绕过 review；不存在第二业务真值源 |
| **H2 — RDF/SHACL Build & Validation** | 规划中；未启动 | H1 Registry 和版本契约稳定 | SKOS、SHACL、PROV-O、必要 GeoSPARQL/OWL-Time、JSON-LD/Turtle、RDFLib/pySHACL CI、受限 OWL 2 RL 实验 | 有批准的 competency queries、Shape owner 和外部互操作样本 | 每个发布包通过 Shape/来源/兼容性/推理回归；JSON Package 与 RDF 投影/hash 一致；推理有 trace |
| **H3 — Semantic Query Gateway & Policy Federation** | 规划中；未启动；非必经 | H2；RuntimeIdentity/Policy；代表性 SLO 与安全基准 | SQL/SPARQL/Graph/Search/Spatial 联邦、EvidenceBundle、query budget、权限下推、隔离缓存；条件部署 Fuseki/RDF4J/企业语义平台 | 轻量 PostgreSQL/Package 在批准的 SLO 或互操作需求上失败；PoC/ADR 通过 | 未授权返回 0；p95/p99 达到 owner SLO；故障可降级到固定 Package；查询/来源/策略可审计 |
| **H4 — Operational Object & Action Service** | 规划中；未启动；非必经 | H3 或等价安全查询能力；Governance Pilot contracts | Object/Property/Link/Action/Function/Interface 服务、动态策略、typed SDK、ChangeSet/ActionResult、写回和审批 | 至少两个独立应用/工作流需要统一对象行动契约，或轻量 Governance Pilot 证明平台化价值 | 一个标准治理场景完成对象发现、Action 规划、审批、执行、评价、写回和回滚；跨入口 schema 一致 |
| **H5 — Multi-Store Projection & Reconciliation** | 规划中；未启动；非必经 | H1-H4 中至少两个在线投影形成稳定生产负载 | Kafka/Redpanda、Schema Registry、Outbox、DLQ、幂等消费者、Projection Reconciler、蓝绿重建和一致性告警 | 单 Outbox/Worker 无法满足已批准的吞吐、重放或隔离要求 | authority/projection hash 和 checkpoint 可对账；故障注入后可重放、重建和安全降级；无双写 |
| **H6 — Production Resilience, SDK & Release Governance** | 规划中；未启动；非必经 | H3-H5 的生产候选服务和 owner 批准 NFR | HA、backup/restore、DR、OTel/SLO、容量、包签名、mTLS、SDK 兼容性、ontology/action CI/CD 和 runbook | 生产上线范围、RPO/RTO、SLO、值班和预算已确认 | restore、projection rebuild、ontology/policy rollback 演练通过；SLO/告警/runbook/责任边界可执行 |
| **H7 — Cross-Organization Federation** | 规划中；未启动；远期 | H6；明确的跨组织业务协议和法律/安全边界 | 签名 namespace、外部映射注册表、冲突协商、联邦 SPARQL、MCP/A2A 交换和多组织发布治理 | 至少两个组织有稳定共享需求、共同语义 owner 和责任协议 | 外部包来源/签名可验证；冲突不静默合并；权限、版本、审计和退出机制经过联合演练 |

路线纪律：

1. **H3+ 不是必经阶段**：如果轻量 Stage 1/2 的 PostgreSQL、OntologyPackage、RDF/SHACL 离线验证和现有 Policy Adapter 满足批准的 SLO、互操作与安全需求，路线停留在轻量架构。
2. **不 RDF 化大规模空间事实**：地块、栅格、点云、轨迹和推演状态继续由 PostGIS、GeoParquet/COG、对象存储、ArcPy 和 TWM 管理；RDF 保存语义、适用性和稳定引用。
3. **不建立多真值源**：业务事实、标准发布和本体模型分别有明确权威；RDF、Operational Graph、Search 和 Vector 只做版本化可重建投影。
4. **不先选产品再找问题**：Stardog、GraphDB、TopBraid、Neptune、Anzo、Fuseki、RDF4J、OPA、Cedar、Kafka/Redpanda 等仅为 PoC 候选，必须经过相同数据、查询、安全、故障和 TCO 基准。
5. **独立实施计划**：H1-H7 每阶段单独形成 ADR、实施计划、验收报告和回滚方案，不与 UWM、ArcPy MCP 或 Runtime Kernel 的代码改造混在同一工作包。

### 启动前待确认项

- 生产并发、吞吐和 p95/p99 延迟 SLO；
- RPO/RTO、异地容灾与 Trace/Memory/Evidence/Artifact 保留期；
- HITL 审批 SLA、责任人和高风险副作用矩阵；
- Runtime 目标物理 DDL、分区、索引与迁移策略；
- 首个真实或脱敏的数据标准驱动治理试点数据集。

> 下方既有“Agent Runtime Reliability & Cognitive Control”P0/P1/P2 清单继续保留，作为现状缺口和 Runtime Kernel/评测工程的详细输入；若与本节交付顺序冲突，以本节五子项目及其验收门为准。

---

## Cross-Cutting — Agent Runtime Reliability & Cognitive Control (规划中, 2026-07-11)

> **主题**：在不削弱现有 GIS、Standards、NL2SQL、TWM 和 DRL 能力的前提下，将当前分散的 Agent、工具、记忆、上下文、评测、安全和可观测性模块收束为一个强类型、可恢复、权限一致、可评测和可复现发布的 Agent Runtime。
>
> **证据基线**：[《AI Agents in Action（第二版）》对 GIS Data Agent 的系统评估与改进建议](ai-agents-in-action-gis-data-agent-assessment-2026-07-11.md)

战略判断：项目当前的主要瓶颈不是 GIS 功能不足，而是部分高级模块“已经定义、尚未进入真实主链”。下一阶段优先修复伪闭环、跨入口策略差异和租户隔离，再建设 Cognitive Runtime；不以继续扩充 GeneralProcessing 工具数量或创建平行模块作为主要路线。

目标运行架构：

```text
All Entrypoints
  -> Unified RunnerFactory
  -> FrontDoor (<= 6-10 meta tools)
  -> RunWorkspace + deterministic AttentionRouter
  -> Typed Specialist Worker (small tool manifest)
  -> Typed Evaluator
  -> retry | replan | retrieve memory | respond | escalate
```

当前审计基线：

- 三个 generator/checker 质量工作流当前只顺序执行一次，`max_iterations` 不参与控制流；
- 核心 Agent 交接主要依赖自由文本和 `output_key`，Skill schema 未进入生产 caller；
- 运行时工具枚举：GeneralProcessing `315`、Planner `63`、DataProcessing `34`、DataAnalysis `41`、GovProcessing `33`；
- UI 会加载 CostGuard、Retry、Provenance、Guardrail 和可选 HITL，多个 headless 入口默认可能使用空插件列表；
- MCP Agent 工具发现未传 username，ContextEngine 缓存键未包含 tenant/user/role；
- task decomposition 调用不存在的 `run_pipeline`，当前路径可触发 `ImportError`；
- Conversation Memory、ContextEngine、DecisionTracer、OTel、PlanRefiner 和 Prompt Registry 均已有实现基础，但主链接线不完整；
- 当前 ADK eval 共 `12` 个正向案例，尚不足以覆盖重试、隔离、注入、故障恢复和认知停滞。

### P0 — Runtime Truthfulness & Security Consistency

> **进入条件**：以当前运行语义缺口编写失败测试；禁止只验证类、属性或辅助函数存在。<br>
> **退出条件**：以下四个工作包全部通过集成测试后，才能扩大主动记忆、自进化和 ContextEngine 的生产接入面。

| 工作包 | 范围 | 依赖 | 验收门 |
|---|---|---|---|
| [ ] **Typed quality loop** | `QualityVerdict(pass/revise/escalate)`、条件回跳、反馈注入、iteration/token/cost/tool-failure/stagnation 门 | ADK Workflow routed edges、Pydantic schema | checker 返回 revise 后 generator 确实重跑；质量通过、预算耗尽和停滞三条路径均有确定性测试 |
| [ ] **Unified RunnerFactory** | UI、headless、MCP、A2A、queue、workflow、CLI、TUI、Bot 统一 mandatory plugin stack、session/memory/context 和 trace | plugins、guardrails、HITL、pipeline runner | 所有入口均加载 CostGuard、Retry、Provenance 和 Guardrail；调用方不能用空列表绕过必需策略 |
| [ ] **Tenant isolation hardening** | MCP tool visibility、Context cache、KB provider 和 RuntimeIdentity 统一 | user ContextVar、MCP Hub、ContextEngine | 双用户私有 MCP/KB/缓存隔离测试通过；缺失身份时默认拒绝私有能力 |
| [ ] **Task decomposition repair** | 正确 headless runner、`agent_hint` 路由、typed TaskResult、失败重规划、最终 synthesis | task decomposer、PlanRefiner、pipeline runner | 多依赖任务可端到端执行；失败节点不会被简单计数掩盖；结果包含证据、产物和失败解释 |

### P1 — Tool Surface & Cognitive Runtime

> **进入条件**：P0 全部通过。<br>
> **退出条件**：复杂任务具备统一 workspace、确定性下一步路由和主动经验检索，且每次运行可重放关键状态。

| 工作包 | 范围 | 依赖 | 验收门 |
|---|---|---|---|
| [ ] **Capability manifest + dynamic tool loading** | 建立 capability catalog、route manifest 和按任务加载的小工具集 | Agent/Skill/Operator/MCP registry | FrontDoor 不超过 10 个工具；specialist 默认不超过 10 个主要工具；trace 记录实际工具及版本 |
| [ ] **RunWorkspace** | 统一 goal、plan、subgoals、evidence、artifacts、failures、memory、budget、confidence 和版本 | typed contracts、trace storage | 每次复杂运行可重建计划修订、工具观察、评价和退出原因 |
| [ ] **Deterministic AttentionRouter** | fast/plan/execute/evaluate/replan/retrieve/respond/escalate 状态路由 | RunWorkspace、QualityVerdict | 低置信、停滞、证据不足和工具失败能够触发可预测路由，不由自由文本直接控制高风险分支 |
| [ ] **Proactive structured memory** | planning 前检索 episodic/procedural/semantic memory，evaluation 后记录结构化经验；加入 TTL、压缩和冲突处理 | Conversation Memory、KB、feedback | 检索命中可改变计划；错误记忆可撤回；过期和跨租户记忆不可见；不以整段长回答作为主要记忆单元 |

### P2 — Evaluation, Observability & Versioned Release

> **进入条件**：P0 完成，P1 至少完成 RunWorkspace 和 tool manifest。<br>
> **退出条件**：从失败发现到回归评测、灰度发布和回滚形成可审计链路。

| 工作包 | 范围 | 依赖 | 验收门 |
|---|---|---|---|
| [ ] **Cognitive failure benchmark** | confident wrong answer、broken record、rigid plan、overcommitted guess、shallow composition，加 GIS CRS/单位/重复计数/权限案例 | ADK Eval、Evaluator Registry | 核心 pipeline 同时包含正向、负向、故障和隔离案例；每例多次运行并统计答案、轨迹、成本和延迟方差 |
| [ ] **Trace wiring** | route、plan、tool、memory、guardrail、quality、cost、confidence、outcome 全链路 | OTel、DecisionTracer、RunWorkspace | 任一失败可定位到决策、证据和版本；trace 不依赖 UI session 才存在 |
| [ ] **Versioned release gates** | prompt/model/tool schema/MCP server version 固定，offline eval -> shadow -> canary -> SLO rollback | Agent factory、Prompt Registry、eval history | prompt deploy 无需依赖进程重启语义；每次运行可复现版本；回归自动阻断晋级 |
| [ ] **Feedback-to-eval promotion** | trace、负反馈和工具失败进入候选 eval，人工审核后晋升回归集 | feedback、failure-to-eval、evaluation CI | 未审核案例和 prompt 修改不能自动进入生产；线上失败可追踪到后续回归用例 |

阶段顺序：

1. **Gate A：真实闭环与隔离** — 完成 P0，消除已知运行时和权限风险；
2. **Gate B：认知控制层** — 收缩工具面，接入 RunWorkspace、AttentionRouter 和主动记忆；
3. **Gate C：评测发布飞轮** — 扩充认知失败 benchmark，完成 trace、版本和灰度回滚；
4. **Gate D：受控自进化** — Self-Evolution 继续保持 review-only，直到反馈、评测、权限和回滚门全部可审计。

非目标：

- 不重写现有 GIS、TWM、Standards 和 NL2SQL 领域算法；
- 不以增加更多 Agent 或 Toolset 替代运行时收束；
- 不把启发式 confidence 作为校准概率；
- 不在 P0 完成前扩大自动 prompt 发布或跨用户记忆注入。

---

## v25.21 — TWM 自然资源部演示闭环 + 数据基础地图化 (自动化验证通过, 待人工确认, 2026-06-27)

> **主题**: Territory World Model 从后台工具和技术验证，推进到面向自然资源原型汇报的前端交互闭环。当前目标是证明“数据基础、地图定位、规则证据、风险推演、方案比选、基线对比、技术载荷”可以在同一条可审计链路中运行，同时严格保留非生产数据和证据门控边界。

- [x] **TWM 前端中文化与子 tab 组织** — TWM 操作页改为中文优先，拆分为 `总览地图`、`数据证据`、`操作推演`、`技术载荷`，避免给自然资源部演示时出现中英文混杂和信息堆叠。
- [x] **数据基础浏览器 + 空间图层目录** — `数据证据` 页展示主演示数据包、空间图层目录、图层 bbox、字段数量、代表性字段、样例属性、图层级坐标诊断、完整数据清单、验证快照、问题-数据适配、阻断项和来源报告；默认主演示包为 `twm_bishan_multi_admin_eval`。
- [x] **逐层上图 + 全量空间数据加载 + 坐标诊断 + 图层开关** — 新增 `GET /api/twm/data-foundation-map-preview/{dataset_id}`，支持 `max_features_per_layer=all` 返回 full GeoJSON，并支持 `layer=` 只加载指定空间图层；主演示包空间 GeoJSON 全量为 `21,603` 个要素，`synthetic_projects.geojson` 单图层为 `90` 个要素；接口返回 `map_overlay_readiness` 和图层级 `crs_diagnostic`，前端会阻断明显非经纬度图层直接叠加，并支持在全量加载后逐图层隐藏/显示。
- [x] **地图叙事范围修正** — 修复此前总览地图审查区和数据基础空间范围不一致的问题。主演示 bbox 固定为 `[106.152182211, 29.667518609, 106.367539714, 29.886844144]`，审查区、风险命中和推荐方案均与该范围对齐。
- [x] **总览地图联动** — `定位审查区`、`展示风险命中`、`展示推荐方案` 可向主地图推送 TWM 图层，演示中可以直接看到空间证据，而不是只看文字框。
- [x] **端到端演示脚本与测试报告** — 新增自然资源部演示脚本和 E2E 测试报告，自动化测试覆盖登录、TWM 子 tab、全量加载、项目构建、规则审查、预测、验证、审计、方案比选、基线对比和技术载荷。
- [x] **空间一致性防回归** — Playwright E2E 不再只检查页面状态文字，而是捕获推送给地图的 GeoJSON bbox，确认全量数据、定位审查区、风险命中和推荐方案均与主演示数据包 bbox 相交。
- [x] **理论与发展边界文档** — 新增全国权威数据能力上限判断、TWM 作为 geospatial world model 的理论创新判断、TWM 后续完善与迭代规划。

已验证证据：

- 后端数据基础 focused tests：`9 passed in 32.13s`
- 前端 build：通过，保留既有 Vite chunk size 和 loaders.gl browser external 警告
- 本地容器健康检查：`http://127.0.0.1:8000/` 返回 `200`
- TWM 演示 Playwright E2E：`1 passed (3.9m)`
- 测试报告：`docs/reports/twm_e2e_test_report_2026-06-27.md`
- 演示脚本：`docs/reports/twm_natural_resources_demo_script_2026-06-27.md`
- 迭代规划：`docs/reports/twm_iteration_improvement_plan_2026-06-27.md`

当前边界：

- 当前数据仍是演示/非生产数据，不能包装成自然资源部门权威结论。
- `twm_one_map_village_standard_sample` 当前坐标不是 WGS84 经纬度，不应和主演示样例直接混合叠加。
- 当前验证证明的是演示链路、空间一致性和工程闭环，不等于证明真实预测效果、全国泛化或规划增益。
- TWM simulator、trainable dynamics、planner 和 baseline comparison 已具备工程雏形，但生产级主张仍需要真实历史、政策动作标签、同案 baseline 和跨期/跨区 holdout。

下一阶段 TWM roadmap：

- [ ] **算法模型路线刷新** — 新增 [TWM Algorithm Model Roadmap](twm-algorithm-model-roadmap-2026-06-30.md)，把后续优化从“演示闭环”转向“生产证据门、状态/action/next-state 契约、action-conditioned dynamics、planner-coupled evaluation、因果/GeoFM gate、模型注册与 L3 promotion gate”。
- [ ] **2-4 周：Production evidence gate** — 接入至少一个真实或脱敏试点包，补齐审批/复核/执法/后续变化历史、政策动作标签、action feasibility、same-case baseline 和 MREP trace；无生产 observed history 时阻断模型 promotion。
- [ ] **2-6 周：State/action/next-state contract** — 固化 `future_latent_state` v2、时间/空间 holdout、数据集 hash、规则/状态/模型版本和失败分类，避免只看 total-area 的虚假通过。
- [ ] **1-3 个月：Dynamics model optimization** — 在同一数据契约下比较 MLP、hierarchical graph、spatiotemporal transformer、TWM-native suitability learner 与 Markov/FLUS/GeoSOS baseline；按 metric-specific 结果表述，不做 blanket superiority claim。
- [ ] **2-4 个月：Planner-coupled evaluation** — 用 legal-feasible top-k、blocked-action recall、planner regret、ranking lift、review workload 和 selected-plan audit 衡量 TWM 是否真的改进规划/审查决策。
- [ ] **3-6 个月：Causal/evidence/GeoFM upgrade** — 将 causal calibration 默认标注为 observational，只有在识别设计、空间诊断、SCCA 外部证据和 GeoFM B0/B1/D2/D3/D4 gate 通过时才升级相关 claim。
- [ ] **6-12 个月：Production promotion + L3 path** — 完成服务拆分、模型注册/版本固定/回滚、replay/regression gate、权限脱敏、内网部署、lakehouse/瓦片化和全国级多尺度状态图；L3 self-evolution 保持 review-only 直到真实反馈闭环通过审计。

---

## 已完成 (v25.0) — Standards Platform 全链路 + 世界模型 v2 + NL2SQL hardening

> **主题**: 数据标准从"Word 文档"升级为**全生命周期可治理资产**——采集 / 起草 / 审定 / 发布 / 派生 / 数据建模六阶段闭环；同时世界模型从单层 latent dynamics 升级为双层 dual-layer dreamer；NL2SQL 加上列名反查 + DISTINCT guard + LLM schema mapper。

### Standards Platform — Wave 1 → Wave 6+ (主线, 2026-05-13 → 2026-05-28, ~30 commits)

- [x] **Wave 1 / 1.5 — 采集底座 + data_elements 动态拼接** — 16 张 `std_*` 表 + Outbox 独立 worker + ltree + pgvector(768) + 12+6 REST + StandardsTab 双 sub-tab
- [x] **Wave 2 — TipTap 起草 + 引用助手 + 一致性校验** + StandardsEditorAgent (Agent #7)
- [x] **Wave 3 — 审定流模板 + v1 Fixes**
- [x] **Wave 4 — 发布 + 版本快照**
- [x] **Wave 5 — ABCD 产品化核心闭环** — standards_platform 210 passed / npm build OK / 浏览器 smoke 后端 SQL 验证
- [x] **Wave 6-eng — ValueDomainStrategy 派生** — `agent_semantic_hints` (migration 081) + SemanticHintStrategy 合并 registry aliases
- [x] **Wave 6+ — SynonymStrategy 派生** — `agent_semantic_sources.derived_synonyms` (migration 082) + grounding 合并 (`synonyms ‖ derived_synonyms`)，**派生覆盖率 33%→50% (3/6 strategy)**

> Migrations 067-082 全部落地；230 standards_platform tests passed。Spec 全集见 `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`。

### 世界模型 v2 + DRL hardening (2026-05 中下旬)

- [x] **world_model_v2** — Causal World Model + Transition Model + 第二层 dynamics (`dual_layer_dreamer.py` + `dual_dreamer_pipeline.py`) + 4 个 DAgger ensemble resume 实验脚本
- [x] **embedding_gateway** — Ollama backup path（本地 `192.168.31.252:11435` nomic-embed-text 768d）
- [x] **classification_routes / world_model_v2_routes / capability_qa toolset** — 数据分级 API + 能力问答 toolset

### NL2SQL hardening (2026-05 全月)

- [x] **llm_schema_mapper** — LLM 主导的 schema 映射降级路径
- [x] **sql_distinct_guard** — DISTINCT 注入静态分析（P=63.5% R=12.1%，作 ablation 而非主线）
- [x] **grid_anonymize + PG 适配器** — 网格匿名化 + 单元 / PG 双套测试
- [x] **gemini-3.5-flash 专属 system_instruction.md** — `prompts_nl2sql/gemini-3.5-flash/` 模型族特化

> 详细攻防记录在内部 memory，本仓库不公开 v6/v7 paper experiments。

---

## v25.3 — Standards Platform Wave 8b (P3 收口, 已完成, 2026-06-03)

- [x] **EA-compatible XMI 导出** — 新增 `data_model_xmi_exporter.py`，从 active `std_data_model_snapshot.pdm_json` 导出 UML/XMI XML；稳定 ID 基于 package + physical_table / physical_column，PDM 类型映射覆盖 string / numeric / integer / boolean / geometry-as-string，nullable 映射为 UML multiplicity。
- [x] **XMI 下载 API** — `GET /api/std/data-model/{vid}/xmi`，任何已登录角色可读；返回 `application/xml` + `Content-Disposition: data_model_<vid>.xml`，复用现有 active snapshot/version 404 语义。
- [x] **前端下载入口** — `DataModelPreviewModal.tsx` 在 DDL 工具栏增加「下载 XMI」，复用既有数据模型预览 modal，不新增独立建模 sub-tab。
- [x] **Round-trip 验证** — 导出的 XMI 可被现有 `parse_xmi_file()` 解析出 class / attribute / multiplicity；新增 exporter + API focused tests，前端 build 通过。

> P3 首个生产级闭环完成：CDM/LDM/PDM + PostgreSQL DDL + EA-compatible XMI export。下一步进入 P4：审定流模板可视化、批量回滚、跨标准影响图谱。

---

## v25.4 — Standards Platform P4 First Slice (已完成, 2026-06-05)

- [x] **Outbox dead-letter UI** — 在 `DeriveSubTab` 增加 admin-only outbox 运维面板，可查看 `failed` / `pending` / `in_flight` / `done` 事件、展开 payload 与 last_error，并支持单条与批量 retry。
- [x] **Outbox admin API** — 新增 `GET /api/std/outbox/events`、`POST /api/std/outbox/events/{id}/retry`、`POST /api/std/outbox/events/retry`；保留 worker at-least-once 语义，不删除或编辑事件 payload。
- [x] **测试覆盖** — 新增 outbox repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化、批量回滚、跨标准影响图谱。

---

## v25.5 — Standards Platform P4 Batch Rollback First Slice (已完成, 2026-06-06)

- [x] **Batch rollback repository/API** — 新增 `link_repo.rollback_versions()` 与 admin-only `POST /api/std/derive/rollback`，复用单版本 rollback 语义，支持 duplicate/missing/malformed ID 跳过与最多 50 个版本的批量请求。
- [x] **Batch rollback UI** — 在 `DeriveSubTab` 增加 admin-only 批量回滚运维面板，可加入当前版本或粘贴多个 version id，显示 rolled_back / skipped 汇总与逐版本结果，并在前端提前拦截超过 50 个 ID 的请求。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化、跨标准影响图谱。

---

## v25.6 — Standards Platform P4 Cross-Standard Impact Graph First Slice (已完成, 2026-06-06)

- [x] **Version impact graph repository/API** — 新增版本级影响图谱聚合，统一派生链、引用关系与相似条款边，输出 nodes/edges/summary，并对 `include_similar` / `min_similarity` / `top_k` 做 API 参数校验。
- [x] **Analyze UI** — 在 `AnalyzeSubTab` 增加跨标准影响图谱摘要与边列表，展示 derives / references / similar_clause 关系和跨版本边计数；加载切换具备 stale guard，避免版本切换时图谱与条款列表错位。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化。

---

## v25.7 — Standards Platform P4 Review Template Visualization First Slice (已完成, 2026-06-06)

- [x] **Review template repository/API** — 新增只读默认审定流模板，按现有 `std_document_version` / `std_review_round` / `std_reference` / `std_review_comment` 状态计算 draft → review → audit → comments → close → approved 的步骤、角色、门禁与摘要。
- [x] **Review UI** — 在 `ReviewSubTab` 顶部增加审定流模板面板，展示版本状态、open/latest round、reviewer、待审引用、未决意见和六步流程状态；引用审定、评论解决、启动/关闭 round 后自动刷新。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 三项（审定流模板可视化、批量回滚、跨标准影响图谱）全部完成。下一阶段进入 P5：标准市场（多组织共享 + 订阅 + diff）。

---

## v25.8 — Standards Platform P5 Market Catalog + Diff First Slice (已完成, 2026-06-06)

- [x] **Market catalog repository/API** — 新增 released 标准版本市场目录，复用现有 `std_document_version.status='released'` 作为可共享条目，返回文档元数据、标签、owner、release 信息和条款/数据元/术语/值域资产计数。
- [x] **Version diff repository/API** — 新增 `GET /api/std/market/diff`，支持两个版本按 clause / data_element / term / value_domain 自然键做 added / removed / changed / unchanged 的确定性结构化 diff。
- [x] **Market UI** — `StandardsTab` 新增「市场」子页，可搜索 released 标准、查看资产计数、设置市场版本为当前版本，并以当前版本 vs 市场版本运行 diff。
- [x] **测试覆盖** — 新增 market repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P5 已启动并完成目录 + diff first slice；订阅持久化已在 v25.9 补齐，市场审核已在 v25.10 补齐，多组织共享/权限模型已在 v25.11 补齐 first slice。P5 剩余主线：diff 深化。

---

## v25.9 — Standards Platform P5 Market Subscriptions First Slice (已完成, 2026-06-06)

- [x] **Market subscription repository/API** — 新增 `std_market_subscription` 迁移与仓储，支持按用户订阅 released 标准版本，记录 `source_version_id`、`last_seen_version_id`、active/cancelled 状态，并提供订阅、列表、mark-seen、取消订阅 API。
- [x] **Update detection** — 订阅列表按同一 `std_document` 的最新 released version 计算 `has_update`，让用户能看到当前订阅版本、最新市场版本和是否有新版本可跟进。
- [x] **Market UI** — 市场页增加「我的订阅」面板，支持从目录订阅/取消、切换订阅版本为当前版本、标记已读，并在目录项上显示已订阅与有更新状态。
- [x] **测试覆盖** — 新增 market subscription repository + API focused tests；focused `12 passed`、standards_platform 全套 `422 passed, 1 skipped`，前端 `npm run build` 通过。

> P5 已完成目录 + diff + 订阅持久化两个 first slice；市场审核已在 v25.10 补齐，多组织共享/权限模型已在 v25.11 补齐 first slice。P5 剩余主线：diff 深化。

---

## v25.10 — Standards Platform P5 Market Review First Slice (已完成, 2026-06-06)

- [x] **Market listing review repository/API** — 新增 `std_market_listing` 迁移与仓储，支持 released 标准版本提交上架、admin 通过/拒绝审核、待审列表与审核审计字段。
- [x] **Catalog visibility integration** — 市场目录兼容历史 released 版本（无 listing 行视为 `legacy_approved`），但对已有 listing 的版本按审核状态控制展示：`submitted/rejected/withdrawn` 隐藏，`approved` 展示。
- [x] **Market UI review controls** — 市场页增加「提交审核」与「市场审核」队列，支持刷新待审项、通过/拒绝，并在目录卡片显示上架审核状态。
- [x] **测试覆盖** — 新增 market listing repository + API focused tests；market focused `34 passed`，standards_platform 全套 `432 passed, 1 skipped`，前端 `npm run build` 通过。

> P5 已完成标准市场目录、版本 diff、订阅持久化和市场审核四个 first slice；多组织共享/权限模型已在 v25.11 补齐 first slice。P5 剩余主线：diff 深化。

---

## v25.11 — Standards Platform P5 Organization Access First Slice (已完成, 2026-06-06)

- [x] **Organization visibility model** — 扩展 `std_market_listing`，新增 `visibility_scope`、`owner_org_id`、`allowed_org_ids`，支持 `public / organization / private` 三类市场可见范围。
- [x] **Catalog ACL integration** — 市场目录读取 JWT metadata 中的 `org_id / organization_id / org / tenant_id`，按 listing 可见范围过滤；legacy released 标准继续公开可见，admin 具备审核目录可见 bypass。
- [x] **Market visibility API/UI** — 提交上架时可设置可见范围、owner org 与 allowed orgs，admin 可 PATCH listing visibility；市场页目录卡片与审核队列显示范围，提交审核表单支持组织访问参数。
- [x] **测试覆盖** — 新增 market org access repository + API tests；market focused `45 passed`，standards_platform 全套 `443 passed, 1 skipped`，前端 `npm run build` 通过。

> P5 标准市场已完成目录、diff first slice、订阅、审核与组织级访问控制。P5 剩余主线：diff 深化（字段级差异解释、影响范围联动、订阅更新提醒增强）。

---

## v25.12 — Standards Platform P5 Diff Deepening First Slice (已完成, 2026-06-18)

- [x] **Field-level market diff** — `GET /api/std/market/diff` 在 changed 资产上返回 `field_changes` 与 `field_change_count`，按 clause / data_element / term / value_domain 的内容字段生成确定性差异。
- [x] **Diff review hints** — diff summary 新增 `field_changes`、`changed_fields_by_asset_type` 和 `review_hints`；对删除/修改项提示兼容性复核，对 datatype / obligation / cardinality / bound_table / bound_column / kind 等契约字段变化标高风险。
- [x] **Market UI field detail** — 市场页 diff 表增加字段差异计数、复核提示和 source/target 字段值对比行，保留原 added / removed / changed / unchanged 视图。
- [x] **测试覆盖** — market repository + API focused tests 通过；前端 `npm run build` 通过。

> P5 diff 深化已完成字段级解释 first slice。剩余主线：影响范围联动（接 `std_impact` / 派生链）和订阅更新提醒增强。

---

## v25.13 — Self-Evolution Orchestration First Slice (已完成, 2026-06-18)

- [x] **SelfEvolutionEngine** — 新增 `data_agent/self_evolution.py`，把 v16 `ToolEvolution`、v19 `FeedbackLoop`、`FailureAnalyzer`、工具失败学习表和 failure-to-eval 串成 `observe -> analyze -> propose` 的可审计进化周期。
- [x] **Dry-run first** — 默认只生成改进提案，不自动修改 prompt、工具或评测集；显式 `apply=true` 时才把 prompt 建议写入指定 environment，默认 `dev`。
- [x] **Agent tool entry** — `ToolEvolutionToolset` 新增 `run_self_evolution_cycle`，Planner 可直接触发自主进化周期，返回反馈统计、失败模式、工具替代建议、prompt 目标、评测候选和下一步动作。
- [x] **测试覆盖** — 新增 self-evolution unit tests，更新 ToolEvolutionToolset 注册测试。

> 这一步把 roadmap 里已有的“工具演化 + 反馈飞轮 + 失败分析”从分散能力升级为可运行的自主进化闭环。后续可继续补：进化周期持久化、人工审批 UI、评测候选一键入库、prompt 建议 diff 视图。

---

## v25.14 — Self-Evolution Persistence First Slice (已完成, 2026-06-18)

- [x] **Cycle audit table** — 新增 `agent_self_evolution_cycles`（migration 089），持久化一次 `observe -> analyze -> propose` 周期的 summary / analysis / proposals / safeguards / full report，支持 proposed / applied / failed / dismissed 审计状态。
- [x] **Runtime persistence API** — `data_agent/self_evolution.py` 增加 `ensure_self_evolution_tables()`、`record_cycle()`、`list_cycles()`、`get_cycle()`；数据库不可用时不会阻断自主进化周期，只返回 persistence skipped。
- [x] **Agent tool persistence options** — `run_self_evolution_cycle` 新增 `persist`、`triggered_by`、`trigger_source` 参数；默认记录 dry-run 报告，显式关闭时只返回一次性报告。
- [x] **Startup initialization** — Chainlit app 启动时初始化 self-evolution audit table，与 feedback / failure learning 表保持同一容错初始化路径。
- [x] **测试覆盖** — 新增持久化、状态判定、查询解码、tool wrapper 参数透传单测。

> 自主进化从“能跑一轮”推进到“能留下可审计候选记录”。后续主线：人工审批 UI、prompt 建议 diff 视图、eval candidates 一键入库、周期定时调度。

---

## v25.15 — Self-Evolution Admin API First Slice (已完成, 2026-06-18)

- [x] **Admin run endpoint** — 新增 `POST /api/self-evolution/run`，admin 可从 REST 触发一次自主进化周期；默认 dry-run + persist，`triggered_by` 默认当前 admin，`trigger_source=api`。
- [x] **Cycle review endpoints** — 新增 `GET /api/self-evolution/cycles` 与 `GET /api/self-evolution/cycles/{id}`，可查看已持久化的进化候选列表与完整报告。
- [x] **Existing RBAC integration** — 路由复用 `api.helpers._require_admin`，统一接入现有 JWT + admin role 鉴权；非 admin 不能触发或查看进化审计记录。
- [x] **Frontend API mount** — 自主进化 API 挂入 `get_frontend_api_routes()`，与现有 React/Chainlit 前端 API 共用路由装载机制。
- [x] **测试覆盖** — 增加 route registration、列表、详情、运行端点 focused tests。

> 自主进化现在具备 Agent tool 和 Admin REST 两个入口。后续主线：审批 UI、prompt 建议 diff 视图、eval candidates 一键入库。

---

## v25.16 — Self-Evolution Admin Review UI First Slice (已完成, 2026-06-18)

- [x] **Admin dashboard entry** — 管理后台新增「自主进化」页签，作为 admin-only 的进化审计入口，不暴露给普通数据面板用户。
- [x] **Dry-run cycle runner** — UI 可配置窗口天数、读取上限、低分阈值、是否生成 prompt 建议，并通过 `POST /api/self-evolution/run` 触发 dry-run + persist 周期。
- [x] **Cycle audit list** — 展示周期 ID、时间、状态、模式、触发来源、坏例数、工具建议数与评测候选数，支持状态过滤和刷新。
- [x] **Review detail preview** — 详情区展示 summary 指标、下一步动作、工具/prompt/eval 候选数量，并提供完整 JSON 报告展开查看。
- [x] **Human-control boundary** — UI 暂不提供自动应用按钮；所有 prompt 变更、eval 入库和工具路由调整仍需后续审批动作实现。
- [x] **验证** — 前端 `npm run build` 通过，保留既有 Vite loaders.gl/browser external 与大 chunk 警告。

> 自主进化已从后端闭环推进到可人工查看的管理台。后续主线：审批动作 API、prompt diff 视图、eval candidates 一键入库。

---

## v25.17 — Self-Evolution Approval Actions First Slice (已完成, 2026-06-18)

- [x] **Review action API** — 新增 `POST /api/self-evolution/cycles/{id}/review`，支持 `approve_eval_candidates`、`approve_prompt_suggestions`、`dismiss` 三类 admin 审批动作。
- [x] **Eval candidate promotion** — `approve_eval_candidates` 将周期报告中的 `eval_candidates` 写入 `agent_eval_datasets`，scenario=`self_evolution`，形成可回归评测的数据集候选。
- [x] **Prompt dev version creation** — `approve_prompt_suggestions` 仅创建 `dev` 环境 prompt version，不直接部署到 prod；审批记录写入 cycle report。
- [x] **Cycle approval audit** — 所有审批动作写回 `report.approvals` / `last_approval`，并更新 cycle status 为 `applied`、`dismissed` 或 `failed`。
- [x] **Prompt diff preview** — 自主进化报告保留 `original_prompt` 与 `suggested_prompt`；管理后台可展开查看当前/建议 prompt 对照和 changes 列表。
- [x] **Review UI actions** — 管理后台「自主进化」页签增加「入库评测候选」「创建 dev prompt 版本」「驳回候选」按钮，按钮按候选可用性禁用。
- [x] **测试覆盖** — 新增审批动作单测和 `/review` API focused test；前端 `npm run build` 通过。

> 自主进化已具备“提出候选 -> 持久化审计 -> 管理台查看 -> 人工审批生成改进资产”的闭环。仍未自动生产部署；下一步可做定时调度、审批队列提醒和 prod 部署门禁。

---

## v25.18 — Self-Evolution Scheduler First Slice (已完成, 2026-06-18)

- [x] **Lightweight interval scheduler** — 新增 `SelfEvolutionScheduler`，基于当前 asyncio event loop 运行单个后台任务，无新增调度依赖；默认关闭。
- [x] **Conservative scheduled cycle** — 定时周期只运行 dry-run + persist，`trigger_source=scheduler`，不会自动应用 prompt、不会自动写 eval dataset、不会部署到 prod。
- [x] **Environment controls** — `.env.example` 增加 `SELF_EVOLUTION_SCHEDULER_ENABLED`、`INTERVAL_SECONDS`、`DAYS`、`LIMIT`、`MIN_SCORE`、`INCLUDE_PROMPTS` 配置。
- [x] **App startup integration** — Chainlit 首次会话启动时按配置启动调度器，和 workflow scheduler 一样延迟到 async context，避免 import 阶段创建任务。
- [x] **Admin scheduler API** — 新增 `GET/POST /api/self-evolution/scheduler`，支持查看状态、启动、停止和 `run_once` 手动触发调度器周期。
- [x] **Admin dashboard controls** — 「自主进化」页签显示调度器状态、最近周期、运行间隔，并提供启动/停止、立即运行按钮。
- [x] **测试覆盖** — 新增 scheduler run-once、默认关闭、scheduler API focused tests；前端 `npm run build` 通过。

> 自主进化主链路已完成“定时发现 -> 候选审计 -> 人工审批 -> 改进资产生成”的 first slice。审批提醒已在 v25.19 补齐；后续仍需 prod prompt 发布门禁，以及 P5 标准市场影响范围联动和订阅提醒增强。

---

## v25.19 — Self-Evolution Approval Reminders First Slice (已完成, 2026-06-18)

- [x] **Pending review summary** — 新增 `get_review_summary()`，基于 `agent_self_evolution_cycles.status='proposed'` 生成待审候选数、待审 eval / prompt / tool 建议数、高优先级计数和最近提醒列表。
- [x] **Review priority heuristics** — 对同时包含 eval 候选与 prompt/tool 建议的周期、集中坏例/差评/工具失败信号标记 high priority；其余改进资产候选标记 medium，低信号周期保留 low。
- [x] **Admin reminder API** — 新增 admin-only `GET /api/self-evolution/review-summary`，复用现有 `_require_admin` 鉴权，不暴露给普通用户。
- [x] **Admin dashboard reminder panel** — 「自主进化」页签顶部增加审批提醒面板，展示待审数量、候选类型数量、最近待审周期快捷入口；运行周期、调度器立即运行和审批动作后自动刷新提醒。
- [x] **测试覆盖** — 新增 review summary 聚合单测、API focused test 和路由注册断言。

> 自主进化现在具备“定时/手动发现 -> 候选审计 -> 审批提醒 -> 人工审批 -> 改进资产生成”的主线闭环。prod prompt 发布门禁已在 v25.20 补齐；下一步是发布前回归评测门禁。

---

## v25.20 — Self-Evolution Prod Prompt Gate First Slice (已完成, 2026-06-19)

- [x] **Two-step prompt promotion** — `approve_prompt_suggestions` 只允许创建 dev/staging prompt version；直接把自主进化建议写入 prod 会被拒绝，避免绕过生产发布门禁。
- [x] **Cycle-scoped prod deployment action** — 新增 `deploy_prompt_versions_to_prod` 审批动作，只部署该 cycle 审批记录中已经创建的非 prod prompt version，并把 source / target version 写入 cycle audit。
- [x] **Duplicate deployment guard** — 已经通过该 cycle 发布过 prod 的 source version 不会重复部署；没有可发布 dev version 时返回可审计错误。
- [x] **Admin API integration** — `/api/self-evolution/cycles/{id}/review` 支持 `target_environment=prod`，仍复用 admin-only 鉴权和 cycle 审计写回。
- [x] **Admin UI control** — 「自主进化」详情页新增「发布 prod prompt」按钮，只有已有 dev prompt version 且尚未 prod 发布时可用，并显示审批记录摘要。
- [x] **测试覆盖** — 新增 prod 绕过阻断、cycle-scoped prod 部署、重复部署阻断和 API 参数透传测试。

> 自主进化现在支持“先生成 dev prompt 版本，再由管理员显式发布 prod”的生产门禁。仍不会自动部署生产 prompt；后续需要把发布前回归评测和阈值门禁接入该动作。

---

## v25.3-eval — Standards Platform Wave 6-eval First Slice (已完成, 2026-06-03)

- [x] **派生质量离线评测框架** — 新增 `data_agent/standards_platform/evaluation/`：统一 `DerivationEvalItem` schema、canonical identity、gold/prediction set 校验、重复身份拒绝。
- [x] **P/R/F1 评分与阈值门禁** — `score_eval_sets()` 输出 overall + per-strategy precision / recall / F1，默认验收阈值 precision >= 0.85、recall >= 0.75；空 gold/prediction 场景按 no-op pass 处理。
- [x] **预测提取器** — 从 active `std_derived_link` 抽取六类派生预测：semantic_hint、value_semantics、synonym、qc_rule、defect_code、data_model；`to_value_semantics` 将 value_domain kind/code/values 纳入匹配身份，`to_synonym` 按 table + token 粒度评分。
- [x] **报告与 CLI** — `render_markdown()` 生成 CI/人工复核报告，`python -m data_agent.standards_platform.evaluation.cli` 支持 gold JSON + version_id 输出 JSON/Markdown，并用退出码表示阈值是否通过。
- [x] **测试 +14** — Wave 6-eval schema / scorer / extractor / report / CLI 全覆盖；standards_platform 全套 **326 passed, 1 skipped**。

> 这是一阶段评测底座：已具备 deterministic scoring 和报告门禁；后续仍需补 50 条款人工 gold set 与真实业务集成评测。

---

## v25.2 — Standards Platform Wave 8 (已完成, 2026-06-01)

- [x] **`to_data_model` 派生策略** — 每个 std_document_version 派生一份 CDM/LDM/PDM 三层模型 + PostgreSQL DDL（migration 085 + `std_data_model_snapshot` 表）；data_model_renderer 纯函数模块，类型映射含 enum CHECK / regex CHECK / range BETWEEN / GEOMETRY(SRID) + GIST / NOT NULL；**派生覆盖率 5/6 → 6/6 (100%)**
- [x] **三层渲染器** — `data_model_renderer.py` 416 行：`build_model()` IR + `render_cdm/ldm/pdm/ddl()`；纯函数无 DB 调用；CDM 屏蔽技术细节、LDM 加 logical_type、PDM 含 PG 物理类型；DEFAULT_CODE_LENGTH / DEFAULT_GEOMETRY_SRID 模块常量便于未来扩展
- [x] **3 个读取 REST 端点** — `GET /api/std/data-model/{vid}`（完整 payload，可 `?layer=cdm\|ldm\|pdm\|ddl`） + `GET /api/std/data-model/{vid}/ddl`（text/plain，Content-Disposition .sql 下载） + `GET /api/std/data-model/{vid}/snapshots`（历史列表）；任何已登录角色可读；写入复用 `/api/std/derive/rerun/{vid}`
- [x] **rollback 联动** — `link_repo._TARGET_DERIVED_STATUS_TABLES` 纳入 std_data_model_snapshot；`rollback_version()` 自动 flip snapshot.derived_status='stale'，无需 strategy 特殊处理；manual snapshot 行永不被动
- [x] **前端预览 modal** — `DataModelPreviewModal.tsx`：4 tab（PDM JSON / DDL 含「复制」+「下载 .sql」/ LDM JSON / CDM JSON）；`DeriveSubTab.tsx` 增加「📐 查看数据模型」按钮；4 个 SDK 函数加入 `standardsApi.ts`
- [x] **测试 +46** — test_migration_085 (8) + test_data_model_renderer (16) + test_data_model_strategy (11) + test_api_data_model (11)；standards_platform 全套 310 passed (vs Wave 7 264)

> 6 commits + spec/plan/roadmap：`db2f6c2..` HEAD。Spec：`docs/superpowers/specs/2026-06-01-std-platform-wave8-data-model-design.md`。

---

## v25.1 — Standards Platform Wave 7 (已完成, 2026-05-30)

- [x] **`to_qc_rule` 派生策略** — 标准 data_element → `agent_quality_rules` 单向派生（migration 083）；mandatory→completeness、enum/range/pattern→field_check；覆盖率 50%→66% (4/6)
- [x] **`to_defect_taxonomy` 派生策略** — 标准 data_element → `agent_defect_code_bindings` 单向派生（migration 084）；mandatory→MIS-001、enum/range→NRM-003、pattern→NRM-002；覆盖率 66%→83% (5/6)
- [x] **派生回滚** — `link_repo.rollback_version()` + `POST /api/std/derive/rollback/{vid}` admin-only；active 链 → superseded、下游 derived_status → stale、manual 行不动
- [x] **影响图谱** — `link_repo.impact_graph()` + `GET /api/std/impact/{kind}/{id}` 4 种 source kind（clause/data_element/term/value_domain）；clause 自动展开到子 element/term/value_domain
- [x] **Wave 6-eval first slice** — 派生质量评测底座：统一 eval item schema、active 派生预测抽取、overall/per-strategy P/R/F1、JSON/Markdown 报告与 CLI；50 条款人工 gold set 继续保留为后续数据工作。

---

## v25.x — Standards Platform 后续阶段 (规划)

> **NDP 归属**：已完成能力作为 NDP-0 Governance Authority/Domain Pack 与 NDP-1 Trusted Data Product 的标准权威基础保留；剩余工作只有在直接支撑四契约族、双试点或阶段退出门时才进入实施，不再独立扩张版本线。

- **P4**：审定流模板可视化、批量回滚、跨标准影响图谱（first slice 全部完成，v25.4-v25.7）
- **P5**：标准市场（目录 + diff first slice、订阅持久化 first slice、市场审核 first slice、组织访问 first slice 已完成，后续补 diff 深化）

---

## 历史 — v24.1 (NL2SQL Benchmark 16/16 + DeepSeek 兼容 + CostGuard 前端配置)

> **主题**: NL2SQL 从"需要英文表名"到"纯自然语言查询"，benchmark 全量通过

### NL2SQL 增强
- [x] **Benchmark v2 去英文表名** — 16 题 question 全部改为纯中文自然语言，不再包含英文表名
- [x] **双向子串匹配** — `_match_aliases()` 支持 alias→text 和 text→alias 双向匹配
- [x] **中文同义词补齐** — 12 张 cq_* 表的 `agent_semantic_sources.synonyms` 全部补充短别名
- [x] **可复用空间 few-shot** — 2 条 canonical pattern (AOI 距离 + 面面相交聚合) 入库 `agent_reference_queries`
- [x] **智能 few-shot 跳过** — 简单单表查询不再触发 embedding 检索，grounding 提速 5-8x
- [x] **SRID 修复** — `cq_ghfw` 和 `cq_jsydgzq` 从 SRID=0 更新为 4523，同步 `agent_semantic_sources`
- [x] **Golden SQL 优化** — MEDIUM_02 空间 join 从 219s→0.5s（转换小表 + GiST 索引命中）
- [x] **Grounding 单位标注** — 列 unit 字段显示在 grounding prompt 中（如"万人"）
- [x] **Grounding SRID 建议** — SRID 不一致时给出具体 Transform 目标 SRID
- [x] **Benchmark 题目修正** — EASY_01 去歧义、EASY_03 改措辞、HARD_03 重写 golden SQL
- [x] **SQL 语法修复** — `reference_queries.py` 的 `:tags::jsonb` 改为 `CAST(:tags AS jsonb)`

### DeepSeek 兼容
- [x] **CoT 泄露清理** — 后端缓冲 sub_agent_direct 输出 + `clean_cot_leakage()` 正则清理
- [x] **前端显示层兜底** — `ChatPanel.tsx` 的 `cleanCotLeakage()` 对 assistant 消息做最终清理
- [x] **标准拒绝格式** — 写操作拒绝和不存在字段拒绝统一为一句标准文案
- [x] **LIMIT 硬规则** — NL2SQL prompt 强制所有 SELECT 必须包含 LIMIT

### CostGuard 前端配置
- [x] **AdminDashboard 成本控制 tab** — 3 个输入框（警告阈值/中止阈值/USD 上限）+ 保存
- [x] **REST API** — `GET/PUT /api/admin/cost-guard-config`（admin only）
- [x] **DB 持久化** — 复用 `agent_model_config` 表，`ModelConfigManager` 扩展 3 个 cost_guard key
- [x] **CostGuardPlugin 读 DB** — 优先从 DB 读取阈值，DB 不可用时降级到 env var

---

## 历史计划输入 — v24.2 STAC 客户端标准化 + 遥感数据源扩展（已撤销版本承诺）

> **状态**：原独立版本计划已撤销。以下条目保留为需求池，其中数据产品发布与消费能力归入 NDP-1，联邦检索和生态互操作能力归入 NDP-4。
>
> **主题**: 把 v13.0 埋下的 STAC 基础设施升级为生产级国际标准对接能力
>
> **背景**: `connectors/stac.py` + `satellite_presets.yaml` + `satellite-imagery` Skill 已经在 v13.0 落地，但实现是裸 httpx、缺 CQL2 / 分页 / 扩展校验，且 Skill 文档里写的 `stac_search` 工具侧一直没对齐。此版本把既有资产补齐到生产级，并为 v25.0 数据产品化和 v27.0 Agent 互操作打地基。
>
> **动因**: STAC 1.1.0（2024-09）是 NASA / Microsoft Planetary Computer / AWS Open Data / Planet / Maxar / USGS / GEE / Esri 全部原生支持的地理数据资产事实标准；继续用方言对外叙事会削弱国际化和"跨系统互操作"定位
>
> **工作量估算**: 1 周 | **依赖**: 无（pystac-client 纯 PyPI）
>
> **Data Agent Level**: 不变（L3.5），仅技术栈标准化

### P0 — 连接器标准化
- [ ] **pystac-client 重构 StacConnector** — `connectors/stac.py` 用 pystac-client 替换裸 httpx，获得 CQL2 filter / 分页 / 扩展字段校验，目标代码 ~100 行 → ~30 行
- [ ] **超时 + 代理配置** — 适配国内网络访问 ESA / AWS STAC 端点，对接 `data_agent/.env` 代理设置
- [ ] **回归测试** — `test_connectors.py` 补 STAC 单元测试，mock pystac-client Client，覆盖 search / collections / 超时

### P0 — 工具侧对齐
- [ ] **stac_search 工具** — 新增到 `toolsets/rs_toolset.py`（或现有 RemoteSensingToolset），参数 `bbox / datetime / cloud_cover / collection / limit`，对齐 `satellite-imagery` Skill 文档契约
- [ ] **stac_list_collections 工具** — 列出指定 STAC 端点的 collection 目录，便于 Agent 自主发现可用数据源
- [ ] **Agent 注入** — 遥感 Agent + General Pipeline 挂载新工具

### P0 — 预设扩展
- [ ] **Microsoft Planetary Computer 预设** — 免认证全球覆盖，端点 `https://planetarycomputer.microsoft.com/api/stac/v1`，加入 `satellite_presets.yaml`
- [ ] **NAIP 预设** — 美国高分辨率航空影像（可选，视客户需求）
- [ ] **LULC 预设迁移** — 现有 `esri_lulc_10m` 是 `source_type: custom`，若有可用 STAC 端点则迁到 STAC 协议

### P1 — 地图渲染直连
- [ ] **STAC → Titiler 瓦片链路** — 搜到 COG `data_href` 后通过 Titiler 生成 XYZ 瓦片 URL，MapPanel 直接添加为 raster layer，不必下载
- [ ] **MapPanel STAC layer 类型** — 新增 layer kind `stac_cog`，支持波段选择 / colormap / rescale 参数
- [ ] **前端 STAC 搜索面板** — DataPanel 增加 "STAC" Tab（可放 v25.0，若 v24.2 时间不够则延后）

### P2 — 华能演示联动（可选增强，不强绑定）
- [ ] **场站影像时序监测辅助场景** — 用 Planetary Computer Sentinel-2/Sentinel-1 查询华能风电场站周边影像，作为演示的加分项（主线仍是 SCADA + RL/MARL，见 `华能新能源_行动计划.md`）

### 质量保障
- [ ] **对标 STAC 1.1.0 规范** — 连接器字段映射对照 STAC spec 文档
- [ ] **pystac-client 版本锁定** — `requirements.txt` 追加 `pystac-client>=0.7.0`
- [ ] **文档更新** — `satellite-imagery` SKILL.md 工具表补 `stac_search` / `stac_list_collections`

---

## v25.x — 数据标准全生命周期智能化平台 (Standards Platform)

### P0 (本期落地)：采集 + 分析底座 — 16 张 std_* 表 + Outbox 独立 worker
  + ltree + pgvector(768) + 12 个 REST + StandardsTab 两个 sub-tab。
  Spec: `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
- **P1**：起草（TipTap + 引用助手 + 一致性校验）+ StandardsEditorAgent (Agent #7)
- **P2**：审定 + 发布 + 派生（6 strategy；标准 → semantic_hints / value_semantics
  / synonyms / qc_rules / defect_taxonomy 单向派生）
- **P3**：to_data_model — CDM/LDM/PDM 三层 + DDL + 反向 XMI（替代 EA 工作流）
- **P4**：审定流模板可视化、批量回滚、跨标准影响图谱（first slice 全部完成，v25.4-v25.7）

---

## 已完成 (v12.2)

- [x] 能力浏览 Tab (CapabilitiesView) — 内置技能/自定义技能/工具集/用户工具聚合展示
- [x] Custom Skills 前端 CRUD — 创建/编辑/删除自定义 Agent
- [x] User-Defined Tools Phase 1 — 声明式工具模板 (http_call / sql_query / file_transform / chain)
- [x] UserToolset — 用户工具暴露给 ADK Agent
- [x] 多 Agent Pipeline 编排 — WorkflowEditor 支持 Skill Agent 节点 + DAG 执行
- [x] 面板拖拽调整宽度 (240-700px)
- [x] DataPanel Tab 横向滚动
- [x] SEC-1~3: DB 降级后门移除、暴力破解防护、SQL 注入 Guardrail
- [x] Skill Bundles 前端 UI — bundle 列表、创建/编辑表单、toolset/skill 多选
- [x] Knowledge Base GraphRAG UI — 图构建按钮、实体列表、图谱搜索
- [x] User Tools Phase 2: Python 沙箱 — AST 验证 + subprocess 隔离 + 环境清洗
- [x] S-2: 线程安全 — _mcp_started / _a2a_started_at 双检锁
- [x] F-2: 全局回调移除 — window.__* → CustomEvent
- [x] SEC-4: Prompt 注入增强 — 24 模式 + 安全边界包裹
- [x] WorkflowEditor 实时执行状态 — 轮询 run status + per-node 状态面板
- [x] ADK list_skills_in_dir 采用 — 替代手动 YAML 解析
- [x] S-4 API 拆分 — api/helpers + bundle_routes + kb_routes + mcp_routes + workflow_routes + skills_routes (42%)
- [x] 启动缺表修复 — workflow_templates + skill_bundles 表初始化
- [x] BP-3 分析血缘自动记录 — pipeline_run_id ContextVar + tool_params 传递 + KG derives_from/feeds_into 边
- [x] 血缘 DAG 可视化 — DataPanel 资产详情横向 DAG 布局 (SVG 箭头 + 类型徽章)
- [x] BP-5 行业分析模板 (首批) — 城市热岛效应/植被变化检测/土地利用优化 3 个模板
- [x] CapabilitiesView 行业分组 — 行业模板过滤器 + /api/templates 集成
- [x] Cartographic Precision UI — Space Grotesk + Teal/Amber + Stone 暖白 + 等高线登录页

---

## 已完成 (v13.0) — 虚拟数据层

> 从"9 个静态资产"到"按需连接多源数据"（参照 SeerAI Entanglement Engine）

- [x] **BP-1 VirtualDataSource 注册表** — `virtual_sources.py`: CRUD + Fernet 加密，支持 `wfs` / `stac` / `ogc_api` / `custom_api` 四种源类型，零复制按需查询
- [x] **WFS/STAC/OGC API 连接器** — 4 个 async 连接器 (`query_wfs`, `search_stac`, `query_ogc_api`, `query_api`)，支持 bbox + CQL 空间过滤
- [x] **查询时 CRS 自动对齐** — 连接器返回 GeoDataFrame 后自动 `to_crs(target_crs)`
- [x] **Schema 基础映射** — `apply_schema_mapping()` 列名重映射（语义匹配 fallback 进行中）
- [x] **连接器健康监控** — `check_source_health()` 端点连通性检测 + DataPanel 健康状态指示灯
- [x] **VirtualSourceToolset** — 5 个 ADK 工具，挂载到 General + Planner pipeline (24 toolsets)
- [x] **REST API** — 6 个端点 `/api/virtual-sources/*` (101 total endpoints)
- [x] **前端 "数据源" Tab** — VirtualSourcesView: 列表/新增/编辑/删除/测试连接 UI
- [x] **52 单元测试** — CRUD、加密、连接器、调度器、健康检查全覆盖

---

## v13.0.1 — Schema 语义映射 (已完成)

> 基于向量嵌入的字段名自动映射

- [x] **语义匹配 fallback** — 当 `schema_mapping` 为空时，用 `text-embedding-004` 对远程列名和规范词汇表做余弦相似度匹配
- [x] **规范词汇表** — 35 个地理空间常用字段语义 (geometry, population, area, elevation, land_use, ...)

---

## v13.1 — MCP Server 高阶工具暴露 (已完成)

> 让外部 Agent（Claude Desktop / GPT）通过 MCP 调用 GIS Data Agent 的分析能力（参照 SeerAI MCP Server 设计）

- [x] **BP-4 高阶元数据工具** — 新增 6 个 MCP 工具：`search_catalog`（语义搜索数据目录）、`get_data_lineage`（血缘追踪）、`list_skills`（技能列出）、`list_toolsets`（工具集列出）、`list_virtual_sources`（虚拟数据源）、`run_analysis_pipeline`（执行完整分析管线）
- [x] **MCP Server v2.0** — 从 30+ 底层 GIS 工具扩展为 36+ 工具（底层 + 高阶元数据 + pipeline 执行）
- [x] **外部 Agent 接入验证** — MCP routes + A2A server 集成测试 ✅

---

## 已完成 (v14.0) — 交互增强 + 扩展市场

> **主题**: 用户可见的体验提升，快速出价值

### 自然语言交互
- [x] **意图消歧对话** — AMBIGUOUS 分类时弹出选择卡片（Optimization/Governance/General），用户点选后路由
- [x] **参数调整重跑** — rerun_with_params action + session 参数存储 ✅ v14.5
- [x] **记忆搜索面板** — MemorySearchTab + /api/memory/search ✅ v14.5

### 用户自扩展
- [x] **Marketplace 画廊** — DataPanel 新增"市场"tab，聚合所有 is_shared=true 的 Skills/Tools/Templates/Bundles，支持排序（评分/使用量/时间）
- [x] **统一评分系统** — Skills 和 Tools 增加 `rating_sum`/`rating_count` 字段 + REST 端点 `POST /api/skills/{id}/rate`、`POST /api/user-tools/{id}/rate`
- [x] **Skill/Tool Clone** — 允许用户克隆他人共享的 Skill/Tool 到自己名下

### DRL 优化
- [x] **场景模板系统** — 定义 `DRLScenario` 配置类，内置 3 个场景模板：耕地优化（现有）、城市绿地布局、设施选址
- [x] **奖励权重 UI** — 前端 slope_weight / contiguity_weight / balance_weight 滑块 ✅

### 三面板 SPA
- [x] **热力图支持** — 集成 deck.gl `HeatmapLayer` 到 Map3DView，MapPanel 增加 `type: heatmap` 处理
- [x] **测量工具** — MapPanel 工具栏增加距离测量 + 面积测量（Leaflet.Draw 或 Turf.js）
- [x] **3D 图层控制** — Map3DView 增加图层列表面板，支持 show/hide/opacity 调节

### 多 Agent 编排
- [x] **Workflow 断点续跑** — resume_workflow_dag + /runs/{id}/resume ✅ v14.5
- [x] **步骤级重试** — retry_workflow_node + REST 端点 ✅ v14.5

---

## 已完成 (v14.1) — 智能深化 + 协作基础

> **主题**: AI 更聪明，协作开始落地

### 自然语言交互
- [x] **追问与上下文链** — Agent 输出后自动生成 3 个推荐追问，用户点击即发送
- [x] **分析意图消歧 v2** — 对复杂查询拆解为子任务列表，用户确认后按序执行 ✅ v23.0
- [x] **自动记忆提取增强** — pipeline 完成后自动调用 `extract_facts_from_conversation()` + 弹出确认 ✅

### 用户自扩展
- [x] **版本管理** — Skills/Tools 新增 `version` 字段，更新时自动 +1，保留最近 10 个版本，支持回滚
- [x] **标签分类** — category + tags[] 列 + migration 035 ✅ v15.0
- [x] **使用统计** — use_count 列 + increment_skill_use_count ✅ v15.0

### DRL 优化
- [x] **多场景环境引擎** — LandUseOptEnv 配置驱动多场景支持 ✅
- [x] **约束建模** — 新增硬约束（保留率下限）+ 软约束（预算/面积上限），Gymnasium action mask 扩展 ✅ v23.0
- [x] **结果对比面板** — OptimizationTab A/B 对比两次优化结果 ✅

### 三面板 SPA
- [x] **3D basemap 同步** — Map3DView 高德/天地图 MapLibre 栅格源 ✅ v14.5
- [x] **标注协同** — WebSocket 实时推送标注变更 (单实例版) ✅ v23.0
- [x] **GeoJSON 编辑器** — DataPanel 新增 tab/modal，支持粘贴/编辑 GeoJSON + 预览到地图
- [x] **跨图层关联** — 选中 A 图层要素时高亮 B 图层空间关联要素 ✅ v23.0

### 多 Agent 编排
- [x] **Agent 注册中心** — 新增 `agent_registry.py`：注册/发现/心跳，Redis 或 PostgreSQL 后端
- [x] **A2A 双向 RPC** — 扩展 `a2a_server.py` 支持主动调用远程 Agent
- [x] **消息总线持久化** — `AgentMessageBus` PostgreSQL 持久化 + 投递确认 ✅

---

## 已完成 (v14.2) — 深度智能 + 生产就绪

> **主题**: DRL 专业化，系统可投产

### 自然语言交互
- [x] **多轮分析工作流** — 支持"分析链"：用户定义条件触发后续分析
- [x] **语音输入** — 集成语音转文字（浏览器 SpeechRecognition）✅

### 用户自扩展
- [x] **Skill Marketplace 社区** — MarketplaceTab Gallery + 排序 + 热度排行 ✅
- [x] **审批工作流** — 管理员审核 is_shared Skill 的发布请求

### DRL 优化
- [x] **自定义训练 API** — train_drl_model 工具暴露 ✅
- [x] **可解释性模块** — 特征重要性分析 ✅ *(SHAP 集成待 GPU 环境)*
- [x] **时序动画** — DRL 优化过程 GIF 回放 + 前后对比 PNG ✅ 2026-04-08

### 三面板 SPA
- [x] **要素绘制编辑** — Leaflet.Draw 点/线/面/矩形 + 导出 GeoJSON ✅ v14.5
- [x] **标注导出** — 标注集导出为 GeoJSON / CSV
- [x] **自适应布局** — 移动端响应式 ✅

### 多 Agent 编排
- [x] **分布式任务队列** — TaskQueue Redis Sorted Set 后端 (替代 Celery) ✅ 2026-04-08
- [x] **Pipeline 断点恢复 v2** — workflow_engine.py checkpoint/resume 逻辑 ✅
- [x] **Circuit Breaker** — 工具/Agent 连续失败时熔断，自动降级到备选 Agent

---

## 已完成 (v14.3) — 联邦多 Agent + 生态开放

> **主题**: 从单机走向分布式，从工具走向平台

### 自然语言交互
- [ ] **个性化模型微调** — 根据用户历史分析偏好微调 Agent 行为（LoRA adapter on Gemini）
- [x] **多语言支持** — 英文/日文 prompt 自动检测 + 路由到对应语言 Agent

### 用户自扩展
- [x] **Skill 依赖图** — 允许 Skill A 依赖 Skill B（DAG 编排），拓扑排序 + 循环检测 + REST API ✅ v23.0
- [x] **Webhook 集成** — 第三方平台 Skill 注册（GitHub Action、Zapier trigger）
- [x] **Skill SDK** — gis-skill-sdk Python 包 (CLI + 验证器 + 测试) ✅

### DRL 优化
- [x] **多目标优化 v2** — NSGA-II 替代加权和方法，真 Pareto 前沿搜索
- [x] **交通网络/设施布局场景** — 新增 2 个 Gymnasium 环境（路网优化、公共设施选址） ✅ v23.0
- [ ] **联邦学习** — 多租户共享模型权重但不共享数据（隐私保护 DRL）

### 三面板 SPA
- [ ] **协同工作空间** — 多用户同时编辑同一项目（CRDT 冲突解决）
- [x] **插件系统** — 允许用户开发自定义 DataPanel tab 插件
- [x] **离线模式** — Service Worker 缓存基础地图 + 已下载数据集 ✅ v23.0

### 多 Agent 编排
- [x] **完整 A2A 协议** — 实现 Google A2A spec：Agent Card、Task lifecycle、Streaming、Push Notification
- [x] **跨实例 Agent 协作** — Agent A (本机) 调用 Agent B (远程) 的工具，结果回传
- [ ] **Agent 联邦** — 多个 GIS Data Agent 实例组成联邦，共享 Skill 注册表 + 负载均衡

---

## 已完成 (v14.4) — 治理深化 + 交互式可视化

> **主题**: 治理管道从 40% → 65%，非 GIS 数据的交互式图表从 0 → 可用
>
> **依据**: `docs/governance-capability-assessment.md` (6 领域 22 子能力评估)、`docs/data-source-connector-assessment.md` (5 通道缺口分析)、dv.gaozhijun.me (数据可视化参考)

### 数据治理管道强化
- [x] **Ch21 审计修复** — P0/P1/P2 全部清零 (A2A 认证、SQL 参数化、线程安全 6 处) ✅ 2026-03-21
- [x] **DataPanel 拆分重构** — 2922 行 → 17 模块化组件 + 分组 Tab (数据/智能/运维/编排) ✅ 2026-03-21
- [x] **GovernanceToolset (7 工具)** — `check_gaps` / `check_completeness` / `check_attribute_range` / `check_duplicates` / `check_crs_consistency` / `governance_score` / `governance_summary` ✅ 2026-03-21
- [x] **治理评分体系** — 6 维加权评分 (拓扑 25% / 间隙 15% / 完整性 20% / 属性 15% / 重复 10% / CRS 15%)，0-100 综合分 + 雷达图 JSON ✅ 2026-03-21
- [x] **治理 Prompt 独立化** — `prompts/governance.yaml` 5 个治理专用 prompt ✅ 2026-03-21
- [x] **GovernanceViz Agent** — 治理管道第 4 阶段：审计结果可视化 ✅ 2026-03-21

### 交互式数据可视化
- [x] **ChartToolset (9 工具)** — bar/line/pie/scatter/histogram/box_plot/heatmap/treemap/radar → ECharts JSON config ✅ 2026-03-21
- [x] **前端 ECharts 集成** — ChartView 通用渲染组件 + DataPanel ChartsTab ✅ 2026-03-21
- [x] **图表交付管道** — `/api/chart/pending` REST 端点 + `app.py` 图表检测 ✅ 2026-03-21
- [x] **Prompt 图表感知** — `general_viz_instruction` 增加非地图可视化指引 ✅ 2026-03-21

### 质量保障
- [x] **治理工具测试** — `test_governance_tools.py` 7 工具 mock 测试 + 评分逻辑验证 ✅ 2026-03-21
- [x] **图表工具测试** — `test_chart_tools.py` 9 工具 ECharts option schema 验证 ✅ 2026-03-21

---

## 已完成 (v14.5) — 全栈治理升级 + 连接器插件化 + Skill 5 模式 + 可观测性

> **主题**: 数据接入补齐短板，标准驱动治理引擎，Skill 设计模式从单一 Tool Wrapper 走向 5 模式全覆盖
>
> **依据**: `docs/agent-observability-enhancement.md` (Phase 1 指标增强)、`docs/data-source-connector-assessment.md` (S1 阶段)、`docs/data-agent-readiness-assessment.md` (客户 Demo 差距评估)、`docs/skill-design-patterns-analysis.md` (5 种 Skill 设计模式)

### 数据接入增强 + 连接器插件化 *(v15.0 插件化提前完成)*
- [x] **BaseConnector 插件架构** — `connectors/__init__.py`: BaseConnector ABC + ConnectorRegistry 注册表，替代 virtual_sources.py 内联 if-elif 分派 ✅ 2026-03-22
- [x] **现有 4 种连接器重构** — WFS/STAC/OGC API/Custom API 从 virtual_sources.py 提取为独立 Connector 子类 ✅ 2026-03-22
- [x] **WMS/WMTS 连接器** — `connectors/wms.py`: GetCapabilities XML 解析 + 返回 `L.TileLayer.WMS` ���层配置 (非像素下载) ✅ 2026-03-22
- [x] **ArcGIS REST FeatureServer 连接器** — `connectors/arcgis_rest.py`: 分页查询 + f=geojson + BBOX，返回 GeoDataFrame ✅ 2026-03-22
- [x] **前端 WMS 图层渲染** — MapPanel 新增 `'wms'` 图层类型 + `L.tileLayer.wms()` 渲染 ✅ 2026-03-22
- [x] **类型专属表单** — VirtualSourcesTab: WMS (layers/styles/format/version) + ArcGIS (layer_id/where/fields) 专属配置表单 ✅ 2026-03-22
- [x] **图层发现** — `POST /api/virtual-sources/discover` 端点 + 前端"发现图层"按钮 (GetCapabilities 代理) ✅ 2026-03-22
- [x] **Toolset 增强** — VirtualSourceToolset 5→7 工具: 新增 `discover_layers_tool` + `add_wms_layer_tool` ✅ 2026-03-22
- [x] **22 连接器测试** — `test_connectors.py`: Registry + 6 连接器 + auth headers 全覆盖 ✅ 2026-03-22
- [x] **Esri File Geodatabase (.gdb) 支持** — `_load_spatial_data()` 增加 FGDB 读取分支 + 图层列表枚举 ✅ 2026-03-22
- [x] **DWG/DXF 元数据读取** — ezdxf 解析 DXF 图层/实体 (POINT/LINE/POLYLINE)，DWG 提示转换 ✅ 2026-03-22
- [x] **数据源注册向导** — 4 步向导 UI (基本信息→CRS/刷新→类型配置→预览确认) ✅ 2026-03-22
- [x] **字段映射可视化编辑器** — FieldMappingEditor 拖拽映射组件 ✅

### 数据标准与治理引擎 *(全部完成)*
- [x] **Data Standard Registry** — YAML 标准定义 + GB/T 21010 (73 值) + DLTB (30 字段 + 4 代码表) ✅ 2026-03-22
- [x] **DataCleaningToolset** — 7 清洗工具 (空值填充/编码映射/字段重命名/类型转换/异常值/CRS/补齐) ✅ 2026-03-22
- [x] **地类编码交叉映射** — CLCD→GB/T 21010 映射表 + map_field_codes 支持 mapping_id ✅ 2026-03-22
- [x] **Gap Matrix 自动生成** — 逐字段标准对比 (present/missing/extra) + 必填覆盖率 ✅ 2026-03-22
- [x] **批量数据集探查** — 目录递归扫描 + 可选标准对照 + 汇总统计 ✅ 2026-03-22
- [x] **标准感知质检规则** — M/C/O 必填/max_length/类型兼容/枚举/公式校验/合规率评分 ✅ 2026-03-22
- [x] **质量规则库 CRUD** — DB 持久化 + 批量执行 + 趋势记录 + REST API 8 端点 ✅ 2026-03-22
- [x] **治理流程模板化** — generate_governance_plan 自动诊断→生成可执行治理步骤 ✅ 2026-03-22

### Skill 设计模式升级 *(全部完成)*
- [x] **Inversion 模式: site-selection** — 4 阶段采访 + 执行门控 (v3.0) ✅ 2026-03-22
- [x] **Inversion 模式: land-fragmentation** — 4 阶段采访 + DRL 参数确认 (v3.0) ✅ 2026-03-22
- [x] **Generator 模式: data-profiling** — assets/ 报告模板 + references/ 评分标准 (v3.0) ✅ 2026-03-22
- [x] **Generator 模式: ecological-assessment** — assets/ 生态评估模板 ✅ 2026-03-22
- [x] **Reviewer 模式: farmland-compliance** — 检查清单提取到 references/ (v3.0) ✅ 2026-03-22
- [x] **Skill L3 参考文档补全** — +5 skills (geocoding/buffer-overlay/3d-viz/data-import-export/site-selection) ✅ 2026-03-22

### Agent 可观测性 Phase 1 *(全部完成)*
- [x] **Prometheus 指标扩展 (4→25+)** — LLM/Tool/Pipeline/Cache/HTTP/CB 6 层 ✅ 2026-03-22
- [x] **ObservabilityMiddleware** — ASGI HTTP 中间件 + path 归一化 ✅ 2026-03-22
- [x] **缓存命中率指标** — semantic_layer hit/miss Counter ✅ 2026-03-22
- [x] **Grafana Dashboard 模板** — grafana/agent_overview.json 11 面板 ✅ 2026-03-22

### 治理运营 *(全部完成)*
- [x] **质量规则库 + 趋势 + 总览** — agent_quality_rules/trends 表 + 8 REST 端点 + GovernanceTab ✅ 2026-03-22

### 交互体验打磨 *(全部完成)*
- [x] **参数调整重跑** — last_pipeline_params session 存储 + rerun_with_params action ✅ 2026-03-22
- [x] **记忆搜索面板** — /api/memory/search + MemorySearchTab + DataPanel "记忆" tab ✅ 2026-03-22
- [x] **3D basemap 同步** — Map3DView 扩展高德/天地图 MapLibre 栅格源样式 ✅ 2026-03-22
- [x] **要素绘制编辑** — Leaflet.Draw 点/线/面 + 导出 GeoJSON + /api/user/drawn-features ✅ 2026-03-22

### 多 Agent 编排 *(全部完成)*
- [x] **Workflow 断点续跑** — resume_workflow_dag() + POST /runs/{id}/resume 端点 ✅ 2026-03-22
- [x] **步骤级重试** — retry_workflow_node() 已有，REST 端点已暴露 ✅ 2026-03-22

---

## 已完成 (v15.0) — 深度可观测 + 数据安全 + 分布式计算

> **主题**: OpenTelemetry 分布式追踪、Agent 决策透明化、安全合规、数据分发与反馈闭环
>
> **依据**: 可观测性文档 Phase 2-4 + 治理评估 §4 数据安全 + 数据源评估 S2 + Spark 架构文档 + readiness 评估 P2 项 + skill-design-patterns P2 项

### Agent 可观测性 Phase 2-4 *(全部完成)*
- [x] **OpenTelemetry 分布式追踪** — `otel_tracing.py`: Pipeline/Agent/Tool 三级 Span + OTLP 导出 ✅ 2026-03-22
- [x] **Agent 决策追踪** — `agent_decision_tracer.py`: DecisionEvent/DecisionTrace + Mermaid 序列图 ✅ 2026-03-22
- [x] **Pipeline 执行瀑布图** — ObservabilityTab 决策时间线 + 事件颜色编码 ✅ 2026-03-22
- [x] **Prometheus Alert 规则** — 9 条告警 (Pipeline/LLM/Tool/CB/Token/Cache/HTTP + 安全) ✅ 2026-03-22

### 数据安全 *(全部完成)*
- [x] **数据分类分级引擎** — PII 检测 (6 模式) + 5 级敏感度 + classify_data_sensitivity 工具 ✅ 2026-03-22
- [x] **数据脱敏工具** — 4 策略 (mask/redact/hash/generalize) + mask_sensitive_fields 工具 ✅ 2026-03-22
- [x] **RLS 实际落地** — 8 核心表 Row Level Security 策略 (owner/shared/admin) ✅ 2026-03-22
- [x] **安全事件告警** — SensitiveDataAccessSpike + BruteForceDetected ✅ 2026-03-22

### 数据分发与反馈闭环 *(全部完成)*
- [x] **数据申请审批流程** — create/approve/reject + 角色过滤 ✅ 2026-03-22
- [x] **数据分发包打包下载** — package_assets ZIP 打包 ✅ 2026-03-22
- [x] **用户反馈通道** — add_review (1-5 评分 + 评论) + get_reviews ✅ 2026-03-22
- [x] **使用热度统计** — log_access + get_hot_assets + access_stats ✅ 2026-03-22

### 数据更新与版本管理 *(全部完成)*
- [x] **增量更新机制** — compare_datasets 差异对比 (要素/列/CRS) ✅ 2026-03-22
- [x] **数据版本管理** — create_version_snapshot + rollback_version + list_versions ✅ 2026-03-22
- [x] **更新日志与通知** — notify_asset_update + get_notifications + mark_read ✅ 2026-03-22

### 连接器扩展 *(全部完成)*
- [x] **BaseConnector 抽象基类** — ConnectorRegistry *(v14.5 提前完成)*
- [x] **DatabaseConnector** — MySQL/PostgreSQL/SQLite 外部数据库连接 ✅ 2026-03-22
- [x] **ObjectStorageConnector** — S3/OBS/OSS 对象存储拉取 ✅ 2026-03-22

### Skill 设计模式深化 *(核心完成)*
- [x] **Pipeline 模式: multi-source-fusion** — 5 步检查点融合 (v3.0) ✅ 2026-03-22
- [x] **新增 data-quality-reviewer Skill** — 入库前 13 项质量审查 ✅ 2026-03-22
- [x] **数据模型推荐引擎** — recommend_data_model 工具 (差距分析+转换路径+工作量评估) ✅ 2026-03-22
- [x] **Generator/Reviewer 输出结构化校验** — Pydantic schema ✅

### 分布式计算 *(全部完成)*
- [x] **SparkToolset (3 工具)** — submit_task + check_tier + list_jobs ✅ 2026-03-22
- [x] **SparkGateway 网关** — 多后端抽象 (local/Livy/Dataproc/EMR) ✅ 2026-03-22
- [x] **三层执行路由** — L1 本地(<100MB) / L2 队列(<1GB) / L3 Spark(>1GB) ✅ 2026-03-22

---

## 已完成 (v15.2) — 地理空间世界模型 + NL2SQL + 地图时间轴

> **主题**: 从"分析已有数据"到"预测未来演变"——构建地理空间 JEPA 世界模型，自然语言直达数据库
>
> **依据**: `docs/world-model-tech-preview-design.md` (方案 A/B/C/D 评审 + 阶段 0 验证)、`docs/multimodal-semantic-fusion-plus-alphaearth-strategy.md`

### 地理空间世界模型 (Plan D: AlphaEarth + LatentDynamicsNet)
- [x] **LatentDynamicsNet 残差 CNN** — `world_model.py`: 459K 参数, 空洞卷积 (dilation 1/2/4, 170m 感受野), 残差连接 + L2 流形保持 ✅ 2026-03-22
- [x] **AlphaEarth 64 维嵌入集成** — GEE `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` 采集 + zonal 聚合 ✅ 2026-03-22
- [x] **5 种情景模拟** — 城市蔓延 / 生态修复 / 农业集约化 / 气候适应 / 基线趋势，one-hot 编码 ✅ 2026-03-22
- [x] **地形上下文感知** — DEM elevation + slope 作为 CNN 额外通道 ✅ 2026-03-22
- [x] **LULC 解码器** — LogisticRegression: 嵌入 → 9 类 ESRI LULC (准确率 83.7%) ✅ 2026-03-22
- [x] **训练管线** — 15 区域 × 8 年嵌入对 + 多步展开训练损失 + GEE 自动下载 ✅ 2026-03-22
- [x] **WorldModelToolset (5 工具)** — predict / scenarios / status / embedding_coverage / find_similar ✅ 2026-03-22
- [x] **世界模型快捷路径** — 意图分类直判 world_model → 跳过 LLM Planner，1 次 API 调用完成预测 ✅ 2026-03-22
- [x] **阶段 0 验证通过** — 年际 cos_sim=0.953, 变化/稳定分离度=2.44x, 嵌入→LULC 解码 83.7% ✅ 2026-03-22

### pgvector 嵌入缓存
- [x] **embedding_store.py** — `agent_geo_embeddings` 表 + pgvector VECTOR(64) + IVFFlat 索引 ✅ 2026-03-23
- [x] **三级缓存** — pgvector (24ms) → .npy 文件 (ms) → GEE 下载 (seconds)，自动回填 ✅ 2026-03-23
- [x] **余弦相似度搜索** — `find_similar_embeddings()` 支持空间半径 + top-K ✅ 2026-03-23

### NL2SQL 动态数据查询
- [x] **NL2SQLToolset (3 工具)** — discover_database_schema / execute_spatial_query / load_admin_boundary ✅ 2026-03-22
- [x] **Schema 发现** — 自动探索 public schema 表结构 + 列类型 + 注释 ✅ 2026-03-22
- [x] **参数化安全查询** — 自动 LIKE 模糊匹配构造，零 SQL 注入风险 ✅ 2026-03-22
- [x] **行政区划加载** — 自然语言地名 → 模糊匹配 → 自动 SQL → GeoJSON ✅ 2026-03-22

### 地图时间轴 + 底图增强
- [x] **时间轴播放器** — MapPanel 多时序 LULC 图层动画切换 + 年份滑块 ✅ 2026-03-22
- [x] **卫星影像底图** — Gaode Satellite + ESRI World Imagery 底图选项 ✅ 2026-03-22
- [x] **WorldModelTab** — DataPanel 新增世界模型专属 Tab (情景选择/预测/面积趋势表/转移矩阵/堆叠条形图) ✅ 2026-03-22

### 质量保障
- [x] **世界模型测试** — `test_world_model.py` 场景/模型/预测/缓存全覆盖 ✅ 2026-03-22
- [x] **NL2SQL 测试** — `test_nl2sql.py` Schema/Query/AdminBoundary 测试 ✅ 2026-03-22

---

## 已完成 (v15.3) — 三角度时空因果推断体系

> **主题**: 为论文构建三个互补角度的因果推断能力——统计方法 × LLM 推理 × 因果世界模型
>
> **依据**: 项目思想起源 (2023-09) 时空因果推断平台构想

### Angle A — GeoFM 嵌入因果推断 (6 tools)
- [x] **CausalInferenceToolset** — `causal_inference.py` (1247 行): PSM / ERF / DiD / Granger / GCCM / Causal Forest ✅ 2026-03-25
- [x] **AlphaEarth 嵌入增强** — 全部 6 工具支持 `use_geofm_embedding=True`，64 维嵌入作为空间混淆控制 ✅ 2026-03-25
- [x] **空间距离加权匹配** — PSM 支持 `spatial_distance_weight` 空间邻近约束 ✅ 2026-03-25
- [x] **21 测试** — 合成数据 ground truth 验证 (Park-price ATE, Pollution DiD, 灌溉 CATE 等) ✅ 2026-03-25

### Angle B — LLM 因果推理 (4 tools)
- [x] **LLMCausalToolset** — `llm_causal.py` (949 行): Gemini 2.5 Pro/Flash 驱动 ✅ 2026-03-25
- [x] **因果 DAG 构建** — `construct_causal_dag()`: 变量/混淆因子/中介/碰撞因子识别 + networkx 可视化 + Mermaid 图 ✅ 2026-03-25
- [x] **反事实推理** — `counterfactual_reasoning()`: 结构化推理链 + 置信度 + 敏感性因子 ✅ 2026-03-25
- [x] **因果机制解释** — `explain_causal_mechanism()`: 接收 Angle A 统计结果 JSON 自动解读 ✅ 2026-03-25
- [x] **What-If 情景生成** — `generate_what_if_scenarios()`: 自动映射到世界模型情景 + Angle A 参数 ✅ 2026-03-25
- [x] **33 测试** — Gemini mock + JSON 解析 + DAG 渲染 + Mermaid 生成 ✅ 2026-03-25

### Angle C — 因果世界模型 (4 tools)
- [x] **CausalWorldModelToolset** — `causal_world_model.py` (1049 行): 世界模型 + 因果干预 ✅ 2026-03-25
- [x] **空间干预预测** — `intervention_predict()`: 子区域施加干预 + 空间溢出效应分析 ✅ 2026-03-25
- [x] **反事实对比** — `counterfactual_comparison()`: 平行情景 + 逐像素 LULC 差异 + 效应图 ✅ 2026-03-25
- [x] **嵌入空间处理效应** — `embedding_treatment_effect()`: cosine/euclidean/manhattan 距离度量 ✅ 2026-03-25
- [x] **统计先验整合** — `integrate_statistical_prior()`: ATT → 校准世界模型预测偏移 ✅ 2026-03-25
- [x] **28 测试** — 空间 mask + 干预/反事实/嵌入效应/校准 全覆盖 ✅ 2026-03-25

### 集成与前端
- [x] **8 REST API 端点** — `/api/causal/*` (4) + `/api/causal-world-model/*` (4) ✅ 2026-03-25
- [x] **CausalReasoningTab** — DataPanel 新增"因果推理" Tab (DAG/反事实/机制/情景 4 区域) ✅ 2026-03-25
- [x] **WorldModelTab 扩展** — 模式切换 (预测/干预/反事实) + 子区域输入 + 双情景选择 ✅ 2026-03-25
- [x] **Data Catalog 语义搜索** — `/api/catalog/search` + CatalogTab 双搜索模式 + 分页 ✅ 2026-03-25
- [x] **intent_router 扩展** — `causal_reasoning` + `world_model` 子类别增强 ✅ 2026-03-25
- [x] **tool_filter 扩展** — `causal_reasoning` 类别 (4 工具) + `world_model` 类别扩展 (7 工具) ✅ 2026-03-25

---

## 已完成 (v15.5) — 论文修订 + DRL-World Model Dreamer 集成

> **主题**: 学术论文 R2 审稿回复 + DRL 与世界模型深度融合
>
> **依据**: IJGIS 审稿意见 + 因果推断论文投稿准备

### 论文修订
- [x] **World Model 论文 R2 回复** — 审稿人意见逐条回复 + 补充实验 ✅ 2026-03-26
- [x] **因果推断论文** — 三角度因果推断体系论文撰写 (IJGIS 目标) ✅ 2026-03-26

### DRL-World Model 融合
- [x] **DreamerEnv** — 世界模型驱动的 DRL 环境，嵌入空间中训练 ✅ 2026-03-26
- [x] **DreamerToolset** — 梦境训练 + 策略评估 + 情景对比工具 ✅ 2026-03-26

---

## 已完成 (v15.7) — 测绘质检智能体系统

> **主题**: 面向测绘行业的专业质检智能体，覆盖 GB/T 24356 标准全流程
>
> **依据**: `docs/surveying_qc_agent_gap_analysis.md`、`docs/qc_agent_architecture_comparison.md`

### 缺陷分类与标准
- [x] **缺陷分类法** — 30 缺陷编码 / 5 类别 (几何/属性/拓扑/完整性/精度)，对标 GB/T 24356 ✅ 2026-03-27
- [x] **QC 工作流模板** — `qc_workflow_templates.yaml`: 3 套标准流程 (通用/建筑/地形) + SLA 约束 ✅ 2026-03-27

### 治理工具集扩展
- [x] **GovernanceToolset 扩展至 18 工具** — 新增拓扑检查/面积一致性/层高验证/坐标精度等 ✅ 2026-03-27
- [x] **DataCleaningToolset 扩展至 11 工具** — 新增几何修复/拓扑修复/属性标准化/批量清洗 ✅ 2026-03-27
- [x] **PrecisionToolset (5 工具)** — 坐标精度评估/高程精度/面积精度/角度精度/综合精度报告 ✅ 2026-03-27

### QC 运营
- [x] **QC 报告引擎** — 结构化质检报告生成 (缺陷统计/分布图/修复建议) ✅ 2026-03-27
- [x] **告警规则** — 缺陷率阈值告警 + SLA 超时告警 ✅ 2026-03-27
- [x] **案例库** — 历史质检案例存储 + 相似案例检索 ✅ 2026-03-27
- [x] **人工复核工作流** — 机检→人审→终审三级流程 + 复核意见记录 ✅ 2026-03-27

### 4 独立子系统
- [x] **CV 检测子系统** — `subsystems/cv_detection/`: 影像缺陷自动识别 ✅ 2026-03-27
- [x] **CAD/3D 解析子系统** — `subsystems/cad_parser/`: DWG/DXF/BIM 数据解析 ✅ 2026-03-27
- [x] **专业工具 MCP 服务** — `subsystems/mcp_tools/`: 测绘专业工具 MCP 封装 ✅ 2026-03-27
- [x] **参考数据服务** — `subsystems/reference_data/`: 标准参考数据管理 ✅ 2026-03-27

### 前端
- [x] **QcMonitorTab** — 实时质检统计 + 最近审查列表 + 工作流进度 ✅ 2026-03-28
- [x] **WorkflowsTab 增强** — 工作流列表 + 运行历史 + 进度可视化 ✅ 2026-03-28
- [x] **质检 API** — `quality_routes.py` + `workflow_routes.py` REST 端点 ✅ 2026-03-28

---

## 已完成 (v15.8) — BCG 企业智能体平台 + 技术债务清零

> **主题**: 对标 BCG 企业级 Agent 平台 6 大能力模块，同时系统性清理全部技术债务
>
> **依据**: `docs/bcg-enterprise-agents-analysis.md`、`tech_debt.md` 技术债务登记表

### BCG 企业平台能力 (6 模块)
- [x] **Prompt Registry** — 版本化 Prompt 管理 + 环境隔离 (dev/staging/prod) + A/B 测试 ✅ 2026-03-28
- [x] **Model Gateway** — 任务感知路由 (Flash/Pro 自动选择) + 成本追踪 + 场景标注 ✅ 2026-03-28
- [x] **Context Manager** — 可插拔上下文策略 + Token 预算管理 + 上下文压缩 ✅ 2026-03-28
- [x] **Eval Scenario Framework** — 场景化评估框架 + 黄金数据集 + 自动回归测试 ✅ 2026-03-28
- [x] **Token Tracking 增强** — 场景/项目/任务类型维度追踪 + 成本归因 ✅ 2026-03-28
- [x] **Eval History** — 评估历史记录 + 版本间对比 + 趋势分析 ✅ 2026-03-28

### DB 迁移 (045-048)
- [x] **Migration 045** — Prompt Registry 表 (agent_prompt_registry) ✅ 2026-03-28
- [x] **Migration 046** — Model Gateway 扩展 (token_usage 增加 scenario/project_id/task_type) ✅ 2026-03-28
- [x] **Migration 047** — Eval Framework 表 (agent_eval_scenarios + agent_eval_history) ✅ 2026-03-28
- [x] **Migration 048** — 数据资产表统一 (agent_data_catalog → agent_data_assets 兼容 VIEW) ✅ 2026-03-29

### 技术债务清零 (6/6)
- [x] **TD-001 (P1)** — 双数据资产表统一: migration 048 + data_catalog.py 全函数迁移至 agent_data_assets ✅ 2026-03-29
- [x] **TD-002 (P2)** — SQLAlchemy `::jsonb` 类型转换: 改用 `CAST(:param AS jsonb)` ✅ 2026-03-28
- [x] **TD-003 (P2)** — 自动迁移运行器: `migration_runner.py` + schema_migrations 追踪表 ✅ 2026-03-29
- [x] **TD-004 (P2)** — 工作流 Chainlit 上下文丢失: `asyncio.create_task()` → `await` ✅ 2026-03-28
- [x] **TD-005 (P1)** — 工作流步骤上下文隔离: `accumulated_context` 步间结果注入 ✅ 2026-03-29
- [x] **TD-006 (P2)** — 工作流阻塞聊天: Chainlit context_var 传播至 background task ✅ 2026-03-29

### 质量保障
- [x] **test_workflow_context.py** — 工作流上下文注入验证 ✅ 2026-03-29
- [x] **50/50 data_catalog 测试通过** — 表统一后全部测试绿色 ✅ 2026-03-29

---

## 历史遗留未完成项 (v13~v14 积累)

> 以下项目在各版本迭代中被跳过或延期，按优先级分类管理

### 优先完成 (低成本高价值)
- [x] **奖励权重 UI** — DRL 前端 slope/contiguity/balance 滑块 *(v14.0, 前端 ~100 行)* ✅ v15.9
- [x] **字段映射可视化编辑器** — FieldMappingEditor 拖拽映射 ✅
- [x] **MCP 外部 Agent 接入验证** — Claude Desktop / Cursor E2E 测试 *(v13.1)* ✅ v15.9

### 择机完成 (中等价值)
- [x] **分析意图消歧 v2** — 复杂查询拆解子任务列表 *(v14.1)* ✅ v15.9
- [x] **自动记忆提取增强** — pipeline 后 extract_facts + 弹窗确认 *(v14.1)* ✅ v15.9
- [x] **消息总线持久化** — AgentMessageBus → PostgreSQL *(v14.1)* ✅ v15.9
- [x] **自适应布局** — 移动端响应式 ✅
- [x] **Skill SDK 发布** — `gis-skill-sdk` Python 包 *(v14.3)* ✅ v15.9

### 远期/冻结
- [~] **标注协同 (WebSocket)** — 实时协同复杂度高 *(v14.1, 冻结)*
- [~] **跨图层关联高亮** — 选中要素联动 *(v14.1, 冻结)*
- [~] **Skill Marketplace 社区** — 需要公网部署 *(v14.2, 冻结)*
- [~] **DRL 自定义训练 API** — *(v14.2, 冻结)*
- [~] **DRL 可解释性 (SHAP)** — *(v14.2, 冻结)*
- [~] **DRL 时序动画** — 优化过程回放 *(v14.2, 冻结)*
- [~] **多场景环境引擎** — DRL 配置驱动重构 *(v14.1, 冻结)*
- [~] **约束建模** — 硬/软约束 Gymnasium 扩展 *(v14.1, 冻结)*
- [~] **结果对比面板** — A/B 对比优化结果 *(v14.1, 冻结)*
- [~] **分布式任务队列 (Celery)** — *(v14.2, 冻结)*
- [~] **Pipeline 断点恢复 v2** — 崩溃后自动恢复 *(v14.2, 冻结)*
- [~] **协同工作空间 (CRDT)** — *(v14.3, 冻结)*
- [~] **Agent 联邦** — 多实例负载均衡 *(v14.3, 冻结)*
- [~] **联邦学习** — 隐私保护 DRL *(v14.3, 冻结)*
- [~] **个性化模型微调 (LoRA)** — *(v14.3, 冻结)*
- [~] **离线模式** — Service Worker *(v14.3, 冻结)*
- [~] **语音输入 (Whisper)** — *(v14.2, 冻结)*
- [~] **Generator/Reviewer 输出结构化校验** — Pydantic schema *(v15.0, 移至 v16.0+)*

---

---

## v15.9 — 向 L3 迈进：Planner-Executor + 中间件链 + DeerFlow 工程质量

> **主题**: 补齐 Proto-L3 短板 + 解决最大技术债 + 工程质量提升
>
> **依据**: SIGMOD 2026 "Data Agents: Levels, State of the Art, and Open Problems" (Luo et al.) + DeerFlow v2.0 架构借鉴
>
> **当前水平**: L2.5 (完整 L2 + 部分 Proto-L3) → **目标**: 完整 L3 条件自主

### 核心升级：从 L2 执行者 → L3 编排者

**关键演进跃迁 (SIGMOD 2026 论文):**
- L2: 人类设计流程，Agent 执行任务特定过程
- L3: Agent 设计流程，人类监督执行结果

### DeerFlow 工程质量借鉴 (P0-P2)

#### **D-1: App 分层重构 — Harness/App 分离 (P0)**
- [x] **core/ 层提取** — agent_runtime.py (Agent 创建 + pipeline 组装) + tool_registry.py (Toolset 注册表) 从 agent.py 提取
- [x] **app.py 瘦身** — 从 3340 行降到 <500 行，仅保留 Chainlit 回调 + 胶水代码
- [x] **CI 边界测试** — test_harness_boundary.py 强制 core/ 永不 import chainlit
- [x] **api/ 进一步拆分** — frontend_api.py 按 domain 拆分 (catalog/workflow/quality/skill 等)

#### **D-2: 中间件链模式 (P1)**
- [x] **PipelineMiddleware 协议** — before_run / after_run / on_error 三阶段钩子
- [x] **7 层中间件提取** — RBAC → FileUpload → ContextSummarization → [Pipeline] → TokenTracking → LayerControl → ErrorClassification
- [x] **中间件注册器** — 可组合、可启停、严格执行顺序

#### **D-3: 上下文自动摘要 (P1)**
- [x] **SummarizationMiddleware** — token 超 80% 阈值时自动压缩历史对话
- [x] **摘要策略** — 保留最近 3 轮完整对话 + 关键数据路径 + 分析结论，丢弃中间推理
- [x] **使用 Gemini 2.0 Flash** — 便宜快速的摘要模型

### SIGMOD 2026 论文借鉴 (P1-P2)

#### **S-1: Planner-Executor 分离 (P1, 向 L3 关键跃迁)**
- [x] **PlannerAgent** — 根据用户意图动态生成 ExecutionPlan (DAG nodes + edges + dependencies)
- [x] **ExecutorAgent** — 拓扑排序 + 并行执行计划
- [x] **ExecutionPlan 数据结构** — 替代硬编码的三条流水线 (Optimization/Governance/General)
- [x] **复用 workflow_engine.py** — DAG 执行逻辑已有，重构为 Planner 输出格式

#### **S-2: 工具选择器 (P2)**
- [x] **ToolSelector** — 根据 task_type + data_profile 推荐工具子集
- [x] **选择规则** — 遥感任务 → RemoteSensingToolset，数据量 >1GB → SparkToolset，因果分析 → CausalInferenceToolset
- [x] **降低 Agent 负担** — 从 28 个 Toolset 全暴露 → 智能推荐 5-8 个相关工具

#### **S-3: 因果错误诊断 (P2)**
- [x] **PipelineErrorDiagnoser** — 构建管道因果图 + 反向追踪错误传播路径
- [x] **根因识别** — 定位哪一步引入错误 (而非仅报告哪一步失败)
- [x] **修复建议** — 自动推荐修复策略 (插入工具调用、调整参数、替换工具)

### 历史遗留完成 (低成本高价值)

- [x] **奖励权重 UI** — DRL 前端 slope/contiguity/balance 滑块 *(v14.0 遗留)*
- [x] **MCP 外部 Agent 接入验证** — Claude Desktop / Cursor E2E 测试 *(v13.1 遗留)*
- [x] **分析意图消歧 v2** — 复杂查询拆解子任务列表 *(v14.1 遗留)*
- [x] **自动记忆提取增强** — pipeline 后 extract_facts + 弹窗确认 *(v14.1 遗留)*
- [x] **消息总线持久化** — AgentMessageBus → PostgreSQL *(v14.1 遗留)*
- [x] **Skill SDK 发布** — `gis-skill-sdk` Python 包 *(v14.3 遗留)*

### 质量保障
- [x] **test_planner_executor.py** — Planner 生成计划 + Executor 执行验证
- [x] **test_middleware_chain.py** — 7 层中间件执行顺序 + 钩子调用
- [x] **test_tool_selector.py** — 任务特征 → 工具推荐准确性
- [x] **test_error_diagnoser.py** — 管道错误根因识别

---

## v16.0 — 完整 L3：语义算子 + 多 Agent 协作 + 遥感智能体

> **主题**: 达到完整 L3 条件自主 + 遥感领域专业化
>
> **依据**: SIGMOD 2026 论文 Proto-L3 设计模式 + Tang et al. (2026) 遥感智能体综述
>
> **目标**: 成为地理空间领域标杆 L3 系统

### SIGMOD 2026 论文借鉴 (完整 L3)

#### **S-4: 语义算子层 (P1)**
- [x] **SemanticOperator 抽象** — Clean / Integrate / Analyze / Visualize 高层算子 ✅ 2026-04-01
- [x] **CleanOperator** — 封装 DataCleaningToolset 11 工具，根据数据特征自动选择清洗策略 ✅ 2026-04-01
- [x] **IntegrateOperator** — 封装连接器 + schema 映射 + 冲突解决 ✅ 2026-04-01
- [x] **AnalyzeOperator** — 封装 GeoProcessing + Analysis + CausalInference ✅ 2026-04-01
- [x] **算子组合** — Planner 组合语义算子而非直接调用底层工具 ✅ 2026-04-01

#### **S-5: 多 Agent 协作 (P1)**
- [x] **DataEngineerAgent** — 负责数据准备 (清洗、集成、标准化) ✅ 2026-04-01
- [x] **AnalystAgent** — 负责分析 (GIS 分析、统计、因果推断) ✅ 2026-04-01
- [x] **VisualizerAgent** — 负责可视化 (地图、图表、报告) ✅ 2026-04-01
- [x] **RemoteSensingAgent** — 负责遥感分析 (光谱指数、变化检测、时序分析) ✅ 2026-04-01
- [x] **CoordinatorAgent** — Planner 增强为协调器，管理 4 专业 Agent + 2 组合工作流 ✅ 2026-04-01

#### **S-6: 计划精化与错误恢复 (P2)**
- [x] **PlanRefiner** — 根据执行反馈调整计划 (插入修复步骤、跳过失败步骤、替换工具) ✅ 2026-04-01
- [x] **ErrorRecoveryStrategy** — 多种恢复策略 (retry / alternative_tool / skip / simplify / escalate) ✅ 2026-04-01
- [x] **局部调整** — 从"全有或全无"到"局部精化" ✅ 2026-04-01

#### **S-7: 工具演化 (P2)**
- [x] **ToolEvolution** — 动态工具库管理 (add_tool / remove_tool / suggest_new_tools) ✅ 2026-04-01
- [x] **失败驱动的工具发现** — 分析失败任务，推荐缺失的工具 ✅ 2026-04-01
- [x] **工具元数据** — 能力描述、成本、可靠性、适用场景 ✅ 2026-04-01

### DeerFlow 工程质量借鉴 (v16.0)

#### **D-4: 工具调用 Guardrails (P2)**
- [x] **GuardrailMiddleware** — 可插拔的确定性策略引擎 (非 LLM 判断) ✅ 2026-04-01
- [x] **三级策略** — Deny (静默拒绝) / Require Confirmation (暂停确认) / Allow (直接执行) ✅ 2026-04-01
- [x] **YAML 策略配置** — viewer deny [delete_*, drop_*], analyst require_confirmation [execute_sql_write] ✅ 2026-04-01
- [x] **与 RBAC 协同** — RBAC (pipeline 级) + Guardrails (工具级) = 两层安全 ✅ 2026-04-01

#### **D-5: AI 辅助 Skill 创建 (P2)**
- [x] **skill-creator Skill** — 用自然语言描述需求 → AI 生成 Skill 配置 ✅ 2026-04-01
- [x] **工作流** — 需求分析 → 推荐 toolsets → 生成配置 → 用户预览确认 → 保存 DB ✅ 2026-04-01
- [x] **复用现有 API** — `/api/skills/generate` 端点 + custom_skills.py CRUD ✅ 2026-04-01

### 遥感智能体 Phase 1 (v16.0)

- [x] **光谱指数库** — 15+ 遥感指数 (EVI/SAVI/NDWI/NDBI/NBR 等) + 智能推荐 ✅ 2026-04-01
- [x] **经验池 (Experience Pool)** — 成功分析经验记录 + RAG 检索 + 经验进化 ✅ 2026-04-01
- [x] **数据质量门控** — 云覆盖检测 + 自动降级 (光学→SAR 切换) ✅ 2026-04-01
- [x] **卫星数据预置** — Sentinel-2/Landsat/SAR STAC 模板 + 5 预置源 ✅ 2026-04-01
- [x] **新增 Skills** — spectral-analysis + satellite-imagery ✅ 2026-04-02

### 质量保障
- [x] **test_semantic_operators.py** — 语义算子组合 + 自动工具选择 ✅ 2026-04-02
- [x] **test_multi_agent_collaboration.py** — 多 Agent 任务分解 + 协调 + 汇总 ✅ 2026-04-02
- [x] **test_plan_refinement.py** — 执行反馈 → 计划调整 ✅ 2026-04-02
- [x] **test_guardrails.py** — 策略引擎 + 三级策略验证 ✅ 2026-04-02

---

## 已完成 (v17.0) — 多模态融合 v2.0 增强

> **主题**: 时序对齐 + 语义增强 + 冲突解决 + 可解释性
>
> **依据**: `docs/fusion_v2_enhancement_plan.md` — 从基础融合到智能语义融合
>
> **目标**: 提升多源数据融合质量，增强语义理解和冲突处理能力

### 时序对齐模块

- [x] **TemporalAligner** — `fusion/temporal.py` 时序对齐引擎 ✅ 2026-04-04
- [x] **时间戳标准化** — 多时区/多格式统一到 UTC ISO8601 ✅ 2026-04-04
- [x] **时序插值** — 线性/样条/最近邻插值，填补时间间隙 ✅ 2026-04-04
- [x] **时间窗口对齐** — 滑动窗口匹配 + 容差配置 ✅ 2026-04-04
- [x] **事件序列对齐** — DTW (Dynamic Time Warping) 算法 ✅ 2026-04-04
- [x] **5 对齐工具** — standardize_timestamps / interpolate_temporal / align_time_windows / align_event_sequences / validate_temporal_consistency ✅ 2026-04-04

### 语义增强模块

- [x] **SemanticEnhancer** — `fusion/semantic_llm.py` + `fusion/ontology.py` 语义增强引擎 ✅ 2026-04-04
- [x] **本体推理** — OWL 本体加载 + RDFS 推理 + 关系传播 ✅ 2026-04-04
- [x] **LLM 语义理解** — Gemini 2.5 Pro 字段语义解析 + 关系抽取 ✅ 2026-04-04
- [x] **跨源实体链接** — 基于嵌入的实体消歧 + 同义词扩展 ✅ 2026-04-04
- [x] **语义相似度计算** — 字段级 + 记录级相似度评分 ✅ 2026-04-04
- [x] **6 语义工具** — load_ontology / infer_relationships / llm_semantic_parse / link_entities / compute_semantic_similarity / enrich_with_context ✅ 2026-04-04

### 冲突解决模块

- [x] **ConflictResolver** — `fusion/conflict_resolver.py` 冲突解决引擎 ✅ 2026-04-04
- [x] **冲突检测** — 值冲突 / 模式冲突 / 时序冲突 / 空间冲突 ✅ 2026-04-04
- [x] **解决策略** — 6 种策略 (source_priority / latest_wins / voting / llm_arbitration / spatial_proximity / user_defined) ✅ 2026-04-04
- [x] **置信度评分** — 数据源可信度 + 时效性 + 空间精度综合评分 ✅ 2026-04-04
- [x] **冲突日志** — 记录所有冲突及解决决策，支持审计 ✅ 2026-04-04
- [x] **5 冲突工具** — detect_conflicts / resolve_value_conflict / resolve_schema_conflict / resolve_temporal_conflict / log_conflict_resolution ✅ 2026-04-04

### 可解释性模块

- [x] **ExplainabilityEngine** — `fusion/explainability.py` 可解释性引擎 ✅ 2026-04-04
- [x] **融合溯源** — 每个融合结果追溯到源数据集 + 转换步骤 ✅ 2026-04-04
- [x] **决策解释** — 为什么选择某个值/策略，生成自然语言解释 ✅ 2026-04-04
- [x] **影响分析** — 某个源数据变化对融合结果的影响评估 ✅ 2026-04-04
- [x] **可视化报告** — Sankey 图 (数据流) + 决策树 (策略选择) ✅ 2026-04-04
- [x] **4 解释工具** — trace_fusion_lineage / explain_decision / analyze_impact / generate_fusion_report ✅ 2026-04-04

### 集成与测试

- [x] **FusionToolset 扩展** — 新增 20 个融合 v2.0 工具 ✅ 2026-04-04
- [x] **fusion_v2_routes.py** — 8 个 REST API 端点 ✅ 2026-04-04
- [x] **FusionV2Tab** — DataPanel 新增融合 v2.0 配置和监控 Tab ✅ 2026-04-04
- [x] **84 测试** — 时序对齐/语义增强/冲突解决/可解释性全覆盖 ✅ 2026-04-04

---

## 已完成 (v17.1) — 矢量切片渲染 + 数据资产编码

> **主题**: 大数据量地图渲染优化 + 数据资产标准化编码
>
> **依据**: 大数据量 GeoJSON 渲染性能瓶颈 + 资产管理规范化需求

### 矢量切片大数据渲染

- [x] **三级自适应交付** — GeoJSON (≤5K features) / FlatGeobuf (5K-50K) / PostGIS MVT (>50K) ✅ 2026-04-04
- [x] **tile_server.py** — MVT 矢量切片生成: 临时表管理 + ST_AsMVT 查询 + 过期清理 ✅ 2026-04-04
- [x] **tile_routes.py** — 5 个切片 REST API 端点 ✅ 2026-04-04
- [x] **Martin 集成** — 外部矢量切片服务器配置 ✅ 2026-04-04
- [x] **Migration 050** — mvt_tile_layers 表 ✅ 2026-04-04

### 数据资产编码系统

- [x] **asset_coder.py** — DA-{TYPE}-{SRC}-{YEAR}-{SEQ} 编码规范 ✅ 2026-04-04
- [x] **data_catalog.py 集成** — 资产注册时自动分配编码 ✅ 2026-04-04
- [x] **Migration 051** — asset_code 字段 + 唯一索引 ✅ 2026-04-04

### 质量保障

- [x] **test_tile_server.py** — 切片生成/清理/API 全覆盖 ✅ 2026-04-04
- [x] **test_asset_coder.py** — 编码生成/解析/唯一性验证 ✅ 2026-04-04

---

## 已完成 (v18.0) — 应用层数据库优化

> **主题**: 连接池扩容 + asyncpg 异步引擎 + 读写分离预埋 + 物化视图 + 连接池监控
>
> **依据**: `docs/distributed_architecture_plan.md` Phase 1 (调整: 华为云 RDS 已有 HA，聚焦应用层优化)
>
> **目标**: 提升数据库连接效率和可观测性，为未来 RDS 只读副本做接口预埋

### 连接池扩容

- [x] **pool_size 5→20** — 适配华为云 RDS 连接能力 ✅ 2026-04-04
- [x] **max_overflow 10→30** — 允许更多突发连接 ✅ 2026-04-04
- [x] **环境变量配置** — DB_POOL_SIZE / DB_MAX_OVERFLOW 可调 ✅ 2026-04-04

### 读写分离接口预埋

- [x] **get_engine(readonly=True/False)** — 接口预埋，当前 fallback 到主库 ✅ 2026-04-04
- [x] **DATABASE_READ_URL 支持** — 配置 RDS 只读副本时自动启用读写分离 ✅ 2026-04-04
- [x] **get_pool_status()** — 连接池实时状态查询 ✅ 2026-04-04

### asyncpg 异步数据库引擎

- [x] **db_engine_async.py** — asyncpg 连接池单例 (min=5, max=20, 可配置) ✅ 2026-04-04
- [x] **便利函数** — fetch_async / fetchrow_async / fetchval_async / execute_async ✅ 2026-04-04
- [x] **RLS 上下文注入** — _inject_user_context_async 支持异步连接 ✅ 2026-04-04
- [x] **优雅关闭** — close_async_pool() 应用关闭时调用 ✅ 2026-04-04

### 物化视图

- [x] **Migration 052** — mv_pipeline_analytics + mv_token_usage_daily + refresh 函数 ✅ 2026-04-04
- [x] **只读角色** — agent_reader 角色创建 (SELECT only) ✅ 2026-04-04
- [x] **连接统计视图** — v_connection_stats (pg_stat_activity 聚合) ✅ 2026-04-04

### 连接池 Prometheus 监控

- [x] **4 个新 Gauge** — db_pool_size / checkedin / checkedout / overflow ✅ 2026-04-04
- [x] **查询延迟 Histogram** — db_query_duration_seconds ✅ 2026-04-04
- [x] **collect_db_pool_metrics()** — /metrics 端点自动采集 ✅ 2026-04-04

### 质量保障

- [x] **test_db_engine_v18.py** — 23 测试: 连接池配置/读写分离/async 生命周期/物化视图/监控 ✅ 2026-04-04

### 跳过的项目 (华为云 RDS 已内置)

- [~] ~~PostgreSQL 主从复制~~ — RDS 内置 HA
- [~] ~~Patroni 故障转移~~ — RDS 自动故障转移
- [~] ~~PgBouncer K8s 部署~~ — 应用层连接池已优化
- [~] ~~postgres-replication.yaml~~ — RDS 已处理

---

## 已完成 (v18.5) — 智能体平台能力增强 + Palantir 风格 UI 重设计

> **主题**: NL2Workflow + 提示词自动优化 + 评估器扩充 + Palantir-inspired 深色主题 UI
>
> **依据**: `docs/agentarts-benchmark-analysis.md` — 华为云 AgentArts 对标分析 + 产品顾问 UI/UX 建议
>
> **目标**: 补齐平台级能力短板 + 产品级视觉升级

### NL2Workflow — 自然语言生成工作流 (P0)

> AgentArts 核心能力: 用户一句话描述业务场景 → 自动生成可执行工作流 DAG

- [x] **NL2WorkflowGenerator** — LLM 解析自然语言需求 → 输出 workflow_engine DAG JSON ✅ 2026-04-04
- [x] **工具推荐** — 根据描述自动匹配 Toolset/Skill 节点 (23 内置 Skill 元数据) ✅ 2026-04-04
- [x] **预览确认** — 生成后返回 DAG 预览 + explanation，用户确认后执行 ✅ 2026-04-04
- [x] **WorkflowEditor 集成** — auto_save 参数直接保存到 workflow_engine ✅ 2026-04-04
- [x] **REST API** — `POST /api/workflows/generate` 接收自然语言描述 ✅ 2026-04-04
- [x] **验证** — 循环依赖检测 (Kahn 拓扑排序) + 字段完整性 + pipeline_type 校验 ✅ 2026-04-04
- [x] **测试** — 26 测试全覆盖 ✅ 2026-04-04

### 提示词自动优化 (P1)

> AgentArts 核心能力: 文本梯度自动分析 bad case → 提示词自动优化

- [x] **BadCaseCollector** — 从评估历史/pipeline 失败/用户反馈三源收集 bad case ✅ 2026-04-04
- [x] **FailureAnalyzer** — LLM 分析失败模式 (模式/根因/受影响 prompt) ✅ 2026-04-04
- [x] **PromptOptimizer** — 基于失败分析生成改进后的 prompt 版本 ✅ 2026-04-04
- [x] **Human-in-the-loop** — 优化建议保存到 dev 环境，需人工确认后部署 ✅ 2026-04-04
- [x] **REST API** — 4 端点 (collect-bad-cases / analyze-failures / optimize / apply-suggestion) ✅ 2026-04-04
- [x] **测试** — 20 测试全覆盖 ✅ 2026-04-04

### 评估器扩充 (P1)

> AgentArts: 30+ 平台精选评估器 (任务完成率/内容质量/安全/轨迹质量)

- [x] **EvaluatorRegistry** — 可插拔评估器注册表 ✅ 2026-04-04
- [x] **内置评估器 (15)** — Quality (ExactMatch/Regex/JsonSchema/Completeness/Coherence) + Safety (Safety/PII/SqlInjection) + Performance (Latency/TokenCost/OutputLength) + Accuracy (ToolCallAccuracy/Numeric/GeoSpatial/InstructionFollowing) ✅ 2026-04-04
- [x] **批量评估** — `run_evaluation()` 多评估器 × 多测试用例 + 聚合统计 ✅ 2026-04-04
- [x] **REST API** — `GET /api/eval/evaluators` + `POST /api/eval/evaluate` ✅ 2026-04-04
- [x] **测试** — 67 测试全覆盖 ✅ 2026-04-04

### Palantir-inspired UI/UX 重设计 (v18.5)

> 产品顾问建议参照 Palantir AIP 风格，提升产品级视觉品质

- [x] **Deep Intelligence 深色主题** — 设计令牌体系: #0B0F19 base / #3B82F6 primary / #111827 surface ✅ 2026-04-05
- [x] **字体升级** — Space Grotesk → Inter (UI) + JetBrains Mono (代码/数据) ✅ 2026-04-05
- [x] **Lucide 图标系统** — DataPanel 所有 emoji 图标 → Lucide SVG (lucide-react v1.7.0) ✅ 2026-04-05
- [x] **DataPanel 3 组重构** — 4 组 → 3 组 (数据资源 / 智能分析 / 平台运营)，编排组解散 ✅ 2026-04-05
- [x] **左右分屏登录页** — 居中卡片 → 左 60% 品牌展示 (统计+特性) + 右 40% 表单 ✅ 2026-04-05
- [x] **AppNav 图标导航栏** — 48px 左侧 icon rail + Header 56px → 40px 状态栏 ✅ 2026-04-05

---

## v19.0 — 上下文工程 + 反馈飞轮 (Datus.ai 对标) ✅ 2026-04-08

> **主题**: 统一上下文引擎 + 结构化反馈闭环 + 语义模型标准化 + 参考查询库
>
> **依据**: `docs/datus_ai_benchmark_analysis.md` — Datus.ai 对标分析 (上下文工程方法论 + 反馈飞轮设计)
>
> **核心洞察**: LLM 回答准确性 80% 取决于输入上下文质量，而非模型本身能力。积累的语义模型、参考查询、成功案例才是真正壁垒。
>
> **v19.0 S3 对象存储** 已在早期版本中实现 (cloud_storage.py + storage_manager.py + obs_storage.py)，版本号复用。

### P0 — 统一上下文引擎 (Context Engine)

> Datus 核心竞争力: Context Engine 自动构建"活的语义地图"，融合 6 类知识源为统一检索接口
>
> 我们现状: semantic_layer.py / knowledge_graph.py / knowledge_base.py / context_manager.py 分散在 4 个模块

- [x] **ContextEngine 统一抽象** — 新增 `context_engine.py`: 融合所有知识源为一个检索接口，替代 BCG context_manager.py 的简单实现 ✅ 2026-04-08
- [x] **6 个 ContextProvider** — SemanticLayerProvider (现有) / KnowledgeGraphProvider (现有) / KnowledgeBaseProvider (现有) / ReferenceQueryProvider (新增) / SuccessStoryProvider (新增) / MetricDefinitionProvider (新增) ✅ 2026-04-08
- [x] **相关性排序** — 基于 query embedding + 任务类型对所有 provider 返回的上下文块进行统一排序 ✅ 2026-04-08
- [x] **Token 预算截断** — 按相关性分数截断到 token_budget，确保不超出 LLM 上下文窗口 ✅ 2026-04-08
- [x] **上下文缓存** — 相同 query + task_type 组合缓存 3 分钟，避免重复检索 ✅ 2026-04-08
- [x] **Pipeline 集成** — Planner/Executor 在生成计划和执行工具前自动调用 `context_engine.prepare()` ✅ 2026-04-08
- [x] **REST API** — `GET /api/context/prepare` (预览上下文) + `GET /api/context/providers` (列出 provider 状态) ✅ 2026-04-08
- [x] **测试** — context_engine 统一检索 + provider 注册 + 排序 + 截断 + 缓存全覆盖 ✅ 2026-04-08

### P0 — 结构化反馈学习闭环 (Feedback Loop)

> Datus 核心差异化: 用户每次 upvote/downvote 都在训练系统，形成"越用越准"的飞轮
>
> 我们现状: prompt_optimizer.py 有 bad case 收集，但无用户侧反馈采集 UI 和自动学习管道

- [x] **前端反馈 UI** — 每条 Agent 回答增加 👍/👎 按钮 + 可选 issue 描述弹窗 (ChatPanel 消息组件扩展) ✅ 2026-04-08
- [x] **agent_feedback 表** — Migration: query_text, response_text, vote (up/down), issue_description, pipeline_type, resolved_at, created_by ✅ 2026-04-08
- [x] **反馈收集 API** — `POST /api/feedback` (提交反馈) + `GET /api/feedback/stats` (反馈统计) ✅ 2026-04-08
- [x] **成功案例自动提取** — upvote 的查询自动提取为参考查询 (query + response + tags)，进入 ReferenceQueryProvider ✅ 2026-04-08
- [x] **失败模式分析管道** — 定期聚合 downvote 反馈 → 调用 prompt_optimizer.py FailureAnalyzer → 生成改进建议 ✅ 2026-04-08
- [x] **反馈→上下文自动更新** — 成功案例 → SuccessStoryProvider；失败模式 → 触发 prompt 优化建议 ✅ 2026-04-08
- [x] **反馈看板** — DataPanel 新增反馈统计子面板 (满意率趋势 / 高频失败模式 / 最近反馈列表) ✅ 2026-04-08
- [x] **测试** — 反馈 CRUD + 成功案例提取 + 失败分析管道 + 统计聚合全覆盖 ✅ 2026-04-08

### P1 — 语义模型标准化 (MetricFlow 兼容)

> Datus 采用 MetricFlow YAML 语义模型，自动从表结构生成，支持指标/维度/关系定义
>
> 我们现状: semantic_layer.py 自定义三级层次结构，与主流数据栈不兼容

- [x] **GIS Semantic Model YAML 格式** — 扩展 MetricFlow YAML 规范，增加 `type: spatial` 维度 + `srid` 字段 + `geometry_type` 属性 ✅ 2026-04-08
- [x] **自动生成器** — `gen_semantic_model` 工具: 从 PostGIS 表结构自动生成语义模型 YAML ✅ 2026-04-08
- [x] **semantic_layer.py 适配** — 现有三级层次结构保留为向后兼容，新增 MetricFlow YAML 读取器 ✅ 2026-04-08
- [x] **语义模型 CRUD API** — `GET/POST/PUT/DELETE /api/semantic/models` ✅ 2026-04-08
- [x] **MetricDefinitionProvider** — 从语义模型中提取指标定义，注入 ContextEngine ✅ 2026-04-08
- [x] **测试** — YAML 解析 + PostGIS 表结构提取 + 语义模型 CRUD + Provider 注入全覆盖 ✅ 2026-04-08

### P1 — 参考查询库 (Reference Query Library)

> Datus 的 gen_sql_summary 子Agent 自动分类+标注 SQL，成功查询积累为参考库
>
> 我们现状: 无验证过的参考查询积累机制

- [x] **agent_reference_queries 表** — Migration: query_text, description, tags[], verified_by, use_count, success_rate, pipeline_type, created_by ✅ 2026-04-08
- [x] **ReferenceQueryProvider** — 实现 ContextProvider 接口，基于 query embedding 检索相似参考查询 ✅ 2026-04-08
- [x] **自动入库** — 用户 upvote → 查询自动进入参考库 (关联 agent_feedback 表) ✅ 2026-04-08
- [x] **手动策展** — `POST /api/reference-queries` 手动添加参考查询 + `PUT` 编辑标签/描述 ✅ 2026-04-08
- [x] **NL2SQL 增强** — NL2SQLToolset 执行前先检索参考库中的相似查询作为 few-shot 示例 ✅ 2026-04-08
- [x] **REST API** — 6 端点 (CRUD + search + stats) ✅ 2026-04-08
- [x] **测试** — 参考查询 CRUD + 相似度检索 + NL2SQL few-shot 注入全覆盖 ✅ 2026-04-08

### 质量保障

- [x] **test_context_engine.py** — 统一上下文引擎全流程 ✅ 2026-04-08
- [x] **test_feedback_loop.py** — 反馈收集→学习→上下文更新闭环 ✅ 2026-04-08
- [x] **test_semantic_model_metricflow.py** — MetricFlow YAML 解析+生成 ✅ 2026-04-08
- [x] **test_reference_queries.py** — 参考查询库 CRUD + NL2SQL 集成 ✅ 2026-04-08

---

## v20.0 — 分布式任务队列与缓存 + 体验优化 ✅ 2026-04-08

> **状态**: ✅ 完成 — Redis 本机部署 (localhost:6379)
>
> **主题**: Celery 分布式任务队列 + Redis 缓存 + Datus 对标 P2 体验优化项
>
> **依据**: `docs/distributed_architecture_plan.md` Phase 2 + `docs/datus_ai_benchmark_analysis.md` P2 项

### Redis 分布式任务队列 ✅

- [x] **redis_client.py** — 统一 Redis 连接管理 (async/sync) + 分布式锁 RedisLock (SETNX+TTL+Lua) ✅ 2026-04-08
- [x] **task_queue.py Redis 后端** — Sorted Set 优先级队列 + 分布式信号量 + 内存降级 ✅ 2026-04-08
- [x] **Redis 缓存迁移** — semantic_layer.py + context_engine.py 双层缓存 (Redis+内存) ✅ 2026-04-08
- [x] **health.py 集成** — Redis 健康检查 + System Status 显示版本 ✅ 2026-04-08

### P2 — 多 LLM 一键切换体验 ✅

- [x] **统一 LLM 配置 YAML** — `conf/models.yaml` 声明式配置所有 LLM provider ✅ 2026-04-08
- [x] **model_gateway.py 适配** — load_from_yaml() 动态注册，保持现有 API 兼容 ✅ 2026-04-08

### P2 — Agentic/Workflow 双模式 ✅

- [x] **模式检测** — intent_router.py 增加 execution_mode 检测 (中英文关键词 + WORKFLOW 意图) ✅ 2026-04-08
- [x] **Agentic Mode** — 现有语义路由 → Planner 自主决策 → 灵活探索 (默认模式) ✅ 2026-04-08
- [x] **Workflow Mode** — 选择预定义工作流 → 确定性步骤执行 → 无 LLM 中间决策 ✅ 2026-04-08
- [x] **模式感知路由** — intent_router.py 返回 execution_mode，app.py 消费 ✅ 2026-04-08

### P2 — 轻量化部署选项 ✅

- [x] **DuckDB 适配器** — duckdb_adapter.py: DuckDB + spatial 扩展，GeoDataFrame 双向转换 ✅ 2026-04-08
- [x] **Lite 模式设计** — 仅 General Pipeline + DuckDB 后端，无 PostGIS 依赖 ✅ v23.0
- [x] **可选依赖分组** — `pip install gis-data-agent[lite]` (核心) vs `[full]` (含 PostGIS/DRL/WorldModel) ✅ v23.0
- [x] **快速启动脚本** — `gis-agent init` 一键初始化 (DuckDB + 默认配置 + 示例数据) ✅ 2026-04-08

---

## 已完成 (v24.0) — @SubAgent 显式路由 + XMI 领域标准

> **主题**: 专家用户直控 + 行业标准体系化
>
> **日期**: 2026-04-19

### @SubAgent Mention Routing
- [x] **mention_registry.py** — 4 类 target 聚合（pipeline / sub-agent / custom skill / ADK skill），handle 去重 + 大小写无关查找
- [x] **mention_parser.py** — leading `@handle` 正则解析，非首位 `@` 忽略，未知 mention 回退语义路由
- [x] **app.py 集成** — `classify_intent()` 前插入 mention 路由，4 种 dispatch 路径（pipeline 直设 intent / sub-agent 状态校验+直接执行 / custom skill DB 查找+build_custom_agent / ADK skill SkillToolset 包装）
- [x] **agent.py `_make_agent_by_name`** — 10 个子代理工厂 lambda，ADK one-parent 约束下按需创建新实例
- [x] **GET /api/chat/mention-targets** — RBAC 过滤的 autocomplete 数据源，返回 handle/type/description/allowed/required_state_keys
- [x] **ChatPanel.tsx autocomplete** — `@` 触发 dropdown，ArrowUp/Down 导航，Enter/Tab 选中，Esc 关闭，onMouseDown 点选
- [x] **observability.py** — `mention_routes` Prometheus counter (target_type/handle/status) + `log_mention_event` 结构化日志
- [x] **24 单元/集成测试** — TestMentionRegistry (9) + TestMentionParser (8) + TestMentionDispatch (4) + TestMentionTargetsAPI (3)

### XMI Domain Standard System
- [x] **XMI 领域标准体系** — 解析器、编译器、工具集、上下文提供器、REST API、前端 Tab

---

## 历史战略输入 — 四看驱动的战略刷新 (2026-04-21)

> **状态**：本节及后续 `v25.0/v26.0/v27.0` 是 2026-04-21 形成的竞品研究和需求池，已被文首 NDP-0~NDP-4 主路线接管，不再作为有效 release line、交付顺序或完成时间承诺。保留原条目用于追溯需求来源；任何条目进入实施前，必须映射到四契约族、治理生命周期、双试点和对应 NDP 退出门。
>
> **原背景**: 基于 2026 Q2 技术四看分析（技术趋势 / 宏观 PEST / 竞争格局 / 自我评估），行业已从"AI 辅助数据治理"全面进入 **Agentic Data Governance** 阶段。GIS Data Agent 原型阶段已完成，下一阶段以"智能体驱动的时空数据治理平台"为叙事，分三个版本产品化落地。
>
> **四看核心结论**:
> - **趋势**: Gartner 2026 MQ for D&A Governance 把 agentic AI + 活跃元数据作为核心评估维度；数据产品化 + AI-Ready Data 成为新范式；MCP/A2A 协议栈重塑 Agent↔数据集成
> - **宏观**: 国务院"AI+"意见、国家数据局数据产权三权分置登记、网安法修订罚款 5-10 倍提升、EU AI Act 2026.8 全面执行
> - **竞争**: 北京数慧（数据编织 + 智能体）、土豆数据（Data for AI 闭环）、阿里 DataWorks（Agent + 语义 ETL）、袋鼠云（多模态数据中台）、Atlan / Alation / Ataccama（agentic governance + metadata lakehouse）
> - **自己**: 空间数据一等公民是核心优势；智能化治理从"缺失"升级为"原型验证"；多模态治理、数据产品化、合规审计、声明式治理仍为缺失项

### 历史需求到 NDP 主路线的迁移

| 历史规划能力 | 当前归属 | 处理原则 |
|---|---|---|
| `v25.0` Active Metadata、Policy as Code、治理 Agent | NDP-1 Agentic Governance Runtime | 必须进入 GovernanceEvent/Task/Policy/Evaluator/HITL/ChangeSet/Version 状态机，不再建设彼此独立的 Agent 孤岛 |
| `v25.0` 数据产品、空间契约、质量门禁、STAC 发布 | NDP-1 Trusted Data Product | 升级为平台级 `DataProductVersion` 和 Human/Agent/AI/GWM 投影；旧 migration 064 仅作需求草案，不能视为已实现 |
| `v26.0` 多模态治理、AI-Ready Data、合规 | NDP-1 / NDP-2 | MMFE 和多类型数据治理前移到主线；先完成 SemanticFusionProductVersion、DatasetVersion/ModelVersion、质量安全策略和效果 benchmark |
| `v26.0` 湖仓、可信流通、资产化 | NDP-4 条件路线 | 只有出现跨组织消费、规模负载或政策交付证据后启动；不得产生第二权威写源 |
| `v27.0` MCP/A2A/STAC/OGC、联邦治理、生态 SDK | NDP-4 条件路线 | 作为同一数据产品的交换与消费接口，不以协议数量代替产品闭环 |
| `v27.0` 行业知识、交付模板 | NDP-0 Domain Pack + NDP-1/NDP-2；GWM 知识投影进入 NDP-3 | 自然资源和城市优先；先沉淀标准/模型/质量/安全/融合/产品模板，再由 TWM/UWM 消费领域状态与证据 |
| Hermes 记忆、执行后端、安全栈 | Cognitive Runtime 子路线 | 服从 RuntimeIdentity、RunWorkspace、Policy、Evidence 和隔离契约 |

---

## 历史计划输入 — v25.0 Agentic Governance Foundation（原计划 2026 H2，已撤销版本承诺）

> **主题**: 把 GIS Data Agent 的智能化治理原型产品化，补齐 agentic data governance 基础设施
>
> **历史等级假设**: L3.5 → **L4**。该假设已撤销，当前整体等级须由 Cognitive Runtime 基准重新评定。
>
> **工作量估算**: 4-5 个月 | **依赖**: 无外部基础设施硬依赖（Kong / Jaeger 等保持搁置）

### P0 — 活跃元数据引擎 (Atlan / Gartner 对标)

- [ ] **active_metadata.py** — 统一活跃元数据层，封装 `semantic_layer.py` + `data_catalog.py` 现有能力 + 新增变更事件流
- [ ] **自动采集扩展** — DB schema / 文件 / API 源 / MCP 工具四类来源的元数据自动采集
- [ ] **元数据 CDC 事件流** — 元数据变更 → Redis Stream → 下游 Agent 订阅响应（血缘重建、质量门禁触发）
- [ ] **活跃血缘** — 当前 BFS 血缘 → 增量血缘 + 影响分析（upstream change → downstream impact 告警）
- [ ] **策略联动** — 元数据变更触发治理策略自动执行（质量门禁、分类分级、合规检查）

### P0 — 治理 Agent 体系 (Alation / Ataccama 对标)

- [ ] **ClassificationAgent** — `skills/classification-agent/` + Skill L1/L2/L3，智能分类分级 + 规则库持续学习
- [ ] **QualityAgent** — `skills/quality-agent/`，智能质检 + 自动修复 + 质量趋势预测
- [ ] **LineageAgent** — `skills/lineage-agent/`，血缘自动发现 + 影响分析 + 血缘差异报告
- [ ] **ComplianceAgent** — `skills/compliance-agent/`，合规审计检查 + 审计报告生成 + 整改追踪
- [ ] **CurationAgent** — `skills/curation-agent/`，元数据策展 + 质量门禁 + 自然语言治理意图翻译
- [ ] **GovernanceTeamPipeline** — 5 个 Agent 组成的治理协作管线，复用现有 `TeamToolset` + A2A 协议

### P0 — 声明式治理引擎 Policy as Code (Alation Curation Automation 对标)

- [ ] **policy_engine.py** — 治理策略 DSL（YAML / JSON），类型: quality / classification / compliance / lineage
- [ ] **LLM 策略翻译层** — 自然语言治理意图（如"所有含身份证号的字段必须脱敏"）→ 可执行策略定义
- [ ] **持续监控** — 策略周期性检查（cron / 事件驱动）+ 违规告警 + Agent 自动修复
- [ ] **策略版本管理** — 复用现有 `prompt_registry.py` 模式，支持 dev/staging/prod 环境隔离 + 回滚
- [ ] **workflow_engine.py 扩展** — 新增 `policy_execution` 步骤类型，让策略执行纳入工作流编排

### P0 — 数据产品化框架 (Gartner MQ 2026 "数据产品策展")

- [ ] **data_products.py** — DataProduct 实体：数据契约 + 质量 SLA + 版本 + 消费统计 + 生命周期
- [ ] **数据契约 DSL** — 面向消费者的数据契约定义（schema / freshness / completeness / uniqueness）
- [ ] **质量门禁** — 数据产品发布前自动执行质检，未达标不允许发布
- [ ] **数据产品目录** — 扩展现有 Marketplace，支持数据产品的发布、订阅、消费审计
- [ ] **DB migration 064** — `agent_data_products` + `agent_data_product_contracts` + `agent_data_product_subscriptions`
- [ ] **STAC 发布器** — DataProduct → STAC Collection/Item 静态目录导出，让治理成果对外遵循 STAC 1.1.0 国际标准，用户拿到链接可在 QGIS / ArcGIS Pro "Add STAC Layer" 直接消费（依赖 v24.2 的 pystac-client 基础）
- [ ] **data_catalog ↔ STAC 双向映射** — `data_catalog.py` 资产加 `to_stac_item()` 方法，外部 STAC 端点加 `register_to_catalog()` 反向导入，实现内部资产编目（DA-{TYPE}-{SRC}-{YEAR}-{SEQ}）与 STAC 生态互通

### P1 — 统一治理仪表盘

- [ ] **GovernanceDashboard.tsx** — 治理覆盖率 / 质量趋势 / 合规状态 / Agent 执行统计四象限视图
- [ ] **治理 KPI API** — `/api/governance/kpi` 聚合治理运营指标
- [ ] **告警中心** — 治理异常的集中告警视图（复用现有 `AlertEngine`）

### P2 — 面向空间数据的治理深化

- [ ] **空间数据契约** — 数据产品契约扩展空间维度（CRS / 空间范围 / 几何有效性 / 拓扑一致性）
- [ ] **STAC Extension 对齐** — 空间契约的 CRS / bbox / 云量 SLA / 波段规范对齐 STAC EO / Projection / Raster extension，避免重新发明轮子
- [ ] **空间质检 Agent 化** — 现有 PrecisionToolset + DataCleaningToolset 包装为 QualityAgent 的子能力
- [ ] **空间血缘可视化增强** — 血缘图谱在 MapPanel 上叠加展示（数据流经过的空间范围）
- [ ] **本地 STAC Catalog 生成器** — 治理成果（清洗后矢量 / DRL 优化结果栅格 / QC 报告）一键发布到 `uploads/{user_id}/catalog/catalog.json`，形成可浏览的静态 STAC 目录树（不依赖数据库后端）

---

## 历史计划输入 — v26.0 Multi-Modal & Data Economy（原计划 2027 H1，已撤销版本承诺）

> **主题**: 多模态数据治理 + 数据要素流通与资产化支撑
>
> **历史等级假设**: L4 → **L4+**。该假设已撤销，能力条目按 NDP-2/NDP-4 退出门重新验收。
>
> **工作量估算**: 5-6 个月 | **驱动政策**: 国家数据局数据产权登记、数据资产入表、网安法修订合规审计

### P0 — 多模态数据治理 (袋鼠云多模态中台对标)

- [ ] **unstructured_governance.py** — 文档 / 图像 / 视频 / 音频的元数据采集、解析、治理
- [ ] **PDF / Word 解析器** — 结构化抽取（章节、表格、图片）+ 元数据提取 + 向量化
- [ ] **图像 / 视频元数据提取** — EXIF / 帧采样 / OCR + 场景分类
- [ ] **非结构化数据质检** — 完整性 / 格式合规 / 内容分类 / 敏感信息识别
- [ ] **统一元数据模型** — 覆盖结构化 + 空间（矢量 / 栅格 / 三维）+ 非结构化的统一 schema
- [ ] **multimodal.py 扩展** — 与 active_metadata 集成，非结构化数据自动纳入元数据管理

### P0 — 数据资产化支撑 (响应数据资产入表政策)

- [ ] **data_asset_valuation.py** — 数据资产价值评估模型（成本法 / 收益法 / 市场法）
- [ ] **资产编码体系增强** — 扩展现有 `DA-{TYPE}-{SRC}-{YEAR}-{SEQ}` 编码，对接数据产权登记
- [ ] **数据资产盘点** — 自动化数据资产清单生成（数量 / 质量 / 使用频次 / 衍生关系）
- [ ] **入表辅助报告** — 按财政部《企业数据资源相关会计处理暂行规定》生成辅助资料
- [ ] **数据产权三权分置支持** — 持有权 / 使用权 / 经营权元数据字段 + 登记信息导出

### P0 — 合规审计自动化 (响应网安法修订 + 个保法合规审计制度)

- [ ] **compliance_audit.py** — 合规检查规则库 + 自动化审计引擎
- [ ] **GB/T 45574（敏感个人信息）规则适配** — 2025.11 生效
- [ ] **GB/T 46068（跨境处理）规则适配** — 2026.3 生效
- [ ] **个人信息合规审计** — 处理 1000 万+ 个人信息的企业每两年审计（自动生成审计底稿）
- [ ] **跨境数据传输 PIP 认证辅助** — 非 CIIO 年传输 10 万-100 万人数据的合规检查
- [ ] **整改追踪工作流** — 审计发现 → 整改任务 → Agent 自动修复 → 复查

### P1 — 可信流通接口层 (预留数据空间 / 隐私计算集成位)

- [ ] **trusted_exchange.py** — 数据契约签署 + 使用权授权 + 审计日志的统一抽象
- [ ] **IDSA 连接器骨架** — 为可信数据空间预留连接器位置，实现需外部基础设施
- [ ] **隐私计算集成接口** — 对接华为等厂商的隐私计算基础设施（联邦学习 / 多方安全计算）
- [ ] **数据产权登记导出** — 生成符合国家数据局登记指南格式的 XML / JSON

### P1 — 湖仓一体适配 (航天云际 / 星环科技对标)

- [ ] **connectors/doris.py** — Doris 连接器 + 元数据采集
- [ ] **connectors/starrocks.py** — StarRocks 连接器
- [ ] **connectors/clickhouse.py** — ClickHouse 连接器
- [ ] **connectors/iceberg.py** — Iceberg 表格式元数据采集
- [ ] **空间数据湖仓统一查询** — PostGIS 空间能力 + 湖仓表数据的联邦查询

### P2 — 数据要素交易试点支撑

- [ ] **数据产品定价模型** — 基于使用频次 / 稀缺性 / 衍生价值的自动定价建议
- [ ] **数据产品交易记录** — 审计级别的交易日志 + 区块链存证预留接口

---

## 历史计划输入 — v27.0 Platform & Ecosystem（原计划 2027 H2-2028 H1，已撤销版本承诺）

> **主题**: 平台化 + 规模化 + 生态化 + 搁置项清零
>
> **历史等级假设**: L4+ → **L4.5**。该假设已撤销，平台化能力仅在 NDP-4 条件满足后启动。
>
> **工作量估算**: 6-12 个月 | **依赖**: 外部基础设施就位（K8s 集群 / Kong / Jaeger / Loki / 隐私计算底座）

### P0 — Agent 互操作协议标准化 (MCP / A2A / STAC / OGC API 对标)

- [ ] **治理 Agent MCP 暴露** — v25.0 的 5 个治理 Agent 通过 MCP 向外部工具链暴露
- [ ] **跨组织 A2A 协作** — 数据空间场景下的跨组织 Agent 协作（需可信身份 + 权限协商）
- [ ] **MCP 工具目录联邦** — 多实例 MCP Hub 的工具目录联邦查询
- [ ] **Agent 服务注册中心** — 基于现有 `agent_registry.py` 扩展，支持跨实例 Agent 发现
- [ ] **STAC API 兼容视图** — `/api/catalog` 暴露 OGC API - Features + STAC API 子集（search / collections / items），让 Claude Desktop / GPT / QGIS / ArcGIS Pro 可通过地理领域事实标准直接发现平台治理的数据产品
- [ ] **CQL2 NL2Search** — 复用 NL2Semantic2SQL 架构，自然语言 → CQL2 filter（"查 2024 年 6 月云量<10% 的山西 Sentinel-2 影像"），可独立成一篇小论文
- [ ] **OGC API 家族对齐** — 评估 OGC API Features / Coverages / Tiles / Processes 的选择性实现，与现有 WFS / WMS / MVT 管线整合

### P0 — 分布式治理架构

- [ ] **治理任务分布式调度** — 基于现有 Celery 扩展，大规模数据治理任务拆分 + 并行执行
- [ ] **metadata_federation.py** — 多实例元数据联邦同步（最终一致性）
- [ ] **水平扩展** — 治理 Agent 无状态化 + 水平扩缩容（HPA）

### P1 — Hermes 观察池择机落地

- [ ] **USER Profile 轻量层** — 用户偏好记录（输出粒度 / 常用场景 / 工作习惯）
- [ ] **历史会话召回** — PG FTS 检索 + LLM 总结，支持"上次做到哪了"
- [ ] **Skill 建议沉淀** — 从成功任务 / 高质量工作流中提炼 Skill / Prompt 建议
- [ ] **结果卡片沉淀入口** — ChatPanel "沉淀为能力"按钮，人工确认后入库

### P1 — 行业知识库深化

- [ ] **行业数据标准自动匹配** — 数据进入时自动匹配 DLTB / GB/T 21010 / CityGML 等标准
- [ ] **行业质检规则模板库** — 自然资源 / 住建 / 水利 / 测绘 / 新能源的质检规则预置
- [ ] **行业治理最佳实践案例库** — 扩展现有 `knowledge_base.py` 的 case 能力
- [ ] **行业本体库** — 基于 v15.7 XMI 领域标准 + v16.0 本体论技术，持续沉淀行业本体

### P2 — 外部基础设施落地 (搁置项清零)

- [ ] **Kong API 网关** — kong-gateway.yaml + Ingress + 插件绑定
- [ ] **Jaeger 追踪后端** — 与 OTel 现有埋点对接
- [ ] **Loki 集中日志** — LokiHandler 日志推送 + 与 trace_id 关联
- [ ] **Grafana 统一看板** — Prometheus + Jaeger + Loki 三数据源聚合

### P2 — 面向客户的产品化交付

- [ ] **治理交付模板** — 面向自然资源 / 住建 / 水利的"开箱即用"治理方案（Skill + Workflow + Policy 三件套）
- [ ] **治理成熟度评估工具** — 对标 DAMA / 《智能化数据治理能力要求》，自动生成客户治理成熟度报告
- [ ] **迁移助手** — 从传统数据治理平台（睿治 / 普元 / 国网等）的资产迁移工具

---

## v21.0+ — L4 主动式探索 (已完成项归档)

> 本节内容为 v21.0-v23.0 的历史完成项归档。原 `v25.0/v26.0/v27.0` 规划只保留为历史需求输入；当前未来主线以文首 NDP-0~NDP-4 为准。



> **主题**: 从响应式 → 主动式，从有监督 → 无监督
>
> **依据**: SIGMOD 2026 论文 L4 愿景 + Datus.ai P3 CLI 入口
>
> **目标**: 持续监控 + 自主任务发现 + 内在动机驱动

### P3 — CLI 终端接口 ✅ (已在 v15.9 实现)

- [x] **gis-agent CLI 框架** — cli.py (609 行, Typer + Rich) ✅
- [x] **chat 命令** — `gis-agent chat` 交互式 REPL + `gis-agent run "..."` 单次执行 ✅
- [x] **TUI 全屏界面** — tui.py (601 行, Textual) 三面板布局 (Chat/Report/Status) ✅
- [x] **Rich 终端渲染** — 表格/进度条/Markdown 渲染 ✅

### 跨系统血缘与数据治理 ✅ 2026-04-08

- [x] **跨系统血缘追踪** — agent_asset_lineage 边表 + 外部资产字段 (external_system/external_id/external_url) ✅ 2026-04-08
- [x] **Migration 056** — agent_asset_lineage 表 + agent_data_assets 外部字段 ✅ 2026-04-08
- [x] **register_external_asset** — 注册外部系统资产 (Tableau/Airflow/PowerBI) ✅ 2026-04-08
- [x] **add_lineage_edge** — 内部↔外部任意组合血缘边 ✅ 2026-04-08
- [x] **get_cross_system_lineage** — BFS 跨系统血缘图谱查询 ✅ 2026-04-08
- [x] **REST API** — 5 端点 (添加血缘/跨系统图谱/注册外部资产/列出系统/删除边) ✅ 2026-04-08

### API 网关与服务网格 ⏸️ (搁置: 等待 Kong 实例)

- [~] **Kong API 网关** — 统一入口，限流/熔断/认证前置 *(搁置)*
- [ ] **kong-gateway.yaml** — K8s 部署 (2 副本 + LoadBalancer)
- [x] **限流插件** — RateLimitMiddleware per-user/minute + per-IP/hour ✅ 2026-04-08
- [x] **JWT 认证** — Starlette 中间件层 JWT cookie 认证 ✅
- [x] **熔断器** — CircuitBreakerMiddleware CLOSED→OPEN→HALF_OPEN ✅ 2026-04-08
- [ ] **kong-ingress.yaml** — Ingress 配置 + 插件绑定

### 分布式追踪与可观测性 ⏸️ (搁置: 等待 Jaeger/Loki 实例)

- [x] **OpenTelemetry 全链路追踪** — HTTP/DB/Pipeline/Tool/LLM 埋点就绪，graceful degradation ✅ v23.0 *(导出需 Jaeger)*
- [~] **Jaeger 追踪后端** — 存储 trace 数据 + UI 查询 *(搁置: 需 Jaeger 实例)*
- [~] **Loki 集中日志** — 替代 stdout，与 trace_id 关联 *(搁置: 需 Loki 实例)*
- [~] **Grafana 统一看板** — Prometheus + Jaeger + Loki 数据源 *(搁置: 需 Grafana 实例)*
- [x] **observability.py 增强** — setup_otel_tracing() + get_tracer() 已实现 ✅
- [~] **LokiHandler** — 日志自动推送到 Loki *(搁置: 需 Loki 实例)*

### SIGMOD 2026 论文借鉴 (L4 能力，v22.0+)

#### **S-8: 持续监控与任务发现** ✅ 2026-04-08
- [x] **DataLakeMonitor** — 7x24 监控守护进程 ✅ 2026-04-08
- [x] **数据漂移检测** — 自动发现数据分布变化 → 触发重训练任务 ✅ 2026-04-08
- [x] **性能退化检测** — 查询延迟监控 → 触发优化任务 ✅ 2026-04-08
- [x] **优化机会发现** — 缺失索引、有益物化视图、冗余计算 → 自主优化 ✅ 2026-04-08
- [x] **任务优先级** — 多任务自主排序 (紧急度 × 收益) ✅ 2026-04-08

#### **S-9: 内在动机引擎** ✅ 2026-04-08
- [x] **IntrinsicMotivation** — 内部奖励信号驱动探索 ✅ 2026-04-08
- [x] **奖励函数** — 发现新数据源 +10，提升数据质量 +5×improvement，减少延迟 +2×reduction ✅ 2026-04-08
- [x] **探索 vs 利用** — ε-greedy 策略平衡已知优化和新机会探索 ✅ 2026-04-08
- [x] **持续自我改进** — 基于操作日志和遥测数据适应策略 ✅ 2026-04-08

### 遥感智能体 Phase 2-4 (v22.0+)

#### **Phase 2: 时空分析**
- [x] **变化检测引擎** — 双时相差异 + 指数差异 + 分类后比较 (rs_temporal.py) ✅ 2026-04-08
- [x] **时间序列分析** — Mann-Kendall 趋势 + 断点检测 (rs_temporal.py) ✅ 2026-04-08
- [x] **证据充分性评估** — 数据覆盖度 × 方法多样性 × 结论支撑强度 (rs_temporal.py) ✅ 2026-04-08

#### **Phase 3: 智能化可信度**
- [x] **代码生成执行** — validate_generated_code 安全沙箱验证 (rs_credibility.py) ✅ 2026-04-08
- [x] **幻觉检测增强** — 空间约束 Fact-Checking + 多源交叉验证 (rs_credibility.py) ✅ 2026-04-08
- [x] **多 Agent Debate** — 主分析 + 独立验证 + 证据评分 + 判定 (rs_credibility.py) ✅ 2026-04-08
- [x] **RS 领域知识库** — 光谱特性 (5 指数) + 处理流程 (3 模板) + 分类体系 (3 标准) ✅ 2026-04-08

#### **Phase 4: 高级遥感**
- [ ] **SAR/高光谱/LiDAR** 数据处理
- [ ] **深度学习推理** — segment-anything-geo / SatMAE / Prithvi
- [x] **具身执行接口** — BaseExecutor ABC + MockUAV/Satellite + 注册表 ✅ v23.0 *(对接实际硬件待定)*
- [x] **Gemma 4 + 多模型管理** — Gemma 4 31B 注册 (Gemini API + vLLM) + DB 持久化管理员配置 + 前端交互式切换 + Intent Router 可配置化 ✅ v23.0

---

## Hermes Agent 对标观察池 (暂不承诺版本)

> **定位**: 作为后续平台化增强候选项进入观察池，不纳入当前已承诺版本范围
>
> **依据**: `docs/hermes_agent_benchmark_analysis.md`
>
> **原则**: 以垂直场景落地优先，仅在有明确产品收益或客户牵引时择机迭代；优先做低成本、高复用、可独立验证的小步增强

### 候选方向 (按建议优先级)

#### P0 — 连续协作体验增强 (优先试点)
- [ ] **USER Profile 轻量层** — 记录用户偏好输出粒度、常用场景、工作习惯，用于提升跨会话协作连续性
- [ ] **历史会话召回** — 基于 SQLite/PostgreSQL FTS 检索历史对话并由 LLM 总结，用于"上次做到哪了"类问题

#### P0 — 经验沉淀闭环 (小范围验证)
- [ ] **Skill 建议沉淀** — 从成功任务、用户正反馈或高质量工作流中自动提炼 Skill / Prompt / Workflow 建议项
- [ ] **结果卡片沉淀入口** — ChatPanel 增加"沉淀为能力"入口，人工确认后入库，避免全自动写入污染资产库

#### P1 — Agent Runtime 平台化增强 (观察项)
- [ ] **执行后端抽象** — 梳理 local / docker / remote worker / arcpy worker / gpu worker 等统一执行后端接口
- [ ] **Agent 执行面安全栈** — 补齐 User Tool / MCP / Shell 级别的审批、分级权限、URL/SSRF 防护、上下文注入检测、隔离执行策略
- [ ] **轻量多入口扩展** — 先考虑消息投递/任务回执类入口，不优先建设完整 TUI 或通用消息网关

### 何时启动
- 出现明确客户需求：需要连续协作、跨端触达、远程任务托管或更强 Agent 安全治理
- 现有垂直场景（测绘质检 / 新能源 / 数据治理）交付稳定，主线需求阶段性收敛
- 能以 1-2 周试点验证价值，而非大规模架构改造

### 当前结论
- **现在不立即启动 Hermes 方向的大规模建设**
- 先保留为 roadmap 观察池，后续仅择机推进 1 个低成本 P0 试点

---

## 历史对标记录 — 标杆对标进度 (更新 2026-04-18)

> 本节记录 2026-04 的逐版本对标判断，不代表当前能力审计或未来 release 承诺。当前差距和交付判断以文首“当前基线判断”、NDP 退出门及 Cognitive Runtime 证据包为准。
>
> 新增标杆: DeerFlow (ByteDance 通用 Agent Harness) + **AgentArts (华为云企业级智能体平台)** + **Datus.ai (开源数据工程智能体 — 上下文工程 + 反馈飞轮)** + **Hermes Agent (通用 Agent Runtime — learning loop + 持久记忆 + 多入口网关)**
>
> AgentArts 对标详情见 `docs/agentarts-benchmark-analysis.md`
>
> Datus.ai 对标详情见 `docs/datus_ai_benchmark_analysis.md`
>
> Hermes Agent 对标详情见 `docs/hermes_agent_benchmark_analysis.md`

| 标杆能力 | 来源 | v16.0 ✅ | v17.1 ✅ | v18.0 ✅ | v18.5 ✅ | v19.0 ✅ | v20.0 ✅ | v21.0 ✅ |
|----------|------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
| 空间数据虚拟化 | SeerAI | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 跨系统 |
| 知识图谱语义发现 | SeerAI | 🟢 | 🟢 | 🟢🟢 本体推理 | 🟢🟢 | 🟢🟢🟢 上下文引擎 | 🟢🟢🟢 | 🟢🟢🟢 |
| 分析血缘自动追踪 | SeerAI | 🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 跨系统 |
| 行业预置模板 | SeerAI | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| Agent 对话交互 | OpenClaw | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 NL2W | 🟢🟢🟢 反馈UI | 🟢🟢🟢 | 🟢🟢🟢🟢 CLI |
| 企业级治理 | Frontier | 🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 |
| Agent 可观测性 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 全链路 |
| 多 Agent 协作 | CoWork | 🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 |
| 时空预测 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 因果推断 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 测绘质检 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 企业平台 | BCG | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 评估器+NL2W | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **Harness/App 分离** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **中间件链** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **上下文摘要** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **Guardrails** | DeerFlow | 🟡 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **Planner-Executor** | SIGMOD L3 | 🔴 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **语义算子** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **工具选择器** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **因果错误诊断** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **多模态融合** | — | 🟢🟢 基础 | 🟢🟢🟢 v2.0 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **NL2Workflow** | AgentArts | 🔴 | 🔴 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 |
| **提示词自动优化** | AgentArts | 🔴 | 🔴 | 🔴 | 🟢🟢 | 🟢🟢🟢 反馈驱动 | 🟢🟢🟢 | 🟢🟢🟢 |
| **评估器体系** | AgentArts | 🟡 | 🟡 | 🟡 | 🟢🟢🟢 15 评估器 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **产品级 UI** | Palantir | 🟡 | 🟡 | 🟡 | 🟢🟢 深色主题 | 🟢🟢 反馈UI | 🟢🟢 | 🟢🟢🟢 |
| **数据库优化** | — | 🔴 | 🔴 | 🟢🟢 asyncpg+池 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 Celery | 🟢🟢🟢 |
| **矢量切片** | — | 🔴 | 🟢🟢🟢 MVT | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **上下文引擎** | Datus | 🔴 | 🔴 | 🔴 | 🟡 BCG CM | 🟢🟢🟢 统一引擎 | 🟢🟢🟢 | 🟢🟢🟢🟢 |
| **反馈学习闭环** | Datus | 🔴 | 🔴 | 🔴 | 🟡 bad case | 🟢🟢🟢 完整飞轮 | 🟢🟢🟢 | 🟢🟢🟢🟢 |
| **语义模型标准化** | Datus | 🔴 | 🔴 | 🔴 | 🟡 自定义 | 🟢🟢 MetricFlow | 🟢🟢 | 🟢🟢🟢 |
| **参考查询库** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 NL2SQL 增强 | 🟢🟢🟢 | 🟢🟢🟢 |
| **多 LLM 切换** | Datus | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟢🟢 YAML 配置 | 🟢🟢🟢 |
| **双模式执行** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 Agentic/WF | 🟢🟢🟢 |
| **CLI 终端入口** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 gis-agent |
| **轻量部署** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 DuckDB Lite | 🟢🟢 |
| **Learning Loop** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 反馈闭环基础 | 🟡 | 🟡 观察池 |
| **持久用户画像** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **历史会话召回** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **执行后端抽象** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **Agent 执行面安全栈** | Hermes | 🟡 Guardrails | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 观察池 |
| **多入口 Agent Runtime** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 CLI | 🟡 观察池 |
| **API 网关** | — | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 Kong |
| **分布式追踪** | — | 🟡 OTel | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟢🟢🟢 Jaeger |
| **Data Agent Level** | SIGMOD | L3 | L3 | L3 | L3 | L3+ | L3+ | L3.5→L4 |

### 历史对标维度 (2026-04-21)

> 表中的 `v25.0/v26.0/v27.0` 列是当时的目标假设，已由 NDP 路线替代，不得据此声明能力已完成或仍按原版本交付。

| 标杆能力 | 来源 | v24.0 ✅ | v25.0 🎯 | v26.0 🎯 | v27.0 🎯 |
|----------|------|----------|----------|----------|----------|
| **活跃元数据 (Active Metadata)** | Atlan / Gartner 2026 | 🟡 语义层 + 基础目录 | 🟢🟢🟢 CDC 事件流 + 策略联动 | 🟢🟢🟢🟢 全模态 | 🟢🟢🟢🟢 联邦 |
| **Agentic Governance** | Alation / Ataccama | 🟡 Agent 原型 | 🟢🟢🟢 5 治理 Agent | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 MCP 标准化 |
| **声明式治理 (Policy as Code)** | Alation Curation Automation | 🔴 | 🟢🟢 LLM 策略翻译 + 规则库 | 🟢🟢🟢 合规策略 | 🟢🟢🟢🟢 |
| **数据产品化** | Gartner MQ 2026 "数据产品策展" | 🔴 | 🟢🟢 契约 + 目录 | 🟢🟢🟢 市场化 | 🟢🟢🟢🟢 |
| **多模态数据治理** | 袋鼠云多模态中台 | 🟡 `multimodal.py` 基础 | 🟡 | 🟢🟢🟢 非结构化治理 | 🟢🟢🟢🟢 |
| **数据资产化 / 入表** | 国家数据局三权分置 | 🔴 | 🟡 编码体系扩展 | 🟢🟢🟢 评估 + 辅助报告 | 🟢🟢🟢 |
| **合规审计自动化** | 网安法修订 / 个保法 | 🔴 | 🟡 合规 Agent 骨架 | 🟢🟢🟢 审计自动化 | 🟢🟢🟢🟢 |
| **MCP / A2A 互操作** | Anthropic / Google | 🟢🟢 MCP Hub | 🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 标准化暴露 |
| **STAC / OGC API 标准对齐** | Radiant Earth / NASA / MS PC / OGC | 🟡 裸 httpx + 4 预设 (v13.0) | 🟢🟢 数据产品 STAC 发布器 + 空间契约 Extension | 🟢🟢🟢 | 🟢🟢🟢🟢 STAC API 兼容视图 + CQL2 NL2Search |
| **湖仓一体适配** | 航天云际 / 星环 | 🔴 | 🟡 | 🟢🟢 Doris/StarRocks/ICE | 🟢🟢🟢 统一查询 |
| **可信数据空间** | 国家数据局行动计划 | 🔴 | 🔴 | 🟡 接口骨架 | 🟢🟢 集成华为等底座 |
| **行业知识库深化** | — | 🟢 XMI + 本体 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢🟢 自然资源/住建/水利 |


### 历史 Data Agent Level 演进假设

> 已完成版本号只说明对应功能曾交付，不自动证明整个平台达到相应自主等级。尤其 `v25.0` 以后等级是已撤销的目标假设；当前等级须在统一 Runtime、权限隔离、失败诊断和可重复 benchmark 上重新评定。

```
v15.9: L2.8 — + Planner-Executor + 中间件链 + 工具选择 + 上下文摘要
v16.0: L3   — + 语义算子 + 多 Agent 协作 + 计划精化 + Guardrails
v17.0: L3   — + 多模态融合 v2.0 (时序对齐 + 语义增强 + 冲突解决) ✅
v17.1: L3   — + 矢量切片大数据渲染 (三级自适应) + 数据资产编码 ✅
v18.0: L3   — + 应用层 DB 优化 (连接池扩容 + asyncpg + 物化视图 + 监控) ✅
v18.5: L3   — + 平台能力增强 (NL2Workflow + 提示词自动优化 + 评估器) + Palantir UI ✅
v19.0: L3+  — + 上下文工程 (统一引擎 + 反馈飞轮 + 语义模型标准化 + 参考查询库) ✅ 2026-04-08
v20.0: L3+  — + 分布式任务队列 (Redis) + 多 LLM 切换 + 双模式执行 + DuckDB Lite ✅ 2026-04-08
v21.0: L3.5 — + 跨系统血缘追踪 (外部资产 + 血缘边表 + BFS 图谱) ✅ 2026-04-08
v21.0: L3.5 — + API 网关 + 分布式追踪 + 跨系统血缘 + CLI 终端入口 (向 L4 探索)
v22.0: L4-  — + 持续监控 + 任务发现 + 内在动机 (L4 初步) ✅ 2026-04-08
v23.0: L3.5 — + Roadmap 清零 (意图消歧 v2 + DRL 约束 + 交通/设施场景 + 离线模式) ✅ 2026-04-09
v24.0: L3.5 — + @SubAgent 显式路由 + XMI 领域标准 ✅ 2026-04-19
v25.0: L4   — + Agentic Governance (5 治理 Agent + 活跃元数据 + 声明式策略 + 数据产品化) 🎯
v26.0: L4+  — + 多模态治理 + 数据资产化 + 合规自动化 + 湖仓一体 + 可信流通接口 🎯
v27.0: L4.5 — + 分布式治理 + Agent 互操作 + 经验沉淀 + 行业知识库深化 + 搁置项清零 🎯
```

### 历史治理能力估算 (《智能化数据治理能力要求》22 项)

> 以下百分比是 2026-04 的方向性估算，未经独立测评，不作为当前验收结果；`v25.0/v26.0/v27.0` 列仅保留用于追溯历史目标。

| 领域 | v14.5 ✅ | v18.5 ✅ | v21.0 ✅ | v24.0 ✅ | v25.0 🎯 | v26.0 🎯 | v27.0 🎯 |
|------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
| 数据标准 | 70% | 88% | 90% | 90% | 93% | 95% 多模态 | 98% |
| 数据模型 | 20% | 50% 本体 | 55% | 55% | 65% 语义+策略 | 75% 多模态 | 85% |
| 数据质量 | 90% | 98% | 98% | 98% | 98% | 98% | 98% |
| 数据安全 | 30% | 60% | 65% | 65% | 75% 合规 Agent | 85% 审计自动化 | 92% |
| 元数据 | 80% | 95% 语义 | 98% 跨系统 | 98% | 98% 活跃元数据 | 98% | 98% 联邦 |
| 数据资源 | 80% | 92% | 95% 分布式 | 95% | 95% | 98% 多模态+湖仓 | 98% |
| **综合** | **~62%** | **~80%** | **~84%** | **~84%** | **~87%** | **~92%** | **~95%** |

---

## 历史容量架构设想

> 本节是早期部署容量假设，并非当前 NDP 目标架构或已验证 SLO。未来物理架构由 NDP 各阶段的真实负载、隔离、RPO/RTO 和试点退出门驱动。

### 当时架构快照 (v18.5)

```
单节点部署:
- App (1 进程, Chainlit + ADK)
- PostgreSQL (华为云 RDS 托管, 连接池 20+30, asyncpg 异步)
- 物化视图 (mv_pipeline_analytics + mv_token_usage_daily)
- 本地文件存储 (uploads/) + OBS 云存储可选
- Prometheus 监控 (连接池 + 查询延迟)
- 3300+ 测试, 254 REST API, 59 迁移, 40 工具集, 26 Skills

适用场景: 开发环境、演示、<20 用户
```

### 当时目标架构设想 (v21.0)

```
分布式高可用部署:
- App (3-5 Pod, HPA 自动扩缩容)
- Celery Worker (3 Pod, 任务并行执行)
- PostgreSQL (1主2从 + PgBouncer 连接池)
- Redis Cluster (3主3从, 分片 + 副本)
- MinIO (4 节点, 纠删码 EC:2)
- Kong Gateway (2 Pod, 限流 + 熔断)
- Observability Stack (Jaeger + Loki + Grafana)

适用场景: 生产环境、>50 用户、高并发
性能指标: 500+ 并发用户, <500ms P95 延迟, 99.9% 可用性
```

---

## 历史性能目标

> 数字均为早期容量规划，尚不能视为当前实测基线或 NDP SLO。

| 指标 | v16.0 当前 | v18.0 目标 | v19.0 目标 | v21.0 目标 |
|------|------------|------------|------------|------------|
| 并发用户 | 10 | 50 | 200 | 500+ |
| 请求延迟 P95 | 2s | 1s | 800ms | <500ms |
| 数据库连接数 | 5 | 50 主 + 100 从 | 50 主 + 100 从 | 50 主 + 100 从 |
| 任务并发数 | 3 | 3 | 50+ | 50+ |
| 文件存储 | 本地 5GB | 本地 5GB | MinIO 10TB+ | MinIO 10TB+ |
| 可用性 | 单点 | 99% | 99.5% | 99.9% |
| RTO 恢复时间 | 手动 | <30 分钟 | <10 分钟 | <5 分钟 |
| RPO 数据丢失 | 未知 | <5 分钟 | <1 分钟 | <1 分钟 |

---

## 历史成本估算 (云厂商部署)

> 以下价格和拓扑仅保留作历史参考，立项时必须按目标环境、数据规模、并发和容灾要求重新测算。

### 阿里云 (华东2 区域)

| 资源 | v16.0 | v21.0 | 月成本 |
|------|-------|-------|--------|
| ECS 计算 | 1×4C8G | 5×4C8G | ¥3000 |
| PolarDB MySQL | 无 | 2C4G 主从 | ¥1500 |
| Redis 集群 | 单实例 | 4G×3 节点 | ¥1200 |
| OSS 对象存储 | 无 | 10TB | ¥2000 |
| SLB 负载均衡 | 无 | 标准版 | ¥300 |
| **总计** | **~¥500** | **~¥8000** | **16x** |

### 自建 K8s (本地机房)

- 服务器 (32C64G × 3): 一次性 ¥60,000
- 存储 (20TB): 一次性 ¥30,000
- 网络设备: 一次性 ¥20,000
- **总计**: ~¥110,000 (一次性) + 电费/运维

---

## 实施时间线（NDP 主路线）

NDP 采用退出门而不是预设版本日期驱动。未通过上一阶段退出门，不得以日历到期为由启动下一阶段。

| 阶段 | 当前状态 | 启动口径 | 完成口径 |
|---|---|---|---|
| **NDP-0 Product Charter, Governance Taxonomy & Contract Freeze** | **当前优先，2026-07-18 启动** | 本 roadmap 刷新完成 | 无 GWM/有 GWM 双层产品章程、治理三维模型、数据类型矩阵、四契约族、PlatformCore/GeoCore/Domain Pack/GWM 边界、双试点 owner/KPI/验收数据冻结 |
| **Baseline CI + Agentic Governance/Cognitive Runtime first slice** | 等待 NDP-0 与工程基线 | UWM/ArcPy 并行改动稳定；目标 commit CI 绿色；治理任务集和隔离集冻结 | 统一 RuntimeIdentity/RunnerFactory/Workspace/Policy；跨入口、恢复、回跳、租户隔离和治理变更审计通过 |
| **NDP-1 Agentic Governance & Trusted Data Product** | 规划中 | Runtime first slice 退出门通过 | 不调用 GWM 完成标准/模型/质量/安全/血缘治理、ChangeSet、审批发布和 Human/Agent/AI 一致消费 |
| **NDP-2 MMFE Semantic Fusion & Data for AI Factory** | 规划中 | NDP-1 产品和治理证据稳定 | MMFE 完成多类型语义融合产品化和效果 benchmark；DataProduct/Dataset/Model/DataDemand 全谱系可重放 |
| **NDP-3 GWM Kernel & LLM+GWM Dual Engine** | 规划中；特有增强 | NDP-2 形成可信 GWMObservationProjection；TWM/UWM 并行改动稳定 | 共享 GWM contracts/ledger/adapters 可运行；Core Platform 可关闭 GWM 独立运行；四路同题消融验证双引擎增益与 claim boundary |
| **NDP-4 Operational Learning, Federation & Ecosystem** | 条件规划 | NDP-1~3 证明业务价值、规模负载或跨组织/真实行动证据需求 | Action/Outcome 证据按等级升级；联邦权限、来源、版本、退出和审计联合演练通过；无第二权威写源 |

### 历史版本时间记录

> 下表用于追溯 2026-04 的版本记录。原 `v24.2/v25.0/v26.0/v27.0` 未来日期已经撤销，不属于当前承诺。

| 版本 | 主题 | 工作量 | 开始时间 | 完成时间 |
|------|------|--------|----------|----------|
| v17.0 | 多模态融合 v2.0 | 4-6 周 | 2026-04-01 | ✅ 2026-04-04 |
| v18.0 | 数据库 HA | 2-3 周 | 2026-04-04 | ✅ 2026-04-04 |
| v18.5 | 平台能力 + UI | 2-3 周 | 2026-04-04 | ✅ 2026-04-05 |
| v19.0 | 上下文工程 + 反馈飞轮 (Datus) | 3-4 周 | 2026-04-08 | ✅ 2026-04-08 |
| v20.0 | 分布式队列 + 体验优化 | 3-4 周 | 2026-04-08 | ✅ 2026-04-08 |
| v21.0 | 跨系统血缘 + CLI | 4-5 周 | 2026-04-08 | ✅ 2026-04-08 |
| v22.0 | L4 持续监控 + 遥感 Phase 2-3 | 1-2 周 | 2026-04-08 | ✅ 2026-04-08 |
| v23.0 | Roadmap 清零 + DRL 约束 | 1-2 周 | 2026-04-09 | ✅ 2026-04-09 |
| v24.0 | @SubAgent 路由 + XMI 域标准 | 2-3 周 | 2026-04-18 | ✅ 2026-04-19 |
| **v24.2** | **STAC 客户端标准化 + 遥感数据源扩展** | **1 周** | **原定 2026-05** | **已撤销日期，能力并入 NDP-1/NDP-4** |
| **v25.0** | **Agentic Governance Foundation** | **4-5 个月** | **原定 2026-05** | **已撤销版本承诺，映射 NDP-1/NDP-2** |
| **v26.0** | **多模态治理 + 数据要素流通** | **5-6 个月** | **原定 2026-12** | **已撤销版本承诺，映射 NDP-2/NDP-4** |
| **v27.0** | **平台化 + 生态化 + 搁置项清零** | **6-12 个月** | **原定 2027-07** | **已撤销版本承诺，映射 NDP-4** |

**当前口径**：历史功能是否“完成”仍以代码、迁移、测试和可运行证据为准；未来产品路线只采用 NDP-0~NDP-4 及其退出门。

---

## 关键文件清单 (v17.0-v21.0)

### v17.0 多模态融合 v2.0 (新增 ~15 个文件)

- `data_agent/fusion/temporal_alignment.py` (~350 行)
- `data_agent/fusion/semantic_enhancement.py` (~400 行)
- `data_agent/fusion/conflict_resolution.py` (~380 行)
- `data_agent/fusion/explainability.py` (~320 行)
- `data_agent/toolsets/fusion_v2_tools.py` (~200 行)
- `data_agent/api/fusion_v2_routes.py` (~180 行)
- `frontend/src/components/datapanel/FusionV2Tab.tsx` (~250 行)
- 测试文件 4 个 (~800 行)

### v18.0-v21.0 分布式架构 (新增 ~40 个文件)

- `data_agent/db_engine_async.py` (~150 行)
- `data_agent/celery_app.py` + tasks/ (~400 行)
- `data_agent/storage/object_storage.py` (~180 行)
- `data_agent/archival/cold_storage.py` (~200 行)
- K8s 配置 15+ 个 YAML 文件
- 数据库迁移 3 个 (059-061)

---

## 总结

GIS Data Agent 的当前主线是 **Geospatial-Native & Agentic-Native Data Platform**，优先服务自然资源和城市场景，同时治理空间与非空间多类型数据。产品不以功能数量或 Agent 等级作为唯一进度，而以治理过程是否严格可执行、数据产品是否可信可版本化、人/Agent/AI 是否一致消费，以及反馈能否形成下一版本为核心结果。

1. **无 GWM 也必须成立**：标准、模型、元数据、质量、安全、汇聚、开发、MMFE、血缘、发布和 Human/Agent/AI 消费共同构成独立完整的 Core Data Platform。
2. **AI for Data 必须 Agentic-native**：Agent 围绕强类型治理对象、Authority、Policy、Capability、Evaluator、HITL、ChangeSet 和版本状态机运行，LLM 不是数据或发布权威。
3. **Data for AI 不等于只为 GWM 准备数据**：同一 `DataProductVersion` 可派生 DatasetVersion，服务训练、评测、推理、RAG、Agent 和多类 AI；GWM 是其中最具差异化的空间智能消费者。
4. **MMFE 是主线而非后期增强**：它把空间与非空间多模态数据加工成可追溯、可评价的 `SemanticFusionProductVersion`，并以融合效果和下游增益而非流程通过验收。
5. **GWM 是特有创新内核**：共享 GWM Runtime Kernel 连接状态图、行动、转移、不确定性、EvidenceClaimLedger 及 TWM/UWM；它增强平台但不侵入基础治理依赖。
6. **LLM + GWM 是双智能引擎产品命题**：LLM 提供语义、知识和治理编排，GWM 提供空间世界状态、过程、推演和证据边界；必须用传统、LLM-only、GWM-only、LLM+GWM 四路同题评测证明组合价值与原创性。
7. **真实 Action-Outcome 是能力升级门，不是平台启动门**：没有真实数据时仍可交付状态模型、机制/条件模拟和证据有界规划；只有在证据满足时才升级真实行动效果与决策优势 claim。
8. 交付从 NDP-0 产品章程和治理契约冻结开始，经 Agentic Governance/Cognitive Runtime 与 NDP-1 Trusted Data Product、NDP-2 MMFE/Data for AI，再进入 NDP-3 GWM 双引擎；NDP-4 保持运营学习、联邦和生态的条件路线。
9. 旧 `v25.0/v26.0/v27.0` 规划、对标表、等级和容量数字保留为历史输入，不再构成版本承诺；所有后续实施以 Core Platform 与 GWM-enhanced 两套独立退出门验收。
