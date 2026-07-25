# ADR-026：以不可变质量证据裁决 PlatformRun 成功

**Status**: Accepted

**Date**: 2026-07-25

**Decision owners**: Platform Architecture, DataOps, Data Platform, Governance, Security

**Related decisions**: ADR-020、ADR-022、ADR-023、ADR-024、ADR-025

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

平台合同已经声明 provider 的 `SUCCESS` 只是 attempt observation，PlatformRun 成功必须由平台裁决。但原有通用 `transition_platform_run(...)` 仍可直接写入 `succeeded`，也没有统一的 QualityResult 合同和数据库证据门。这使文字边界与实际写权限不一致：知道 Run UUID、state version 和 workload actor 的调用方仍可能绕过输出、质量和血缘核验。

AR-1 当前更需要封闭这个 authority gap，而不是先增加一个常驻 consumer CLI。consumer 只解决投递；若终局函数本身可绕过，它会更可靠地传播错误裁决。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 由 adapter 看见 provider success 后直接 transition | 实现最少 | provider 成为事实上的终局权威，没有产品证据闭环 | 拒绝 |
| B. 仅在 HTTP handler 校验质量 JSON | 接入快 | 直接数据库调用可绕过，证据没有稳定身份与不可变历史 | 拒绝 |
| C. 不可变 QualityResult + 数据库 evidence gate | 终局权限与合同一致，可审计、幂等并可独立验证 | 增加一张证据表和专用终局函数 | **选择** |

## Decision

### 1. QualityResult 是不可变裁决证据

migration `096_platform_success_verdict.sql` 新增 tenant-scoped、FORCE RLS 的 `gda_control.quality_result`。每条结果绑定 Run、目标 ResourceVersion、规则版本、`passed/failed` verdict、非空 metrics、evidence Artifact、evaluator workload、评估时间和内容 fingerprint。

gateway role 只有 `SELECT/INSERT`，没有 `UPDATE/DELETE`。表级 trigger 进一步拒绝变更；Python 合同重算 fingerprint 并拒绝不一致 payload。质量 evidence Artifact 必须与同一 Run 和 ResourceVersion 关联，并由该 evaluator 创建。

### 2. success evidence 精确绑定四类事实

`RunSuccessEvidence` 固定以下 UUID：

- DolphinScheduler success FrameworkAttemptObservation；
- output Artifact；
- passed QualityResult；
- input-to-output LineageEvent。

`evidence_sha256` 对上述 UUID、tenant 和 Run 做 canonical JSON SHA-256。数据库函数按同一字节合同重算摘要，不能用一串格式正确但内容不匹配的 hash 替代绑定。

### 3. 数据库拥有成功终局门

公共 `transition_platform_run(...)` 明确拒绝 `succeeded`。原 transition 实现改名为私有 `apply_platform_run_transition(...)`，撤销 gateway 与 PUBLIC 的执行权；只有 SECURITY DEFINER 的 `finalize_platform_run_success(...)` 可以调用私有 primitive 写入成功。

finalizer 在同一行锁/CAS 事务中验证：

1. tenant context 和 actor 必须与 Run 的 workload SubjectContext 完全一致；
2. Run 当前必须是 `running` 或 `reconciling`；
3. observation 必须属于同一 Run、framework 为 DolphinScheduler、state 为 `success`；
4. output Artifact 必须属于同一 Run，且内容 SHA-256 与目标 ResourceVersion 完全一致；
5. QualityResult 必须为 `passed`、绑定该输出版本、晚于或等于输出，并由不同于 Run actor 的 workload 独立评估；
6. quality evidence Artifact 必须绑定同一 Run/版本并由 evaluator 创建；
7. LineageEvent 必须绑定同一 Definition、输出 Artifact 和目标版本，source 必须来自该 Run 的 immutable input binding。

相同 actor、reason 和完整 evidence details 的成功重放返回既有 state version。已成功 Run 上的不同 terminal verdict 作为冲突拒绝。

### 4. API 只接受 workload identity

新增 `POST /api/platform/v1/quality-results` 和 `POST /api/platform/v1/runs/{run_id}/finalize-success`。tenant 和 actor 仍从认证 principal 派生；客户端不能覆盖。通用 transition API 即使收到 `succeeded` 也会在 gateway 和数据库两层 fail closed。

### 5. 部署边界不变

本决策只完成合同、数据库 authority、gateway/API 和合成 golden slice。它没有部署常驻 outbox worker、真实 provider callback、OIDC/IAM、独立 DolphinScheduler metadata PostgreSQL，也没有跑通真实地类图斑 staging 数据链，因此不构成 AR-1 或生产退出门。

## Consequences

正面影响：

- provider success 不再有任何通用写路径可直接升级为 PlatformRun success；
- 输出内容、质量 verdict、质量 evidence 和血缘在一个数据库事务内共同裁决；
- 成功重放具备确定的幂等语义，审计事件保存精确证据集合；
- 不引入第二个 scheduler、queue、quality service 或 Run authority。

限制与缓解：

- 当前只支持 DolphinScheduler `success` observation；新增 provider 必须先定义等价 observation profile 和 conformance test；
- 独立 evaluator 目前按 workload subject 分离，生产还需要 IAM principal、credential 和职责分离策略证明；
- `failed/cancelled/timed_out` 仍走通用状态机，后续应按风险分别定义终局 evidence profile，不能假设本 ADR 已覆盖所有终态。

## Verification

- 合同、gateway、HTTP 与 crosswalk 定向测试覆盖 fingerprint、workload identity、route 和 golden fixture；
- 真实 PostgreSQL 16 测试覆盖 QualityResult 最小权限、私有 transition 不可执行、通用 success 拒绝、输出 hash、failed quality、缺失 lineage、篡改 evidence fingerprint 和独立 evaluator 拒绝；
- 有效证据链从 `running` 进入 `succeeded`，完全相同的 replay 返回同一 state version；
- migration、contract、crosswalk、gateway 和 DolphinScheduler 静态 validator 继续作为 CI 门禁。

## Revisit Triggers

- 需要为 failed、cancelled 或 timed_out 建立对称的 evidence-gated terminal verdict；
- Temporal、Spark、Flink 或 ArcPy 成为可裁决 provider，需要扩展 observation profile；
- 质量评估发生在流式窗口、多个规则集或多方签名场景，需要组合 verdict 合同；
- 实测 finalization 写锁或 evidence join 达到已记录的性能瓶颈。
