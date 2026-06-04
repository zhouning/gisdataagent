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
`DATABASE_URL` only to an isolated demo/test database. If using a shared test
database, first verify the connection uses an explicit dedicated schema or
`search_path` for these synthetic tables.

The seed file runs `TRUNCATE TABLE ... RESTART IDENTITY`, and the SQL is not
schema-qualified. Do not run these commands against production, any production
clone, or any shared schema that contains real or manually curated tables.

After verifying the target is isolated, run from this directory:

```powershell
psql "$env:DATABASE_URL" -f schema_postgis.sql
psql "$env:DATABASE_URL" -f seed_small.sql
```

## Optional Neo4j Load

Neo4j is optional and only validates the external graph-database route. Current
local NL2Semantic2SQL integration uses Postgres projection KG hints and does not
require a Neo4j runtime. Neo4j Desktop is sufficient; Neo4j Server is not needed
for current local development.

For Neo4j Desktop 2.1.4 on Windows:

1. Create a dedicated empty synthetic project, DBMS, and database. Do not use an
   existing real graph or local production graph.
2. Start the DBMS/database.
3. Locate or open the DBMS import directory from Desktop.
4. Copy `neo4j_nodes_small.csv`, `neo4j_edges_small.csv`, and
   `neo4j_import.cypher` into the import directory.
5. Load the Cypher with one of these Desktop-safe options:
   - Open `neo4j_import.cypher`, paste its contents into Neo4j Browser or Query,
     and run it against the dedicated synthetic database.
   - From the import directory, run:

```powershell
cypher-shell -u neo4j -p <password> -f neo4j_import.cypher
```

The import creates synthetic nodes and edges. Do not run it against real graph
data or any shared local production graph.
