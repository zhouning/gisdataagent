# ADR-075：受保护的 DolphinScheduler Worker 单副本激活边界

**Status**: Accepted

**Date**: 2026-08-16

**Decision owners**: Platform Architecture, DataOps, Security, SRE

**Related decisions**: ADR-027、ADR-028、ADR-029、ADR-033、ADR-034

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-027 建立了默认零副本的 managed DolphinScheduler command worker，受保护 readiness workflow 又能把 release、环境外部提供的 ConfigMap snapshot、Secret key attestation 与只读 live observation 绑定为 `ready_for_activation`。但 readiness 只能证明某个精确候选允许进入变更审批，不能自行改变集群。

若操作者下载 manifest 后手工执行 `kubectl apply`，readiness run、artifact、release attestation、manifest digest 与目标集群之间会失去可验证的连续绑定。若让 readiness workflow 同时持有 observer 和 mutation 权限，则会破坏只读采集边界，并可能绕过单副本和 production promotion 的固定阻断。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. readiness 后由操作者手工 apply | 实现最少 | artifact 和实际 apply 不可证明为同一内容，目标集群与审批也无法结构化审计 | 拒绝 |
| B. readiness workflow 直接扩容 | 步骤少 | 混合只读观察与写权限，失败证据可能意外进入 mutation 路径 | 拒绝 |
| C. 独立 protected activation workflow | admission、审批、mutation identity 和 live evidence 可分层验证 | 需要独立环境凭据和人工 reviewer | **选择** |

## Decision

1. `.github/workflows/activate-staging-dolphinscheduler-worker.yml` 是唯一登记的 worker staging 激活入口。它只能由 `main` 上的 `workflow_dispatch` 手工触发，使用 `staging-live` protected environment、专用 self-hosted runner 和 reviewer gate；不得有 push、pull request、schedule 或 workflow-chain 自动触发。
2. 调用者只提交 successful readiness run ID。workflow 必须从 GitHub API 验证 run 属于本仓库、`main`、固定 readiness workflow、`workflow_dispatch` 且成功完成，再选择名称与 run ID 精确绑定的唯一未过期 artifact。
3. 下载的 artifact archive 必须匹配 GitHub API 提供的 `sha256` digest。`activation-manifest.yaml`、`manifest-report.json`、`activation.json`、`readiness.json` 和 `release.json` 必须逐文件验证 readiness workflow attestation；`release.json` 还必须按其 verifier revision 验证原始 provenance verifier attestation。
4. side-effect-free admission verifier 必须在加载 mutation kubeconfig 前完成。它重新验证 schema、内部 fingerprint、release/activation/readiness 绑定、目标 namespace、protected cluster/namespace UID、manifest 文件 digest、immutable image、exactly-one replica 和资源白名单。
5. mutation manifest 只能包含以下三个 namespaced resource，且名称固定：
   - `Deployment/gis-agent-dolphinscheduler-command-worker`
   - `ServiceAccount/gis-agent-dolphinscheduler-command-worker`
   - `NetworkPolicy/postgres-access`
6. workflow 只有一次 `kubectl apply --server-side` mutation command，只能读取已 admission 的原始 manifest。禁止 `kubectl scale`、`kubectl patch`、读取 Secret/ConfigMap、创建环境 evidence、生成 provider identity 或访问 production authority。
7. apply 后只采集 allowlisted Deployment、Pod 和 worker health；必须重新生成 live readiness，并验证一个 ready replica、零首次激活重启、Pod-UID-derived worker ID 和 healthy status。admission、apply 与 live-readiness 结果全部 attested 和上传。
8. admission 与所有后续报告固定 `automatic_scale_allowed=false`、`promotion_authority_verified=false`、`production_promotion_allowed=false`。一次成功激活不授权第二副本、自动扩缩容、golden slice 成功裁决或 production promotion。
9. base manifest 继续保持 `replicas: 0`。只有被 admission 的 activation artifact 可以包含 `replicas: 1`；本 ADR 不允许修改默认副本数。

## Consequences

正向结果：

- readiness 证据、artifact archive、逐文件 attestation、release provenance、目标集群身份和唯一 mutation 形成可审计链路；
- observer identity 与 mutation identity 分离，缺任一外部 evidence 或 reviewer approval 时 fail closed；
- 实际 apply 内容被限定为可静态检查的最小资源集合，不能携带 Secret 或 ConfigMap。

代价与限制：

- staging 环境必须独立提供 kubeconfig、固定 cluster/namespace UID 与人工 reviewer；workflow 不负责 provision；
- activation 只证明 worker 单副本 rollout 和即时 health，不证明 callback、lease takeover、credential rotation、provider failover 或数据产品全链；
- artifact retention 到期或任一 identity/digest/fingerprint 漂移时必须重新运行 readiness，不能人工跳过 admission。

## Validation

- admission 单元测试覆盖正确 artifact、错误 workflow/run、artifact identity/digest drift、manifest bytes drift、Secret 注入、多副本、已部署 readiness 与 protected cluster UID drift；
- workflow 静态合同固定触发器、权限、environment、验证顺序、唯一 apply、禁用 scale/patch/Secret/ConfigMap read 和最终 promotion boundary；
- 两组测试进入 required platform CI，Ruff 与 `git diff --check` 为合并门；
- 本 ADR 的实现阶段不运行 activation workflow，不创建环境配置或凭据。真实 staging 状态在获得 ConfigMap snapshot、Secret attestation、provider identity 和 reviewer approval 前继续为 blocked。
