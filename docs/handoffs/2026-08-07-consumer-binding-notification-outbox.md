# ConsumerBinding migration notification outbox handoff

## 已完成

- migration 152 新增 tenant RLS、不可直接写的 durable outbox，并在 pending migration state 插入事务内
  自动 enqueue；通知绑定 binding、from/to ProductVersion 和 source state SHA-256。
- claim/complete/fail 使用 lease、`FOR UPDATE SKIP LOCKED`、retry、10 次默认 dead-letter 和 stale pending
  supersede；done/failed 均由数据库生成可复核 receipt SHA-256。
- migration state 的 terminal evidence 已收紧为精确 `notification_id + receipt_sha256`。数据库 recorder
  会复算 receipt 并核对 tenant/binding/version/source state；任意人工 delivered evidence 被拒绝。
- `PlatformGateway` 增加 claim/complete/fail/list 方法，并把 outbox terminal state 与 deterministic CAS
  migration successor 放在同一事务。
- 新增 `consumer_binding_notification_worker.py`：Alertmanager v2 provider、server-owned URL/token、route
  namespace、signal shutdown、metrics 和 Compose `alerts` profile。

## 验证证据

- `uv run pytest -q data_agent/test_consumer_binding.py data_agent/test_consumer_binding_notification_worker.py data_agent/test_data_product_registry.py data_agent/test_architecture_successor_data_product_release_postgis.py data_agent/test_migration_runner.py data_agent/test_platform_contracts.py data_agent/test_platform_gateway.py data_agent/test_incident_notification_worker.py data_agent/test_approval_case_notification_worker.py data_agent/test_approval_case_authority.py`
  -> `197 passed, 1 skipped`。
- `uv run python scripts/certify_consumer_binding_authority.py --report .tmp/consumer-binding-notification-certification/report.json`
  在 PostgreSQL 16 通过。
- 报告 SHA-256：`d4f7c2a6151afc050ff32c1e90913c9440c5bb2720d77a4f94759debc54ebd6c`。
- migration catalog：152；最后迁移：`152_consumer_binding_migration_notification_outbox`；fingerprint：
  `ace747819bc480af9a98c2394170e138438ca8e7cfe7ba84158da7bfe49a9ed3`。
- PostgreSQL 认证覆盖 done receipt、伪造 receipt forbidden、10 次失败 dead-letter/failed successor、
  gateway role 直写 `42501`、RLS 跨租户零行和 acknowledgement 后 promotion。

## 运行配置

- 启动入口：`python -m data_agent.consumer_binding_notification_worker`。
- Compose profile：`docker compose --profile alerts up consumer-binding-notification-worker`。
- 必填：`GDA_CONSUMER_BINDING_NOTIFICATION_TENANT_ID`、`GDA_ALERTMANAGER_URL`。
- secret file：`GDA_ALERTMANAGER_BEARER_TOKEN_FILE`；不要把 token 放入 URL。
- terminal state actor：`GDA_CONSUMER_BINDING_NOTIFICATION_RECORDED_BY`，必须是 typed platform subject。

## 未完成边界

该切片完成的是 Product-level ConsumerBinding migration notification authority，不代表下一代 Data
Platform 或 AR-4 完成。尚未完成的主要退出门包括 GIS Service Control Plane 的 service/endpoint scoped
ConsumerBinding 与 ServiceSLO、Kubernetes HA/PDB/告警和 dead-letter operator recovery、多 provider
conformance、生产 OpenMetadata/Gravitino/DolphinScheduler 组合验收，以及跨集群 RPO/RTO。

## 下一步

优先进入 AR-4.2 的最小服务控制面切片：以 active DataProductVersion 为 source，建立
`GISServiceDefinitionVersion + ServiceDeploymentRevision + EndpointRevision` authority，并让服务级
ConsumerBinding/SLO 复用本次 receipt/outbox 模式，不新建平行 catalog 或第二套产品 registry。
