# ADR-184：通过 GIS Control Plane 提供版本绑定的 MVT Operator Route

**Status**: Accepted
**Date**: 2026-08-08
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.4
**Related decisions**: [ADR-181](adr-181-atomic-gis-service-release-binding.md) ·
[ADR-182](adr-182-martin-mvt-provider-adapter-boundary.md)

## Context

已有 `MartinVectorTileProvider` 能够读取真实 MVT，但旧 `/api/tiles/martin/*` 和 map publication
proxy 不读取 `GISServiceControlProjection`，会绕过 active release、deployment state 和 endpoint
authority。下一步需要一个可测试的 Gateway boundary，同时不能在 ConsumerBinding、policy 和 cache
authority 尚未完成时伪装成普通消费者数据面。

## Decision

1. 新增 `GET /api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf`，通过 `service_urn` query
   选择 tenant-scoped GIS service。
2. route 只允许 `platform_operator`/`admin`，从 `PlatformGateway.get_gis_service_control_projection()`
   读取 active definition、release、TMS、deployment 和 endpoint；禁止从请求拼接 provider host、layer
   或 publication query。
3. 请求中的 `release_key` 必须等于 active `ServiceReleaseBinding.release_key`；service 必须是
   `vector_tile`，endpoint 必须是 MVT，deployment 必须 `ready` 且 provider 为 Martin。
4. endpoint contract 固定为 `gda.mvt_endpoint.v1`，至少包含经过 UUID 校验的 `publication_id`，并由
   `MVTProviderReleaseContext.from_release()` 绑定精确 service/layer/style/TMS 后调用 provider。
5. route 在 Gateway 边界校验 TMS zoom/x/y、媒体类型、upstream ETag 和 provider failure；响应带 release
   key/state version，缓存固定 `private, no-store`，直到 policy/cache authority 另行批准。
6. 该 route 是 operator preview/control surface，不授予 ConsumerBinding、resource/column/row/spatial/
   temporal/purpose policy，也不替代旧 proxy 的兼容性；普通消费者 route 必须经过后续 AR-4.4 gate。

## Trade-offs

- 现在能证明 active release 到 provider 的 Gateway 数据面边界，但 operator-only 限制使其不能直接作为
  生产消费 API。
- `no-store` 放弃缓存收益，换取在 cache namespace 和权限语义尚未冻结时不产生错误的跨 revision/跨主体
  缓存行为。
- Martin-specific endpoint contract 暂不覆盖 Feature、Raster、STAC 或其他 provider；各 provider 继续使用
  独立 capability profile。

## Verification

- `data_agent/test_platform_gis_mvt_route.py`：未认证、active release mismatch、非法 TMS 坐标、未绑定
  publication、成功 MVT response/header 五项测试通过。
- route/provider/control-plane 聚焦回归：`23 passed, 1 warning`。
- 真实 Martin tile-read 证据仍见 [ADR-182](adr-182-martin-mvt-provider-adapter-boundary.md)；本 ADR 的 route
  尚未宣称真实 active deployment 的端到端 HTTP certification。

## Revisit Triggers

- Service-level ConsumerBinding、SubjectContext/PolicyDecision 和 cache namespace authority 可由 Gateway
  读取并在请求中证明；
- 可重放的真实 ServiceReleaseBinding/DeploymentRevision fixture 完成 route 的 Compose/K8s HTTP 认证；
- 需要把 route 扩展到 TileJSON/style、Feature/Raster/STAC、signed URL、quota 或 multi-provider placement。
