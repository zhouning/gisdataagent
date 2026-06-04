# Major Project KG to NL2Semantic2SQL Integration Design

## Context

The user has a full-lifecycle knowledge graph model for national major projects in the natural-resources domain. The business data structure is not sensitive, but real records are sensitive. Implementation must therefore reuse realistic table structure, field semantics, lifecycle stages, graph labels, edge types, and join logic, while generating fully synthetic project records, organization names, identifiers, dates, geometries, approvals, certificates, and spatial relationships.

This design uses the most capable route: PostgreSQL/PostGIS synthetic business tables, an external graph-database export path, graph projection tables for local integration, semantic-layer registration data, and an NL2Semantic2SQL hybrid planner.

## Goals

- Generate synthetic major-project data that resembles the documented real schema without containing real records.
- Cover DBMS tables, PostGIS geometries, knowledge-graph nodes and edges, semantic-layer metadata, and NL2Semantic2SQL benchmark questions.
- Support SQL-only, graph-only, and hybrid graph-to-SQL query flows.
- Keep the initial implementation usable without an external graph server, while producing Neo4j-compatible CSV/Cypher exports for the full graph-database path.
- Preserve association evidence: exact-key match, fuzzy match, spatial overlay, confidence, and provenance.

## Non-Goals

- Do not ingest, infer, or transform real sensitive records.
- Do not allow the LLM to generate unconstrained graph queries against a large external graph database.
- Do not require Neo4j to run the synthetic data generator or PostgreSQL-only tests.
- Do not create a production-grade cross-network data synchronization system in this phase.

## Recommended Approach

Use a dual execution surface:

1. PostgreSQL/PostGIS stores synthetic relational and spatial tables.
2. `kg_nodes` and `kg_edges` store a graph projection inside PostgreSQL for local testing.
3. Neo4j-compatible exports allow the same synthetic graph to be loaded into an external graph database.
4. NL2Semantic2SQL receives semantic-layer hints plus compact graph hints.
5. Hybrid queries resolve lifecycle paths or graph filters first, materialize candidate project IDs into a session-scoped table, then use SQL/PostGIS for aggregation and spatial measurement.

## Architecture

```text
Natural language question
  -> NL2SQL intent classifier
  -> semantic_layer.resolve_semantic_context()
  -> major_project_kg_resolver.resolve()
  -> KG hints + semantic hints + candidate tables
  -> NL2Semantic2SQL grounding prompt
  -> SQL/PostGIS generation or graph-template resolution
  -> optional kg_query_result materialization
  -> final SQL execution and result explanation
```

## Synthetic Relational Schema

The synthetic DBMS schema should use `mp_` table names while preserving documented source-table semantics.

| Synthetic table | Real-structure source | Purpose |
| --- | --- | --- |
| `mp_project_list` | `zz_zdxmqd` | Major project list and project identity anchor |
| `mp_land_plan` | `zz_tdlyjhapqk` | Land-use plan allocation |
| `mp_pre_review` | `xs_xmjbqk` | Construction land pre-review |
| `mp_site_selection` | `xs_xmjbqk_xz` | Planning site selection |
| `mp_conversion_expropriation` | `zz_xmjbqk` | Agricultural land conversion and expropriation |
| `mp_advance_land` | `xx_xmjbqk` | Advance land-use approval for key projects |
| `mp_approval_project` | `t_bpxm` | Land approval project |
| `mp_approval_supply` | `t_bpgy` | Approval-to-supply bridge |
| `mp_land_supply` | `t_gdxm` | Land supply result |
| `mp_land_use_permit` | `yg_xmjbqk` | Construction land planning permit |
| `mp_construction_permit` | `gg_xmjbqk` | Construction engineering planning permit |
| `mp_verification` | `hy_tdhyghhsxx` | Land verification and planning verification |
| `mp_project_parcel` | derived | Project-to-parcel bridge |
| `mp_spatial_overlap` | derived | Spatial overlay relations and overlap ratios |
| `mp_relation_confidence` | derived | Match method, confidence, and evidence |

Core key columns:

- `project_id`: synthetic unified project primary key.
- `zdxmbh`: major project number.
- `zdxm_sec`: major project unique code.
- `flowsn`: workflow number.
- `dzjgh`: electronic supervision number.
- `xs_dzjgh`: pre-review electronic supervision number.
- `ygdzjgh`: land-use planning electronic supervision number.
- `ggdzjgh`: construction planning electronic supervision number.
- `bp_guid`: approval GUID.
- `gd_guid`: land-supply GUID.

Spatial columns should use PostGIS geometry in SRID 4326 unless a test case intentionally exercises missing or invalid SRID handling.

## Knowledge Graph Schema

Use graph projection tables for local execution and external graph exports for Neo4j.

```text
kg_nodes(
  node_id text primary key,
  label text,
  biz_id text,
  name text,
  properties jsonb,
  created_at timestamp
)

kg_edges(
  edge_id text primary key,
  source_node_id text,
  target_node_id text,
  edge_type text,
  confidence numeric,
  match_method text,
  evidence jsonb,
  valid_from date,
  valid_to date
)
```

Node labels:

- `MajorProject`
- `LandPlan`
- `PreReview`
- `SiteSelection`
- `ConversionExpropriation`
- `AdvanceLand`
- `ApprovalProject`
- `ApprovalSupply`
- `LandSupply`
- `LandUsePermit`
- `ConstructionPermit`
- `Verification`
- `Parcel`
- `Organization`
- `Certificate`
- `Material`
- `Indicator`
- `Region`
- `RiskEvent`

Edge types:

- `HAS_LAND_PLAN`
- `HAS_PRE_REVIEW`
- `HAS_SITE_SELECTION`
- `HAS_CONVERSION`
- `HAS_ADVANCE_LAND`
- `HAS_APPROVAL_PROJECT`
- `HAS_APPROVAL_SUPPLY`
- `HAS_LAND_SUPPLY`
- `HAS_LAND_USE_PERMIT`
- `HAS_CONSTRUCTION_PERMIT`
- `HAS_VERIFICATION`
- `OCCUPIES_PARCEL`
- `OVERLAPS_REDLINE`
- `USES_INDICATOR`
- `SUBMITTED_BY`
- `APPROVED_BY`
- `FLOWS_TO`
- `MISSING_STAGE`
- `HAS_RISK`

## Semantic Layer Mapping

The semantic layer is a query-facing projection over the relational schema and graph schema. It should not store all graph facts.

Generated semantic artifacts:

- `semantic_sources.json`: table-level display names, descriptions, synonyms, geometry type, and SRID.
- `semantic_registry.json`: column-level aliases, units, semantic domains, geometry flags, and value semantics.
- `semantic_models.yaml`: MetricFlow-style entities, dimensions, measures, and metrics for major project lifecycle analysis.
- `semantic_relation_map.json`: mapping from natural-language lifecycle relations to graph edges and SQL bridge paths.

Example semantic relation map entry:

```json
{
  "semantic_relation": "project_has_pre_review",
  "kg_edge_type": "HAS_PRE_REVIEW",
  "source_label": "MajorProject",
  "target_label": "PreReview",
  "source_table": "mp_project_list",
  "target_table": "mp_pre_review",
  "source_key": "project_id",
  "target_key": "project_id",
  "confidence_threshold": 0.75,
  "expose_to_prompt": true
}
```

## Synthetic Data Generation

The generator should be deterministic with a configurable random seed. It should never read from real source tables.

Data sizes:

| Profile | Projects | Stage records | Parcels | Graph edges | Purpose |
| --- | ---: | ---: | ---: | ---: | --- |
| `small_dev` | 200 | about 1,000 | about 500 | about 2,000 | development and unit tests |
| `medium_eval` | 5,000 | about 30,000 | about 15,000 | about 80,000 | NL2Semantic2SQL evaluation |
| `stress_optional` | 100,000 | generated on request | generated on request | million-scale | performance testing |

Synthetic record rules:

- Use fictional project names such as `示范重大项目A-0001`.
- Use fictional organization names such as `示范建设单位-023`.
- Use deterministic synthetic codes for `zdxmbh`, `zdxm_sec`, `flowsn`, `dzjgh`, `bp_guid`, and `gd_guid`.
- Generate synthetic polygons inside a fictional coordinate extent or clearly marked demonstration regions.
- Include complete lifecycle chains and controlled error cases.
- Include exact-key, fuzzy-name, and spatial-overlay association evidence.
- Include records with missing stages, delayed stages, duplicate names, missing strong keys, and spatial overlap threshold cases.

Controlled anomaly classes:

- missing pre-review
- pre-review without conversion/expropriation
- supplied land without land-use planning permit
- construction permit without verification
- duplicated project names
- missing strong keys but successful fuzzy match
- missing strong keys but successful spatial overlay
- farmland occupation above threshold
- ecological redline overlap
- overdue approval stage

## Hybrid Query Flow

For graph or lifecycle queries, do not inject large ID lists into prompts. Use a resolver result table:

```text
kg_query_result(
  session_id text,
  project_id text,
  path_summary text,
  confidence numeric,
  evidence jsonb,
  created_at timestamp
)
```

Flow:

1. Classify user intent.
2. Resolve lifecycle or graph relation with `major_project_kg_resolver`.
3. Materialize matching projects into `kg_query_result`.
4. Build NL2SQL context with candidate tables and `kg_hints`.
5. Generate SQL that joins `kg_query_result` for aggregation or spatial analysis.
6. Return result rows plus compact path evidence.

## External Graph Database Export

Primary export format:

- `neo4j_nodes.csv`
- `neo4j_edges.csv`
- `neo4j_import.cypher`

The exports should be generated from the same synthetic graph source as `kg_nodes` and `kg_edges`. The graph adapter should remain pluggable:

```text
graph_backend = postgres_projection | neo4j
```

Initial implementation can validate graph behavior with `postgres_projection`. Neo4j import and query tests can be added once the external graph server is available.

## NL2Semantic2SQL Integration Points

New or updated modules:

- `scripts/synthetic_major_projects/generate_major_project_data.py`
- `data_agent/major_project_kg_resolver.py`
- `data_agent/synthetic/major_projects/`
- optional `data_agent/toolsets/major_project_kg_tools.py`

`major_project_kg_resolver.resolve(question, semantic, intent)` should return:

```json
{
  "matched_entities": [],
  "lifecycle_stage": null,
  "required_edges": [],
  "missing_stage_filter": false,
  "spatial_overlap_threshold": 0.3,
  "candidate_tables": [],
  "join_paths": [],
  "graph_backend": "postgres_projection"
}
```

The resolver output should be added to the NL2SQL grounding payload under `kg_hints`.

## Benchmark Questions

Generate a JSONL benchmark with natural-language questions, expected query class, required tables, required graph relations, and expected result checks.

Question groups:

- SQL-only stage counts.
- SQL-only spatial area statistics.
- Graph-only lifecycle path inspection.
- Hybrid graph-to-SQL aggregation.
- Missing-stage detection.
- Spatial overlay threshold cases.
- Fuzzy association cases.
- Robustness and access-control cases.

Example questions:

- `统计每个生命周期阶段的重大项目数量。`
- `查询已完成用地预审但未完成农转征的项目数量。`
- `统计占用耕地面积超过100亩的重大项目，按地市分组。`
- `列出存在审批流程断点的项目及缺失阶段。`
- `查询通过空间叠加补全关联的项目有哪些。`
- `统计已供地但未完成规划核实的项目面积。`

## Security and Data Hygiene

- Synthetic generation must not call real business APIs or query real source tables.
- Generated identifiers must not resemble real identifiers except for structural format.
- All files should be marked as synthetic/demo data.
- Geometry extents should be fictional or clearly labeled demonstration extents.
- Data lineage should record `synthetic_seed`, `profile`, and `generator_version`.
- Access-control test rows should exist, but no real sensitivity labels should be copied from production.

## Error Handling

- Missing key fields should produce low-confidence associations, not silent joins.
- Fuzzy matches must store confidence and matched fields.
- Spatial overlay matches must store overlap ratio and geometry source.
- Graph resolver must cap traversal depth and returned path count.
- Hybrid query execution must materialize IDs into `kg_query_result` instead of using huge `IN (...)` prompts.
- Neo4j export should remain optional if the graph server is unavailable.

## Testing

Verification commands should cover:

- Synthetic generator determinism under a fixed seed.
- Relational row counts by profile.
- Referential integrity of lifecycle keys.
- PostGIS geometry validity and SRID.
- Graph node/edge consistency.
- Neo4j CSV/Cypher export syntax smoke test.
- Semantic artifact validity.
- NL2Semantic2SQL benchmark execution on `small_dev`.
- No real data leakage by scanning for known production-only strings provided by the user when available.

## Planned Generated Files

```text
scripts/synthetic_major_projects/generate_major_project_data.py
data_agent/synthetic/major_projects/schema_postgis.sql
data_agent/synthetic/major_projects/seed_small.sql
data_agent/synthetic/major_projects/kg_nodes_small.csv
data_agent/synthetic/major_projects/kg_edges_small.csv
data_agent/synthetic/major_projects/neo4j_nodes_small.csv
data_agent/synthetic/major_projects/neo4j_edges_small.csv
data_agent/synthetic/major_projects/neo4j_import.cypher
data_agent/synthetic/major_projects/semantic_sources.json
data_agent/synthetic/major_projects/semantic_registry.json
data_agent/synthetic/major_projects/semantic_models.yaml
data_agent/synthetic/major_projects/semantic_relation_map.json
data_agent/synthetic/major_projects/nl2sql_benchmark_questions.jsonl
```

## Implementation Order

1. Build synthetic schema and data generator.
2. Generate `small_dev` relational, spatial, and graph data.
3. Generate semantic-layer artifacts.
4. Add graph projection import and Neo4j export files.
5. Add `major_project_kg_resolver`.
6. Merge `kg_hints` into NL2SQL grounding payload.
7. Add benchmark questions and verification tests.
8. Run end-to-end NL2Semantic2SQL checks on synthetic data.

## Acceptance Criteria

- `small_dev` can be generated without any production data access.
- PostgreSQL/PostGIS schema loads successfully.
- Graph projection contains nodes and edges for all lifecycle stages.
- Neo4j-compatible CSV/Cypher files are generated from the same synthetic graph.
- Semantic artifacts register major-project tables, columns, metrics, and relation paths.
- At least 30 benchmark questions are generated.
- NL2Semantic2SQL can answer representative SQL-only and hybrid graph-to-SQL questions on synthetic data.
- Missing-stage and spatial-overlap cases are present and queryable.
