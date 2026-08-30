# ADR-297: Versioned Multi-Agent AgentOps Contract

状态：已采纳，多智能体 topology/deployment/run/tool/evaluation 合同已实现；Temporal runtime、真实 Agent worker 和生产 rollout 仍未完成  
日期：2026-08-25

## 背景

项目已有 agent registry、工具集合和评测脚本，但这些能力分别表达发现、调用或离线评测，不能证明一次
Agent 执行使用了哪个版本的 Agent bundle、数据产品、策略、工具副作用和质量结论。把多个 specialist
都塞进一个聊天 Agent 会丢失委派、并行、审查和回滚边界。

## 决策

新增 `data_agent.agentops_contracts`，冻结以下控制/证据对象：

- `AgentSpecVersion`：包含 coordinator、DAG topology、prompt/model/tool/policy refs、预算和评测集；
  topology 至少有两个节点，coordinator 必须是 supervisor，所有 specialist 必须从 coordinator 可达。
- `AgentRole` 明确支持 `data_engineer`、`quality_guardian`、`multimodal_fusion`、`gwm_specialist`、
  `gis_analyst` 和 `visualizer` 等角色。MMFE/GWM specialist 只消费已绑定的 DataProductVersion，不能
  写原始数据真值、替代 DataOps 或拥有独立 metadata authority。
- `AgentDeploymentRevision`：必须绑定 AgentSpec hash、EvaluationBinding、policy、owner 和 rollout
  strategy；active/shadow/canary 的流量约束由合同校验。
- `AgentRun`、`AgentTaskStep`、`AgentToolCall`：保留 root/parent correlation，绑定 SubjectContext、
  DataProductVersion refs、policy decision、idempotency key 和 Artifact；成功 tool call 必须有 output
  Artifact，外部副作用必须能进入 reconciliation。
- `AgentOnlineVerdict`：由独立 evaluator 写入 evidence Artifact 和 metrics，不能由执行 Agent 自评。

topology 是静态 DAG；长时等待、重试、补偿和有限循环由后续 Temporal workflow 状态承载，不能在
topology 中偷偷形成循环。该合同复用平台的 ResourceURN、SubjectContext、Artifact、Run 和 Policy
语义，不新增 Agent registry、DataProductVersion 或 scheduler。

## 已验证范围

`data_agent/test_agentops_contracts.py` 的 AgentOps/Temporal 回归覆盖：包含 MMFE/GWM specialist 的有效拓扑、环和
孤立节点拒绝、评测绑定与 canary 流量约束、DataProduct-bound AgentRun、自带 policy/artifact 关联的
TaskStep/ToolCall，以及 finite online verdict metrics。

## 边界

本 ADR 不宣称 Temporal namespace/worker、Agent execution provider、模型路由、真实 shadow/canary、
多副本 HA、在线事故自动暂停或生产 OIDC 已完成。AR-5 仍需等待 AR-1 至 AR-4 parity/control gate，
下一步是按 ADR-298 接入 Temporal integration harness，再验收真实 retry/replan、incident/rollback 和
多租户隔离。
