# ADR-306: Temporal Activity Provider Adapter and Evidence Bridge

状态：已采纳，provider-neutral activity adapter 已实现；真实 Temporal activity worker 未完成  
日期：2026-08-26  
决策关联：ADR-303、ADR-305

## 背景

ADR-305 已冻结 activity dispatch request，但 provider 返回结果仍需要一个统一入口，才能
把 activity identity、attempt、request fingerprint 和副作用证据接回 `ToolCall` projection。
如果每个 worker 自己组装 `TemporalActivityEvidence`，同一个 provider receipt 可能出现不同
的 idempotency key、policy 引用或 artifact 绑定。

## 决策

新增 `TemporalProviderActivityResult`、`TemporalActivityAdapter` 以及 workflow harness 的
`dispatch_activity()` / `dispatch_activity_async()`：

- provider 必须回显 tenant/workflow/run/step/ToolCall/activity/attempt 和
  `request_sha256`，并提供 `provider_receipt_ref`；activity identity 必须符合 ADR-305 的
  UUID5 派生规则。
- 成功结果必须带 output artifact；unknown 结果必须带 provider operation ref；失败结果必须
  带 failure type。adapter 还根据 request 的 side effect 检查 external receipt，读操作不能
  携带外部写回执，外部写成功不能缺回执 artifact。
- adapter 生成稳定 evidence idempotency key：
  `ToolCall.idempotency_key + activity attempt`。provider receipt/operation ref 进入
  `TemporalActivityEvidence`，然后由 workflow harness 统一做 ToolCall 状态投影和
  reconciliation；provider 不能直接推进 AgentRun。
- 同步入口遇到 awaitable provider 立即关闭 coroutine 并 fail closed；异步入口只等待
  provider result，不创建或嵌套 event loop。

MMFE、GWM、data engineer 使用同一 adapter contract。它们的 request 仍保留 specialist graph
step；adapter 不改变多智能体拓扑，也不授予 specialist 数据真值、调度或质量最终裁决权。

## 验证

`data_agent/test_agentops_temporal_adapter.py` 新增覆盖：

- canonical activity request 透传、provider receipt 转 evidence、workflow projection 接回；
- receipt request fingerprint/identity drift fail closed；
- workflow harness 通过 adapter dispatch 后 ToolCall 进入 succeeded；
- sync/async provider 边界行为。

AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 58 个通过；完整 AgentOps
集合和这些 scoped tests 均无失败，Ruff/compileall 通过。

## 边界与后续

本 ADR 只证明 provider-neutral adapter 和 deterministic fake-provider evidence bridge，
不证明 Temporal SDK activity invocation、worker image、真实 activity retry、worker
termination/restart、history replay、HITL、online verdict、incident/rollback、HA 或生产
RPO/RTO。下一步是在 pinned SDK/server sandbox 中实现 worker activity handler，把真实
provider receipt、unknown outcome 和 restart 后 replay 接入同一 adapter。
