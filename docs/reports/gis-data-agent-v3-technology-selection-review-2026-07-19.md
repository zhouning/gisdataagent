# GIS Data Agent 对时空数据中台 v3.0 技术选型的复审与升维结论

**日期**：2026-07-19

**状态**：Architecture Baseline Input / Accepted Decisions

**审查输入**：`/Users/zhouning/Downloads/时空数据中台产品详细设计v3.0.0.0.docx`，完整文本、技术选型表、部署设计与关键架构图均已审查。

**关联决策**：[ADR-001](../architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)、[ADR-004](../architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)、[ADR-006](../architecture-decisions/adr-006-openmetadata-governance-and-active-metadata-platform.md)、[ADR-007](../architecture-decisions/adr-007-dolphinscheduler-temporal-orchestration-platform.md)。

## 1. 结论先行

v3.0 不是一个应被“替代掉”的旧系统，而是 GIS Data Agent 的生产能力下限和重要架构输入。它已经正确识别了地理空间数据平台必须具备的湖仓、批流双引擎、分层、元数据、调度、Canvas/SQL/Notebook/API 多入口、质量、安全、资产服务、地图、审批、多租户和多形态部署能力。

GIS Data Agent 的升维不是把这些能力改成聊天功能，也不是照抄 v3.0 的 Spring 微服务、GPA、Neo4j、RabbitMQ、DataX 或历史版本。正确做法是：以稳定资源身份、不可变 definition/version、policy、run/artifact/evidence 为共同合同，将旧平台的确定性工程能力收束到可配置数据面和统一控制面；LLM/GWM 则在其上提供受治理的意图理解、候选计划、推演和解释。

最重要的新约束是：**每个生产 capability 必须同时具有受治理的 Agent tool 调用路径和至少一个不依赖 LLM 的确定性路径。** 这不是“提供一个备用页面”。它要求 Web、API、SDK、CLI、TUI、Notebook、Canvas 和 Agent 共用相同的 `CapabilitySpec`、`DefinitionVersion`、`PolicyDecision`、`PlatformRun`、`Artifact` 与 audit；差异只发生在交互表达和展示层。

## 2. 复审方法与判定类别

每项旧选型按五个问题评估：是否满足当前私有化/离线/云/轻量 profile；是否形成单一权威边界；是否支持空间数据与数据分层；是否可通过真实恢复、权限和跨引擎 conformance 验收；是否会把历史实现债带入未来十年。

| 判定 | 含义 |
|---|---|
| **保留为默认基线** | 已进入目标架构默认 profile，按认证版本部署 |
| **保留为可配置 provider** | 合法且有价值，但不能成为所有部署的固定依赖 |
| **替换为统一框架** | 需求保留，原实现不再是权威或默认 |
| **条件引入** | 只有 workload、SLO、合规或兼容性证据触发时引入 |
| **不纳入新基线** | 仅保留迁移/兼容适配，不继续扩展 |

历史文档中列出的精确中间件版本是当时的兼容矩阵，不是 GIS Data Agent 的当前生产 pin。每个 DeploymentProfile 使用经过安全扫描、兼容、容量、备份恢复和 conformance suite 验证的 BOM；禁止使用 `latest`，也禁止把历史版本号当作“已经认证”的证据。

## 3. 数据底座与计算选型

| v3.0 选型/能力 | 判定 | GIS Data Agent 基线 | 实施边界与准入 |
|---|---|---|---|
| ODS、DWD、DWS、ADS 分层 | **保留并统一** | `Landing/Raw -> ODS/Bronze -> DIM+DWD/Silver -> DWS/Gold aggregate -> ADS/Gold serving` | 同一逻辑分层映射 Medallion；不能为传统数仓和湖仓复制两套产品真值 |
| MinIO/S3、Iceberg、Gravitino | **保留为默认湖仓方向** | MinIO + Iceberg 默认；Gravitino 为 technical metadata lake/federation；OpenMetadata 为治理 catalog | Gravitino 在 Spark/Sedona/Flink 真实 conformance 前不得是唯一 Iceberg catalog；默认使用已认证 Iceberg REST catalog |
| Spark、Sedona | **保留为默认批处理** | Spark/Sedona batch provider | 仅由 capability/placement 选择；Definition 不绑定引擎；空间类型、GeoParquet/WKB、snapshot、取消、reconcile 必须认证 |
| Flink、Flink CDC | **保留为默认流处理** | Flink stream provider；认证的 Flink CDC/Debezium-compatible source adapter | CDC 记录 source offset、schema evolution、checkpoint、watermark、dead-letter/replay；trigger/影子表是受限兼容路径，不是默认“实时”方案 |
| Spark Streaming | **替换** | Flink 是默认流执行器 | 不在新 blueprint 新建 Spark Streaming 生产路径；已有作业经 provider adapter 迁移或维持兼容期 |
| PostGIS、DuckDB 单机存算一体 | **保留为轻量 profile** | `Lightweight Integrated`：PostGIS 或 DuckDB/Spatial + 对象存储可选 | 仍需逻辑分层、版本、质量、血缘、备份和可重放；不因单机就绕过 DataOps 合同 |
| 云盘客户端、大文件分片/断点续传/下载 | **保留并升维为一级能力** | `DriveTransfer`：桌面/边缘/浏览器客户端 + S3 multipart pre-signed URL + TransferProvider + quarantine/ingest | 客户端只保留本地恢复缓存；服务端 `TransferSession`/manifest/policy/audit 是真值；上传完成不等于入湖，必须完整性/扫描/元数据通过 |
| Trino 湖仓查询 | **条件引入** | 跨 catalog 即席 SQL/query federation provider | 需证明跨源查询、并发、权限下推和运维成本；不能替代 Spark/Flink 生产编排，也不以 Trino 成功证明 Gravitino Spark/Flink 已可用 |
| ClickHouse、Doris | **条件引入** | OLAP/serving projection provider | 只在低延迟聚合、并发或成本 SLO 证明 PostGIS/Iceberg 查询不足时引入；从 DataProductVersion 构建，不成为原始/治理真值 |
| HDFS、HBase、MongoDB | **不纳入默认基线** | S3-compatible object store、Iceberg、PostGIS/DuckDB 优先 | 仅以特定客户兼容 provider 接入；不为“覆盖面”主动部署 |

### 3.1 空间数据与文件数据

v3.0 对空间库、Shapefile/FileGDB/UDBX、影像、3D、点云、S3/NAS/FTP 的覆盖是重要下限。尤其不能遗漏其“类似云盘”的客户端：用户设备或边缘环境可以上传、下载、目录同步、分片、暂停/恢复和进度查看。GIS Data Agent 将其改造成 `DriveTransfer` capability family，而不是把它降格为一个浏览器上传按钮；文件上传、远程发现、同步、解析、预览和发布是不同能力，不能混成一个“导入”按钮。

`DriveTransfer` 的耐久对象是 `DriveEndpoint`、`FolderBinding`、`TransferSession`、`TransferCheckpoint`、`FileRevision`、`IntegrityVerdict`、`ArtifactManifest` 与 `IngestRequest`。桌面/边缘客户端通过 `gda drive` CLI/TUI、Web 传输面板或 SDK 调用同一合同；本地 SQLite 等 checkpoint 仅用于重启恢复，服务端 session/manifest/policy/audit 才是权威。默认使用受限的 S3 multipart pre-signed URL，NAS/SMB/FTP/SFTP 等通过认证 `TransferProvider` 接入；multipart ETag 不是完整文件 hash，必须记录 part checksum/receipt、full content hash 和输入 fingerprint。

大文件先进入 tenant-scoped quarantine，经历分片与全文件校验、病毒/格式扫描、classification、许可/配额、bundle 完整性和 manifest 后，才由 DolphinScheduler ingestion process 解析并提升到 append-only Landing；目录同步采用 checkpoint、tombstone、冲突策略、幂等键和 retry，远程删除不直接删除已发布 Raw/DataProduct。Shapefile/FileGDB/GeoJSON/CSV/Excel/COG/点云/3D 的 parser 都是认证 plugin，输出原始 Artifact 与结构化/空间 descriptor。每个 parser 必须声明 CRS、geometry/coverage、时间范围、许可、敏感级别和转换证据，不能由 LLM 猜测。

Agent 可以提交用户已经显式授权的 transfer plan，但没有本地客户端授予路径、操作、期限和字节上限时，不能扫描用户磁盘、开始下载或扩大同步范围。无 LLM profile 下，云盘客户端的上传/下载/恢复/入湖仍必须完整工作。

## 4. 元数据、血缘、语义与治理选型

| v3.0 选型/能力 | 判定 | GIS Data Agent 基线 | 实施边界与准入 |
|---|---|---|---|
| Gravitino 元数据湖 | **保留并纠正边界** | technical metadata/federation 层 | 管理 metalake/catalog/schema/table/fileset/topic 和跨 catalog technical facts；不替代 owner、术语、质量协作或治理 UI |
| 自研元数据、ES 同步、资源/数据级采集 | **替换为 fabric bridge** | OpenMetadata + Gravitino + GDA Control Ledger | `gda-metadata-fabric-bridge` 管理 ResourceURN/entity/object mapping 和空间/时间/证据 extension；采集由 DolphinScheduler 运行，不能出现第二通用 catalog |
| Neo4j 数据血缘 | **条件引入** | OpenLineage event + OpenMetadata generic lineage 为默认 | 图数据库只在已冻结 impact/competency query 或 SLO 无法满足时建设可重建 projection；不把 Neo4j 当血缘唯一写源 |
| Elasticsearch 搜索与日志 | **拆分并条件化** | OpenMetadata search backend 仅服务治理检索；日志/指标/trace 使用 OTel/SRE stack | 不把搜索索引或日志库当控制面权威；专用搜索/向量引擎须证明召回、延迟和成本 |
| 语义模型约束 NL2Semantic2SQL | **保留并扩展** | Canonical Semantic Model + OSSIE exchange + SemanticQueryIR + deterministic compiler | 语义模型、指标、口径、权限和 SQL 检查先行；LLM 只可生成候选 QueryIR，LLM 禁用时由表单、DSL、CLI/TUI 和 API 直接提交 QueryIR |
| 标准、质量、安全、资产关联 | **保留为 P0 治理闭环** | Standard/Contract/Quality/Classification/Policy 绑定 ResourceVersion 与 DataProductVersion | 质量、血缘、权限、发布审批不依赖聊天历史或模型上下文 |

## 5. 调度、工作流、开发与质量选型

| v3.0 选型/能力 | 判定 | GIS Data Agent 基线 | 实施边界与准入 |
|---|---|---|---|
| Apache DolphinScheduler | **保留为默认 DataOps runtime** | self-hosted DolphinScheduler | 统一 DataOps DAG、schedule、manual trigger、complement/backfill、worker group、resource queue、alert；DataProductBlueprint 编译为版本化 ProcessDefinition |
| GPA 单机算子/Canvas | **保留能力，替换框架权威** | typed operator registry + Definition/ExecutionPlan compiler | GPA/SuperMap 算子可作为 certified executor/plugin；不可成为独立 definition、权限、运行或调度真值 |
| Spark Canvas、画布逻辑校验、试运行 | **保留并泛化** | Visual TaskGraph -> typed operator -> preview sandbox -> publish changeset | Visual、SQL、Python/Notebook、CLI/TUI 和 Agent 共用 schema propagation、dry-run、preview、cost/impact；输出节点在 preview 默认无写副作用 |
| JupyterHub/Jupyter、脚本生产化 | **保留为专家路径** | JupyterHub sandbox + GDA SDK + notebook-to-definition publish | 发布时冻结 notebook/script、image、dependency lock、input version、resource spec、owner；交互 kernel 不直接是生产任务 |
| Deequ + 空间质量算子 | **保留为规则 provider** | typed quality rule registry：属性、时空、拓扑、contract、freshness | Deequ 用于适配的 Spark 属性规则；PostGIS/Sedona/GDAL/SuperMap provider 承担空间规则；质量结论统一写 `QualityAssessment` |
| 内部审批流程 | **保留，运行时替换** | `ApprovalCase`/policy 由 Temporal durable workflow 承载 | 数据申请、发布、敏感操作、规则/模型变更都由同一审批合同处理；DolphinScheduler 不承担长时人机 signal 与补偿 |
| APScheduler、应用内 queue、后台任务 | **不纳入生产基线** | DolphinScheduler + Temporal + transactional outbox | API/Web/CLI/TUI/Agent 只提交 command 或 RunRef；不让 Web 进程或 Redis 保存唯一运行状态 |

## 6. 数据服务、地图与体验选型

| v3.0 选型/能力 | 判定 | GIS Data Agent 基线 | 实施边界与准入 |
|---|---|---|---|
| RocketAPI 低代码接口 | **保留需求，替换固定产品依赖** | versioned `ServiceDefinition` + API gateway/provider adapter | SQL/attribute API、OGC/STAC、MVT/map、COG/raster、file/export、AgentContext 从 DataProductVersion 发布；可接 RocketAPI 但不能把其配置当服务权威 |
| PostGIS MVT + Redis 缓存 | **保留并标准化** | PostGIS/Martin MVT serving projection；Redis 仅 cache/wake-up | MVT 由已发布 ProductVersion 构建；缓存可丢，失效由 version/etag 控制，不能成为权限或产品真值 |
| SuperMap iServer/iObjects/iClient | **保留为商业 GIS provider** | certified spatial processing/serving/client adapter | 许可、版本、部署、CPU/环境约束进入 ProviderManifest；不让商业 SDK 定义跨引擎 schema 或平台生命周期 |
| 2D/3D 一张图、资产一张图 | **保留为 Discover/Consume 体验** | Map/2D/3D 仅消费受治理投影 | 地图范围、时态、样式、权限和 ProductVersion 可重建；地图不是第二数据编辑/发布通道 |
| Vue/AntV/ECharts/SuperMap 前端 | **保留为 Web 实现候选，不定义平台边界** | Web 通过 CapabilitySpec/UI schema 调用控制面 | 前端框架升级可独立进行；不以 UI 表单藏业务规则或特权执行 |

### 6.1 多入口而非单一 Web

旧平台已有 Canvas、SQL、Notebook 和 API 的雏形。GIS Data Agent 增加统一的 API/SDK/CLI/TUI/Agent layer，而不是增加第二套产品：

| 表面 | 选择 | 价值 | 同一性要求 |
|---|---|---|---|
| Web/Map/Canvas | 当前 React/地图工作台与生成式 UI schema | 可视化建模、空间浏览、审批、运营 | 产生或编辑同一个 DefinitionVersion/ChangeSet |
| HTTP API/SDK | OpenAPI 3.1、JSON Schema、AsyncAPI/CloudEvents | 集成、GitOps、CI/CD、脚本化和第三方应用 | 使用同一个 command/query、idempotency、RunRef 和错误码 |
| `gda` CLI | Python `Typer` + `Rich`（项目已有依赖） | 自动化、离线运维、批处理、CI | 支持 JSON/YAML、dry-run、wait、JSON output、non-zero exit；不保留业务状态 |
| `gda` TUI | Python `Textual`（项目已有依赖） | SSH/堡垒机、弱网络、现场值守、审批和 Run 救援 | 仅消费公开 API；地图以范围/图层/Artifact descriptor 表示，不伪造 Web 渲染 |
| Notebook | JupyterHub sandbox + GDA SDK | 研究、调试和可复现实验 | 发布转 DefinitionVersion，不直接提交 kernel 产物 |
| Agent/MCP/A2A | CapabilitySpec 投影的 typed tools | 自然语言、跨 Agent 协作、解释与受控执行 | tool 结果返回 resolved version、policy、RunRef、Artifact/Evidence；不得隐式操作 |

## 7. 安全、租户、部署与运维选型

| v3.0 选型/能力 | 判定 | GIS Data Agent 基线 | 实施边界与准入 |
|---|---|---|---|
| OIDC/OAuth2/CAS/LDAP、RBAC + ABAC | **保留并统一** | SubjectContext + OIDC federation + RBAC/ABAC/purpose/row/column/spatial/temporal/action policy | 每个入口和 workload identity 使用同一 policy decision；LLM 不参与授权 |
| 分级分类、国密、动静态脱敏 | **保留为 provider-neutral 能力** | classification、encryption/tokenization/masking provider、key reference、release gate | 具体国密/云 KMS/客户 HSM 由 deployment profile 认证；静态脱敏不得覆盖 Raw evidence |
| 租户 schema/bucket/queue/resource pool 隔离 | **保留并细化** | Shared、Dedicated Data、Dedicated Runtime、Dedicated Stack isolation class | 根据 policy 选择 PostgreSQL RLS/schema、bucket/prefix、catalog namespace、DolphinScheduler project/worker group、Temporal namespace、compute namespace |
| Kubernetes/Rancher | **保留为生产 profile** | Kubernetes + Helm/IaC + OTel + backup/restore；Rancher 等可作为 cluster management adapter | 控制面是模块化单体，外部 metadata/scheduler/runtime 独立部署；不因使用 K8s 强拆几十个业务微服务 |
| 传统物理机/VM | **保留为一级部署** | traditional process/VM profile | 使用同一配置、identity、backup、observability、provider contracts；无 K8s 不等于无 DataOps 或无 CLI/TUI |
| docker-compose 单机 | **保留为 dev/lightweight** | compose/single-node profile | 明示不可用的 HA/SLO，仍运行 deterministic platform path；不能把 compose 健康检查视为生产认证 |
| Nacos、RabbitMQ | **不纳入默认基线** | typed config/secret provider；PostgreSQL transactional outbox，Kafka-compatible backbone 条件升级 | 通过客户现有平台 adapter 集成，但不将其设为所有部署的前提 |
| 微服务全拆分 | **不纳入默认基线** | 模块化单体控制面 + 独立计算/metadata/scheduler runtime | 以 SLO、故障隔离、独立扩缩容和组织边界证明后拆分 |

## 8. LLM 缺失时的完整运行合同

`llm_mode` 是 DeploymentProfile 的显式字段，而不是某个环境变量的偶然结果：

| profile 值 | 可用能力 | 不可用能力 | 行为要求 |
|---|---|---|---|
| `disabled` | 全部数据治理、源接入、Canvas/SQL/Notebook、API/SDK/CLI/TUI、调度、质量、安全、审批、资产、服务、地图、确定性 GWM/规则/传统模型 | 自然语言意图解析、生成式解释、LLM-driven plan | 返回 `LLM_UNAVAILABLE` 和相应 deterministic capability URI；不隐藏或静默降级生产功能 |
| `optional` | `disabled` 全部能力，加上已批准的 Agent assistance | provider 故障时仅生成式功能 | 断路器、预算、审计和 fall-back 到 direct/declarative path |
| `required_for_agent_feature` | 平台基础能力仍完整；特定产品的明确 Agent enhancement 需要 LLM | 该 enhancement | 产品 UI/API 必须标明 optional feature，不能让它占据基础操作唯一入口 |

所有 P0 capability 都要在无模型 provider、无外网、无 Agent worker 的测试 profile 完成以下验证：创建/读取/修改 definition，dry-run/preview，policy/approval，提交/查询/取消/重试 Run，查看 Artifact/lineage/quality，发布/回滚服务，以及 audit/recovery。相同输入在 direct deterministic 和 Agent tool path 上必须产生相同 definition 或解释可审计差异；Agent 无法调用的 capability 不能被标记为“已 agentic”，而没有 deterministic path 的 capability 不能进入生产。

## 9. 实施顺序与验收

1. **AR-0**：冻结 `CapabilitySpec`、OpenAPI/AsyncAPI/MCP projection、`llm_mode`、SubjectContext、入口 parity matrix；以旧平台的 Source/Sync、DataProduct、质量、服务、审批、Run 救援作为代表能力。
2. **AR-1**：OpenMetadata + Gravitino metadata fabric、DolphinScheduler + Temporal orchestration 均通过 OIDC、恢复和审计演练；CLI/TUI 不再访问应用内部表或 queue。
3. **AR-2**：完成 Source -> Landing/ODS -> Silver -> Gold -> PostGIS/STAC 的 CDC、批处理、云盘客户端文件三条路径；DriveTransfer 必须在真实大型空间 bundle 上通过中断、重启、hash、隔离、权限和入湖验收，并在 Lakehouse、Lightweight、Cloud 代表 profile 通过同一 contract。
4. **AR-3/AR-4**：Visual/SQL/Notebook/API/SDK/CLI/TUI 完成相同 Blueprint/ServiceDefinition 的 preview、publish、backfill、quality/security gate、审批和 rollback；地图和 API 仅消费已发布投影。
5. **AR-5**：Agent/MCP/A2A 使用已有 CapabilitySpec，不另建 pipeline；以同一代表任务证明步骤、成功率、恢复或可解释性 uplift，同时持续通过 LLM-free gate。

完成标准不是“部署了很多组件”，而是一个有权限的用户或集成系统在 Web、API/SDK、CLI/TUI、Notebook 或 Agent 中任意选择入口，都能追到同一 definition、policy、run、artifact、lineage 和恢复证据；在没有 LLM 的受限环境里，这条路径仍保持完整。
