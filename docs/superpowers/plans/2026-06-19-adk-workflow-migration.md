# ADK Workflow API 迁移实施计划

- **日期**：2026-06-19
- **关联评估**：`docs/adk-deprecation-warning-assessment.md`
- **目标**：把 GIS Data Agent 中仍依赖 ADK deprecated template workflow classes 的编排逐步迁移到 ADK 2.x `Workflow` graph API。
- **范围边界**：这是独立技术债迁移任务，不并入 TWM 主开发线。

## 结论

当前 warning 不是“继续升级 ADK”可以解决的问题。项目 `.venv` 中已安装 `google-adk 2.2.0`，且 `google.adk.workflow.Workflow` 和 `JoinNode` 可导入。warning 的直接原因是运行时代码仍实例化：

- `ParallelAgent`
- `SequentialAgent`
- `LoopAgent`

正确处理方式是迁移 agent orchestration。迁移需要单独排期，因为现有测试、拓扑 API、pipeline analytics、hook/guardrail 逻辑和多处文档都把旧类当作结构契约。

## 当前事实

代码入口集中在 `data_agent/agent.py`：

| 对象 | 当前类型 | 风险 |
|---|---|---|
| `parallel_data_ingestion` | `ParallelAgent` | 触发 deprecated warning；并行分支状态合并语义需要验证 |
| `data_engineering_agent` | `SequentialAgent` | 依赖 `ParallelDataIngestion -> DataProcessing` 顺序 |
| `analysis_quality_loop` | `LoopAgent` | 依赖 `approve_quality` 设置停止信号 |
| `data_pipeline` | `SequentialAgent` | root_agent 当前指向该对象，影响最大 |
| `farmland_optimization_pipeline` | `SequentialAgent` | app 中有专门路由，影响真实优化路径 |
| `governance_report_loop` | `LoopAgent` | 治理报告质量门 |
| `governance_pipeline` | `SequentialAgent` | 治理主流程 |
| `general_summary_loop` | `LoopAgent` | 通用总结质量门 |
| `general_pipeline` | `SequentialAgent` | 默认兜底主流程 |
| `explore_process_workflow` | `SequentialAgent` + `ParallelAgent` | 推荐 pilot，低风险且拓扑小 |
| `analyze_viz_workflow` | `SequentialAgent` | 可作为第二个顺序型 pilot |
| `full_analysis_workflow` | `SequentialAgent` | S-5 多智能体协作路径 |
| `rs_analysis_workflow` | `SequentialAgent` | 遥感专业路径 |

版本元数据存在不一致：

- `.venv` 实测：`google-adk 2.2.0`
- `requirements.txt`：`google-adk==1.26.0`
- `pyproject.toml`：`google-adk>=1.27`
- `docs/roadmap.md`：仍写 `ADK: v1.27.2`

这不是迁移本身的第一步，但必须在 pilot 前确认实际运行环境，避免 CI、本地和部署环境看到不同 warning 或不同 API。

## 官方 API 依据

ADK 官方文档将 ADK 2.0+ 的 graph-based workflows 描述为用 nodes 和 edges 组合 agents、tools、function nodes 和 human input 的显式执行图，用于提升复杂任务的控制性、可预测性和可靠性。

迁移中需要遵守的关键限制：

- `Workflow` graph 使用 `START` 作为入口，通过 edges 定义顺序、分支、并行和 join。
- 并行 fan-out/fan-in 使用 `JoinNode`，所有上游节点必须产出 `Event.output`，否则 join 会停住。
- graph workflow 中可以放入 agents/LlmAgents，但需要注意 task/single-turn 模式限制；不要把交互式 chat session 直接并行跑。
- LLM 节点建议使用结构化输出或明确 `output_key`，否则下游 function node、join 和持久化层容易遇到序列化或类型问题。

## 非目标

本任务不做：

1. 不升级或降级 ADK 版本来“消 warning”。
2. 不修改 TWM toolset/service/API 主开发线。
3. 不一次性替换 `agent.py` 中所有旧类。
4. 不删除 legacy pipelines，pilot 期间必须保留 fallback。
5. 不把测试从旧类断言全量改成空泛存在性断言；需要迁移为拓扑和行为契约断言。

## Pilot 选择

优先迁移 `explore_process_workflow`，原因：

- 拓扑小：`WFExplorer` 与 `WFSemanticPreFetch` 并行，然后进入 `WFProcessor`。
- 不直接作为 `root_agent`，不会影响默认会话入口。
- 覆盖了最关键的并行 + join 模式，能验证 `ParallelAgent` 的替代路径。
- 相关测试集中在 `test_parallel_pipeline.py` 和 `test_adk_optimization.py`，回归面可控。

目标拓扑：

```text
START -> WFExplorer --------\
                            -> JoinNode("WFIngestionJoin") -> WFProcessor
START -> WFSemanticPreFetch /
```

建议保留两个导出对象：

```text
explore_process_workflow_legacy
explore_process_workflow
```

其中 `explore_process_workflow` 在 feature flag 开启时指向新 `Workflow`，默认仍可保持 legacy，直到 pilot 测试和运行验证通过。

## Phase 0：环境与契约冻结

目标：迁移前先把当前行为和版本事实固定下来。

改动建议：

- 新增 `data_agent/adk_compat.py`
  - 提供 `get_adk_runtime_version()`
  - 提供 `has_workflow_api()`
  - 提供 `USE_ADK_WORKFLOW_API` feature flag
- 增加轻量测试，确认 `.venv`/CI 环境能导入 `Workflow`、`JoinNode`。
- 把版本元数据不一致列为单独修复项：`requirements.txt`、`pyproject.toml`、`roadmap.md` 后续统一，但不要和 pilot 同 commit 混在一起。

验收：

```bash
.venv/bin/python -m pytest data_agent/test_adk_compat.py -q
```

## Phase 1：ExploreAndProcess Workflow pilot

目标：用 ADK `Workflow` 重建 `ExploreAndProcess`，保留 legacy fallback。

改动建议：

- 新增工厂函数：
  - `_make_explore_process_legacy()`
  - `_make_explore_process_workflow()`
- 新 workflow 使用新的 agent 实例，避免 ADK one-parent 约束。
- `WFExplorer` 与 `WFSemanticPreFetch` 必须都产生可 join 的 output。
- `WFProcessor` 继续读取 `data_profile`、`semantic_context` 等 state/output。
- 新增 feature flag：
  - `ADK_WORKFLOW_PILOT=explore_process`
  - 未开启时保持旧对象。

验收：

```bash
.venv/bin/python -m pytest \
  data_agent/test_parallel_pipeline.py \
  data_agent/test_adk_optimization.py \
  -q
```

测试调整原则：

- 对 legacy fallback 仍可保留旧类结构断言。
- 对 Workflow pilot 不再断言 `isinstance(..., SequentialAgent/ParallelAgent)`。
- 新断言应检查：
  - workflow name 是 `ExploreAndProcess`
  - graph 中有 `WFExplorer`、`WFSemanticPreFetch`、`WFProcessor`
  - 有 join node
  - feature flag 关闭时旧行为不变
  - feature flag 开启时不触发旧类实例化 warning

## Phase 2：运行链路 smoke

目标：确认新 pilot 不破坏 Runner、planner 调用和拓扑展示。

验证点：

- `planner_agent` 的 sub-agent/tool 路由不因 pilot 对象变化而失效。
- `agent_hooks.attach_lifecycle_hooks()` 不再假设只有 `SequentialAgent/ParallelAgent/LoopAgent` shell。
- `topology_routes.py` 能展示 `Workflow` 节点，或者显式把 workflow graph 降级为可读节点列表。
- `pipeline_runner.py` 能接受 `Workflow` 类型 agent。

建议测试：

```bash
.venv/bin/python -m pytest \
  data_agent/test_agent_hooks.py \
  data_agent/test_topology_api.py \
  data_agent/test_toolsets.py \
  -q
```

## Phase 3：顺序型工作流迁移

目标：迁移低风险顺序流程，不碰 root pipeline。

顺序建议：

1. `analyze_viz_workflow`
2. `full_analysis_workflow`
3. `rs_analysis_workflow`
4. `farmland_optimization_pipeline`

验收标准：

- 每个 workflow 均有 legacy fallback。
- 每个 workflow 都有结构测试和至少一个 runner smoke。
- 不新增 `SequentialAgent`。
- 不改变外部对象名，避免 app/router 大面积修改。

## Phase 4：LoopAgent 质量门迁移

目标：把 generator-critic loop 改成 routed graph loop。

候选：

- `analysis_quality_loop`
- `governance_report_loop`
- `general_summary_loop`

迁移模式：

```text
START -> generator -> checker -> route
route("continue") -> generator
route("exit") -> next stage
```

关键要求：

- loop 必须有 max iteration 保护。
- checker 的输出必须结构化，例如 `{ "status": "pass" | "fail", "feedback": "...", "iteration": n }`。
- 不能只依赖文本里包含 pass/fail。
- `approve_quality` 的停止语义需要映射到 `Event.route="exit"`。

## Phase 5：Root pipelines 迁移

目标：迁移影响最大的三个主 pipeline。

顺序建议：

1. `general_pipeline`，因为它是兜底路径，但结构最短。
2. `governance_pipeline`，因为治理质量门和报告输出更容易验收。
3. `data_pipeline`，最后迁移 root_agent 当前默认入口。

验收：

- `data_agent/app.py` 选择 pipeline 的路径不变。
- `message_handler.py`、`task_queue.py`、`workflow_engine.py` 不需要知道 legacy/new 的差别。
- `root_agent = data_pipeline` 在 Workflow 迁移后仍可被 ADK runner 接受。
- 旧类 warning 在默认测试集内消失或只剩 legacy fallback 显式测试产生。

建议回归：

```bash
.venv/bin/python -m pytest \
  data_agent/test_team.py \
  data_agent/test_planner.py \
  data_agent/test_parallel_pipeline.py \
  data_agent/test_adk_optimization.py \
  data_agent/test_multi_agent.py \
  data_agent/test_multi_agent_collaboration.py \
  data_agent/test_agent_hooks.py \
  data_agent/test_guardrails.py \
  -q
```

## 回滚策略

每个阶段都必须保留 feature flag 和 legacy fallback，直到该阶段验收完成。

推荐环境变量：

```text
ADK_WORKFLOW_API_ENABLED=false
ADK_WORKFLOW_PILOT=none
```

开启 pilot：

```text
ADK_WORKFLOW_API_ENABLED=true
ADK_WORKFLOW_PILOT=explore_process
```

如果发现 runner、A2A、topology 或 callback 不兼容，直接关闭 flag，不回滚 TWM 或其他业务改动。

## 与 TWM 的关系

TWM 当前主线是 toolset/service/API/data contract，不依赖旧 `ParallelAgent`、`SequentialAgent`、`LoopAgent` 语义，因此 ADK warning 不阻塞 TWM。

如果后续 TWM 需要多阶段自动工作流，例如：

```text
build_state -> evaluate_rules -> forecast -> rollout -> validation_report -> dynamics_training_examples
```

应直接用 `Workflow` graph 实现，不能再新增旧 template workflow classes。

## 完成定义

迁移任务完成需要同时满足：

- 默认运行路径不再实例化 deprecated workflow classes。
- `rg -n "ParallelAgent|SequentialAgent|LoopAgent" data_agent/agent.py data_agent/agent_composer.py` 只剩 legacy fallback、测试或文档引用。
- CI/本地测试不再出现 ADK deprecation warnings，除非测试显式覆盖 legacy fallback。
- `requirements.txt`、`pyproject.toml`、`docs/roadmap.md` 对 ADK 版本描述一致。
- 拓扑 API、agent hooks、guardrails、workflow engine、message routing 均通过回归。
