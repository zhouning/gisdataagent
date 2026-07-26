# ADR-031：Staging Release Bundle 结构化物化

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, SRE, Security

**Related decisions**: ADR-028、ADR-029、ADR-030

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

Candidate evidence 与 live observation gate 已存在，但两者之间缺少可审计的 release manifest：base 使用可变 image tag、开发 profile、占位 Secret 和本地模型 Service，也没有把 source revision、candidate fingerprint 与预期 live platform fingerprint 写入 Pod template。直接手工修改 YAML 会让同一 revision 产生不可复核的部署差异。

Release bundle 只能包含非秘密发布事实。真实 Secret、registry provenance、目标集群身份和 live 状态分别属于受保护环境、attestation authority 和 live collector，不能由一份本地 YAML 自我声明。

## Decision Drivers

- 同一 registry digest 必须覆盖 App、migration authority、Outbox 和 DolphinScheduler worker；
- Pod template 必须绑定 source/candidate/environment/platform 四个发布注解；
- 任何 Secret、hostPath、本地模型 endpoint 或 ServiceAccount token 漂移必须在 apply 前阻断；
- preflight 通过不能被解释为 staging 已部署或 registry provenance 已验证。

## Considered Options

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| 提交一份具体环境完整 YAML | apply 简单 | 容易陈旧，可能携带 Secret，发布事实分散 | 拒绝 |
| shell `envsubst`/`sed` 替换模板 | 实现快 | 类型和字段边界不可验证，错误替换难以 fail closed | 拒绝 |
| 公共 Kustomize staging template + Python/YAML 结构化物化 | 可测试、Secret-free、字段级绑定、输出可 fingerprint | 仍需要受保护 registry 与环境输入 | 采用 |

## Decision

1. `k8s/overlays/staging` 只保存公共 template：启用 strict staging、固定单副本，删除占位 Secret、本地 Ingress 和本地 Ollama Service。环境 Secret 必须预先由受保护系统提供。
2. `data_agent.staging_deployment_bundle` 接收已渲染 template、validated candidate、预期 live platform snapshot 和 registry `@sha256:` image。
3. materializer 删除所有 Secret 文档，将同一 image digest 写入 App、migration Job、Outbox 和 DolphinScheduler worker 的主/init container，并给四类 workload 的 Pod template 写入 source/candidate/environment/platform 注解。
4. 所有 release workload 禁用 ServiceAccount token automount；Secret resource、hostPath、敏感 ConfigMap/inline env、任意容器的可变 image tag、非 HTTPS/本地模型 endpoint、非 strict staging 和多副本 App 全部阻断。
5. 成功报告使用 `ready_for_staging_apply`，但固定 `registry_digest_verified=false`、`staging_deployed=false`、`live_cluster_verified=false` 和 `production_promotion_allowed=false`。真实 verdict 仍由 registry provenance 和 ADR-029 live observation 提供。

## Consequences

正面影响：

- release manifest 第一次成为 source、candidate、预期平台状态和镜像摘要的确定性组合；
- 公开仓库与生成 bundle 都不包含 Secret；
- mutation 测试可以在集群外验证最小权限、单副本和发布绑定。

限制与代价：

- 当前 GitHub 身份失效且没有 GHCR publish workflow，尚无真实 registry digest 或 provenance；
- 公共 template 中的基础设施镜像仍是 version tag，受保护环境必须将它们全部覆盖为 digest，bundle 才会通过；
- 公共 template 的默认 `http://ollama` 会被 bundle gate 主动阻断，受保护环境必须提供非本地 HTTPS 模型 endpoint；
- `bundle_ready` 只允许进入 staging apply 步骤，不证明 apply 已发生、配置与运行状态一致或 golden slice 通过。

## Verification

- 完整 fixture 可生成 Secret-free bundle，并确认七个 release image consumer 使用同一 digest；
- candidate fingerprint mutation、tagged image、敏感 ConfigMap、本地模型 endpoint、两副本 App 和 hostPath 均 fail closed；
- CLI 只在 `bundle_ready=true` 时写 manifest；
- staging Kustomize template 可渲染，且静态合同固定 Secret/Ingress/Ollama 删除与 HPA 单副本。

## Revisit Triggers

- GHCR 或等价 registry 已能产生同 revision digest 与可验证 provenance；
- protected environment 已提供 Secret、目标 cluster/namespace UID 和环境特定 ConfigMap overlay；
- live staging 已跑通首条真实 golden slice。
