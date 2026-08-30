# ADR-338：AgentOps Temporal ApprovalCase expiry automatic convergence

## 状态

已采纳；Docker Desktop Temporal sandbox + 临时 PostgreSQL 的 bounded expiry rehearsal
已通过。生产审批 SLA、HA/DR 和运营规模仍未宣称。

## 背景

ADR-337 已把高风险 TaskGraph step 绑定到 PostgreSQL `ApprovalCaseAuthority`，并证明人工
批准/拒绝路径可以恢复或拒绝 provider activity。剩余缺口是 pending case 在没有人工决定时
不能只停留在 Temporal timer：必须由同一审批权威原子地判断到期、关闭 assignment，并阻止
任何 specialist/provider dispatch。

## 决策

- 新增 migration `243_agentops_approval_expiry_authority.sql` 和
  `ApprovalCaseAuthority.expire(...)`。函数在 PostgreSQL 事务内以 `FOR UPDATE` 锁定
  `ApprovalCase`，使用 `clock_timestamp()` 判断 `expires_at`，只允许 `pending -> cancelled`；
  人工批准/拒绝与 expiry 共享同一行锁解决竞争。
- expiry 使用独立、确定性的 Temporal activity identity，并复用现有 assignment close
  trigger；不复制 ApprovalCase 状态机。相同 expiry evidence 的重放返回同一终态。
- `TemporalTaskGraphWorkflow` 对 pending ApprovalCase 使用 durable timer。到期后先调用
  `gda.agentops.approval.expire`，只有拿到 PostgreSQL 权威 `cancelled` 结果才调用
  `cancel_after_review`；authority 不可用时 fail closed，不伪造终态，也不调度 specialist。
- 合同允许 expiry 的 `decided_at >= expires_at`，但人工 `approved/rejected` 仍必须发生在
  expiry 之前；expiry result 固化 case、binding、actor、reason 和 evidence hash。

## 证据

- expiry/authority/workflow focused 回归已通过；本切片验证了 expiry contract、hash-bound
  cancellation evidence、terminal race、timeout cancellation 不产生 provider schedule，及
  migration 的 atomic lock/CAS/RLS/expiry marker 约束。
- 真实 rehearsal：
  `docs/reports/agentops_temporal_step_hitl_expiry_rehearsal_2026-08-28.json`。
- 原始 Temporal history：
  `docs/reports/agentops_temporal_step_hitl_expiry_history_2026-08-28.json`。
- Temporal server `1.29.7`、Python SDK `1.32.0`；pending case 到期后收敛为
  `cancelled`，assignment 事件为 `assigned -> closed`、version `2`，specialist/provider
  activity 调用数为 `0`，2 个 activity schedule、22 个 history events，Replayer passed。
  报告标记 `production_readiness_claimed=false`。

报告 canonical SHA-256：
`264122758a7a44178e82b6621887feb5a43eb314629ae6f195db414bd3e363ec`。

原始 history SHA-256：
`cf92121f0f0825355fdecf2de4bfc1a4787463fa6088cf4ad331c09f9598a195`。

## 影响和未关闭边界

超时不再依赖 Web 进程存活，审批与执行之间形成可重放、可审计的自动收敛边界；代价是
每个 pending case 增加一次 expiry activity 和数据库权威读取。通知 SLA、升级/批量审批、
生产 Temporal/ApprovalCase HA、OIDC/secret rotation、NetworkPolicy enforcement、
backup/restore、RPO/RTO、shadow/canary、online verdict 和 incident rollback 仍未完成。
