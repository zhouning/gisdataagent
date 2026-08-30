# ADR-304: AgentOps Workflow Checkpoint and Replay Contract

状态：已采纳，provider-neutral checkpoint/replay 已实现；真实 Temporal crash/restart/replay 未完成  
日期：2026-08-25  
决策关联：ADR-298、ADR-301、ADR-303

## 背景

ADR-303 已把 task graph、ToolCall 和 activity receipt 组合成 workflow projection，但其
状态仍只存在于进程内。若重启后只恢复 AgentRun 或只恢复 Temporal history，step projection、
unknown reconciliation 和 signal 去重都可能分叉，无法证明恢复后仍沿着同一 graph 继续执行。

## 决策

- `TemporalTaskGraphWorkflowCheckpoint` 封存 `TemporalWorkflowInput`、当前 `AgentRun`、完整
  transition history、activity evidence、已应用 signal、`AgentTaskExecutionState` 和
  `checkpoint_sha256`。
- checkpoint validator 强制校验 history 从 sequence 0 连续到当前 `run.state_version`，
  最新 transition 与 Run 状态一致，所有 signal/activity 与 workflow/tenant/run 关联，且
  execution graph 与 workflow input 的 immutable graph 完全一致。
- `TemporalIntegrationHarness.restore()` 在恢复 workflow 的同时重建 signal idempotency
  index；相同 signal 重放返回原 snapshot，内容变化则拒绝。恢复后的 harness 可以继续推进
  graph，step dependency gate、ToolCall 状态和 graph hash 保持不变。
- checkpoint 是 provider-neutral durable-state contract，不是数据库存储实现；生产环境
  仍需由 Temporal history/continue-as-new、GDA evidence store 或经批准的 checkpoint store
  提供真实持久化和权限边界。

## 验证

`data_agent/test_agentops_temporal_workflow.py` 新增：

- checkpoint round-trip 后阻塞错误依赖并继续执行；
- 恢复 signal idempotency index，重复 signal 幂等、内容变化拒绝；
- Run 与最新 history 不一致的 checkpoint fail closed。

AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 49 个通过。该证据仍不代表
真实 Temporal server、worker crash/restart、history replay、HA、OIDC、RPO/RTO 或生产
checkpoint store。

## 后续

在 pinned Temporal SDK/server sandbox 中注入 worker termination、网络不确定和 history replay，
验证 checkpoint/evidence 与 provider operation receipt 的一致性；再进行 production worker
和恢复目标评审。
