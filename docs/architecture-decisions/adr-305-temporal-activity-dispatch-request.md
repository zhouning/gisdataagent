# ADR-305: Typed Temporal Activity Dispatch Request

状态：已采纳，provider-neutral request contract 已实现；真实 Temporal activity dispatch 未完成  
日期：2026-08-26  
决策关联：ADR-301、ADR-303、ADR-304

## 背景

ADR-303 已能把 ToolCall 和 provider receipt 投影到同一条 workflow 路径，但 dispatch
边界仍只接收 `tool_call_id`。provider worker 如果自行补齐 tenant、step、policy、主体或
attempt 信息，重试和 replay 就可能使用与当前 execution projection 不同的输入；MMFE/GWM
specialist 也可能在进入 provider 后失去其 graph step 关联。

## 决策

新增 `TemporalActivityRequest` 和 `derive_temporal_activity_id()`，由
`TemporalTaskGraphWorkflowHarness.build_activity_request()` 从当前 immutable graph 与
execution projection 构造：

- 请求固定 tenant/workflow/run/step/tool-call correlation、tool/capability、policy decision、
  `SubjectContext`、side effect、idempotency key 和 input artifacts；provider 不得从另一个
  topology 或外部上下文补写这些字段。
- `activity_id` 使用 `run_id + tool_call_id + attempt_no` 的 UUID5 稳定派生。同一 attempt
  重放得到同一个 identity；attempt 变化必须产生新 identity，并受 workflow retry policy
  的 `max_attempts` 限制。
- 只有 `REQUESTED` 或 `RUNNING` 的 ToolCall 可生成新的 dispatch request。`RECONCILING`、
  `SUCCEEDED`、`FAILED`、`DENIED` 等状态必须先通过 receipt/reconciliation 或显式终态处理，
  不能偷偷创建另一条 provider side effect。
- request SHA-256 覆盖完整 dispatch 输入。它是 provider invocation 的输入证据，不是
  provider 已执行证明；执行结果仍必须返回 `TemporalActivityEvidence`，由统一控制面记录
  output artifact、external receipt 或 unknown reconciliation。

MMFE 和 GWM 仍是普通 specialist step：请求可以携带各自 tool/capability，但不能取得
数据真值、workflow 调度或质量最终裁决权。它们与 data engineer 的 dispatch 共享同一合同。

## 验证

`data_agent/test_agentops_temporal_workflow.py` 新增覆盖：

- 同一 ToolCall attempt request 重放稳定、attempt 变化产生不同 activity ID，并拒绝超出
  retry policy 的 attempt；
- request 字段从 ToolCall projection 绑定，篡改 activity identity fail closed；
- `RECONCILING` 和 `SUCCEEDED` ToolCall 禁止新的 dispatch；
- MMFE/GWM request 保留各自 graph step 和 tool ref；
- checkpoint activity evidence 必须对应 execution 中已存在 ToolCall；
- 直接调用 `TemporalIntegrationHarness.restore()` 时，history/state version 不一致被拒绝。

AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 54 个通过；Ruff 和
compileall 通过。

## 边界与后续

本 ADR 不实现 Temporal SDK activity worker、provider invocation、真实 retry、worker
crash/restart、history replay、HITL、online verdict、incident/rollback 或生产 HA/RPO/RTO。
下一步是在 pinned SDK/server sandbox 中把 request 映射到真实 activity input，注入 worker
termination 和提交后不确定结果，并核对 request/evidence/checkpoint 的一致性。
