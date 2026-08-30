# ADR-301: Agent Task Execution Projection and Tool-Call Evidence Boundary

状态：已采纳，provider-neutral execution projection 已实现；真实模型/tool provider 和 Temporal worker 未完成  
日期：2026-08-25  
决策关联：ADR-297、ADR-300

## 背景

ADR-300 只生成 immutable `AgentTaskGraph`。执行器还需要推进 step 状态、绑定工具调用、
接收 artifact 和处理外部副作用的不确定结果。如果这些状态直接改写 graph，plan hash 会
随着运行变化；如果每个 provider 自己管理 tool-call identity，又会破坏重放和审计关联。

## 决策

新增 `data_agent.agentops_task_execution`：

- `AgentTaskExecutionState.graph` 永远保留 ADR-300 编译出的 immutable plan；运行中的
  `AgentTaskStep` 放在同序的 `step_states` projection。plan 的 `graph_sha256` 不随状态推进
  变化，projection 和 tool calls 由 `state_sha256` 封存。
- `start_step()` 只允许 pending step 在所有依赖 succeeded 后进入 running；因此 coordinator
  完成前，planner/MMFE/GWM 等 specialist 不能被执行器提前启动。
- `bind_tool_call()` 用 UUID5(`run_id`, `step_id`, `idempotency_key`) 生成稳定 tool-call ID。
  重投递同一 immutable 内容返回原状态；同一 key 改变 tool、capability、policy、subject 或
  input artifact 会拒绝。
- `settle_tool_call()` 明确区分 requested/running/reconciling/succeeded/failed。外部写入
  进入 reconciliation 必须携带 external receipt artifact；成功必须携带 output artifact。
- `complete_step()` 只有在该 step 的所有 tool calls succeeded 后才允许写入 output artifacts。
- `AgentTaskExecutionState` 对 `step_states` 与 graph 逐项比较 tenant、run、step、agent、role、
  sequence 和 dependency 字段；这些 plan 字段即使重新计算 projection hash 也不能被运行态改写。
  该模块不调用模型、provider、数据库或 scheduler；Temporal 只负责持久化/恢复这些返回状态。

## 验证

`data_agent/test_agentops_task_execution.py` 的 4 个测试覆盖：

- DAG 依赖门禁、step/state hash 推进、immutable graph hash 保持和 projection plan-field drift 拒绝；
- tool-call stable ID、requested/running replay、output artifact 门禁和 step completion；
- external-write unknown/reconcile receipt 门禁，reconciling step 不得伪装成功。

AgentOps/Temporal/task-graph/execution scoped tests 共 35 个通过。

## 未完成与下一步

本 ADR 不代表真实工具调用、Capability/Policy admission、Artifact 持久化、Temporal activity
retry、HITL、online verdict、replan、shadow/canary 或生产 worker 已完成。ADR-302 已将
immutable graph 绑定到 Temporal workflow input；下一步是让 workflow/activity 持久化该
projection，由 activity 返回 typed tool/evidence receipt，GDA control plane 再记录
`AgentRun`/`ToolCall`/`Artifact` 投影。
