# ADR-003：统一调度与作业控制面

**Status**: Superseded by [ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md)

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related review**: [GIS Data Agent 企业级架构复审](../architecture-review-2026-07-19.md)

**Related decisions**: [ADR-001 可插拔地理空间存储、计算与服务边界](adr-001-geospatial-lakehouse-and-postgis-boundary.md) · [ADR-004 传统平台能力下限与 Human/Agent 双入口](adr-004-capability-floor-and-dual-entry-agentic-platform.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md) · [ADR-007 DolphinScheduler + Temporal 编排平台](adr-007-dolphinscheduler-temporal-orchestration-platform.md)

> **Supersession note (2026-07-19)**：本 ADR 中 `DefinitionVersion`、`PlatformRun`、Artifact、幂等、策略、审计和跨 executor reconcile 的合同继续有效；“自建 PostgreSQL scheduler/worker 为首期最终方案”已被 ADR-007 替代。DolphinScheduler 是 DataOps 的 DAG/schedule/complement/backfill framework，Temporal 是 Agent/GWMOps 的 durable workflow framework；GIS Data Agent 不再自研 scheduler、queue 或 workflow runtime。

## Context

项目同时存在 APScheduler workflow cron、Redis/in-memory `TaskQueue`、`SparkGateway`、Standards outbox worker、自进化 scheduler 和 API 进程内 background tasks。它们缺少共同耐久状态、租约、接管、幂等、取消、制品和 lineage 合同。

统一调度中心不是仅提供 cron 页面。它必须统一手工、API、事件、数据到达、定时和 Agent 触发，并把 DuckDB、PostGIS、Spark/Sedona、Flink、云托管计算、MMFE、AI/GWM 等执行器纳入同一 Run/Attempt 状态机。

约束：私有化优先；当前 workload 和团队尚不足以证明 Temporal、Airflow/Dagster 或 Kafka 是强制依赖；PostgreSQL 与独立 worker 已可部署；长任务不得依附 Web 生命周期。

## Options Considered

| 方案 | 优点 | 缺点 | 适用条件 | 结论 |
|---|---|---|---|---|
| A. 修补 APScheduler + 当前 Redis queue | 近期代码少 | 多写状态、跨进程 payload 丢失、无统一恢复 | 单进程原型 | 不选 |
| B. PostgreSQL durable control state + scheduler/worker | 复用现有栈、事务和审计；离线部署简单 | 需实现 lease、DAG 和运维工具 | 当前规模与团队 | **选择** |
| C. Temporal | durable execution、timer、retry 和 saga 成熟 | 引入服务、SDK/运维和迁移成本 | 长流程、高可靠、大量外部活动 | 条件路线 |
| D. Airflow/Dagster | 数据 DAG、backfill、UI 和资产编排成熟 | 与交互式 Agent workflow/细粒度 command 不完全匹配 | 数据工程团队和批 DAG 为主 | 条件路线 |

## Decision

### 1. 控制面与执行面分离

- API、CLI、UI、Agent 和 event handler 只提交 command，创建耐久 Run；不使用 `asyncio.create_task` 承担需要恢复的工作。
- 独立 scheduler 只计算到期 trigger 并创建 Run，不执行领域任务。
- 独立 worker 通过 executor adapter 承接 attempt。DuckDB/本地 Python、PostGIS、Spark/Sedona、Flink、云托管计算、MMFE、Standards、AI/GWM 都是 executor kind。
- Definition 声明 `batch/stream/interactive/spatial` capability、资源、SLO 和 portability class；placement resolver 只在兼容 provider 集合中选择版本化 `ComputeBinding`，Run 固化实际 provider、region、engine/version、ExecutionPlanArtifact 和配置。
- PostgreSQL 保存定义和运行真值；Redis 可用于 wake-up、短期进度推送和 cache，不能保存唯一 payload/state。

### 2. 核心模型

```text
JobDefinition -> JobDefinitionVersion -> TaskGraph
Schedule / Trigger / EventSubscription
Run -> TaskRun -> TaskAttempt
Queue / ResourcePolicy
Lease / Heartbeat
InputBinding / Artifact / Checkpoint
RunEvent / OutboxEvent
```

状态机至少包含：

```text
Run: queued -> running -> succeeded | failed | cancelled
                  \-> cancelling -> cancelled
                  \-> paused -> queued
Attempt: pending -> leased -> running -> succeeded | retry_wait | failed | lost
```

所有状态迁移使用 compare-and-set/version column，记录 actor、reason、timestamp 和 trace。

### 3. Claim、Lease 与恢复

- worker 以 `FOR UPDATE SKIP LOCKED` claim due attempt，并写 `lease_owner`、`lease_expires_at` 和 heartbeat。
- lease 到期的 `leased/running` attempt 进入 `lost`，根据 retry policy 生成新 attempt；旧 worker 的迟到结果因 fencing token 被拒绝。
- scheduler 支持 leader lease 或对 due schedule 使用原子 claim；多副本不会为同一 fire time 创建重复 Run。
- run/attempt payload 完整持久化；queue 只传 ID 也能由任意 worker 从数据库恢复全部执行合同。

### 4. 幂等、重试、取消和补数

- 每个提交使用 `idempotency_key = trigger + definition_version + logical_input_version + scheduled_time`；数据库唯一约束阻止重复 Run。
- task 声明 retryable、max attempts、backoff、timeout 和 side-effect class；非幂等外部写入必须使用 idempotency token 或 prepare/commit publisher。
- cancel 是持久 command；worker 轮询或接收通知，executor adapter 实现 graceful/force cancel。不能取消的外部操作必须明确状态并等待 reconcile。
- backfill/replay 创建新 Run，引用原 immutable inputs 和原/新 definition version，不能修改历史 Run。

### 5. Artifact、Metadata 与 Lineage

- attempt 只返回小型 result metadata；文件、表、snapshot、模型和报告作为 Artifact 引用当前 StorageBinding 下的对象存储、湖表、PostGIS 或 DuckDB location。
- 创建/完成 Artifact 时调用统一元数据控制面，记录 content hash、schema/version、location 和 classification。
- Run 的 input/output binding 自动生成 LineageEvent；质量门和审批通过后才允许创建 active DataProductVersion。

### 6. 权限、资源和可观测

- Run 固化 submitter、tenant、purpose 和经过解析的 execution identity；worker 不能继承 Web 超级用户身份。
- Queue/ResourcePolicy 控制 CPU、内存、GPU、batch/stream engine slot、云配额、并发、租户优先级和成本预算。
- 指标至少覆盖 queue age、schedule lag、claim latency、run/attempt success、retry/lost、lease expiry、executor saturation、artifact bytes 和 publish latency。
- log/trace/metric 统一带 `run_id`、`task_run_id`、`attempt_id`、`resource_urn`、`tenant_id`。

## Migration Strategy

1. 修复 schema migration truth 后建立最小 Run/Attempt/Lease/Artifact/Outbox 表和状态机测试。
2. 先迁移 AR-2 湖仓 vertical slice；API/CLI 均提交同一 JobDefinitionVersion。
3. 将 Standards outbox handler 作为 executor 接入，保留其领域事件表直至双跑一致。
4. 将 workflow API 的 background task 和 APScheduler cron 改为 submit/trigger；独立 scheduler 接管。
5. 修复或退役当前 `TaskQueue` 和 `SparkGateway` 的内存真值；executor adapter 只返回外部 job reference 和 reconcile 状态。
6. 最后迁移 self-evolution、MMFE、AI 和 GWM 长任务；短于请求 SLO 的纯读操作可继续同步执行。

## Acceptance Tests

- 两个 scheduler 实例对同一 cron fire time 只创建一个 Run。
- worker 在 claim 后、写 artifact 前、发布中三个时点退出，lease 能回收且无重复产品版本。
- retry、timeout、cancel、pause/resume、backfill 和 checkpoint 均保留完整审计。
- 双租户无法查看、取消、重试或下载对方 Run/Artifact。
- PostGIS/DuckDB、Iceberg/Spark、Flink 和已认证云外部 job 状态可 reconcile；控制面重启后不丢 Run。
- 同输入、同 definition version 重放得到相同 hash；副作用 publisher 满足幂等。

## Consequences

### Positive

- 所有批处理、Agent workflow 和发布任务获得统一状态、恢复、审计与 lineage。
- Web 扩缩容不再导致 scheduler 重复或长任务丢失。
- 执行器可以独立演进，替换本地、Spark/Flink 或云托管计算不改变上层提交合同。

### Negative

- 需要实现并运维状态机、lease、worker、reconciler 和 dashboard。
- 迁移期会同时存在旧 workflow/task 状态与新 Run 状态。
- PostgreSQL queue 在极高吞吐下不是最终方案。

### Mitigation

- 只实现首条数据链需要的最小 DAG 和 executor，不复制成熟调度器的全部功能。
- 使用数据库约束、状态机 property tests、故障注入和 reconciliation job 控制可靠性。
- 通过 outbox 通知减少 polling 压力；只有真实 benchmark 失败后才换外部 durable execution engine。

## Revisit Triggers

- 运行规模或 timer 数量使 PostgreSQL claim/schedule lag 超出冻结 SLO。
- 跨天人工流程、补偿事务和外部 activity 数量使自建状态机复杂度不可接受。
- 数据工程团队需要 Airflow/Dagster 的资产 backfill/UI，且双控制面集成成本可控。
- 多区域 active-active、严格 workflow history replay 或更高可用要求成立。
