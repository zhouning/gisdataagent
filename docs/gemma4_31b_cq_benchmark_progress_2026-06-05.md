# Gemma4 31B CQ NL2Semantic2SQL Progress - 2026-06-05

## Host228 Windows Real Scenario Validation

Current competition demo runtime:

```text
OS=Windows
repo=D:\adk
branch=feat/v12-extensible-platform
git sync=HEAD...origin/feat/v12-extensible-platform -> 0 0
OLLAMA_API_BASE=http://192.168.25.228:11434
LLM tag=Gemma4:31b
Embedding tag=nomic-embed-text-v2-moe:latest
model registry name=gemma4-31b-host228
embedding registry name=nomic-embed-text-v2-moe-host228
```

Ollama `/api/tags` confirmed:

```text
Gemma4:31b
  parameter_size=31.3B
  capabilities=completion, tools, thinking

nomic-embed-text-v2-moe:latest
  embedding_length=768
  capabilities=embedding
```

App-level route check:

```text
standard tier=gemma4-31b-host228
model_class=LiteLlm
model=ollama_chat/Gemma4:31b
family=gemma
```

## Real Scenario 1: PostGIS NL2Semantic2SQL

This validation used the production high-level tool entry point directly:

```text
data_agent.nl2sql_executor.run_nl2semantic2sql
data_agent.nl2sql_presentation.build_bridge_building_map_update
```

Question:

```text
统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。
```

Result:

```text
status=ok
execution.rows=1
execution.data[0].count=1
candidate_tables=cq_osm_roads_2021, cq_buildings_2021, cq_osm_roads
few_shot_count=0
family=gemma
corrections=semantic_column_alias
```

Executed SQL:

```sql
SELECT COUNT(DISTINCT b."Id")
FROM cq_buildings_2021 AS b
JOIN cq_osm_roads_2021 AS r
  ON ST_INTERSECTS(b.geometry, r.geometry)
WHERE r.bridge = 'T'
```

Map layer result:

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

Documentation implication:

- The demo script must distinguish the aggregate SQL result (`COUNT(DISTINCT)=1`) from the map visualization rows (`31` building geometries).
- Recording should show `ST_INTERSECTS`, `COUNT(DISTINCT)`, candidate tables, correction metadata, and the map update.

## Real Scenario 1B: Additional Spatial NL2Semantic2SQL Suite

This follow-up validation added more real spatial scenarios from `benchmarks/gis_spatial_30q_subset.json`.
It used `run_nl2semantic2sql` with Gemma4:31b on host228, then executed the generated SQL and golden SQL against the real PostGIS database.

```text
scenario=nl2semantic2sql_spatial_suite_real_postgis
model=Gemma4:31b @ http://192.168.25.228:11434
questions=5
generation_status_ok=5/5
exact_top10_match=2/5
semantically_or_numerically_acceptable=4/5
semantic_mismatch=1/5
```

| QID | Spatial pattern | Result | Validation finding |
| --- | --- | --- | --- |
| `CQ_GEO_HARD_10` | `ST_INTERSECTS` road/POI spatial join | `status=ok`, `match_top10=true` | Generated SQL used spatial join and grouped road counts. Both generated and golden returned no rows for the top-5 primary-road intersection case. |
| `CQ_GEO_HARD_14` | `ST_DWITHIN(...::geography)` 1 km building query | `status=ok`, `match_top10=true` | Returned 30 buildings with `Floor > 10` around Chongqing University, matching golden SQL. |
| `CQ_GEO_HARD_25` | `ST_Length(...::geography)` road-class aggregation | `status=ok`, `match_top10=false` | Numeric results match golden top-10; mismatch is caused by output alias differences. |
| `CQ_GEO_MEDIUM_23` | historic-district contains POI grouped count | `status=ok`, `match_top10=false` | Real semantic mismatch: generated SQL used `COUNT(DISTINCT poi."ID")`, while golden SQL counts POI rows. Example: `磁器口` generated 972 vs golden 1299. |
| `CQ_GEO_MEDIUM_30` | `ST_Union` + area aggregation | `status=ok`, `match_top10=false` | Numeric value is equivalent after rounding: generated `2.8790834651026738`, golden `2.8791`; mismatch is alias/precision only. |

Observed follow-up:

- The spatial operator coverage is broader than the single demo question: `ST_INTERSECTS`, `ST_DWITHIN`, `ST_Length`, `ST_Contains`/grouped spatial counts, and `ST_Union`/area all compile and execute on real data.
- `semantic_distinct_join_count` improves duplicate protection for many spatial joins but is too aggressive for grouped POI row-count semantics. The grouped spatial count rewrite should only inject `DISTINCT` when the target question asks for unique entities or the join path can duplicate the same logical entity.
- The evaluator should normalize aliases and configurable numeric rounding before counting precision-only spatial aggregation failures.

## Real Scenario 2: Buchanan VA WorldModelV21 MPC

This validation used the real Paper9 repository and the real Buchanan VA restoration prepared data/checkpoints under `D:\test\_publish\arcgis-farmland-mpc`.

Tool trajectory:

```text
world_model_v21_status -> world_model_v21_plan
```

Status result:

```text
status=ready
version=2.1.0
repo_exists=true
importable=true
onnx_member_count=3
prepared_dir=D:\test\_publish\arcgis-farmland-mpc\runs\restoration\buchanan_va\prepared_watershed
ensemble_dir=D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\restoration\profiles\buchanan_va\watershed\ensemble_seed0
```

Planning parameters:

```text
env_kind=restoration
horizon=2
top_k=5
n_episodes=1
continuation=greedy
scoring=reward
threads=0
```

Planning result:

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

Artifacts:

```text
mpc_summary.json
mpc_land_use.npy
world_model_v21/20260605_114726_601605/restoration_mpc_units.geojson
```

Documentation implication:

- The demo should present this as multi-step planning, not a single function call.
- The video should show status checks, ONNX ensemble count, MPC run logs, summary metrics, and the generated map layer.

## Real Scenario 2B: WorldModelV21 County Extension - Bishan and Dongxing

The county-level follow-up used the current ADK `WorldModelV21Service`, which expects a prepared county layout plus ONNX ensemble members.
This is a stricter live validation path than reading historical research summaries.

### Bishan

Input data and model availability:

```text
prepared_dir=D:\test
prepared_data=
  D:\test\townships.json
  D:\test\results_real
  D:\test\dem_slope_analysis\output\DLTB_with_slope.gpkg
ensemble_dir=D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\bishan\shipped_onnx
onnx_member_count=3
env_kind=county
horizon=2
top_k=5
n_episodes=1
continuation=greedy
scoring=reward
proj_crs=EPSG:32648
```

Environment build result:

```text
env_build=ok
swappable_parcels=52515
blocks=2600
n_parcels=52515
max_steps=100
initial_avg_slope=9.6157
initial_contiguity=3.5852
initial_baimu_fang=109 patches, 46843.7 ha total
onnx_members_loaded=3
```

Planning result:

```text
plan_status=blocked_by_memory
error=Unable to allocate 401 MiB for an array with shape (2380, 2600, 17) and data type float32
```

Interpretation:

- Bishan passes repository, prepared-data, environment-build, and ONNX loading checks.
- Current county MPC planning is too memory-heavy for the local live demo path at this data size.
- The 5-minute competition video should keep Buchanan VA as the live WorldModelV21 planning scene until county MPC batching or stage-1 memory optimization is added.

### Dongxing / Neijiang Dongxing

Current ADK live preflight:

```text
dongxing_neijiang_baseline_pt.onnx_member_count=0
dongxing_repro_artifacts.onnx_member_count=0
bishan_shipped_onnx.onnx_member_count=3
validate_plan_request.status=expected_rejected
validate_plan_request.error=No ONNX ensemble members found under D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\neijiang\baseline
```

Available Dongxing artifacts:

```text
paper/checkpoints/neijiang/baseline/*.pt
paper/checkpoints/neijiang/partial_transfer/*.pt
paper/repro_artifacts/macos_2026-05-29/dongxing_5seed.json
paper/repro_artifacts/macos_2026-05-29/dongxing_5seed_RESEARCH_ensembles.json
```

Historical package result from `dongxing_5seed.json`:

```text
region=Neijiang Dongxing
mode=baseline
n_seeds=5
slope_pct_mean=-0.5741333407356206
slope_pct_std=0.02327154233135224
cont_pct_mean=3.651550268946533
baimu_count_delta_mean=0.4
baimu_area_delta_ha_mean=30.17277189565897
reward_mean=96.29512009811995
reward_std=9.3806583302709
```

Interpretation:

- Dongxing has research/checkpoint evidence, but the current ADK `WorldModelV21Service` live planner consumes ONNX ensembles and cannot run directly from the available `.pt` state dicts.
- The correct next engineering step is to export the Neijiang/Dongxing `.pt` ensembles to ONNX with the matching county block shape, then rerun the same live preflight and planning path.
- Until that export exists, Dongxing should be described as historical reproducibility evidence, not as a completed live ADK WorldModelV21 run.

## Real Scenario 3: Postgres Memory

This validation used the real Postgres-backed memory table.

```text
memory_table=agent_user_memories
user=demo_gemma4_memory_user
key=Gemma4空间演示_20260605_114845
memory_type=analysis_result
save_status=success
recall_status=success
recall_count=1
```

Persisted value summary:

```text
model=Gemma4:31b @ http://192.168.25.228:11434
nl2sql=COUNT(DISTINCT)=1, map geometry rows=31, bridge roads=19
world_model=steps_run=50, n_blocks=562, n_selected=50, total_reward=230.75136300693933
```

Documentation implication:

- The script should show both `save_memory` and `recall_memories`.
- Memory should be described as persistent user context in Postgres, not an in-process cache.

## Focused Regression

Focused regression tests after syncing the GitHub development branch:

```text
192 passed, 1 warning
```

Command:

```powershell
.\.venv\Scripts\python.exe -B -m pytest ^
  data_agent/test_model_config.py ^
  data_agent/test_nl2sql_cq_eval_gemma.py ^
  data_agent/test_nl2sql_presentation.py ^
  data_agent/test_pipeline_helpers.py ^
  data_agent/test_world_model_v21_presentation.py ^
  data_agent/test_world_model_v21_tools.py::test_world_model_v21_plan_tool_normalizes_payload_and_returns_map_update ^
  data_agent/test_world_model_v21_tools.py::test_world_model_v21_plan_normalizes_common_env_kind_typo ^
  data_agent/test_world_model_v21_tools.py::test_world_model_v21_agent_is_directly_mentionable ^
  data_agent/test_mention_routing.py::TestMentionTargetsAPI::test_returns_targets ^
  data_agent/test_nl2sql_executor.py ^
  data_agent/test_nl2sql_grounding.py ^
  data_agent/test_nl2sql_semantic_rewrite.py ^
  data_agent/test_nl2sql_major_project_kg_hints.py ^
  data_agent/test_sql_postprocessor.py ^
  data_agent/test_nl2sql_tools.py -q
```

## Code Changes Made

App-level built-in registry entries for the Windows demo:

```text
data_agent/model_gateway.py:
  gemma4-31b-host228 -> ollama_chat/Gemma4:31b @ http://192.168.25.228:11434

data_agent/embedding_gateway.py:
  nomic-embed-text-v2-moe-host228 -> nomic-embed-text-v2-moe:latest @ http://192.168.25.228:11434
```

Additional verification:

```text
py_compile passed for:
  data_agent/model_gateway.py
  data_agent/embedding_gateway.py
  data_agent/test_model_config.py
  family12_gemma4_31b_host228_runner.py
  scripts/nl2sql_bench_cq/run_cq_eval.py

host228 registry tests:
  2 passed, 1 warning
```

The host228 runner registers:

```text
model registry name=gemma4-31b-host228
model_id=ollama_chat/Gemma4:31b
api_base=http://192.168.25.228:11434
extra_body={"think": false}
embedding model=nomic-embed-text-v2-moe-host228
```

`run_cq_eval.py` now allows baseline LiteLLM timeout to be configured with:

```text
BASELINE_LITELLM_TIMEOUT
```

The 31B runner sets:

```text
CQ_EVAL_QUESTION_TIMEOUT=900
BASELINE_HARD_TIMEOUT=420
BASELINE_LITELLM_TIMEOUT=360
NL2SQL_GEMMA_SQL_RETRIES=3
```

## Historical Host164 Benchmark Context

The CQ benchmark runner previously completed baseline and full modes on the 125-question CQ dataset using host164:

```text
Result dir:
D:\adk\data_agent\nl2sql_eval_results\family12_gemma4_31b_host164_productized_both_2026-06-04_232959

baseline: 73/125, EX=0.5840, valid=0.9680, wall=11.88 min
full:     96/125, EX=0.7680, valid=0.9200, wall=17.91 min
delta:    +0.1840
```

The benchmark path says `chongqing_geo_nl2sql_100_benchmark.json`, but the current file contains 125 questions.

Comparable previous 26B full-mode results:

```text
26b host164 productized full:
D:\adk\data_agent\nl2sql_eval_results\family12_gemma4_26b_host164_productized_full_2026-06-03_024449
full: 105/125, EX=0.8400, valid=0.9520

26b host228 productized full:
D:\adk\data_agent\nl2sql_eval_results\family12_gemma4_26b_host228_productized_full_2026-06-03_183313
full: 113/125, EX=0.9040, valid=0.9360

31b host164 current full:
full: 96/125, EX=0.7680, valid=0.9200
```

Against 26B host164 full, per-question diff:

```text
both pass: 88
26b pass, 31b fail: 17
26b fail, 31b pass: 8
both fail: 12
```

Observed 31B failure patterns:

1. Wrong semantic table selection, especially `mp_parcel`, `cq_osm_roads`, or hallucinated `road`.
2. KNN ordering drift: 31B sometimes orders by `ST_Distance` instead of `geometry <-> geometry`.
3. Runtime guard / empty SQL: 31B full has invalid empty outputs including `runtime_guard:give_up_placeholder` and `runtime_guard:hallucinated_table:road`.
4. Robustness discipline is weaker than the best previous 26B run.

## How To Resume

Run the current 31B benchmark again:

```powershell
cd D:\adk
.\.venv\Scripts\python.exe family12_gemma4_31b_host228_runner.py --mode both
```

Run only full:

```powershell
cd D:\adk
.\.venv\Scripts\python.exe family12_gemma4_31b_host228_runner.py --mode full
```

Resume an interrupted run:

```powershell
cd D:\adk
$env:RESUME_DIR="D:\adk\data_agent\nl2sql_eval_results\<existing_result_dir>"
.\.venv\Scripts\python.exe family12_gemma4_31b_host228_runner.py --mode both
```

## Suggested Next Investigation

1. Re-run a small targeted subset of the 17 lost QIDs with verbose prompts and tool logs enabled.
2. Inspect why 31B chooses `mp_parcel` for land-use questions and whether semantic context ranking or prompt wording makes that table too salient.
3. Add or tune 31B-specific grounding constraints for `cq_land_use_dltb`, `cq_dltb`, `cq_osm_roads_2021`, `cq_buildings_2021`, and `cq_amap_poi_2024`.
4. Strengthen KNN instruction for 31B: use `ORDER BY a.geometry <-> b.geometry LIMIT K` for nearest-neighbor ranking, and use `ST_Distance(...::geography)` only for projected distance columns.
5. Strengthen robustness prompts so write, maintenance, or schema-missing requests produce a refusal or a safe placeholder, not a misleading query.
