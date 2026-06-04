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

## Optional PostGIS Load

Requires PostgreSQL with PostGIS enabled. For Huawei Cloud DB development, set
`DATABASE_URL` to the demo/test database or schema, then run from this directory:

```powershell
psql "$env:DATABASE_URL" -f schema_postgis.sql
psql "$env:DATABASE_URL" -f seed_small.sql
```

These files are synthetic fixtures. Load them only into a demo/test namespace,
not a production schema.

## Optional Neo4j Load

Neo4j is optional and only validates the external graph-database route. Current
local NL2Semantic2SQL integration uses Postgres projection KG hints and does not
require a Neo4j runtime. Neo4j Desktop is sufficient; Neo4j Server is not needed
for current local development.

For Neo4j Desktop 2.1.4 on Windows:

1. Create a local project, DBMS, and database if none exists.
2. Start the DBMS/database.
3. Locate or open the DBMS import directory from Desktop.
4. Copy `neo4j_nodes_small.csv`, `neo4j_edges_small.csv`, and
   `neo4j_import.cypher` into the import directory.
5. Open Neo4j Browser and run:

```cypher
:source neo4j_import.cypher
```
