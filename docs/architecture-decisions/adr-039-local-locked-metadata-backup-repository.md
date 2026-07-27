# ADR-039: Local Locked Metadata Backup Repository

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-038](adr-038-local-metadata-fabric-recovery-rehearsal.md) · [ADR-040](adr-040-local-cross-cluster-metadata-recovery.md)

**Evidence**: [metadata-fabric-backup-repository-2026-07-27.json](../evidence/metadata-fabric-backup-repository-2026-07-27.json)

## Context

ADR-038 证明三份本地临时 backup artifact 可以恢复，但不能证明 artifact 离开 runner 主机后仍可按版本、校验和与保留策略取回。直接复用 `gis-agent` MinIO 会与应用共享 namespace、管理员身份、PVC 和故障域，也不能形成 metadata recovery 的独立边界。

当前没有获准使用的生产 backup account/bucket、KMS key、workload identity 或第二 Kubernetes cluster，因此本 ADR 必须同时固定生产合同并限制本地声明，不能把本地 MinIO 写成生产 durable backup。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 复用 `gis-agent` MinIO | 最少资源 | 共享故障域、凭据与生命周期；应用管理员可破坏备份 | 拒绝 |
| 直接声明云 S3 生产方案 | 目标形态正确 | 当前没有真实 bucket/KMS/IAM/cross-cluster evidence | 只冻结合同，不声明验证 |
| 独立本地 S3-compatible repository + 生产策略合同 | 可真实验证 versioning、Object Lock、artifact round-trip，同时保持边界 | 仍与 source 同集群，namespace/PVC 删除可绕过存储保留 | 采用 |

## Decision

### 1. 独立本地 repository profile

`gda-metadata-backup-repository` 使用独立 namespace、ServiceAccount、ClusterIP Service 和 8 Gi PVC 运行固定版本 MinIO。Secret 不进入 Git；root credential 由 runner 在私有临时文件中生成并通过临时 Secret 注入，ServiceAccount 与 workload 均禁止 Kubernetes token automount。

MinIO 使用 non-root、read-only root filesystem、独立 data/config/tmp volume。namespace 默认拒绝 ingress/egress，只为带 `gda.openai.com/backup-client=true` 标签的同 namespace client 声明 9000/TCP allow rule。当前 Docker Desktop kindnet 不执行 NetworkPolicy，因此 `network_policy_enforcement_verified=false`。

### 2. 三 artifact repository round-trip

ADR-038 runner 增加可选 artifact callback，不改变默认恢复路径。M2b-2 callback 对 OpenMetadata PostgreSQL dump、Gravitino PostgreSQL dump 和 OpenSearch snapshot 依次执行：

1. 上传到 `gda-metadata-fabric-backups` 的 recovery-point prefix；
2. 记录 SHA-256、bytes、S3 version ID、retention mode 和 retain-until；
3. bucket versioning 固定为 `Enabled`，Object Lock 固定为 `Enabled`，本地默认 retention 为 `GOVERNANCE/1 day`；
4. 对每个显式 version 发起无 bypass 删除，必须被拒绝；
5. 删除 runner 上的全部 artifact，确认路径不存在；
6. 按 version ID 下载并重新验证 SHA-256/bytes；
7. 只使用下载后的 artifact 完成 ADR-038 三存储恢复和内容 fingerprint 对比。

成功或失败都必须停止 port-forward、恢复源 provider、删除 recovery/repository namespace 与 PVC、删除临时凭据。删除本地 repository namespace 会物理移除受锁 PVC，因此只证明 S3 API 行为，不证明独立 durability。

### 3. 生产策略合同

`config/metadata-fabric-backup-policy.production.yaml` 固定生产准入目标：

- repository 位于 source cluster 之外的独立 backup account/project；
- S3 bucket versioning=`Enabled`；
- Object Lock=`COMPLIANCE`，暂定最小 30 天安全下限，最终 retention 仍须由 owner/SLO/compliance 冻结；
- TLS 1.2+、SSE-KMS、SHA-256 与独立 read-after-write；
- writer 使用 workload identity 且不能删除 retained backup；recovery reader 不能写入；
- public access blocked，endpoint/region/KMS 只存引用，不存 Secret。

该文件是 fail-closed 配置合同，不是生产验证结果。

## Verification

2026-07-27 的真实本地演练结果：

- 总耗时 `137.914` 秒，repository-backed recovery 子流程 `111.123` 秒；二者都不是 RTO SLO；
- 独立 repository PVC 为 8 Gi，UID `22204802-c426-4840-8045-ad03a53c88e4`；
- bucket versioning 与 Object Lock 均启用；三个对象均获得唯一 version ID、`GOVERNANCE` retention 和次日 retain-until；
- 三个 retained version 的无 bypass 删除全部被拒绝；
- 本地 artifact 全部删除后重新下载，恢复 OpenMetadata 176 张表、Gravitino 39 张表和 OpenSearch 79 个索引；
- source 五个 Pod 恢复 Ready，repository/recovery namespace、临时 PVC、credential 与 port-forward 全部清理；
- repository evidence fingerprint 为 `2897f9e6aaae21fb366da0b72edea5cf072d5b2c1aeac0807d263bd0a5f5f133`；
- recovery evidence fingerprint 为 `da1214294045f8b0abe2e2775b81ef33967eac9ab0e97055ae80212ac0c08a4b`。

## Claim Boundary

允许声明：

- `backup_repository_verified=true`，scope 仅为 `local_same_cluster_isolated_s3_compatible_repository`；
- `local_repository_round_trip_verified=true`；
- `repository_backed_restore_verified=true`。

仍固定为 `false`：

- `production_backup_target_verified`、`production_retention_verified`；
- `production_kms_verified`、`production_tls_verified`；
- `cross_cluster_recovery_verified`、`cross_region_recovery_verified`；
- `rpo_slo_verified`、`rto_slo_verified`；
- `oidc_verified`、`network_policy_enforcement_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Consequences

**Positive**：恢复链第一次证明真实三存储 artifact 离开本地临时目录、获得版本与保留锁、再按 version ID 下载后仍可恢复；生产策略也有了可执行的 fail-closed 最小合同。

**Negative**：本地 MinIO 与 source 仍在同一 kind cluster；root 管理员和 namespace/PVC 删除仍能绕过 API retention；没有 TLS、KMS、workload identity、跨 account 或第二 cluster。

**Next gate**：[ADR-040](adr-040-local-cross-cluster-metadata-recovery.md) 已将本地 repository 移出两个 Kubernetes cluster，并验证本机双集群恢复、`COMPLIANCE/1 day` 与独立 MinIO writer/reader。下一步仍须在 source host/cluster 外的独立 account/project 建立真实 S3-compatible bucket、KMS、TLS 与 workload identity，验证 source loss 后恢复并冻结 RPO/RTO。若云/provider 不支持等价 Object Lock、KMS、identity 或独立故障域，必须阻断该 DeploymentProfile，不能降级为普通 versioned bucket。
