# ADR-300: Deterministic Agent Task Graph Compiler

状态：已采纳，task graph compiler 已实现；模型执行、Temporal worker 和生产 rollout 未完成  
日期：2026-08-25  
决策关联：ADR-297、ADR-298、ADR-299

## 背景

ADR-297 已冻结 supervisor、planner、data engineer、quality guardian、MMFE、GWM 和
visualizer 等 specialist 的 topology，但 topology 本身还不能被执行器消费。若让每个
provider 自己解释节点和边，会导致 step ID、依赖顺序和重放结果分叉。

## 决策

新增 `data_agent.agentops_task_graph`：

- `compile_agent_task_graph()` 只接受同租户、同 AgentSpec、同 DeploymentRevision 的 root
  `AgentRun`，状态限定为 `accepted` 或 `planning`；不接受 child、terminal 或脱离 deployment
  的 run。
- 使用稳定 UUID5(`run_id`, `agent_spec_sha256`, `agent_id`) 生成每个 specialist 的 step ID；
  同一 immutable 输入在 replay/restart 中得到相同 step ID 和 graph SHA-256。
- 用确定性 Kahn 排序编译 DAG；边顺序不参与执行顺序，依赖按 step ID 排序，sequence number
  连续且依赖只能指向更早的 step。
- `AgentTaskGraph` 只包含 `AgentTaskStep`、依赖和 hash，不执行模型、工具、数据写入或调度。
  Temporal、deterministic harness 或后续其他 executor 可以消费它，但不能改变 GDA 的
  AgentRun、policy、DataProductVersion 和 evidence authority。

## 验证

`data_agent/test_agentops_task_graph.py` 的 5 个测试覆盖：

- coordinator -> planner -> data_engineer/MMFE/GWM -> quality 的确定性顺序和 fan-in；
- MMFE/GWM specialist role 与依赖落盘；
- replay 生成相同 step ID/graph fingerprint；
- progressed/child run 和篡改 graph hash 被拒绝。
- runtime `AgentTaskStep` projection（非 pending、attempt 或 artifact）不能伪装成 immutable graph plan。

## 未完成与下一步

本 ADR 不代表模型路由、tool execution、Temporal workflow、activity retry、HITL、replan、
online verdict、shadow/canary 或生产 AgentOps worker 已完成。下一步是让 Temporal workflow
以该 graph 作为 immutable input，逐 step 产生 `AgentToolCall`/`Artifact` evidence，并验证
pause/resume/reconcile；不得在 worker 内再次解析 topology 或生成另一套 step identity。
