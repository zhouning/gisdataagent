# ADR-029：Live Staging Observation 与 Promotion Authority 边界

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related decisions**: ADR-027、ADR-028

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-028 已把 CI candidate 与真实 staging deployment 分开，但 production 仍缺少机器可验证的 live observation。单独查看 `kubectl rollout status`、Pod Ready 或 HTTP 200 不能证明运行镜像来自指定 source revision，也不能证明 schema、配置、运行时清单和 golden-slice 终局属于同一 Deployment。

Docker Desktop 首次实采证明了该风险：应用 Deployment 为 1/1 Ready，`/health` 与 `/ready` 正常，应用角色可读取 97/97 in-sync migration ledger；但运行镜像是本地 tag，Pod template 没有 source/candidate/platform fingerprint 注解，实际 profile 是 development，运行对象仍挂载 service-account token，且没有真实 golden-slice 证据。把这些状态称为 staging verified 会继续制造平台事实错误。随后 ADR-030 已消除 token 挂载，其他缺口仍继续阻断。

## Options Considered

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| 只在 workflow 中编写 `kubectl`/`curl` shell | 实现快 | 难以单测、字段容易泄漏、日志成功语义不稳定 | 拒绝 |
| 引入 Kubernetes Python SDK 和新的 DeploymentRevision 数据库 | API 完整 | 增加依赖与第二套未成熟权威，当前没有真实 staging provenance | 延后 |
| 标准库 collector + 纯 JSON verifier | 只读、字段白名单、可离线复核、可在真实 staging 直接运行 | v1 仍需外部 provenance/attestation 才能晋级 | 采用 |

## Decision

1. 新增 `data_agent.staging_live_evidence`，提供 `collect` 与 `validate`。collector 仅通过参数数组调用 `kubectl`，不使用 shell，不读取 Kubernetes Secret，也不保存完整 Deployment、ConfigMap 或应用响应；输出只保留验证所需字段。
2. 集群身份使用 `kube-system` namespace UID，环境身份使用 `gis-agent` namespace UID。两者的 expected value 必须来自受保护环境配置，不能由本次观察值自动接受。
3. live Deployment Pod template 必须绑定 `org.opencontainers.image.revision`、candidate evidence fingerprint、`staging` environment 和预期 platform fingerprint。v1 固定单副本 staging，直到逐 Pod config/runtime/health 采集实现；镜像必须为 registry `@sha256:` digest，Deployment generation/replica/Available/Progressing、Pod runtime image ID、ServiceAccount、禁用 token 挂载和 ready EndpointSlice Pod UID 必须一致。
4. collector 在运行中的 app container 内以普通应用凭据执行 migration `status` 和 platform `snapshot`，并通过 Kubernetes Service proxy 读取 `/health`、`/ready`。schema fingerprint 和 runtime fingerprint 必须与 candidate 对齐。
5. candidate 的临时 config fingerprint 不要求等于真实 staging config fingerprint。真实 config 与 runtime 重新组成 live platform fingerprint，并必须等于 Deployment Pod template 注解；这样既允许环境特定 endpoint/bucket，又禁止未声明配置漂移。
6. golden-slice evidence 采用固定字段白名单，绑定 source revision、Deployment UID、registry digest、live schema/config/runtime fingerprint、Run、output Artifact、QualityResult、LineageEvent 和 RunSuccessEvidence fingerprint；额外字段、过期证据或内容 fingerprint 不一致均 fail closed。
7. `live_staging_verified=true` 只表示 observation 内部一致。v1 固定 `promotion_authority_verified=false`、`production_promotion_allowed=false`。production workflow 在受保护 runner identity、artifact attestation 和同 revision approval 接入前继续固定失败。

## Consequences

正面影响：

- rollout、身份、配置、数据库、健康和业务终局第一次形成同一机器可验证边界；
- collector 不读取 Secret，且不会把完整 Kubernetes annotation、非必要配置或健康 detail 写入 artifact；
- 当前本地开发集群可以被真实观察，但会因客观缺口阻断，不会被包装成 staging 成功；
- 后续 provenance gate 可直接签署稳定 evidence fingerprint，不需要重新定义 observation 内容。

限制：

- `kube-system` UID 是实用的 cluster identity，不是密码学集群证明；
- v1 只从单个 app Pod 读取 process config/runtime，因此不接受多副本 staging；
- JSON 文件可被本地伪造，因此未 attested observation 不能成为 promotion authority；
- v1 不创建真实 golden-slice、registry push、staging overlay、worker activation 或 production rollout。

## Verification

- 行为测试覆盖完整 live binding、candidate/revision/digest/identity/schema/config/health/golden drift、过期/缺失 evidence、CLI fail closed 和 collector 字段白名单；
- 完整 fixture 可得到 `live_staging_verified=true`，同时保持 production promotion 为 false；
- Docker Desktop 首次实采验证 schema/runtime/health 通过，并正确识别 token 挂载；ADR-030 修复后重采得到 `automount_service_account_token=false`，immutable digest/revision/platform 注解、strict staging 和 golden-slice 缺口继续分域阻断；
- collector 输出未包含测试注入的 Secret、完整 last-applied annotation、health detail 或 platform config entries。

## Revisit Triggers

- 已有受保护 staging runner，可通过 GitHub OIDC、Sigstore 或等价机制证明 collector identity 与 artifact provenance；
- 真实 staging overlay 能绑定 registry digest、candidate/platform fingerprint 和固定 cluster/namespace identity；
- 首条真实地类图斑 golden-slice 能从数据库权威导出 Artifact/Quality/Lineage/RunSuccessEvidence，而不是手工 JSON。
