# ADR-057: Production Object-Store Readiness Gate

**Status**: Accepted

**Date**: 2026-07-29

**Decision owners**: Metadata Platform, Data Engineering, Security, SRE, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-053](adr-053-production-metadata-fabric-identity-readiness-gate.md) · [ADR-056](adr-056-local-spark-object-store-interoperability.md)

## Context

M3-10 已证明 Spark `3.5.0`、Iceberg `1.6.1` 与 Gravitino `1.3.0` 可以在 Docker Desktop Kubernetes 中通过跨节点 MinIO S3 API 读写同一 Iceberg warehouse，并由直接对象检查验证 data、metadata、manifest、schema 和 snapshot 一致。但 MinIO、两个 Kubernetes node 和 PVC 仍位于同一台主机；运行时使用临时静态凭据、Basic IdP 和无认证 HTTP REST。因此该 evidence 不能证明生产对象存储、独立 failure domain、protected workload identity、TLS、KMS、tenant isolation 或灾难恢复。

在具体云账户、region、bucket、identity integration、KMS、replication、owner 和受保护环境尚未获批时，直接选择 AWS S3、华为云 OBS 或另一个 S3-compatible provider 会把技术默认值伪装成生产决策。M3-11 需要先把生产对象存储的最低边界和验收证据冻结为机器可验证、默认关闭的合同，同时明确不选择 provider、不部署基础设施、不持有凭据，也不制造 production attestation。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 将 M3-10 MinIO evidence 直接提升为生产对象存储 | 无新增实现 | 同主机 failure domain、静态凭据和 HTTP 不具备生产语义 | 拒绝 |
| 在未获批时直接选择并部署一个云 provider | 快速得到真实 endpoint | 账户、区域、安全、成本、合规和 owner 决策均越权 | 拒绝 |
| 继续只在 roadmap 维护对象存储缺口 | 无新增代码 | CI 无法拒绝 placeholder、权限扩大、过期证明或配置漂移 | 拒绝 |
| 版本化 pending profile + 独立、新鲜且完全绑定的 attestation | 决策与运行证据分离；未选型时可诚实 fail closed | 需要 owner 后续批准 profile 并维护证明生命周期 | 采用，限定为 M3-11 |

## Decision

### 1. Checked-in profile 固定生产对象存储边界，不代表选型或部署

`config/metadata-fabric-object-store.production.yaml` 固定：

- Spark `3.5.0`、Iceberg `1.6.1`、Gravitino `1.3.0` 与 M3-10 local evidence fingerprint；
- provider account、region、HTTPS endpoint、bucket、warehouse prefix、基础设施和 failure-domain reference，以及独立 recovery region；
- 只允许 `aws_s3`、`huawei_obs_s3_compatible` 或 `managed_s3_compatible`；原生非 S3 provider 必须进入新的 conformance slice；
- OIDC workload federation、Kubernetes ServiceAccount、最长 900 秒 session、禁止 static credential，以及精确的八项 S3 data-plane permission；
- TLS 1.2+、private connectivity、DNS/trust/certificate policy；
- KMS server-side encryption、key policy/rotation、versioning、delete recovery、cross-region replication 与 `RPO <= 15 min`、`RTO <= 60 min`；
- strong read/list-after-write、multipart cleanup、Iceberg orphan cleanup、tenant prefix + provider policy、cross-tenant denial 和 public-access block；
- platform/security/storage/incident owner、audit、metrics/alert、availability/latency SLO、operations/recovery/rollback runbook 与 protected-environment policy；
- 所有 self-reported production claim 固定为 `false`。

`null` 与 `decision_status=pending` 是合法的显式 blockers，所以当前 profile 可以结构有效而不假装外部决策已完成。placeholder、HTTP/loopback/cluster-local endpoint、credential-bearing 字段、扩大后的 S3 permission、local evidence 或 engine version 漂移、自报生产结论、同 region recovery 或弱化 identity/TLS/KMS/durability/tenancy baseline 都使 profile 无效。

### 2. 生产结论只能从受保护 attestation 派生

`data_agent.metadata_fabric_object_store_gate` 将结果分为三层：

1. `profile_valid`：profile 的结构、安全基线和 M3-10 evidence binding 可信；
2. `ready_for_protected_verification`：provider、identity、transport、encryption、durability、consistency、tenancy 和 operations 的 43 项外部输入均已明确；
3. `production_object_store_gate_passed`：另有新鲜的 `production-object-store` protected-environment attestation，且绑定当前 profile、source revision、M3-10 evidence、engine versions、八组 section fingerprint 和三个 runbook version。

attestation 的精确 26 项检查必须全部为 `passed`，覆盖 provider/account/failure domain、private network/TLS、workload identity/static credential absence、least-privilege allow 与 administrative/cross-tenant/public denial、KMS/rotation、versioning/cross-region replication、read/list consistency、multipart/orphan cleanup、Spark/Gravitino read-write、commit failure recovery、source-cluster loss recovery、audit、metrics/alert、backup/restore 和 rollback rehearsal。观测时间不得早于验证时刻 24 小时，expiry 必须在未来且有效期最长七天，evidence URI 必须是非本地 HTTPS；任何 binding 漂移、过期或失败都会关闭门禁。

### 3. 对象存储门禁通过也不等于平台生产就绪

同一有效 attestation 可派生 object-store decision、protected workload identity、TLS、KMS、tenant isolation、durability、failure recovery 和 production object-store claims。报告中的 `production_ready` 始终固定为 `false`；生产 identity 全链、observability、NetworkPolicy、provider ingestion、持久 binding、cancel/reconcile/lineage、完整 Spark/Flink conformance、upgrade、registry provenance 和其他退出门仍须独立通过。

`validate` 只验证 checked-in profile，因此有效的 pending contract 在 CI 中成功；`evaluate` 必须提供 attestation，且仅在对象存储门禁实际通过时成功；`verify` 拒绝 fingerprint 漂移、派生 claim 不一致和 overall production overclaim。本切片不提交真实 attestation、不连接 provider、不创建 bucket/key/policy，也不修改 Kubernetes workload。

## Verification

当前 checked-in profile：

- profile fingerprint：`668e194b3c688307014148391e7f389c9d6e9ca69c95d7b4cc92b4acae93181a`；
- report fingerprint：`85362dd10b7dc565f9fa567673d90b774cdec714bd1e70fb2c3c83c1af48b5ea`；
- `profile_valid=true` 且无 profile errors；
- 43 项 provider/identity/transport/encryption/durability/consistency/tenancy/operations 外部输入以 blockers 暴露；
- `ready_for_protected_verification=false`、`attestation_valid=false`；
- 全部对象存储生产 claims 与 `production_ready` 固定为 `false`。

32 个定向测试覆盖 pending/complete profile、三类允许的 S3-compatible provider、原生非 S3 provider 拒绝、新鲜且完全绑定的合成 attestation、least privilege 与 local evidence drift、static credential/HTTP/public access/same-region recovery、敏感字段、自报 claim、全部 section binding、关键 security/durability/recovery check、runbook version、过期证明、报告篡改、malformed YAML 和生产 overclaim。

## Claim Boundary

允许声明：

- M3-11 production object-store readiness contract 已建立；
- 当前 pending profile 结构有效，并机器可读地暴露 43 个 blockers；
- 合成完整 profile/attestation 验证了 fail-closed 门禁逻辑。

当前不得声明：

- 已选择、采购、配置、部署或验证 AWS S3、华为云 OBS 或任何生产对象存储；
- 已验证生产 workload identity、TLS/private network、KMS、tenant isolation、versioning/replication、RPO/RTO、commit failure 或 source-cluster loss recovery；
- 已完成 cancel/reconcile/lineage、Flink 或完整 Spark conformance；
- `production_object_store_gate_passed=true`、`production_object_store_verified=true` 或 `production_ready=true`。

## Consequences

**Positive**：本地 MinIO evidence 不再可能被误读为生产 storage；provider-neutral 的 S3-compatible 决策边界、最小权限、failure domain 和受保护证据生命周期可由 CI 与后续 protected runner 一致校验。

**Negative**：M3-11 本身不增加生产存储能力。门禁会保持 blocked，直到 Metadata Platform、Data Engineering、Security 和 SRE 完成 provider、账户、区域、identity、network、KMS、replication、tenancy、operations 和 owner 决策。

**Next gate**：批准并物化 production profile，在受保护环境部署选定的 S3-compatible 路径，生成绑定当前 source/profile 的真实 attestation并通过全部 26 项检查；随后以该路径执行 commit failure、source-cluster loss、cancel/reconcile/lineage 和完整 Spark/Flink conformance，同时继续独立完成其余 production gates。
