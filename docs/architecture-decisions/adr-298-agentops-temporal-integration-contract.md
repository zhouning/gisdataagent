# ADR-298: AgentOps Temporal Integration Contract and Harness

状态：已采纳，provider-neutral integration contract 已实现；真实 Temporal runtime 未完成  
日期：2026-08-25  
决策关联：ADR-005、ADR-007、ADR-297

## 背景

ADR-297 已冻结 AgentSpecVersion、AgentDeploymentRevision、AgentRun、AgentTaskStep 和
AgentToolCall，但这些对象还没有规定如何进入 Temporal。若先接 SDK，容易把 workflow id、
重试、人工信号和 provider 的未知结果散落在 worker 代码里，导致重试重复副作用、跨租户串
workflow，以及控制台状态和 workflow history 不一致。

仓库当前没有 temporalio 依赖，也没有已验收的 Temporal 集群。因此本阶段先冻结适配合同，
并使用 deterministic in-memory harness 做 contract tests。

## 决策

新增 data_agent.agentops_temporal_contracts：

- TemporalNamespaceIdentity 和 TemporalTaskQueueIdentity 固化 tenant、isolation class、
  namespace、queue 和 workload identity；不携带 provider credential。
- TemporalWorkflowIdentity 的 workflow id 由 tenant/isolation、namespace、workflow type、
  immutable AgentSpec hash、DeploymentRevision hash 和 idempotency key 派生。重试、worker
  重启和 replay 不改变该 id；改变租户、隔离级别、部署版本或幂等键必须得到不同 id。
- TemporalWorkflowInput 将 root AgentRun、SubjectContext、retry policy 和 input artifact
  绑定到 workflow identity；Temporal worker 不直接成为数据产品或策略权威。
- TemporalSignal 只接受带 expected state version 的 approve/reject/pause/resume/cancel/
  reconcile 信号；过期 signal 和不允许的状态推进必须拒绝。
- TemporalActivityEvidence 要求 policy decision ref；成功调用必须有 output artifact，外部
  写入还必须有 external receipt；provider unknown outcome 必须携带 operation ref，并进入
  RECONCILING，不能自动重放副作用。
- TemporalStateTransition 只投影 GDA AgentRun 的审计状态；Temporal history 不是平台审计
  唯一权威，控制面仍保存 correlation、policy、artifact 和 outcome evidence。

TemporalIntegrationHarness 只用于确定性合同测试和后续真实 adapter 的验收基线，不执行模型、
工具、数据写入，也不模拟生产 Temporal durability。

## 验证

data_agent/test_agentops_contracts.py 现有 11 个测试覆盖：

- workflow identity 稳定性、幂等键变化和 tenant/isolation 隔离；
- approval、pause、resume、stale signal 和非法状态边界；
- unknown provider outcome -> reconciliation；
- activity evidence 幂等和同一幂等键的证据冲突拒绝。

## 未完成与下一步

本 ADR 不代表 Temporal namespace/worker、OIDC、HA、真实 crash/restart、timer、signal、
replay、版本迁移、shadow/canary、在线事故回滚或生产多租户隔离已完成。下一切片应在独立
optional profile 中通过 ADR-299 的 provider adapter 接入 pinned Temporal SDK，先完成一个
高风险审批 action 和一个 GWM rollout 的 sandbox rehearsal，再决定生产部署。

## 取舍

先做 provider-neutral 合同会暂时缺少真实 worker 的网络、序列化和 replay 证据，但避免在没有
集群和依赖基线时伪造“已接入”。当真实 Temporal profile 通过 crash/restart、signal、timer、
retry、compensation 和 audit 演练后，本合同可直接作为 adapter conformance suite。
