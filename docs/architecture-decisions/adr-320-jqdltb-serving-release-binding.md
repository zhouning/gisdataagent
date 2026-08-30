# ADR-320: JQDLTB DataProductVersion 到 GIS Serving 的绑定

**状态**: Accepted for AR-0 implementation
**日期**: 2026-08-26

## 决策

JQDLTB 的产品发布和 GIS serving 发布分为两个连续阶段：

1. `JqdltbDataProductReleasePlan` 负责把同一 Run 的 transformation、质量、血缘、六层分布和业务审批写成当前 `DataProductVersion`。
2. 该版本成为产品 current 后，`JqdltbServingReleaseBinding` 通过既有 GIS Service Control Plane 绑定：
   - `GISServiceDefinitionVersion` 的 product/version/manifest；
   - ADS `output_resource_version_id` 对应的 `LayerDefinitionVersion`；
   - `MVTServingProjectionVersion` 的 PostGIS schema/table、geometry、属性白名单和 source content SHA；
   - `ServiceReleaseBinding`；
   - 已激活且属于同一 service 的 `GISServiceSLOBinding`。

绑定 fingerprint 写入独立的 append-only `gda_control.jqdltb_serving_release_binding`，由 migration 235 的 SECURITY DEFINER recorder 和 Gateway 入口写入。重复提交必须返回同一内容；任何 product/version、manifest、ADS output、租户、layer、projection、service release 或 SLO 漂移 fail closed。

Migration 236 将这份 authority 接入 endpoint promotion：当 `DataProductVersion.mapping_contract.schema` 为
`gda.jqdltb_mapping_binding.v1` 时，`gis_service.active_endpoint_revision_id` 的更新必须找到同一
product/version、manifest、service definition、layer、MVT projection 和 service release 的 exact serving
binding；缺少绑定或任一身份不一致直接以 SQLSTATE `23514` 拒绝。非 JQDLTB mapping contract 的通用 GIS
服务继续走原有 release/cache/policy/readiness/SLO gates。

## 时序边界

不能把 serving binding 写进首次 `DataProductVersion` 事务：GIS service definition recorder 本身要求 source DataProductVersion 已经是 current，前置绑定会与产品发布形成环依赖。因此 serving binding 是 product release 成功后的 serving promotion 输入；服务 endpoint activation 继续由既有 release/cache/policy/readiness/SLO authority 控制。

## 已实现与未声称

  - 已实现 typed binding、跨合同 fingerprint、Gateway recorder/read API、migration 235/236、RLS 和不可变触发器；MVT 物理 relation 的 catalog 观察与 promotion 漂移复核见 [ADR-321](adr-321-mvt-serving-relation-attestation.md)。
- 已通过 122 项聚焦 Python/Gateway 回归，以及包含完整 synthetic PlatformRun、GIS deployment
  terminal settlement、SLO authority 和 endpoint promotion gate 的 disposable PostgreSQL 认证。
  认证覆盖：无 serving binding 的 endpoint activation 返回 `23514`；登记 exact binding 后 activation
  成功并进入 state version `1`；首次写入、幂等重放、manifest/ADS output/SLO 漂移拒绝、跨租户零行、
  RLS 强制和直接 update/delete 拒绝。报告标记为 `synthetic_disposable`，不构成业务发布证据。
- 可重复认证入口：`scripts/certify_jqdltb_serving_release_binding.py`；该脚本创建临时数据库、
  加载所需 migration、运行 Gateway/SQL 负向场景，结束后删除临时数据库和登录角色。
- 尚无真实重庆 JQDLTB `DataProductVersion`、PostGIS serving artifact、GIS service definition、SLO activation 或生产 endpoint；synthetic contract 认证不构成业务发布证据。
