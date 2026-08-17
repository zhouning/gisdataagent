# GIS Data Agent — 总体架构 Roadmap

**Last updated**: 2026-07-24

**Status**: Architecture reset, authoritative mainline

**Current gate**: AR-0 Architecture, Schema and Runtime Truth Freeze

**Next delivery gate**: AR-1 Unified Metadata and Orchestration Control Planes

**Historical roadmap**: [roadmap-history-through-2026-07-18.md](roadmap-history-through-2026-07-18.md)

> 本文是唯一有效的总体交付顺序。领域 roadmap、研究计划、版本历史和功能清单只能作为输入，不能改变本文的依赖顺序和退出门。

## 1. 架构重置结论

GIS Data Agent 的产品定义调整为：

> 以传统时空数据中台的完整生产能力为下限，以 DataOps 持续交付和可靠运营为数据产品底座，以 AgentOps 管理 Agent 的评测、部署、安全和运行闭环，以统一元数据和统一调度作为平台控制脊柱，以 LLM 可选的 Web/API/SDK/CLI/TUI/Notebook/Agent 多入口降低复杂度，以 GWM 作为可插拔空间世界认知增强的 Data + AI 平台。

过去的路线把 Agent、标准、本体、MMFE、TWM/UWM、前端和部署能力分别扩张，却没有先建立统一的数据生产主链、平台控制脊柱、DataOps/AgentOps 运营闭环和产品能力下限。此次重置纠正十一个问题：

1. **先冻结 schema/config/runtime 真值**：迁移版本重复、失败继续和环境配置漂移不解决，任何新平台表都没有可信地基。
2. **统一元数据必须采用双层 Metadata Fabric**：OpenMetadata 负责 owner、domain、术语、分类、质量、generic lineage 与治理 catalog；Gravitino 负责 technical metadata lake、metalake/catalog 与跨 catalog federation；GIS Data Agent 只维护 ResourceURN mapping、空间/证据 extension 与 control/evidence contracts。
3. **统一调度必须采用分层运行时**：DolphinScheduler 统一 DataOps 的 DAG、定时、补数、资源队列和 Spark/Flink 任务；Temporal 统一 Agent/GWM 的长时等待、审批和补偿；GDA 只关联 PlatformRun，不能依赖 Web 进程或自研 scheduler 生命周期。
4. **数据底座必须先于 Agent 智能升级**：没有可执行的数据分层、质量门禁、血缘和版本，Agent 只能操作文件和临时表。
5. **湖仓不是远期生态能力，也不是固定厂商栈**：默认 profile 使用 MinIO + Iceberg、Spark/Sedona + Flink 和 PostGIS serving；相同逻辑合同可绑定 Azure 等云平台能力，或以 PostGIS/DuckDB 运行轻量存算一体 profile。
6. **传统平台能力是下限，不是模板**：数据规划、源与汇聚、建模、开发、质量、安全、资产、服务、地图、审批和运维的代表任务必须有完整路径；不照搬其菜单、微服务和中间件。
7. **Agentic 不等于 LLM 前提或取消专业工作台**：Visual/SQL/Notebook/API/SDK/CLI/TUI 和 Agent 必须通过同一 `CapabilitySpec` 编辑、提交和观察同一 typed definition、Run 和 Artifact；无 LLM profile 保留完整确定性平台路径，Agent 不能另建隐式 pipeline。
8. **GWM 是消费者和增强内核**：GWM 消费已治理的数据产品，不能替代数据底座，也不能成为基础治理的前置依赖。
9. **DataOps 是 P0 平台能力**：数据产品必须有 CI/CD、质量门、promotion、运行观测、SLO、事故、恢复和反馈闭环，不能只交付一个能运行的 pipeline。
10. **AgentOps 是独立但共享控制面的 P1 能力**：Agent bundle、评测、灰度、AgentRun、ToolCall、安全、预算、事故、回滚和反馈必须有生命周期，不能把 Prompt registry 或 Agent trace 当作完成。
11. **GIS 服务发布是独立 P0 架构域**：不能用一个 `ServiceDefinition` 名词或若干 OGC/MVT/STAC endpoint 代替发布平台；必须分别建设服务控制面、可认证 provider runtime 和统一 gateway/operations，覆盖图层、样式、二维/三维、部署 revision、消费者、SLO、原子切换、缓存一致性、回滚和退役。

从本次刷新开始，新增 Agent、模型、工具、Tab、数据库或协议，必须说明它服务哪个数据产品、处于哪个生命周期阶段、读写哪一层、由什么规则验收。不能回答的工作不进入主线。

## 2. 产品边界与约束

### 2.1 优先场景

1. 自然资源：地类图斑、规划管控、变化监测、遥感证据和治理报告。
2. 城市：设施、道路、人口、环境、宜居性状态和干预证据。
3. 空间原生但不排斥非空间数据：关系表、文档、图像、视频、日志、模型特征和评测数据可以独立治理，也可以与空间对象关联。

### 2.2 约束

- 支持私有化和离线部署，默认不能依赖外部 SaaS 数据平面。
- 当前团队和运行边界不支持全面微服务化，先采用模块化单体和独立计算运行时。
- 数据规模从单用户文件到千万级要素已有证据；TB/PB 级只作为架构容量方向，未通过基准前不得宣称已支持。
- PostgreSQL/PostGIS、MinIO/S3、Spark/Flink、现有 Standards Platform 和 MMFE 必须通过 adapter 增量演进，不做一次性重写。
- 存储后端、湖表格式/catalog 和计算执行器是三个独立配置维度；平台提供默认值，但 Blueprint/DeploymentProfile 不得硬编码单一云厂商或引擎。
- 传统平台能力等价按用户结果判断，不按菜单、中间件或 connector 数量判断；首期只认证代表数据源和任务，保留扩展合同。
- 当前工作树并行改动很多；每个架构阶段必须在独立变更边界内完成并验证。

### 2.3 非目标

- 不建设通用云数仓、通用 GIS 编辑器或无行业边界的数据中台。
- 不因名词先进而引入 Kafka、Trino、RDF 服务、图数据库、专用向量库或服务网格；默认 Spark/Flink 也必须按任务能力和规模路由，不能强迫轻量任务使用分布式引擎。
- 不用配置文件、接口 spec、mock publisher 或单个 notebook 证明平台已完成。
- 不用测试数量、工具数量、Agent 数量或前端 Tab 数量代表产品进度。
- 不复制传统平台的菜单树、微服务拓扑和默认全量中间件，也不以对话入口替代可审查、可调试的专业路径。

## 3. 当前事实基线

| 能力 | 当前可运行事实 | 架构判断 |
|---|---|---|
| Schema 与配置真值 | SQL migration、Compose、K8s migration Job 和多套环境配置存在 | `011`-`017` 迁移版本重复且失败不阻断；目标环境 schema 可能分叉，必须 P0 修复 |
| 产品入口与专业工作台 | 对话、地图、DataPanel、WorkflowEditor 及大量领域 Tab | 有入口但信息架构偏功能堆叠；缺 Discover/Build/Operate/Govern 稳定工作面和同定义双入口 |
| 数据源与汇聚 | virtual source/connectors、PostGIS intake、stream 和文件/对象存储组件 | 查询/扫描能力多于生产同步；无统一 Source/SyncDefinition/SyncRun、CDC，以及云盘客户端 `DriveTransfer` 的服务端会话/断点/入湖闭环 |
| 应用与空间数据库 | PostgreSQL/PostGIS + pgvector；业务、治理、语义和运行表共库；Martin 提供矢量瓦片 | 可作为控制平面和在线 serving store，不能继续同时承担所有原始、分析和产品真值 |
| 文件与对象存储 | 本地 `uploads/`；`StorageManager` 路由 file/S3/OBS/PostGIS；Compose 提供 uploads 和 lakehouse 两个 MinIO bucket | 有存储适配和对象存储，没有强制 Landing/ODS/DWD/DWS/ADS 生命周期 |
| 存储/计算 profile | MinIO/S3、PostGIS、Iceberg、Spark/Sedona 和本地 Python 组件存在 | 配置分散，未形成 StorageBinding/TableCatalogBinding/ComputeBinding、capability certification 或云/轻量 profile |
| 湖仓配置 | 约定 `raw/`、`curated/`、`warehouse/`；存在 Iceberg、STAC、S3A 和 Spark/Sedona 配置 | 是默认 profile 的基础配置，不是可替换的完整湖仓运行时 |
| 湖仓执行 | 有独立 Spark/Sedona 镜像、smoke scripts 和 TxPoint10M 专项 Iceberg 作业；Flink 默认执行合同尚未形成 | 证明部分批处理技术可行；尚无通用 batch/stream ingestion/publish/rollback/serving pipeline |
| 元数据与目录 | 资产 JSONB、catalog、lineage、intake、semantic/standard/AI registry 和 STAC/Iceberg 局部元数据 | 多写路径、双血缘和无统一 ResourceVersion；不是统一元数据中心 |
| 调度与执行 | APScheduler、TaskQueue、SparkGateway、Standards outbox、自进化 scheduler 和 API background task | 无统一耐久作业模型；存在重复 cron、跨进程丢任务和无法接管风险 |
| 数据治理 | 标准、质量规则、分类、版本、RLS、审计已有表与局部 API | 能力真实但分散，尚未成为逐层发布门禁 |
| 建模与数据开发 | semantic/standard data model、workflow/template、SQL/Python/GIS tools 已有局部能力 | 缺 model deploy 生命周期、typed operator、preview sandbox 和 Notebook -> production 统一链 |
| 资产与服务运营 | catalog、usage/tag、distribution/review、REST/MVT/STAC/MCP 接口和 Martin 部署存在 | 有 endpoint 和局部 serving，不等于 GIS 发布平台；缺统一 Service Control Plane、Layer/Style/TileMatrixSet 版本、provider 准入、部署 revision、原子切换、缓存一致性、3D/传统 OGC 兼容、消费者影响和退役闭环 |
| 分析与空间体验 | NL2Semantic2SQL、图表、2D/3D map、遥感与领域分析能力丰富 | 差异能力真实，但未统一绑定产品版本、语义口径、权限和可复现 view |
| 平台运维 | 结构化日志、Prometheus、OTel、K8s、数据库日备和 CI/CD 文件存在 | 缺数据产品级 SLI/SLO、联合恢复演练；CI 配置和生产 CD 有占位/漂移 |
| DataOps | source、workflow、quality、catalog、Run、DataProduct 和部分 CI 组件存在 | 没有贯穿 definition -> CI -> promotion -> run -> observe -> incident -> replay 的统一运营闭环 |
| AgentOps | Agent registry、Prompt version、eval history、OTel Agent/Tool span、guardrail、feedback、cost guard 存在 | 没有 AgentSpec bundle、EvaluationBinding、DeploymentRevision、online verdict、AgentRun/ToolCall 质量闭环、事故和可执行回滚 |
| MMFE | Profiling、Assessment、Alignment、Execution、Validation 及语义产品合同已存在 | 应接入 Silver/Gold 数据生产，不再作为旁路工具 |
| STAC | 外部 STAC connector、publish spec 和部分静态资产能力 | 尚无统一、可查询、可回滚的本地产品目录服务 |
| Cognitive Runtime | 已有正式设计、Agent/Workflow/Policy/Evaluator 等局部实现 | 必须建立在稳定的数据契约和确定性 pipeline 之上 |
| GWM/TWM/UWM | 领域模型、状态、规则、预测、规划和证据边界已有大量实现 | 作为 Gold/DataProduct 消费者保留；不能反向定义原始数据真值 |

**当前总评**：项目是“Agent 应用 + PostGIS + 对象存储 + 分散控制组件 + 局部湖仓实验”的混合系统，尚未形成生产级地理空间湖仓、完整 DataOps 或 AgentOps 平台。它在部分智能能力上超过传统平台，但在基础生产与运营闭环上尚未达到传统时空数据中台的能力下限。完整证据见 [企业级架构复审](architecture-review-2026-07-19.md)、[传统平台能力基线与 Agentic 升维设计](traditional-platform-baseline-and-agentic-elevation-2026-07-19.md) 和 [ADR-005：DataOps 与 AgentOps 双运营闭环](architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md)。

## 4. 总体架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│ LLM-Optional Multi-Surface Experience Plane                          │
│ Discover | Build | Operate | Govern | Conversational Copilot        │
│ Visual/DAG | SQL | Notebook | Map/2D/3D | API/SDK | CLI/TUI | MCP/A2A │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│ Consumption & Intelligence Plane                                     │
│ Human Views | Agent Context | AI Datasets | GWM Observation/Scenario │
│ PostGIS/Martin | STAC/OGC | SQL/API | Files/Notebooks               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ DataProductVersion
┌───────────────────────────────▼──────────────────────────────────────┐
│ Unified Metadata & Governance Control Plane                          │
│ OpenMetadata: Governance Catalog/Search/Owner/Glossary/Quality       │
│ Gravitino: Technical Metadata Lake/Metalake/Catalog/Federation       │
│ GDA Ledger: ResourceURN/Policy/Approval/Evidence/Action/Outcome      │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ immutable resource/input binding
┌───────────────────────────────▼──────────────────────────────────────┐
│ Unified Orchestration & Job Control Plane                            │
│ gda Gateway: Definition/Policy/PlatformRun/Artifact correlation     │
│ DolphinScheduler: DataOps DAG/schedule/complement/resource queue     │
│ Temporal: durable Agent/GWM workflow/signal/retry/compensation       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ governed executor contract
┌───────────────────────────────▼──────────────────────────────────────┐
│ Data Production Plane                                                │
│ Ingest -> Profile -> Standardize -> Fuse/MMFE -> Aggregate -> Publish│
│ DuckDB/local | PostGIS | Spark/Sedona | Flink | Cloud | AI/GWM      │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│ Storage & Serving Plane                                              │
│ Configurable Storage/Table Providers                                 │
│ default: MinIO + Iceberg | cloud: ADLS/etc. | light: PostGIS/DuckDB │
│ PostgreSQL: GDA control/evidence ledger; OpenMetadata/Gravitino/     │
│             DolphinScheduler/Temporal                                │
│             each use their independently managed persistence stores  │
│ PostGIS: operational editing, spatial serving, materialized products│
│ Redis: cache/progress/rate limit; never queue or workflow truth      │
└──────────────────────────────────────────────────────────────────────┘

Cross-cutting: identity, policy, tenant isolation, observability,
provenance, idempotency, checkpoint, backup, retention and cost.

DataOps loop: DataProductSpec -> DolphinScheduler DAG/CI/quality -> promotion -> DataRun
 -> SLO/observe -> incident/remediation -> replay/new DataProductVersion.

AgentOps loop: AgentSpecBundle -> eval/safety/cost -> deployment/canary
 -> Temporal AgentRun/ToolCall -> online verdict/guardrail -> incident/rollback/feedback.

The two loops share Metadata, Orchestration, Policy, Artifact, Audit and Incident
contracts. AgentOps can submit DataOps Run, but neither loop creates a second
metadata authority or scheduler.

Cognitive Runtime plans and submits approved capabilities across the planes when enabled.
It is not a scheduler database, storage engine, metadata authority, quality truth
or permission engine. Web/API/SDK/CLI/TUI/Notebook/Agent triggers enter the same durable Run model; the deterministic triggers remain available when LLM is disabled.
```

### 4.1 LLM 可选的多入口能力合同

```text
Web/Map/Canvas | API/SDK | gda CLI | gda TUI | Notebook | MCP/A2A Agent
       \             |          |            |             |            /
        \------------+----------+------------+-------------+-----------/
                                    |
           CapabilitySpec -> DefinitionVersion / ChangeSet -> Policy
                                    |
                         Preview / Approval -> PlatformRun
                                    |
       DolphinScheduler / Temporal / typed executor -> Artifact + Audit
```

每个生产 capability 先定义版本化 `CapabilitySpec`：输入/输出 JSON Schema 与 semantic type、query/command/long-running、读写资源/side effect/risk、SubjectContext/PolicyDecision obligation、idempotency/expected version、dry-run/preview、RunRef/Artifact/Evidence、cancel/compensate/reconcile，以及 OpenAPI/AsyncAPI-CloudEvents/MCP 映射。入口等价是 capability、definition、policy、Run、Artifact 和 audit 等价；TUI 无需复制 Web 地图的像素渲染，但必须能通过 layer/extent/style/Artifact descriptor 完成对应的受治理操作。

`gda` CLI 使用项目既有的 Python `Typer` + `Rich`，支持 JSON/YAML、`--dry-run`、`--wait`、`--output json`、稳定退出码；`gda` TUI 使用既有 `Textual`，支持目录/搜索、definition diff、Run/日志/进度、质量问题、审批与恢复，且只调用公开 API。`llm_mode = disabled | optional | required_for_agent_feature` 是 DeploymentProfile 字段：禁用 LLM 时，Web/API/SDK/CLI/TUI/Notebook、调度、质量、安全、审批、服务、地图与确定性 GWM/规则仍完整可用；仅生成式能力返回 `LLM_UNAVAILABLE` 及等价确定性入口。详细决策见 [ADR-004](architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)。

### 4.2 GIS 服务发布三层架构

```text
DataProductVersion + Policy/Quality/Approval
                  |
                  v
GIS Service Control Plane (GDA authority)
Service/Layer/Style/TMS definition -> DeploymentRevision -> active/rollback pointer
consumer/deprecation/SLO           -> publish Run/Artifact/Evidence
                  |
                  v
Certified Provider Runtime (replaceable data plane)
Feature/API | MVT | Raster/COG | STAC | Map/legacy OGC | 3D | Process
                  |
                  v
Gateway, Cache and Operations
OIDC/workload identity | policy enforcement | route/WAF/rate/quota
cache/ETag | metrics/log/trace | usage/billing | incident/degraded mode
```

服务控制面是 GDA 必须自有的领域能力，因为它承载跨 provider 的产品版本、治理策略、部署和消费者生命周期；它不是新的 GIS server。实际协议、渲染、切片和目录查询由成熟 provider 承担，Gateway 也不拥有服务生命周期。三层均使用统一 `ResourceURN`、`SubjectContext`、`PlatformRun`、Artifact、PolicyDecision、ApprovalCase、SLO/Incident 和 AuditEvent。

核心发布对象冻结为：通用 `ServiceDefinitionVersion` 的 GIS typed profile `GISServiceDefinitionVersion`，以及 `LayerDefinitionVersion`、`StyleDefinitionVersion`、`TileMatrixSetDefinitionVersion`、`CachePolicyVersion`、`ServicePolicyBinding`、`ServiceDeploymentRevision`、`EndpointRevision`、`ConsumerBinding`、`ServiceSLO` 和 `RollbackPointer`；它们共用一个 service registry 和 lifecycle，不新建第二套服务权威。定义至少声明 source `DataProductVersion`、schema/geometry/CRS、spatial-temporal extent、scale/generalization/label/style、format/protocol、provider capability、auth/policy、quota/rate/cache、compatibility/deprecation 和 reliability class。运行时投影均可从产品版本重建，不得成为数据真值。

首期 provider 基线不是单产品通吃：

| 服务能力 | 默认 provider/格式 | 兼容或可替换 provider | 首期边界 |
|---|---|---|---|
| SQL/attribute API | GDA typed API projection + PostGIS/DuckDB adapter | 云 SQL/API、RocketAPI adapter | OpenAPI/JSON Schema 固化；RocketAPI 配置不成为权威 |
| OGC API Features | `pg_featureserv` 用于 PostGIS 轻量直出；`pygeoapi` 用于多源 OGC API facade | GeoServer、云/商业 GIS adapter | provider 选择由过滤、事务、CRS、并发和扩展需求决定 |
| OGC API Tiles/vector tile | PostGIS + Martin，MapLibre Style/TileJSON；OGC API Tiles 由标准 facade 暴露 | 云 tile provider、SuperMap/ArcGIS adapter | MVT 只读已发布 serving schema；版本进入 URL/ETag/cache key |
| Raster/imagery | COG + TiTiler | GeoServer WCS/WMTS、云影像服务、SuperMap/ArcGIS | 原始/派生 COG 仍在对象存储；服务只做窗口、重采样、render projection |
| STAC | pgSTAC + stac-fastapi 或通过同一 conformance 的实现 | 云 STAC provider | Catalog/Collection/Item 与对象 checksum、ProductVersion 和权限一致 |
| WMS/WFS/WMTS/WCS 与复杂制图 | GeoServer 作为条件兼容 provider | SuperMap iServer、ArcGIS Enterprise | 不作为所有新服务默认路径；用于旧系统兼容、SLD/复杂制图和既有生态 |
| 3D/点云/mesh | OGC 3D Tiles + object storage/gateway；构建任务进入 DataOps | S3M、I3S provider adapter；PDAL/Entwine/Py3DTilers 类构建 provider 经认证 | 3D Tiles/S3M/I3S 分别登记 capability、style/scene、LOD、坐标和版本，禁止笼统标记“支持 3D” |
| 时空观测/实时订阅 | OGC API EDR/SensorThings capability profile；pygeoapi/FROST-Server 类 provider 经认证 | 云 IoT/stream API adapter | Flink/产品投影保存版本和 checkpoint；provider/broker 不是历史数据真值或第二调度器 |
| OGC API Processes | pygeoapi/协议 facade 返回统一 `RunRef` | 商业 GIS process adapter | 执行委托 DolphinScheduler；provider 不建立第二调度器或隐藏长任务状态 |
| File/export/offline package | 版本化 Artifact + signed distribution；GeoPackage/FlatGeobuf/GeoParquet/COG/PMTiles/MBTiles 按 capability 认证 | 云文件分发、商业离线包 adapter | 大文件复用 `DriveTransfer`/multipart；导出固定 ProductVersion、policy、checksum、expiry 和 consumer |
| API gateway | Apache APISIX 作为私有化候选基线，经 ADR benchmark 后冻结 | Azure API Management 或其他云 gateway adapter | Gateway 只负责认证、路由、WAF、限流和观测；不能替代 Service Control Plane |

详细取舍、接受条件和重评触发见 [ADR-017：GIS 服务发布控制面与 Provider Runtime](architecture-decisions/adr-017-gis-service-publishing-control-plane-and-provider-runtime.md)。在 ADR-017 从 Proposed 转为 Accepted 前，上表是实现和 benchmark 基线，不得宣称 production-supported。

## 5. 数据分层与物理映射

传统 ODS/DWD/DWS/ADS 与 Lakehouse Medallion 不再各建一套。下表定义逻辑层和默认湖仓映射；云与轻量 profile 必须保持相同层级、版本和发布门，不要求物理介质完全相同：

| 逻辑层 | Lakehouse 映射 | 主要内容 | 主存储/格式 | 写入规则 | 退出门 |
|---|---|---|---|---|---|
| **Landing / Raw** | Raw zone | 原始文件、源导出、API 响应、影像、文档、压缩包 | 默认 MinIO/S3；云 blob/data lake；轻量 PostGIS/DuckDB append-only Raw table 或外部目录 | 不可覆盖；content hash；source/run manifest；敏感级别 | 内容/表版本、checksum、来源、许可、空间时间范围和 owner 齐全 |
| **ODS** | Bronze | 对源结构做 1:1 可查询快照，不修业务语义 | 默认 Iceberg Parquet/GeoParquet；认证云湖表；轻量 PostGIS/DuckDB snapshot/table | 追加或 snapshot；保留源字段、源主键、批次和摄取时间 | 行数/字节数对账；schema drift 被记录；可按版本重放 |
| **DIM + DWD** | Silver | 一致维度、标准化明细、对象身份、坐标/单位/代码统一、质量问题 | 默认 Iceberg；认证云湖表；轻量 schema/table/view | 标准/模型版本固定；确定性转换；问题不静默丢弃 | 主键/引用闭包、CRS、geometry、值域、拓扑、完整性和血缘门通过 |
| **DWS** | Gold aggregate | 主题汇总、空间网格/行政区聚合、变化事实、指标和 AI 特征 | 默认 Iceberg；云/轻量物化表或受控快照 | 只能消费已发布 Silver version；指标公式版本化 | 汇总守恒、维度一致、增量等价、性能和质量 SLA 通过 |
| **ADS / Serving** | Gold serving | 地图、API、报表、Agent context、AI dataset、GWM observation | PostGIS/Martin、STAC、API、GeoParquet/COG exports | 从指定 Gold/DataProductVersion 可重建；不反写上游 | 消费权限、版本一致性、可用性、回滚和审计通过 |

默认 Iceberg profile 的首期跨引擎空间合同固定为 `geometry_wkb + srid + bbox + optional h3/geohash`。只有 Spark/Sedona、Flink、DuckDB/Spatial、PostGIS、PyArrow/GeoPandas 和目标云引擎对相关读写路径完成 geometry encoding、时间语义与 GeoParquet metadata 互操作测试后，才把原生 geometry 类型作为跨引擎权威合同。分区字段必须由真实查询基准决定，优先低基数时间、区域或受控空间分桶；禁止沿用未经验证的 `partition_by=product_id` 默认值，也禁止直接按高基数 geometry/object ID 分区。

### 5.1 可配置存储与计算 profiles

```text
DataProductBlueprint requirements
 -> DeploymentProfile defaults
 -> PlacementPolicy
 -> StorageBinding + TableFormatCatalogBinding + ComputeBinding
 -> provider compiler -> ExecutionPlanArtifact
 -> Run freezes provider/engine/version/config
```

| Profile | 默认物理组合 | 使用场景 | 必须保持的合同 |
|---|---|---|---|
| Default Lakehouse | MinIO + Iceberg；Spark/Sedona batch；Flink stream；PostGIS serving | 标准私有化生产 | snapshot/checkpoint、ACID/幂等、lineage、replay、rollback、RPO/RTO |
| Cloud Managed | Azure Blob/ADLS Gen2 等云数据湖 + 认证 catalog/table adapter + 云 Spark/Flink-compatible/managed compute adapter | 云部署、弹性和托管运维 | 云 IAM/密钥、region、加密、版本、取消/reconcile、成本和 egress 可见 |
| Lightweight Integrated | PostGIS 或 DuckDB/Spatial；大对象可外接对象存储 | 单机、边缘、开发和较小数据集 | 逻辑分层、ResourceVersion、质量门、lineage、备份/导出和可重放 |
| Hybrid | 上述 binding 按数据产品和 task 组合 | 云地协同、迁移和轻重混合 | 同一 Definition、Run、Artifact、DataProductVersion 和策略语义 |

存储 provider 至少声明 object/blob、table/snapshot、transaction、encryption、versioning、retention 和 egress 能力；计算 provider 至少声明 batch/stream/interactive/spatial、checkpoint、cancel、reconcile、resource、metrics 和 cost 能力。TaskGraph 同时声明 `portable`、`engine_family` 或 `provider_native`：只有 portable operator 可跨引擎编译并比较 golden result，原生代码迁移必须生成新 DefinitionVersion。平台只调度经过 conformance suite 认证且满足 portability constraint 的组合。

### 5.2 数据家族策略

| 数据家族 | 权威内容存储 | 表/目录策略 | 在线消费 |
|---|---|---|---|
| 矢量/关系表/时序事实 | Iceberg + GeoParquet/Parquet | ODS/Silver/Gold 表 | PostGIS 物化产品、SQL/API、文件导出 |
| 栅格/遥感 | MinIO/S3 COG | STAC Collection/Item；索引、统计和派生事实可入 Iceberg | TiTiler/兼容服务、地图、窗口读取 |
| 文档/图片/视频/3D/点云 | MinIO/S3 原对象或优化格式 | 资产 manifest、元数据、片段/特征/证据索引 | 受控下载、预览、检索和 MMFE |
| 实时流 | Flink 是默认流执行器；消息/日志接入和短期状态可使用认证 broker/state backend | checkpoint 后写入 Bronze/Iceberg 或所选云/轻量 table binding | SSE/API；历史查询走版本化分析层 |
| embedding/模型特征 | 先存 Iceberg/Parquet 并保留模型版本 | 百万级低延迟 ANN 需求成立后再引入 LanceDB/专用向量投影 | RAG、相似检索、训练 |
| 图/RDF | PostgreSQL 关系和 JSON package 为第一权威 | 只有 competency query、互操作或 SLO 失败时增加图/RDF 读投影 | Resolver/API，不产生第二权威写源 |

### 5.3 真值边界

- 原始证据真值：Landing/Raw 对象和 source manifest。
- 分析表真值：元数据中心登记的不可变 TableSnapshot/ResourceVersion；默认 profile 为 Iceberg snapshot/version。
- 治理与产品权威：OpenMetadata 中的治理 catalog 事实、Gravitino 中的 technical metadata/federation 事实，以及 GDA PostgreSQL Control Ledger 中的 ResourceURN mapping、Policy/Approval、PlatformRun、Action/Outcome 和产品发布证据；三者通过受控 metadata fabric bridge 关联。
- PostGIS operational 表可以是编辑事务的源系统，但每次有效变更必须生成版本/事件并重新进入 Raw/ODS；不得直接修改 Silver/Gold 真值。
- PostGIS serving projection 可重建，不是批量分析唯一真值。
- 遥感发现真值：STAC metadata + 对象 checksum；STAC 不保存影像内容。
- GWM 输出：带来源和不确定性的派生产品，不是 observed outcome。

## 6. 模块边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| **Unified Metadata Control Plane** | OpenMetadata governance catalog/quality/generic lineage + Gravitino technical metadata lake/federation + GDA ResourceURN mapping、空间/证据 extension、policy/release evidence | 不自研 catalog/search/connector/lineage UI/technical metadata lake；不保存大对象或复制 Iceberg/STAC 内容真值 |
| **Engine Provider Layer** | DeploymentProfile、Storage/Table/Compute binding、capability registry、placement、credential reference 和 conformance status | 不拥有产品语义、Run 真值或权限审批 |
| **DataOps Operating Loop** | DolphinScheduler DAG/CI、quality gate、schedule、complement/backfill、worker group/resource queue、promotion、DataProduct release、SLO、incident、replay、cost/capacity feedback | 不拥有底层存储真值、Agent 行为状态或第二调度器 |
| **AgentOps Operating Loop** | Temporal Agent workflow、AgentSpec bundle、eval/safety/cost、deployment/canary、AgentRun/ToolCall observation、guardrail、budget、incident、rollback、feedback | 不拥有数据产品真值、元数据 authority 或 DataOps asset scheduler |
| **Unified Orchestration Control Plane** | `gda-orchestration-gateway` 的 definition/policy/PlatformRun correlation、artifact/lineage evidence、placement resolution；DolphinScheduler/Temporal 的运行时边界 | 不实现 cron、DAG、queue、lease、timer 或 workflow engine；不把 Web/Redis/外部引擎状态当唯一运行真值 |
| **Data Platform Runtime** | ingest、分层转换、snapshot、发布、回滚、对账及 executor adapters | 不拥有调度状态，不理解自然语言，不自行批准治理变更 |
| **Data Product Engineering** | blueprint、source/sync、关系/维度/空间模型、Visual/SQL/Notebook、preview/test、publish | 不维护第二套 definition，不绕过调度直接生产发布 |
| **Governance & Product Control** | 标准、模型、本体、质量、安全、审批和保留策略 | 不另建资产身份/血缘写源，不执行大规模 GIS 计算 |
| **Asset & Service Operations** | discover/search/map、申请/订阅、consumer impact、usage/SLO/incident/deprecation/retire | 不实现协议 runtime，不把 serving projection 作为分析真值，不暴露临时结果为长期服务 |
| **GIS Service Control Plane** | Service/Layer/Style/TMS/Cache/Policy definition、provider placement、Deployment/Endpoint revision、publish/validate/activate/rollback、consumer/SLO 生命周期 | 不实现 OGC/STAC/MVT/3D 协议引擎，不保存地图服务数据，不承担 Gateway 路由和 WAF |
| **GIS Provider Runtime** | pg_featureserv/pygeoapi、Martin、TiTiler、pgSTAC/stac-fastapi、GeoServer 及 SuperMap/ArcGIS/云 adapter 的协议、查询、渲染和切片运行时 | 不拥有 DataProductVersion、策略审批、active pointer 或消费者生命周期；不建立第二调度器 |
| **Gateway & Service Edge** | OIDC/workload identity、策略执行、路由、WAF、quota/rate limit、cache/ETag、usage 和 request telemetry | 不成为 ServiceDefinition 权威，不允许 provider endpoint 绕过统一入口直接公开 |
| **MMFE** | 多源多模态 profiling、对齐、融合、冲突和语义产品 | 不成为资产目录、权限或 Iceberg catalog |
| **Cognitive Runtime** | 任务框定、检索、规划、能力选择、评价和 HITL | 不直接执行耐久长任务；此类工作由 Temporal workflow 调用 typed Action，不成为调度、数据、权限、质量或发布权威 |
| **GWM Kernel** | 状态、行动、转移、不确定性、情景和证据 claim | 不绕过数据质量、安全、版本和审批门 |

### 6.1 DataOps 与 AgentOps 运营闭环

```text
DataOps:
DataProductSpec -> Build/CI -> Quality/Security -> Promotion/Release
 -> DataRun -> Observe/SLO -> DataIncident/Remediation -> Replay/New Product

AgentOps:
AgentSpecBundle -> Eval/Safety/Cost -> Approval/Promotion
 -> Shadow/Canary -> AgentRun/ToolCall -> Online Verdict/Guardrail
 -> Incident/Rollback/Feedback -> New AgentSpecVersion
```

DataOps 管理数据产品的持续交付与可靠性；AgentOps 管理 Agent bundle 的评测、部署、安全、预算和在线行为。MLOps/LLMOps 是 AgentOps 的模型与 Prompt 子域，PlatformOps/SRE 管理共享基础设施，三者不能替代这两个领域闭环。

两者共用 `ResourceURN`、不可变 version、`SubjectContext`、`Run/Artifact` 关联、`PolicyDecision`、`ApprovalCase`、`Incident/Problem`、`SLO`、`ChangeSet`、`AuditEvent` 和 transactional outbox，但保留领域状态机：`DataRun` 不能替代 `AgentRun`，`AgentRun` 也不能替代数据生产 Run。AgentOps 可以提交 DataOps Run；Agent 反馈、安全事件和 `DataDemand` 可以回流 DataOps，触发数据修复、重算或新产品版本。

## 7. 关键架构决策

详细理由见 [ADR-001：可插拔地理空间存储、计算与服务边界](architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)、[ADR-002：统一元数据控制面](architecture-decisions/adr-002-unified-metadata-control-plane.md)、[ADR-003：统一调度与作业控制面](architecture-decisions/adr-003-unified-orchestration-and-job-control-plane.md)、[ADR-004：传统平台能力下限与 Human/Agent 双入口](architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)、[ADR-005：DataOps 与 AgentOps 双运营闭环](architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md)、[ADR-006：OpenMetadata + Gravitino Metadata Fabric](architecture-decisions/adr-006-openmetadata-governance-and-active-metadata-platform.md)、[ADR-007：DolphinScheduler + Temporal 编排平台](architecture-decisions/adr-007-dolphinscheduler-temporal-orchestration-platform.md) 和 [ADR-017：GIS 服务发布控制面与 Provider Runtime](architecture-decisions/adr-017-gis-service-publishing-control-plane-and-provider-runtime.md)。

| 决策 | 选择 | 放弃/延后 |
|---|---|---|
| 应用形态 | 模块化单体控制面 + 可插拔计算运行时 | 全面微服务 |
| 存储与计算 | 默认 MinIO + Iceberg、Spark/Sedona + Flink；支持认证云 provider 与 PostGIS/DuckDB 轻量存算一体 profile | 固定厂商/引擎；每个后端复制一套 pipeline |
| 空间在线服务 | PostGIS/Martin 承担 serving projection 和编辑型工作负载 | 把 PostGIS 当无限扩展的数据湖 |
| 栅格 | COG + STAC；派生表和统计进入 Iceberg | 把大栅格二进制塞入关系表 |
| 分层 | ODS/DWD/DWS/ADS 映射 Bronze/Silver/Gold/Serving | 两套并行分层术语和物理副本 |
| 控制元数据 | OpenMetadata 是治理 catalog，Gravitino 是 technical metadata lake/federation；GDA PostgreSQL 仅保存 ResourceURN mapping、control/evidence contracts；物理系统通过 fabric bridge/harvester 同步 | 多 registry/JSONB 并行写；自建第二个 catalog/technical metadata lake/图/RDF 写权威 |
| 调度与作业 | DolphinScheduler 是 DataOps DAG/schedule/backfill/worker-resource runtime；Temporal 是 durable Agent/GWMOps runtime；GDA 只保留 PlatformRun correlation | Web 内 APScheduler、`asyncio.create_task`、`TaskQueue`、Dagster 或自研 scheduler/workflow runtime 作为生产运行时 |
| 元数据与调度事件 | transactional outbox + 幂等 consumer；首期不要求 Kafka | 无事实依据先上全量流平台 |
| 产品入口 | Discover/Build/Operate/Govern 四工作面 + 上下文 Agent；Web/Map/Canvas、Visual/SQL/Notebook、API/SDK、CLI/TUI、MCP/A2A 共用 `CapabilitySpec`/definition；`llm_mode=disabled` 完整可用 | 对话或 LLM 取代专业工作台；入口各自实现业务逻辑；继续增加孤立基础平台 Tab |
| 能力下限 | 传统平台代表任务作为 parity gate，Agentic 路径另设 uplift gate | 复制旧菜单/中间件；以新能力数量掩盖基础任务缺口 |
| 计算路由 | capability + SLO + cost placement；默认 batch=Spark/Sedona、stream=Flink，轻量=PostGIS/DuckDB | 用数据量阈值或默认引擎名称硬编码所有任务 |
| 发布 | DataOps 以 DataProductVersion 驱动 PostGIS/STAC/API/AI/GWM 投影；AgentOps 以 AgentDeploymentRevision 驱动 Agent bundle 灰度/回滚 | 各工具自行生成无版本结果 |
| GIS 服务发布 | GDA Service Control Plane 持有定义/版本/部署/消费者/SLO；成熟 provider 负责协议与渲染；Gateway 负责入口安全和流量 | 让 GeoServer/SuperMap/ArcGIS/APISIX 配置成为平台权威；自研 OGC/STAC/MVT/3D server |
| GIS provider 基线 | pg_featureserv/pygeoapi + Martin + TiTiler + pgSTAC/stac-fastapi；GeoServer、SuperMap、ArcGIS 和云能力作为经认证兼容 provider；3D 以 3D Tiles 开放交换为默认 | 单一 GIS server 承担所有协议、调度、治理和生命周期；用 endpoint 存在代替 conformance |
| 运营闭环 | DataOps 与 AgentOps 共用 Metadata/Orchestration/Policy/Artifact/Audit/Incident 合同 | 仅有局部 registry、eval、trace 或 CI job 就宣称 Ops 完成 |

首期 PostgreSQL 控制表、operational 表和 PostGIS serving 表可以同集群部署，但必须使用独立 schema、角色、连接池和备份/恢复边界；只有资源争用、RPO/RTO 或故障隔离基准失败时才物理拆库。

## 8. 主路线与强制退出门

```text
AR-0 Architecture / Schema / Runtime Truth
  -> AR-1 Unified Metadata + Orchestration Control Planes
  -> AR-2 Source / Ingestion + Geospatial Lakehouse Vertical Slice
  -> AR-3 Data Product Engineering + Governance Workbench
  -> AR-4 Asset / GIS Service / Spatial Experience Operations
  -> AR-5 AgentOps Runtime + UX Uplift
  -> AR-6 MMFE + Data for AI
  -> AR-7 GWM Enhancement
  -> AR-8 Scale / High-throughput Realtime / Federation / Ecosystem (conditional)
```

### AR-0 — Architecture, Schema and Runtime Truth Freeze（当前，P0）

**目标**：停止概念、schema、配置和完成状态漂移，为两个控制面以及 DataOps/AgentOps 运营闭环建立可信地基。

交付：

- 开发、测试、Compose、Kubernetes 和已知客户环境的 schema/config fingerprint；`schema_migrations` 实际记录与缺失表/列报告。
- 迁移机制前向修复：迁移 ID/文件名/checksum 唯一，重复版本被显式拒绝，失败阻断 Job/启动，禁止静默 skip；不重写已执行历史。
- 当前部署组件、数据存储、表、bucket/prefix、job/scheduler、API、registry 和 owner 清单。
- DeploymentProfile、EngineCapability、StorageBinding、TableFormatCatalogBinding、ComputeBinding、placement 与 credential/cost/SLO 合同；默认、云托管和轻量 profile 的能力矩阵。
- `CapabilitySpec` registry：P0 capability 的 JSON Schema/semantic type、query-command-long-running、side effect/risk、SubjectContext/policy、idempotency/preview/RunRef/Artifact、OpenAPI/AsyncAPI/MCP projection 与 Web/API/SDK/CLI/TUI/Notebook/Agent parity matrix；`llm_mode=disabled|optional|required_for_agent_feature` 及无 LLM 环境测试 profile。
- DataOps/AgentOps 术语、对象、责任矩阵、环境晋级、Release/Promotion、Incident/Problem、SLO/SLI、on-call、审计和反馈合同。
- 术语表：Asset、Dataset、Table、Product、Snapshot、Run、Artifact、Evidence 的唯一定义。
- ADR-001 至 ADR-007、ADR-017、分层命名、控制面边界、数据保留和真值边界；其中 ADR-006 冻结 OpenMetadata + Gravitino metadata fabric，ADR-007 冻结 DolphinScheduler + Temporal，ADR-017 冻结 GIS 服务控制面、provider/Gateway 边界和首期框架矩阵，旧 ADR-002/003 的自建框架选型已被取代。
- GIS 服务事实盘点与准入矩阵：当前 REST/MVT/STAC endpoint、Martin/PostGIS、样式、缓存、Ingress/Gateway、商业 GIS/云 GIS 依赖、消费者和外网暴露面；冻结 Feature/MVT/COG/STAC/legacy OGC/3D/Process 代表服务、数据规模、并发、冷启动、p95/p99、RPO/RTO、兼容和安全验收集。
- OpenMetadata、Gravitino、DolphinScheduler、Temporal 的独立 namespace/database、OIDC/workload identity、backup/restore、OTel、Helm/IaC、版本 pin、升级 sandbox 和责任人清单；不以 docker-compose 能启动作为生产就绪证据。
- 传统平台能力基线、代表任务清单、Human/Agent 双入口原则和 parity/uplift 指标基线。
- SubjectContext、tenant/owner、service identity、secret reference 和 policy enforcement matrix。
- 自然资源首条 vertical slice 的源数据、标准版本、预期产物和 golden checks。
- CI/CD/config 基线；数据库集成测试必须证明连接真实 PostGIS，而不是走未配置 fallback。
- metadata freshness、schedule lag、queue age、run success、RPO/RTO、吞吐和容量的试点 SLI/SLO 冻结。
- data freshness、quality pass rate、release lead time、change failure rate、restore time、Agent eval pass rate、online safety verdict、tool error rate、intervention rate、token/cost budget 和 agent incident MTTR 的试点基线。

退出门：

- 所有目标环境 schema 达到已批准 fingerprint；重复迁移、checksum 漂移和失败迁移在 CI/部署中 fail closed。
- 所有“已完成”能力都有代码、真实后端、测试或运行产物证据。
- 元数据、调度、湖仓、STAC、MMFE、治理和 GWM 的“配置/合同/运行”状态被分别标注。
- 每个生产数据产品和 Agent deployment 都能映射到 owner、definition version、approval、SLO、incident policy、rollback pointer 和运行证据。
- 代表 P0 capability 的 Web/API/SDK/CLI/TUI/Notebook/Agent parity matrix、OpenAPI/AsyncAPI/MCP projection 和 `llm_mode=disabled` 测试计划均已冻结；不能以聊天 prompt、页面点击或 notebook cell 充当唯一接口。
- metadata/lineage/workflow/task API 的双租户越权路径已有回归测试和修复计划。
- 首条数据链路 owner、输入、规模、敏感级别和验收数据冻结。

### AR-1 — Unified Metadata and Orchestration Control Planes（P0）

**依赖**：AR-0 schema/config truth 退出门通过。

**目标**：先建立所有数据生产、Agent 和 GWM 都必须复用的平台控制脊柱；采用 OpenMetadata + Gravitino、DolphinScheduler 和 Temporal，不建设新的孤立 registry、scheduler、queue 或 durable workflow runtime。

统一元数据最小交付：

- OpenMetadata production foundation：独立 PostgreSQL/OpenSearch、OIDC、backup/restore、health/metrics、版本 pin；OpenMetadata 是治理 catalog、owner/steward、domain、glossary、classification、generic lineage 和质量的写权威。
- Gravitino foundation：metadata store、metalake/catalog namespace、provider binding、OIDC、backup/restore、health/metrics、版本 pin；它承担 technical metadata lake/federation，不替代治理 catalog。
- `gda-metadata-fabric-bridge`：ResourceURN/entity/object mapping、GIS spatial/temporal/evidence extension、OpenLineage emitter、provider connector capability matrix 和 bridge replay；GDA PostgreSQL 只保留 control/evidence ledger，不能再充当通用 catalog。
- ResourceURN、ResourceVersion、PhysicalLocation、SchemaVersion、DataContractVersion、PolicyBinding、QualityAssessment、LineageEvent 和 DataProductVersion；治理字段引用 OpenMetadata entityLink/version，技术 catalog 字段引用 Gravitino metalake/catalog/object，不复制完整 metadata JSON。
- DeploymentProfile、EngineProvider/Capability、StorageBinding、TableFormatCatalogBinding、ComputeBinding 和 PlacementDecision 也进入统一资源/版本模型。
- PostGIS/DuckDB schema、对象存储 manifest、Iceberg/云湖表 snapshot、STAC、workflow/job 的 harvester/adapter；每次采集记录 provider、region、source revision、observed_at、freshness、hash 和 tombstone。
- Authority matrix、metadata change outbox、OpenMetadata/Gravitino search/read bridge、lineage/impact API；动态 filter/sort/layer 只允许服务端枚举。
- `MetadataManager`、`data_catalog`、intake 和 JSONB/edge lineage 的 crosswalk；新链路停止 generic/technical metadata 多写源，旧接口通过 metadata fabric bridge facade 兼容。
- repository 层统一 SubjectContext、RLS GUC 和显式授权，血缘节点/边继承资源权限。

统一调度最小交付：

- DolphinScheduler production foundation：self-hosted API/master/worker/alert、metadata DB、project/tenant/worker group/resource queue、OIDC/workload identity、backup/restore 与 metrics；它是唯一 DataOps process/schedule/complement/backfill/task framework。
- PlatformDefinitionVersion、OrchestrationClass、PlatformRun、FrameworkAttemptObservation、Artifact、RunEvent/outbox 和 `gda-orchestration-gateway`；gateway 只做 policy gate、ProcessDefinition compiler、external run correlation、artifact/lineage evidence，不实现 cron、DAG、lease、queue 或 timer。
- DataRun 与 AgentRun/TaskStep/ToolCall 的关联合同，以及 DataIncident、AgentSafetyIncident、Release、DeploymentRevision、EvaluationBinding、OnlineVerdict、Budget 和 Observation 最小对象。
- DataOps 统一编译为 DolphinScheduler process/task；OpenMetadata/Gravitino ingestion、Source/Sync、Spark/Sedona、Flink deployment/reconcile、PostGIS/STAC projection、quality、publish 和 complement/backfill 不再经 APScheduler 或 `TaskQueue` 运行。
- 平台与 DolphinScheduler 使用对应 idempotency/correlation key；DolphinScheduler 负责自身 process/task queue、worker group、launch/retry。Redis 只做 cache/progress fan-out，不保存 queue payload 或唯一运行状态。
- DuckDB/local、PostGIS 和 external job 三类基础 executor adapter；Spark/Sedona batch、Flink stream 和云计算均通过 DolphinScheduler task/provider contract 接入；长任务 API 只创建 PlatformRun，不再用进程内 background task。
- capability/SLO/cost placement resolver；Run 固化实际 storage/compute binding、engine/version、region 和配置，重放不得静默切换引擎。
- input/output Artifact 自动登记元数据并生成 run lineage。

**Temporal 的引入边界**：AR-1 只冻结 namespace、identity、SDK、workflow conventions 和 integration test harness，不迁入生产 Agent/GWM 任务。AR-5/AR-7 按 ADR-007 将 Agent approval/tool/action 与 GWM rollout/evaluation 迁入 Temporal；它不能替代 DolphinScheduler 的 DataOps scheduling。

退出门：

- PostGIS/DuckDB、Iceberg/云湖表、STAC 和对象存储中的同一试点资源可解析到唯一 ResourceURN/OpenMetadata entity/Gravitino object/Version/Location，重复采集幂等，schema drift 可见。
- Gravitino 对 MinIO/Iceberg、Spark/Sedona、Flink 完成真实 create/read/write/schema evolution/snapshot/cancel/reconcile/lineage conformance；失败时自动保留认证 Iceberg REST catalog，不允许 Gravitino 进入该 profile 的唯一生产路径。
- DolphinScheduler schedule、manual trigger、complement/backfill、retry、cancel、worker group/resource queue 和 DataOps UI 运行真实 vertical slice；APScheduler/`TaskQueue`/Dagster 不再创建生产 DataOps run。
- `PlatformRun`、DolphinScheduler process/task、Spark/Flink/cloud job 和 Artifact 可双向关联；master/worker/API 重启后可 reconcile，迟到回调不能推进产品状态。
- retry、cancel、checkpoint/replay 不产生重复 Artifact 或 active product version。
- 双租户无法发现、遍历、运行、取消、重试或读取对方 Resource/Run/Artifact。
- Web、DolphinScheduler、OpenMetadata、Gravitino、worker 和 bridge 重启后不丢版本、产品、血缘、PlatformRun correlation 或审批状态。
- DataOps 状态可从 DolphinScheduler/OpenMetadata/Gravitino/GDA evidence 恢复；任何 release/deployment 都能从事件、Artifact、评测、策略、incident 和 rollback pointer 重放。Temporal durable recovery 在 AR-5/AR-7 单独验收。

当前 Metadata Fabric 证据边界：M1 只读 bridge 合同已验证；ADR-037 至 ADR-046 分别覆盖本地 foundation/recovery/metrics/network-policy 演练与 production readiness contracts；ADR-047 至 ADR-050 已依次建立 deterministic projection plan、本地双 provider replay、tenant-scoped binding ledger 与本地 OpenLineage 幂等 wire delivery；ADR-051 以临时非管理员 OpenMetadata bot 证明项目专用 grant 只有 `table/Create`、`policy/Create` 被 403 拒绝，且 JWT 轮换/吊销后旧值/当前值均返回 401；ADR-052 又在隔离 Gravitino `1.3.0` Basic IdP 中证明 bounded user 的 `USE_CATALOG`、`USE_SCHEMA`、`CREATE_TABLE` 范围、catalog-create 403、密码轮换和用户吊销；ADR-053 将生产 OIDC federation、双 provider integration/workload identity、最小权限、TLS/mTLS、持久 Gravitino catalog、tenant isolation、运营责任和新鲜 protected attestation 冻结为 fail-closed readiness contract。Gravitino `1.3.0` 镜像只发现 Basic IdP，不假设 native OIDC；当前 profile 仍有 40 个外部 blockers 且未提交真实 attestation。`local_openmetadata_minimum_privilege_verified=true` 与 `local_gravitino_minimum_privilege_verified=true` 都只描述各自临时 provider rehearsal；M3-2 ingestion 仍使用 bootstrap admin，Gravitino probe catalog 仍是 memory catalog。因此 `provider_minimum_privilege_verified`、protected workload identity、OIDC、TLS、持久 catalog、生产 ingestion/conformance、生产 lineage receiver、`production_identity_gate_passed` 与 `production_ready` 仍为 false。

### AR-2 — Source, Ingestion and Geospatial Lakehouse Vertical Slice（P0）

**依赖**：AR-1 两个控制面的最小合同通过故障注入和隔离验收。

**目标**：用统一元数据和统一调度跑通一条真实自然资源 DataOps 链，并建立可扩展的 Source/Sync 基础，不依赖 LLM 和 GWM。

链路：

```text
地类图斑源数据
 -> Raw object + ingest manifest
 -> ODS/Bronze source snapshot
 -> DIM region/date/land_class/source
 -> DWD/Silver land_patch + land_change
 -> DWS/Gold region_period_change + coverage
 -> ADS PostGIS map/API + STAC/DataProduct manifest
```

交付：

- 真实源 admission contract：以不可变 archive checksum、解压 payload fingerprint、source-group manifest、metadata profile 和治理 blocker 建立准入基线；证据不得含源 payload、绝对路径、记录值或 geometry，profiling 不等于 content admission。
- M3-29 extraction provenance contract：以 M3-28 上游 evidence fingerprint、archive/extracted comparison 和明确的 derivation blocker 固定“已观察比较”与“派生证明缺失”的边界；operator、tool、command、modified/additional manifest 和 archive-to-working-set attestation 未齐全前不得 content admission。
- M3-30 source governance gate：选择 `bishan_land_use_dltb_local` 作为首条地类图斑候选，绑定 M3-28/M3-29 指纹并把 owner、license、retention、access、privacy/sensitivity、标准版本、DataSLO、golden result 八项决策冻结为独立 pending records；完整派生证明、签名决策和 fresh protected attestation 未齐全前不得 content admission。
- M3-31 protected admission readiness contract：绑定 M3-28/M3-29/M3-30 的逻辑与文件 fingerprints，把 6 项 derivation、8 项 governance 和 1 项 protected attestation 固定为 15 个 fail-closed requirements；`admission_eligible=false` 前不得创建 Landing、ResourceVersion、PlatformRun、scheduler submission 或 provider mutation。
- M3-32 protected admission attestation intake：固定外部 attestation 的 M3-31 logical/file fingerprint binding、15 项逐项 SHA-256 证明、受保护 verifier/source binding、24 小时 freshness、七天 validity 上限和八项 no-payload/no-mutation checks；`evaluate` 只产生 fingerprinted readiness report，不创建任何 Landing、ResourceVersion、PlatformRun、scheduler submission 或 provider mutation authority。
- M3-33 protected admission verifier workflow：只允许从 `main` 手工触发受保护 `chongqing-admission` environment 的专用 verifier runner，消费 metadata-only secret bundle，绑定 exact M3-31 fingerprints，执行 M3-32 evaluate/verify，并以 GitHub OIDC provenance attestation 固定 input/report；workflow 不含 source scan、Landing/ResourceVersion/PlatformRun 创建、scheduler submission 或 provider client，环境/runner/15 项真实 attestation 未 provision 前仍 blocked。
- M3-34 public/open-source immutable Landing slice：以显式 HTTPS source、license、owner、expected SHA-256 和 controlled actor 将真实 public-domain bytes 写入 content-addressed local Landing；复用现有 Resource/ResourceVersion/Artifact authority，通过单事务 gateway registration 保证幂等 replay 和冲突回滚；Natural Earth 110m smoke 已通过，public profile 仍非 production-ready，也不改变 Chongqing protected admission。
- SourceDefinition、CredentialReference、SourceCapability、SyncDefinition/Version、SyncRun、Cursor/Watermark、SchemaDriftEvent 和 Reconciliation。
- 数据库、对象存储/空间文件、HTTP/STAC 三类代表 source 的连接、凭据、连通、发现、preview、profile 和 owner 登记。
- 全量/增量微批的 Append/Overwrite/Merge 策略，以及至少一个真实 CDC 或事件流 source 通过 Flink 写入版本化 Bronze；覆盖 watermark/offset、checkpoint、迟到/乱序、源端删除、幂等、对账、重放和失败恢复。
- `DriveTransfer` 云盘客户端：`DriveEndpoint/FolderBinding/TransferSession/TransferCheckpoint/FileRevision/IntegrityVerdict/ArtifactManifest/IngestRequest`、上传/下载/目录同步、S3 multipart pre-signed URL 与认证 NAS/SMB/FTP/SFTP provider、pause/resume、part/full checksum、输入 fingerprint、配额、quarantine、bundle completeness、DolphinScheduler 入湖 process；本地 checkpoint 仅供恢复，服务端 session/manifest/audit 是真值。首期以真实大型空间 bundle 验收，不宣称未测试的 TB 规模。
- Default Lakehouse、Cloud Managed、Lightweight Integrated 三类 DeploymentProfile，以及 object/table/catalog/compute/serving binding 的环境化配置。
- 默认命名基线：Iceberg 使用 `gis_ods`、`gis_dim`、`gis_dwd`、`gis_dws` namespace；PostGIS 使用 `ads_<domain>` serving schema；云/轻量 provider 用 namespace mapping 保持相同逻辑层；现有 `agent_*` 控制表先映射、不做无收益搬迁。
- 通用 ingest manifest、JobDefinitionVersion、Run/Attempt、Artifact、snapshot 和 layer transition contracts。
- 默认 profile 的真实 MinIO/Iceberg writer、Spark/Sedona batch executor 和 Flink stream executor，不再只生成 publish spec；Flink 首期覆盖受控流/增量链、checkpoint、cancel、reconcile 和幂等 sink，不在此阶段承诺未验证的高吞吐 CDC SLO。
- DataOps 最小闭环：release/promotion、DataSLO、数据观测、DataIncident、根因/修复、replay 和新 DataProductVersion。
- 轻量 profile 以 PostGIS 或 DuckDB/Spatial 跑通同一逻辑 JobDefinitionVersion；至少一个 Azure 代表 adapter 完成 storage identity/读写/version 和 compute submit/status/cancel 的认证 smoke，具体托管服务由部署 profile 选择。
- Silver 标准化：CRS、geometry、代码表、单位、主键、时间和行政区关联。
- Gold 聚合和 PostGIS/STAC 发布；从同一 snapshot 一键重建和回滚。
- CLI/API/人工触发调用同一 JobDefinitionVersion 和 pipeline implementation；所有 DataOps 执行由 DolphinScheduler 接管并关联同一 PlatformRun。

退出门：

- 三类代表 source 均完成 credential rotation、schema drift、网络中断和重复摄取测试；connector 支持矩阵只登记真实认证版本。
- 云盘客户端在网络中断、进程/设备重启、session/credential 过期、源文件变更、并发同名上传和 commit 前崩溃后，只能从已验证分片恢复或安全拒绝；part/full checksum 与源一致，失败文件停留 quarantine，不能进入 Bronze active snapshot；Agent 未获本地路径/操作/期限授权不能启动传输。
- 原始 bundle checksum、Bronze/Silver/Gold snapshot 和 serving version 可追溯。
- 资源、位置、合同、质量、Run/Attempt、Artifact 和 column/object lineage 可从统一元数据中心解析。
- 行数、面积、行政区/地类汇总守恒；geometry、CRS、值域和拓扑检查通过。
- 同一输入和版本重复运行结果 hash 一致；失败可从 checkpoint 恢复。
- Iceberg time travel、产品回滚、PostGIS 重建和 STAC 发现完成真实后端验证。
- 默认湖仓与轻量 profile 对同一 golden input 产生语义等价的 ResourceVersion/DataProductVersion；差异在批准容差内并可解释。
- provider conformance suite 阻止缺少必需 snapshot/checkpoint、cancel/reconcile、权限、lineage、metrics 或 recovery 能力的 engine binding 进入生产。
- 完成 Raw、所选 TableBinding、control metadata 和 serving/STAC projection 的备份恢复与 rebuild 演练，达到该 DeploymentProfile 在 AR-0 冻结的 RPO/RTO。
- Source/Sync、DataRun、质量、SLO、DataIncident、remediation、replay 到 DataProductVersion 的全链路可审计；故障注入后可恢复并防止重复发布。
- 未通过质量门的数据不能发布到 ADS、AI 或 GWM。

### AR-3 — Data Product Engineering and Governance Workbench（P0）

**依赖**：AR-2 真实湖仓链已证明控制面合同。

**目标**：补齐传统平台已经具备的规划、建模、开发、试运行、质量、安全和审批专业工作流，并把它们收束到统一 definition 和产品生命周期。

核心对象：

```text
ResourceVersion -> Run -> Artifact -> QualityAssessment -> ChangeSet
 -> Approval -> DataProductVersion -> ConsumptionProjection
LineageEvent connects every transition.
```

交付：

- DataProductBlueprint：domain/owner/source、layer/storage placement、model/contract、quality/security/SLO、pipeline/projection、retention/cost。
- DataOps release manifest：环境 promotion、owner/on-call、DataSLO、quality/contract gate、incident policy、rollback pointer 和 cost/capacity budget。
- 概念/逻辑/物理、关系/维度/空间模型的目录、版本、diff、兼容性、DDL/Iceberg deployment 和 rollback。
- 同一 JobDefinitionVersion 的 Visual DAG、SQL、Python/Notebook、API/SDK、CLI/TUI 和 Agent tool 编辑/调用入口；typed operator registry、portability class/provider compiler、schema propagation、preview sandbox、中间结果、test 和 publish changeset。
- Notebook/脚本生产化：代码、依赖、运行镜像、输入版本、资源规格和 owner 快照；交互 session 不直接成为生产定义。
- 统一 Authority/Policy/Contract/Owner/Steward resolver，不另建资源身份和血缘写源。
- 数据合同和 schema evolution policy；RuleVersion/RuleSet/AssessmentRun/Issue/Remediation/Recheck，质量门绑定层和产品。
- 行政区、地类、时间和数据源一致维度；CanonicalID、代码集有效期、匹配/合并和变更影响。
- 字段/对象级分类分级、resource/column/row/spatial/temporal/action/purpose policy、静态/动态脱敏和发布审批。
- 通用 ApprovalCase/Inbox：发布、数据申请、敏感操作和模型/规则变更的审批、委托、超时、通知和审计；不以聊天 HITL 替代正式流程。
- 血缘影响分析、质量趋势、消费审计、SLA 和 retention/archive。

退出门：

- 一个模型可从 blueprint 生成、以 Visual/SQL、Notebook、API/SDK 或 CLI/TUI 试运行、发布、调度、观察日志并回滚；不同入口解析到同一 definition/version，并在无 LLM profile 通过相同验收。
- schema/model 不兼容变更产生 consumer impact 和 migration plan，不能直接上线。
- Notebook 生产 Run 在干净 worker 上按固化依赖重放，结果不依赖用户交互环境。
- 一次治理问题从发现、修复、评价、审批到新产品版本全程可审计。
- DataOps CI/CD 能从 definition diff 触发 contract/quality/security test、审批、promotion、部署观察、事故处置和 replay；发布失败不会产生 active DataProductVersion。
- 越权、缺 owner、缺 lineage、质量失败、schema 不兼容和未审批变更无法发布。
- Visual/SQL/Notebook/API/SDK/CLI/TUI 路径在同一代表任务上通过传统能力 parity gate；Agent path 只在该 gate 后验证 uplift。

### AR-4 — Asset, GIS Service and Spatial Experience Operations（P0）

**依赖**：AR-3 可稳定发布 DataProductVersion；ADR-017 的 provider benchmark、ownership 和安全边界通过 AR-0 冻结门。

**目标**：补齐传统平台的资产发现、申请订阅、API/GIS 服务、二维/三维地图和运营闭环，并把 GIS 发布从若干 endpoint 提升为可治理、可替换、可观测、可回滚的产品能力。

#### AR-4.1 Discover 与消费生命周期

- 通过 OpenMetadata catalog/search/lineage API + GDA spatial/policy bridge 提供关键词/分类/owner/质量/地图范围/时间搜索；自然语言检索是可选增强，不再开发平行 catalog search。
- 产品详情、地图/时间 preview、related products、适用范围、draft/active/deprecated/retired、使用/热度/评分/问题/成本/freshness、申请/审批/订阅/到期、版本变更和废弃通知。
- `ConsumerBinding` 固化 consumer、purpose、scope、Product/Service version range、credential、quota、expiry 和 compatibility；上游变更先做影响分析再允许 promotion。

#### AR-4.2 GIS Service Control Plane

- 实现 `GISServiceDefinitionVersion`、`LayerDefinitionVersion`、`StyleDefinitionVersion`、`TileMatrixSetDefinitionVersion`、`CachePolicyVersion`、`ServicePolicyBinding`、`ServiceDeploymentRevision`、`EndpointRevision`、`ConsumerBinding`、`ServiceSLO`、`RollbackPointer` 及状态机 `draft -> validating -> approved -> deploying -> active -> deprecated -> retired`，事故可进入 `suspended -> rollback`。
- 发布只能引用 active/approved `DataProductVersion`；记录 input snapshot、schema/CRS/extent、quality/security verdict、style/TMS/generalization、provider/version/config fingerprint、Artifact hash、approval、endpoint、consumer impact 和 rollback pointer。
- 构建新 projection 和 deployment revision，经 schema/protocol/security/visual/performance validation 后原子切换 active pointer；禁止原表就地发布、共享可变 style、覆盖对象 key 或让临时表/Notebook 结果直接上线。
- 所有 publish/rebuild/warmup/validate/rollback/retire 都创建统一 `PlatformRun`；数据构建由 DolphinScheduler 执行，Gateway/provider 只返回外部 deployment/job reference 并支持 reconcile。

#### AR-4.3 Provider Runtime 与兼容生态

- 默认开源路径：PostGIS + pg_featureserv/pygeoapi、Martin、COG + TiTiler、pgSTAC + stac-fastapi；按 ADR-017 capability matrix 分配 Feature、MVT、Raster、STAC 和 Process 职责，不自研 GIS server。
- GeoServer 作为 WMS/WFS/WMTS/WCS、SLD/复杂制图和旧客户端兼容 provider，不成为所有新服务的默认控制面。
- SuperMap iServer/iObjects、ArcGIS Enterprise 和云 GIS 通过 `GISServingProvider` adapter 接入；ProviderManifest 固化许可、版本、协议、CRS、filter/style/transaction/3D、部署、监控和资源限制。
- 3D 以 OGC 3D Tiles + 对象存储/Gateway 为默认开放交换；S3M、I3S 分别作为 provider capability，点云/mesh/倾斜摄影构建使用经认证 DataOps executor。scene、LOD、tileset、坐标、style 和时间版本必须显式建模。
- 时空观测和实时订阅使用 OGC API EDR/SensorThings capability profile，pygeoapi、FROST-Server 或云 IoT provider 逐项认证；Flink/checkpoint 后的产品投影是历史消费依据，provider/broker 不成为第二历史真值。
- OGC API Processes 只提供协议 facade；执行映射到受控异步 `PlatformRun`/DolphinScheduler process，禁止 GIS provider 自建隐藏 scheduler、queue 和结果真值。
- file/export/offline package 以版本化 Artifact 发布，GeoPackage、FlatGeobuf、GeoParquet、COG、PMTiles、MBTiles 及商业离线包按 capability 认证；大文件交付复用 `DriveTransfer`/multipart、checksum、expiry 和 ConsumerBinding。

#### AR-4.4 Gateway、安全与缓存一致性

- 所有公开 endpoint 统一经过 Gateway；私有化候选基线为 Apache APISIX，云 profile 可替换为 Azure API Management 等认证 adapter。provider 使用 workload identity 和内网策略，不直接暴露公网。
- SubjectContext/PolicyDecision 向 provider 下推 resource、column、row、spatial、temporal、action 和 purpose obligation；无法安全下推时由受控 projection 隔离，不能降级为仅隐藏 UI。
- 版本进入 route、URL/TileJSON/STAC link、ETag 和 cache key；active pointer 切换触发精确 purge 或 namespace rollover。Redis/CDN/GeoWebCache/对象缓存均可丢且可重建，不保存权限或发布真值。
- 统一 auth、WAF、quota/rate limit、signed URL、request/response schema、usage/cost、log/metric/trace、correlation id、审计和 abuse protection；错误、capabilities、tile metadata 和 preview 也必须通过权限检查。

#### AR-4.5 空间体验与确定性多入口

- HumanView、Map/Scene、AgentContext、AIDataset、GWMObservation 都是引用同一 DataProductVersion 的可重建投影。
- NL2Semantic2SQL、SQL/空间分析、表格/图表/2D/3D 地图联动支持保存、分享和 replay；结论绑定查询/算法、语义口径、数据/服务/样式版本和权限。
- Web/Map、API/SDK、CLI/TUI、Notebook 和 Agent 共用 publish/validate/diff/approve/deploy/observe/rollback/retire `CapabilitySpec`。`llm_mode=disabled` 时仍可完成全部 P0 发布和运维；Agent 只能生成可审查 ChangeSet。
- Operate 工作面统一展示 source/sync、Run/Attempt、quality issue、DeploymentRevision、endpoint/consumer、service SLO、缓存、告警、成本和 recovery；支持 Compose/K8s install/upgrade/rollback/backup-restore preflight。

退出门：

- 用户能在目录和地图发现产品，完成申请、审批、订阅、消费、版本变更通知、废弃迁移和到期回收；每个 endpoint 可追溯到 consumer、policy、DataProductVersion、DeploymentRevision 和 owner。
- 同一 DataProductVersion 端到端发布 OGC API Features/Tiles、MVT、COG/raster tile、STAC、versioned export 和 AgentContext；启用相应 profile 时，legacy OGC、3D Tiles、EDR/SensorThings 代表服务也必须通过。协议用 OGC CITE/对应 conformance、STAC validator、TileJSON/style/COG/3D Tiles validator 和平台 contract tests 验收，不能只做 HTTP 200 smoke。
- 发布在持续流量下完成新 revision 构建、缓存预热、原子切换和回滚；客户端不会观察到跨 revision 的 layer/style/schema 混合，失败发布不改变 active pointer，projection 可从固定 ProductVersion 重建。
- resource/column/row/spatial/temporal/purpose 的允许与拒绝用例覆盖 API、Feature、tile、STAC、下载、preview、capabilities 和错误响应；provider 公网直连和未授权数据泄漏为零。
- provider conformance suite 覆盖 capability discovery、schema/CRS/axis order、geometry/empty/invalid、filter/paging、style/label/scale、cache invalidation、cancel/reconcile、restart/failover、metrics、backup/restore 和升级回滚；未认证组合不能被 placement resolver 选择。
- OGC API Processes 请求产生统一 RunRef，可在 Web/API/CLI/TUI 中观察、取消、重试和追溯；DolphinScheduler 是唯一 DataOps 执行真值。
- 在无 LLM 环境中，用户可通过 Web/API/SDK/CLI/TUI 完成定义、preview、diff、审批、发布、监控、回滚和退役，产物与 Agent 提交相同 ChangeSet 时等价。
- 智能问数或空间分析结果可从固定语义/查询/算法、数据/服务/样式版本重放；临时表、交互 Notebook 和 provider 配置不能绕过发布合同。
- 单机/Compose/K8s 目标环境通过安装、升级、provider 故障隔离、Gateway 降级、缓存重建、projection rebuild、回滚和联合恢复演练。
- DataOps Operate 闭环覆盖产品 freshness/quality/SLO、服务 availability/latency/error/cache staleness、告警、DataIncident/Problem/RCA、remediation、backfill/replay、成本和容量；事故修复生成新的可审计 DataProductVersion 或 ServiceDeploymentRevision。

### AR-5 — AgentOps Runtime and UX Uplift（P1）

**依赖**：AR-1 至 AR-4 的确定性专业能力和代表任务通过 parity gate。

**目标**：在 DataOps 通过 parity/control gate 后，建设完整 AgentOps 生命周期；Agent 将自然语言意图转成可审查、可执行、可回滚的数据产品 changeset，降低传统平台复杂度，而不是另建一套隐式 pipeline。

交付：`AgentSpecVersion` bundle（Agent、Prompt、ModelBinding、Tool/Skill、Policy、Memory/Context）；EvaluationSet/EvaluationRun/OnlineVerdict、safety/red-team/tool-accuracy/cost eval；Approval/Promotion、Shadow/Canary、AgentDeploymentRevision；**Temporal-backed** AgentRun/TaskStep/ToolCall/TraceObservation；循环/超时/提示注入/越权检测、Guardrail、Budget、HITL、SafetyIncident/QualityIncident、disable/rollback、feedback 和 DataDemand 回流。RuntimeIdentity、RunnerFactory、RunWorkspace、intent-to-DataProductBlueprint、evidence-backed planning、typed TaskGraph/QualityVerdict、preview/diff/cost/impact、真实 retry/replan 复用统一控制面。

退出门：

- Visual/SQL/Notebook/API/SDK/CLI/TUI/MCP/Agent 使用相同身份、`CapabilitySpec`、definition、策略、工具合同、Run 和审计。
- 用户可从 Agent 提案进入 blueprint/DAG/SQL/policy/Run 详情修改，也可从专业工作台请求 Agent 解释和诊断。
- Agent 和确定性 pipeline 对相同任务产生同一产品版本或明确的可审计差异。
- revise/replan 真实重跑；无效工具、越权工具和高风险写入不可绕过门禁。
- 每个 active AgentDeploymentRevision 都有 bundle/version、评测证据、策略、预算、SLO、owner、灰度范围和 rollback pointer；离线通过不等于可生产。
- 线上 AgentRun/ToolCall 能关联数据版本、策略决定、工具副作用、trace、成本、质量 verdict 和 incident；出现安全/质量/成本阈值越界可自动暂停或回滚。
- AgentOps 事故可从用户反馈、tool failure、policy violation、stuck loop 或数据质量问题回溯到 AgentSpec/Prompt/Model/Tool/Policy 版本，并生成新评测和 changeset。
- 在 AR-0 冻结的代表任务上，Agentic 路径至少在配置步骤、端到端耗时、首跑成功率或失败恢复之一达到批准的 uplift 阈值，并保留非 Agent、无 LLM 的重放；Agent runtime/LLM 不可用时不能使 P0 capability 退化。

### AR-6 — MMFE and Data for AI Factory（P1）

**依赖**：可信 DataProductVersion 和 AgentOps Runtime 稳定。

**目标**：把 MMFE 纳入 Silver/Gold 生产，并建立 DataProduct -> Dataset -> Model -> DataDemand 闭环。

交付：SemanticFusionProductVersion、统一调度 executor、增量/content-hash 执行、空间与非空间多模态融合 benchmark、DatasetVersion、EvaluationSet、Feature/Label lineage、ModelVersion/PromptVersion/Deployment 和 drift/DataDemand；ModelOps/LLMOps 作为 AgentOps bundle 的模型与 Prompt 子域，AI 对象登记统一元数据中心，不能建立第二套 AgentOps 资产目录或发布状态机。

退出门：字段映射、实体解析、时空对齐、冲突识别、置信度校准、人工修正率、吞吐/成本和下游增益达到冻结阈值；未通过质量和权限门的数据不能进入训练、评测和推理。

### AR-7 — GWM Kernel and LLM + GWM Product（P2）

**依赖**：AR-6 形成稳定 GWMObservationProjection。

**目标**：抽取共享 GWM Kernel，并让 TWM/UWM 消费同一可信产品版本。

交付：StateSnapshot、CanonicalAction、Transition、Uncertainty、EvidenceClaimLedger、TWM/UWM adapters、DataDemand 和地图审计。

退出门：关闭 GWM 后 Core Data Platform 仍完整运行；传统/规则、LLM-only、GWM-only、LLM+GWM 四路同题评测证明组合增益；observed/proxy/synthetic 和 claim boundary 自动执行。

### AR-8 — Scale, High-throughput Realtime, Federation and Ecosystem（条件路线）

只有真实负载或跨组织需求触发时启动：

- 独立 Iceberg REST Catalog、更大规模 Spark/Flink 集群、查询联邦和冷热分层。
- 高吞吐生产 CDC、Kafka/事件总线、Flink 多集群 HA、严格 exactly-once 跨系统 sink 和实时指标；只有 freshness/SLA 证明 AR-2 的增量/流 profile 不满足时启用。
- 图/RDF/Search/LanceDB 读投影。
- 跨组织 OGC/STAC federation、MCP/A2A 数据空间和隐私计算；单域 OGC/STAC 发布属于 AR-4 P0，不得延后到本阶段。
- 多集群、HA、DR、服务拆分和容量治理。
- Kafka/Redpanda、Trino、专用 vector/graph/RDF、跨地域 federation、service mesh 等条件能力；OpenMetadata/Gravitino/DolphinScheduler/Temporal 的扩容、版本升级和替换仍须经 ADR、TCO、恢复与 conformance 评审。

进入门：现有架构在已批准的容量、SLO、隔离或互操作 benchmark 上失败，并完成 ADR、TCO、owner 和回滚评审。

## 9. 首条 Vertical Slice 验收模型

| 层 | 建议首批对象 | 必须记录 |
|---|---|---|
| Raw | source bundle、source manifest | source URI、license、checksum、size、CRS hint、spatial/temporal extent、owner、sensitivity |
| ODS | `ods_land_patch_source` | source row ID、batch ID、ingested_at、raw asset version、raw fields |
| DIM | `dim_region`、`dim_date`、`dim_land_class`、`dim_data_source` | authority/version、effective dates、code mappings |
| DWD | `dwd_land_patch`、`dwd_land_change` | canonical ID、geometry、period、class、area、quality status、lineage |
| DWS | `dws_region_period_change`、`dws_h3_period_coverage` | metric/formula version、source snapshots、aggregation grain |
| ADS | PostGIS serving schema、STAC Collection/Item、Feature/MVT/COG/API/Map/Scene projection | product version、service/layer/style/TMS version、provider/build/deployment/endpoint revision、ACL/SLO、consumer、cache namespace、rollback pointer |

Golden checks 至少覆盖：

- raw/ODS 行数和字段对账；重复摄取幂等。
- CRS、geometry validity、empty/duplicate、行政区包含关系和拓扑。
- 地类代码、必填字段、单位、时间有效性和标准版本。
- 面积从 DWD 到 DWS 的守恒及允许误差。
- 全链路 column/object/run lineage 和 checksum。
- snapshot/time travel、schema evolution、重跑、回滚和 PostGIS projection rebuild。
- 双用户/双租户访问隔离和敏感字段策略。
- Human/Agent/AI/GWM 投影引用同一产品版本。
- OGC API Features、MVT、COG/TiTiler、STAC 和启用 profile 的 legacy OGC/3D 从同一产品版本发布；active revision、style、cache 和 rollback 一致。
- 服务在 Gateway 内外、不同 zoom/extent/filter/format、capabilities/preview/error 路径均通过空间/属性/用途权限负向测试。

## 10. 衡量方式

### 10.1 架构与数据正确性

- 100% 目标环境通过 migration ID/checksum 和 schema fingerprint 一致性门。
- 100% 发布资源拥有唯一 ResourceURN、不可变 version、owner、location、contract 和 authority source。
- 100% 发布产品可追溯到 raw asset、Run/Attempt、规则/标准版本和代码版本。
- 100% serving projection 可从 DataProductVersion 重建。
- 100% active GIS endpoint 关联不可变 Service/Layer/Style/TMS/Policy/Deployment revision、provider fingerprint、consumer/SLO 和 rollback pointer；provider 配置不得成为唯一发布真值。
- 100% layer transition 通过声明式输入输出合同和质量门。
- 未授权对象、属性、关系和 artifact 返回数为 0。
- 未授权 feature、tile、raster window、STAC item/asset、3D tile、capabilities、preview 和错误响应泄漏数为 0；公开 provider 直连数为 0。
- 同输入、同配置、同代码版本的确定性 pipeline 结果 hash 一致。
- 每个生产 Run 固化 provider/engine/version/binding；跨 engine/profile 的 golden 结果满足批准的数值、geometry、时间与水位线语义容差。
- 每个 active DataProductVersion 都有 DataOps release/promotion、quality verdict、DataSLO、owner/on-call、incident policy、rollback pointer 和运行观察证据。
- 每个 active AgentDeploymentRevision 都有 AgentOps bundle、EvaluationBinding、online verdict、policy/budget、owner、灰度状态、incident policy 和 rollback pointer。

### 10.2 运行质量

- DolphinScheduler schedule/process/task queue age、worker group/resource saturation、retry/complement、Temporal workflow/task-queue latency/activity retry、cancel/reconcile 和 executor saturation 可观测。
- ingest、transform、publish、rollback 各阶段有成功率、延迟、数据量和失败原因。
- GIS 服务发布和运行至少观测 build/validation/warmup/activation/rollback 时延与失败率，endpoint availability、p50/p95/p99、error/timeout、cache hit/staleness/purge lag、provider saturation、bytes/tiles/features served、consumer usage/cost 和 revision skew。
- storage/compute provider 的 submit latency、engine utilization、checkpoint age、cancel/reconcile、bytes scanned、egress 和 cost attribution 可观测。
- DataOps 指标至少覆盖 release lead time、deployment frequency、change failure rate、data freshness/quality/SLO、DataIncident MTTR、replay success 和 cost drift。
- AgentOps 指标至少覆盖 eval regression、online task success、tool-call error/latency、stuck-loop rate、policy violation、human intervention、token/cost budget、safety incident MTTR 和 rollback success。
- checkpoint/resume 不重复提交数据或产生重复产品版本。
- metadata harvest 有 freshness、drift、conflict、tombstone 和 impact completeness 指标。
- RPO、RTO、吞吐和 p95/p99 在 AR-0 按试点环境冻结，不使用未验证的行业数字。

### 10.3 产品价值

- 12 项能力下限代表任务的 parity 通过率；只有全部通过，才可宣称达到下一代时空 Data Platform 基线。
- 同一代表任务的有效配置步骤、端到端耗时、首跑成功率和失败恢复时间；分别比较旧平台、专业入口和 Agentic 入口。
- Agentic 路径必须至少在一项批准指标上稳定优于专业基线，同时保持权限、审计、回滚、definition 导出和非 Agent 重放能力。
- 从源数据到可用数据产品的周期。
- 自动发现/修复率、人工修正率、质量趋势和规则误报/漏报。
- Human/Agent/AI/GWM 的活跃消费、复用和版本升级影响。
- MMFE 和 GWM 相对确定性/传统/单引擎基线的可重复增益。

## 11. 近期执行清单

只允许按以下顺序进入实现：

1. 导出所有目标环境 schema/config fingerprint，修复重复 migration ID、checksum 和 fail-open runner。
2. 完成部署、存储、bucket、registry、scheduler/job、API/GIS endpoint、图层/样式/缓存、provider/Gateway、数据资产、消费者和权限事实盘点；部署 OpenMetadata/Gravitino/DolphinScheduler/Temporal sandbox，冻结 owner、version、OIDC、backup/restore 和升级责任。
3. 冻结 ResourceURN、ResourceVersion、PlatformDefinition/PlatformRun/FrameworkAttemptObservation/Artifact/LineageEvent、SubjectContext 与 storage/table/compute provider 最小合同。
4. 分阶段实现 `gda-metadata-fabric-bridge`：M1 只读 mapping/reconciliation、M2a 本地 foundation/重启连续性、M2b-1 本地三存储恢复、M2b-2 隔离 versioned/Object-Locked repository round-trip、M2b-3 本机双集群 + Kubernetes 外 COMPLIANCE repository + 独立 writer/reader、M2c-1 provider-native metrics、M2c-2 临时 OTel Collector + JSON Exporter 的双周期本地 pipeline、M2c-3 本地单 job scrape 故障检测/配置恢复/完整清理 evidence、M2c-4 绑定 source revision 的 production observability readiness contract，以及 M2d-1 本地 kindnet 跨节点 NetworkPolicy enforcement 已验证；M2c-4 当前仍有 20 项 blockers，M2d-1 也未验证生产 provider policy 或 tenant isolation。下一步完成 source host/cluster 外的生产 bucket、KMS/TLS/workload identity、source-loss recovery 与 RPO/RTO，并批准 metrics backend、retention、OTel/TLS、tenant、alert/SLO/owner 后在受保护环境验证持续采集、存储、查询、真实告警投递、runbook 响应和 provider NetworkPolicy；再推进 OIDC、upgrade/rollback、registry provenance 和 owner/runbook；之后才进入 M3 ingestion/OpenLineage/conformance。
5. 实现 `gda-orchestration-gateway`、DolphinScheduler process/task/schedule/complement/worker-group、Spark/Flink provider task adapter 和故障注入；不再开发新的 lease/queue/scheduler。
6. M3-28 已冻结全量重庆真实源的 path-free physical/metadata admission baseline，M3-29 已建立 metadata-only extraction provenance gap baseline，M3-30 已选择 `bishan_land_use_dltb_local` 并把八项治理输入固化为 fail-closed pending records，M3-31 已将三层证据统一成 protected admission readiness contract，M3-32 已固定 protected attestation intake/evaluate/verify boundary，M3-33 已固定受保护 workflow execution/provenance boundary，M3-34 已用 Natural Earth public-domain bytes 验证 immutable Landing 与 ledger registration path；下一步用 public Landing 绑定最小 DataOps PlatformRun 并物化轻量 serving slice，同时 provision 专用 environment/runner 并取得 Chongqing 的 15 项外部 attestation，未获批准前不得 content admission。
7. 冻结 Default Lakehouse、Cloud Managed、Lightweight Integrated profiles；以统一 Run 完成默认 MinIO/Iceberg/Spark/Flink、轻量 PostGIS/DuckDB 和 Azure 代表 adapter 的 conformance smoke。
8. 实现跨 profile 的 Raw -> ODS -> DIM/DWD -> DWS -> ADS 通用生产、质量、发布、回滚和 golden equivalence。
9. 建立 DataProductBlueprint、模型版本和 Visual/SQL/Notebook 共用 definition 的 Build 工作台，打通 preview、test、publish、approval 和 rollback。
10. 完成并接受 ADR-017：用冻结服务集 benchmark pg_featureserv/pygeoapi、Martin、TiTiler、pgSTAC/stac-fastapi、GeoServer、APISIX 及启用的 SuperMap/ArcGIS/云 provider；输出 capability/TCO/security/SLO/upgrade matrix 和 production-supported 清单。
11. 实现 GIS Service Control Plane 及 Service/Layer/Style/TMS/Cache/Policy/Deployment/Endpoint/Consumer/SLO 对象；所有 publish/validate/warmup/activate/rollback/retire 进入统一 PlatformRun 和审计。
12. 打通 OGC API Features/Tiles、MVT、COG/raster、STAC、versioned export 和启用 profile 的 legacy OGC、3D、EDR/SensorThings 代表服务的 provider adapters、Gateway、权限下推、缓存 namespace、原子切换、回滚、conformance 与故障注入；OGC API Processes 映射 DolphinScheduler RunRef。
13. 建立基于 OpenMetadata + Gravitino metadata fabric bridge 的 Discover/Operate/Govern 工作面，完成资产申请订阅、服务发布监控、消费者影响、空间分析重放和联合恢复；无 LLM 的 Web/API/SDK/CLI/TUI 路径完整验收。
14. 实现 DataOps release/promotion、DataSLO、数据/服务观测、DataIncident/Problem、remediation、replay 和成本反馈闭环。
15. 对 12 项代表任务及 GIS 发布 provider/conformance/security matrix 完成 parity 与 control gate；此时才接入 AgentOps Runtime。
16. 部署 Temporal production profile；AgentOps 通过 Temporal workflow 的 approval/signal/retry/compensation、Agent bundle eval、shadow/canary、online verdict、incident/rollback 和配置步骤/耗时/首跑成功率/恢复效率 uplift gate 后，再推进 MMFE Data for AI 和 GWM 共享 Kernel。

## 12. Stop List

AR-4 parity/control gate 退出前暂停以下主线扩张：

- 新的通用 Agent、推理模式、工具市场能力、领域 Agent 页面和孤立前端 Tab。
- 没有首条数据产品消费者的数据库、图、向量或 RDF 基础设施。
- 仅增加 spec、mock、配置、文档或 notebook，却标记为生产完成。
- 直接从用户上传文件或临时 PostGIS 表生成新的“权威”AI/GWM 数据集。
- 新增局部 metadata registry、scheduler、queue、后台线程或进程内长任务状态。
- 绕过 Service Control Plane 直接公开 GeoServer/Martin/TiTiler/STAC/SuperMap/ArcGIS endpoint，或让 provider/Gateway 配置成为服务定义、权限和 active revision 的唯一真值。
- 未经过 ADR-017 capability/conformance/security/TCO 认证即增加新的 GIS server、3D 服务格式、tile cache 或 API gateway；不得以 endpoint 可访问、地图可显示或 HTTP 200 代替发布完成。
- 新增孤立的 Prompt/Model/Tool/Skill/Eval/Trace/Feedback registry，或以离线评测和 trace 数量冒充 AgentOps 完成。
- 在 DataOps/AgentOps 缺少 owner、SLO、incident、rollback 和线上证据时新增领域 Agent 或自动写入能力。
- 与首条 vertical slice 无关的架构重写和跨模块重构。

## 13. 文档与状态纪律

- 本文只维护总体架构、依赖顺序、阶段状态和退出门。
- 阶段详细设计放入 `docs/superpowers/specs/`；实施步骤放入 `docs/superpowers/plans/`；重大决策放入 `docs/architecture-decisions/`。
- 已完成历史保存在 [roadmap-history-through-2026-07-18.md](roadmap-history-through-2026-07-18.md)，不再混入主 roadmap。
- 状态只允许 `planned`、`in_progress`、`blocked`、`verified`。`verified` 必须同时有实现、测试和真实后端/产物证据。
- 文档中的目标架构、配置合同、smoke、benchmark 和生产能力必须分别标识，不得互相替代。

## 14. 当前状态

| 阶段 | 状态 | 下一证据 |
|---|---|---|
| AR-0 Architecture/Schema/Runtime Truth Freeze | `in_progress` | 全环境 schema/config fingerprint、迁移 fail-closed、事实清单、storage/compute/GIS serving provider profile/capability、ADR-017 benchmark、owner/SLO 和首条数据/服务验收集冻结 |
| AR-1 Unified Metadata + Orchestration Control Planes | `in_progress` | controlled gateway、DolphinScheduler adapter、Metadata Fabric M1/M2a/M2b、M2c-1 provider metrics、M2c-2 本地临时 OTel pipeline、M2c-3 本地 scrape failure/recovery、M2c-4 production observability readiness contract 与 M2d-1 本地跨节点 NetworkPolicy enforcement 已验证，生产观测和生产 policy/tenant isolation 仍 blocked；下一证据是 source host/cluster 外的生产 recovery、持久 metrics backend/TLS/tenant/真实 alert delivery/SLO、OIDC、受保护 provider NetworkPolicy、升级回滚/registry provenance，以及受控 ingestion/replay 与无双写验收 |
| AR-2 Source/Ingestion + Geospatial Lakehouse Vertical Slice | `in_progress` | M3-28 admission baseline、M3-29 extraction provenance gap baseline、M3-30 first-candidate governance gate、M3-31 protected admission readiness、M3-32 attestation intake、M3-33 protected verifier workflow contract 与 M3-34 public immutable Landing slice 已完成；public profile 已有真实 bytes/manifest/ledger path，但 DataOps PlatformRun、Bronze/Silver/Gold、serving 和 rollback 尚未完成；checked Chongqing baseline 仍为 `admission_eligible=false`，下一证据是 public Landing 的最小 DataOps run，以及专用 environment/runner provisioning、15 项外部 attestation 和首次 protected verifier run |
| AR-3 Data Product Engineering + Governance Workbench | `planned` | Blueprint、模型、Visual/SQL/Notebook、DataOps CI/CD、质量/安全/审批共用 definition 和产品生命周期 |
| AR-4 Asset/GIS Service/Spatial Experience Operations | `planned` | Service Control Plane、Features/Tiles/MVT/COG/STAC/export 及条件 legacy OGC/3D/EDR provider、Gateway/权限/缓存、原子切换/回滚、Discover/Operate/Govern 和无 LLM 多入口通过 conformance/parity/control gate |
| AR-5 AgentOps Runtime + UX Uplift | `planned` | DataOps parity/control 通过；Agent bundle eval、deployment、online observation、incident/rollback 和 uplift gate |
| AR-6 MMFE + Data for AI | `planned` | 稳定 DataProductVersion、统一 Run/Artifact 和 AgentOps ModelOps/LLMOps binding |
| AR-7 GWM Enhancement | `planned` | 可信 GWMObservationProjection |
| AR-8 Scale/High-throughput Realtime/Federation/Ecosystem | `planned, conditional` | 真实容量/SLO/freshness/互操作触发证据 |
