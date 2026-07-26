# ADR-033：受保护的 Staging OCI Provenance 独立验证

**Status**: Accepted

**Date**: 2026-07-26

**Updated**: 2026-07-26 after ADR-035 mainline recovery

**Decision owners**: Platform Architecture, SRE, Security

**Related decisions**: ADR-029、ADR-031、ADR-032

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-032 建立了 candidate 到 GHCR subject 和 GitHub OIDC provenance 的发布链，但 publisher 自己生成的 `registry.json` 固定不能自证 attestation。仅检查 JSON 字段、attestation action 成功状态或 OCI tag，都会让发布者同时成为验证权威。

GitHub CLI 可以把 repository、signer workflow、source ref/digest、signer digest、OIDC issuer 和 runner environment 作为证书扩展校验。与 workflow 可影响的 provenance predicate 不同，这些证书扩展由 GitHub OIDC/Fulcio 身份链提供。验证必须在独立运行和受保护 environment 中执行，并把结果自身再次 attested，才能为后续 release bundle 提供可验证输入。

## Decision Drivers

- publisher 不能通过自己上传的 `registry.json` 获得 staging apply 权限；
- verifier 必须固定 source repository、`main`、完整 SHA 和 signer workflow，调用方不能放宽策略；
- self-hosted publisher、错误 OIDC issuer、错误 predicate 或不同 OCI subject 必须 fail closed；
- verification evidence 自身需要独立 workflow identity，但仍不能声明 staging deployment 或 production promotion；
- `workflow_run` 的高权限边界必须只接受本仓库 `main` 上人工触发且成功的 publisher run。

## Considered Options

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| publisher workflow 内直接把 verified 写为 true | 实现最短 | 自签自验，没有独立 authority | 拒绝 |
| 只解析 attestation JSON/predicate | 易测试 | predicate 可被 publisher 控制，不能证明证书身份 | 拒绝 |
| 独立 `workflow_run` + `gh attestation verify` 固定证书策略 | GitHub 原生、可审计、subject/identity 双重绑定 | 需要 environment 保护和首次远端运行 | 采用 |
| 立即迁移到独立仓库 trusted reusable workflow | 隔离更强 | 当前尚无组织级 builder/owner 和运维边界 | 后续演进 |

## Decision

1. 新增 `data_agent.staging_provenance_evidence`。它先验证 registry evidence schema、fingerprint、source/candidate/local image ID、GHCR repository/digest 和所有非 promotion flag，再决定是否调用外部 verifier。
2. verifier 固定执行 `gh attestation verify`，同时约束：`--repo`、`--signer-workflow`、`--signer-digest`、`--source-ref refs/heads/main`、`--source-digest`、GitHub OIDC issuer、SLSA v1 predicate 和 `--deny-self-hosted-runners`。调用方只能提供本仓库 slug 与 publisher run SHA。
3. 命令必须成功且 JSON 中至少一个 verified statement 的 subject name/digest 精确匹配 `repository@sha256:`。原始 attestation bundle、证书和命令 stderr 不复制到 GDA evidence。
4. `Publish - Staging Candidate Image` 只允许 `workflow_dispatch`，且 publisher job 明确要求 `refs/heads/main`。`verify-staging-provenance.yml` 只响应该 workflow 的成功、本仓库、`main`、`workflow_dispatch` 类型 `workflow_run`。它 checkout publisher 的精确 SHA，并进入 `staging-provenance` environment。禁止通过普通 `main` push 隐式发布 candidate。
5. environment 必须设置 environment-level `GDA_STAGING_PROVENANCE_PROTECTED=true`，并在 GitHub 中配置 required reviewers、禁止无审核 bypass。变量只是显式启用开关，不能替代 GitHub environment protection rule。
6. verifier workflow 仅拥有 `actions: read`、`contents: read`、`packages: read`、`id-token: write` 和 `attestations: write`；验证结果由该独立 workflow 再生成 artifact attestation，成功后才上传。
7. `provenance_verified` 允许 `provenance_attestation_verified=true` 与 `registry_digest_verified=true`，但固定 `staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`。release bundle 消费前仍须验证 provenance evidence artifact identity。

## Consequences

正面影响：

- GHCR subject、source SHA、publisher workflow 和 GitHub-hosted runner 第一次由独立策略验证；
- repository/workflow/ref/digest/issuer 使用证书扩展，而不是信任 publisher predicate；
- provenance evidence 具备自己的 verifier workflow identity，后续 release apply 可以验证其来源。

限制与代价：

- publisher 与 verifier 仍位于同一仓库；在独立 trusted builder/reusable workflow 建立前，安全性依赖 main branch protection、CODEOWNERS 和 environment reviewers；
- GitHub environment protection 不能由仓库 YAML 自证，必须在远端配置并留存设置证据；
- `staging-provenance` environment、required reviewer、禁止 admin bypass 和 environment-level 显式变量已配置；publisher/verifier 尚未完成一次成功的真实运行；
- verifier 只证明 OCI provenance，不证明 release manifest、Secret、目标集群、live config 或 golden slice。

## Verification

- 测试覆盖精确 command policy、成功 subject、registry/source/fingerprint 漂移、空与错误 subject、CLI 故障脱敏和非 promotion flags；
- workflow 合同测试固定 publisher 只能手工从 main 触发，并固定 verifier 的 `workflow_run` 来源、main、`workflow_dispatch`、本仓库、environment、最小权限、artifact run-id、GHCR login、verification-attestation-upload 顺序和无部署命令；
- GitHub CLI 2.92.0 help 与官方实现源码已复核，确认 signer/source digest、source ref、OIDC issuer 和 runner environment 分别映射到证书扩展；
- 真实 GHCR subject 验证仍是未完成的外部验收项。

## Revisit Triggers

- 组织级 trusted reusable builder 与独立 Security owner 可用；
- `staging-provenance` environment 已配置并完成首次 publisher/verifier run；
- release bundle workflow 需要消费并验证 provenance evidence artifact；
- production promotion authority 开始组合 live evidence、approval 和 rollback verdict。
