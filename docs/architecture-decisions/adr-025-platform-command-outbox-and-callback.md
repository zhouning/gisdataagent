# ADR-025：以 Tenant-Scoped Outbox 可靠传播 Provider Command

**Status**: Accepted

**Date**: 2026-07-25

**Decision owners**: Platform Architecture, DataOps, Data Platform, Security, SRE

**Related decisions**: ADR-003、ADR-007、ADR-020、ADR-022、ADR-023、ADR-024

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-023 已建立幂等 DolphinScheduler correlation，ADR-024 已在 dispatch 前强制授权，但 API 线程仍直接承担触发责任。Run 成功提交后若进程崩溃，调用方必须自行判断是否重试；provider callback 重复或乱序时也没有统一的耐久 reconcile 入口。

项目已有 `std_outbox`，但它属于 Standards 领域，没有 tenant/RLS、claim owner 或 lease expiry，worker 在 `in_flight` 崩溃后不能自动接管。直接扩展该表会混合领域权限和恢复语义。引入 Redis/RabbitMQ/Kafka 或新 orchestration service 则会在当前规模下增加第二套部署与恢复边界。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 复用 `std_outbox` | 代码最少 | 缺 tenant/RLS/lease，事件 vocabulary 和 owner 错位 | 拒绝 |
| B. 立即引入外部 broker 和独立 worker service | 吞吐与扩缩边界清晰 | 增加基础设施、凭据、投递和恢复复杂度，仍不能替代数据库事务 | 暂缓 |
| C. `gda_control` tenant-scoped command outbox + 薄 consumer | Run/observation 与 command 可原子提交，复用 PostgreSQL/RLS，后续可替换传输层 | 需要维护小型 lease/delivery 状态和轮询入口 | **选择** |

## Decision

### 1. Outbox 只拥有投递状态

migration `095_platform_command_outbox.sql` 新增 `gda_control.platform_command_outbox`，只接受 `dolphinscheduler.dispatch` 和 `dolphinscheduler.reconcile`。每条 command 固定 tenant、Run、execution-plan Artifact、actor、dedupe key、最大尝试次数和可选 callback observation。

command 的 `pending/in_flight/done/failed` 是投递状态，不是 PlatformRun、DolphinScheduler instance 或业务任务状态。PlatformRun/event 仍是平台终局权威，DolphinScheduler 仍执行 DAG，outbox payload 不允许承载长业务逻辑。

### 2. 保持原子写入边界

调用方在 Run submission 上显式设置 `request_dispatch=true` 时，PlatformGateway 在同一 tenant transaction 中验证 ADR-024 授权、创建或幂等恢复 Run，并写入确定性 dispatch command。先提交 Run、后 best-effort enqueue 的双写窗口不被允许。幂等重放比较 command 的逻辑绑定而不是可变 delivery 字段，因此 command 被 claim、重试或完成后仍可安全重放。

版本化 callback API 只接受 workload identity。gateway 要求 callback actor 与 Run workload 完全一致，在同一事务追加 FrameworkAttemptObservation 并写入确定性 reconcile command。callback state 标记为 `correlation_verified=false`，只用于唤醒；command 按 gateway 接收时间立即可领取，不信任 callback 的 `observed_at` 决定投递时间。consumer 必须重新查询 provider、读取 instance variables 并执行 ADR-023 精确关联，callback 本身不能推进 Run。

### 3. 数据库控制 claim/lease

gateway role 对 outbox 只有 `SELECT/INSERT`，没有直接 `UPDATE/DELETE`。`claim_platform_commands`、`complete_platform_command` 和 `fail_platform_command` 是唯一 delivery mutation 入口：

- claim 按 tenant 和 workload actor 定向筛选，并使用 `FOR UPDATE SKIP LOCKED`，同一 command 同时只交给一个 worker；
- claim 记录 worker、lease expiry 和 attempt count；过期 lease 可由新 worker 接管；
- stale worker、错误 tenant 或非 owner 不能 complete/fail；
- fail 按最大尝试次数回到 pending 或进入 failed，错误文本有长度上限；
- RLS、tenant GUC 和函数内 tenant equality 同时约束跨租户访问。

### 4. Consumer 保持薄且可替换

`DolphinSchedulerCommandConsumer.run_once` claim 有界批次，只调用现有 adapter 的 dispatch/reconcile，再 complete 或 fail。它没有循环、schedule、DAG、provider 状态投影或 Run 终局裁决，因此不是自研 scheduler/queue runtime。

dispatch 网络结果不确定时，consumer 在同一数据库事务把当前 dispatch command 标为 done 并创建确定性 reconcile command。若 lease 在 provider 调用期间过期，旧 worker 无法确认；adapter 的四字段 correlation 和非 accepted Run 禁止重提规则继续承担 at-least-once delivery 下的外部幂等保护。

## Consequences

正面影响：

- Run+dispatch、callback evidence+reconcile 都没有 best-effort 双写窗口；
- worker 重启、重复 callback 和多 worker claim 可通过数据库状态恢复；
- callback 乱序不会直接倒退 Run，provider 当前状态仍由 adapter 重新读取；
- 没有新增 broker、微服务、scheduler 或第二个 Run authority。

限制与缓解：

- 当前只提供 `run_once` library，不包含常驻进程部署、通知唤醒或 autoscaling；staging 可先由受管进程周期调用，再依据延迟/吞吐决定是否引入 broker；
- 没有 lease heartbeat；provider HTTP timeout 必须小于部署配置的 lease，长调用需求出现时再增加受控 renew function；
- callback API 依赖现有 workload principal，不等于 provider OIDC/IAM 和网络入口已配置；
- reconcile command 失败只表示投递耗尽，不裁决 PlatformRun failed，必须由运维告警和人工恢复处理。

## Verification

- 单元测试覆盖 dispatch complete、未知结果转 reconcile、reconcile 退避和最大尝试失败。
- HTTP 测试覆盖 human callback 拒绝、workload callback observation 构造和原子 enqueue 调用。
- 真实 PostgreSQL 16 测试覆盖最小 grant、无直接 UPDATE/DELETE、幂等 Run+dispatch、跨租户与错误 workload 空读、lease 过期接管、stale owner 拒绝、dispatch 转 reconcile、完成后 callback replay 和 fail/retry/complete。
- migration、platform contract 和 gateway 静态 validator 固定 migration 095、`SKIP LOCKED`、lease recovery、受控函数、callback route 和薄 consumer marker。

## Revisit Triggers

- 实测 command 延迟、吞吐或数据库锁竞争超过已记录 SLO；
- provider 调用时长需要 lease heartbeat/renewal；
- 多区域或跨数据库投递要求外部 broker；
- callback provider 支持签名事件或 OIDC federation，需要升级 ingress trust；
- 出现新的 provider command type，需要独立完成幂等、取消、reconcile 和权限评审。
