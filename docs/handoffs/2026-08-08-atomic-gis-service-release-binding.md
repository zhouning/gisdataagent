# Atomic GIS Service Release Binding handoff

## 已完成

- migration 154 新增不可变 `LayerDefinitionVersion`、`StyleDefinitionVersion`、
  `TileMatrixSetDefinitionVersion` 和原子 `ServiceReleaseBinding` authority。
- layer 强制绑定服务源产品的精确 output ResourceVersion，并固化 geometry/schema/CRS/extent；style 归属精确
  layer；layer-scoped TMS 不能与其他 layer 混搭，vector-tile release 必须包含 TMS。
- 新 `ServiceDeploymentRevision` 必须引用一个完整 release。历史 migration 153 行保持可读，旧 deployment
  recorder 已对 Gateway 撤权，insert trigger 同时拒绝无 release 新记录。
- endpoint 创建和 active endpoint CAS 均由数据库复核 release completeness；active projection 一次返回完整
  definition/release/layer/style/TMS/deployment/endpoint。
- 四张新表强制 tenant RLS 和 append-only，Gateway 只有 SELECT 与 SECURITY DEFINER recorder 权限。

## 验证证据

- 聚焦回归：`179 passed, 2 skipped, 1 warning`。
- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/gis_agent uv run pytest -q data_agent/test_gis_service_control_plane_postgres.py`
  -> `1 passed`。
- PostgreSQL 16 disposable certification：
  `.tmp/gis-service-control-plane-certification/report.json`，状态 `passed`。
- 报告 SHA-256：`87b069715ec2be651c647d6f314b6bdc3eca11cfd1ccf5bc5aaa8d77ea98fa58`。
- migration catalog：154；最后迁移：`154_gis_service_release_binding`；fingerprint：
  `5c313a739edc0346194df3709d4bc7c40199eb36d485b4294d6dfb5d94cb2d80`。
- Ruff、compileall、`git diff --check` 通过；disposable database/login role 由 certifier finally 清理。

## 未完成边界

该切片完成的是 AR-4.2 的发布版本组合 authority，不代表 AR-4 或完整 GIS Service Control Plane 完成。尚未覆盖
多 layer release manifest、CachePolicy、ServicePolicy、service-scoped ConsumerBinding、ServiceSLO/DataIncident、
suspend/retire、真实 pygeoapi/Martin/GeoServer/TiTiler/STAC/ArcGIS provider adapter、Gateway 数据面、OGC/安全/
视觉/性能 conformance、多 region endpoint set、Kubernetes HA 和生产 RPO/RTO。

## 下一步

优先接入一个真实 Feature 或 MVT provider adapter：由统一 PlatformRun 生成 provider revision 和 observation，
使用当前 release binding 部署并跑 schema/CRS/extent/protocol smoke；随后再引入 version-bound CachePolicy 和 cache
namespace/warmup evidence，不新增 provider-side catalog 或独立 active pointer。
