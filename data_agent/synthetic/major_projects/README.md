# Synthetic Major-Project Artifacts

These files are synthetic only. They preserve the business structure needed for
major-project lifecycle, land-use, parcel, knowledge-graph, and Chinese NL2SQL
grounding tests, but they contain no production records and no copied customer
data.

The generated artifacts include:

- PostGIS schema and seed SQL for synthetic major-project tables.
- KG and Neo4j CSV exports for synthetic nodes and edges.
- Neo4j import Cypher marked as synthetic/no-production data.
- Semantic source, registry, model, and relation-map files for Chinese NL2SQL
  grounding.
- A small JSONL benchmark seed set for SQL-only, graph, and hybrid routing.

Regenerate the runtime artifacts from the repository root with:

```powershell
python scripts\synthetic_major_projects\generate_major_project_data.py --profile small_dev --project-count 200 --seed 20260604 --output-dir data_agent\synthetic\major_projects
```
