# ADR-328：Temporal History 与 GDA Checkpoint 对账

- **状态**：已采纳，provider-neutral 合同、SDK conformance 与真实 sandbox 三态对账已完成；生产 checkpoint store 与 rollout 仍未完成
- **日期**：2026-08-27
- **范围**：AR-5 AgentOps Runtime

## 背景

Temporal history 和 GDA execution projection 记录的是同一次 AgentRun 的不同侧面。Temporal
负责 durable workflow history、activity schedule/started/terminal event 和 provider run；GDA
负责 AgentRun、TaskStep、ToolCall、Artifact、policy 以及可恢复 checkpoint。任一侧都不能静默
覆盖另一侧：只看 Temporal 会丢失治理和副作用证据，只看 checkpoint 会把未发生的 provider 执行
误当成事实。

## 决策

1. `TemporalioProviderClient.observe_workflow_history()` 只读指定 workflow run 的 history，使用
   已连接 client 的 `DataConverter` 解码 canonical workflow input、`TemporalActivityRequest` 和
   `TemporalProviderActivityResult`；它不启动、signal、retry 或修改 provider 状态。
2. history observation 固定绑定 tenant、namespace、workflow、provider run、首个 start input
   fingerprint、history event count/hash，以及按 schedule event 顺序排列的 activity attempts。
   activity 的 started、timeout、failed、cancelled、completed 都必须能回指一个 schedule；孤立
   event、重复 started/terminal、request/activity identity 漂移和超过显式 retry 边界的 attempt
   一律 fail closed。
3. `reconcile_temporal_checkpoint()` 以 Temporal history 为 provider execution authority，以
   GDA checkpoint 为治理/投影 authority。对账前先校验 tenant/workflow 和 canonical start input
   fingerprint，再逐 activity 校验 attempt、request hash、request content 和 terminal evidence。
4. 对账只产生不可变 `TemporalCheckpointReconciliation`：
   - `matched`：两侧 activity、request、terminal evidence 完全一致；
   - `checkpoint_behind`：provider 已有 GDA 尚未落盘的 activity 或 evidence，只能补写/重放
     checkpoint，不能重发副作用；
   - `provider_behind`：GDA 已有 schedule 但 provider history 尚未观察到，只能等待/重新观察，
     不能把它当成失败后自动 retry；
   - 两侧出现互相独有的 activity identity、identity/hash/input drift 或不完整 terminal 证据时
     直接报错，不生成可晋级的 verdict。
5. activity 的平台 retry 仍由 GDA workflow 显式产生新 attempt；Temporal SDK
   `maximum_attempts=1`，因此 reconciliation 可以区分 timeout/failure、未知传输和已完成回执，
   不会把 provider 内部重试隐藏成一次 ToolCall。

## 证据

- 合同实现：[agentops_temporal_reconciliation.py](../../data_agent/agentops_temporal_reconciliation.py)
- SDK observer：[agentops_temporalio_provider.py](../../data_agent/agentops_temporalio_provider.py)
- 对账合同测试：[test_agentops_temporal_reconciliation.py](../../data_agent/test_agentops_temporal_reconciliation.py)
- SDK fake-history conformance：[test_agentops_temporalio_provider.py](../../data_agent/test_agentops_temporalio_provider.py)
- 本轮验证：reconciliation `6 passed`，Temporal SDK provider `10 passed`，rehearsal contract
  `2 passed`；fake history 使用
  `temporalio==1.32.0` 官方 converter 和 protobuf `HistoryEvent`，覆盖 start input、activity
  schedule/start/completion、request drift、checkpoint-behind/provider-behind 和 start-input drift。

2026-08-27 已在 disposable `gda-agentops-sandbox` 使用 Temporal server `1.29.7` / Python SDK
`1.32.0` 执行真实三态对账：workflow 先停在 signal gate，此时 GDA 已有 schedule 而 provider
history 尚无 activity，结论为 `provider_behind`；放行并完成 activity 后，原 checkpoint 缺 terminal
evidence 且 AgentRun 仍为 running，结论为 `checkpoint_behind`；将同一 provider result 投影为 GDA
evidence、完成 TaskStep 和 AgentRun 后，结论收敛为 `matched`。完整 history 为 15 events，offline
replay passed。证据文件：

- [总报告](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27.json)
- [原始 history](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_history.json)
- [provider observation](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_observation.json)
- [checkpoint before](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_checkpoint_before.json)
- [checkpoint after](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_checkpoint_after.json)
- [provider-behind](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_provider_behind.json)、
  [checkpoint-behind](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_checkpoint_behind.json)、
  [matched](../reports/agentops_temporal_checkpoint_reconciliation_2026-08-27_matched.json)

报告 `report_sha256`：
`e15b59d099b7ece4e94a8915fa4bffdc7752b827f61c2edf2b13d367e7573a06`。rehearsal 完成后
Temporal/PostgreSQL sandbox 已恢复为默认 `replicas: 0`。

## 边界与下一步

ADR-329 已把 observation/reconciliation 接入 PostgreSQL append-only authority，并完成 disposable
数据库中的 CAS、RLS、不可变性和跨进程恢复验证；ADR-330 进一步完成 owner/epoch fencing、旧
worker 迟到写拒绝和 commit 前/后崩溃恢复。本 ADR 仍不代表生产 checkpoint store rollout、真实
多副本 reconciler、HITL、online observation、incident/rollback、HA、备份恢复或 RPO/RTO 已完成。
下一步把 lease lifecycle 接入真实 worker 并做多副本故障演练；AR-5 的生产退出门仍未关闭。
