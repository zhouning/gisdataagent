# Minimal GIS Service Control Plane handoff

## 已完成

- migration 153 新增最小 `GISServiceDefinitionVersion + ServiceDeploymentRevision + EndpointRevision` authority，
  复用既有 Resource、PlatformDefinition、DataProductVersion、PlatformRun 和 FrameworkAttemptObservation。
- 服务定义只接受当前 active、质量 passed 且有 governed lifecycle event 的精确产品版本；旧产品版本不能创建
  新定义，已存在定义仍可幂等重放。
- 部署状态机为 `planned -> deploying -> ready|failed`，每次转换使用 state-version CAS 和 append-only event；
  ready 必须绑定 succeeded Run 与精确 provider observation evidence。
- endpoint 只能从 ready deployment 产生，URI 必须是稳定、无 credential/query/fragment 的 HTTPS URI；协议与
  service type 由数据库校验。
- 每个服务只有一个 active endpoint pointer；activation/rollback 都通过 CAS function 和不可变 event，禁止
  Gateway 表级 UPDATE。
- `PlatformGateway` 已增加定义、部署、endpoint 的 register/get/transition/activate/projection API。

## 验证证据

- `uv run pytest -q data_agent/test_gis_service_control_plane.py data_agent/test_gis_service_control_plane_postgres.py data_agent/test_platform_gateway.py data_agent/test_migration_runner.py data_agent/test_platform_contracts.py data_agent/test_data_product_registry.py data_agent/test_consumer_binding.py data_agent/test_architecture_successor_data_product_release_postgis.py data_agent/test_approval_case_authority.py`
  -> `177 passed, 2 skipped`。
- `uv run python scripts/certify_gis_service_control_plane.py --report .tmp/gis-service-control-plane-certification/report.json`
  在 PostgreSQL 16 通过。
- 报告 SHA-256：`e4212667acf835aaacf51ac3b41ae152e922a237e608d1487f491bbd7b5941d4`。
- migration catalog：153；最后迁移：`153_gis_service_control_plane`；fingerprint：
  `9f17eceddedd61b245357a78bdb595fbbff1d4737dd2a56c7a84fb2a6223a3e0`。
- disposable database 和 login role 已清理，没有启动新的 Compose 服务。

## 未完成边界

该切片只完成最小服务控制面 authority，不代表 AR-4 或完整 GIS Service Control Plane 完成。尚未覆盖：
Layer/Style/TMS/Cache/Policy、service-scoped ConsumerBinding、ServiceSLO/DataIncident、suspend/retire、真实
pygeoapi/GeoServer/Martin/TiTiler/STAC/ArcGIS provider adapter、Gateway 数据面、OGC/安全/性能 conformance、
缓存一致性、多 region endpoint set、Kubernetes HA 和生产 RPO/RTO。

## 下一步

优先实现 AR-4.2 的 `LayerDefinitionVersion + StyleDefinitionVersion + TileMatrixSetDefinitionVersion` 最小组合，
使 feature/MVT 代表服务的 schema/CRS/extent、style/TMS 和 cache namespace 与本次 service definition、
deployment 和 active endpoint revision 同一 release binding；随后接入一个真实 provider adapter 和 conformance
smoke，不新增平行 catalog 或自研 GIS server。
