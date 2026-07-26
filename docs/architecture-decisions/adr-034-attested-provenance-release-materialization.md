# ADR-034：Attested Provenance 到 Staging Release 的受保护物化

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, SRE, Security

**Related decisions**: ADR-031、ADR-032、ADR-033

**Supersedes**: ADR-033 Decision 4 中 checkout publisher revision 执行 verifier 的细节；OCI 验证策略保持不变

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-033 让独立 workflow 验证 GHCR subject，并对 `provenance.json` 再做 artifact attestation。但 ADR-031 的 bundle materializer 仍由调用方直接传入 image，且固定 `registry_digest_verified=false`；仅把 `provenance.json` 下载到 runner 并读取其中的 `true` 字段，会重新退化为信任可伪造 JSON。

`workflow_run.head_sha` 是 publisher revision，verifier run 的 `GITHUB_SHA` 是 verifier workflow/code revision。两者可能因 main 前进而不同。若 verifier checkout publisher revision 执行代码，或者下游把两个 SHA 当成一个，就无法精确证明哪一版 verifier 生成了 evidence。

## Decision Drivers

- release image 必须只能来自已验证 provenance，调用者不能另传一个不同 digest；
- `provenance.json` 的文件 digest、signer workflow、verifier revision、main ref、OIDC issuer 和 runner environment 必须由证书身份验证；
- publisher source revision 与 verifier code revision 必须分别记录和分别校验；
- provenance artifact、candidate、registry、platform 和 manifest fingerprint 任一漂移都必须 fail closed；
- verified bundle 只能授权 staging apply，不能声明 apply、live cluster 或 production promotion 已完成。

## Considered Options

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| 读取 `provenance.json` 的 verified 字段后直接 materialize | 实现最短 | 本地伪造 JSON 可获得 apply 输入权 | 拒绝 |
| 在 bundle CLI 增加 `--provenance-verified=true` | 改动小 | 调用者自报安全 verdict，无法审计 authority | 拒绝 |
| 先固定身份验证 provenance artifact，再由其中的 image 调用原结构化 materializer | artifact、内容与 manifest 形成可测试链；保留 ADR-031 的纯 preflight | 增加一次 GitHub attestation 查询，并需要两个 revision | 采用 |
| 立即新增自动 apply workflow | 可缩短交付路径 | 当前无受保护 overlay、真实 Secret/endpoint、完整基础设施 digest 和 cluster identity | 暂缓 |

## Decision

1. `verify-staging-provenance.yml` checkout 自身 `github.sha` 的受保护 verifier revision 执行代码；publisher `workflow_run.head_sha` 只作为 OCI source/signer policy 的被验证 revision。`provenance.json` 同时记录 `source_revision` 和 `verifier_revision`。
2. 新增 `data_agent.staging_release_evidence`。它对本地 `provenance.json` 执行 `gh attestation verify`，固定 repository、`verify-staging-provenance.yml` signer workflow、verifier signer/source digest、`refs/heads/main`、GitHub OIDC issuer、SLSA v1 和 `--deny-self-hosted-runners`。
3. 命令成功后仍须确认 verified statement subject 的 `sha256` 等于本地 provenance 文件 digest。原始 bundle、证书和 stderr 不写入 release evidence。
4. provenance 内容必须满足 schema/fingerprint、publisher verification policy、source/verifier revision、candidate/registry fingerprint、GHCR repository/digest/image、正数 attestation count、全部 identity verdict 和所有非 deployment flag。candidate source/fingerprint 必须与之精确一致。
5. image 不再由受保护 materializer 的调用者提供，只能读取已验证 provenance 的 `repository@sha256:`。随后复用 ADR-031 materializer 验证 platform、Secret-free manifest、全部 immutable image、release annotations、单副本和最小权限。
6. 成功状态为 `verified_for_staging_apply`，允许 `provenance_evidence_artifact_verified=true`、`provenance_attestation_verified=true` 和 `registry_digest_verified=true`；仍固定 `staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`。
7. 在受保护环境 overlay、Secret lifecycle、外部 HTTPS endpoint、基础设施 image digest、cluster/namespace identity 和 rollback 入口完整前，不新增会实际调用 `kubectl apply` 的 workflow。

## Consequences

正面影响：

- publisher SHA、verifier SHA、provenance artifact digest、OCI digest 和 manifest fingerprint 形成分层绑定；
- 本地伪造 provenance JSON、错误 verifier revision、candidate 漂移或不同 artifact subject 都不能生成 manifest；
- ADR-031 的离线模板检查仍可独立使用，受保护 authority 则有单独、不可用布尔参数绕过的入口。

限制与代价：

- 合成 `verified_for_staging_apply` 只证明代码合同；在真实 artifact attestation 可查询前仍不是远端发布事实；
- GitHub workflow identity 与 main protection 仍属于同一仓库信任域，后续可迁移到独立 trusted reusable workflow；
- materializer 不管理 Secret、不选择 cluster，也不执行 apply；这些权限必须留在后续受保护部署 workflow；
- verifier run 与 publisher run 的 revision 不必相等，运维和审计必须保留两个 SHA。

## Verification

- 合同测试固定 artifact verifier 的 repository/workflow/ref/digest/issuer/hosted-runner 参数；
- 成功 fixture 验证 artifact digest 后从 provenance 派生 image，并生成同 manifest fingerprint 的 release report；
- provenance/candidate 漂移会在外部命令前阻断，错误 artifact subject digest 会在 materialize 前阻断；
- CLI 仅在完整链成立时写 manifest，外部 verifier 失败信息不会进入 evidence；
- 原 ADR-031 bundle mutation 测试继续覆盖 Secret、tag、本地 endpoint、hostPath、敏感配置和多副本漂移。

## Revisit Triggers

- `staging-provenance` environment 完成首次真实 verifier run；
- 受保护 staging overlay 与全部基础设施 digest 已形成独立 review authority；
- cluster/namespace identity、Secret provisioning 和 rollback workflow 可用；
- 组织级 trusted reusable workflow 或独立 Security repository 建立。
