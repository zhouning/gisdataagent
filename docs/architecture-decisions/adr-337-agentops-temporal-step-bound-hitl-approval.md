# ADR-337：AgentOps Temporal step-bound HITL approval

## 状态

已采纳；Docker Desktop Temporal sandbox + 临时 PostgreSQL 的 bounded rehearsal 已通过，
并补齐现有 ApprovalCase assignment/principal authority 的真实绑定验证。
生产就绪、HA/DR 和审批运营规模仍未宣称。

## 背景

ADR-336 关闭了多 specialist TaskGraph 的 Temporal 执行、显式 retry、ToolCall/activity
证据回写和 history replay，但高风险 `CONTROL_WRITE` / `EXTERNAL_WRITE` 仍可直接进入
provider activity。已有的 `ApprovalCase` 和 `ApprovalCaseAuthority` 是平台统一审批权威；
问题是 workflow 尚未证明一个人工批准究竟对应哪一个 graph、step、ToolCall、policy 和
side-effect，也没有证明旧 signal 或 pending case 能阻止 provider dispatch。

## 决策

- 新增 hash-bound `TemporalStepApprovalBinding`，固定 tenant、workflow/run、graph SHA、
  step/agent/role、ToolCall identity、tool/capability、policy decision、SubjectContext、
  side-effect、idempotency key、ApprovalCase ref、owner/scope 和期望 ApprovalCase state
  version。`CONTROL_WRITE` / `EXTERNAL_WRITE` 必须有且只能有一个 binding；MMFE/GWM 仍不能
  获得 control-plane write 权威。
- binding 生成 deterministic `ApprovalCase` identity。workflow 通过
  `gda.agentops.approval.create` activity 幂等提交 pending case；activity 只调用现有
  `ApprovalCaseAuthority`，不新增第二套审批状态机。
- workflow 为每个高风险 step 暴露 `gda_agentops_pending_approval` query 和
  `gda_agentops_step_approval` signal。query 返回 binding、pending case 和 workflow state
  version；signal 只进入内存 inbox，不能直接恢复执行。
- `gda.agentops.approval.verify` 是只读 authority verification activity。它重新从
  PostgreSQL 加载 `ApprovalCase`，逐字段比对 binding、case ref/target/fingerprint/action/
  requester/context、case state version、过期时间、terminal verdict、human approver 和
  decision reason；同时重新读取既有 assignment projection，要求 assignment 已由同一
  `ApprovalCase` 决策关闭、最终 scope 与 binding 的 `approver_scope_ref` 相同、关闭 actor
  和时间与 terminal verdict 一致。任何 mismatch、stale signal、跨租户/跨 graph/跨 step、
  pending、未分配/转派不一致或权威不可用都 fail closed。
- 只有 verification accepted 后，workflow 才把 run 从 `WAITING_REVIEW` 转为 `RUNNING` 并
  schedule provider activity。reject 将 ToolCall 标为 `DENIED`、step 标为 `FAILED`，不产生
  provider schedule。重复 signal id 必须内容完全相同，否则拒绝。

## 取舍

| 选项 | 结果 |
|---|---|
| 在 workflow 内直接信任 approve signal | 路径短，但无法验证审批权威、scope 和 graph/ToolCall 绑定，拒绝 |
| 在 Temporal 内复制 ApprovalCase 状态机 | 可局部方便，但产生第二套审批真值和漂移风险，拒绝 |
| `ApprovalCaseAuthority` + step-bound binding + read-only verification activity | 增加一次 authority read 和两个活动，但保留 PostgreSQL 为唯一审批权威，采用 |

## 证据

- focused HITL/TaskGraph/Temporal 回归：`15 passed`（本 ADR 定向合同）；完整 Temporal
  专项回归：`136 passed, 5 skipped`；完整 AgentOps 集合：`181 passed, 5 skipped`；Ruff、
  compileall 通过。
- 真实 rehearsal：
  `docs/reports/agentops_temporal_step_hitl_assignment_rehearsal_2026-08-28.json`。
- 原始 Temporal history：
  `docs/reports/agentops_temporal_step_hitl_assignment_history_2026-08-28.json`。
- Temporal server `1.29.7`、Python SDK `1.32.0`；临时 PostgreSQL 执行 migration
  `092/094/102/103/120/121`，登记 team/human principal 和 membership；创建 1 个 pending
  case，先 assign standby 再 reassign 到 binding scope。旧 assignee 的直接决定被 PostgreSQL
  authority 拒绝；pending state 0 时的 approve signal 被拒绝，匹配 scope 的人工批准后 fresh
  signal 才恢复；最终 assignment 为 `closed`，事件链为 `assigned -> reassigned -> closed`，
  10 次显式 activity schedule/completion，history 67 events，Replayer passed。报告中
  `production_readiness_claimed=false`。
- 本次 rehearsal 报告 canonical SHA-256（排除该字段自身后计算）：
  `0808651f86d1b4f19606d05d9ac95f08344b5138f214aee8e6f9a3841e8a52ca`。
- 原始 Temporal history SHA-256：
  `cc459ea7505039c5b41ca5bb38664812d1fdc19a03a478ab09ac5dc4faf7b097`。

本次 rehearsal 还在第一个 worker 退出、第二个全新 worker 接管后验证 pending query 完全
恢复（`worker_restart_pending_state_preserved=true`），再执行 assignment、审批和 provider
activity；它证明的是 Temporal history 驱动的 bounded restart/replay，不是生产 worker HA。

## 影响和未关闭边界

正向影响是高风险写操作有可追溯的人工决策边界，审批对象可直接定位到 graph/step/ToolCall
和 provider activity，Temporal replay 不依赖实时数据库状态之外的隐式信任。代价是每个高风险
step 增加 case 创建、等待和 authority verification 的延迟；通知 SLA、审批超时自动取消、
批量审批、跨区域数据库可用性和运营审计仍由 ApprovalCase 域继续建设。

本 ADR 不代表生产 Temporal HA/DR、Kubernetes NetworkPolicy enforcement、OIDC/secret
rotation、backup/restore、RPO/RTO、shadow/canary、online verdict、incident rollback 或
真实 MMFE/GWM provider 已完成。`production_readiness_claimed` 保持 `false`。
