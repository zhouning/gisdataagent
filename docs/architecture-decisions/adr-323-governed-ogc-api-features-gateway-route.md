# ADR-323: Release-bound OGC API Features Gateway route

## Status

Accepted for the AR-4 bounded data-plane slice (2026-08-26)

## Decision

新增 `GET /api/platform/v1/gis/features/{release_key}/collections/{collection_id}/items`，由既有
`PlatformGateway.get_gis_service_control_projection()` 读取 active projection 后再访问 provider。路由
要求：

- `service_urn` 必须属于当前身份 tenant，调用者必须是平台角色或 GIS consumer 角色；最终放行由 ADR-324 的 Features policy 决定；
- `release_key`、`collection_id` 必须分别匹配 active release 和 release layer key；
- active endpoint 必须是 `ogc_api_features`，contract 必须精确为
  `gda.ogc_api_features_endpoint.v1 + collection_id`；deployment 必须 `ready` 且 provider 为 `pygeoapi`；
- `limit` 只接受 1..1000，`bbox` 只接受有限且有序四元组；provider 4xx/5xx、错误 GeoJSON、错误媒体类型和
  provider transport failure 均 fail closed；
- provider origin 只从 Gateway 内部 `PYGEOAPI_URL` 注入，不使用 consumer-facing endpoint URI；响应暂时固定
  `private, no-store`，带 release、endpoint state version 和 collection headers。

Features 不复用 MVT 的 `mvt.read` ServicePolicyBinding，而使用独立的 `ogc_features.read` /
`ogc_features_read` profile。普通消费者还必须具备 exact-release、exact consumer 的 active
ServiceConsumerBinding；operator/admin 由 active Features policy 直接放行。行列/空间下推、分页 token、
复杂过滤、缓存和 quota 仍未实现。

## Rationale

这样数据面复用唯一的 service/release/deployment/endpoint authority，同时不会把 MVT 的授权合同误套到
Features。consumer binding、admission 和 outcome 证据均沿用既有 security ledger 与 approval-bound
control-plane authority。

## Verification

- `data_agent/test_platform_gis_ogc_api_features_route.py`：成功读取、collection mismatch、release/protocol/
  provider/state mismatch、非法 limit/bbox、tenant/role、provider 4xx/5xx 和 Features policy admission 共 7 项通过。
- `uv run pytest -q data_agent/test_platform_gis_ogc_api_features_route.py data_agent/test_platform_gateway.py -k 'ogc_api_features or routes_are_versioned or routes_are_visible'`：8 passed。
- 真实 disposable active-release certification：真实 `geopython/pygeoapi:latest`（`0.25.dev0`）+ 临时
  PostgreSQL + FastAPI Gateway route，返回 2 个 Feature；collection mismatch `409`、非法 limit `400`。
  报告 `.tmp/ogc-api-features-active-release-certification/report.json`，SHA-256
  `f605332fd034766cd56c7a5d2f9b01a73843690568c8b16305dd9d75412a243e`，receipt SHA-256
  `ce7aeda568fbde418fd54f923bd65e956db28c65d2907ca993c30b382b89e92a`。

## Evidence boundary

该证据证明 release-bound provider 到 Gateway 的 disposable 数据面链路，不证明生产 endpoint、生产身份、
OGC CITE、消费者授权、ABAC/policy pushdown、分页/过滤扩展、缓存、quota、HA 或性能 SLO。
