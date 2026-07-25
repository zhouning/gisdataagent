# ADR-024：以不可变证据强制 DataOps Dispatch 授权

**Status**: Accepted

**Date**: 2026-07-25

**Decision owners**: Platform Architecture, DataOps, Data Platform, Security

**Related decisions**: ADR-007、ADR-020、ADR-022、ADR-023

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-022 已建立 tenant-scoped PlatformGateway，ADR-023 已把 DolphinScheduler binding 固化为 append-only execution-plan Artifact，但 `platform_operator` 仍可提交没有资源级授权证据的 Run，adapter 也只依赖调用方传入的 actor 字符串。生产 DataOps dispatch 必须把已认证 workload、不可变资源版本、execution plan、策略判定和必要的人工审批绑定在同一个 Run 上，并在任何 provider 调用前 fail closed。

本切片不能新增 scheduler、queue、微服务或第二个 Run authority。PolicyDecision 和 Approval 在 Run 提交前形成，当前也没有需要独立查询、分派和变更的审批生命周期。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 在 PlatformRun 内嵌自由 policy/approval JSON | 实现最少 | Run 自报授权，缺少独立内容身份和复核边界 | 拒绝 |
| B. 立即新增 PolicyDecision/Approval 表和服务 | 查询与工作流边界显式 | 在没有生命周期和容量证据时增加 schema、API、权限和恢复成本 | 暂缓 |
| C. 强类型 evidence Artifact + PlatformRun 不可变引用 | 复用 append-only ledger、tenant RLS 和幂等 gateway，同时保留未来拆表路径 | 当前不提供审批 inbox、委派或专用查询模型 | **选择** |

## Decision

### 1. 冻结资源级授权合同

`PolicyDecision` 必须绑定 tenant、Run ID、完整 SubjectContext、command action、Definition ResourceVersion、全部 input ResourceVersion 和 execution-plan Artifact。判定还包含 versioned policy reference、独立 evaluator workload、effect、有效期、obligations 和是否需要审批。资源集合必须精确相等；未知 obligation 当前一律拒绝，不能静默忽略。

`ApprovalRecord` 必须绑定同一 tenant、Run、Definition、PolicyDecision Artifact UUID 和内容 SHA-256，并记录 human approver、verdict、理由和不超过 policy 的有效期。批准者必须与 executor 和 evaluator 分离。

### 2. 复用 append-only Artifact

PolicyDecision 和 Approval 使用版本化 envelope、canonical JSON hash/size、确定性 UUID、稳定 media type 和 PostgreSQL evidence URI。manifest 与 Artifact metadata、creator 和 timestamp 必须完全一致；任何缺失、内容或 metadata 篡改均 fail closed。

PlatformRun 只保存 `RunPolicyReferences` 中的 Artifact UUID，不复制或允许修改判定内容。现有 `gda_control.platform_run.policy_refs` JSONB 和 append-only Artifact 表是这一阶段的持久化边界，不新增 registry 或表。未来只有出现审批生命周期查询、跨团队工作流或已测得的容量需求时才重新评估专用表。

### 3. 在提交和 dispatch 两次校验

PlatformGateway 在同一 tenant-scoped 提交事务中读取 PolicyDecision、可选 Approval 和 execution-plan Artifact，验证不可变资源 scope、effect、有效期和审批关系后才创建带引用的 Run。为兼容尚未迁移的旧 Run，gateway 仍允许 `policy_refs=NULL`；这不是 DolphinScheduler dispatch 的授权豁免。

DolphinScheduler adapter 在 provider 查询、CAS transition 和 start 调用前强制要求 policy references，重新加载持久化 execution plan 和授权证据，并以实际时钟校验 `action=dolphinscheduler.dispatch` 和有效期。授权失败时不得调用 provider，也不得改变 PlatformRun 状态。

### 4. 绑定 workload identity

Run SubjectContext 继续由 versioned API 的认证 principal 派生。adapter profile 显式配置 executor workload 和独立 policy evaluator workload；binding publish、dispatch、reconcile 和 cancel 的 actor 必须与 profile 及 Run SubjectContext 完全一致。Policy/Approval Artifact 通过 API 写入时，`created_by` 仍必须等于认证主体。

这建立的是 authenticated SubjectContext、configured workload/evaluator 和 evidence gate 的代码边界，不等于生产 IAM 已完成。DolphinScheduler service token 的 OIDC/IAM provisioning、轮换、吊销和 provider 侧最小权限仍需 staging 验证。

## Consequences

正面影响：

- 资源、执行计划、主体、策略和审批形成可内容寻址复核的一条授权链；
- deny、过期、scope 漂移、未知 obligation、缺失或拒绝审批均在 provider 调用前失败；
- 继续复用 PlatformGateway、RLS、Artifact 和唯一 PlatformRun authority，没有新增运行时组件。

限制与缓解：

- 当前 evaluator 负责产生判定，平台只验证证据合同，不包含通用 policy engine；
- Artifact 完整性依赖受控 API、数据库权限和 append-only ledger，不是可脱离平台验证的签名凭证；
- legacy Run 可不带 policy refs，但 DolphinScheduler 新 dispatch 已强制要求；生产切换前必须清点其他执行入口；
- 没有 approval inbox、委派、撤回或生命周期查询；出现真实需求后再以 Artifact 为迁移来源建立投影或专用表。

## Verification

- 合同与 evidence 测试覆盖 canonical scope、稳定 Artifact identity、metadata 篡改、deny、过期、未知 obligation、缺失/拒绝审批和独立人工批准。
- gateway 测试覆盖 API policy refs 透传、提交期证据校验和 PostgreSQL JSONB round-trip。
- 36 个 adapter 定向测试中新增 workload/evaluator mismatch、缺失引用和授权失败零 provider 调用/零 Run transition 断言。
- platform contracts、gateway 和 DolphinScheduler 静态 validator 固定新增合同与 dispatch gate marker。

## Revisit Triggers

- 审批需要 inbox、委派、撤回、SLA 或跨团队检索；
- policy/approval 查询或保留规模证明 JSONB 引用和 Artifact 检索不足；
- 需要跨平台可验证的签名授权凭证或外部 policy engine federation；
- provider 支持 OIDC/workload federation，需要替换 token profile；
- 新执行 adapter 需要不同 action、obligation 或审批职责分离模型。
