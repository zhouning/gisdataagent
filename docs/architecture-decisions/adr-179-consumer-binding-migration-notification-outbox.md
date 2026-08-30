# ADR-179：ConsumerBinding 迁移通知使用 durable outbox 与可验证 provider receipt

**Status**: Accepted  
**Date**: 2026-08-07  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.1

## Context

迁移 150 已把 breaking product transition 的通知状态和 evidence 纳入 promotion fail-closed，
但 `notification_status=delivered|failed` 仍可由调用方提交任意非空 JSON。它不能证明通知经过真实
provider，也无法在 worker 崩溃时保证 delivery terminal state 与 CAS migration state 一致收敛。

本切片必须复用现有 PostgreSQL control ledger，保持 endpoint/credential server-owned，并避免为一个
产品级通知场景引入 Kafka、第二套消费者状态机或新的 metadata authority。

## Options Considered

| Option | 优点 | 代价与风险 | Decision |
|---|---|---|---|
| 保留客户端 notification evidence | 改动最小 | 任意 JSON 可伪造 delivered，不能审计 provider | Rejected |
| migration recorder 内同步调用 webhook | 表面原子 | 外部 HTTP 占用数据库事务，失败语义和重试不可控 | Rejected |
| 引入 Kafka/独立通知服务 | 扩展能力强 | 当前吞吐和边界不支持新增运行系统复杂度 | Deferred |
| PostgreSQL transactional outbox + provider worker | 复用已认证模式，事务边界清晰，可租约/重试/dead-letter | 至少一次投递，仍需部署级 HA 与 receiver 幂等 | Accepted |

## Decision

1. migration 152 新增 tenant-scoped
   `consumer_binding_migration_notification_outbox`。pending migration state 在同一事务自动 enqueue，
   outbox 精确绑定 binding、from/to ProductVersion、source migration state ID 和 SHA-256。
2. destination 只保存逻辑引用 `alertmanager:consumer-binding-default`。Alertmanager URL、bearer token、
   route namespace 和 worker identity 仅来自 server-owned environment/secret，不接受请求提交 URL。
3. claim 使用 `FOR UPDATE SKIP LOCKED`、5-3600 秒 lease、最多 100 次尝试，并提供 retry、terminal
   failed receipt 和 stale pending supersede。默认最大尝试为 10。
4. done/failed 由数据库按完整 terminal document 生成 `receipt_sha256`。migration state terminal evidence
   必须且只能包含 `notification_id` 与 `receipt_sha256`；recorder 重新计算 receipt、核对 tenant、binding、
   version transition、provider status 和 source state，伪造 evidence 返回 forbidden。
5. `PlatformGateway` 在同一数据库事务内 terminalize outbox 并追加确定性 UUID、previous-SHA CAS-linked
   migration successor，避免“HTTP 已成功但 migration state 永久 pending”的崩溃窗口。最终失败采用相同
   settlement 路径。
6. `consumer_binding_notification_worker.py` 复用 Alertmanager v2 client，提供 signal shutdown、批量/lease/
   retry 配置、Prometheus metrics、Kubernetes namespace route label，并进入 Compose `alerts` profile。

## Trade-offs

- 投递语义是 at-least-once；stable Alertmanager labels 和数据库 receipt 保证可重放与可审计，但 receiver
  仍需按标签去重。
- 当前只有 Alertmanager adapter。邮件、企业 IM、webhook registry 或 service-specific destination 需要
  后续 provider contract，不在本 migration 扩展 channel。
- Compose service 使 worker 可部署，但本切片没有新增 Kubernetes HA/PodDisruptionBudget/告警规则；因此
  不能据此宣称生产 HA/RPO/RTO 或 AR-4 完成。

## Consequences

- promotion 不再接受人工制造的 delivered/failed JSON；只有 terminal outbox receipt 可解除通知阻塞。
- delivery、dead-letter、consumer acknowledgement 均保留独立 authority：provider receipt 证明投递，
  ConsumerBinding migration state 证明迁移阶段，bound consumer acknowledgement 仍由 consumer 主体提交。
- Product-level notification authority 已形成可验证纵向切片；Service Control Plane 服务级 binding/SLO、
  多 provider conformance、生产 HA 和恢复退出门仍未完成。

## Verification

- 跨模块回归：`197 passed, 1 skipped`。
- PostgreSQL 16 disposable certification：
  `.tmp/consumer-binding-notification-certification/report.json`。
- 报告 SHA-256：`d4f7c2a6151afc050ff32c1e90913c9440c5bb2720d77a4f94759debc54ebd6c`。
- 认证覆盖自动 enqueue、claim、done receipt、伪造 receipt 拒绝、ack 后 promotion、10 次失败 dead-letter、
  terminal failed state、gateway role 直写拒绝和跨租户零行。
- migration catalog 为 152 条，最后迁移为
  `152_consumer_binding_migration_notification_outbox`，catalog fingerprint 为
  `ace747819bc480af9a98c2394170e138438ca8e7cfe7ba84158da7bfe49a9ed3`。

## Revisit Triggers

- ConsumerBinding 通知量或 provider 数量证明 PostgreSQL outbox 已成为吞吐瓶颈；
- Service Control Plane 引入 service/endpoint scoped ConsumerBinding 与独立通知 routing authority；
- 需要 Kubernetes HA、跨区恢复、SLO 告警和 operator-governed dead-letter recovery。
