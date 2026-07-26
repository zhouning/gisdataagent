# ADR-032：单次构建的 GHCR Candidate 与 OIDC Provenance

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, SRE, Security

**Related decisions**: ADR-028、ADR-029、ADR-031

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

Staging candidate evidence 已绑定 source revision、本地 image ID 和平台指纹，release bundle 也要求不可变 registry digest，但两者之间此前没有发布链。若验证后重新构建、从 `docker push` 文本猜测 digest，或仅以 tag 传递镜像，就无法证明 candidate 与后续 attestation 指向同一 OCI subject。

Registry binding 也不能自我证明 registry 身份或 attestation 有效。发布 workflow 可以请求 GitHub OIDC authority 生成 provenance，但真正的 promotion authority 仍必须在受保护 runner 上独立验证 OCI subject、repository/workflow identity 和 live staging evidence。

## Decision Drivers

- candidate 验证与 GHCR 发布必须使用同一个本地 application image ID；
- registry subject 必须是从远端 manifest 得到的不可变 `sha256` digest；
- provenance 必须绑定 GHCR subject，而不是可变 tag 或本地文件；
- 发布失败时仍应保留已形成的 candidate evidence；
- workflow 不得借发布或 attestation 声称 staging 已部署或允许 production promotion。

## Considered Options

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| 验证后重新构建并发布 | workflow 分段直观 | 两次构建可能漂移，candidate image ID 无法约束发布镜像 | 拒绝 |
| 从 `docker push` 控制台文本提取 digest | 实现短 | 依赖非结构化输出，客户端版本变化会破坏解析 | 拒绝 |
| 仅记录 GHCR tag | 易读 | tag 可移动，不能作为 release 或 attestation subject | 拒绝 |
| 单次构建 + 远端 raw manifest digest + GitHub OIDC provenance | candidate、registry subject 和 attestation 可连续绑定 | 仍依赖 GitHub/GHCR 身份，且需要后续独立验证 | 采用 |

## Decision

1. `.github/workflows/cd-staging.yml` 只构建一次 application candidate，并写入 `org.opencontainers.image.revision` 与 `org.opencontainers.image.source` OCI label；临时 PostgreSQL candidate 镜像不属于 application candidate。
2. candidate evidence 生成后，将同一个本地 image ID 重新 tag 到小写 `ghcr.io/${GITHUB_REPOSITORY}` 并 push，不执行第二次 application build。
3. 使用 `docker buildx imagetools inspect --raw` 从 registry 读取原始 manifest 字节，对其计算 OCI `sha256` digest，再以 `repository@digest` 做远端复查；禁止解析 `docker push` 文本。
4. `staging_registry_evidence` 校验 candidate fingerprint、source revision、本地 image ID、受保护 GHCR repository 和 manifest digest 的内部一致性。报告固定 `provenance_attestation_verified=false`、`registry_digest_verified=false`、`staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`。
5. workflow 使用 `actions/attest-build-provenance@v3` 为 GHCR `repository@digest` 请求 GitHub OIDC provenance，并推送 registry attestation。权限严格限定为 `contents: read`、`packages: write`、`id-token: write` 和 `attestations: write`。
6. candidate artifact 使用 `if: always()` 保留；registry binding artifact 只有在 provenance action 成功后才上传。两类 artifact 都不能单独授权 staging apply 或 production promotion。
7. workflow 不调用 Helm、Kustomize apply 或 `kubectl`，production workflow 继续固定失败。受保护 runner 后续必须独立验证 OCI attestation identity，再把已验证 subject 绑定到 release bundle 和 live staging observation。

## Consequences

正面影响：

- candidate 的本地 image ID、source revision、GHCR manifest digest 和 provenance subject 第一次形成可审计连续链；
- digest 来源不依赖 push 日志，tag 只承担发现作用；
- publication、attestation、deployment 和 promotion 保持为四个不同 verdict。

限制与代价：

- 截至 2026-07-26，本机可通过 `127.0.0.1:7897` 代理读取公开 GitHub 元数据，但 GitHub 登录已失效；workflow 尚未真实运行，GHCR 中没有由本次变更证明的 published subject 或 attestation；
- `staging_registry_evidence` 只检查输入绑定，不能替代 `gh attestation verify` 或等价 OCI 验证；
- 当前 workflow 只发布 application image，release bundle 依赖的 PostgreSQL、Redis 等基础设施镜像仍须由受保护环境 pin 到 digest；
- GitHub 托管 action 的公开 v3 输入契约已在线复核，实际 OIDC/GHCR 行为仍需在恢复身份后由首次受控运行验证。

## Verification

- 单元测试覆盖成功绑定、candidate fingerprint/source/image/repository/digest 漂移和 CLI 退出码；
- workflow 合同测试固定单次 application build、OCI revision label、远端 raw manifest digest、GHCR 登录、OIDC attestation、artifact 顺序和最小权限；
- candidate、registry、release bundle 与 live observation 的组合测试固定所有非 promotion flag 为 false；
- 首次真实 GitHub 运行仍是未完成的外部验收项。

## Revisit Triggers

- GitHub/GHCR 身份恢复并完成首次 attested subject 发布；
- protected staging runner 接入独立 attestation verification；
- publication 改用 `docker/build-push-action` 或其他可直接提供 digest/metadata 的构建系统；
- production promotion authority 需要支持 GitHub 以外的 OCI provenance issuer。
