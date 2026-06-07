# Gemma 4 AI Agent 赛道代码说明：Memory 与 Tool Calling

本文档用于补充比赛提交材料中的代码说明。范围只限定两个主场景：

1. `nl2semantic2sql`：中文空间问题 -> 语义 grounding -> Gemma 4 SQL 合成 -> PostGIS 执行 -> 地图/结果/Memory。
2. `worldmodelv2.1`：短句触发 -> Gemma 4 工具规划 -> WorldModel v2.1 A/B/C/D pipeline -> Tool 4 MPC -> 地图/结果/Memory。

## 1. Gemma 4 调用入口

比赛 Docker 环境通过 `docker-compose.gemma4-demo.yml` 固定使用 `gemma4-26b-host228`：

```yaml
ROUTER_MODEL: gemma4-26b-host228
MODEL_FAST: gemma4-26b-host228
MODEL_STANDARD: gemma4-26b-host228
MODEL_PREMIUM: gemma4-26b-host228
MODEL_CONFIG_FORCE_ENV: "true"
NL2SQL_AGENT_MODEL: gemma4-26b-host228
NL2SQL_LLM_SCHEMA_MAPPER_MODEL: gemma4-26b-host228
OLLAMA_API_BASE: http://192.168.25.228:11434
```

`data_agent/model_gateway.py` 把该别名映射到 Ollama Chat 模型 `ollama_chat/Gemma4:26b`。这样路由、标准 Agent、NL2SQL Agent 和 schema mapper 都走同一个 Gemma 4 26B 模型。

## 2. @mention 路由

`data_agent/agent.py` 中 `_AGENT_MAP` 注册了比赛主场景的直接路由：

```python
_AGENT_MAP = {
    ...
    "NL2SQL": _build_mention_nl2sql_agent,
    "WorldModelV21": _build_mention_world_model_v21_agent,
}
```

用户输入：

```text
@NL2SQL 统计重庆2021年道路网络中所有桥梁道路（bridge = T）的总长度，单位为公里。
```

或：

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 dongxing 数据集运行一次快速县域 MPC 规划。
```

前端和后端会把请求交给对应 Agent，而不是让通用 Agent 自由猜测工具。

## 3. NL2Semantic2SQL Tool Calling

### 3.1 代码路径

主路径：

```text
data_agent/agent.py
  -> _build_mention_nl2sql_agent()
  -> data_agent/nl2semantic2sql_direct_agent.py
  -> data_agent/nl2sql_executor.py::run_nl2semantic2sql()
  -> data_agent/nl2sql_grounding.py
  -> data_agent/nl2sql_semantic_rewrite.py
  -> data_agent/sql_postprocessor.py
  -> PostGIS
  -> data_agent/nl2sql_presentation.py
```

### 3.2 ADK function_call 事件

Gemma/Ollama demo 路径中，`@NL2SQL` 使用显式路由和确定性 ADK function call 事件。`DirectNL2SemanticSQLAgent` 会先向 ADK event stream 写入工具调用：

```python
types.Part.from_function_call(
    name="run_nl2semantic2sql",
    args={"user_question": question},
)
```

然后执行真实工具：

```python
result = run_nl2semantic2sql(question)
```

再写入工具响应：

```python
types.Part.from_function_response(
    name="run_nl2semantic2sql",
    response={"result": result},
)
```

这保证运行日志中能看到 `run_nl2semantic2sql` 的工具调用轨迹。Gemma 4 的核心作用在 `run_nl2semantic2sql()` 内部的 SQL 合成环节，而不是让模型直接输出未经执行的自然语言答案。

### 3.3 空间 SQL harness

`run_nl2semantic2sql()` 内部执行空间 SQL harness：

1. `build_nl2sql_context()` 从语义层和 PostGIS schema 中找候选表、候选列、空间字段、SRID、样例值和 few-shot。
2. Gemma 4 26B 在 grounded prompt 下生成 SQL。
3. `apply_semantic_sql_rewrites()` 修复空间 SQL 常见问题，例如：
   - `ST_Length(ST_Transform(geometry, 3857))` 改为 `ST_Length(geometry::geography)`。
   - `ST_DWithin(a.geometry, b.geometry, 100)` 改为 `ST_DWithin(a.geometry::geography, b.geometry::geography, 100)`。
   - 空间 join 计数按语义需要使用或避免 `COUNT(DISTINCT ...)`。
4. `postprocess_sql()` 做 AST 安全检查、标识符修正、只读限制和大表保护。
5. PostGIS 真实执行 SQL。
6. `nl2sql_presentation.py` 把结构化结果转成中文摘要，并在需要时生成地图图层。

### 3.4 比赛演示中的 NL2SQL 证据

推荐展示三条空间查询：

| 查询 | 关键证据 |
|---|---|
| 桥梁道路总长度 | SQL 使用 `ST_Length(CAST(geometry AS GEOGRAPHY)) / 1000.0`，结果约 `1376.5976 km` |
| 最长桥梁 100m 内 POI | SQL 使用 CTE 找最长桥梁，并用 `ST_DWithin(... GEOGRAPHY ..., 100)`，结果 `35` |
| 与桥梁相交的建筑物轮廓 | SQL 使用 `ST_Intersects` 和 `COUNT(DISTINCT b."Id")`，结果 `1` |

运行日志截图要展开 `run_nl2semantic2sql` Step，展示函数参数、SQL、候选表、few-shot 数量、语义修正和执行结果。

## 4. WorldModel v2.1 Tool Calling

### 4.1 代码路径

主路径：

```text
data_agent/agent.py
  -> _build_mention_world_model_v21_agent()
  -> data_agent/toolsets/world_model_v21_tools.py::WorldModelV21Toolset
  -> data_agent/world_model_v21.py::WorldModelV21Service
  -> Paper9 farmland_mpc package
  -> optimized_dltb.shp / optimized_dltb.fgb / mpc_summary.json
  -> data_agent/world_model_v21_presentation.py
```

### 4.2 Gemma 4 驱动的多步工具规划

`MentionWorldModelV21` 是标准 `LlmAgent`，绑定 `WorldModelV21Toolset()`。它的 instruction 明确约束：

- 必须先调用 `world_model_v21_status`。
- 默认调用 `world_model_v21_pipeline` 展示完整 A/B/C/D 链路。
- 用户提到 `dongxing` 或 `东兴` 时，工具参数必须设置 `dataset="dongxing"`。
- 用户提到 `bishan` 或 `璧山` 时，工具参数必须设置 `dataset="bishan"`。
- 用户没有给路径时，路径参数留空，让工具根据 dataset preset 自动解析。

推荐比赛轨迹：

```text
world_model_v21_status -> world_model_v21_pipeline
```

### 4.3 Toolset 暴露的函数

`data_agent/toolsets/world_model_v21_tools.py` 暴露：

| 工具 | 类型 | 作用 |
|---|---|---|
| `world_model_v21_status` | `FunctionTool` | 检查 Paper9 repo、默认目录、ONNX、PROJ runtime |
| `world_model_v21_prepare` | `LongRunningFunctionTool` | Tool 1，DLTB + DEM -> prepared data |
| `world_model_v21_sample` | `LongRunningFunctionTool` | Tool 2，prepared -> transition samples |
| `world_model_v21_train` | `LongRunningFunctionTool` | Tool 3，samples -> ONNX ensemble |
| `world_model_v21_plan` | `LongRunningFunctionTool` | Tool 4，MPC planning |
| `world_model_v21_pipeline` | `LongRunningFunctionTool` | A/B/C/D 编排，支持复用已有产物 |

### 4.4 A/B/C/D pipeline

`world_model_v21_pipeline()` 最终进入 `WorldModelV21Service.run_pipeline()`：

```text
A / Tool 1 Prepare
B / Tool 2 Sample
C / Tool 3 Train
D / Tool 4 Plan
```

演示时设置 `reuse_existing=true`，所以 A/B/C 对已有 Bishan/Dongxing 产物返回 `skipped_reused`，D/Tool 4 真实运行快速 MPC：

```text
A / Tool 1 Prepare: skipped_reused
B / Tool 2 Sample: skipped_reused
C / Tool 3 Train: skipped_reused
D / Tool 4 Plan: ok
```

这比只显示一个 `world_model_v21_plan` 更符合比赛对“多步规划”的要求。

### 4.5 数据集 preset

工具层内置 demo 数据集：

| dataset | prepared_dir | ensemble_dir |
|---|---|---|
| `bishan` | `/app/bishan-runs/prepared` | `/app/bishan-runs/prepared/ensemble_seed0` |
| `dongxing` | `/app/dongxing-runs/prepared` | `/app/dongxing-runs/prepared/ensemble_seed0` |

这使用户只需要输入短句，不需要在对话框里手写路径和 MPC 参数。

### 4.6 地图输出

Tool 4 产物包括：

```text
mpc_summary.json
mpc_land_use.npy
optimized_dltb.shp
optimized_dltb.fgb
```

地图按 `CHG_FLAG` 分类显示：

- 灰色：保持不变。
- 红色：耕地 -> 林地。
- 绿色：林地 -> 耕地。

运行日志截图要展开 `world_model_v21_status` 和 `world_model_v21_pipeline`，同时展示 A/B/C/D 阶段状态和地图事件。

## 5. Memory 代码说明

### 5.1 Memory 和历史会话的区别

比赛要求中的 Memory 指 Agent 可持久化并检索上下文，不等同于聊天历史。聊天历史来自 Chainlit `Thread/Step`；Memory 来自 ADK memory service 和 `agent_user_memories`。

### 5.2 代码路径

```text
data_agent/conversation_memory.py
  -> PostgresMemoryService(BaseMemoryService)

data_agent/memory.py
  -> save_memory()
  -> recall_memories()
  -> save_auto_extract_memories()
  -> list_auto_extract_memories()

data_agent/app.py
  -> Runner(..., memory_service=get_memory_service())
  -> 工具响应后自动提取 facts
  -> 保存 analysis_result / auto_extract

data_agent/frontend_api.py
  -> /api/user/memories
  -> /api/memory/search
  -> /api/agent/run-logs
```

### 5.3 工具级 Memory 演示

比赛录制建议显式展示：

```text
请把本次演示保存为记忆：Gemma 4 完成了桥梁道路与建筑物相交的空间 NL2Semantic2SQL 查询，世界模型 v2.1 完成了 Bishan 和 Dongxing 县域 MPC 规划。关键词：Gemma4空间演示。
```

随后检索：

```text
检索关键词“Gemma4空间演示”的记忆。
```

运行日志中应展示：

```text
save_memory -> recall_memories
```

### 5.4 自动 Memory

`data_agent/app.py` 在分析结束后会尝试从响应中提取 facts，并调用 `save_auto_extract_memories()`。自动提取有触发条件、去重和配额限制，所以比赛主证据应该是工具级 `save_memory` / `recall_memories`，自动 Memory 作为补充截图。

## 6. 运行日志代码说明

`data_agent/app.py` 捕获 ADK event stream 中的 `function_call` 和 `function_response`，并写入 Chainlit Step。`data_agent/frontend_api.py` 的 `/api/agent/run-logs` 会聚合最近 runs：

```text
tool_count
memory_count
map_event_count
step timeline
tool args / response 摘要
```

前端入口：

```text
工作台 -> 平台运营 -> 运行日志
```

对应代码：

```text
frontend/src/components/datapanel/AgentRunLogsTab.tsx
```

比赛截图建议至少保留两张：

1. `@NL2SQL` 最新 run：展开 `run_nl2semantic2sql`，展示 SQL、结果和候选表。
2. `@WorldModelV21` 最新 run：展开 `world_model_v21_status -> world_model_v21_pipeline`，展示 A/B/C/D 阶段。

## 7. 代码说明结论

本项目的比赛提交重点不是通用聊天能力，而是 Gemma 4 + ADK Tool Calling 的可审计 GIS 执行链路：

- `nl2semantic2sql` 展示空间 SQL grounding、Gemma 4 SQL 合成、PostGIS 执行和地图输出。
- `worldmodelv2.1` 展示 Gemma 4 驱动的多步工具规划、A/B/C/D pipeline 和县域 MPC 真实产物。
- Memory 展示工具级持久化和检索，运行日志展示每次工具调用和 Memory 的可审计证据。
