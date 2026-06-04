# Gemma4 AI Agent Demo Progress - 2026-06-04

## Current State

- Branch: `feat/v12-extensible-platform`
- Runtime mode: pure Docker Desktop via `docker-compose.gemma4-demo.yml`
- App URL while running: `http://localhost:8000`
- Login used for local validation: `admin/admin123`
- Kubernetes deployment remains out of the demo path; the validated path is Docker Compose.

## Deployment Notes

- Added/used `docker-compose.gemma4-demo.yml` for the Gemma4 hackathon demo stack:
  - app: `gis-data-agent:dev`
  - db: `gis-postgis-pgvector:16-3.4`
  - redis: `redis:7-alpine`
- The compose app service forces model config from environment with `MODEL_CONFIG_FORCE_ENV=true`, so DB-stored Google Gemini defaults do not override the local Ollama/Gemma4 routing.
- The app service mounts:
  - `/private/tmp/paper9-demo:/app/paper9-demo:ro`
  - `/Users/zhouning/farmland_mpc_runs/bishan:/app/bishan-runs:ro`

## NL2SQL Demo Result

Question:

```text
@NL2SQL 统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

Validated result:

- Golden SQL count: `COUNT(DISTINCT b."Id") = 1`
- Spatial join rows: `33`
- Distinct building geometry rows shown on map: `31`
- Related `bridge='T'` road lines: `19`

Important interpretation:

- The answer "1" is the golden SQL aggregate field value, not "returned one row".
- The map intentionally shows the geometry evidence behind the aggregate: 31 building geometry rows and 19 bridge road features.

Improvements made:

- Direct `@NL2SQL` output is formatted into readable Chinese Markdown.
- Tool call is surfaced as `run_nl2semantic2sql`.
- SQL, candidate tables, few-shot count, model family, and corrections are shown.
- Bridge/building map layers are generated and injected into the right-side map.

## World Model v2.1 Demo

Added `@WorldModelV21` direct mention agent.

Expected demo prompt for Buchanan VA restoration:

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，再使用系统默认的 Buchanan VA restoration 数据运行一次快速 MPC 规划。参数：env_kind=restoration，horizon=2，top_k=5，n_episodes=1，continuation=greedy，scoring=reward。使用默认 prepared_dir 和 ensemble_dir，不要要求我补充路径。
```

Validated Buchanan result:

- Status/version: `ok / 2.1.0`
- Mode: `tool4_mpc`
- Env kind: `restoration`
- Steps run: `50`
- N blocks: `562`
- N selected: `50`
- Total reward: `230.75`
- Map layer: `restoration_mpc_units.geojson`

Map notes:

- The Buchanan prepared directory has no exact vector parcel boundary, so the restoration map is an approximate planning-unit grid generated from `attributes.csv` row/col plus `mpc_land_use.npy`.
- Right-side map displays `World Model v2.1 optimized`.
- Green means selected units; gray means not selected.

Implementation fixes:

- Added nested `map_update` extraction for ADK tool response wrappers such as `{"result": "...json..."}`.
- Queued WorldModelV21 map updates for the current authenticated user instead of a fixed tool user.
- Added deterministic WorldModelV21 chat presentation so key metrics come from tool JSON, not LLM restatement.
- Added common `env_kind` typo normalization, e.g. `rest_oration` -> `restoration`.
- Strengthened CoT/leaked planning text cleanup for direct mention responses.

## Bishan World Model v2.1 Demo

Bishan host data:

- Source shapefile: `/Users/zhouning/Downloads/shp/bishan.shp`
- Prepared dir: `/Users/zhouning/farmland_mpc_runs/bishan/prepared`
- Container prepared dir: `/app/bishan-runs/prepared`
- Container ensemble dir: `/app/bishan-runs/prepared/ensemble_seed0`

Recommended prompt:

```text
@WorldModelV21 请先检查世界模型 v2.1 状态，再使用 Bishan 数据运行一次快速 MPC 规划。参数：env_kind=county，prepared_dir=/app/bishan-runs/prepared，ensemble_dir=/app/bishan-runs/prepared/ensemble_seed0，horizon=2，top_k=5，n_episodes=1，continuation=greedy，scoring=reward，proj_crs=EPSG:32648。
```

Validated quick run result:

- Env kind: `county`
- Parcels: `53,004`
- Blocks: `2,640`
- Steps run: `100`
- Swaps completed: `427`
- Slope change: `-1.7531%`
- Contiguity change: `+0.0125`
- Baimu area change: `-483.94 ha`
- Total reward: `71.78`
- Map artifact: `world_model_v21/20260604_094603_461868/optimized_dltb.fgb`

Map notes:

- The generated FGB file is about 138 MB and was verified through `/api/user/files/...` with HTTP 200.
- For Bishan/county mode, the right-side map is classified by optimized land-use field `OPT_DLBM`.
- Yellow represents `011` farmland; green represents `031` forest.

## Tests Run

Focused regression tests passed during this session:

```text
data_agent/test_world_model_v21_presentation.py
data_agent/test_pipeline_helpers.py
data_agent/test_world_model_v21_tools.py::test_world_model_v21_plan_tool_normalizes_payload_and_returns_map_update
data_agent/test_world_model_v21_tools.py::test_world_model_v21_plan_normalizes_common_env_kind_typo
data_agent/test_world_model_v21_tools.py::test_world_model_v21_agent_is_directly_mentionable
data_agent/test_mention_routing.py::TestMentionTargetsAPI::test_returns_targets
```

Latest focused WorldModelV21 presentation test run:

```text
5 passed, 1 warning
```

## Known Warnings / Follow-up

- App startup logs still show custom skill queries referencing missing `output_schema`; this did not block the demo, but the migration/schema mismatch should be cleaned up later.
- The MCP cad-parser service config still points at a Windows path (`D:\adk\.venv\Scripts\python.exe`) and fails to connect in the Docker demo environment. This is unrelated to the NL2SQL/WorldModelV21 demo path.
- Bishan full baseline is expensive: historical full run was around 80+ minutes. Use the quick prompt above for hackathon demo timing.
- The generated Bishan FGB is large. If demo loading is slow on a weaker browser/device, consider adding a simplified/vector-tile version later.

## Shutdown Reminder

For this session the Docker stack should be stopped after commit/push:

```bash
docker compose -f docker-compose.gemma4-demo.yml down
```
