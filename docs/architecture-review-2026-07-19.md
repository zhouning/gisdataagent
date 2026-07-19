# GIS Data Agent 企业级架构复审

**日期**：2026-07-19

**结论**：不通过当前平台化验收；允许在完成 AR-0 架构与运行真值冻结后，按新版 roadmap 进入整改。

**范围**：传统平台能力下限、产品工作流、数据接入、湖仓与服务、元数据、调度、治理、安全、DataOps、AgentOps、LLM 可选多入口、可观测与灾备、交付平台、AI/Agent 治理、GWM 边界。

**关联决策**：

- [ADR-001：可插拔地理空间存储、计算与服务边界](architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)
- [ADR-002：统一元数据控制面](architecture-decisions/adr-002-unified-metadata-control-plane.md)
- [ADR-003：统一调度与作业控制面](architecture-decisions/adr-003-unified-orchestration-and-job-control-plane.md)
- [ADR-004：传统平台能力下限、LLM 可选与多入口能力合同](architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md)
- [ADR-005：DataOps 与 AgentOps 双运营闭环](architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md)
- [传统平台能力基线与 Agentic 升维设计](traditional-platform-baseline-and-agentic-elevation-2026-07-19.md)
- [v3.0 技术选型复审与升维结论](reports/gis-data-agent-v3-technology-selection-review-2026-07-19.md)
- [总体架构 Roadmap](roadmap.md)

## 1. 执行结论

GIS Data Agent 不是没有元数据、工作流、质量、安全、湖仓或 AI 治理代码，而是长期以功能点和局部组件累积代替平台架构。代码存在、单点可运行、平台闭环是三个不同成熟度；当前大量能力停在前两层，却在历史版本记录中被描述为“统一”“分布式”或“完成”。

这次复审也必须纠正评审方法本身：第一轮关注湖仓和数仓分层，第二轮补上两个控制面，但两轮仍然过度偏向后端架构，没有把旧平台已经具备的源汇聚、模型设计、Visual/SQL/Notebook 开发、试运行发布、资产申请、服务运营、空间分析和通用审批视为一个不可拆散的产品闭环。这正是“只补用户点名的概念”造成的系统性遗漏。传统平台不是实现模板，但它完成的代表任务必须成为 GIS Data Agent 的能力下限。

因此，统一元数据和统一调度是平台脊柱，不是完整产品。下一代还必须提供 Discover、Build、Operate、Govern 四个稳定工作面，并让 Web/Map/Canvas、Visual/DAG、SQL、Notebook、API/SDK、CLI/TUI 与 Agent 共同操作同一 `CapabilitySpec`、typed definition、Run、Artifact 和审批记录。`llm_mode=disabled` 时确定性工作面仍必须完整可用；Agent 的升维价值必须以更少步骤、更短耗时、更高首跑成功率或更快恢复证明，不能以新增对话、工具或页面数量证明。

统一元数据中心和统一调度中心都必须建设，而且必须成为湖仓、PostGIS、STAC、MMFE、DataOps、AgentOps、Agent、AI 和 GWM 共同依赖的两个控制面：

- **统一元数据控制面回答**：平台里有什么，哪个版本是真值，在哪里，谁负责，谁能用，质量如何，上下游影响什么。
- **统一调度与作业控制面回答**：什么定义在何种触发下运行，由哪个执行器承接，运行到哪一步，失败后如何重试、接管、取消和恢复，产生了哪些版本与制品。

二者不能各自复制资产、运行和血缘事实。`Run`、`Artifact`、`AssetVersion`、`DataProductVersion`、`DataIncident`、`AgentSpecVersion`、`AgentRun` 和 `LineageEvent` 必须使用同一组不可变标识关联。

本次复审新增一个明确结论：DataOps 和 AgentOps 不是可选的管理术语，而是平台运营能力。DataOps 是数据产品的持续交付与可靠性闭环；AgentOps 是 Agent bundle 的评测、部署、安全、预算、运行、事故和反馈闭环。当前项目两者都有组件，没有闭环，因此不能宣称平台化完成。

## 2. 关键发现

### P0-1 数据库迁移历史不确定，平台 schema 真值可能已经分叉

迁移器只把三位数字版本写入唯一列，并用该版本判断是否已应用；仓库中 `011` 至 `017` 每个版本都有两个不同文件。一个同号文件登记后，另一个会被永久视为已应用。单个迁移失败又只记录 warning 并继续，迁移 Job 最终仍可退出成功。

证据：

- `data_agent/migration_runner.py:30`：`version` 唯一，未以文件名或 checksum 标识迁移。
- `data_agent/migration_runner.py:85`：只读取版本集合判断 pending。
- `data_agent/migration_runner.py:102`：失败回滚后 `skipping`，不阻断环境启动。
- `data_agent/migrations/011_create_semantic_metrics.sql` 与 `011_create_stream_tables.sql`，以及 `012` 至 `017` 的同类重复版本。

影响：开发、测试、Compose、Kubernetes 和已有客户环境可能拥有不同表结构。统一元数据和调度中心若直接在此基础上增加表，只会扩大不可诊断差异。

决定：AR-0 首先导出每个目标环境的 schema fingerprint 和 `schema_migrations` 事实，建立不可重复 ID、checksum、失败即阻断和前向修复机制；在此之前不新增平台控制表。

### P0-2 没有统一、耐久、可接管的调度与作业控制面

当前运行语义分散在 APScheduler、`TaskQueue`、`SparkGateway`、Standards outbox、自进化 scheduler 和 API 进程内 `asyncio.create_task` 中，彼此没有共同的 `JobDefinition`、`Schedule`、`Run`、`TaskAttempt`、`Lease`、`Artifact` 和取消合同。

证据：

- `data_agent/app.py:2996`：工作流 scheduler 在首次聊天时才启动，不是独立平台进程。
- `data_agent/workflow_engine.py:889`：每个 Web 进程都可创建自己的 APScheduler；`sync_jobs()` 只在启动时调用。
- `data_agent/api/workflow_routes.py:151`、`:319`：API 用进程内 background task 执行，进程退出即失去执行。
- `data_agent/task_queue.py:344`：Redis 只弹出 job ID；`data_agent/task_queue.py:362` 再从当前进程内 `_jobs` 取完整对象，跨进程 worker 会拿不到并静默跳过。
- `data_agent/task_queue.py:128`：队列必须显式 `start()`；生产代码未发现对应启动调用。
- `data_agent/spark_gateway.py:83`：Spark job 只保存在内存；`:129` 的 L2 queue 实际同步走本地 dispatch；`:157` 的 local PySpark 分支仍调用 GeoPandas dispatch。

影响：重复 cron、丢任务、僵尸 run、无法跨进程恢复、无法可靠取消，也无法保证数据产品只发布一次。

决定：按 ADR-007 建设 DolphinScheduler DataOps runtime + Temporal durable Agent/GWMOps runtime，GDA PostgreSQL 仅保存 PlatformRun correlation、policy/approval、artifact/evidence 等控制事实；Redis 只作通知和缓存，不作唯一作业真值。所有 Web/API/SDK/CLI/TUI/Notebook/Agent 入口只提交 command/RunRef，不直接持有长任务。

### P0-3 有多套元数据实现，但没有统一元数据中心

`MetadataManager`、`data_catalog.py`、PostGIS intake profiles、Standards Platform、semantic registry、STAC、Iceberg manifests、prompt/model/tool registries 各自维护局部对象，没有统一资源标识、版本、采集事件、权威冲突规则、freshness 或跨域影响分析。

证据：

- `data_agent/metadata_manager.py:40` 与 `data_agent/data_catalog.py:319`：两条路径都直接写 `agent_data_assets`。
- `data_agent/metadata_manager.py:43`：技术、业务、运行、血缘四个 JSONB 被当作主要元数据模型，没有跨系统实体/版本合同。
- `data_agent/dataset_intake.py:48`：主动采集只覆盖 PostGIS 表扫描，未统一采集 Iceberg snapshot、STAC、对象存储、pipeline、AI 和 GWM 对象。
- `data_agent/metadata_manager.py:193`：血缘可写在资产 JSONB；`data_agent/data_catalog.py:1275` 又写 `agent_asset_lineage`，未定义哪个是真值。
- `data_agent/metadata_manager.py:115`：由请求参数拼接列名；`data_agent/api/metadata_routes.py:47` 未对白名单进行校验。

影响：同一资产在目录、STAC、Iceberg、PostGIS 和 AI 数据集中无法稳定对齐；schema drift、质量失败和上游版本更新不能驱动统一影响分析和重算。

决定：按 ADR-002 建设统一标识、版本与事件模型，以 PostgreSQL 为元数据写权威，通过 adapter/harvester 接入现有注册表和物理系统。现有 JSONB 作为扩展属性保留，不再承担核心关系和状态机。

### P0-4 租户与权限执行在元数据和血缘路径上不一致

迁移 `032` 已给 `agent_data_assets` 配置 RLS，这一点不是“没有 RLS”；问题是调用路径没有一致注入数据库身份，也没有全部使用显式 owner/tenant 条件。血缘边表没有可见的 RLS/所有权验证。

证据：

- `data_agent/migrations/032_rls_policies.sql:9`：资产表启用了 RLS。
- `data_agent/database_tools.py:59`：身份 GUC 需要每个事务显式 `_inject_user_context()`。
- `data_agent/db_engine.py:30`：引擎层没有全局身份注入。
- `data_agent/metadata_manager.py:94`、`:119`、`:191`：更新、读取和血缘查询均未注入 GUC，也没有 owner 条件。
- `data_agent/api/lineage_routes.py:13`：只验证已登录，未设置 DB user context；`data_agent/data_catalog.py:1442` 按 edge ID 直接删除。

影响：不同连接和部署角色下可能 fail closed，也可能因表 owner 绕过 RLS；跨系统血缘可能泄露或被越权修改。

决定：所有控制面命令必须携带不可伪造的 `SubjectContext`，repository 层统一设置事务身份并做资源权限判断；RLS 是纵深防御，不替代应用授权。AR-1 验收必须包含双租户的读、写、遍历和删除测试。

### P1-1 湖仓组件存在，但产品生命周期和可配置引擎合同尚未由运行时强制

MinIO/S3、Iceberg、GeoParquet、STAC、Spark/Sedona 和 PostGIS 均有配置、适配器或 smoke，但通用 ingest、layer transition、snapshot publish、rollback 和 projection rebuild 尚未形成同一 pipeline。存储路由也不等于可配置数据平台：当前未发现统一 `DeploymentProfile`、`StorageBinding`、`TableFormatCatalogBinding`、`ComputeBinding`、capability certification 和 placement decision；Flink、云平台计算及 DuckDB/PostGIS 轻量存算一体尚未进入同一执行合同。

`StorageManager` 解决 URI 路由，不解决不可变 Raw、schema contract、snapshot transaction、provider capability 或产品版本；`SparkGateway` 当前也不能作为可靠的大任务后端。ADR-001 的目标边界调整为稳定逻辑合同 + 可配置 provider profile：默认 MinIO/Iceberg、Spark/Sedona + Flink；Azure 等云平台通过认证 adapter 替换；PostGIS/DuckDB 提供轻量 profile。必须由 AR-2 的默认、云代表和轻量垂直链验证后才能称为可配置湖仓一体。

### P1-2 数据接入缺统一 Source、Sync、Cursor、CDC 和 schema drift 合同

连接器覆盖数据库、对象存储、STAC、WFS/WMS/OGC/API，但没有共同的 source instance、credential reference、watermark、cursor、snapshot、CDC offset、reconciliation 和 dead-letter 模型。生产代码未发现 Debezium、逻辑复制或同等 CDC 实现；增量能力主要停留在评估文档或个别任务。

影响：周期同步、增量重放、源端删除、迟到数据、schema drift 和断点续传无法跨连接器一致处理。

决定：AR-2 用默认 Flink executor 认证至少一条真实 CDC 或事件流 source，覆盖 watermark/offset、checkpoint、迟到/乱序、删除、幂等 sink 和重放；AR-8 只承接多源高吞吐、多集群 HA、事件总线和严格实时 SLO 扩展。

### P1-3 质量、标准、主数据和参考数据尚未形成发布门

项目有 standards、quality rules、classification、semantic model 和 reference-data 子系统，但缺统一的 MasterEntity/CanonicalID、代码集有效期、匹配合并、survivorship、发布订阅和下游影响合同。质量结果也尚未作为所有 `DataProductVersion` 状态迁移的强制前置条件。

决定：不先建设庞大通用 MDM 产品；首条自然资源链先实现行政区、地类、时间和数据源四个受版本控制的一致维度，再以复用证据扩展。

### P1-4 可观测、SRE 与灾备覆盖了应用信号，未覆盖数据平台闭环

已有结构化日志、Prometheus 和 OpenTelemetry 基础，也有每日 PostgreSQL dump。但缺少贯穿 source/asset/run/attempt/snapshot/product/projection 的统一 correlation；未见对象存储、Iceberg catalog、PostGIS projection 和控制面状态的联合恢复演练。

证据：

- `data_agent/otel_tracing.py:71`：trace 主要围绕 pipeline 调用。
- `docker-compose.prod.yml:42`：仅见数据库日备和 7 天默认保留。
- `scripts/backup-db.sh:46`：提供 dump，没有对应自动恢复校验。

决定：AR-0 按 DeploymentProfile 冻结 SLI/SLO、RPO/RTO 和容量基线；AR-2 用真实版本执行默认湖仓和轻量 profile 的恢复演练，并验证云代表 adapter 的版本、权限与恢复合同。未验证恢复前不能宣称 DR。

### P1-5 交付与配置合同存在漂移，CI/CD 不能证明生产部署

- `.github/workflows/ci.yml:56` 设置 `DATABASE_URL`，而 `data_agent/database_tools.py:37` 只读取分离的 `POSTGRES_*`；数据库测试可能实际处于未配置路径。
- `.github/workflows/cd-production.yml:102` 至 `:150` 的 canary、部署、健康检查和回滚是说明性 `echo`，没有执行真实部署或探测。
- `k8s/base/outbox-worker.yaml:10` 仍称 outbox 没有 `SKIP LOCKED`，但 `data_agent/standards_platform/outbox.py:58` 已实现，表明部署文档与代码漂移。

决定：将 schema migration、控制面 contract、默认 MinIO/Iceberg/Spark/Flink、轻量 PostGIS/DuckDB 和 Azure 代表 adapter 的真实集成与部署 smoke 纳入强制 gate；删除用说明文本替代执行的“成功”口径。

### P1-6 AI/Agent 治理是多个注册表，不是统一 ModelOps/AgentOps 控制面

Prompt 有数据库版本和回滚，eval 有数据集与历史；`ModelRegistry` 仍以进程内字典/YAML 为主。名为 model gateway 的迁移只给 token usage 增加归因字段，并未建立 ModelVersion、Artifact、Approval、Deployment、EvaluationBinding 或 lineage。

证据：

- `data_agent/model_gateway.py:375`：模型注册表是进程内可变字典。
- `data_agent/model_gateway.py:401`：运行时注册不持久化。
- `data_agent/migrations/046_model_gateway.sql:1`：只修改 token usage。
- `data_agent/prompt_registry.py:71`、`:125`：prompt 有独立部署和回滚状态机。

决定：AI 对象复用统一元数据标识和统一 Run/Artifact；AR-5 建设 AgentOps bundle、评测、部署、在线 verdict、事故和回滚；AR-6 再补 ModelOps/LLMOps 的 ModelVersion/PromptVersion/EvaluationSet/Deployment binding，不另建第二资产目录或第二调度器。

### P1-7 Standards outbox 是可复用基础，但仍不等于平台事件总线

`std_outbox` 已使用 `FOR UPDATE SKIP LOCKED`、重试和退避，是当前最接近耐久 worker 的实现。但 claim 后只设置 `in_flight`，没有 lease expiry/heartbeat/reclaim；worker 在 complete/fail 前退出会留下永久 `in_flight`。事件类型又被 Standards 域硬编码，不能直接承担全平台任务。

决定：复用其事务 outbox 和 claim 模式，不复用其领域表为通用 queue。平台事件采用独立 envelope、幂等 consumer 和租约回收。

### P1-8 DataOps 与 AgentOps 没有形成可接管的运营闭环

当前文档和代码有 workflow、quality、CI、Prompt Registry、Agent Registry、eval history、OTel、guardrail、feedback 和 cost guard，但没有统一定义 `DataProductRelease`、`Promotion`、`DataIncident/Problem`、`AgentSpecBundle`、`EvaluationBinding`、`AgentDeploymentRevision`、`OnlineVerdict`、`AgentRun/ToolCall`、`SafetyIncident` 和 rollback 状态机。

证据：

- `data_agent/agent_registry.py:2-5` 明确是服务发现和 heartbeat，不是 AgentSpec 生命周期。
- `data_agent/prompt_registry.py:13-14`、`:71-126` 只管理 Prompt 版本、部署和回滚。
- `data_agent/eval_history.py:1-5`、`:55-69` 只持久化离线评测结果和趋势。
- `data_agent/otel_tracing.py:99-135` 记录 Agent/Tool span，但没有 AgentRun/ToolCall verdict、策略副作用和事故状态机。
- `.github/workflows/cd-production.yml:102-150` 的 canary、健康检查和 rollback 仍是说明性 `echo`。

影响：数据产品可以运行但不能持续可靠运营；Agent 可以调用工具但无法证明上线版本、线上质量、安全事件、成本预算和回滚责任。DataOps 与 AgentOps 若继续以局部组件推进，会再次形成第二套 registry、第二套 release 状态和不可审计的 Agent 行为。

决定：按 ADR-005 建设两个领域运营闭环，共用 Metadata/Orchestration/Policy/Artifact/Audit/Incident/Change 合同。AR-2 至 AR-4 先完成 DataOps，AR-5 完成 AgentOps，AR-6 将 ModelOps/LLMOps 纳入 AgentOps bundle。

## 3. 企业能力域矩阵

| 能力域 | 当前事实 | 成熟度判断 | 目标归属 | Roadmap |
|---|---|---|---|---|
| 传统平台能力下限 / 产品工作流 | Agent、语义、标准、问数、MMFE/GWM 较强；Source/Sync、建模开发、资产服务运营和专业工作面不完整 | **未达传统平台完整任务闭环** | Product Architecture + Four Work Surfaces | AR-0/AR-2/AR-3/AR-4 |
| DataOps | source、workflow、quality、catalog、Run、CI 组件存在 | **缺 release/promotion、data observability、DataIncident、replay 和可靠性闭环** | Data Product Operations | AR-0/AR-2/AR-3/AR-4 |
| AgentOps | Agent registry、Prompt version、eval history、OTel、guardrail、feedback、cost guard 存在 | **缺 AgentSpec bundle、EvaluationBinding、DeploymentRevision、online verdict、incident 和可执行 rollback** | Agent Runtime Operations | AR-0/AR-1/AR-5/AR-6 |
| Schema / Config Truth | SQL migration、环境变量、K8s Job 均存在 | **危险：环境可能分叉** | Platform Foundation | AR-0 |
| 统一元数据 / Catalog / Lineage | 多套表、JSONB、API 和 registry | **局部可用，未统一** | Metadata Control Plane | AR-1 |
| 统一调度 / Job Control | APScheduler、queue、outbox、内存 gateway | **不可耐久接管** | Orchestration Control Plane | AR-1 |
| 数据接入 / Batch / CDC | 多种 connector、PostGIS intake、Redis stream | **缺统一同步合同** | Data Production | AR-2/AR-8 |
| 可配置存储 / 计算引擎 | 存在 StorageManager、MinIO/S3、PostGIS、SparkGateway 和本地执行 | **缺 provider capability、placement、Flink/云/轻量统一合同** | Engine Provider Layer | AR-0/AR-1/AR-2 |
| 湖仓 / 数仓分层 / Serving | MinIO、Iceberg、Spark/Sedona、PostGIS、STAC | **默认批处理技术可行，未产品化** | Storage + Data Production | AR-2 |
| 质量 / 标准 / MDM / Reference | 规则、标准、语义和参考数据组件 | **未成为发布门** | Governance Control | AR-3 |
| IAM / Policy / Secrets / Audit | Auth、RLS、K8s Secret、审计 | **执行不一致** | Security Control | AR-0/AR-1/AR-3 |
| Observability / SRE / DR | 日志、metrics、trace、DB backup | **无数据产品级恢复闭环** | Platform Operations | AR-0/AR-2 |
| 数据开发 / 专业工作台 | WorkflowEditor、SQL/Python/GIS tools 和局部 model/workflow | **缺 typed operator、preview/publish 和 Notebook 生产链** | Data Product Engineering | AR-3 |
| 资产 / 服务 / 空间体验运营 | catalog、distribution/review/usage、REST/MVT/STAC/MCP 和地图分析局部存在 | **缺统一申请订阅、ServiceDefinition 生命周期和可重放结论** | Product + Service Operations | AR-4 |
| API / Event / Integration | REST、MCP/A2A、outbox、stream | **合同和事件分散** | Integration Plane | AR-1/AR-4/AR-8 |
| Developer Platform / CI/CD | tests、Compose、K8s、GitHub Actions | **配置漂移，CD 多为占位** | Platform Engineering | AR-0/AR-2/AR-4 |
| Agent / Model / Prompt Governance | 多注册表、eval、HITL、guardrail | **缺统一版本与运行血缘** | Cognitive + AI Governance | AR-5/AR-6 |
| MMFE | 多模态 profiling/alignment/fusion | **真实能力，仍是旁路** | Data Production Executor | AR-6 |
| GWM/TWM/UWM | 丰富领域 kernel、证据与评测 | **边界需收束** | Intelligence Consumer | AR-7 |

## 4. 目标总体架构

```text
LLM-Optional Multi-Surface Experience
Discover | Build | Operate | Govern | Contextual Agent
Visual/DAG | SQL | Notebook | Map/2D/3D | API/SDK | CLI/TUI | MCP/A2A
                         |
            shared typed definitions / changesets
                         |
+------------------------+-------------------------+
| Unified Metadata Control Plane                    |
| identity/version | catalog/search | contract      |
| owner/policy | quality | lineage/impact | SLA     |
+------------------------+-------------------------+
                         |
+------------------------+-------------------------+
| Unified Orchestration & Job Control Plane         |
| definition | trigger/schedule | run/DAG/attempt   |
| lease/heartbeat | retry/cancel | artifact/event   |
+------------------------+-------------------------+
                         |
        executor contract + immutable inputs
                         |
+------------------------+-------------------------+
| Data Production / Execution                       |
| ingest | profile | standardize | MMFE | aggregate |
| DuckDB/local | PostGIS | Spark/Sedona | Flink     |
| certified cloud compute | AI/GWM executors        |
+------------------------+-------------------------+
                         |
+------------------------+-------------------------+
| Configurable Storage, Table & Serving Providers   |
| default: MinIO + Iceberg | cloud: ADLS/etc.       |
| light: PostGIS/DuckDB | PostGIS/STAC serving      |
+--------------------------------------------------+
                         |
                         v
Consumption & Intelligence
Human Views | Agent Context | AI Dataset/Inference | GWM/TWM/UWM

Cross-cutting: SubjectContext, policy enforcement, secrets, audit,
observability, provenance, schema/config truth, backup/restore and cost.
```

Agent 是控制面的高级调用者和规划者，不是 metadata authority、scheduler database、permission engine 或 storage engine。确定性 pipeline、人工操作和 Agent 请求必须通过同一 `CapabilitySpec` 进入同一 Run 状态机；没有 LLM、外网或 Agent worker 时，Web/API/SDK/CLI/TUI/Notebook 的确定性路径不得消失。

DataOps loop: DataProductSpec -> CI/quality -> promotion -> DataRun -> SLO/observe -> DataIncident/remediation -> replay/new DataProductVersion.

AgentOps loop: AgentSpecBundle -> eval/safety/cost -> deployment/canary -> AgentRun/ToolCall -> online verdict/guardrail -> incident/rollback/feedback.

`DeploymentProfile` 提供平台默认值，`DataProductBlueprint` 声明 capability/SLO/cost/data-sovereignty 需求，placement resolver 生成版本化 Storage/Table/Compute binding。Definition 不硬编码 provider endpoint，但必须声明 portability class：portable TaskGraph 可编译为 provider ExecutionPlanArtifact；engine-family/provider-native 作业显式受限。Run 固化实际 provider、region、engine/version、执行计划、配置和 artifact location。这样云平台替换和轻量部署改变物理执行，不改变逻辑分层、治理、血缘或产品身份，也不虚构任意原生代码可自动移植。

## 5. 两个控制面的共同合同

```text
ResourceURN + AssetVersion
    -> PlacementDecision + Storage/Table/Compute bindings
    -> JobDefinitionVersion + immutable input bindings
    -> Run -> TaskAttempt(s) -> Artifact(s)
    -> QualityAssessment + LineageEvent(s)
    -> Approval -> DataProductVersion
    -> PostGIS/STAC/Human/Agent/AI/GWM projections
```

共同约束：

1. 每个资产、schema、数据产品、工作流、模型、prompt、tool 和 GWM 输出都有稳定 `ResourceURN`，每次变化生成不可变 version。
2. Run 只引用不可变 definition 和 input version；运行中参数不能静默覆盖定义。
3. Artifact 记录 URI、content hash、media/schema、大小、敏感级别和 producer attempt，不把大结果塞进 queue。
4. Lineage 由运行事件生成，人工补录必须标注来源与审批；JSONB lineage 降级为兼容读字段。
5. Metadata change 和 Run state change 通过 transactional outbox 发布；首期不要求 Kafka。
6. 资源访问先由统一 policy resolver 决策，再由 RLS、bucket policy 和 executor identity 做纵深约束。
7. 所有 consumer projection 可由指定 `DataProductVersion` 重建，不能反向成为分析真值。

## 6. 实施原则与验证门

- **先修真值，再加表**：先解决 migration/config/schema 漂移，再引入控制面 schema。
- **先平台脊柱，再湖仓链路**：AR-1 先交付最小 Metadata + Run/Attempt/Lease；AR-2 的地类图斑链必须全程使用它们。
- **先 DataOps，再 AgentOps**：AR-2 至 AR-4 必须证明数据产品的持续交付、可靠性、事故和恢复闭环；AR-5 才能将 Agent bundle 进入灰度和线上运行。
- **默认不等于绑定**：MinIO/Iceberg、Spark/Sedona + Flink 是开箱 profile；Azure 等云 provider 和 PostGIS/DuckDB 轻量 profile 复用同一 SPI、Definition 和验收套件，不能复制 pipeline。
- **先完整专业闭环，再 Agentic 升维**：AR-3/AR-4 必须通过传统平台代表任务的 parity/control gate；AR-5 才以同一任务验证步骤、耗时、首跑成功率和恢复效率 uplift。
- **框架不等于自研替代品**：OpenMetadata + Gravitino、DolphinScheduler 与 Temporal 已在 ADR-006/007 冻结，分别承担治理/technical metadata fabric、DataOps 和 durable Agent/GWMOps；GIS Data Agent 只建设 bridge、typed contract、policy/evidence 与 provider adapter。Gravitino 进入默认 Spark/Flink catalog 路径前必须通过 conformance。Kafka、Trino、专用 vector/graph/RDF、service mesh 等仍只在 workload/SLO 证据满足后引入。
- **不做大爆炸重写**：现有 catalog、workflow、outbox、quality 和 registry 通过 adapter 迁移；新写路径切到统一服务后再逐步停止旧写路径。
- **状态必须有证据**：只有 contract test、真实后端 integration、故障注入和恢复产物同时通过，才能标记 `verified`。

下一次架构复审的最小输入：

1. 全环境 schema/config fingerprint 和迁移修复记录。
2. 两个控制面的逻辑模型、API/event schema、权限矩阵和运行 dashboard。
3. 双 scheduler、worker crash、lease expiry、retry、cancel、幂等发布的故障注入报告。
4. PostGIS/DuckDB、Iceberg/云湖表、STAC 和对象存储的 provider-aware metadata harvesting 与冲突解析报告。
5. Default Lakehouse、Cloud Managed 代表 adapter 和 Lightweight Integrated profiles 的 capability matrix 与 conformance 报告。
6. Raw 到 DataProductVersion 再到 serving projection 的真实重放、跨引擎 golden equivalence 和恢复报告。
7. 12 项能力下限代表任务的 parity/control 结果、Web/API/SDK/CLI/TUI/Notebook/Agent 的 CapabilitySpec 可达性矩阵，以及无 LLM profile 的重放证据。
8. DataOps release/promotion/SLO/incident/replay 报告，以及 AgentOps bundle eval、shadow/canary、online verdict、ToolCall/Policy observation、budget、incident/rollback 报告。
