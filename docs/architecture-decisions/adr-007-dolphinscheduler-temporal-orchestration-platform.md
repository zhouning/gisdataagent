# ADR-007: 采用 Apache DolphinScheduler + Temporal 的分层统一编排平台

**Status**: Accepted

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Platform, SRE, Security, AI/GWM Engineering

**Supersedes**: ADR-003 的“自建 PostgreSQL scheduler/worker 为首期最终方案”框架选型；其 DefinitionVersion、PlatformRun、Artifact、Policy 和审计合同仍然有效。

**Related decisions**: ADR-001、ADR-005、ADR-006

## Context

当前 `workflow_engine.py` 使用 APScheduler，`TaskQueue` 使用 Redis/in-memory 状态，`SparkGateway`、outbox worker、background task 和 self-evolution scheduler 各有自己的触发与运行语义。把这些继续收敛为自建 lease/claim/DAG/retry/signal/replay 框架，会重复成熟调度器和 durable workflow runtime 的核心能力，并将故障恢复成本长期留在项目内。

GIS Data Agent 的默认生产负载是 Spark/Sedona batch、Flink streaming、MinIO/Iceberg、PostGIS serving、私有化与传统数仓/时空中台代表任务。这个 DataOps 核心需要可视化 DAG、多租户/项目/资源队列、worker group、任务插件、补数、告警和企业运维，而不仅是 Python asset abstraction。Agent/GWMOps 则需要跨天等待、人工审批、外部副作用、signal、补偿和 durable workflow history。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. APScheduler + Redis/PostgreSQL 自建调度器 | 近期开销低 | 没有企业级 backfill、资源队列、可视化 DAG、durable workflow、升级与生态；持续自研 | 不选 |
| B. Apache Airflow 单独承担全部流程 | 批处理生态和 operator 丰富 | 对私有化可视化工作流、资源/租户治理和 Agent/HITL saga 不是最优组合 | 不选 |
| C. Dagster + Temporal | asset-first、Python 开发体验好 | 对默认 Spark/Flink 私有化数仓调度、可视化 DAG/worker group/资源队列不如 DolphinScheduler 直接；同时引入两套调度语义 | 不选为默认 |
| D. DolphinScheduler 单独承担全部流程 | 企业 DataOps DAG、资源队列、任务插件、补数、告警成熟 | 不适合长期 human signal、跨系统 compensation、Agent/GWM workflow history | 不选 |
| E. DolphinScheduler 负责 DataOps，Temporal 负责 Agent/GWMOps durable orchestration | 与 Spark/Flink、传统中台、私有化和 Agent/GWM 时间语义分别匹配 | 需要严格 PlatformRun correlation 与权限边界 | **选择** |

## Decision

### 1. 框架职责

| 层 | 选型 | 唯一职责 | 明确不负责 |
|---|---|---|---|
| DataOps orchestration | **Apache DolphinScheduler**（self-hosted） | process definition/version、visual DAG、schedule、complement/backfill、project/tenant/worker group/resource queue、任务插件、告警和 DataOps UI | Agent/HITL durable workflow、行动补偿、GWM session 真值 |
| Durable Agent/GWMOps | **Temporal OSS**（self-hosted；server 1.29.7 + Python SDK 1.32.0 sandbox 认证基线） | Agent/GWM workflow、approval signal、timer、retry、activity、compensation、versioning/replay、长任务恢复 | catalog、DataOps batch/stream scheduler、Spark/Flink 调度 UI |
| Execution lifecycle | Spark/Flink task plugin 或 submit、Spark Operator、Flink Kubernetes Operator、Kubernetes Job、PostGIS/DuckDB、Azure provider adapter | 提交、监视、取消和 reconcile 实际计算 | 业务 schedule、产品生命周期权威 |
| Platform gateway | `gda-orchestration-gateway` | policy gate、DefinitionVersion -> ProcessDefinition/Workflow mapping、`PlatformRun` correlation、Artifact/lineage evidence、统一 API/地图/Agent 视图 | 不实现 DAG scheduler、queue、timer、lease 或 workflow engine |

统一调度中心的含义是一个统一的提交 API、策略与预算门、`PlatformRun` 关联视图、审计/lineage/incident 视图；不是将不同时间语义强行塞进自研 runtime，也不是同时运行 DolphinScheduler 和 Dagster 两个 DataOps scheduler。

### 2. DolphinScheduler 实施边界

- 以认证的 DolphinScheduler release、metadata database、API/master/worker、alert、worker group/resource queue 和 Kubernetes/private deployment profile 作为默认生产 DataOps runtime；精确版本和 task plugin BOM 在 AR-1 的 Spark/Flink/MinIO/Iceberg POC 后锁定，禁止浮动 `latest`。
- `DataProductBlueprint` 经 `gda-orchestration-gateway` 编译为版本化 `ProcessDefinition`。每个 process/task instance 必须携带 `gda.resource_urn`、definition version、input snapshot、classification、quality verdict、idempotency key 与 `PlatformRun` correlation。
- OpenMetadata/Gravitino ingestion、Source/Sync、Iceberg maintenance、Spark/Sedona batch、Flink deployment/reconcile、PostGIS/STAC projection、quality、publish 和 complement/backfill 都是 DolphinScheduler process/task；APScheduler、self-evolution scheduler、API background task 和 `TaskQueue` 不再创建生产 DataOps run。
- 对 Spark/Flink 的具体任务类型不作纸面假设：每个 plugin/submit path 都必须通过 submit/status/cancel/checkpoint/reconcile/identity/lineage conformance；不通过时使用认证的 Kubernetes/executor adapter，而不是直接绕过调度中心。

### 3. Temporal 实施边界

- Temporal namespace 按 tenant/isolation class 划分；workflow id 从 GDA immutable definition/version 和 idempotency key 派生，worker 使用独立 workload identity。
- 只用于 AgentRun、tool/action approval、跨系统 mutation、GWM rollout/evaluation、长时间 external wait、compensation/reconcile 等 durable workflow。
- Temporal activity 不直接访问生产数据库或 provider admin credential；它调用受 policy gate 的 typed action/executor API，返回 artifact reference 和 evidence。
- Temporal workflow history 不是全平台 audit 的唯一权威。GDA Control Ledger 接收 correlation、policy、approval、artifact、action/outcome 的小型不可变证据；大 payload 留在对象存储/湖仓。

### 4. PlatformRun Correlation Contract

```text
PlatformDefinitionVersion
  -> OrchestrationClass(dataops | durable_agent | durable_gwm | action)
  -> PolicyDecision / Approval
  -> DolphinScheduler ProcessDefinition/ProcessInstance OR Temporal Workflow/Run
  -> execution provider ref (Spark / Flink / K8sJob / cloud job)
  -> Artifact + OpenLineage event + QualityVerdict
  -> DataProductVersion / ActionResult / OutcomeObservation
```

`PlatformRun` 只存 correlation id、immutable bindings、policy/approval、external run reference、状态 projection、artifact/evidence references 和 terminal verdict。DolphinScheduler/Temporal 保存各自的 task/workflow state；任何一方都不允许成为另一方的 shadow scheduler。

### 5. 事件与队列

- PostgreSQL outbox 保留为 command/event 可靠传播和审计机制；其 consumer 触发 DolphinScheduler API 或 gateway command，不能执行长业务逻辑。
- Redis 仅可用于 cache、progress fan-out、rate limit、websocket wake-up，不能保存 queue payload 或唯一运行状态。
- Kafka/Redpanda 是高吞吐 event backbone 的条件升级，不是 DolphinScheduler/Temporal 的前置依赖。

## Migration Plan

1. **O0 - Platform bootstrap**：部署 DolphinScheduler sandbox，冻结 master/worker/resource queue/alert/metadata DB、OIDC/workload identity、metrics、backup restore；实现 `gda-orchestration-gateway` 只读 run correlation。
2. **O1 - First DataOps slice**：将地类图斑 Source -> Raw -> Iceberg -> PostGIS/STAC -> quality/publish 编译为 DolphinScheduler process definition，完成 schedule、manual trigger、complement/backfill、OpenMetadata/Gravitino ingestion；人工/API/Agent 均经 gateway 触发同一 process。
3. **O2 - Retire local scheduler**：把 `workflow_engine` 的生产 cron、APScheduler、background task 和 `TaskQueue` producer 改为 DolphinScheduler process/schedule/launch；旧 API 仅做 redirect/compatibility read。
4. **O3 - Execution adapters**：将 `SparkGateway` 收敛为 DolphinScheduler task/provider adapter，接入 Spark/Flink/Kubernetes/Azure job reconcile；保留外部 job id，不保存内存真值。
5. **O4 - Temporal pilot**：部署 Temporal production profile；以一个高风险审批 Action 和一个 GWM rollout 为试点，完成 worker crash、signal、timer、retry、compensation、versioning/replay 和 audit 演练。
6. **O5 - Agent/GWMOps cutover**：AgentRun、Human approval、tool side effect 和 GWM long-running flows 全部迁移 Temporal；短同步只读请求可继续在 API 内执行。

## Acceptance Criteria

- cron、data-arrival、manual、API、complement/backfill 和 Agent 发起的数据任务均由 DolphinScheduler 创建；master/worker 高可用故障后不重复发布产品。
- `PlatformRun`、DolphinScheduler process/task instance、Spark/Flink/cloud job 和 Artifact 可双向关联；任一 scheduler/worker/API 进程重启后没有用户可见的“unknown final state”。
- 同一 `DefinitionVersion + InputBinding + scheduled partition` 的 GDA、DolphinScheduler 与 Temporal 幂等键对应关系可验证。
- Temporal workflow 能在等待人工审批至少 24 小时、worker 全部重启后继续，并执行批准/拒绝、超时、取消、补偿和审计。
- `TaskQueue`、APScheduler、Dagster 和自建 workflow scheduler 不承担任何生产真值；Redis 故障不丢失 Run。
- Spark/Flink/云 job 状态可 reconcile；失败、取消、部分发布和迟到回调均不会错误推进 DataProduct/Action 状态。

## Consequences

**Positive**：DataOps 获得与默认 Spark/Flink、传统中台和私有化运维匹配的企业调度能力；Agent/GWM 获得 durable workflow；团队不再承担 scheduler/queue/workflow runtime 的自研债务。

**Negative**：新增 DolphinScheduler 和 Temporal 两套运营面；需要编译 Definition、关联 run、控制 task plugin 版本和权限。

**Mitigation**：只有一个 GDA gateway/API 和一套 PlatformRun correlation；使用 Helm/IaC、版本 pin、project/tenant/worker group 隔离、OTel、backup/restore、故障演练和 provider conformance suite；不同时引入 Airflow、Dagster、Celery、Prefect 或 Kestra。

## Revisit Triggers

- DolphinScheduler 无法满足经认证的 Spark/Flink、补数、资源隔离、私有化或 SLO；
- Temporal 无法满足私有化、durability、workflow history、成本或跨地域要求；
- 工作负载强制要求特定云编排服务，此时通过 executor/provider adapter 集成，而不是另起平台调度真值。
