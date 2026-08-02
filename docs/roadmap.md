# GIS Data Agent — 总体架构 Roadmap

**Last updated**: 2026-08-02

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

当前 Metadata Fabric 证据边界：M1 只读 bridge 合同已验证；ADR-037 至 ADR-046 分别覆盖本地 foundation/recovery/metrics/network-policy 演练与 production readiness contracts；ADR-047 至 ADR-050 已依次建立 deterministic projection plan、本地双 provider replay、tenant-scoped binding ledger 与本地 OpenLineage 幂等 wire delivery；ADR-051 以临时非管理员 OpenMetadata bot 证明项目专用 grant 只有 `table/Create`、`policy/Create` 被 403 拒绝，且 JWT 轮换/吊销后旧值/当前值均返回 401；ADR-052 又在隔离 Gravitino `1.3.0` Basic IdP 中证明 bounded user 的 `USE_CATALOG`、`USE_SCHEMA`、`CREATE_TABLE` 范围、catalog-create 403、密码轮换和用户吊销；ADR-053 将生产 OIDC federation、双 provider integration/workload identity、最小权限、TLS/mTLS、持久 Gravitino catalog、tenant isolation、运营责任和新鲜 protected attestation 冻结为 fail-closed readiness contract。Gravitino `1.3.0` 镜像只发现 Basic IdP，不假设 native OIDC；当前 profile 仍有 40 个外部 blockers 且未提交真实 attestation。M3-27 已将 identity/object-store 两个 profile 与两份 protected attestation 的全部 85 个 blocker 精确且唯一分配给 16 个无环 owner decision groups，但不替 owner 选择 IdP、provider、account、bucket、region、KMS 或运行责任，所有 group 仍为 `unresolved`。M3-28 又以全量重庆真实源启动 AR-2：固定 468,462,251-byte 原 ZIP、584-file/700,610,744-byte 解压工作集、11 个 source groups 与 16 个 metadata profiles，但因 6 个 archive entry 已变化、52 个解压新增文件及 57 个治理 blocker，只允许 metadata profiling，不允许 content admission。`local_openmetadata_minimum_privilege_verified=true` 与 `local_gravitino_minimum_privilege_verified=true` 都只描述各自临时 provider rehearsal；M3-2 ingestion 仍使用 bootstrap admin，Gravitino probe catalog 仍是 memory catalog。因此 `provider_minimum_privilege_verified`、protected workload identity、OIDC、TLS、持久 catalog、生产 ingestion/conformance、生产 lineage receiver、`production_identity_gate_passed` 与 `production_ready` 仍为 false。

M3-22 至 M3-25 已把一份真实重庆 20-feature EPSG:4490 slice 从受授权 Spark/Sedona + JDBC/S3 Iceberg ingestion，推进到保留 7 天的 staging material、原子 GDA Control `ResourceVersion + 2 Artifacts + QualityResult + LineageEvent` 晋级、数据库裁决的 `succeeded@3` 和保留运行时的受控 restart continuity。M3-24 已持久化完整 execution-plan/PolicyDecision/Approval Artifacts，回读真实 DolphinScheduler `SUCCESS`，由独立 evaluator 重开 Parquet 并重算九项空间质量与 row fingerprint；M3-25 又按 PostgreSQL -> MinIO -> Gravitino -> GDA Control 顺序重启同一运行时，证明稳定 namespace/StatefulSet/Service/PVC/container/volume 身份不变、Pod/PID 轮换，且 Iceberg snapshot/Parquet/Gravitino projection/GDA ledger facts SHA 与 `succeeded@3` 精确 replay 均不漂移、不新增事实。M3-26 进一步把该真实 predecessor 与 production identity/object-store gates 组合为受保护重执行准入，强制两份 attestation 绑定同一 source revision，并禁止本地 retained material 直推；M3-27 又将 85 个 blocker 精确映射为 16 个 owner decision groups，固化依赖、允许/禁止边界、profile path、required artifact 和 protected verification command。当前两个 profile 虽结构有效，但所有 group 仍未决，所以 `ready_for_protected_reexecution=false`，没有调度或 provider 写入授权。M3-28 的全量重庆 admission evidence 是另一条 AR-2 源基线，不继承 20-feature slice 的授权或成功状态；它只证明源文件完整盘点、内容指纹与 metadata profiling，不能触发 scheduler/provider。生产 owner 决策与 identity/storage/tenant attestation、source governance、常驻 scheduler/executor、独立故障域、backup/PITR、production restart recovery、staging scale 和完整 Spark/Flink conformance 仍是下一门槛。边界见 [ADR-070](architecture-decisions/adr-070-retained-real-feature-terminal-success.md)、[ADR-071](architecture-decisions/adr-071-retained-real-feature-restart-recovery.md)、[ADR-072](architecture-decisions/adr-072-protected-real-feature-reexecution-gate.md)、[ADR-073](architecture-decisions/adr-073-protected-profile-owner-decision-packet.md) 与 [ADR-074](architecture-decisions/adr-074-chongqing-real-source-admission-manifest.md)。

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
- [x] 已发布重庆 OSM 道路 `v1.2.0` 的 50,366 条真实数据完成首条受权威 checkpoint 管理的
  Spark/Iceberg micro-batch：full baseline 形成 snapshot `4541513947196238885`；第二个 Run 用单次
  `MERGE INTO` 精确执行 1 insert、1 update、1 delete，形成 snapshot `5267674800802558836`，行数和
  road ID 唯一性守恒。两个 snapshot 均完成 time travel 回读，checkpoint 从 0 精确推进到 2。
  第三个合法 Run 在写前以 source-slice SHA-256 命中既有 commit，未再次启动 provider 写入，Iceberg
  history 和 checkpoint 分别保持 2；跨 Run commit recovery 返回原 commit。随机 PostgreSQL database、
  Iceberg table 和 MinIO prefix 已删除，主库三张 sync 表前后保持 0 行。10 项端到端检查全部通过；证据
  `.tmp/source-sync-certification/chongqing-osm-report.json`，SHA-256
  `42e762e0e16fa8f6e5e3e907467b193ab3b3fba3a88e2a958a605fc9e84b3abf`。
- [x] 同一 `v1.2.0` Silver GeoParquet 已完成首条真实 Flink 1.19.3 事件流验收。50,366 条道路中
  确定性选择四条形成 10-event insert/update/delete slice；Flink 在 completed checkpoint `6`、offset
  `5` 后主动失败，attempt `1` 从 offset `5` 恢复。最终仅提交 8 条唯一 accepted event，重复 delete
  和超 watermark 的迟到 update 各进入一条 audit；容差内乱序 update 被接受，两个源端 delete 生效，
  最终状态为 2 条道路。SourceSync checkpoint 从 0 精确推进到 1，第二个合法 Run 在写前命中原 source
  slice 并跳过 Flink，provider write 保持 1 次。随机数据库和工作目录均删除，主库 sync 表仍为 0 行。
  该证据使用本地短生命周期 Docker + Flink `local` target，不是 Compose 常驻容器或 K8s runtime；也不
  宣称 PostgreSQL CDC、Flink/Iceberg、跨系统 exactly-once 或生产 SLO 已完成。详见
  [ADR-105](architecture-decisions/adr-105-flink-event-stream-source-sync-certification.md) 和
  `.tmp/source-sync-certification/chongqing-osm-flink-report.json`，报告 SHA-256
  `f02add8a4a953712d58a2b0973fbab271c583c5182e1889ab88da750e86bc673`。
- [x] 同一真实 OSM source slice 已完成 PostgreSQL 16.14 WAL -> 官方 PostgreSQL CDC connector 3.3.0 ->
  Flink 1.19.3 的 log-based CDC 验收。三条初始快照、两次 update、两次 delete 和一条中间 insert 形成
  10 条唯一 Table changelog（含两组 update-before/update-after）；Flink 在 completed checkpoint `6`、
  处理计数 `5` 后失败，attempt `1` 从 count `3` 恢复，并在 checkpoint `9` 提交全部变更。最终源状态
  与 Bronze 重建状态均为 2 条道路；initial/final/confirmed-flush LSN、replication slot、connector/JAR/
  runtime image 和 drain savepoint 均进入证据。SourceSync checkpoint 仅推进 `0 -> 1`，第二个合法 Run
  写前命中原 commit，provider 只执行一次。9 项端到端门与 8 项 provider 门全部通过，隔离容器、控制
  数据库和工作目录已删除，主库 sync 表保持为空。该证据仍是本地短生命周期 Docker，不是 K8s；不
  代表 Flink/Iceberg、跨系统事务、活跃 CDC schema evolution、生产 SLO 或 HA。详见
  [ADR-106](architecture-decisions/adr-106-postgresql-cdc-flink-source-sync-certification.md) 和
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`，报告 SHA-256
  `3776339344874594809293a6e595f22b1fcebe4a421c4cebf068fdbd8653bba7`。
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
  SourceSync definition/commit/checkpoint authority 已验证；但
  production STAC provider 认证、非 JSON 对象格式的 schema drift、三类 source 网络故障与重复摄取、
  其他 source 的重复摄取、活跃 CDC schema evolution/网络分区/slot lifecycle、Flink/Iceberg kill -9/
  网络分区不确定提交、position/MOR
  destructive-write 并发冲突隔离及通用 SQL UPDATE/MERGE 冲突隔离、REST/Gravitino catalog 互操作、
  并发/reconcile、
  DataSLO/Incident、
  DriveTransfer、双租户、备份恢复和默认/轻量/
  云 profile 语义等价仍未完成；ApprovalCase Inbox、委托、通知、SLA timeout automation 和除 schema
  drift 外的 consumer 接入也未完成，因此 AR-2 仍不得标为 `verified`。

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
4. 分阶段实现 `gda-metadata-fabric-bridge`：M1 只读 mapping/reconciliation、M2a 本地 foundation/重启连续性、M2b 本地与跨集群恢复、M2c metrics/OTel 故障演练、M2d production readiness contracts，以及 M3-1 至 M3-25 projection、provider identity/interoperability、Active Metadata、真实 feature ingestion、原子 ledger promotion、retained terminal success 和同一保留 authority 的本地进程重启连续性已验证；M3-26 已建立真实 predecessor 的 protected re-execution 组合门禁，M3-27 已把 85 个外部 blockers 收敛为 16 个可分派、可校验但仍未决的 owner decision groups。下一步必须由 packet 指定的 owner 批准并物化 production identity/object-store profiles，在同一 source revision 生成受保护 identity/storage/tenant attestations；随后才可另行授权常驻 scheduler/executor 与持久 catalog/control/storage，做 fresh protected ingestion，并验证 backup/PITR、独立故障域、production restart recovery、staging scale、完整 Spark/Flink conformance 和真实告警/runbook。本地 retained material 不得直接晋级，也不计入生产退出门。
5. 实现 `gda-orchestration-gateway`、DolphinScheduler process/task/schedule/complement/worker-group、Spark/Flink provider task adapter 和故障注入；不再开发新的 lease/queue/scheduler。
6. M3-28 已冻结全量重庆真实源的 path-free physical/metadata admission baseline；下一步补齐解压派生 provenance，并由 owner 决定首条地类图斑源的 license、retention、access、privacy/sensitivity、标准版本、SLO 和 golden result，未获批准前不得 content admission。
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
| AR-1 Unified Metadata + Orchestration Control Planes | `in_progress` | controlled gateway、DolphinScheduler adapter、Metadata Fabric 本地 recovery/metrics/policy/identity/interoperability、真实 feature ingestion 与临时 GDA Control 原子 output promotion 已验证；下一证据是可保留 staging material、完整授权/成功/独立质量 provenance、source host/cluster 外 recovery、持久 metrics/TLS/tenant/alert/SLO、OIDC、NetworkPolicy、升级回滚/registry provenance 与无双写验收 |
| AR-2 Source/Ingestion + Geospatial Lakehouse Vertical Slice | `in_progress` | M3-28 已完成全量重庆真实源的 path-free、content-addressed、metadata-only admission baseline；下一证据是解压派生 provenance 与 owner/license/retention/access/privacy 决策，之后才可建立 Landing authority，并让三类代表源、`DriveTransfer`、默认湖仓、轻量 profile 与 Azure adapter 通过统一控制面及 Raw -> ADS 验收 |
| AR-3 Data Product Engineering + Governance Workbench | `planned` | Blueprint、模型、Visual/SQL/Notebook、DataOps CI/CD、质量/安全/审批共用 definition 和产品生命周期 |
| AR-4 Asset/GIS Service/Spatial Experience Operations | `planned` | Service Control Plane、Features/Tiles/MVT/COG/STAC/export 及条件 legacy OGC/3D/EDR provider、Gateway/权限/缓存、原子切换/回滚、Discover/Operate/Govern 和无 LLM 多入口通过 conformance/parity/control gate |
| AR-5 AgentOps Runtime + UX Uplift | `planned` | DataOps parity/control 通过；Agent bundle eval、deployment、online observation、incident/rollback 和 uplift gate |
| AR-6 MMFE + Data for AI | `planned` | 稳定 DataProductVersion、统一 Run/Artifact 和 AgentOps ModelOps/LLMOps binding |
| AR-7 GWM Enhancement | `planned` | 可信 GWMObservationProjection |
| AR-8 Scale/High-throughput Realtime/Federation/Ecosystem | `planned, conditional` | 真实容量/SLO/freshness/互操作触发证据 |
