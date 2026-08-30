# ADR-308: Temporal AgentOps Worker Registration Contract

状态：已采纳，provider-neutral worker registration/factory 已实现；真实 Temporal worker 未完成  
日期：2026-08-26  
决策关联：ADR-299、ADR-307

## 背景

ADR-307 已冻结 activity handler，但 worker 仍缺少注册边界。仅把 Temporal server 副本调到
1 不能证明 worker 注册了正确的 namespace、task queue、workflow/activity 类型，也不能证明
当前 AgentSpec/deployment revision 与 worker identity 一致。

## 决策

新增 `TemporalWorkerRegistration` 和 `TemporalioWorkerFactory`：

- registration 固定 tenant、namespace、task queue、worker identity、workflow type、activity
  type 集合、AgentSpec hash、DeploymentRevision hash 和 activity/workflow 并发上限；完整
  内容由 `registration_sha256` 封存。
- activity type 规范化为排序且唯一的 provider 名称；workflow/activity 定义缺失、namespace
  与 client 不一致或注册类型漂移时，factory 在构造 SDK Worker 前 fail closed。
- 显式传入 `worker_class` 可用于 fake-provider conformance；未显式传入时才 lazy-import
  `temporalio.worker.Worker`。缺失 SDK 不影响 lite mode，但不能伪装成 worker 已启动。
- factory 只负责构造 Worker，不执行 workflow、工具或数据写入。Temporal runtime 仍负责
  history、retry、heartbeat、cancellation 和 worker lifecycle；activity action 通过
  ADR-307 handler 进入。

MMFE/GWM worker action 与其他 specialist 使用同一注册和 handler 边界；registration 不授予
specialist 调度权、数据真值或质量最终裁决权。

## 验证

`data_agent/test_agentops_temporal_worker.py` 覆盖 registration hash、namespace/task queue/
workflow/activity/并发绑定、定义缺失、namespace drift 和缺失 `temporalio` fail-closed。

AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 64 个通过；完整 AgentOps
集合 84 个通过；Ruff/compileall 通过。

## 边界与后续

本 ADR 不证明 Temporal SDK/server、worker image、OIDC/workload identity、真实 worker
registration、activity retry/heartbeat/cancellation、termination/restart、history replay、
HA 或生产 RPO/RTO。下一步是在 pinned SDK/server sandbox 中由 factory 构造真实 Worker，注册
workflow/activity，完成一次 start -> activity -> receipt -> replay 演练。
