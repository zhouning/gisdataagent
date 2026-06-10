# Gemma 4 AI Agent 赛道演示脚本

本文档用于录制 GIS Data Agent 参加 Gemma 4 开发者大赛 AI Agent 赛道的 5 分钟演示视频，并记录 2026-06-10 最新端到端刷新结果。

比赛 README 对齐点：

- AI Agent 赛道需要展示 Native Function Calling / Tool Calling、Memory 和多步规划。
- 赛道 A 提交建议提供运行日志截图；本项目使用“工作台 -> 平台运营 -> 运行日志”展示可截图的 Thread/Step、Tool Calling、Memory、地图事件摘要和“完整详情”弹窗。
- 核心代码需要包含 Gemma 4 调用逻辑。
- 演示视频控制在 5 分钟以内。
- 必须准备技术报告，阐述为何主线选择 Gemma 4 26B MoE，并说明未采用 31B Dense 的取舍，以及 GIS Data Agent 的架构设计。
- 提交文档需要说明本地安装、环境变量和可复现运行方式；本项目参赛主线使用纯 Docker / Docker Compose，不把 K8s 作为评审必需环境。

## 提交材料硬性清单

1. 核心代码说明：
   - 明确指出 Gemma 4 调用逻辑在 `data_agent/model_gateway.py`、模型配置和 NL2SQL / WorldModelV21 Agent 调用链中的位置。
   - 明确说明不是单纯 Prompt 工程，而是通过 Agent 路由、Tool Calling、结构化工具返回、PostGIS / WorldModel 工具执行形成原生函数调用闭环。

2. Memory 与 Tool Calling 代码说明：
   - `nl2semantic2sql` 场景：说明 `@NL2SQL` 路由、`run_nl2semantic2sql` 工具调用、SQL 生成/语义修正/PostGIS 执行、结果地图和自动 Memory 提取。
   - `worldmodelv2.1` 场景：说明 `world_model_v21_status`、`world_model_v21_pipeline` 的 A/B/C/D 多步规划，以及 Tool 4 MPC 真实运行产物。
   - 自然语言优化场景：不使用 `@`，通过“我有哪些数据”和“基于 xx 数据进行耕地空间布局优化分析”展示 GENERAL -> OPTIMIZATION 自动路由、文件发现、资产目录和 DRL 工具调用。
   - 使用“工作台 -> 平台运营 -> 运行日志”截图展示 Thread/Step、Tool Calling、Memory、Step Timeline 和完整详情。
   - 代码说明入口：`docs/gemma4_ai_agent_code_walkthrough.md`。

3. 技术报告：
   - 单独准备技术报告，覆盖模型选型理由、Gemma 4 规格选择、架构设计、关键模块、函数调用链路、真实数据与部署方式。
   - 当前报告入口：`docs/gemma4_ai_agent_technical_report.md`。
   - 报告中必须把 `nl2semantic2sql` 和 `worldmodelv2.1` 作为主场景，不泛泛描述平台能力。

4. README / About 刷新：
   - `README.md` 需要围绕 Gemma 4 AI Agent 赛道重新组织，而不是保留泛平台介绍。
   - README 需包含一键 Docker Compose 启动、环境变量、模型配置、演示脚本、运行日志截图路径、技术报告入口。
   - GitHub About 建议改成比赛导向的一句话，例如：`Gemma 4 powered GIS Data Agent for NL2Semantic2SQL and WorldModel v2.1 planning with native tool calling and memory.`

## 录制前真实验证基线

准备过程不计入 5 分钟视频。录制前不要展示任何密码、API key、数据库连接串或云账号凭证。

```text
local_retest_date=2026-06-10
local_os=macOS
repo=/Users/zhouning/gisdataagent
branch=feat/v12-extensible-platform
local_app_url=http://127.0.0.1:8000
paper9_repo=/Users/zhouning/arcgis-farmland-mpc
paper9_commit=aefc9e85a0b8b4f8443bc5785e6f7f3016286abb
paper9_version=0.2.1
proj_data_dir=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj
docker_compose_file=docker-compose.gemma4-demo.yml
docker_services=gisdataagent-app-1, gisdataagent-db-1, gisdataagent-redis-1 healthy
docker_db=gisdataagent-db-1 on localhost:5433, database=gis_agent, schema=public
docker_timezone=Asia/Shanghai, API timestamps include +08:00
k8s_status=gis-agent namespace workloads scaled to 0; not part of demo path
```

模型与录制环境：

```text
OLLAMA_API_BASE=http://host.docker.internal:11434
MODEL_FAST=gemma4-26b-ollama
MODEL_STANDARD=gemma4-26b-ollama
MODEL_PREMIUM=gemma4-26b-ollama
ROUTER_MODEL=gemma4-26b-ollama
MODEL_CONFIG_FORCE_ENV=true
NL2SQL_AGENT_MODEL=gemma4-26b-ollama
NL2SQL_LLM_SCHEMA_MAPPER_MODEL=gemma4-26b-ollama
EMBEDDING_MODEL=nomic-embed-text-v2-moe
```

已验证模型标签：

```text
Gemma4:26b
  parameter_size=25.8B
  capabilities=completion, tools, thinking

nomic-embed-text-v2-moe:latest
  embedding_length=768
  capabilities=embedding
```

本次本地测试命令：

```bash
docker compose -f docker-compose.gemma4-demo.yml up -d --build app
docker compose -f docker-compose.gemma4-demo.yml up -d db redis

docker exec gisdataagent-db-1 psql -U postgres -d gis_agent -c \
  "SELECT 'roads' AS table_name, count(*) FROM cq_osm_roads_2021
   UNION ALL SELECT 'buildings', count(*) FROM cq_buildings_2021
   UNION ALL SELECT 'poi', count(*) FROM cq_amap_poi_2024
   UNION ALL SELECT 'historic', count(*) FROM cq_historic_districts
   UNION ALL SELECT 'memory', count(*) FROM agent_user_memories
   ORDER BY table_name;"

env POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 \
  POSTGRES_DATABASE=gis_agent POSTGRES_USER=agent_user \
  POSTGRES_PASSWORD=<redacted> \
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
    data_agent/test_sql_postprocessor.py \
    data_agent/test_nl2sql_semantic_rewrite.py \
    data_agent/test_nl2sql_executor.py \
    data_agent/test_nl2sql_cq_eval_gemma.py \
    data_agent/test_nl2sql_tools.py -q

# result: 143 passed

env PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  /Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
    data_agent/test_world_model_v21.py \
    data_agent/test_world_model_v21_tools.py \
    data_agent/test_world_model_v21_routes.py \
    data_agent/test_world_model_v21_presentation.py \
    data_agent/test_pipeline_helpers.py -q

# result: 45 passed

/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_frontend_api.py -k agent_run_logs -q

# result: 9 passed, 75 deselected
```

最新回归摘要：

```text
latest_full_local_tests=261 passed, 11 skipped
container_run_logs_pipeline_subset=90 passed
targeted_run_logs_api_tests=9 passed, 75 deselected
run_logs_timezone=+08:00 / Asia/Shanghai
run_logs_internal_reasoning_leak=false
```

纯 Docker PostGIS 数据验证：

```text
postgis_extensions=postgis, vector
postgres_database=gis_agent
postgres_schema=public
cq_tables_public=22
cq_osm_roads_2021=50366
cq_buildings_2021=107035
cq_amap_poi_2024=1194351
cq_historic_districts=20
agent_user_memories=15
explain_row_estimate(SELECT COUNT(*) FROM cq_osm_roads_2021)=1
explain_row_estimate(SELECT * FROM cq_amap_poi_2024)=1194474
memory_smoke=transactional insert count 1, rollback count 0
```

## 运行日志 tab 刷新验证

位置：`工作台 -> 平台运营 -> 运行日志`。

本轮已修复用例 7 暴露的问题：

- 时间显示使用 Docker/app 的 `Asia/Shanghai` 口径，API 返回时间包含 `+08:00`，不再表现为 UTC 漂移。
- 运行日志 API 会清理历史 Step 中泄露的英文内部推理文本，验证口径为 `run_logs_internal_reasoning_leak=false`。
- 单条记录展开后展示最终回答、工具输入/输出、Step 输入/输出摘要；若下拉区域仍不足以查看全文，点击“完整详情”打开完整 modal。
- 前端文件为 `frontend/src/components/datapanel/AgentRunLogsTab.tsx`；后端聚合接口为 `data_agent/frontend_api.py` 的 `/api/agent/run-logs`。
- 如果浏览器仍显示旧布局，先对 `http://127.0.0.1:8000` 做 hard refresh，避免缓存旧 bundle。

## 新增场景：无 @ 自动数据发现与耕地优化

这个场景用于证明 GIS Data Agent 不是只能靠 `@NL2SQL` / `@WorldModelV21` 显式路由；用户直接在对话框提问时，系统仍能通过意图路由进入多智能体优化工作流。

数据进入方式：

```text
user_upload_zip=/Users/zhouning/Downloads/shp/斑竹村10000.zip
source_shp=/Users/zhouning/Downloads/shp/斑竹村10000.shp
docker_uploaded_zip=/app/data_agent/uploads/admin/斑竹村10000.zip
docker_extracted_shp=/app/data_agent/uploads/admin/斑竹村10000/斑竹村10000.shp
asset_catalog_name=斑竹村10000.shp
asset_code=DA-VEC-ADM-2026-0001
features=10653
crs=EPSG:4523
required_fields=DLMC, Slope
dlmc_main=旱地 3489; 水田 3248; 果园 1520; 有林地 995
```

录制步骤：

1. 在聊天框上传 `斑竹村10000.zip`。
2. 不加 `@`，直接输入：

```text
我有哪些数据
```

预期路由和工具：

```text
intent=GENERAL
reason=用户在查询现有的数据库内容或数据资产
expected_tools=list_user_files, list_data_assets/search_data_assets
expected_visible_path=斑竹村10000/斑竹村10000.shp
sidecar_visibility=隐藏 .dbf/.shx/.prj/.cpg 等 shapefile sidecar
```

3. 继续不加 `@`，输入：

```text
基于斑竹村10000数据进行耕地空间布局优化分析
```

预期路由和工作流：

```text
intent=OPTIMIZATION
pipeline_type=farmland_optimization
pipeline=Farmland Optimization Workflow (耕地空间布局优化)
workflow=FarmlandDataPreparation -> FarmlandDRLOptimizer -> FarmlandOptimizationVisualizer -> FarmlandOptimizationSummary
core_tools=drl_model, visualize_interactive_map
input_path=斑竹村10000/斑竹村10000.shp
resolved_path=/app/data_agent/uploads/admin/斑竹村10000/斑竹村10000.shp
```

本轮容器内真实验证：

```text
router_case_1="我有哪些数据" => GENERAL
router_case_2="基于斑竹村10000数据进行耕地空间布局优化分析" => OPTIMIZATION
list_user_files_contains=斑竹村10000/斑竹村10000.shp
data_catalog_register=ok
drl_model_status=ok
comparison_map_status=ok
pdf_report_export=ok, output=Analysis_Report.pdf, embeds_optimized_png=true
latest_drl_output=/app/data_agent/uploads/admin/optimized_data_ee9235b4.shp
latest_drl_map=/app/data_agent/uploads/admin/optimized_map_1d74f23d.png
conversions=200
pairs=0
net_change=-130
```

最新修复口径：

- Farmland Optimization Workflow 的最终回答会优先使用 `drl_model` 工具 JSON 生成事实型摘要，不再依赖 LLM 自行改写 DRL 指标。
- 对 `Conversions/Pairs/Net Change` 做原样展示；当 `Pairs=0` 时明确说明未形成成对置换，当 `Net Change` 不为 0 时明确说明存在地类数量净变化。
- 优化对比地图必须由 `visualize_interactive_map(original_data_path, optimized_data_path)` 生成并写入右侧地图；若 LLM 漏调，后端会强制补跑 DRL/地图兜底。
- “导出 PDF 报告”必须生成 PDF 而不是 Word 回退，并嵌入最新优化 PNG。
- GENERAL / OPTIMIZATION / GOVERNANCE 等管线的最终文本会先缓冲并清理英文内部推理，再发送给前端。

录制口径：

- 这个场景强调“无 `@` 自然语言触发”和“多智能体优化工作流”，不是 WorldModel v2.1。
- 当前斑竹村 10000 数据默认 DRL v7 会生成优化产物，但 `Pairs=0, Net Change=-130`；录制时不要口播“完美面积守恒”或“成对置换已经达成”，只说“自动完成耕地布局优化推理并生成结果 Shapefile/PNG”。
- OPTIMIZATION 属于高成本管线，前端可能先弹出分析方案确认；录制时点击“确认”后继续执行。

## 场景一：真实 PostGIS NL2Semantic2SQL

用户输入：

```text
@NL2SQL 统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

验证工具链：

```text
tool_name=run_nl2semantic2sql
model=Gemma4:26b @ http://host.docker.internal:11434
database=PostGIS on configured POSTGRES_* / DATABASE_URL
docker_database=gisdataagent-db-1, exposed at localhost:5433 for local tests
```

期望 SQL 形态：

```sql
SELECT COUNT(DISTINCT b."Id")
FROM cq_buildings_2021 AS b
JOIN cq_osm_roads_2021 AS r
  ON ST_Intersects(b.geometry, r.geometry)
WHERE r.bridge = 'T';
```

纯 Docker SQL 实测结果：

```text
bridge_buildings_distinct=1
bridge_building_join_rows=33
bridge_roads=7532
named_bridge_roads=2111
bridge_road_length_km=1376.597572365853
pois_within_100m_longest_bridge=35
buildings_near_any_bridge_1000m=86167
historic_district_sample=慈云寺-米市街-龙门浩历史文化街区
historic_district_sample_poi_cnt=38
```

Gemma4:26b 端到端工具实测：

```text
tool=run_nl2semantic2sql
status=ok
raw_sql=SELECT COUNT(DISTINCT b."Id") FROM cq_buildings_2021 AS b WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r WHERE ST_Intersects(b.geometry, r.geometry) AND r.bridge = 'T')
final_sql=SELECT COUNT(DISTINCT b."Id") FROM cq_buildings_2021 AS b WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r WHERE ST_INTERSECTS(b.geometry, r.geometry) AND r.bridge = 'T')
execution_rows=1
execution_count=1
candidate_tables=cq_osm_roads_2021, cq_osm_roads, cq_buildings_2021
few_shot_count=1
corrections=semantic_column_alias
regression_fixed=_extract_sql no longer selects inner EXISTS(SELECT 1 ...) fragment
regression_fixed=_extract_sql preserves WITH CTE around the final outer SELECT
```

纯 Docker 容器内 Gemma4:26b 空间查询扩展实测：

```text
case_1=bridge/building ST_Intersects count
status=ok
final_sql=SELECT COUNT(DISTINCT b."Id") FROM cq_buildings_2021 AS b WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r WHERE ST_INTERSECTS(b.geometry, r.geometry) AND r.bridge = 'T')
data=[{"count": 1}]

case_2=bridge road length in km
status=ok
final_sql=SELECT SUM(ST_LENGTH(CAST(geometry AS GEOGRAPHY))) / 1000 AS total_length_km FROM cq_osm_roads_2021 WHERE bridge = 'T'
data=[{"total_length_km": 1376.5975723658505}]
manual_fail_if=SQL uses ST_Length(ST_Transform(geometry, 3857)) for real-world length
manual_fail_if=chat label says 道路数量 instead of 道路总长度（公里）

case_3=POI count within 100m of the longest bridge
status=ok
final_sql=WITH longest_bridge AS (SELECT geometry FROM cq_osm_roads_2021 WHERE bridge = 'T' ORDER BY ST_LENGTH(CAST(geometry AS GEOGRAPHY)) DESC LIMIT 1) SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p, longest_bridge AS lb WHERE ST_DWITHIN(CAST(p.geometry AS GEOGRAPHY), CAST(lb.geometry AS GEOGRAPHY), 100)
data=[{"count": 35}]
manual_fail_if=chat label says 道路总长度 instead of POI数量
```

录制重点：

- 展示 `run_nl2semantic2sql` 工具调用，而不是只展示模型文本输出。
- 展示自然语言参数、候选表、Gemma 4 生成 SQL、语义后处理修正和真实数据库执行结果。
- 停留在 `ST_Intersects` 和 `COUNT(DISTINCT)`，说明空间 join 与多对多去重计数。
- 录制前使用 Docker Compose 数据库确认真实 PostGIS 返回结果，避免把 K8s PVC 当作参赛复现前提。

口播建议：

> 用户只提出一个自然语言空间问题，Gemma 4 通过 `run_nl2semantic2sql` 进入语义 SQL 工作流。系统识别建筑物和道路表，生成 PostGIS 的 `ST_Intersects` 空间连接，并使用 `COUNT(DISTINCT)` 避免空间 join 重复计数。这里展示的是 Function Calling 进入工具、SQL 后处理和真实数据库执行结果的完整链路。

## 场景二：真实 WorldModelV21 Bishan / Dongxing MPC

主录屏建议优先用 Bishan，因为纯 Docker 容器内完整运行约 54 秒，适合 5 分钟视频。Dongxing 纯 Docker 容器内约 90 秒，可作为答辩补充或展示摘要。

GIS Data Agent 现在已集成 World Model v2.1 的完整 A->B->C->D 四阶段工具链：

```text
A / Tool 1 = world_model_v21_prepare
  DLTB + DEM -> prepared_dir

B / Tool 2 = world_model_v21_sample
  prepared_dir -> tool2/transitions.npz + tool2/pairwise.npz

C / Tool 3 = world_model_v21_train
  tool2 samples -> ONNX ensemble members

D / Tool 4 = world_model_v21_plan
  prepared_dir + ensemble_dir -> MPC optimized output

orchestrator = world_model_v21_pipeline
  支持 reuse_existing=true，已有 prepared/ensemble 时跳过 A/B/C，直接进入 D。
```

ADK Tool Calling 口径：

```text
WorldModelV21Toolset exposed_tools=6
tools=world_model_v21_status, world_model_v21_prepare, world_model_v21_sample, world_model_v21_train, world_model_v21_plan, world_model_v21_pipeline
preferred_agent_flow=world_model_v21_status -> world_model_v21_pipeline
pipeline_adk_surface=one standard ADK LongRunningFunctionTool call
pipeline_internal_orchestration=A/B/C/D stages executed by Python service orchestration
independent_stage_tools=prepare, sample, train, plan can be called separately when explicitly requested
```

录屏时要注意：`world_model_v21_pipeline` 对 Agent 外层来说是一次标准 ADK 工具调用；A/B/C/D 四个阶段是 pipeline 工具内部的服务编排和结构化进度返回，不是让 LLM 在外层连续发起四次工具调用。这样可以减少 LLM/tool 往返，同时保留四个阶段工具的独立调用入口。

比赛录屏建议不要现场重跑 B/C 采样和训练；它们是长任务。录屏时展示智能体调用 `world_model_v21_status -> world_model_v21_pipeline`，其中 A/B/C 阶段通过 `reuse_existing=true` 显示 `skipped_reused`，D/Tool 4 实际运行快速县域 MPC。只有用户明确说“只运行 Tool 4”时才展示 `world_model_v21_plan`。

前端人工验证：打开右侧数据面板的“世界模型 v2.1”tab，应先看到 A/Tool 1 Prepare、B/Tool 2 Sample、C/Tool 3 Train、D/Tool 4 Plan 四张阶段卡片。选择 Bishan 或 Dongxing 快捷数据集后，保持 `reuse_existing=true`，点击“运行/复用 A→D 编排”，A/B/C 应显示 `skipped_reused`，D 阶段会运行快速 MPC 并返回规划摘要与地图产物。

用户输入：

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 bishan 数据集运行一次快速县域 MPC 规划。
```

Dongxing 补充验证输入：

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 dongxing 数据集运行一次快速县域 MPC 规划。
```

工具链：

```text
world_model_v21_status -> world_model_v21_pipeline
repo=/app/paper9-demo
env_kind=county
onnx_member_count=3
docker_mounts=/app/bishan-runs, /app/dongxing-runs
default_fast_params=horizon=1, top_k=1, n_episodes=1, continuation=greedy, scoring=reward, threads=0
dataset_mapping=bishan -> /app/bishan-runs/prepared + /app/bishan-runs/prepared/ensemble_seed0
dataset_mapping=dongxing -> /app/dongxing-runs/prepared + /app/dongxing-runs/prepared/ensemble_seed0
progress=A/B/C/D 4 阶段完成
steps=A prepare skipped_reused, B sample skipped_reused, C train skipped_reused, D plan ok
```

Bishan 真实 plan 验证：

```text
status=ok
prepared_dir=/app/bishan-runs/prepared
ensemble_dir=/app/bishan-runs/prepared/ensemble_seed0
n_blocks=2640
n_parcels=53004
steps_run=100
swaps_completed=427
total_reward=66.43446147434678
slope_change_pct=-1.7563837440044885
cont_change=0.011685552407931787
baimu_area_change_ha=-489.02137531148793
```

Bishan 产物验证：

```text
out_dir=/app/data_agent/uploads/agent_world_model_v21/world_model_v21/<timestamp>
artifacts=mpc_summary.json, mpc_land_use.npy, optimized_dltb.shp, optimized_dltb.fgb
map_layer=world_model_v21/<timestamp>/optimized_dltb.fgb
warnings=[]
```

Dongxing 真实 plan 验证：

```text
status=ok
prepared_dir=/app/dongxing-runs/prepared
ensemble_dir=/app/dongxing-runs/prepared/ensemble_seed0
n_blocks=3711
n_parcels=76377
steps_run=100
swaps_completed=466
total_reward=112.63640181479221
slope_change_pct=-0.5822305233384841
cont_change=0.035509686447719346
baimu_area_change_ha=40.31168372728825
```

Dongxing 产物验证：

```text
out_dir=/app/data_agent/uploads/agent_world_model_v21/world_model_v21/<timestamp>
artifacts=mpc_summary.json, mpc_land_use.npy, optimized_dltb.shp, optimized_dltb.fgb
map_layer=world_model_v21/<timestamp>/optimized_dltb.fgb
warnings=[]
```

录制重点：

- 先展示 `world_model_v21_status`，再展示 `world_model_v21_pipeline`，突出智能体多步工具编排。
- 展示顶部进度不再是“1 步骤完成”，而是 `A/B/C/D 4 阶段完成`。
- 展示 A/B/C 阶段 `skipped_reused`，D/Tool 4 `ok`，说明长任务可复用且 Tool 4 真实执行。
- 展示用户只输入短句，Agent 自动根据 `bishan` / `dongxing` 选择正确数据集路径。
- 展示 3 个 ONNX ensemble member、县域 prepared_dir 和长任务运行日志。
- 展示环境构建：Bishan `53004 parcels / 2640 blocks` 或 Dongxing `76377 parcels / 3711 blocks`。
- 展示规划摘要、输出目录、`mpc_summary.json`、`mpc_land_use.npy` 和 `optimized_dltb.fgb`。
- 展示地图图例：`CHG_FLAG` 灰色保持不变、红色耕地 -> 林地、绿色林地 -> 耕地。
- 说明这是县域土地利用规划模型执行，不是纯文本推理。

口播建议：

> 第二个场景展示多步工具规划。用户只说使用 Bishan 或 Dongxing 运行快速县域 MPC，Agent 先调用 `world_model_v21_status` 检查 Paper9 世界模型、PROJ 运行时、ONNX ensemble 和默认路径，再调用 `world_model_v21_pipeline` 展开 A/B/C/D 四阶段。这里 A/B/C 复用已有 prepared、sample 和 ensemble，D 阶段实际运行 Tool 4 MPC，输出 Shapefile、FlatGeobuf、Numpy 结果和 JSON 摘要。地图按 `CHG_FLAG` 展示优化变化，灰色保持不变，红色表示耕地转林地，绿色表示林地转耕地。

## 场景三：真实 Postgres Memory 保存与检索

保存输入：

```text
请把本次演示保存为记忆：Gemma 4 完成了桥梁道路与建筑物相交的空间 NL2Semantic2SQL 查询，世界模型 v2.1 完成了 Bishan 和 Dongxing 县域 MPC 规划。关键词：Gemma4空间演示。
```

检索输入：

```text
检索关键词“Gemma4空间演示”的记忆。
```

录制时 DB 验证项：

```text
memory_table=agent_user_memories
memory_type=analysis_result
schema=username, memory_type, memory_key, memory_value, description
docker_smoke_insert=success inside transaction
docker_smoke_rollback=verified no residual test row
recording_requirement=save_memory and recall_memories through app UI/tool call
latest_recall_keyword=Gemma4空间演示
latest_recall_records=3
latest_recall_internal_reasoning_leak=false
```

记忆内容建议包含：

```text
model=Gemma4:26b @ http://host.docker.internal:11434
nl2sql=bridge-road/building ST_Intersects COUNT(DISTINCT)
world_model_bishan=steps_run=100, n_blocks=2640, n_parcels=53004, total_reward=66.43446147434678
world_model_dongxing=steps_run=100, n_blocks=3711, n_parcels=76377, total_reward=112.63640181479221
```

录制重点：

- 展示 `save_memory` 和 `recall_memories` 两个工具调用。
- 展示检索返回的是 Postgres 中持久化的用户空间记忆。
- 说明 Memory 可把已执行工具结果沉淀为后续上下文，而不是临时聊天缓存。

## 扩展验证：NL2Semantic2SQL 空间查询

本次新增和修复的空间查询覆盖：

```text
CQ_GEO_HARD_10:
  pattern=ST_Intersects grouped road-POI count
  assertion=COUNT(DISTINCT p."ID"), GROUP BY r.name, ORDER BY poi_cnt DESC LIMIT 5

CQ_GEO_HARD_14:
  pattern=ST_DWithin geography + singleton CROSS JOIN
  assertion=ST_DWithin(b.geometry::geography, u.geometry::geography, 1000)
  assertion=保持 COUNT(*)，不误改为 COUNT(DISTINCT b."Id")

CQ_GEO_HARD_25:
  pattern=grouped road length aggregate
  assertion=SUM(ST_Length(geometry::geography)) / 1000.0

CQ_GEO_MEDIUM_23:
  pattern=LEFT JOIN + ST_Contains grouped POI count
  assertion=保持 COUNT(p."ID")，不误注入 COUNT(DISTINCT p."ID")
```

已修复问题：

- `CQ_GEO_MEDIUM_23` 历史街区包含 POI 计数不再强行注入 `COUNT(DISTINCT)`。
- `CQ_GEO_HARD_14` 子查询别名 `u.geometry` 不在候选表 alias map 时，仍能安全改写为 geography 距离。
- `CQ_GEO_HARD_14` 的单点 `CROSS JOIN (SELECT ... LIMIT 1)` 不再触发不必要的 distinct 计数改写。
- `_extract_sql` 不再把 `EXISTS(SELECT ...)` 或 `WITH ... SELECT` CTE 中的内层/外层片段误当成完整 SQL。
- `data_agent.toolsets` 改为 lazy re-export，NL2SQL 导入不再加载无关 DRL 依赖。

CQ125 benchmark 中也有一批不需要空间函数的 SQL-only 问题，可用于说明系统不是所有题都强行走 `ST_*`：

```text
cq125_file=benchmarks/chongqing_geo_nl2sql_125q_clean_v3.json
cq125_total=125
cq125_sql_only_candidates=61

CQ_GEO_EASY_01:
  question=统计重庆2021年建筑物轮廓中 floors >= 40 的建筑物数量。
  spatial_function_required=false

CQ_GEO_EASY_02:
  question=列出重庆2021年道路网络中 maxspeed > 100 且 fclass = 'primary' 的道路名称。
  spatial_function_required=false

CQ_GEO_EASY_04:
  question=按 fclass 分组统计重庆2021年道路网络中的道路数量。
  spatial_function_required=false
```

## 扩展验证：WorldModelV21 工程修复

本次修复：

```text
WorldModelV21 PROJ_DATA auto-detect:
  fixed=macOS/conda pyproj DataDirError
  detected=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj

WorldModelV21 restoration GeoJSON:
  fixed=PROJ/GDAL 缺失时最小 GeoJSON 输出失败
  approach=直接写标准 FeatureCollection

optional dependencies:
  analysis_tools=sb3_contrib/stable_baselines3 optional
  visualization_tools=contextily optional
  spatial_statistics=libpysal/esda optional
```

注意：

- Dongxing 顶层 `runs/dongxing/ensemble` 与当前 prepared 不匹配，`n_blocks=2640` vs `3711`，会被正确拒绝。
- Dongxing 录制要使用容器内 `/app/dongxing-runs/prepared/ensemble_seed0`。
- Bishan 录制要使用容器内 `/app/bishan-runs/prepared/ensemble_seed0`。
- Paper9 shipped Bishan ONNX 仍可作为 ONNX 存在性证据，但本次 live plan 使用 matching prepared ensemble。

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
- 对话框“历史会话”：恢复 Chainlit `Thread/Step` 对话记录，属于会话历史/产品体验，不等同于 Agent Memory。

## 5 分钟时间分配

```text
0:00-0:20  开场：GIS Data Agent + Gemma 4 AI Agent 赛道对齐
0:20-1:05  新增场景：无 @ 数据发现 -> 耕地优化工作流
1:05-2:05  场景一：真实 PostGIS NL2Semantic2SQL
2:05-2:20  展示 NL2SQL Tool Calling 日志、SQL/map 结果和运行日志面板
2:20-3:45  场景二：WorldModelV21 status -> pipeline A/B/C/D 多步规划
3:45-4:25  场景三：Memory 保存与检索
4:25-4:50  架构、代码路径和运行日志管理对齐
4:50-5:00  收尾总结
```

架构展示路径：

```text
data_agent/model_gateway.py
data_agent/embedding_gateway.py
data_agent/nl2semantic2sql_direct_agent.py
data_agent/nl2sql_executor.py
data_agent/nl2sql_semantic_rewrite.py
data_agent/nl2sql_presentation.py
data_agent/toolsets/file_tools.py
data_agent/data_catalog.py
data_agent/gis_processors.py
data_agent/drl_engine.py
data_agent/toolsets/world_model_v21_tools.py
data_agent/world_model_v21.py
data_agent/memory.py
data_agent/frontend_api.py  # /api/agent/run-logs
frontend/src/components/datapanel/AgentRunLogsTab.tsx
```

## 录制注意事项

- 不展示数据库密码、API key、云账号、OBS AK/SK、OAuth secret 等敏感信息。
- 视频中只展示 host、端口、模型名、工具名、SQL 和结果摘要。
- 录制前重新确认 Docker Compose PostGIS 和 `run_nl2semantic2sql` 真实执行。
- 每个核心场景完成后切到“工作台 -> 平台运营 -> 运行日志”，展开最新运行，截图保留 Tool Calling、Memory 和 Step Timeline；需要查看全文时点击“完整详情”。
- 运行日志时间应显示东八区 `+08:00`；如果看到旧布局或内容截断，先 hard refresh `http://127.0.0.1:8000`。
- WorldModelV21 录制优先 Bishan；Dongxing 可展示已跑通摘要和产物目录。
- 不要临时使用 Dongxing 顶层 `runs/dongxing/ensemble`，它与当前 prepared 维度不匹配。
- 结尾强调：Gemma 4 + Function Calling + Tool Calling 日志 + Memory + 多步规划 + 真实 GIS 数据/模型执行。
