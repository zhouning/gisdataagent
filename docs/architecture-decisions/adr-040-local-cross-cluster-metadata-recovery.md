# ADR-040: Local Cross-Cluster Metadata Recovery

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-038](adr-038-local-metadata-fabric-recovery-rehearsal.md) · [ADR-039](adr-039-local-locked-metadata-backup-repository.md)

**Evidence**: [metadata-fabric-cross-cluster-recovery-2026-07-27.json](../evidence/metadata-fabric-cross-cluster-recovery-2026-07-27.json)

## Context

ADR-039 证明三份 metadata backup artifact 可以离开 runner 临时目录，在同一 Kubernetes 集群内的独立 MinIO/PVC 中获得 version 与 Object Lock 后重新下载和恢复，但 source 与 repository 仍共享 cluster lifecycle。下一步需要验证 recovery workload 能否在具有独立 API、namespace、node runtime 与 cluster UID 的第二个 Kubernetes cluster 中，从 Kubernetes 之外的 repository 恢复。

本地只有一台 Docker Desktop 主机，没有获准使用的云 backup account、KMS key、OIDC/workload identity 或异地主机。因此本决策只能证明同一 Docker host 内的双集群恢复，不能证明 source-host loss、生产 durability、跨区域 DR 或 RPO/RTO。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 继续在 source cluster 新建 namespace | 最少资源，复用 ADR-038 | 不是独立 cluster failure domain | 拒绝作为 M2b-3 证据 |
| 在 source cluster 内运行 vcluster | API 表面独立，启动快 | 仍共享 source cluster node、CNI、storage 与 lifecycle | 拒绝作为故障域证明 |
| Docker Desktop kubeadm 单节点 cluster | 与桌面产品集成 | 只能保留一个 Docker Desktop cluster，无法同时作为 source 与 recovery | 不采用 |
| 保留 Docker Desktop source，另建固定版本 kind cluster | 两个 context 和 cluster UID 可同时验证；可销毁重建 recovery cluster | 仍共享 Docker daemon、主机、电源和网络 | 采用，声明严格限定在本机 |

## Decision

### 1. 双集群边界

source 固定为 `docker-desktop`，recovery 固定为 `kind-gda-metadata-recovery`，kind node image 固定为 `kindest/node:v1.35.5`。每个 `kubectl` 调用都显式绑定 context，不依赖全局 current-context。runner 在开始前读取两个 `kube-system` namespace UID；context 是否相同必须与 cluster UID 是否相同一致，且 M2b-3 要求二者都不同。

source provider 只在有界备份窗口内 quiesce。三份 artifact 恢复到第二集群的 `gda-metadata-recovery-rehearsal` namespace 和新 PVC，source namespace/PVC 不迁移，source cluster 也不被删除。因此 `source_cluster_loss_verified=false`。

### 2. Kubernetes 外 repository

固定版本 MinIO 作为 Docker-host container 运行，data 使用独立临时 Docker volume，不属于 source 或 recovery Kubernetes cluster。bucket 固定启用 versioning 和 `COMPLIANCE/1 day` Object Lock。

runner 动态创建三种本地 S3 identity：管理员只用于初始化和验证 COMPLIANCE 删除阻断；writer 可写入和读取但没有删除权限；reader 只读且写入 probe 必须被拒绝。三份 artifact 必须获得唯一 version ID、未来 retain-until、匹配的 SHA-256/bytes；writer 删除和管理员删除 retained version 都必须失败。本地 artifact 删除后只能按 version ID 由 reader 下载，再进入第二集群恢复。

这些是本地 MinIO 用户，不是云 workload identity；repository 使用 loopback HTTP，没有 TLS 或 KMS，因此相应生产声明保持 `false`。

### 3. 恢复与 cleanup

复用 ADR-038 的 PostgreSQL custom dump、OpenSearch native snapshot、内容 marker 和新 PVC 验证，但 source 与 recovery 使用独立 command runner。恢复后必须同时满足：

1. OpenMetadata PostgreSQL、Gravitino PostgreSQL 和 OpenSearch 内容 marker 与 source 一致；
2. source provider 全部恢复 Ready；
3. recovery namespace/PVC 删除；
4. Docker-host MinIO container、volume 和运行期凭据删除；
5. recovery cluster UID 保持可访问且未被 rehearsal 清理。

`platform_truth.RUNTIME_INVENTORY` 将该 runtime 登记为 `local_verification_only`。它不是 scheduler、生产 backup controller 或运行状态权威；唯一持久结果是 committed、可校验且绑定当前合同指纹的 evidence。

## Verification

2026-07-27 的真实本地演练结果：

- 总耗时 `122.791` 秒；该观测值不是 RTO SLO；
- source cluster UID `c3c9b...445ab`，recovery cluster UID `04ddf...94858`；
- OpenMetadata PostgreSQL artifact `1,269,181` bytes，恢复 176 张表；
- Gravitino PostgreSQL artifact `188,109` bytes，恢复 39 张表；
- OpenSearch artifact `393,375` bytes，恢复 79 个索引；
- bucket versioning=`Enabled`、Object Lock=`Enabled`、retention=`COMPLIANCE/1 day`；writer delete、reader write 和管理员删除 retained version 均被拒绝；
- source 五个 Pod 恢复 Ready；recovery namespace、Docker container/volume 和运行期凭据全部清理；recovery cluster 保持 Ready；
- contract fingerprint `352f59b10d845b288a465b59386e7a15f42aa706559fe337db5ed1dcb7234815`；
- evidence fingerprint `9eaf8cec9ec2d3763260c271c0c27c1c3251717820d38aadfef0bec7d7a574a8`。

required CI 同时校验 evidence 自身完整性、嵌套 recovery evidence 与当前合同指纹绑定。

## Claim Boundary

允许声明：

- `local_cross_cluster_recovery_verified=true`；
- scope 仅为 `local_same_host_distinct_kubernetes_clusters_external_s3_repository`；
- `local_external_repository_verified=true`；
- `local_writer_reader_identity_separation_verified=true`。

仍固定为 `false`：

- `cross_cluster_recovery_verified` 与 `production_cross_cluster_recovery_verified`；
- `production_backup_target_verified`、`production_retention_verified`；
- `production_kms_verified`、`production_tls_verified`；
- `source_cluster_loss_verified`、`cross_region_recovery_verified`；
- `rpo_slo_verified`、`rto_slo_verified`；
- `oidc_verified`、`network_policy_enforcement_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Consequences

**Positive**：恢复链第一次跨越两个独立 Kubernetes API/cluster UID；repository 也移出两个 Kubernetes lifecycle，并以 COMPLIANCE retention 和独立 writer/reader 权限完成真实恢复。

**Negative**：两个 cluster 和 repository 仍共享一台 Docker Desktop 主机与 Docker daemon；删除 Docker volume、主机故障或管理员越权仍可物理破坏数据。静态 MinIO identity、loopback HTTP、一天 retention 和手工准备 kind cluster 都不能进入生产 profile。

**Next gate**：在 source host/cluster 之外的独立 account/project 建立生产 bucket、KMS、TLS 与 workload identity，执行 source cluster/host unavailable 条件下的恢复并冻结 RPO/RTO；随后完成 OIDC、NetworkPolicy enforcement、upgrade/rollback、registry provenance、metrics/OTel 和 owner/runbook。任何 provider 不满足 COMPLIANCE Object Lock、KMS、identity 或独立故障域时必须阻断该 DeploymentProfile。
