# Martin MVT provider adapter handoff

## GitHub continuation

- Continuation branch: `feat/gis-data-platform-mvt-gateway-20260808`
- Repository: `zhouning/gisdataagent`
- New-window resume: `git fetch origin && git switch feat/gis-data-platform-mvt-gateway-20260808`
- Read this handoff and [roadmap.md](../roadmap.md) before changing code. Do not reset or clean unrelated
  worktree changes from other vertical slices.

## 已完成

- 新增 [gis_provider_runtime.py](/Users/zhouning/gisdataagent/data_agent/gis_provider_runtime.py)：
  `GISProviderManifest`、`MVTProviderReleaseContext`、`MartinVectorTileProvider` 和 provider health/tile evidence。
- adapter 只读 health、catalog 和 MVT tile；release context 必须绑定精确 service/layer/style/TMS，zoom、坐标、
  media type 和 5xx/非 200 响应均 fail closed。
- `build_ready_observation` 生成可由现有 PlatformGateway 记录的
  `FrameworkAttemptObservation`，不在 provider 内保存 run/deployment 状态。
- 新增 [certify_martin_provider.py](/Users/zhouning/gisdataagent/scripts/certify_martin_provider.py)，支持实际
  Martin endpoint 的 discovery-only 或带 publication ID 的 read certification。
- 新增版本绑定的 operator-only Gateway route：
  `/api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf?service_urn=...`。route 复用 active
  `GISServiceControlProjection`，校验 tenant、active release key、MVT endpoint contract、Martin ready
  deployment、TMS zoom/坐标，并将 release key/state version 写入响应 header；provider contract 或 upstream
  故障均 fail closed。当前 route 固定 `private, no-store`，不向普通消费者开放。
- 修复开发环境 migration authority 的历史兼容性：151 的 rollback authority CHECK 使用 `NOT VALID`，保留
  既有 legacy rollback event，不伪造 authority，同时继续约束所有新写入；153 的 advisory-lock key 改为等价的
  字符串拼接，避免 SQLAlchemy 将 `:gis` 误识别为 bind parameter。迁移已在 Compose PostgreSQL 实际应用至
  154/154，catalog/database fingerprint 均为
  `65dabce7fa341c6c85ddab1e08483b3abae9a5fad512b926e5442e4323636066`。

## 验证证据

- `uv run pytest -q data_agent/test_gis_provider_runtime.py` -> `4 passed`。
- `uv run pytest -q data_agent/test_platform_gis_mvt_route.py data_agent/test_gis_provider_runtime.py
  data_agent/test_gis_service_control_plane.py data_agent/test_route_registration.py` -> `23 passed`。
- 真实 Compose Martin `v0.18.0`（容器内 `http://martin:3000`）：health `200/ready`，catalog 发现
  `map_publication`，并通过一次性 `public.agent_map_publications` publication fixture 完成真实 tile read：
  HTTP `200`、`application/x-protobuf`、1479 bytes、ETag 存在，tile SHA-256
  `dec5b71111f23adfbf4c157b4f283de2b7cf41923edde9469014f8829e07635f`。
- 报告：`.tmp/gis-martin-provider-certification/report.json`；SHA-256：
  `ea66d7b3ea47c031e14fd68445702798c0b4c8c9a03b07360e9cc7cd5460700f`。报告包含 publication ID、请求坐标、
  response evidence 与本次 release context 的 service/layer/style/TMS IDs。fixture 和容器临时副本已删除。
- manifest SHA-256：`177f2739bcf70016659940316dc6d044b8e377c6e454130b523c77eb76d7c080`；catalog SHA-256：
  `57b769c220a53bd86ff9257e4e8e7545ac5920efdd217649fa7ffdd20bc64b1c`。
- 重建后的 Compose app 已通过实际启动检查：容器 `healthy`，schema verification 为 `in_sync`，
  `GET http://127.0.0.1:8000/health` 返回 HTTP 200；未认证请求
  `GET /api/platform/v1/gis/tiles/...` 返回 HTTP 401。聚焦 route/provider/control-plane/registration 回归为
  `23 passed`（另有 1 个既有 Starlette/httpx deprecation warning）。

## 未完成边界

该切片不代表 Martin production-supported，也不代表 AR-4.3/AR-4.4 完成。虽然已有真实 tile read 和 Gateway
operator route，当前真实 Compose 认证的 release context 仍由认证脚本构造，且开发数据库当前没有 active
GIS service/release/endpoint fixture，因此 route 尚未在真实 active deployment 上做端到端 HTTP 认证；route
也未执行 ConsumerBinding/SubjectContext policy pushdown。尚未覆盖
OGC API Features、TileJSON/style、cache namespace/warmup、provider deployment dry-run、schema/CRS/extent/
visual/security/resilience conformance、Feature/MVT SLO、HA/RPO/RTO 或其他 provider。

## 下一步

在统一 ServiceReleaseBinding authority 中登记可重放的 Martin publication/deployment fixture，解决 Compose
Martin HTTP 与 `EndpointRevision` HTTPS 合同之间的 transport bridge，使用 PlatformRun 运行 provider
health/catalog/tile conformance，并把成功 observation 记录到 deployment；随后将 operator route 升级为带
ConsumerBinding/SubjectContext 的消费者 route，接入 version-bound cache namespace，不再扩展旧 table proxy
的权限或发布语义。
