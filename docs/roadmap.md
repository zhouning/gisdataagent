# GIS Data Agent — 总体架构 Roadmap

**Last updated**: 2026-08-30

**Status**: Architecture reset, authoritative mainline

**Current gate**: AR-0 first vertical slice business approval and quality repair

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
| 数据源与汇聚 | virtual source/connectors、PostGIS intake、stream、文件/对象存储组件，以及 `OfflineIngestStore` 的 lightweight `DriveTransfer` 本地 file-lake profile | 轻量 profile 已有真实分片/断点/完整性/入湖证据；仍无统一生产 Source/SyncDefinition/SyncRun、CDC，以及云盘客户端生产 provider 的服务端会话/断点/入湖闭环 |
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

核心发布对象冻结为：通用 `ServiceDefinitionVersion` 的 GIS typed profile `GISServiceDefinitionVersion`，以及 `LayerDefinitionVersion`、`StyleDefinitionVersion`、`TileMatrixSetDefinitionVersion`、`CachePolicyVersion`、`ServicePolicyBinding`、`MVTServingProjectionVersion`、`ServiceDeploymentRevision`、`EndpointRevision`、`ConsumerBinding`、`ServiceSLO` 和 `RollbackPointer`；它们共用一个 service registry 和 lifecycle，不新建第二套服务权威。定义至少声明 source `DataProductVersion`、schema/geometry/CRS、spatial-temporal extent、scale/generalization/label/style、format/protocol、provider capability、auth/policy、quota/rate/cache、compatibility/deprecation 和 reliability class。运行时投影均可从产品版本重建，不得成为数据真值。

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

本轮新增决策索引：[ADR-192：Provider credential source contract](architecture-decisions/adr-192-provider-credential-source-contract.md)、[ADR-193：Metadata provider bridge observability](architecture-decisions/adr-193-metadata-provider-bridge-observability.md)、[ADR-194：Metadata provider health and readiness contract](architecture-decisions/adr-194-metadata-provider-health-readiness-contract.md)、[ADR-195：DolphinScheduler cancel capability admission](architecture-decisions/adr-195-dolphinscheduler-cancel-capability-admission.md)、[ADR-196：DolphinScheduler cancel terminal evidence timing](architecture-decisions/adr-196-dolphinscheduler-cancel-terminal-evidence-timing.md)、[ADR-245：DuckDB 轻量存算一体架构采集与对账](architecture-decisions/adr-245-duckdb-architecture-provider-reconciliation.md)、[ADR-246：S3-compatible JSON/GeoJSON 对象架构观察](architecture-decisions/adr-246-object-storage-architecture-observation.md)、[ADR-247：对象存储观察接入控制账本的联合验收](architecture-decisions/adr-247-object-storage-ledger-integration-acceptance.md)、[ADR-248：Gravitino Iceberg 表架构观察](architecture-decisions/adr-248-iceberg-architecture-observation.md)、[ADR-249：真实 Iceberg snapshot 到架构账本的联合验收](architecture-decisions/adr-249-real-iceberg-snapshot-ledger-acceptance.md)、[ADR-250：Iceberg snapshot lineage observation contract](architecture-decisions/adr-250-iceberg-snapshot-lineage-observation-contract.md)、[ADR-251：Gravitino Iceberg REST catalog 数据面验收](architecture-decisions/adr-251-gravitino-iceberg-rest-catalog-data-plane-acceptance.md)、[ADR-252：Flink 通过 Gravitino Iceberg REST catalog 数据面验收](architecture-decisions/adr-252-flink-gravitino-iceberg-rest-catalog-acceptance.md)、[ADR-253：DriveTransfer 轻量 file-lake profile 验收](architecture-decisions/adr-253-drive-transfer-lightweight-file-lake-acceptance.md)、[ADR-294：Tenant-scoped object recovery](architecture-decisions/adr-294-tenant-scoped-object-recovery.md) 和 [ADR-295：Cross-store recovery identity binding](architecture-decisions/adr-295-cross-store-recovery-identity-binding.md)。

本轮继续新增 [ADR-254：Flink/Iceberg 物理故障窗口的提交不确定性对账](architecture-decisions/adr-254-flink-iceberg-physical-fault-uncertainty-reconciliation.md)。

本轮继续新增 [ADR-348：Flink/Iceberg terminal-checkpoint kill 不确定性对账](architecture-decisions/adr-348-flink-iceberg-kill-uncertainty-reconciliation.md)。

本轮继续新增 [ADR-349：Flink REST provider cancellation adapter](architecture-decisions/adr-349-flink-rest-provider-cancellation-adapter.md)。

本轮继续新增 [ADR-350：Live Flink provider cancellation integration](architecture-decisions/adr-350-live-flink-provider-cancellation.md) 和 [ADR-351：Temporal activity to Flink provider cancellation settlement](architecture-decisions/adr-351-temporal-flink-provider-cancellation-activity.md)。

本轮继续新增 [ADR-255：Flink position-delete/MOR stale commit 冲突隔离](architecture-decisions/adr-255-flink-position-delete-stale-conflict-isolation.md)。

本轮继续新增 [ADR-267：Spark SQL MERGE 复杂 AND/OR/IN 谓词的 bounded 语义](architecture-decisions/adr-267-spark-sql-merge-complex-predicate.md)。

本轮继续新增 [ADR-268：Spark SQL UPDATE 复杂 AND/OR/IN 谓词的 bounded 语义](architecture-decisions/adr-268-spark-sql-update-complex-predicate.md)。

本轮继续新增 [ADR-269：Spark SQL MERGE 重复 source 的确定性自动去重](architecture-decisions/adr-269-spark-sql-merge-deterministic-auto-deduplication.md)。

本轮继续新增 [ADR-270：Spark SQL MERGE retry budget 的 fail-closed admission](architecture-decisions/adr-270-spark-sql-merge-retry-budget-fail-closed.md)。

本轮继续新增 [ADR-271：Spark SQL MERGE 跨 target 的显式 survivorship admission](architecture-decisions/adr-271-spark-sql-merge-cross-target-survivorship.md)。

本轮继续新增 [ADR-272：Spark SQL MERGE 跨分区多文件写入范围对账](architecture-decisions/adr-272-spark-sql-merge-partition-file-scope.md)。

本轮继续新增 [ADR-273：Spark SQL UPDATE 的受控 scope 子查询](architecture-decisions/adr-273-spark-sql-update-subquery-scope.md)。

本轮继续新增 [ADR-274：Spark SQL MERGE retry budget 的自适应退避](architecture-decisions/adr-274-spark-sql-merge-adaptive-backoff.md)。

本轮继续新增 [ADR-275：Spark SQL MERGE 退避后的成功 fresh retry](architecture-decisions/adr-275-spark-sql-merge-successful-retry.md)。

本轮继续新增 [ADR-276：Spark SQL MERGE 的跨进程 retry budget authority](architecture-decisions/adr-276-spark-sql-merge-cross-process-budget.md)。

本轮继续新增 [ADR-277：Spark SQL MERGE 的连续成功 fresh retry](architecture-decisions/adr-277-spark-sql-merge-multiple-successful-retries.md)。

本轮继续新增 [ADR-278：Spark SQL MERGE 的跨进程成功 fresh retry](architecture-decisions/adr-278-spark-sql-merge-cross-process-successful-retry.md)。

本轮继续新增 [ADR-279：Spark SQL MERGE provider abort recovery](architecture-decisions/adr-279-spark-sql-merge-provider-abort-recovery.md)。

本轮继续新增 [ADR-280：Spark SQL UPDATE 的相关 scope 子查询](architecture-decisions/adr-280-spark-sql-update-correlated-subquery.md)。

本轮继续新增 [ADR-281：Spark SQL UPDATE SET 相关 scalar subquery capability probe](architecture-decisions/adr-281-spark-sql-update-scalar-subquery-capability-probe.md)。该 probe 已真实证明当前 Spark/Iceberg runtime 对该写入语义 `unsupported_fail_closed`，因此不将它计入已支持能力。

本轮继续新增 [ADR-282：Spark/Flink Iceberg partition-spec evolution](architecture-decisions/adr-282-spark-flink-iceberg-partition-evolution.md)、[ADR-283：Spark SQL mixed-spec destructive write](architecture-decisions/adr-283-spark-sql-mixed-spec-destructive-write.md)、[ADR-284：Spark/Flink mixed-spec equality delete capability probe](architecture-decisions/adr-284-spark-flink-mixed-spec-equality-delete.md) 和 [ADR-285：混合 partition spec 先受控 rewrite，再执行 equality delete](architecture-decisions/adr-285-spark-controlled-rewrite-before-equality-delete.md)。

本轮继续新增 [ADR-286：Flink 单 RowDelta 跨两个 data file 的 position-delete 写入](architecture-decisions/adr-286-flink-multi-file-position-delete-write.md)。

本轮继续新增 [ADR-287：Flink 多文件 position-delete stale commit 冲突隔离](architecture-decisions/adr-287-flink-multi-file-position-delete-stale-conflict-isolation.md)。

本轮继续新增 [ADR-288：Spark/Iceberg provider 真实重放与控制面 authority gap 对账](architecture-decisions/adr-288-spark-iceberg-provider-rehearsal-and-authority-gap-recovery.md)。

本轮继续新增 [ADR-289：Provider-neutral GIS MVT cache purge 执行边界](architecture-decisions/adr-289-provider-neutral-gis-mvt-cache-purge-execution.md)。

本轮继续新增 [ADR-290：HTTP GIS MVT cache purge provider](architecture-decisions/adr-290-http-gis-mvt-cache-purge-provider.md)。

本轮继续新增 [ADR-291：GIS MVT purge provider process selection](architecture-decisions/adr-291-gis-mvt-purge-provider-selection.md)。

本轮继续新增 [ADR-318：Decision Packet 作为 JQDLTB Readiness 输入](architecture-decisions/adr-318-jqdltb-decision-packet-readiness-bridge.md)。

本轮继续新增 [ADR-325：Temporal Start Input Reconciliation](architecture-decisions/adr-325-temporal-start-input-reconciliation.md)。

详细理由见 [ADR-001：可插拔地理空间存储、计算与服务边界](architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)、[ADR-002：统一元数据控制面](architecture-decisions/adr-002-unified-metadata-control-plane.md)、[ADR-003：统一调度与作业控制面](architecture-decisions/adr-003-unified-orchestration-and-job-control-plane.md)、[ADR-004：传统平台能力下限与 Human/Agent 双入口](architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)、[ADR-005：DataOps 与 AgentOps 双运营闭环](architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md)、[ADR-006：OpenMetadata + Gravitino Metadata Fabric](architecture-decisions/adr-006-openmetadata-governance-and-active-metadata-platform.md)、[ADR-007：DolphinScheduler + Temporal 编排平台](architecture-decisions/adr-007-dolphinscheduler-temporal-orchestration-platform.md)、[ADR-017：GIS 服务发布控制面与 Provider Runtime](architecture-decisions/adr-017-gis-service-publishing-control-plane-and-provider-runtime.md)、[ADR-187：Gravitino 持久化元数据平面验收边界](architecture-decisions/adr-187-gravitino-persistent-metadata-plane-acceptance.md)、[ADR-188：Metadata Fabric crosswalk 搜索与读取桥接](architecture-decisions/adr-188-metadata-fabric-crosswalk-search-read-bridge.md)、[ADR-189：Metadata provider read bridge](architecture-decisions/adr-189-metadata-provider-read-bridge.md)、[ADR-190：Bound Gravitino provider search](architecture-decisions/adr-190-bound-gravitino-provider-search.md) 和 [ADR-191：Bound OpenMetadata provider search](architecture-decisions/adr-191-bounded-openmetadata-provider-search.md)。

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

**2026-08-22 范围收敛**：AR-0 不再等待整个 Data Platform 的所有目标能力同时完成。首期冻结对象、状态机、已有证据、外部待决和生产晋级条件以
[AR-0 首条 Vertical Slice Freeze Manifest](freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)
为准。当前状态为 `awaiting_business_approval`：技术设计、首条标准映射验收和 approval-required transformation contract 已冻结，JQDLTB 全量源质量仍失败，`business_steward`、`license_status`、SLO/on-call 和生产环境 owner 仍待批准。MMFE、GWM、完整协议矩阵、跨引擎和生产 HA/DR 进入后续阶段，不再反向扩大本次 AR-0 退出门。

以下清单保留为平台级目标架构和后续阶段输入，不再逐项作为本次首条切片的即时退出门；本次即时范围以 Freeze Manifest 为准。

平台级目标交付：

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

平台级长期退出门（按 AR-1～AR-8 分阶段满足）：

- 所有目标环境 schema 达到已批准 fingerprint；重复迁移、checksum 漂移和失败迁移在 CI/部署中 fail closed。
- 所有“已完成”能力都有代码、真实后端、测试或运行产物证据。
- 元数据、调度、湖仓、STAC、MMFE、治理和 GWM 的“配置/合同/运行”状态被分别标注。
- 每个生产数据产品和 Agent deployment 都能映射到 owner、definition version、approval、SLO、incident policy、rollback pointer 和运行证据。
- 代表 P0 capability 的 Web/API/SDK/CLI/TUI/Notebook/Agent parity matrix、OpenAPI/AsyncAPI/MCP projection 和 `llm_mode=disabled` 测试计划均已冻结；不能以聊天 prompt、页面点击或 notebook cell 充当唯一接口。
- metadata/lineage/workflow/task API 的双租户越权路径已有回归测试和修复计划。
- 首条数据链路 owner、输入、规模、敏感级别和验收数据冻结。

首条切片按 `draft -> technical_frozen -> awaiting_business_approval -> promotable` 推进。技术冻结不等于产品晋级；尚未批准的组织责任、许可、SLO 和 transformation 策略不允许由代码或 Agent 代填。AR-0 下一证据固定为 Manifest 的业务批准记录、批准绑定的 transformation contract，以及 JQDLTB source-quality 修复后的重跑报告；在这三项完成前，不再用新增旁路 authority、worker 或框架 benchmark 替代该证据。

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
- [x] 已对同一冻结 bundle 完成只读质量修复诊断：`TBBH` 是完整且唯一的技术候选键；`TBMJ`/
  `TBDLMJ` 各 6 条非正值；7 条记录的面积偏差超过 1%，其中 2 条超过 10%；`SJNF`、`MSSM`
  没有可自动采纳的语义来源。诊断只输出聚合证据，未修改源字节、未持久化源值、未生成默认
  canonical 值，报告指纹绑定在 AR-0 machine Manifest。详见
  [ADR-241](architecture-decisions/adr-241-jqdltb-approval-gated-quality-repair-diagnostic.md)。
- [ ] 下一步不是自动“修复”：业务/数据责任人需要批准 canonical key、非正面积的更正或隔离、
  面积偏差处理和 `SJNF/MSSM` 推导语义；批准后工程才能把当前 draft 升级为 execute contract
  并重跑 source-quality。
- [x] 已编译 approval-required transformation contract：它绑定 archive/bundle、标准版本与指纹、
  source `ResourceVersion` 和质量诊断指纹；当前 `mode=approval_required`，不携带面积策略、
  推导规则或 ApprovalCase。执行校验对 checksum、诊断指纹和 source identity 漂移 fail closed。
  详见 [ADR-242](architecture-decisions/adr-242-jqdltb-transformation-contract.md)。
- [x] 已补齐 transformation 审批生命周期：完整业务策略只能先生成不可执行 `dry_run` proposal；
  统一 ApprovalCase 同时绑定 plan fingerprint 和完整 request context；`execute` contract 只能从原
  proposal 与已批准 case 编译。真正执行还必须从 PostgreSQL authority 重读完全相同的批准记录，
  本地 JSON 不能单独授权写数据层。当前尚无业务策略输入，因此未生成虚假 proposal 或审批结果。
- [x] JQDLTB transformation 已从“有执行器”接到真正的 DataOps 调度准入：独立的
  `PlatformDefinitionVersion`、DolphinScheduler workflow、deployment/submit 脚本和
  `gda.dolphinscheduler_jqdltb_transformation_plan.v1` execution-plan Artifact 已实现。该
  Artifact 同时绑定 workflow binding、`mode=execute` contract、`plan_sha256`、
  `contract_sha256` 和 ApprovalCase；部署时会从 ApprovalCase authority 重读并拒绝 case/plan
  漂移，PlatformRun policy decision 指向同一 plan。DolphinScheduler 任务不会运行时选策略，
  只提交编译后的 contract；执行器会把请求 contract 与平台 plan 再校验一次。详见
  [ADR-244](architecture-decisions/adr-244-jqdltb-transformation-scheduler-plan.md)。
- [x] transformation candidate 的平台证据失败路径已固定：输出目录保留显式
  `platform_evidence.status=failed` 和失败类型，同一 contract 的重试会清理未完成候选并重新
  原子落地；完成状态才可 replay，半成品不能被当成成功或 DataProductVersion。
- [x] 已补齐 JQDLTB candidate 到既有 `DataProductVersion` registry 的显式发布门：typed release
  plan 强制同一 Run/source/output、完整 Raw/ODS/DIM/DWD/ADS/quarantine layer manifest、passed
  `QualityResult`、质量 Artifact、lineage、transformation ApprovalCase，以及 business steward、
  license、DataSLO/ServiceSLO、on-call、environment owner、DeploymentProfile 和 backup/restore
  evidence。任一治理值仍为 pending/unknown/unassigned 时计划即拒绝；发布还需独立
  `data_product.publish_jqdltb` ApprovalCase，并在调用既有 `DataProductRegistry.publish` 前重读
  authority 和完整 request context。执行器同时新增内容寻址的 `layer-manifest.json`，修正了原
  OUTPUT Artifact URI 指向 ADS 文件但哈希代表 layer manifest 的身份不一致。数据库再以不可变
  `jqdltb_data_product_release`、deferred constraint trigger、RLS/FORCE RLS 和 gateway append-only
  权限封住直接 registry 绕过。JQDLTB 聚焦回归 28 项、registry 相关回归 56 项通过；全新
  PostGIS 16/3.4 容器认证 1 项通过，报告 SHA-256 为
  `3a4d60945a43be1cca5e272f8140a6b3da0948b583e9009df9997fa801cf7e6e`。认证中的审批、发布计划和
  `DataProductVersion` 是随容器销毁的 fixture；当前仍没有真实业务批准、真实 JQDLTB 发布计划或
  持久化产品版本，因此不改变 `awaiting_business_approval` 状态。详见
  [ADR-292](architecture-decisions/adr-292-jqdltb-data-product-release-gate.md)。
- [x] 已补齐 JQDLTB transformation 审批前只读 readiness preflight：复用 Freeze verifier、冻结
  baseline 和 source-quality diagnostic，输出 canonical key、面积策略、`SJNF/MSSM` 推导的机器化
  决策要求；可选策略只在内存中校验并生成 proposal preview/fingerprint，不写源数据、不创建
  ApprovalCase。默认报告的 readiness SHA-256 为
  `b0322495824050293aee52ba23976026582ebb1617cf98840e417ead5077eb77`；decision requirements
  现在同时绑定 `SJNF/MSSM` 语义审计指纹和最小业务输入。这只是缩短业务输入后的
  prepare 路径，不替代业务批准或 source-quality 重跑。
- [x] 已在冻结的真实 1,555 条 JQDLTB 源上增加 impact preview：读取前后 sidecar bundle 身份一致，
  对 `quarantine/business_correction` × `preserve_source/use_geometry/quarantine` 六种组合输出
  版本化影响证据。当前可精确投影的 `quarantine + preserve_source` 为 1,549 条候选/6 条隔离，
  `quarantine + quarantine` 为 1,542 条候选/13 条隔离；缺少 correction identity 的组合保持
  `null`，不做估算。预览不创建 ApprovalCase、不写任何数据层、不创建 DataProductVersion；
  同时 executor 已按冻结规则对 `TBMJ/TBDLMJ` 双字段 fail closed。详见 [ADR-312](architecture-decisions/adr-312-real-jqdltb-transformation-impact-preview.md)
  和 [`jqdltb_transformation_impact_preview_2026-08-26.json`](reports/jqdltb_transformation_impact_preview_2026-08-26.json)，
  报告 canonical 内容指纹为 `30ebf144218725372ef85a863c16facb24414c4cb676e6cdd6658f9e24c72ef5`。
- [x] 已关闭批准规则与运行字节脱钩的缺口：`SJNF/MSSM` derivation 必须读取并校验版本化
  `gda.jqdltb_derivation_rule.v1` artifact；`use_geometry` 必须读取并校验
  `gda.jqdltb_geometry_area_rule.v1` artifact；business correction 必须逐行校验 `TBBH`、双面积
  更正和 SHA-256。规则、CRS、method、source fields 或 correction 内容漂移会在输出目录创建前
  fail closed；执行证据记录实际 rule binding。详见 [ADR-313](architecture-decisions/adr-313-jqdltb-runtime-rule-artifact-binding.md)。
  JQDLTB/AR-0 聚焦回归 `41 passed`；下游发布门随后在 disposable PostGIS 16.4/PostGIS 3.4.3
  中 `1 passed`，报告 SHA-256 为 `86cb83fc01222a065379c03b506ade8bd5ef4a44534bf973c9a49231a9eb43e4`。
  该数据库中的批准和 DataProductVersion 均为随容器销毁的 fixture，不改变真实 AR-0 状态。
- [x] 已完成 `SJNF/MSSM` 来源证据审计：标准表 5-13 明确 `SJNF` 是“数据生产的年份”；
  `MSSM` 是必填 `Char(2)`，但现有标准材料没有 DLTB 值域或填写规则。真实源中 `PZWH` 仅
  10/1,555 非空，`SM/DLBZ` 全空，`JQDLMC` 是地类名称；ArcGIS 2018/2019 处理日期也不等于
  数据生产年份。因此所有当前候选保持拒绝，业务输入缩为生产年份权威材料和 `MSSM Char(2)`
  填写规则两项。审计不创建 rule、strategy、ApprovalCase 或 DataProductVersion；报告 canonical
  SHA-256 为 `90bead274d1dc7238cfb1b7f0400e8dc539f0f8aa9af932a6209a80a9acff4f8`。详见
  [ADR-314](architecture-decisions/adr-314-jqdltb-sjnf-mssm-semantic-evidence.md)。
- [x] 已把语义证据门前移到 transformation admission：readiness 和 `prepare` 现在只接受语义
  审计状态为 `accepted/approved` 的 source field；`rejected`、`pending_business_evidence` 或
  未登记字段均在 proposal/ApprovalCase 创建前拒绝。当前真实冻结审计没有可用来源，因此 readiness
  明确报告 `semantic_derivation_evidence_missing.SJNF/.MSSM`，不会产生虚假审批状态。当前
  默认 readiness SHA-256 为 `b0322495824050293aee52ba23976026582ebb1617cf98840e417ead5077eb77`。
  公开 `prepare_approval()` 已提升为唯一受支持的生产构造入口，会重跑完整 Freeze verifier，并
  绑定 diagnostic、semantic audit、Manifest 指向的完整 baseline 和 source admission；私有 builder 只用于不声称
  业务准入的合成测试。通过准入的 proposal/execute contract 现在把
  `semantic_candidate_audit_sha256` 纳入 plan、contract fingerprint 和 ApprovalCase context，
  旧 baseline 指纹保持兼容。AR-0/JQDLTB 聚焦回归 `51 passed, 1 skipped`，跳过项为未配置外部
  PostgreSQL 发布门 DSN；Ruff、Python compile 和 31 项 Freeze machine checks 通过。
  详见 [ADR-315](architecture-decisions/adr-315-jqdltb-semantic-admission-before-approval.md)。
- [x] 已把 semantic admission 从审批入口延伸到运行前：带
  `semantic_candidate_audit_sha256` 的 execute contract 必须重新读取实际 audit，校验 canonical
  fingerprint、archive/bundle/standard identity，并确认 `SJNF/MSSM` 的每个 source field 仍为
  `accepted/approved`，且 target decision 必须为 accepted 状态；缺文件、内容篡改或状态回退均在输出目录创建前拒绝。DataOps executor 已增加
  semantic audit 路径装配，运行 evidence、lineage、artifact 和平台 technical refs 记录同一 SHA。
  成功路径只使用 disposable accepted fixture，不代表真实业务放行。详见
  [ADR-316](architecture-decisions/adr-316-jqdltb-runtime-semantic-audit-revalidation.md)。
- [x] 已将机器化 JQDLTB Decision Packet 接入 readiness：`--decision-packet` 与
  `--strategy` 互斥；readiness 每次重新校验 packet、Manifest、baseline、diagnostic 和
  semantic audit identity。draft 或 transformation 决定不完整时只输出分层 blockers；已提交且
  五项 transformation 决定及语义证据齐全时，在内存中复用既有 strategy/proposal preview，
  不创建 ApprovalCase。五项 promotion 决定仍独立阻断产品晋级；packet SHA、validation SHA
  和输入覆盖检查均纳入报告。详见 [ADR-318](architecture-decisions/adr-318-jqdltb-decision-packet-readiness-bridge.md)。
- [x] 已将 Decision Packet 接入 JQDLTB DataProduct release gate：submitted packet 的十项决定与
  executable transformation contract、release operating contract 逐项比对；packet identity 或
  canonical/面积/语义/责任/许可/SLO/环境 owner 任一漂移均 fail closed。packet SHA-256 同时进入
  mapping binding、layered distribution、release ApprovalCase context 和 registry binding；development
  synthetic fixture 保持兼容，staging/production 强制 packet。新增 migration 234 的不可变列与 deferred
  trigger，并补齐内存和 Postgres 负向回归。原始 draft 仍保留；当前真实 packet 已有一个 partial
  `submitted` 版本，但尚未产生完整业务批准、DataProductVersion 或生产发布。详见
  [ADR-319](architecture-decisions/adr-319-jqdltb-data-product-release-binding.md)。
- [x] 已补齐 draft 到 submitted 的人工提交入口：`submit-decision-packet` 只接受固定十项 target
  的显式 patch，冻结 evidence/identity 不可覆盖，提交人必须为 `human:*`；省略项继续保持
  `pending_business_evidence`。提交前后都会重新验证 packet、证据和 semantic admission，任何
  未知 target、非法字段、未批准语义来源或 fingerprint 漂移都在输出文件创建前 fail closed。
  该入口只生成 `submitted` Decision Packet，不创建 ApprovalCase、Strategy、层文件或
  `DataProductVersion`；原始 draft 仍保持不可变。详见
  [ADR-363](architecture-decisions/adr-363-jqdltb-human-decision-submission-cli.md)。
- [x] 已将本次业务确认写入一个受证据约束的 partial submitted packet：`TBBH`、
  `preserve_source` 和 `business_steward=team:<freedo>` 已提交；`business_correction` 因更正
  artifact 待补交，`SJNF/MSSM` 因权威语义规则缺失继续隔离，其余许可、SLO 和 staging/production
  attestation 仍保持 pending。提交文件为
  [`jqdltb_business_decision_packet_submitted_2026-08-30.json`](reports/jqdltb_business_decision_packet_submitted_2026-08-30.json)，
  packet SHA-256 为 `e291d95b0d1e8de360b5e3e199a91a06a0879253f6a2df9e745ea0884165d4cf`；validation
  SHA-256 为 `50eb2d8300864cb822469303d7de3ed797204cc7649b7c2579d48324a241b0aa`，readiness
  SHA-256 为 `2d594d600359469e69aa4516aa8ec53610823b1cf57984bbda10f44b77c8d748`。该提交没有创建
  ApprovalCase、Strategy、层文件或 `DataProductVersion`，AR-0 仍为 `awaiting_business_approval`，
  source-quality 仍为 `failed`。
- [x] 已将业务确认的 `SJNF/MSSM=quarantine_until_authority_exists` 建模为显式 `deferred`
  决定，而不是继续伪装成未决定。`deferred` 只允许这两个语义 target，不携带 source field、
  semantic rule 或默认值；它仍阻断 Strategy、ApprovalCase 和产品晋级，待未来出现权威规则后可
  通过增量 packet 解析为普通 submitted 语义决定。`business_correction` 在 artifact 待补交期间
  同样标记为 `deferred`，待 ResourceVersion/SHA-256 到位后再解析。实际 packet v3 为
  [`jqdltb_business_decision_packet_submitted_v3_2026-08-30.json`](reports/jqdltb_business_decision_packet_submitted_v3_2026-08-30.json)，
  packet SHA-256 为 `9fe8d542329a428b4cf30ac0a1aa124fabcb1e18f048850e5485f4dd7a7761ee`；validation
  SHA-256 为 `04573bbe8cdd8ff562075cd327f1096e2ab864eb85cf4f699d2bb17af19832ff`，readiness SHA-256
  为 `25909bc34e2dd519f22e76114a7ab215fb290449519d0f8b166d2c49517e40cb`。详见
  [ADR-364](architecture-decisions/adr-364-jqdltb-explicit-semantic-quarantine.md)。
- [x] 已为 `business_correction=待补交` 生成可复跑的空值更正模板：脚本读取冻结的真实
  `JQDLTB.shp`，按 `TBMJ/TBDLMJ` 非正规则自动找出 6 个 `TBBH`（`486、487、576、579、861、1063`），
  输出当前源值、待填写字段和 archive/bundle/diagnostic 身份。模板状态固定为
  `draft_template_not_approved`，不包含业务更正值，也不包含 ResourceVersion 或批准 SHA-256；空模板
  传给 executor 仍会 fail closed。脚本为
  [`build_chongqing_jqdltb_business_correction_template.py`](../scripts/build_chongqing_jqdltb_business_correction_template.py)，
  输出为
  [`jqdltb_business_correction_template_2026-08-30.json`](reports/jqdltb_business_correction_template_2026-08-30.json)，
  文件 SHA-256 为 `fc3734165bb968828985dc3afdde4a211d870a66144b5ead7bfb451d41397949`；模板与漂移负向
  回归共 `24 passed`。
- [x] 同一入口新增 `--validate` 收件校验：填好的 artifact 必须恰好覆盖冻结的 6 个 `TBBH`，
  `TBMJ/TBDLMJ` 必须是有限正数，并可选复核模板中的源值；通过后只返回
  `ready_for_resource_version_registration`、artifact SHA-256 和冻结源身份。空模板命令以非零码
  fail closed；完整 6 行探针返回 `authority_state_created=false`、`data_product_version_created=false`，
  没有写控制面。该校验仍不替代 ResourceVersion 登记或业务批准。
- [x] Decision Packet 增加 `update-submitted-decision-packet` 增量入口：以后补交 correction
  artifact 或新增环境证据时，以最近一次 `submitted` packet 为 base，只允许把 pending target
  提交为新版本，保留既有决定；已 submitted/accepted 的 target 不允许覆盖，提交时间必须严格
  递增，输出前重验全部 frozen evidence/identity。该入口不创建 ApprovalCase、Strategy、层文件或
  `DataProductVersion`；提交入口与 AR-0 packet/readiness 回归共 `32 passed`。
- [x] 已补齐语义字段级隔离的 candidate-only 链：在完整 transformation 审批尚未形成时，
  可对冻结 JQDLTB 源生成 Raw→ODS→DIM→DWD→ADS 候选投影；Raw 保留源记录，候选层删除未获准的
  `SJNF/MSSM`，不写空值或猜测值，并生成逐记录逐字段的
  `gda.jqdltb_semantic_field_quarantine.v1` 内容寻址 artifact。候选证据明确为
  `quality_verdict=failed`、`promotable=false`，不调用控制面、不创建 ResourceVersion、
  ApprovalCase、QualityResult 或 `DataProductVersion`；若语义审计已 accepted/approved，候选入口
  反而拒绝执行，必须转入批准执行器。真实冻结源运行结果为 1,555 条候选记录、3,110 个
  `SJNF/MSSM` 字段隔离，源质量仍 failed；candidate fingerprint 为
  `1f92095ad78cd6128702878f353bc70a7c28779ed46ce2fdd42fe7ae05896f6a`，隔离 artifact
  fingerprint 为 `52bc15f001d5939f260d5081d5962526419fa6636183abe87c8435c064569562`。
  详见 [ADR-365](architecture-decisions/adr-365-jqdltb-semantic-field-quarantine-candidate.md)
  和 `scripts/build_chongqing_jqdltb_semantic_candidate.py`。
- [x] 已补齐更正文件的 fail-closed ResourceVersion 登记入口：
  `scripts/register_chongqing_jqdltb_correction_resource.py` 先复用更正 artifact 的冻结键集合、
  双面积正数校验和源身份校验，再通过唯一 PlatformGateway 登记内容寻址的 correction
  ResourceVersion；登记不等于批准，不创建 Strategy、ApprovalCase 或 `DataProductVersion`。
  空模板、键集合/内容不完整或 owner 未使用 typed identity 时在 Gateway 调用前失败。当前业务
  更正文件仍未补交，因此真实控制账本没有创建 correction ResourceVersion。详见
  [ADR-366](architecture-decisions/adr-366-jqdltb-correction-resource-version-registration.md)。
- [x] 已把 AR-0 的源质量修复输入整理成可直接交付业务/数据责任人的只读
  `gda.jqdltb_source_quality_repair_candidate_packet.v1`：集中列出 10 项待决事项、`quarantine`
  与 `business_correction`/面积偏差策略的聚合影响、`SJNF/MSSM` 语义证据要求，以及每个选项
  可关闭和仍保留的 blocker。packet 绑定 manifest、baseline、diagnostic、semantic audit、impact
  preview、readiness 和 draft decision packet 的 SHA-256；所有选项保持
  `pending_business_evidence`，不会创建 Strategy、ApprovalCase、更正 artifact、层文件或
  `DataProductVersion`。新增 `--validate` 会重新读取全部引用证据并在身份漂移时 fail closed。
  当前 packet SHA-256 为 `d953267afb5636b0f5c4071674283daf9162c33ee80671fbdc0528d618718523`，AR-0
  仍为 `awaiting_business_approval`，source-quality 仍为 `failed`。详见
  [ADR-360](architecture-decisions/adr-360-jqdltb-source-quality-repair-candidate-packet.md)。
- [x] 已把批准后的 JQDLTB executor 运行证据收紧到真实 source identity 和完整 candidate quality：真实
  `.shp` 输入在读取前后各复核 sidecar bundle SHA-256，窗口内字节变化或与 approved contract 不一致
  均在输出目录创建前 fail closed；物化后执行 10 项 `post_transformation_candidate_full_dataset`
  检查，空物化集合、几何无效、双面积非正、派生字段缺失、非法 quarantine reason 或记录对账失败
  均不能得到 passed。证据记录 source identity verification、质量规则版本和逐项 metrics；不会因此
  创建 DataProductVersion；面积策略按物化阶段显式处理计数与偏差总数精确对账，不能仅凭策略名称
  或最终 quarantine reason 通过。聚焦回归 `43 passed`，详见
  [ADR-361](architecture-decisions/adr-361-jqdltb-post-transformation-quality-and-source-identity.md)。
- [x] 已修复一个会在 pytest collection 阶段直接 `exit(1)` 的外部 OBS 测试入口：未配置
  Huawei OBS 凭据时显式 `skip`，配置后仍执行真实 `head_bucket/list_objects_v2`；这项改动不改变
  任何平台权限或生产状态。当前 `data_agent/` collection 已能继续并报告缺失的可选依赖（主要是
  `h5py`/`fitz`）而不是被导入副作用中止，AR-0 结论仍以定向主链回归为准。
- [x] 已把 collection 依赖缺口收敛为可审计的安装合同：`h5py==3.16.0` 进入
  `scientific`/`full` profile 和锁定的 `requirements.txt`，`PyMuPDF==1.27.2.2` 进入
  `documents`/`full` profile；CI 安装后执行两者的 import smoke check，并新增无第三方导入的
  profile contract test 防止声明漂移。Lite profile 不安装这两个重量依赖，GWM/GeoTransport
  与标准 PDF 抽取必须显式选择对应 profile。本轮已补齐开发环境中的两个锁定依赖，
  `data_agent` 全量 collection 成功收集 `13,953` 个测试；这项合同修复不冒充 AR-0
  业务批准或生产完成。详见
  [ADR-362](architecture-decisions/adr-362-runtime-dependency-profiles.md)。
- [x] 已将同一依赖边界同步到 Windows standalone 交付档：`production` wheelhouse 固定
  `litellm>=1.84,<2.0`、`h5py==3.16.0` 和 `PyMuPDF==1.27.2.2`，`core` 保持不含两个可选
  读取器；profile contract test 会解析 `-r` 链接并阻止版本或档位漂移。该修复只证明交付
  合同可复核，未在本机生成 vendor wheelhouse 或声称离线 bundle、JQDLTB 产品版本已经发布。
- [x] Windows bundle builder 进一步读取 wheel 内 `dist-info/METADATA`，按直接依赖的完整
  specifier 验证名称和版本；错误版本的 wheelhouse 在 ZIP 创建前 fail closed。正/反例合同
  测试已覆盖 `litellm` 下限和两个新增可选读取器，避免仅凭文件名或包名误放行。
- [x] 已将 JQDLTB 的真实 DolphinScheduler 运行事实编译为可验证 attestation：3.4.2 sandbox health、workflow
  deployment、PlatformRun dispatch、provider `SUCCESS`、authoritative quality `failed`、终态 Run 和
  `data_product_version_created=false` 均绑定冻结 source/definition/run identity。报告为
  [`jqdltb_dolphinscheduler_runtime_2026-08-26.json`](reports/jqdltb_dolphinscheduler_runtime_2026-08-26.json)，
  `report_sha256=b8d855d892570cd6c09f6dbdbc25601cf2c0d5f2866037f8b4331090326bdbe6`。该报告已在
  GDA 控制账本登记 evidence Artifact `e0836289-92bf-5d49-bc73-6f93add58fd8`；同一运行证据第二次登记
  返回 `artifact_created=false`，内容 SHA-256 保持 `d85f488852628e584eba006205e8120b38931a717b38d80de09ae3052ce57d5d`。
  该证据关闭 `dolphinscheduler_runtime_not_configured`，但只覆盖本地单节点 sandbox；质量失败、业务/许可审批、
  staging/production HA/RPO/RTO 和产品发布仍保持阻断。
- [x] 已补齐 JQDLTB 产品版本到 GIS serving 的第二阶段绑定合同：新增 typed
  `JqdltbServingReleaseBinding`，把 current `DataProductVersion` 的 product/version/manifest、ADS
  output、`GISServiceDefinitionVersion`、`LayerDefinitionVersion`、`MVTServingProjectionVersion`、
  `ServiceReleaseBinding` 和 exact active `GISServiceSLOBinding` 收敛为一个 fingerprint。migration 235
  建立独立 append-only serving authority、RLS、不可变触发器和 Gateway recorder/read；同一版本重放
  幂等，跨租户、manifest、ADS output、layer、MVT、service release 或 SLO 漂移 fail closed。这个绑定
  明确放在 DataProductVersion 成为 current 之后，避免 GIS definition 要求 current version 与产品首次
  发布形成环依赖。122 项聚焦 Python/Gateway 回归和完整 GIS control-plane + SLO authority 的
  disposable PostgreSQL 认证已通过；认证覆盖首次写入、幂等重放、manifest/ADS output/SLO
  漂移拒绝、跨租户零行、RLS 强制和直接 update/delete 拒绝，证据类为 `synthetic_disposable`；
  可重复入口为 `scripts/certify_jqdltb_serving_release_binding.py`。
- [x] 已把 serving binding 接入 GIS endpoint promotion，而不是保留为旁路台账：migration 236 仅对
  `gda.jqdltb_mapping_binding.v1` 产品版本启用 exact binding gate，缺少 binding 或 product/version、
  manifest、service definition、layer、MVT projection、service release 任一身份漂移时以 SQLSTATE
  `23514` 拒绝 endpoint activation；通用 GIS 服务不受影响。disposable 认证已覆盖完整 synthetic
  PlatformRun/deployment settlement：无 binding 被拒绝，登记 exact binding 后 endpoint state version
  为 `1`。这仍只是控制面与合成环境证据，尚无真实重庆 JQDLTB 产品版本、PostGIS serving artifact、
  SLO activation 或生产 endpoint。详见 [ADR-320](architecture-decisions/adr-320-jqdltb-serving-release-binding.md)。
- [x] 已补齐 serving projection 到真实 PostGIS relation 的物理 attestation：migration 237 由数据库
  catalog 读取 relation OID/kind、geometry type/SRID/维度、feature-id 数据类型和属性列，写入不可变
  `mvt_serving_relation_attestation` 并生成 relation schema SHA-256；JQDLTB endpoint promotion
  现在同时要求 attestation 存在且当前 relation 与 attestation 完全一致。disposable PostGIS 认证已
  覆盖“exact binding 但无 attestation”返回 `23514`、登记后 activation 成功，以及登记后属性列漂移
  再 activation 返回 `23514`。证据等级仍为 `synthetic_disposable`，不替代真实业务 artifact 或生产
  endpoint。详见 [ADR-321](architecture-decisions/adr-321-mvt-serving-relation-attestation.md)。
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

**2026-08-12 staging candidate 交付基线（已验证切片）**：

- [x] staging candidate workflow 改为仅允许 `main` 手工触发的非晋级验证合同：一次性 PostGIS 候选库
  完整重放 migration，admin/application ledger fingerprint 对账，完整 Python 回归、严格 staging
  platform snapshot 与 Docker image 构建均要求绑定同一 source revision；候选镜像后续必须绑定 GHCR
  immutable digest 和 GitHub OIDC provenance attestation。本地已验证 workflow/证据合同，尚未声称远端
  GHCR push 或 OIDC attestation 已真实执行。
- [x] migration runner 的实际连接合同已统一为 `POSTGRES_HOST/PORT/DATABASE/USER/PASSWORD`；真实候选库
  返回 `status=in_sync`、156/156 applied，catalog/database fingerprint 均为
  `85c33b9811a5e4bdd17689ccf54d1ee24cf90aa7bea3da665c6cfd06b7e3b64b`，admin/application
  compare 为 `match=true`。
- [x] AR-0 platform truth 已登记当前配置读取和后台运行机制。新增识别 Abu Dhabi 模型线程池、受限
  ArcGIS snapshot 页 fan-out 和内置 ingestion worker；前两项业务执行机制与 ingestion worker 的
  process-local 调度均未取得新的状态权威，需替换的 runtime 继续列为 production blocker。静态合同、
  migration/deployment profile 与 candidate/registry/provenance 合同扩大回归 `67 passed`，Ruff 和
  diff check 通过；严格 staging snapshot 返回 `config.valid=true`、`startup_allowed=true`、runtime
  inventory `valid` 且 primitive baseline 匹配。
- [x] production CD 已删除只打印 canary/full rollout 命令的伪部署成功路径；在缺少同 revision 的 live
  staging deployment、workload identity、health/golden slice 和批准证据时固定 fail closed。
- [ ] 本切片只证明 ephemeral CI candidate、registry subject 和 provenance 合同，不代表镜像已部署到
  live staging，也不构成 production promotion authority；受保护环境 runner 的 live observation、
  rollback/reconcile、批准 SLO/RPO/RTO 和客户环境证据仍未完成。
- [ ] AR-0 整体仍为 `in_progress`：live staging、production、客户环境 fingerprint 与批准的
  reconcile 证据，以及 config/provider/capability/SLO 等其余退出门尚未完成。

**2026-08-13 live staging 观察边界（已验证切片）**：

- [x] 新增只读 live staging collector/verifier 和 ADR-029。collector 只投影 Kubernetes、migration
  ledger、platform snapshot、`/health`、`/ready` 的固定白名单，不读取 Secret；verifier 将 source
  revision、candidate、registry digest、cluster/namespace/Deployment/Pod/EndpointSlice 身份、schema、
  config、environment-access baseline、runtime 与 golden slice 绑定为一份 fail-closed evidence。
- [x] live verifier 的完整离线 fixture 可得到 `live_staging_verified=true`，但 v1 无论验证结果如何均保持
  `promotion_authority_verified=false`、`production_promotion_allowed=false`。环境访问指纹漂移、parse
  error 或 golden-slice 绑定漂移均会阻断；candidate/live/registry/provenance/platform truth 相关回归
  `39 passed`，新增文件 Ruff 与 diff check 通过。
- [x] 已对 `docker-desktop` 的现有 `gis-agent` namespace 完成真实只读采集，没有修改 Deployment。
  collection 和 health 通过：应用 1/1 Ready、EndpointSlice 对齐、service-account token 自动挂载关闭、
  `/health` 与 `/ready` 正常、migration ledger 97/97 in sync、runtime primitive baseline 匹配。
- [ ] 当前实例被正确判定为开发部署而非 live staging：镜像仍为 `gis-data-agent:dev`，profile 为
  `development`，缺 source revision、candidate/environment/platform fingerprint 注解，旧镜像未输出
  environment-access baseline，也没有 golden-slice。GitHub 上没有成功的 staging candidate run；最近记录
  为 workflow-level `failure` 且无 job，因此不存在可用于同 revision 绑定的 candidate/registry artifact。
- [ ] 下一项唯一晋级门是建立受保护的真实 staging：先让 `main` 的 candidate workflow 成功产出
  GHCR immutable digest、OIDC provenance 和 candidate artifact，再用独立 staging overlay 部署同一 digest
  并采集 golden slice。现有开发 namespace 不作为 staging 原地覆盖；在此之前 AR-0 保持
  `in_progress`，production promotion 继续 fail closed。

**2026-08-13 protected staging release admission（已验证切片）**：

- [x] 新增 `gda.staging_release_evidence.v2`，把 candidate、registry subject 与 protected provenance
  收敛为接触集群前唯一 release bundle。builder 会重新验证三份上游 evidence 的稳定内容，而非只信
  `status`；同一 source/verifier revision、GHCR repository/digest/image、candidate/registry/provenance
  fingerprint、OIDC policy 以及 schema/config/environment-access/runtime fingerprint 必须全部一致。
- [x] admission 只授予 `staging_apply_allowed=true`，明确保持 `staging_deployed=false`、
  `live_cluster_verified=false`、`golden_slice_verified=false`、`production_promotion_allowed=false`。
  candidate 内容、registry digest、provenance policy 或交叉引用漂移均已验证 fail closed。
- [x] protected provenance workflow 现在从同一个成功 candidate run 下载 candidate 和 registry artifact，
  独立验证 OCI attestation 后构建 release bundle；provenance 与 release JSON 分别进行 artifact
  attestation，并上传包含 candidate/registry/provenance/release 四份 JSON 的完整 bundle。该 workflow
  仍无 `kubectl`、Helm 或集群写权限。
- [x] candidate/registry/provenance/release/live/platform truth 扩大回归 `44 passed`；新增模块及相关
  文件 Ruff、YAML parse、diff check 通过。
- [ ] 本切片没有声称远端 candidate/provenance workflow 已成功执行，也没有部署 staging。现有
  `k8s/base` 同时包含占位 Secret、本地 Postgres/MinIO 和开发配置，不能作为真实 staging 原样 apply。
  下一门是建立独立的 application workload staging overlay，由环境方预置 namespace、Secret、数据服务
  与 workload identity；deploy workflow 只能消费并验证已 attested release bundle，然后执行 migration、
  immutable rollout、live observation 和真实 golden slice。

**2026-08-13 protected staging workload deploy contract（已验证切片）**：

- [x] 新增 workload-only renderer，固定输出 preflight、migration、application 三个阶段，只管理短生命周期
  preflight Job、两个 ServiceAccount、单次 migration Job、应用 Deployment 和 Service；不创建 Namespace、
  ConfigMap、Secret、PostgreSQL、Redis、对象存储、Ingress 或 worker，也明确拒绝开发 namespace
  `gis-agent`。所有容器镜像都来自 release bundle 的同一个 GHCR `@sha256:` subject，并只按名称引用环境
  预置的 image-pull Secret。
- [x] preflight 使用候选镜像和环境实际配置生成最小脱敏 platform snapshot，只保留 config、environment-
  access、runtime 与 platform fingerprint/status；不输出 config entries、环境访问路径或 runtime inventory，
  不挂载 Kubernetes API token，也不持有 schema admin credential。真实 platform fingerprint 通过后才渲染
  migration/application manifest。
- [x] migration Job 是唯一 schema writer；应用 init container 只用 application role 轮询 migration ledger
  `in_sync`，app/init container 均显式清空 admin credential。Pod template 同时绑定 source、candidate、release、
  schema、environment-access、runtime 和真实 platform fingerprint；live verifier 还会要求运行镜像精确等于
  attested release image，而不只是任意合法 digest。
- [x] 新增受保护 `staging-live` deploy workflow：按精确 provenance run-id 下载固定名 release bundle，验证
  release artifact attestation 后从 bundle 解析并检出 verifier revision，核对受保护 cluster/namespace UID，
  依次执行 server dry-run、preflight、migration、immutable rollout 和只读 live collection。工作流不读取
  Secret/ConfigMap 内容；RBAC preflight 还要求 runner 对 Secret、ConfigMap 和 namespace 没有管理权限，
  且工作流没有 production 权限。
- [x] 全部 staging evidence/renderer/workflow 合同回归 `42 passed`，Ruff、workflow YAML parse 和 scoped
  diff check 通过。生成的三个 manifest 已完成离线 YAML/资源边界验证；本机 kubectl v1.36 即使
  `--dry-run=client --validate=false` 仍强制 API discovery，空 kubeconfig 只访问 `localhost:8080` 并失败，
  因此没有借用或修改 Docker Desktop 集群来制造本地 dry-run 成功。
- [ ] 这仍不是“staging 已上线”：远端 candidate/provenance/deploy workflow 尚未有成功执行证据，受保护
  `staging-live` runner、namespace/ConfigMap/Secret/数据服务及 cluster/namespace UID 仍需环境方提供。当前
  deploy workflow 在缺真实 golden slice 时会上传 observation 后固定失败，且
  `production_promotion_allowed=false`；下一道唯一门槛是真实环境首次运行和权威 golden slice 生成。

**2026-08-13 protected staging golden slice contract（已验证切片）**：

- [x] 新增只读 `staging_golden_slice` verifier，不自动选择最近成功 Run，只接受环境冻结的 tenant、
  capability、definition version、input ResourceVersion 和显式 Run ID。它在 tenant RLS 下使用
  `gda_control_gateway` 和 read-only transaction，要求唯一的 evidence-gated `succeeded` 终态事件、真实
  DolphinScheduler success observation、content-bound output Artifact、独立 passed QualityResult 与
  input-to-output LineageEvent，并重新计算 Run success 和 quality fingerprint。
- [x] golden evidence 进一步绑定当前 staging Pod 之后的 submitted/started/terminal/evidence 时间，以及
  source revision、Deployment UID、镜像 digest、schema/config/environment-access/runtime、tenant、
  capability、definition fingerprint、input/output ResourceVersion。历史成功 Run、跨 capability/definition/
  input 复用、陈旧 Run、同 workload 自评质量或任一指纹漂移均 fail closed。
- [x] 新增独立、手工触发的 protected golden workflow。rollout workflow 继续在缺 golden slice 时失败并
  上传 attested observation、candidate 和 release；数据责任人完成 post-rollout Run 后，验收 workflow 按
  精确 deployment run ID 下载证据、校验 release/collection attestation、检出 release 指定 verifier revision、
  使用无 workload/Secret/ConfigMap 写权限的 observer 身份重新采集并生成 golden evidence。完整通过仍固定
  `promotion_authority_verified=false`、`production_promotion_allowed=false`。
- [x] 全部 staging 相关回归扩大为 `53 passed`，Ruff 与 workflow YAML parse 通过；数据库权限审查确认所需
  表均由现有 `gda_control_gateway` tenant-scoped SELECT 覆盖，角色为 `NOBYPASSRLS`，生成器显式设置只读事务。
- [ ] 该切片关闭的是“如何从真实账本生成 golden slice”的代码与权限合同，不是 staging 已验证。GitHub 仍
  没有成功 candidate/provenance/deploy run，环境方也尚未提供 protected runner、namespace/config/secret/
  数据服务、冻结的 golden identities 或 post-rollout Run；在真实 artifact attestation 生成前，AR-0 保持
  `in_progress`，production promotion 继续禁止。

**2026-08-13 protected staging readiness checkpoint（已验证切片）**：

- [x] 新增机器可读、只读的 `staging_environment_readiness`。它分别检查远端四段 workflow 是否与本地已审
  合同一致、`staging-provenance`/`staging-live` 的 reviewer/no-admin-bypass/protected-branch policy、在线
  `[self-hosted, linux, gda-staging]` runner、所需 environment variable/Secret 名称、显式 Kubernetes identity
  observation，以及 candidate/provenance release/deploy observation/golden 四阶段 run + artifact 是否存在。
  报告不输出 variable/Secret 值，默认不调用 Kubernetes，也不会把已配置 UID 当成已验证集群。
- [x] 真实 GitHub 只读检查得到 `status=blocked`：远端 `main` 尚未包含当前完整四段 workflow 合同；只有
  `staging-provenance` environment，且已有 reviewer、admin bypass 已关闭、protected branch policy 已设置、
  `GDA_STAGING_PROVENANCE_PROTECTED=true`，repository ruleset 也已使 `main` 处于 protected 状态；但
  `staging-live` 不存在，repository self-hosted runner 数为 0；
  candidate/provenance release/deploy/golden artifact 均不存在。最近 candidate run 仍为
  `31580276845`，由 feature branch push 触发、workflow-level failure 且无 job，不是合格的 main 手工 candidate。
- [x] 聚焦回归 `5 passed`，Ruff 与 Python compile 通过；报告始终保持 AR-0 `in_progress` 和
  `production_promotion_allowed=false`，deploy workflow 的预期 fail-closed conclusion 只有在同一 run 保留
  observation artifact 时才记为该阶段已观察。
- [ ] 最前置动作已从笼统的“搭 staging”收敛为可执行顺序：先让经审查的四段 workflow 合同进入 `main`；
  再由环境责任人创建/冻结 `staging-live`、配置双 kubeconfig 与固定 identity/数据身份、提供受限 runner；
  然后才能按 candidate -> provenance release -> deploy observation -> post-rollout golden 顺序产生真实证据。
  本次未修改 GitHub environment/secret/runner、未触发 workflow、未访问 Kubernetes，因此不声称 staging 完成。

**2026-08-13 protected golden verifier revision boundary（已验证切片）**：

- [x] 修复 golden workflow 的 verifier revision 混淆。原合同虽 checkout 了 release 绑定的 protected-source，
  但通过 `kubectl exec ... python -m data_agent.staging_golden_slice` 实际运行的是候选镜像内代码，受保护 verifier
  没有真正持有账本查询和判定权。现在候选容器不再 import 或执行该应用模块。
- [x] 新增受保护 `staging_golden_ledger.sql`：只允许 `/usr/bin/psql -X -qAt` 在 `BEGIN READ ONLY`、
  `SET LOCAL ROLE gda_control_gateway` 和 `app.current_tenant` RLS 下按显式 tenant/Run/capability 查询，输出固定
  `gda.staging_golden_ledger_export.v1`。psql 参数使用 literal quoting，查询仍要求 output ResourceVersion 内容绑定、
  独立 quality evidence、input lineage 和终态 evidence set；0 行或多行都由 verifier fail closed。
- [x] ledger JSON 通过 stdout/stdin 直接进入 runner 上 release 绑定的 protected Python verifier，不落 self-hosted
  runner 文件系统、不进入 artifact。verifier 已去除 SQLAlchemy、应用 DB engine 和 `platform_contracts` 依赖，
  用标准库重新计算 canonical Run-success/quality fingerprint，并只接受完整字段闭集；最终只 attest allowlisted
  collection、golden slice 与 live verdict。
- [x] golden 聚焦回归扩大为 `16 passed`，覆盖字段注入、0/多行、显式 ledger/collection CLI、SQL read-only/RLS/
  参数化合同和 workflow 管道；Ruff、Python compile、YAML parse 与 scoped diff check 通过。
- [ ] 该修复关闭的是候选应用 Python 控制验收 verdict 的问题，不是独立 observer runtime。`psql` 仍运行在候选
  容器并使用应用数据库连接；在 production promotion 前仍需由环境方提供独立、digest-bound observer image/
  workload identity 或等价隔离证明。当前 AR-0、真实 staging 和 production gate 状态不变。

**2026-08-13 protected release source bundle readiness（已验证切片）**：

- [x] 修复 staging readiness 只比较四段 workflow YAML 的假就绪风险。candidate/provenance/deploy/golden
  workflow 在受保护主线或 release 绑定 revision 上还会执行 evidence builder、release verifier、preflight/manifest
  renderer、live collector/verifier 及 golden ledger/verifier；仅同步 YAML 而缺失或漂移这些执行源会在 workflow
  启动后才失败，不能视为 repository contract ready。
- [x] `gda.staging_environment_readiness.v2` 现在将四段 workflow、九个受保护执行源和 GitHub 元数据读取完整性
  分成三个机器门：`repository_workflows_ready`、`protected_release_sources_ready` 和
  `repository_metadata_reads_complete`。九个源覆盖 candidate、registry、provenance、
  release、platform preflight、workload manifest、live evidence、golden verifier 和只读 ledger SQL；报告逐文件只
  暴露存在性与 digest 是否一致，不输出源码、变量值或 Secret 值。
- [x] 真实 GitHub 只读复核继续得到 `status=blocked`：远端缺 deploy/golden workflow；九个受保护源均未与本地
  已审合同一致，其中 platform preflight、workload manifest、golden verifier 和 ledger SQL 在远端 `main` 不存在。
  `staging-live` 仍不存在，repository runner 仍为 0，最近 candidate 仍是 run `31580276845` 的 feature-branch
  push/no-job failure。真实报告 fingerprint 为
  `c077c714a3f3573915b4d8bbe42450c5f3c2871a748b27b305c977853f3842ec`；
  `repository_metadata_reads_complete=true`，因此这些阻塞是已观察的远端事实，不是 API 部分读取造成的未知状态。
- [x] GitHub 404 已与网络/权限/分页读取失败分离：已确认 workflow/source 不存在只阻塞对应合同门，真正的
  metadata read failure 才阻塞 `repository_metadata_reads_complete`，避免把“缺文件”和“没有看清”混为一谈。
- [x] readiness 聚焦回归扩大为 `9 passed`，完整 staging 合同回归 `68 passed`；Ruff、Python compile、四份
  workflow YAML parse 和 scoped diff check 通过。
- [ ] 当前最前置动作修正为：将经审查的四段 workflow **连同九个受保护执行源**作为一个 release-source bundle
  进入远端 `main`，再配置 `staging-live`/runner/identity 并运行真实证据链。本次未提交或推送、未修改 GitHub
  environment/secret/runner、未触发 workflow、未访问 Kubernetes；AR-0 保持 `in_progress`，production promotion
  继续禁止。

**2026-08-18 protected staging readiness recheck（部分远端观测）**：

- [x] 只读报告观察到 `main` 上 candidate `31862363442`、provenance/release `31862984294` 和
  intentional fail-closed deploy `31863077257` 均已出现，三者绑定 source revision
  `5fffc854185687133cbf77f9324a834ee77ae130`；candidate、release 和 deploy observation artifact metadata
  门均为 `ready=true`。
- [x] `staging-provenance` 与 `staging-live` environment 均已存在，均有 required reviewer、protected-branch
  policy 和 admin bypass disabled；`GDA_STAGING_KUBECONFIG_B64` 与 observer secret 名称也已登记。
- [ ] 当前远端观测到两个 environment 的 `prevent_self_review=false`，因此本地 readiness 已将
  `protected_environment_metadata_ready` fail closed；环境责任人必须修正该保护规则后才能进入真实证据链。
- [ ] prevent-self-review gate 收紧前的本次报告 fingerprint 为
  `ae2bad7c6509caeb46b10ea231c2787de62f704f58ec05f970a15b6410544659`，但
  `repository_metadata_reads_complete=false`，因此这些结果只能作为部分观测，不能替代完整远端复核或
  content-bound artifact verification。
- [ ] 当前仍阻塞于：本地十源合同与远端 `main` 漂移（新增 `staging_platform_snapshot.py` 也必须纳入同一
  bundle）、runner 无合格实例、staging-live 缺 4 个 golden identity variables、无独立 Kubernetes identity
  observation，以及尚无 post-rollout golden evidence；`production_promotion_allowed=false` 保持不变。

**2026-08-19 runtime privilege truth checkpoint（真实开发库已阻断）**：

- [x] 新增只读 `gda.runtime_privilege_contract.v1` verifier，将 migration ledger truth 与当前 PostgreSQL
  ACL truth 分开。它通过 application login 读取 `pg_catalog`，精确验证 runtime login 到
  `gda_control_gateway` 的成员关系、gateway 的 `NOLOGIN/NOSUPERUSER/NOINHERIT/NOBYPASSRLS` 等属性、
  `gda_control` schema USAGE、DataProduct/Incident 5 张核心表的最小且不超额权限，以及
  `transition_data_incident(text,uuid,integer,text,text,text,jsonb)` 的 EXECUTE/Public revoke 合同；报告不含
  credential、只生成确定性 contract/evidence fingerprint，也不会自动执行 GRANT。
- [x] staging candidate workflow 已在 application-role ledger check 后、集成测试结束再各执行一次 runtime
  privilege admission，最终 artifact 保存 post-test 状态；任何
  missing object、missing/excess privilege、Public exposure、role membership 或 role attribute drift 都会在
  镜像发布前 fail closed，脱敏报告作为 candidate artifact 独立保留。fake SQLAlchemy connection 回归与
  staging workflow 合同共 `14 passed`，Ruff、Python compile 和 scoped diff check 通过。
- [x] 真实本地 PostGIS 16 以 `agent_user` 运行得到 `status=blocked`：runtime/gateway 角色、membership、
  gateway attributes、schema、`data_incident`、`data_incident_event` 和 Incident transition function 均
  `in_sync`；`data_product` 缺 `INSERT/SELECT/UPDATE`，`data_product_version` 与 `data_product_event`
  均缺 `INSERT/SELECT`。evidence fingerprint 为
  `0badd33679452abff183a59d7fa4f9edbab4c4167fefe2f8e18986fcb6361956`。报告文件含观察时间戳，
  不再把不稳定的文件 SHA 写入路线；稳定 evidence fingerprint 才是后续绑定字段。
- [x] 初次观测确认 migration `100_data_product_registry` 的 ledger checksum 与仓库文件完全一致，但 live ACL
  已漂移，证明“migration applied/checksum equal”不能替代 runtime privilege equality；当时未静默修复权限，
  先完成了 actor/变更路径定位，后续处理见下方 ACL drift root-cause and repair checkpoint。AR-0 仍保持
  `in_progress`，staging/production admission 继续关闭。

**2026-08-19 ACL drift root-cause and repair checkpoint（本地开发库已收敛）**：

- [x] 根因已复现并定位：`test_platform_gateway_postgres.py` 原先在共享 `DATABASE_URL` 上重放
  `094_platform_control_gateway.sql`；第二个测试因 DataProduct 表已存在而跳过 `100_data_product_registry.sql`，
  但仍提交了 094 的 schema-wide gateway revoke，随后只由 Incident migration 恢复 Incident ACL，留下三张
  DataProduct 表缺权。两个 PostgreSQL gateway 测试现改用随机临时数据库，结束时 `DROP DATABASE ... WITH (FORCE)`；
  真实 PostGIS 回归 `2 passed`，临时数据库零残留，共享库 privilege fingerprint 前后均为原 drift fingerprint。
- [x] 新增 migration `189_data_product_gateway_privilege_repair.sql`：先确认 gateway role 与三张表存在，再
  `REVOKE` Public/旧 gateway ACL 并精确重授 migration 100 的最小权限；不创建 login、不改变 membership、不做
  broad schema grant。一次性 PostgreSQL drift -> 189 -> in_sync 回归 `1 passed`。
- [x] migration authority 已在本地开发 PostGIS 应用 189，ledger 返回 `189/189`、catalog/database fingerprint
  `8a7c5424d6f12da65885756bb767dd4e5c377654aba9f101ce9d316dbfa5f262` 且 `status=in_sync`；随后以
  `agent_user` 复核 ledger 也为相同的 `189/189` fingerprint；只读运行时 verifier 得到
  `status=in_sync`、`admission_allowed=true`、drift `[]`，新 evidence
  fingerprint 为 `b46664b711e4c7edb4e141477809abaa2081b9284836631b584aa127dfd342f6`。
- [x] 将隔离约束提升为共享 pytest fixture `isolated_postgres_url`，覆盖 6 个会重放 migration SQL 的真实
  PostgreSQL 测试；全套回归 `6 passed`，之后再次读取共享库仍为同一 `in_sync` fingerprint，临时数据库无残留。
- [ ] 189 只修复已观测的本地开发库漂移，不证明 staging/production/customer 环境没有同类 ACL 漂移；candidate
  workflow 的前后 runtime privilege gate 仍是必需条件，下一步应在每个目标环境用独立 application-role observation
  复验，再决定是否允许环境级 promotion。AR-0 仍保持 `in_progress`。

**2026-08-19 runtime privilege evidence binding checkpoint（合同已完成，真实环境仍待证据）**：

- [x] runtime privilege observation 已从 candidate artifact 旁路提升为 v2 evidence contract。candidate、registry、
  release、Deployment annotation、live collection 和 live evidence 均绑定同一
  `runtime_privilege_fingerprint`；registry/provenance evidence 已分别升级为
  `gda.staging_registry_evidence.v2`/`gda.staging_provenance_evidence.v2`，并将该 fingerprint 纳入自己的
  stable content fingerprint；旧
  candidate/registry/provenance/release/live v1 artifact 缺字段时 fail closed。
- [x] candidate verifier 要求 `agent_user` 只读观察、`gda_control_gateway` 固定角色属性、完整对象 observation
  集无 drift/Public exposure，并重算 runtime privilege stable content fingerprint；篡改 ACL 报告内容即使保留
  64 位 fingerprint 也会被拒绝。
- [x] provenance 与 release verifier 现在重新计算并交叉校验 candidate、registry、provenance 三方的
  runtime privilege fingerprint；registry 或 provenance artifact 被替换/篡改时，在 OCI attestation 或
  protected staging apply 之前 fail closed。
- [x] protected staging workload 的 migration 完成后，application init gate 用 application role 重新执行
  `data_agent.runtime_privilege_contract`；live collector 与 golden verifier 同样强制采集并校验 runtime ACL，
  不读取 Kubernetes Secret/ConfigMap 值。staging/runtime privilege 聚焦回归 `76 passed, 1 skipped`，Ruff、Python compile、workflow YAML
  parse 和 diff check 通过。
- [ ] 本地代码合同和开发库 evidence 已完成，但 GitHub candidate/provenance/deploy/golden 尚未形成新的 v2
  真实 artifact 链，staging/production/customer application-role observation 仍缺失；本 checkpoint 不改变
  AR-0 `in_progress`、`production_promotion_allowed=false` 或“不得把本地通过宣称环境完成”的边界。

**2026-08-19 protected staging readiness recheck（远端链条部分已观察）**：

- [x] 只读 GitHub readiness 观察到 `main` 已存在四段 staging workflow；candidate run
  `31862363442`、provenance/release run `31862984294` 和 deploy run `31863077257` 绑定同一 source
  revision `5fffc854185687133cbf77f9324a834ee77ae130`。candidate、provenance/release 和 deploy
  observation artifact metadata 均已出现。
- [x] deploy run 的 preflight、migration、immutable application rollout、replica/EndpointSlice convergence、
  health/readiness、live collection 和 fail-closed verifier 均成功；最后的 promotion-boundary step 因没有
  post-rollout golden slice 按设计失败。该失败不是部署成功的替代品，也不允许 production promotion。
- [x] readiness collector 现在将脱敏 `collection_errors` 纳入
  `gda.staging_environment_readiness.v2` 报告；GitHub API 部分读取失败时，报告明确区分“读失败”和“资源缺失”，
  不再只输出一个无法行动的 `repository_metadata_reads_complete=false`。
- [ ] 远端仍缺：四段 workflow/受保护 source 与当前本地 v2 bundle 完全一致、两个 environment 的
  required reviewer/protected branch/prevent-self-review/no-admin-bypass 全部满足、在线 `gda-staging` runner、
  Kubernetes identity observation、4 个 golden identity variables 和成功 golden Run。最近一次重采集又遇到
  GitHub API connectivity failure，因此不能把部分读取结果升级为完整 readiness；AR-0 与 production gate 保持不变。

**2026-08-19 MetricObservation vertical slice（本地可运行闭环）**：

- [x] 新增 `gda.metric_observation.v1` 追加写入合同：成功且已完成的 metric `PlatformRun` 才能投影，观测固定绑定
  metric/projection version、两个 fingerprint、query observation、结果 Artifact 和 output ResourceVersion；业务值、维度、
  时空窗口和空间资源引用均参与稳定 fingerprint，时间戳采用 UTC canonical 格式。
- [x] 新增 migration `192_metric_observation_projection`：表启用强制 RLS 和 immutable trigger，gateway 只有 `SELECT`，
  通过受控 `record_metric_observation(...)` SECURITY DEFINER 函数追加写入；函数拒绝失败/未终态成功 run、跨租户、重复
  或冲突投影，结果 Artifact 仍保持原始事实，不复制结果内容。
- [x] 新增 API：`POST/GET /api/platform/v1/metric-query-runs/{run_id}/observation`。POST 可由 run 提交者或平台 operator
  触发，实际记录身份固定为 `workload:metric-observation-projector`；同一 run 重放必须给出完全相同的 projection。
- [x] 业务投影 contract、路由、migration catalog、metric、profile、staging 和 runtime privilege 组合回归
  `175 passed, 1 skipped`，Ruff、Python compile 和 migration discovery 通过（当前 catalog `192` 项，最新为
  `192_metric_observation_projection`）。
- [ ] 当前只证明代码合同与隔离回归，尚未在 staging/production/customer application-role 上形成真实 observation artifact；
  不改变 AR-0 `in_progress`、`production_promotion_allowed=false` 或 protected staging golden 缺口。

**2026-08-19 database connection capacity slice（部署合同已完成）**：

- [x] PostgreSQL 服务端连接上限已从镜像隐含默认值改为部署可调：Compose 使用
  `POSTGRES_MAX_CONNECTIONS`（默认 `150`）和 `POSTGRES_SUPERUSER_RESERVED_CONNECTIONS`，Kubernetes 通过
  ConfigMap 驱动同一启动参数（当前基线 `200/5`）；修改后重启 PostgreSQL 即可生效，不需要重建镜像。
- [x] API 同步/异步池和后台 worker 分开预算：Compose API 默认峰值为 `20 + 20` 个同步连接及 `10` 个异步连接，
  普通 worker 收敛为 `5 + 0` 及 `1`；Martin 池从 `20` 收敛为 `10`。配置支持进程倍数和运维预留，非法负数、
  越界和异步最小值大于最大值会明确失败，显式 `max_overflow=0` 已修复为真实生效。
- [x] Kubernetes API 按 HPA `maxReplicas=8` 单独收敛为每 Pod 同步 `6 + 2`、异步 `2`，API 全扩容理论峰值
  为 `80`，不会把 Compose 单实例池配置直接乘以 8；ingestion/outbox/notification/metric worker 继续使用小池。
- [x] `/api/admin/system-info` 的数据库子系统现在返回脱敏的实际 `max_connections`、两类 reserved slots、当前连接、
  剩余连接、利用率、进程池峰值和声明预算状态；现有 Prometheus pool 使用指标继续保留，不返回 URL 或凭据。
- [x] 本地 `main-compose-dev` 已真实应用：重建前 PostgreSQL 为 `max_connections=100`、superuser reserve `3`，
  `pg_stat_activity` 观察到 `104` 条记录且无活动业务查询；保留 `gisdataagent_pgdata-arm64` named volume 重建数据库容器后，
  实际值为 `150/5`、连接记录回落为 `6`，`agent_user` 经 TCP 登录并读取到完整 `193` 条 migration 账本。
- [ ] 该切片建立可调配置和容量诊断，不等于生产容量认证；扩大 `max_connections` 前仍需结合 PostgreSQL 内存、
  workload/进程/Pod 副本总数做压测，RDS 参数组修改及重启窗口也仍由具体环境负责。

**2026-08-19 MetricObservation consumption slice（本地 application-role 已验证）**：

- [x] 新增 `GET /api/platform/v1/metric-definitions/{metric_definition_id}/versions/{version}/observations`：按不可变
  metric/projection/output ResourceVersion、observed time、spatial ref 和 dimension subset 检索，稳定倒序并以
  `limit + 1` 给出 `has_more`；普通用户只能读取自己提交 Run 的观测，`admin/platform_operator` 才能读取租户视图，
  响应使用 `private, no-store`。
- [x] 真实本地库发现 migration `094` 历史重放造成 metric gateway ACL 漂移；migration
  `194_metric_observation_gateway_privilege_repair` 只恢复 definition、execution admission/observation 三张强制 RLS
  表的 `SELECT`，不授予 INSERT/UPDATE/DELETE。迁移后 194 条账本与 host fingerprint 一致，三项
  `has_table_privilege(..., 'SELECT')` 均为 true。
- [x] `agent_user -> SET LOCAL ROLE gda_control_gateway -> MetricObservationAuthority.search()` 已真实返回合法
  `gda.metric_observation_page.v1` 空页，owner + dimension SQL 不再触发 permission denied；指标、迁移与 deployment
  profile 聚焦回归 `156 passed`，两个 Compose profile static verification、Ruff、compile 和 diff check 通过。
- [ ] 当前开发库没有业务 observation 行，因此尚未证明真实业务时间序列内容、staging/production rollout、容量 SLO
  或跨消费者授权；AR-0/AR-1 状态不变。

**2026-08-19 automatic scalar MetricObservation projection（真实 PostGIS 已验证）**：

- [x] PostGIS metric provider 对无 group-by 且只返回一行 `metric_value` 的结果，从同一 canonical rows 自动生成
  `gda.metric_observation_result_projection.v1`；equality filters 固化为业务 dimensions，查询时间范围固化为 observation
  window，projection evidence 绑定精确 result SHA、row index、row count 和 columns，不再由 API 调用方手工填写业务值。
- [x] metric command worker 在成功 completion 后自动追加 MetricObservation；若 Run 已成功但 command ACK 前进程中断，
  重领只从不可变 result Artifact 对账并幂等补投影，不重跑 provider SQL。Artifact/Run/SHA/rows/columns 任一漂移均拒绝，
  旧 Artifact 没有 projection evidence 时保持原行为。
- [x] disposable PostgreSQL `16.4` + PostGIS 真实认证 `19/19`：原 grouped 查询仍返回两行；新增 scalar 查询从四行源数据
  精确过滤 `district=500101, observation_date=2026-08-01`，provider 返回 `10.00`，最终 Observation canonical value 为
  `10`、dimensions 与 result Artifact ID/SHA 完全一致；临时容器和结果目录已清理。
- [x] 完整 metric 聚焦回归 `132 passed`，provider bytes、首次投影、terminal reconciliation、hash drift 拒绝、worker
  health/result access/S3 version-lock 原路径均通过；Ruff、Python compile 和 diff check 通过，migration catalog 保持 194。

**2026-08-19 grouped MetricObservation atomic projection（真实 PostGIS 已验证）**：

- [x] migration `195_metric_observation_grouped_projection` 将 Run identity 演进为
  `(tenant_id, run_id, result_row_ordinal)`，保留旧 scalar `uuid5(run_id, "metric-observation:v1")`，grouped 行使用
  ordinal + canonical row fingerprint 生成稳定 v2 ID；每行显式绑定 result Artifact、row ordinal/fingerprint、业务维度和值。
- [x] PostGIS provider 从同一有序 canonical rows 生成最多 10,000 行的完整 batch evidence；一个
  `record_metric_observation_batch(...)` SECURITY DEFINER 函数在同一事务内校验整批、成功 Run、row count 和 replay，
  任一非法/缺失/冲突行都会拒绝整批，不产生部分 Observation；gateway 仍无表 INSERT/UPDATE/DELETE 权限。
- [x] worker 首次完成和 terminal command 重领均对账完整 Artifact/Run/SHA/rows/columns 并幂等投影整批，不重跑 SQL；
  旧 scalar 路径和手工 API 保持兼容。disposable PostgreSQL `16.4` + PostGIS 真实认证 `21/21`，两行 grouped 结果分别
  物化为 canonical value `10/15`，非法第二行演练后数据库残留 `0` 行，随后 ACK-loss reconciliation 补齐 `2` 行。
- [x] 完整 metric 聚焦回归 `137 passed`；Ruff、Python compile、diff check 通过。migration catalog 为 `195`，fingerprint
  `62a3e44c755a5688ba8227a690c486187fbe8527e53961935ed8fbdd762b73ba`。
- [ ] 当前证据是开发/临时真实后端，不等于 staging/production rollout 或容量 SLO；AR-0/AR-1 状态不变。

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
- [x] 新增 canonical `GravitinoTechnicalObjectReference` bridge contract：固定
  `ResourceURN + ResourceVersion + metalake/catalog/namespace/object/version`，生成稳定 SHA-256，并可
  与现有 `MetadataFabricBinding(system=gravitino)` 双向转换；不复制技术 catalog 内容，也不把 GDA
  binding 伪装成 Gravitino authority。provider fact 已可投影到既有、append-only
  `ArchitectureProviderObservation` ledger，复用 present/tombstoned 约束和后续
  `in_sync/stale/schema_drift/location_drift/tombstoned` 对账状态；observation ID 绑定完整事实指纹，
  freshness 变化不会与旧事实共享幂等键。Metadata Fabric/OpenMetadata/DolphinScheduler 聚焦回归为
  `114 passed, 1 skipped`，Ruff 与 Python compile 通过。
- [x] 已通过固定镜像 `gda/gravitino:1.3.0-local-arm64`（image ID
  `sha256:d355dc7e92f9e3545d717f3eab2cbdf412115f2b82e1e544d7f6235c1eacd5a5`）完成第一条真实
  Gravitino metadata-plane 验收：实际创建并读取 `metalake -> lakehouse-iceberg catalog -> schema -> table`，
  精确观察到 `iceberg/parquet`、format v2、provider location 和完整 namespace；真实删除后 load 返回
  `NoSuchTableException`，同一 provider response 已生成可重放的 `ResourceVersion -> reference -> binding ->
  present observation -> tombstone observation`。可重复脚本为
  `scripts/metadata-fabric-gravitino-acceptance.sh`，脱敏 `0600` 报告为
  `.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json`，报告 SHA-256
  `a914b0733cac737e1f92b7edda6f973c4fc10f5506ab2a3220fab246da57b8d0`。
- [x] 2026-08-18 已将 Gravitino 验收推进到本地持久化切片：固定镜像下以独立持久卷运行文件型
  H2 entity store、以 PostgreSQL JDBC backend 运行 Iceberg catalog；`seed` 后只重建 Gravitino
  容器，`recover` 真实确认 metalake/catalog/schema/table 的稳定技术投影和 fingerprint 跨重启保持一致。
  Gravitino 重启后会重建运行时 `audit` 字段，该 volatile 字段被显式记录但不进入技术对象 revision；
  同一验收还完成 provider-read present fingerprint/evidence、post-delete not-found、
  ResourceURN/reference/binding、present replay 和 tombstone projection。最新报告
  `.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json` 为 `0600`，
  `gda.gravitino_metadata_bridge_acceptance.v4` 的 report fingerprint 为
  `ff81a05ad9a93b35d187135b3a59791e8efa35e429744b986ef3bca2418cd6d3`；决策边界见
  [ADR-187](architecture-decisions/adr-187-gravitino-persistent-metadata-plane-acceptance.md)。
- [x] 已补齐 GDA crosswalk 的只读 search/read facade：迁移 186 增加稳定排序索引，
  `GET /api/platform/v1/metadata-fabric/bindings/search` 只搜索 authenticated tenant 的
  `ResourceURN` 与外部稳定引用，`system` 使用枚举、`q`/分页有界，结果可再交给按 ResourceURN
  的精确读取接口。平台网关、OpenAPI、租户传播、分页和越界查询测试均通过；该切片不读取或复制
  OpenMetadata/Gravitino provider metadata，决策边界见
  [ADR-188](architecture-decisions/adr-188-metadata-fabric-crosswalk-search-read-bridge.md)。
- [x] 已补齐 provider-backed read bridge：新增 `gda.metadata_provider_read.v1` typed observation，
  Gravitino 按精确 metalake/catalog/namespace/object 路径读取并对 `metadata-sha256` stable revision
  做漂移拒绝；OpenMetadata 按显式 external UUID 读取，复用 bearer token、`/api/v1`、no-redirect
  和 timeout 约束。authenticated `GET /api/platform/v1/metadata-fabric/provider-read` 只解析同租户
  唯一 GDA binding，返回 present/not-found、provider revision、bounded evidence 和 fingerprint，
  不写 ledger、不回传 provider 完整 JSON。MockTransport、路由租户隔离/OpenAPI 和真实固定镜像
  Gravitino 双阶段 acceptance 均通过；详见
  [ADR-189](architecture-decisions/adr-189-metadata-provider-read-bridge.md)。
- [x] 已补齐 bounded Gravitino provider search：新增 `gda.metadata_provider_search.v1`，按精确
  `metalake/catalog/namespace` 调用 provider list API，限制响应 512 KiB/5000 identifiers，过滤错误
  namespace、规范化 object name、稳定排序和有界分页，只返回候选 identity/evidence/fingerprint。
  authenticated `GET /api/platform/v1/metadata-fabric/provider-search` 要求 `system=gravitino` 且请求
  namespace 已存在于同租户 GDA crosswalk；不会枚举未绑定 namespace，也不会返回完整 catalog JSON。
  单测、路由租户隔离/OpenAPI 和真实 Gravitino acceptance 均通过，详见
  [ADR-190](architecture-decisions/adr-190-bound-gravitino-provider-search.md)。
- [x] 已补齐 bounded OpenMetadata provider search：复用
  `gda.metadata_provider_search.v1`，仅允许同租户已绑定的 `service:<name>` namespace、非空有界
  `q` 和 `table_search_index`，只返回 canonical entity UUID、name/FQN 与 service identity evidence；
  跨 service、非法 UUID、超大响应和未配置 provider 均 fail closed。候选仍必须经显式 UUID
  provider-read 验证。固定 OpenMetadata 1.13.1 acceptance 已真实发现 `source_parcels`，并完成
  candidate fingerprint + UUID read-after-search；报告为
  `.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json`（`0600`，SHA-256
  `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`；本次 provider bridge
  调用只注入 `GDA_OPENMETADATA_BEARER_TOKEN_SOURCE`。详见
  [ADR-191](architecture-decisions/adr-191-bounded-openmetadata-provider-search.md)。
- [x] 已按 [ADR-192](architecture-decisions/adr-192-provider-credential-source-contract.md)
  统一 OpenMetadata worker/read/search 四条调用路径的 bearer credential source contract：运行时
  `GDA_OPENMETADATA_BEARER_TOKEN_FILE` 必须是绝对普通文件，Compose/直接进程均可使用
  `GDA_OPENMETADATA_BEARER_TOKEN_SOURCE`（相对路径按进程工作目录解析），双配置必须解析到同一
  canonical 文件，缺失、冲突、目录和特殊文件均 fail closed。token 内容仍只在请求时读取，未进入
  ledger、配置摘要或 evidence；定向回归 `44 passed`。该切片只解决 secret source/rotation 的路径
  一致性，不代表 OIDC/workload identity 或 production secret manager 已完成；固定
  OpenMetadata `1.13.1` acceptance topology 已通过 source-only provider search + UUID
  read-after-search，报告 SHA-256 为
  `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`。
- [x] 已按 [ADR-193](architecture-decisions/adr-193-metadata-provider-bridge-observability.md)
  给 Metadata Fabric read/search bridge 增加低基数 Prometheus operation metrics：
  `gda_metadata_provider_operations_total` 和
  `gda_metadata_provider_operation_duration_seconds` 只记录 provider、operation 和
  `present/not_found/success/error` outcome，不记录 tenant、namespace、object ID、URL 或错误文本。
  read/search service dispatch 的成功、not-found、配置错误和 transport error 均在 `finally` 中计时落样；
  聚焦测试 `23 passed`。固定 OpenMetadata `1.13.1` source-only acceptance 已观察到真实 search/read
  metric samples，报告 SHA-256 为
  `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`。该切片只建立 bridge
  telemetry，不代表 OpenMetadata/Gravitino production metrics、OTel、dashboard、SLO 或 HA 已完成。
- [x] 已按 [ADR-194](architecture-decisions/adr-194-metadata-provider-health-readiness-contract.md)
  增加 `gda.metadata_provider_health.v1` 只读探针：Gravitino 固定检查 `/health`，OpenMetadata 固定检查
  `/api/v1/system/version`，只返回 provider、固定 endpoint、HTTP status、耗时、retryability 和
  `configuration_error/unauthorized/unavailable/protocol_error` 分类，不读取 catalog 内容。
  `/ready` 对已配置但不可用的 provider fail closed，未配置 provider 保持 local-only/unconfigured；
  `/api/admin/system-info` 同步显示受限摘要。该切片不代表 provider-native SLO、HA、backup/restore、
  OIDC/workload identity 或 production foundation 已完成。固定 OpenMetadata `1.13.1` acceptance
  已真实观察 `/system/version` `200`，并与 source-only credential、bounded search、UUID read-after-search
  和 provider metrics 同批通过；报告 `.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json`
  权限 `0600`，SHA-256 为 `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`。
  固定 Gravitino `1.3.0-local-arm64` seed/restart/recover acceptance 也真实观察 `/health` `200`，
  并在同一持久化切片中通过 provider-read/search 和 tombstone projection；报告的
  `report_sha256` 为 `ff81a05ad9a93b35d187135b3a59791e8efa35e429744b986ef3bca2418cd6d3`。
- [x] 按 [ADR-245](architecture-decisions/adr-245-duckdb-architecture-provider-reconciliation.md)
  补齐 lightweight integrated profile 的第一条 DuckDB 架构采集闭环。新增
  `data_agent.duckdb_architecture_harvester`，通过真实 DuckDB 1.5.5 只读文件连接采集
  `table_oid`、columns、constraints 和 indexes，生成与现有 `ResourceVersion` 对齐的
  `SchemaVersion`、`PhysicalLocation` 和 `ArchitectureProviderObservation` 候选；不复制
  provider SQL/完整 catalog，不自动注册或发布产品。定向回归 `3 passed`：固定时间重复采集
  指纹一致；新增列只触发 schema 指纹变化而保留 location 指纹；删除表只生成空 tombstone。
  DuckDB 1.5.5 只读重开会按逻辑表名复用 `table_oid`，因此同名删除重建的物理位置漂移
  不由本切片冒充已解决，需等待 provider 暴露稳定 revision 或以新 ResourceVersion 承接。
  该证据只覆盖 DuckDB lightweight provider 的架构观察，不外推到 Iceberg/Gravitino、对象存储
  字节、Spark/Sedona/Flink、云 provider、生产 HA/DR 或跨系统双租户。
- [x] 按 [ADR-246](architecture-decisions/adr-246-object-storage-architecture-observation.md)
  将 S3-compatible JSON/GeoJSON 对象接入同一架构观察合同。新增
  `data_agent.object_storage_architecture_harvester`：先用 `HEAD` 固化 `VersionId` 或
  `ETag+ContentLength` revision，再执行有界完整 `GET`，生成 shape-only schema snapshot、
  `SchemaVersion`、`PhysicalLocation` 和 observation 候选；完整长度不匹配、JSON/GeoJSON 解析
  失败、超出 byte/record 上限、403 或 transport error 均 fail closed，不把采样或访问失败写成
  架构事实。定向回归 `4 passed`：固定 revision replay、schema/content revision 分离、明确
  not-found tombstone、权限错误与超限拒绝。随后运行固定镜像
  `minio/minio:RELEASE.2025-04-22T22-12-26Z` 的 disposable acceptance，真实开启 bucket
  versioning，连续写入三个 VersionId，验证同 schema revision、字段新增 drift、旧版本精确
  回读、delete-marker tombstone；bucket/container/volume/network 均清理成功。随后按
  [ADR-247](architecture-decisions/adr-247-object-storage-ledger-integration-acceptance.md)
  在同一脚本中启动固定 `postgres:16.4`，将三条 present observation 和一条 tombstone 通过
  `PlatformGateway` 写入账本；真实验证幂等重放、`unbound -> in_sync`、同 schema 的
  `location_drift`、字段变化的 `schema_and_location_drift`、delete-marker 的 `tombstoned`、
  append-only、强制 RLS 和跨租户拒绝。联合报告 `.tmp/object-storage-architecture/object-storage-report.json`
  的 canonical `report_sha256` 为 `1973cd79969e91b3d1643ecf288803cc0aada6aa5ad6ba6954ebca34efe66063`，
  文件 SHA-256 为 `ad98d10ccbe70b3ceb9bc346984c9604c36f66c819d41cc8789ed0a4f8013fb0`。该证据仍未覆盖
  PostgreSQL production foundation、MinIO/S3 生产 HA/复制/Object Lock/RPO/RTO、Parquet/COG/二进制对象、
  sidecar manifest 或 Iceberg snapshot；对象双租户恢复的 bounded manifest/字节切片见 ADR-294，
  不代表生产 provider 恢复。
- [x] 已按 [ADR-294](architecture-decisions/adr-294-tenant-scoped-object-recovery.md) 补齐对象存储
  双租户恢复的第一条可验收合同。新增 `data_agent.platform_runtime.object_recovery`：每个租户绑定
  不重叠 key prefix，每个对象固化 size、ETag、VersionId 和完整 SHA-256，source/restored inventory
  以 canonical manifest 对账；默认要求 VersionId 也一致，跨 bucket 复制仅可通过显式
  `allow_version_id_remap` 放宽 provider 重新发号，仍必须满足 key/prefix/size/ETag/字节摘要一致。
  `TenantObjectScope` 在 provider 调用前拒绝跨前缀 read/write/delete/head/list。固定 MinIO + mc
  disposable 认证覆盖两个租户、两个前缀、源/恢复 bucket 各 4 个对象、完整字节回读和 6/6 跨租户
  越权拒绝；所有临时 bucket、用户、policy、container、volume、network 均清理成功。报告
  `.tmp/tenant-object-recovery/acceptance-report.json` 的 canonical `report_sha256` 为
  `88108c1391040f9fea18906b563782a330c419129b0f61014160391b102e2cbc`，文件 SHA-256 为
  `b672f639bd32fee8237c9f54cbf8f49e1e69b2e97f806c979f936af657fc4ccc`。该切片仍不覆盖生产复制、
  Object Lock、HA/PITR/RPO/RTO、multipart ETag 跨 provider 语义或控制账本与对象存储的跨 store
  原子提交。
- [x] 已按 [ADR-295](architecture-decisions/adr-295-cross-store-recovery-identity-binding.md) 补齐
  控制账本与对象 manifest 的共同恢复身份。`data_agent.platform_runtime.cross_store_recovery`
  将排序后的租户集合、源 `ResourceVersion`、源内容 SHA-256、控制 manifest SHA-256 和对象
  manifest SHA-256 绑定为 `gda.cross_store_recovery_binding.v1`；source/restored 任一侧的租户
  集合、源版本或任一 manifest 漂移都会拒绝成组恢复。联合合同回归（对象恢复、控制账本恢复、
  binding）`28 passed`。随后新增 `232_cross_store_recovery_binding_authority.sql` 和
  `PostgresCrossStoreRecoveryBindingAuthority`，按租户持久化同一份 binding 证据副本，使用强制
  RLS、append-only trigger 和 `SECURITY DEFINER` 受控写路径；同 binding 重放幂等，同一源版本
  的不同 binding fail closed。disposable PostGIS + MinIO 联合认证六项检查和五项清理检查全部
  通过。随后新增 `CrossStoreRecoveryAdmission`，统一执行 source/restored manifest 对账、
  binding 构造、逐租户 durable 写入和重启 read-back；对象 VersionId 只有在显式允许时才能
  重映射，控制账本 manifest 必须精确一致。联合认证脚本已改走该准入入口。最新报告
  `.tmp/cross-store-recovery-binding/acceptance-report.json` 的最新 canonical `report_sha256` 为
  `1a89ff492a19560752f53fec0d7ba5907169b5fb9d1028460ee0ca7d1ce0569c`，文件 SHA-256 为
  `7ec0c58f9fd262c896e5758b9bfc127f12f98532bbb35b63d5f2b3ffd9ee732f`。认证同时验证
  `planned -> admitted -> completed` 控制器合同和重新构造后的终态 read-back。新增
  `233_cross_store_recovery_controller_authority.sql` 与
  `PostgresCrossStoreRecoveryControllerLedger`，在同一 PostgreSQL transaction 内为每个 covered
  tenant 写入同一份 controller snapshot，强制 RLS、append-only event chain、受控 `SECURITY DEFINER`
  写入、同快照幂等和租户副本漂移拒绝均已通过真实 disposable PostGIS 回归；联合认证脚本已改用
  PostgreSQL durable controller ledger，十一项功能检查和五项清理检查均为 `true`。该证据仍不
  宣称 PostgreSQL 与对象存储的跨 store atomic commit、生产复制、PITR、HA、RPO/RTO 或 provider
  故障注入。随后将 controller 接入既有 durable projection recovery job：job claim 后先校验
  plan 对应的 admission bundle，provider 未知结果/目标漂移进入 controller
  `reconciliation_required`，只有 checkpoint authority 已提交才推进 `completed`；租约丢失时
  不写 terminal settlement。Compose projection-recovery profile 已提供可选
  `GDA_PROJECTION_RECOVERY_CONTROLLER_ADMISSION_FILE`，按 `plan_sha256` 读取 server-owned
  binding/tenant-copy evidence，并为每个 job 使用 PostgreSQL durable controller ledger。该
  bounded deployment 适配回归 `27 passed`，覆盖 controller admission/settlement、未知结果、重启
  后不重复 provider side effect 以及 admission bundle 的 plan/tenant 绑定。随后接入现有 PostgreSQL
  recovery rehearsal，真实执行 `233` 号 migration 和 durable queue/lease；2026-08-25 报告的
  `39/39` 检查通过，其中新增 `durable_controller_settles_projection_job` 与
  `durable_controller_blocks_unknown_provider_replay`。报告位于
  `docs/reports/cross_store_projection_recovery_postgres_rehearsal_2026-08-25.json`，canonical
  `report_sha256` 为 `379da6be675ac1630915fd0253b04858a1e5b089b54030925fc485388495d264`，文件
  SHA-256 为 `c6ad8dd194468d3b097609f73e86fd9edc5b371ad3ce47ae34c2ede67a277464`。正式 recovery
  controller HA、生产 workload identity/OIDC、备份策略、provider 故障注入和 RPO/RTO 仍是后续
  工作。随后补齐 `k8s/optional/projection-recovery-worker` deployment profile：它不进入默认
  `k8s/base`，默认 `replicas: 0`，使用独立 ServiceAccount、UID/GID 10001、只读根文件系统、无
  Kubernetes API token，以及只允许 DNS/PostgreSQL/MinIO 的 NetworkPolicy；租户 ID 和按
  `plan_sha256` 索引的 admission bundle 通过环境-owned Secret 提供；resolver 同时将 binding 的
  source ResourceVersion/source content SHA-256 与 sealed plan 精确对账，缺失或错配证据时不会
  误启动或放行 provider。YAML/Kustomize 合同测试 `5 passed`，该 profile 仍是 sandbox deployment
  contract，不代表 recovery controller HA、OIDC/workload identity、备份策略、provider 故障
  注入和 RPO/RTO。
- [x] 已补齐 admission bundle 的部署侧生成与轮换合同（ADR-296）。新增
  `ProjectionRecoveryAdmissionBundle`，严格冻结
  `gda.cross_store_recovery_admission_bundle.v1` 的顶层/entry 字段、排序 plan key、binding
  指纹和完整 tenant copy；新增原子轮换写入（同目录临时文件、`fsync`、`0440`、`os.replace`），
  runtime resolver 改为复用该解析器。聚焦回归 `12 passed`，覆盖 canonical round-trip、未知字段
  和 tenant drift 拒绝、plan key 拒绝、轮换无半写文件/临时残留以及缺失 evidence fail closed。
  环境-owned recovery controller 仍需在 source/restored manifest 对账和 durable read-back 后签发
  bundle；格式本身不提供签名、OIDC、Secret Manager、HA 或 RPO/RTO，不能据此标记生产 recovery
  controller 完成。
- [x] 新增 `k8s/overlays/projection-recovery-sandbox` 作为显式 opt-in 环境入口。它只组合
  optional recovery profile，将 worker 从默认 `replicas: 0` patch 到 `1`，不复制 base 的占位
  Secret，不携带 provider credential、row bundle 或外部 egress；正常 base 服务和环境-owned
  Secret 必须由部署方预置。离线 overlay/Kustomize 合同回归已覆盖默认 profile 不变、worker 安全
  上下文保留和无凭据渲染；该入口仍是 sandbox enablement，不代表生产 OIDC、Secret Manager
  rotation、controller HA、PITR 或 RPO/RTO。
- [x] 按 [ADR-248](architecture-decisions/adr-248-iceberg-architecture-observation.md) 增加受限
  Gravitino Iceberg table architecture harvester。它只接受已绑定的
  `metalake/catalog/namespace/table` table payload，校验 `provider=iceberg`、format version、数字
  `current-snapshot-id`、有界 columns 和无凭据 location，生成独立 schema snapshot、Iceberg snapshot
  revision、`SchemaVersion`、`PhysicalLocation` 和 `ArchitectureProviderObservation` 候选。定向回归
  `6 passed`，覆盖 replay、同 schema snapshot 变化、字段增加 drift、明确 not-found tombstone 和
  provider/协议事实 fail closed。该 harvester 契约本身不等于真实 Iceberg catalog/table
  create/read/write/schema evolution、snapshot lineage、REST/Gravitino 数据面、对象字节、
  HA/backup/restore 或 PostgreSQL ledger；真实 provider/ledger 证据见 ADR-249/250，REST 数据面及
  candidate projection 证据见 ADR-251，AR-1 继续保持
  `in_progress`。
- [x] 按 [ADR-249](architecture-decisions/adr-249-real-iceberg-snapshot-ledger-acceptance.md) 完成真实
  Spark/Flink/Iceberg snapshot 到控制账本的联合验收。固定 Spark runtime 在 disposable MinIO + Iceberg
  JDBC catalog 中真实创建 format v2 baseline snapshot `3379225455652360291`；Flink 1.19 + Iceberg
  1.7.2 读取 baseline，增加 `flink_commit_tag` 并追加一行，形成 child snapshot
  `3726182389816928569`；Spark 反向读取最终 4 行/5 列，验证 schema evolution 可见、内容精确、parent
  chain、两次 append 和 baseline time-travel。新增 [ADR-250](architecture-decisions/adr-250-iceberg-snapshot-lineage-observation-contract.md)
  后，harvester 对 baseline root 和 evolved child 的有界 `snapshot_id/parent_id/operation` 链执行顺序、
  唯一性和 current-snapshot 尾部校验，并把 lineage 写入 acceptance report。两次真实 table observation
  通过 Iceberg harvester 投影为 observation/candidate，再由 `PlatformGateway` 写入独立 PostgreSQL
  ledger；`unbound -> in_sync`、后续 `schema_and_location_drift`、幂等 replay、append-only 两条
  present observation、强制 RLS、跨租户拒绝和所有 provider/container/network/work directory cleanup
  均通过。报告 `.tmp/iceberg-architecture/acceptance-report.json` 的 canonical `report_sha256` 为
  `b53ef5d3fdab781ea99b5701879c84167dcb57654365d8f6999f604cebfdd1a8`，文件 SHA-256 为
  `693409258b97ab1545850b67f23f69c31b17964aa2dab286aa25e19dc1d5af59`。这仍不代表 Gravitino REST
  catalog、snapshot checkpoint/recovery、生产 HA/DR、PITR/RPO/RTO、多表/多并行度 conformance 或双租户恢复已完成。
- [x] 按 [ADR-251](architecture-decisions/adr-251-gravitino-iceberg-rest-catalog-data-plane-acceptance.md)
  完成真实 Spark -> Gravitino Iceberg REST catalog 数据面验收。固定
  `gda/gravitino:1.3.0-local-arm64` 通过 `http://gravitino:9001/iceberg`、`default_catalog`，在
  disposable PostgreSQL JDBC backend + MinIO warehouse 中创建 namespace/table，Spark/Iceberg
  1.6.1 完成 format v2 baseline、schema evolution、append、snapshot parent chain 和 baseline
  time-travel；随后以 REST `GET table` 读取标准 Iceberg metadata，经 bounded projection 接入
  `harvest_gravitino_iceberg_table`，生成 observation、SchemaVersion、PhysicalLocation candidate，
  并验证 REST lineage 与 Spark lineage 一致。S3 location、REST readiness 及
  bucket/container/volume/network/work directory cleanup 全部通过。报告
  `.tmp/gravitino-rest/acceptance-report.json` 的 canonical `report_sha256` 为
  `468bcaec08a5c83bb7539628b3f7222dfde60761dee30181919807b6b1c081d0`，文件 SHA-256 为
  `dfef08db0deff8a4bad8a63ef55627f6ee92e70d12a19e4a1ee1796e2b1b9791`。同一验收还在独立控制
  PostgreSQL 上验证 observation 写入、replay 幂等、`unbound -> in_sync`、强制 RLS 和跨租户拒绝；
  该切片只覆盖 Spark REST、candidate projection 和 disposable ledger binding，不覆盖 Flink REST、
  production metadata fabric 或生产 foundation。
- [x] 按 [ADR-252](architecture-decisions/adr-252-flink-gravitino-iceberg-rest-catalog-acceptance.md)
  完成真实 Flink -> Gravitino Iceberg REST catalog -> Spark 回读验收。Spark 使用 `rest` 本地 alias，
  Flink 使用 `lakehouse` 本地 alias，但共享 `default_catalog`、namespace/table 坐标和同一真实 OSM
  `interop-plan`；Flink 完成 schema evolution 与单行 append，Spark 精确回读 4 行并验证 baseline
  time-travel、snapshot parent chain、REST lineage 对齐和 bounded architecture candidate projection。
  同一验收在独立控制 PostgreSQL 验证 observation 写入、replay 幂等、`unbound -> in_sync`、append-only、
  强制 RLS 和跨租户拒绝；报告 `.tmp/gravitino-rest/flink-acceptance-report.json` 的 canonical
  `report_sha256` 为 `ae3a37bd1316c9dabb8867127d7d5f716a918d7aecf1ca909aecc4b000d40d00`，文件
  SHA-256 为 `ece1d903ea68c0c219c751b1c68336b0c1b07233937c250df2a5a55695886fc7`。该切片只覆盖
  单表、单并行度、bounded Flink REST 数据面互操作，不覆盖生产 HA/身份/恢复、多表 conformance、
  kill-9/网络不确定提交或通用 destructive-write 并发冲突。
- [ ] 上述证据仍只是本地 Gravitino metadata-plane persistence 和受限 Spark/Flink/Iceberg snapshot acceptance，
  不是 production foundation 或数据面 conformance；OIDC/workload identity、生产 HA、backup/restore/PITR、
  metrics、provider-wide schema evolution/snapshot lineage、
  Spark/Sedona/Flink create/read/write/schema evolution/cancel/reconcile/lineage、provider-backed
  OpenMetadata/provider-wide search、双租户隔离与故障注入仍未完成。GDA crosswalk search/read、
  provider-backed read、bounded Gravitino namespace search 和 bounded OpenMetadata service search 已完成，
  但 provider-wide/unbound federation、OpenMetadata/Gravitino/DolphinScheduler 外部系统双租户和恢复仍未完成；
  对象存储双租户 bounded slice 已按 ADR-294 验证，AR-1 保持 `in_progress`。
- [x] 已按 [ADR-293](architecture-decisions/adr-293-tenant-scoped-control-ledger-recovery.md) 完成控制账本的双租户恢复证据：
  固定 `postgis/postgis:16-3.4` disposable backend 中创建两个租户的 Resource/ResourceVersion/
  Definition/PlatformRun/Artifact/QualityResult/Lineage graph，执行 custom-format `pg_dump` 并恢复到
  隔离数据库；source/restored 的 9 张账本表逐租户 manifest 完全一致，恢复后通过 gateway/RLS 逐租户
  可见行数精确匹配，跨租户可见行、跨租户 Gateway read 和跨租户 predecessor 均为拒绝，重复登记返回
  `created=false`。4 个合同测试通过，报告 `.tmp/tenant-recovery/acceptance-report.json` 的文件 SHA-256
  为 `c4aebfda5059299a103d0c8c8cf0121d6c4a35a1eabbbe8cc923fc5de02e3803`。该证据只覆盖 GDA 控制账本，
  不外推 OpenMetadata/Gravitino/DolphinScheduler/对象存储恢复、异地复制、PITR、生产 HA 或 RPO/RTO；
  AR-1 总体仍保持 `in_progress`。
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
- [x] 已按 [ADR-195](architecture-decisions/adr-195-dolphinscheduler-cancel-capability-admission.md)
  增加 `gda.dolphinscheduler_capability.v1` 版本锁定的 cancel capability admission：profile 默认
  `unknown`，在 CAS 或外部 STOP 前 fail closed；只有带非敏感 evidence reference 的 `certified` 才能
  作为 production admission，显式 sandbox 只允许 `conformance_probe` 且报告 `probe_only`。
  capability fingerprint 会进入取消状态转换 evidence；adapter/consumer/conformance 回归 `59 passed`。
  该切片收紧了准入边界，但不替代真实 provider terminal `STOP` 认证，现有 cancel terminal 退出门仍保持未完成。
- [x] 已按 [ADR-196](architecture-decisions/adr-196-dolphinscheduler-cancel-terminal-evidence-timing.md)
  修正真实取消不一致路径的时序与 replay 幂等边界：terminal mismatch 现在锚定不可变的
  `PlatformRun -> cancelling` admission event，并对 DolphinScheduler 3.4 的秒级 provider timestamp
  保留严格 1 秒截断容差；outbox delivery retry 不再伪装成 provider attempt。真实新 Run
  `0083c7f2-ce09-50e4-acfa-a561f7719834` / instance `35` 观察到 provider `FAILURE` 后，平台收敛为
  `failed`，打开 incident `7b631d0f-cd74-57fd-b6ab-72611492a482`，cancel replay 未创建新 command 或
  policy artifact，且未创建 DataProductVersion。报告为
  `.tmp/dolphinscheduler-sandbox/cancel-v1/governed-cancel-rehearsal-report.json`，SHA-256
  `339996fdc97df600717459f928d1a6e25886e3f51260dba869750ad4da9693ee`；DolphinScheduler capability
  仍是 `conformance_probe` / `probe_only`，因此 provider `STOP` 认证退出门继续保持未完成。
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
  OpenMetadata/provider-wide search、双租户与恢复仍未完成，Gravitino fabric、Spark/Flink provider correlation 与
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
- [x] 按 [ADR-254](architecture-decisions/adr-254-flink-iceberg-physical-fault-uncertainty-reconciliation.md)
  完成 Flink/Iceberg 物理故障窗口的真实提交不确定性对账。`kill` profile 在终态 source
  checkpoint `offset=4` 后对 Flink provider container 注入 Docker `SIGKILL`（实际
  `Running=false`、exit code `137`）；`network` profile 在同一窗口执行真实
  `docker network disconnect`，并由网络成员检查确认 provider 已移除。两种故障都故意不把
  provider ACK 送入控制面，独立 Spark snapshot probe 仍按 commit token、parent、operation、
  行数和内容 SHA-256 找到唯一 `committed_unacknowledged` 终态，SourceSync 只从 `0 -> 1` 推进；
  重放返回 `already_recorded`，snapshot 列表和内容 hash 无变化，DataProductVersion 保持 `0`。
  两份报告的 14 项顶层门和清理门均通过：
  `kill` 报告文件 SHA-256 `b5dcfcdb5de0a06dbe8c54429ba5b3fca09ddf7aaf2e8507ac86f701877bd936`，
  `network` 报告文件 SHA-256 `a1f3dc7c157dc764d3f47d3783cddd026a01c9edcf64b2d4a923ca42d09eb58d`。
  该证据只放行单表、单并行度、disposable runtime 的物理故障 reconciliation，不代表生产
  Flink HA/restart、自动 fencing、Kubernetes recovery、跨区域 RPO/RTO 或跨系统 exactly-once。
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
- [x] 按 [ADR-255](architecture-decisions/adr-255-flink-position-delete-stale-conflict-isolation.md)
  完成真实 Flink position-delete/MOR stale commit 冲突隔离。第一次 Flink TaskManager
  RowDelta 在三行无分区 format-v2 表上提交 position delete；第二次 writer 继续绑定旧 baseline、
  同一 data file/position 和不同 token，真实 Iceberg validation 返回 ValidationException，
  catalog metadata location 和 snapshot 数量保持不变，stale token 没有 snapshot。失败尝试物化的
  delete file 由 writer 通过 FileIO 清理并输出 orphan_cleanup=true，独立 Spark 回读确认最终
  两行、baseline time travel、唯一 delete file 和 2 metadata/4 manifest/2 Parquet 对象图均准确。
  16 项顶层门和清理门通过；报告 .tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-conflict-report.json
  文件 SHA-256 为 8cf105c2f3cafbff2e2df1193bc5422e86fd98f8edc648db5c926ccccebe1320。原有单写
  profile 也以独立回归报告通过，文件 SHA-256 为
  f53d522413274cb32b02fdb83128f04ee7223fa593cd96dea9404e43485319fd。该证据只放行单表、
  单文件、单并行度 stale position-delete conflict 和失败 artifact 清理，不代表分区/多文件
  position delete、通用 SQL UPDATE/MERGE、自动 retry、streaming checkpoint、HA 或 K8s。
- [x] 按 [ADR-256](architecture-decisions/adr-256-spark-sql-merge-stale-conflict-isolation.md)
  完成真实 Spark SQL `MERGE INTO` stale snapshot 冲突隔离。Spark 在 identity(`road_id`)、
  format-v2 表上以 `expected_revision` 绑定单 source row，在提交前由 barrier 暂停；Flink
  single-operation append 先提交同一道路 revision 2 并推进 JDBC Catalog，陈旧 SQL MERGE
  得到真实 Iceberg `ValidationException`，catalog 保持两条 append snapshot，stale token 没有
  snapshot。验收器以 Flink child 对象集合为基线并执行逐对象 orphan 清理；本次 stale 尝试没有
  新对象（`detected_keys=[]`），该清理门仍通过。独立 fresh-state SQL MERGE 将 revision 2
  更新为 revision 3，形成第三条 overwrite child；baseline/Flink/final time travel、15 个物理
  对象图、容器/前缀/工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `.tmp/source-sync-certification/chongqing-osm-spark-flink-sql-merge-conflict-report.json`，
  SHA-256 为 `4cb13c93cccba85425c31af22d6753e6619d7f7f0a10a60606185722943e08c0`。该证据只放行
  当前版本矩阵下单键、单 source row、`WHEN MATCHED THEN UPDATE` 的 bounded SQL MERGE；不代表
  SQL UPDATE 独立语义、MERGE insert/delete/多 source row、多分区 destructive write、自动 retry、
  streaming writer、REST/Gravitino destructive-write conformance、HA 或 K8s。
- [x] 按 [ADR-257](architecture-decisions/adr-257-spark-sql-update-snapshot-guard.md) 完成真实
  Spark SQL `UPDATE` stale snapshot fail-closed。真实运行确认当前 Spark 3.5/Iceberg 1.6.1
  JDBC Catalog 版本矩阵不会稳定把跨会话 SQL UPDATE stale race 转成 provider
  `ValidationException`，因此平台在 barrier 释放后清除 table cache、刷新 snapshot 并执行
  snapshot guard；baseline/current 不一致时不发起 SQL UPDATE。Flink 同键 revision 2 先提交后，
  stale UPDATE 被 guard 拒绝，catalog 保持两条 append snapshot，stale token 不在当前数据中；
  fresh-state SQL UPDATE 将 revision 2 更新到 revision 3，形成第三条 overwrite snapshot。
  baseline/Flink/final time travel、对象图、容器/前缀/工作目录清理和主库 SourceSync `0/0/0`
  均通过。报告 `.tmp/source-sync-certification/chongqing-osm-spark-flink-sql-update-conflict-report.json`，
  SHA-256 为 `8d92d3cb8f2e6338ef00fc0dc8d65fa9a3ddcadb616ee7cf51a6e4bf9a417d0a`。该证据只放行
  当前版本矩阵下 identity-key 单行、单谓词、`SET` 字段更新的 SQL UPDATE guard、stale
  fail-closed 和 fresh retry；不代表 UPDATE join/subquery、多行复杂谓词、MERGE 多分支、
  自动 retry、REST/Gravitino destructive-write conformance、HA 或 K8s。
- [x] 按 [ADR-258](architecture-decisions/adr-258-spark-sql-update-multi-row-conflict-isolation.md)
  完成真实多行 Spark SQL `UPDATE` snapshot guard。以重庆 OSM 三行 baseline 为基础，两个道路
  (`102262017`、`102262020`) 分别由 Flink 提交 revision 2，形成两个连续 child snapshot；Spark
  使用单条 `road_id IN (id1, id2) AND revision = 1` UPDATE，在 barrier 释放后识别 baseline/current
  不一致并整体 fail-closed，两个目标均保留 revision 1/2，没有部分提交。fresh-state 同一条多行
  UPDATE 一次性将两个 revision 2 行更新到 revision 3，形成第四条 overwrite snapshot；baseline/
  Flink/final time travel、4 metadata/10 manifest/7 parquet 对象图、容器/前缀/工作目录清理和主库
  SourceSync `0/0/0` 均通过。报告 `docs/reports/chongqing_osm_spark_flink_sql_update_multi_conflict_2026-08-24.json`，
  SHA-256 为 `bfd1ad94cb07db586857b9bed243ff32e30ecd7b1b0146699ab042807cd8212b`。该证据只放行
  两目标、简单 `IN` 谓词、同一 expected revision 的多行 UPDATE；复杂谓词、join/subquery、多表、
  跨分区/多文件 destructive write、SQL MERGE 多分支/多 source row 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-259](architecture-decisions/adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)
  完成真实 Spark SQL `MERGE` 多 source row cardinality fail-closed。以重庆 OSM 三行 baseline 为基础，
  Flink 先提交同一道路 revision 2；Spark 随后提交两条绑定同一 `road_id + expected_revision=1` 的
  source row。真实 Spark `MergeRowsExec` cardinality validator 拒绝该 MERGE，两个 source token
  均未落库，catalog 保持两条 append snapshot，没有部分提交。显式去重后的单条 fresh source row
  将 revision 2 更新到 revision 3，形成第三条 overwrite snapshot；baseline/Flink/final time travel、
  3 metadata/7 manifest/5 parquet 对象图、容器/前缀/工作目录清理和主库 SourceSync `0/0/0` 均通过。
  报告 `docs/reports/chongqing_osm_spark_flink_sql_merge_multi_source_conflict_2026-08-24.json`，
  SHA-256 为 `4ec2f8628cfc58ae52d1eb498ee07510ecfb3da80dc82d45444a5e85e3ca3bc3`。该证据只放行
  单 target row、两条重复 source row 的 cardinality 拒绝和显式去重后的 retry；自动去重、MERGE
  insert/delete、多 target row、多分区语义和生产 writer recovery 仍未完成。
- [x] 按 [ADR-260](architecture-decisions/adr-260-spark-sql-merge-multi-branch-update-insert.md)
  完成真实 Spark SQL `MERGE` 的 bounded 多分支 update/insert。以重庆 OSM 三行 baseline 为基础，
  Flink 先提交 `102262017` 的 revision 2；Spark 以一条 `expected_revision=2` source row 执行
  `WHEN MATCHED THEN UPDATE` 到 revision 3，同时以 baseline 外的 `102262028` 执行
  `WHEN NOT MATCHED THEN INSERT`。单次 MERGE 形成 `append -> append -> overwrite` snapshot 链，
  matched/insert token 各出现一次，baseline/Flink/final time travel、5 行最终内容、对象图、
  容器/对象前缀/工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_multi_branch_2026-08-24.json`，SHA-256 为
  `95981585330ff72906a482e33922fa5b4a527b6627cd6f5f63e6fbd4dd2432f0`。该证据只放行单表、单
  target row、单 insert row、简单 ON 谓词的 matched-update + not-matched-insert；delete、多个
  matched/not-matched branch、多 target row、复杂谓词/跨分区 destructive write 和生产 writer
  recovery 仍未完成。
- [x] 按 [ADR-261](architecture-decisions/adr-261-spark-sql-merge-matched-delete.md) 完成真实
  Spark SQL `MERGE` matched-delete。以重庆 OSM 三行 baseline 为基础，Flink 先提交
  `102262017` 的 revision 2；Spark 使用同一 `road_id + expected_revision=2` 的单条 source row
  执行 `WHEN MATCHED THEN DELETE`，只删除 revision 2，baseline revision 1 保留。snapshot 链为
  `append -> append -> delete`，最终三行内容、baseline/Flink/final time travel、对象图、容器/
  对象前缀/工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_delete_2026-08-24.json`，SHA-256 为
  `52da24a731219db83c3881a6fbe8fbac309e3c16bc9f96ddc1cee4598a6057a2`。该证据只放行单表、单
  target row、单 source row、简单 ON 谓词的 matched-delete；多个 target row、多个 matched
  branch、复杂谓词/跨分区 destructive write、混合分支并发冲突和生产 writer recovery 仍未完成。
- [x] 按 [ADR-262](architecture-decisions/adr-262-spark-sql-merge-multi-target-update.md) 完成真实
  Spark SQL `MERGE` 多 target row matched-update。重庆 OSM 三行 baseline 上，Flink 先提交
  `102262017` revision 2；Spark 使用两条唯一 source row，在一次 `WHEN MATCHED THEN UPDATE`
  中将 `102262017` 更新到 revision 3、将另一条 baseline road `102262020` 更新到 revision 2。
  单次 MERGE 形成 `append -> append -> overwrite` snapshot 链，两个 commit token 各出现一次，
  最终四行内容、baseline/Flink/final time travel、对象图、容器/对象前缀/工作目录清理和主库
  SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_multi_target_2026-08-24.json`，SHA-256 为
  `4096d55f99f5509910d91d75f41f465022b7a089f513a997249b4e25dbbb09be`。该证据只放行两条唯一
  source row、两个不同 target row、单个 matched-update branch 的单次 MERGE；重复 source row、
  多 branch、复杂谓词/跨分区 destructive write、自动 retry 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-263](architecture-decisions/adr-263-spark-sql-merge-multiple-matched-branches.md) 完成
  真实 Spark SQL `MERGE` 多 matched branch。重庆 OSM 三行 baseline 上，Flink 先提交
  `102262017` revision 2；Spark source 的一行以 `action=delete` 命中条件 branch，删除该 revision
  并保留 baseline revision 1；另一行以 `action=update` 命中默认 matched-update branch，更新
  `102262020` 到 revision 2。单次 MERGE 形成 `append -> append -> overwrite` snapshot 链，delete
  branch token 为 0、update branch token 为 1，最终三行内容、time-travel、对象图、容器/对象前缀/
  工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_multi_matched_branch_2026-08-24.json`，SHA-256 为
  `3ea49d71aa9ee2e1177da08a42e3154e40bc9a65a8e70e91a58dd086eb5a795f`。该证据只放行一个条件
  matched-delete 加一个默认 matched-update branch；更多 branch、多个 not-matched branch、复杂
  谓词/跨分区 destructive write、自动 retry 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-264](architecture-decisions/adr-264-spark-sql-merge-multiple-not-matched-branches.md)
  完成真实 Spark SQL `MERGE` 多 not-matched branch。重庆 OSM 三行 baseline 上，Flink 先提交
  `102262017` revision 2；Spark source 的 `102262028` 以 `action=insert_priority` 命中条件
  not-matched insert，`102262030` 走默认 not-matched insert。单次 MERGE 形成
  `append -> append -> append` snapshot 链，两个 insert token 各出现一次，最终 6 行内容、
  baseline/Flink/final time travel、对象图、容器/对象前缀/工作目录清理和主库 SourceSync
  `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_multi_not_matched_branch_2026-08-24.json`，
  SHA-256 为 `ba4a6dc862cc407a13b10c7322675791c199ceb58292da8a5e7062a7ef5ab5b6`。该证据只放行
  单表、两条唯一且均未匹配 target 的 not-matched insert branch；更多 branch、混合分支复杂组合、
  复杂谓词/跨分区 destructive write、自动 retry 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-265](architecture-decisions/adr-265-spark-sql-merge-mixed-branches.md) 完成真实
  Spark SQL `MERGE` 混合 branch 组合。重庆 OSM 三行 baseline 上，Flink 先提交 `102262017`
  revision 2；同一条 Spark SQL `MERGE` 同时执行条件 matched-delete、默认 matched-update、
  条件 not-matched-insert 和默认 not-matched-insert。最终 5 行内容、`append -> append -> overwrite`
  snapshot 链、四个 branch token 计数、baseline/Flink/final time travel、对象图、容器/对象前缀/
  工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_mixed_branches_2026-08-24.json`，SHA-256 为
  `ff281f846a80375c154a93f3778392d91641e61cb4692019cd1870e29e819356`。该证据只放行四条唯一
  source row、简单 ON 谓词的四分支组合；更多 branch、复杂谓词/跨分区 destructive write、自动
  retry 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-266](architecture-decisions/adr-266-spark-sql-merge-automatic-fresh-retry.md) 完成
  真实 Spark SQL `MERGE` cardinality fail-closed 后的同 worker 自动 fresh-state retry。重复
  source 的 `MergeRowsExec$BitmapCardinalityValidator` 拒绝后，worker 校验 catalog 仍停在
  Flink child，再自动提交 policy-bound `fresh-source-deduplicated` row，形成第三条 overwrite
  snapshot。最终 4 行内容、baseline/Flink/final time travel、对象图、容器/对象前缀/工作目录
  清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_auto_retry_2026-08-24.json`，SHA-256 为
  `497e99a92844dd01505f8d7a6c975ae4e477bfe84250d77fde863831dfda7cfd`。该证据只放行单 target、
  两条重复 source row 的自动 retry 编排；自动 deduplication 规则、retry budget/退避、跨分区
  retry 和生产 recovery controller 仍未完成。
- [x] 按 [ADR-267](architecture-decisions/adr-267-spark-sql-merge-complex-predicate.md) 完成真实
  Spark SQL `MERGE` 复杂 `AND/OR/IN` 谓词切片。以重庆 OSM 三行 baseline 为基础，Flink 先提交
  `102262017` revision 2；Spark 在同一条 `MERGE` 中以 `target.road_id = source.road_id`、
  `target.revision = source.expected_revision` 和 `promote OR (refresh AND road_id IN (...))`
  组合条件更新 `102262017`、`102262020`，而 `102262024/ignore` guard row 不更新、不插入。
  两个 matched token 各出现一次，guard token 缺失，最终四行内容和
  `append -> append -> overwrite` snapshot 链、baseline/Flink/final time travel、对象图、容器/
  前缀/工作目录清理及主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_complex_predicate_2026-08-24.json`，SHA-256 为
  `cd55e5621fe2e5d7c4965259369f52a34a8fb1478226f77d6f7c8a0d34028031`。该证据只放行单表复杂
  谓词匹配；join/subquery、SQL UPDATE 复杂谓词、跨分区/多文件 destructive write、自动
  deduplication/retry、REST/Gravitino destructive-write conformance 和生产 writer recovery 仍未完成。
- [x] 按 [ADR-268](architecture-decisions/adr-268-spark-sql-update-complex-predicate.md) 完成真实
  Spark SQL `UPDATE` 复杂 `AND/OR/IN` 谓词切片。以重庆 OSM 三行 baseline 为基础，Flink 先对
  `102262017`、`102262020` 各提交 revision 2；stale UPDATE 在 snapshot guard 处整体拒绝，
  fresh retry 使用 `revision = expected_revision AND (road_id IN (...) OR (road_id = ... AND
  writer_engine = 'flink-1.19.3'))` 一次更新两个 Flink 行到 revision 3。`102262024` guard row
  保持 revision 1。最终内容、baseline/Flink/final time travel、对象图、容器/前缀/工作目录清理和
  主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_update_complex_predicate_2026-08-24.json`，SHA-256 为
  `b1541e9a2113426c7f18055fd02a61585c4de2911b073e7cfa144b091134385a`。该证据只放行单表复杂
  UPDATE 谓词；join/subquery、跨分区/多文件写入、自动 retry budget/退避和生产 recovery 仍未完成。
- [x] 按 [ADR-269](architecture-decisions/adr-269-spark-sql-merge-deterministic-auto-deduplication.md)
  完成真实 Spark SQL `MERGE` 重复 source 的确定性自动去重。以重庆 OSM 三行 baseline 为基础，
  worker 先真实拒绝两条重复 source，再按显式 `highest_rank_then_source_row_id` 规则从
  `fresh-source-deduplicated`（rank 100）和 `candidate-lower-priority`（rank 10）中选择前者。
  未选 candidate token 未落库，fresh snapshot 仍是 Flink child，最终内容、time-travel、对象图、
  容器/前缀/工作目录清理和主库 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_auto_dedup_2026-08-24.json`，SHA-256 为
  `256749d2d6376b631240d3a77f36c489589f8e8e7db2bc23cc633d9723bf9fb2`。该证据只放行显式 rank
  的单表自动去重；retry budget/退避、跨 target/跨分区 survivorship 和生产 recovery 仍未完成。
- [x] 按 [ADR-270](architecture-decisions/adr-270-spark-sql-merge-retry-budget-fail-closed.md)
  完成真实 Spark SQL `MERGE` retry budget admission。Flink child 上重复 source 在提交前被识别；
  `retry_budget=1`、强制需求 2 次时只记录一次 `duplicate_source_rejected_before_merge`，第二次
  提交被阻止，catalog、行集和 snapshot 不变。11 项检查、对象图、容器/前缀/工作目录清理和
  SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_retry_budget_2026-08-24.json`，SHA-256 为
  `8953e1e77f17a171260fa6851460ef5ae1d91927b4a6849513b103fb1b316b3c`。该证据只放行提交前
  admission budget；自适应退避、第二次 destructive retry、provider abort recovery 和生产
  writer recovery 仍未完成。
- [x] 按 [ADR-271](architecture-decisions/adr-271-spark-sql-merge-cross-target-survivorship.md)
  完成真实 Spark SQL `MERGE` 跨 target survivorship admission。两个 target 各有两条 candidate，
  worker 按 `highest_rank_then_source_row_id_per_target` 独立选择 rank 100 row，未选 candidate
  token 未落库；最终单次 snapshot、baseline/Flink/final time-travel、对象图、容器/前缀/工作目录
  清理和 SourceSync `0/0/0` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_cross_target_survivorship_2026-08-24.json`，
  SHA-256 为 `8e43422e44d29a0741de60b47f9093943661cdc63d0a832f64cbb9290db36c5d`。该证据只放行
  两 target 的单表 per-target rank 选择；跨分区/多文件 survivorship、字段级业务合并、自适应
  retry/backoff 和生产 recovery 仍未完成。
- [x] 按 [ADR-272](architecture-decisions/adr-272-spark-sql-merge-partition-file-scope.md)
  完成真实 Spark SQL `MERGE` 跨分区多文件范围对账。`identity(road_id)` 表在 MERGE 前后读取
  Iceberg `table.files`：`102262017`、`102262020` 两个目标分区的 data-file 集合发生替换，
  guard 分区 `102262024` 文件集合保持不变，变化分区集合精确等于目标集合。最终四行、
  `append -> append -> overwrite` snapshot parent、baseline/Flink/final time-travel、3 metadata/
  8 manifest/6 parquet 对象图、容器/前缀/工作目录清理和 SourceSync `[0,0,0]` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_partition_file_scope_2026-08-24.json`，
  SHA-256 为 `788573f25501ff295ac4d68855bc8f673c964671379778317302ad579dfae8fc`。该证据只放行
  单表、两个 identity 分区、一次 matched-update MERGE 的物理文件范围；通用 partition evolution、
  MOR/delete files、混合分支跨分区写入、自适应 retry/backoff、provider recovery 和生产 HA 仍未完成。
- [x] 按 [ADR-282](architecture-decisions/adr-282-spark-flink-iceberg-partition-evolution.md)
  完成真实 Spark/Flink Iceberg bounded partition-spec evolution。Spark 先创建无分区 format-v2
  baseline，再真实执行 `ADD PARTITION FIELD identity(road_id)`；Flink 单并行度 append revision=2
  后，Spark 通过 `table.files.spec_id`、partition struct、snapshot parent 和 baseline time-travel
  证明 spec 0 的旧无分区 data file 保留、spec 1 的新 identity 分区 file 物化且两代 spec 可同时读取。
  报告 `docs/reports/chongqing_osm_spark_flink_partition_evolution_2026-08-25.json`，SHA-256 为
  `bb18139dd70686de855ea343d209caaaab12e0060bc0f83c8d4504bc8282fcfb`。该证据只放行单表、一次新增 identity field、单并行度 append；多次/并发
  evolution、schema evolution、混合 spec destructive write/MOR、跨 catalog 和生产 HA 仍未完成。
- [x] 按 [ADR-283](architecture-decisions/adr-283-spark-sql-mixed-spec-destructive-write.md)
  完成真实混合 partition spec 的 Spark SQL destructive-write 物理范围对账。目标道路在 spec 0
  旧无分区 file 和 spec 1 新 identity 分区 file 中各有一行；Spark SQL `DELETE` 后两个目标文件
  被精确移除，旧 spec 的 guard file 保留，最终行集、`append -> append -> delete` parent 链和
  baseline/Flink/final time-travel 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_mixed_spec_mor_delete_2026-08-25.json`，SHA-256 为
  `1b8843b2cc511817c8cd3c45668412dd643881523a895f7dbe3e9d5f710858d1`。真实 provider 行为记录为
  `copy-on-write`：虽然请求了 `write.delete.mode=merge-on-read`，本版本 SQL DELETE 未产生 delete
  file，因此 MOR 物理写入仍未放行。
- [!] 按 [ADR-284](architecture-decisions/adr-284-spark-flink-mixed-spec-equality-delete.md) 完成真实
  mixed-spec equality-delete capability probe。Spark baseline 注册 `road_id` identifier field，
  partition evolution 后由 Flink append revision=2，使目标道路同时位于 spec 0/spec 1；Flink 随后确实
  物化 `content=2`、`equality_ids=[1]` 的 equality-delete files，并删除 evolved spec 的 revision=2
  行，但 legacy spec 0 的 revision=1 行仍然可见，最终 logical key 未删除。真实 snapshot operation
  为 `append -> overwrite -> delete`，对象图和清理通过，但跨 spec equality delete 在当前 JDBC Catalog
  + Spark/Flink provider 组合下为 `unsupported`，因此不计入已支持能力。报告
  `docs/reports/chongqing_osm_spark_flink_mixed_spec_equality_delete_2026-08-25.json`，SHA-256 为
  `36f3860cab93d039cb991df2bf7a67eb0478856069f53175fc4c4b5ae4ac56a3`。同时新增
  `build_iceberg_equality_delete_admission`：在真实 `data_spec_ids=[0,1]` 上 fail-closed，要求先完成
  受控 rewrite/compaction。
- [x] 按 [ADR-285](architecture-decisions/adr-285-spark-controlled-rewrite-before-equality-delete.md)
  完成受控 rewrite 后 equality-delete 的真实闭环。第一次 `INSERT OVERWRITE` 试验确认旧 spec 0
  文件不会被全量替换，因此实现改为先物化源行、显式删除全部活动 data files，再用独立 DataFrame
  按 current spec append 回写。真实报告证明 rewrite 前 admission 对 `data_spec_ids=[0,1]` 为
  `rejected`，rewrite 后活动文件只剩 spec 1、admission 为 `admitted`；随后 Flink equality-delete
  物化 `content=2`、`equality_ids=[1]` Parquet 文件并删除 revision=1/2 两行。snapshot parent 链为
  `append -> overwrite -> delete -> append -> delete`，baseline/rewrite/final time-travel、对象图、
  容器/工作目录和 SourceSync `[0,0,0]` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_mixed_spec_rewrite_equality_delete_2026-08-25.json`，
  SHA-256 为 `863f025c25c86d8887d37acb65705db389e999299bf35aec9edd7b2f79b78428`。该证据只放行
  单表、一次 identity evolution、单并行度 Flink append、显式 delete+append rewrite 和 rewrite 后
  单键 equality-delete；自动 compaction/rewrite、并发 writer recovery、混合 spec UPDATE/MERGE 和
  生产 HA 仍未完成。
- [x] 按 [ADR-286](architecture-decisions/adr-286-flink-multi-file-position-delete-write.md) 完成两文件
  position-delete writer 的真实跨引擎验收。Spark 先以两个 append snapshot 物化两个 data file，两个目标
  道路分别绑定不同的 `_file/_pos`；Flink 单并行度单 RowDelta 写入一个 `content=1`、Parquet、
  `record_count=2` 的 delete file；Spark 独立验证两条物理 payload、两个原 data file 保留、最终只剩
  guard 行和 `append -> append -> delete` parent 链。报告
  `docs/reports/chongqing_osm_flink_spark_multi_file_position_delete_2026-08-25.json`，SHA-256 为
  `3f3240f581513e6aa5a96e1ac04aad56a11ddb124f629c9bc6b63a8639cf7de4`。该证据只放行无分区、两文件、
  单并行度、单 delete file 的 bounded writer；分区/更多文件扩展、并发冲突、自动 compaction 和生产 HA
  仍未完成。
- [x] 按 [ADR-287](architecture-decisions/adr-287-flink-multi-file-position-delete-stale-conflict-isolation.md)
  完成两文件 position-delete stale conflict isolation。第二个 Flink writer 继续绑定旧 baseline
  snapshot 和不同 token，真实进入 Iceberg validation 后整体被 `ValidationException` 拒绝；两个 position
  记录没有部分提交，catalog metadata location 与 snapshot 数量保持不变，物化但未提交的 delete file
  清理并输出 `orphan_cleanup=true`。冲突报告
  `docs/reports/chongqing_osm_flink_spark_multi_file_position_delete_conflict_2026-08-25.json`，SHA-256 为
  `86cbcfce87dd165b935e957c16fdb213be05c54f4b83298abb6ad3733ddb2df5`。该证据只放行无分区、两文件、
  单并行度 stale multi-file RowDelta 的整体拒绝和失败 artifact 清理，不代表自动 retry、更多文件、
  分区表、并发 writer recovery 或生产 HA。
- [x] 按 [ADR-273](architecture-decisions/adr-273-spark-sql-update-subquery-scope.md) 完成真实
  Spark SQL UPDATE 的不相关 scope 子查询切片。worker 建立 `gda_sql_update_scope` 临时视图，两个
  target `102262017/102262020` 为 `eligible=true`，guard `102262024` 为 `false`；真实 UPDATE 使用
  `road_id IN (SELECT scope_road_id ... WHERE eligible = true) AND revision = expected_revision`。
  stale baseline 被 snapshot guard 整体拒绝，fresh retry 重读 Flink child 后两个目标各更新一次，
  guard 行不变；baseline/Flink/final time-travel、`append -> append -> append -> overwrite` 链、
  4 metadata/10 manifest/7 parquet 对象图、容器/前缀/工作目录清理和 SourceSync `[0,0,0]` 均通过。
  报告 `docs/reports/chongqing_osm_spark_flink_sql_update_subquery_2026-08-24.json`，SHA-256 为
  `a0f540eb35f15e46ffa7f1f52495c232192c086de9d07b7f0a872c973b8923c1`。该证据只放行单表、两个
  target、一个不相关 scope subquery；相关子查询、UPDATE join、多表写入和生产 recovery 仍未完成。
- [x] 按 [ADR-274](architecture-decisions/adr-274-spark-sql-merge-adaptive-backoff.md) 完成真实
  Spark SQL MERGE retry budget 的自适应退避切片。重复 source cardinality admission 在同 worker
  内按 `0/0.01/0.02` 秒策略等待，预算 `3`、强制尝试 `4`；报告记录实际等待约
  `0/0.01063/0.02009` 秒，前三次均 `duplicate_source_rejected_before_merge`，第 4 次未提交。
  catalog、行集和 snapshot 保持不变；真实重庆 OSM source、Flink child、对象图、容器/前缀/工作目录
  清理和 SourceSync `[0,0,0]` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_retry_backoff_2026-08-24.json`，SHA-256 为
  `7edfa487c8829aca922545c7f7f4b3fccf8670639fd6d410280214bc2b990189`。该证据只放行同 worker、
  单表、bounded budget 的等待与 fail-closed；provider abort recovery 和生产 SLO 仍未完成。
- [x] 按 [ADR-275](architecture-decisions/adr-275-spark-sql-merge-successful-retry.md) 完成真实
  Spark SQL MERGE 退避后的成功 fresh retry。重复 source cardinality rejection 后实际等待约
  `0.01161` 秒，再按 fresh deduplicated source 提交一次 overwrite；fresh token 出现一次，
  未选 token 缺失，snapshot parent 为 Flink child，baseline/Flink/final time-travel、3 metadata/
  7 manifest/5 parquet 对象图、容器/前缀/工作目录清理和 SourceSync `[0,0,0]` 均通过。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_successful_retry_2026-08-24.json`，SHA-256 为
  `edf618ff83cddf0cfca56eb8373fbb9a2fb090b358c1f984a2f6485d5d418a89`。该证据只放行单 worker、
  单表、单 target 的一次成功 retry；provider abort recovery 和生产 HA 仍未完成。
- [x] 按 [ADR-276](architecture-decisions/adr-276-spark-sql-merge-cross-process-budget.md) 完成真实
  Spark SQL MERGE 跨进程 retry-budget admission。两个独立 OS worker 连接同一个 PostgreSQL authority，
  对同一 `operation_key` 并发发起各 2 次 admission；预算为 3，账本真实记录 3 次 admitted 和第 4 次
  `retry_budget_exhausted` denied，attempt number 全局连续，超限不递增。临时 schema、worker 工作目录
  清理完成，主 SourceSync 保持 `[0,0,0]`。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_cross_process_budget_2026-08-24.json`，SHA-256 为
  `d1fe66415803d47cb44b1880dccce58076c1a6957e44447febc63d270c97202e`。该证据只放行共享 PostgreSQL
  admission ledger；不代表跨进程 Iceberg destructive write beyond this bounded sequence、provider abort recovery、
  exactly-once 或生产 HA 已完成。
- [x] 按 [ADR-277](architecture-decisions/adr-277-spark-sql-merge-multiple-successful-retries.md) 完成真实
  Spark SQL MERGE 连续成功 fresh retry。Flink child 先将目标推进到 revision 2；Spark 先拒绝 stale
  duplicate source，再 fresh 提交 revision 3，并重新读取 revision 3 后再次提交 revision 4。四个
  snapshot 的 operation/parent 链为 `append -> append -> overwrite -> overwrite`，两次 overwrite
  均成功、最终行集和独立 time-travel 校验通过，第二次 retry token 仅出现一次。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_multiple_successful_retries_2026-08-24.json`，
  SHA-256 为 `981d132dc581ffc72a8d9b6d4da0f991721232b0193b1b045f5d3f3a130bb873`。该证据只放行
  单 worker、单表、单 target 的连续两次成功 retry；provider abort recovery、
  exactly-once、REST/Gravitino destructive-write conformance 和生产 HA 仍未完成。
- [x] 按 [ADR-278](architecture-decisions/adr-278-spark-sql-merge-cross-process-successful-retry.md) 完成真实
  Spark SQL MERGE 跨进程成功 fresh retry。两个 distinct Spark worker 共享同一 JDBC Iceberg Catalog：
  first worker 在 Flink child 上拒绝 stale duplicate source 并提交 revision 3，second worker 重新
  读取 revision 3 后提交 revision 4。四段 snapshot parent 链、两个 worker 的独立 checks、revision 3
  中间 time-travel、最终行集和对象/容器/工作目录清理均通过，主 SourceSync 保持 `[0,0,0]`。报告
  `docs/reports/chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry_2026-08-24.json`，
  SHA-256 为 `f58dc0cfc69e848764f4ec45c619278a4fb98d1aebf37656597c6492891ea9b5`。该证据只放行
  两个独立 worker、单表、单 target 的成功 retry；provider abort recovery、跨系统 exactly-once、
  REST/Gravitino destructive-write conformance 和生产 HA 仍未完成。
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
  自动修复/恢复、物理磁盘耗尽与 predictive capacity SLO、Flink/Iceberg 物理故障后的生产
  HA/fencing/RPO-RTO（终态 checkpoint 后的 bounded SIGKILL/网络断开 reconciliation 已按
  ADR-254 验证）、position/MOR
  destructive-write 复杂谓词并发冲突隔离、SQL UPDATE 相关子查询/join/跨分区语义及 SQL MERGE provider abort recovery、多分支/多 target row 冲突隔离、
  REST/Gravitino destructive-write catalog 互操作、
  并发/reconcile、
  DataSLO/Incident、
  DriveTransfer 生产 provider、双租户、备份恢复和默认/轻量/
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
- [x] 按 [ADR-253](architecture-decisions/adr-253-drive-transfer-lightweight-file-lake-acceptance.md) 完成
  `DriveTransfer` lightweight local file-lake slice：真实重庆 OSM GeoParquet bundle 经过 11 个
  1 MiB 分片的乱序上传、错误 checksum 中断与断点恢复，完成 Raw immutable commit、full hash、
  ZIP 安全解包、expanded manifest、GeoParquet profiling、upload/expansion lineage 和 ingest
  replay 幂等；报告 `.tmp/drive-transfer/lightweight-acceptance-report.json` 的 canonical
  `report_sha256` 为 `de8eda36b9f3bf67bc3da834515791504e7e66d39ea04e899ce51d1727b86f96`，文件
  SHA-256 为 `e166098deda2fef91becd13007a0d581c363e1c97014159d4ab6dbc87c22e161`。该证据只放行
  本地 file-lake profile，不代表 PostgreSQL durable session、S3 multipart、云盘/NAS/SMB/FTP/SFTP、
  多租户生产身份/配额/扫描、TB 吞吐或 HA/RPO/RTO。
- `DriveTransfer` 生产合同仍包括 `DriveEndpoint/FolderBinding/TransferSession/TransferCheckpoint/FileRevision/IntegrityVerdict/ArtifactManifest/IngestRequest`、上传/下载/目录同步、S3 multipart pre-signed URL 与认证 NAS/SMB/FTP/SFTP provider、pause/resume、part/full checksum、输入 fingerprint、配额、quarantine、bundle completeness、DolphinScheduler 入湖 process；本地 checkpoint 仅供恢复，服务端 session/manifest/audit 是真值。生产 profile 尚未完成。
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
- [x] 已完成首个最小可运行 `DataProductBlueprint` 编译切片：typed contract 覆盖 tenant、domain、owner、
  source、storage placement、model、quality、security、SLO、pipeline、projection、retention 和 cost，使用
  canonical SHA-256 阻止内容篡改，并统一 UTC/offset 时间表达；definition、product 与全部 source URN 必须
  属于同一 tenant。`POST /api/platform/v1/data-product-blueprints` 复用既有认证、tenant/actor 防伪和
  `PlatformGateway.register_definition()`，将 Blueprint 确定性编译为已有 `Resource`、`ResourceVersion` 和
  `PlatformDefinitionVersion`，未增加第二套 registry、migration、queue 或 lifecycle authority。创建、幂等、
  actor/tenant 拒绝、非法合同和 OpenAPI/static-boundary 已覆盖；与 platform gateway、MVT、ConsumerBinding、
  GIS service control plane 以及一次性 PostgreSQL 16 写入的最终聚焦回归为 `122 passed`；数据库验证确认重复
  注册后现有三张 authority 表各只有一条记录且 Blueprint/definition hash 一致。该证据只代表
  Blueprint-to-definition authority 的首个开发环境切片，不代表 Visual/SQL/Notebook Build 工作台、
  preview/test/publish/approval 完整链、统一模型版本、DataOps CI/CD parity、production rollout 或 AR-3
  已 verified。
- [x] 已将 Blueprint 推进到无副作用的 compile preview：`POST /api/platform/v1/data-product-blueprints/preview`
  读取可选 predecessor `PlatformDefinitionVersion`，输出 deterministic logical-definition diff、四项
  compile checks、compile verdict、`change_set_sha256` 和可直接提交给既有 ApprovalCase authority 的
  `target_resource_urn/target_fingerprint/action` review binding；preview 不写数据库，不伪造 publish 或 approval。
  successor 的 `ResourceVersion.predecessor_version_id` 已绑定现有 immutable ledger，且同一 definition Resource
  的 authority locator/technical refs 已保持跨版本稳定，避免把 version/hash 错误写进 Resource identity。
  preview、route non-mutation、predecessor mismatch、OpenAPI/static boundary 与一次性 PostgreSQL 16 的
  v1 注册、v2 diff、predecessor 外键和重复注册验证均已通过。该切片仍不代表 ApprovalCase 已自动创建、模型
  版本目录、Visual/SQL/Notebook 工作台、DataOps CI/CD parity、publish/rollback 生命周期或生产证据完成。
- [x] Blueprint changeset 已接入统一 ApprovalCase authority：
  `POST /api/platform/v1/data-product-blueprints/reviews` 必须提交完整 typed Blueprint，服务端重新读取 predecessor
  并重建 preview，不信任客户端提供的 changeset/fingerprint；随后以 definition version 生成 deterministic case
  identity，将 `change_set_sha256` 精确绑定为 `target_fingerprint`，action 固定为
  `data_product_blueprint.change_review`。ApprovalCase context 只保存 definition/predecessor/hash、变化路径和 compile
  evidence hash 的有界摘要，不复制 Blueprint 或另建 review registry。tenant/actor 防伪、创建/重放幂等和
  OpenAPI/static boundary 已覆盖；一次性 PostgreSQL 16 验证了 pending case、初始化事件、同 version 换内容冲突、
  独立 human reviewer 的 CAS 批准和第二条不可变事件；连同 platform gateway、MVT、ConsumerBinding 和 GIS service
  control plane 的最终聚焦回归为 `127 passed`。definition 注册是候选 definition 落账，不等同 publish。
- [x] Blueprint changeset ApprovalCase 已进入 `DataProductVersion` release/promotion 强制门：preview 和 ApprovalCase
  context 现同时绑定 `product_urn`、目标 `version_key`、definition/Blueprint hash 与 `change_set_sha256`；typed
  `DataProductBlueprintReleaseBinding` 将 definition URN/version/hash、changeset 和 ApprovalCase ref 写入
  `distribution_manifest.blueprint_release`，由既有 `manifest_sha256` 纳入不可变版本合同，没有新增 registry、
  approval authority 或 migration。`DataProductRegistry.publish()` 对声明该 manifest 的版本要求显式提供同一 typed
  binding，并在写产品、版本和 pointer 之前、同一 PostgreSQL 事务内重新读取 `PlatformDefinitionVersion`、
  `ResourceVersion` 和 ApprovalCase，精确校验 tenant/product/version、definition/Blueprint hash、action/target/
  fingerprint/context、approved 状态、独立 human verdict、decision 时序与未过期条件；pending、rejected、expired、
  tampered 或缺失 binding 均 fail closed。后续 `promote()` 会从已持久化 manifest 重新构造 typed version/binding 并
  复核 live ApprovalCase，旧的非 Blueprint 发布路径保持兼容。一次性 PostgreSQL 16 已验证 pending/rejected/
  expired/tampered 拒绝、approved 双次确定性校验、完整 publish、active pointer、manifest 持久化和幂等重放仅一条
  lifecycle event；聚焦单元回归为 `40 passed`。该门禁仍不代表模型版本目录、Visual/SQL/Notebook Build 工作台、
  test/rollback、DataOps CI/CD parity 或 staging/production rollout 完成，因此 AR-3 保持 `in_progress`。
- [x] 已补齐普通 Blueprint release 的平台发布边界：`POST /api/platform/v1/data-products/blueprint-releases`
  只接受 workload identity，校验 tenant、`version.published_by` 与 typed
  `DataProductBlueprintReleaseBinding`/`distribution_manifest.blueprint_release` 一致性，然后委托唯一的
  `DataProductRegistry.publish()`。新发布返回 `201`，幂等重放返回 `200`，冲突/缺失/注册表不可用映射为稳定错误；
  路由不直接写控制库、不复制 ApprovalCase 或 DataProductVersion 状态机。聚焦 gateway/OpenAPI/合同测试已通过。
  该切片仍使用现有 registry 的真实 PostgreSQL 门禁；本地路由 double 不构成生产验收，AR-3 继续保持
  `in_progress`。详细边界见 [ADR-206](architecture-decisions/adr-206-blueprint-release-publish-gateway.md)。
- [x] 已补上 Build 工作台的首个 deterministic contract-test gate：`POST /api/platform/v1/data-product-blueprints/tests`
  对 typed Blueprint 只做无副作用的 definition 编译和契约检查，输出稳定排序的 source/storage/pipeline/
  projection/quality-security-SLO、Blueprint hash 与 definition hash evidence，并以
  `test_report_sha256` 封存；preview 同时携带相同 test report，ApprovalCase context 和
  `DataProductBlueprintReleaseBinding` 也精确绑定该 hash。该入口不冒充 provider 执行或 PlatformRun，后续真实
  Visual/SQL/Notebook test 可以复用同一 definition/Run/Artifact authority；tenant/actor 防伪、重复调用确定性和
  OpenAPI route registration 已覆盖，聚焦 Blueprint/platform 回归为 `120+ passed`，真实 PostgreSQL publish
  验收继续通过。它仍不代表真实 provider test execution、模型版本目录或完整 Build 工作台完成。
- [x] 已将 contract-test 从静态预检推进到既有 `PlatformRun` admission：
  `POST /api/platform/v1/data-product-blueprints/test-runs` 接受显式、tenant-scoped 的
  `ResourceBinding` 输入版本和幂等键；服务端重新编译并核对已注册 `PlatformDefinitionVersion`，要求每个
  Blueprint source 都被精确绑定，然后在同一事务写入 `PlatformRun` 与不可变 execution-plan `Artifact`。
  execution plan 同时绑定 Blueprint/definition/test-report hash、source ResourceVersion/content hash 和
  `provider_execution_required=true`，重放复用同一 Run/Artifact identity；admission 不调用 provider、不写
  `DataProductVersion`，因此 pending/failed test 不会产生 active product。新增 route、请求合同、输入缺失/错配
  和幂等边界的单元覆盖，聚焦 Blueprint/platform 回归为 `97 passed`。真实 provider executor、attempt
  observation、output Artifact、QualityResult、LineageEvent、RunSuccessEvidence、失败重放以及成功证据后
  publish 仍未完成。
- [x] 已将 admitted Blueprint test 接入一个明确隔离的 deterministic local executor：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/execute` 仅接受 workload identity，
  重用同一 `PlatformRun`/execution-plan Artifact，写入 output `ResourceVersion`、output/evidence Artifact、
  独立 workload 评估的 passed `QualityResult`、DuckDB framework 的
  `gda.blueprint_test_executor_receipt.v1` deterministic-local attempt observation、输入到输出
  `LineageEvent`，最后调用迁移 `197_blueprint_test_execution_success.sql` 的 evidence-gated success authority。
  success authority 会重新校验 output content binding、独立质量证据、血缘、receipt schema/mode 和
  `RunSuccessEvidence` fingerprint；相同 request 重放复用相同 UUID/证据与 terminal event，不发布
  `DataProductVersion`。新增 PostgreSQL 16 acceptance 已验证 succeeded/passed、独立 evaluator、
  deterministic-local receipt、RunSuccessEvidence 和幂等重放，Blueprint/platform 聚焦回归为
  `124 passed`，Gateway report、Ruff、compileall、diff check 均通过。该切片只证明平台证据链和本地
  executor 边界，不代表真实 DuckDB/Spark/provider conformance、staging/production executor，亦不把
  deterministic receipt 当作生产执行结果。
- [x] 成功 test evidence 已可作为发布绑定的可选增强门：`DataProductBlueprintReleaseBinding` 可精确引用
  `test_run_id` 与 `test_success_evidence_sha256`，旧的只绑定静态 `test_report_sha256` 合同保持兼容；若声明
  执行证据，`DataProductRegistry.publish()` 在同一事务中重新检查 execution-plan 对 Blueprint/definition/
  test-report/product/version 的绑定、共享 `PlatformRun` 的 `succeeded` 终态、终态事件中的
  `RunSuccessEvidence` hash 和 deterministic-local receipt。缺失、错配、未成功或非 deterministic receipt
  均 fail closed，未新增 publish registry、scheduler 或 success authority。PostgreSQL 16 acceptance 已验证
  成功执行证据绑定后的 live release validation、完整 publish 与幂等重放；该门目前是可选的，尚未强制所有
  Blueprint 发布必须经过真实 provider execution。
- [x] deterministic local executor 已补齐显式 failure receipt：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/fail` 仅接受 admitted Run 的 workload
  identity，并复用同一 execution-plan Artifact；failure details 固定绑定 plan、error code 和 reason，
  通过既有 `transition_platform_run()` 进入 `failed`。相同 failure receipt 幂等重放返回同一 terminal Run，
  不生成 output/quality/success evidence；已验证 workload/path 身份拒绝、终态冲突、真实 PostgreSQL
  failure transition 和 replay。该入口只提供测试执行失败的控制面证据，不代表 provider cancel/reconcile、
  retry/backoff 或生产 executor 已完成。
- [x] 已补齐 governed cancellation 后的 executor convergence：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/cancel` 仅接受 workload identity，
  要求 Run 已处于 `cancelling` 或 `reconciling`，并绑定同一 execution-plan Artifact；随后通过既有
  `transition_platform_run()` 进入 `cancelled`。相同 `external_cancel_ref`/reason 幂等重放复用同一终态事件，
  非 workload、path/body mismatch、未进入取消态和终态冲突均 fail closed。真实 PostgreSQL acceptance 已
  验证 `dispatching -> running -> cancelling -> cancelled`、幂等重放和无 output/success evidence 副作用；
  这仍不代表 provider reconcile、retry/backoff、取消超时 incident 或生产 executor conformance。
- [x] 已建立首个通用 provider reconcile 纵向切片：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/reconcile` 仅接受 workload identity，
  typed receipt 同时绑定 tenant、 admitted execution-plan Artifact、provider framework/external run reference、
  attempt observation、provider state 和 receipt SHA-256；明确排除 DolphinScheduler/Temporal/legacy callback，
  不复用调度器专用 policy 或 callback authority。平台只允许既有 `reconciling` Run 收敛到
  `running`、`failed` 或 `cancelled`，通过既有 SECURITY DEFINER `transition_platform_run()` 完成状态锁定；
  相同 observation/receipt replay 复用同一 immutable `platform_run_event`，不同 verdict、错误 plan、错误 tenant、
  非 workload、未进入 reconciling 的请求均 fail closed。一次性 PostgreSQL 16 acceptance 已验证三种收敛结果、
  workload/actor/plan 拒绝和幂等重放；这仍不代表真实 DuckDB/Spark/provider executor conformance、retry/backoff、
  取消超时 incident 或生产 provider rollout。
- [x] 已补齐 Blueprint provider 取消超时的 incident 收敛切片：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/cancel-timeout` 仅接受 workload identity，
  typed timeout receipt 同时绑定 tenant、admitted execution-plan Artifact、非终止 provider observation、
  `reconcile_attempt/max_reconcile_attempts` 和 timeout receipt SHA-256；只有取消处于 `cancelling` 或
  `reconciling` 且重试次数已耗尽时，才通过既有 `DataIncident` authority 原子创建 high-severity
  `blueprint_provider_cancellation_timeout` incident，并复用 `transition_platform_run()` 将 Run fail closed
  为 `failed`，不伪造 `cancelled`。稳定 incident/Run event identity 保证相同 observation/receipt 重放不新增
  incident、incident event 或 `platform_run_event`；错误 actor、plan、tenant、非 workload、未耗尽重试和已终止
  provider state 均 fail closed。单元/路由回归 103 项，隔离 PostgreSQL 16 acceptance 1 项通过；真实 provider
  executor conformance、retry/backoff 和生产 rollout 仍未完成。
- [x] 已补齐通用 Blueprint provider retry/backoff 切片：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/retry` 仅接受 workload identity，typed
  retry receipt 绑定 tenant、execution-plan Artifact、transient provider observation、当前 retry attempt/
  max budget 和 receipt SHA-256；仅允许 `reconciling` Run 进入下一次 `dispatching`，退避策略固定为有界指数
  backoff（5s、10s、20s...，上限 300s），`retry_after` 由 observation 时间和平台策略确定；Run transition 与
  `blueprint_provider.retry` command 在同一事务落账，既有 command outbox 的 `available_at` 在数据库层阻止提前
  claim，immutable `platform_run_event` 同时保存完整 backoff 决策。相同 observation/receipt replay 复用同一
  event/command，不新增 observation、command 或状态迁移；错误
  actor、plan、tenant、非 transient provider state、非 reconciling Run 和耗尽 retry budget 均 fail closed，耗尽
  后必须提交现有 terminal reconcile/timeout receipt。迁移 `198` 只扩展既有 command vocabulary，不新增表；
  聚焦合同/路由/migration 回归 151 项，隔离 PostgreSQL 16 acceptance 1 项通过并验证到期前零 claim；这仍不
  代表真实 provider executor conformance 或生产 rollout。migration catalog 为 198 项，fingerprint 为
  `54a08cbd2aef31c2d4011a91d929beffbf220bcf8ce85502b789ac7ce9260478`。
- [x] 已按 [ADR-197](architecture-decisions/adr-197-bound-duckdb-blueprint-provider.md) 完成首个真实
  Lightweight DuckDB/Parquet Blueprint provider：
  `POST /api/platform/v1/data-product-blueprints/test-runs/{run_id}/providers/duckdb/execute` 只接受固定
  `workload:blueprint-duckdb-executor`，admission 要求每个输入具有完整 SchemaVersion/DataContractVersion/
  PhysicalLocation/architecture binding，并把 Parquet `file://` locator、ResourceVersion/content SHA-256、location/
  schema/contract/binding fingerprint、typed DuckDB pipeline、固定输出 URI 和 plan hash 封入同一个 execution-plan
  Artifact。provider 先用 PyArrow 读取且复核精确输入字节，再将表注册到内存 DuckDB、关闭 external access，
  只允许单条只读 SQL 引用 admitted relation；未绑定关系、catalog/schema、file/network table function、DDL/DML、
  无序 deterministic 输出、输入篡改、超时和超行数均 fail closed，输出以 atomic replace 写出真实 Parquet。
  typed receipt 固化真实 DuckDB 版本、input/output rows/bytes、columns、duration、atomic-output checkpoint、output
  checksum 和 external-access verdict；provider-local certify 双次执行并比较实际 Parquet hash。迁移 `199` 在不修改
  历史迁移的前提下扩展同一个 Blueprint success authority，数据库重新验证 plan/definition/output Artifact/
  independent QualityResult/LineageEvent/DuckDB observation 后才允许 `succeeded`；live Blueprint release gate 也已接受
  该 real provider receipt。provider 单元 conformance `8 passed`，Blueprint/platform 聚焦回归 `134 passed`，隔离
  PostgreSQL 16 acceptance `1 passed`，91 条 Platform route/OpenAPI operation、Ruff、compileall 和 diff check 通过；
  migration catalog 为 199 项，fingerprint 为
  `a9f91b1071eb699077fea42c951f6462a8bfdf3da1dc6de0d12045b565e5dbe5`。该认证仅覆盖同步本地 DuckDB/Parquet
  核心执行；DuckDB Spatial extension 尚未安装认证，外部长任务 cancel/reconcile 对此 adapter 为 not applicable，
  Spark provider、生产 worker、HA、staging/production rollout 仍未完成。
- [x] 已按 [ADR-198](architecture-decisions/adr-198-managed-duckdb-blueprint-command-worker.md) 将 DuckDB Blueprint
  执行从 HTTP 请求生命周期推进到 managed command worker：DuckDB admission 现于同一事务创建 Run、execution-plan
  Artifact 和 plan/definition hash 绑定的 `blueprint_provider.execute` command，且只允许固定
  `workload:blueprint-duckdb-executor` 准入和领取。`gda-duckdb-blueprint-worker` 复用既有 tenant-scoped outbox 的
  due/lease/SKIP LOCKED/ACK/redelivery 语义，在 API 与控制面事务之外执行真实 DuckDB；成功权威仍由迁移 199
  的 Run/output/quality/lineage evidence gate 唯一收敛。Run 已终态的重投只完成 command ACK、不重算 provider，
  控制面瞬时故障以脱敏稳定错误码回到 outbox；Worker 提供配置预算、DuckDB/PyArrow/output-root readiness、私有
  原子状态文件、health/liveness、`validate` 和 graceful stop。迁移 `200` 只扩展共享 command vocabulary，不新增
  scheduler、Run 或 provider state 表；同 admission 重放和成功后错误 workload 读取均已在真实 PostgreSQL 16
  fail closed。Provider/worker 单元回归 `17 passed`，扩展 Blueprint/platform 聚焦回归 `144 passed`，隔离
  PostgreSQL 16 worker-to-release acceptance `1 passed`；migration catalog 为 200 项，fingerprint 为
  `e0b1827cf6d636671b3ba25aa0a43c7618a041851a262a9e3b9f32f8bbfa1e48`。该切片完成可部署进程合同，尚未加入
  Compose/Kubernetes workload；输入/输出仍为需 API 与 worker 共享挂载的 `file://`，immutable object-store、
  长任务 lease heartbeat、multi-replica HA、NetworkPolicy、容量 SLO 与 staging/production rollout 仍未完成。
- [x] 已按 [ADR-199](architecture-decisions/adr-199-immutable-object-store-duckdb-blueprint-io.md) 完成 DuckDB
  Blueprint 不可变对象存储 I/O 合同：S3/MinIO profile 将输入绑定为 allowlisted `s3://` URI、ResourceVersion
  SHA-256 与 PhysicalLocation `revision_ref` 中的精确 VersionId；worker 流式暂存 exact-version bytes、执行总字节
  上限和 SHA-256 复核，DuckDB 仍关闭 external access。输出使用 tenant/Run 稳定 key、`If-None-Match: *` 条件
  创建、VersionId/ETag、HEAD 与 exact-version GET 回读；同字节 replay 复用证据，异字节绝不覆盖。receipt、
  Artifact manifest 和 framework observation 保存同一 `gda.s3_object_version.v1`，migration `201` 在数据库层
  强制 S3 输出证据；临时对象存储故障保持 Run 非终态并由 outbox 重投，完整性冲突才终态失败。local `file://`
  profile 保持兼容；对象存储/provider/worker/gateway/platform 聚焦回归通过，migration catalog 为 201 项，
  fingerprint 为 `091240116b1bac49799032082abd3c56d6c52bfdd14fef99f7abf86f6a7362ca`。真实
  disposable MinIO 已通过 12/12：admission 后 current input 覆盖仍读取原 VersionId、条件输出、exact-version
  readback、输出 current version 被新增版本遮蔽后仍验证原 VersionId、同字节 replay、异字节拒绝及完整清理，
  报告 SHA-256 为 `3ab007d9841f1e87c8cfbe68eb58b4d9e6b133ddc8aadd83a18d2c34ae72f199`。该 ADR 当时尚未认证的
  scoped worker identity、worker-to-release/ACK-loss、权限故障注入和部署合同已由下一项 ADR-200 继续收敛。
- [x] 已按 [ADR-200](architecture-decisions/adr-200-duckdb-blueprint-worker-deployment-and-redelivery.md)
  完成 DuckDB Blueprint worker 的首个部署与 redelivery 切片：Compose 通过显式 `blueprint` profile 启动独立
  worker，API 只共享非 secret S3 bucket/prefix 配置，专用 MinIO credential 只进入 worker；私有 workspace/status、
  read-only root、tmpfs、drop ALL capabilities、no-new-privileges、原生 health 和生产 2 CPU/4 GiB 上限均已接线。
  MinIO bootstrap 创建 Object Lock + default governance retention 输出 bucket，并绑定只允许 admitted input exact-version
  read、output prefix get/put 和 readiness probe 的 policy。可选 Kubernetes Kustomize profile 固定 UID/GID 999、
  RuntimeDefault seccomp、无 SA token、只读根和私有 emptyDir，egress 仅 DNS/PostgreSQL/MinIO；base MinIO policy 的空
  pod selector 已移除，避免 additive policy 绕过隔离。deployment/object-store/worker 聚焦回归 `27 passed`，两种
  Compose model 与 Kustomize 均离线渲染。scoped disposable MinIO IAM 认证 `8/8`，证明 cross-prefix read/write、delete
  和 retention bypass 均拒绝，报告 SHA-256 为
  `e59f6d771ea5e717479c1e4592b182dfd795bf1882522fa140cd1e5eb03fb8b5`。真实 PostgreSQL + scoped MinIO
  worker-to-release acceptance 通过：worker A 完成 provider/Run 后故意丢 ACK，lease 过期由 worker B 重领，command
  `attempt_count=2`、只做一次 terminal reconcile、不重算或覆盖 exact output VersionId，并通过 live release gate；报告
  SHA-256 为 `1e5d2eeed390d99351475c1232bd89a2ea4ab527d6ccf4881c58383483d83c7d`，临时 bucket/container 完整清理。
  该切片仍不代表真实集群 NetworkPolicy enforcement、identity rotation、mid-query lease heartbeat、multi-replica HA、
  capacity/SLO 或 staging/production rollout。
- [x] 已按 [ADR-201](architecture-decisions/adr-201-duckdb-spatial-blueprint-conformance.md) 完成 DuckDB Spatial
  Blueprint conformance：DuckDB 固定为 `1.5.5`，镜像构建期下载官方匹配 Spatial extension 并复制为只读
  `/app/duckdb-extensions/spatial.duckdb_extension`；worker 运行期关闭 DuckDB auto-install/auto-load，只能 `LOAD`
  该预装路径，receipt 固化 extension version、binary SHA-256、install source/mode 和禁用自动安装/加载的证据。
  Spatial Blueprint 必须显式声明 `require_spatial: true` 与 `spatial_output_srid`，否则空间 SQL fail closed；输出强制
  `geometry_wkb + srid + bbox`，逐行验证 WKB、有界 SRID、有限且与 geometry envelope 一致的 bbox，并写入
  GeoParquet 1.1 WKB/PROJJSON `geo` metadata。迁移 `202` 在 Artifact/observation 约束和 terminal-event trigger
  双层重新校验 extension/output evidence 与 admitted pipeline 的 SRID，非空间 provider receipt 携带空间证据也 fail
  closed。真实 DuckDB Spatial 的 EPSG:4326 -> EPSG:3857 execution、deterministic replay、extension/path/encoding
  fault cases 共 `13 passed`；PostgreSQL 16 managed command/ACK-loss/release-gate acceptance `1 passed`；独立认证脚本
  `scripts/certify_duckdb_blueprint_spatial.py` 报告文件 SHA-256 为
  `9a5db90b605cb7e07f21256373f54f1933567800cfb22d94ad32a97d3839bd37`。migration catalog 为 202 项，fingerprint
  为 `22bfbcd9ff64d24bfdfd47777e1b8b357adfb001c7fb4f12c67e772c693a0f8e`。此证据只覆盖 DuckDB bounded
  local/provider + disposable PostgreSQL；Spark/Sedona/Flink/PostGIS 的 shared geometry encoding/temporal/GeoParquet
  cross-engine conformance、真实集群 NetworkPolicy/identity、heartbeat/HA/capacity/SLO 与 staging/production rollout
  仍未完成。
- [x] 按 [ADR-288](architecture-decisions/adr-288-spark-iceberg-provider-rehearsal-and-authority-gap-recovery.md)
  完成真实 Spark/Iceberg provider rehearsal。隔离 Spark 3.5/Iceberg 1.6.1、MinIO 和临时 PostgreSQL 中，
  provider 对 445 个真实客户空间 feature（439 个 distinct parcel）完成 rebuild；随后模拟 provider 已提交、
  控制面 checkpoint 尚未落账的 authority gap，重启 executor 后 receipt replay 恢复同一 snapshot/commit ref，
  不重复写入，并完成同内容新 snapshot 冲突、stale predecessor fail-closed、checkpoint-only recheck、delete
  receipt/tombstone replay 和顺序 checkpoint history。18 项检查全部通过，临时 database、bucket、container、
  volume、network 全部清理。报告 `docs/reports/lakehouse_projection_spark_provider_rehearsal_2026-08-25.json`，
  SHA-256 为 `6ef9bfb71170e179cd5c102d875412e1f3e20992f484c8fbad49cedcffe634b7`。该证据只覆盖 disposable
  bounded provider 和 authority-gap recovery，不代表生产 Spark 集群、长任务 cancel/reconcile、HA、容量 SLO、
  NetworkPolicy/identity rotation 或 staging/production rollout。
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
- [x] 已将既有 GIS Service Control Plane authority 暴露为正式平台入口：
  `GET /api/platform/v1/gis/services/{service_id}/control-projection` 以认证 tenant 构造 canonical GIS service URN，
  返回 active endpoint、deployment、definition、release、layer/style/TMS、cache/policy 与 MVT serving projection；
  `POST /api/platform/v1/gis/services/{service_id}/activation` 仅允许 admin 以 endpoint revision、state-version CAS、
  actor、原因、幂等键和固定 `occurred_at` 切换 active pointer。发生时间进入幂等事件内容，确保故障重试可重放同一
  activation event；ready-deployment、RLS、CAS、不可变 event 和跨租户校验仍由 migration 153 的 PostgreSQL recorder
  执行。7 个路由契约测试覆盖认证、角色、canonical service ID、tenant delegation、请求校验、冲突映射和 OpenAPI；
  详见 [ADR-207](architecture-decisions/adr-207-gis-service-control-plane-gateway.md)。此切片提供 inspect/activate
  API，不替代发布审批、provider deploy/readiness、缓存预热、provider activation、rollback orchestration 或 ServiceSLO/
  incident 闭环，AR-4 的总体退出门仍以完整 provider/conformance/operations 证据为准。
- [x] 已补 DeploymentRevision 的服务归属查询和受控状态迁移入口：
  `GET /api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}` 先按认证 tenant 解析 service，
  再复核 deployment 所属 `GISServiceDefinitionVersion`；`POST .../transitions` 只接受 workload identity 的
  `planned -> deploying -> ready|failed` 事件，并固定 CAS version、原因、幂等键和 timezone-aware `occurred_at`。
  `deploying` 禁止携带 observation，`ready/failed` 必须携带 observation；数据库仍复核同一 PlatformRun、provider
  deployment/revision evidence、Run terminal 状态、RLS、CAS 和 append-only event，不由 Gateway 或 provider 直接改写
  lifecycle。13 个路由契约测试覆盖 service ownership、workload admission、payload、委派、冲突映射和零 provider 调用；
  详见 [ADR-208](architecture-decisions/adr-208-gis-service-deployment-transition-gateway.md)。此切片使服务状态可
  inspect/transition，不包含 deploy command、provider health probe、approval、endpoint creation、cache warmup、
  activate/rollback orchestration 或 ServiceSLO/incident 闭环。
- [x] 已补 ready deployment 到 immutable EndpointRevision 的受控登记入口：
  `POST /api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/endpoints` 只接受 workload 的
  endpoint UUID、协议、无 credential HTTPS URI、endpoint contract 和发生时间；Gateway 从认证与路径生成 tenant、service
  URN、deployment ID、creator 和 endpoint hash，避免客户端伪造服务归属或不可变身份。migration 153 继续强制 deployment
  已 ready、服务匹配、endpoint time 不早于 readiness、服务类型/协议兼容、RLS 与 UUID 内容幂等。17 个路由契约测试覆盖
  workload admission、服务端 identity/hash、URI 校验、ready-gate 冲突映射、零 provider 调用和 OpenAPI；详见
  [ADR-209](architecture-decisions/adr-209-gis-service-endpoint-registration-gateway.md)。该入口只登记 endpoint metadata，
  不公开 provider、不切换 active pointer、不执行健康检查/审批/cache warmup/rollback 或 ServiceSLO/incident。
- [x] 已补 release-bound `ServiceDeploymentRevision` 的初始登记入口：
  `POST /api/platform/v1/gis/services/{service_id}/deployments` 只接受 workload 提交既有
  `PlatformRun`、服务 definition/release、provider placement、revision key、configuration hash 和有时区的创建时间。
  Gateway 由认证 tenant 与 path 生成 service URN，复核 definition 与 release 都属于该服务后，固定 `planned` / state
  version `0`、认证 actor 和 deployment fingerprint；migration 154 继续校验 release 完整性、Run/definition 一致性、Run
  input 中 source DataProductVersion output ResourceVersion、RLS 及 UUID 内容幂等。21 个 route contract tests 覆盖
  workload admission、服务/release 归属、服务端身份字段、Run evidence conflict、零 provider 调用及 OpenAPI；详见
  [ADR-210](architecture-decisions/adr-210-gis-service-deployment-registration-gateway.md)。该入口只登记计划中的 placement，
  不创建 Run、不提交或调用 provider、不采集 health、不开启 endpoint、不预热 cache，也不替代 approval、切换或 rollback。
- [x] 已补 DeploymentRevision 的 immutable event timeline 查询入口：
  `GET /api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/events` 先复核 tenant 与 path service
  对 deployment/definition 的归属，再从既有 PostgreSQL event ledger 按 sequence 返回 initial `planned`、后续 state edge、
  actor、reason、idempotency key、provider observation reference、发生时间和 event SHA-256。该读模型不新增 audit store、
  registry 或 lifecycle authority；数据库继续执行 RLS、state-machine、append-only 与 event digest 约束。22 个路由契约测试
  覆盖 service-bound timeline、跨 service 拒绝与 OpenAPI；详见
  [ADR-211](architecture-decisions/adr-211-gis-service-deployment-event-timeline.md)。它只解释已记录的生命周期，不代表 provider
  health/reconcile、deploy command、approval、cache operation、ServiceSLO 或 incident 已完成。
- [x] 已将 GIS deployment terminal provider evidence 从通用 observation 写入收紧为 release-bound v2 合同：
  `POST /api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/observations` 仅接受 workload 的
  terminal state、provider version、credential-free HTTPS endpoint、health evidence hash、provider receipt 与发生时间；
  Gateway 从 path deployment 固定 tenant、Run、definition/release、provider placement、revision 与 config hash。migration 207
  不新增 health/deployment 表，而是在既有 `FrameworkAttemptObservation` 上拒绝绕过专用 recorder 的 v2 evidence，并在
  `ready|failed` transition 时重新校验 Run、release、provider system/namespace/deployment/revision、config 与外部引用，旧 v1
  observation 不能作为终态依据。Martin adapter 已生成相同 v2 ready/failed evidence，并仅将实际非 200 health
  response 作为 failed 证据；详情见
  [ADR-212](architecture-decisions/adr-212-gis-service-deployment-readiness-evidence.md)。PostgreSQL 16 disposable certification
  已验证 generic v2 recorder 拒绝、legacy v1 transition 拒绝、专用 recorder 创建/幂等重放、ready state 与 RLS，报告为
  `/private/tmp/gis-service-control-plane-208-report.json`，SHA-256 为
  `29d18888af833fb065d3d475b097b71710276bd41cd81abf2702465c70457c58`；migration catalog 为 208 条，latest 为
  `208_gis_service_endpoint_readiness_binding`。该报告仅是本机 disposable 证据，不代表真实 provider deploy/reconcile、
  生产网络健康、approval、endpoint build、warmup、switch/rollback、ServiceSLO 或 incident 已完成。
- [x] 已将 deployment terminal evidence 与状态转换收束为同一数据库事务：
  `POST /api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/terminal-settlements` 仅接受 workload
  的 terminal observation、CAS、原因、幂等键和发生时间；Gateway 从已登记 deployment 固定 tenant、Run、definition/release、
  placement、revision 和 config，并由 observation state 确定 `ready` 或 `failed`。v2 evidence 写入或幂等重放后立即调用既有
  PostgreSQL transition authority；Run 终态、RLS、release/config 复核或 CAS 任一失败都会回滚 observation，避免留下无法推进
  lifecycle 的孤立终态证据。旧 observation/transition 入口继续保留给需要分阶段入账的有界 controller。详情见
  [ADR-213](architecture-decisions/adr-213-gis-service-deployment-terminal-settlement.md)。该操作不创建 deploy/reconcile worker，
  不提交或轮询 provider，也不改变 endpoint、cache、traffic、rollback、ServiceSLO 或 incident 的完成边界。
- [x] 已将 EndpointRevision 绑定到 ready deployment 的已验证地址：migration 208 复用既有
  `record_endpoint_revision`，在登记新 endpoint 时从 deployment 的 terminal `FrameworkAttemptObservation` 读取 v2
  `endpoint_uri`，并要求与 endpoint URI 精确一致；不同 URI 即使同属 ready deployment 也会被数据库拒绝。RLS、ready gate、
  MVT serving-projection、immutable replay 和 active pointer CAS 不变，因此每个可激活地址都能沿着 release/deployment/readiness
  evidence 回溯。详情见 [ADR-214](architecture-decisions/adr-214-gis-service-endpoint-readiness-binding.md)。这不代表 provider
  deploy、跨网络区 health、cache warmup、canary traffic、rollback orchestration、ServiceSLO 或 incident 已完成。
- [x] 已补 GIS ServiceSLO 精确绑定切片：migration 223 新增 tenant-scoped、append-only
  `gis_service_slo_binding` projection；`SECURITY DEFINER bind_gis_service_slo(...)` 只接受真实
  `gda_control.gis_service`、当前 generic SLO activation 的 exact version/fingerprint/ApprovalCase/CAS
  版本，并复核 SLO 的 `service_resource_urn` 与 GIS service URN 相等。Gateway 新增
  `GET /api/platform/v1/gis/services/{service_id}/slo` 与 admin-only
  `POST .../slo-binding`，路由从认证 tenant、当前 activation 和 actor/time 推导绑定身份；表启用
  `FORCE RLS`、直接写入/修改/删除拒绝，历史 activation binding 保留，当前查询与 active pointer 精确联结。
  `gis_service` 的 firing/resolved SLO Alertmanager reconciliation 现在必须找到对应 immutable binding，
  缺失、服务错配或 activation 漂移均 fail closed。详见 [ADR-233](architecture-decisions/adr-233-gis-service-slo-binding.md)。
  该切片已通过真实 PostgreSQL 16 行为认证：`scripts/certify_gis_service_slo_binding.py` 在 `gda_223_cert` 验证真实
  service/SLO/ApprovalCase/activation 建立、相同 binding replay 幂等、service/SLO 不匹配拒绝、fingerprint/ApprovalCase/CAS
  漂移拒绝、直接 INSERT/UPDATE/DELETE 拒绝、FORCE RLS 跨租户零行，以及 activation 变更后旧 binding 不再被 active 查询接受。
  认证结果为：v1 activation `1`、v2 activation `2`、重放返回同一 binding、active 行数在切换时 `1 -> 0` 并在 v2 明确重绑后
  恢复为 `1`、跨租户可见行 `0`；数据库拒绝 SQLSTATE 覆盖合同校验 `23514`、最小权限 `42501` 与 append-only trigger
  `55000`，catalog 同时确认 RLS enabled/forced。该切片尚未完成 ServiceSLO 自动随 activation 编排、完整 Incident automation、多
  provider conformance、HA/RPO/RTO，AR-4 仍保持 `in_progress`。
- [x] 已补 ServiceSLO activation 自动编排切片：migration 224 新增
  `gis_service_slo_reconciliation_outbox`，generic SLO activation 只产生 tenant-scoped、幂等的 reconciliation task，独立
  `gis-service-slo-reconciliation-worker` 以 lease/attempt bounded delivery 再次核对 exact version/fingerprint/ApprovalCase/CAS
  后调用 migration 223 的 binding authority。旧 activation 在处理前被替代时进入 `superseded`，已有 exact manual binding 被复用，
  claim 阶段对 migration 224 上线前或 trigger 短暂缺失期间的 active GIS SLO 做补偿扫描，expired lease 支持 redelivery 并在
  max attempts 后 terminal `failed`。worker 已接入 main/gemma4 Compose 的 `gis-slo` profile；Pydantic/Gateway/worker 测试和
  PostgreSQL 16 全链路认证已通过（224 migrations、幂等 replay、manual reuse、superseded、backfill、lease/max-attempt、RLS、
  权限、跨租户均有证据），详见 [ADR-234](architecture-decisions/adr-234-gis-service-slo-activation-reconciliation.md) 与
  `scripts/certify_gis_service_slo_reconciliation.py`。该切片仍不宣称 worker HA/RTO、完整 Incident automation 或 multi-provider
  conformance，AR-4 保持 `in_progress`。
- [x] 已补 GIS ServiceSLO 告警到统一 DataIncident 的原子 authority：migration 225 的
  `assert_gis_service_slo_incident_authority(...)` 在一个事务内锁定 exact generic SLO activation、ApprovalCase、SLO version
  fingerprint 和 223 ServiceSLO binding；`PlatformGateway.open_gis_service_slo_incident` 随后复用既有
  resource-bound `data_incident`、`data_incident_event` 与 notification outbox。GIS firing/resolved reconciliation 对 GIS service
  使用该 atomic gateway path，普通 resource SLO 继续使用原有 resource incident path；stale activation、fingerprint、ApprovalCase
  或缺失 binding 在 incident 提交前拒绝。PostgreSQL 16.14 disposable certification 已验证 incident 创建、replay 幂等、事件和
  通知 outbox、跨租户拒绝、激活更新锁竞争和 gateway 无 binding 表写权限，脚本为
  `scripts/certify_gis_service_slo_incident_authority.py`；migration catalog 已更新为 225 条，详见
  [ADR-235](architecture-decisions/adr-235-gis-service-slo-incident-atomic-authority.md)。该切片仍不宣称完整 Incident automation、
  自动 remediation、worker HA/RTO、multi-provider conformance 或 production DR，AR-4 保持 `in_progress`。
- [x] 已将 DataIncident 通知从“worker 完成”推进到“provider receipt 可审计”：migration 226 在既有
  `data_incident_notification_outbox` 上增加 `provider_receipt`、`receipt_sha256` 与
  `terminal_worker_id`，Alertmanager 只有 2xx、destination 和 `accepted_at` 均有效时才能由 Gateway
  原子结算为 `done`；失败重试保持无 receipt，max-attempts 后的 failed 记录 failure hash。226 上线前
  的历史 done 行显式回填 `accepted=false` 的 legacy unknown receipt，不追认外部已接收。开发库已由
  `221/225` 前向同步至 `226/226 in_sync`，catalog/database fingerprint 均为
  `dfe4b17c4dadd8327b0cc4b6cf794dbd679c3d6a1b95bda60887aad54cd33bbc`；8 条历史 done 均有 receipt/hash、
  9 条 pending 保持空 receipt/hash，定向测试 34 项和 Gateway static conformance 通过，详见
  [ADR-236](architecture-decisions/adr-236-incident-notification-provider-receipt.md)。该切片仍不宣称
  production Alertmanager HA、receiver/on-call、metrics/dead-letter 运维、多 provider routing、自动
  remediation、worker HA/RTO 或 production DR，AR-4 保持 `in_progress`。
- [x] 已收紧 provider receipt 的 completion authority：migration 227 只接受真实
  `gda.alertmanager_provider_receipt.v1`、2xx、精确 destination 和 `accepted_at`，226 的 legacy
  unknown receipt 不能作为新的 done 输入；缺失或伪造 receipt 在数据库事务内 fail closed。开发库已
  通过 migration authority 达到 `227/227 in_sync`，catalog/database fingerprint 为
  `e8358ecefeb4efa5adcfbff767209eab6ea957740cc91cf4c86d396fea5a26a9`；fresh PostgreSQL 16.14
  certification 已验证 receipt/hash 持久化和既有 GIS ServiceSLO incident authority，详见
  [ADR-237](architecture-decisions/adr-237-strict-incident-notification-receipt-authority.md)。该切片仍不宣称
  production Alertmanager HA、receiver/on-call、metrics/dead-letter 运维、多 provider routing、自动
  remediation、worker HA/RTO 或 production DR，AR-4 保持 `in_progress`。
- [x] 已补齐 Incident Notification Worker 的生产形态 observability 与 HA deployment contract：worker
  记录 claimed/delivered/retrying/dead-letter/cycle-error、cycle duration 和成功心跳，支持受校验的
  Kubernetes namespace route label；`k8s/observability/incident-notifications/` 提供双副本、zero-unavailable
  rolling update、PDB、metrics Service/ServiceMonitor、PrometheusRule、AlertmanagerConfig、专用 runtime
  Secret 和只允许 PostgreSQL/Alertmanager/DNS/metrics 的 NetworkPolicy。canonical Prometheus 规则与 CRD
  通过一致性测试，`kubectl kustomize` 渲染 8 个对象。定向测试 `52 passed`；真实 Alertmanager `v0.28.1` +
  Prometheus `v3.5.0` rehearsal 验证 `GDADataIncident` 只进入 `incident-oncall`、无关告警隔离、receiver URL
  从 secret file 加载及临时资源清理，报告 schema 为 `gda.incident_observability_routing_rehearsal.v1`，SHA-256
  `3ae162260ed1ec9c99fb232acb05508a019a326c92c03e01b7865f4018fb814b`，详见
  [ADR-238](architecture-decisions/adr-238-incident-notification-observability-ha-contract.md)。该切片是
  可执行的部署/观测合同和 disposable routing 证据，不宣称已完成生产集群 rollout、Alertmanager HA、企业
  on-call、容量 SLO、RPO/RTO、自动 remediation 或 exactly-once；AR-4 保持 `in_progress`。
- [x] 已补 DataIncident 通知 dead-letter 的受控恢复 authority：migration 228 在既有 notification
  outbox 上增加最多 10 次的恢复投影和 append-only recovery event；只有 human admin 可携带 expected
  attempt count、failed receipt SHA-256 和原因将 `failed` 原子恢复为 `pending`，事务同时保留恢复前错误、
  尝试上限、terminal worker、completed time 与 receipt hash。Gateway 新增通知列表、恢复历史与恢复提交
  3 个 REST endpoint；恢复事件启用 tenant RLS/FORCE RLS、owner INSERT guard 和 UPDATE/DELETE immutable
  trigger，Gateway 只有 event SELECT 与 function EXECUTE。定向 contract/Gateway/REST/static 测试为
  `99 passed`；`scripts/certify_incident_notification_recovery.py` 在真实 PostgreSQL 16.15 上以 17 项检查
  验证 10 次恢复、pending/done 拒绝、attempt/hash CAS、非 human 拒绝、跨租户隔离、直接写保护和最小权限。
  开发库已达到 `228/228 in_sync`，catalog/database fingerprint 均为
  `4864556af67959c2a1d32b9c1541dc55ce77cc898f64d43a587f18e932e1fb1c`，详见
  [ADR-239](architecture-decisions/adr-239-incident-notification-governed-recovery.md)。该切片不是自动 remediation、
  exactly-once 或生产 DR/RPO/RTO 证据，AR-4 保持 `in_progress`。
- 实现 `GISServiceDefinitionVersion`、`LayerDefinitionVersion`、`StyleDefinitionVersion`、`TileMatrixSetDefinitionVersion`、`CachePolicyVersion`、`ServicePolicyBinding`、`MVTServingProjectionVersion`、`ServiceDeploymentRevision`、`EndpointRevision`、`ConsumerBinding`、`ServiceSLO`、`RollbackPointer` 及状态机 `draft -> validating -> approved -> deploying -> active -> deprecated -> retired`，事故可进入 `suspended -> rollback`。
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
- [x] 已补齐首个 OGC API Features provider-conformance slice：`OGCAPIFeaturesProvider`/`pygeoapi_provider_manifest`
  复用现有 release-bound deployment observation 和 Gateway settlement，不维护 provider registry、Run 或 active pointer。
  `OGCAPIFeaturesReleaseContext` 固化 DataProduct、service definition、layer、release binding 与 `collection_id`；
  provider runtime 依次读取根路径、`/conformance`、`/collections` 和精确 `items`，校验 OGC Features conformance、
  collection 广告、GeoJSON FeatureCollection、非空响应、media type、bbox/limit、4xx/5xx 和 credential-free
  origin，并生成 `gda.gis_ogc_api_features_conformance.v1` receipt，嵌入现有
  `gda.gis_service_deployment_observation.v2` 终态证据。migration 238 将
  `gda.ogc_api_features_endpoint.v1 + collection_id` 绑定到 release layer key，防止 endpoint 激活到错误图层。
  认证入口为 `scripts/certify_ogc_api_features_provider.py`；聚焦 contract/identity tests 共 11 项通过，
  `scripts/certify_ogc_api_features_provider_disposable.py` 通过 health/conformance/catalog/items/product-layer
  identity 5 项检查，报告明确标记 `synthetic_disposable`。随后使用真实 `geopython/pygeoapi:latest`
  （容器内 `0.25.dev0`）和 disposable GeoJSON collection 完成 5 项真实 provider 检查，报告为
  `.tmp/ogc-api-features-pygeoapi-certification/report.json`，文件 SHA-256 为
  `b75c801b8af50fcb839331274df03c82185a17652f3b996850bd53f23d739f08`；其
  `evidence_class=real_provider_disposable_control_fixture`，明确只证明真实 pygeoapi 数据面和 receipt
  绑定，不代表 active Gateway、生产 provider、OGC CITE、权限下推、性能、缓存或 HA 完成。随后新增一次性
  PostgreSQL control-plane fixture，应用 migration 238，经 `PlatformGateway` 注册并激活 feature
  service/release/deployment/endpoint，再由真实 pygeoapi 完成 `active_release_read_certified`；报告为
  `.tmp/ogc-api-features-active-release-certification/report.json`，文件 SHA-256 为
  `f605332fd034766cd56c7a5d2f9b01a73843690568c8b16305dd9d75412a243e`，并记录 migration 238
  对错误 `collection_id` 的运行时拒绝；其 `evidence_class=real_provider_disposable_postgresql_control_fixture`，证明 active-release 集成路径，
  仍不代表生产数据库、生产 endpoint、OGC CITE、权限下推、性能、缓存或 HA 完成。详见
  [ADR-322](architecture-decisions/adr-322-ogc-api-features-provider-conformance.md)。

#### AR-4.4 Gateway、安全与缓存一致性

- 所有公开 endpoint 统一经过 Gateway；私有化候选基线为 Apache APISIX，云 profile 可替换为 Azure API Management 等认证 adapter。provider 使用 workload identity 和内网策略，不直接暴露公网。
- SubjectContext/PolicyDecision 向 provider 下推 resource、column、row、spatial、temporal、action 和 purpose obligation；无法安全下推时由受控 projection 隔离，不能降级为仅隐藏 UI。
- 版本进入 route、URL/TileJSON/STAC link、ETag 和 cache key；active pointer 切换触发精确 purge 或 namespace rollover。Redis/CDN/GeoWebCache/对象缓存均可丢且可重建，不保存权限或发布真值。
- 统一 auth、WAF、quota/rate limit、signed URL、request/response schema、usage/cost、log/metric/trace、correlation id、审计和 abuse protection；错误、capabilities、tile metadata 和 preview 也必须通过权限检查。
- [x] 已接入首个 governed OGC API Features route：`GET /api/platform/v1/gis/features/{release_key}/collections/{collection_id}/items`。
  路由复用 `PlatformGateway` active projection，校验 tenant-scoped `service_urn`、active release/layer collection、
  `gda.ogc_api_features_endpoint.v1`、ready 的 pygeoapi deployment，以及 `limit`/`bbox`；provider origin 只从
  内部 `PYGEOAPI_URL` 注入，4xx/5xx、错误 GeoJSON 和错误媒体类型 fail closed，响应固定 `private, no-store`。
  `data_agent/test_platform_gis_ogc_api_features_route.py` 7 项通过；真实 `geopython/pygeoapi:latest` + 临时
  PostgreSQL active-release fixture 已经 FastAPI route 返回 2 个 Feature，collection mismatch `409`、非法 limit `400`。
  报告 `.tmp/ogc-api-features-consumer-auth-certification/report.json`，SHA-256 为
  `592e1ec7db67c9559dcec54044bb70cbfd316235452932c3307b2171a4a2bcdd`；证据仍是 disposable，证明
  migration 239、Features policy、exact-release admission、provider 读取和 route fail-closed 参数校验，
  不代表生产身份、真实消费者审批发行、ABAC/policy pushdown、分页/过滤扩展、缓存、quota、HA 或性能 SLO。
  详见 [ADR-323](architecture-decisions/adr-323-governed-ogc-api-features-gateway-route.md) 和
  [ADR-324](architecture-decisions/adr-324-ogc-api-features-consumer-authorization.md)。
- [x] 已接入首个 governed MVT operator route：`GET /api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf`
  必须携带 tenant-scoped `service_urn`，只读取 active `GISServiceControlProjection`，并校验 release key、MVT
  endpoint contract、Martin provider、ready deployment 和 TMS zoom/坐标；响应带 release/state-version headers，
  在 policy/cache authority 完成前固定为 `private, no-store`。5 个 route contract tests 通过，连同 provider/
  control-plane 聚焦回归为 23 passed。该 route 初始明确限于 `platform_operator/admin`，不代表 ConsumerBinding、
  SubjectContext policy pushdown、缓存 namespace 或生产消费者数据面已完成，详见
  [ADR-184](architecture-decisions/adr-184-governed-mvt-operator-route.md)。
- [x] MVT route 曾以 DataProduct `ConsumerBinding` 建立消费者授权切片：operator/admin 保留运维路径，
  `viewer`、`analyst`、`standard_editor` 和 `standard_reviewer` 需通过 active GIS service projection 解析的
  `source_product_urn` 与 `source_data_product_version_id`，由 PlatformGateway 在 tenant-scoped PostgreSQL 事务内
  精确匹配 `consumer_ref`，并由数据库过滤 binding expiry 与 ProductVersion min/max bounds；route 再强制
  `scope.operations` 包含 `read`，否则在 provider 调用前返回结构化 403。合法消费者继续复用 Martin provider，
  响应保持 `private, no-store`，不引入新的 registry、cache 或 policy authority。10 个 MVT route contract tests、
  platform gateway/control-plane/ConsumerBinding 聚焦回归 102 个通过。该证据仍是开发/测试环境切片，尚未证明
  service-scoped ConsumerBinding、SubjectContext policy pushdown、cache namespace、provider/Gateway conformance、
  production identity/HA/SLO 或完整真实服务数据面；但 disposable PostgreSQL 16 certification 已由
  `scripts/certify_gis_mvt_consumer_authorization.py` 覆盖 active exact-version、missing consumer、expired binding、
  version bounds 和 successor-version 五项检查全部通过，报告为
  `.tmp/gis-mvt-consumer-authorization-certification/report.json`，SHA-256 为
  `4830ef6a39a19f615420c716e6309a825feebba2f78e074c313ea3779a5eacea`。该授权事实现仅用于数据产品
  promotion、兼容性与消费者影响工作流；MVT 数据面已由下方 exact-release `ServiceConsumerBinding` 取代。AR-4.4 与
  AR-4 总体状态保持未完成。
- [x] 已完成 MVT release-bound private cache authority：migration 203 新增不可变
  `CachePolicyVersion`，以 tenant RLS、insert/update/delete guard 和 `SECURITY DEFINER` recorder 固化 service
  definition、policy key/version、namespace、1-300 秒 TTL 及 tenant/release/principal/tile 四个缓存隔离维度。
  新 vector-tile `ServiceReleaseBinding` 必须同时引用 TMS 和 CachePolicy；历史 release 仍按原指纹可读，但不能经过
  governed MVT route 出图。route 在 ConsumerBinding 检查和 access admission 之后，只为 `200` MVT 设置
  `private, max-age=N, must-revalidate`，并依据 policy/release/endpoint/principal/binding/tile/content 构造 opaque
  namespace 和确定性 ETag；非 200 仍 `private, no-store`。此项 authority 本身不包含
  ServicePolicy/row-column-spatial-temporal pushdown、CDN/GeoWebCache、purge/warmup、Redis HA 或跨区 DR。详见
  [ADR-202](architecture-decisions/adr-202-release-bound-mvt-private-cache-policy.md)。
- [x] 已完成首个可执行的 release-bound `ServicePolicyBinding`：migration 204 将 `mvt.read`、
  Gateway 执行点、允许角色、必须持有 exact-version `ConsumerBinding` 的角色及 `read` operation 固化并精确绑定
  到一个 MVT release。新 endpoint 与 active pointer 同时要求 cache policy 和 service policy；Gateway 在调用
  Martin 前执行角色与 ConsumerBinding 决策，并将策略 ID/fingerprint 加入私有 tile cache identity。该实现不是
  通用 ABAC，也不包含 `PolicyDecision` 审计、row/column/spatial/temporal/purpose obligation、受控投影或
  provider-side pushdown；详见
  [ADR-204](architecture-decisions/adr-204-release-bound-mvt-service-policy.md)。
- [x] 已将 MVT 从 Gateway 角色准入推进到 release-bound Martin/PostGIS serving projection：migrations
  205/206 新增不可变 `MVTServingProjectionVersion`，每个 vector-tile release 精确绑定 source
  `ResourceVersion`、内容 hash、源表/geometry/feature ID、属性白名单、空间范围和单瓦片要素上限；缺投影的
  release 与源 hash 不匹配的投影均由数据库拒绝。Gateway 仅接受指向该 projection UUID 的固定 Martin endpoint
  contract，并在调用前与 active release 比对；Martin 通过 `gda_mvt_serving_projection` 函数层执行字段白名单和
  空间裁剪，projection ID/hash 同时进入 ETag 和私有缓存 namespace。disposable PostgreSQL certification 覆盖 RLS、
  Gateway 无直写权限、幂等投影写入、源 hash 漂移、缺投影 release 与 active pointer，详见
  [ADR-205](architecture-decisions/adr-205-release-bound-mvt-serving-projection.md)。当前数据面保障为固定的
  release projection；Martin 必须继续仅内网可达，按主体动态行级空间策略和 provider-direct 隔离尚待单独实现与验收。
- [x] 已将 Martin readiness 的实现边界从单次 health 提升为 release-bound MVT conformance：adapter 会对
  `gda_mvt_serving_projection` 执行 health、catalog 和固定 `serving_projection_version_id` 的已知数据瓦片读取，
  将响应媒体类型、ETag、字节数、内容 hash、release 和 serving projection ID 写入自校验 receipt；receipt 可直接
  作为既有 terminal settlement 的 provider receipt。Gateway 读取 provider 时改用受信任的内部 `MARTIN_URL`，
  对外 HTTPS `EndpointRevision` 仍只代表消费者地址，避免 Gateway 回调公开地址或绕过私网边界。认证脚本现只从
  active `GISServiceControlProjection` 读取实际 release，拒绝再以 legacy `map_publication` fixture 代替当前发布。
  聚焦 contract tests 通过；Compose Martin `v0.18.0` 已验证 health 与 governed function catalog。新增
  `scripts/certify_martin_active_release.py` 后，系统可在自动清理的临时 PostGIS 库中通过既有
  `PlatformGateway` 注册并激活一条 Martin release，以无源表/控制平面读取权限的 Martin login 实际返回 MVT，随后由
  `certify_martin_provider.py` 从 active projection 回读并签发 `active_release_read_certified`。该认证暴露了受限
  `SECURITY DEFINER` search path 下 PostGIS `ST_*` 函数及 `&&` 运算符无法解析的真实数据面缺陷，已由 migrations
  210/211 通过显式 `public.ST_*`、`OPERATOR(public.&&)` 修复，未将 `public` 加入函数 search path。fixture report SHA-256
  为 `e4bb5ebe8dcf8552fb5ffe4435c134c93a18fcd86a77608bc77bb41c75951262`，当前 Compose migration catalog/database
  fingerprint 均为 `792d267eac939a2874954bde6e10b4ff8a36a801252039facb71ddb8aff8d1a0`。开发库仍没有业务 active GIS
  service；这份 fixture 只证明可重放的运行时闭环，不替代生产 provider、真实 SubjectContext policy pushdown、cache
  namespace 和消费者数据面的独立验收。详见
  [ADR-215](architecture-decisions/adr-215-martin-release-bound-conformance.md)。
- [x] 已将上述 active Martin fixture 接到真实 Gateway HTTP 消费边界：路由先从签名 Cookie 构造
  `SubjectContext`，再由专用 `MVTAccessService` 对 tenant、source `DataProductVersion`、active release、
  `ServicePolicyBinding`、`MVTServingProjectionVersion`、exact-version `ConsumerBinding` 与 `z/x/y` 生成
  单次访问 decision SHA-256，随后才允许 Martin 读取。允许请求的不可变 security ledger 顺序固定为
  `admitted (0 provider calls) -> outcome (1 provider call)`，两条记录共享同一 decision SHA-256；未绑定
  消费者在 provider 调用前留下 `denied`。成功 tile 只有在 outcome 审计落账后才返回，私有 ETag/namespace 同时
  绑定 decision、主体、binding、release、policy、projection、endpoint state 与 tile，避免不同授权上下文复用
  同一缓存身份。`scripts/certify_gis_mvt_gateway_http.py` 在自动清理的 PostGIS/Martin fixture 上以 FastAPI HTTP
  contract 验证无 Cookie `401`、签名 Cookie 但无 binding `403 consumer_binding_required`、精确 binding 下
  122-byte MVT `200`、private cache header、三段审计顺序及 ledger chain；报告为
  `.tmp/gis-mvt-gateway-http-certification/report.json`，SHA-256 为
  `44fe8b6fd77f6998362d5b93913d35a762e6e92c26e61d6af80eefe034d47875`。这证明的是 Gateway 对
  release-bound static projection 的受控读取，不表示通用 ABAC、动态 row/column/spatial/temporal/purpose
  pushdown、生产 OIDC/API Gateway、Redis/CDN/purge、quota/rate、HA/SLO 或非 Martin provider 已完成；详见
  [ADR-216](architecture-decisions/adr-216-authenticated-gateway-mvt-access-evidence.md)。
- [x] 已完成 Gateway 首个真实共享消费者缓存切片：新增二进制安全 Redis MVT response cache，授权与 admission
  audit 始终先于缓存查询；稳定 key 绑定 tenant、service URN、release/cache policy/service policy、serving
  projection、endpoint revision/state、主体、exact ServiceConsumerBinding 和 tile，移除每次请求都会变化的
  decision hash。只缓存非空 HTTP 200 MVT，TTL 不超过 `CachePolicyVersion`，损坏 entry 自动丢弃；Redis get/set/
  decode/连接故障回源私网 Martin，access audit 故障仍 fail-closed。outcome audit 显式记录 `delivery_source` 与
  `provider_invocations`，缓存命中为 `redis_cache/0`。真实 disposable PostgreSQL/PostGIS + Martin `v0.18.0` +
  Redis `7-alpine` + FastAPI signed-cookie certification 已验证首请求 Martin miss、同 binding 重放 Redis hit、停止
  Redis 后回源，以及缓存存在时撤销 binding 仍为 `403`；报告 `.tmp/gis-mvt-redis-gateway-certification/report.json`，
  SHA-256 为 `6d26f8e343bc3a1cd6c233fece668ff2d999a1c2681d0de6b7611267129c7293`。详见
  [ADR-228](architecture-decisions/adr-228-gateway-redis-mvt-response-cache.md)。该切片不外推到自动 cutover-triggered purge/warmup
  dispatch、CDN/GeoWebCache、Redis HA/跨区 DR、非 Martin provider、ServiceSLO/Incident automation；AR-4 继续
  `in_progress`。
- [x] 已把 active release 切换的缓存代际语义收束为可执行的 namespace rollover：新增
  `mvt_response_cache_namespace()`，将 tenant/service、release、cache/service policy、serving projection、endpoint
  revision/state version 固化为 generation token，再将主体、exact ConsumerBinding 和 tile 作为 generation 内的对象键维度。
  因此 218 cutover 或 219 rollback 每次推进 active pointer 都会得到新的 `X-GDA-Cache-Namespace` 与 ETag；即使回滚到旧的
  human release key，也不会复用切换前对象。旧 Redis generation 只按现有有界 TTL 自然过期，不执行 `FLUSHDB`、跨租户扫描或
  伪造 purge receipt。新增 namespace/key contract 与 Gateway rollover tests，聚焦缓存/Gateway 回归 `41 passed`，Ruff、
  compileall、diff check 通过。详见 [ADR-229](architecture-decisions/adr-229-mvt-cache-namespace-rollover.md)。该切片已关闭
  “切换后缓存身份依赖隐含实现”的工程缺口，但仍不代表精确 Redis prefix purge、CDN/GeoWebCache adapter、显式 cache
  warmup command、Redis HA/跨区 DR 或 provider-neutral cache conformance 已完成。真实 disposable PostgreSQL/PostGIS +
  Martin + Redis HTTP certification 已在该改动后复跑，继续通过 miss、hit、Redis 故障回源、撤销后 403 与 ledger chain；
  报告 SHA-256 为 `6d26f8e343bc3a1cd6c233fece668ff2d999a1c2681d0de6b7611267129c7293`。
- [x] 已补齐 Redis generation 的精确运维回收适配器：`RedisMVTResponseCache.purge_namespace()` 只匹配
  `key_prefix:<generation>:`，使用增量 `SCAN` 收集后再 `UNLINK`，并用第二次精确扫描确认残留为零；`max_keys` 和
  `scan_count` 都有上限，超过上限或 Redis/残留校验失败均返回失败，不产生伪成功。新增
  `scripts/purge_gis_mvt_cache_namespace.py`，完整 generation token 由 `X-GDA-Cache-Generation` 响应头提供，Redis URL
  只从环境变量读取；新增真实 `redis:7-alpine` certification，证明
  目标 generation `2/2` 删除、相邻 generation 保留、无关 key 保留，以及超限时原 key 全部保留。报告为
  `.tmp/gis-mvt-cache-namespace-purge-certification/report.json`，SHA-256 为
  `d83540959783b6e3dc67ad7b67d4ef722de328594b6573fab3e20bf3905c89db`；单元测试 `9 passed`，Ruff、compileall、diff check
  通过。详见 [ADR-230](architecture-decisions/adr-230-exact-mvt-cache-generation-purge.md)。该切片只提供显式 Redis
  运维回收，不把 purge 伪装成 cutover/rollback 的 PostgreSQL 原子步骤；自动 dispatch、CDN/GeoWebCache adapter、Redis
  HA/跨区 DR 和 provider-neutral purge conformance 仍未完成。
- [x] 已把 cutover/rollback 后的旧 MVT generation 回收接成独立的异步闭环：migration 222 新增 tenant-scoped
  `gis_mvt_cache_purge_outbox`，218 cutover 与 219 rollback 的 immutable receipt 在同一 PostgreSQL 事务内通过
  `AFTER INSERT` trigger 幂等入队；active pointer 不等待 Redis。任务保存 release/policy/projection/endpoint 的完整
  cache context 与 generation token，legacy/non-vector context 明确记录 `bypassed`，不能伪造成功。新增
  `GISMVTCachePurgeWorker`，只以 `workload:gis-mvt-cache-purge-controller` claim，Redis 故障回到 pending、超过
  attempt limit 才 failed，成功必须上报 matched/deleted/remaining 且 remaining 为 0；K8s 已加入独立 Deployment 和
  最小 Postgres/Redis NetworkPolicy，配置见 `.env.example`。真实 disposable PostgreSQL 222-chain certification 已验证
  cutover/rollback 各一条任务、replay 不重复、SQL/Python generation parity、错误 workload 拒绝、retry/lease/complete、
  RLS 和 direct-write denial；报告 `.tmp/gis-mvt-cache-purge-certification/migration-impact-report.json`，SHA-256 为
  `c7398639623de0f9d7d1bfcba491567794b4acb068b9b6ef3e3dae78339ce3d7`。真实 `redis:7-alpine` worker certification 已验证
  `1` task claim、目标 generation `2/2` 删除、相邻 generation 保留、zero residual 和 async client close；报告
  `.tmp/gis-mvt-cache-purge-certification/report.json`，SHA-256 为
  `4c67f0e8b632c4c9722fd6bcc9814505f508a542e0f6bda3b61598d74cc6b81a`。详见
  [ADR-231](architecture-decisions/adr-231-gis-mvt-cache-purge-outbox.md)。这关闭了“切换后旧 generation 没有可审计异步
  回收闭环”的一个工程卡点，但 AR-4 仍不宣称完成；CDN/GeoWebCache、Redis HA/跨区 DR、provider-neutral purge
  conformance、ServiceSLO/Incident automation 仍在后续切片。
- [x] 已将 MVT purge worker 的执行边界从 Redis 实现抽象为 provider-neutral `GISMVTCachePurgeProvider`：worker
  继续只消费 immutable generation token 和有界 `max_keys/scan_count`，Redis response cache 由显式 adapter 接入，
  替代 provider 可在不改变 PostgreSQL outbox、lease、retry、zero-residue 和 completion authority 的前提下替换。
  focused purge/response-cache 回归为 `15 passed`；真实 `redis:7-alpine` worker certification 复跑通过，报告 SHA-256
  为 `d553e3b732954f3898b4a9ed4bd00e53180397e08b42e87c2a0b48b20946561d`。该切片只关闭 worker 与 Redis 实现的
  工程耦合，不计入 CDN/GeoWebCache 行为、Redis HA、跨区 DR、provider-neutral 协议 conformance 或生产 rollout；详见
  [ADR-289](architecture-decisions/adr-289-provider-neutral-gis-mvt-cache-purge-execution.md)。
- [x] 已补齐首个外部 HTTP purge provider 实现：`HTTPGISMVTCachePurgeProvider` 固化
  `gda.gis_mvt_cache_purge.v1` 请求/receipt schema，只接受无凭据 HTTP(S) endpoint，Bearer 只从绝对路径 token file
  读取；5xx/transport failure、schema 漂移、generation 回显不一致和非零残留均回到既有 outbox retry/failure，adapter
  不在控制面外隐藏重试。HTTP provider contract 与缓存回归共 `26 passed`；loopback 真实 HTTP certification 通过 9
  项检查，报告 SHA-256 为 `69f858ceb93dad18ba56771fb0d2aee8f2a10bcd918bac6619719ddc8901a43d`。该证据只证明版本化
  HTTP transport/receipt 合同，不计入真实 CDN/GeoWebCache、purge latency SLO、HA/DR 或生产 rollout；详见
  [ADR-290](architecture-decisions/adr-290-http-gis-mvt-cache-purge-provider.md)。
- [x] 已把 provider 选择接入 managed purge worker 的部署合同：`GDA_GIS_MVT_CACHE_PURGE_PROVIDER=redis|http`；HTTP
  模式要求 endpoint，支持 mounted bearer token file 和 bounded timeout，Redis 仍是 Compose/Kubernetes 默认值。未知
  provider、HTTP 缺 endpoint 或 Redis 模式混入 HTTP 参数会在 claim task 前 fail closed；worker selection/purge 回归为
  `21 passed`，Ruff、compileall 和 `docker compose config --quiet` 通过。该切片只完成进程配置接线，不计入外部 cache
  service、CDN/GeoWebCache production identity、HA/DR、purge SLO 或 staging/production rollout；详见
  [ADR-291](architecture-decisions/adr-291-gis-mvt-purge-provider-selection.md)。
- [x] MVT 消费授权已收紧为精确 GIS 服务发布级 `ServiceConsumerBinding`：migration 212 固化 tenant、`gis_service` URN、
  `ServiceDefinitionVersion`、`ServiceReleaseBinding`、typed consumer、`mvt.read`、`gis_mvt_read`、唯一允许的
  `{"operations":["read"]}` scope、credential reference、expiry、compatibility evidence 和 SHA-256。表为 append-only，
  release 外键、RLS/FORCE RLS、直写 trigger 与 `SECURITY DEFINER` recorder 共同约束；Gateway 只有读取和 recorder
  执行权限。consumer role 的请求必须按 tenant + service + definition + release + typed principal 命中未过期 binding；
  `MVTAccessDecision` v2、security ledger、ETag 与 private cache namespace 都封存 binding ID/hash，旧 release 的授权不能
  随 active pointer 切换复用。`scripts/certify_gis_mvt_gateway_http.py` 已在自动清理的 PostGIS/Martin fixture 上验证
  无 Cookie `401`、有签名身份但无 binding `403 service_consumer_binding_required`、精确 binding 下 122-byte MVT
  `200`、审计链、ledger chain、RLS/Force RLS、Gateway 无 `INSERT`、recorder 有 `EXECUTE` 与直写 SQLSTATE `42501`；
  报告为 `.tmp/gis-mvt-gateway-http-certification/service-consumer-binding-v2-report.json`，SHA-256 为
  `4d29dea8ce73b1aa560b543b89e3be9d04d7985af797fa1a85643fc193b0395e`。本机 Compose 开发库已通过 fail-closed migration
  runner 应用 212（随后已前向升级到 213），当时 catalog/database fingerprint 均为
  `f8be921931d402e6527513352bfcd257ceaae576f014db2e2830ed9324b1b981`。随后 migration 213 把新 binding issuance
  接入既有 `ApprovalCase`：`ServiceConsumerBindingGrantPlan` 固化完整载荷，独立 eligible human 批准后，数据库
  recorder 再逐字段核对 case 的 target、plan fingerprint 和 request context；旧 212 recorder 已撤销 Gateway
  `EXECUTE`，历史 212 行只读兼容。disposable control-plane certification 验证 unapproved/pending/tampered
  grant 全部拒绝、approved grant 单次创建且 replay 幂等；真实 Martin/PostGIS/FastAPI certificate 继续通过
  `401`、`403 service_consumer_binding_required`、122-byte MVT `200` 和三段审计链。当前本机 Compose 库已同步至
  213/213，catalog/database fingerprint 均为
  `467cf6d22c1b70ec8aacd8c03719dfacac71a2b2e56c897b8da916a2162a173d`；最新 HTTP 报告为
  `.tmp/gis-mvt-gateway-http-certification/service-consumer-binding-approval-v3-report.json`，SHA-256 为
  `75ce7af28f60eaec993563fe6ba9e3f034309ee98e30ee0e44c5e1d25e9205fe`。migration 214 新增
  `ServiceConsumerBindingRevokePlan` 与 append-only `service_consumer_binding_revocation`：撤销请求复用
  `ApprovalCase`，数据库 recorder 核对 binding ID/hash、release、consumer、reason/context、批准人和 case
  fingerprint；Gateway active lookup 用 `NOT EXISTS` 排除撤销事实。disposable control-plane certification 验证
  pending revoke 拒绝、approved revoke 单次写入、replay 幂等、篡改 reason 拒绝、撤销前后 active lookup 变化及
  RLS/recorder 权限；真实 Martin/PostGIS/FastAPI certification 验证撤销后同一 signed subject 返回
  `403 service_consumer_binding_required` 且 provider invocation 不增加；214 revocation certification 当时为
  `214/214 in_sync`，随后已由 215/216 renewal 及 decision guard 前向升级；详见
  [ADR-220](architecture-decisions/adr-220-approval-bound-gis-service-consumer-binding-revocation.md)。consumer migration
  notification、通用 ABAC、动态 row/column/spatial/temporal obligation、实时 quota/rate、跨协议
  binding、生产 OIDC/API Gateway、共享缓存/失效、HA 与 ServiceSLO 仍在 AR-4.4 后续范围；详见
  [ADR-218](architecture-decisions/adr-218-exact-release-gis-service-consumer-binding.md)、
  [ADR-219](architecture-decisions/adr-219-approval-bound-gis-service-consumer-binding-issuance.md)、
  [ADR-220](architecture-decisions/adr-220-approval-bound-gis-service-consumer-binding-revocation.md)。
- [x] 已完成 binding renewal 首个生命周期切片：migration 215 将 renewal 实现为“新 immutable
  `ServiceConsumerBinding` + append-only `service_consumer_binding_renewal` 事实”，不 UPDATE 原 binding；目标绑定
  固化 source binding ID/hash、renewal ApprovalCase 和 plan fingerprint，`ServiceConsumerBindingRenewalPlan` 冻结完整
  target payload。数据库 recorder 校验 live approved case、完整 payload、source checksum、同一 service definition/release/
  consumer、延长后的 expiry、source 未撤销及每个 source 只能续期一次；Gateway active lookup 排除已续期 source，解析
  最新未撤销且未过期 target。disposable PostgreSQL certification 已验证 pending reject、approved create、identical
  replay `created=false`、active source→target 切换、RLS/FORCE RLS、immutable relation 和 Gateway recorder-only；真实
  Martin/PostGIS/FastAPI HTTP certification 继续通过 `401`、未绑定 `403`、approved binding `200`、撤销后 `403`，且
  provider invocation 不增加；renewal actor/timestamp 篡改在 SQL recorder wrapper 处被拒绝。Compose 当前 `216/216 in_sync`，
  catalog/database fingerprint 均为 `7ed130a940debc6577587747461e24fb9694367a3e6c628d4a009c98cbca13c9`；详见
  [ADR-221](architecture-decisions/adr-221-approval-bound-gis-service-consumer-binding-renewal.md)。
- [x] 已完成 GIS service migration impact 首个关联切片：migration 217 新增 append-only
  `gis_service_consumer_binding_migration_impact`，把 exact `ServiceConsumerBinding`、源/目标
  `GISServiceDefinitionVersion` 与 `ServiceReleaseBinding`、产品 migration state 和既有通知 ID 固化在一条
  可重放事实中。recorder 在 SQL 边界校验 service release lineage、同一 source product 与 from/to version、产品/GIS
  consumer 一致性、通知归属和 source binding checksum；表启用 tenant RLS/FORCE RLS、immutable trigger，Gateway
  只有 SELECT 和 recorder EXECUTE。现有 ConsumerBinding notification envelope/Alertmanager worker 复用原 outbox，
  对单一 impact 输出 service URN、source/target release、exact service binding ID/hash 和 impact fingerprint；没有
  新增第二套 provider 队列，也不把 service cutover、自动 renewal、cache purge 或 generic ABAC 计为完成。详见
  [ADR-222](architecture-decisions/adr-222-gis-service-consumer-migration-impact.md)。该切片完成后，AR-4.1/AR-4.4
  仍需真实 service migration orchestration、provider conformance、通用策略、共享缓存/失效、生产身份、HA/SLO
  和跨协议 consumer lifecycle。Python/notification focused regression `14 passed`，Gateway static boundary
  validation 为 `valid`；Compose migration `217/217 in_sync`，catalog/database fingerprint 均为
  `ba8c384156516ecc33b5e55bc2b3e02c4bcbfab2fcbbb2b32286a6b33d713ddd`。fingerprint parity 已在 PostgreSQL
  复核通过。新增 `scripts/certify_gis_service_consumer_migration_impact.py` 在一次性 PostgreSQL 中建立两代
  `DataProductVersion`、两代 GIS definition/release、产品/GIS consumer binding、migration state 和既有通知的
  source→target 完整链；认证通过首次写入、幂等 replay、伪造 target release/identity drift 拒绝、Python/SQL
  fingerprint parity、RLS/FORCE RLS、immutable trigger、跨租户零行以及 Gateway `SELECT=true`、`INSERT=false`、
  recorder `EXECUTE=true`。报告为 `.tmp/gis-service-consumer-migration-impact-certification/report.json`，SHA-256
  为 `5fae0c7ef1aff521599274f48ff8a605d7825ccbfc2bd74d318ae7a3f6a237ec`，一次性数据库和角色已清理；这份证据
  认证的是 migration-impact authority，尚未把关联事实冒充完整 service migration orchestration 的生产认证。
- [x] 已完成 GIS service migration 的全消费者原子 cutover 切片：migration 218 新增 append-only
  `gis_service_migration_cutover` 和单事务 `cutover_gis_service_migration(...)`。数据库在持有 product/service
  advisory lock 与 endpoint row lock 时，核对 active source endpoint、ready target endpoint、source release 的完整
  有效 `ServiceConsumerBinding` 集合、逐 binding migration impact、`done` 通知、最新 `delivered + consumer
  acknowledgement` 状态，以及逐 consumer target exact-release binding；随后复用既有 active pointer CAS，在同一事务
  写 activation event 与包含三组 set fingerprint 的 cutover receipt。原 `activate_gis_service_endpoint(...)` 名称保留
  首次激活和同产品 revision 切换，旧实现已转为 Gateway 无 `EXECUTE` 的 private function；跨 ProductVersion 且 source
  release 仍有有效消费者时，通用激活和 pointer trigger 均拒绝绕过。MVT release 已进入 cache namespace/ETag，因此
  receipt 记录 `release_namespace_rollover`，但没有把 shared cache purge 冒充完成。disposable PostgreSQL 认证真实走通
  notification claim/complete、consumer ack、target grant 与 source→target 切换，并验证 pending ack、缺 target binding、
  generic bypass、stale CAS 全部失败且 source pointer 不变，成功切换只推进一个 state version；replay、identity drift、
  Python/SQL fingerprint、RLS/FORCE RLS、immutable ledger 和 Gateway 最小权限均通过。报告为
  `.tmp/gis-service-migration-cutover-certification/report.json`，SHA-256 为
  `f309dac26cf6764b2e9338e6ea5e3a60003c1cb298b996d645e1530b9ce66ff8`；catalog 为 218，fingerprint 为
  `be09c4928697887a092141bcbcdc3980021225176b7f72c3ad1a1afaf3913d88`，详见
  [ADR-223](architecture-decisions/adr-223-atomic-gis-service-migration-cutover.md)。该切片关闭了“已确认消费者集合到 active
  pointer”之间的事务空档；provider build/warmup、shared cache purge、自动 target renewal、rollback/provider migration、
  生产 HA/SLO 和跨协议 migration orchestration 仍未完成，AR-4 保持 `in_progress`。
- [x] 已完成 GIS service migration 的受控 rollback authority 切片：migration 219 新增 append-only
  `gis_service_migration_rollback` 和单事务 `rollback_gis_service_migration(...)`。回滚必须引用 immutable 218
  cutover ID/SHA，并精确沿 target endpoint/release/ProductVersion 回到该 cutover 的 source；数据库沿用同一 active
  endpoint pointer、product/service advisory lock 和 CAS，不创建第二套 rollback 状态机，也不覆盖原 cutover receipt。
  门禁按回滚时当前 target release 的完整有效消费者集合计算，要求每个 consumer 都有且仅有一个有效 source
  exact-release binding；随后验证 source deployment 仍为 `ready`，以及一个直接绑定 GIS ServiceURN 的
  `open/acknowledged` DataIncident，或 action 为 `gis_service_migration.rollback`、未过期且 fingerprint/context 精确绑定
  cutover SHA、endpoint 方向和 state version 的 approved ApprovalCase。authority evidence、consumer set fingerprint、
  endpoint CAS、activation event 和 rollback receipt 同一事务提交；generic activation、直接 INSERT、identity drift 和
  stale CAS 均 fail closed。disposable PostgreSQL 认证真实构造 cutover 后新增 target-only consumer，证明缺 source
  binding、无 authority、错误 Incident subject、generic bypass 和 stale CAS 都不改变 target；补齐第二名消费者的 source
  binding 后，ApprovalCase 分支在回滚事务内成功并主动回滚测试事务，Incident 分支正式恢复 source endpoint，state version
  只推进一次。两名消费者集合相等、幂等 replay、Python/SQL fingerprint、RLS/FORCE RLS、immutable ledger 和 Gateway
  `SELECT=true/INSERT=false/controlled EXECUTE=true/private activation=false` 均通过。报告为
  `.tmp/gis-service-migration-rollback-certification/report.json`，SHA-256 为
  `d002e9bb43f9a8eae9bbf2b73e23fd58af2582cd730eba166e0346b4ca9fa4cc`；catalog 为 219，fingerprint 为
  `b489a82988bed543e42e5628f017114726612545fff1567bde58e8b5985834b3`，详见
  [ADR-224](architecture-decisions/adr-224-authority-bound-gis-service-migration-rollback.md)。该切片关闭的是 active endpoint
  的数据库权威回退；provider rebuild/health refresh、cache warmup/shared purge、自动 incident routing、ServiceSLO、
  多 provider compensation 与生产 HA/RTO 仍未完成，AR-4 保持 `in_progress`。
- [x] 已完成 GIS service migration destination 的 Run-bound warmup evidence 切片：migration 220 新增 append-only
  `gis_service_endpoint_warmup` 与 controlled recorder，将一个 evidence-gated `succeeded` PlatformRun、provider receipt
  Artifact、exact endpoint/deployment/definition/release、cache policy/namespace、全成功 sample set 及有效期固化为同一
  指纹事实。Run capability 固定为 `gis-service-endpoint-warmup`，输入必须包含当前 GIS service source
  `DataProductVersion` 的 output ResourceVersion；receipt 记录时仍须有效，且最长有效期不超过 exact cache policy TTL。
  218 cutover 和 219 rollback 的目标 pointer 现在都必须命中 current live receipt；缺 target warmup 的 cutover 与缺 source
  warmup 的有效 Incident rollback 均 fail closed 且原 pointer/state version 不变。首次 activation 与同产品 revision
  activation 不受该门禁影响，不新增 provider 队列或第二套 endpoint 状态机。disposable PostgreSQL 认证为每个 endpoint
  真实执行现有 `accepted -> dispatching -> running -> succeeded` 控制面路径，并绑定 DolphinScheduler success observation、
  output Artifact、独立 QualityResult、lineage 和 RunSuccessEvidence；随后验证 source→target cutover、ApprovalCase 回滚
  分支和 Incident 正式回滚，以及 replay、identity drift、Python/SQL fingerprint、RLS/FORCE RLS、immutable ledger、
  direct INSERT denial 和 Gateway 最小权限。报告为
  `.tmp/gis-service-endpoint-warmup-certification/report.json`，SHA-256 为
  `2286eecc8a9c06d375050163ca07ba68c4cd8aece2a9559e8176e2b20f6b1fbf`；disposable catalog 为 220，fingerprint 为
  `3f65e65fc1bee30d7eed2822f4f95c4e2b9516164b0565b03df58553c3637292`，详见
  [ADR-225](architecture-decisions/adr-225-run-bound-gis-endpoint-warmup-evidence.md)。主开发库前向应用前只读 audit 证明
  219 applied、220 唯一 pending 且无 checksum/metadata/probe/duplicate/unknown drift；应用后复审为
  `220/220 in_sync`，catalog/database fingerprint 均为上述 `3f65...`。聚焦 Python/Gateway 回归 `94 passed`，
  扩大相关回归 `160 passed`，GIS service control-plane 与 Platform Gateway PostgreSQL 组合回归 `3 passed`；
  Ruff 与本切片 scoped `git diff --check` 通过。认证中的 provider receipt 是确定性 fixture，
  不代表真实 Martin/GeoServer/ArcGIS provider worker、Redis/CDN/GeoWebCache purge、provider rebuild/health refresh、
  automated incident routing、ServiceSLO、多 provider compensation 或生产 HA/RTO 已完成；AR-4 继续为 `in_progress`。
- [x] 已完成 Martin exact-release provider-origin 多样本 warmup adapter 与真实容器认证：现有
  `MartinVectorTileProvider` 新增 typed ordered sample set 和 `warmup_mvt_tiles()`，在发起 I/O 前校验 exact ready
  deployment、MVT endpoint、release、cache policy、serving projection 及 endpoint contract；随后真实执行 health、
  catalog 和 1–100 个唯一坐标的 MVT GET。每个样本必须返回非空 HTTP 200 MVT，回执固化 consumer endpoint 与
  private provider origin、全部 control IDs、cache namespace、坐标、media type、bytes、content SHA-256、ETag、时间及
  两级指纹；重复坐标、identity drift、缺 catalog layer、204/空 tile 均 fail closed。一次性
  `ghcr.io/maplibre/martin:v0.18.0` + 隔离 PostGIS 认证实际读取 `0/0/0`、`1/1/0`、`2/3/1` 三个含数据坐标，
  `3/3` 为非空 HTTP 200 `application/x-protobuf`；sample-set SHA-256 为
  `e36a2d0e4bd6b31c34bf2e67181d938d51fa1931b4aee631623918554b95b25b`，provider receipt SHA-256 为
  `ed2aaf329cd1ece300c7f83018a9e6d516decc74ce4b784be0e34faf1d6601da`。报告为
  `.tmp/martin-endpoint-warmup-certification/report.json`，SHA-256 为
  `b033dd20bcd99939a18ca99c64492052fd037887be87bffda715ed79067ceadd`，临时容器/数据库/角色已由认证路径清理；
  聚焦 provider/certifier/220 receipt 回归 `19 passed`，扩大 GIS control-plane/Gateway 回归 `126 passed`，
  PostgreSQL 组合回归 `3 passed`，Ruff 与 scoped `git diff --check` 通过，详见
  [ADR-226](architecture-decisions/adr-226-martin-release-bound-origin-warmup.md)。该历史 adapter 认证只证明
  Martin origin 的 release readiness 与 tile materialization；其后续 managed command/221 atomic settlement
  已由下项独立认证，仍不代表 Gateway、Redis/CDN/GeoWebCache shared cache 已预热。
- [x] 已完成 Martin provider-origin managed warmup command 与原子结算：migration 221 将
  `gis_service.endpoint_warmup` 接入现有 shared `platform_command_outbox`，没有新建队列或 endpoint 状态机。
  admission 在一个 Gateway transaction 中创建 `PlatformRun`、不可变 execution-plan Artifact 和 command；managed
  consumer claim 后推进 `accepted -> dispatching -> running`，调用私网 Martin health/catalog/ordered MVT samples，
  将与 provider receipt SHA 完全一致的 receipt 文件作为 evidence Artifact，再由专用 finalizer 原子写入 Martin
  observation、Artifact、passed QualityResult、source output→warmup definition LineageEvent、Run success 和 migration
  220 receipt。ACK 丢失时先对账成功 Run/receipt 后只补 ACK；provider unavailable 有界重试；plan/endpoint/release/catalog/
  sample-set drift 则让 Run 与 command 同时 terminal failed。独立 PostgreSQL 认证覆盖 admission replay、shared outbox、
  five-evidence atomic settlement、terminal failure、RLS/FORCE RLS 和最小权限，报告
  `.tmp/gis-service-endpoint-warmup-worker-certification/report.json` 的 SHA-256 为
  `9935ed85622c53b412be4f69cd1e3e2458ff14b59d86147350f0f2babd9dbd5f`。随后真实
  `ghcr.io/maplibre/martin:v0.18.0` + disposable PostGIS 端到端认证实际读取 `0/0/0`、`1/1/0`、`2/3/1` 三个
  122-byte MVT，`Run=succeeded`、`Command=done`，observation/Artifact/QualityResult/LineageEvent/220 receipt 均为 1，
  receipt file/provider receipt SHA 相等。报告
  `.tmp/martin-managed-warmup-certification/report.json` 的 SHA-256 为
  `393ff5d09e4cd97ab5788f36e4c51ed60bfd3ce2eb451f839c00da6444cd4a10`；临时 Martin、数据库和角色已清理。
  `build_gateway_report()` 现静态约束 221 finalizer、admission/settlement API、managed consumer 和 worker 源标记，
  删除 finalizer marker 的负向测试返回 `invalid`。详见
  [ADR-227](architecture-decisions/adr-227-managed-martin-warmup-command-and-atomic-settlement.md)。这只证明
  Martin private origin 的受控 warmup 与 control-plane settlement；不代表 consumer Gateway、Redis/CDN/GeoWebCache
  shared cache、其他 provider、worker HA/RTO、ServiceSLO 或自动 Incident 已完成。
- [x] 已完成 managed Martin warmup receipt 的真实 S3/MinIO 生产型对象存储认证：新增
  `S3WarmupReceiptStore` 的 versioned、Object-Locked、credential-free receipt profile，条件创建后把 exact
  `VersionId`/规范化 `ETag` 写入 Artifact storage evidence，并在结算前对同一版本执行 HEAD/GET、字节、size、
  `ContentType` 和 SHA-256 metadata 回读；AWS 凭据只走 SDK credential chain，不进入 Run、Artifact、receipt 或
  worker status。合同/故障测试覆盖 null/非法 VersionId、metadata/size/read-back/version drift、local/S3 互斥配置、
  bucket/prefix/tenant 隔离、versioning/Object Lock/default-retention probe 和状态信息不泄露。真实 disposable
  PostgreSQL/PostGIS + `ghcr.io/maplibre/martin:v0.18.0` + `minio/minio:RELEASE.2025-04-22T22-12-26Z` 认证通过
  `18/18`：三坐标 MVT、`Run=succeeded`、`Command=done`、五条 evidence、retention、prefix 外写入拒绝和 retention
  绕过拒绝均通过；从 exact VersionId 读回并校验的同内容重放复用原 URI/SHA/size/VersionId/ETag，且对象仍只有一个
  版本；异内容重放被拒绝。报告 `.tmp/martin-managed-warmup-s3-certification/report.json`，SHA-256 为
  `6ed8e487b7f6b6c1520183368b32bbc52d87dd345280f2a4ecb3848f8fc1b094`，MinIO bucket/container 与 Martin/PostGIS
  fixture 均清理完成。该证据关闭 AR-4 的“生产 receipt object storage”缺口，但不外推到 bucket replication/跨区
  DR、worker 多副本 HA/RTO、Gateway/Redis/CDN/GeoWebCache shared cache 或其他 GIS provider。
- [x] 已退役一条会绕过上述服务面约束的旧 Martin table/catalog proxy：旧
  `/api/tiles/martin/{table}/{z}/{x}/{y}.pbf` 接受任意 catalog 名称，虽要求登录，却不读取 active release、
  ConsumerBinding、service policy、serving projection 或访问审计；现在两个旧 URL 仅在认证后返回稳定的
  `410 legacy_martin_proxy_retired`，不读取 `MARTIN_URL`、catalog 或 provider。用户私有的临时工作层
  `/api/tiles/{layer_id}/...` 与 TileJSON 不属于 DataProduct GIS service，保留 owner-only 语义但由
  `public, max-age=3600` 收紧到 `private, no-store`、`Vary: Authorization, Cookie` 与无 wildcard CORS，避免
  认证工作成果进入共享缓存。`map-publications` 保持其既有 governed result-delivery 边界，未被混入此迁移。
  独立 Starlette HTTP 路由回归已验证无认证仍为 `401`；即使设置了看似有效的 `MARTIN_URL`，认证后的旧 tile/catalog
  均稳定返回 `410`，且不会初始化 `httpx.AsyncClient`。这条证据防止路由注册或未来重构重新接通 provider。
  同时 `mercantile==1.2.1` 已从仅存在于 `requirements.txt` 的状态补入 `pyproject.toml` full profile，修复
  `uv` tile runtime 的依赖漂移。详见
  [ADR-217](architecture-decisions/adr-217-retire-generic-martin-proxy.md)。
- [x] 开发环境 migration authority 已同步至 221/221：151 的 rollback authority CHECK 采用 `NOT VALID` 保留
  legacy rollback facts，153 的 advisory-lock SQL 避免 `:gis` bind-param 误解析；209 进一步修复了 migration
  ledger 已到位但 GIS Gateway ACL 被环境漂移移除的状态，恢复 control projection 所需的最小读取、terminal
  observation 写入及既有 controlled recorder/transition 执行权限；210/211 在不放宽 `SECURITY DEFINER` search path
  的条件下，显式解析 PostGIS 函数和空间重叠运算符；212 追加 exact-release `ServiceConsumerBinding` authority，
  213/214 接入 approval-bound issuance/revocation，215/216 接入 approval-bound renewal 及 decision identity guard，217
  接入 GIS service migration impact 事实及既有通知 envelope enrichment，218 接入全消费者 migration cutover gate、
  防绕过 activation wrapper 与 append-only cutover receipt，219 接入 Incident/ApprovalCase-bound rollback、当前消费者
  source exact-release binding gate、同一 pointer CAS 与 append-only rollback receipt；220 接入 exact
  endpoint/release/cache namespace 的 Run-bound warmup receipt，并为 218/219 migration destination 增加 live evidence
  gate；221 接入 managed Martin warmup command、专用 Run success/failure authority 和 shared outbox delivery。221
  前向应用前只读 audit 为 220 applied、221 唯一 pending，无 checksum/metadata/probe/duplicate/unknown drift；应用后
  runner 返回 `221/221 in_sync`，当前
  catalog/database fingerprint 均为
  `5ebdd1e1e9082b1455fc36a7058b62f01e01fbccef4183925a2a4c444fa508fc`；Compose Martin `/health` 返回 HTTP
  200 并发布 `gda_mvt_serving_projection`。该证据只证明运行时、migration 与权限边界，不代表生产 service、
  SubjectContext policy pushdown、cache namespace 或消费者真实数据面已完成。

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

**状态（2026-08-28）**：`in_progress`。AgentOps 版本合同、Temporal provider/start/reconcile
合同、PostgreSQL checkpoint/lease/target authority、真实 Temporal start/history 恢复、managed
discovery worker 和 Docker Desktop Kubernetes 双副本运行门已经形成连续证据。当前主线转向
approval/HITL、shadow/canary、online verdict、incident/rollback 与
代表任务 UX uplift；ADR-339 已关闭业务 target 的 Kubernetes lease takeover；真实 MMFE/GWM
provider、NetworkPolicy enforcement 和生产 HA/DR 仍未关闭。

交付：`AgentSpecVersion` bundle（Agent、Prompt、ModelBinding、Tool/Skill、Policy、Memory/Context）；EvaluationSet/EvaluationRun/OnlineVerdict、safety/red-team/tool-accuracy/cost eval；Approval/Promotion、Shadow/Canary、AgentDeploymentRevision；**Temporal-backed** AgentRun/TaskStep/ToolCall/TraceObservation；循环/超时/提示注入/越权检测、Guardrail、Budget、HITL、SafetyIncident/QualityIncident、disable/rollback、feedback 和 DataDemand 回流。RuntimeIdentity、RunnerFactory、RunWorkspace、intent-to-DataProductBlueprint、evidence-backed planning、typed TaskGraph/QualityVerdict、preview/diff/cost/impact、真实 retry/replan 复用统一控制面。

**2026-08-25 AgentOps contract foundation（ADR-297）**：新增
`data_agent.agentops_contracts`，先冻结多智能体 topology 和生命周期对象，再接 Temporal runtime。
`AgentSpecVersion` 要求 supervisor coordinator、可达且无环的 specialist DAG；角色合同包含
`data_engineer`、`quality_guardian`、`multimodal_fusion`、`gwm_specialist`、`gis_analyst` 和
`visualizer`。`AgentDeploymentRevision` 绑定 evaluation/policy/owner/rollout，`AgentRun`、
`AgentTaskStep`、`AgentToolCall` 和 `AgentOnlineVerdict` 统一回指 DataProductVersion、SubjectContext、
Policy 和 Artifact。6 个 contract tests 已通过。该切片是设计/合同基础，不代表 Temporal worker、真实
多智能体执行、shadow/canary、在线事故回滚或 AR-5 退出；MMFE/GWM 仍是下游 specialist/consumer，
不拥有数据真值或调度权威。

2026-08-25 Temporal integration contract（ADR-298）：新增
data_agent.agentops_temporal_contracts，冻结 Temporal namespace/isolation、task queue、
workflow identity、retry policy、workflow input、approval/pause/resume/cancel/reconcile signal、
activity evidence 和 AgentRun 状态投影；TemporalIntegrationHarness 用 deterministic
in-memory 方式验证同一 immutable definition/deployment/idempotency 产生稳定 workflow id，
stale signal 拒绝，以及 unknown provider outcome 进入 reconciliation。该切片没有新增
temporalio 依赖，也不声称已有 Temporal 集群、worker、OIDC、HA 或真实 crash/replay 证据。
11 个 AgentOps/Temporal contract tests 已通过；下一步是独立 optional profile 的 pinned SDK
sandbox rehearsal。

2026-08-25 Temporal provider adapter contract（ADR-299）：新增
data_agent.agentops_temporal_adapter，固定 GDA 到 Temporal provider 的唯一 start/signal
边界。canonical start payload 绑定 workflow identity、task queue、retry policy 和
policy decision；provider started/already_exists/unknown receipt 均有明确证据要求，unknown
不自动重试；signal receipt 必须校验 tenant、workflow 和 signal id。fake-provider conformance
新增 6 个测试，AgentOps/Temporal 相关测试共 17 个通过。该切片仍未接 temporalio、Temporal
server、OIDC、worker、HA 或真实 crash/replay；下一步才是 optional pinned SDK/server sandbox。

2026-08-25 Temporal sandbox deployment contract（ADR-299）：新增
`k8s/optional/temporal-agentops-sandbox` 与显式 overlay
`k8s/overlays/temporal-agentops-sandbox`。profile 固定可用的 `temporalio/auto-setup:1.29.7`、
`postgres:16.4-alpine`，将 Temporal metadata 与 GDA 控制库隔离，声明 namespace
`gda-agentops-sandbox`、使用外部 Secret `gis-agent-temporal-runtime`、frontend/matching
Service 和三条最小 NetworkPolicy。optional profile 的 PostgreSQL、Temporal server 和
AgentOps worker 默认均为 `replicas: 0`；overlay 只将 PostgreSQL/server 调到 `1`，worker
仍为 `0`。`data_agent/test_agentops_temporal_sandbox.py` 的 4 个离线合同测试通过，两个
profile 均经 `kubectl kustomize` 渲染成功。该证据只证明 manifest/namespace/Secret 引用/
网络隔离和 opt-in 行为，不证明 Temporal 集群已部署、temporalio SDK/worker 已接通、审批
action/GWM rollout 已执行，亦不证明 crash/restart/replay、HA、OIDC、备份恢复或生产 RPO/RTO。

2026-08-25 Temporal async provider boundary（ADR-299）：扩展
`data_agent.agentops_temporal_adapter`，新增 `TemporalAsyncProviderClient` 及
`TemporalWorkflowAdapter.start_async()` / `signal_async()`，复用既有 canonical start/signal
payload、policy binding、tenant/workflow/signal correlation 和 receipt 校验。同步入口收到
async provider result 时明确拒绝并关闭未消费 coroutine，不在 GDA 内创建或嵌套 event loop。
adapter focused tests 共 `9 passed`，AgentOps/Temporal/deployment scoped tests 共 `24 passed`。
该切片仍不包含 `temporalio` 依赖、SDK client implementation、worker image、真实 workflow
execution 或 crash/replay 证据；下一步是以锁定的 SDK 版本实现 provider client，并在 sandbox
中验证 start/signal/reconcile。

2026-08-25 Temporal SDK bridge（ADR-299）：新增
`data_agent.agentops_temporalio_provider.TemporalioProviderClient`，以 lazy-import 方式把
Temporal Python SDK 的 `start_workflow`、`WorkflowHandle.signal` 和 `RetryPolicy` 映射到
现有 async provider contract。bridge 显式传递 tenant/namespace/workflow/task queue，
将 `WorkflowAlreadyStartedError` 映射为 `already_exists`，其他提交后不确定结果映射为
`unknown` 且不自动重试；signal receipt 固化 signal id。新增 4 个 bridge conformance tests，
AgentOps/Temporal/deployment scoped tests 共 `28 passed`。当前环境仍未安装 `temporalio`，
因此这证明的是 SDK bridge 的边界和缺失依赖时的 fail-closed 行为，不是已执行真实 Temporal
workflow；下一步是锁定 SDK 版本/worker image，接入真实 namespace 后验证 start/signal/reconcile。

2026-08-25 Deterministic Agent Task Graph compiler（ADR-300）：新增
`data_agent.agentops_task_graph` 与 `AgentTaskGraph`。编译器只接受同租户、同
`AgentSpecVersion`、同 `AgentDeploymentRevision` 的 root `AgentRun`，将 topology 编译为
确定性 Kahn 顺序的 `AgentTaskStep` DAG；step ID 由 `run_id + agent_spec_sha256 + agent_id`
稳定派生，依赖按 step ID 固化，graph SHA-256 绑定完整计划。现有 supervisor/planner/
data_engineer/MMFE/GWM/quality topology 已真实生成 coordinator -> planner -> 三路 specialist
-> quality fan-in，replay 结果保持相同 step ID。新增 4 个 task-graph tests；AgentOps/Temporal/
task-graph/deployment scoped tests 共 `32 passed`。该切片是 provider-neutral planning evidence，
不代表模型、工具、数据写入、Temporal activity 或生产 worker 已执行；下一步是让 Temporal
workflow 直接消费该 immutable graph，并把每个 step 的 ToolCall/Artifact evidence 接回统一控制面。

2026-08-25 Agent task execution projection（ADR-301）：新增
`data_agent.agentops_task_execution`。`AgentTaskExecutionState` 将 ADR-300 的 immutable
`AgentTaskGraph` 与同序 `step_states` 运行投影分离，step 状态推进不会改变 plan
`graph_sha256`；`state_sha256` 封存每次 projection。`start_step` 强制依赖 succeeded，
`bind_tool_call` 用 `run_id + step_id + idempotency_key` 派生稳定 ToolCall ID，重复投递保持
幂等；`settle_tool_call` 对外部副作用要求 receipt artifact，成功要求 output artifact，
`complete_step` 禁止未结算 tool call 直接成功。新增 3 个 execution tests，AgentOps/Temporal/
task-graph/execution scoped tests 共 `35 passed`。该切片仍是 provider-neutral state/evidence
 contract，不代表真实工具、Capability/Policy admission、Artifact 持久化或 Temporal worker 已执行；
 下一步是让 Temporal workflow 直接持久化该 projection，并把 activity receipt 接回统一控制面。

同日补强 execution projection：`AgentTaskExecutionState` 现在逐项锁定 graph step 的 tenant、run、
step/agent identity、role、sequence 和 dependency 字段；即使篡改者重新计算 `state_sha256`，
plan-field drift 也会 fail closed。新增负向 contract test，AgentOps/Temporal/task-graph/
execution scoped tests 共 `41 passed`。该补强只提升 provider-neutral projection 证据，不代表
Temporal activity、Artifact persistence 或生产 worker 已完成。

同日补强 task graph plan guard：`AgentTaskGraph` 明确只接受 `pending`、`attempt=1` 且无
输入/输出 artifact 的计划 step；运行态 step 必须留在 ADR-301 projection。新增 runtime-step
负向 contract test，AgentOps/Temporal/task-graph/execution scoped tests 共 `42 passed`。

2026-08-25 Temporal workflow task-graph binding（ADR-302）：`TemporalWorkflowInput` 现在必须
携带 ADR-300 编译出的 `AgentTaskGraph`，并在 starter 边界校验 tenant、root `run_id`、
`AgentSpec` hash 和 `DeploymentRevision` hash；跨租户、跨 run、跨 spec/deployment 的 graph
均 fail closed。完整 graph 进入 `input_sha256` 和 canonical Temporal start payload，graph drift
保持原 workflow identity 但不能复用旧 input evidence，避免 worker 重解析 topology 产生另一套
step identity。新增四类 graph binding 篡改测试和 graph fingerprint/idempotency 测试；
AgentOps/Temporal/task-graph/execution scoped tests 共 `42 passed`。该切片仍是 provider-neutral
合同，不代表 Temporal server、worker、真实 already-exists 对账、crash/replay、HITL、replan
或生产 rollout 已完成；下一步是在可用的 pinned SDK/server sandbox 中验证真实 payload 对账，
再接入 ADR-301 execution projection。

2026-08-25 Deterministic task-graph workflow projection（ADR-303）：新增
`data_agent.agentops_temporal_workflow`，将 immutable `AgentTaskGraph`、ADR-301 execution
projection 和 Temporal activity evidence 组合为一条 provider-neutral workflow harness。它
强制依赖完成后才能启动 step，ToolCall dispatch/receipt 必须与当前 projection 对齐，unknown
结果进入 reconciliation，只有全图 fan-in 成功才关闭 AgentRun；成功、dispatch、activity 和
unknown 对账均支持幂等重放。新增 4 个 workflow tests，AgentOps/Temporal/task-graph/
execution/workflow scoped tests 共 `46 passed`。该切片仍不代表真实 Temporal server、worker、
模型/tool provider、HITL、crash/replay、HA 或生产 RPO/RTO；下一步是把同一 projection 接入
pinned SDK/server sandbox。

2026-08-25 AgentOps checkpoint/replay contract（ADR-304）：新增
`TemporalTaskGraphWorkflowCheckpoint`，封存 workflow input、AgentRun、完整 transition
history、activity evidence、signal 去重状态和 execution projection，并以 checkpoint SHA-256
校验 history 连续性、Run 最新状态、tenant/workflow/run correlation 和 immutable graph 一致性。
恢复后可继续执行 task graph；signal 重放保持幂等，Run/history 不一致的 checkpoint fail closed。
新增 3 个 recovery tests，AgentOps/Temporal/task-graph/execution/workflow scoped tests 共
`49 passed`。这是 provider-neutral recovery evidence，不代表真实 Temporal crash/restart、
history replay、HA、OIDC、RPO/RTO 或生产 checkpoint store；下一步是在 pinned SDK/server
sandbox 中注入 worker termination、网络不确定和 history replay。

2026-08-26 Typed Temporal activity dispatch request（ADR-305）：新增
`TemporalActivityRequest`、`derive_temporal_activity_id()` 和
`TemporalTaskGraphWorkflowHarness.build_activity_request()`。dispatch 输入现在由当前
ToolCall/execution projection 生成，固定 tenant/workflow/run/step/tool/capability/policy/
subject/side-effect/idempotency/input-artifact correlation，并用 `run_id + tool_call_id +
attempt_no` 派生稳定 activity identity；attempt 受 retry policy 限制。同一 attempt 重放稳定，
MMFE/GWM specialist request 保留各自 graph step；RECONCILING、SUCCEEDED 等终态禁止新
dispatch。checkpoint 还要求每条 activity evidence 对应 execution 中已存在的 ToolCall。
新增 5 个 request/recovery 负向与 specialist binding tests，AgentOps/Temporal/task-graph/
execution/workflow scoped tests 共 `54 passed`，Ruff/compileall 通过。该切片仍是
provider-neutral 输入合同，不代表真实 Temporal activity worker、provider invocation、
crash/restart/history replay、HITL、online observation、incident/rollback 或生产 HA/RPO/RTO；
下一步是在 pinned SDK/server sandbox 中把 request 接入真实 activity input 并注入 worker
termination 与提交后不确定结果。

2026-08-26 Temporal activity provider adapter（ADR-306）：新增
`TemporalProviderActivityResult`、`TemporalActivityAdapter`，以及 workflow harness 的
`dispatch_activity()` / `dispatch_activity_async()`。provider result 必须回显 request
fingerprint、run/step/ToolCall/activity/attempt identity，提供 receipt；adapter 根据
request side effect 校验 output/external receipt/failure/unknown 规则，并生成稳定的
`TemporalActivityEvidence` idempotency key，再交回统一 ToolCall projection。MMFE/GWM 与
其他 specialist 共用该边界，仍只拥有各自 graph step。新增 activity receipt、identity drift、
workflow projection 和 sync/async boundary tests；AgentOps/Temporal/task-graph/execution/
workflow scoped tests 共 `58 passed`，完整 AgentOps 集合 `78 passed`，Ruff/compileall 通过。
该切片仍是 provider-neutral evidence bridge，不代表真实 Temporal activity worker、SDK
invocation、retry、crash/restart/history replay、HITL、online observation、incident/rollback
或生产 HA/RPO/RTO；下一步是在 pinned SDK/server sandbox 中接入真实 activity handler。

2026-08-26 Temporal activity worker handler（ADR-307）：新增
`TemporalActivityWorkerHandler`，提供同步/异步 worker 入口：解析序列化
`TemporalActivityRequest`，调用注入的 typed action executor，复用 ADR-306 的 receipt
correlation/evidence 校验，并输出 JSON-safe provider result。非法 request、错误 identity/
fingerprint、错误 result 类型和同步阻塞异步 executor 均 fail closed。该 handler 是真实
`@activity.defn` worker 的唯一候选接入边界，Temporal SDK history/retry/heartbeat/cancel
仍由 provider runtime 负责；MMFE/GWM 仍只是 specialist action。新增 worker handler tests；
AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 `60 passed`，完整 AgentOps
集合 `80 passed`，Ruff/compileall 通过。仍不代表真实 Temporal server、worker image、SDK
activity invocation、restart/replay、HITL、online observation、incident/rollback 或生产
HA/RPO/RTO；下一步是在 pinned SDK/server sandbox 中注册真实 activity worker 并演练
start -> activity -> receipt -> replay。

2026-08-26 Temporal worker registration contract（ADR-308）：新增
`TemporalWorkerRegistration`、`TemporalioWorkerFactory`。registration hash-bound 固定
tenant/namespace/task queue/worker identity、AgentSpec/deployment revision、workflow/activity
类型和并发上限；factory 在构造 SDK Worker 前校验 client namespace、定义集合和类型绑定，
缺失 `temporalio` 或绑定漂移均 fail closed。显式 fake Worker class 仅用于合同测试，不代表
真实 worker 启动。MMFE/GWM action 与其他 specialist 共用同一 worker registration/handler
边界。新增 worker registration/factory tests；AgentOps/Temporal/task-graph/execution/
workflow scoped tests 共 `64 passed`，完整 AgentOps 集合 `84 passed`，Ruff/compileall 通过。
仍不代表 Temporal server/worker image、OIDC、真实 registration、retry/heartbeat/cancel、
termination/restart/history replay、HA 或生产 RPO/RTO；下一步是在 pinned SDK/server sandbox
中用 factory 构造真实 worker，注册 workflow/activity 并完成 start -> activity -> receipt -> replay。

2026-08-26 Temporal worker runtime config（ADR-309）：新增
`TemporalWorkerRuntimeConfig.from_env()` 和 `TemporalWorkerDefinition(name, handler)`。
worker 启动现在必须显式提供 tenant/namespace/frontend/task queue/worker identity、workflow/
activity 类型、AgentSpec hash 和 DeploymentRevision hash；frontend 端口、activity 名称、
并发上限和 hash 格式在启动前校验，缺配置直接 fail closed。provider type name 与 Python
函数名解耦，避免 `gda.agentops.gis_product` 之类稳定类型被错误映射。runtime config 可生成
ADR-308 registration；新增配置缺失/漂移及显式 name-handler tests。AgentOps/Temporal/task-
graph/execution/workflow scoped tests 共 `66 passed`，完整 AgentOps 集合 `86 passed`，
Ruff/compileall 通过。仍不代表 Temporal SDK/server、真实 worker、OIDC、activity retry/
heartbeat/cancel、termination/restart/history replay、HA 或生产 RPO/RTO；下一步是在 pinned
SDK/server sandbox 中注入这些配置、注册真实 worker，并完成 start -> activity -> receipt -> replay。

2026-08-26 Temporal activity scheduling plan（ADR-310）：新增
`TemporalActivitySchedulePlan` 与 `TemporalioActivityScheduleMapper`，将 activity type、task queue、
request/activity identity、三个 timeout、cancellation strategy 和 SDK `maximum_attempts=1`
绑定为 hash-bound schedule。平台 retry 现在要求前一 attempt 先产生确定 `FAILED` evidence；
`UNKNOWN`/`RECONCILING` 不得自动 schedule 下一副作用，attempt 2 必须生成新的 request hash 和
activity ID。schedule 已纳入 workflow checkpoint，SDK bridge 的 fake mapping 通过
`maximum_attempts=1`、timeout、task queue 和 cancellation conformance。Temporal scoped tests
共 `45 passed`，AgentOps/Temporal/task-graph/execution scoped tests 共 `70 passed`，完整
AgentOps 集合 `90 passed`，Ruff/compileall/diff check 通过。仍不代表真实 Temporal activity、
heartbeat/cancel、worker termination/restart/history replay、HA 或生产 RPO/RTO；下一步是在
pinned SDK/server sandbox 完成显式 `start -> schedule -> activity -> receipt -> replay`，再做
worker termination/unknown transport rehearsal。

2026-08-26 Real Temporal AgentOps rehearsal（ADR-311）：在 disposable Kubernetes
`gda-agentops-sandbox` 中以 Temporal server `1.29.7`、Python SDK `1.32.0` 和独立
PostgreSQL 完成真实 `start -> schedule -> activity -> receipt -> history export -> replay`。
本机 worker 通过 `TemporalioWorkerFactory` 注册独立 `gda.agentops.rehearsal.v1`，history 共
`11` 个事件，activity schedule/completion 各 `1`，SDK `maximum_attempts=1`，request、schedule、
provider result、activity evidence、history 和 report 均有 hash，离线 `Replayer` 为
`passed`；workflow 执行 `0.079464s`，worker shutdown `0.043624s`。真实证据见
`docs/reports/agentops_temporal_rehearsal_2026-08-26.json` 和对应 history。过程中修正了
server tag、driver、dynamic config、retention 和容器 UID/GID 等部署合同，并将它们加入
Kustomize tests。该切片只关闭真实 provider 的单次执行门，不代表 already-exists/unknown
对账、worker termination/restart、heartbeat/cancel、HITL、online observation、incident/rollback、
HA 或生产 RPO/RTO；下一步做 termination/unknown transport rehearsal。

2026-08-26 Temporal start input reconciliation（ADR-325）：新增
`TemporalWorkflowAdapter.reconcile_start()` 和 `gda.temporal_start_reconciliation.v1`。已有
workflow 只有在 provider 提供的 input fingerprint 与当前 immutable start payload 完全一致时才可
标记 `already_exists_matched`；指纹缺失或漂移 fail closed。`unknown` 只形成
`unknown_pending` evidence，不自动重试、不生成 provider run id。该切片是 provider-neutral
合同和 fake-provider conformance，不代表真实 Temporal already-exists/unknown history 对账；真实
sandbox 恢复后仍需执行重复 start、提交后 transport uncertainty 和 history/input observation。
本次聚焦回归为 Temporal adapter/provider/workflow `37 passed`，完整 AgentOps 测试为 `94 passed`；
这两个数字都是代码合同证据，不替代真实 provider 运行证据。

2026-08-26 Temporal provider input observation（ADR-326）：新增
`TemporalProviderWorkflowInputObservation`、`TemporalioProviderClient.observe_workflow_input()` 和
`TemporalWorkflowAdapter.reconcile_start_async()`。SDK bridge 现在从指定 workflow run 的首个
`WORKFLOW_EXECUTION_STARTED` history event 读取 payload，使用连接的 Temporal `DataConverter`
重建 canonical start request 并生成 typed observation；`unknown` 在观察到同一 input/run 时可收敛为
`already_exists_matched`，观察失败则保持 `unknown_pending`，`already_exists` 缺证据仍 fail closed。
新增真实 SDK converter 编码的 history fake conformance；Temporal adapter/provider/workflow scoped
回归为 `44 passed`。这一段本身仍是 SDK bridge/合同证据，不是 Temporal server 运行证据；真实
运行结果见下面的 start reconciliation rehearsal。

2026-08-26 Real Temporal start reconciliation rehearsal（ADR-326）：在修正 optional profile 的
`BIND_ON_IP=0.0.0.0` 后，disposable `gda-agentops-sandbox` 以 Temporal `1.29.7` / Python SDK
`1.32.0` 实际执行重复 start 与提交后 transport uncertainty。第一条 workflow 的同 ID 第二次
start 返回真实 `already_exists`，读取真实首个 start event 的 input 后匹配为
`already_exists_matched`；第二条 workflow 在 Temporal 已接受 start 后由注入 client 抛出异常，
provider 返回 `unknown`，GDA 未重试，读取真实 history 后同样收敛为
`already_exists_matched`。两条最终完整 history 各 `10` 个事件，观察调用均读取真实首个
`WORKFLOW_EXECUTION_STARTED` event；
报告与原始 history 见 `docs/reports/agentops_temporal_start_reconciliation_2026-08-26.json` 及
同名前缀的两份 history。该证据只关闭单副本、单 namespace、短 workflow 的 start/input
reconciliation slice，不外推到 worker termination/restart、HITL、online observation、incident/
rollback、HA 或生产 RPO/RTO。

2026-08-27 Real Temporal worker termination/restart rehearsal（ADR-327）：新增
`scripts/rehearse_agentops_temporal_worker_restart.py`，以两个独立本地 worker 进程连接
disposable `gda-agentops-sandbox`。第一 worker 在真实 `ACTIVITY_TASK_STARTED` 后被 `SIGKILL`，
Temporal history 产生一个 definitive `TIMEOUT_TYPE_START_TO_CLOSE` activity timeout；SDK
`maximum_attempts=1` 没有隐藏重试，
workflow 显式提交新的 attempt 2（新的 activity/request/schedule SHA-256，复用同一 ToolCall
业务幂等键），第二 worker 接管并完成。真实 Temporal `1.29.7` / Python SDK `1.32.0` 证据：
第一 worker exit `-9`，第二 worker exit `-15`，history `19` 个事件（两个 schedule、一个 timeout、
一个 completion），`history_replay_status=passed`，恢复耗时 `61.871384s`。报告与原始 history
见 `docs/reports/agentops_temporal_worker_restart_2026-08-27.json` 和同名前缀 history。
该 slice 只证明单 namespace、单 task queue、单副本 worker 的 termination -> explicit attempt
recovery -> replay；仍不代表生产 worker image、checkpoint store 对账、HITL、online observation、
incident/rollback、fencing、HA、备份恢复或 RPO/RTO。

2026-08-27 Temporal history/checkpoint reconciliation contract（ADR-328）：新增
`data_agent.agentops_temporal_reconciliation`，把 Temporal provider history 与 GDA
`TemporalTaskGraphWorkflowCheckpoint` 做 hash-bound、fail-closed 对账。新增
`TemporalioProviderClient.observe_workflow_history()`，使用 Temporal SDK `DataConverter` 解码真实
history 中的 workflow input、activity schedule/start/terminal event 和 provider result；孤立 event、
重复 terminal、request/activity identity 漂移、start input drift 和超过显式 retry 边界的 attempt
均拒绝生成 observation。对账输出固定为 `matched`、`checkpoint_behind` 或 `provider_behind`，并在
对账前校验 canonical start input fingerprint，避免相同 workflow id 下的错误投影被误判为一致。
本轮 reconciliation 合同 `6 passed`，Temporal SDK provider `10 passed`，rehearsal contract
`2 passed`；fake-history conformance
使用 `temporalio==1.32.0` 官方 converter 与 protobuf `HistoryEvent`，覆盖 start input、activity
completion、worker-restart timeout projection、request drift、checkpoint/provider lag 和 start
input drift。随后在 disposable `gda-agentops-sandbox` 以 Temporal `1.29.7` / Python SDK `1.32.0`
完成真实 `provider_behind -> checkpoint_behind -> matched` 三态对账：signal gate 前 provider history
尚无 activity；activity 完成后旧 checkpoint 同时缺 terminal evidence 和 AgentRun terminal status；
投影同一 provider result、完成 TaskStep/AgentRun 后两侧一致。完整 history `15` events，offline replay
passed；报告、原始 history、provider observation、checkpoint before/after 和三份 reconciliation
见 `docs/reports/agentops_temporal_checkpoint_reconciliation_2026-08-27*`，报告 SHA-256 为
`e15b59d099b7ece4e94a8915fa4bffdc7752b827f61c2edf2b13d367e7573a06`。该 slice 已关闭真实
provider observation 与 checkpoint 对账门，尚未关闭生产 checkpoint/evidence repository、crash
window、并发 reconciler/fencing、HITL、online observation、incident/rollback、HA 或生产 RPO/RTO。

2026-08-27 AgentOps Temporal checkpoint PostgreSQL authority（ADR-329）：新增 migration 240 和
`PostgresAgentOpsTemporalCheckpointAuthority`，以 tenant/workflow predecessor CAS 保存 append-only
checkpoint chain，以 provider history/checkpoint hash 保存 append-only reconciliation evidence；
数据库重新计算 canonical SHA-256，gateway 只能通过 `SECURITY DEFINER` gateway 写入，两张表均有
RLS/FORCE RLS 和 immutable trigger。disposable PostgreSQL 复用 ADR-328 真实证据，完成 2 个
checkpoint、2 条 `checkpoint_behind -> matched` reconciliation、旧 predecessor/actor drift/篡改
拒绝、跨租户隐藏、直接写拒绝和独立进程 typed 恢复，13 项检查全部通过。报告见
`docs/reports/agentops_temporal_checkpoint_postgres_rehearsal_2026-08-27.json`，SHA-256 为
`01464da844774881393d9842193b99586e331bdc09915ec37c3683d29ecad9b8`。这是持久权威技术基线，
不代表生产 checkpoint store 已部署。

2026-08-27 AgentOps Temporal reconciler lease/fencing（ADR-330）：新增 migration 241。每个
tenant/workflow 的 PostgreSQL lease 在到期接管时单调递增 epoch；checkpoint/reconciliation 写入前
在同一事务锁定并核验 owner、epoch 和 expiry，成功写入同时追加不可变 lease binding；gateway 的
旧无租约写权限被撤销。真实进程级演练证明 commit 前退出完整回滚、commit 后退出可按精确 hash
恢复且不重写，worker B 以 epoch 2 接管后 worker A 的迟到写被拒绝。最终 2 个 checkpoint、2 条
reconciliation，14 项检查全部通过；报告见
`docs/reports/agentops_temporal_reconciler_fencing_2026-08-27.json`，SHA-256 为
`6fed4f66c13eca393d999d5c7ffb450d0035ea77ccf079b4c4f253a3735295f3`。该 slice 关闭数据库写入
fencing 与 checkpoint crash window，不外推为真实多副本 worker、生产 rollout、HA 或 RPO/RTO。

2026-08-27 Managed AgentOps Temporal reconciler worker（ADR-331）：新增
`data_agent.agentops_temporal_reconciler_worker`，对显式 tenant/namespace/workflow/provider-run target
执行 per-cycle acquire、慢 observation 期间 heartbeat、fenced reconciliation、未知提交精确恢复和
graceful release；heartbeat 失败会取消 observation 并保持零写入，配置漂移进程级 fail closed，
Temporal 暂时错误进入下一轮。disposable PostgreSQL 启动独立进程 A，数据库实际观察到 5 次 renew，
超过原始 TTL 后进程 B 仍不能接管；A 被 `SIGKILL`（exit `-9`）后，B 等待最后一次 expiry 并以
epoch 2 接管，写入唯一一条 `matched` evidence，A 的 epoch 1 迟到写被拒绝。9 项检查全部通过，
报告见 `docs/reports/agentops_temporal_reconciler_worker_2026-08-27.json`，SHA-256 为
`fb75f5c117b687fa83683743a8bc60d9559582cfbd1136e061a54d06b74966f1`。本次 observation 复用
ADR-328 的真实 Temporal 文件，没有同时连接 live Temporal；动态 work discovery、Kubernetes
多副本和生产 rollout 仍未完成。

2026-08-27 Temporal start target registration/work discovery（ADR-332）：新增 migration
242 与 `PostgresAgentOpsTemporalStartTargetAuthority`，把完整
`TemporalWorkflowStartRequest`、`TemporalProviderStartResult` 和 start reconciliation
证据持久登记为 target；`unknown`/`unknown_pending` 只能停留在
`pending_start_reconciliation`，不能伪造 provider run。新增 `start_and_register[_async]`
入口、数据库 `FOR UPDATE SKIP LOCKED` claim、claim renew、过期恢复、unknown input-match
绑定、retry、complete/fail 状态机和 RLS/受控函数边界；discovery worker 领取后复用
ADR-331 的 fenced history/checkpoint reconciler，没有 GDA checkpoint 时只释放 claim 等待
下一轮。真实 PostgreSQL disposable 演练 6/6 通过：start receipt 重放幂等、live claim 排他、
过期 claim 接管、unknown -> input matched 收敛和 stale worker 拒绝。报告见
`docs/reports/agentops_temporal_start_target_postgres_rehearsal_2026-08-27.json`，SHA-256 为
`a49f86e6562618b4db91d4dd7eddd57f1c078fc46122111ad0901bccaf5c38cd`。随后在
`gda-agentops-sandbox` 完成 live Temporal + PostgreSQL 联合 discovery `5/5`：真实 start
后注入 transport uncertainty、真实 `unknown` receipt、discovery claim、首个
`WORKFLOW_EXECUTION_STARTED` input 读取、input hash 匹配后的 provider run 绑定，以及无
GDA checkpoint 时保持 `ready`。报告见
`docs/reports/agentops_temporal_start_target_live_rehearsal_2026-08-27.json`，SHA-256 为
`83a2339ac8b976a24ffb751b761288a9fe3339a86126cd1dd17c7fd1e87a8fe3`。该报告本身覆盖
disposable PostgreSQL/Temporal 单副本 sandbox；后续 Kubernetes 多副本证据见 ADR-335。

同日补齐 discovery deployment contract：`k8s/optional/temporal-agentops-sandbox/discovery-worker.yaml`
作为独立、默认 `replicas: 0` 的 deployment，复用 GDA `DATABASE_URL`/tenant-id Secret，使用
`python -m data_agent.agentops_temporal_reconciler_worker --discover`，并以 NetworkPolicy 限制到
GDA PostgreSQL、Temporal frontend 和集群 DNS。它不承载 Temporal activity handler，也不创建 workflow；
base profile 保持 `replicas: 0`，只有通过准入检查的显式 overlay 才能启用副本。
跨 namespace 到 GDA control PostgreSQL 的 ingress policy 单独放在
`k8s/optional/temporal-agentops-discovery-control-access`，不会被 sandbox namespace 的
kustomize namespace transformer 错放到 Temporal namespace。

同日补齐 discovery worker 运行健康面：状态文件以原子替换保存 worker state、最近成功周期、
Temporal frontend reachability、claim/completed/pending/failed、claim-lost 和 observation-timeout
计数；`health` readiness 要求最近成功周期且 frontend health serving，`liveness` 只判断进程循环
仍在推进。新增 Prometheus discovery operation/cycle/last-success 指标，并将 metrics Service、
startup/readiness/liveness probes 纳入 optional profile；Prometheus Operator `ServiceMonitor`
另拆为 `k8s/optional/temporal-agentops-discovery-observability` 可选 package；profile 仍默认
`replicas: 0`；另提供 `k8s/overlays/temporal-agentops-discovery-sandbox` 的显式双副本
RollingUpdate/PDB overlay。

同日补齐 ADR-334 的 discovery sandbox deployment preflight：新增只读
`scripts/preflight_agentops_temporal_discovery_sandbox.py`，对 rendered overlay、外置
`gis-agent-agentops-discovery-runtime` 的 `database-url`/`tenant-id` 引用、跨 namespace
control-database policy、migration 240/241/242 status report 和目标集群资源做 fail-closed
检查；不创建 Secret、不执行 migration、不修改 Kubernetes。`--static-only` 报告会在缺少
控制库 migration status 时正确阻断。
同时 `temporalio==1.32.0` 已进入 requirements，临时镜像
`gis-data-agent:agentops-discovery-20260827` 已验证 Temporal SDK、240/241/242 migration、
worker import 与 CLI help；overlay 已固定镜像 digest。新增 preflight/container contract 共 6 项
测试通过。首次 live preflight 发现控制库为旧 `97/97`、runtime Secret 和跨 namespace
NetworkPolicy 未满足；首次 server-side dry-run
因缺少 ServiceMonitor CRD 阻断后，已将 ServiceMonitor 拆为独立 optional observability
package；核心 profile 保留 metrics Service，不再依赖 Prometheus Operator CRD。旧控制库只读
status 保存为
`docs/reports/agentops_control_schema_status_2026-08-27.json`，其中旧 app 镜像报告
`catalog_count=97`，不能用其 `pending=[]` 作为 migration 通过证据。

2026-08-28 Kubernetes discovery sandbox runtime acceptance（ADR-335）：正式 migration Job 将
控制库从 97/97 前向迁移到 242/242，catalog/database fingerprint 同为
`a7b1688cdae830ae4d42bb97fc533011eee14a0564ff7cf8344a005296992636`；外置 Secret 仅含
`database-url` 和 `tenant-id`，runtime 使用普通 `agent_user` 及受控函数写入。修复
`get_db_connection_url()` 未读取 `DATABASE_URL` 的启动故障，并为 Docker Desktop 增加明确的
本地镜像 overlay，通用 overlay 继续固定 immutable digest。`--expect-deployed` post-apply
preflight 全部通过，两个 Pod 的 status、health 和 metrics 均通过。

故障演练结果：单 Pod 终止时 ready/available/Service endpoint 最低为 1，约 7 秒补回，存活
worker cycle 持续增长；Temporal deployment `1 -> 0 -> 1` 时 worker 进入 degraded，readiness
失败而 liveness 保持，依赖恢复后无需重启自动回到 ready；RollingUpdate 全程至少两个 ready
endpoint，最大 3 Pod；PDB 允许第一次 eviction，并以 429 拒绝第二次并发 eviction。完整报告见
`docs/reports/agentops_temporal_discovery_kubernetes_sandbox_acceptance_2026-08-28.json`。当前
`kindnet` 不执行 NetworkPolicy，不能登记网络分区通过；`local-dev` 无 due target，也不能登记
Kubernetes 业务 lease takeover。跨节点/可用区、数据库恢复、identity rotation、容量 SLO、HA、
backup/restore 和 RPO/RTO 继续保持未通过。

2026-08-28 AgentOps Temporal multi-specialist TaskGraph execution（ADR-336）：新增
`TemporalTaskGraphExecutionManifest` / `TemporalTaskGraphExecutionInput`，将每个 graph step 的
activity type、tool/capability/policy、SubjectContext、side-effect、task queue、超时、取消策略
和显式 idempotency key 做 hash-bound 执行绑定；workflow 启动前重新用 AgentSpec、deployment 和
root AgentRun 编译并比对 immutable graph，MMFE/GWM 保持普通 specialist，不能取得 control-plane
write 权威。新增 `TemporalTaskGraphWorkflow`，真实按 coordinator -> planner ->
data_engineer/MMFE/GWM fan-out -> quality fan-in 执行；每个 specialist 共用 typed
`TemporalActivityWorkerHandler` / `TemporalActivityAdapter`，SDK `maximum_attempts=1`，失败后的
下一次 attempt 由平台显式创建，unknown 保留同 wave 已回写证据并停在 reconciliation。

本地 execution/authority/replay 测试及既有 Temporal worker/provider 回归共 `43 passed`（当前
完整 Temporal 专项回归 `136 passed, 5 skipped`；完整 AgentOps 集合 `181 passed, 5 skipped`）；在
`gda-agentops-sandbox` 使用 Temporal server `1.29.7`、Python SDK `1.32.0` 完成真实六 specialist
rehearsal：4 个 execution waves，6 个 ToolCall，7 次显式 activity schedule/completion，其中
GWM attempt 1 为 transient failure、attempt 2 成功；checkpoint 中 7 条 evidence、所有 step/
ToolCall 均 succeeded，Temporal history 41 events，Replayer passed。机器可读报告、原始 history
和 SHA-256 见 `docs/reports/agentops_temporal_task_graph_rehearsal_2026-08-28.json`、
`docs/reports/agentops_temporal_task_graph_history_2026-08-28.json`。该 slice 只关闭真实
TaskGraph 执行、显式 retry、evidence 回写和 history replay；HITL、shadow/canary、online verdict、
incident/rollback、真实 MMFE/GWM data provider、Kubernetes NetworkPolicy enforcement、生产 HA/DR
和 RPO/RTO 仍未完成。

2026-08-28 AgentOps Temporal step-bound HITL（ADR-337）：新增
`TemporalStepApprovalBinding`，把 tenant/workflow/run、graph SHA、step/agent、deterministic
ToolCall、tool/capability、policy decision、SubjectContext、side-effect、ApprovalCase ref、
owner/scope 和期望 state version 做 hash-bound 绑定；`CONTROL_WRITE` / `EXTERNAL_WRITE`
没有唯一 binding 时 workflow input fail closed，MMFE/GWM 仍不能取得 control-plane write 权威。
workflow 在 provider activity 前通过 create activity 幂等写入现有 PostgreSQL
`ApprovalCaseAuthority`，进入 `WAITING_REVIEW` 并暴露 pending query；approve/reject signal 只进入
durable inbox，随后由 read-only verification activity 重新加载权威 case，逐字段验证 binding、
terminal verdict、human approver、expiry 和 workflow state version，验证通过后才恢复或拒绝。
没有引入第二套审批真值。

focused HITL 合同回归 `15 passed`，完整 Temporal 专项回归 `136 passed, 5 skipped`，完整
AgentOps 集合 `181 passed, 5 skipped`，Ruff 和 compileall 通过。真实
 `gda-agentops-sandbox` rehearsal 使用 Temporal server `1.29.7`、SDK `1.32.0` 和一次性
 PostgreSQL database：第一个 worker 创建 pending case 后退出，第二个全新 worker 从 history
 replay 恢复完全相同的 pending query（`worker_restart_pending_state_preserved=true`）；case
 先 assign standby 再 reassign 到 binding scope，旧 assignee 的决定被 PostgreSQL authority
 拒绝；case 仍为 state 0 时的提前 approve signal 被 authority verification 拒绝；匹配 scope
 的人工批准后 fresh signal 才恢复 coordinator control write；最终 assignment 事件链为
 `assigned -> reassigned -> closed`、version 3；10 次显式 activity schedule/completion，
 Temporal history 67 events，Replayer passed。报告与原始 history 见
 `docs/reports/agentops_temporal_step_hitl_assignment_rehearsal_2026-08-28.json`、
 `docs/reports/agentops_temporal_step_hitl_assignment_history_2026-08-28.json`。该 bounded slice
 不代表生产审批运营、Temporal/ApprovalCase HA/DR、通知 SLA、OIDC/secret rotation、NetworkPolicy
 enforcement、backup/restore、RPO/RTO、shadow/canary、online verdict 或 incident rollback 已
 完成，`production_readiness_claimed=false`。报告 canonical SHA-256 为
 `0808651f86d1b4f19606d05d9ac95f08344b5138f214aee8e6f9a3841e8a52ca`，原始 history SHA-256 为
 `cc459ea7505039c5b41ca5bb38664812d1fdc19a03a478ab09ac5dc4faf7b097`。

以上 ADR-337 记录已由 assignment authority 和 restart/replay follow-up 证据更新；旧报告
hash 不再作为当前证据引用。当前唯一有效报告是
`docs/reports/agentops_temporal_step_hitl_assignment_rehearsal_2026-08-28.json`，其 canonical
report SHA-256 为 `0808651f86d1b4f19606d05d9ac95f08344b5138f214aee8e6f9a3841e8a52ca`，history
SHA-256 为 `cc459ea7505039c5b41ca5bb38664812d1fdc19a03a478ab09ac5dc4faf7b097`。

2026-08-28 Temporal ApprovalCase expiry automatic convergence（ADR-338）：新增 migration
`243_agentops_approval_expiry_authority.sql` 和 `ApprovalCaseAuthority.expire(...)`。expiry
在 PostgreSQL 同一行锁内使用 `clock_timestamp()` 判断到期，只允许 `pending -> cancelled`，
与人工批准/拒绝共享竞争控制，并复用既有 assignment close trigger；Temporal workflow 使用
ApprovalCase `expires_at` 的 durable timer，只有拿到权威 `cancelled` 结果才收敛 workflow，
authority 不可用时 fail closed，不调度 specialist/provider。真实 sandbox + 临时 PostgreSQL
演练已通过：case 到期后为 `cancelled`，assignment 事件为 `assigned -> closed`、version 2，
provider/specialist activity 调用数为 0，2 个 activity schedule、22 个 history events，
Replayer passed。报告见
`docs/reports/agentops_temporal_step_hitl_expiry_rehearsal_2026-08-28.json`，原始 history 见
`docs/reports/agentops_temporal_step_hitl_expiry_history_2026-08-28.json`；报告 canonical
SHA-256 为 `264122758a7a44178e82b6621887feb5a43eb314629ae6f195db414bd3e363ec`，history
SHA-256 为 `cf92121f0f0825355fdecf2de4bfc1a4787463fa6088cf4ad331c09f9598a195`。
该证据仍标记 `production_readiness_claimed=false`；通知 SLA、升级/批量审批、生产
HA/DR、备份恢复、RPO/RTO 和审批运营闭环继续保持未完成。

2026-08-28 AgentOps Kubernetes business target lease takeover（ADR-339）：在
`gda-agentops-sandbox` 使用真实 Temporal `1.29.7`、Python SDK `1.32.0`、PostgreSQL
242 authority 和 discovery Deployment 完成业务 target 生命周期故障演练。一个使用同一
镜像、runtime Secret、worker identity 和 NetworkPolicy-compatible labels 的临时 holder Pod
先 claim 提交后 `unknown` 的 start target，随后被强制终止；恢复的 managed discovery Pod 等待
原 60 秒 lease 到期后重新 claim，通过真实 Temporal history/input observation 写入匹配的
provider run/reconciliation evidence。target attempt `1 -> 2`，lease wait `61.481s`，history
5 events，Replayer passed，11/11 checks 通过。报告与 history 见
`docs/reports/agentops_temporal_discovery_kubernetes_business_target_2026-08-28.json` 和
`docs/reports/agentops_temporal_discovery_kubernetes_business_target_history_2026-08-28.json`；
report SHA-256 为 `bd1b259db7f5930143ef0be5199f2a788b81db1412130ab857b0ed855532262a`，canonical
history SHA-256 为 `e1c77efe3fde01fd798f38466f6ec2c8ab8a285c93e183f3633bd502c729cb68`。
该 bounded slice 仍标记 `production_readiness_claimed=false`；kindnet 不执行 NetworkPolicy，
跨节点/可用区、Temporal/数据库 HA、failover/restore、identity rotation、容量 SLO、staging/
production rollout 和 RPO/RTO 继续保持未完成。

2026-08-28 AgentOps 真实 MMFE/GWM specialist provider slice（ADR-340）：为
`TemporalActivityRequest` 增加可选、hash-bound 的 `TemporalProviderExecutionSpec`，固定
provider、operation、参数、输出媒体类型和输入 Artifact UUID 选择；provider 不能从请求中
自行发现未绑定的输入。新增注入式 `SpecialistArtifactStore` 与 bounded filesystem 实现，
activity output 以 deterministic Artifact UUID 幂等写入，并在 manifest 中保存 request hash、
输入 lineage、content SHA-256、MMFE quality/strategy 或 GWM claim boundary。

真实 Temporal `1.29.7` / Python SDK `1.32.0` 演练通过：4 个 execution waves、6 个 ToolCall、
6 次显式 activity schedule/completion、Temporal history 41 events、Replayer passed；MMFE
`spatial_join` 真实输出 1 行 GeoJSON、quality score `1.0`，GWM 真实输出
`uwm.canonical_observation.v1` 且 claim boundary 为 `bounded_support`。报告见
`docs/reports/agentops_temporal_real_specialists_2026-08-28.json`，原始 history 见
`docs/reports/agentops_temporal_real_specialists_history_2026-08-28.json`；报告文件 SHA-256
为 `2081ad7a89d955a2f6d58dc9b2a7e4255efec7557a48f78013b22d0169b8c135`，history 文件 SHA-256
为 `e23a73781077da13e75881a2a2507225da3759fe743bad9c0c725c02c4679658`。

该 slice 只证明已有 MMFE/GWM runtime 在 Temporal activity 边界上的真实调用、Artifact 输入
选择、输出 checksum/lineage 和 replay；filesystem store 是 disposable 实现，不能外推为
PostgreSQL Artifact authority、MinIO/Iceberg/PostGIS provider、跨引擎 conformance 或生产
readiness。provider cancellation/unknown 对账、NetworkPolicy enforcement、identity/secret
rotation、HA/backup/restore、SLO、shadow/canary、online verdict、incident/rollback 仍未完成。

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
6. 执行 [AR-0 首条 Vertical Slice Freeze Manifest](freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)：补齐业务责任/许可/SLO 批准，修复 JQDLTB source-quality blocker，并重跑冻结协议。
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
| AR-0 Architecture/Schema/Runtime Truth Freeze | `in_progress`（首条切片的范围/身份/设计、真实源 impact preview、语义准入、批准规则 artifact 运行绑定和本地 DolphinScheduler 3.4.2 runtime attestation 已完成；JQDLTB 十项 decision packet 已产生 partial `submitted` 版本，当前仍有 `nonpositive_area_policy`、`SJNF/MSSM`、许可、SLO 和环境 attestation blocker，`awaiting_business_approval`，全量源质量仍失败） | [Freeze Manifest](freezes/2026-08-22-ar0-first-vertical-slice-freeze.md) 的业务/SLO 批准记录；补齐更正 artifact 与语义证据后的完整 decision packet；批准后的 versioned transformation contract、规则 artifact、source-quality 重跑报告和同一 ProductVersion 的 Raw→ADS evidence |
| AR-1 Unified Metadata + Orchestration Control Planes | `in_progress`（开发环境 control/evidence ledger + 真实 OpenMetadata 1.13.1 generic-lineage reconciliation 与已绑定 glossary-term 主数据字段投影 + 真实 DolphinScheduler manual/backfill、原子 schedule-window admission、质量与 runtime restart/reconcile 切片 + GDA crosswalk search/read + bounded Gravitino/OpenMetadata provider search/read + GDA 控制账本双租户 dump/restore 已验证，仍受 AR-0 阻塞） | OpenMetadata production foundation/治理采集/provider-wide search/OpenMetadata parity、外部系统双租户与恢复、产品化 glossary term provisioning/binding + Gravitino fabric production foundation、DolphinScheduler production foundation/manual UI + OIDC/retry/cancel/迟到回调/生产触发源/metadata restore/HA 与 Spark/Flink adapter 通过故障注入和双租户验收 |
| AR-2 Source/Ingestion + Geospatial Lakehouse Vertical Slice | `in_progress`（真实重庆 OSM 已验证 Lightweight 全分层、Default Lakehouse Spark/Iceberg batch + merge/time-travel/replay、Flink event stream、PostgreSQL WAL CDC，以及 Spark/Flink/MinIO Iceberg create/read/schema evolution/append/checkpoint recovery/cancel/ack-loss reconciliation/并发 append 乐观重基/snapshot-bound overwrite、无分区与 identity-partitioned copy-on-write key-delete、identity-key partition-replace update、bounded 单键 SQL MERGE stale conflict isolation、单表复杂 `AND/OR/IN` SQL MERGE 谓词匹配、单行 SQL UPDATE snapshot guard/stale fail-closed、两个目标简单 IN 谓词多行 SQL UPDATE 整体 fail-closed/fresh retry、两个目标单表复杂 `AND/OR/IN` SQL UPDATE guard/fresh retry、两个 target 的不相关 scope subquery UPDATE stale/fresh retry、单表显式 rank 自动去重后 fresh MERGE、跨进程 PostgreSQL retry-budget admission、连续两次成功 fresh retry、position/equality delete 双向顺序互操作、两文件单 RowDelta position-delete 及 stale conflict isolation、update/equality-delete 和 equality-delete/insert 冲突隔离，以及安全检查开启的 single-operation Flink writer lifecycle；restricted 重庆建筑与 DEM 已验证 ODS；connector、schema drift、ApprovalCase 基础权威；SourceSync 已冻结数据形态、采集方式、目标层、adapter、标准/模型/质量/分类/保留/schema evolution/quarantine/promotion 治理合同，并原子强制 Silver/Gold 的 QualityResult、ApprovalCase、LineageEvent、metadata outbox 和 provider quarantine receipt；通用 quarantine recorder 已由真实 Flink duplicate/late、PostgreSQL CDC invalid-record 拒绝和 Spark/Iceberg 双 phase 零拒绝回执共同认证；PostgreSQL CDC 同一 slot 的双次有界网络分区、逐阶段目标 LSN 恢复、WAL 积压、无部分 sink commit、分区中 active nullable-column DDL/DML continuity、三次快速断连/重连后的精确 DML LSN 恢复、超过 checkpoint timeout 的 20 秒断网及 60 秒 sink/slot 联合恢复预算、20-cycle 高频物理抖动的 post-detachment LSN 停滞/精确目标/残余 WAL 安全预算、物理 slot absence 与同名新 incarnation 的 SourceSync-0 fail-closed、有限 `max_slot_wal_keep_size` 下同一槽 WAL `lost` 与文件系统安全底线、PostgreSQL 16 真实物理备库精确回放/提升/timeline 递增与 logical-slot 缺失 fail-closed、stop-and-detach fencing 证据、live-primary split-brain fail-closed admission，以及绑定旧 checkpoint 的 recovery plan 与独立 full/overwrite resnapshot provider commit/reconciliation、plan-bound automatic recovery schedule、真实 DolphinScheduler dispatch 与 success-evidence finalization；breaking successor fail-closed 已验证；ResourceVersion 架构四元绑定、PostGIS 架构观测/对账、drift-to-ApprovalCase 入审、外部 schema Artifact、确定性 compatibility、lineage-bound assessed ApprovalCase、双层审批后的 successor ResourceVersion/架构四元组/血缘原子创建，以及第三层产品 release 审批、消费者感知 promotion 和确定性 rollback pointer 切片已验证；Flink through Gravitino REST catalog 的单表、单并行度 bounded 数据面互操作已按 ADR-252 验证；DriveTransfer lightweight local file-lake 的真实 bundle/断点/完整性/解包/幂等切片已按 ADR-253 验证） | 将 quarantine receipt 扩展到其他数据库 CDC/非结构化/点云/时序真实 adapter、production STAC、非 JSON drift、跨 source 重复摄取、CDC selected-column/concurrent-DDL evolution、reconnect-backoff exhaustion、生产 recovery-controller/slot-loss detection、slot 自动修复/同步与 CDC 自动续传、物理磁盘耗尽与 predictive capacity SLO、生产 failover RPO/RTO、自动 fencing/lease 与 split-brain prevention、Flink/Iceberg kill/network uncertainty、position/MOR 复杂谓词、SQL UPDATE 相关子查询/join/跨分区/通用多文件语义、SQL MERGE provider abort recovery、跨 target/跨分区 survivorship、通用 partition evolution/MOR 多文件 destructive write、`DriveTransfer` 生产 provider、生产 SLO/Incident、双租户/恢复，以及默认/轻量/云 profile 等价验收 |
| AR-2 mutation evidence note | ADR-259 已补齐单 target row、两条重复 source row 的 SQL MERGE cardinality fail-closed 和显式去重 retry；ADR-260 已补齐单 target row 的 matched-update + not-matched-insert 多分支单次 snapshot；ADR-261 已补齐单 target row 的 matched-delete 单次 snapshot；ADR-262 已补齐两个不同 target row 的单次 matched-update；ADR-263 已补齐一个条件 matched-delete 加一个默认 matched-update branch；ADR-264 已补齐两个均未匹配 target 的 not-matched insert branch 单次 snapshot；ADR-265 已补齐 matched-delete、matched-update、条件 not-matched-insert、默认 not-matched-insert 的四分支单次 snapshot；ADR-266 已补齐同 worker 内 cardinality rejection 后的 fresh-state retry 编排；ADR-267 已补齐单表 `AND/OR/IN` 复杂谓词匹配及 guard row fail-closed；ADR-268 已补齐两个 target 的单表复杂 `AND/OR/IN` SQL UPDATE guard/fresh retry 及 guard row fail-closed；ADR-269 已补齐单表显式 rank 的自动去重选择及未选 token fail-closed；ADR-270 已补齐提交前 retry budget admission、超预算停止和 catalog/row-set fail-closed；ADR-271 已补齐两个 target 的 per-target rank survivorship admission 及未选 token fail-closed；ADR-272 已补齐两个 identity 分区 MERGE 的 `table.files` before/after 物理范围对账、目标分区替换和 guard 分区不变；ADR-273 已补齐单表两个 target 的不相关 scope subquery UPDATE、stale guard 和 fresh retry；ADR-274 已补齐同 worker、单表 bounded MERGE 的自适应退避、retry budget 和超预算 fail-closed；ADR-275 已补齐单 worker、单 target 退避后的单次成功 fresh retry；ADR-276 已补齐两个独立 worker 共享 PostgreSQL retry-budget authority 的 3 次准入和第 4 次 fail-closed 拒绝；ADR-277 已补齐同 worker 内连续两次成功 fresh retry 及 overwrite snapshot parent 链；ADR-282 已补齐单表一次 `identity(road_id)` partition-spec evolution、旧 spec 文件保留、新 spec Flink append 和混合 spec time-travel/read；ADR-283 已补齐混合 spec SQL DELETE 的 COW 物理范围对账，并记录 MOR 请求在当前 provider 上实际落成 COW；ADR-285 已补齐混合 spec equality-delete 的受控 delete+append rewrite、rewrite 前后 admission 和 rewrite 后单键 equality-delete。当前仍不覆盖 SQL UPDATE 相关子查询/join、多表、通用 partition evolution/MOR 多文件 destructive write、自动 compaction/rewrite、provider abort recovery、字段级业务合并、混合分支并发冲突或生产 writer recovery。 |
| AR-2 mutation evidence follow-up | ADR-286 已补齐两个 data file 的单 RowDelta position-delete 物理范围对账；ADR-287 已补齐该 multi-file writer 的 stale snapshot 整体拒绝、catalog 不变和失败 delete file 清理。 |
| AR-3 Data Product Engineering + Governance Workbench | `in_progress`（typed DataProductBlueprint 已可编译、diff、幂等写入既有 definition authority，将 changeset 提交统一 ApprovalCase，并由 DataProductVersion publish/promotion 精确消费；contract-test 已进入 PlatformRun admission，deterministic local executor 已完成 output/quality/lineage/success-evidence 闭环并支持幂等 failure receipt 和 governed cancellation convergence；首个真实 Lightweight DuckDB/Parquet provider 已执行 plan/PhysicalLocation 精确绑定的输入字节，关闭 external access，以真实 output checksum/metrics/quality/lineage 通过数据库 success authority、幂等重放和 live release gate；DuckDB Spatial 已固定预装 extension、extension-binary receipt evidence、WKB/SRID/bbox + GeoParquet 1.1 output contract 和 PostgreSQL success trigger 认证；DuckDB admission 已原子写共享 execute command，managed worker 已通过 outbox lease/ACK/redelivery 在请求外执行并对账终态 Run；S3/MinIO profile 已实现 exact-VersionId 输入、条件创建输出、exact-version 回读、数据库 storage evidence gate 与 transient 重投合同，并通过 disposable MinIO 12/12；scoped worker IAM 已通过 8/8 权限故障注入，Compose/Kubernetes optional deployment contract 和 NetworkPolicy 边界已冻结，真实 PostgreSQL + MinIO ACK-loss redelivery 已证明只对账终态 Run 并通过 live release gate；首个通用 provider reconcile receipt 已绑定 execution-plan/attempt/external reference，并验证 reconciling -> running/failed/cancelled 三种收敛与 immutable event replay；provider cancellation-timeout receipt 已绑定 execution-plan/observation/retry budget，通过既有 DataIncident 原子创建 high incident 并将 Run fail closed；provider retry/backoff 已绑定 transient observation、retry budget、immutable dispatching event 和共享 command outbox，验证 bounded backoff、到期前零 claim 与幂等重放） | 真实 Spark provider bounded rehearsal 已验证；仍缺 DuckDB/Spark/Sedona/Flink/PostGIS cross-engine spatial conformance、生产/集群 Spark provider、真实集群 NetworkPolicy enforcement 与 identity rotation、lease heartbeat、multi-replica HA/staging-production rollout、是否将成功 evidence gate 提升为生产强制策略、模型版本与 Visual/SQL/Notebook 共用 definition 的 Build 工作台、test/rollback 和 DataOps CI/CD parity |
| AR-4 Asset/GIS Service/Spatial Experience Operations | `in_progress`（GIS Service Control Plane authority、release-bound deployment registration、deployment inspect/event timeline/transition、绑定 definition/release/config/provider revision 的专用 terminal provider observation 与原子 terminal settlement、readiness-URI-bound endpoint registration、release-bound MVT 与 OGC API Features provider/Gateway/consumer/cache/policy/serving-projection 与 active-endpoint inspect/activate API、ApprovalCase-bound ServiceConsumerBinding issuance/revocation/renewal、GIS ServiceSLO exact activation binding、activation 自动 reconciliation 与 GIS ServiceSLO→DataIncident atomic authority 已落地；GIS migration-impact、全消费者 source→target 原子 cutover、Incident/ApprovalCase-bound target→source rollback 及两方向 Run-bound destination warmup gate 已通过 disposable PostgreSQL certification；Martin exact-release provider-origin 三坐标 warmup 已由 shared outbox managed worker 自动沉淀为 evidence-gated Run、221 atomic settlement 和 220 receipt，并完成真实 Martin/PostGIS 容器认证；managed receipt 的 versioned/Object-Locked S3/MinIO profile 已完成真实 `18/18` 认证，同内容重放复用 exact VersionId 且无第二对象版本；Gateway Redis MVT shared response cache 已完成真实 miss→hit→provider fallback 与撤销后 403 认证；OGC API Features adapter 已完成 11 项 contract/identity tests、synthetic disposable 5 项检查、真实 pygeoapi disposable-control 5 项检查及真实 pygeoapi + disposable PostgreSQL Gateway projection 的 active-release certification，但尚无生产 provider/生产 Gateway 证据） | Features/Tiles/MVT/COG/STAC/export 及条件 legacy OGC/3D/EDR provider、Gateway/权限/共享缓存、Gateway/Redis/CDN/GeoWebCache purge/warmup、provider build/health/migration/compensation、bucket replication/跨区 DR、通用 ABAC、发布审批、Discover/Operate/Govern、完整 Incident automation、自动 remediation、worker HA/RTO 和无 LLM 多入口通过 conformance/parity/control gate |
| AR-5 AgentOps Runtime + UX Uplift | `in_progress`（AgentOps topology、Temporal provider-neutral contracts、SDK bridge、sandbox deployment contract、deterministic task graph、execution projection、workflow-input graph binding、task-graph workflow projection、checkpoint/replay contract、显式 activity attempt schedule、SDK 单次执行门禁、真实 sandbox `start/schedule/activity/receipt/history export/replay`、真实 `already_exists`/提交后 `unknown` 的 history/input reconciliation、worker termination -> definitive timeout -> 新 attempt -> worker restart -> history replay，以及 Temporal history 与 GDA checkpoint 的 `provider_behind -> checkpoint_behind -> matched` 真实对账已完成；PostgreSQL append-only checkpoint/reconciliation authority 已通过 2 个 checkpoint、2 条 reconciliation、CAS、RLS、不可变性和独立进程恢复验证；reconciler owner/epoch lease、旧 worker 迟到写拒绝、不可变 fencing binding 和 checkpoint commit 前/后崩溃恢复已通过 14 项 disposable PostgreSQL 检查；managed reconciler 已实现 per-cycle acquire/heartbeat/fenced write/release，并通过 5 次实际 renew、`SIGKILL`、epoch 2 接管和唯一 evidence 的双进程 PostgreSQL 演练；start receipt -> reconciliation target 的 migration 242 持久登记、幂等重放、claim/renew/过期接管、unknown input-match 收敛和 stale worker 拒绝已通过当前 migration 对应的 6/6 disposable PostgreSQL 演练；live Temporal + PostgreSQL discovery 联合链路已通过 5/5 sandbox 检查；discovery worker 已补齐原子 status、frontend health readiness/liveness 和 Prometheus metrics deployment contract；ADR-333 的双进程 discovery 演练已通过 11/11，证明 target heartbeat、`SIGKILL` 后过期接管、Temporal 网络失败安全释放、恢复后唯一 reconciliation、三类 stale write fencing 和 frontend health 降级/恢复；ADR-336 的真实多 specialist TaskGraph execution 已通过 4 个 execution waves、6 个 ToolCall、7 次显式 activity schedule/completion、GWM attempt 1->2、41 个 Temporal history events 和 Replayer replay；ADR-337 step-bound HITL 已通过 pending case、提前 signal 拒绝、人工批准后恢复、10 次 activity、67 个 history events 和 Replayer replay；ADR-337 follow-up 又通过现有 ApprovalCase assignment/principal authority 的真实 scope 校验，先 assign standby 再 reassign 到绑定 team，旧 assignee 被拒绝，最终 assignment `assigned -> reassigned -> closed`、version 3；ADR-338 expiry follow-up 已通过 pending -> timeout -> cancelled、assignment `assigned -> closed`、version 2、provider dispatch withheld、22 个 history events 和 Replayer replay；ADR-340 至 ADR-355 已完成真实 MMFE/GWM specialist、provider cancellation、Temporal/Flink settlement、PostgreSQL receipt/retry-budget authority、跨进程 worker recovery 和共享 MinIO exact-VersionId 内容面 recovery；ADR-356 又完成 specialist S3/MinIO Object Lock + default retention 的启动探针与真实删除阻断演练，并保留 `production_readiness_claimed=false`；ADR-358 已完成 ApprovalCase 通知 SLA 升级 bounded slice，并保留 `production_readiness_claimed=false`） | 在支持策略执行的 CNI 环境完成 NetworkPolicy enforcement，并用实际业务 target 验证 Kubernetes lease takeover；HITL 已完成通知 SLA 升级和逐案结果批量升级 bounded slice，仍需批量审批、生产审批通知与运营闭环；再完成 staging/production identity/secret rollout、Agent bundle eval/deployment、shadow/canary、online observation、incident/rollback、HA/backup/RPO/RTO 和 uplift gate |
| AR-6 MMFE + Data for AI | `planned` | 稳定 DataProductVersion、统一 Run/Artifact 和 AgentOps ModelOps/LLMOps binding |

状态校正（2026-08-28，ADR-339）：上表 AR-5 的“下一证据”旧文字仍保留
“业务 target 的 Kubernetes lease takeover”，该项已由真实 sandbox 演练关闭。当前 AR-5
的 Flink specialist provider 也已由 ADR-349 至 ADR-351 完成 adapter、真实 provider cancel/observe
和 Temporal activity -> PostgreSQL receipt settlement 的 bounded live 认证。下一证据从
NetworkPolicy enforcement（需支持策略执行的 CNI），以及 HITL 通知/升级/批量审批运营闭环
开始；provider 权限拒绝、retry budget/worker restart、provider receipt recovery 和共享 MinIO
VersionId 内容面 recovery 的 bounded 证据已在 ADR-352 至 ADR-355 及下文记录中补齐。业务 target
takeover 和 Flink settlement 的 report/history 及 hash-bound 证据以 ADR-339、ADR-351 和下文记录为准。

**状态推进（2026-08-29，ADR-346）：provider-native cancellation adapter boundary 已落地。**
新增 `SpecialistProviderCancellationAdapter` 与 hash-bound
`SpecialistProviderCancellationObservation`，把 Temporal activity cancellation
转换为 provider 侧的 `accepted/confirmed/unknown/unsupported` 请求/观察合同。
`BoundSpecialistExecutor` 在收到取消时发出 adapter 请求；未收到 provider 终态时，
specialist receipt 仍为 cancellation-requested/`unknown`，只有 provider 明确
`confirmed` 才能收敛为 terminal `cancelled`，重放不会重新执行 side effect。契约测试
覆盖 accepted/confirmed/unsupported、身份绑定、请求幂等、取消后 unknown 和确认后
重放收敛；Ruff、compileall 和 focused provider/authority suites 通过。这关闭了“没有
provider-native cancellation 接口”的架构边界小步，但不关闭真实 provider cancellation：
当前 MMFE/GWM 仍使用显式 `unsupported` adapter。下一步是为至少一个真实长任务 provider
实现 cancel/observe API，并在 Temporal + PostgreSQL history observer 中验证超时、取消
请求、provider 终态和权限/重试预算；MinIO/Iceberg/PostGIS conformance、NetworkPolicy、
HA/DR、身份轮换和生产 rollout 仍未完成。

**状态推进（2026-08-29，ADR-347）：Temporal workflow cancellation transport 已完成真实
sandbox 认证。** `TemporalWorkflowAdapter.cancel/cancel_async` 通过 SDK bridge 调用原生
workflow `cancel` API，并返回 hash-bound `TemporalProviderCancellationResult`；真实
Temporal `1.29.7` 演练中，start RPC 返回 `unknown` 但 history 找到同一 started workflow，
随后 cancel 返回 `accepted`，3-event history 出现
`EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED`。报告为
`docs/reports/agentops_temporal_workflow_cancel_transport_2026-08-29.json`，
`report_sha256=786ba3348c88d10ee2f769a0c0217f7dea7b50169f190cd9e096769e91393d05`，
history 文件 SHA-256 为
`2b79f6a82a09b9e25d71fada4a56286d13d7f4afe58075faadb82c94a4221869`。该证据只认证
Temporal cancel transport/history，不认证 provider operation cancellation；报告明确
`provider_operation_cancellation_claimed=false`、`production_readiness_claimed=false`。

状态校正（2026-08-28，ADR-340）：上表 AR-5 的“真实 specialist provider”旧文字已由
bounded MMFE/GWM provider slice 关闭；其后续的 PostgreSQL Artifact authority bounded 集成
演练也已完成：3 个输入 Artifact 先登记到临时 PostgreSQL，MMFE/GWM 真实 Temporal activity
按 UUID 读取，2 个输出 Artifact 再登记回 PostgreSQL，authority lookup、checksum、manifest、
41-event history 和 replay 均通过。当前仍需接入 MinIO/Iceberg/PostGIS 目标 provider，完成
provider cancellation/unknown 对账与跨引擎 conformance；该 bounded slice 的 Temporal
report/history、临时 filesystem content backend 和 `production_readiness_claimed=false` 限制
以 ADR-340 和上文记录为准。

ADR-340 后续 authority 证据（2026-08-28）：
`docs/reports/agentops_temporal_postgres_artifact_authority_2026-08-28.json` 的文件 SHA-256 为
`7d2830c4d635ca009aad87619e7cc8a544647a2ffd3231ba197b8ec40ed36a0e`，报告内
`report_sha256=f72440316dcdfd7777a31103acbd57e6f45ae7459ffbdabde70821a6d487d396`；对应
Temporal history 文件 SHA-256 为
`6202e5503e93d9f4e8a9ab92ccee9552d5086fc0d221b316407e661044ae15bf`。该证据只关闭
“PostgreSQL Artifact authority bounded adapter”这一小步，不关闭 MinIO/Iceberg/PostGIS
生产 provider、provider cancellation/unknown 对账或跨引擎 conformance。

同日补充的 MinIO/S3 bounded authority 证据：临时 bucket 开启 versioning，3 个输入和 2 个
输出对象各只有 1 个版本，输出 manifest 均绑定 VersionId，`authority_lookup_verified`、
`output_version_ids_bound`、`each_object_single_version` 均为 true。报告文件 SHA-256 为
`e70566ca02da49e9cbbb5bb84573e1664515c7653e461b031cfcb6dc2897904a`，报告内
`report_sha256=344c69a3d91f38ce59456f92a49820aac46c03bd0ca3b6b38b1acfdbc1735b28`；history
文件 SHA-256 为 `3a8893457e1a61a0491a892f53558861013aecf30ed16c54c5aeebf588dcca84`。本次另有
`authority_output_replay_count=2`，证明 authority-level replay 未新增对象版本。这只关闭
MinIO/S3 content backend 的 bounded 适配证据，不关闭对象锁/跨区复制、生产身份轮换、provider
cancellation/unknown 对账或跨引擎 conformance。

同日新增 provider cancellation/unknown reconciliation bounded slice：`BoundSpecialistExecutor`
现在为每个 provider operation 登记独立、hash-bound 的 operation receipt；provider 已提交但
activity 响应丢失时返回 `UNKNOWN`，不自动重试、不伪造 output Artifact 或成功 evidence。对账器
先观察 operation receipt，再通过同一 Artifact store 校验 deterministic output UUID、request hash、
输入 lineage、media type 和内容 checksum；全部匹配才收敛为 `matched_succeeded`，provider 明确
失败/取消才收敛为 `definitive_failed`，其余保持 `unknown_pending`。副作用 activity 的未知状态
引用 Artifact `EVIDENCE` 角色的 operation receipt；unknown 与后续 settlement 使用不同 evidence
idempotency key，避免把合法收敛误判为重复写入。

契约回归 `40 passed`，新增脚本
`scripts/rehearse_agentops_specialist_unknown_reconciliation.py` 完成真实 MMFE `spatial_join`
提交后失联、receipt+output 对账成功，以及 GWM 取消/超时无输出保持 pending；报告见
`docs/reports/agentops_specialist_unknown_reconciliation_2026-08-28.json`，文件 SHA-256 为
`cf6c5e0e989be805e4b713a6af6b3ab9a485b53cd725a48663d90dd1f2a281d6`，报告内
`report_sha256=a9f9516ac8e371814f15c2b8d30844e68a4ad914cdadcab57964cb33211736e4`。
该证据仍是 bounded local Temporal-contract rehearsal，不代表 Temporal server、PostgreSQL/
MinIO receipt authority、provider cancellation API、跨进程 reconciler、HA/DR 或 production
readiness 已完成；下一步是把相同 receipt/observation 合同接入真实 PostgreSQL authority 和
Temporal history/worker cancellation 观测，再做跨 provider conformance。

2026-08-28 Temporal workflow provider-bound failure boundary（ADR-343）：修正
`agentops_temporal_task_graph_runtime._execute_schedule` 的异常投影。带
`provider_spec` 的 MMFE/GWM activity 在 Temporal timeout、cancel、transport loss 或未被
Temporal 接收的 activity failure 后，不再直接写 `FAILED`；运行时生成带确定性
`provider_operation_ref=<operation_ref>://<activity_id>` 与
`provider_receipt_ref=provider://specialist/<activity_id>/<attempt_no>` 的 `UNKNOWN`
结果，停止当前 wave，交由 specialist receipt/history reconciler 做只读对账。无 provider
binding 的普通 activity 仍保留 `FAILED` 语义。新增 runtime contract tests 覆盖 timeout、
cancellation、generic activity failure 和 unbound regression；专项回归 `19 passed`，Ruff/
compileall 待本轮统一执行。该项只关闭 workflow-side misclassification gap，不代表真实
Temporal server、PostgreSQL receipt authority、provider-native cancellation、HA/DR 或
production readiness 已完成。

AR-2 的 `Flink/Iceberg kill/network uncertainty` 缺口现已拆分：ADR-254 已放行“终态
checkpoint 后的 provider SIGKILL 或 Docker 网络断开 + 独立 snapshot reconciliation”这一
bounded slice；roadmap 仍保留生产 HA/restart、自动 fencing、Kubernetes recovery、任意时序
网络分区、跨区域 RPO/RTO 和跨系统 exactly-once 作为未完成退出门。这样 `verified` 只覆盖报告
实际证明的故障边界，不把 disposable runtime 的结果扩展成生产承诺。
同样，ADR-255 只关闭单文件、单并行度 stale position-delete/MOR validation 和失败 artifact
清理；ADR-256 只关闭当前版本矩阵下单键、单 source row、`WHEN MATCHED THEN UPDATE` 的
  bounded SQL MERGE；ADR-257 只关闭单行 SQL UPDATE snapshot guard/stale fail-closed；ADR-258
  进一步关闭两个目标、简单 `IN` 谓词的多行 SQL UPDATE 整体 fail-closed 和 fresh retry；ADR-259
  关闭单 target row、两条重复 source row 的 MERGE cardinality fail-closed 和显式去重 retry；ADR-260
  进一步关闭单 target row、单 insert row 的 matched-update + not-matched-insert 多分支单次 snapshot；ADR-261
  再关闭单 target row、单 source row 的 matched-delete 单次 snapshot；ADR-262 进一步关闭两个不同
  target row 的单次 matched-update；ADR-263 再关闭一个条件 matched-delete 加一个默认
  matched-update branch；ADR-264 再关闭两个均未匹配 target 的条件/默认 not-matched insert branch；
  ADR-265 再关闭 matched-delete、matched-update 与两个 not-matched insert 的四分支组合；ADR-266
  再关闭同 worker 内 cardinality rejection 后的 fresh-state retry 编排；ADR-267 再关闭单表
  `AND/OR/IN` 复杂谓词匹配及 guard row fail-closed；ADR-268 再关闭两个 target 的单表
  `AND/OR/IN` SQL UPDATE guard/fresh retry 及 guard row fail-closed；ADR-269 再关闭单表显式 rank
  自动去重选择及未选 token fail-closed；ADR-270 再关闭提交前 retry budget admission、超预算停止和
  catalog/row-set fail-closed。SQL UPDATE 相关子查询/join/跨分区语义、
  跨 target survivorship、更多 branch、分区/多文件
  destructive write 和生产 writer recovery
仍未完成。
| AR-7 GWM Enhancement | `planned` | 可信 GWMObservationProjection |
| AR-8 Scale/High-throughput Realtime/Federation/Ecosystem | `planned, conditional` | 真实容量/SLO/freshness/互操作触发证据 |

AR-2 mutation evidence correction（2026-08-25）：ADR-279 已将“单表、单 target、单次 Spark SQL MERGE 的 provider abort recovery”移入已验证证据；ADR-280 已将“单表、两个 target、WHERE 相关 `EXISTS` scope subquery 的 Spark SQL UPDATE”移入已验证证据；ADR-281 已将 SET 表达式相关 scalar subquery 纳入真实 capability probe，但结果为 `unsupported_fail_closed`，不计入已支持能力。剩余缺口仍包括生产 HA/自动恢复/fencing/RPO/RTO、UPDATE JOIN、多表、SET scalar subquery provider support、多文件 destructive write、跨 target survivorship、字段级业务合并和混合分支并发冲突；不得把这些 disposable slice 外推为生产 writer recovery。

AR-2 mixed-spec equality-delete correction（2026-08-25）：ADR-284 的真实 capability probe 已证明当前 JDBC Catalog + Spark/Flink provider 可以物化 `equality_ids=[1]` 的 equality-delete files，并删除 evolved spec 行，但 legacy spec 0 的同一 logical key 仍存活；该结果标记为 `unsupported`，不计入跨 partition spec destructive write 能力。`build_iceberg_equality_delete_admission` 已在真实 `data_spec_ids=[0,1]` 上返回 `rejected`，后续 admission 必须要求单一 current spec 或先完成受控 rewrite/compaction，不能把 ADR-117 的单 spec equality-delete interoperability 外推到混合 spec 表。

AR-2 controlled-rewrite correction（2026-08-25）：ADR-285 的真实切片证明，Spark `INSERT OVERWRITE` 不能作为混合 spec 全量 rewrite 证据；显式“源行物化 -> 全量 DELETE -> current-spec append”后，活动 data files 只剩 spec 1，admission 从 `rejected` 变为 `admitted`，Flink equality-delete 删除两代目标行。该路径仍是单表、单并行度、一次 evolution 的 bounded provider evidence，不代表自动 compaction、并发 rewrite recovery 或生产 HA。

AR-2 multi-file position-delete correction（2026-08-25）：ADR-286 将原先单文件单行 position-delete writer 扩展为两个不同 data file 的单 RowDelta、两条物理 position 记录，并由 Spark 独立对账。该证据不外推到分区表、更多文件、并发 position/MOR writer 或自动 retry。

AR-2 multi-file position-delete conflict correction（2026-08-25）：ADR-287 在 ADR-286 的两个 data file
切片上增加旧 snapshot stale writer。真实 Iceberg validation 整体拒绝 RowDelta，catalog snapshot 与
metadata location 不变，未提交 delete file 清理通过；该证据只覆盖两个文件、单并行度、显式 bounded
冲突探针，不等于自动重试、并发恢复或生产 HA。

AR-3 Spark provider correction（2026-08-25）：ADR-288 将“Spark provider 仍无真实证据”修正为已完成 disposable bounded rehearsal。真实报告证明 445 feature/439 parcel rebuild、authority-gap receipt replay、幂等 mutation、stale predecessor、checkpoint 和 delete 对账均通过；生产 Spark 集群、长任务恢复、HA、SLO 和跨引擎空间 conformance 仍是未完成退出门。

2026-08-28 AgentOps specialist operation receipt PostgreSQL authority（ADR-342）：新增 migration 246 与 `PostgresSpecialistOperationAuthority`，把 MMFE/GWM provider operation receipt 从内存合同推进为租户隔离、append-only、hash-bound 的 PostgreSQL authority。`operation_ref` 作为一次 provider side effect 的唯一身份；首条 receipt 必须为 `submitted`，`submitted/unknown` 只能按允许状态机收敛到 `succeeded/failed/cancelled`，终态不可被旧 worker 覆盖；成功 receipt 外键绑定现有 output Artifact。executor 仍通过 dependency injection 使用 authority，不把数据库访问混进 provider handler。该实现已通过 migration 静态契约、repository 负向、tamper rejection 及 6/6 disposable PostgreSQL authority-boundary rehearsal；详见下方状态校正和 ADR-342。当前不能宣称 Temporal cancellation/history end-to-end、HA/DR、provider-native cancellation 或 production readiness。

同一切片新增 `reconcile_specialist_activity_history`：Temporal 的 timeout/cancel/failure observation
先生成未知结果 envelope，再读取 specialist operation receipt 与 output Artifact；receipt 未到终态时
输出 `unknown_pending`，不产生失败 evidence，不触发第二次 provider submission。该入口已用 GWM
timeout + pending receipt 合同回归验证；receipt authority 同时区分“请求取消后的 unknown”和
provider 明确确认后的 terminal `cancelled`。仍未接入真实 Temporal server history/cancellation API。

2026-08-28 Temporal specialist receipt authority integration（ADR-344）：真实 specialist
rehearsal 现在可注入 `PostgresSpecialistOperationAuthority`；PostgreSQL wrapper 在 worker 启动前
启用 migration 246，并在临时 workspace 清理前用新 executor 实例重放每个 MMFE/GWM 请求。重放只
读取已提交的 terminal receipt，返回同一 output Artifact，且 history cardinality 不增加；报告同时
记录 receipt-to-activity correlation、terminal success CAS、backend 和 replay 结果。原先在
workspace 清理后进行 Artifact replay 的失效检查已移入 rehearsal 生命周期内。该实现已通过
specialist/provider `16 passed, 1 skipped`、Ruff、compileall，以及真实 Temporal + PostgreSQL
bounded rehearsal；报告/hash 见 `agentops_temporal_postgres_artifact_authority_2026-08-28.json`。
该证据不代表 Temporal cancellation/history end-to-end、provider-native cancellation、
MinIO/Iceberg/PostGIS provider conformance、HA/DR 或 production readiness 已完成。

2026-08-28 Managed reconciler specialist wiring follow-up（ADR-344）：显式 workflow worker 与
`--discover` worker 现在共用 `_build_specialist_runtime_dependencies`，启动时装配
`PostgresArtifactAuthoritySpecialistStore`、`PostgresSpecialistOperationAuthority`、checkpoint
authority 和 start-target authority。运行配置必须明确选择 `filesystem`（仅 disposable/local）或
`s3`/`minio` 内容后端；S3/MinIO 强制 `VersionId`，并要求绝对 materialization root。启动前执行只读
receipt 表和 Artifact 表探针，缺少 `DATABASE_URL`、migration 246、gateway role、boto3、bucket
或路径配置会直接 fail closed，不会等到 provider-bound activity 才发现依赖缺失。discovery 为每个
target 复用同一组 authority，避免 child reconciler 回退到默认/内存依赖。新增取消终态、submitted
pending、成功 receipt 与 Artifact 不匹配、运行时 wiring 配置回归；本轮 focused suite `37 passed`，
Ruff/compileall 通过。代码装配已由真实 Temporal + PostgreSQL bounded worker rehearsal 补齐；
仍不代表 provider-native cancellation、跨 provider conformance、HA/DR 或 production readiness
已完成。下一步是接入 provider-native cancellation、Temporal history observer，再验证
MinIO/Iceberg/PostGIS provider 和跨进程 history/cancellation 对账。

2026-08-28 Managed reconciler deployment contract follow-up：发现 discovery Deployment 在
代码切换为“显式 Artifact backend + migration 246”后仍缺少对应运行配置，启用副本会在启动阶段
因缺少 backend/root 环境变量而 fail closed。已补齐 optional sandbox 的显式 filesystem backend、
绝对 content/materialization 路径和独立 `emptyDir` 挂载，并将 preflight 的硬检查扩展到 backend
和两个路径；README 同步标明该配置只用于无执行 worker 的 disposable sandbox，不能充当共享生产
Artifact content plane，生产 overlay 必须改为带 VersionId 的共享 S3/MinIO 后端。preflight 的
必需 migration 集合同时纳入 246，避免旧的 242/242 status report 被误当作 specialist authority
已部署。随后在当前 sandbox 对双副本 discovery 执行了只读 live preflight：2/2 ready、generation
收敛、不可变 image、filesystem backend 和两个 mount 均通过；仍未宣称生产 HA/DR 或共享生产
Artifact content plane。

2026-08-28 Managed reconciler preflight hardening：preflight 现在把 discovery 镜像固定为
不可变 `@sha256:<64 hex>`，校验 filesystem/S3/MinIO backend 与实际可写 volume mount 的覆盖
关系，并在 `--expect-deployed` 模式读取 live ConfigMap 和 Deployment status，要求
`observedGeneration`、ready、available、updated 副本全部收敛。新增 S3 缺 bucket、关闭
VersionId、mutable image、rollout 未收敛和 ConfigMap 漂移的负向测试；相关回归 `12 passed`，
Ruff、compileall 和 Kustomize render 通过。该项只增强部署前/部署后 fail-closed 检查，不产生
新的 Kubernetes runtime 证据；历史 242/242 acceptance report 仍不能用于当前要求 migration
246 的 specialist worker，必须在真实环境重新迁移、preflight 和 rehearsal 后再更新报告。

**状态校正（2026-08-28，ADR-342/344）：PostgreSQL specialist receipt authority 已完成
bounded runtime 验证。** Temporal + PostgreSQL specialist bounded rehearsal 中，真实
MMFE/GWM specialist 共完成 6 次 activity schedule/completion，生成 2 条 PostgreSQL durable
receipt，导出 41 个 Temporal history event，并通过 history replay。新 executor 实例重放两个
provider 请求均返回同一 output Artifact，未产生第二次提交；对应报告为
`docs/reports/agentops_temporal_postgres_artifact_authority_2026-08-28.json`，其
`report_sha256=8e31a0e8e31721be0400bd162f06fe15bca12713f57441e1ee793ac102458e46`。

随后以镜像 `gis-data-agent:agentops-specialist-20260828-v9`（manifest digest
`sha256:6b0106dc8ac9264f994012c4595af045eec862e01c881a548fc8044de099bf22`）运行独立
authority boundary rehearsal，6/6 检查也已通过：submit replay 幂等、repository
restart 恢复、terminal success CAS、stale failure 拒绝、取消但 provider 未确认时保持
`unknown`、跨租户 RLS 隔离。报告为
`docs/reports/agentops_specialist_operation_authority_postgres_2026-08-28.json`，其
`report_sha256=5ef38ebb9b6cf838d7fd776b2ec704e6fdf187fc8a1a37254eb10442c211f466`。
这两份报告均明确 `production_readiness_claimed=false`。因此 AR-5 当前已关闭
“PostgreSQL receipt authority bounded integration”小步；随后 ADR-345 已关闭真实
Temporal timeout/history observer bounded 小步。此处仍未关闭 provider-native
cancellation、MinIO/Iceberg/PostGIS provider conformance、NetworkPolicy enforcement、
HA/DR、身份轮换和生产晋级；下一步按这些退出门推进，不再重复执行已通过的 bounded
receipt slice。

同日 live discovery preflight 只读检查也已通过：sandbox namespace、Secret keys、PostgreSQL
NetworkPolicy、Deployment 2/2 ready、`observedGeneration=25`、不可变 discovery image
`gis-data-agent@sha256:0d09d950ee02bbe5e55058bbd8c116cf8dc00b1fad4fcb6172ee89d57221c3cb`、
filesystem specialist backend 及 content/materialization mount 全部匹配。将期望 image digest
或 backend 改为错误值时，`cluster.discovery_image` 和
`cluster.specialist_content_config_binding` 均为 `block`，证明 live 漂移检查是 fail-closed
的；这些检查只读集群状态，没有修改 Deployment 或 ConfigMap。

**状态推进（2026-08-29，ADR-346）：provider-native cancellation adapter boundary 已落地。**
新增 `SpecialistProviderCancellationAdapter` 与 hash-bound
`SpecialistProviderCancellationObservation`，把 Temporal activity cancellation
转换为 provider 侧的 `accepted/confirmed/unknown/unsupported` 请求/观察合同。
`BoundSpecialistExecutor` 在收到取消时发出 adapter 请求；未收到 provider 终态时，
PostgreSQL specialist receipt 仍为 cancellation-requested/`unknown`，只有 provider
明确 `confirmed` 才能收敛为 terminal `cancelled`，重放不会重新执行 side effect。
契约测试覆盖 accepted/confirmed/unsupported、身份绑定、请求幂等、取消后 unknown
和确认后重放收敛；Ruff、compileall 和 focused provider/authority suites 通过。
这关闭了“没有 provider-native cancellation 接口”的架构边界小步，但不关闭真实
provider cancellation：当前 MMFE/GWM 仍使用显式 `unsupported` adapter。下一步是为
至少一个真实长任务 provider 实现 cancel/observe API，并在 Temporal + PostgreSQL
history observer 中验证超时、取消请求、provider 终态和权限/重试预算；MinIO/Iceberg/
PostGIS conformance、NetworkPolicy、HA/DR、身份轮换和生产 rollout 仍未完成。

**状态推进（2026-08-29，ADR-347）：Temporal workflow cancellation transport 已接入。**
`TemporalWorkflowAdapter` 与 SDK bridge 现在提供 typed `cancel/cancel_async`，通过
绑定 namespace、tenant、workflow identity 调用 Temporal 原生 workflow cancel，并返回
hash-bound `TemporalProviderCancellationResult`（`accepted` 或 `unknown`、reason、receipt）。
RPC 失败保持 `unknown`，不会被投影成业务终态；专项 Temporal/provider 回归 `23 passed`，
Ruff 与 compileall 通过。该项只关闭 Temporal cancel 的传输边界，不代表 MMFE/GWM 或
其他计算 provider 已经停止：仍需真实 provider 的 cancel/observe、provider 终态 receipt、
live Temporal history observer、权限与重试预算验证后，才能关闭 provider-native
cancellation 退出门。

**状态推进（2026-08-29，ADR-348）：Flink/Iceberg 物理 kill 证据已刷新（不新增退出门）。**
真实重庆 OSM source slice 在 pinned Flink `1.19.3`、Iceberg runtime `1.7.2`、临时
JDBC catalog、MinIO 和 PostgreSQL authority 上完成了终态 source checkpoint 后的
`SIGKILL` 注入。15 项检查全部通过：取消未推进控制面、独立 snapshot reconciliation
精确收敛、重试复用已提交 commit 且没有第二个 snapshot，临时 catalog/container/object
prefix/authority 清理完整。报告为
`docs/reports/chongqing_osm_flink_iceberg_kill_uncertainty_2026-08-29.json`，文件
SHA-256 为 `52092866728798cc29a839fc4def85ab375bbd19c9f5a632bf7bb6aac1c27e4e`。
该报告是 ADR-254 既有 disposable `Flink/Iceberg kill` 小步的当前环境重认证，
不新增或扩大 AR-2 退出门；自动 Flink HA、Kubernetes fencing、任意网络分区、跨区
RPO/RTO、生产吞吐和 AgentOps provider-native cancel/observe 仍未完成。

**状态推进（2026-08-29，ADR-349）：Flink provider cancellation adapter contract 已完成。**
新增 `FlinkProviderCancellationAdapter`，将 Flink REST 原生
`PATCH /jobs/{job_id}?mode=cancel` 和 `GET /jobs/{job_id}` 接入统一的
`SpecialistProviderCancellationAdapter`。provider、operation、32 位 job identity 和
`flink://job/<job_id>` receipt 绑定均强制校验；HTTP `202` 只产生 `accepted`，只有
provider 返回 `state=CANCELED` 才产生 `confirmed`，超时、404、非 2xx、畸形响应和非终态
保持 `unknown`。7 个正负向契约/集成测试通过，Ruff/compileall 通过；provider receipt
派生已同步接入 specialist executor、Temporal unknown envelope 和 history reconciler，
Flink 使用 job-bound receipt，MMFE/GWM 保持旧 generic receipt。该切片只完成真实 provider
适配器实现和 fail-closed 合同，不声称 live Flink activity、Temporal→Flink 跨进程对账或
生产就绪；下一步是用真实长任务把 adapter、Temporal history、PostgreSQL receipt authority、
权限和 retry budget 串成一份端到端证据。

**状态推进（2026-08-29，ADR-350）：真实 Flink provider cancellation bounded integration 已完成。**
现有 Flink/Iceberg reconciliation certification 现在发布临时 Flink REST 端口，并对真实
Flink `1.19.3` 长任务调用 `FlinkProviderCancellationAdapter`。本轮 `ack-loss` 认证中，
REST `PATCH /jobs/<job_id>?mode=cancel` 后由 `GET /jobs/<job_id>` 观察到
`state=CANCELED`，生成 `confirmed` 的 job-bound receipt；原有 14 项顶层检查和嵌套取消
检查全部通过，Iceberg 基线未被取消推进，独立 snapshot reconciliation、无重复 retry
和临时资源清理均通过。报告为
`docs/reports/chongqing_osm_flink_iceberg_agentops_cancel_2026-08-29.json`，文件
SHA-256 为 `584c04907ccb05f155c8752f93703054eeb8b2896bb127b75769a8ca8aa01542`。
这关闭 AR-5 的 bounded “真实 Flink provider cancel/observe transport”小步；认证进程
尚非 Temporal worker，因此 Temporal history、跨进程 PostgreSQL receipt settlement、
worker restart retry budget、NetworkPolicy、HA/fencing 和生产 RPO/RTO 仍未完成。

**状态推进（2026-08-29，ADR-351）：Temporal activity -> Flink provider settlement bounded live 认证已完成。**
新增 `TemporalProviderCancellationProbeExecutor` 和
`scripts/rehearse_agentops_temporal_flink_cancellation.py`。前者在 Temporal
activity 取消到达后调用注入的 provider cancellation adapter，并把
`accepted/unknown` 与 `confirmed` 分别写入 specialist operation receipt authority；
后者把真实 Temporal worker、Flink REST adapter、PostgreSQL receipt authority、Temporal
history observer、specialist history reconciler 和 history replay 串成一条可执行演练路径。
Flink operation identity 固定为 `flink://job/<job_id>`，activity replay 不重复提交。
live 演练先暴露并关闭两个运行时缺口：长 activity 只有启动 heartbeat 会在取消交付前变成
heartbeat timeout；Flink `PATCH` accepted 后如果不继续观察 provider，也无法把 receipt 提升为
terminal cancelled。当前 activity 在完整执行期持续 heartbeat，executor 在有界窗口内执行
`accepted -> confirmed` 观察；超时仍保持 `UNKNOWN + cancellation_requested`。
本轮在 Temporal Server `1.29.7`、Python SDK `1.32.0`、PostgreSQL `16.14` 和 Flink `1.19.3`
上完成真实长任务认证：Temporal activity=`cancelled`，Flink job=`CANCELED`，PostgreSQL
receipt=`cancelled/FlinkJobCancelled`，specialist reconciliation=`definitive_failed`，16 个 history
events 可 replay，7/7 检查通过。报告为
`docs/reports/agentops_temporal_flink_cancellation_2026-08-29.json`，文件 SHA-256
`4e01721abaa6d4cfb4fb442996532cc8e518478bc189ba64ca3269c25529121b`；history 文件 SHA-256
`c66e06ab1cc8613d9648ad8c5a8594703bf306fa022b8f0e5dd1b19e49eaeb0b`。聚焦回归 `15 passed`，
Ruff/compileall 通过。该证据关闭 bounded live worker cancellation settlement，不声称生产 worker
deployment、provider 权限拒绝、retry budget/worker restart、NetworkPolicy、HA/fencing、备份恢复、
身份轮换或生产 rollout 已完成。

**状态推进（2026-08-29，ADR-352）：provider cancellation 权限拒绝可诊断链路已完成。**
Flink cancellation adapter 不再把 401/403、网络不可达、job 不存在、provider 拒绝、畸形响应和
非取消状态压成同一个无原因 `UNKNOWN`；新的 `uncertainty_type` 贯穿 provider observation、
specialist operation receipt/observation 和 PostgreSQL authority。migration 247 将该字段作为从
immutable receipt document 派生的 generated/indexed column，并限制其只能出现在 `unknown`
receipt；字段为空时继续使用 migration 246 的原 fingerprint payload，既有回执 hash 不失效。
disposable PostgreSQL 16 的 246→247 演练通过 7/7，包含跨实例恢复、append-only/CAS、RLS 和
`FlinkCancellationPermissionDenied` 持久读取；报告文件 SHA-256 为
`aed5771ee411808c4237e6f60b8e6947bb8da9fe661d9a2e4627dc98af3b6764`。live 负向演练用策略
代理透传真实 Flink GET、只拒绝 PATCH cancellation：Temporal activity=`cancelled` 时 Flink job
仍为 `RUNNING`，PostgreSQL receipt=`unknown + cancellation_requested +
FlinkCancellationPermissionDenied`，specialist reconciliation=`unknown_pending`，18 个 Temporal
history events replay 通过，8/8 检查通过；随后绕过代理将 disposable Flink job 清理到
`CANCELED`。报告文件 SHA-256 为
`740a58aabeebbeca4de86e8d14d90101a505f8774c892fe4a5d5e3ab25dd8f94`，history 文件 SHA-256 为
`d9c616465a3bdeae60b23ac05285648921d344b976e64cfeabf01cf247edce10`。该切片关闭权限拒绝的
durable diagnosis，不声称生产 identity/permission rollout、按原因自动告警/补救、worker
restart/retry budget、NetworkPolicy、HA/fencing、备份恢复或生产 RPO/RTO 已完成。

**状态推进（2026-08-29，ADR-353）：provider 权限恢复后的 managed reconciliation 收敛已接入。**
权限拒绝演练现在继续执行一次后续 reconciliation 周期：首个 Temporal cancellation 仍产生
`unknown + cancellation_requested + FlinkCancellationPermissionDenied`，Flink 作业保持
`RUNNING`；恢复 provider 观察/取消权限后，reconciler 通过原 job-bound receipt 观察到
`CANCELED`，在 PostgreSQL authority 上追加唯一的 terminal `cancelled` receipt，并把
specialist reconciliation 收敛为 `definitive_failed`。整个过程不重新提交 Flink 作业，Temporal
history 仍可 replay。报告
`docs/reports/agentops_temporal_flink_cancellation_permission_denied_2026-08-29.json` 已包含
恢复前后两组证据；报告文件 SHA-256 为
`a6d707f99646b4089dd72f6e94770a14bc8c90211bdb407073750d5162e1d505`，history 文件 SHA-256 为
`e7fe8bc24d7a9424fde3c8735b684119ca62f195f94731a2504282cead7bfda6`。这只关闭 bounded
permission-recovery convergence 小步，不声称生产 worker restart/retry-budget、自动告警/补救、
NetworkPolicy、HA/DR、备份恢复或 RPO/RTO。

**状态重认证（2026-08-29，ADR-327）：worker termination/restart bounded slice 已再次通过。**
使用两个独立 worker 进程连接同一 `gda-agentops-sandbox`，第一 worker 在真实
`ACTIVITY_TASK_STARTED` 后 `SIGKILL`（exit `-9`），Temporal 记录唯一的
`TIMEOUT_TYPE_START_TO_CLOSE`；第二 worker 只执行 workflow 显式安排的 attempt 2（复用同一
ToolCall 幂等键，使用新的 activity/request/schedule hash），最终 19 个 history event，replay
通过，第二 worker 正常完成后退出 `-15`。报告中的 `report_sha256` 为
`b8ae8f1763d95b688b219e5bdacc98e9589955101bcee284ba97debab08df3a7`，报告文件 SHA-256 为
`b3211226b7fb0d1ab62305bc468fa626142b4f000af0482d88cadb742661ee64`，history 文件 SHA-256 为
`d308cfa1bdc493cb730705f6114782a5c89618131d9fea9a44b6dc2851bb7029`。这只是重认证已有
explicit attempt recovery，不关闭 provider receipt recovery、跨 worker retry budget、生产
worker image、HA/DR 或 RPO/RTO。

**状态推进（2026-08-29，ADR-354）：provider commit 后的跨进程 worker recovery 已完成
bounded 认证。** 新增 PostgreSQL specialist retry-budget authority（migration 248），以
`provider_ref://run_id/tool_call_id` 作为跨 worker 共享的 operation family；同一
`request_sha256 + attempt_no` 重放只返回既有 admission，只有显式新 attempt 才消费预算，
authority 不可用和预算耗尽均在 provider side effect 前 fail closed。真实 recovery 演练中，
worker A 通过 PostgreSQL Artifact authority 执行 GWM provider 并提交 terminal receipt 后被
`SIGKILL`（exit `-9`），activity 结果为 `unknown`；worker B 以全新的 receipt、retry-budget 和
Artifact-store 实例恢复同一请求，返回原 output Artifact，没有再次执行 provider。4/4 检查
通过：receipt history 保持 `submitted + succeeded` 两条，内容面只有一个 output，retry budget
保持 1 次 attempt、1 次 admission。报告为
`docs/reports/agentops_specialist_worker_recovery_2026-08-29.json`，内部
`report_sha256=6c0565388c4e5e54d47bdad3fcb67820c8cd85dff2601b414d97992c080d77c1`，
文件 SHA-256 为 `6ddbf0250cc9036ef7ee65e5ff91a7024f860427b7f998c7be354a0a24b2cb3b`。
独立 retry-budget PostgreSQL 演练同时通过 3/3，内部
`report_sha256=97dc0f256903b833b1523de28a3053833cd7004260a01bd8e856140ded37122f`。
这关闭 ADR-327 明确保留的“provider receipt recovery + 跨 worker retry budget” bounded 小步，
但不把 AR-5 标为 `verified`：共享生产 S3/MinIO VersionId/object-lock、Kubernetes worker HA/
fencing、NetworkPolicy、备份/RPO/RTO、身份轮换和 staging/production rollout 仍是退出门。

**状态推进（2026-08-30，ADR-355）：共享 MinIO VersionId 内容面上的跨进程 recovery 已完成
bounded 认证。** 在 ADR-354 的 PostgreSQL receipt/retry-budget 恢复演练上，将内容面切换为
本地 MinIO versioned bucket：输入和输出 Artifact manifest 均绑定精确 `VersionId`，replacement
worker 读取既有 VersionId，不读取 bucket latest，也不执行第二次 PUT。worker A 在真实 GWM
provider commit 后返回 `unknown` 并被 `SIGKILL`；worker B 用全新 authority/store 实例恢复同一
terminal receipt 和 output。6/6 检查通过：provider 未重执行、receipt history 仍为两条、output
对象仍只有一个版本、retry budget 仍为 1 次 attempt/1 次 admission、临时对象版本和 bucket
清理完成。报告为
`docs/reports/agentops_specialist_worker_recovery_minio_2026-08-30.json`，内部
`report_sha256=cad97bd8b319e1ad1f6fb1df918ce067cd9f54078d1a603798f57b0f08f90ecd`，
文件 SHA-256 为 `90a2ff83f43f621486dc7c97d230d32e3efd6c168a8188e76a2ff5cd26e5a145`。
新增的精确 VersionId 跨实例回归和 specialist suite 通过；该证据关闭 AR-5 的“共享 MinIO
内容面 worker recovery” bounded 小步，但不关闭 Object Lock/跨区复制、生产身份轮换、
Kubernetes worker HA/fencing、Temporal HA、备份/RPO/RTO、NetworkPolicy 或生产 rollout。

**状态推进（2026-08-30，ADR-356）：specialist S3/MinIO Object Lock + retention enforcement 已完成 bounded 认证。**
`S3ArtifactContentBackend` 新增只读 `probe()`，在 live specialist reconciler 启动时强制检查
bucket versioning、Object Lock 和正数默认 `GOVERNANCE/COMPLIANCE` retention；显式关闭该合同会在
Temporal polling 前 fail closed。真实 disposable MinIO bucket 以 Object Lock + 一天 Governance
retention 创建，使用专用 writer 完成 probe、精确 VersionId 写入/读回和 retention 查询；root 身份对
该精确版本的删除被 Object Lock 拒绝，对象仍可按 VersionId 读取，scoped writer 的 retention bypass
也被拒绝。9/9 检查通过，临时 bucket、全部 object versions 和容器已清理。报告为
`docs/reports/agentops_specialist_s3_object_lock_2026-08-30.json`，内部
`report_sha256=fb5b3d74b6044a67281af86b5cd700cb40cddcdf3f5082ccb9bc5c6813399aed`，文件 SHA-256 为
`08ac61734fb02052694359b3b4f697d8df60856c3fe1256f84b7b888f349f21e`。这关闭 AR-5 的 specialist
Object Lock/retention bounded 小步，不关闭跨区复制、VersionId remap、生产身份轮换、Kubernetes
worker HA/fencing、Temporal HA、备份/RPO/RTO、NetworkPolicy 或生产 rollout。

**状态推进（2026-08-30，ADR-357）：NetworkPolicy enforcement certification harness 已落地，但当前环境明确阻断。**
新增 `scripts/certify_agentops_networkpolicy_enforcement.py`：先读取集群 Pod/DaemonSet inventory
识别 CNI；`kindnet` 和未知 CNI 直接 fail closed 且 `mutation_performed=false`，不创建临时资源。
在识别到 Cilium、Calico、Antrea 或 kube-router 等候选 CNI 后，才创建 disposable namespace、server、
allowed/denied client 和 ingress policy，验证允许流量成功、非允许流量失败并自动清理。当前 Docker
Desktop 集群实际观察到 `kindnet`，演练正确返回 `passed=false`，没有把 policy YAML 存在误写为网络隔离已生效。
报告为 `docs/reports/agentops_networkpolicy_enforcement_2026-08-30.json`，内部
`report_sha256=72bae1ccd05f465fd56510eba5c4a8acb66ceae5814cba6617e296bc47e1aa92`，文件 SHA-256 为
`d6988bd5b1cf16b61d495cb07560002566301a39d879058e316564250d3108fd`。本切片关闭“缺少可重复
enforcement 验收工具”的工程缺口，不关闭 NetworkPolicy 退出门；后续必须在支持策略执行的 CNI
上跑同一 harness，并进一步验证 discovery→Temporal 和 discovery→control PostgreSQL 的实际路径。

**可靠性修正（2026-08-30）：ApprovalCase verification activity 支持显式 clock 注入。**
`build_approval_verification_activity_definition` 现在可接收演练/测试 clock，生产默认仍使用
UTC 当前时间；固定历史 case 不再因运行日期变化而被误判为 expired。AgentOps 回归恢复为
`268 passed, 6 skipped`，并保持 provider、HITL 和 Temporal 终态判断不变。

**状态推进（2026-08-30，ADR-358）：ApprovalCase 通知 SLA 升级 bounded slice 已完成。**
新增 `ApprovalCaseEscalationPlan`、`ApprovalCaseEscalation` 及 PostgreSQL migration 249：
每个升级阶段绑定 tenant、case、pending state version、action、target fingerprint、due time、
值班团队和 on-call reference，并由数据库重算完整 scope 的幂等 SHA-256 key。到期项通过
`SKIP LOCKED` 物化到既有 notification outbox，Alertmanager 告警携带升级阶段、目标团队和
值班引用；ApprovalCase 进入 terminal 状态时只抑制尚未发送的升级，不改变 verdict。真实
PostgreSQL 16 disposable 认证通过 11/11：重放幂等、两阶段同时物化、terminal suppression、stale
state rejection、租户隔离、gateway 最小权限和 approved verdict 保持均有证据。报告为
随后新增前向 migration 250，将 `escalation_stage` 纳入 notification outbox delivery 唯一键，
并使人工终态同时抑制已物化但仍 pending 的 stage 1/2 通知，同时保留 escalation projection 的
`materialized_at` 证据；同一认证脚本已覆盖两阶段同时到期、
两阶段各物化一次、重放不产生副本以及终态后两阶段均抑制。真实 PostgreSQL 16 disposable
认证仍为 verified，报告为
`docs/reports/agentops_approval_sla_escalation_2026-08-30.json`，内部
`report_sha256=5e8baee73736f8c05947300059a491c6aa5fc9838e4fa550c3c27d9116687f40`，文件
SHA-256 为 `c97dd1f5c62776133b326ea4c2e005060e309ee4c8ce14a80b7c9bb84e0b70b9`。该切片关闭
“没有可执行的审批 SLA 升级投影”这一工程缺口，不关闭生产 paging、企业 on-call 同步、
批量审批、HITL UI、身份轮换、HA/备份/RPO/RTO 或生产 rollout；后续批量操作仍须
逐 case 复用 assignment/principal authority 并返回逐 case 成功/冲突/拒绝结果。

**状态推进（2026-08-30，ADR-359）：**新增 `ApprovalCaseBatchEscalationRequest`、
`ApprovalCaseBatchEscalationResult` 和 `ApprovalCaseBatchEscalationResponse`，将批量升级
限定为同租户、单 actor、最多 100 案、逐案调用既有 `ApprovalCaseAuthority` 的编排请求。
真实 PostgreSQL 16 disposable 认证覆盖两个成功 case 和一个不存在 case，结果按输入顺序返回
`scheduled, scheduled, not_found`，成功项进入既有双阶段 materialize 路径，报告 v3 与 ADR-359
一致。该切片关闭“没有逐案结果的批量升级编排”缺口，不提供批量批准、持久 batch ledger、
客户端丢失后的 resume、生产 paging、企业 on-call 同步或生产 HA/RPO/RTO。

**入口收敛（2026-08-30）：**该 bounded slice 已接入正式 CapabilitySpec
`agentops.approval-case.batch-escalate@1.0.0`，统一 HTTP
`POST /api/platform/v1/approval-cases/escalation-batches` 与 MCP
`schedule_approval_case_batch_escalation`；SDK/CLI/TUI/Notebook 通过同一 HTTP
projection 使用。HTTP 与 MCP 均强制认证 tenant/actor 绑定，并保留 capability fingerprint
漂移保护。路由与 MCP 聚焦回归 `59 passed`，AR-5/ApprovalCase/Capability/Gateway 扩展回归
`495 passed, 6 skipped`；本次只完成入口契约，不改变“无持久 batch ledger、
无批量审批和无生产 paging”的范围。机器可读证据见
`docs/reports/agentops_approval_batch_capability_2026-08-30.json`。
