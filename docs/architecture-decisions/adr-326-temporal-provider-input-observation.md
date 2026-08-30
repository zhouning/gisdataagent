# ADR-326: Temporal Provider Input Observation

状态：已采纳，SDK bridge 合同已实现；真实 sandbox 对账尚未完成  
日期：2026-08-26  
决策关联：ADR-299、ADR-311、ADR-325

## 背景

ADR-325 已经规定 `already_exists` 必须核对既有 workflow input，`unknown` 不能自动重试。
此前只有调用方手工传入 fingerprint 的 provider-neutral 测试，SDK bridge 没有读取 Temporal
history 的实现，因而无法把重复启动或提交后传输不确定收敛到统一 reconciliation evidence。

## 决策

- 新增 `gda.temporal_workflow_input_observation.v1` typed observation，绑定 tenant、namespace、
  workflow、provider run、provider receipt、observed input fingerprint 和 observation fingerprint。
- `TemporalioProviderClient.observe_workflow_input()` 只执行 `get_workflow_handle()` +
  `fetch_history()`，读取首个 `WORKFLOW_EXECUTION_STARTED` event 的 payload，并用连接的
  Temporal `DataConverter` 解码后重建 `TemporalWorkflowStartRequest`。它不启动 workflow、不发
  signal、不重试。
- `TemporalWorkflowAdapter.reconcile_start_async()` 对 `already_exists` 要求 provider run 和
  matching input；对 `unknown` 尝试读取 workflow history，若观察到同一 input 和实际 run，则
  生成 `already_exists_matched`，否则只生成 `unknown_pending`。观察结果缺字段、tenant/namespace/
  workflow/run 不一致或 input fingerprint 漂移均 fail closed。
- provider 无法读取 history 时，只有 `unknown` 可以保留 pending；`already_exists` 仍直接失败，
  不能用“可能已存在”替代证据。

## 验证

SDK bridge conformance 使用真实 `temporalio==1.32.0` converter 对编码的 start payload 构造
history fake，验证 `unknown -> history input observation -> already_exists_matched`，并保留既有
start/signal/async/fail-closed 测试。

2026-08-26 已在 disposable Kubernetes `gda-agentops-sandbox` 实际执行
`scripts/rehearse_agentops_temporal_start_reconciliation.py`：

- 同一 workflow ID 的第二次 start 收到真实 `WorkflowAlreadyStartedError`，provider status 为
  `already_exists`；读取真实 `WORKFLOW_EXECUTION_STARTED` history 的首个 start event 后，input
  fingerprint 匹配，reconciliation 为 `already_exists_matched`。该 workflow 最终完整 history 为
  10 个事件。
- 第二个 workflow 的第一次 start 由注入的 client 在 Temporal 已接受后抛出传输异常，provider
  status 为 `unknown`；不重试，读取真实 history 的首个 start event 后观察到 provider run 与
  canonical input，reconciliation 收敛为 `already_exists_matched`。该 workflow 最终完整 history
  为 10 个事件。
- 真实版本为 Temporal server `1.29.7`、Python SDK `1.32.0`。报告和两份原始 history：
  [report](../reports/agentops_temporal_start_reconciliation_2026-08-26.json)、
  [duplicate history](../reports/agentops_temporal_start_reconciliation_duplicate_history_2026-08-26.json)、
  [uncertain history](../reports/agentops_temporal_start_reconciliation_uncertain_history_2026-08-26.json)。
  报告 `report_sha256` 为
  `2294036755b273dabf9f066d93facc3d51867131cd6dd1218bade2bfc44359c3`。

本次是真实 provider sandbox evidence，但仍是单副本、短 workflow、单 namespace 的 bounded slice，
不代表 worker termination/restart、HITL、online observation、incident/rollback、HA 或生产 RPO/RTO。

## 未完成与下一步

Temporal server 恢复后，已使用同一 workflow ID 做真实重复 start，读取真实 history 的 run/input，
并注入提交后网络不确定记录 observation/reconciliation receipt。之后才进行 worker
termination/restart、checkpoint/reconciliation projection、HITL、online observation、incident/
rollback 和 HA/RPO/RTO 验收。
