# ADR-177：正式 ConsumerBinding authority 取代过渡授权作为产品消费者影响来源

**Status**: Accepted  
**Date**: 2026-08-07  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-3、AR-4.1

## Context

ADR-122 已经让 `DataProductVersion` promotion 在版本锁定分发授权存在时 fail closed，
但迁移 105-108 的 `agent_data_requests` 仍只是资产级兼容证据。它没有正式产品消费者的
purpose、scope、Product version range、credential reference、quota 或 compatibility evidence，
也无法成为服务生命周期的消费者真值。

## Decision

1. 新增租户隔离、append-only 的 `gda_control.consumer_binding`，每条记录绑定一个
   `DataProduct`、typed `consumer_ref`、purpose、scope、产品版本上下界、credential reference、
   quota、expiry、compatibility fingerprint/evidence 和创建主体。
2. `binding_sha256` 覆盖全部不可变字段；`record_consumer_binding` 使用 `SECURITY DEFINER`、
   tenant context 和 `ON CONFLICT DO NOTHING`，保证重复提交返回同一 immutable payload，gateway
   不能直接 `INSERT/UPDATE/DELETE` 表。
3. promotion impact 先调用 `active_consumer_binding_impact`，只返回当前版本范围内且未过期的
   formal binding。若 authority 尚未部署或没有 formal binding，才回退到迁移 108 的过渡授权函数；
   过渡表不再是唯一消费者 authority。
4. migration 150 增加按 `from_product_version_id -> to_product_version_id` 建模的 append-only
   `consumer_binding_migration_state`。每次状态推进都必须携带前一状态 SHA-256，并在同一产品
   advisory lock 下追加；它固化 `compatibility_conclusion`、`notification_status`、通知证据、
   `migration_deadline` 和 typed consumer acknowledgement。
5. formal impact 升级为 `gda.data_product_promotion_impact.v3`。impact fingerprint 覆盖最新
   migration state、通知状态、截止时间和 acknowledgement；缺状态、indeterminate compatibility、
   未送达 breaking 通知或缺 consumer acknowledgement 均形成 `promotion_blockers`，promotion
   fail closed。操作员仍需确认最新完整 impact fingerprint。

## Trade-offs

- Product binding 先独立于 Service Control Plane，保持本切片可在现有产品 registry 上验证；服务级
  endpoint/SLO、通知和迁移窗口仍需后续 authority。
- 版本范围以 `vMAJOR.MINOR.PATCH` 数组比较实现，简单且可审计，但暂不表达 feature flag 或字段级
  capability negotiation。
- 旧 `agent_data_requests` 继续作为迁移期 fallback，避免未迁移消费者被静默忽略；这意味着正式
  ConsumerBinding 覆盖率仍需要运营指标，不能把“有一条 formal binding”当作全租户迁移完成。

## Consequences

- promotion preview 和 promotion acknowledgement 现在能引用可验证的正式消费者合同，并保留
  compatibility evidence、quota/expiry 及迁移状态证据。状态变更不会覆盖旧行，旧 impact fingerprint
  会立即失效。
- notification delivery 的 provider/outbox 仍是后续运营域；migration state 只记录经过授权路径验证的
  delivery evidence，不把通知表伪装成消费者 acknowledgement authority。secret rotation、DataSLO/
  DataIncident 和 incident-bound rollback 尚未实现。
- AR-0、AR-1、AR-2 继续 `in_progress`，AR-3/AR-4 继续 `planned`；该切片不构成生产平台或
  下一代 Data Platform 完成声明。

## Verification

- `data_agent/test_consumer_binding.py`、`data_agent/test_data_product_registry.py`：27 passed。
- `scripts/certify_consumer_binding_authority.py` 在一次性 PostgreSQL 16 数据库中验证：RLS、
  recorder 首次/重放幂等、migration state CAS/重放、通知/截止时间/ack 指纹失效、旧 fingerprint
  fail closed、最新 fingerprint promotion、普通登录角色直写 `42501` 拒绝及跨租户零行；报告为
  `.tmp/consumer-binding-certification-v2/report.json`，SHA-256 为
  `323a250f508ca92166ffd13f95c5ad24bf42c2143ab863bddb65ef7b4feb6b4b`。
- migration catalog 为 150 条，最后迁移为 `150_consumer_binding_migration_state`，catalog fingerprint 为
  `48e8ac86ff38ac3cf6c3aa255a9f60930007d8641e8f95a206869eddf024cb8e`。

## Revisit Triggers

- formal binding 覆盖率达到首批产品消费者迁移门，并需要通知、迁移期限和 deprecation 状态机；
- Service Control Plane 引入服务级 credential/rate/cost quota 或 endpoint consumer binding；
- rollback 需要绑定已批准的 DataIncident 或 Human rollback ApprovalCase。
