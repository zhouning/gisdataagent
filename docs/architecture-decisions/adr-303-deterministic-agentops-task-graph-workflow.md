# ADR-303: Deterministic AgentOps Task-Graph Workflow Projection

状态：已采纳，provider-neutral workflow harness 已实现；真实 Temporal worker 和生产运行时未完成  
日期：2026-08-25  
决策关联：ADR-300、ADR-301、ADR-302

## 背景

ADR-302 已把 immutable `AgentTaskGraph` 绑定到 Temporal workflow input，但仍缺少一个把
step、ToolCall、activity receipt 和 AgentRun 状态放在同一条可重放路径上的实现。若这层
逻辑继续留在未来 provider worker 内，测试环境和 Temporal 环境可能各自解释依赖、重试和
终态，导致 evidence 分叉。

## 决策

新增 `data_agent.agentops_temporal_workflow`，提供 deterministic
`TemporalTaskGraphWorkflowHarness`：

- `start_step()` 只允许 graph 依赖全部 succeeded 的 step 启动，并把 accepted/planning
  的 AgentRun 推进到对应运行态；同一 running/reconciling/succeeded dispatch 重放幂等。
- `bind_tool_call()` 复用 ADR-301 stable ToolCall identity；`dispatch_tool_call()` 只记录
  provider dispatch 边界，不执行模型或 provider。
- `record_activity()` 必须找到已绑定的 ToolCall，校验 policy decision 和当前状态；成功、
  失败、unknown 分别投影为 succeeded、failed、reconciling。unknown 不自动重试，后续带
  external receipt 的成功 receipt 才能收敛回 running。
- `complete_step()` 只能在该 step 的 ToolCall 全部 succeeded 后完成；只有所有 graph steps
  成功才把 AgentRun 推进到 succeeded。`fail_step()` 是显式的 failed terminal projection。
- workflow snapshot 同时保留 Temporal harness history 与 execution projection，graph hash
  始终不变；provider 可以替换 harness，但不能重新解析 topology 或另建 step identity。

## 验证

`data_agent/test_agentops_temporal_workflow.py` 的 4 个测试覆盖成功 receipt/重放、unknown
reconciliation、DAG fan-in terminal gate 和 failed activity projection。AgentOps/Temporal/
task-graph/execution/workflow scoped tests 共 46 个通过。

## 边界

该 harness 不连接 Temporal SDK、server、worker、模型、工具、Artifact store 或数据库，也不
证明 activity retry、HITL、replan、crash/restart/replay、HA、OIDC、online verdict 或生产
RPO/RTO。下一步是在 pinned SDK/server sandbox 中将同一 projection 接入真实 workflow/activity
并验证 worker 重启和 provider unknown receipt 对账。
