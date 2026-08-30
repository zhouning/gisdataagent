# ADR-324: OGC API Features Consumer Authorization

## Status

Accepted for the AR-4 bounded consumer-read slice (2026-08-26)

## Decision

OGC API Features 使用独立于 MVT 的 `ogc_features.read` action 与
`ogc_features_read` purpose。授权仍复用既有 `service_policy_binding` 和
`service_consumer_binding` 表、tenant RLS、PlatformGateway recorder、ApprovalCase
发行、exact service definition/release 查询、撤销和续期事实，不新增第二套 registry。

Features Gateway route 在 provider 调用前固定以下范围：

- tenant-scoped service URN、active release、feature service、OGC API Features endpoint contract、ready pygeoapi deployment；
- active service policy 的 action 必须是 `ogc_features.read`；
- policy 命中的普通 GIS consumer role 必须有 exact-release、exact consumer、未过期且未撤销的 binding，binding action/purpose 和 `scope.operations=[read]` 必须匹配；
- operator/admin 仍可由 policy 直接放行，但不绕过 tenant、release、collection、provider 和审计约束；
- admission、denied、provider success/failure 都写入 security event ledger；outcome 只记录 provider invocation count、feature count、HTTP/media type 和内容 SHA-256，不记录响应正文。

`ServicePolicyBinding`/`ServiceConsumerBinding` 的 MVT profile 保持兼容；migration 239
只扩展允许的动作和按 service type 选择的 recorder 检查。Features 目前不声明 row/column/spatial/temporal
ABAC、provider-side policy pushdown、分页 token、复杂过滤、quota、共享缓存、HA 或生产身份。

## Rationale

MVT 与 Features 都是 GIS service release 的数据面，但协议的响应语义和后续策略边界不同，不能把
`mvt.read` 当作通用读取权限。把动作/目的分开，同时复用同一 exact-release authority，可以让审计和
撤销语义保持一致，也避免另造 active pointer 或 consumer registry。

## Verification

- `uv run pytest -q data_agent/test_gis_ogc_api_features_access.py data_agent/test_platform_gis_ogc_api_features_route.py data_agent/test_service_consumer_binding.py data_agent/test_gis_service_control_plane.py data_agent/test_platform_gateway.py`：125 passed。
- disposable PostgreSQL + 真实 `geopython/pygeoapi:latest`（0.25.dev0）active-release route 认证通过；migration 239、Features policy、provider 返回 2 个 Feature、collection mismatch `409`、非法 limit `400` 均通过。
- 报告：`.tmp/ogc-api-features-consumer-auth-certification/report.json`，SHA-256 `592e1ec7db67c9559dcec54044bb70cbfd316235452932c3307b2171a4a2bcdd`。

## Evidence boundary

报告属于 `real_provider_disposable_postgresql_control_fixture`，只证明一次性控制库、真实 pygeoapi
和 Gateway 的集成路径；不代表生产数据库、生产身份、消费者 binding 的真实审批发行、OGC CITE、ABAC
下推、性能 SLO、quota、缓存、HA 或灾备完成。
