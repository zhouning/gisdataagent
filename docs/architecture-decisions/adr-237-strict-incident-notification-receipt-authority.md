# ADR-237: Strict Incident Notification Receipt Authority

**Status**: Accepted  
**Date**: 2026-08-22  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4

## Context

226 为已有 DataIncident notification outbox 增加了 receipt 字段，并把旧 terminal 行标成
`accepted=false` 的 legacy evidence。若新 completion authority 仍接受 legacy payload，worker 或
调用方就能把“未知的历史状态”重新当作成功结算，破坏 receipt 的证据含义。

## Decision

Migration `227_incident_notification_receipt_strict_authority` 替换
`complete_data_incident_notification(tenant, notification, worker, receipt)`：

- 新的 `done` 必须带 `gda.alertmanager_provider_receipt.v1`，provider 为 Alertmanager、accepted
  为 true、HTTP 状态为 2xx、destination 与 outbox 精确相等，并提供 `accepted_at`。
- 226 的 legacy receipt 只读保留，不能作为新的 completion 输入；缺失、伪造、跨 destination 或
  非 2xx receipt 在数据库事务内以 `22023` 拒绝。
- 227 不新增 outbox、队列或事故真值；仍由同一 Gateway role 通过函数执行，表直接写入权限保持关闭。

## Evidence

- 开发库已通过 migration authority 应用到 `227/227 in_sync`；catalog/database fingerprint 为
  `e8358ecefeb4efa5adcfbff767209eab6ea957740cc91cf4c86d396fea5a26a9`。
- 226/227 fresh PostgreSQL 16.14 GIS ServiceSLO incident certification 通过：incident 原子创建、
  幂等 replay、共享 event/outbox、provider receipt/hash 持久化、stale fingerprint、缺失 binding、
  跨租户和 activation lock 竞争均通过，Gateway 无 GIS binding 表写权限。

## Consequences

通知的 `done` 现在具有清晰的外部接受语义；历史 unknown 不会被追认。生产 Alertmanager HA、
receiver/on-call、metrics/dead-letter 运维、多 provider routing、自动 remediation、worker HA/RTO
和 production DR 仍未完成，AR-4 继续保持 `in_progress`。
