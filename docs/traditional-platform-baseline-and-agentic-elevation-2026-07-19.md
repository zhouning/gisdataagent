# 从传统时空数据中台到 Agentic Data Platform：能力基线与升维设计

**日期**：2026-07-19

**基线来源**：`/Users/zhouning/Downloads/时空数据中台产品详细设计v3.0.0.0.docx`

**复审覆盖**：逐章阅读完整正文与表格，并核对功能架构、技术架构、数据架构、安全架构、数据汇聚、数据开发、数据服务和元数据等关键架构图；不是仅按目录或功能名称对标。

**目的**：把传统时空数据中台作为 GIS Data Agent 的产品能力下限，而不是实现模板；明确哪些能力必须继承、哪些复杂度应消除、哪些能力必须由 Agentic 架构升维。

**关联文档**：

- [企业级架构复审](architecture-review-2026-07-19.md)
- [总体架构 Roadmap](roadmap.md)
- [ADR-004：传统平台能力下限与 Human/Agent 双入口](architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)
- [ADR-005：DataOps 与 AgentOps 双运营闭环](architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md)

## 1. 复审结论

传统平台虽然以菜单、画布、向导、脚本和多套中间件驱动，使用复杂度较高，但它已经形成完整的数据生产与运营体系：

```text
规划 -> 接入/汇聚 -> 存储分层 -> 建模 -> 开发 -> 调度
 -> 质量/安全/审批 -> 资产 -> 服务 -> 分析/地图 -> 运营
```

GIS Data Agent 当前在 Agent、语义、标准、智能问数、MMFE 和 GWM 上投入较深，但在数据源管理、批流文件汇聚、专业开发工作台、服务发布运营、资产运营、通用审批通知和生产部署等基础能力上，没有形成与上述闭环同等清晰的产品合同。此前只关注数据分层、湖仓、元数据和调度仍然不够，因为它们是平台脊柱，不是完整产品。

下一代目标必须同时满足：

1. **不低于传统平台的任务覆盖面**：传统平台能完成的核心生产任务，在下一代都有可验证路径。
2. **不继承传统平台的操作负担**：用户不需要在多个模块重复配置源、schema、权限、质量、调度和服务。
3. **不把对话当作唯一入口**：可视化、SQL、Python/Notebook、API/CLI 和 Agent 使用同一底层对象与状态机。
4. **Agent 不能绕过工程纪律**：自然语言产生的是可审查的 plan、contract、DAG、policy 和 changeset，执行仍由确定性控制面完成。
5. **更强必须可度量**：用完成时间、配置步骤、首跑成功率、恢复时间、人工修正率、可追溯率和下游价值证明升维。

## 2. 传统平台提供的真实能力基线

### 2.1 门户、工作区与统一支撑

旧平台不是一组后端服务，而是有统一产品入口：门户首页、工作区、资产管理、资产统计、资产一张图、知识库，以及统一认证、权限、目录、调度、审批、消息、日志和多租户。

下一代必须保留统一工作入口，但不照搬十几个平级菜单。建议采用四个稳定工作面：

- **Discover**：搜索、目录、地图、资产详情、血缘、质量、使用与申请。
- **Build**：接入、建模、SQL/画布/Notebook、试运行、发布。
- **Operate**：Run、调度、质量问题、服务、SLO、告警、成本和恢复。
- **Govern**：标准、合同、owner/steward、权限、审批、审计和保留。

对话助手常驻四个工作面，读取当前上下文并生成可审查操作，不另建一套“Agent 页面里的隐式平台”。

### 2.2 数据规划与架构

旧平台覆盖数仓分层、数据存储、数据架构、数据标准和元数据规划。下一代必须把这些从文档和人工配置升级为可执行 `DataProductBlueprint`：

```text
Domain + owner + source
 -> layer/storage placement
 -> schema/model/contract
 -> quality/security/SLO
 -> pipeline + projections
 -> cost/capacity + retention
```

Agent 可从需求和源数据起草 blueprint、识别缺项并评估影响；架构师/数据 owner 审批后才生成资源和任务。Blueprint 与实际 ResourceVersion/Run 持续对账，防止设计和运行漂移。

### 2.3 数据源、汇聚与同步

传统基线覆盖：

- 关系/空间/分析数据库、消息、API、S3/NAS/FTP/SFTP 和空间文件。
- 物理汇聚与虚拟汇聚。
- 手工、定时批处理、CDC、消息监听和触发器/微批。
- 非结构化大文件分片、断点续传、校验、解析和元数据登记。
- Append、Overwrite、Merge/Upsert、临时表原子切换和失败回滚。
- 贴源表配置、字段映射、目标映射、运行监控、表/字段血缘和资产沉淀。

下一代不承诺首期复制旧平台全部数据库认证矩阵，但必须提供统一 `Source -> SyncDefinition -> SyncRun` 合同和 connector certification matrix。每种接入类型至少有一个真实后端通过：发现、预览、全量、增量、删除、schema drift、重放、对账、凭据轮换和故障恢复。

Agentic 升维：用户描述目标后，Agent 自动完成能力探测、采样 profiling、主键/watermark/CRS 推断、目标层建议、资源与成本估算、数据合同和质量门草稿；有风险的推断必须展示证据和不确定性。

### 2.4 存储、湖仓与数仓分层

传统平台已经明确 ODS/DWD/DWS/ADS、主题/核心库、Iceberg 数据湖、对象存储、Spark/Flink 计算和数据库/GIS serving 的组合。下一代采用 ADR-001 定义的一套逻辑层和可配置 provider profile：

```text
Landing/Raw -> ODS/Bronze -> DIM+DWD/Silver
 -> DWS/Gold -> ADS/Serving
```

默认数据湖存储为 MinIO，默认批/流计算为 Spark/Sedona 与 Flink；Azure 等云平台可以通过认证 adapter 替换对象/湖存储、catalog 和计算能力；PostGIS 或 DuckDB/Spatial 可以作为单机、边缘和较小数据集的轻量存算一体 profile。存储、湖表/catalog、计算必须分别配置，不能把云替换简化为 URI 替换。

升维重点不是换名词，而是让 placement、provider capability、partition、format、retention、compaction、snapshot/checkpoint、serving projection、data sovereignty 和成本成为 blueprint/metadata 的可执行策略；Agent 可以建议优化，但不能无审批改写 binding 或权威表。无论使用哪个 profile，逻辑分层、ResourceVersion、质量门、血缘、Run/Artifact、发布和回滚合同不变。

### 2.5 数据模型与语义

传统基线包括关系模型、维度模型、模型目录、版本、上线和下线。下一代必须同时保留：

- 概念/逻辑/物理模型，关系与维度建模。
- GIS 对象身份、geometry/CRS、空间/时间粒度和拓扑约束。
- 模型版本、diff、兼容性、DDL/湖表定义、部署和回滚。
- 从物理 schema 反向发现，从标准/本体/业务术语正向生成。

Agentic 升维：Agent 生成候选模型、字段映射、SCD/事实维度建议和迁移计划；用真实数据 profile、标准与 competency query 验证，而不是仅生成 DDL。

### 2.6 数据开发与算子体系

传统基线提供画布、单机/Spark 算子、SQL/Python、Notebook、模型模板、参数与节点配置、逻辑校验、试运行、中间结果预览、发布为任务、依赖和正式调度。它还有明确的交互开发与生产运行分界。

下一代必须提供同一个 `JobDefinitionVersion/TaskGraph` 的多入口编辑：

- 可视化 DAG：面向低代码和运维可读性。
- SQL editor：面向数据工程与分析开发。
- Python/Notebook：面向探索、GIS 和 AI。
- API/CLI：面向 CI/CD 和平台集成。
- Agent：面向意图到可审查 DAG、参数、测试和发布 changeset。

所有入口共享算子注册表、typed input/output、preview sandbox、版本、权限、测试、发布和 lineage。Notebook 发布必须固化代码、环境、依赖、输入版本和资源规格，不能直接把交互 session 当生产任务。

### 2.7 统一调度、工作流与审批

旧平台把任务调度与业务审批区分开：调度处理计算依赖，流程中心处理审核流转。下一代也必须区分但共享事件和身份：

- **Orchestration**：schedule/event/manual/Agent trigger、Run/Attempt/Lease、资源、重试、恢复和 artifact。
- **Approval Case**：发布、数据申请、敏感操作、模型/规则/服务变更的审批、会签、委托、超时和审计。

Agent 可以补齐参数、解释影响和提醒审批人；不能冒充审批人，也不能把 HITL 对话临时状态当正式审批记录。

### 2.8 元数据、血缘与全域检索

传统基线包含管理元数据、业务资源关联、手工/批量/自动采集、存量同步、全文检索、标签筛选、数据湖目录集成和表/字段血缘。下一代统一到 ADR-002：

- 一个 ResourceURN/Version 模型覆盖数据、任务、服务、模型、prompt、tool 和 GWM 产品。
- 技术、业务、操作、质量、安全和使用元数据统一关联，但按 authority source 分权维护。
- 运行自动产出 lineage，人工关系带 evidence/approval。
- 关键词、自然语言、地图范围、时间、分类、owner、质量、权限和 lineage impact 都可检索。

Agentic 升维：元数据从被动登记升级为主动控制面，持续发现漂移、孤儿资产、失效 owner、陈旧数据、断裂血缘和不兼容变更，并生成修复 changeset。

### 2.9 数据质量与问题闭环

传统基线包括质量概览、规则、方案、任务、评分、问题分布和结果面板。下一代至少要实现：

```text
RuleVersion -> RuleSet/QualityContract -> AssessmentRun
 -> Issue -> Assignment/Remediation -> Recheck -> Trend/SLA
```

质量不能只是一次 profiling 报告，必须成为 layer transition 和 product publish 的机器门。Agent 可以从标准、profile 和历史问题推荐规则、解释根因、定位影响和生成修复方案；规则启用和自动修复遵守风险策略与审批。

### 2.10 数据安全与租户隔离

传统基线覆盖分级分类、脱敏、授权、白名单、统一身份/授权/审计/监控，以及表、字段、空间范围和时间范围权限。下一代必须扩展为：

- Subject、service、Agent 和 executor 的统一身份。
- resource/table/column/row/spatial/temporal/action/purpose 多维 policy。
- 静态导出和动态查询脱敏、加密/密钥引用、下载水印和审计。
- 数据申请、到期回收、紧急授权和 break-glass 审计。
- prompt/tool/model/data 的组合授权，防止 Agent 通过工具链绕过数据权限。

Agent 只能在用户委托和策略交集内行动；安全解释必须展示实际命中的 policy，而不是给出语言模型判断。

### 2.11 数据资产与运营

传统基线包含资产目录、检索、标签、地图、统计、一张图、申请分发和知识库。下一代必须把 `DataProductVersion` 做成可运营产品：

- owner/steward、描述、合同、版本、质量、SLA、敏感级别和适用范围。
- 地图/时间预览、sample、schema、lineage、相关产品和使用说明。
- 使用量、复用、热度、评分、问题、成本、freshness 和消费者影响。
- 申请、审批、订阅、交付、到期和变更通知。
- draft/active/deprecated/retired 生命周期和替代产品指引。

Agentic 升维：基于任务上下文推荐“可用且有权”的产品，解释为什么适用；主动发现重复资产、低质量高使用资产和即将破坏消费者的变化。

### 2.12 数据与 GIS 服务产品化

传统基线覆盖向导/SQL/模板 API、外部服务注册、二维/三维/影像/目录服务、数据分发和服务监控。下一代服务面至少覆盖：

- SQL/attribute API、OGC/STAC、MVT/map、raster/COG、file/export、Agent context 和 AI/GWM projection。
- publish/register/version/deploy/auth/quota/rate limit/cache/monitor/deprecate/retire。
- request/response schema、sample、SLA、policy、consumer、usage、cost 和 rollback。
- 服务从 DataProductVersion 可重建，不把临时表或 Notebook 结果直接暴露为长期接口。

Agentic 升维：用户可描述服务用途和消费者，Agent 生成 API/地图投影、策略、测试和部署计划；根据使用与 SLO 建议物化、缓存或空间索引，并通过审批 changeset 实施。

### 2.13 分析、智能问数与二三维空间体验

传统基线包含图表、大屏、智能仪表盘、智能问数和二三维一张图。下一代不能只返回聊天文本：

- 可信 NL2Semantic2SQL、SQL/空间分析、表格/图表/地图联动。
- 2D vector/raster 和 3D terrain/model/point-cloud 的统一场景目录与版本。
- 保存、分享、复现和发布分析视图；每个结论绑定查询、数据版本、时间和权限。
- Agent 在地图选择、时空范围和当前图层上下文中工作，能解释口径和不确定性。

### 2.14 运维、部署与交付

传统基线明确传统进程、Compose、Kubernetes 非高可用/高可用、容量、性能、安全、信创替代和商业许可。下一代首期不需要复制微服务数量，但必须把交付当产品能力：

- 单机/离线开发包、Compose 试点包、Kubernetes 生产包使用同一配置 schema。
- install/upgrade/rollback、schema migration、secret、license、backup/restore 和 preflight。
- application、scheduler/worker、PostgreSQL/PostGIS、MinIO/Iceberg、Redis、GIS serving 的健康与容量。
- SLI/SLO、告警、Run 诊断、审计、成本和恢复演练。
- 数据源/数据库/GIS/对象存储的认证兼容矩阵；“支持”必须有版本和集成测试证据。

Agentic 升维：Agent 汇总故障上下文、定位失败层、提出恢复或扩容建议并模拟影响；生产变更仍由 runbook/policy/approval 执行。

### 2.15 扩展生态

传统平台支持 API 和算子扩展。下一代统一扩展合同覆盖 connector、operator、quality rule、service projection、Agent skill、MCP/A2A tool 和 domain pack。扩展必须声明：typed schema、权限、side effect、resource requirement、version、test、owner、license 和 compatibility；注册后自动进入元数据、调度和审计，而不是只加入工具列表。

### 2.16 DataOps 与 AgentOps

传统平台虽然没有使用这些新名词，但已经具备 DataOps 的用户结果：数据规划、开发、调度、质量、安全、审批、发布、监控、资产运营和恢复。下一代不能只继承功能，而必须把它们组织成持续运营闭环：

```text
DataOps:
DataProductSpec -> CI/Contract/Quality -> Promotion/Release
 -> DataRun/SLO/Observe -> Incident/Remediation -> Replay/New Version

AgentOps:
AgentSpecBundle -> Eval/Safety/Cost -> Approval/Canary
 -> AgentRun/ToolCall/Online Verdict -> Guardrail/Incident
 -> Rollback/Feedback -> New AgentSpecVersion
```

DataOps 管理数据产品可靠交付；AgentOps 管理 Agent、Prompt、Model、Tool、Skill、Policy、Memory/Context 和副作用的可靠运行。MLOps/LLMOps 是 AgentOps 的子域，不等于 AgentOps。两者共享 Resource/Version、Metadata、Orchestration、Policy、Artifact、Audit、SLO、Incident 和 Change 合同，但保留 `DataRun` 与 `AgentRun` 两套领域状态机。

AgentOps 的完成口径不能是“有 Prompt Registry、Agent Registry、离线 Eval 或 Trace”。必须具备 bundle 评测、灰度/影子发布、线上 verdict、工具调用和策略事件、预算、人工接管、安全/质量事故、禁用/回滚和反馈回灌；DataOps 的完成口径必须具备 CI/CD、promotion、数据观测、freshness/quality SLO、事故、修复、重放和新产品版本。

## 3. 当前能力对标矩阵

成熟度定义：

- **可运行闭环**：真实后端和用户入口可完成完整生命周期。
- **局部可用**：有实质代码/API/UI，但缺关键状态或跨模块闭环。
- **组件/实验**：只有适配器、工具、配置、smoke 或专项实现。
- **缺失**：未发现能支撑该产品任务的实现。

| 能力域 | 传统平台基线 | GIS Data Agent 当前事实 | 判断 | 下一代目标阶段 |
|---|---|---|---|---|
| 门户/工作区 | 首页、工作区、资产与知识入口 | 对话、地图、DataPanel 和大量领域 Tab | 局部可用，信息架构偏功能堆叠 | AR-4 |
| 数据规划 | 分层、架构、存储、标准、元数据规划 | 新 roadmap/ADR 与 standards 存在，无可执行 blueprint 工作台 | 组件/设计 | AR-3 |
| 数据源管理 | 多库/消息/API/文件，连通与目录发现 | virtual sources/connectors 覆盖多种 GIS/API/数据库查询；凭据、认证矩阵和同步合同不统一 | 局部可用 | AR-2 |
| 批量/增量/实时汇聚 | 定时、CDC、消息、触发器/微批 | PostGIS intake、Redis stream、局部 pipeline；无生产 CDC 和统一 SyncRun | 组件/实验 | AR-2 认证首条 CDC/事件流；AR-8 扩展高吞吐实时 |
| 大文件/非结构化 | 分片、断点、校验、目录同步、解析 | 文件上传、对象存储、MMFE 解析组件存在；未形成可靠传输闭环 | 局部可用 | AR-2 |
| 湖仓与分层 | ODS/DWD/DWS/ADS、Iceberg、Spark/Flink、serving | MinIO/Iceberg/Sedona 配置与 smoke，尚无 Flink、云/轻量 provider 和通用生产链 | 组件/实验 | AR-2 |
| 数据模型 | 关系/维度模型、目录、版本、上线/下线 | semantic model、Standards data-model snapshot/XMI/DDL 有实质能力，未统一物理部署生命周期 | 局部可用 | AR-3 |
| 数据开发 | 画布/SQL/Python/Notebook、试运行、发布 | WorkflowEditor、工具/模板和 pipeline 丰富；未统一到可生产的 typed operator/preview/release | 局部可用 | AR-3 |
| Notebook 生产化 | JupyterHub、依赖/代码快照、发布调度 | 未发现完整 JupyterHub -> JobDefinition -> Run 产品链 | 缺失 | AR-3 |
| 统一调度 | DAG、依赖、定时、监控、多执行器 | 多套 scheduler/queue/gateway，存在耐久性缺陷 | 局部但 P0 风险 | AR-1 |
| 审批/通知 | 通用流程、消息、日志、多租户 | HITL、Standards review、数据分发审批和 Agent messaging 分散 | 局部可用，非统一 Case/Inbox | AR-3/AR-4 |
| 元数据/血缘 | 多源采集、全文检索、湖目录、表字段血缘 | catalog/metadata/intake/lineage/semantic/Standards 多套实现 | 局部但 P0 分裂 | AR-1 |
| 全域发现 | 全文、标签、分类、地图发现 | catalog search、KB/semantic search、地图能力分散 | 局部可用 | AR-4 |
| 数据质量 | 规则、方案、任务、评分、问题与趋势 | 规则、trends、QC monitor、Standards 派生存在；未统一发布门和 Issue 闭环 | 局部可用 | AR-3 |
| 数据安全 | 分级、脱敏、授权、白名单、多维权限 | auth/RLS/classification/audit 有实现；执行路径不一致，脱敏/空间时间策略不足 | 局部但 P0 风险 | AR-1/AR-3 |
| 资产运营 | 目录、标签、统计、地图、申请、评价/热度 | catalog、tags/usage、distribution/review 有代码；产品版本和运营面未统一 | 局部可用 | AR-4 |
| 数据/API 服务 | 向导/SQL/模板发布、注册、鉴权、监控 | REST/MCP/OGC/MVT 多接口；未发现统一 ServiceDefinition 生命周期 | 组件/局部 | AR-4 |
| 二三维/影像 | 2D、3D、影像和统一一张图 | MapPanel、Map3DView、tiles、STAC/remote sensing 存在 | 局部可用，未绑定 DataProductVersion | AR-4 |
| 智能问数/分析 | 语义问数、规划、安全执行、图表结论 | NL2Semantic2SQL、图表、地图和 Agent 能力较强 | 接近核心差异能力，仍需产品版本/权限闭环 | AR-4/AR-5 |
| 运维/部署 | 传统/Compose/K8s/HA、容量、安全、许可 | Compose/K8s/metrics/trace/DB backup 存在；CD、联合恢复和 HA 证据不足 | 局部可用 | AR-0/AR-4/AR-8 |
| 扩展 | API、算子 | tools、skills、plugins、MCP/A2A、connectors 很丰富 | 组件丰富，缺统一扩展治理合同 | AR-3/AR-5 |
| DataOps | 数据产品 CI/CD、质量、调度、发布、监控、事故和恢复闭环 | source/workflow/quality/catalog/Run/CI 组件存在，但缺统一 promotion、DataIncident、data observability、replay 和可靠性运营 | 局部组件，未形成闭环 | AR-0/AR-2/AR-3/AR-4 |
| AgentOps | Agent bundle 版本、评测、审批、灰度、运行观测、安全、预算、事故和回滚 | Agent registry、Prompt version、eval history、OTel、guardrail、feedback、cost guard 分散存在；缺 AgentSpec/DeploymentRevision/online verdict/incident 状态机 | 局部组件，未形成闭环 | AR-0/AR-1/AR-5/AR-6 |

## 4. 不照抄的内容

以下是传统平台的实现选择或复杂度，不自动成为下一代依赖：

| 传统做法 | 下一代处理 |
|---|---|
| 每个业务域独立菜单、配置和元数据副本 | 四个工作面 + 一个 Resource/Run 模型；渐进披露专业参数 |
| 微服务、注册中心、消息中心和多存储先行 | 模块化控制面；有独立扩缩容/隔离证据后再拆服务 |
| DolphinScheduler、GPA、Spark/Flink 多层定义 | 一个 JobDefinition/TaskGraph，按 capability 路由多 executor adapter |
| Gravitino、ES、Neo4j 各自形成目录/索引/图事实 | PostgreSQL metadata authority；外部系统只作物理 catalog 或读投影 |
| 为“支持广”默认部署十几种中间件 | connector/plugin certification，按场景装配 |
| 湖和仓各建重复物理副本 | 一套逻辑 Bronze/Silver/Gold + serving；默认 Iceberg，云/轻量 profile 保持相同版本与门禁 |
| 画布或向导成为唯一生产定义 | 画布/SQL/Notebook/API/Agent 共享可移植 definition-as-code |
| 用户手工串联元数据、质量、调度、权限和服务 | blueprint + policy/evaluator 自动补齐，changeset 一次审批 |
| “有页面/有接口”即标记完成 | 真实后端、生命周期、故障恢复和用户任务验收后才 verified |

## 5. Agentic 升维模型

### 5.1 Human/Agent 双入口

```text
Human: Visual | SQL | Notebook | API/CLI
                     |
                     v
           Shared typed definitions
                     ^
                     |
Agent: intent -> evidence -> plan -> preview -> changeset -> approval
                     |
                     v
Metadata + Policy + Orchestration + Artifact + Audit control planes
```

Agent 不生成另一套不可见 pipeline。用户可在对话、画布、SQL 和 Run 详情之间往返，看到同一个 definition、参数、输入版本、执行状态和结果。

### 5.2 Intent-to-DataProduct

目标体验示例：

> “接入这套年度地类图斑，每月检查更新，统一到 2000 国家大地坐标系和国标地类，生成区县变化指标，发布地图、API 和 Agent 可用数据。”

系统应生成而不是直接执行：

1. Source capability/profile 和风险证据。
2. DataProductBlueprint、分层与物理 placement。
3. schema/model/field mapping/standard version。
4. batch/CDC 策略、typed TaskGraph、资源与成本估算。
5. 质量、安全、owner、SLO、retention 和 approval。
6. PostGIS/STAC/API/Agent projection 和 consumer impact。
7. preview/golden reconciliation 和 changeset。

审批后统一调度执行；任何失败都能定位到 Run/Attempt/Artifact，修复后从 checkpoint 重放。

### 5.3 主动治理与运营

Agent 主动能力必须由事件和 evaluator 驱动，而不是定期生成泛化建议：

- schema drift -> impact -> compatibility verdict -> migration proposal。
- quality/SLA failure -> root cause evidence -> affected products -> remediation plan。
- stale/duplicate/orphan asset -> owner notification -> merge/retire proposal。
- failed/slow Run -> executor/resource/partition diagnosis -> retry or optimization changeset。
- service usage/SLO change -> cache/materialization/index proposal。
- new AI/GWM demand -> missing field/time/space/quality requirement -> DataDemand 回写。

高风险写入、发布、授权、删除、模型部署和生产扩缩容必须经过 policy/approval。

### 5.4 复杂度预算

下一代比传统平台好用必须有量化门：

- 常见接入到首个可用产品的人工配置步骤和耗时显著下降。
- 同一信息只录入一次；source/schema/owner/policy 在下游自动引用。
- 80% 常见任务使用 Easy path，专业用户可展开完整参数且不损失控制力。
- Agent 提案展示证据、假设、影响、成本和 rollback，不能只显示“已完成”。
- 所有 Agent 产生的 definition 可导出、测试、review、diff 和由非 Agent 路径重放。

具体阈值由 AR-0 基于旧平台代表任务和目标用户测试冻结，不在架构文档中臆造。

### 5.5 AgentOps 升维

AgentOps 的 Agent bundle 必须把 Agent、Prompt、ModelBinding、Tool/Skill、Policy、Memory/Context、EvaluationBinding 和 DeploymentRevision 作为一个可审查版本单元。运行时记录 `AgentRun -> TaskStep -> ToolCall -> Artifact/Observation`，并关联数据产品版本、权限决定、成本、策略 verdict 和副作用。

发布流程必须是：离线任务/安全/工具准确性/成本评测 -> 审批 -> shadow/canary -> 线上质量与安全 verdict -> promotion 或 rollback。任何 stuck loop、提示注入、越权空间访问、错误工具写入、预算超限和连续质量回退都必须触发 AgentOps incident；Agent 可以提出修复 changeset，但不能自动绕过审批成为 active 版本。

## 6. 强制能力回归门

GIS Data Agent 只有以下 12 项代表任务全部通过，才能宣称“下一代时空 Data Platform 基线完成”。其中前 10 项继承传统平台用户结果，第 11 项验证可配置引擎架构，第 12 项验证 Agentic 升维：

1. 注册真实数据库/对象存储/API，完成凭据、连通、发现、profile 和 owner 登记。
2. 完成一次全量、一次增量/微批、一次 Flink CDC/事件流和一次大文件断点恢复，并可对账、重放和处理 schema drift、watermark/offset。
3. 设计一个关系/维度/空间模型，生成兼容性 diff，部署到 Silver/Gold 并可回滚。
4. 同一变换分别从可视化/SQL 或 Notebook 和 Agent 入口创建，发布后解析到同一 JobDefinitionVersion。
5. scheduler/worker 故障后 Run 可接管，不重复写入或发布产品。
6. 质量失败、安全策略失败和未审批 changeset 均不能发布。
7. 在目录和地图中发现产品，完成权限申请、订阅、版本变更通知和审计。
8. 从同一 DataProductVersion 发布 API、地图/STAC 和 AgentContext，完成监控、回滚和下线。
9. 智能问数/空间分析的结论可追溯到语义口径、查询、数据版本和权限。
10. 从备份恢复控制面、所选 Storage/Table binding 和 serving projection，达到该 DeploymentProfile 冻结的 RPO/RTO。
11. 同一代表 pipeline 可在默认湖仓和 PostGIS/DuckDB 轻量 profile 上运行，并通过跨引擎 golden equivalence；Azure 代表 adapter 通过权限、版本、提交、取消、reconcile 和监控认证。
12. Agent bundle 经过离线评测、shadow/canary、线上 verdict、工具/策略/预算观测、incident/rollback 后，对同一代表任务在步骤、耗时、首跑成功率或问题恢复上优于传统路径，同时保留专业可控性。

每项任务必须同时提供实现、真实后端、自动化测试、运行证据和用户验收；缺任一项不能标记 `verified`。
