# ADR-100: Durable DataIncident Delivery to Alertmanager

**Status**: Accepted  
**Date**: 2026-08-01  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

## Context

ADR-099 建立了租户隔离的 `DataIncident` 权威账本和人工处置生命周期，但事故只能通过查询 API
发现。直接在检测事务中调用 Alertmanager/IM 会把数据库提交依赖于外部网络；提交后再异步发送又会
在进程崩溃时丢告警。平台需要可恢复、可去重且不复制事故真值的外部投递边界。

## Decision

### Transactional Notification Outbox

新增 migration `099_platform_incident_notification_outbox`：

- 每个 immutable `DataIncidentEvent` 由数据库 trigger 在同一事务创建一条
  `data_incident_notification_outbox`；事故事务回滚时通知也回滚；
- outbox 只绑定 incident/event/sequence、channel 和逻辑 `destination_ref`，不保存 URL、token
  或其他凭据；endpoint 与 secret 只存在于 worker 的服务端配置；
- migration 对历史事故只回填最新生命周期事件，避免部署时重放已经过时的 open 状态；
- 同一 incident 的后续事件必须等待较早事件完成，防止 resolved 先于 open 到达外部系统；
- delivery 使用 pending/in_flight/done/failed、租约、`FOR UPDATE SKIP LOCKED`、有界重试和
  tenant RLS。Gateway role 只有表级 SELECT 和 claim/complete/fail 函数 EXECUTE，没有
  INSERT/UPDATE/DELETE。

### Alertmanager Adapter

`data_agent.incident_notification_worker` 实现 Alertmanager v2 `POST /api/v2/alerts`：

- alert identity 标签在 open/acknowledged/resolved 之间保持稳定；状态、事件序号、原因和 actor
  放在 annotations；resolved 事件以 `endsAt` 关闭同一个 alert；
- URL 只允许无凭据、无 query/fragment 的绝对 HTTP(S) 地址；可从只读 token file 获取 bearer
  token，响应 redirect 或非 2xx 时 fail closed；
- HTTP 是 at-least-once。若接收成功后 worker 在 outbox complete 前崩溃，重投依赖稳定标签在
  Alertmanager 侧幂等覆盖，平台不声称 exactly-once；
- Compose 提供默认不启动的 `alerts` profile。未配置 endpoint 时 worker 不启动，不影响当前 app
  拓扑，也不能把 adapter 存在解释成生产告警已经部署。

## Evidence

- Compose migration ledger 为 101/101、strict、in sync；catalog/database fingerprint 一致。
- 合同、网关和 worker 定向测试 51 项、control-plane 回归 200 项通过；真实 PostgreSQL 集成 2 项
  通过，覆盖最小权限、RLS、event trigger、open -> acknowledged -> resolved 顺序、失败重试、
  完成和跨租户负向。
- 本地真实 HTTP rehearsal 从 `local-dev` outbox 领取并成功 POST 两个历史 high incident：
  `09674ef6-fac8-5a51-9adc-50a478c6b27d` 和
  `0ed1097c-56bc-5f9c-b968-9911d03c1517`。两次请求均返回 202，outbox 最终为 2 done、0 pending，
  无 retry/dead-letter。
- gateway static conformance 为 valid，仍暴露 17 个 OAuth2 platform operations；通知 worker 不新增
  未受治理的公网 API。

## Consequences

- 事故创建、处置和外部通知不再依赖 Web 进程内 background task，也不会因短暂网络失败丢失。
- Alertmanager 是通知投影，不是事故状态真值；外部 acknowledge/silence 不反写 `DataIncident`。
- 生产 Alertmanager endpoint、路由规则、IM/email receiver、on-call ownership、HA、metrics 和
  dead-letter 人工恢复尚未部署验证，因此 AR-1 production alerting gate 仍未完成。
- DolphinScheduler provider terminal `STOP` conformance、semantic retry、OIDC、HA、metadata restore
  及 101-migration PITR 仍是独立未完成项。
