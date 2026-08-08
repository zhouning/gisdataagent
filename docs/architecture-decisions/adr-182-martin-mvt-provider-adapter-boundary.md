# ADR-182：Martin MVT Provider Adapter 只承载受治理的只读数据面

**Status**: Accepted
**Date**: 2026-08-08
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.3
**Related decisions**: [ADR-017](adr-017-gis-service-publishing-control-plane-and-provider-runtime.md) ·
[ADR-181](adr-181-atomic-gis-service-release-binding.md)

## Context

仓库已有 Martin Compose runtime 和旧的 HTTP proxy，但旧 proxy 直接按 table/publication 路由请求，不验证
`ServiceReleaseBinding`，也不产生可供 `ServiceDeploymentRevision` 使用的 provider evidence。继续扩展旧 proxy
会让 provider route 成为第二发布路径。

本切片需要一个真实、可测试的 MVT provider boundary，同时保持 Service Control Plane、PlatformRun 和
FrameworkAttemptObservation 为唯一权威。

## Decision

1. 新增 `MartinVectorTileProvider`，只实现 read-only `health`、`catalog` 和 MVT tile read；不创建、修改或
   激活 service、deployment、endpoint 或 provider-side catalog。
2. `GISProviderManifest` 固化 `martin` provider/version、MVT protocol、catalog/health/MVT-read capability 和
   manifest SHA-256。未声明的 capability 不可调用。
3. `MVTProviderReleaseContext` 必须由同一 `ServiceReleaseBinding` 与精确 TMS 构造；vector-tile service、TMS
   service/layer ID、zoom range 和 provider layer reference 不一致时 fail closed。
4. tile 请求校验 zoom/x/y、MVT media type 和 provider HTTP 状态；5xx 为 unavailable，非 MVT 200 response 为
   contract error。adapter 不缓存、不保存权限结果、不维护异步状态。
5. `build_ready_observation` 生成现有 `FrameworkAttemptObservation` evidence，绑定 run、release/layer/style/TMS
   IDs、provider version、endpoint 和 health evidence；调用方必须通过 PlatformGateway 记录它。
6. 旧 `/api/tiles/martin/*` proxy 保持兼容，但不被标记为新的 governed publish path；后续 Gateway route 应改为
   使用 release context 调用 adapter。

## Trade-offs

- 只读 MVT 首批能力不能覆盖 feature query、style rendering、cache warmup 或 provider deployment；这些能力继续
  作为独立 conformance gates。
- provider layer reference 和 query 参数仍需由 deployment/provider placement 提供，不能从用户请求直接拼接。
- Martin 版本与镜像仍需在真实 tile read、schema/CRS/extent、security 和 resilience conformance 后才可进入
  production-supported 清单。

## Verification

- provider contract tests：`4 passed`，覆盖 manifest fingerprint、TMS mismatch、health/catalog/tile/evidence、
  media-type 和 5xx fail-closed。
- 真实 Compose Martin `v0.18.0`：health HTTP `200`，catalog 发现 `map_publication`；使用一次性 governed
  publication fixture 完成 tile-read，HTTP `200`、MVT media type、1479 bytes、ETag 和 tile SHA-256
  `dec5b71111f23adfbf4c157b4f283de2b7cf41923edde9469014f8829e07635f` 均通过。fixture 认证后删除。
- 认证报告：`.tmp/gis-martin-provider-certification/report.json`，SHA-256
  `ea66d7b3ea47c031e14fd68445702798c0b4c8c9a03b07360e9cc7cd5460700f`；报告同时记录 publication、坐标和
  release context IDs。该 context 是认证用的 typed contract，不等同于已接入真实 deployment authority。
- Ruff、compileall 和 diff check 通过。

## Revisit Triggers

- 需要固定、治理过的 publication/deployment fixture，以扩展真实 MVT tile read 到 empty/invalid tile conformance；
- Feature/OGC API、style/TileJSON、cache namespace 或 provider deployment dry-run 需要进入同一 SPI；
- Martin 需要事务写入、动态 catalog 或多 region active-active；
- provider HTTP boundary 需要 Gateway policy pushdown、signed URL 或流量/缓存治理。
