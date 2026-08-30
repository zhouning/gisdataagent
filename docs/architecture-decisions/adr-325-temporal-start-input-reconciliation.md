# ADR-325: Temporal Start Input Reconciliation

状态：已采纳，provider-neutral reconciliation contract 已实现；真实 Temporal sandbox 对账尚未完成  
日期：2026-08-26  
决策关联：ADR-299、ADR-302、ADR-311

## 背景

Temporal 的 `start_workflow` 可能返回三类结果：首次启动、`already_exists`，以及提交后传输结果不确定的
`unknown`。仅凭 workflow ID 和 provider run ID 不能证明已存在的 workflow 使用了当前 immutable
`TemporalWorkflowInput`。如果把 `already_exists` 直接当作当前请求成功，会把旧 graph、旧 policy 或旧
deployment 的 workflow 误关联到新请求。

## 决策

- 新增 `TemporalWorkflowAdapter.reconcile_start()` 和
  `gda.temporal_start_reconciliation.v1` 证据合同。
- `already_exists` 必须由 provider 提供既有 workflow 的 input fingerprint，并且必须等于当前
  canonical start payload 的 `payload_sha256`；缺失或漂移直接 fail closed。
- `unknown` 只能生成 `unknown_pending` reconciliation evidence，不自动重试、不生成 provider run
  id，也不把它推进为 started。后续必须由独立 provider observation 得到明确终态。
- 首次 `started` 可生成 `started` observation；如果调用方同时提供 input fingerprint，也必须匹配当前
  request。所有结果都绑定 tenant、namespace、workflow、provider receipt、request fingerprint 和
  reconciliation fingerprint。

这只是 GDA 控制面合同。Temporal provider 负责取得既有 workflow 的输入观察；GDA 不把 workflow history
当作唯一审计权威，也不允许 provider 绕过统一 Run/Artifact/evidence 记录。

## 验证

新增 adapter tests 覆盖：`already_exists` 匹配成功、输入指纹漂移拒绝、缺少既有输入证据拒绝，以及
`unknown` 保持 pending 且不产生第二次 start。Ruff、compileall 和完整 AgentOps/Temporal scoped
回归通过：Temporal adapter/provider/workflow `37 passed`，完整 `data_agent/test_agentops*.py`
为 `94 passed`。

## 未完成与下一步

当前只完成 provider-neutral contract 和 fake-provider conformance；没有把它计为真实 Temporal
already-exists/unknown 运行证据。下一步在 pinned Temporal sandbox 恢复后，执行同一 workflow ID 的
重复 start、提交后网络不确定和 history/input observation，对账结果写入统一 evidence ledger；随后再
进行 worker termination/restart、checkpoint/replay、HITL 和生产 HA/RPO/RTO 验收。
