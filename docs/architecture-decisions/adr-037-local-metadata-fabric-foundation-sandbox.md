# ADR-037：本地 Metadata Fabric Foundation Sandbox 与 Live Evidence 边界

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Platform Architecture, Metadata Platform, Data Governance, SRE, Security

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-036](adr-036-read-only-metadata-fabric-bridge-contract.md)

**Evidence**: [metadata-fabric-foundation-sandbox-2026-07-27.json](../evidence/metadata-fabric-foundation-sandbox-2026-07-27.json)

## Context

ADR-036 只证明 OpenMetadata/Gravitino 的只读 bridge 合同和合成 provider reconciliation。继续实现受控 ingestion 前，必须先回答更基础的问题：选定版本能否在当前 ARM64 Kubernetes 环境真实启动、使用相互独立的 persistence、保持内网隔离，并在 Pod 替换后恢复相同 schema/index 状态。

仅提交 Helm values 或看到 Pod `Running` 都不能回答这些问题；一次本地重启也不能被描述为 backup/restore、PITR、DR、OIDC、生产 provider conformance 或生产就绪。

## Decision

### 1. M2a 本地 foundation profile

在 Docker Desktop `docker-desktop` context 的两节点 ARM64 kind cluster 中建立独立 namespace `gda-metadata-sandbox`：

| 组件 | 固定版本/来源 | Persistence | 角色 |
|---|---|---|---|
| OpenMetadata | 官方 chart `1.13.1`，SHA-256 `63081a...2000cf9a`；官方 ARM64 manifest `sha256:13df...ef538` | 专用 PostgreSQL 8 Gi + OpenSearch 16 Gi | governance foundation，不启用 ingestion |
| Gravitino | Apache release `1.3.0`，binary SHA-256 `bed7e5...625cd`，tag commit `40fdf6...8f0` | 专用 PostgreSQL 8 Gi | technical metadata foundation，不创建 production catalog |
| PostgreSQL | `16.10-bookworm` | 两个互不共享的 PVC | 分离 OpenMetadata 与 Gravitino metadata store |
| OpenSearch | `3.3.2` | 独立 16 Gi PVC | 仅作为 OpenMetadata search backend |

Gravitino 官方 release 没有可直接用于本机的受信 ARM64 registry artifact，因此由固定 release tarball 和 JDBC driver 构建 `gda/gravitino:1.3.0-local-arm64`。它的 provenance 必须写为 `local_release_build`，不能写成 registry provenance 或 production image attestation。

OpenMetadata 必须按固定 ARM64 manifest digest 拉取、验证 `linux/arm64`、重新标记官方 `1.13.1` tag，并导入全部 kind 节点；workload 使用 `imagePullPolicy: Never`。这既避免 registry 短读导致的 `ImagePullBackOff`，也防止节点运行时重新解析可变 tag。

### 2. 隔离与 Secret 边界

- 所有 Service 都是 `ClusterIP`；不创建 Ingress、Gateway、Route、NodePort 或 LoadBalancer；
- 所有 workload 使用专用 ServiceAccount 且 `automountServiceAccountToken=false`；
- PostgreSQL password 和 OpenMetadata Fernet key 由部署时外部生成的 Secret 提供，Secret object/value 不进入仓库或 evidence；
- pipeline deployment/client、Airflow auth、OIDC、HPA、PDB 和 OMJob operator 在 M2a 中关闭；
- 八条 NetworkPolicy 已配置，但本 ADR 不把配置存在写成 CNI enforcement 已验证；
- namespace CPU limit quota 为 15：常态 limit 使用 11，允许 OpenMetadata 单副本 RollingUpdate 峰值 14，同时保持 namespace 有界。

### 3. Live evidence 合同

新增 `data_agent.metadata_fabric_live_evidence`，只允许采集以下白名单事实：

- cluster context/UID、server/node version 和 architecture；
- namespace、workload、Pod、Service、PVC 和 NetworkPolicy identity；
- image、runtime image ID、pull policy、ServiceAccount、token automount 和 Ready 状态；
- OpenMetadata health/version/revision 与 Gravitino ready/version/revision；
- PostgreSQL public schema table name/count fingerprint；
- OpenSearch cluster UUID、version 和 index name/count fingerprint；
- 静态 source contract fingerprint。

collector 不读取 Kubernetes Secret。出现 secret/token/password/private-key 等额外字段时 verifier fail closed；`automount_service_account_token` 是唯一安全语义字段例外。

受控重启证明要求：

1. 五个 workload 的 Pod UID 前后全部变化，workload/cluster/namespace/source contract identity 不变；
2. 三个 PVC 的 UID、volume name、capacity、storage class 和状态完全一致；
3. OpenMetadata 176 张表、Gravitino 39 张表和 OpenSearch 78 个索引的名称 fingerprint 完全一致；
4. OpenSearch cluster UUID 不变；
5. 重启后 provider 版本、revision 和健康端点重新通过。

任一项漂移都会得到 `blocked`，不能以部分 Ready 或人工解释覆盖。

### 4. 固定的非声明

M2a evidence 即使通过，也必须固定：

- `production_provider_verified=false`；
- `production_table_catalog_provider_verified=false`；
- `network_policy_enforcement_verified=false`；
- `oidc_verified=false`；
- `backup_restore_verified=false`；
- `upgrade_verified=false`；
- `writes_to_gda_enabled=false`；
- `production_ready=false`。

Pod 重建后 PVC/schema/index 连续只证明本地持久卷被重新挂载和应用可恢复；它不证明备份可恢复、时间点恢复、节点/集群丢失恢复、RPO/RTO 或跨区域灾备。

## Verification

2026-07-27 的本地实采结果：

- Kubernetes `v1.35.5`，两个 `linux/arm64` 节点；
- OpenMetadata `1.13.1` revision `afcb2d...dc9` 返回 `OK`；
- Gravitino `1.3.0` revision `40fdf6...8f0` 返回 ready；
- 五个 workload 均为单副本 Ready，五个 Service 均为 ClusterIP；
- 三个 PVC 分别为 8 Gi、8 Gi、16 Gi，受控重启前后 identity 不变；
- 五个 Pod UID 全部变化，两个 PostgreSQL schema fingerprint、OpenSearch cluster UUID/index fingerprint 不变；
- evidence fingerprint 为 `ac21ee50ba3c1f27f949420cc7e4483963714b6b955bb0157eca1dd39cf102c3`。

该 evidence 是本机 point-in-time observation，不是受保护 runner attestation，也不授权 staging/production apply。

## Consequences

**Positive**：AR-1 第一次拥有可执行、可重放、Secret-free 的 OpenMetadata/Gravitino live foundation 和重启连续性证据；registry EOF、Gravitino runtime config、PostgreSQL PVC mount 和 RollingUpdate quota 等问题已进入代码合同。

**Negative**：本地 profile 仍是单副本、basic auth、local-path storage；运行 Gravitino local release image 还没有独立 registry provenance。

**Next gate**：M2b 完成 OIDC/workload identity、NetworkPolicy enforcement、backup/restore、upgrade/rollback、metrics/OTel、registry provenance 和 owner/runbook；M3 在同一地类图斑 ResourceVersion 上完成受控 ingestion/replay、OpenLineage、无双写和 Gravitino Spark/Sedona/Flink catalog conformance。
