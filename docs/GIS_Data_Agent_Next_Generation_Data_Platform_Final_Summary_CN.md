# GIS Data Agent 作为下一代 Data Platform：收尾总结

更新时间：2026-08-30
适用仓库：`zhouning/gisdataagent`
当前主线：`feat/abu-dhabi-stormwater-world-model-foundation`

## 一句话定义

GIS Data Agent 是一个面向自然资源、城市和其他空间业务的可治理数据平台：它把数据接入、分层加工、质量、版本、血缘、服务发布、审批和运行恢复做成一条可追溯的生产链，再让人和多智能体用同一套能力合同去发现、构建、运行和消费数据产品。

它的价值不在于多一个聊天窗口，而在于把“问一个空间问题”或“做一次空间规划”变成有输入身份、有规则、有运行记录、有输出版本、可复核、可回放的工作。

## 平台到底提供什么

### 1. 数据生产链

数据从来源进入平台后，沿着固定的生命周期流转：

```text
来源/文件/接口/CDC
    -> Raw（不可变原始证据）
    -> ODS（贴源结构）
    -> DIM/DWD（标准化、实体和明细）
    -> DWS（汇总，可按产品需要启用）
    -> ADS（面向业务的数据产品）
    -> PostGIS / MVT / OGC API / STAC / 文件导出 / AgentContext
```

每层都有自己的记录数、schema、质量结果、血缘和内容指纹。PostGIS 负责在线空间服务和操作性数据；对象存储与 Iceberg 保存原始、分析和历史快照；DuckDB/PostGIS 可以组成轻量部署；Spark/Sedona、Flink 和云适配器承担经认证的批处理或流处理。存储、表格式和计算引擎是可替换的配置维度，不被某一个厂商锁死。

### 2. 统一控制面

平台的控制面由几类已有组件组成，各自有清晰边界：

| 控制面 | 负责的事情 |
|---|---|
| Resource / Definition / Product | 资源、schema、工作流、数据产品和服务定义的不可变版本 |
| Metadata Fabric | OpenMetadata 管治理目录、owner、术语和通用血缘；Gravitino 管 technical metadata、metalake/catalog 和联邦；GDA 维护 GIS/证据扩展及跨系统映射 |
| Orchestration | DolphinScheduler 负责 DataOps DAG、定时、补数和资源队列；Temporal 负责 Agent/GWM 的长时等待、审批、重试和补偿 |
| Policy / Approval | 租户、身份、权限、质量门、业务审批、许可和 SLO 约束 |
| Run / Artifact / Evidence | 运行、输入输出制品、质量结果、血缘、观测和审计证据 |
| Service Control Plane | 图层、样式、瓦片矩阵、部署 revision、endpoint、消费者、缓存、SLO、切换和回滚 |

GIS Data Agent 通过这些控制面发起和关联操作，不另造一套元数据中心、产品注册表或调度器。

### 3. 多入口和多智能体

Web、地图、SQL、Notebook、API/SDK、CLI/TUI、MCP/A2A Agent 进入的是同一个 `CapabilitySpec -> DefinitionVersion/ChangeSet -> Policy -> Run -> Artifact` 链路。关闭 LLM 时，确定性的 Web/API/CLI/TUI/Notebook、质量、审批、调度、发布和回滚路径仍然可用。

Agent 采用 coordinator + specialist 的静态 DAG，而不是把所有能力塞进一个聊天 Agent。一个典型拓扑是：

```text
Coordinator
  ├─ Data Engineer：资源发现、数据产品构建和运行提交
  ├─ Quality Guardian：质量规则、证据和发布门
  ├─ MMFE Specialist：多模态 profiling、对齐和融合
  ├─ GIS Analyst：空间查询、服务和地图产物
  ├─ GWM Specialist：消费已发布产品，做状态、行动和情景推演
  └─ Visualizer：把同一 Run/Artifact 转成地图、图表或报告
```

Coordinator 只做委派、依赖和有限重规划；specialist 不能绕过 DataOps、质量或权限去改写原始真值。每个 AgentRun、TaskStep 和 ToolCall 都绑定 Agent bundle、DataProductVersion、SubjectContext、PolicyDecision、幂等键和输出 Artifact。

## MMFE 和 GWM 在平台中的位置

### MMFE

MMFE 是数据生产链中的融合执行器，不是旁路分析脚本。它接收已纳管的 Raw/ODS 或标准化数据，完成多模态 profiling、字段/实体对齐、空间时间匹配、冲突识别、置信度和人工修正记录，产出带版本和证据的融合数据产品。融合结果仍要经过质量、审批、血缘和产品发布门，才能进入下游。

### GWM

GWM 是数据产品消费者和空间世界认知增强内核。它读取已发布的 Gold/ADS/DataProductVersion，把空间对象或网格作为状态，把地类置换、规划动作或干预作为行动，用状态转移模型和情景推演估计后果，再由 MPC 或其他规划器搜索方案。它的输出必须回到 Run、Artifact、质量和审批链；GWM 不拥有原始数据真值，也不替代湖仓、元数据、调度或服务控制面。

这一区分让“数据可信”和“模型聪明”可以分别验收：先保证数据产品可追溯，再评价 MMFE/GWM 带来的融合、预测和规划增益。

## 已经形成的成果

以下是代码和证据已经体现的能力，按事实强度分层理解：

1. 已完成总体架构重置、数据分层、控制面边界、GIS 服务发布边界、DataOps/AgentOps 闭环和多智能体合同，并用 ADR 固化关键取舍。
2. 已形成重庆璧山 JQDLTB 首条垂直切片的冻结身份、标准映射、质量诊断、分层 transformation、语义准入、审批合同、产品发布门和 serving release 门。
3. 已实现大量确定性执行器和 provider adapter，包括 DuckDB/Parquet、PostGIS、MinIO/S3、Iceberg/Spark/Flink 的边界合同，GIS MVT/OGC API Features 发布控制面，以及 Temporal AgentOps 的任务图、HITL、checkpoint、重试、取消和对账切片。
4. 已完成多次 disposable PostgreSQL、MinIO、Martin、pygeoapi、DolphinScheduler 和 Temporal sandbox 认证；相应测试覆盖了幂等、RLS、内容寻址、失败收敛、取消未知态和恢复对账等工程问题。
5. 已实现 JQDLTB candidate-only 语义隔离链：1,555 条冻结源记录被物化为候选投影，3,110 个 `SJNF/MSSM` 字段级条目进入隔离；候选明确标记 `quality_verdict=failed`、`promotable=false`，不创建产品版本。
6. 已实现业务更正文件的 ResourceVersion 登记入口。入口会先校验 `TBBH`、面积、源身份和 typed owner；当前因更正文件尚未补交，没有登记真实 correction ResourceVersion。

这些是设计、代码、测试和本地/一次性运行证据。它们不自动等于客户生产环境已上线。

## 当前还没有完成什么

当前状态必须直说：

- AR-0 仍为 `in_progress / awaiting_business_approval`。冻结源全量质量结论仍是 `failed`。
- 业务更正 artifact 尚未补交；`SJNF`、`MSSM` 的权威语义规则尚未批准；许可、SLO/on-call 和 staging/production attestation 仍未形成可验证批准。
- 因此还没有基于真实业务批准创建 JQDLTB `DataProductVersion`，也没有把它作为正式 MVT/OGC Features 产品对外发布。
- AR-1 至 AR-5 有大量合同、测试和 sandbox/容器认证，但生产级 OpenMetadata/Gravitino、DolphinScheduler/Temporal、跨租户恢复、集群网络策略、HA/RPO/RTO、真实 staging/production rollout、Agent bundle 灰度/在线 verdict/事故回滚仍有未关闭项。
- AR-6（MMFE 作为统一 Data for AI 生产链，以及 GWM 共享 Kernel 的产品化接入）仍是 planned；目前 MMFE/GWM 已有真实领域能力和 specialist 边界，但不能把它们描述成全平台生产完成。

因此，当前最准确的结论是：架构设计已经覆盖下一代平台所需的主要边界，代码也形成了大量可复跑的工程切片；但生产平台的最后证据链仍被业务批准、真实环境和跨系统运维责任卡住。

## 对用户的实际意义

当平台完成生产闭环后，用户不需要分别学习一套“智能体入口”、一套“数据平台入口”和一套“GIS 服务入口”。同一个数据产品可以被：

- 数据工程师用 DAG、SQL、Notebook 或 CLI 构建和补数；
- 业务人员在目录、地图或对话中申请、查询和订阅；
- 质量和治理人员审查字段、规则、血缘、许可和发布条件；
- Agent 协调多个 specialist 完成发现、融合、分析、规划和报告；
- GWM 消费同一版本数据做状态评估和情景推演；
- 运维人员按 Run、Artifact、Incident 和 rollback pointer 追踪、恢复和回放。

所有入口看的是同一份版本化事实，而不是各自维护一份结果。

## 最终定义

> 作为下一代 Data Platform 的 GIS Data Agent，是一条以数据产品为中心、以 Raw 到 serving 的生产链为底座、以元数据/调度/策略/证据为控制脊柱、以 MMFE 做多模态融合、以多智能体协作和 GWM 做空间认知增强、并能被人或 LLM 通过同一能力合同安全操作的地理空间数据平台。

本定义描述的是目标架构和已形成的工程基础；当前生产晋级仍以 AR-0 的业务批准、质量修复和真实环境证据为准。
