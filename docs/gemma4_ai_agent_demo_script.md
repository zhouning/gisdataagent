# Gemma 4 AI Agent 赛道演示脚本

本文档用于录制 GIS Data Agent 参加 Gemma 4 开发者大赛 AI Agent 赛道的 5 分钟演示视频。

比赛 README 对齐点：

- AI Agent 赛道需要展示 Native Function Calling、Tool Calling、Memory 和多步规划。
- 核心代码需要包含 Gemma 4 调用逻辑。
- 演示视频控制在 5 分钟以内。
- 提交文档需要说明本地安装、环境变量和可复现运行方式。

本次演示固定使用本机 Windows 测试环境，模型来源为 `http://192.168.25.228:11434/` 上的 `Gemma4:31b`。

## 录制前真实验证基线

准备过程不计入 5 分钟视频。录制前先确认以下基线，不在视频里展示任何密码、API key 或云账号凭证。

```text
OS=Windows
repo=D:\adk
branch=feat/v12-extensible-platform
git sync=HEAD...origin/feat/v12-extensible-platform -> 0 0

OLLAMA_API_BASE=http://192.168.25.228:11434
MODEL_FAST=gemma4-31b-host228
MODEL_STANDARD=gemma4-31b-host228
MODEL_PREMIUM=gemma4-31b-host228
ROUTER_MODEL=gemma4-31b-host228
MODEL_CONFIG_FORCE_ENV=true
NL2SQL_AGENT_MODEL=gemma4-31b-host228
NL2SQL_LLM_SCHEMA_MAPPER_MODEL=gemma4-31b-host228
EMBEDDING_MODEL=nomic-embed-text-v2-moe-host228

POSTGRES_HOST=119.3.175.198
POSTGRES_PORT=5432

PAPER9_FARMLAND_MPC_REPO=D:\test\_publish\arcgis-farmland-mpc
PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR=D:\test\_publish\arcgis-farmland-mpc\runs\restoration\buchanan_va\prepared_watershed
PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR=D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\restoration\profiles\buchanan_va\watershed\ensemble_seed0
```

已验证模型标签：

```text
Gemma4:31b
  parameter_size=31.3B
  capabilities=completion, tools, thinking

nomic-embed-text-v2-moe:latest
  embedding_length=768
  capabilities=embedding
```

已验证应用模型路由：

```text
standard tier=gemma4-31b-host228
model_class=LiteLlm
model=ollama_chat/Gemma4:31b
family=gemma
```

启动并打开系统：

```text
http://localhost:8000
登录：admin / admin123
```

## 场景一：真实 PostGIS NL2Semantic2SQL

用户输入：

```text
@NL2SQL 统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

验证工具链：

```text
tool_name=run_nl2semantic2sql
model=Gemma4:31b @ http://192.168.25.228:11434
database=PostGIS on 119.3.175.198:5432
```

真实验证结果：

```text
status=ok
execution.rows=1
execution.data[0].count=1
candidate_tables=cq_osm_roads_2021, cq_buildings_2021, cq_osm_roads
few_shot_count=0
family=gemma
corrections=semantic_column_alias
```

已执行 SQL：

```sql
SELECT COUNT(DISTINCT b."Id")
FROM cq_buildings_2021 AS b
JOIN cq_osm_roads_2021 AS r
  ON ST_INTERSECTS(b.geometry, r.geometry)
WHERE r.bridge = 'T'
```

地图层验证：

```text
golden_building_count=1
building_feature_count=31
bridge_road_count=19
map_center=[29.61213837765004, 106.54456038199999]
map_zoom=10
layers=
  相交建筑几何行 (31 个)
  bridge=T 道路线 (19 条)
```

录制重点：

- 展示 `run_nl2semantic2sql` 工具调用，而不是只展示模型文本输出。
- 展示自然语言参数、候选表、Gemma 4 生成 SQL、后处理修正和真实数据库执行结果。
- 明确解释 `count=1` 是 `COUNT(DISTINCT b."Id")` 的聚合结果；地图上展示的是满足相交条件的几何行，数量为 31。
- 停留在 `ST_INTERSECTS` 和 `COUNT(DISTINCT)`，说明空间 join 和去重计数是关键。

口播建议：

> 用户只提出一个自然语言空间问题，Gemma 4 通过 `run_nl2semantic2sql` 进入语义 SQL 工作流。系统识别建筑物和道路表，生成 PostGIS 的 `ST_INTERSECTS` 空间连接，并使用 `COUNT(DISTINCT)` 避免空间 join 重复计数。SQL 已在真实 PostGIS 数据库执行，返回建筑物轮廓聚合数量为 1，同时右侧地图展示参与相交判断的建筑几何行和桥梁道路线。

## 场景二：真实 WorldModelV21 Buchanan MPC

用户输入：

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，再使用系统默认的 Buchanan VA restoration 数据运行一次快速 MPC 规划。参数：env_kind=restoration，horizon=2，top_k=5，n_episodes=1，continuation=greedy，scoring=reward。使用默认 prepared_dir 和 ensemble_dir，不要要求我补充路径。
```

验证工具链：

```text
world_model_v21_status -> world_model_v21_plan
repo=D:\test\_publish\arcgis-farmland-mpc
prepared_dir=...\runs\restoration\buchanan_va\prepared_watershed
ensemble_dir=...\paper\checkpoints\restoration\profiles\buchanan_va\watershed\ensemble_seed0
```

真实 status 验证：

```text
status=ready
version=2.1.0
repo_exists=true
importable=true
onnx_member_count=3
```

真实 plan 验证：

```text
plan_status=ok
mode=tool4_mpc
env_kind=restoration
steps_run=50
n_blocks=562
n_parcels=562
n_selected=50
total_reward=230.75136300693933
budget_used=132013.76804078548
budget_fraction_used=0.6600688402039274
map_update_queued=true
```

产物验证：

```text
artifacts=mpc_summary.json, mpc_land_use.npy, restoration_mpc_units.geojson
map_layer=world_model_v21/20260605_114726_601605/restoration_mpc_units.geojson
```

录制重点：

- 先展示 `world_model_v21_status`，再展示 `world_model_v21_plan`，突出多步规划。
- 展示 3 个 ONNX ensemble member、Buchanan VA restoration 默认数据目录和长任务运行日志。
- 展示规划摘要、地图图层和产物文件。
- 说明这是地块级土地利用规划模型执行，不是纯文本推理。

口播建议：

> 第二个场景展示多步工具规划。Agent 先检查 Paper9 世界模型、ONNX ensemble 和默认数据目录，再调用长任务工具运行 Buchanan VA restoration MPC。这个过程真实加载 562 个规划单元和 3 个 ONNX 成员，完成 50 步规划，输出规划摘要、Numpy 结果和可视化 GeoJSON 图层。

## 扩展验证：空间 SQL 与区县世界模型

这部分不进入 5 分钟主录屏，只作为答辩或提交说明中的真实验证补充。

新增 NL2Semantic2SQL 空间场景验证：

```text
model=Gemma4:31b @ http://192.168.25.228:11434
database=PostGIS on 119.3.175.198:5432
questions=5
generation_status_ok=5/5
exact_top10_match=2/5
covered_patterns=ST_INTERSECTS, ST_DWITHIN, ST_Length, grouped contains count, ST_Union area
```

验证结论：

- `CQ_GEO_HARD_10` 和 `CQ_GEO_HARD_14` 与 golden SQL 精确匹配。
- `CQ_GEO_HARD_25` 道路长度聚合、`CQ_GEO_MEDIUM_30` union 面积聚合为数值等价，差异来自别名或小数精度。
- `CQ_GEO_MEDIUM_23` 暴露真实问题：当前 `COUNT(DISTINCT poi."ID")` 修正会改变 grouped POI 行计数语义，后续需要按问题意图限制去重注入。

WorldModelV21 区县数据验证：

```text
Bishan:
  prepared_dir=D:\test
  ensemble_dir=D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\bishan\shipped_onnx
  onnx_member_count=3
  env_build=ok
  swappable_parcels=52515
  blocks=2600
  plan_status=blocked_by_memory
  error=Unable to allocate 401 MiB for shape (2380, 2600, 17) float32

Dongxing / Neijiang Dongxing:
  current_live_onnx_member_count=0
  available_checkpoints=.pt state dicts
  live_plan_status=expected_rejected_without_onnx
  historical_repro_reward_mean=96.29512009811995
  historical_repro_slope_pct_mean=-0.5741333407356206
```

答辩说明：

> 主演示选择 Buchanan VA，是因为当前 Windows 本机可以完整完成 status -> plan -> GeoJSON 图层输出。Bishan 已通过真实数据、ONNX 和环境构建验证，但区县级规划在本机 MPC 阶段触发内存不足；Dongxing 当前只有 `.pt` 研究检查点和历史复现实验摘要，ADK v2.1 实时入口需要先导出 ONNX ensemble 后才能运行同一路径。

## 场景三：真实 Postgres Memory 保存与检索

保存输入：

```text
请把本次演示保存为记忆：Gemma 4 完成了桥梁道路与建筑物相交的空间 NL2Semantic2SQL 查询，世界模型 v2.1 完成了 Buchanan VA restoration MPC 规划。关键词：Gemma4空间演示。
```

检索输入：

```text
检索关键词“Gemma4空间演示”的记忆。
```

真实 DB 验证：

```text
memory_table=agent_user_memories
user=demo_gemma4_memory_user
key=Gemma4空间演示_20260605_114845
save_status=success
recall_status=success
recall_count=1
memory_type=analysis_result
```

记忆内容包含：

```text
model=Gemma4:31b @ http://192.168.25.228:11434
nl2sql=COUNT(DISTINCT)=1, map geometry rows=31, bridge roads=19
world_model=steps_run=50, n_blocks=562, n_selected=50, total_reward=230.75136300693933
```

录制重点：

- 展示 `save_memory` 和 `recall_memories` 两个工具调用。
- 展示检索返回的是 Postgres 中持久化的用户空间记忆。
- 说明 Memory 可把已执行工具结果沉淀为后续上下文，而不是临时聊天缓存。

口播建议：

> AI Agent 赛道要求展示 Memory。这里系统把本次 NL2SQL 和 WorldModel 的真实执行结果保存为用户空间记忆，随后按关键词从 Postgres 检索回来。后续对话可以复用这些上下文。

## Memory 考察项边界

比赛 README 中 AI Agent 赛道的 Memory 要点，应理解为 Agent 能把有价值的用户偏好、分析结果或上下文事实持久化，并在后续请求中检索复用。演示时优先展示可审计的工具级记忆能力：

```text
save_memory(memory_type="analysis_result", key="Gemma4空间演示_...", value={...})
recall_memories(memory_type="analysis_result", keyword="Gemma4空间演示")
storage=PostgreSQL agent_user_memories
scope=per-user persistent memory
```

和 Memory 相关但不作为主评分点的能力：

- 个人信息里的“智能记忆”：展示系统自动提取的 `auto_extract` 记忆，支持列表和删除，属于长期记忆管理 UI。
- 右侧数据面板“记忆”：搜索 `region`、`viz_preference`、`analysis_result`、`auto_extract`、`custom` 等用户记忆。
- 对话框“历史会话”：恢复 Chainlit `Thread/Step` 对话记录，属于会话历史/产品体验，不等同于 Agent Memory；可作为辅助展示，但不要替代 `save_memory`/`recall_memories`。

录制建议：

> Memory 这里不只展示历史聊天列表，而是让 Gemma 4 调用记忆工具，把已经执行过的空间 SQL 和世界模型规划结果保存到用户级持久化记忆中，再通过关键词检索回来。历史会话用于恢复 UI 对话线程，智能记忆用于管理自动提取事实，它们是增强体验；比赛主证据是工具调用日志和 Postgres 持久化结果。

## 5 分钟时间分配

```text
0:00-0:20  开场：GIS Data Agent + Gemma 4 AI Agent 赛道对齐
0:20-1:50  场景一：真实 PostGIS NL2Semantic2SQL
1:50-2:15  展示 NL2SQL Tool Calling 日志和地图层差异
2:15-3:45  场景二：WorldModelV21 status -> plan 多步规划
3:45-4:25  场景三：Memory 保存与检索
4:25-4:50  架构与代码路径对齐
4:50-5:00  收尾总结
```

架构展示路径：

```text
data_agent/model_gateway.py
data_agent/embedding_gateway.py
data_agent/nl2semantic2sql_direct_agent.py
data_agent/nl2sql_executor.py
data_agent/nl2sql_presentation.py
data_agent/toolsets/world_model_v21_tools.py
data_agent/world_model_v21.py
data_agent/memory.py
```

## 录制注意事项

- 不展示数据库密码、API key、云账号、OBS AK/SK、OAuth secret 等敏感信息。
- 视频中只展示 host、端口、模型名、工具名、SQL 和结果摘要。
- PowerShell 一次性命令不要直接传原始中文 here-string；需要使用 UTF-8 文件或 `\u` 转义，避免中文变成 `????` 后影响语义候选表。
- Windows 本机 ArcPy worker 当前会打印启动失败提示；本次 NL2SQL、WorldModelV21 和 Memory 场景均不依赖 ArcPy，该提示不影响演示。
- 演示时不要只展示单元测试或评测封装，要展示真实数据库、真实 Buchanan 数据和真实 Memory 持久化结果。
- 如被问到 Bishan 或 Dongxing，不要在 5 分钟视频中临时运行区县 MPC；直接展示上面的真实验证边界和后续工程项。
- 结尾强调：Gemma 4 + Function Calling + Tool Calling 日志 + Memory + 多步规划 + 真实 GIS 数据/模型执行。
