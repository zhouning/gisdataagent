# ADR-310: Typed Temporal Activity Scheduling Plan

状态：已采纳，provider-neutral schedule plan 与 SDK option mapping 已实现；真实 Temporal activity 未完成  
日期：2026-08-26  
决策关联：ADR-305、ADR-306、ADR-308、ADR-309

## 背景

ADR-305 让 `activity_id` 由 `run_id + tool_call_id + attempt_no` 稳定派生。Temporal SDK
的 activity retry 如果仍使用 `maximum_attempts > 1`，同一 schedule 的重放会继续携带
attempt 1 的 request 和 activity ID，物理执行次数与平台 evidence 身份不再一一对应。对
外部写入而言，这会让 receipt、reconciliation 和后续重试无法判断具体是哪一次执行。

## 决策

新增 `TemporalActivitySchedulePlan` 与 `TemporalioActivityScheduleMapper`：

- plan 固定 tenant/workflow/run/step/tool-call/activity/attempt、activity type、task queue identity、
  request hash、schedule-to-close/start-to-close/heartbeat timeout、cancellation type 和
  SDK `maximum_attempts=1`；完整内容由 `schedule_sha256` 封存。
- 平台拥有 retry 编排。只有前一 attempt 有确定 `FAILED` evidence 时，workflow 才能创建
  attempt N+1；新 attempt 必须有新的 request hash 和 activity ID。`UNKNOWN` 先进入
  reconciliation，不能自动生成下一次副作用。
- side-effecting activity 使用等待 cancellation 完成的策略；heartbeat timeout 不得超过
  start-to-close，schedule-to-close 不得短于 start-to-close。非法组合在 plan 构造时拒绝。
- schedule plan 写入 workflow checkpoint，worker restart/history replay 能恢复实际调度
  参数，而不是只恢复 ToolCall 或 receipt。
- SDK bridge 只做参数翻译，并再次拒绝任何非 1 的 `maximum_attempts`。它不执行 provider，
  不把 fake SDK 映射当作真实 Temporal 证据。

## 验证

新增 workflow/provider tests 覆盖：

- attempt 1/2 的 ID、request hash 和 schedule hash 稳定且不同；重复 schedule 幂等；
- SDK retry 强制为 1，activity type、task queue、三个 timeout 和 cancellation strategy
  映射到调用参数；
- 没有前一失败 evidence、已有 `UNKNOWN/RECONCILING`、非法 timeout/cancellation 时 fail closed；
- schedule 纳入 checkpoint，恢复后保持完全相同的 plan。

Temporal scoped suite（`test_agentops_temporal*.py`）共 45 个通过；AgentOps/Temporal/
task-graph/execution scoped tests 共 70 个通过，完整 AgentOps 集合 90 个通过；Ruff、
compileall 和 diff check 通过。

## 后果与边界

优点是平台的 attempt identity、provider receipt 和重试决策保持可追溯，SDK 隐藏 retry
不会绕过 AgentOps evidence 合同。代价是每次重试都需要 workflow history 中新增一个
schedule/request，吞吐和 history retention 需要后续实测。

本 ADR 不证明 Temporal SDK/server、真实 activity worker、heartbeat/cancellation 行为、
worker termination/restart、history replay、HITL、online observation、incident/rollback、
HA 或生产 RPO/RTO。下一步是在 pinned SDK/server sandbox 中完成显式
`start -> schedule(attempt 1) -> activity -> receipt -> replay`，再注入 worker termination
和 transport uncertainty。
