# ADR-236: DataIncident Notification Provider Receipt

**Status**: Accepted  
**Date**: 2026-08-22  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4

## Context

ADR-100 把 DataIncident lifecycle event 写入 durable notification outbox，并以 Alertmanager
v2 worker 投递。原 outbox 的 `done` 只表示 worker 在自己的租约内完成了数据库更新；它没有保存
外部 provider 返回的 HTTP 状态、destination 或接受时间。发生重投、审计或故障调查时，平台只能
证明“有一次完成”，不能证明“哪一个外部端点接受了哪一份投影”。

## Decision

Migration `226_incident_notification_provider_receipt` 继续复用
`gda_control.data_incident_notification_outbox`，新增 `provider_receipt`、`receipt_sha256`
和 `terminal_worker_id`：

- Alertmanager 只有在 2xx、稳定 destination、`accepted_at` 存在时才能由 Gateway 原子结算为
  `done`；receipt 绑定 notification、incident event、attempt、worker 和 terminal time，数据库
  计算 SHA-256，Gateway role 不能直接修改表。
- 重试中的 `pending`/`in_flight` 行不带 receipt；达到 `max_attempts` 的 `failed` 行保存失败
  原因和终态 hash，仍不写 provider acceptance。
- 226 上线前已经完成的旧 `done` 行被标记为
  `gda.data_incident_notification_legacy_receipt.v1`、`accepted=false`，明确表示“未知”，不
 追认历史外部投递；这个 legacy receipt 只能被读取，新的 complete authority 不接受它。
- worker 继续使用至少一次投递和稳定 Alertmanager labels；receipt 是平台的外部接受证据，不是
  exactly-once 或 Alertmanager 自身持久性的证明。

## Evidence

- 开发 PostgreSQL migration ledger 已由 `221/225` 前向应用至 `226/226 in_sync`，catalog/database
  fingerprint 均为
  `dfe4b17c4dadd8327b0cc4b6cf794dbd679c3d6a1b95bda60887aad54cd33bbc`。
- 开发库 8 条历史 `done` notification 均有 legacy receipt 和 hash；9 条 pending notification
  保持空 receipt/hash。
- Incident worker、contract 定向测试 `34 passed`；Gateway static conformance valid；Python
  compile 和 diff whitespace 检查通过。

## Consequences

平台现在能把“外部接受”与“worker 完成”区分开，并能对失败终态做不可变审计。尚未完成的仍包括
生产 Alertmanager HA、receiver/on-call 配置、metrics/dead-letter 运维、多 provider routing、
自动 remediation、worker HA/RTO 和 production DR；本 ADR 不关闭这些 AR-4 退出门。
