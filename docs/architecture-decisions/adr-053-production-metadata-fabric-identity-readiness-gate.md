# ADR-053: Production Metadata Fabric Identity Readiness Gate

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, Security, SRE, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-046](adr-046-production-network-policy-readiness-gate.md) · [ADR-051](adr-051-local-openmetadata-bounded-provider-identity.md) · [ADR-052](adr-052-local-gravitino-basic-bounded-provider-identity.md)

## Context

M3-5 与 M3-6 已分别证明 OpenMetadata `1.13.1` 临时 bot 和 Gravitino `1.3.0` Basic user 的本地最小权限、越权拒绝、credential rotation/revocation 与完整清理。两次演练都依赖本地管理员 provisioner、loopback HTTP 和短生命周期凭据；Gravitino probe 还使用 memory catalog。因此它们不能证明双 provider 的生产 OIDC、受保护 workload identity、TLS、持久 catalog、tenant isolation 或生产 credential delivery。

对 Gravitino `1.3.0` 镜像的检查只发现 `/opt/gravitino/libs/gravitino-idp-basic-1.3.0.jar`，没有发现随镜像交付的原生 OIDC extension。生产设计不能假设不存在的 native OIDC 能力，也不能把 Basic IdP 包装成生产联邦身份。本切片需要把生产身份决策和验收条件冻结为机器可验证、默认关闭的合同，但不替团队选择 IdP、部署认证组件或制造生产证明。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 将 M3-5/M3-6 本地结果直接提升为生产身份 | 无新增实现 | 本地 JWT/Basic、HTTP 与 memory catalog 没有生产身份语义 | 拒绝 |
| 假设 Gravitino 内置 native OIDC | 配置看似简单 | 与 `1.3.0` 镜像内容不符，形成不可执行合同 | 拒绝 |
| 继续只在 roadmap 列举 IAM 缺口 | 无新增代码 | CI 无法拒绝 static credential、placeholder、过期证明或配置漂移 | 拒绝 |
| 版本化 pending profile + 独立、新鲜且完全绑定的 attestation | 决策与运行证据分离；可在未选型时诚实 fail closed | 需要后续 owner 明确选型并维护证明生命周期 | 采用，限定为 M3-7 |

## Decision

### 1. Checked-in profile 固定生产身份边界，不代表部署

`config/metadata-fabric-identity.production.yaml` 固定：

- OpenMetadata `1.13.1`、Gravitino `1.3.0` 及 M3-5/M3-6 两份本地 evidence fingerprint；
- OIDC federation、`sub` workload subject、`gda_tenant_id` tenant claim、最长 900 秒 token 与 short-lived token exchange；
- 每个 provider 的 integration mode、digest-pinned authentication component、环境和 Kubernetes ServiceAccount binding，以及禁止绕过受证明身份路径；
- M3-5/M3-6 已验证的精确 allow/deny authorization contract；
- TLS 1.2+、内部 mTLS、持久 Gravitino catalog、namespace + provider policy tenant isolation；
- identity/security/incident owner、audit、rotation/revocation SLO、runbook 与 rollback runbook；
- 所有 self-reported production claim 固定为 `false`。

OpenMetadata 只允许 `provider_native_oidc` 或 `identity_aware_proxy`；Gravitino 只允许 `custom_oidc_authenticator` 或 `identity_aware_proxy`。`simple`、本地 `basic`、静态 JWT、密码或长生命周期 credential 都不能通过该门禁。认证组件必须是 digest-pinned OCI reference。

`null` 和 `decision_status=pending` 是合法的显式 blockers，所以当前 profile 可以结构有效而不假装外部决策已完成。placeholder、loopback/cluster-local 或非 HTTPS endpoint、credential-bearing 字段、mutable OCI reference、扩大后的 provider permission、provider version/local evidence 漂移或自报生产结论都会使 profile 无效。

### 2. 生产结论只能从受保护 attestation 派生

`data_agent.metadata_fabric_identity_gate` 将结果分为三层：

1. `profile_valid`：profile 的结构、安全边界和本地 evidence binding 可信；
2. `ready_for_protected_verification`：federation、双 provider、TLS、catalog、tenancy 和 operations 的 40 项外部输入已经明确；
3. `production_identity_gate_passed`：另有新鲜的 production protected-environment attestation，且绑定当前 profile、source revision、provider versions、本地 evidence、六组派生 fingerprint 和两个 runbook version。

attestation 的精确 18 项检查必须全部为 `passed`：OIDC discovery/token exchange、workload subject 和 tenant claim binding、双 provider allow/administrative deny、provider direct-access bypass denial、static credential absence、rotation/revocation、TLS/mTLS、持久 catalog restart、cross-tenant denial、audit delivery 和 rollback rehearsal。观测时间不得早于验证时刻 24 小时，expiry 必须在未来且有效期最长七天，evidence URI 必须是非本地 HTTPS；任何漂移、过期或失败都关闭门禁。

### 3. 身份门禁通过也不等于平台生产就绪

同一有效 attestation 可唯一派生 provider minimum privilege、protected workload identity、OIDC、TLS、rotation/revocation、persistent catalog identity binding 和 production identity claims。报告中的 `production_ready` 始终固定为 `false`；生产 recovery、observability、NetworkPolicy、upgrade、registry provenance、持久 binding、ingestion/OpenLineage conformance 等退出门仍须独立通过。

`validate` 只验证 checked-in profile，因此有效的 pending contract 在 CI 中成功；`evaluate` 必须提供 attestation，且仅在身份门禁实际通过时成功；`verify` 拒绝 fingerprint 漂移、派生 claim 不一致和 overall production overclaim。本切片不提交真实 attestation、不部署认证组件，也不修改 provider。

## Verification

当前 checked-in profile：

- profile fingerprint：`2e9d5cac3560b853820f923669f6794ead63bcb36a528639fc0e9539e148ee2f`；
- report fingerprint：`c607589ee25a87acc8a1ab71372618a9a4c10c1e8ebff15b8db7e78b37600b9f`；
- `profile_valid=true` 且无 profile errors；
- 40 项 federation/provider/TLS/catalog/tenancy/operations 外部输入以 blockers 暴露；
- `ready_for_protected_verification=false`、`attestation_valid=false`；
- 全部生产身份 claims 与 `production_ready` 固定为 `false`。

26 个定向测试覆盖 pending/complete profile、新鲜且完全绑定的合成 attestation、两类 provider integration mode、Gravitino native OIDC/Basic/simple 拒绝、authorization/local evidence/binding drift、placeholder/HTTP/loopback/mutable OCI、敏感字段、自报 claim、过期或失败证明、报告篡改和生产 overclaim。

## Claim Boundary

允许声明：

- M3-7 production Metadata Fabric identity readiness contract 已建立；
- 当前 pending profile 结构有效，并机器可读地暴露 40 个 blockers；
- 合成完整 profile/attestation 验证了 fail-closed 门禁逻辑。

当前不得声明：

- 已选择、部署或验证生产 IdP、OIDC federation、identity proxy 或 Gravitino custom authenticator；
- 已验证生产 workload identity、TLS/mTLS、tenant isolation、持久 catalog identity binding 或双 provider minimum privilege；
- `production_identity_gate_passed=true` 或 `production_ready=true`。

## Consequences

**Positive**：本地 Basic/JWT evidence 不再可能被误读为生产身份；Gravitino 的实际扩展边界被显式记录；受保护环境可用同一 profile-bound gate 发现 credential、权限、配置和证据漂移。

**Negative**：M3-7 本身不增加登录或授权能力。门禁会保持 blocked，直到 Metadata Platform、Security 和 SRE 完成 IdP、provider integration、持久 catalog、tenant、TLS 与运营决策。

**Next gate**：批准并物化 production profile，在受保护环境部署 digest-pinned authentication path，生成绑定当前 source/profile 的真实 attestation并通过全部 18 项检查；随后将该身份路径用于受控双 provider ingestion、持久 binding 和 production OpenLineage conformance，且继续独立完成其余 production gates。
