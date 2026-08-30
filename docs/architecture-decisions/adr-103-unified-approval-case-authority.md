# ADR-103: Unified ApprovalCase Authority

**Status**: Accepted  
**Date**: 2026-08-02  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2 / AR-3

## Context

平台原有 `ApprovalRecord` 精确绑定 `PlatformRun + PolicyDecision artifact`，适合执行授权，但不能代表
schema drift、产品发布、数据申请、敏感操作或模型变更等跨领域审批。迁移 102 的 breaking schema drift
只能保存一个格式正确的 ApprovalCase ResourceURN；如果没有真实 authority，任意字符串都可能被当成
审批事实，职责分离、有效期、目标绑定和审计事件无法由平台强制执行。

把聊天 HITL、前端待办状态或业务表各自的 approval 字段提升为权威，会产生多个审批写源，也无法在
LLM disabled、worker 重启和租户隔离条件下稳定重放。

## Decision

### Separate Generic Authority

保留 Run 专用 `ApprovalRecord`，新增通用 `ApprovalCase`，两者不互相冒充。每个 case：

- 自身是 `gda://{tenant}/approval_case/{id}` Resource，由 `gda_control` 持有 authority；
- 不可变绑定一个 `target_resource_urn + target_fingerprint + action`；
- 保存 typed requester、理由、结构化 context、requested/expires 时间；
- 以 `pending/state_version=0` 创建，并且只允许一次 `approved/rejected/cancelled` 终态决定；
- approved/rejected 必须由独立 human approver 在 expiry 前决定，requester 不能自批。

`gda_control.approval_case` 保存 current projection，`approval_case_event` 保存 append-only 初始化和决定事件。
创建 case 与其 Resource projection 在同一事务中完成；同一 immutable request 重放幂等，即使 case 已决定
也返回现有终态。决定只能通过 `transition_approval_case(...)` 做 state-version CAS；gateway role 没有
base-table UPDATE、event INSERT 或 DELETE 权限。

### Authenticated REST Boundary

Platform Gateway 增加 4 个 `/api/platform/v1` 操作：

- `POST /approval-cases`
- `GET /approval-cases/{case_id}`
- `GET /approval-cases/{case_id}/events`
- `POST /approval-cases/{case_id}/decision`

创建 API 只接收 case ID、target、fingerprint、action、reason/context 和时间边界；tenant 与 requester 从
认证 principal 注入。决定 API 同样注入 actor，且 HTTP 边界要求 human identity。稳定错误 envelope 区分
conflict、not-found、forbidden、validation 与 authority unavailable。Resource owner 由非敏感部署参数
`GDA_APPROVAL_CASE_OWNER_REF` 配置，默认 `team:data-platform`。

### First Consumer

迁移 `103_unified_approval_case_authority` 使新 schema-drift lifecycle event 引用真实 ApprovalCase；历史
迁移 102 事实通过 `NOT VALID` 外键保留，不伪造或重写。breaking drift 的 approved/rejected transition
必须匹配同租户 case、exact drift ResourceURN、drift event fingerprint、
`source_schema_drift.reconcile` action、verdict、actor、reason 和有效期。

## Evidence

主 Compose 由专用 migration authority 应用迁移 103 后为 105/105 applied records，catalog/database
fingerprint 均为 `66dc3cafe1c0baccd6d25d0fc046badc3a5149c6c43a2d92e68dd48792225c3e`。
`approval_case` 与 `approval_case_event` 均启用并强制 RLS，应用登录角色已确认可切换到
`gda_control_gateway`；主库 ApprovalCase 和 schema-drift 表保持 0 行。

`.tmp/source-connector-certification/drift-ledger-report.json` 在随机临时 PostgreSQL database 中用真实
repository 验证 approved 和 rejected 两条 breaking-drift 消费链，以及未登记、pending、wrong target、
wrong verdict、requester 自批、expired、stale CAS、直接 UPDATE、最小权限和跨租户负向；case Resource
projection 与 pending/decided 后幂等重放也通过。临时 database 已精确删除。

真实重庆 OSM `v1.2.0` STAC Item 的 object-storage/STAC schema-drift 回归保持 12 项 provider 行为和
8 项清理检查全部通过。Gateway、authority、platform contract、migration 和 drift 聚焦测试 58 项通过，
Ruff 与 diff whitespace 检查通过。

## Consequences

- schema drift 不再消费未经登记的字符串审批引用，通用审批拥有唯一 PostgreSQL 写权威和审计时间线。
- REST、后续 UI/CLI/TUI 和 Agent tool 必须调用同一 authority，不能各自保存审批终态。
- 本 ADR 只完成核心 authority 和首个 schema-drift consumer；完整 Inbox、查询/分派、delegation、通知、
  SLA timeout automation、Temporal 长等待，以及 PlatformRun、产品发布、数据申请和其他敏感操作 consumer
  仍未完成。
- AR-2 与 AR-3 的其余退出门不因 ApprovalCase 核心落地而自动通过。
