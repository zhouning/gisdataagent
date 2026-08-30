# ADR-181：GIS Layer、Style、TMS 以原子 Release Binding 发布

**Status**: Accepted  
**Date**: 2026-08-08  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.2

## Context

ADR-180 已建立 ServiceDefinition、DeploymentRevision、EndpointRevision 和 active endpoint CAS，但一个服务
revision 尚未固化 layer schema/CRS/extent、style 和 tile matrix set。若这些对象拥有独立 active pointer，发布
过程中会出现 service、layer、style、TMS 跨版本混搭；若继续使用 provider 内可变配置，又会使 provider 成为
第二发布真值。

本切片必须复用既有 `DataProductVersion`、GIS service definition、PlatformRun 和 PostgreSQL authority，不引入
平行 GIS catalog、事件总线或自研 GIS server。

## Decision

1. `LayerDefinitionVersion` 归属精确 `GISServiceDefinitionVersion`，并必须引用该服务源
   `DataProductVersion.output_resource_version_id`。geometry type/column、schema contract、CRS、extent 和 fingerprint
   均不可变。
2. `StyleDefinitionVersion` 归属精确 layer version。style format、document 和 fingerprint 不可变；不允许通过共享
   可变 style 改变已发布 release。
3. `TileMatrixSetDefinitionVersion` 归属精确 service definition，可进一步收窄到一个 layer version；CRS、tile
   size、zoom range、逐级 scale denominator、extent 和 fingerprint 不可变。vector-tile release 必须引用 TMS。
4. `ServiceReleaseBinding` 是 service definition、layer、style 和 optional TMS 的唯一原子组合。数据库 recorder
   校验它们属于同一 service/layer version chain，拒绝跨 layer style 或 layer-scoped TMS 混搭。
5. `ServiceDeploymentRevision` 新增 `service_release_binding_id`。migration 154 为 migration 153 的历史记录保留
   nullable 兼容，但新 deployment recorder 和 insert trigger 强制非空；Gateway 对旧 recorder 撤销执行权。
6. 新 endpoint 创建和 active endpoint CAS 都增加 release-completeness trigger。因而 endpoint 只能来自绑定完整
   release 的 ready deployment，调用方不能分别切换 layer/style/TMS pointer。
7. 四张新 authority 表 append-only、强制 tenant RLS。Gateway 只有 `SELECT` 与五个新增
   `SECURITY DEFINER` recorder 的执行权，没有表级写权限。

## Consequences

- active projection 可一次返回 service definition、release、layer、style、TMS、deployment 和 endpoint，客户端
  不再自行拼接发布版本。
- 已发布 style/TMS 更新必须创建新 version、release、deployment 和 endpoint，再经现有 CAS 激活；旧 release 可
  用于确定性回切。
- 历史 migration 153 deployment 仍可读取，但不能创建新 endpoint 或再次激活；只有完整 release 可进入新发布路径。
- 当前一个 release 只承载一个代表 layer/style 组合。多 layer service 的 release manifest、CachePolicy、
  ServicePolicy、ConsumerBinding、ServiceSLO 和多 region endpoint set 仍需后续切片。

## Verification

- 聚焦回归：`179 passed, 2 skipped`；跳过项为未配置 `DATABASE_URL` 的 PostgreSQL 测试入口。
- PostgreSQL 16 集成入口单独运行：`1 passed`。
- disposable certification：`.tmp/gis-service-control-plane-certification/report.json`，schema
  `gda.gis_service_control_plane.certification.v2`，报告 SHA-256
  `87b069715ec2be651c647d6f314b6bdc3eca11cfd1ccf5bc5aaa8d77ea98fa58`。
- 认证覆盖四类 authority 幂等、跨 layer/style 混搭拒绝、无 release deployment 拒绝、旧 recorder 撤权、
  endpoint/release 直写 `42501`、十张表 RLS、active release 三次 CAS 切换/回切和跨租户零行。
- migration catalog 为 154 条，最后迁移为 `154_gis_service_release_binding`，fingerprint 为
  `5c313a739edc0346194df3709d4bc7c40199eb36d485b4294d6dfb5d94cb2d80`。

## Revisit Triggers

- 一个 service release 需要原子包含多个 layer/style/TMS entry；
- CachePolicy、ServicePolicy、ConsumerBinding 或 ServiceSLO 需要进入同一个 release manifest；
- 真实 provider conformance 证明现有 style/TMS contract 不足；
- 发布吞吐或跨 region active-active 要求证明 PostgreSQL recorder/CAS 边界不足。
