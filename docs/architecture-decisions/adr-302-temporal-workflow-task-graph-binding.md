# ADR-302: Temporal Workflow Task Graph Binding

状态：已采纳，workflow input 已绑定 immutable task graph；Temporal worker 和生产运行时未完成  
日期：2026-08-25  
决策关联：ADR-297、ADR-298、ADR-299、ADR-300、ADR-301

## 背景

ADR-300 将多智能体 topology 编译成确定性的 `AgentTaskGraph`，ADR-301 又把该计划与
运行态 `step_states` 分离。若 Temporal workflow 只接收 `AgentRun` 和 deployment hash，
worker 就可能重新解析 topology，导致 step ID、依赖或 specialist fan-in 在重试和恢复时
分叉。MMFE/GWM 也会因此失去统一的计划边界。

## 决策

- `TemporalWorkflowInput.task_graph` 为必填的 `AgentTaskGraph`，workflow starter 只接受
  已通过 graph 自身 schema 校验的 immutable 计划。
- input validator 强制校验 graph 的 tenant、root `run_id`、`agent_spec_sha256` 和
  `deployment_revision_sha256` 分别与 workflow input/identity 一致；任何跨租户、跨 run、
  跨 spec 或跨 deployment 的 graph 都 fail closed。
- `input_sha256` 覆盖完整 task graph。workflow identity 仍只由既定的租户、isolation、
  namespace、workflow type、spec/deployment hash 和 idempotency key 派生，因此 graph drift
  不会生成第二个 workflow ID；同一 ID 复用时必须发现 input fingerprint 冲突并进入对账/拒绝。
- Temporal adapter 的 canonical start payload 原样携带 task graph；worker 不再解析
  `AgentTopology` 或自行生成 step identity。运行态只能写 ADR-301 的 `step_states`、
  ToolCall 和 evidence projection，不能修改 graph。
- 本 ADR 不新增 temporalio 依赖、不提供 provider 查询或生产 worker；真实 provider 对
  `already_exists` 的 input 对账仍需 sandbox/production adapter evidence。

## 验证

`data_agent/test_agentops_contracts.py` 新增：

- graph tenant、run、spec、deployment 四类有效但不匹配输入均被拒绝；
- graph 内容变化会改变 `input_sha256`，但保持 workflow ID 不变，旧 workflow 不接受新的
  input evidence。

`data_agent/test_agentops_temporal_adapter.py` 验证 canonical payload 含完整 graph hash
和 coordinator。AgentOps/Temporal/task-graph/execution scoped tests 共 42 个通过；这些
测试仍是 provider-neutral 证据，不代表 Temporal server、worker、crash/replay、HA、OIDC
或生产 rollout 已完成。

## 后续

在可用的 pinned SDK/server sandbox 中，使用真实 `already_exists`、signal 和 unknown
transport receipt 验证 payload fingerprint 对账；随后把 ADR-303 workflow projection 接入
workflow/activity，并补 crash/restart/replay、HITL、replan、shadow/canary 和生产 RPO/RTO
证据。
