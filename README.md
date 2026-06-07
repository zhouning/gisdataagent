# GIS Data Agent for Gemma 4 AI Agent Track

[English](./README_en.md) | **中文**

Gemma 4 powered GIS Data Agent for NL2Semantic2SQL and WorldModel v2.1 planning with native tool calling and persistent memory.

本仓库当前 README 面向 Gemma 4 开发者大赛 Track A: AI Agent 组织，重点展示：

- Gemma 4 26B MoE 的规格选择依据。
- 基于 Google ADK 的多智能体架构。
- 原生 Function Calling / Tool Calling。
- Agent Memory。
- 两个真实 GIS 场景：`nl2semantic2sql` 和 `worldmodelv2.1`。
- 纯 Docker Compose 可复现演示环境。

## Competition Alignment

| 比赛要求 | 本项目交付 |
|---|---|
| 核心代码包含 Gemma 4 调用逻辑 | `data_agent/model_gateway.py` 注册 `gemma4-26b-host228`，Docker 环境变量固定所有 demo 模型 tier |
| Native Function Calling / Tool Calling | ADK `FunctionTool` / `LongRunningFunctionTool`，运行日志展示 `run_nl2semantic2sql` 和 `world_model_v21_status -> world_model_v21_pipeline` |
| 多步规划 | WorldModel v2.1 A/B/C/D pipeline: Prepare, Sample, Train, Plan |
| Memory | `PostgresMemoryService`、`save_memory`、`recall_memories`、`auto_extract`、运行日志 Memory 统计 |
| 演示视频 5 分钟以内 | [docs/gemma4_ai_agent_demo_script.md](docs/gemma4_ai_agent_demo_script.md) |
| 技术报告 | [docs/gemma4_ai_agent_technical_report.md](docs/gemma4_ai_agent_technical_report.md) |
| Memory / Tool Calling 代码说明 | [docs/gemma4_ai_agent_code_walkthrough.md](docs/gemma4_ai_agent_code_walkthrough.md) |
| Docker 部署指南 | 本 README 的 [Docker Compose Quick Start](#docker-compose-quick-start) |
| 运行日志截图 | UI 路径：`工作台 -> 平台运营 -> 运行日志`；建议保存到 `docs/submission_screenshots/` |

## Why Gemma 4 26B

模型选择基于同一套 CQ-125 PostGIS benchmark，对 Gemma 4 家族 5 个规格在同一 host228 Ollama 环境下评测。

Evidence:

- [docs/assets/gemma4_host228_scale_sweep_summary.csv](docs/assets/gemma4_host228_scale_sweep_summary.csv)
- [docs/assets/gemma4_host228_scale_sweep.svg](docs/assets/gemma4_host228_scale_sweep.svg)

![Gemma4 host228 CQ-125 scale sweep](docs/assets/gemma4_host228_scale_sweep.svg)

| 模型 | CQ-125 full EX | full runtime | 选择判断 |
|---|---:|---:|---|
| Gemma4:e2b | 82/125 = 65.6% | 21.22 min | 准确率不足 |
| Gemma4:e4b | 80/125 = 64.0% | 13.49 min | 准确率不足 |
| Gemma4:12b | 107/125 = 85.6% | 16.45 min | 可作为备选 |
| Gemma4:26b | 113/125 = 90.4% | 12.50 min | 本项目采用 |
| Gemma4:31b | 114/125 = 91.2% | 20.04 min | EX 最高，但演示延迟更高 |

26B 只比 31B 低 1 道题，也就是 0.8 个百分点，但约快 37.6%。因此本项目选择 `Gemma4:26b` 作为比赛演示模型：接近 31B 的空间 SQL 执行准确率，同时更适合 5 分钟现场 Tool Calling 和多步规划演示。

该结果是固定主机部署探针，不声称统计显著优于 31B。

## Core Scenarios

### 1. NL2Semantic2SQL

用户输入中文空间问题，系统执行：

```text
@NL2SQL 统计距离道路网络中最长桥梁100米范围内的高德POI数量。
```

核心链路：

```text
@NL2SQL route
  -> DirectNL2SemanticSQLAgent
  -> function_call: run_nl2semantic2sql(user_question)
  -> semantic layer + schema grounding + few-shot
  -> Gemma 4 26B SQL synthesis
  -> semantic SQL rewrites
  -> SQL postprocessor / read-only guard
  -> PostgreSQL + PostGIS execution
  -> result summary + optional map layer
```

已验证空间查询包括：

| 查询 | 关键 PostGIS 点 | 已验证结果 |
|---|---|---:|
| `bridge = T` 道路总长度 | `ST_Length(geometry::geography) / 1000` | `1376.5976 km` |
| 最长桥梁 100m 内 POI | CTE + `ST_DWithin(...::geography, 100)` | `35` |
| 与桥梁相交的建筑物轮廓 | `ST_Intersects` + `COUNT(DISTINCT b."Id")` | `1` |

为什么不是普通 NL2SQL：空间 SQL 需要处理 geometry/geography 单位、SRID、空间谓词、距离/面积/长度和空间 join 去重。项目通过 semantic grounding 和 PostGIS harness 降低 LLM 直接生成空间 SQL 的不稳定性。

### 2. WorldModel v2.1

用户输入短句即可运行县域 MPC 规划：

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 dongxing 数据集运行一次快速县域 MPC 规划。
```

Gemma 4 推荐工具轨迹：

```text
world_model_v21_status -> world_model_v21_pipeline
```

`world_model_v21_pipeline` 展示完整 A/B/C/D 阶段：

| 阶段 | 工具 | 演示行为 |
|---|---|---|
| A / Tool 1 Prepare | DLTB + DEM -> prepared data | `skipped_reused` |
| B / Tool 2 Sample | prepared -> transition samples | `skipped_reused` |
| C / Tool 3 Train | samples -> ONNX ensemble | `skipped_reused` |
| D / Tool 4 Plan | ONNX ensemble -> MPC output | `ok`, 真实运行 |

内置数据集 preset：

| dataset | prepared_dir | ensemble_dir |
|---|---|---|
| `bishan` / `璧山` | `/app/bishan-runs/prepared` | `/app/bishan-runs/prepared/ensemble_seed0` |
| `dongxing` / `东兴` | `/app/dongxing-runs/prepared` | `/app/dongxing-runs/prepared/ensemble_seed0` |

已验证结果：

| 数据集 | blocks | parcels | steps_run | total_reward |
|---|---:|---:|---:|---:|
| Bishan | 2640 | 53004 | 100 | 66.43446147434678 |
| Dongxing | 3711 | 76377 | 100 | 112.63640181479221 |

地图按 `CHG_FLAG` 展示优化变化：

- 灰色：保持不变。
- 红色：耕地 -> 林地。
- 绿色：林地 -> 耕地。

## Architecture

```mermaid
flowchart TB
  U[Chat UI / React Workbench] --> R[@mention Router]
  R --> A[Google ADK Agents]
  A --> M[Gemma 4 26B via Ollama]
  A --> T[ADK Toolsets]
  T --> N[NL2Semantic2SQL]
  T --> W[WorldModel v2.1]
  T --> MEM[Memory Tools]
  N --> PG[(PostgreSQL + PostGIS + pgvector)]
  MEM --> PG
  W --> FS[(Paper9 + Bishan/Dongxing runs)]
  A --> LOG[Chainlit Thread/Step Run Logs]
```

Key code:

| Area | Files |
|---|---|
| Gemma 4 model gateway | `data_agent/model_gateway.py`, `docker-compose.gemma4-demo.yml` |
| ADK routing | `data_agent/agent.py` |
| NL2Semantic2SQL direct tool event | `data_agent/nl2semantic2sql_direct_agent.py` |
| NL2SQL execution harness | `data_agent/nl2sql_executor.py`, `data_agent/nl2sql_grounding.py`, `data_agent/nl2sql_semantic_rewrite.py`, `data_agent/sql_postprocessor.py` |
| WorldModel v2.1 tools | `data_agent/toolsets/world_model_v21_tools.py`, `data_agent/world_model_v21.py` |
| Memory | `data_agent/conversation_memory.py`, `data_agent/memory.py` |
| Run logs | `data_agent/app.py`, `data_agent/frontend_api.py`, `frontend/src/components/datapanel/AgentRunLogsTab.tsx` |

## Docker Compose Quick Start

### Prerequisites

- Docker Desktop or Docker Engine with Compose.
- Access to Ollama host with `Gemma4:26b`.
- Local Paper9 / Bishan / Dongxing paths matching `docker-compose.gemma4-demo.yml`, or edit the volume mounts before running.

Required local mounts in the current demo compose file:

```yaml
- /Users/zhouning/arcgis-farmland-mpc:/app/paper9-demo:ro
- /Users/zhouning/farmland_mpc_runs/bishan:/app/bishan-runs:ro
- /Users/zhouning/arcgis-farmland-mpc/runs/dongxing:/app/dongxing-runs:ro
```

### Start

```bash
docker compose -f docker-compose.gemma4-demo.yml up -d --build
```

Open:

```text
http://localhost:8000
```

Local demo login, if auth is enabled:

```text
admin / admin123
```

### Check Services

```bash
docker compose -f docker-compose.gemma4-demo.yml ps
docker compose -f docker-compose.gemma4-demo.yml logs -f app
```

### Stop

```bash
docker compose -f docker-compose.gemma4-demo.yml down
```

Use `-v` only when you intentionally want to delete local Docker volumes.

## Environment Variables

The demo compose file pins the competition model and runtime:

| Variable | Value in demo | Purpose |
|---|---|---|
| `MODEL_CONFIG_FORCE_ENV` | `true` | Force env-based model config |
| `ROUTER_MODEL` | `gemma4-26b-host228` | Intent routing model |
| `MODEL_FAST` | `gemma4-26b-host228` | Fast tier model |
| `MODEL_STANDARD` | `gemma4-26b-host228` | Standard tier model |
| `MODEL_PREMIUM` | `gemma4-26b-host228` | Premium tier model |
| `NL2SQL_AGENT_MODEL` | `gemma4-26b-host228` | NL2SQL SQL synthesis path |
| `NL2SQL_LLM_SCHEMA_MAPPER_MODEL` | `gemma4-26b-host228` | NL2SQL schema mapper |
| `EMBEDDING_MODEL` | `nomic-embed-text-v2-moe-host228` | Few-shot / semantic retrieval embedding |
| `OLLAMA_API_BASE` | `http://192.168.25.228:11434` | Ollama endpoint |
| `PAPER9_FARMLAND_MPC_REPO` | `/app/paper9-demo` | WorldModel v2.1 Paper9 repo |
| `PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR` | `/app/bishan-runs/prepared` | Default Bishan prepared data |
| `PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR` | `/app/bishan-runs/prepared/ensemble_seed0` | Default Bishan ONNX ensemble |
| `PROJ_DATA` / `PROJ_LIB` | pyproj data dir inside container | Fix projection runtime, e.g. `EPSG:32648` |

PostGIS / Redis are also configured in `docker-compose.gemma4-demo.yml`.

## Demo Script

Open the app and run the following prompts.

NL2Semantic2SQL:

```text
@NL2SQL 统计重庆2021年道路网络中所有桥梁道路（bridge = T）的总长度，单位为公里。
```

```text
@NL2SQL 统计距离道路网络中最长桥梁100米范围内的高德POI数量。
```

```text
@NL2SQL 统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

WorldModel v2.1:

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 bishan 数据集运行一次快速县域 MPC 规划。
```

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，然后使用 dongxing 数据集运行一次快速县域 MPC 规划。
```

Memory:

```text
请把本次演示保存为记忆：Gemma 4 完成了桥梁道路与建筑物相交的空间 NL2Semantic2SQL 查询，世界模型 v2.1 完成了 Bishan 和 Dongxing 县域 MPC 规划。关键词：Gemma4空间演示。
```

```text
检索关键词“Gemma4空间演示”的记忆。
```

Full recording guide:

- [docs/gemma4_ai_agent_demo_script.md](docs/gemma4_ai_agent_demo_script.md)

## Run Log Screenshots

For the competition submission, capture run logs from:

```text
工作台 -> 平台运营 -> 运行日志
```

Recommended screenshot paths:

```text
docs/submission_screenshots/run_logs_nl2sql.png
docs/submission_screenshots/run_logs_worldmodel_v21.png
docs/submission_screenshots/run_logs_memory.png
```

Each screenshot should show:

- Thread / Step timeline.
- Tool Calling records.
- Function args / response summary.
- Memory count where relevant.
- Map event summary for generated map layers.

The API behind this panel is:

```text
GET /api/agent/run-logs
```

## Submission Documents

| Document | Purpose |
|---|---|
| [docs/gemma4_ai_agent_technical_report.md](docs/gemma4_ai_agent_technical_report.md) | Technical report: model choice, architecture, scenarios, deployment |
| [docs/gemma4_ai_agent_code_walkthrough.md](docs/gemma4_ai_agent_code_walkthrough.md) | Memory and Tool Calling code explanation for `nl2semantic2sql` and `worldmodelv2.1` |
| [docs/gemma4_ai_agent_demo_script.md](docs/gemma4_ai_agent_demo_script.md) | 5-minute demo script and local retest evidence |
| [docs/assets/gemma4_host228_scale_sweep_summary.csv](docs/assets/gemma4_host228_scale_sweep_summary.csv) | Gemma 4 model sweep evidence |
| [docs/assets/gemma4_host228_scale_sweep.svg](docs/assets/gemma4_host228_scale_sweep.svg) | Model sweep figure |

## GitHub About

Recommended repository description:

```text
Gemma 4 powered GIS Data Agent for NL2Semantic2SQL and WorldModel v2.1 planning with native tool calling and memory.
```

Recommended topics:

```text
agent-memory, ai-agent, docker-compose, function-calling, gemma4, geospatial, gis, google-adk, mpc, multi-agent, nl2sql, postgis, tool-calling, world-model
```

## License

MIT
