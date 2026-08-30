# ADR-307: Temporal Activity Worker Handler Contract

状态：已采纳，provider-neutral worker handler 已实现；真实 Temporal worker 未完成  
日期：2026-08-26  
决策关联：ADR-305、ADR-306

## 背景

ADR-306 已把 provider receipt 转为 GDA evidence，但真实 Temporal worker 还需要一个稳定的
activity 函数边界：解析序列化 request、调用领域 action、校验结果，再把 receipt 返回给
Temporal。若每个 worker 自己做这些步骤，SDK worker、fake worker 和未来多副本 worker 会有
不同的 request/result 解释。

## 决策

新增 `TemporalActivityWorkerHandler`：

- `handle(payload)` / `handle_async(payload)` 先用 `TemporalActivityRequest` 解析输入；非法
  tenant、identity、attempt 或 request fingerprint 直接 fail closed。
- handler 调用注入的 `TemporalActivityExecutor`。executor 只负责实际 typed action，必须返回
  `TemporalProviderActivityResult`；handler 不替 executor 写数据，也不改变 AgentRun。
- handler 复用 `TemporalActivityAdapter.evidence_from_result()` 校验 result 与 request 的
  run/step/ToolCall/activity/attempt/request hash 关联，以及 output、external receipt、
  unknown/failure 证据规则，然后返回 JSON-safe provider result。
- 同步 handler 遇到 awaitable executor 立即关闭 coroutine 并拒绝阻塞；异步 handler 才等待
  executor。这为真实 `@activity.defn` worker 保留单一 async 边界。

Temporal SDK worker 只需要把 activity payload 传给 handler，再把返回 JSON 作为 activity
result；SDK history、heartbeat、retry 和 cancellation 仍属于 Temporal runtime。MMFE/GWM
specialist 使用同一 handler，不获得调度或数据真值权威。

## 验证

`data_agent/test_agentops_temporalio_provider.py` 新增覆盖：

- request 解析、executor 调用和 JSON 序列化；
- async executor 与同步入口 fail-closed；
- 非法 request 拒绝。

AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 60 个通过；完整 AgentOps
集合 80 个通过；Ruff/compileall 通过。

## 边界与后续

本 ADR 仍不证明 Temporal SDK/server 已连接、worker image 已构建、activity retry/heartbeat/
cancellation、worker termination/restart、history replay、HITL、online verdict、incident/
rollback、HA 或生产 RPO/RTO。下一步是在 pinned SDK/server sandbox 中注册真实
`@activity.defn`/worker，并用该 handler 做一次 start -> activity -> receipt -> replay 演练。
