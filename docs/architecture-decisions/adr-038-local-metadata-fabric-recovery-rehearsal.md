# ADR-038: Local Metadata Fabric Recovery Rehearsal

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md)

**Evidence**: [metadata-fabric-recovery-rehearsal-2026-07-27.json](../evidence/metadata-fabric-recovery-rehearsal-2026-07-27.json)

## Context

ADR-037 证明 Pod 替换后原 PVC 可以重新挂载，不能证明独立备份可被恢复。M2b 在升级/回滚前必须先建立可执行的恢复演练：备份必须离开源数据卷，恢复必须进入新的 namespace 和 PVC，内容必须与 quiesced source 一致，任何失败都必须恢复源服务并清理临时资源。

本 ADR 只回答本地同集群逻辑备份与隔离恢复。它不回答生产备份保留、对象存储 durability、PITR、RPO/RTO、节点或集群丢失、跨区域 DR。

## Decision

### 1. 三存储备份合同

`data_agent.metadata_fabric_recovery_rehearsal` 在固定 `docker-desktop` context 中执行：

1. 验证 M2a 静态合同、源 namespace identity 和恢复 namespace 不存在；
2. 将 OpenMetadata 与 Gravitino 各自从 1 副本缩容到 0，保持两个 PostgreSQL 和 OpenSearch 在线，形成有界 quiesced window；
3. 对 OpenMetadata PostgreSQL 和 Gravitino PostgreSQL 分别执行 PostgreSQL custom-format logical dump；
4. 对 OpenSearch 79 个显式索引执行 native filesystem snapshot；`path.repo` 只授权 `/var/lib/gda-snapshots`，实际 repository 固定为其 `repository/` 子目录；
5. 三个本地临时 artifact 均为 `0600`，记录 SHA-256 和字节数后在终局删除，不进入 Git。

OpenSearch snapshot tar 在导入前必须通过结构化校验：非空、根目录只能是 `repository/`、禁止绝对路径、`..`、symlink、hardlink 和 device。Secret 值不进入参数、日志、artifact metadata 或 evidence。

### 2. 隔离恢复目标

恢复目标固定为临时 namespace `gda-metadata-recovery-rehearsal`：

- Pod Security `restricted`，默认拒绝 ingress/egress，不创建 Service、Ingress、Route、Gateway 或 Kubernetes RBAC；
- 三个专用 ServiceAccount 均禁止 token automount；
- 两个 PostgreSQL `16.10-bookworm` 恢复到各自 2 Gi 新 PVC；OpenSearch `3.3.2` 恢复到 8 Gi 新 PVC；
- 恢复 credential 在运行期外部生成，以临时文件创建 Secret，Secret object/value 不进入仓库或 evidence；
- OpenSearch 保持 read-only root filesystem；initContainer 从相同固定镜像复制 config 到受控 `emptyDir`，logs、config 和 snapshot staging 各自使用有界可写 volume；
- 恢复 OpenSearch 先枚举并按显式名称清空启动期索引，再恢复 snapshot；禁止 `_all` 或通配删除。

### 3. 内容与终局验证

PostgreSQL source/recovered 必须完全匹配：

- server/image version；
- user table 数量与名称 fingerprint；
- 每张表 row count fingerprint；
- sequence state fingerprint；
- extension name/version fingerprint。

OpenSearch source/recovered 必须完全匹配 version、索引总数/名称和 document count fingerprint，且恢复 cluster UUID 必须不同。恢复目标三块 PVC 必须 Bound 且具有新 UID/volume identity。

无论成功或失败，runner 都必须恢复两个源 provider 的原副本数并等待 Ready，注销 source snapshot repository，清空 snapshot staging，删除恢复 namespace/PVC 和本地 artifact。任一终局未完成，evidence 为 `blocked/error`。

### 4. 声明边界

本地三存储演练通过后允许：

- `backup_restore_verified=true`，但 scope 固定为 `local_same_cluster_new_namespace_and_pvcs`；
- `local_backup_restore_verified=true`。

以下仍固定为 `false`：

- `production_backup_restore_verified`；
- `rpo_slo_verified`、`rto_slo_verified`；
- `cross_cluster_recovery_verified`、`cross_region_recovery_verified`；
- `oidc_verified`、`network_policy_enforcement_verified`、`upgrade_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Verification

2026-07-27 的本地实采结果：

- 演练耗时 `113.926` 秒；该观测值不是 RTO SLO；
- OpenMetadata PostgreSQL backup `1,179,744` bytes，恢复 176 张表；
- Gravitino PostgreSQL backup `188,109` bytes，恢复 39 张表；
- OpenSearch snapshot archive `400,544` bytes，恢复 79 个索引；
- 两个 PostgreSQL 的 table/row/sequence/extension fingerprints 全部一致；
- OpenSearch index/document fingerprints 一致，source/recovery cluster UUID 不同；
- 恢复 PVC 为 2 Gi、2 Gi、8 Gi，均为新的 Bound identity；
- source provider 恢复 Ready，恢复 namespace、本地 artifact 与 source snapshot staging 全部清理；
- evidence fingerprint 为 `ebb0db3646010d427601c5d06760f984c742a7a4b6fa143fd2d6c7833246ab30`。

Evidence 不包含 Secret，且由 required CI 的静态 validator、单元负例和 evidence integrity test 约束。

## Consequences

**Positive**：M2b 第一次拥有覆盖 OpenMetadata PostgreSQL、Gravitino PostgreSQL 和 OpenSearch 的真实逻辑备份、隔离恢复、内容一致性和 cleanup 闭环；升级演练不再建立在“原 PVC 还能挂载”的假设上。

**Negative**：演练会短暂停止两个 provider；artifact 只在本机临时目录存在，没有验证远端 immutable backup store、加密/KMS、retention、PITR、跨集群调度和 RPO/RTO。

**Next gate**：M2b 继续完成生产型 backup target/retention 与跨集群恢复、OIDC/workload identity、NetworkPolicy enforcement、upgrade/rollback、metrics/OTel、registry provenance 和 owner/runbook；之后才进入 M3 受控 ingestion/replay、OpenLineage、无双写和 Gravitino Spark/Sedona/Flink conformance。
