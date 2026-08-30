# ADR-327：Temporal Worker 终止后的显式 Attempt 恢复

- **状态**：Accepted for sandbox rehearsal; production rollout remains blocked
- **日期**：2026-08-27
- **范围**：AR-5 AgentOps Runtime

## 背景

Temporal server 保存 workflow history，但它不会替 GDA 判断一次 Agent ToolCall 是否已经产生
可接受的副作用。worker 在 activity 执行期间被终止时，客户端可能只看到连接断开；如果把 SDK
retry 当成平台 retry，会隐藏 attempt、破坏 ToolCall 幂等证据，也无法把超时和新 worker 的
执行结果对回 AgentRun、Artifact 和 policy。

此前的 AR-5 切片已经冻结了 `TemporalActivityRequest`、`TemporalActivitySchedulePlan`、
`TemporalActivityEvidence` 和 `TemporalTaskGraphWorkflowCheckpoint`，并在真实 sandbox 完成
单次 `start -> activity -> receipt -> history replay`。缺少的是 worker termination/restart 后的
真实 history 证据。

## 决策

1. Temporal SDK activity retry 固定为 `maximum_attempts=1`。平台 attempt 由 GDA workflow 显式
   编排，attempt 2 必须使用新的 `activity_id`、`request_sha256` 和 `schedule_sha256`，并复用
   同一 ToolCall 的业务幂等键。
2. worker 终止后，只有 Temporal history 中的 definitive timeout/failure 事件才能触发下一次
   attempt；`UNKNOWN` provider receipt 仍先进入 reconciliation，不得因为 worker 重启而自动重放
   有副作用的调用。
3. 新 worker 使用同一 namespace、task queue、worker identity、AgentSpec hash 和 deployment
   revision 注册。workflow history 是 Temporal 运行时真值；GDA 的 execution projection、
   activity evidence、Artifact 和 checkpoint 继续由 GDA 控制面负责。
4. 重启 rehearsal 必须证明：第一 activity 已产生 `ACTIVITY_TASK_STARTED`，第一 worker 被实际
   终止，随后出现一个 timeout、第二个显式 schedule 和一个 completion；最终 history 可离线
   replay，且不宣称生产 HA、RPO/RTO 或 Kubernetes worker image 已就绪。

## 取舍

- 显式 attempt 增加 workflow 代码和 history 事件，但保留 GDA 对副作用、证据和回滚的控制，
  能区分“没执行”“执行超时”和“已执行但回执丢失”。
- `maximum_attempts=1` 会牺牲 Temporal SDK 的内建便利；换来的是真实 retry policy、预算和
  reconciliation 可以落在统一 AgentOps projection，而不是隐藏在 provider。
- sandbox 使用本地子进程模拟 worker crash，验证 provider/history 边界；它不能替代多副本
  worker、fencing、持久 checkpoint store、OIDC、备份恢复和故障演练。

## 验收证据

脚本：[rehearse_agentops_temporal_worker_restart.py](../../scripts/rehearse_agentops_temporal_worker_restart.py)

合同测试：[test_agentops_temporal_worker_restart.py](../../data_agent/test_agentops_temporal_worker_restart.py)

真实运行已完成，报告和 history：

- `docs/reports/agentops_temporal_worker_restart_2026-08-27.json`
- `docs/reports/agentops_temporal_worker_restart_history_2026-08-27.json`

证据摘要：Temporal `1.29.7` / Python SDK `1.32.0`；第一 worker 在 activity started 后
`SIGKILL`，exit code `-9`；history 出现一个 `TIMEOUT_TYPE_START_TO_CLOSE` activity timeout，
第二 worker 以新的 activity identity 完成 attempt 2；最终 history 19 events，offline replay
passed，SDK `maximum_attempts=1`，本次恢复耗时 `61.871384s`。报告 `report_sha256` 为
`0e5b9e66648153d9d599eeb72033d0934cc5055a5136ebf696a422ac7f33cd86`。

上面的摘要 hash 仅用于人工定位；以报告文件中的完整 `report_sha256` 为准。生产退出门仍要求
HITL、online observation、incident/rollback、HA、worker image 和 uplift evidence。

## 2026-08-29 Re-authentication

在同一 pinned Temporal sandbox 重新执行了两个独立 worker 进程的 termination/restart rehearsal：
第一 worker 在 `ACTIVITY_TASK_STARTED` 后退出码为 `-9`，Temporal 记录一个
`TIMEOUT_TYPE_START_TO_CLOSE`；第二 worker 只执行 workflow 显式安排的 attempt 2，最终 history
仍为 19 个事件且 replay 通过。报告中的 `report_sha256` 为
`b8ae8f1763d95b688b219e5bdacc98e9589955101bcee284ba97debab08df3a7`；报告文件 SHA-256 为
`b3211226b7fb0d1ab62305bc468fa626142b4f000af0482d88cadb742661ee64`，history 文件 SHA-256 为
`d308cfa1bdc493cb730705f6114782a5c89618131d9fea9a44b6dc2851bb7029`。这次重认证仍只覆盖
explicit attempt recovery；provider receipt recovery、跨 worker retry budget、生产 worker image
和 HA/DR 仍未关闭。
