# ConsumerBinding authority handoff

## 已完成

- 新增 [149_consumer_binding.sql](../../data_agent/migrations/149_consumer_binding.sql)：formal
  `consumer_binding` append-only ledger、tenant RLS/`FORCE ROW LEVEL SECURITY`、不可变触发器、
  Product FK、版本范围/quota/expiry/compatibility constraints。
- 新增 [consumer_binding.py](../../data_agent/consumer_binding.py)：不可变 Pydantic contract、
  canonical SHA-256 fingerprint 和 typed consumer reference。
- `PlatformGateway.register_consumer_binding()` 只调用 SECURITY DEFINER recorder；
  `list_consumer_bindings()` 只经 gateway tenant transaction 读取。
- `DataProductRegistry._promotion_impact()` 先读取 formal version-ranged binding，formal authority
  不可用或没有记录时才回退迁移 108 的过渡分发授权；impact snapshot 新增 authority/binding evidence。
- 新增 [150_consumer_binding_migration_state.sql](../../data_agent/migrations/150_consumer_binding_migration_state.sql)：
  按产品 from/to version 追加兼容性结论、通知状态/证据、迁移截止时间和 typed consumer acknowledgement；
  状态通过 previous SHA-256 CAS 串联，并与 binding recorder、promotion 共用产品 advisory lock。
- `PlatformGateway.record_consumer_binding_migration_state()` 和列表读取已接入；promotion impact
  升级为 `gda.data_product_promotion_impact.v3`，任何状态、通知、截止时间或 acknowledgement 变化
  都会改变 fingerprint。缺状态、indeterminate/breaking 未完成迁移门时 promotion fail closed。

## 证据

- 单元与 registry 回归：`uv run pytest -q data_agent/test_consumer_binding.py data_agent/test_data_product_registry.py`
  -> `27 passed`。
- 认证入口：`uv run python scripts/certify_consumer_binding_authority.py`
- 一次性 PostgreSQL 16 认证报告：`.tmp/consumer-binding-certification-v2/report.json`
- 报告 SHA-256：`323a250f508ca92166ffd13f95c5ad24bf42c2143ab863bddb65ef7b4feb6b4b`
- migration catalog 已从 149 条推进到 150 条，最后迁移为 `150_consumer_binding_migration_state`，catalog
  fingerprint 为 `48e8ac86ff38ac3cf6c3aa255a9f60930007d8641e8f95a206869eddf024cb8e`。
- 认证断言：首次 recorder `created=true`、幂等重放 `created=false`、registry preview 返回 formal
  authority 和 1 条 active version-range binding、普通临时登录角色直接 SQL `INSERT` 被 PostgreSQL
  `42501` 拒绝。
- migration-state certification：三个 append-only state snapshot（pending -> delivered -> acknowledged）
  均按 CAS 写入，首次 state replay `created=false`，每次状态变更产生新 impact fingerprint；旧
  fingerprint 被拒，最新 acknowledgement 后 promotion 通过，state table 跨租户查询为零行且直接 SQL
  `INSERT` 被 `42501` 拒绝。

## 未完成边界

这只是产品消费者 authority 的 verified slice，不代表 AR-0/AR-1/AR-2 或下一代 Data Platform 完成。
通知 provider/outbox 的生产投递、DataSLO/DataIncident、incident-bound rollback、Service Control Plane
的服务级 binding、生产 OpenMetadata/Gravitino/DolphinScheduler、HA/RPO/RTO 和多租户恢复仍按 roadmap
退出门推进；本切片只记录已验证的通知 evidence，不宣称生产通知系统已完成。

## 下一步

沿现有 product registry 同一 advisory-lock 事务已接入兼容性结论、通知状态、迁移截止时间和 acknowledgement。
下一切片进入 DataSLO/DataIncident authority，并为 rollback 增加 incident 或 Human rollback ApprovalCase
绑定；不要在本切片同时实现 incident-bound rollback。
