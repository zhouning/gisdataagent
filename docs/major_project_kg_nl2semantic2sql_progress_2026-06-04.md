# Major Project KG + NL2Semantic2SQL Progress

Date: 2026-06-04
Branch: `feat/v12-extensible-platform`

## Current Status

The synthetic major-project knowledge-graph route is implemented and pushed to
GitHub. It uses synthetic data only: table structures, lifecycle stages, graph
labels, relation types, semantic metadata, and benchmark questions are modeled
after the major-project domain, but no production records are included.

The current integration supports this route:

1. Synthetic PostGIS tables in Huawei Cloud PostgreSQL/PostGIS.
2. Synthetic graph data in local Neo4j Desktop database `zdxmdb`.
3. NL2Semantic2SQL grounding with KG hints.
4. Gemma/Ollama direct NL2SQL execution via `DirectNL2SemanticSQLAgent`.
5. End-to-end smoke verification from benchmark questions.

## Local Environment Notes

The local `data_agent/.env` has been configured for this route and is ignored by
git. It contains local Neo4j and NL2SQL runtime settings. Do not commit this
file or copy its secrets into documentation.

Important runtime settings:

- `NL2SQL_AGENT_MODEL=gemma4-26b-host9`
- `MAJOR_PROJECT_KG_BACKEND=neo4j`
- `NEO4J_URI=neo4j://127.0.0.1:7687`
- `NEO4J_DATABASE=zdxmdb`
- `NL2SQL_DISABLE_FEWSHOT=1`

The global standard model tier remains `gemini-2.5-flash`; only the `@NL2SQL`
mention path is routed through `NL2SQL_AGENT_MODEL`.

Windows note: C drive temporary space was full during testing. Use `D:\tmp` for
pytest and smoke temp output:

```powershell
$env:TEMP='D:\tmp'
$env:TMP='D:\tmp'
```

## Completed Implementation

Key commits:

- `4338729 fix: preserve actionable major project kg grounding`
- `eacbaf7 feat: add optional neo4j major project kg backend`
- `2804b08 fix: prioritize graph projection tables for major project kg smoke`
- `25bb58b test: add major project kg nl2sql smoke runner`
- `e580b7e fix: route nl2sql mention through configured direct model`

Important files:

- `scripts/synthetic_major_projects/generate_major_project_data.py`
- `scripts/synthetic_major_projects/smoke_major_project_kg_nl2sql.py`
- `data_agent/major_project_kg_resolver.py`
- `data_agent/nl2sql_grounding.py`
- `data_agent/agent.py`
- `data_agent/nl2semantic2sql_direct_agent.py`
- `data_agent/synthetic/major_projects/README.md`

## Verified Results

Neo4j import:

- Database: `zdxmdb`
- Nodes: 2,422
- Relationships: 4,039
- Important relationship counts:
  - `OCCUPIES_PARCEL`: 200
  - `SPATIALLY_OVERLAPS`: 25
  - `FUZZY_PROJECT_PARCEL_MATCH`: 20

End-to-end smoke runner:

```powershell
$env:TEMP='D:\tmp'
$env:TMP='D:\tmp'
.\.venv\Scripts\python.exe scripts\synthetic_major_projects\smoke_major_project_kg_nl2sql.py
```

Result:

- `mp_bench_sql_type_001`: `ok`, 5 rows
- `mp_bench_graph_missing_001`: `ok`, 28 rows, SQL uses `kg_edges`, `kg_nodes`, `MISSING_STAGE`
- `mp_bench_hybrid_pre_no_conv_001`: `ok`, 0 rows
- `mp_bench_hybrid_spatial_002`: `ok`, 10 rows, SQL uses `mp_spatial_overlap`
- `mp_bench_farmland_001`: `ok`, 38 rows, SQL uses `mp_relation_confidence` and `mp_parcel`

Regression tests run:

- Major-project KG suite: `39 passed, 1 warning`
- Nearby NL2SQL/semantic suite: `44 passed, 1 warning`
- NL2SQL builder/direct path suite: `11 passed, 1 warning`
- Focused builder suite after final edit: `3 passed, 1 warning`

Warnings:

- `ArcPyBridge` startup warning appears during some checks and is non-blocking
  for this NL2SQL/KG route.
- Some old pytest temp directories show permission warnings in `git status`;
  they were not touched.

## How To Resume

1. Pull or checkout branch:

```powershell
git checkout feat/v12-extensible-platform
git pull origin feat/v12-extensible-platform
```

2. Ensure Neo4j Desktop DBMS/database is running:

- Bolt URI: `neo4j://127.0.0.1:7687`
- Database: `zdxmdb`

3. Ensure Ollama is reachable:

```powershell
Invoke-RestMethod -Uri "http://192.168.43.9:11434/api/tags" -TimeoutSec 10
```

4. Run smoke:

```powershell
$env:TEMP='D:\tmp'
$env:TMP='D:\tmp'
.\.venv\Scripts\python.exe scripts\synthetic_major_projects\smoke_major_project_kg_nl2sql.py
```

5. Test in GIS Data Agent with `@NL2SQL`:

```text
@NL2SQL 找出知识图谱中缺少用地预审阶段的重大项目。
@NL2SQL 列出与地块存在空间叠加关系的重大项目名称、叠加比例和叠加面积。
@NL2SQL 列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。
```

If the application server was already running before the `.env` or code changes,
restart it before testing `@NL2SQL`.

## Remaining Follow-Ups

- Investigate whether `mp_bench_hybrid_pre_no_conv_001` returning 0 rows is an
  acceptable synthetic-data outcome or whether the generator should guarantee at
  least one such case.
- Fix or bypass Ollama embedding `/api/embeddings` 404 before re-enabling
  few-shot retrieval and auto-curation.
- Consider adding a small UI/admin health check that reports active KG backend,
  Neo4j database, selected NL2SQL model, and smoke status without exposing
  credentials.

## GitHub Push

The branch was pushed to GitHub:

```text
origin/feat/v12-extensible-platform
```

Latest pushed commit before this progress note:

```text
e580b7e fix: route nl2sql mention through configured direct model
```
