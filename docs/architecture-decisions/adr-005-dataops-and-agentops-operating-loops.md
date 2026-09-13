# ADR-005：DataOps 与 AgentOps 双运营闭环

**Status**: Accepted

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Platform, Agent Runtime, SRE, Security

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md)

**Related decisions**: [ADR-002 统一元数据控制面](adr-002-unified-metadata-control-plane.md) · [ADR-003 统一调度与作业控制面](adr-003-unified-orchestration-and-job-control-plane.md) · [ADR-004 能力下限与 Human/Agent 双入口](adr-004-capability-floor-and-dual-entry-agentic-platform.md)

## Context

GIS Data Agent 已有数据接入、工作流、质量、Prompt、模型、Tool、Skill、评测、Guardrail、反馈和 tracing 等组件，但它们尚未组成两个可运营、可审计、可恢复的生命周期。不能因为存在这些组件，就宣称平台具备 DataOps 或 AgentOps。

- **DataOps** 管理数据产品从定义、开发、测试、发布、运行、观测、事故、恢复到反馈迭代的持续交付与可靠性。
- **AgentOps** 管理 Agent bundle 从设计、评测、审批、部署、灰度、在线运行、工具与策略观测、安全事故、预算控制、反馈到回滚迭代的全生命周期。
- **MLOps/LLMOps** 是模型、Prompt、RAG 和推理服务的子域；它们不能替代 AgentOps 对工具、技能、记忆、策略、计划和副作用的治理。
- **PlatformOps/SRE** 管理共享控制面、执行器、存储、网络、备份和基础设施；它不能替代 DataOps 或 AgentOps 的产品语义。

当前 `agent_registry` 是服务发现/心跳，Prompt registry 是 Prompt 版本，eval history 是离线结果，OTel 是 span，feedback 是用户反馈，CI/CD 中的 canary/health/rollback 仍有说明性占位。这些是原材料，不是运营闭环。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 继续把 DataOps/AgentOps 当作零散功能 | 改动最少 | 生命周期、责任和事故边界继续缺失 | 不选 |
| B. 为 DataOps 和 AgentOps 各建一套元数据、调度和发布平台 | 领域表面清晰 | 产生双重 Run、权限、Artifact、审计和回滚事实 | 不选 |
| C. 两个领域状态机，共用平台控制合同和运营基础设施 | 保留领域差异，避免事实分裂，可渐进交付 | 需要定义跨域事件、关联 ID 和责任边界 | **选择** |

## Decision

### 1. 两个闭环

```text
DataOps:
DataProductSpec -> Build/CI -> Quality/Security -> Release/Promotion
 -> DataRun -> Observe/SLO -> Incident/Remediation -> Replay/New Product Version

AgentOps:
AgentSpecBundle -> Eval/Safety/Cost -> Approval/Promotion
 -> Canary/Shadow -> AgentRun/ToolCall -> Online Verdict/Guardrail
 -> Incident/Rollback/Feedback -> New AgentSpecVersion
```

DataOps 产出受治理的 `DataProductVersion`、`AgentContextProjection` 和 `AIDatasetVersion`；AgentOps 消费这些不可变版本，并把质量反馈、`DataDemand`、安全事件和缺失数据需求回流 DataOps。AgentOps 不得把聊天结果、临时表或工具输出直接升级为数据真值。

### 2. 领域对象

DataOps 对象至少包括：

```text
DataProductSpec/Blueprint
Source/SyncDefinition
DataContractVersion/ModelVersion
Pipeline/JobDefinitionVersion
QualityRuleVersion/AssessmentRun
DataProductVersion/DeploymentRevision
DataRun/Artifact/LineageEvent
DataSLO/Observation/DataIncident/Problem
Release/Promotion/ChangeSet
```

AgentOps 对象至少包括：

```text
AgentSpecVersion
PromptVersion/ModelBinding
ToolVersion/SkillVersion
PolicyVersion/MemoryContextContract
EvaluationSet/EvaluationRun/OnlineVerdict
AgentDeploymentRevision
AgentRun/TaskStep/ToolCall/TraceObservation
Budget/SafetyIncident/QualityIncident/Feedback
```

两域共用：`ResourceURN`、不可变 version、`SubjectContext`、`Run`/`Artifact` 关联、`PolicyDecision`、`ApprovalCase`、`Incident/Problem`、`SLO`、`ChangeSet`、`AuditEvent` 和 transactional outbox。AgentOps 可以创建平台 `Run`，但 `AgentRun` 记录认知循环，不能替代数据平台 `Run`。

### 3. 强制运营能力

DataOps 必须提供数据 CI/CD、环境 promotion、质量/合同门、schema drift、data observability、freshness、backfill/replay、数据事故、根因分析、恢复和成本/容量反馈。

AgentOps 必须提供 bundle 评测、回归/安全/工具准确性评测、离线与在线 verdict、shadow/canary、策略和工具权限、AgentRun/ToolCall 追踪、循环/超时/越权/提示注入检测、token/计算预算、人工接管、事故分级、禁用/回滚和反馈回灌。

任何发布只有同时拥有 owner、版本、评测证据、策略、SLO、回滚指针和审计记录，才能进入 active。

### 4. Roadmap 归属

- **AR-0**：冻结 DataOps/AgentOps 术语、对象、责任矩阵、环境、SLO/SLI、Incident/Problem/Change/Release 合同和指标基线。
- **AR-1**：让两个闭环复用统一 Metadata/Orchestration Control Planes、Artifact、Policy、Audit 和 outbox。
- **AR-2**：完成 Source/Sync 到 DataProductVersion 的第一条 DataOps 闭环，包含批处理、Flink CDC/事件流、质量、恢复和重放。
- **AR-3**：完成 Data CI/CD、模型/合同、质量安全门、promotion 和数据事故闭环。
- **AR-4**：完成数据产品、服务、SLO、使用、告警、问题、恢复和成本运营。
- **AR-5**：实现完整 AgentOps Runtime，包括 AgentSpec bundle、评测、部署、AgentRun、ToolCall、在线观测、预算、Guardrail、HITL、事故和回滚。
- **AR-6**：把 ModelOps/LLMOps、Dataset/Evaluation/Model/Prompt/Deployment 纳入 AgentOps bundle 和统一血缘，不再建第二套 AI 资产目录。

## Consequences

### Positive

- 数据生产和 Agent 运行都有明确的 owner、版本、SLO、事故和恢复责任。
- DataOps 与 AgentOps 可以独立演进，但不会复制元数据、调度、权限和审计事实。
- Agent 的质量反馈和数据需求可以可追溯地驱动数据产品新版本。

### Negative

- 需要新增 Release、Promotion、Incident、OnlineVerdict、AgentDeployment 和跨域事件模型。
- 运行观测、评测和事故数据会增加存储、指标和运维复杂度。
- AgentOps 不能只靠 CI 离线评测，必须建设线上行为与副作用观测。

### Mitigation

- 先在自然资源地类图斑 DataOps vertical slice 和一个受控 Agent 数据治理任务上实现最小闭环。
- 复用统一控制面、outbox、Artifact、Policy 和 Audit，不引入第二调度器或第二资产目录。
- 先提供最小 Incident/Promotion 状态机；只有真实 SLO、并发和组织协作需求击穿时再引入外部 ITSM/实验平台。

## Revisit Triggers

- DataOps 或 AgentOps 的状态量、事件吞吐或跨团队审批复杂度超过 PostgreSQL 控制面冻结 SLO。
- Agent 需要跨区域、多集群或强隔离部署，现有 Deployment/Policy/Incident 模型无法满足。
- 在线评测、成本归因或安全事件规模要求独立流处理、实验平台或 ITSM 集成。
