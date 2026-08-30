# ADR-294: Tenant-Scoped Object Recovery Contract

状态：已采纳，合同、测试和 disposable MinIO 认证已实现；不是生产灾备退出门  
日期：2026-08-25

## 背景

ADR-293 只证明了 PostgreSQL 控制账本恢复后的租户边界。对象存储中的 Raw、STAC、GeoJSON、
二进制和其他派生文件仍没有一份可以对照源与恢复目标的租户级字节清单。只比较对象数量、
ETag 或总 bucket 行为，无法识别漏对象、误写其他租户前缀、VersionId 变化或恢复后字节漂移。

## 决策

新增 `data_agent.platform_runtime.object_recovery` 合同：

- 每个租户登记一个相互不重叠的 canonical key prefix；
- 每个对象登记 tenant、prefix、key、size、ETag、VersionId 和完整 SHA-256；
- manifest 对租户前缀和对象身份排序后计算 `gda.tenant_object_recovery_manifest.v1` 指纹；
- source/restored 默认要求 manifest 完全相等，包括 provider VersionId；
- 跨 bucket 或 provider 复制如果重新发放 VersionId，必须显式启用 `allow_version_id_remap`，且
  key、prefix、size、ETag 和完整字节 SHA-256 仍需完全一致；
- `TenantObjectScope` 在调用 S3 client 前校验 read/write/delete/head/list 的 key，越权请求
  fail closed；provider listing 出现前缀外对象也拒绝。

## 取舍

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 只比较数量/ETag | 成本低 | 无法证明字节一致或租户边界 |
| 直接要求 VersionId 一致 | 绑定强 | 新 bucket/新 provider 复制通常会重新发号 |
| 默认严格 + 显式 VersionId remap | 保留强默认，同时覆盖新目标恢复 | 复制流程必须明确声明 remap，不能隐式放宽 |

选择最后一项。manifest 不把对象内容放进控制账本或报告，只保存可复核摘要；完整字节在认证
过程中回读并哈希。它是恢复准入证据，不是对象复制编排器，也不替代 provider 自身的 IAM、
Object Lock、复制和保留策略。

## 已验证范围

`data_agent/test_object_recovery.py` 的 15 项对象合同测试与控制账本恢复测试一起通过。固定镜像
`minio/minio:RELEASE.2025-04-22T22-12-26Z` + `minio/mc:RELEASE.2025-04-16T18-13-26Z` 的
一次性认证 `scripts/certify_tenant_object_recovery.py` 通过：

- 两个租户分别使用 `tenants/tenant-a/`、`tenants/tenant-b/`，源/恢复 bucket 各 4 个对象；
- 源/恢复对象数、完整字节 SHA-256、ETag 全部一致；恢复 bucket VersionId 重新生成，并通过
  显式 VersionId remap admission；
- 每个租户的跨租户 read/write/delete 均返回 `AccessDenied`，越权对象不存在；
- source/restored bucket versioning 已开启；容器、volume、network、bucket、临时用户和 policy
  均在 finally 中清理。

报告：`.tmp/tenant-object-recovery/acceptance-report.json`   
报告 canonical `report_sha256`：`88108c1391040f9fea18906b563782a330c419129b0f61014160391b102e2cbc`  
文件 SHA-256：`b672f639bd32fee8237c9f54cbf8f49e1e69b2e97f806c979f936af657fc4ccc`

## 边界与后续

本 ADR 不证明生产对象存储复制、Object Lock、HA、PITR、RPO/RTO、multipart ETag 的跨 provider
语义，也不证明控制账本和对象存储的跨 store 原子提交。下一步需要在批准的 DeploymentProfile
上补充生产 provider、故障注入、恢复窗口与控制账本/对象 manifest 的联合提交协调。

