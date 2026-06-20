# ADK Deprecation Warning Assessment

## 结论

当前测试中的 ADK deprecation warnings 不表示“立刻需要升级 ADK”。本地环境已经是：

- `google-adk 2.2.0`
- `google-genai 2.8.0`

warning 的直接原因是 GIS Data Agent 代码仍在使用 ADK 2.x 中已废弃的编排类：

- `ParallelAgent`
- `SequentialAgent`
- `LoopAgent`
- 间接触发的 `BaseAgentConfig`

ADK 2.2.0 的提示明确指向新 API：`Workflow`。因此继续升级 ADK 可能不会消除 warning，反而可能在未来版本中因为旧类被移除而造成运行失败。正确方向是做一次 agent orchestration migration。

## 证据

测试 warning 指向 `data_agent/agent.py` 中多处实例化：

- `ParallelAgent`
- `SequentialAgent`
- `LoopAgent`

本地 ADK 包中存在新的 `google.adk.workflow.Workflow`，其 graph 编排使用：

- `Workflow`
- `START`
- `Edge`
- `FunctionNode`
- `JoinNode`
- `Node`

同时，ADK 源码限制：`mode='task'` 的 `LlmAgent` 不能直接作为静态 workflow graph node，需要通过 chat coordinator 或动态 `ctx.run_node` 调用。这意味着迁移不是机械替换类名。

## 风险判断

| 选项 | 影响 | 建议 |
|---|---|---|
| 只升级 ADK | 可能仍有 warning；未来旧类被移除时风险更大 | 不作为主要方案 |
| 忽略 warning | 短期可运行；长期会累积技术债 | 可短期接受 |
| 迁移到 Workflow | 消除旧编排类依赖，适配 ADK 2.x 方向 | 推荐单独立项 |

## 建议迁移路径

1. 先不要全量替换 `agent.py` 中所有工作流。
2. 选择一个低风险 workflow 做 pilot，例如 `ExploreAndProcess`。
3. 用 `Workflow(edges=[...])` 重建：
   - `START -> explorer`
   - `START -> semantic_prefetch`
   - `explorer/semantic_prefetch -> JoinNode`
   - `JoinNode -> processor`
4. 保留原 legacy agent 作为 fallback。
5. 添加专门测试，确认 Runner、A2A card、custom skills 不受影响。
6. 再逐步迁移 `DataPipeline`、`FullAnalysis`、`RSAnalysis` 等较大编排。

## 与 TWM 的关系

TWM 当前新增能力主要是 toolset/service/API，不依赖 `ParallelAgent`、`SequentialAgent` 或 `LoopAgent` 的旧编排语义。因此 ADK warning 不阻塞 TWM 开发。后续如果要把 TWM 做成多阶段自动工作流，例如：

```text
build_state -> evaluate_rules -> forecast -> rollout -> validation_report -> dynamics_training_examples
```

建议直接用新的 ADK `Workflow` API 实现，而不要再新增旧 `SequentialAgent` 或 `LoopAgent`。

