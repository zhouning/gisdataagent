# ADR-309: Temporal Worker Runtime Configuration Contract

状态：已采纳，provider-neutral runtime config 已实现；真实 Temporal worker 未启动  
日期：2026-08-26  
决策关联：ADR-308

## 背景

ADR-308 已有 worker registration/factory，但 K8s ConfigMap 只有 namespace、task queue 和
frontend 地址，AgentSpec/deployment hash、workflow/activity 类型和 worker identity 仍可能
靠进程默认值或人工拼接。这样即使 server 可连接，也可能消费错误 task queue 或错误版本的
Agent action。

## 决策

新增 `TemporalWorkerRuntimeConfig`：

- `from_env()` 要求显式提供 tenant、namespace、frontend `host:port`、task queue、worker
  identity、workflow type、activity type 列表、AgentSpec SHA-256 和 DeploymentRevision
  SHA-256；只对并发上限提供受限默认值。
- frontend 地址端口、activity 名称、hash 和并发边界在构造前验证；缺少任何身份/hash 或
  非法值都抛出 `TemporalAdapterError`，不启动 worker。
- `registration()` 将 runtime config 转成 ADR-308 hash-bound `TemporalWorkerRegistration`。
- provider definition 使用显式 `TemporalWorkerDefinition(name, handler)`，不再假设 Temporal
  类型名等于 Python 函数 `__name__`；因此 `gda.agentops.gis_product` 等稳定 provider 名称
  可以绑定任意 Python handler，同时保留类型漂移门禁。

## 验证

新增 runtime config、缺失 hash、非法 frontend/activity 和显式 provider name-handler
绑定测试。AgentOps/Temporal/task-graph/execution/workflow scoped tests 共 66 个通过；
完整 AgentOps 集合 86 个通过；Ruff/compileall 通过。

## 边界与后续

本 ADR 不读取或管理 Temporal/PostgreSQL Secret，不连接 server，也不把 ConfigMap 渲染或
fake Worker 构造当作运行证据。真实 sandbox 仍需注入 hash/config、安装 pinned `temporalio`、
连接 namespace、注册 workflow/activity，并完成 worker termination/history replay/真实
activity receipt 演练后才能评估 worker 副本和生产准入。
