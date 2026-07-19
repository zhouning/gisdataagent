# GIS Data Agent 新一代 Data Platform 规划设计与全球对标报告

**报告日期**：2026-07-19<br>
**规划视野**：2026-2036<br>
**比较基线**：`/Users/zhouning/Downloads/时空数据中台产品详细设计v3.0.0.0.docx`<br>
**评审对象**：GIS Data Agent 当前实现、已确认目标架构、Roadmap、DataOps/AgentOps、MMFE、GWM/TWM/UWM 体系<br>
**信息口径**：竞品以截至 2026-07-19 可核对的官方公开资料为准；公开资料未说明的能力不推断，营销术语不直接等同于生产能力。

---

## 0. 执行摘要

### 0.1 总体判断

GIS Data Agent 不应被定义为“给传统时空数据中台加一个聊天入口”，也不应被定义为“以 GWM 为中心、外围数据能力按需补齐的研究系统”。正确的产品定义是：

> 以传统时空数据中台完整的数据生产与运营能力为下限，以开放可配置的湖仓和轻量存算一体架构为数据底座，以统一元数据和统一调度为控制脊柱，以 DataOps 与 AgentOps 为双运营闭环，以 Human/Agent 双入口降低复杂度，以地理空间运营本体连接数据、业务对象和行动，并以 GWM 提供可验证的状态理解、后果推演和规划能力的新一代地理空间智能 Data Platform。

相比 v3.0，真正的进步不只是增加 LLM、Agent、MMFE 或 GWM，而是完成五个层次的升维：

1. **从功能菜单到可执行数据产品**：把规划、源、模型、任务、质量、权限、服务、SLO、成本和生命周期收束为版本化 `DataProductSpec/DataProductVersion`。
2. **从分散工具到双控制面**：统一元数据中心管理“是什么、谁负责、能否使用、影响谁”；统一调度中心管理“何时运行、由谁执行、产物是什么、失败如何恢复”。
3. **从项目交付到持续运营**：DataOps 管数据产品的构建、发布、观测、事故和重放；AgentOps 管 Agent bundle 的评测、灰度、安全、预算、工具副作用、回滚和反馈。
4. **从人机分离到双入口同构**：可视化、SQL、Notebook、API/CLI 与 Agent 共用 typed definition、changeset、Run、Artifact、Policy 和 Audit，而不是维护两套平台。
5. **从“回答数据问题”到“理解状态并评估行动”**：LLM 负责语言、意图、解释和候选计划；GWM 负责状态、行动、转移、约束、不确定性和反事实推演；确定性控制面负责执行和治理。

但必须明确：**这些是目标架构的进步，不等于当前产品已经全面实现。** 当前 GIS Data Agent 在 Agent、标准/语义、GIS 专业工具、MMFE 和 GWM 研究上已经形成明显特色；在统一接入、湖仓生产链、数据开发工作台、统一元数据、统一调度、DataOps、AgentOps、服务运营、HA/DR 和跨云认证上仍存在从“组件”到“平台闭环”的距离。

### 0.2 全球对标结论

世界上没有一个平台与 GIS Data Agent 的目标形态完全重合。它处在五类平台的交叉点：

- **Databricks、Snowflake、Microsoft Fabric、Google Cloud、AWS**：代表通用数据与 AI 基础设施规模、湖仓/数仓、治理和云生态。
- **Palantir Foundry + Ontology + AIP + Apollo**：代表从数据、运营本体、AI 到真实行动和生产运维的完整闭环，是最重要的整体架构对标物。
- **Esri、CARTO、FME**：代表 GIS 生态、空间分析、空间数据云原生处理和空间数据集成的专业成熟度。
- **Collibra、Atlan、Informatica、DataHub、OpenMetadata**：代表治理、active metadata、catalog、lineage 和数据协作的深度。
- **Google Earth Engine、Microsoft Planetary Computer、NVIDIA Earth-2 及各类 GeoFM**：代表地球观测、地球系统建模、空间基础模型和大规模时空计算的邻近方向，但通常不是完整 Data Platform，也不自动构成 action-conditioned world model。

因此 GIS Data Agent 不应在“通用云数仓吞吐量”“全套 GIS 软件品类”“通用企业实施规模”上正面复制领先者。可持续的位置应当是：

> **开放可部署的数据平台底座 + DataOps + AgentOps + 地理空间运营本体 + 证据约束行动系统 + action-conditioned GWM。**

### 0.3 未来 5～10 年核心判断

未来数据平台将依次经历：数据资产化、数据产品化、Agent 化、运营本体化、状态与行动模型化。5～10 年后，领先平台的核心对象不再只是表、文件、pipeline 和 dashboard，而会是：

```text
现实对象及其状态
  + 数据与证据
  + 可执行行动
  + 约束与权限
  + 状态转移与不确定性
  + 行动后的真实结果和反馈
```

GIS Data Agent 有机会提前占据这个方向，但护城河不会来自“接入了多少模型”或“Agent 数量”，而来自长期积累的：受治理时空数据产品、空间运营本体、行动-结果轨迹、证据边界、可回放实验、跨环境可靠运营和真实业务反馈。

---

## 1. 评审方法与边界

### 1.1 三种状态必须分开

本报告对 GIS Data Agent 和竞品统一采用以下状态，防止目标、原型和成熟产品混写：

| 状态 | 定义 |
|---|---|
| 已产品化 | 有正式产品入口、稳定合同、生产生命周期和公开证据 |
| 局部可用/预览 | 有实质能力，但适用范围、SLA、治理或闭环不完整 |
| 目标架构 | 已形成明确设计和 Roadmap，尚不能作为当前能力销售 |
| 未发现公开证据 | 不能因宣传语、演示或相邻能力而推断存在 |

### 1.2 传统平台不是照抄模板，而是能力下限

v3.0 已经覆盖从规划到运营的完整任务链，价值在于完整性；它的问题主要是模块多、配置重复、专业门槛高、上下文割裂、设计与运行容易漂移。本次基线不是按目录和功能名称推断，而是建立在原文正文、表格以及功能、技术、数据、安全、汇聚、开发、服务、元数据等关键架构图的完整复审之上。GIS Data Agent 必须保留用户结果，消除操作负担，并把系统提升为可持续演化的平台。

### 1.3 “更强大”必须可度量

下一代平台不能只用功能数或模型参数证明进步，至少应使用以下指标：

- 从需求到首个可信数据产品的时间；
- 配置步骤、跨模块跳转次数和重复字段数；
- 首跑成功率、平均恢复时间、自动重放成功率；
- 数据合同/质量门覆盖率、血缘完整率和变更影响命中率；
- Agent 建议采纳率、人工修正率、越权/高风险拦截率；
- 结论证据覆盖率、可复现率、预测校准度和行动后结果回收率；
- 数据产品复用率、SLO 达标率、单位任务成本和消费者价值。

---

## 2. v3.0 时空数据中台的真实能力基线

从原始详细设计看，v3.0 不是一个简单数据目录或 GIS 门户，而是完整的传统时空数据生产平台：

```text
数据规划
 -> 多源接入与批/流/CDC/文件汇聚
 -> ODS/DWD/DWS/ADS 与湖仓/数据库存储
 -> 关系/维度/空间模型
 -> 画布/SQL/Python/Notebook 开发
 -> 试运行/发布/依赖/调度
 -> 质量/标准/安全/审批/消息/日志
 -> 元数据/血缘/检索/资产目录
 -> 数据分发/API/GIS 服务
 -> 智能问数/2D/3D/一张图
 -> Compose/Kubernetes/HA/运维交付
```

这意味着 GIS Data Agent 的基础门槛不是“能对话、能查 PostGIS、能调用若干 GIS 工具”，而是能在更低操作复杂度下完成上述整条生产链。

---

## 3. GIS Data Agent 相比 v3.0 的全面进步

### 3.1 总体架构升维

目标架构应形成以下稳定分层：

```text
Human + Agent Experience
Discover | Build | Operate | Govern | Map/2D/3D | API/CLI | MCP/A2A
                              |
                 shared typed definitions / changesets
                              |
+-----------------------------+------------------------------+
| Unified Metadata Control Plane                             |
| identity/version | catalog/search | contract | ontology    |
| owner/policy | quality | lineage/impact | SLO/cost/usage   |
+-----------------------------+------------------------------+
                              |
+-----------------------------+------------------------------+
| Unified Orchestration & Job Control Plane                  |
| definition | trigger | DAG/run/attempt | lease/heartbeat   |
| retry/cancel/replay | artifact/event | approval handoff    |
+-----------------------------+------------------------------+
                              |
                    executor/provider contract
                              |
+-----------------------------+------------------------------+
| Data Production and Execution                              |
| ingest | profile | standardize | model | MMFE | aggregate  |
| DuckDB | PostGIS | Spark/Sedona | Flink | cloud compute    |
+-----------------------------+------------------------------+
                              |
+-----------------------------+------------------------------+
| Configurable Storage, Table, Catalog and Serving           |
| MinIO + Iceberg | ADLS/S3/cloud lake | PostGIS | DuckDB    |
| STAC/OGC/MVT/raster/API/AI context projections             |
+-----------------------------+------------------------------+
                              |
          Data Products | Operational Ontology | GWM
```

其中，元数据控制面和调度控制面是整个系统的“控制脊柱”；Spark、Flink、PostGIS、DuckDB、MinIO、Azure 等只是可替换执行与存储能力。Agent 和 GWM 不能绕过控制面直接形成新的隐式权威源。

### 3.2 逐能力域对比

| 能力域 | v3.0 传统方式 | GIS Data Agent 的目标进步 | 当前必须承认的缺口 |
|---|---|---|---|
| 产品入口 | 门户、工作区和多个功能菜单 | Discover/Build/Operate/Govern 四工作面，Agent 读取当前上下文 | 入口和对象仍分散，尚未形成统一工作台 |
| 数据规划 | 文档、人工设计、分层配置 | `DataProductBlueprint` 把领域、owner、层级、合同、质量、安全、SLO、成本变成可执行规范 | Blueprint、实际资源与运行持续对账尚未闭环 |
| 数据源与汇聚 | 多向导配置批量、实时、CDC、大文件 | Agent 探测源、profiling、推断 PK/watermark/CRS，生成可审查 `SyncDefinition` | connector certification、删除语义、schema drift、断点恢复不足 |
| 湖仓与分层 | ODS/DWD/DWS/ADS，Iceberg、对象存储、Spark/Flink | 统一逻辑分层不绑定具体引擎；placement、retention、compaction、snapshot、serving 成为策略 | 默认技术组件存在，但生产级 lakehouse vertical slice 未完全产品化 |
| 存储/计算 | 平台预置为主 | storage/table/catalog/compute provider 分离，可配置云、私有化和轻量 profile | provider capability、兼容矩阵、跨云认证仍需建设 |
| 数据建模 | 关系、维度、空间模型与版本 | 标准、本体、业务术语、真实 profile 双向驱动模型；GIS identity/CRS/topology 一等化 | 模型 diff、兼容性、迁移、部署回滚链不完整 |
| 数据开发 | 画布、SQL、Python、Notebook 多工具 | 所有入口编辑同一个 typed `JobDefinitionVersion/TaskGraph` | typed operator、preview sandbox、Notebook 生产固化不足 |
| 调度 | 定时、依赖、运行监控 | 统一 Run/Attempt/Lease/Artifact/Event，跨 batch/stream/Agent/GWM 编排 | 多个运行体系并存，缺统一业务状态和恢复语义 |
| 审批 | 独立流程中心 | 审批与调度区分领域状态机，但共享身份、事件、changeset 和审计 | HITL 对话与正式审批仍需严格分界 |
| 元数据 | 采集、登记、检索、表/字段血缘 | 一个 ResourceURN/Version 贯穿数据、任务、服务、模型、prompt、tool、GWM；active metadata 自动发现漂移和影响 | authority source、字段级运行血缘、影响闭环未统一 |
| 质量 | 规则、方案、任务、评分和问题面板 | 质量成为 layer transition 和 product publish 的机器门，形成 Issue-Remediation-Recheck-SLO | 规则存在但尚未成为统一发布门和事故闭环 |
| 安全 | 分级分类、脱敏、表/字段/时空权限 | user/service/Agent/executor 统一身份，resource/row/column/spatial/temporal/action/purpose 组合策略 | 入口、工具链、缓存和派生数据的一致执行仍有缺口 |
| 数据资产 | 目录、标签、申请、分发、统计、一张图 | `DataProductVersion` 具备 owner、合同、质量、SLO、成本、消费者和退役策略 | 资产、Run、服务和消费者的生命周期仍未完全统一 |
| 数据/GIS 服务 | API、二维/三维/影像/目录服务 | 由 DataProductVersion 投影为 API、OGC/STAC、MVT、COG、Agent context、AI/GWM 产品 | 缺统一 `ServiceDefinition`、发布、配额、版本、回滚和消费观测 |
| 分析与地图 | 智能问数、大屏、2D/3D 一张图 | 查询、图表、地图和 Agent 结论绑定数据版本、时空范围、口径、证据和权限，可保存与复现 | 当前多个体验仍是专项页面或旁路结果 |
| 部署运维 | Compose/K8s/HA、容量、安全、兼容 | 同一配置 schema 支持开发、试点、K8s、私有云、云 provider；SLO、备份、恢复和升级成为产品能力 | HA/DR、升级回滚和认证矩阵缺完整生产证据 |
| 扩展生态 | API/算子扩展 | connector/operator/rule/service projection/skill/tool/domain pack 共用 typed manifest、权限、资源、版本和测试 | 现有插件、tool、MCP、skill 注册语义仍分散 |
| DataOps | 已有开发、调度、质量、发布等结果，但未形成统一闭环 | 数据产品从 spec、CI、promotion 到 SLO、incident、replay 和新版本的持续运营 | 当前只能称组件存在，不能称完整 DataOps 产品 |
| AgentOps | 传统平台无 | Agent/Prompt/Model/Tool/Skill/Policy/Context 作为 bundle 做评测、灰度、线上 verdict、预算、安全事故和回滚 | Prompt registry、trace、eval 等存在，但 canary/rollback/online eval 未闭环 |
| MMFE/Data for AI | 多模态能力分散 | 矢量、栅格、影像、文本、规则、图、时序对齐为可版本化 AI Dataset/Context Product | 必须从专项处理链提升为受治理 DataProduct projection |
| GWM | 无真正世界模型内核 | 用 state/action/transition/uncertainty/evidence 表示现实世界并进行反事实推演与规划 | 仍需真实 action-outcome 数据、跨时空验证和生产门控 |

### 3.3 存储与计算架构的实质进步

GIS Data Agent 不应把“支持 MinIO、Spark、Flink、PostGIS、DuckDB、Azure”理解成列出一组技术名称，而应定义一套稳定的 provider contract。

#### 逻辑数据分层

```text
Landing/Raw
 -> ODS/Bronze
 -> DIM + DWD/Silver
 -> DWS/Gold
 -> ADS/Serving
 -> AI Dataset / Agent Context / GWM State Projection
```

逻辑层是数据合同和治理语义，不等于物理 bucket 或数据库 schema。不同部署 profile 可以选择不同物理实现，但不得改变版本、质量、血缘、Run、Artifact、发布和回滚合同。

#### 推荐 provider profile

| Profile | 存储/表格式 | 计算 | Serving | 适用场景 |
|---|---|---|---|---|
| 默认开放湖仓 | MinIO + Iceberg + catalog | Spark/Sedona 批、Flink 流 | PostGIS、STAC、MVT、COG/API | 私有化、中大型数据、可移植部署 |
| Azure 云 | ADLS/云湖存储 + 认证表/catalog 能力 | Azure 对应批流/SQL/AI 计算 adapter | 云原生服务 + GIS projection | 已采用 Azure 的大型组织 |
| 轻量一体 | PostGIS 或 DuckDB/Spatial | 本地 SQL/GIS 执行 | 同库查询、文件/API | 单机、边缘、试点、小中数据集 |
| 混合/联邦 | 湖仓保留权威数据，PostGIS/云仓作 projection | 按任务 placement | 多区域/多云 serving | 数据主权、跨域协作、渐进迁移 |

provider adapter 至少要显式声明：事务/快照、schema evolution、空间类型、batch/stream、CDC、partition、compaction、time travel、权限下推、成本、区域、加密、备份恢复和 SLA。URI 可替换不等于引擎可替换。

### 3.4 DataOps 与 AgentOps 是下一代平台的双运营闭环

```text
DataOps
DataProductSpec -> Build/CI -> Contract/Quality/Security
 -> Promotion/Release -> DataRun -> Observe/SLO
 -> Incident/Remediation -> Replay/New Product Version

AgentOps
AgentSpecBundle -> Eval/Safety/Cost -> Approval/Promotion
 -> Shadow/Canary -> AgentRun/ToolCall -> Online Verdict
 -> Incident/Rollback/Feedback -> New AgentSpecVersion
```

两者共用 ResourceURN、不可变 Version、SubjectContext、Metadata、Orchestration、Policy、Approval、Artifact、Audit、SLO、Incident、ChangeSet 和 transactional outbox；但 `DataRun` 与 `AgentRun` 必须保留不同状态机。数据失败关注完整性、时效、重放和消费者影响；Agent 失败还关注推理轨迹、工具副作用、越权、预算、幻觉、人工接管和模型漂移。

### 3.5 Human/Agent 双入口比“全对话化”更先进

真正好用不是隐藏一切，而是让用户在需要时看见正确的结构：

- Agent 把自然语言转成 draft plan、DAG、contract、policy、quality rule 和 changeset；
- 画布/SQL/Notebook 展示并允许专业人员编辑同一个定义；
- 高风险推断显示证据、冲突和不确定性；
- 执行由确定性控制面完成；
- 结果、Run、Artifact、lineage、审批和回滚可复现；
- 用户可以从对话进入结构化工作面，也可以从地图、表、DAG 反向召唤 Agent。

这比传统菜单更简单，也比“黑盒聊天机器人代替平台”更可靠。

---

## 4. 全球对标版图：谁真正与 GIS Data Agent 竞争

### 4.1 对标应分层，而不是做一张扁平竞品表

| 层级 | 代表平台 | 与 GIS Data Agent 的关系 |
|---|---|---|
| 综合 Data/AI Platform | Databricks、Snowflake、Microsoft Fabric、Google Cloud、AWS、Dremio | 对标湖仓/数仓、批流、治理、AI、开放性、云生态和工程成熟度 |
| 数据到行动平台 | Palantir Foundry/Ontology/AIP/Apollo | 最接近整体目标；对标运营本体、Action、AI 治理、应用和运维闭环 |
| GIS/空间数据平台 | Esri ArcGIS、CARTO、Safe FME | 对标 GIS 专业深度、空间数据集成、地图服务、分析和生态 |
| Governance/DataOps | Informatica、Collibra、Atlan、DataHub、OpenMetadata、Dagster/Airflow/Prefect | 对标元数据、lineage、治理协作、数据产品、编排和运营实践；多数不是完整平台 |
| 地球智能/GWM 邻近物 | Earth Engine、Planetary Computer、NVIDIA Earth-2、GeoFM 体系 | 对标地球观测、空间基础模型、模拟和时空计算；通常不具备完整企业 Data Platform 和行动闭环 |

### 4.2 核心平台能力矩阵

符号说明：`强` 表示正式产品的主要能力；`中` 表示具备但不是最深差异化；`局部` 表示预览、限定场景或需组合产品；`弱/无证据` 表示不是其主要公开能力，不能推断为不存在任何内部或合作能力。

| 平台 | 湖仓/数仓与批流 | Metadata/DataOps | Agent/AgentOps | 运营本体/行动 | GIS 原生 | WM/模拟 | 私有化/开放性 |
|---|---|---|---|---|---|---|---|
| Palantir Foundry+AIP | 强 | 强 | 强，生产治理领先 | **强，核心优势** | 中到强 | 局部，非公开通用 GWM | 强私有部署，平台专有性高 |
| Databricks | **强，核心优势** | 强 | 强化中，AI/Agent 产品丰富 | 中，偏数据/AI 语义与应用 | 中，依赖开放生态和空间库 | 局部，无通用 action-conditioned WM 证据 | 多云，开放格式较强 |
| Snowflake | **强，核心优势** | 强 | 强化中，Cortex 系列 | 中，偏语义/应用/数据协作 | 中，空间 SQL 与生态 | 弱/无证据 | SaaS 多云，平台绑定较强 |
| Microsoft Fabric | 强，一体化 SaaS | 强，与 Purview/OneLake 协同 | 强化中，Copilot/Data Agent 方向 | 中，依赖 Power Platform/Dynamics/Azure | 中，需 Azure/Esri 等组合 | 局部，Planetary Computer 非行动 WM | SaaS/Azure 生态绑定 |
| Google BigQuery/BigLake | 强 | 强，Dataplex 等 | 强化中，Gemini/Agents 组合 | 中，需 Google Cloud 多产品组合 | 中到强，BigQuery GIS/Earth Engine | 局部，地球观测/GeoAI 强 | 云服务为主，开放格式中等 |
| AWS 数据/AI组合 | 强但产品分布较多 | 强，需多服务组合 | 强化中，Bedrock/Agent 体系 | 中，需应用层组装 | 中，合作生态/自建为主 | 局部，仿真和行业服务分散 | 云生态广，集成复杂 |
| Esri ArcGIS | 中，非通用湖仓核心 | 中，GIS catalog/治理强 | 局部，GeoAI/助手持续增强 | 中，GIS 对象/工作流强 | **强，核心优势** | 局部，空间分析/预测不等于 WM | Enterprise 可私有化，生态专有性较高 |
| CARTO | 中，云数仓原位分析 | 中 | 局部 | 弱到中 | **强，云原生空间分析** | 弱/无证据 | 对主流云仓开放，业务层平台化 |
| Safe FME | 弱，非存储平台 | 中，数据集成/流转强 | 局部 | 弱 | **强，格式与空间 ETL** | 无证据 | 部署灵活，连接器/转换生态强 |
| Earth Engine | 专用大规模 EO 计算 | 中，数据目录强 | 局部 | 弱 | **强，地球观测** | 中，分析/预测为主 | 托管服务为主 |
| Planetary Computer | 专用 EO 数据生态 | 中，STAC/开放数据强 | 弱 | 弱 | 强 | 局部 | 开放数据和标准较强，非完整平台 |
| Collibra/Atlan/Informatica | 非核心或依赖组合 | **强，核心优势** | 局部，治理助手增强 | 中，治理语义而非完整 Action 系统 | 弱到中 | 无证据 | 企业集成强，产品差异大 |
| DataHub/OpenMetadata | 非计算平台 | **强，开放元数据** | 局部 | 弱到中 | 弱到中 | 无证据 | **开源开放性强** |
| GIS Data Agent 目标态 | 强，可配置湖仓+轻量 | **强，双控制面+DataOps** | **强，独立 AgentOps** | **强，空间运营本体+Action** | **强** | **强，GWM 核心差异** | **多 profile、私有化、开放合同** |
| GIS Data Agent 当前态 | 局部 | 组件/目标架构 | 组件丰富、闭环不足 | 原型/目标架构 | 局部到强，专业模块丰富 | 研究与专项原型领先 | 私有化基础存在，认证不足 |

### 4.3 主要对标物详细分析

#### 4.3.1 Palantir：最重要的整体架构对标物

Palantir 的优势不只是“能接数据和调用 LLM”，而是把 Foundry 数据链、Ontology 的 object/property/link/action/function、动态安全、AIP、业务应用和 Apollo 运维连接成生产系统。其核心启示是：**数据只有进入可操作对象和真实业务行动，才完成从分析到运营的跃迁。**

GIS Data Agent 应学习：

- operational ontology，而不是只做知识本体或术语图谱；
- Object-Action-Capability 的统一契约；
- 权限下沉到对象、属性、关系、Action、Function 和 AI context；
- typed SDK/应用构建层；
- ontology/action diff、跨环境发布、灰度、回滚和长期运维。

GIS Data Agent 的潜在超越点：自然资源数据标准、空间身份与拓扑、CRS、时空证据、遥感与多模态、规则约束、规划推演、GWM 以及更开放的 provider/部署合同。但当前在平台完整性、动态安全、应用生态、开发者体验和生产运营上仍落后。

#### 4.3.2 Databricks：数据与 AI 工程底座对标物

Databricks 的核心强项是 Lakehouse、开放表格式生态、统一批流/SQL/AI 工程、治理目录、Notebook/开发者体验、ML/GenAI 生命周期和多云规模。其 Data Intelligence/Genie/Agent 方向说明通用数据平台正在把自然语言、语义和 Agent 直接嵌入数据工程与消费。

GIS Data Agent 不应复制其通用计算平台规模，而应确保：

- Iceberg/开放格式和 Spark/Flink/PostGIS/DuckDB provider 合同真正可替换；
- Notebook、SQL、DAG、Agent 共用生产合同；
- Data for AI、模型/Agent lineage、eval、serving 和成本可治理；
- 地理空间能力不是外部库拼装，而是 metadata、quality、lineage、ontology、serving 的一等语义。

Databricks 的公开定位仍主要是数据与 AI 平台；其 AI/Agent 能力不能直接等同于完整的空间运营本体或 GWM。

#### 4.3.3 Snowflake：托管数据云与 AI 消费对标物

Snowflake 的强项是低运维的数据云、跨组织数据共享、治理、SQL/应用生态以及 Cortex AI 能力。它代表另一条路线：用户无需管理复杂基础设施，数据、应用和 AI 在托管平台中协同。

GIS Data Agent 的启示是：

- Agentic 体验必须显著降低部署、扩容、权限和数据共享复杂度；
- 数据产品应具备稳定消费合同、共享策略和成本可见性；
- AI 助手不能只生成 SQL，还应受语义层、策略、证据和运行历史约束。

GIS Data Agent 的差异应落在私有化/边缘、多引擎、GIS 专业深度、行动闭环和 GWM，而不是再做一个通用云数仓。

#### 4.3.4 Microsoft Fabric：一体化工作负载与 Agent 入口对标物

Fabric 通过 OneLake、数据工程、仓库、实时智能、BI、数据科学和治理生态强调 SaaS 一体化。其 Copilot/Data Agent 路线说明“Agent 成为跨工作负载入口”正在进入主流。

GIS Data Agent 应对标它的一体化体验，但不能把统一入口误解为统一实现：

- 一个资源身份和权限模型贯穿湖、仓、实时、BI、AI 和 GIS；
- 一个 workspace 能从发现进入构建、运营和消费；
- Agent 读取用户当前工作区、语义模型、权限和数据产品上下文；
- Azure storage/compute 通过 provider adapter 接入，而非硬编码成第二套架构。

Fabric 的 Planetary Computer 等相邻能力可以增强 EO 场景，但公开资料不能据此推断其已具备统一 action-conditioned GWM。

#### 4.3.5 Google Cloud：BigQuery、Earth Engine 与 Gemini 组合对标

Google 的优势来自 BigQuery/BigLake/Dataplex 的云数据能力、BigQuery GIS、Earth Engine 的大规模地球观测、Vertex AI/Gemini 的模型能力和丰富的地图生态。它在海量遥感、时空分析和 GeoAI 上是重要对标物。

GIS Data Agent 应学习大规模 EO 数据目录、就地计算、开放空间索引/格式、模型与地球观测结合；但要明确：Earth Engine 的时序分析、分类、预测或遥感基础模型不自动等于世界模型。GWM 还必须包含明确行动、状态转移、约束、不确定性、反事实、验证和真实 outcome。

#### 4.3.6 AWS：组合式云数据与 Agent 基础设施对标

AWS 通过 S3、Lake Formation、Glue、Athena/EMR、Redshift、SageMaker、Bedrock 等形成广泛组合。优势是基础设施广度、行业生态和部署选择，弱点是用户往往需要自行整合多个控制面。

GIS Data Agent 的启示是 provider contract 与 certification matrix 必须先于“支持某云”的宣传；同时产品体验应把多服务复杂度隐藏在 blueprint、policy、Run、SLO 和 cost 之下。

#### 4.3.7 Esri：GIS 专业能力和应用生态的首要对标物

Esri 的核心壁垒是完整 GIS 产品家族、空间分析、制图、影像、3D、实时、现场作业、行业模型、ArcPy/SDK 和长期用户生态。GIS Data Agent 即使拥有更先进的 Agent 和 GWM，也不能低估空间数据编辑、拓扑、坐标、制图表达、服务发布和行业工作流的产品深度。

GIS Data Agent 的竞争策略不是复制全部 ArcGIS，而是：

- 通过 ArcPy/MCP/OGC/STAC 等与现有 GIS 生态共存；
- 把跨引擎数据治理、数据产品、AgentOps、证据与行动推演做成更开放的控制层；
- 在自然资源/城市/农业/生态等重点域建立 GWM 和运营本体深度；
- 让结果可回写 Esri、PostGIS、云仓和业务系统，避免孤岛。

#### 4.3.8 CARTO：云数仓原位空间计算对标物

CARTO 的差异在于围绕主流云数据仓库进行空间分析、可视化和应用构建，尽量减少数据复制。它证明“空间分析应接近数据，而不是把所有数据搬入专有 GIS 存储”。

GIS Data Agent 应把 compute placement、federated query、spatial pushdown 和 serving projection 纳入 provider contract；其优势则应扩展到治理、AgentOps、行动本体和 GWM。

#### 4.3.9 Safe FME：空间数据接入与转换生态对标物

FME 的壁垒是海量格式/系统连接、复杂转换、自动化和成熟的空间 ETL 用户体验。GIS Data Agent 的 connector/operator 生态若不能覆盖真实世界的 CAD、BIM、遥感、文件、数据库、API、消息和行业格式，就无法达到传统平台的能力下限。

Agent 可以降低 FME 类流程的构建门槛，但不能替代确定性 reader/writer、schema mapping、坐标转换、错误隔离、断点恢复和认证测试。

#### 4.3.10 治理与 active metadata 平台：统一元数据中心的对标物

Collibra、Atlan、Informatica、DataHub、OpenMetadata 等说明元数据中心不应只是静态目录。下一代能力包括：自动采集、业务术语、owner/steward、字段血缘、质量、policy、使用热度、数据产品、事件、影响分析和协作处置。

GIS Data Agent 应特别增强两点：

1. 把空间范围、CRS、geometry、分辨率、时间覆盖、拓扑、地理适用性和空间 lineage 纳入统一元数据；
2. 将 data、pipeline、service、prompt、model、tool、Agent、evidence、GWM projection 放在同一个资源与版本图中，同时保留各自 authority source。

### 4.4 竞品普遍尚未解决的组合空白

基于公开产品边界，尚未看到一个成熟通用平台同时把以下能力做成统一产品：

- 开放可替换的湖仓、云和轻量存算一体 profile；
- 完整 DataOps 与独立 AgentOps；
- 空间原生 active metadata 和 operational ontology；
- 证据、规则、权限和人工审批约束的真实行动；
- vector/raster/text/time-series/event/rule 多模态统一状态；
- action-conditioned GWM、反事实推演、规划和 outcome 反馈；
- 私有化、云、边缘、跨域协作的一致合同。

这正是 GIS Data Agent 的战略窗口。但“组合空白”只代表机会，不代表已经形成产品优势；只有端到端可运行、可部署、可证明、可恢复，才是壁垒。

### 4.5 相比几个月前竞品分析，必须更新的判断

1. **NL2SQL 和 Copilot 已快速商品化**：主流数据平台都在把自然语言查询、代码生成、语义理解和数据助手嵌入产品。仅凭“能问数据、能生成 SQL、能调用工具”已经无法形成长期差异。
2. **竞争单元正在从模型变成受治理 Agent**：公开产品路线越来越强调 Agent framework、data agent、tool use、评测、权限和应用集成。GIS Data Agent 必须把 AgentOps 做成平台层，不能停留在 prompt registry、trace 和离线 eval。
3. **语义层重新成为核心**：为了让 Agent 得到一致口径并执行真实任务，catalog、semantic model、ontology、business object 和 policy 正从辅助能力变成控制层。统一元数据中心和 spatial operational ontology 因此比过去更紧迫。
4. **开放湖仓本身不再构成充分差异**：Iceberg、对象存储、批流一体和多云已经是主要平台的共同竞争面。GIS Data Agent 的优势必须来自可配置 profile 之上的 GIS 数据产品、行动合同、证据和 GWM。
5. **空间智能仍然是割裂市场**：通用数据平台增强空间 SQL 和 GeoAI，GIS 厂商增强云原生和 AI，地球观测平台增强基础模型与时空计算，但公开市场仍缺少统一的 DataOps + AgentOps + spatial action system + GWM 产品。这一窗口存在，但正在缩短。
6. **“World Model”一词正在泛化**：基础模型、数字孪生、天气/地球系统模拟和生成式视频都可能使用相近叙述。GIS Data Agent 必须用 state/action/transition/rollout/uncertainty/outcome 的工程合同守住定义，否则创新会被概念稀释。

---

## 5. GWM：GIS Data Agent 最具创新性的内核

### 5.1 GWM 在平台中的正确位置

GWM 不是替代数据库、湖仓、元数据、调度、GIS 引擎或 LLM 的万能组件。它应当是受治理数据产品的消费者和新的派生产品生产者：

```text
Governed DataProductVersion
 -> MMFE / State Builder
 -> GWM State + Action + Transition + Constraint Model
 -> Rollout / Counterfactual / Planner / Uncertainty
 -> Scenario Product + EvidenceBundle + Decision Proposal
 -> Human/Policy Approval
 -> Real Action
 -> Outcome Observation
 -> Replay / Calibration / New GWM Version
```

Data Platform 即使没有 GWM 也必须完整可用；GWM 只有建立在可靠数据、行动定义、真实反馈和治理闭环之上才有价值。

### 5.2 真正的 GWM 最小合同

| 合同 | 必须回答的问题 |
|---|---|
| `State` | 当前世界由哪些空间对象、属性、关系、时间状态和观测构成？ |
| `Action` | 谁在什么权限和约束下，可对哪些对象实施什么干预？ |
| `Transition` | 给定状态和行动，未来状态如何变化？ |
| `ExogenousContext` | 天气、宏观政策、市场、灾害等外生因素如何进入？ |
| `Constraint` | 法规、生态红线、物理规律、预算、容量和业务规则如何限制行动？ |
| `Uncertainty` | 数据缺失、模型误差、分布外输入和情景差异如何量化？ |
| `Evidence` | 每个状态、假设、规则和结论来自哪里，是否 observed/proxy/synthetic？ |
| `Rollout` | 多步行动如何产生轨迹，而不只是一次预测？ |
| `Objective` | 效益、风险、公平、成本、韧性等如何多目标权衡？ |
| `Outcome` | 真实行动后的结果如何回收、归因、校准和审计？ |

若只有遥感分类、时序外推、空间插值、变化预测或 LLM 生成情景，而没有明确 action、transition、constraint、uncertainty、rollout 和验证，就不应称为完整 GWM。

### 5.3 LLM-only 与 LLM+WM 双驱动的本质差异

| 任务 | LLM-only 系统 | LLM + GWM 系统 | 确定性控制面的职责 |
|---|---|---|---|
| 理解需求 | 强于语言、知识和意图解析 | LLM 解析，GWM 映射到可计算状态/行动 | 校验 schema、权限和作用域 |
| 查询与解释 | 可生成 SQL/工具计划和自然语言解释 | 可把结果放入时空状态和因果/转移语境 | 执行查询、保留版本与 lineage |
| 预测 | 依赖文本知识或调用外部模型，容易把 plausibility 当 probability | 用显式 transition/uncertainty 产生可评估预测 | 选择已批准模型和数据版本 |
| What-if | 常生成听起来合理的叙事 | 在行动、约束和状态模型中做 counterfactual rollout | 限制合法行动、预算和终止条件 |
| 多步规划 | 容易短视、状态漂移或忽略物理/政策约束 | Planner 在 GWM 中搜索并比较轨迹 | hard gate、审批、补偿和回滚 |
| 证据 | 可引用文档，但难保证结论与状态转移一致 | EvidenceBundle 绑定状态、假设、模型版本和结果 | 验证来源、完整性和访问策略 |
| 学习反馈 | 主要积累对话、偏好和工具成功率 | 额外积累 action-outcome trajectory 和校准误差 | AgentOps/GWM Ops 控制晋级和回退 |
| 安全 | prompt guardrail 容易被高估 | WM 仍不能代替安全，风险可在 rollout 中暴露 | Policy/HITL/Action gate 才有最终权威 |

双驱动不是让 LLM 与 GWM 各自输出一个答案再投票，而是职责分工：

- LLM：语言、知识检索、意图分解、候选假设、解释和人机协作；
- GWM：状态估计、动力学、行动后果、反事实、多步规划和不确定性；
- 控制面：身份、权限、合法状态转换、工具执行、审批、预算、记录和恢复。

### 5.4 GWM 的独特护城河

模型架构本身很难形成 10 年壁垒，真正难复制的是：

1. **空间运营本体**：真实对象、空间关系、规则、Action 和业务状态的长期积累；
2. **行动-结果轨迹**：规划、审批、调度、治理或干预后的实际 outcome，而不只是历史观测影像；
3. **证据分级**：observed、derived、proxy、simulated、synthetic 的边界和适用条件；
4. **验证体系**：时间/空间 holdout、历史回放、跨区域迁移、因果校准、hard constraint 和人工审计；
5. **闭环部署**：scenario -> approval -> action -> observation -> replay 的生产链；
6. **垂直域包**：自然资源、城市、农业、生态、水利、基础设施各自的 state/action/constraint/metric pack。

### 5.5 GWM 必须通过的成熟度阶梯

| 等级 | 能力 | 可对外声称 |
|---|---|---|
| G0 数据/可视化 | 统一时空数据和地图 | 时空数据产品，不称世界模型 |
| G1 状态估计 | 多模态 state、缺失和不确定性 | 世界状态表征 |
| G2 被动预测 | 在无干预条件下预测未来 | 时空预测模型 |
| G3 条件行动模型 | 显式 action-conditioned transition | 初级世界模型 |
| G4 反事实与约束规划 | 多步 rollout、counterfactual、hard gate、校准 | 可验证规划推演系统 |
| G5 闭环行动学习 | 真实 action-outcome 回收、在线监测、受控更新 | 生产级 GWM |
| G6 跨域组合世界模型 | 多尺度、多域、跨模型接口和联邦验证 | 地理空间世界模型平台 |

当前各专项成果应按这套证据阶梯登记，不能用统一的“GWM 已完成”掩盖不同 kernel 的成熟度差异。

---

## 6. 未来 5～10 年趋势与 GIS Data Agent 战略

### 6.1 趋势一：Data Platform 从资产管理走向数据产品运营

未来 1～3 年，表、文件和 pipeline 仍然重要，但平台的稳定交付单元会转向有 owner、contract、SLO、quality、policy、cost、consumer 和生命周期的 Data Product。DataOps 不再只是 CI/CD 工具集合，而是产品可靠性体系。

**GIS Data Agent 要求**：先把 `DataProductSpec -> Version -> Run -> Artifact -> SLO -> Incident -> Replay` 做成主链，GWM、Agent 和 GIS 服务都从这条链消费。

### 6.2 趋势二：Agent 将成为入口，但确定性控制面不会消失

未来 2～4 年，自然语言会成为发现、开发、治理和运营的重要入口，数据工程将出现大量自主 proposal、修复建议和任务生成。但生产环境不会接受“LLM 直接修改一切”。typed contract、policy、approval、sandbox、eval、budget、audit 和 rollback 会更加重要。

**GIS Data Agent 要求**：Agent 的默认输出是可审查 changeset；低风险动作可策略化自动执行，高风险动作必须模拟影响并审批。

### 6.3 趋势三：AgentOps 将成为与 DataOps 同等级的平台层

随着 Agent 调用真实数据和业务系统，prompt/model/tool 单项版本管理远远不够。行业会形成 bundle 级评测、在线 verdict、灰度、轨迹观测、成本预算、越权检测、安全事故、人工接管和回滚标准。

**GIS Data Agent 要求**：利用已有 registry、eval、trace、feedback 基础，收束为完整 AgentOps，而不是继续增加互不连通的 Agent 组件。

### 6.4 趋势四：语义层将从“指标解释”升级为 Operational Ontology

未来 3～5 年，领先平台会把数据语义连接到真实对象、关系、事件、状态和行动。语义层不只帮助生成 SQL，还会驱动权限、业务应用、Agent 工具、审批和写回。

**GIS Data Agent 要求**：在领域/标准/治理本体之上建立 spatial operational ontology，统一 Object-Action-Capability；几何和海量时序仍留在合适引擎中，本体保存身份、关系、语义和行动合同。

### 6.5 趋势五：多模态时空状态将成为 AI 的关键数据产品

未来 3～6 年，文本 RAG 不足以支撑真实空间决策。矢量、栅格、影像、时序、传感器、事件、文档、法规和业务行动需要共同形成可版本化 state/evidence bundle。

**GIS Data Agent 要求**：MMFE 从旁路算法提升为平台级 projection；明确时间对齐、空间对齐、分辨率、观测误差、来源和派生 lineage。

### 6.6 趋势六：从 Copilot 到 Action System，再到 World Model

未来 4～10 年的演进主线很可能是：

```text
问答/生成
 -> 工具调用 Agent
 -> 受治理 Action System
 -> 状态与行动的数字孪生
 -> action-conditioned World Model
 -> 多步规划与闭环学习
```

LLM 会继续重要，但无法独自承担物理、空间、长期状态和行动后果建模。世界模型也不会替代 LLM，而会成为 Agent 的“可推演环境”和决策校验器。

### 6.7 趋势七：开放标准、主权部署与跨域联邦会重新重要

政府、自然资源、城市和关键基础设施不可能全部进入单一公有云。未来平台要同时支持云、私有化、边缘、离线和跨域协作；数据主权、模型主权、审计和供应商锁定将影响采购。

**GIS Data Agent 要求**：以 Iceberg/Parquet、STAC、OGC、SQL、MCP/A2A、OpenTelemetry 等开放合同为优先；provider capability 和认证测试保证跨环境一致性。

---

## 7. 2026-2036 分阶段路线

### 阶段 A：2026-2027，补齐平台主干并达到 v3.0 能力下限

目标不是继续增加孤立智能功能，而是完成第一条生产级垂直链：

```text
Source/Sync
 -> Landing/ODS/DWD/DWS/ADS
 -> DataProductVersion
 -> Quality/Policy/Lineage
 -> Schedule/Run/Replay
 -> API/STAC/Map/Agent Context
 -> SLO/Incident/Recovery
```

必须交付：统一 ResourceURN/Version、统一元数据中心、统一调度中心、默认 MinIO+Iceberg+Spark/Sedona+Flink profile、PostGIS/DuckDB 轻量 profile、DataOps 最小闭环、结构化工作台和 connector certification。

退出条件：选定一个自然资源真实场景，在无开发团队手工介入的情况下完成接入、分层、建模、发布、服务、故障恢复和审计；与 v3.0 逐项验收，任务覆盖不低于旧平台。

### 阶段 B：2027-2028，形成真正的 Agentic Data Platform

必须交付：Human/Agent 双入口、AgentSpecBundle、离线/在线 eval、shadow/canary/rollback、tool side-effect policy、预算、人工接管、Agent incident、DataOps/AgentOps 联合 lineage；Agent 能生成并修订 typed changeset，而不是只调用零散工具。

退出条件：在真实数据工程与治理任务上证明显著减少配置步骤和完成时间，同时没有降低合规、可复现和恢复能力。

### 阶段 C：2028-2030，空间运营本体和数据到行动闭环

必须交付：ObjectType/Property/Link/Event/Action/Function/Policy/ChangeSet；GIS object identity、时空状态、动态安全、审批、写回、补偿和 OSDK-like SDK；数据产品、地图应用、Agent 和业务系统共享 Action 合同。

退出条件：至少 3 个垂直域形成从发现问题、生成方案、审批、执行到结果回收的生产闭环。

### 阶段 D：2030-2033，GWM 从专项模型升级为平台能力

必须交付：统一 GWM contracts、model registry、state/evidence product、action/outcome ledger、rollout service、planner、uncertainty、跨区域验证、GWM Ops；自然资源、城市、农业、生态或水利形成可组合 domain kernel。

退出条件：G4 级以上 kernel 在多区域、跨时间 holdout 和真实行动回收中通过门槛；能够证明相对传统模拟器、纯预测模型和 LLM-only Agent 的增益。

### 阶段 E：2033-2036，跨域世界状态与行动平台

必须交付：跨尺度对象和状态对齐、多 GWM 组合、联邦数据/模型协作、云边协同、长期规划、实时事件响应、验证市场和领域扩展生态。

退出条件：平台的核心商业价值来自可验证的“状态-行动-结果”闭环，而不是项目定制、单一模型或单一数据源。

---

## 8. 必须坚持的战略取舍

### 8.1 必须做

1. 把 v3.0 的完整用户任务覆盖作为 release gate，而不是参考资料。
2. 优先统一元数据和调度控制面，停止继续产生新的旁路运行体系。
3. 建立 DataProductVersion、DataRun、AgentRun、Action、Evidence 和 GWM Projection 的稳定合同。
4. 用一个真实领域纵向打穿默认湖仓、轻量 profile、DataOps、AgentOps、GIS 服务和 GWM。
5. 把 connector/provider/operator/tool/domain pack 做成可认证生态。
6. 建立 action-outcome ledger，这是 GWM 未来最稀缺的数据资产。
7. 用 evidence grade 和 maturity gate 管理所有“智能”能力的对外表述。

### 8.2 不应做

1. 不做 Databricks/Snowflake 的通用基础设施规模复制品。
2. 不复制 Esri 的全部桌面、服务器和行业应用品类。
3. 不把 Palantir 的专有实施模式原样搬入产品。
4. 不把对话作为唯一入口，不让 Agent 绕过合同、权限、审批和审计。
5. 不把 foundation model、遥感预测、数字孪生可视化或 LLM 情景叙述直接包装为 GWM。
6. 不以 Agent 数量、工具数量、页面数量或模型参数作为平台成熟度指标。
7. 不在基础平台闭环未完成时，让 GWM 研究持续吞噬全部主线资源。

---

## 9. 核心风险与治理要求

| 风险 | 后果 | 治理措施 |
|---|---|---|
| 目标架构被当成当前产品 | 销售承诺和交付失真 | 所有能力标注 current/partial/target/evidence |
| GWM 挤压基础平台建设 | 研究领先但无法形成可用平台 | Roadmap 资源配额和能力下限 release gate |
| 多运行时继续分裂 | 无法统一调度、血缘、恢复和成本 | 新 executor 必须接统一 Run/Artifact contract |
| 元数据成为另一个静态目录 | 无法驱动质量、权限和影响分析 | active metadata 事件、authority、SLO 和修复闭环 |
| Agent 直接执行高风险动作 | 越权、误写、不可恢复 | changeset、simulation、policy、HITL、idempotency、compensation |
| World model 缺真实行动数据 | 只能做相关性预测和演示 | action-outcome ledger、实验设计、跨时空验证 |
| 云 provider 名义支持 | 项目中暴露兼容和恢复问题 | capability matrix、版本认证、故障注入和恢复测试 |
| 过度平台化 | 长期没有垂直价值 | 以自然资源/城市等真实产品纵向驱动平台抽象 |

---

## 10. 建议的北极星指标

### 平台指标

- 传统 v3.0 核心任务覆盖率：首个正式版本达到 100%；
- 一个新源到首个受治理数据产品的中位时间；
- Resource/Version、Run/Artifact、字段级 lineage 覆盖率；
- 数据产品 SLO 达标率、MTTR、重放成功率和破坏性变更拦截率；
- 跨 MinIO/Iceberg、PostGIS/DuckDB、Azure profile 的合同一致性通过率。

### AgentOps 指标

- Agent 生成 changeset 的一次审查通过率与人工修改量；
- 离线 eval、shadow、canary 和 rollback 覆盖率；
- 工具调用越权拦截率、错误副作用率和人工接管成功率；
- 单任务 token/compute 成本、质量和延迟的联合 SLO。

### GWM 指标

- state/evidence 的 observed/proxy/synthetic 占比；
- 时间、空间、跨域 holdout 的预测与校准指标；
- hard constraint 违反率和不可行行动拦截率；
- 相对 LLM-only、传统模型和无 GWM planner 的增益；
- rollout 结论可复现率；
- 真实 action-outcome 回收率、反馈延迟和再校准效果。

---

## 11. 最终结论

GIS Data Agent 的机会不在于证明它比所有平台“功能更多”，而在于定义并实现一个当前市场尚未被完整占据的新品类：

> **Geospatial Data-to-Action-and-World Platform**：把受治理的时空数据产品、Agentic 生产、空间运营本体、真实行动、证据和世界模型统一起来。

它相比 v3.0 的正确进步路径是“继承完整能力、消除操作复杂度、统一控制面、建立持续运营、进入行动与推演”，而不是以新概念替代旧平台已经解决的基础问题。

它相比全球竞品的正确策略是“组合领先、垂直做深、开放共存”：以 Databricks 等为数据/AI 工程标杆，以 Palantir 为数据到行动和生产运维标杆，以 Esri/CARTO/FME 为空间专业标杆，以 active metadata 平台为治理标杆，再用独立 AgentOps、空间运营本体、证据约束和 GWM 形成自己的不可替代性。

要引领未来 5～10 年，最重要的不是提前写出所有未来功能，而是从现在开始积累未来最难补的资产：统一合同、真实生产 Run、数据产品 SLO、空间对象与 Action、本体化规则、证据链、行动-结果轨迹和跨时空验证。只有这些持续进入同一个可运营系统，GWM 才会从创新概念成长为平台内核，GIS Data Agent 才可能从优秀原型成长为一个真正的新一代 Data Platform。

---

## 12. 公开资料与内部证据索引

### 12.1 竞品官方公开资料

以下链接用于核对产品定位和公开能力，访问/复核日期为 2026-07-19；产品页面随时可能更新：

- Palantir Foundry: https://www.palantir.com/platforms/foundry/
- Palantir AIP: https://www.palantir.com/platforms/aip/
- Palantir Ontology: https://www.palantir.com/docs/foundry/ontology/overview/
- Databricks Data Intelligence Platform: https://www.databricks.com/product/data-intelligence-platform
- Databricks Genie: https://www.databricks.com/product/genie
- Databricks Agent Framework: https://docs.databricks.com/aws/en/generative-ai/agent-framework/
- Snowflake Cortex AI: https://www.snowflake.com/en/product/features/cortex/
- Snowflake Cortex Agents: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents
- Microsoft Fabric overview: https://learn.microsoft.com/en-us/fabric/get-started/microsoft-fabric-overview
- Microsoft Fabric data agent: https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent
- Google BigQuery: https://cloud.google.com/bigquery
- Google Earth Engine: https://earthengine.google.com/
- Microsoft Planetary Computer: https://planetarycomputer.microsoft.com/
- AWS analytics: https://aws.amazon.com/big-data/datalakes-and-analytics/
- AWS SageMaker Unified Studio: https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/what-is-sagemaker-unified-studio.html
- NVIDIA Earth-2: https://www.nvidia.com/en-us/high-performance-computing/earth-2/
- Esri ArcGIS Online: https://www.esri.com/en-us/arcgis/products/arcgis-online/overview
- Esri GeoAI: https://www.esri.com/en-us/capabilities/geoai/overview
- CARTO Platform: https://carto.com/platform/
- Safe Software FME: https://www.safe.com/fme/
- Collibra Platform: https://www.collibra.com/us/en/platform
- Atlan: https://atlan.com/
- Informatica IDMC: https://www.informatica.com/products/intelligent-data-management-cloud.html
- DataHub: https://datahub.com/
- OpenMetadata: https://open-metadata.org/
- Dremio: https://www.dremio.com/platform/

### 12.2 GIS Data Agent 内部设计证据

- `docs/roadmap.md`
- `docs/architecture-review-2026-07-19.md`
- `docs/traditional-platform-baseline-and-agentic-elevation-2026-07-19.md`
- `docs/roadmap-mainline-checkpoint-2026-07-19.md`
- `docs/architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md`
- `docs/architecture-decisions/adr-002-unified-metadata-control-plane.md`
- `docs/architecture-decisions/adr-003-unified-orchestration-and-job-control-plane.md`
- `docs/architecture-decisions/adr-004-capability-floor-and-dual-entry-agentic-platform.md`
- `docs/architecture-decisions/adr-005-dataops-and-agentops-operating-loops.md`
- `docs/reports/gis-data-agent-brain-vs-palantir-objective-comparison-2026-07-15.md`
- `docs/designs/gis_data_agent_cognitive_runtime_2026-07-15/GIS_Data_Agent_Cognitive_Runtime_详细设计说明书.md`

### 12.3 证据限制

- 本报告只评价公开可见产品能力，不推断竞品未公开内部路线。
- “AI-powered”“Copilot”“Agent”不自动等同于完整 AgentOps。
- “数字孪生”“GeoAI”“时序预测”“foundation model”不自动等同于 action-conditioned world model。
- GIS Data Agent 的目标设计与当前实现已明确分列；任何目标能力进入对外材料前，仍需以端到端运行、测试、部署和运营证据重新判定。
