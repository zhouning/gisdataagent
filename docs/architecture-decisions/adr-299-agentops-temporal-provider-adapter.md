# ADR-299: AgentOps Temporal Provider Adapter Boundary

状态：已采纳，provider-neutral contract 与 lazy SDK bridge 已实现；Temporal SDK/runtime 未完成  
日期：2026-08-25  
决策关联：ADR-007、ADR-297、ADR-298

## 背景

ADR-298 已冻结 namespace、workflow identity、signal、retry 和 activity evidence，但还缺少
从 GDA 控制面到 Temporal provider 的单一调用边界。直接在业务代码里调用 SDK 会把
provider payload、policy、幂等和 receipt 处理分散到多个 worker。

当前仓库没有 temporalio 依赖，也没有已验收的 Temporal server。因此本阶段实现
provider-neutral adapter contract 和 fake-provider conformance，不引入默认依赖。

## 决策

新增 data_agent.agentops_temporal_adapter：

- TemporalWorkflowStartRequest 是唯一允许提交给 provider 的 canonical payload，包含
  namespace、workflow identity、task queue、完整 workflow input 和 policy decision ref。
- TemporalProviderStartResult 只接受 started、already_exists 或 unknown。前两者必须
  有 provider run id 和 receipt；unknown 必须有 receipt ref，adapter 不自动重试。
- TemporalProviderSignalResult 必须带 provider receipt，并校验 tenant、workflow、signal id
  与 GDA identity 一致。
- TemporalWorkflowAdapter 只负责构造 payload、调用 provider client、校验 correlation；
  Temporal workflow history、activity retry 和 durable state 仍归 Temporal，GDA 继续保存
  AgentRun、Policy、Artifact 和 provider evidence。
- TemporalProviderClient 是最小 Protocol；未来 pinned temporalio 实现只能替换该 client，
  不得绕过 GDA contracts。
- TemporalAsyncProviderClient 与 TemporalWorkflowAdapter 的 `start_async()` /
  `signal_async()` 是 Python Temporal SDK 的异步入口；它们复用同一 canonical payload 和
  receipt correlation 校验。同步入口遇到 awaitable provider result 会 fail closed，不创建或
  嵌套 event loop。
- `data_agent.agentops_temporalio_provider.TemporalioProviderClient` 是 lazy-import 的 SDK
  bridge：只在调用 retry-policy translation 时导入 `temporalio.common.RetryPolicy`，把
  Temporal `start_workflow`/`WorkflowHandle.signal` 映射为 GDA 的 started/already_exists/
  unknown 与 accepted/unknown receipt。provider 已提交但 transport outcome 不确定时不自动重试。

## 验证

data_agent/test_agentops_temporal_adapter.py 的 fake-provider conformance 覆盖：

- canonical start payload 和 policy binding；
- workflow identity/retry policy 透传；
- unknown start receipt 不自动重试；
- 错误 receipt correlation fail-closed；
- signal identity 和 signal id 保持；
- 已推进 AgentRun 不能作为新的 Temporal starter input。

此前 AgentOps/Temporal 相关测试共 17 个通过；联合 platform/recovery/deployment 回归仍通过。
本轮异步 adapter 回归新增 3 个用例，验证 async start、async signal 以及同步入口拒绝
async provider；adapter focused tests 共 9 个通过。
新增 `data_agent/test_agentops_temporalio_provider.py` 的 4 个 bridge conformance tests，
覆盖成功 start/signal、provider failure unknown、already-started receipt 和缺失 SDK fail-closed。

## 未完成与下一步

本 ADR 不代表 Temporal server、namespace、OIDC/workload identity、HA、真实 worker、
crash/restart、timer/replay、版本迁移、shadow/canary 或生产 RPO/RTO 已完成。已新增
`k8s/optional/temporal-agentops-sandbox` 及显式 overlay
`k8s/overlays/temporal-agentops-sandbox`：固定 `temporalio/auto-setup:1.29.7` 和
`postgres:16.4-alpine`，使用独立 metadata PostgreSQL、namespace
`gda-agentops-sandbox` 资源、Secret 引用和最小 NetworkPolicy；默认 profile 的 server、PostgreSQL
和 worker 均为 `replicas: 0`，overlay 只启用 server/PostgreSQL，worker 仍关闭。4 个离线
Kustomize/deployment contract tests 已通过。这是可渲染的 sandbox deployment contract，
不是已部署的 Temporal 集群；bridge 已实现但当前环境没有安装 `temporalio`，也没有真实
AgentOps action worker。
下一步是锁定并引入 SDK worker image，完成审批 action 与 GWM rollout 的 sandbox rehearsal，
再进行生产准入评审。
