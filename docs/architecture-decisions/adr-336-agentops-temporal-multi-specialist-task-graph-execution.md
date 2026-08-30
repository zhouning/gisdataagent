# ADR-336：AgentOps Temporal 多 Specialist TaskGraph 执行

## 状态

已采纳；Docker Desktop Temporal sandbox 的 bounded runtime slice 已通过，生产晋级保持关闭。

## 背景

ADR-300/301 定义了 immutable `AgentTaskGraph` 和独立的 execution projection，ADR-302/303/304
将 graph、ToolCall、activity evidence 和 checkpoint/replay 绑定到 Temporal 边界。此前真实
Temporal 证据主要覆盖单 activity、start/reconciliation、worker restart 和 checkpoint 对账，
尚未证明一个多智能体 graph 能按依赖执行并把 specialist 结果回写到统一控制面。

## 决策

- 新增 `TemporalTaskGraphExecutionManifest`。它逐 step 固化 activity type、tool、capability、
  policy decision、SubjectContext、side-effect、task queue、超时、取消策略和 idempotency key，
  并以 `manifest_sha256` 绑定 graph。
- 新增 `TemporalTaskGraphExecutionInput`。workflow 在启动前重新用 `AgentSpecVersion`、
  `AgentDeploymentRevision` 和 `AgentRun` 编译 graph；graph、deployment/spec hash、manifest
  和 execution input fingerprint 任一漂移都 fail closed。capability/tool 必须属于 AgentSpec
  授权集合；MMFE/GWM 是普通 specialist，不能取得 control-plane write 权威。
- 新增 `TemporalTaskGraphWorkflow`。它按 graph 的 ready wave 执行 coordinator -> planner ->
  data_engineer/MMFE/GWM fan-out -> quality fan-in；同一 wave 使用并行 activity，下一 wave
  只有在前置 step 成功并且 ToolCall/Artifact evidence 已回写后才开始。
- 所有 specialist 共用一个 `TemporalActivityWorkerHandler` 和 typed
  `TemporalActivityAdapter`。SDK `RetryPolicy.maximum_attempts` 固定为 1；activity 失败后由
  workflow projection 记录 definitive failure，只有 retry policy 允许时显式创建下一个
  platform attempt。`unknown` 会保留所有同 wave 已收到的 evidence，并停在 reconciliation，
  不被另一个成功 receipt 错误清成 running。
- workflow 返回 hash-bound `TemporalTaskGraphWorkflowCheckpoint`，包括完整 transition history、
  ToolCall、activity schedule/evidence 和最终 step 状态；Temporal history 作为 provider history，
  GDA checkpoint 仍是控制面投影，二者不互相替代。

## 取舍

| 选项 | 结果 |
|---|---|
| 在 workflow 中按 agent id 猜 tool/capability/timeout | 实现快，但无法审计授权和配置漂移，拒绝 |
| 为每个 specialist 建独立 workflow/activity 类型 | 类型隔离更强，但复制调度和 receipt 逻辑，拒绝 |
| 一个 typed activity + hash-bound execution manifest | 增加一个输入合同，但保持 graph、policy、ToolCall 和 receipt 单一边界，采用 |

## 证据

- 本地 focused contract/runtime 测试：`43 passed`（TaskGraph execution、Temporal workflow、
  worker、provider bridge 和 regression）；完整 AgentOps 集合 `166 passed, 5 skipped`。
- 真实 Docker Desktop sandbox 报告：
  `docs/reports/agentops_temporal_task_graph_rehearsal_2026-08-28.json`。
- 原始 Temporal history：
  `docs/reports/agentops_temporal_task_graph_history_2026-08-28.json`。
- Temporal server `1.29.7`、Python SDK `1.32.0`；6 个 ToolCall，7 次显式 activity
  schedule/completion（GWM attempt 1 失败、attempt 2 成功），4 个执行 wave，41 个 history
  events，Replayer passed。

机器可读报告文件 SHA-256：
`aae37bbde4e4785386c4bab3beb175e500b3bb0822fb3d814685112ceb8b6a17`；原始 history 文件
SHA-256：`b0597695cfd03b1863aec68c0d41c0d28504de20945eb451aea9b0abcfd8fa42`。

## 未关闭边界

本 ADR 只关闭 bounded 多 specialist execution、显式 retry、ToolCall/Artifact evidence 回写和
history replay。它不代表生产 Temporal HA/DR、OIDC/secret rotation、Kubernetes NetworkPolicy
enforcement、HITL approval/signal、shadow/canary、online verdict、incident/rollback、真实
MMFE/GWM 数据 provider、跨区域 RPO/RTO 或 AR-5 整体退出。
