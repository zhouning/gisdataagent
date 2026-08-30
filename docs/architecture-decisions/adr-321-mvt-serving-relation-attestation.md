# ADR-321: MVT Serving Relation Attestation

**状态**: Accepted for AR-0 serving-promotion hardening
**日期**: 2026-08-26
**相关路线**: [GIS Data Agent Roadmap](../roadmap.md), AR-0, AR-4

## 背景

`MVTServingProjectionVersion` 固定了 source schema/table、geometry 列、SRID、feature ID 和属性白名单，但这些字段原先只是控制面声明。表被删除、重建或改列后，旧 projection 和 release 仍可能看起来完整，导致 endpoint activation 把“控制面身份正确”误当成“实际 serving relation 仍然正确”。

## 决策

新增 `gda_control.mvt_serving_relation_attestation` 作为 serving projection 的不可变物理观察记录。登记函数不接受调用方提交的列元数据，而是由 `SECURITY DEFINER` 函数读取当前 PostgreSQL/PostGIS catalog：

- `pg_class` 的 relation OID 和 relation kind；
- `geometry_columns` 的 geometry column、geometry type、SRID 和维度；
- `pg_attribute` 的 feature ID 数据类型与属性白名单列；
- `pg_attribute` 的属性列 `format_type` 顺序列表；
- 规范化观察文档的 SHA-256。

JQDLTB exact serving binding 在 endpoint promotion 时执行两次门禁：先检查 235 的产品/服务链路 binding，再由 237 的 assertion 读取当前 relation 并与不可变 attestation 比对。关系被重建或列/几何元数据漂移时，activation 以 SQLSTATE `23514` fail closed；必须创建新的 serving projection version，不能覆盖旧 attestation。

通用 GIS 服务仍沿用原有 release/cache/policy/readiness gates；relation attestation 只对 `gda.jqdltb_mapping_binding.v1` 产品的 JQDLTB promotion 生效。provider runtime 只负责暴露已经通过控制面的 projection，不拥有 attestation 或 active pointer。

## 证据

- migration `237_mvt_serving_relation_attestation.sql`：attestation 表、catalog observer、不可变 recorder、漂移 assertion、RLS 和最小权限。
- `PlatformGateway.record_mvt_serving_relation_attestation`：唯一应用写入口。
- `scripts/certify_jqdltb_serving_release_binding.py`：disposable PostGIS 认证覆盖：
  - exact serving binding 已登记但 relation attestation 缺失时 activation 返回 `23514`；
  - 真实 `serving.districts_v1` 的 Polygon/4326、feature ID 和属性列观察登记成功，随后 activation state version 为 `1`；
  - 登记后将属性列重命名，再次 activation 返回 `23514`；
  - attestation replay 幂等，RLS 强制，直接 update/delete 仍返回 `42501`。

这份报告的证据等级是 `synthetic_disposable`，不代表真实重庆 JQDLTB serving artifact、业务批准或生产 endpoint 已完成。

## 后续

真实 JQDLTB 发布时，serving controller 必须在 provider deployment ready、关系已由 PostGIS 真实 catalog 观察后登记 attestation；关系重建或 schema migration 后必须生成新的 projection version 并重新走 release binding、SLO 和 endpoint promotion。
