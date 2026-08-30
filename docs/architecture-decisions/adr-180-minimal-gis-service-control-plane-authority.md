# ADR-180：最小 GIS Service Control Plane 复用统一产品、运行与证据权威

**Status**: Accepted  
**Date**: 2026-08-07  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.2

## Context

AR-4.1 已形成正式产品消费者与迁移通知 authority，但 GIS 服务仍缺少不可变服务定义、部署 revision、
provider terminal evidence 和唯一 active endpoint pointer。若直接把 pygeoapi、GeoServer、Martin、ArcGIS
或云 GIS 配置当成发布真值，会形成平行 catalog，并使产品版本、部署 Run、endpoint 和回滚无法一致审计。

本切片只建立可验证的最小控制面闭环。它必须复用现有 `Resource`、`PlatformDefinitionVersion`、
`DataProductVersion`、`PlatformRun`、`FrameworkAttemptObservation` 和 PostgreSQL control ledger，不提前引入
Kafka、第二套产品注册表、完整微服务体系或自研 GIS server。

## Options Considered

| Option | 优点 | 代价与风险 | Decision |
|---|---|---|---|
| provider 配置即服务真值 | 实现快 | 无统一版本、产品绑定、CAS、审计或可移植性 | Rejected |
| 新建独立 GIS service catalog 与 deployment DB | 边界表面清晰 | 平行 Resource/Product/Run authority，双写和恢复复杂 | Rejected |
| 事件总线 + 多个控制面微服务 | 扩展性强 | 当前规模没有证明该复杂度，事务一致性成本高 | Deferred |
| PostgreSQL 模块化 authority，复用统一 ledger | 单事务、RLS、约束和审计可直接认证 | 当前吞吐和 provider adapter 能力有限 | Accepted |

## Decision

1. `GISServiceDefinitionVersion` 是既有 `gis_service` Resource 和 `PlatformDefinitionVersion` 的 GIS 扩展，
   不复制 title、owner、governance 或产品 metadata。定义只能绑定当前 active、质量已通过且有
   `published|advanced|promoted|rolled_back` 生命周期事件的精确 `DataProductVersion` 和 manifest SHA-256。
2. `ServiceDeploymentRevision` 绑定一个正式 `PlatformRun`。Run 的 definition 必须等于服务定义引用的
   `PlatformDefinitionVersion`，且 Run input 必须包含产品版本的 output `ResourceVersion`。
3. 部署状态机固定为 `planned -> deploying -> ready|failed`。每次转换使用 state-version CAS 并追加不可变
   event；`ready` 只接受 succeeded Run 和同一 Run 的 success/ready provider observation，observation evidence
   必须精确绑定 deployment、provider deployment ID 和 provider revision ref。
4. `EndpointRevision` 只能引用 ready deployment，协议必须与 feature/map/vector-tile/coverage 类型兼容；
   endpoint URI 必须是无 credential、query 和 fragment 的稳定 HTTPS URI。
5. 每个 GIS service 只有一个 active endpoint pointer。切换使用 endpoint state-version CAS，并追加不可变
   activation event；回滚通过重新激活先前不可变 endpoint revision 完成，不改写 provider 或 endpoint 历史。
6. migration 153 对六张 authority/event 表强制 tenant RLS。Gateway 只有 `SELECT` 和五个
   `SECURITY DEFINER` recorder/transition function 的执行权，没有表级 `INSERT`/`UPDATE`；定义、endpoint 和
   event append-only，deployment 只有受控状态字段可变。

## Trade-offs

- 当前只覆盖 ServiceDefinition、DeploymentRevision 和 EndpointRevision。Layer、Style、TMS、Cache、Policy、
  service-scoped ConsumerBinding、ServiceSLO、suspend/retire 和事故自动回滚仍待后续切片。
- provider observation 复用通用 `FrameworkAttemptObservation`，没有引入 GIS provider 专用运行数据库；后续
  adapter 需要统一 observation evidence schema 和 conformance suite。
- 本切片认证控制面状态与证据，不证明真实 pygeoapi/GeoServer/Martin/ArcGIS 部署、数据面 Gateway、协议正确性、
  性能、安全负向测试或生产 HA/RPO/RTO。

## Consequences

- GIS 服务发布不再能绕过 active/approved 产品版本、统一 PlatformRun 和 provider observation。
- active endpoint 切换与回切具备数据库级 CAS、不可变历史和租户隔离，不依赖 provider 配置作为唯一真值。
- 架构保持模块化 PostgreSQL transaction script；只有真实吞吐、隔离或跨组织需求证明不足时，才重新评估
  事件总线和服务拆分。

## Verification

- 聚焦回归：`177 passed, 2 skipped`；两个跳过项均为未配置 `DATABASE_URL` 的 PostgreSQL 测试入口。
- PostgreSQL 16 disposable certification：
  `.tmp/gis-service-control-plane-certification/report.json`。
- 报告 SHA-256：`e4212667acf835aaacf51ac3b41ae152e922a237e608d1487f491bbd7b5941d4`。
- 认证覆盖 definition/deployment 幂等、inactive ProductVersion 拒绝、ready 前 endpoint 拒绝、
  evidence-gated Run success、`planned -> deploying -> ready`、provider evidence、三次 active pointer CAS 切换/回切、陈旧 CAS 拒绝、
  gateway role 直写 `42501`、不可变 endpoint `55000` 和跨租户零行。
- migration catalog 为 153 条，最后迁移为 `153_gis_service_control_plane`，catalog fingerprint 为
  `9f17eceddedd61b245357a78bdb595fbbff1d4737dd2a56c7a84fb2a6223a3e0`。

## Revisit Triggers

- Layer/Style/TMS/Cache/Policy authority 需要与 service pointer 形成多对象原子 release；
- 一个服务需要多 region/cluster active-active endpoint set，而不再是单 active revision；
- provider 数量或发布吞吐证明 PostgreSQL recorder/observation 查询成为瓶颈；
- 真实 provider conformance、Gateway 数据面、ServiceSLO/Incident 或 HA 恢复要求改变当前边界。
