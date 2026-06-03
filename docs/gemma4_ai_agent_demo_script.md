# Gemma 4 AI Agent 赛道演示脚本

本文档用于录制 GIS Data Agent 参加 Gemma 4 开发者大赛 AI Agent 赛道的 5 分钟演示视频。

演示目标：

- 展示 Gemma 4 在 GIS Data Agent 中的函数调用能力。
- 展示 NL2Semantic2SQL 如何把自然语言空间问题转成可执行 PostGIS SQL。
- 展示世界模型 v2.1 如何作为长任务工具被 Agent 调用。
- 展示 Tool Calling 日志和 Memory，满足 AI Agent 赛道说明。

## 录制前准备

准备过程不计入 5 分钟视频。

确认运行环境变量：

```text
OLLAMA_API_BASE=http://192.168.25.228:11434
NL2SQL_AGENT_MODEL=gemma4-26b-ollama
EMBEDDING_MODEL=nomic-embed-text-v2-moe
POSTGRES_HOST=119.3.175.198
POSTGRES_PORT=5432
```

确认 Ollama 模型：

```text
Gemma4:26b
nomic-embed-text-v2-moe:latest
```

启动并打开系统：

```text
http://localhost:8000
登录：admin / admin123
```

不要在视频中展示 API key、数据库密码、云账号凭证等敏感信息。

## 0:00-0:25 开场

画面：GIS Data Agent 主界面。

口播：

> 大家好，这是 GIS Data Agent，一个面向时空数据治理和空间决策的 Gemma 4 AI Agent。今天演示两个真实场景：第一，自然语言到语义增强 PostGIS SQL；第二，调用世界模型 v2.1 做土地利用规划。重点展示 Gemma 4 的函数调用、工具链和可审计执行日志。

## 0:25-1:55 场景一：NL2Semantic2SQL 空间查询

画面：聊天输入框。

输入：

```text
@NL2SQL 统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

等待执行完成。

画面重点依次停留：

1. 工具调用进度条或日志中的 `run_nl2semantic2sql`。
2. `user_question` 参数。
3. 生成 SQL。
4. 查询结果。

期望 SQL：

```sql
SELECT COUNT(DISTINCT b."Id")
FROM cq_buildings_2021 AS b
JOIN cq_osm_roads_2021 AS r
  ON ST_INTERSECTS(b.geometry, r.geometry)
WHERE r.bridge = 'T'
```

期望执行结果：

```text
status=ok
count=1
corrections=["semantic_distinct_join_count"]
```

口播：

> 这里不是普通 SQL 生成。用户只说“桥梁相交的建筑物轮廓数量”，Gemma 4 通过 `run_nl2semantic2sql` 工具进入语义 SQL 工作流。系统自动识别建筑物和道路表，生成 `ST_Intersects` 空间连接，并使用 `COUNT(DISTINCT)` 避免空间 join 造成重复计数。最后 SQL 在华为云 PostGIS 中真实执行，返回结果。

## 1:55-2:20 展示 Tool Calling 日志

画面：展开工具调用详情、调试日志或执行结果 JSON。

重点展示：

```text
tool_name=run_nl2semantic2sql
candidate_tables=[
  cq_osm_roads,
  cq_buildings_2021,
  cq_osm_roads_2021
]
few_shot_count=1
family=gemma
```

口播：

> 评审可以看到完整工具轨迹：自然语言问题、语义候选表、Gemma 4 生成的 SQL、后处理修正、数据库执行结果。这是可审计的 Agent 工具调用，而不是单次 prompt 输出。

## 2:20-3:45 场景二：世界模型 v2.1 调用

画面：聊天输入框。

输入：

```text
@Analyst 调用世界模型 v2.1。先检查状态，然后使用 Buchanan VA prepared_watershed 和 ensemble_seed0，运行 restoration 环境下的 MPC 规划：horizon=2，top_k=5，n_episodes=1，continuation=greedy，scoring=reward。
prepared_dir=D:/test/_publish/arcgis-farmland-mpc/runs/restoration/buchanan_va/prepared_watershed
ensemble_dir=D:/test/_publish/arcgis-farmland-mpc/paper/checkpoints/restoration/profiles/buchanan_va/watershed/ensemble_seed0
```

画面重点：

1. `world_model_v21_status`。
2. `world_model_v21_plan`。
3. 长任务执行日志。
4. 输出摘要和产物路径。

期望结果重点：

```text
status=ok
version=2.1.0
mode=tool4_mpc
env_kind=restoration
steps_run=50
n_blocks=562
n_selected=50
total_reward≈230.75
artifacts=mpc_summary.json, mpc_land_use.npy
```

口播：

> 第二个场景展示多步规划。Agent 先调用 `world_model_v21_status` 检查 Paper9 世界模型、ONNX ensemble 和数据目录，再调用长任务工具 `world_model_v21_plan` 执行 MPC。这个工具不是文本推理，而是真实运行地块级土地利用规划模型，并输出规划摘要和结果文件。

## 3:45-4:20 Memory 展示

画面：聊天输入框。

输入：

```text
请把本次演示保存为记忆：Gemma 4 完成了桥梁道路与建筑物相交的空间 NL2Semantic2SQL 查询，世界模型 v2.1 完成了 Buchanan VA restoration MPC 规划。关键词：Gemma4空间演示。
```

随后输入：

```text
检索关键词“Gemma4空间演示”的记忆。
```

画面重点：

- `save_memory`
- `recall_memories`
- 记忆内容返回

口播：

> AI Agent 赛道要求展示 Memory。这里系统把本次工具执行结果保存成用户空间记忆，后续可以被检索并作为上下文复用。

## 4:20-4:45 架构与提交对齐

画面：快速切到代码或 README，不要停太久。

展示路径：

```text
data_agent/model_gateway.py
data_agent/nl2semantic2sql_direct_agent.py
data_agent/nl2sql_executor.py
data_agent/toolsets/world_model_v21_tools.py
data_agent/memory.py
```

口播：

> 架构上，模型网关负责 Gemma 4/Ollama 路由；NL2Semantic2SQL 是高层函数调用工具；世界模型 v2.1 通过 ADK FunctionTool 和 LongRunningFunctionTool 暴露；Memory 工具负责持久化用户上下文。README 中提供 Docker 部署和环境变量说明，方便评审复现。

## 4:45-5:00 收尾

画面：回到系统结果页。

口播：

> 总结一下，GIS Data Agent 用 Gemma 4 把自然语言空间问题转成可执行 PostGIS 查询，并进一步调用世界模型完成土地利用规划。整个过程有工具调用、执行日志、记忆和真实数据库/模型结果，面向的是 GIS 数据治理中的真实痛点。

## 验证记录

空间 NL2Semantic2SQL 用例已做真实端到端验证：

```text
verified=true
status=ok
count=1
```

验证 SQL：

```sql
SELECT COUNT(DISTINCT b."Id")
FROM cq_buildings_2021 AS b
JOIN cq_osm_roads_2021 AS r
  ON ST_INTERSECTS(b.geometry, r.geometry)
WHERE r.bridge = 'T'
```

语义层命中：

```text
candidate_tables=[
  cq_osm_roads,
  cq_buildings_2021,
  cq_osm_roads_2021
]
few_shot_count=1
family=gemma
corrections=["semantic_distinct_join_count"]
```

世界模型 v2.1 用例已做真实端到端验证：

```text
status=ok
version=2.1.0
mode=tool4_mpc
env_kind=restoration
steps_run=50
n_blocks=562
n_selected=50
total_reward=230.7513
artifacts=mpc_summary.json, mpc_land_use.npy
```

## 录制注意事项

- 视频总时长严格控制在 5 分钟以内。
- 不展示数据库密码、API key、云账号信息。
- NL2Semantic2SQL 场景必须展示 `ST_INTERSECTS`，不要使用普通属性过滤查询。
- 世界模型 v2.1 场景要展示 `world_model_v21_status` 和 `world_model_v21_plan` 两个工具调用。
- Memory 场景要展示保存和检索，避免只口头描述。
- 讲解时强调“Gemma 4 + Native Function Calling + Tool Calling 日志 + Memory + 多步规划”。
