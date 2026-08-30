# ADR-099: DataIncident and Cancellation Convergence

**Status**: Accepted  
**Date**: 2026-08-01  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

## Context

ADR-098 保证只有 DolphinScheduler `STOP` evidence 才能把 Run 判为 `cancelled`，但 provider 在
STOP 请求后可能返回 `FAILURE`、`SUCCESS` 或长期停留在 `READY_STOP`。这些状态不能被猜测为
取消成功，同时也不能让平台 Run 无限停留于 `cancelling`/`reconciling`。平台还缺少一等公民
incident、租户级 attention queue 和可审计的人工确认/解决生命周期。

## Decision

### First-class Incident Ledger

新增 `DataIncident` 和 `DataIncidentEvent` 合同，以及 migration
`098_platform_data_incident`：

- incident 的 Run、dedupe key、类型、级别、摘要、provider observation、details、detector 和
  opened time 由 SHA-256 内容指纹绑定；同一 identity 的载荷漂移 fail closed；
- 当前状态只允许 `open -> acknowledged -> resolved` 或 `open -> resolved`，不允许 reopen、
  self-transition 或解决后修改；
- cause/evidence binding 不可变，状态只能通过 security-definer CAS function 修改，每次变化
  追加不可变 event；
- 两张表均 FORCE RLS。gateway role 只有 incident `SELECT/INSERT`、event `SELECT` 和状态函数
  `EXECUTE`，没有表级 UPDATE/DELETE。

### Provider Terminal Mismatch

当已交付 governed cancel command，且对应 DolphinScheduler observation 为 `FAILURE`、`SUCCESS`
或 `PAUSE` 时，gateway 在一个 PostgreSQL 事务中：

1. 幂等保存并校验 observation；
2. 创建 high-severity `provider_cancel_terminal_mismatch` incident；
3. 将仍处于 `cancelling` 或 `reconciling` 的 Run CAS 迁移为 `failed`；
4. 在 RunEvent details 中绑定 incident ID、type 和 fingerprint。

这不把 provider failure 解释成 cancel success，也不创建 DataProductVersion。相同 evidence 重放
返回已有 incident 和终态 Run。

### Bounded Convergence

若 provider 一直处于 `READY_STOP` 等非终态，reconcile command 继续使用既有有界退避。达到
`max_attempts` 时，command、`cancellation_convergence_timeout` incident 和 Run `failed` 在同一
gateway 事务中收敛，避免永久 pending。后续 semantic retry 必须创建新的 Run identity；不得
复活该终态 Run。

### Operator Remediation

新增三个 OAuth2 平台操作：tenant-scoped incident list（支持 status/run filter）、incident get 和
human-only CAS transition。open/high incident 构成数据库内 attention queue；确认和解决只改变
incident 生命周期，不改写 Run/provider evidence。外部 Alertmanager、邮件或 IM 投递仍是后续
production foundation 工作，不能把查询 API 宣称为外部告警已完成。

历史证据修复使用 `scripts/converge_dataops_cancel_incident.py`。CLI 只接受 tenant、Run 和已存在的
observation ID，provider state 从 immutable observation 读取，且 gateway 再验证已完成的 governed
cancel command；操作员不能手填 provider 结果。

## Evidence

- Compose migration ledger 为 100/100、strict、in sync；migration、database fingerprint 一致。
- control-plane 定向测试 195 项通过、2 项按环境跳过。
- 真实 PostgreSQL 集成 2 项通过，覆盖 incident RLS、append-only、非 STOP 终态原子失败、幂等
  重放、跨租户不可见、open/acknowledged/resolved 事件，以及取消对账重试耗尽自动开 incident。
- 历史 provider `FAILURE` Run `7ce30152-147c-5cab-b68d-8acb6ec3e48a` 收敛为 `failed`，incident
  `0ed1097c-56bc-5f9c-b968-9911d03c1517`；真实重放返回 `incident_created=false`。
- 历史 provider `SUCCESS` after cancel Run `874b4da8-7cdd-5ab5-aa75-bfb97df604b2` 收敛为
  `failed`，incident `09674ef6-fac8-5a51-9adc-50a478c6b27d`。
- rebuilt Compose app healthy；`/health`、`/openapi.json` 为 200，17 个 platform operation ID
  唯一，未认证 incident list 返回结构化 401。

## Consequences

- cancellation 的 provider truth、platform verdict 和 operator remediation 被明确分层。
- Run 不再因为 provider 非 STOP 终态或重试耗尽而无限 pending。
- incident resolved 不表示原 Run 成功，也不表示 provider terminal cancel conformance 已通过。
- DolphinScheduler 3.4.2 的 shell cancel 缺陷和上游修复验证仍阻塞 AR-1 provider cancel 退出门；
  [ADR-100](adr-100-durable-incident-alertmanager-delivery.md) 已补 durable Alertmanager 投递合同和
  本地真实 HTTP 演练，但生产 endpoint/IM/on-call、OIDC/workload identity、HA、metadata restore
  和 semantic retry 仍未完成。
