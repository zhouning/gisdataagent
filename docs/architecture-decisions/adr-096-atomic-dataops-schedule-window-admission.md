# ADR-096：DataOps Schedule Window 原子准入与漏窗恢复

**Status**: Accepted

**Date**: 2026-08-01

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

**Related decisions**: [ADR-003](adr-003-unified-orchestration-and-job-control-plane.md) ·
[ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) ·
[ADR-095](adr-095-governed-dataops-invocation-and-backfill.md)

## Context

ADR-095 已冻结不可变 DataOps invocation 和一 Run 一 provider backfill 实例，但首次
实现仍分别提交 invocation Resource、ResourceVersion、策略 Artifact、PlatformRun 和
outbox command。进程在事务之间失败会留下半成品；并发 controller 也可能用不同准入时间
构造不同 invocation，再争用同一个逻辑窗口。

DolphinScheduler 原生 ONLINE schedule 仍不能直接启用，因为它会先于 GDA 创建执行，无法
预绑定 PlatformRun、策略范围和唯一 correlation。GDA 也不得通过 APScheduler、cron parser、
timer、lease 或第二个任务队列取代 DolphinScheduler。

## Decision

### 1. Controller 只接收精确窗口，不生成时间

`DataOpsScheduleWindowSpec` 接收外部触发源或漏窗扫描已经物化的 `scheduled_for`、UTC
半开逻辑窗口、schedule reference、definition、输入版本、execution plan、工作负载身份和
策略版本。`DataOpsScheduleController` 不解析 cron、不等待 timer、不保存 provider 状态；
漏窗恢复只是按 schedule time 排序后逐个提交精确窗口。

窗口 fingerprint 只由 tenant、definition、schedule reference、scheduled_for 和逻辑窗口
组成，不包含首次发现或恢复时间。Run ID 和 idempotency key 从该 fingerprint 确定性派生，
tenant 参与身份，因此同一业务窗口跨租户不会共享 Run 身份。

### 2. 首次准入时间由 PostgreSQL 事务确定

`PlatformGateway.submit_schedule_window` 在 tenant-scoped、最小权限事务中：

1. 使用窗口 fingerprint 派生的两个 signed integer 获取 `pg_advisory_xact_lock`。
2. 在锁内按确定性 idempotency key 查找已有 Run。
3. 首次准入使用数据库 `clock_timestamp()` 构造 invocation、策略决定和 Run。
4. 在同一事务写入 invocation Resource/ResourceVersion、策略 Artifact、PlatformRun、input
   bindings 和 dispatch outbox command。
5. 任一步失败则全部回滚；重放从已存 invocation 恢复首次准入时间，并逐项比较不可变绑定。

advisory lock 只串行化准入事务，不是 scheduler lease 或运行真值；持久去重仍由 Run 和 outbox
唯一约束承担。策略在真实准入时求值，不能把漏窗原定时间伪装成 policy decision time。

### 3. Provider 使用受治理的即时启动

schedule invocation 显式绑定一个 provider schedule time。DolphinScheduler 接收
`START_PROCESS`，同时获得 Run、tenant、definition、idempotency、invocation version/hash、
schedule reference、schedule time 和逻辑窗口变量。provider `scheduleTime` 保持空值，不创建
或发布 ONLINE native schedule。

Provider `SUCCESS` 仍只进入 observation/reconciliation；最终状态继续由 GDA Artifact、质量
和血缘证据决定。

## 2026-08-01 Real-data Acceptance

重庆璧山 JQDLTB 漏窗恢复窗口 `[2026-07-02, 2026-07-03)`、scheduled time
`2026-07-03T00:05:00Z` 生成：

- window SHA-256 `29cd4346be6a2065edf73205fced1b5dd7132e850cc16dd804244c972b7ed1c9`
- PlatformRun `70b0ac4b-d142-5180-9868-811a872a4d5b`
- invocation version `af2060cd-4030-513c-b874-d60f69fcb47f`
- dispatch command `826768eb-1067-5584-94e0-949a0c55a8b1`
- DolphinScheduler instance `3`

同一窗口第二次提交保留首次 `admitted_at`，invocation version、策略 Artifact、Run 和 command
均 `created=false`。DolphinScheduler 只有一个匹配实例，`commandType=START_PROCESS`、
`scheduleTime=null`，14 个 GDA/definition/source correlation 变量完整。

实例为 `SUCCESS`，但 1,555 条真实要素的权威质量结果
`b302ffac-ac24-503e-abff-9a739c494814` 为 `failed`，Run 终止为 `failed`，未创建
DataProductVersion。终态重放未新增 observation、assessment version、lineage 或状态迁移。

真实验收报告：
`.tmp/dolphinscheduler-sandbox/schedule-window-v1/jqdltb-schedule-window-acceptance-report.json`。
相关单元/合同测试 135 项通过；真实 PostgreSQL 的并发双提交、全事务回滚和既有 RLS/账本
集成测试 2 项通过。

## Trade-offs

- 同一窗口的并发提交会短暂等待 PostgreSQL advisory transaction lock；窗口间仍可并行。
- controller 需要上游提供精确窗口。生产触发源、窗口 cursor、schedule lag 指标和 HA 恢复
  仍需单独验收，但不得为此在 GDA 内实现 cron 或第二调度器。
- 首次策略证据有有效期；outbox 若在有效期后才投递会失败关闭，需要重新授权，而不是复用
  过期决策。
- schedule invocation 新增 correlation 变量；升级前的 manual/backfill 历史实例保持原合同，
  不要求补写不存在的 schedule 字段。

## Revisit Triggers

- DolphinScheduler 提供可在创建 provider execution 前原子调用 GDA admission hook 的版本化
  schedule 合同。
- schedule source 必须原子提交多个窗口，且逐窗口 Run 无法满足批准的恢复或容量 SLO。
- PostgreSQL advisory transaction lock 在真实并发 benchmark 上成为已证明的准入瓶颈。
