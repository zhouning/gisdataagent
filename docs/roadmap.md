# GIS Data Agent — 总体架构 Roadmap

**Last updated**: 2026-08-07

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

**2026-07-31 migration reliability 与 runtime truth checkpoint（已验证切片）**：

- [x] 迁移身份升级为完整 filename ID + SHA-256 checksum；冻结 `011` 至 `017`
  历史冲突集合，任何新增版本冲突或内容漂移 fail closed。
- [x] PostgreSQL advisory lock、结构化 `MigrationReport`、单项事务回滚和失败后停止；
  CLI 提供 validate/audit/migrate/reconcile/compare。
- [x] 历史数据库 reconcile 必须有 actor/reason 和逐 migration schema probe；开发库
  24 个漏账状态通过 probe 入账，未通过的 `091` 被真正执行，最终 93/93 fingerprint
  一致。详见 [ADR-090](architecture-decisions/adr-090-fail-closed-migration-ledger.md)。
- [x] Compose/Kubernetes migration authority 独占 DDL；应用启动只读验证账本，开发容器
  重启后 healthy。空库重放、幂等重跑、SQL 故障停止和 checksum drift 均由真实
  PostgreSQL 验证。
- [x] migration authority 收归 ledger/sequence owner，撤销默认或遗留 DML，仅向
  `agent_user` 授予 ledger SELECT 并验证有效权限；真实负向 INSERT 返回 permission
  denied。主 Compose 与 Gemma4 demo Compose 均执行相同 one-shot 边界。
- [x] 主 Compose 与 Gemma4 demo 建立严格、非敏感、版本化 DeploymentProfile；冻结
  Compose project/file/network/service/volume、规范化 config fingerprint、migration、
  released standard、capability、HTTP probe 和 governance 合同。未知字段、host path、
  带凭据 URL 和敏感环境值进入证据时 fail closed。详见
  [ADR-091](architecture-decisions/adr-091-versioned-deployment-profile-runtime-truth.md)。
- [x] 主 Compose 开发环境完成 live verifier：required service 全部 healthy，one-shot
  service exited 0，迁移 93/93、标准 174 数据元、应用到 Redis 连接和 MVT/health/ready
  HTTP 行为均通过；`technical_pass=true`、`profile_contamination=false`。首次运行发现并
  修复了 Gemma4 Redis source/network/volume 污染，未删除、合并或复制任何 volume。
- [x] 主 Compose 完成全量隔离逻辑恢复演练：3.03 GB PostgreSQL dump 恢复到
  `template0` 临时库，93 条迁移、174 个标准数据元、777332 个 TWM 状态对象、1433322
  条关系和 29556 条证据均与源一致；MinIO lakehouse 的 213 个对象、2.29 GB 内容
  SHA-256 inventory 一致。端到端观测 459.499 秒，临时 container/volume/bucket 已清理，
  主环境保持 healthy。详见
  [ADR-092](architecture-decisions/adr-092-isolated-logical-recovery-rehearsal.md)。
- [x] 上述演练已固化为 `main-compose-dev-20260731` 版本化恢复 SLI 基线；严格合同绑定
  DeploymentProfile、Compose config、脱敏源报告、数据库/对象存储逻辑身份、容量和四项
  阶段耗时。版本化证据重建的五项检查全部通过；schema 只允许单次观测，不接受未经审批
  的 SLO/RPO/RTO 数值。详见
  [ADR-093](architecture-decisions/adr-093-versioned-recovery-sli-observation-baseline.md)。
- [x] 主 Compose 完成真实 6.72 GB physical backup + streamed WAL 的有界 PITR：base backup
  结束后提交 target/later transaction，隔离恢复包含 target、排除 later 并完成 promote；
  manifest、WAL 内容、93 条 migration、174 个标准数据元和重庆 TWM 代表表逻辑身份全部
  对账，端到端 24.994 秒且临时 slot/probe/container/介质归零。版本化 seal 五项重建检查
  全部通过。详见
  [ADR-094](architecture-decisions/adr-094-bounded-streamed-wal-pitr-rehearsal.md)。
- [ ] 该演练只验证开发环境单节点、短窗口 streamed-WAL PITR；`archive_mode=off`，尚未
  证明批准的 RPO/RTO、持续 WAL archive、slot 监控、备份加密、异地副本、跨
  PostGIS/MinIO 时间点一致性、Iceberg catalog/STAC projection 和 DataProductVersion
  rebuild；因此 `backup_restore` 与 `slo` blocker 保持不变。
- [ ] 技术通过不等于晋级：当前 `promotion_ready=false`，仍缺 `business_steward`、
  `license_status`、`slo` 和 `backup_restore`；Gemma4、staging、production 与客户环境
  仍需分别运行并批准，不能外推主 Compose 开发环境证据。
- [x] 首条真实数据验收集已技术冻结：重庆 JQDLTB golden 绑定 released 标准和
  `parcel_current` 业务域，在 `llm_mode=disabled` 下获得 precision 1.0、recall 0.6；
  重庆 OSM 道路和中心城区建筑两个负向 holdout 均为零自动推荐。协议固定原始压缩包、
  标准数据元和 Shapefile sidecar bundle 指纹，报告不保存样本值或绝对路径。详见
  [ADR-089](architecture-decisions/adr-089-standard-version-bound-application-contract.md) 和
  [验收协议](../benchmarks/standard_mapping_chongqing_v0_1/README.md)。
- [ ] 该数据切片尚不可 promotion：`business_steward` 与 `license_status` 未确认；当前只
  验证标准映射 proposal，不代表 AR-2 Raw -> lakehouse -> DataProductVersion ingestion
  已开始或完成。
- [x] 首个 P0 `CapabilitySpec` 可执行切片已建立：`catalog.asset.search@1.0.0` 以同一
  Draft 2020-12 输入/输出合同约束现有 `search_data_assets`，登记 Web/API/SDK/CLI/TUI/
  Notebook/Agent 入口，显式映射 HTTP `q` 到 canonical `query`，并从同一 spec 生成
  OpenAPI 3.1 与 MCP projection。受认证 `/api/capability-specs` 提供版本、fingerprint、
  parity matrix 和 projection；`llm_mode=disabled` 验证仍保留六条确定性入口，Agent 入口
  被排除。实现返回若违反输出合同会 fail closed，不能降级成普通业务错误。
- [x] 第二个 P0 `CapabilitySpec` 纵向切片已建立：`dataops.run.submit-manual@1.0.0`
  复用 ADR-097 已验证的人工 DataOps 原子准入与 DolphinScheduler transactional outbox，
  将 API 请求/响应模型提升为 `dataops_manual` 共享合同，并直接生成同一 Draft 2020-12
  input/output schema。spec 明确 `long_running`、external write/high risk、required
  idempotency、required execution-plan preview Artifact、RunRef、cancel/reconcile、tenant-scoped
  admin/platform-operator policy；OpenAPI 3.1 准确表达 platform-v1 response envelope，AsyncAPI
  3.0 投影使用 CloudEvents 1.0 `PlatformRun` 状态事件并绑定同一 capability fingerprint。
  受认证详情 API 返回 OpenAPI/AsyncAPI；`llm_mode=disabled` 下暴露 API 以及共用该认证 HTTP
  projection 的 Web/SDK/CLI/TUI/Notebook，Agent 保持 `planned`。相关合同、路由和既有 Gateway
  聚焦回归 97 项通过，Ruff 与 diff check 通过。
- [x] long-running 状态事件的首期真实投递闭环已建立：`platform_run_event` 保持唯一、不可变
  Run 状态事实，`129_platform_run_event_delivery_outbox.sql` 通过同事务 trigger 只为部署后的新事件
  建立 PostgreSQL outbox；CloudEvent `id` 复用原始 event UUID，`status/state_version` 从历史事件而非
  当前 Run 快照生成。租约、`SKIP LOCKED`、有界重试、dead letter、同 Run 顺序、强制 RLS 和双租户
  隔离均由数据库执行；worker 只持有逻辑 destination ref，服务端 URL/token file 不进入账本，使用
  `application/cloudevents+json`、禁用 redirect，并仅在 HTTP 2xx 后确认。实际 payload 已通过同一
  CapabilitySpec 生成的 AsyncAPI/JSON Schema；一次性 PostgreSQL 16 + 本地真实 HTTP receiver 验收
  覆盖 prospective/no-backfill、原子写入、2xx 确认、过期租约接管、dead letter 与顺序阻塞，结果
  `1 passed`；全新 PostgreSQL 16 上既有 Gateway 集成回归 `2 passed`；合同/Gateway 聚焦回归
  `120 passed, 3 skipped`（未配置数据库时跳过三项 PostgreSQL 真实验收）。
- [x] 首个 P0 command `CapabilitySpec` 已建立：`dataops.run.cancel@1.0.0` 复用既有人工取消
  原子准入、expected state version、稳定 `client_request_id`、Run 绑定的 execution-plan Artifact、
  独立 `dolphinscheduler.cancel` policy evidence 与 cancel outbox；未新增命令队列或 Run authority。
  canonical input 将 `run_id` 与 body 字段纳入同一 Draft 2020-12 合同，通用 HTTP projection 再将
  `run_id` 如实映射为 OpenAPI path parameter，body 禁止重复或伪造该身份。共享请求/响应合同位于
  `dataops_cancel`，现有 REST 路由只负责认证身份、path/body 适配和 server-owned runtime profile；
  spec 标记 command、external write/high risk、required idempotency、expected version、同步 admission、
  reconcile；API 与共用其认证 HTTP projection 的 Web/SDK/CLI/TUI/Notebook 标记 implemented，Agent
  仍保持 planned。取消收敛继续通过同一真实 `PlatformRun` CloudEvents
  AsyncAPI 通道观察。合同/路由聚焦回归 `93 passed`，全新 PostgreSQL 16 Gateway 回归 `2 passed`。
- [x] DataOps 确定性客户端纵向切片已建立：`CapabilityClient` 在网络调用前使用本地 canonical
  input schema fail closed，并读取受认证 capability detail 比对精确 version/fingerprint；不一致时不会
  发送 command。匹配后由同一 `HttpProjection` 自动拆分 path/query/body，携带 capability fingerprint，
  使用既有 `access_token` cookie 调用 Gateway，再按 direct/platform-v1 envelope 提取并验证 canonical
  output。SDK 不签发身份、不判断策略、不直连控制库或调度器；CLI `capability list/show/invoke` 仅为
  SDK 的结构化薄适配器，凭据来自环境或 token file，不进入命令历史，Notebook 直接复用同一客户端。
  SDK/CLI/registry/Gateway/CloudEvents 扩大回归 `168 passed, 3 skipped`；三项 PostgreSQL 用例在一次性 PostgreSQL 16
  中单独 `3 passed`，Ruff 与 diff check 通过，Gateway 静态报告为 `valid`。
- [x] CapabilitySpec 执行期协商已建立：所有 HTTP projection 统一声明可选
  `X-GDA-Capability-Fingerprint`，SDK 每次执行都发送其已验证的本地 fingerprint；catalog search、
  manual DataOps submit 与 run cancel 三个真实执行入口在认证/身份校验后、领域解析和 Gateway 调用前
  使用 canonical spec 做常量时间比较，错配返回 `409 capability_contract_mismatch` 且不产生领域调用。
  这关闭了 SDK discovery 与 execution 之间的部署切换窗口，执行阶段 409 也恢复为类型化
  `CapabilityContractDriftError`，不会被当作普通业务冲突重试。当前缺失 header 仍兼容旧客户端；待
  Agent 迁移且 Web/TUI/Agent 取得跨入口证据后，才能把生产 profile 提升为 required，不能提前破坏入口。
  扩大回归 `257 passed, 3 skipped`（未配置一次性 PostgreSQL 时显式跳过三项真实库验收），核心
  Ruff 与 diff check 通过；Gateway 静态报告为 `valid`，23 条路由、0 项错误。
- [x] DataOps 的确定性 TUI 入口已建立：现有 Textual TUI 新增受认证的 `capability list/show/invoke`
  薄适配器，发现与执行继续只调用公开 CapabilitySpec/Gateway HTTP projection，并复用
  `CapabilityClient` 的本地 schema 校验、远端 version/fingerprint preflight、执行期 fingerprint header
  和 canonical output 校验。凭据只从 `GDA_ACCESS_TOKEN` 或 `GDA_ACCESS_TOKEN_FILE` 委派，不进入
  slash command 或历史；Textual `8.1.1` 同步进入基础安装合同，结束 requirements 与 pyproject 漂移。
  低风险只读 query 可直接执行；所有带 side effect 或 high/critical risk 的调用先展示 capability、版本、
  risk、side effect 和完整 canonical input，使用绑定 spec fingerprint 与输入的 12 位确认码，五分钟过期，
  错码、过期、未确认或已有 pending invocation 时均不发网络请求。确认后仍由服务端 human identity、
  policy、execution-plan Artifact、idempotency/expected version 和审计账本决定是否准入；TUI 不成为第二
  权限或状态机。`dataops.run.submit-manual` 与 `dataops.run.cancel` 的 TUI surface 据此提升为
  `implemented`，扩大回归 `285 passed, 3 skipped`，核心 Ruff、diff check 与 23-route Gateway 静态
  报告通过。该里程碑完成时 Web/Agent 仍为 `planned`。
- [x] DataOps 的确定性 Web 入口已建立：现有 Capabilities 工作面新增“平台能力 / 技能工具”分段，
  默认从受认证 `/api/capability-specs?surface=web&llm_mode=disabled` 发现 canonical spec，不新增孤立
  基础平台 Tab。Web client 使用当前登录 cookie，通过 AJV Draft 2020-12 与 format 扩展在网络前校验
  canonical input，并按同一 `HttpProjection` 拆分 path/query/body、发送 capability fingerprint；执行前再次
  获取精确 version/fingerprint，发现部署漂移即不发送命令，执行窗口 `409 capability_contract_mismatch`
  也恢复为类型化漂移。所有 side effect 或 high/critical risk 调用使用与 TUI 等价的 spec + input 绑定
  12 位确认码和五分钟过期门，前端角色仅作提示/禁用，服务端 policy 仍是授权真值。direct/platform-v1
  output 均按 canonical schema 验证并展示结构化 receipt；DataOps 首次准入 `202 created=true` 与幂等重放
  `200 created=false` 已同时进入 OpenAPI、SDK 和 Web 成功合同。`dataops.run.submit-manual` 与
  `dataops.run.cancel` 的 Web surface 据此提升为 `implemented`，Agent 继续保持 `planned`。Web client
  7 项单测、生产 TypeScript/Vite build、Python 扩大回归 `211 passed, 2 skipped`、核心 Ruff 与
  diff check 均通过；Gateway 静态报告为 `valid`，23 条路由、0 项错误。
- [ ] 当前完成的是三个代表 capability 和 PostgreSQL transactional outbox + 单 destination HTTP
  consumer 的纵向切片，不代表 Kafka/broker、生产多副本 worker、跨区域 HA、queue SLO/告警或部署
  晋级已完成。Agent 的 DataOps 适配器、更多 P0 query/command/long-running、全量 policy
  enforcement matrix 与跨入口等价证据仍未完成，不能据此标记 AR-0 退出或宣称多入口平台整体完成。
- [ ] AR-0 整体仍为 `in_progress`：staging、production、客户环境 fingerprint 与批准的
  reconcile 证据，以及 config/provider/capability/SLO 等其余退出门尚未完成。

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

**2026-07-31 至 2026-08-01 unified control/evidence ledger 开发环境检查点**：

- [x] 保留已执行的 `092_std_application_mapping_contract` 不可变历史，并将并行主线的
  `092_platform_control_ledger` 显式冻结为唯一允许的第二个 `092`；任何第三个同号文件
  仍 fail closed。主 Compose PostgreSQL 已前向迁移到 102/102，catalog/database
  fingerprint 一致且无 checksum、identity 或 metadata drift。
- [x] `Resource`、`ResourceVersion`、`PlatformDefinitionVersion`、`PlatformRun`、input
  binding、RunEvent、FrameworkAttemptObservation、Artifact、LineageEvent、command outbox、
  不可变 `QualityResult`、DataIncident、IncidentEvent 和 incident notification outbox 已进入
  统一 `gda_control` 账本；Run
  只有绑定调度器成功观测、
  content-bound output、独立 passed QualityResult 和输入到输出血缘后才能判定 succeeded。
- [x] 最小权限 `gda_control_gateway`、租户 RLS、17 个 `/api/platform/v1` 端点和
  DolphinScheduler adapter/command consumer/worker 合同已接入应用。应用登录角色只通过
  transaction-local `SET ROLE` 和 `app.current_tenant` 访问账本；主 Compose 实测角色为
  `gda_control_gateway`、租户上下文为 `local-dev`，未登录 HTTP 请求返回结构化 401。
- [x] 平台合同/授权/网关/调度适配/迁移/部署单测 118 项通过，真实 PostgreSQL 的账本、
  append-only、双租户、回调/outbox 和 evidence-gated success 集成测试 3 项通过；重建后
  `/health`、`/ready` 均为 200，PostgreSQL、MinIO、Redis 和应用容器 healthy。
- [x] 首个真实源版本已按原始重庆璧山 `JQDLTB` Shapefile 全 sidecar bundle 登记：
  1,555 个要素、EPSG:4523、bundle SHA-256
  `cae2047f6b72127e5eae0651909761c0f06d8c3e0491921dbd806c653ba715c3`。
  全量只读审计覆盖 bundle、CRS、几何、必填源字段、必填值、主键、数值和面积一致性，
  确定性报告与非权威 evidence Artifact 已通过最小权限网关写入 `local-dev` 账本；重复登记
  三个对象均幂等返回 `created=false`。工作台会分别显示字段映射基准和全量源质量状态。
- [x] DolphinScheduler `3.4.2` 单机开发 sandbox 的 PostgreSQL、API、master、worker 和
  alert 均已启动；tenant、最小权限 service user、project 和独立 worker group 由幂等
  bootstrap 管理。真实 JQDLTB `PlatformRun de2a6b36-4b3a-5bde-89a6-c50ef4100721`
  经 PostgreSQL transactional outbox 投递到 process instance `1`，认证 executor 完成
  1,555 个要素的全量只读扫描；DolphinScheduler 执行状态为 `SUCCESS`。
- [x] 平台没有把 scheduler `SUCCESS` 提升为产品成功：权威 `QualityResult
  3cd806bb-3b3e-59c5-9526-050506ff8f96` 判定 `failed`，质量评估 ResourceVersion 和
  source -> assessment 血缘已落账，Run 事件序列为 `accepted -> dispatching ->
  reconciling -> failed`。终态归档重放时 observation、Resource、ResourceVersion 和
  LineageEvent 均返回 `created=false`，本次 Run 关联的 `data_product` 资源计数为 0。
- [x] 已对单机开发 sandbox 执行真实 DolphinScheduler runtime restart：runtime 容器
  启动时间发生变化，metadata PostgreSQL 容器身份和启动时间保持不变；20.875 秒后 API
  恢复 `UP`。重启后仍从持久化元数据定位 process instance `1`，并恢复相同 PlatformRun、
  QualityResult、Evidence Artifact、质量评估 ResourceVersion 和 LineageEvent；终态归档
  重放未产生新 observation、Resource、ResourceVersion、LineageEvent 或状态迁移。
- [x] 已按 [ADR-095](architecture-decisions/adr-095-governed-dataops-invocation-and-backfill.md)
  建立不可变 DataOps invocation：trigger kind、UTC 半开逻辑窗口、显式 schedule time、
  schedule reference、请求身份和 fingerprint 进入 `ResourceVersion`，并以 `invocation`
  input binding 自动加入策略资源范围。gateway 的多 input binding 幂等比较已改为规范排序，
  command worker 也会把 DeploymentProfile IANA 时区传入 provider adapter。
- [x] 真实重庆 JQDLTB backfill Run
  `c4c54854-885f-55f0-a445-cb1baf4ab20a` 经 transactional outbox 创建唯一
  DolphinScheduler instance `2`；provider metadata 的 `command_type=5` 已由固定版本枚举
  反证为 `COMPLEMENT_DATA`，schedule time 为 `2026-07-01 09:00:00`，Run、definition、
  invocation version/hash 和逻辑窗口 correlation 完整。实例 `SUCCESS` 后平台仍根据 1,555
  条全量扫描的权威质量结果 `failed` 将 Run 终止为 `failed`，未创建 DataProductVersion。
  终态重放的 observation、assessment version、lineage 和状态迁移均为 `created=false`；
  本轮 93 项相关合同/adapter/gateway/worker 测试通过。
- [x] 已按
  [ADR-096](architecture-decisions/adr-096-atomic-dataops-schedule-window-admission.md)
  建立 schedule-window 原子准入：精确窗口的 tenant/definition/schedule reference/scheduled
  time/UTC 半开逻辑窗口形成确定性 window identity、Run ID 和 idempotency key；PostgreSQL
  transaction advisory lock 内原子写入 invocation、策略 Artifact、PlatformRun、input binding
  和 outbox。失败全事务回滚，同窗并发/重放保留首次准入时间且不产生孤立对象；controller
  不解析 cron、不保存 timer/lease/queue 状态。
- [x] 真实重庆 JQDLTB 漏窗恢复 Run
  `70b0ac4b-d142-5180-9868-811a872a4d5b` 创建唯一 DolphinScheduler instance `3`；provider
  `commandType=START_PROCESS`、`scheduleTime=null`，schedule reference/time、invocation、Run、
  tenant、definition、source 和逻辑窗口 correlation 完整，未启用 native ONLINE schedule。
  同窗重放所有原子对象均 `created=false`；provider `SUCCESS` 后平台仍根据 1,555 条全量扫描
  的权威质量结果 `failed` 将 Run 终止为 `failed`，未创建 DataProductVersion；终态重放也未
  新增 observation、assessment version、lineage 或状态迁移。本轮 135 项相关测试通过，真实
  PostgreSQL 并发双提交、全事务回滚和既有租户/RLS 账本集成测试 2 项通过。
- [x] 已按
  [ADR-097](architecture-decisions/adr-097-atomic-governed-dataops-manual-admission.md)
  建立人工触发原子准入。tenant-scoped `client_request_id` 形成稳定 request identity、Run ID、
  idempotency key 和 advisory lock，完整不可变 payload 另行 fingerprint；同一请求重放恢复首次
  `admitted_at`，载荷漂移或跨 definition 改绑 fail closed。认证 API 从 session 派生 tenant/human
  requester，workload 和 policy evaluator 只取服务端 profile；invocation 保存 requester，Run 以
  workload 执行并通过 `delegated_by` 固化委托。invocation、policy Artifact、Run、input binding
  和 outbox 在一个 PostgreSQL 事务内写入，缺失 execution plan 时全部回滚。
- [x] 真实重庆 JQDLTB manual Run
  `66815080-292b-591c-b161-623d961eadf5` 创建唯一 DolphinScheduler instance `4`；human requester
  与 workload executor 分离，provider `commandType=START_PROCESS`、`scheduleTime=null`，
  `gda_client_request_id` 和其余 12 个 correlation 变量完整。同一请求原子重放全部
  `created=false`；provider `SUCCESS` 后平台仍根据 1,555 条全量扫描的权威质量结果 `failed`
  将 Run 终止为 `failed`，未创建 DataProductVersion；终态重放也无新增。相关 control-plane、
  adapter 和 worker 测试 159 项、真实 PostgreSQL 集成测试 2 项通过。sandbox 脚本 requester
  只是本地操作员声明，不作为生产 OIDC 证据。
- [x] 已按
  [ADR-098](architecture-decisions/adr-098-governed-dataops-cancel-and-terminal-callbacks.md)
  建立受治理取消和终态 callback 隔离。human requester、tenant 从认证 session 派生，workload 与
  policy evaluator 从服务端 profile 派生；稳定 request identity 与完整 payload fingerprint 分离。
  独立 `dolphinscheduler.cancel` PolicyDecision Artifact、Run `cancelling` CAS event 和 cancel
  outbox 在一个 PostgreSQL 事务内提交，通用 transition API 不再允许绕过。STOP 交付后原子创建
  reconcile；只有 provider `STOP` evidence 才能进入 `cancelled`。终态 callback 保留 immutable
  observation，但返回 `ignored_terminal=true` 且不生成 command。相关测试 195 项通过、2 项按环境
  跳过，真实 PostgreSQL 集成 2 项通过。当前 Compose app 已重建部署并验证健康；全局 OpenAPI
  恢复为 `200`，17 个 platform operation 均可发现且声明 OAuth2，未认证 cancel/incident 返回
  结构化 `401`。
- [x] 已按
  [ADR-099](architecture-decisions/adr-099-data-incident-and-cancellation-convergence.md)
  建立 DataIncident 和取消收敛闭环。provider 在 governed cancel 后进入 `FAILURE`、`SUCCESS` 或
  `PAUSE` 时，平台原子创建 high-severity incident 并将 Run fail closed 为 `failed`；持续
  `READY_STOP` 等状态耗尽 reconcile `max_attempts` 时创建 convergence-timeout incident，避免
  Run 永久 pending。incident cause/evidence 由 SHA-256 绑定，状态只允许 open/acknowledged/resolved
  单向 CAS 迁移；attention queue/get/remediation API 均为租户隔离，只有 human 可确认或解决。
  该阶段验收时 migration ledger 为 101/101；真实 PostgreSQL 已覆盖 RLS、append-only、幂等、
  跨租户负向和超时收敛。
- [x] 已按
  [ADR-100](architecture-decisions/adr-100-durable-incident-alertmanager-delivery.md)
  建立事故事务性通知 outbox 和 Alertmanager v2 adapter。每个 IncidentEvent 与通知任务同事务，
  destination 只保存逻辑引用，worker 以租约、`SKIP LOCKED`、有界重试和事件顺序约束执行；稳定
  alert labels 保证 at-least-once 重投覆盖同一告警，resolved 以 `endsAt` 关闭。Compose 提供默认
  不启动的 `alerts` profile。两个历史 `local-dev` high incident 已经真实本地 HTTP 投递并收敛为
  2 done、0 pending；真实 PostgreSQL 覆盖最小权限、RLS、open/acknowledged/resolved 顺序、失败
  重试和跨租户负向，control-plane 回归 200 项、真实 PostgreSQL 集成 2 项通过。生产 Alertmanager
  endpoint、IM/email receiver、on-call、HA、metrics 和 dead-letter 恢复尚未部署，不能勾选
  production alerting 退出门。
- [x] 认证 OpenLineage 事件已进入版本化 `LineageEvent` 控制账本；Metadata Fabric crosswalk
  只保存 `ResourceURN -> OpenMetadata entity UUID / Gravitino object` 的稳定外部引用，迁移 112
  通过同一血缘事务写入 `metadata_change_outbox`。OpenMetadata worker 只消费显式 UUID binding，
  采用 lease、写前查询、最小 `PUT /api/v1/lineage`、写后精确边确认和不确定提交对账；缺失映射
  保持可重试，不从名称或 FQN 猜测身份。详见
  [ADR-130](architecture-decisions/adr-130-authenticated-openlineage-control-ledger-ingestion.md)、
  [ADR-131](architecture-decisions/adr-131-metadata-fabric-crosswalk-and-transactional-outbox.md) 和
  [ADR-132](architecture-decisions/adr-132-openmetadata-lineage-reconciliation-worker.md)。
- [x] 上述 worker 已通过真实 OpenMetadata 1.13.1 隔离验收：未认证 lineage PUT 返回 `401`；
  模拟 provider 已提交但客户端超时时，实际调用为 `GET -> PUT -> GET` 并完成 read-after-write
  reconciliation；同一 envelope 重放只调用 `GET`，provider 精确边保持 `1`，outbox 为
  `done/attempt_count=1`。版本固定的 OpenMetadata/PostgreSQL/OpenSearch 验收拓扑只绑定宿主机
  loopback 端口，成功或失败后均删除临时容器、卷和 token。脚本为
  `scripts/metadata-fabric-openmetadata-acceptance.sh`，脱敏报告保存于
  `.tmp/metadata-fabric/openmetadata-lineage-acceptance-report.json`。该证据只将 OpenMetadata
  generic-lineage 投影切片标记为 operational，不代表 Metadata Fabric 或生产 OpenMetadata 完成。
- [x] `ResourceVersion` 数据架构版本权威已补齐最小闭环：迁移 113 增加不可变、tenant-scoped
  `SchemaVersion`、`DataContractVersion`、`PhysicalLocation` 和完整四元绑定，只保存
  OpenMetadata/Gravitino/provider 稳定引用、snapshot/revision、checksum 与 canonical SHA-256，
  不复制完整 schema/contract JSON。复合外键强制三类对象属于同一 `ResourceVersion`；缺少任一对象
  或最终 binding 时，gateway 明确返回 `architecture_ready=false`。一次性 PostgreSQL 16.14 已验证
  幂等登记、同 ID 载荷冲突、跨资源组合拒绝、跨租户拒绝、直接 UPDATE/DELETE 拒绝、4 张表强制
  RLS/不可变 trigger 和 gateway 仅 `SELECT/INSERT`；2 个完整资源版本均通过。详见
  [ADR-133](architecture-decisions/adr-133-resource-version-data-architecture-authority-binding.md) 和
  `.tmp/data-architecture-version-authority/acceptance-report.json`，报告 SHA-256
  `fd3121b6f4051aa737fbf6bec19bbaf90004df180481fb628db02c1bb9e81109`。该切片只建立“结构、合同、主物理位置”
  的版本绑定，不包含真实 provider harvester/reconcile、schema compatibility、replica/placement history、
  变更执行或 UX，因此不代表 Metadata Fabric、AR-1 数据架构或下一代 Data Platform 已完成。
- [x] 已补第一条真实数据架构采集与对账链：迁移 114 增加 append-only、tenant-scoped provider
  observation，只保存 provider/object、source revision、schema content/candidate/location 指纹、
  `observed_at`、`fresh_until` 和 tombstone，不复制系统目录或凭据。PostGIS harvester 在 read-only
  transaction 中通过参数化系统目录查询规范化 column/constraint/index/geometry type/SRID；查询错误
  不会伪造 tombstone，差异只返回候选和 `unobserved/unbound/in_sync/stale/schema_drift/location_drift/
  tombstoned` 状态，不自动覆盖权威绑定。真实 `postgis/postgis:16-3.4`（PostgreSQL 16.4、PostGIS
  3.4.3）依次验证 polygon/SRID/GiST 基线、过期、`ALTER TABLE` schema drift、同 schema 删除重建后的
  relation location drift 和最终 DROP tombstone；账本保留 3 条 present + 1 条 tombstone，而正式
  schema/contract/location/binding 始终各 1 条。详见
  [ADR-134](architecture-decisions/adr-134-postgis-architecture-observation-and-reconciliation.md) 和
  `.tmp/data-architecture-provider-reconciliation/acceptance-report.json`，报告 SHA-256
  `bc160bdc7d9e2807db8b851992f4af3edd0727f9b126bd85496051e21c425778`。该证据不外推到 Gravitino、
  Iceberg、STAC、对象存储或 DuckDB，也未完成 compatibility/impact/approval、调度告警和自动新版本流程。
- [x] 已将审批后的架构后继版本接入既有 `DataProductVersion` release/promotion/rollback 权威：
  `ArchitectureSuccessorDataProductReleasePlan` 同时绑定产品前后继、ADR-137 adoption plan/ApprovalCase、
  完整架构 binding、质量证据、全部分发 Artifact 和确定性 rollback pointer；第三个独立
  `data_product.publish_architecture_successor` ApprovalCase 才能授权发布。迁移 116 的 append-only、
  forced-RLS release binding 与 deferred constraint trigger 阻止旧 `publish()` 或直接 SQL 绕过；
  已提交版本继续复用 ADR-122 消费者影响门，promotion 会重验 release facts，rollback 只能回到计划中的
  immediate predecessor。一次性 PostgreSQL 16.4 / PostGIS 3.4.3 已验证绕过和 pending 审批均无版本残留、
  批准后原子 advanced、幂等重放、受限 rollback 和重新 promotion，最终精确保留 2 个产品版本、1 条
  release binding、3 个 Human-approved cases 和 `published/advanced/rolled_back/promoted` 四类事件。
  详见 [ADR-138](architecture-decisions/adr-138-approval-bound-architecture-successor-data-product-release.md)
  和 `.tmp/data-product-architecture-successor-release/acceptance-report.json`，报告 SHA-256
  `d6df71d5ec2089b25360ba09b3477b18c2174b50b45797a486d2a4f179426ddc`。该切片尚未验证生产对象存储
  字节、正式 ConsumerBinding/通知/迁移、rollback 影响确认、DataSLO/Incident、serving revision 或非
  PostGIS provider，不能据此宣称 AR-2/AR-3/AR-4 或下一代 Data Platform 完成。
- [ ] 真实 DolphinScheduler cancel terminal 尚未验证。instance `6` 首轮 STOP 因官方 3.4.2
  standalone 镜像缺少 `pstree` 无法杀死 shell 进程，观察窗内停在 `READY_STOP`，随后任务自然
  完成并被 provider 写成 `SUCCESS`。sandbox 镜像已补入 `psmisc`；新 Run
  `7ce30152-147c-5cab-b68d-8acb6ec3e48a` / instance `7` 的进程树已被 SIGINT 成功终止，但 worker
  报 exit `130` 后将 task 和 workflow 写成 `FAILURE`，仍未形成权威 `STOP`。两个平台 Run 最初
  进入 `reconciling`，ADR-099 上线后已基于原始 immutable observations 分别收敛为 `failed`，并创建
  incidents `09674ef6-fac8-5a51-9adc-50a478c6b27d`（provider `SUCCESS`）和
  `0ed1097c-56bc-5f9c-b968-9911d03c1517`（provider `FAILURE`）；均未误标 `cancelled`，也未创建
  DataProductVersion。原始证据分别见
  `.tmp/dolphinscheduler-sandbox/cancel-v1/governed-cancel-rehearsal-report-pstree-missing.json` 和
  `.tmp/dolphinscheduler-sandbox/cancel-v1/governed-cancel-rehearsal-report-pstree-fixed-provider-failure.json`。
  上游 [issue #18311](https://github.com/apache/dolphinscheduler/issues/18311) 及 PR
  [#18312](https://github.com/apache/dolphinscheduler/pull/18312)、
  [#18367](https://github.com/apache/dolphinscheduler/pull/18367) 尚未合并；不能把 `FAILURE` 猜测为
  cancel 成功，也不能据此勾选 provider cancel 退出门。
- [ ] 真实源版本不等于标准化产品：全量审计真实发现 `BSM` 1,555 行重复、`TBMJ` 和
  `TBDLMJ` 各 6 条非正值、7 条记录的声明面积偏差超过 1%，并缺少待审批派生的 `MSSM`
  与 `SJNF`。标准落标样本预检仍是抽样证据；全量报告已由真实 DolphinScheduler
  `PlatformRun` 执行并写入权威 `QualityResult`，但尚无通用 ApprovalCase，也未创建
  DataProductVersion。业务 steward、许可状态和上述质量失败继续阻塞晋级。
- [ ] 原子 schedule-window admission 与显式漏窗恢复已通过，但生产触发源、持久 window
  cursor、schedule lag/失败告警、runtime restart/HA 下的持续物化和跨系统双租户负向矩阵仍
  未完成。DolphinScheduler 原生 schedule 创建合同仍不携带 GDA `PlatformRun` 和策略证据，
  因此当前 workflow 继续不得设为 ONLINE cron；controller 只能接收外部已经物化的精确窗口。
- [ ] 该切片不代表 AR-1 退出：DolphinScheduler 尚未达到 production foundation，未完成
  OIDC/workload identity、HA、metadata DB backup/restore、metrics、manual DataOps UI、生产
  Alertmanager/IM/on-call、provider terminal cancel、semantic retry 和在途任务故障注入验收；
  OpenMetadata generic-lineage 投影虽已通过真实 provider 验收，但 production foundation、治理采集、
  search/read bridge、双租户与恢复仍未完成，Gravitino fabric、Spark/Flink provider correlation 与
  跨系统双租户隔离也仍未完成。已完成的单节点 runtime
  restart/reconcile 不能外推为 metadata restore、master/worker HA 或批准的 RPO/RTO。
- [ ] 历史 93 migration 的恢复/PITR 基线必须按当前 149 migration 状态重演，不能把旧恢复
  证据外推到本检查点。

退出门：

- PostGIS/DuckDB、Iceberg/云湖表、STAC 和对象存储中的同一试点资源可解析到唯一 ResourceURN/OpenMetadata entity/Gravitino object/Version/Location，重复采集幂等，schema drift 可见。
- Gravitino 对 MinIO/Iceberg、Spark/Sedona、Flink 完成真实 create/read/write/schema evolution/snapshot/cancel/reconcile/lineage conformance；失败时自动保留认证 Iceberg REST catalog，不允许 Gravitino 进入该 profile 的唯一生产路径。
- DolphinScheduler schedule、manual trigger、complement/backfill、retry、cancel、worker group/resource queue 和 DataOps UI 运行真实 vertical slice；APScheduler/`TaskQueue`/Dagster 不再创建生产 DataOps run。
- `PlatformRun`、DolphinScheduler process/task、Spark/Flink/cloud job 和 Artifact 可双向关联；master/worker/API 重启后可 reconcile，迟到回调不能推进产品状态。
- retry、cancel、checkpoint/replay 不产生重复 Artifact 或 active product version。
- 双租户无法发现、遍历、运行、取消、重试或读取对方 Resource/Run/Artifact。
- Web、DolphinScheduler、OpenMetadata、Gravitino、worker 和 bridge 重启后不丢版本、产品、血缘、PlatformRun correlation 或审批状态。
- DataOps 状态可从 DolphinScheduler/OpenMetadata/Gravitino/GDA evidence 恢复；任何 release/deployment 都能从事件、Artifact、评测、策略、incident 和 rollback pointer 重放。Temporal durable recovery 在 AR-5/AR-7 单独验收。

### AR-2 — Source, Ingestion and Geospatial Lakehouse Vertical Slice（P0）

**依赖**：AR-1 两个控制面的最小合同通过故障注入和隔离验收。

**状态**：`in_progress`。2026-08-01 已完成第一个真实、可消费的轻量 profile
vertical slice，但尚未达到 AR-2 退出门：

- [x] 真实重庆 OSM 道路 Shapefile 全量读取 50,366 条要素；源 bundle、成员 checksum、
  CRS、范围和 schema 形成不可变 `ResourceVersion`。
- [x] 10 个源字段经标准别名、类型和歧义阈值自动落标，结果为 10 个 recommended、
  0 review required、0 unmatched、0 conflict；批准映射合同和 fingerprint 可追溯。
- [x] 全量执行 9 项关键质量门：行数守恒、EPSG:4326、geometry 完整有效、道路 ID
  唯一、必填语义、值域/速度、重庆范围和 ODbL 许可归属全部通过。
- [x] 首个受治理 `DataProductVersion` `chongqing-osm-roads/v1.0.0` 已写入不可变
  注册表；active pointer、append-only 发布/回滚事件、GeoJSON Artifact、PostGIS
  projection、source -> standardized lineage 已在真实 PostgreSQL/PostGIS 验证。
- [x] 重复执行返回同一产品版本且无新增 ResourceVersion、Artifact、LineageEvent 或
  pointer event；目录、详情、要素、下载、血缘 API 和地图页均通过真实 HTTP/浏览器验收。
- [x] `v1.1.0` 已将同一真实输入扩展为 Lightweight Integrated profile 的
  Raw -> ODS -> Silver -> Gold -> ADS 分层链：8 个原始 bundle 成员及 Raw manifest、
  ODS/Silver GeoParquet、Gold 道路分类指标、ADS GeoJSON 共 13 个数据对象，加上
  catalog/collection/item 三个 STAC 文档，全部写入 MinIO 后回读校验 SHA-256；各层
  ResourceVersion、Artifact 和 Raw -> ODS -> Silver -> Gold -> ADS 递归 lineage 已写入
  PostgreSQL 控制账本。STAC Item 可通过产品 API 发现，协议 validator/conformance 仍留在
  AR-2/AR-4 对应退出门。
- [x] 产品已有真实 `v1.0.0 -> v1.1.0` predecessor 链；active pointer 已实际回滚到
  `v1.0.0` 并使 STAC 消费面随版本降级，再通过新的 append-only `promoted` 事件恢复
  `v1.1.0`。重复分层发布未新增 ResourceVersion、Artifact、lineage 或 pointer event。
- [x] `v1.2.0` 已把同一 50,366 条真实 OSM 输入接入统一控制链：不可变
  `PlatformDefinitionVersion c7893029-09cb-522b-88a6-9ea0646fa099` ->
  `PlatformRun 859195f5-5e81-59a6-855a-de52b3b11d7d` -> DolphinScheduler workflow
  instance `10` -> 3 条 Attempt observation -> 9 个 Run-bound Artifact -> 5 条
  Run/Definition-bound lineage -> 独立 `passed` QualityResult -> evidence-gated
  `succeeded`。active `DataProductVersion` 为
  `5bdffe0f-edd7-5de2-826f-a36486be44ba`；产品、STAC 和 lineage HTTP API 均返回
  `v1.2.0` 的 Run/Definition correlation。
- [x] 真实调度过程验证了失败收敛和自动 retry：首次 Run 因 Raw manifest 错误地混入
  Run 上下文而触发不可变对象冲突，已终结为 `failed` 且未创建产品版本；后续 Run 又暴露
  GeoParquet 逻辑/物理 hash 混用和已存在逻辑 Resource 重绑定问题。修复为源 manifest
  与 Run 证据分离、GeoParquet 逻辑 snapshot + 物理 SHA-256 双重寻址、已存在逻辑版本
  复用后，DolphinScheduler retry 从已物化分层继续并成功。相同 client request 完整重放时
  `platform_run_created=false`、`dispatch_command_created=false`、outbox claimed `0`、
  success observation 未新增、终态未迁移、产品版本数仍为 `3`。验收证据：
  `.tmp/dolphinscheduler-sandbox/osm-roads-v1.2.0/acceptance-report.json`。
- [x] `v1.2.0` 的下载消费面已从容器本地文件收敛到受治理 S3 Artifact：端点优先选择
  `S3GeoJSON`，并在返回前交叉校验 distribution、Artifact 账本、MinIO object metadata、
  `ContentLength` 和实际 payload SHA-256；旧版 `file://` 分发保持兼容。真实 HTTP 下载返回
  `200`、`36,427,513` bytes、50,366 条要素，SHA-256
  `c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164` 与 Artifact/STAC
  一致。验收证据：`.tmp/dolphinscheduler-sandbox/osm-roads-v1.2.0/download-acceptance-report.json`。
- [x] 同一 `v1.2.0` 已完成首个真实 Default Lakehouse batch provider 切片：Spark `3.5.0`
  从 MinIO S3A 读取 ADS GeoJSON，Sedona `1.9.0` 将 50,366 条 MultiLineString 转为
  `geometry_wkb + srid + bbox` 跨引擎合同，并写入 Iceberg v2 表
  `lakehouse.gis_dwd.chongqing_osm_roads`。50,366 个道路 ID 唯一，geometry、EPSG:4326、
  bbox 和内容 fingerprint 均与输入一致；snapshot `6767532492674345422` 可按 snapshot-id
  time travel 回读。相同输入重跑复用该 snapshot，history 保持 `1`，未制造重复 commit。
  该报告保留为 batch provider 层验收证据：
  `.tmp/dolphinscheduler-sandbox/osm-roads-v1.2.0/default-lakehouse-acceptance-report.json`。
- [x] 上述 Default Lakehouse executor 已进一步接入统一控制链：不可变
  `PlatformDefinitionVersion 3e436515-2df8-54c5-91f9-6dc842ae03a3` 以 v1.2.0 ADS
  `ResourceVersion 04eaa6f8-475c-5dcd-8992-e54307fc0395` 为只读输入，通过
  `PlatformRun 786cf4c2-0014-5e1c-b267-507ea43a0170` 和 DolphinScheduler workflow
  instance `11` 调用认证 executor；Iceberg snapshot 被登记为
  `ResourceVersion 9d0602e9-a3d1-523c-9935-05e80c9bdc70`，并生成 Run-bound output/evidence
  Artifact、Run+Definition-bound materialize lineage 和独立 evaluator 的 passed
  QualityResult，最终由 evidence gate 收敛为 `succeeded/state_version=4`。相同 client
  request 完整重放时 PlatformRun/dispatch command 均未创建、outbox claimed `0`、success
  observation 未新增、终态未迁移，executor 快速返回 `replayed=true` 且不再启动 Spark；
  Iceberg history 仍为 `1`，active 产品仍为 `v1.2.0` 且版本数保持 `3`。验收证据：
  `.tmp/dolphinscheduler-sandbox/osm-roads-default-lakehouse-v1/acceptance-report.json`。
- [x] Default Lakehouse 的 commit 后控制面已从 OSM executor 抽为跨产品通用
  materialization contract/recorder；OSM 复用该记录器后，既有 Artifact、QualityResult、
  lineage 和 ResourceVersion 身份保持不变。第二个真实输入选用重庆中心城区建筑：原始
  bundle SHA-256 `e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d`，
  全量 107,452 条；确定性源快照保留原始 `source_id=0`，以 Fiona `feature.id` 派生
  107,452 个唯一 `source_fid`，并将 Polygon 无损提升为 MultiPolygon 以形成稳定的
  Spark 输入合同。46,229,820-byte 快照以物理 SHA-256
  `6fd8c873ffce0c0a91089c554b3b0d432527102272260a7363744cb75290bf29`
  不可变写入 MinIO 并完成回读校验。
- [x] 该 restricted 建筑快照已通过 Spark `3.5.0`/Sedona `1.9.0` 写入 Iceberg v2
  `lakehouse.gis_ods.chongqing_central_buildings_2021`，snapshot
  `2900773797038828981` 可 time travel 回读 107,452 行。质量门精确保留并记录 417 条
  空 geometry、416 条由空值形成的重复 geometry、0 条非空重复、0 条非空无效 geometry、
  原始 ID 仅 1 个 distinct value 和楼层 1–66；`passed` 仅表示 ODS 全量守恒、缺陷记账、
  可回放和 commit 幂等，不表示数据已清洗或完成落标。
- [x] 建筑 ODS 已接入第二条完整控制链：Definition
  `05cabc57-63a3-5076-a19b-963c5452f7f2` -> PlatformRun
  `b8cdded1-5e9c-5f6d-acf3-bcbdc8290fc5` -> DolphinScheduler instance `12` ->
  Iceberg ResourceVersion `e36703d6-ba3b-53be-96c1-fb8aeb8465b6` -> output/evidence
  Artifact、materialize lineage 和独立 ODS ingestion-integrity QualityResult ->
  `succeeded/state_version=4`。`classification=restricted`、`logical_stage=ods`、
  `promotion_eligible=false` 在 Definition、Resource、表属性、Artifact 和 QualityResult
  一致；DWD/ADS 与建筑 DataProductVersion 均未创建，OSM 产品仍为 `v1.2.0/3 versions`。
  完整重放未新增 source/definition/binding/Run/command/observation，executor 未启动 Spark，
  Iceberg history 保持 `1`。验收证据：
  `.tmp/dolphinscheduler-sandbox/central-buildings-ods-v1/acceptance-report.json`。
- [x] Source 接入已从产品脚本中的隐含约定收敛为不可变、fail-closed 的声明式 adapter
  registry：adapter ID/version/fingerprint、source kind、extension/driver、bundle member policy、
  profiler/transform adapter、目标层、classification、required evidence/checks 和 promotion
  policy 均进入 Definition 或 source manifest。建筑 Shapefile 迁移后既有 bundle SHA-256
  `e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d`
  保持不变；未知 adapter/extension/driver、缺少必需成员、未声明同 stem sidecar 和 restricted
  直接晋升均会被拒绝。
- [x] 第三类真实数据选择重庆 2020 DEM，证明接入面不局限于 Shapefile/矢量。原始
  GeoTIFF、world file、GDAL auxiliary、external overview、value table 和 metadata 共 7 个
  成员按显式 sidecar policy 封存，bundle SHA-256
  `7e2cdcb92263283167e2305542dd1208e7fc907c56de365ea3b83cddcc60e333`，主 TIFF
  SHA-256 `d3d167bc94f5d6ed52053942f0e98737557e94c8761497d74d58eb88bf9bd09f`。
  七个对象均按 bundle + physical SHA-256 不可变写入 MinIO 并回读校验；完整重放全部复用。
  全分辨率扫描精确记录 1766 x 1454、EPSG:4490、int16、NoData 32767、998,698 个有效
  像元、1,569,066 个 NoData、高程 24–2802、均值 731.07092834871、128 x 128 block、
  LZW 和 2/4/8 overviews。
- [x] DEM 没有被强制行表化或覆盖转换，而是以 byte-preserving `native_raster_bundle`
  进入对象型 ODS 控制链：raw ResourceVersion
  `998628d5-ad68-51ea-b36b-6c54cf3663ed` -> Definition
  `cf9e56cf-8d94-5ded-b8d9-62d3295a4e81` -> PlatformRun
  `dfc75abf-4779-50d3-8cfb-4b660f379950` -> DolphinScheduler instance `15` -> ODS
  ResourceVersion `25c9396e-2880-5a04-beb6-c407d8f2cc43` -> output/evidence Artifact、copy
  lineage 和独立 native-raster ingestion-integrity QualityResult -> `succeeded/state_version=3`。
  COG conformance、标准映射和产品晋升分别保持 `not_evaluated/not_evaluated/blocked`，没有创建
  DEM DataProductVersion。首次真实执行还暴露并修复了 raw/ODS authority locator 冲突及跨 Run
  内容版本时间戳冲突；两个失败 Run 均按 provider STOP 终结为 `failed/state_version=4`，未伪造
  success observation。相同成功请求完整重放未新增 Run、command、observation 或物理对象，
  executor 未再次运行 provider。验收证据：
  `.tmp/dolphinscheduler-sandbox/chongqing-dem-ods-v1/acceptance-report.json`。
- [x] 数据库、对象存储和 HTTP/STAC 已收敛到 secret-free、owner-bound、不可变
  `SourceDefinition + CredentialReference` 合同；运行时 resolver 才取得凭据。connector certification
  逐项记录 `connect/discover/preview/profile` 的通过、失败、未支持或未评估状态，只有真实通过项才能
  进入 `SourceCapability` matrix。现有 connector 被复用，没有新建第二套查询栈；database preview
  强制只读事务，MinIO 使用签名 S3 list/get，STAC 同时读取根 conformance 和 collections。
- [x] 首轮只读真实认证覆盖 PostgreSQL 16.14/PostGIS 3.4.3、MinIO
  `RELEASE.2025-04-22T22-12-26Z` 的 S3-compatible API，以及由已发布重庆 OSM 道路
  `v1.2.0` STAC Item 驱动的本地 STAC API 1.0.0 transport。3 个 source 的 12 项能力全部
  `passed`；重复认证的 discovery/profile fingerprint 稳定。错误 PostgreSQL/MinIO 凭据和 STAC
  网络中断均 fail closed，认证报告未包含 secret。验收证据：
  `.tmp/source-connector-certification/acceptance-report.json`。本地 STAC transport 不是生产
  stac-fastapi/pgSTAC 认证，MinIO 精确 release 来自 compose runtime inventory，S3 响应仅声明
  `MinIO/S3-compatible`。
- [x] PostgreSQL provider 已完成隔离 sandbox 中的真实 credential rotation 和字段级 schema
  mutation/drift 验收：revision v1 的 `connect/discover/preview/profile` 通过后，在服务端执行
  `ALTER ROLE ... PASSWORD`，stale v1 随即失败，revision v2 恢复通过且 discovery fingerprint
  不变。新增 nullable `observed_at TIMESTAMPTZ` 被记录为非 breaking `added`，`id INTEGER ->
  BIGINT` 被记录为 breaking `type_changed`；只授予 `USAGE + SELECT` 的 provider role 尝试
  `INSERT` 得到 SQLSTATE `42501`，未产生写入。随机 schema/role 在 `finally` 中精确删除并验证
  不再存在，报告不含运行时密码。验收证据：
  `.tmp/source-connector-certification/postgresql-rotation-drift-report.json`。该报告负责生成不可变
  `SchemaDriftEvent`，控制账本持久化和 lifecycle 由迁移 102 及下述独立验收负责。
- [x] MinIO/object-storage provider 已完成真实 credential rotation 和最小权限验收：已发布重庆
  OSM 道路 `v1.2.0` STAC Item 被原样复制到随机临时 bucket，随机用户的自定义 policy 只允许
  list/get 该对象。revision v1 的 `connect/discover/preview/profile` 全部通过；同一 access key 在
  MinIO 服务端更新 secret 后，stale v1 失败，revision v2 恢复通过，discovery/profile fingerprint
  均不变。对随机、预先确认不存在的 key 执行 `PutObject` 得到 `AccessDenied`，管理员复查对象仍
  不存在；临时 user、policy、policy file、object 和 bucket 均被精确删除并验证。报告不包含两版
  runtime secret。验收证据：
  `.tmp/source-connector-certification/minio-rotation-report.json`。该 credential rotation 证据本身
  不宣称 schema mutation/drift、重复摄取或增量摄取已经完成。
- [x] STAC connector 已完成 authenticated HTTP transport 的 bearer credential rotation：临时
  transport 只服务已发布重庆 OSM 道路 `v1.2.0` Item，并要求根文档、`/collections` 和 `/search`
  全部携带运行时 Authorization header。revision v1 的四项能力通过，错误 token 被拒绝；服务端切换
  到 revision v2 后 stale v1 立即失败，v2 与重复认证均通过，discovery/profile/report fingerprint
  稳定，网络中断继续 fail closed。provider 记录 15 个授权请求、2 个未授权请求和 accepted revision，
  不保存 header/token；临时 server 与 thread 均已关闭。验收证据：
  `.tmp/source-connector-certification/stac-rotation-report.json`。该 transport 是真实 HTTP 认证切换，
  但不是 production stac-fastapi/pgSTAC provider 认证。
- [x] `SchemaDriftEvent` 已进入现有 PostgreSQL Control Ledger，而不是停留在 JSON 报告：迁移
  `102_source_schema_drift_ledger` 新增 tenant-scoped `source_schema_drift` 当前状态投影和 append-only
  lifecycle event，`SourceSchemaDriftLedger` 通过 transaction-local gateway role/RLS 提供幂等记录、
  查询和 CAS transition。非 breaking 事件走 `observed -> reconciled`；breaking 事件初始为
  `approval_required`，不能直接 reconcile，只有携带同租户外部 `ApprovalCase` ResourceURN 才能进入
  `approved/rejected`，批准后才能 reconcile。该约束只消费审批引用，不创建第二套 ApprovalCase
  authority。隔离真实 PostgreSQL 验收覆盖重复记录、stale CAS、直接 UPDATE 拒绝、最小权限和跨租户
  负向，随机 database 已删除。主 Compose 当前已迁移为 106/106 applied records、最新 migration 104，
  catalog/database fingerprint 一致。验收证据：
  `.tmp/source-connector-certification/drift-ledger-report.json`。
- [x] JSON/GeoJSON object-storage 与 STAC Item schema 已接入同一 drift 闭环。两个 connector
  复用确定性的嵌套字段规范化器：按字段路径记录 JSON 类型和 nullable，值或 ETag 单独变化不冒充
  schema drift；STAC discovery 按 `collection_id` 通过带认证的 `/search` 取样 Item schema，MinIO
  discovery 使用同一只读运行时凭据对指定对象取样。`observe_certification_schema_drift` 只接受同一
  source、connector、provider 和不可变 SourceDefinition 的两次 passed certification，随后才生成并
  幂等写入 `SchemaDriftEvent` 账本。
- [x] 同一真实重庆 OSM 道路 `v1.2.0` STAC Item 已在随机 MinIO bucket 与临时 authenticated STAC
  transport 中分别执行非持久 mutation：新增
  `properties.gda:schema_drift_probe_v1:string` 被两类 provider 一致识别为 non-breaking `added` 并
  `observed -> reconciled`；再变为 integer 被一致识别为 breaking `type_changed`，只进入
  `approval_required`，未伪造审批。两类 provider 的三轮 `connect/discover/preview/profile` 全部通过，
  重复观察不新增事件，报告不含 runtime secret。12 项行为检查和 8 项清理检查全部通过；随机 MinIO
  user/policy/bucket、STAC server/thread 和 PostgreSQL database 均已删除，主库 drift/lifecycle 仍为
  0 行。验收证据：`.tmp/source-connector-certification/object-stac-drift-report.json`，SHA-256
  `23cf344e592b6519f7d147ed4388dd162745e521be375de6f0301d6d6743efe6`。
- [x] 通用 `ApprovalCase` 已成为独立于 Run 专用 `ApprovalRecord` 的统一审批权威：每个 case 以
  `gda://{tenant}/approval_case/{id}` 登记 Resource，并不可变绑定 target ResourceURN、target
  fingerprint 和 action；current projection 与 append-only event 分离，终态决定通过 CAS 且只允许一次。
  approved/rejected 必须由未发起该 case 的 human actor 在有效期内作出。迁移
  `103_unified_approval_case_authority` 已把 breaking schema drift 的 approval reference 改为真实同租户、
  exact-target、exact-verdict authority 校验；历史迁移 102 的既有事实不被伪造或重写。
- [x] ApprovalCase 已通过 4 个认证 `/api/platform/v1` 端点暴露创建、查询、event audit 和人工决定；
  tenant/requester/decider 均由认证 principal 注入，客户端不能覆盖，workload 不能提交决定。主 Compose
  已由专用 migration authority 前向迁移；主 Compose 当前为 106/106，catalog/database fingerprint 为
  `ec36731518456a7e3d7c27cf1968cd59b9ac92c25abea5601ed5b23bb4eb8362`。隔离真实 PostgreSQL 验收覆盖
  未登记/pending/过期/wrong-target/wrong-verdict/self-approval、幂等、stale CAS、RLS、最小权限和租户隔离；
  相关 Gateway/authority/contract/drift 聚焦测试 58 项通过。详见
  [ADR-103](architecture-decisions/adr-103-unified-approval-case-authority.md) 和
  `.tmp/source-connector-certification/drift-ledger-report.json`。主库 case/drift 表保持 0 行。
- [x] 增量接入控制面已建立唯一 `SourceSyncDefinitionVersion -> SourceSyncCommit ->
  SourceSyncCheckpoint` 权威。定义冻结 full/incremental、overwrite/append/merge、cursor、主键和删除
  语义，并与 source/target ResourceURN 及执行 `PlatformDefinitionVersion` 绑定；Resource、
  ResourceVersion、typed definition 和 version-0 checkpoint 原子创建。commit 通过 PostgreSQL 函数
  锁定 checkpoint，以 state-version + cursor 做 CAS，在同一事务内追加 provider commit evidence 并精确
  推进一个版本；同 ID 和跨合法 Run 的相同 source slice 可恢复，target evidence 不同、stale cursor、
  wrong definition/actor/status/run/tenant 均 fail closed。
- [x] 迁移 `104_source_sync_checkpoint_authority` 已先通过随机临时 PostgreSQL 的 16 个行为门和 10 个
  数据库控制检查，再由专用 authority 进入主严格账本。当前 106/106，catalog/database fingerprint 为
  `ec36731518456a7e3d7c27cf1968cd59b9ac92c25abea5601ed5b23bb4eb8362`；三张主库 sync 表保持 0 行，
  RLS/FORCE RLS、checkpoint-to-commit 外键、append-only trigger、gateway 最小权限和 membership 均通过。
  详见 [ADR-104](architecture-decisions/adr-104-source-sync-checkpoint-authority.md) 和
  `.tmp/source-sync-certification/authority-report.json`。
- [x] 入湖治理现已进入同一 `SourceSyncDefinitionVersion` 权威，而不是新增平行 registry：
  `gda.source_sync_governance.v1` 冻结 landing/ODS/Silver/Gold、tabular/vector/raster/document/image/
  video/point-cloud/timeseries、batch/micro-batch/CDC/event-stream、adapter 版本与 fingerprint，以及标准
  mapping、标准版本、数据模型、质量规则、分类、保留、schema evolution、quarantine 和 promotion
  绑定。Landing/ODS 禁止晋级；Silver/Gold 必须绑定标准、模型和同租户隔离区，Gold 必须人工审批；
  event stream 必须有 event-time/watermark，CDC/stream 必须使用 token/offset cursor。新定义在应用层和
  PostgreSQL trigger 均不能省略合同；历史定义保留旧 fingerprint 和可读性，不伪造治理事实。
- [x] 迁移 `141_source_sync_governance_contract` 已在随机临时 PostgreSQL 通过 17 个 Authority 行为门和
  15 个数据库控制检查，包括 gateway 直接缺合同写入、重复质量规则、RLS、append-only 和最小权限负向；
  随机数据库已确认删除。平台合同、SourceSync、Spark incremental、Flink stream、PostgreSQL CDC、
  Flink/Iceberg reconciliation 和 migration 聚焦回归 69/69，通过 Python 编译与 diff 检查。现有真实
  vector 认证定义已分别标注 micro-batch、event-stream 和 CDC，全部作为 ODS 明确阻断 promotion；本次
  不宣称所有枚举数据形态已有 adapter，也不宣称质量结果和 ApprovalCase 已与 provider commit 原子入账。
  详见 [ADR-160](architecture-decisions/adr-160-source-sync-governance-contract.md) 和
  `.tmp/source-sync-certification/authority-report.json`，报告 SHA-256
  `2339671f2c4eb82efac63dfdc26d745d687701ca1a8ab0d8a157fa3b1b8b0905`。
- [x] Silver/Gold 的运行时晋级现已由同一 SourceSync PostgreSQL 权威强制执行，而不再只是定义期声明：
  新 `SourceSyncCommitGovernanceEvidence` 以不可变 fingerprint 绑定 target ResourceVersion、output
  Artifact、完整且独立评估的 passed QualityResult 集合、LineageEvent、自动 OpenMetadata metadata
  outbox，以及 Gold/approval-gated 必需的已批准 ApprovalCase。迁移 104 的 CAS 原语已私有化；迁移
  `142_source_sync_commit_governance_evidence` 的唯一公开 wrapper 在同一事务中验证证据、追加 commit、
  推进 checkpoint 并写入治理绑定，任一步失败均回滚。Landing/ODS 保持无晋级证据的兼容路径。
- [x] 随机临时 PostgreSQL 认证已覆盖 Silver 缺证据/缺质量规则/failed quality/同 actor 自评/错误
  target、artifact、lineage、outbox，以及 Gold 缺审批/pending/错误 fingerprint/错误 action；所有失败
  均保持 checkpoint/commit/governance/quarantine=`0/0/0/0`，合法 Silver/Gold 均原子形成 `1/1/1/1`。
  同 ID 重放要求治理和隔离证据完全一致，跨 Run 同 source slice 只复用原 commit 与原证据。累计 40/40
  行为门、26/26 数据库控制通过，随机数据库已删除。详见
  [ADR-161](architecture-decisions/adr-161-source-sync-commit-governance-evidence.md) 和
  `.tmp/source-sync-certification/authority-report.json`，报告 SHA-256
  `48889777cb4ca2201cba8ab12d9e3ce3a6bd8323c650a391f3ef2ba01242aeb1`。该隔离数据库证据不是持久
  开发/生产部署。
- [x] provider rejected-record quarantine 已从“存在一个隔离 Resource”收敛为不可变
  `SourceSyncQuarantineEvidence`。迁移 `143_source_sync_quarantine_evidence` 新增 forced-RLS、append-only
  隔离证据账本和唯一受控 binder；延迟约束触发器要求每个新 Silver/Gold commit 在外层事务结束前绑定
  source slice、quarantine ResourceVersion、`quarantine` Artifact、拒绝总数、原因分布和 canonical
  SHA-256。缺证据、伪造 ResourceVersion、错误 Artifact 角色、错误 Run、错误数量和同 ID 证据不一致
  均 fail closed，并与 checkpoint/commit/governance 一起回滚；Gold 同时证明 0 rejected 的显式空回执。
  详见 [ADR-163](architecture-decisions/adr-163-source-sync-provider-quarantine-evidence.md)。
- [x] quarantine provider assembly 已从 Flink 认证脚本抽取为通用
  `SourceSyncQuarantineRecorder`。provider 仍负责物理提交并给出 URI、media type、内容 SHA-256、大小、
  拒绝总数、原因分布和 provider facets；recorder 只登记 Resource、commit-bound ResourceVersion、
  `quarantine` Artifact 并生成 canonical evidence，不接管分类、物理写入、调度或 checkpoint。稳定 ID
  允许登记中断后幂等重试，最终仍由 SourceSync authority 原子绑定四账本。Spark 执行保留 `s3a://`，
  Artifact 治理地址在 adapter 边界规范为 `s3://`。详见
  [ADR-164](architecture-decisions/adr-164-provider-neutral-source-sync-quarantine-recorder.md)。该 recorder
  现已由 Spark/Iceberg micro-batch 零拒绝、Flink event-stream duplicate/late 拒绝和 PostgreSQL CDC
  invalid-record 拒绝三类 provider 共同认证。
- [x] 已发布重庆 OSM 道路 `v1.2.0` 的 50,366 条真实数据完成首条受权威 checkpoint 管理的
  Spark/Iceberg Silver micro-batch：full baseline 形成 snapshot `4946718755623873398`；第二个 Run 用
  单次 `MERGE INTO` 精确执行 1 insert、1 update、1 delete，形成 snapshot
  `5804234102856417302`，行数和 road ID 唯一性守恒。两个 phase 分别登记 target ResourceVersion、output
  Artifact、独立 passed QualityResult、LineageEvent、OpenMetadata outbox 和显式零拒绝 quarantine receipt，
  并与各自 SourceSync commit 原子绑定；两个 snapshot 均完成 time travel 回读，checkpoint 从 0 精确
  推进到 2。
  第三个合法 Run 在写前以 source-slice SHA-256 命中既有 commit，未再次启动 provider 写入，Iceberg
  history 和 checkpoint 分别保持 2；跨 Run commit recovery 返回原 commit 及治理/隔离双证据。随机
  PostgreSQL database、Iceberg table、MinIO prefix 和工作目录已删除，主库三张 sync 表前后保持 0 行。
  12 项端到端检查全部通过；证据
  `.tmp/source-sync-certification/chongqing-osm-report.json`，SHA-256
  `211ae24a532dd5060049ce2c139bfc50f6a43c76d42d7a5e54d4aeb908d5f2f5`。
- [x] 同一 `v1.2.0` Silver GeoParquet 已完成首条真实、受治理 Silver 的 Flink 1.19.3 事件流验收。
  50,366 条道路中
  确定性选择四条形成 10-event insert/update/delete slice；Flink 在 completed checkpoint `6`、offset
  `5` 后主动失败，attempt `1` 从 offset `5` 恢复。最终仅提交 8 条唯一 accepted event，重复 delete
  `cq-osm-e05` 和超 watermark 的迟到 update `cq-osm-e07` 各进入一条物理 quarantine；容差内乱序 update
  被接受，两个源端 delete 生效，最终状态为 2 条道路。output、quality、quarantine 三份物理 manifest
  分别登记 target/evidence/quarantine Artifact，并与 ResourceVersion、passed QualityResult、LineageEvent、
  OpenMetadata outbox、治理证据和隔离证据在 SourceSync 同一事务中绑定。checkpoint 从 0 精确推进到 1；
  同 ID 重放要求双证据一致，第二个合法 Run 在写前命中原 source slice 并复用原双证据，provider write
  保持 1 次。随机数据库和工作目录均删除，持久 sync 表保持不变。
  该证据使用本地短生命周期 Docker + Flink `local` target，不是 Compose 常驻容器或 K8s runtime；也不
  宣称 PostgreSQL CDC、Flink/Iceberg、跨系统 exactly-once 或生产 SLO 已完成。详见
  [ADR-105](architecture-decisions/adr-105-flink-event-stream-source-sync-certification.md)、
  [ADR-163](architecture-decisions/adr-163-source-sync-provider-quarantine-evidence.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-report.json`，报告 SHA-256
  `413561aff0b8608b44645b05679180816a5ea57cedbd919bf463cf63ffea70ed`；12/12 端到端门与 11/11 Flink
  行为门通过。
- [x] 同一真实 OSM source slice 已完成 PostgreSQL 16.14 WAL -> 官方 PostgreSQL CDC connector 3.3.0 ->
  Flink 1.19.3 的受治理 Silver log-based CDC 验收。三条初始快照、后续 WAL 和 active schema probe
  形成 20 条唯一 Table changelog（含六组 update-before/update-after）；checkpointed router 把 18 条合法
  变更提交到 Silver，把真实 OSM road `102262026` 的非法 geometry-hash insert/delete 各一次提交到
  quarantine，原因分布精确
  为 `{"invalid_geometry_sha256": 2}`。同一 publication、slot、Flink job 和 SourceSync Run 先后经历两个
  真实网络分区：`base_mutations` 持续 3.246 秒，分区期间 Silver/quarantine 保持 `3/0`、confirmed flush
  LSN 保持 `0/1952108`，重连后精确追到目标 `0/1952778`，WAL lag 为
  `248 -> 1,648 -> 56` bytes；`additive_schema_evolution` 持续 3.477 秒，分区期间保持
  `10/2`、confirmed flush LSN 保持 `0/1952778`，nullable DDL 与投影 DML 已积压在 WAL，重连后精确
  追到目标 `0/19548E0`，WAL lag 为 `56 -> 8,552 -> 0` bytes。随后 revision `3 -> 4` 更新在首次
  快速断网中产生目标 LSN `0/1954A48`，三个 0.5 秒 disconnect/reconnect cycle 共持续 4.309 秒；首个
  cycle 保持 `12/2`，第二个 cycle 在 slot 仍停滞时通过 checkpoint 显示 `14/2`，最终精确达到目标。
  revision `4 -> 5` 更新在 20.310 秒物理断网中产生目标 `0/1998AB8`，超过 Flink 15 秒 checkpoint
  timeout；期间保持 `14/2`，重连后 sink 与 slot 在 2.290 秒内共同恢复到 `16/2` 并精确达到目标，满足
  60 秒预算。revision `5 -> 6` 更新在 20 个配置间隔 0.1 秒的物理 cycle 中产生目标 `0/1998C58`，
  train 共持续 16.007 秒；每个 cycle 的 post-detachment LSN 与断网期末 LSN 相等，Job 全程
  `RUNNING`。首个 cycle 保持 `16/2`，到第三个 cycle 时 slot 仍停滞且输出已显示 `18/2`；最终重连后 0.107 秒内
  达到 `18/2` 和 confirmed LSN `0/1998C90`，残余 WAL 为 0 bytes，满足 60 秒恢复与 1 MiB WAL 安全
  预算，并在 drain 后 inactive。Flink 在 completed checkpoint `26`、处理计数 `5` 后失败，attempt `1`
  从 count `3` 恢复，checkpoint `165` 至 `214` 均观测全部 20 条记录。最终源状态与 Silver 重建状态均为
  2 条道路；各阶段 sink、slot、LSN、WAL、Job 状态、connector/JAR/runtime image 和 drain savepoint
  均进入 commit evidence。
  第二次分区中增加 nullable `observed_at TIMESTAMPTZ` 后，显式四字段投影继续消费，恢复后 Silver 从
  `10` 增至 `12` 且 quarantine 保持 `2`；该 drift 已走 `observed -> reconciled`。随后把该列收紧为 `NOT NULL`
  产生 breaking `nullable_tightened` drift；既有作业仍为 `RUNNING`，但 successor 保持
  `approval_required`，绑定的 ApprovalCase 只有一条 `pending` 事件且无人工 verdict，通用
  `SourceSchemaPromotionDecision` 以 `breaking_schema_drift_pending_approval` 阻断自动晋级。该决定与漂移
  ID、ApprovalCase reference 和运行投影一起进入 commit evidence。
  target/output、独立 QualityResult、LineageEvent、OpenMetadata outbox 和物理非零 quarantine receipt
  与 SourceSync commit 原子绑定，checkpoint 仅推进 `0 -> 1`；同 ID 和第二个合法 Run 均恢复原双证据，
  provider 只执行一次。18 项端到端门、20 项 provider 门与 4 项 schema-governance 门全部通过，隔离
  容器、控制数据库和工作目录已删除，主库 sync 表保持为空。该证据仍是本地短生命周期 Docker，不是
  K8s；不代表 Flink/Iceberg CDC
  sink、跨系统事务、selected-column type/remove/rename 等更广 schema evolution、reconnect-backoff
  exhaustion、slot 自动修复/恢复、WAL capacity、PostgreSQL failover、生产 SLO 或 HA。详见
  [ADR-106](architecture-decisions/adr-106-postgresql-cdc-flink-source-sync-certification.md)、
  [ADR-165](architecture-decisions/adr-165-checkpoint-consistent-cdc-quarantine-routing.md)、
  [ADR-166](architecture-decisions/adr-166-bounded-cdc-network-partition-slot-recovery.md)、
  [ADR-167](architecture-decisions/adr-167-active-cdc-schema-evolution-promotion-gate.md)、
  [ADR-168](architecture-decisions/adr-168-repeated-cdc-partition-schema-wal-recovery.md)、
  [ADR-169](architecture-decisions/adr-169-rapid-cdc-network-flapping-slot-recovery.md)、
  [ADR-170](architecture-decisions/adr-170-long-duration-cdc-outage-recovery-budget.md)、
  [ADR-171](architecture-decisions/adr-171-sustained-high-frequency-cdc-flapping.md)、
  [ADR-172](architecture-decisions/adr-172-cdc-slot-incarnation-fail-closed-admission.md) 和
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`，报告 SHA-256
  `abd4a89b66cff55a866eeab3187de4e989d69e7127565a0c31936c0ff6b4bb26`。
- [x] 已完成同一 PostgreSQL CDC source 的 replication-slot teardown/invalidation 独立负向认证。
  三条初始快照进入 checkpoint 后，先物理断开 PostgreSQL 容器网络，再定向终止该 slot 唯一 active
  backend；原 slot inactive 后于 LSN `0/1952200` 删除，并由 `pg_replication_slots` 查询证明物理不存在。
  无 slot 期间 projected mutation 提交到 `0/1952340`；随后用相同名称重建 `pgoutput` slot，consistent
  LSN 为 `0/1952378`。平台以 PostgreSQL system identifier、database identity、slot name/plugin/type、
  creation-anchor LSN、incarnation ordinal 和建立事件生成实例 fingerprint；原实例
  `a8956f5035fafb592bd8f5e2768b54895f5585f3fdf74b55b05784d8bff16b35` 与同名新实例
  `7b0d16866d49dac2c28f9c520ab7e1697a7723a903e176f9f749de06e93de4d5` 不同。
  controller 以 `replication_slot_absence_witnessed` 和 `replication_slot_incarnation_changed` 返回
  `rejected_fail_closed`，在重连前把仍为 `RUNNING` 的 Flink job 终止为 `CANCELED`；故障后物理 sink
  保持 `3/0` 零增长。PlatformRun 最终为 `failed`，SourceSync checkpoint 保持 version `0`，commit
  history 为空，Artifact、QualityResult、LineageEvent、target ResourceVersion 和成功 provider admission
  均为 0。9/9 provider 门和 9/9 顶层门全部通过，隔离容器、控制数据库和工作目录全部删除；这证明
  同名 slot 不是连续性身份；该认证本身不代表自动修槽、connector backoff exhaustion、WAL capacity 或 failover。
  详见 [ADR-172](architecture-decisions/adr-172-cdc-slot-incarnation-fail-closed-admission.md) 和
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-slot-invalidation-report.json`，报告 SHA-256
  `057c83ed556975a57a241a4a7ff19749cc9c049275931eced3fa4ab27d6025e6`。
- [x] 已完成同一 PostgreSQL CDC source 的有限 slot WAL capacity 独立负向认证。SourceSyncDefinition
  fingerprint 已绑定 1 MiB `max_slot_wal_keep_size`、64 KiB 最小安全余量、512 MiB 源文件系统安全底线和
  `on_unsafe_or_lost=reject_fail_closed`。三条初始快照进入 checkpoint 后物理断网并终止复制 backend，
  原同一 slot inactive 且为 `reserved`，restart LSN `0/19520D0`、`safe_wal_size=7,003,648`。
  一轮 16 x 524,288-byte 的确定性 logical-message 压力请求 8,388,608 payload bytes；WAL 从
  `0/1952200` 经 emitted `0/21586D8` 推进到 checkpoint `0/30000D8`，实际距离 23,781,080 bytes。
  checkpoint 后该 slot 仍同名、同 system identifier 且物理存在，但 `wal_status=lost`、`restart_lsn`
  为空、`safe_wal_size=null`。`pg_wal` 从 16,785,408 增至 50,339,840 bytes，测量路径仍有
  1,344,133,394,432 bytes 可用，远高于安全底线；最大 payload 与 segment-aware 物理 WAL 预算分别为
  32 MiB 和 160 MiB，因此证明的是有界配置保留失效，不是磁盘耗尽。
  controller 以 `replication_slot_wal_status_lost`、`replication_slot_restart_lsn_missing` 和
  `replication_slot_safe_wal_size_exhausted` 返回 `rejected_fail_closed`，在重连前把 Flink 从 `RUNNING`
  终止为 `CANCELED`；sink 保持 `3/0` 零增长。PlatformRun 为 `failed`，SourceSync checkpoint 保持 0，
  commit、Artifact、QualityResult、LineageEvent、target ResourceVersion 和成功 provider admission 均为 0。
  11/11 provider 门、10/10 顶层门和全部清理门通过；不代表物理磁盘耗尽恢复、自动 resnapshot、connector
  backoff exhaustion、生产 WAL rate/RPO/RTO 或 failover。详见
  [ADR-173](architecture-decisions/adr-173-bounded-cdc-slot-wal-capacity-admission.md) 和
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-wal-capacity-report.json`，报告 SHA-256
  `412aacd1a90c1c165332510649d28c32a4128268f0c7a0aef13e6fddf769c919`。
- [x] 已完成 PostgreSQL 16 CDC 真实物理主备切换与 timeline admission 独立负向认证。隔离主库以
  `pg_basebackup -R -X stream` 建立异步 streaming standby；revision-2 projected mutation 在主库提交到
  LSN `0/3000390`，备库 receive/replay LSN 均精确达到 `0/3000390` 且完整行一致，Flink sink 已在
  checkpoint count 5 固化为 `5/0`。停止并从网络移除旧主库后提升备库，同一 PostgreSQL
  `system_identifier=7671164979134124066` 保持不变，timeline 从 `1` 精确递增至 `2`；提升源保留 publication
  和 replayed row，但 PostgreSQL 16 不存在原 `pgoutput` logical slot。controller 仅以
  `logical_replication_slot_missing_after_promotion` 返回 `rejected_fail_closed`；稳定源 alias 随后才转移，
  Docker network metadata 反查确认 alias 已挂到提升源；revision-3 probe 推进到 `0/30008E8`，随后 2.0 秒
  观察期内物理 sink 仍保持 `5/0` 零增长，Flink 从 `RUNNING` 由
  controller 终止为 `CANCELED`。PlatformRun 为 `failed`，SourceSync checkpoint 保持 0，commit、成功
  output Artifact、QualityResult、LineageEvent、target ResourceVersion 和成功 provider admission 均为 0；
  另有 1 个绑定失败 Run 的 recovery evidence Artifact。13/13 provider 门、20/20 顶层门和 11/11 清理门通过；这证明物理集群连续性不等于 logical slot
  连续性，不代表自动 slot 同步/重建、CDC 自动续传、生产 RPO/RTO 或 HA。详见
  [ADR-174](architecture-decisions/adr-174-postgresql-cdc-physical-failover-timeline-admission.md) 和
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-failover-report.json`，报告 SHA-256
  `0b484dfe466b75a07099fff3ce12701d58a012a47182e0aaecf4efecb3ee654c`。
- [x] 已补齐 PostgreSQL CDC promotion 的 fencing 负向门。正常 failover 认证现在要求
  `gda.postgresql_primary_fencing.v1` 的 `stop_and_detach` 证据：旧主停止、网络移除且 post-fence
  写探针被拒绝；旧主仍在线时的真实 split-brain 认证让旧主与 promoted 主分别写入同一道路的
  divergent revision，确认旧 alias 未接管并在任何 alias transfer 前 `rejected_fail_closed`；该
  standalone provider 不调用 SourceSync。
  主备/卷清理门和 split-brain 9/9 provider 门均通过。该切片证明 fail-closed
  fencing admission，不代表自动 fencing、lease、split-brain prevention、生产 RPO/RTO 或 HA。
  详见 [ADR-175](architecture-decisions/adr-175-postgresql-cdc-split-brain-fencing-admission.md)、
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-split-brain-report.json`，报告 SHA-256
  `5f922455708c4d31f19b1d482804d827ec59ae178affd0e8f19e0d8f5629b364`。
- [x] 已将 failover 拒绝转为不可变的受治理恢复边界。`PostgresqlCdcFailoverRecoveryPlan`
  绑定原始 admission evidence、最后安全的 SourceSync checkpoint 和 reason codes，明确
  `resnapshot_and_reconcile`、`cursor_disposition=do_not_advance` 与必须创建新 Run；恢复计划
  fingerprint 为 `7e687270e2a494b3dcae8b90108281e18e2d0a28903cc59291bfd555e5dff4c2`，checkpoint
  保持 `0`，commit/成功 output Artifact/QualityResult/LineageEvent/成功 provider admission 均为
  `0`，并将 1 个 recovery evidence Artifact 以幂等方式写入失败 Run。该切片只固化
  fail-closed 后的 recovery contract，不代表生产 recovery-controller、slot 重建、CDC 续传、
  生产 RPO/RTO 或 HA；详见 [AR-2 handoff](handoffs/2026-08-05-ar2-postgresql-cdc-failover.md)。
- [x] 同一认证已完成 resnapshot provider、自动 recovery schedule 与真实 DolphinScheduler 终态闭环：注册新
  definition/version `334e0c3d-8a53-4937-90d1-fd8e5e626159`
  （`full`/`overwrite`/无 cursor/`batch`），创建新 Run
  `9e7026ab-86d5-55ca-9876-08bd68d4ddcd`，admission fingerprint 为
  `e56ede9622f674d8250e6ccaa3dcbdecbeaa955e3010617f9f284f76a9b000eb`；从 promoted standby
  实际读取 3 行并以 `29fda3d9cf9a36f40957a0001210bea4d73f5d077ba741dbfa38926e12bf6936` 作为
  source/target snapshot fingerprint，完成 output/quality/quarantine/lineage/metadata evidence、
  commit `365b65c9-98a0-5560-8163-4ad70112b853` 和幂等重放。恢复控制器不再伪装人工请求：
  标准 `DataOpsScheduleWindowSpec` 以 recovery-plan SHA-256 固化 schedule identity，原子创建
  invocation/Run/policy Artifact/dispatch command，`trigger_kind=schedule` 且无 human delegation。
  DolphinScheduler 3.4.2 workflow `180820130339392` / instance `28` 真实观察 `SUCCESS`，`RunSuccessEvidence` 将 Run 从
  `reconciling` 收敛为 `succeeded`；旧 definition/checkpoint 保持不变，新 checkpoint 为 `1`。
  该证据只证明隔离环境自动触发纵向切片；生产 recovery-controller 部署、自动 slot-loss 检测、
  slot 重建、CDC 续传、生产 RPO/RTO 或 HA 仍未完成；报告 SHA-256 为
  `0b484dfe466b75a07099fff3ce12701d58a012a47182e0aaecf4efecb3ee654c`，详见
  [AR-2 handoff](handoffs/2026-08-05-ar2-postgresql-cdc-failover.md)。
- [x] 已将 slot-loss 判定从认证脚本提升为可复用的 recovery-controller 合同：
  `PostgresqlCdcSlotIncarnation` 对 slot identity/ incarnation 做不可变 fingerprint，
  `PostgresqlCdcSlotContinuityObservation` 绑定 tenant、sync-definition version 和最后安全
  checkpoint cursor，`PostgresqlCdcRecoveryDecision` 明确 `resume_cdc`、有物理缺失证据时的
  `schedule_resnapshot`，以及证据不足时的 `rejected_fail_closed`。连续 slot 只保留原 checkpoint
  authority；slot 缺失/同名重建只保留 checkpoint 并要求新 governed Run；未观测到缺失的变化不得
  自动排程。现有 slot-invalidation certification 已复用该模块，8 项新契约测试与原 5 项负向
  测试通过；真实 PostgreSQL 16.14 + Flink 1.19.3 隔离认证的 provider/top-level/cleanup
  gates 分别为 `9/9`、`9/9`、`7/7`，checkpoint 保持 `0`、commit history 为空，报告 SHA-256
  为 `b81d996f5588fc1c9608db72d80d1647be2122d844e0c98a6d83df4e79f35413`。该切片仍不代表
  controller 的生产部署、观测持久化、slot repair、CDC resume 或 RPO/RTO/SLO；failover 认证已
  在创建 recovery plan/schedule 前强制该 controller 返回 `schedule_resnapshot`，并将 observation
  与 decision fingerprint 写入 recovery evidence；该 rerun `21/21` top-level、`11/11` cleanup，
  同时通过 PlatformGateway 持久化 controller evidence Artifact（首写/幂等重放分别为
  `created=true/false`），最终 rerun `22/22` top-level、`11/11` cleanup，report SHA-256 为
  `41706da28f937c572a16d6d9545e90c1b282aef906b2ac1e77e42ce5281ef049`；该 rerun 已由
  gateway-injected runtime service 执行，而非认证脚本内置 persistence。详见
  [ADR-176](architecture-decisions/adr-176-postgresql-cdc-recovery-controller-slot-continuity.md)。
- [x] 已把 recovery-controller observation 从 Artifact-only projection 推进为可查询的 durable
  control-plane ledger：迁移 `147_postgresql_cdc_recovery_observation` 使用 append-only table、
  tenant RLS/`FORCE ROW LEVEL SECURITY`、immutable trigger 和 SECURITY DEFINER recorder，
  以 Artifact、SourceSync definition version、PlatformRun、checkpoint cursor、observation/
  decision/recovery-plan fingerprint 建立单一关联；`PlatformGateway` 在一个事务内完成 Artifact
  和 ledger 写入，gateway role 仅有 ledger `SELECT` 与 recorder `EXECUTE`，直接写权限为零。
  真实 PostgreSQL 16.4 + Flink 1.19.3 + DolphinScheduler 3.4.2 rerun 的 provider/top-level/
  cleanup gates 为 `13/13`、`23/23`、`11/11`，ledger 首写/重放为 `true/false`，查询 projection
  与 checkpoint/observation/decision/recovery-plan 全部一致，旧 SourceSync checkpoint 仍为 `0`；
  report SHA-256 为 `7d4a731ecb97e21e8b9a4b9f42e048261f3e31253dc5ad08823b31a09fb36cc1`，migration
  catalog/database 为 `148/148`，fingerprint 为
  `6ffffe01e1f337ddbcb9cf6500b93757eb43a86aba693c4334b680f2c995b71f`。平台现已通过
  `GET /api/platform/v1/recovery-observations/{artifact_id}` 暴露该 projection：tenant 只能
  来自认证主体，客户端没有 tenant override，UUID/401/403/404 与 OpenAPI 安全合同由
  platform gateway 的 77 项测试覆盖。该接口只读取 observation/evidence authority，不会
  写 checkpoint、创建 Run 或调度恢复；这仍不代表生产 recovery-controller deployment、
  slot repair、CDC resume、failover RPO/RTO 或 HA。
- [x] 已完成同一真实 OSM source slice 的 Spark/Flink/MinIO Iceberg 双向互操作。Spark 3.5 + Iceberg
  1.6.1 先创建 3 行 format-v2 基线 snapshot `4841911483547347489`；Flink 1.19.3 + Iceberg 1.7.2
  读到基线后增加 `flink_commit_tag` 字段并追加第 4 行，形成 child snapshot
  `5136003194891216528`；Spark 1.6.1 runtime 随后读到精确 5 列/4 行，并通过旧 snapshot time travel
  回读原 3 行。随机 JDBC Catalog 与 MinIO S3FileIO 下实际形成 3 个 metadata JSON、4 个 manifest AVRO
  和 3 个 Parquet；6 项端到端门全部通过，10 个对象、catalog/Flink 容器和工作目录全部删除。该认证
  冻结了 Flink Iceberg/AWS/Hadoop/JDBC artifact 哈希，但只证明 create/read/add-column/append/readback/
  time-travel；不代表 streaming checkpoint recovery、cancel/uncertain commit、并发写、REST/Gravitino
  catalog、生产 SLO、HA 或 K8s。详见
  [ADR-107](architecture-decisions/adr-107-spark-flink-minio-iceberg-interoperability.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-iceberg-report.json`，报告 SHA-256
  `778772de0868533c683b042f0d352392c0010a66d654cbce57f0132a863c419c`。
- [x] 在 ADR-107 同一 Spark/Flink/Iceberg/MinIO 版本矩阵上完成真实 checkpoint recovery。Spark 先创建
  三行 OSM 基线；Flink checkpointed source 发送四个唯一真实道路事件，在 completed checkpoint `2`、
  offset `2` 后主动失败，attempt `1` 从 offset `2` 精确恢复并完成 offset `4`。Spark 最终读取 7 行，
  四个 stream event 无重复/丢失，且能回看恢复前的三行基线 snapshot。基线与三次有效 Flink append
  形成四层连续 snapshot parent chain；MinIO 物化 6 个 metadata JSON、9 个 manifest AVRO 和 5 个
  Parquet。6 项端到端、3 项 recovery、7 项 Spark readback 门全部通过；20 个对象、catalog/Flink
  容器、checkpoint 和工作目录已删除。本证据只声明单 job/单并行度/单表 checkpoint recovery，不代表
  cancel、uncertain commit、跨引擎并发、跨系统 exactly-once、REST/Gravitino、生产 SLO、HA 或 K8s。
  详见 [ADR-108](architecture-decisions/adr-108-flink-iceberg-checkpoint-recovery.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-iceberg-recovery-report.json`，报告 SHA-256
  `8fd1e3727af3864df4f19720c7e312b3d23d5468301cd718324b082415d1e473`。
- [x] 已完成 Flink/Iceberg checkpoint 前 cancel 与“provider 已提交但控制面确认丢失”的真实对账。
  取消作业在四条 source event 已发出、completed checkpoint 为 0 时被真实取消，Flink 终态
  `CANCELED`，Iceberg 仍只有三行基线 snapshot，SourceSync/DataProductVersion 均未推进。随后同一确定性
  source slice 以自身 SHA-256 作为 commit token，先在 checkpoint offset 3 形成合法部分快照，再在
  offset 4 形成唯一七行终态 snapshot；
  验收故意不回写控制面，SourceSync 保持 version 0，再由独立 Spark time-travel probe 按 token、行数、
  operation 和内容 SHA-256 找回该 snapshot，原子推进 SourceSync `0 -> 1`。第三个合法 Run preflight
  命中原 commit 并跳过 Flink，snapshot chain、内容 hash 和单条 commit 均无新增；DataProductVersion
  始终为 0。14 项门全部通过，14 个 MinIO 对象、随机控制数据库、Catalog/Flink 容器、checkpoint 和
  工作目录已删除，主库 sync 表保持 `0/0/0`。本证据不代表 kill -9/网络分区、跨引擎并发写、
  跨系统 exactly-once、REST/Gravitino、生产 SLO、HA 或 K8s。详见
  [ADR-109](architecture-decisions/adr-109-flink-iceberg-cancel-and-uncertain-commit-reconciliation.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-iceberg-reconciliation-report.json`，报告 SHA-256
  `f3478cc12e1b0f71ae7bbee3095c70e17da9843000cd3f3d05b7ace671ae20ef`。
- [x] 已完成同一 MinIO Iceberg 表上的 Spark/Flink 受控并发 append。Spark 基于三行 baseline 启动写入
  并进入 executor barrier；Flink 随后追加第四行，独立 JDBC Catalog 检查确认 pointer 已推进到 Flink
  child snapshot 后才释放 Spark。Spark 乐观重基到该 child 并追加第五行，最终三个 append snapshot
  形成线性 parent chain；五行内容、road ID、writer 计数和两个 commit token 均精确且无重复/丢失，
  baseline 与 Flink 后状态均可 time travel 回读。9 项顶层门全部通过；3 个 metadata JSON、6 个
  manifest/list AVRO 和 4 个 Parquet 共 13 个对象已真实物化并清理，Spark/Flink/Catalog 容器和工作目录
  已删除，主库 SourceSync 保持 `0/0/0`。本证据只放行 batch append convergence，不代表 overwrite/
  delete/update/merge 冲突隔离、并发 streaming writer、REST/Gravitino、HA 或 K8s。详见
  [ADR-110](architecture-decisions/adr-110-spark-flink-concurrent-append.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-concurrent-append-report.json`，报告 SHA-256
  `e70c5d487e5264fbdd42ac5b4f336936df1831e5392451d0f4fda9bb4034354d`。
- [x] 已完成 Spark/Flink 破坏性 overwrite 冲突隔离。Spark 先建立通过
  `validateFromSnapshot + validateNoConflictingData/Deletes` 绑定三行 baseline 的 Iceberg
  `OverwriteFiles` transaction；Flink append 第四行并推进 JDBC Catalog 后才释放 Spark。陈旧 overwrite
  得到 `ValidationException`，没有生成 snapshot，catalog 与四行内容保持在 Flink child，Spark token 为
  0。独立 Spark retry 先读取精确四行 fresh state，再更新一条道路并保留 Flink 行，只生成一个 overwrite
  snapshot；最终 Flink/Spark token 各一次，baseline 与 Flink 后状态均可 time travel。12 项顶层门全部
  通过；3 个 metadata JSON、8 个 manifest/list AVRO 和 5 个 Parquet 共 16 个对象已清理，三个验收容器
  和工作目录已删除，主库 SourceSync 保持 `0/0/0`。本证据不放行 delete/row-level update/merge、自动
  retry、并发 streaming writer、REST/Gravitino、HA 或 K8s。详见
  [ADR-111](architecture-decisions/adr-111-snapshot-bound-overwrite-conflict-isolation.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-overwrite-conflict-report.json`，报告 SHA-256
  `640684c15c5c88283751b0460107af89309598fd19c9a030f01be1627881bcb3`。
- [x] 已完成 Spark/Flink 业务键 delete 与同 key insert 的冲突隔离。三行 baseline 不包含目标道路
  `102262026`；Spark 先建立绑定 baseline、目标 key 和 delete token 的 `OverwriteFiles` conflict intent，
  Flink 再插入目标道路并推进 catalog。陈旧 intent 得到 `ValidationException`，没有 delete snapshot，
  四行内容和 catalog 保持 Flink child，delete token 为 0。独立 Spark retry 精确读取 fresh state 后使用
  `DeleteFiles` 删除该 key，只形成一个带 token 的 delete snapshot；三条非目标道路与 baseline 内容完全
  一致，baseline/Flink 状态均可 time travel。12 项顶层门全部通过；3 个 metadata JSON、6 个
  manifest/list AVRO 和 3 个 Parquet 共 12 个对象已清理，三个验收容器和工作目录已删除，主库
  SourceSync 保持 `0/0/0`。本证据只放行无分区 copy-on-write key delete/insert race，不代表
  partitioned/equality/position/MOR delete、row-level update/merge、自动 retry、HA 或 K8s。详见
  [ADR-112](architecture-decisions/adr-112-snapshot-bound-key-delete-conflict-isolation.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-delete-conflict-report.json`，报告 SHA-256
  `f32cd1bf6dfd786637cfd876c273b76a931d2b21bf8922aa26cd76cc1d3cbf8c`。
- [x] 已完成 Spark/Flink identity-key 分区替换型 update 冲突隔离。三行 baseline 按 `road_id` identity
  partition，目标道路 `102262017` 已有 revision 1；Spark 建立绑定 baseline 和目标 key 的
  `OverwriteFiles` conflict intent 后，Flink 在同一分区追加 revision 2。陈旧 intent 得到
  `ValidationException`，没有生成 Spark snapshot/token，revision 1/2 和 catalog Flink child 均保持不变。
  独立 Spark retry 精确重读 Flink snapshot，保留其道路名称与 geometry hash，使用
  `overwritePartitions()` 只把目标分区更新为 revision 3；最终仍为三个唯一 road ID，两个非目标分区及
  baseline/Flink time travel 均准确。12 项顶层门全部通过；3 个 metadata JSON、8 个 manifest/list AVRO
  和 5 个 Parquet 共 16 个对象及全部临时容器/目录已清理，主库 SourceSync 保持 `0/0/0`。首轮证据中
  Flink/Iceberg partition fanout writer 需要关闭 classloader leak check；ADR-114 随后通过 single-operation
  writer lifecycle 移除了该 override。本证据不代表通用 SQL UPDATE/MERGE、delete-file/MOR、自动
  retry、HA 或 K8s。
  详见 [ADR-113](architecture-decisions/adr-113-partition-replace-update-conflict-isolation.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-update-conflict-report.json`，报告 SHA-256
  `a1f1ca87aad779493dfb8bab6a1c4e0469b20c6f4aa62cd51f814fe62bb4ddce`。
- [x] 已完成 Flink partition writer classloader 安全生命周期收敛。新的 Flink job 只执行一次
  partitioned `INSERT`，baseline admission 和最终 readback 分别由 Spark/JDBC Catalog 独立负责；隔离
  集群显式保持 `classloader.check-leaked-classloader: true`，并由 JobManager REST 观测实际值。在完全相同
  的重庆 OSM update 冲突场景中，13 项顶层门全部通过，内容 hash 与 ADR-113 首轮证据一致；3 个
  metadata JSON、8 个 manifest/list
  AVRO、5 个 Parquet 共 16 个对象和所有临时容器/目录已清理，主库 SourceSync 保持 `0/0/0`。这只移除
  当前 partition-replace path 的 override blocker，不放行通用多 query/streaming Flink lifecycle、SQL
  UPDATE/MERGE、HA 或 K8s。详见
  [ADR-114](architecture-decisions/adr-114-single-operation-flink-writer-lifecycle.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-update-conflict-no-override-report.json`，报告
  SHA-256 `4ce57c0237a19e28bb9c3ff3680a2cf80eba503fa7cdda3b45b7818eae8ffd4a`。
- [x] 已完成 identity-partitioned copy-on-write key delete 冲突隔离。目标道路 `102262017` 在三分区
  baseline 中已有 revision 1；Spark 建立 snapshot-bound delete intent 后，Flink single-operation writer
  在同 partition 追加 revision 2。陈旧 intent 得到 `ValidationException`，没有生成 delete snapshot/token；
  fresh retry 精确重读 Flink child 后使用原生 `DeleteFiles` 删除目标 partition 的两个 data file，两个
  非目标 partition 逐行保留，baseline/Flink 状态均可 time travel。13 项顶层门全部通过，JobManager REST
  观测 classloader safety check 为 `true`；3 个 metadata JSON、7 个 manifest/list AVRO、4 个 Parquet 共
  14 个对象和所有临时容器/目录已清理，主库 SourceSync 保持 `0/0/0`。本证据不放行 equality/position
  delete file、merge-on-read、通用 SQL UPDATE/MERGE、自动 retry、HA 或 K8s。详见
  [ADR-115](architecture-decisions/adr-115-partitioned-copy-on-write-delete-conflict-isolation.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-partition-delete-conflict-report.json`，报告
  SHA-256 `77795e9698c7a989b65aa24e33778e18042e7bca9dee7a430be10ad34e441c82`。
- [x] 已完成 Spark MOR position delete 到 Flink 的顺序读取互操作。Spark 在无分区 format-v2 表中
  以单个 Parquet data file 写入三条真实重庆 OSM 道路，再用 SQL `DELETE` 删除道路 `102262020`；
  metadata 证明原三行 data file 保留，并新增唯一 `content=1`、`record_count=1`、
  `equality_ids=[]` 的 Parquet delete file，其 position `1` 精确指向原 data file。Flink 1.19.3/
  Iceberg 1.7.2 single-operation read 返回两行、目标零行和两个唯一 road ID，且 catalog pointer 不变；
  独立 Spark 会话精确验证最终状态和 baseline time travel。10 项顶层门全部通过，JobManager REST 观测
  classloader safety check 为 `true`；2 个 metadata JSON、4 个 manifest/list AVRO、2 个 Parquet 共
  8 个对象及隔离 Flink/JDBC Catalog 容器和工作目录已清理，主库 SourceSync 保持 `0/0/0`。本证据只
  放行当前版本矩阵下 sequential position-delete/MOR read interoperability，不放行 equality delete、
  Flink 侧 position-delete 写入、并发 position-delete conflict isolation、自动 retry、HA 或 K8s。详见
  [ADR-116](architecture-decisions/adr-116-spark-flink-position-delete-read-interoperability.md) 和
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-position-delete-interop-report.json`，报告 SHA-256
  `e0a0c5ed96b6e2208a6a2efe05aaba91db37fab1b63cdc5e75e999a340c4eaa5`。
- [x] 已完成 Flink equality delete 到 Spark 的反向顺序互操作。Spark 用显式 DDL 创建
  `road_id BIGINT NOT NULL` 的无分区 format-v2 表，把 `road_id` 注册为唯一 identifier field，并以
  单个 data file 写入三条真实重庆 OSM 道路；Flink bounded streaming job 通过唯一 DELETE changelog
  删除道路 `102262020`，只执行一次 provider DML。独立 Spark 证明原三行 data file 保留，新增唯一
  `content=2`、`record_count=1`、`equality_ids=[1]` 的 Parquet equality delete file，当前两行和
  baseline time travel 均逐行准确；验收进程通过 MinIO 直接读取 480-byte 物理 delete Parquet，确认只含
  目标 key。10 项顶层门全部通过，JobManager REST 观测 classloader safety check 为 `true`；4 个
  metadata JSON、4 个 manifest/list AVRO、2 个 Parquet 共 10 个对象及隔离 Flink/JDBC Catalog 容器和
  工作目录已清理，主库 SourceSync 保持 `0/0/0`。本证据只放行当前版本矩阵下 bounded single-key
  equality-delete write/read interoperability，不放行并发 equality-delete conflict、Flink
  position-delete writer、复合 key、持续 checkpoint stream、HA 或 K8s。详见
  [ADR-117](architecture-decisions/adr-117-flink-spark-equality-delete-write-interoperability.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-spark-equality-delete-interop-report.json`，报告 SHA-256
  `bbc1c222460b4c8dbd7724be97c5acdc8910e583c4fb88c999052b620917b49b`。
- [x] 已完成 snapshot-bound Spark update intent 与 Flink equality delete 的同 key 冲突隔离。Spark
  intent 先绑定三行 baseline snapshot、目标道路 `102262020`、同 key conflict filter 和 update token；
  Flink bounded single-operation job 再提交该 key 的 equality delete 并推进 JDBC Catalog，之后才释放
  Spark。陈旧 update 得到 provider `ValidationException`，未生成 Spark snapshot/token，catalog、最终
  两行和物理 equality delete file 均保持 Flink child。独立 fresh-state reconciliation 观测目标已删除，
  按 `delete-wins-target-absent-no-resurrection` 返回 `retry_authorized=false`，没有创建第三个 snapshot；
  独立 Spark verify 精确验证最终状态和 baseline time travel。14 项顶层门全部通过，JobManager REST
  观测 classloader safety check 为 `true`；4 个 metadata JSON、4 个 manifest/list AVRO、2 个 Parquet
  共 10 个对象及隔离 Spark/Flink/JDBC Catalog 容器和工作目录已清理，主库 SourceSync 保持
  `0/0/0`。本证据只放行 update-versus-equality-delete conflict，不放行 equality-delete/insert race、
  Flink position-delete writer、position/MOR 并发冲突、自动 resurrection/retry、HA 或 K8s。详见
  [ADR-118](architecture-decisions/adr-118-snapshot-bound-update-versus-equality-delete-conflict-isolation.md)
  和 `.tmp/source-sync-certification/chongqing-osm-spark-flink-equality-delete-conflict-report.json`，报告
  SHA-256 `7659f665a5a6e3b10bc68213e56f84320bf26964454750f5fec0f4e10e4be9b5`。
- [x] 已完成 snapshot-bound Spark equality-delete authorization 与 Flink append insert 的同 key 冲突
  隔离。三行 baseline 不含目标道路 `102262026`；Spark intent 绑定 baseline、目标 key 和 conflict
  filter 后等待，Flink single-operation `INSERT INTO` 以 append snapshot 插入目标并推进 JDBC Catalog，
  再释放 Spark。陈旧 intent 得到 provider `ValidationException`，没有生成 authorization snapshot，四行
  insert 状态保持 current。独立 Spark fresh-state 会话精确读取四行并返回 `retry_authorized=true`，授权
  本身不创建 snapshot；单独 Flink bounded DELETE changelog job 随后生成唯一 equality delete file，
  独立 Spark 验证最终 baseline 三行、baseline/insert time travel 和 `append -> append -> delete` 快照链。
  物理文件为 `content=2`、`record_count=1`、`equality_ids=[1]`，MinIO 直读只含目标 key。16 项顶层门
  全部通过，JobManager REST 观测 classloader safety check 为 `true`；5 个 metadata JSON、6 个
  manifest/list AVRO、3 个 Parquet 共 14 个对象及隔离 Spark/Flink/JDBC Catalog 容器和工作目录已清理，
  主库 SourceSync 保持 `0/0/0`。本证据只放行 equality-delete authorization versus insert race，不放行
  Flink position-delete writer、position/MOR 并发冲突、通用 SQL UPDATE/MERGE、自动 retry、HA 或 K8s。
  详见
  [ADR-119](architecture-decisions/adr-119-snapshot-bound-equality-delete-versus-insert-conflict-isolation.md)
  和 `.tmp/source-sync-certification/chongqing-osm-spark-flink-equality-delete-insert-conflict-report.json`，报告
  SHA-256 `af051adf8d4e54c467b29d42db0b33f7d1c0bd21c965c303d606a8a26398bafe`。
- [x] 已完成 Flink position delete 到 Spark 的反向写入互操作。Spark 在无分区 format-v2、MOR 表中
  以单个 data file 建立三行重庆 OSM baseline，并通过隐藏列 `_file/_pos` 把目标道路 `102262020`
  绑定到原文件 position `1`。Flink 1.19.3 单元素 DataStream 在唯一 TaskManager task 内使用 Iceberg
  1.7.2 position writer 和一次 `RowDelta.commit()` 提交，显式关闭自动重启并绑定 baseline snapshot、
  data-file existence 和确定性 commit token。JobManager REST 只观测到一个 `FINISHED` job 和一个
  finished task；独立 Spark 证明原三行 data file 保留，新增唯一 `content=1`、`record_count=1`、
  `equality_ids=[]` 的 Parquet delete file，当前两行、baseline time travel 和 `append -> delete` 链均
  精确。MinIO/PyArrow 直接读取 1,882-byte 物理文件，确认只有 baseline data file 和 position `1`。
  12 项顶层门全部通过，classloader safety check 为 `true`；2 个 metadata JSON、4 个 manifest/list
  AVRO、2 个 Parquet 共 8 个对象及隔离 Flink/JDBC Catalog 容器和工作目录已清理，主库 SourceSync
  保持 `0/0/0`。本证据只放行专用 low-level adapter 的单文件单行 position-delete writer，不代表
  Flink SQL position delete、position/MOR 并发冲突、自动 retry、checkpoint exactly-once、HA 或 K8s。
  详见 [ADR-120](architecture-decisions/adr-120-flink-spark-position-delete-write-interoperability.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-interop-report.json`，报告
  SHA-256 `ec13afd09a3d8617519c112461009495da8265131cc3b53beb43489549fd95d5`。
- [ ] 跨产品 batch/object materialization 的统一控制与证据管线、vector/raster adapter registry，
  三类 connector 的只读基础能力，以及 PostgreSQL 的真实 credential rotation/schema
  mutation/drift、MinIO 的真实 credential rotation、authenticated STAC transport 的 credential
  rotation、三类 source 的字段级 drift、SchemaDriftEvent 账本和受控 reconciliation，以及
  SourceSync definition/commit/checkpoint authority 及 Silver/Gold 质量、审批、血缘、metadata outbox
  原子晋级门已验证；Flink event-stream duplicate/late、PostgreSQL CDC invalid-record 的实际拒绝与
  Spark/Iceberg micro-batch 显式零拒绝 receipt 已走同一通用 recorder，但其他数据库 CDC、非结构化、
  点云和时序 provider 尚未认证，且
  production STAC provider 认证、非 JSON 对象格式的 schema drift、三类 source 网络故障与重复摄取、
  其他 source 的重复摄取、CDC selected-column/concurrent-DDL evolution、reconnect-backoff exhaustion、slot
  自动修复/恢复、物理磁盘耗尽与 predictive capacity SLO、Flink/Iceberg kill -9/
  网络分区不确定提交、position/MOR
  destructive-write 并发冲突隔离及通用 SQL UPDATE/MERGE 冲突隔离、REST/Gravitino catalog 互操作、
  并发/reconcile、
  DataSLO/Incident、
  DriveTransfer、双租户、备份恢复和默认/轻量/
  云 profile 语义等价仍未完成；ApprovalCase 基础 Inbox、指派/委托和 SLA/通知 outbox 已接入，但
  生产通知路由/恢复验收和除架构漂移外的 consumer 接入仍未完成，因此 AR-2 仍不得标为 `verified`。

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
- [x] 基于统一 ApprovalCase authority 的基础 Inbox 已提供 tenant-scoped、status/action 筛选、有界分页、
  append-only event 审计和携带 `expected_state_version` 的人工终态决定；前端“审批中心”禁用终态/过期
  case，独立人工、禁止 workload 决策、过期与 stale CAS 仍由 authority fail closed。
- [x] ApprovalCase 指派/委托已按
  [ADR-142](architecture-decisions/adr-142-approval-case-assignment-and-delegation.md) 建立独立路由权威：
  human admin 可指派、重指派或释放，当前负责人可委托给另一名非申请人，委托深度最多 5；全部变化携带
  assignment version CAS、理由和不可修改事件。存在 active assignee 时，PostgreSQL 内的 ApprovalCase
  transition 只接受该负责人作终态决定；决定落库时同事务关闭路由并追加事件，未指派或已释放事项保持
  开放处理池语义。审批中心展示当前负责人、委托深度和路由审计，并按身份开放操作。隔离 PostgreSQL 16
  认证脚本 `scripts/certify_approval_case_assignment.py` 的原有 19 项路由检查全部通过，覆盖非负责人决定/委托拒绝、
  requester 排除、五级深度、CAS、终态关闭、双租户、不可修改事件和 gateway 最小权限。
- [x] ApprovalCase 主体目录与团队权威已按
  [ADR-143](architecture-decisions/adr-143-approval-principal-directory-and-team-authority.md) 落地：迁移 121
  建立 tenant-scoped human/team 主体、审批资格、在岗状态、有效期和 effective-time 团队成员关系；主体与成员
  变更均使用 version CAS、human actor、理由及不可修改 snapshot event。指派只接受当前合格主体，空团队、
  停用/不在岗/未生效/已过期主体 fail closed；团队成员可代表团队决定，只有 `can_delegate` 成员可委托。
  PostgreSQL 同一权威返回当前 actor 的 decide/delegate access，审批中心据此开放操作并用目录选择器替代自由
  用户名。平台 API 已提供主体查询/维护及团队成员查询/维护，迁移前必须完成各 tenant 目录预同步，不提供旧
  collaboration team fallback。扩展后的隔离 PostgreSQL 16 认证 34/34 通过。
- [x] ApprovalCase SLA/通知源码切片已按
  [ADR-140](architecture-decisions/adr-140-approval-case-sla-notification-outbox.md) 建立事务性 outbox：
  `requested` 与定时 `expired` 随初始 event 原子创建，终态 event 原子抑制未到期提醒并排入 `decided`；
  forced RLS、租约、`SKIP LOCKED`、有界重试和稳定 Alertmanager 标签均已实现。expiry 只作为 SLA
  事实，不伪造 approval verdict。迁移 118/119 已在一次性 PostgreSQL 16 中联合验证 RLS、最小权限、
  恢复 CAS、上限和 stale-expiry 拒绝。`scripts/rehearse_approval_alertmanager_delivery.py` 进一步使用真实
  PostgreSQL 16.14、Alertmanager 0.28.1 和 Prometheus 3.5.0 完成 receiver pause/unpause 演练：2 次
  requested 失败均回到 pending，恢复后 requested、decided、expired 共 4 次投递成功；approved 告警以
  稳定标签关闭，expired 告警保持 active 但 case 仍为 pending，最终 outbox 重跑 claim 为 0。
- [x] ApprovalCase 通知 dead-letter 受控恢复源码切片已按
  [ADR-141](architecture-decisions/adr-141-governed-approval-notification-recovery.md) 完成：只有同租户
  human admin 可对 `failed` 通知携带 `expected_attempt_count` 和理由恢复；每条通知最多人工恢复 10 次，
  原尝试次数、原错误、操作者和理由进入 forced-RLS、不可修改的恢复事件。恢复只重置投递预算，不改变
  ApprovalCase 或制造 verdict；终态 case 的过期告警禁止重放。审批中心可查看恢复历史并执行单条重投，
  worker 已提供低基数 Prometheus outcome counter 和 cycle duration。隔离 PostgreSQL 16 认证脚本
  `scripts/certify_approval_notification_recovery.py` 的 10 项检查全部通过，覆盖连续 10 次恢复、上限、CAS、
  stale expiry、双租户、不可修改审计和 gateway 只读权限；真实投递演练已从 Prometheus API 反查
  `delivered=4`、`retrying=2`、cycle histogram count `=4` 且 target health 为 up，并验证全部一次性容器
  已清理。该开发环境证据不代表生产 receiver 路由、认证/TLS、HA、dashboard、告警升级或 on-call 已验证。
- [x] ApprovalCase 通知生产形态可观测性已按
  [ADR-144](architecture-decisions/adr-144-approval-notification-production-observability.md) 建立可选 Kubernetes
  组件：两副本 worker、RollingUpdate、PDB、反亲和、专用最小 Secret、非 root/只读文件系统、ServiceMonitor、
  五条 PrometheusRule、AlertmanagerConfig 和受限 NetworkPolicy。worker 通过 Downward API 注入 namespace
  稳定路由标签，并暴露最后成功周期时间戳，从而区分 scrape down 与消费循环停滞。Prometheus 3.5.0 的五组
  promtool 规则触发测试和 Alertmanager 0.28.1 的 amtool 校验均通过；真实 receiver 演练只将
  `GDAApprovalCase` 送达 `approval-oncall`，无关控制告警未泄漏，receiver URL 来自 Secret 文件。当前
  Docker Desktop 集群未安装 Prometheus Operator CRD，也未接企业 webhook，不能宣称 staging/production
  部署、TLS gateway、长期指标、dashboard 或 paging escalation 已验证。
- [x] ApprovalCase 长期运营查询与 Grafana provisioning 已按
  [ADR-145](architecture-decisions/adr-145-approval-notification-operational-sli-and-dashboard.md) 落地：canonical
  Prometheus 规则新增健康/目标副本、成功周期 age、30 分钟与 6 小时投递成功率、5 分钟投递结果速率和周期
  P95 共 7 条 recording rule；无通知的空闲窗口保持成功，worker down/stalled 仍由独立信号暴露。固定 UID
  `gda-approval-case-operations` 的只读 Grafana 看板包含 10 个运营面板/11 个 PromQL 查询，datasource URL
  仅由环境注入；Kustomize 从同一 JSON 生成 sidecar 可发现的 ConfigMap。Prometheus 3.5.0 的 recording/告警
  数值测试全部通过，真实 Grafana 11.6.0 已通过 datasource health、search、dashboard、folder 和 provisioning
  API 验收，全部一次性容器与网络已清理。这是本地真实二进制证据，不代表 Docker Desktop 或
  staging/production 已部署 Grafana sidecar、长期存储、企业认证/TLS、paging escalation 或多集群聚合。
- [x] 通用 SLODefinitionVersion 权威首个纵向切片已按
  [ADR-146](architecture-decisions/adr-146-versioned-slo-definition-approval-authority.md) 落地：迁移 122 建立
  tenant-scoped 不可变 definition version、CAS active pointer 和不可修改事件，PostgreSQL 对规范化 JSONB
  自行计算 SHA-256；激活必须绑定同租户、action=`slo_definition.activate`、target ResourceURN/fingerprint
  完全一致且未过期的 approved ApprovalCase，candidate/pending/rejected/错 action/错 fingerprint 全部
  fail closed。首个 `event_success_ratio` 编译器仅接受 exact active version，生成带最小流量门的多窗口
  error-budget burn rules。一次性 PostgreSQL 16.14 + Prometheus 3.5.0 认证 21/21 通过，并在首次演练中发现
  和修复 `ON CONFLICT DO NOTHING` 的 NULL 幂等事件缺陷。`/api/platform/v1/slo-definitions` 已补齐受认证
  生命周期 API：服务端注入 tenant/actor/time，提供不可变候选入库与有界分页、精确版本审批申请、admin-only
  CAS 激活、active pointer、active-only Prometheus 规则预览及事件审计；候选版本规则预览 fail closed，路由和
  OpenAPI 契约共新增 7 条。认证用 99% 仅为 disposable test data；仓库没有擅自批准或部署 production SLO，
  UI、retire 和规则 rollout/rollback 仍待完成。
- [x] 获批 SLO 告警到统一 DataIncident 的闭环已按
  [ADR-147](architecture-decisions/adr-147-approved-slo-alert-to-resource-bound-data-incident.md) 落地：迁移 123
  将事故主体扩展为 `run_id` 与 canonical `subject_resource_urn` 恰好二选一，保留原 Run 事故 fingerprint，
  并复用既有 CAS 状态、顺序 IncidentEvent 和事务性通知 outbox。受认证的
  `POST /api/platform/v1/slo-alerts/alertmanager` 只允许配置的 workload identity，拒绝 truncated delivery，
  并逐项核对 SLO version/fingerprint、service/owner/on-call、burn window/severity 和 ApprovalCase。firing 必须
  对应 exact active pointer；resolved 可凭 immutable activation event 关闭历史获批 episode；Alertmanager
  fingerprint 与 `startsAt` 共同保证重放幂等且新一轮告警不复用已关闭事故。一次性 PostgreSQL 16.14 认证
  11/11 通过，最终事故为 resolved，生成 2 条事件和 2 条通知任务，并验证主体约束/不可变和双租户 RLS。
  当前证据不代表 staging/production inbound TLS/认证、receiver、paging 或多集群交付已验收。
- [x] 首个参考主数据权威纵向切片已按
  [ADR-148](architecture-decisions/adr-148-approval-gated-reference-master-golden-record-authority.md) 落地：迁移 124
  建立 tenant-scoped 不可变 source revision、AI 只读 match candidate、entity version、active golden pointer
  和 append-only event。`master-match-v1` 只根据业务键、规范化名称和真实 active parent business key 生成可解释
  候选；激活必须绑定 action=`master_data.entity.activate` 的未过期 approved ApprovalCase、精确
  ResourceURN/fingerprint 和 activation CAS，并由数据库强制 active business-key 唯一、层级环检测、RLS、不可变
  trigger 与 gateway 无直接写权限。平台 API 已提供 source observation、machine matching、version stage/list、
  approval、activation、active 和 events 共 8 个操作。一次性 PostgreSQL 16.14 认证脚本
  `scripts/certify_master_data_lifecycle.py` 的 18 项检查全部通过，报告确认 v2 active、双 source revision、
  精确审批、重放幂等、双租户隔离和容器清理。当前不等于完整企业 MDM，不包含 merge/split survivorship、批量层级
  变更、大规模实体解析、黄金记录多渠道分发或 staging/production 验收。
- [x] 主数据激活已按
  [ADR-149](architecture-decisions/adr-149-atomic-master-resource-version-projection.md) 接入平台通用身份：迁移 125
  在同一激活事务内校验 exact master version/fingerprint，登记 `Resource`，生成确定性
  `ResourceVersion`，并追加不可变 `master_resource_projection`；任何既存 Resource/ResourceVersion 证据冲突
  都使 active pointer、projection 和 activation event 整体回滚。新增只读分页 API
  `GET /api/platform/v1/master-data/entities/{entity_id}/resource-projections`，平台路由总数为 56；投影表强制
  RLS、gateway 仅 SELECT。一次性 PostgreSQL 16.14 的扩展认证 28/28 通过，覆盖 v1/v2 predecessor、确定性
  ID 重放、精确 content hash/authority evidence、OpenMetadata governance crosswalk 可登记、不可变性、双租户和
  冲突回滚。该 crosswalk 本身不表示 OpenMetadata glossary term 已创建；真实 provider 投影证据由下述
  ADR-150 隔离验收提供。Gravitino 绑定必须等待真实 PostGIS/Iceberg 技术对象，EA round-trip、黄金记录
  多渠道分发和 staging/production 验收仍未完成。
- [x] 主数据到 Metadata Fabric 的 durable delivery 合同已按
  [ADR-150](architecture-decisions/adr-150-leased-master-metadata-glossary-projection.md) 落地：迁移 126 以
  `master_resource_projection` 的 AFTER INSERT trigger 在激活事务内写入强类型
  `master_metadata_projection_outbox`，通过复合外键精确绑定 entity、activation、ResourceVersion 和
  fingerprint；独立 lease/complete/fail 函数提供 bounded retry/dead-letter，gateway 无直接写权限。
  `openmetadata_master_data_worker` 只接受显式 canonical UUID `glossaryTerm` binding，执行
  `GET -> minimal JSON PATCH(displayName/description only) -> GET`，超时后也必须读回精确确认；缺失、陈旧、删除、
  类型或 glossary namespace 错配都保持 retryable，不从名称/FQN 猜身份。可选 Compose
  `metadata-fabric` profile 已增加独立 worker。合同/API/网关/迁移聚焦回归 139 项通过，一次性 PostgreSQL 16.14 认证
  32/32 通过。版本固定的真实 OpenMetadata 1.13.1 验收已用 provider 返回的 glossary/term UUID 完成
  `GET -> PATCH -> GET`、已提交 PATCH 响应丢失后的 GET 对账、GET-only 幂等重放、唯一 term、未认证 401、
  outbox `done/attempt_count=1` 及 term/glossary hard-delete 后 404；无秘密报告位于
  `.tmp/metadata-fabric/openmetadata-master-data-acceptance-report.json`。该证据只将已显式绑定 term 的
  `displayName/description` 投影标记为 operational；产品化 term provisioning/binding、层级/owner/tag/status、
  OpenMetadata production foundation、Gravitino、EA round-trip 和 staging/production 仍未完成。
- [x] 数据指标 canonical write authority 首个纵向切片已按
  [ADR-151](architecture-decisions/adr-151-canonical-versioned-metric-definition-authority.md) 落地：迁移 135
  建立 tenant-scoped 不可变 `MetricDefinitionVersion`、CAS active pointer 和 append-only event，统一承载
  指标 identity/version、`semantic_expression_v1`、单位与聚合语义、时间/空间粒度、CRS、measure binding、
  quality/materialization policy 和 dependency DAG。每个 source binding 必须精确命中既有
  `DataProductVersion`；发布必须绑定 action=`metric_definition.activate`、target ResourceURN/fingerprint
  完全一致且未过期的 approved ApprovalCase，所有依赖也必须在精确版本 active。gateway 无直接写权限，
  三张表强制 RLS；平台新增 stage/list、approval、admin activation、active、events 和 active-only resolution
  共 7 个 API 操作，canonical/display/alias 歧义 fail closed。聚焦契约测试 8/8 通过；一次性 PostgreSQL
  16.14 认证 16/16 通过，覆盖真实 DataProductVersion 绑定、幂等、错误审批、依赖门、解析、不可变、最小权限
  和双租户隔离，容器已清理。旧 `agent_semantic_metrics`、YAML、OSSIE、MMFE 和 GWM/TWM 指标仍是待迁移
  projection；不可变 SemanticModelVersion、Metric Query Compiler、Gold 自动物化/缓存、MetricObservation、
  异常归因、UI 以及 staging/production 验收尚未完成。
- [x] 指标的 version-bound Gold/Serving projection 和确定性查询路由首个纵向切片已按
  [ADR-152](architecture-decisions/adr-152-version-bound-metric-projections-and-deterministic-query-routing.md)
  落地：迁移 136 建立不可变 `MetricProjectionVersion`、CAS active pointer 和 append-only event，精确绑定
  active MetricDefinitionVersion、passed DataProductVersion、输出 ResourceVersion、manifest SHA-256、物理
  snapshot、引擎/层级、维度/时间/空间 grain 与观测延迟。`MetricQueryPlanner` 不接受 LLM SQL，只生成结构化
  `gda.metric_query_plan.v1`；可加指标允许安全 rollup，半可加/不可加、staleness、CRS、同步扫描上限和 latency
  不满足时 fail closed，受控大扫描改走 Iceberg+Spark async，Serving 优先于 Interactive/Gold/Batch。cache key
  已包含 metric/projection/product/output/manifest/snapshot/query/tenant/subject/role/purpose 全部证据。平台新增
  projection stage/list/activate/events、active projection 和 query-plan 共 6 个 API 操作；聚焦指标测试 16/16、
  一次性 PostgreSQL 16.14 认证 17/17 通过，覆盖 CAS、不可变、最小权限和双租户 RLS，容器已清理。当前只完成
  可审计 planning，不等于 SQL/Spark 执行、Gold 自动物化、分布式结果缓存、MetricObservation、智能归因、UI、
  容量 benchmark 或 staging/production 验收；无实测 SLO 缺口前不引入 Trino/ClickHouse/Doris/StarRocks。
- [x] 指标查询已按
  [ADR-153](architecture-decisions/adr-153-metric-query-platform-run-admission-and-provider-receipts.md)
  接入统一执行证据面：迁移 137 建立基础协议，迁移 138 在不改历史文件的前提下收紧 provider replay，二者与
  `MetricQueryExecutionAuthority` 共同复用
  `PlatformDefinitionVersion/PlatformRun/FrameworkAttemptObservation/Artifact`，由服务端重新规划后，在单一事务
  内原子创建 Run、exact metric-source input binding、execution-plan Artifact 和不可变 admission；PostGIS/DuckDB
  同步定义使用 `synchronous`，Iceberg+Spark 异步定义使用 `dataops`，没有另建 query job/scheduler。provider 必须以
  platform workload 身份分别提交 start 与 terminal receipt；成功绑定 credential-free、content-hashed 结果 Artifact，
  失败只绑定 error，cache hit/miss/bypass、rows/bytes scanned 和 duration 均进入不可变 observation，改变 replay、
  错 start、CAS 冲突和失效 projection 全部 fail closed，provider manifest 不能覆盖平台保留证据。平台新增 run
  admit/get/start/complete 共 4 个 API，指标路由总数为 17；聚焦执行/规划测试 23/23、一次性 PostgreSQL 16.14
  认证 17/17 通过，覆盖原子性、同步成功、异步失败、幂等/冲突、RLS、不可变和最小权限，容器已清理。该切片只
  完成 execution admission/receipt protocol，尚未真实执行 SQL、提交 Spark、建立 dispatch/outbox、cancel/reconcile、
  分布式结果缓存、业务 `MetricObservation`、智能归因、容量 benchmark 或 staging/production 验收。
- [x] 指标查询可靠派发与首个真实 PostGIS provider 已按
  [ADR-154](architecture-decisions/adr-154-metric-query-command-outbox-and-postgis-provider.md)
  落地：迁移 139 将 `metric_query.execute` 纳入统一 `PlatformCommand` transactional outbox，admission 与稳定
  command ID/dedupe/payload 同事务提交，并按 PostGIS、DuckDB、Iceberg/Spark 隔离 workload identity；start/terminal
  receipt 必须命中 canonical command，复制 payload 但伪造 UUID/dedupe 的命令不能授权执行。消费者复用既有
  claim lease、owner 校验、指数退避和过期接管，delivery attempt 与固定 query attempt 1 分离；临时 provider 故障
  回到 outbox，耗尽前先写 query failure receipt，Run 已终态但 command 未确认时重领只完成 command、不重复查询。
  PostGIS provider 不接受 SQL，只编译结构化 plan，identifier validation/quoting、参数绑定、只读事务、statement
  timeout、结果行上限和受控时空谓词均 fail closed；结果以原子 rename 写 canonical JSON，并把 content SHA-256、
  logical rows/`pg_column_size` bytes 和 read-only evidence 绑定到 Artifact。聚焦指标测试 29/29、一次性 PostgreSQL
  16.4 + PostGIS 认证 15/15 通过，真实 EPSG:4490 `centroid_within` 查询返回并记录预期 2 行，137/138/139 同时通过
  迁移认证且容器已清理；139 复用 138 的严格 receipt 实现且未修改历史文件。当前不宣称
  DuckDB/Spark provider、分布式缓存、cancel/reconcile、worker 生产部署、业务 `MetricObservation`、智能归因、容量
  benchmark 或 staging/production 验收完成。
- [x] PostGIS 指标查询 consumer 已按
  [ADR-155](architecture-decisions/adr-155-managed-metric-query-command-worker.md)
  形成 tenant-scoped managed worker：平台控制账本继续使用既有 runtime connection，serving provider 只从
  owner-only secret file 读取独立 PostgreSQL URL，URL user 必须等于声明的 governed database role，live probe
  拒绝 superuser 或 `gda_control_gateway` 成员，配置摘要、日志和 mode-`0600` 原子状态文件不包含 DSN/密码；
  每轮在领取 lease 前先以有界 connect timeout 建立只读事务并验证 PostGIS，provider 或 Gateway 不可用时进入
  `degraded` 且 readiness fail closed，fresh degraded 仍保持 liveness，命令级查询失败则作为受治理结果计数而不误报
  进程故障。lease 必须覆盖 execution reconnect 和 evidence/result 两条 statement timeout，健康窗口还必须覆盖
  probe/execute 两次连接、三条有界 statement 和两个 poll；进程支持
  `validate/run --once/health/liveness`、SIGINT/SIGTERM 当前批次后停机及稳定 package entry point。worker 单测
  12/12，Artifact 文件系统故障会形成脱敏 transient provider error 并返回 outbox，而不是让进程崩溃；全部指标
  聚焦回归 50/50、共享 control-plane 回归 178 passed/2 个未配置专用 DSN 用例 skipped，Ruff/编译/入口/diff check
  均通过；一次性 PostgreSQL 16.4 + PostGIS 认证
  18/18，通过真实 EPSG:4490 查询验证双 engine 边界、read-only probe、ready/liveness、状态权限/脱敏；专用
  provider role 只拥有源表 `SELECT`，没有 `INSERT`、superuser、create database/role 或平台 gateway membership，
  同时保留 outbox retry/recovery、伪造命令拒绝和双租户 RLS，容器已清理。当前只完成可部署进程合同和 disposable backend
  认证，尚未完成 orchestrator secret ownership、staging/production rollout、容量/并发 SLO、分布式缓存、cancel/
  reconcile、业务 `MetricObservation`、智能归因或 DuckDB/Spark provider。
- [x] PostGIS 指标查询 worker 的首个 Kubernetes 部署合同已按
  [ADR-156](architecture-decisions/adr-156-optional-kubernetes-metric-query-worker-profile.md)
  作为独立可选 Kustomize package 落地，未加入默认 `k8s/base`：pod/init/worker 固定非 root UID/GID 10001、
  `RuntimeDefault` seccomp、只读根文件系统、drop ALL capabilities、禁止 privilege escalation 和 ServiceAccount
  token；原始 projected provider Secret 只挂给 init，由非 root materializer 原子复制到 memory `emptyDir`，并验证
  当前 UID ownership 与 mode-`0400`，主进程只看到 owner-scoped 副本且禁用 control DB admin credential fallback。
  startup/readiness/liveness 分别复用 worker 本地 liveness/health 语义，NetworkPolicy 将 worker ingress 置空、egress
  限于 cluster DNS 和同 namespace PostgreSQL，并以策略并集补充 PostgreSQL 入站许可。当前因结果仍是
  PVC-backed `file://` Artifact，Deployment 固定单副本、`Recreate` 和 RWO 10Gi；离线部署/安全测试 8/8、worker
  `degraded -> ready` 恢复和共享 control-plane 回归 187 passed/2 个未配置专用 DSN 用例 skipped，Ruff、编译、
  shell 语法与 diff check 均通过，`kubectl kustomize` 可离线渲染。该切片只完成 deployment contract，未对任何
  集群 rollout，也不代表 NetworkPolicy 实际执行、secret rotation、backup/restore、容量/SLO 或 staging/production
  验收；生产横向扩展前必须先落集群可访问的 object-store Artifact backend。
- [x] 指标查询结果已按
  [ADR-157](architecture-decisions/adr-157-immutable-object-store-metric-query-results.md)
  从 worker PVC 升级为可替换的 immutable result-store contract：轻量/一次性 profile 保留本地 write-once
  backend，默认 lakehouse profile 使用确定性
  `s3://bucket/prefix/{tenant_id}/{run_id}.json`，以 `If-None-Match: *` 条件创建并在成功或竞争后逐字节读回，
  size/SHA-256 必须匹配 canonical JSON；同内容重放返回同 URI，不同内容不覆盖并形成 terminal contract error，
  transport/auth/availability 则脱敏后返回现有 `PlatformCommand` 重试。worker 配置禁止 local/S3 双重绑定，S3
  endpoint/credential 不进入 Artifact、状态或安全摘要，lease/health budget 纳入 bucket probe、put 和 read-back，
  每轮领取 command 前同时探测 PostGIS 与结果 bucket。可选 Kubernetes profile 已移除结果 PVC，改用独立 bucket
  与专用 S3 Secret keys，egress 只新增同 namespace MinIO:9000；仍保持单副本 `Recreate`，不提前宣称容量能力。
  result-store/provider/worker/deployment 聚焦测试 44/44、共享回归 203 passed/2 个未配置专用 DSN 用例 skipped；
  一次性 MinIO `RELEASE.2025-04-22T22-12-26Z` 认证现已由 ADR-159 扩展到 17/17，通过 version/ETag 捕获、条件创建、
  重放、冲突拒绝、精确版本读回、默认 governance retention、SHA metadata、prefix 外写入拒绝、删除/retention
  bypass 拒绝及清理验证，随机 bucket/container 已删除且报告无 runtime secret。当前未执行 Kubernetes rollout，
  也未完成云对象存储 portability、credential rotation、
  backup/restore、多副本容量/SLO、结果读取 API、分布式缓存、cancel、业务 `MetricObservation` 或智能归因。
- [x] 指标查询结果访问已按
  [ADR-158](architecture-decisions/adr-158-governed-metric-query-result-access.md)
  接入统一治理边界：新增 `POST /api/platform/v1/metric-query-runs/{run_id}/result-access`，只允许 Run
  submitter 或 `admin/platform_operator` 在同租户读取 succeeded Run 精确绑定的 result Artifact；服务端同时核对
  Artifact 的 tenant/Run/role/key、plan/cache/execution evidence、HEAD size/media type/SHA metadata，并在每次签发前
  流式重算对象实际字节 SHA-256，metadata 或同长度内容篡改均 fail closed。通过验证后只签发 60-900 秒 SigV4
  GET capability，响应不包含稳定 `s3://` URI、SDK 配置或长期 secret，并设置 `no-store/no-cache`；API 可分离
  内部 verification endpoint 与调用方可达 signing endpoint，使用独立 prefix-scoped reader/workload identity。
  每个成功 grant 必须先写现有 tenant-scoped immutable `SecurityEventLedger`，审计只记录 actor/role、access/Run/
  Artifact ID、TTL、media/size/hash，不记录签名 URL 或存储 URI；账本不可用则不披露 URL，非 owner、未知 Run 和
  未完成结果保持拒绝。聚焦访问/执行/规划/存储测试 54/54；一次性 MinIO
  `RELEASE.2025-04-22T22-12-26Z` 认证现已由 ADR-159 扩展到 16/16，真实验证版本锁定签名读取、供应商签名过期、
  TTL/租户 key 约束、current version 覆盖后旧 Artifact 仍返回原字节、reader 写删拒绝和资源清理；共享
  Gateway/security-ledger/platform-contract 回归 214 passed、2 个
  未配置专用 DSN 用例 skipped，Ruff/编译/diff check 通过。当前仍未执行 Kubernetes/云 rollout，也未完成 public S3 endpoint/
  workload identity rotation、生产 retention/lifecycle 审批、backup/restore、访问容量/SLO、签名即时撤销、
  provider 实际 GET access-log 对账、大结果 checksum 优化、分布式缓存、结果级 ABAC、业务
  `MetricObservation` 或智能归因。
- [x] 指标查询结果的校验到下载竞态已按
  [ADR-159](architecture-decisions/adr-159-version-locked-metric-query-result-publication.md)
  关闭：`MetricQueryResultStore` 现在返回含稳定 URI、backend、非空 `VersionId` 和 ETag 的 publication receipt，
  PostGIS provider 将 `gda.s3_object_version.v1` 证据固化到现有 Artifact manifest，不新增数据库迁移；worker 在
  领取 command 前强制 bucket versioning `Enabled`、Object Lock `Enabled` 和正数默认
  `GOVERNANCE/COMPLIANCE` retention，缺任一合同即 readiness fail closed。Result Access 对 manifest 版本证据
  strict parse，HEAD、逐字节 GET 和 SigV4 URL 全部带同一 `VersionId`，并核对返回 version/ETag、size/media/SHA；
  stable key 即使随后产生不同 current version，旧 Artifact 仍只能下载原版本。writer 只增加 bucket versioning/
  lock configuration 读取能力且无删除/retention bypass，reader 只有 prefix-scoped `GetObject/GetObjectVersion`。
  聚焦 store/provider/worker/access 测试 65/65，指标链路与共享 Gateway/Artifact/security-ledger 回归 215/215，
  Ruff、编译和 diff check 通过；一次性 MinIO writer 认证 17/17、
  access 认证 16/16，均确认 version lock、最小权限与 bucket/container 清理。该证据不是 Kubernetes/staging/
  production rollout；生产 retention/lifecycle、backup/restore、workload identity rotation、容量/SLO、签名即时
  撤销和 provider GET access-log 对账仍未完成。
- [ ] Inbox 仍需接入发布、数据申请、敏感操作和模型/规则变更，补齐企业目录/on-call 同步、替班/超时升级/自动回收、
  staging/production 实际部署和企业 paging 演练、长期存储、跨 case/incident 运营视图和
  批量升级流程；不以聊天 HITL 替代正式流程。
- 血缘影响分析、质量趋势、消费审计、SLA 和 retention/archive。
- [x] 过渡态分类分级与空间脱敏入口已收紧服务端安全边界：分类总览只返回本人、共享或管理员
  可见资产；analyst/admin 脱敏和逆向验证必须先解析为可访问的 PostGIS 目录资产，危险 identifier
  在进入数据库前拒绝，输出表已存在时返回冲突且核心执行不再 `DROP TABLE`。成功、失败、拒绝写入
  现有运营审计。迁移 109 对统一资产表启用并强制 RLS，拆分 SELECT/INSERT/UPDATE/DELETE 策略，
  共享资产只读。详细边界见 [ADR-123](architecture-decisions/adr-123-spatial-anonymization-security-boundary.md)。
  该入口边界不单独代表 AR-3、AR-4 或下一代 Data Platform 完成。
- [x] 空间脱敏和逆向验证已增加租户内不可变安全事件链：拒绝请求尽力写 `denied`；全部检查通过后
  必须先写 `admitted`，写入失败则返回 503 且不启动空间操作；执行完成或异常后写 `outcome`，结果
  证据写入失败返回稳定的 `security_evidence_incomplete` 和 attempt ID。迁移 110 复用现有
  `gda_control` 和最小权限 gateway role，以租户序号、前序 SHA-256、强制 RLS、幂等键和不可修改
  trigger 提供可验证证据；一次性 PostgreSQL 16 的 17 项认证覆盖双租户隔离、幂等/冲突、连续哈希、
  直接增删改拒绝及高权限篡改检测，脚本为 `scripts/certify_immutable_security_event_ledger.py`。详细取舍见
  [ADR-124](architecture-decisions/adr-124-immutable-security-event-admission-ledger.md)。空间 DDL 与 outcome
  尚非同一事务，超级管理员仍可停用 trigger，外部 hash anchor/WORM、字段加密、tenant/purpose/
  column/row/spatial/temporal policy 和统一发布安全门仍未完成；AR-3、AR-4 状态不变。
- [x] 已补齐“空间脱敏完成但 outcome 写入失败”的确定性对账切片：迁移 111 在现有 `gda_control`
  中增加租户隔离、不可修改、带 SHA-256 指纹的操作完成回执；数据库写回执前重新验证同 attempt 的
  admission、resource、输出表、实际行数和有效 GiST 索引。管理员 API 和外部调度可调用的 CLI 只会
  对单个、证据完全匹配的 `data_anonymize` attempt 补写 success outcome；回执缺失/错配和无持久结果的
  逆向验证继续进入人工复核。一次性 PostgreSQL 16 的 14 项认证覆盖真实 12 行表、真实 GiST、幂等、
  双租户隔离、链和回执指纹验证，脚本为 `scripts/certify_security_event_reconciliation.py`。详细取舍见
  [ADR-125](architecture-decisions/adr-125-immutable-security-operation-receipt-reconciliation.md)。DDL、回执和
  outcome 仍非同一事务，超级管理员仍在共同信任边界；完整安全生命周期、AR-3、AR-4 状态不变。
- [x] 空间脱敏输出与完成回执已收束为同一 PostgreSQL 事务：polygon/point 的建表、差分隐私更新、
  输出统计、GiST 索引和受控回执不再中途提交；回执校验或写入失败会回滚整个输出，目录血缘只在事务
  成功后做 best-effort 投影。PostgreSQL 16 对账认证扩展为 17 项，并新增真实
  `postgis/postgis:16-3.4` 的 15 项认证，实际覆盖 polygon/point `ST_SquareGrid`、GiST、回执、outcome
  对账以及 resource 错配时输出表和回执均不残留，脚本为
  `scripts/certify_atomic_spatial_anonymization.py`。详细取舍见
  [ADR-126](architecture-decisions/adr-126-atomic-spatial-output-and-security-receipt.md)。outcome 仍是后续
  独立事务并由 ADR-125 对账；异步状态、自动 provider retry/cancel 和 DolphinScheduler/Temporal 正式
  Run 尚未接入，因此完整安全生命周期、AR-3、AR-4 状态不变。
- [x] 空间脱敏已完成统一 DataOps Run 的原子准入切片：新增异步
  `/api/classification/anonymize/submit`，将源/输出、point/polygon、等级、字段、k 值和差分隐私参数固化
  为不可变 request `ResourceVersion`；Gateway 在一个事务内写 request、invocation、policy Artifact、
  PlatformRun 和 DolphinScheduler dispatch outbox。同 tenant/client request ID 并发重放只产生一套对象，
  载荷漂移返回 conflict 且不留下第二个版本；隔离 PostgreSQL 16 已通过真实 advisory lock、RLS/外键和
  并发双提交集成测试。提交阶段不执行 PostGIS，也不提前写执行 `admitted` 安全事件。详见
  [ADR-127](architecture-decisions/adr-127-governed-spatial-anonymization-run-admission.md)。Run 终态收敛、
  retry/cancel 和正式 source snapshot binding 尚未完成，因此完整安全生命周期、AR-3、AR-4 状态不变。
- [x] 空间脱敏正式 Run 已增加确定性 Worker：调度入口只接收 tenant/Run ID，并仅从不可变 request
  binding 读取执行参数；Run 派生稳定安全 attempt，tenant/attempt advisory lock 拒绝重叠 worker。
  首次执行写 `admitted`，真实 PostGIS 操作原子提交输出、GiST 和回执后再写 success outcome；重放发现
  回执时只对账 outcome，不重复脱敏。临时 `postgis/postgis:16-3.4` 的 `13/13` 认证已覆盖真实 polygon
  输出、事件/回执完整性、恢复、并发互斥、漂移冲突和一套 request/Run/command，脚本为
  `scripts/certify_spatial_anonymization_run_worker.py`。详见
  [ADR-128](architecture-decisions/adr-128-deterministic-spatial-anonymization-run-worker.md)。Run 成功证据门、
  retry/cancel 仍未完成；完整安全生命周期、AR-3、AR-4 状态不变。
- [x] 空间脱敏 Run 已接通真实 DolphinScheduler 3.4.2 provider：版本化 SHELL definition 和带 Bearer
  认证的 typed executor 只传 tenant/Run ID，provider 不保存源/输出、等级、字段、k 值或差分隐私参数；
  outbox consumer 创建真实 process instance 并把 dispatch/success observation 写回同一 Run。隔离 PostGIS
  认证 `16/16` 通过，workflow `180506926715456` / instance `18` 为 `SUCCESS`，输出、GiST、回执、
  安全链、重放与精确 correlation 全部成立；Run 仍按证据门停在 `reconciling`。脚本为
  `scripts/certify_spatial_anonymization_dolphinscheduler.py`，详见
  [ADR-129](architecture-decisions/adr-129-real-dolphinscheduler-spatial-anonymization-provider.md)。production
  provider/网络/secret/SLO 认证、输出 ResourceVersion/Artifact、独立质量、输入到输出血缘以及
  retry/cancel 仍未完成；完整安全生命周期、AR-3、AR-4 状态不变。

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
- [x] 过渡态只读资产运营详情已接入现有 Catalog：以确定性规则汇总 owner、描述/分类、
  CRS、敏感级别、许可、质量证据、访问/评分、版本、申请和血缘，展示生命周期阶段、发布
  准备度及阻塞项，并修复旧/新目录 API 字段口径不一致。该兼容投影不写入新的状态真值，
  不替代 OpenMetadata/Gravitino metadata fabric、DataProductVersion 或 Service Control Plane；
  因此不改变 AR-0 `in_progress` 与 AR-4 `planned` 状态。
- [x] 现有 Catalog 详情已接通分发申请闭环：普通用户可提交用途并查看本人最新状态，管理员
  只在当前资产内查看、批准或带原因驳回待办；重复待审批申请幂等返回，资产 RLS、责任人约束
  和角色可见性由服务端执行。该过渡流程继续复用 `agent_data_requests`；后续 105-107 已补期限、
  版本、撤销和离线包次数额度，但仍不是带服务版本范围、credential 与 compatibility 的正式
  `ConsumerBinding`，因此不代表 AR-4.1 或 AR-4 完成。
- [x] 资产级分发申请已扩展为有界离线分发授权：申请记录固化用途、`download` operation 和
  1-365 天期限，独立管理员批准后生成活跃授权，过期自动失去新建分发包权限；本地文件打包
  在服务端逐资产校验 RLS、责任人/管理员或有效授权。该迁移 105 兼容合同是后续版本锁定与撤销
  的基线，不单独代表 `ConsumerBinding`、AR-4.1 或 AR-4 完成。
- [x] 分发授权已增加可验证的精确产品版本快照和可执行撤销：Catalog 继续通过既有
  `operational_metadata.publication.data_product_urn` 声明产品，审批时由治理注册表校验并锁定当时
  active `DataProductVersion`，复合外键防止伪造版本；管理员可查看有效授权、填写原因撤销，打包和
  下载都拒绝已撤销/过期授权，相关已生成包同步失效并尽力清理。ZIP 内含授权/版本 manifest，新包
  只走受控下载接口；无产品声明的旧资产明确保留为 `asset_compatibility`。详细边界见
  [ADR-121](architecture-decisions/adr-121-version-locked-revocable-asset-distribution.md)。当前交付仍来自
  Catalog 本地文件，不是远端 `DataProductVersion` Artifact；服务级 Service version range、服务级
  quota、通知/迁移窗口和 Service Control Plane binding 仍未完成。产品级 promotion 影响分析与正式
  `ConsumerBinding` authority 已在后续迁移 149 完成一条可验证切片，AR-4.1 与 AR-4 状态不变。
- [x] 过渡分发授权已增加可执行的离线包次数额度：申请声明 1-100 次额度，审批固化批准额度；普通用户
  打包时锁定授权行并在锁后统计历史 package，最后一次额度只能被一个并发请求消费，耗尽后 API 返回
  稳定的 `quota_exhausted` / HTTP 409。Catalog 显示申请额度和“已用 / 总额 / 剩余”，耗尽后关闭打包
  并开放“申请追加额度”；ZIP manifest 记录消费前后额度证据。迁移 107 不返还已撤销包的历史消耗。
  这只是版本锁定过渡授权的 package-count quota，不是服务 rate/capacity/cost quota，也不是正式
  `ConsumerBinding`；AR-4.1 与 AR-4 状态保持不变。详细边界见 [ADR-121](architecture-decisions/adr-121-version-locked-revocable-asset-distribution.md)。
- [x] `DataProductVersion` 前向切换已增加过渡消费者影响门：新版本发布时若旧 active 版本仍有有效
  分发授权，新版本只登记为 `staged`，active pointer 保持不变；管理员可预览 consumer、锁定版本、
  到期时间和离线包剩余额度，并必须提交最新影响指纹才能 promotion。分发审批与 promotion 共用产品级
  事务锁，因此新批准授权会使旧确认失效；staged 与 promoted 事件均引用不可变影响快照。迁移 108 已在
  一次性 PostgreSQL 16 完成双消费者、陈旧确认拒绝、精确确认切换、跨租户隔离和不可篡改验证，认证脚本为
  `scripts/certify_data_product_promotion_impact.py`。这仍以版本锁定分发授权作为过渡消费证据，未提供通知、
  Service version range、服务级 quota、通知/迁移 acknowledgement，紧急 rollback 也尚未进入
  相同确认门；AR-4.1 与 AR-4 状态不变。详细边界见
  [ADR-122](architecture-decisions/adr-122-consumer-aware-data-product-promotion.md)。
- [x] 已补正式产品消费者 authority：迁移 149 的 append-only `consumer_binding` 以 Product FK、
  Product version range、credential reference、quota、expiry 和 compatibility evidence 固化不可变
  binding；gateway 只可调用 SECURITY DEFINER recorder，tenant RLS/直接 SQL `INSERT` 拒绝已在一次性
  PostgreSQL 16 验证。promotion impact 优先读取有效 formal binding，并输出 v2 binding evidence；正式
  authority 不可用或无记录时才回退迁移 108 的过渡 grant。23 个聚焦测试通过，认证入口为
  `scripts/certify_consumer_binding_authority.py`，报告 SHA-256 为
  `e8c20456490cf808b6b68a41139b17a5b36d8c53c830fc9e2286b1a00c6f9a53`，详见
  [ADR-177](architecture-decisions/adr-177-formal-consumer-binding-authority.md) 和
  [ConsumerBinding handoff](handoffs/2026-08-07-consumer-binding-authority.md)。该切片不包含通知、
  迁移 acknowledgement、DataSLO/DataIncident、incident-bound rollback、服务级 binding 或任何生产
  HA/RPO/RTO，因此 AR-0/AR-1/AR-2 状态不变。
- [x] 正式消费者迁移状态已接入产品 promotion：迁移 150 的 append-only
  `consumer_binding_migration_state` 按 ProductVersion from/to 绑定兼容性结论、通知状态与 evidence、
  migration deadline 和 typed consumer acknowledgement；previous state SHA-256 CAS、不可变触发器、
  tenant RLS、直接 SQL 绕过拒绝以及 ConsumerBinding recorder/promotion 共用产品 advisory lock。
  impact 升级为 `gda.data_product_promotion_impact.v3`，状态/通知/截止时间/ack 任一变化都会使旧
  fingerprint 失效；缺状态、indeterminate compatibility、breaking 通知未送达或 consumer 未确认时
  promotion fail closed。27 个聚焦 contract/registry 测试通过，一次性 PostgreSQL 16 认证覆盖三次
  state snapshot、幂等重放、旧指纹拒绝、最新 acknowledgement promotion 和跨租户零行，报告为
  `.tmp/consumer-binding-certification-v2/report.json`，SHA-256 为
  `323a250f508ca92166ffd13f95c5ad24bf42c2143ab863bddb65ef7b4feb6b4b`；migration catalog 为 150 条，
  fingerprint 为 `48e8ac86ff38ac3cf6c3aa255a9f60930007d8641e8f95a206869eddf024cb8e`。该切片仍不等于生产通知 provider/outbox、
  DataSLO/DataIncident、incident-bound rollback、Service Control Plane 服务级 binding 或生产
  HA/RPO/RTO；AR-0/AR-1/AR-2 及 AR-4.1/AR-4 总体退出门保持未完成。
- [x] DataProduct rollback 已进入统一 authority 门：迁移 151 在不可变 rollback event 上记录
  `incident` 或 `approval_case` 的引用与 SHA-256 证据；新 rollback 必须绑定当前产品的 active
  resource-bound DataIncident，或绑定未过期、独立 human-approved 的
  `data_product.rollback` ApprovalCase，且 ApprovalCase fingerprint 精确覆盖 current/target
  ancestor 操作。registry 在现有产品 advisory lock 内完成 authority 校验、pointer flip 和 event
  写入；数据库 trigger 要求 recorder session marker 并拒绝直接 SQL rollback insert，幂等 replay
  必须复用同一 authority。77 个 product/consumer/architecture release/migration/platform contract
  回归测试通过；一次性
  PostgreSQL 16 认证覆盖 Incident rollback、human ApprovalCase rollback、不可变 authority evidence
  和直接 SQL 绕过拒绝，报告为 `.tmp/data-product-rollback-certification/report.json`，SHA-256 为
  `5cc2d817ca3ef93e16ac5e5f5cadc54a2631851a1d49bc4a9bf2c005fdfb81ae`。migration catalog 为 151 条，
  fingerprint 为 `60bee34db38f6f52ed6c327059ea8e7c3f46a06001ecc9a1d59f04f86cbb4a0f`。该切片不包含生产通知
  provider、GIS Service Control Plane 服务级 binding、HA/RPO/RTO 或 AR-4 总体退出门。
- [x] ConsumerBinding migration notification 已从人工 evidence 升级为 durable provider receipt：迁移
  152 的 tenant-scoped outbox 在 pending migration state 同事务 enqueue，精确绑定 binding、from/to
  ProductVersion 和 source state SHA-256；claim 使用 `FOR UPDATE SKIP LOCKED`、lease、retry、10 次默认
  dead-letter 和 stale pending supersede。done/failed receipt 由数据库生成 SHA-256，terminal migration
  evidence 只能引用 `notification_id + receipt_sha256`，recorder 会复算 receipt 并拒绝任意人工
  delivered/failed JSON。Gateway 在同一事务 terminalize outbox 并追加 deterministic CAS successor，
  Alertmanager worker 使用 server-owned URL/token/route namespace、metrics、signal shutdown 和 Compose
  `alerts` profile。197 个跨模块测试通过、1 个既有测试跳过；PostgreSQL 16 一次性认证覆盖成功投递、
  伪造 receipt forbidden、ack 后 promotion、10 次失败 dead-letter、failed successor、直写 `42501` 和
  跨租户零行。报告为 `.tmp/consumer-binding-notification-certification/report.json`，SHA-256 为
  `d4f7c2a6151afc050ff32c1e90913c9440c5bb2720d77a4f94759debc54ebd6c`；migration catalog 为 152 条，
  fingerprint 为 `ace747819bc480af9a98c2394170e138438ca8e7cfe7ba84158da7bfe49a9ed3`。详见
  [ADR-179](architecture-decisions/adr-179-consumer-binding-migration-notification-outbox.md) 和
  [handoff](handoffs/2026-08-07-consumer-binding-notification-outbox.md)。该切片仍不包含 Kubernetes HA/PDB/
  告警和 operator dead-letter recovery、多 provider conformance、GIS Service Control Plane 服务级
  ConsumerBinding/ServiceSLO 或生产 HA/RPO/RTO；AR-4.1/AR-4 总体退出门保持未完成。

#### AR-4.2 GIS Service Control Plane

- [x] 已完成最小服务控制面 authority 纵向切片：migration 153 以既有 `Resource`/
  `PlatformDefinitionVersion` 承载 `GISServiceDefinitionVersion`，只接受当前 active、quality passed 且有
  governed lifecycle event 的精确 `DataProductVersion`；`ServiceDeploymentRevision` 绑定相同 definition 的
  `PlatformRun` 和产品 output input，状态机为 `planned -> deploying -> ready|failed`，ready/failed 必须引用
  同一 Run 的精确 provider observation。`EndpointRevision` 只允许从 ready deployment 产生，稳定 HTTPS URI
  不得携带 credential/query/fragment；每个服务只有一个 state-version CAS active endpoint pointer，切换和
  回切均追加不可变 event。六张 authority/event 表强制 tenant RLS，Gateway 只有 SELECT 和
  SECURITY DEFINER recorder 权限。177 个聚焦回归测试通过、2 个未配置 `DATABASE_URL` 的测试跳过；
  PostgreSQL 16 disposable certification 覆盖旧 active ProductVersion 拒绝、ready 前 endpoint 拒绝、provider
  evidence、三次 CAS 切换/回切、陈旧 CAS、直写 `42501`、不可变 `55000` 和跨租户零行。报告为
  `.tmp/gis-service-control-plane-certification/report.json`，SHA-256 为
  `e4212667acf835aaacf51ac3b41ae152e922a237e608d1487f491bbd7b5941d4`；migration catalog 为 153 条，
  fingerprint 为 `9f17eceddedd61b245357a78bdb595fbbff1d4737dd2a56c7a84fb2a6223a3e0`。详见
  [ADR-180](architecture-decisions/adr-180-minimal-gis-service-control-plane-authority.md) 和
  [handoff](handoffs/2026-08-07-minimal-gis-service-control-plane.md)。该切片不包含 Layer/Style/TMS/Cache/
  Policy、service-scoped ConsumerBinding/ServiceSLO、真实 provider/Gateway 数据面 conformance、HA/RPO/RTO，
  不代表 AR-4 或完整 Service Control Plane 完成。
- [x] 已完成原子 GIS release binding 纵向切片：migration 154 新增 append-only
  `LayerDefinitionVersion`、`StyleDefinitionVersion`、`TileMatrixSetDefinitionVersion` 和
  `ServiceReleaseBinding`。layer 强制绑定服务源产品的精确 output ResourceVersion 并固化 geometry/schema/CRS/
  extent，style 归属精确 layer，layer-scoped TMS 不可跨 layer 混搭，vector-tile release 必须包含 TMS；deployment
  必须引用完整 release，endpoint 创建和 active CAS 均由数据库复核 release completeness。migration 153 历史
  deployment 保持可读，但旧 recorder 已对 Gateway 撤权，所有新 deployment fail closed。四张新表强制 tenant
  RLS，Gateway 只有 SELECT 与 SECURITY DEFINER recorder 权限；active projection 原子返回完整
  definition/release/layer/style/TMS/deployment/endpoint。179 个聚焦回归通过、2 个未配置 `DATABASE_URL` 的入口
  跳过；PostgreSQL 16 集成入口单独 `1 passed`，disposable certification 覆盖混搭拒绝、无 release deployment
  拒绝、旧 recorder 撤权、直写 `42501`、十表 RLS、三次 CAS 切换/回切和跨租户零行。报告为
  `.tmp/gis-service-control-plane-certification/report.json`，SHA-256 为
  `87b069715ec2be651c647d6f314b6bdc3eca11cfd1ccf5bc5aaa8d77ea98fa58`；migration catalog 为 154 条，
  fingerprint 为 `5c313a739edc0346194df3709d4bc7c40199eb36d485b4294d6dfb5d94cb2d80`。详见
  [ADR-181](architecture-decisions/adr-181-atomic-gis-service-release-binding.md) 和
  [handoff](handoffs/2026-08-08-atomic-gis-service-release-binding.md)。该切片仍不包含多 layer release、Cache/
  Policy、service-scoped ConsumerBinding/ServiceSLO、真实 provider/Gateway 数据面 conformance 或 HA/RPO/RTO，
  AR-4 与完整 Service Control Plane 状态保持未完成。
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
- [x] 已完成首个真实 provider runtime 边界：新增只读 `MartinVectorTileProvider`、`GISProviderManifest` 和
  `MVTProviderReleaseContext`，health/catalog/tile 请求必须绑定 `ServiceReleaseBinding` 的精确
  service/layer/style/TMS，zoom、坐标、MVT media type、5xx 和非 200 响应 fail closed；成功 health 可生成现有
  `FrameworkAttemptObservation`，provider 不拥有 Run、deployment、active pointer 或第二 catalog。4 个 provider
  contract tests 通过；真实 Compose Martin `v0.18.0` 容器内 health `200/ready`、catalog 发现 `map_publication`，
  并使用一次性 governed `agent_map_publications` publication fixture 完成真实 tile read：HTTP `200`、
  `application/x-protobuf`、1479 bytes、ETag 存在，tile SHA-256 为
  `dec5b71111f23adfbf4c157b4f283de2b7cf41923edde9469014f8829e07635f`。fixture 已在认证后删除，数据库无残留；
  报告为 `.tmp/gis-martin-provider-certification/report.json`，SHA-256 为
  `ea66d7b3ea47c031e14fd68445702798c0b4c8c9a03b07360e9cc7cd5460700f`。认证脚本现记录 publication、tile 坐标、
  release context、响应媒体类型、ETag 和内容哈希。详见
  [ADR-182](architecture-decisions/adr-182-martin-mvt-provider-adapter-boundary.md) 和
  [handoff](handoffs/2026-08-08-martin-mvt-provider-adapter.md)。该切片仍不代表 Martin production-supported、
  AR-4.3 或 AR-4 完成：release context 尚未接入真实 Gateway/deployment authority，仍需协议/安全/缓存/韧性
  conformance 及 governed Gateway route。

#### AR-4.4 Gateway、安全与缓存一致性

- 所有公开 endpoint 统一经过 Gateway；私有化候选基线为 Apache APISIX，云 profile 可替换为 Azure API Management 等认证 adapter。provider 使用 workload identity 和内网策略，不直接暴露公网。
- SubjectContext/PolicyDecision 向 provider 下推 resource、column、row、spatial、temporal、action 和 purpose obligation；无法安全下推时由受控 projection 隔离，不能降级为仅隐藏 UI。
- 版本进入 route、URL/TileJSON/STAC link、ETag 和 cache key；active pointer 切换触发精确 purge 或 namespace rollover。Redis/CDN/GeoWebCache/对象缓存均可丢且可重建，不保存权限或发布真值。
- 统一 auth、WAF、quota/rate limit、signed URL、request/response schema、usage/cost、log/metric/trace、correlation id、审计和 abuse protection；错误、capabilities、tile metadata 和 preview 也必须通过权限检查。
- [x] 已接入首个 governed MVT operator route：`GET /api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf`
  必须携带 tenant-scoped `service_urn`，只读取 active `GISServiceControlProjection`，并校验 release key、MVT
  endpoint contract、Martin provider、ready deployment 和 TMS zoom/坐标；响应带 release/state-version headers，
  在 policy/cache authority 完成前固定为 `private, no-store`。5 个 route contract tests 通过，连同 provider/
  control-plane 聚焦回归为 23 passed。该 route 目前明确限于 `platform_operator/admin`，不代表 ConsumerBinding、
  SubjectContext policy pushdown、缓存 namespace 或生产消费者数据面已完成，详见
  [ADR-184](architecture-decisions/adr-184-governed-mvt-operator-route.md)。
- [x] 开发环境 migration authority 已恢复到 154/154：151 的 rollback authority CHECK 采用 `NOT VALID` 保留
  legacy rollback facts，153 的 advisory-lock SQL 避免 `:gis` bind-param 误解析；Compose app 实际启动为
  `healthy`，schema fingerprint `65dabce7fa341c6c85ddab1e08483b3abae9a5fad512b926e5442e4323636066` 与
  catalog 一致，`/health` 返回 HTTP 200，未认证 MVT route 返回 HTTP 401。该证据只证明运行时与认证边界，
  不改变上项 operator-only、无 active fixture、无 ConsumerBinding/policy pushdown/cache namespace 的未完成边界。

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
4. 实现 `gda-metadata-fabric-bridge`、空间/时间/证据 extension、OpenMetadata entity/Gravitino object mapping、PostGIS/DuckDB/Iceberg/STAC/object storage harvester、OpenLineage emitter 和旧目录 crosswalk；完成 Gravitino Spark/Sedona/Flink conformance。
5. 实现 `gda-orchestration-gateway`、DolphinScheduler process/task/schedule/complement/worker-group、Spark/Flink provider task adapter 和故障注入；不再开发新的 lease/queue/scheduler。
6. 冻结首条地类图斑数据、标准版本、敏感级别、owner、SLO 和 golden result。
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
| AR-0 Architecture/Schema/Runtime Truth Freeze | `in_progress` | 全环境 schema/config fingerprint、事实清单、storage/compute/GIS serving provider profile/capability、ADR-017 benchmark、owner/SLO、首条数据业务责任/许可放行和首条服务验收集冻结 |
| AR-1 Unified Metadata + Orchestration Control Planes | `in_progress`（开发环境 control/evidence ledger + 真实 OpenMetadata 1.13.1 generic-lineage reconciliation 与已绑定 glossary-term 主数据字段投影 + 真实 DolphinScheduler manual/backfill、原子 schedule-window admission、质量与 runtime restart/reconcile 切片已验证，仍受 AR-0 阻塞） | OpenMetadata production foundation/治理采集/search-read/双租户/恢复、产品化 glossary term provisioning/binding + Gravitino fabric bridge、DolphinScheduler production foundation/manual UI + OIDC/retry/cancel/迟到回调/生产触发源/metadata restore/HA 与 Spark/Flink adapter 通过故障注入和双租户验收 |
| AR-2 Source/Ingestion + Geospatial Lakehouse Vertical Slice | `in_progress`（真实重庆 OSM 已验证 Lightweight 全分层、Default Lakehouse Spark/Iceberg batch + merge/time-travel/replay、Flink event stream、PostgreSQL WAL CDC，以及 Spark/Flink/MinIO Iceberg create/read/schema evolution/append/checkpoint recovery/cancel/ack-loss reconciliation/并发 append 乐观重基/snapshot-bound overwrite、无分区与 identity-partitioned copy-on-write key-delete、identity-key partition-replace update、position/equality delete 双向顺序互操作、update/equality-delete 和 equality-delete/insert 冲突隔离，以及安全检查开启的 single-operation Flink writer lifecycle；restricted 重庆建筑与 DEM 已验证 ODS；connector、schema drift、ApprovalCase 基础权威；SourceSync 已冻结数据形态、采集方式、目标层、adapter、标准/模型/质量/分类/保留/schema evolution/quarantine/promotion 治理合同，并原子强制 Silver/Gold 的 QualityResult、ApprovalCase、LineageEvent、metadata outbox 和 provider quarantine receipt；通用 quarantine recorder 已由真实 Flink duplicate/late、PostgreSQL CDC invalid-record 拒绝和 Spark/Iceberg 双 phase 零拒绝回执共同认证；PostgreSQL CDC 同一 slot 的双次有界网络分区、逐阶段目标 LSN 恢复、WAL 积压、无部分 sink commit、分区中 active nullable-column DDL/DML continuity、三次快速断连/重连后的精确 DML LSN 恢复、超过 checkpoint timeout 的 20 秒断网及 60 秒 sink/slot 联合恢复预算、20-cycle 高频物理抖动的 post-detachment LSN 停滞/精确目标/残余 WAL 安全预算、物理 slot absence 与同名新 incarnation 的 SourceSync-0 fail-closed、有限 `max_slot_wal_keep_size` 下同一槽 WAL `lost` 与文件系统安全底线、PostgreSQL 16 真实物理备库精确回放/提升/timeline 递增与 logical-slot 缺失 fail-closed、stop-and-detach fencing 证据、live-primary split-brain fail-closed admission，以及绑定旧 checkpoint 的 recovery plan 与独立 full/overwrite resnapshot provider commit/reconciliation、plan-bound automatic recovery schedule、真实 DolphinScheduler dispatch 与 success-evidence finalization；breaking successor fail-closed 已验证；ResourceVersion 架构四元绑定、PostGIS 架构观测/对账、drift-to-ApprovalCase 入审、外部 schema Artifact、确定性 compatibility、lineage-bound assessed ApprovalCase、双层审批后的 successor ResourceVersion/架构四元组/血缘原子创建，以及第三层产品 release 审批、消费者感知 promotion 和确定性 rollback pointer 切片已验证） | 将 quarantine receipt 扩展到其他数据库 CDC/非结构化/点云/时序真实 adapter、production STAC、非 JSON drift、跨 source 重复摄取、CDC selected-column/concurrent-DDL evolution、reconnect-backoff exhaustion、生产 recovery-controller/slot-loss detection、slot 自动修复/同步与 CDC 自动续传、物理磁盘耗尽与 predictive capacity SLO、生产 failover RPO/RTO、自动 fencing/lease 与 split-brain prevention、Flink/Iceberg kill/network uncertainty、position/MOR 与通用 SQL UPDATE/MERGE 冲突隔离、REST/Gravitino catalog、`DriveTransfer`、生产 SLO/Incident、双租户/恢复，以及默认/轻量/云 profile 等价验收 |
| AR-3 Data Product Engineering + Governance Workbench | `planned` | Blueprint、模型、Visual/SQL/Notebook、DataOps CI/CD、质量/安全/审批共用 definition 和产品生命周期 |
| AR-4 Asset/GIS Service/Spatial Experience Operations | `planned` | Service Control Plane、Features/Tiles/MVT/COG/STAC/export 及条件 legacy OGC/3D/EDR provider、Gateway/权限/缓存、原子切换/回滚、Discover/Operate/Govern 和无 LLM 多入口通过 conformance/parity/control gate |
| AR-5 AgentOps Runtime + UX Uplift | `planned` | DataOps parity/control 通过；Agent bundle eval、deployment、online observation、incident/rollback 和 uplift gate |
| AR-6 MMFE + Data for AI | `planned` | 稳定 DataProductVersion、统一 Run/Artifact 和 AgentOps ModelOps/LLMOps binding |
| AR-7 GWM Enhancement | `planned` | 可信 GWMObservationProjection |
| AR-8 Scale/High-throughput Realtime/Federation/Ecosystem | `planned, conditional` | 真实容量/SLO/freshness/互操作触发证据 |
