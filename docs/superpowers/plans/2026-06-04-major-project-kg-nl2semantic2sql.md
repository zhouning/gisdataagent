# Major Project KG NL2Semantic2SQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build synthetic major-project DBMS and KG data, export Neo4j-compatible graph files, register semantic-layer artifacts, and integrate compact KG hints into NL2Semantic2SQL grounding.

**Architecture:** A deterministic generator produces PostgreSQL/PostGIS SQL, graph projection rows, Neo4j CSV/Cypher, semantic-layer JSON/YAML, and benchmark questions without reading any production records. A `major_project_kg_resolver` maps natural-language lifecycle and graph intents to compact `kg_hints`; `nl2sql_grounding.build_nl2sql_context()` merges those hints into the grounding payload. Full graph-database capability is supported through Neo4j export while local tests use PostgreSQL-style graph projection files.

**Tech Stack:** Python standard library, pytest, PostgreSQL/PostGIS SQL text generation, JSON/YAML artifact generation, Neo4j CSV/Cypher export, existing `data_agent.nl2sql_grounding` and semantic-layer patterns.

---

## Environment and Middleware

Required to generate files and run unit tests:

- Existing Python environment used by this repository.
- `pytest`.
- No external graph database is required for generator or unit tests.
- No real production data source is required or allowed.

Required only to load generated SQL into a live database:

- PostgreSQL with PostGIS extension enabled.
- A database user with permission to create demo tables in a test schema.

Required only for external graph-database import tests:

- Neo4j Desktop, Neo4j Server, or Neo4j running in Docker.
- The generated `neo4j_nodes_small.csv`, `neo4j_edges_small.csv`, and `neo4j_import.cypher` files.

If Neo4j is not installed, implement and test all local functionality with the Postgres graph projection files first.

## File Structure

- Create `scripts/synthetic_major_projects/generate_major_project_data.py`
  - Deterministic synthetic data generator and file writer.
- Create `scripts/synthetic_major_projects/__init__.py`
  - Package marker for imports in tests.
- Create `data_agent/major_project_kg_resolver.py`
  - Query-time lifecycle and graph hint resolver.
- Modify `data_agent/nl2sql_grounding.py`
  - Merge `kg_hints` into the grounding payload and prompt formatter.
- Create `data_agent/synthetic/major_projects/README.md`
  - Explains generated artifacts and safe-use rules.
- Generated at runtime under `data_agent/synthetic/major_projects/`
  - `schema_postgis.sql`
  - `seed_small.sql`
  - `kg_nodes_small.csv`
  - `kg_edges_small.csv`
  - `neo4j_nodes_small.csv`
  - `neo4j_edges_small.csv`
  - `neo4j_import.cypher`
  - `semantic_sources.json`
  - `semantic_registry.json`
  - `semantic_models.yaml`
  - `semantic_relation_map.json`
  - `nl2sql_benchmark_questions.jsonl`
- Create `data_agent/test_major_project_synthetic_generator.py`
  - Generator tests.
- Create `data_agent/test_major_project_kg_resolver.py`
  - Resolver tests.
- Create `data_agent/test_nl2sql_major_project_kg_hints.py`
  - Grounding integration tests.

---

### Task 1: Synthetic Generator Core

**Files:**
- Create: `scripts/synthetic_major_projects/__init__.py`
- Create: `scripts/synthetic_major_projects/generate_major_project_data.py`
- Test: `data_agent/test_major_project_synthetic_generator.py`

- [ ] **Step 1: Create package marker**

Create `scripts/synthetic_major_projects/__init__.py` with:

```python
"""Synthetic major-project data generation utilities."""
```

- [ ] **Step 2: Write failing generator determinism test**

Create `data_agent/test_major_project_synthetic_generator.py` with:

```python
from scripts.synthetic_major_projects.generate_major_project_data import (
    GenerationConfig,
    SyntheticMajorProjectGenerator,
)


def test_generator_is_deterministic_for_same_seed():
    cfg = GenerationConfig(profile="small_dev", project_count=5, seed=42)
    first = SyntheticMajorProjectGenerator(cfg).build()
    second = SyntheticMajorProjectGenerator(cfg).build()

    assert first.projects == second.projects
    assert first.land_plans == second.land_plans
    assert first.kg_nodes == second.kg_nodes
    assert first.kg_edges == second.kg_edges


def test_small_profile_contains_expected_lifecycle_anomalies():
    cfg = GenerationConfig(profile="small_dev", project_count=30, seed=7)
    data = SyntheticMajorProjectGenerator(cfg).build()

    anomaly_types = {edge["edge_type"] for edge in data.kg_edges}
    assert "MISSING_STAGE" in anomaly_types
    assert "HAS_RISK" in anomaly_types
    assert any(row["match_method"] == "spatial_overlay" for row in data.relation_confidence)
    assert any(row["match_method"] == "fuzzy_name" for row in data.relation_confidence)
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_synthetic_generator.py -q
```

Expected: fails because `scripts.synthetic_major_projects.generate_major_project_data` does not exist.

- [ ] **Step 4: Implement generator data classes and deterministic build**

Create `scripts/synthetic_major_projects/generate_major_project_data.py` with these public types and methods:

```python
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LIFECYCLE_STAGES = [
    "project_list",
    "land_plan",
    "pre_review",
    "site_selection",
    "conversion_expropriation",
    "approval_project",
    "approval_supply",
    "land_supply",
    "land_use_permit",
    "construction_permit",
    "verification",
]


@dataclass(frozen=True)
class GenerationConfig:
    profile: str = "small_dev"
    project_count: int = 200
    seed: int = 20260604
    output_dir: Path = Path("data_agent/synthetic/major_projects")


@dataclass
class SyntheticDataBundle:
    projects: list[dict[str, Any]] = field(default_factory=list)
    land_plans: list[dict[str, Any]] = field(default_factory=list)
    pre_reviews: list[dict[str, Any]] = field(default_factory=list)
    site_selections: list[dict[str, Any]] = field(default_factory=list)
    conversions: list[dict[str, Any]] = field(default_factory=list)
    approval_projects: list[dict[str, Any]] = field(default_factory=list)
    approval_supplies: list[dict[str, Any]] = field(default_factory=list)
    land_supplies: list[dict[str, Any]] = field(default_factory=list)
    land_use_permits: list[dict[str, Any]] = field(default_factory=list)
    construction_permits: list[dict[str, Any]] = field(default_factory=list)
    verifications: list[dict[str, Any]] = field(default_factory=list)
    parcels: list[dict[str, Any]] = field(default_factory=list)
    spatial_overlaps: list[dict[str, Any]] = field(default_factory=list)
    relation_confidence: list[dict[str, Any]] = field(default_factory=list)
    kg_nodes: list[dict[str, Any]] = field(default_factory=list)
    kg_edges: list[dict[str, Any]] = field(default_factory=list)


class SyntheticMajorProjectGenerator:
    def __init__(self, config: GenerationConfig):
        self.config = config
        self.rng = random.Random(config.seed)

    def build(self) -> SyntheticDataBundle:
        bundle = SyntheticDataBundle()
        for idx in range(1, self.config.project_count + 1):
            project = self._project(idx)
            bundle.projects.append(project)
            self._append_project_graph(bundle, project)
            self._append_lifecycle_records(bundle, project, idx)
            self._append_parcels_and_spatial_relations(bundle, project, idx)
        return bundle

    def _project(self, idx: int) -> dict[str, Any]:
        region = self.rng.choice(["示范省A", "示范省B", "示范省C"])
        return {
            "project_id": f"MP{idx:06d}",
            "zdxmbh": f"ZDXM-{idx:06d}",
            "zdxm_sec": f"SEC-{idx:08d}",
            "project_name": f"示范重大项目-{idx:06d}",
            "project_type": self.rng.choice(["交通", "能源", "水利", "产业园区", "民生"]),
            "province": region,
            "city": f"{region}示范市{idx % 5 + 1}",
            "county": f"示范县{idx % 9 + 1}",
            "construction_unit": f"示范建设单位-{idx % 37 + 1:03d}",
            "total_investment_million": round(self.rng.uniform(80, 5000), 2),
            "planned_land_area_mu": round(self.rng.uniform(10, 1200), 2),
            "list_year": 2022 + idx % 5,
            "status": self.rng.choice(["储备", "审批中", "已供地", "建设中", "已核实"]),
            "geom_wkt": self._square_wkt(idx),
        }

    def _square_wkt(self, idx: int) -> str:
        base_x = 100.0 + (idx % 50) * 0.02
        base_y = 30.0 + (idx % 40) * 0.02
        size = 0.005 + (idx % 5) * 0.001
        return (
            f"POLYGON(({base_x} {base_y}, {base_x + size} {base_y}, "
            f"{base_x + size} {base_y + size}, {base_x} {base_y + size}, "
            f"{base_x} {base_y}))"
        )

    def _append_project_graph(self, bundle: SyntheticDataBundle, project: dict[str, Any]) -> None:
        bundle.kg_nodes.append({
            "node_id": f"project:{project['project_id']}",
            "label": "MajorProject",
            "biz_id": project["project_id"],
            "name": project["project_name"],
            "properties": json.dumps(project, ensure_ascii=False),
        })

    def _append_lifecycle_records(self, bundle: SyntheticDataBundle, project: dict[str, Any], idx: int) -> None:
        project_id = project["project_id"]
        zdxmbh = project["zdxmbh"]
        flowsn = f"FLOW-{idx:08d}"
        dzjgh = f"DZJGH-{idx:08d}"
        if idx % 6 != 0:
            plan = {"plan_id": f"PLAN{idx:06d}", "project_id": project_id, "zdxmbh": zdxmbh, "flowsn": flowsn}
            bundle.land_plans.append(plan)
            self._add_node_edge(bundle, project, "LandPlan", plan["plan_id"], "HAS_LAND_PLAN", 0.98, "exact_key")
        if idx % 7 != 0:
            pre = {"pre_review_id": f"PRE{idx:06d}", "project_id": project_id, "dzjgh": dzjgh, "xs_dzjgh": dzjgh}
            bundle.pre_reviews.append(pre)
            self._add_node_edge(bundle, project, "PreReview", pre["pre_review_id"], "HAS_PRE_REVIEW", 0.95, "exact_key")
        else:
            self._add_missing_stage(bundle, project, "pre_review")
        if idx % 5 != 0:
            conversion = {"conversion_id": f"CONV{idx:06d}", "project_id": project_id, "flowsn": flowsn, "dzjgh": dzjgh}
            bundle.conversions.append(conversion)
            self._add_node_edge(bundle, project, "ConversionExpropriation", conversion["conversion_id"], "HAS_CONVERSION", 0.93, "exact_key")
        if idx % 4 != 0:
            supply = {"land_supply_id": f"SUP{idx:06d}", "project_id": project_id, "gd_guid": f"GD-{idx:08d}"}
            bundle.land_supplies.append(supply)
            self._add_node_edge(bundle, project, "LandSupply", supply["land_supply_id"], "HAS_LAND_SUPPLY", 0.90, "exact_key")
        if idx % 9 == 0:
            self._add_risk(bundle, project, "overdue_approval")

    def _append_parcels_and_spatial_relations(self, bundle: SyntheticDataBundle, project: dict[str, Any], idx: int) -> None:
        parcel = {
            "parcel_id": f"PARCEL{idx:06d}",
            "project_id": project["project_id"],
            "land_use_type": self.rng.choice(["耕地", "建设用地", "林地", "未利用地"]),
            "area_mu": round(project["planned_land_area_mu"] * self.rng.uniform(0.5, 1.2), 2),
            "geom_wkt": project["geom_wkt"],
        }
        bundle.parcels.append(parcel)
        method = "spatial_overlay" if idx % 8 == 0 else ("fuzzy_name" if idx % 10 == 0 else "exact_key")
        confidence = 0.72 if method == "spatial_overlay" else (0.81 if method == "fuzzy_name" else 0.99)
        bundle.relation_confidence.append({
            "project_id": project["project_id"],
            "target_id": parcel["parcel_id"],
            "relation_type": "OCCUPIES_PARCEL",
            "match_method": method,
            "confidence": confidence,
            "evidence": json.dumps({"overlap_ratio": 0.35 if method == "spatial_overlay" else 1.0}, ensure_ascii=False),
        })
        self._add_node_edge(bundle, project, "Parcel", parcel["parcel_id"], "OCCUPIES_PARCEL", confidence, method)

    def _add_node_edge(
        self,
        bundle: SyntheticDataBundle,
        project: dict[str, Any],
        label: str,
        target_id: str,
        edge_type: str,
        confidence: float,
        match_method: str,
    ) -> None:
        node_id = f"{label.lower()}:{target_id}"
        bundle.kg_nodes.append({
            "node_id": node_id,
            "label": label,
            "biz_id": target_id,
            "name": f"{label}-{target_id}",
            "properties": json.dumps({"biz_id": target_id}, ensure_ascii=False),
        })
        bundle.kg_edges.append({
            "edge_id": f"edge:{project['project_id']}:{edge_type}:{target_id}",
            "source_node_id": f"project:{project['project_id']}",
            "target_node_id": node_id,
            "edge_type": edge_type,
            "confidence": confidence,
            "match_method": match_method,
            "evidence": json.dumps({"source": "synthetic"}, ensure_ascii=False),
        })

    def _add_missing_stage(self, bundle: SyntheticDataBundle, project: dict[str, Any], stage: str) -> None:
        bundle.kg_edges.append({
            "edge_id": f"edge:{project['project_id']}:MISSING_STAGE:{stage}",
            "source_node_id": f"project:{project['project_id']}",
            "target_node_id": f"stage:{stage}",
            "edge_type": "MISSING_STAGE",
            "confidence": 1.0,
            "match_method": "rule",
            "evidence": json.dumps({"missing_stage": stage}, ensure_ascii=False),
        })

    def _add_risk(self, bundle: SyntheticDataBundle, project: dict[str, Any], risk_type: str) -> None:
        risk_id = f"risk:{project['project_id']}:{risk_type}"
        bundle.kg_nodes.append({
            "node_id": risk_id,
            "label": "RiskEvent",
            "biz_id": risk_id,
            "name": risk_type,
            "properties": json.dumps({"risk_type": risk_type}, ensure_ascii=False),
        })
        bundle.kg_edges.append({
            "edge_id": f"edge:{project['project_id']}:HAS_RISK:{risk_type}",
            "source_node_id": f"project:{project['project_id']}",
            "target_node_id": risk_id,
            "edge_type": "HAS_RISK",
            "confidence": 0.88,
            "match_method": "rule",
            "evidence": json.dumps({"source": "synthetic_rule"}, ensure_ascii=False),
        })
```

- [ ] **Step 5: Run generator tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_synthetic_generator.py -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add scripts\synthetic_major_projects data_agent\test_major_project_synthetic_generator.py
git commit -m "feat: add major project synthetic generator core"
```

---

### Task 2: File Writers for SQL, CSV, Cypher, and Semantic Artifacts

**Files:**
- Modify: `scripts/synthetic_major_projects/generate_major_project_data.py`
- Create: `data_agent/synthetic/major_projects/README.md`
- Test: `data_agent/test_major_project_synthetic_generator.py`

- [ ] **Step 1: Add failing artifact writer test**

Append to `data_agent/test_major_project_synthetic_generator.py`:

```python
import csv
import json


def test_generator_writes_expected_artifacts(tmp_path):
    cfg = GenerationConfig(profile="small_dev", project_count=12, seed=11, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(cfg)
    bundle = generator.build()
    written = generator.write_all(bundle)

    expected = {
        "schema_postgis.sql",
        "seed_small.sql",
        "kg_nodes_small.csv",
        "kg_edges_small.csv",
        "neo4j_nodes_small.csv",
        "neo4j_edges_small.csv",
        "neo4j_import.cypher",
        "semantic_sources.json",
        "semantic_registry.json",
        "semantic_models.yaml",
        "semantic_relation_map.json",
        "nl2sql_benchmark_questions.jsonl",
    }
    assert expected.issubset({p.name for p in written})
    assert (tmp_path / "seed_small.sql").read_text(encoding="utf-8").startswith("-- Synthetic major-project seed data")
    assert "CREATE TABLE IF NOT EXISTS mp_project_list" in (tmp_path / "schema_postgis.sql").read_text(encoding="utf-8")

    with (tmp_path / "kg_nodes_small.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows
    assert {"node_id", "label", "biz_id", "name", "properties"}.issubset(rows[0])

    semantic_sources = json.loads((tmp_path / "semantic_sources.json").read_text(encoding="utf-8"))
    assert any(row["table_name"] == "mp_project_list" for row in semantic_sources)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_synthetic_generator.py::test_generator_writes_expected_artifacts -q
```

Expected: fails because `write_all` does not exist.

- [ ] **Step 3: Implement writer methods**

Add these methods to `SyntheticMajorProjectGenerator`:

```python
    def write_all(self, bundle: SyntheticDataBundle) -> list[Path]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        written = [
            self._write_text("schema_postgis.sql", self._schema_sql()),
            self._write_text("seed_small.sql", self._seed_sql(bundle)),
            self._write_csv("kg_nodes_small.csv", bundle.kg_nodes, ["node_id", "label", "biz_id", "name", "properties"]),
            self._write_csv(
                "kg_edges_small.csv",
                bundle.kg_edges,
                ["edge_id", "source_node_id", "target_node_id", "edge_type", "confidence", "match_method", "evidence"],
            ),
            self._write_csv("neo4j_nodes_small.csv", bundle.kg_nodes, ["node_id", "label", "biz_id", "name", "properties"]),
            self._write_csv(
                "neo4j_edges_small.csv",
                bundle.kg_edges,
                ["edge_id", "source_node_id", "target_node_id", "edge_type", "confidence", "match_method", "evidence"],
            ),
            self._write_text("neo4j_import.cypher", self._neo4j_cypher()),
            self._write_text("semantic_sources.json", json.dumps(self._semantic_sources(), ensure_ascii=False, indent=2)),
            self._write_text("semantic_registry.json", json.dumps(self._semantic_registry(), ensure_ascii=False, indent=2)),
            self._write_text("semantic_models.yaml", self._semantic_models_yaml()),
            self._write_text("semantic_relation_map.json", json.dumps(self._semantic_relation_map(), ensure_ascii=False, indent=2)),
            self._write_text("nl2sql_benchmark_questions.jsonl", self._benchmark_questions_jsonl()),
        ]
        return written

    def _write_text(self, filename: str, content: str) -> Path:
        path = self.config.output_dir / filename
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def _write_csv(self, filename: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
        path = self.config.output_dir / filename
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
        return path
```

Add `_schema_sql()`:

```python
    def _schema_sql(self) -> str:
        return """-- Synthetic major-project schema. Contains no production records.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS mp_project_list (
  project_id text PRIMARY KEY,
  zdxmbh text UNIQUE,
  zdxm_sec text UNIQUE,
  project_name text,
  project_type text,
  province text,
  city text,
  county text,
  construction_unit text,
  total_investment_million numeric,
  planned_land_area_mu numeric,
  list_year integer,
  status text,
  geom geometry(Polygon, 4326)
);

CREATE TABLE IF NOT EXISTS mp_land_plan (
  plan_id text PRIMARY KEY,
  project_id text REFERENCES mp_project_list(project_id),
  zdxmbh text,
  flowsn text
);

CREATE TABLE IF NOT EXISTS mp_pre_review (
  pre_review_id text PRIMARY KEY,
  project_id text REFERENCES mp_project_list(project_id),
  dzjgh text,
  xs_dzjgh text
);

CREATE TABLE IF NOT EXISTS mp_conversion_expropriation (
  conversion_id text PRIMARY KEY,
  project_id text REFERENCES mp_project_list(project_id),
  flowsn text,
  dzjgh text
);

CREATE TABLE IF NOT EXISTS mp_land_supply (
  land_supply_id text PRIMARY KEY,
  project_id text REFERENCES mp_project_list(project_id),
  gd_guid text
);

CREATE TABLE IF NOT EXISTS mp_parcel (
  parcel_id text PRIMARY KEY,
  project_id text REFERENCES mp_project_list(project_id),
  land_use_type text,
  area_mu numeric,
  geom geometry(Polygon, 4326)
);

CREATE TABLE IF NOT EXISTS mp_relation_confidence (
  project_id text,
  target_id text,
  relation_type text,
  match_method text,
  confidence numeric,
  evidence jsonb
);

CREATE TABLE IF NOT EXISTS kg_nodes (
  node_id text PRIMARY KEY,
  label text,
  biz_id text,
  name text,
  properties jsonb,
  created_at timestamp DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kg_edges (
  edge_id text PRIMARY KEY,
  source_node_id text,
  target_node_id text,
  edge_type text,
  confidence numeric,
  match_method text,
  evidence jsonb,
  valid_from date,
  valid_to date
);

CREATE TABLE IF NOT EXISTS kg_query_result (
  session_id text,
  project_id text,
  path_summary text,
  confidence numeric,
  evidence jsonb,
  created_at timestamp DEFAULT now()
);
"""
```

Add `_seed_sql()` with SQL escaping:

```python
    def _sql_str(self, value: Any) -> str:
        if value is None:
            return "NULL"
        return "'" + str(value).replace("'", "''") + "'"

    def _seed_sql(self, bundle: SyntheticDataBundle) -> str:
        lines = ["-- Synthetic major-project seed data. Contains no production records."]
        for row in bundle.projects:
            lines.append(
                "INSERT INTO mp_project_list "
                "(project_id,zdxmbh,zdxm_sec,project_name,project_type,province,city,county,construction_unit,"
                "total_investment_million,planned_land_area_mu,list_year,status,geom) VALUES "
                f"({self._sql_str(row['project_id'])},{self._sql_str(row['zdxmbh'])},{self._sql_str(row['zdxm_sec'])},"
                f"{self._sql_str(row['project_name'])},{self._sql_str(row['project_type'])},{self._sql_str(row['province'])},"
                f"{self._sql_str(row['city'])},{self._sql_str(row['county'])},{self._sql_str(row['construction_unit'])},"
                f"{row['total_investment_million']},{row['planned_land_area_mu']},{row['list_year']},"
                f"{self._sql_str(row['status'])},ST_GeomFromText({self._sql_str(row['geom_wkt'])},4326));"
            )
        for row in bundle.land_plans:
            lines.append(
                "INSERT INTO mp_land_plan (plan_id,project_id,zdxmbh,flowsn) VALUES "
                f"({self._sql_str(row['plan_id'])},{self._sql_str(row['project_id'])},{self._sql_str(row['zdxmbh'])},{self._sql_str(row['flowsn'])});"
            )
        for row in bundle.pre_reviews:
            lines.append(
                "INSERT INTO mp_pre_review (pre_review_id,project_id,dzjgh,xs_dzjgh) VALUES "
                f"({self._sql_str(row['pre_review_id'])},{self._sql_str(row['project_id'])},{self._sql_str(row['dzjgh'])},{self._sql_str(row['xs_dzjgh'])});"
            )
        for row in bundle.conversions:
            lines.append(
                "INSERT INTO mp_conversion_expropriation (conversion_id,project_id,flowsn,dzjgh) VALUES "
                f"({self._sql_str(row['conversion_id'])},{self._sql_str(row['project_id'])},{self._sql_str(row['flowsn'])},{self._sql_str(row['dzjgh'])});"
            )
        for row in bundle.land_supplies:
            lines.append(
                "INSERT INTO mp_land_supply (land_supply_id,project_id,gd_guid) VALUES "
                f"({self._sql_str(row['land_supply_id'])},{self._sql_str(row['project_id'])},{self._sql_str(row['gd_guid'])});"
            )
        for row in bundle.parcels:
            lines.append(
                "INSERT INTO mp_parcel (parcel_id,project_id,land_use_type,area_mu,geom) VALUES "
                f"({self._sql_str(row['parcel_id'])},{self._sql_str(row['project_id'])},{self._sql_str(row['land_use_type'])},"
                f"{row['area_mu']},ST_GeomFromText({self._sql_str(row['geom_wkt'])},4326));"
            )
        for row in bundle.relation_confidence:
            lines.append(
                "INSERT INTO mp_relation_confidence (project_id,target_id,relation_type,match_method,confidence,evidence) VALUES "
                f"({self._sql_str(row['project_id'])},{self._sql_str(row['target_id'])},{self._sql_str(row['relation_type'])},"
                f"{self._sql_str(row['match_method'])},{row['confidence']},{self._sql_str(row['evidence'])}::jsonb);"
            )
        for row in bundle.kg_nodes:
            lines.append(
                "INSERT INTO kg_nodes (node_id,label,biz_id,name,properties) VALUES "
                f"({self._sql_str(row['node_id'])},{self._sql_str(row['label'])},{self._sql_str(row['biz_id'])},"
                f"{self._sql_str(row['name'])},{self._sql_str(row['properties'])}::jsonb);"
            )
        for row in bundle.kg_edges:
            lines.append(
                "INSERT INTO kg_edges (edge_id,source_node_id,target_node_id,edge_type,confidence,match_method,evidence) VALUES "
                f"({self._sql_str(row['edge_id'])},{self._sql_str(row['source_node_id'])},{self._sql_str(row['target_node_id'])},"
                f"{self._sql_str(row['edge_type'])},{row['confidence']},{self._sql_str(row['match_method'])},{self._sql_str(row['evidence'])}::jsonb);"
            )
        return "\n".join(lines) + "\n"
```

Add semantic and benchmark artifact methods:

```python
    def _semantic_sources(self) -> list[dict[str, Any]]:
        return [
            {"table_name": "mp_project_list", "display_name": "重大项目清单", "description": "合成重大项目主表", "geometry_type": "Polygon", "srid": 4326, "synonyms": ["重大项目", "重点项目", "项目清单"]},
            {"table_name": "mp_land_plan", "display_name": "土地利用计划安排", "description": "合成土地利用计划阶段表", "geometry_type": None, "srid": None, "synonyms": ["土地利用计划", "计划安排"]},
            {"table_name": "mp_pre_review", "display_name": "用地预审", "description": "合成建设项目用地预审表", "geometry_type": None, "srid": None, "synonyms": ["用地预审", "预审意见"]},
            {"table_name": "mp_conversion_expropriation", "display_name": "农转用与土地征收", "description": "合成农转征审批表", "geometry_type": None, "srid": None, "synonyms": ["农转征", "土地征收", "农用地转用"]},
            {"table_name": "mp_land_supply", "display_name": "土地供应", "description": "合成供地结果表", "geometry_type": None, "srid": None, "synonyms": ["供地", "土地供应"]},
            {"table_name": "mp_parcel", "display_name": "项目地块", "description": "合成项目地块空间表", "geometry_type": "Polygon", "srid": 4326, "synonyms": ["地块", "项目范围", "用地范围"]},
        ]

    def _semantic_registry(self) -> list[dict[str, Any]]:
        return [
            {"table_name": "mp_project_list", "column_name": "project_id", "semantic_domain": "PROJECT_ID", "aliases": ["项目ID"], "unit": None, "is_geometry": False},
            {"table_name": "mp_project_list", "column_name": "zdxmbh", "semantic_domain": "PROJECT_CODE", "aliases": ["重大项目编号"], "unit": None, "is_geometry": False},
            {"table_name": "mp_project_list", "column_name": "planned_land_area_mu", "semantic_domain": "AREA", "aliases": ["计划用地面积"], "unit": "亩", "is_geometry": False},
            {"table_name": "mp_project_list", "column_name": "geom", "semantic_domain": "GEOMETRY", "aliases": ["项目范围"], "unit": None, "is_geometry": True},
            {"table_name": "mp_parcel", "column_name": "land_use_type", "semantic_domain": "LAND_USE", "aliases": ["地类", "用地类型"], "unit": None, "is_geometry": False},
        ]

    def _semantic_models_yaml(self) -> str:
        return """semantic_models:
  - name: mp_project_lifecycle
    description: 合成重大项目全生命周期语义模型
    source_table: mp_project_list
    srid: 4326
    geometry_type: Polygon
    entities:
      - name: project_id
        type: primary
        column: project_id
      - name: zdxmbh
        type: natural
        column: zdxmbh
    dimensions:
      - name: project_type
        type: categorical
        column: project_type
      - name: region
        type: categorical
        column: city
      - name: geom
        type: spatial
        column: geom
        srid: 4326
    measures:
      - name: project_count
        agg: count
        column: project_id
      - name: planned_land_area
        agg: sum
        column: planned_land_area_mu
      - name: total_investment
        agg: sum
        column: total_investment_million
    metrics:
      - name: major_project_count
        type: simple
        measure: project_count
      - name: total_planned_land_area
        type: simple
        measure: planned_land_area
"""

    def _semantic_relation_map(self) -> list[dict[str, Any]]:
        return [
            {"semantic_relation": "project_has_pre_review", "kg_edge_type": "HAS_PRE_REVIEW", "source_table": "mp_project_list", "target_table": "mp_pre_review", "source_key": "project_id", "target_key": "project_id", "confidence_threshold": 0.75, "expose_to_prompt": True},
            {"semantic_relation": "project_has_conversion", "kg_edge_type": "HAS_CONVERSION", "source_table": "mp_project_list", "target_table": "mp_conversion_expropriation", "source_key": "project_id", "target_key": "project_id", "confidence_threshold": 0.75, "expose_to_prompt": True},
            {"semantic_relation": "project_occupies_parcel", "kg_edge_type": "OCCUPIES_PARCEL", "source_table": "mp_project_list", "target_table": "mp_parcel", "source_key": "project_id", "target_key": "project_id", "confidence_threshold": 0.70, "expose_to_prompt": True},
        ]

    def _neo4j_cypher(self) -> str:
        return """// Synthetic major-project Neo4j import. Contains no production records.
LOAD CSV WITH HEADERS FROM 'file:///neo4j_nodes_small.csv' AS row
MERGE (n:KGNode {node_id: row.node_id})
SET n.label = row.label, n.biz_id = row.biz_id, n.name = row.name, n.properties_json = row.properties;

LOAD CSV WITH HEADERS FROM 'file:///neo4j_edges_small.csv' AS row
MATCH (s:KGNode {node_id: row.source_node_id})
MATCH (t:KGNode {node_id: row.target_node_id})
MERGE (s)-[r:RELATED {edge_id: row.edge_id}]->(t)
SET r.edge_type = row.edge_type,
    r.confidence = toFloat(row.confidence),
    r.match_method = row.match_method,
    r.evidence_json = row.evidence;
"""

    def _benchmark_questions_jsonl(self) -> str:
        rows = [
            {"qid": "MP_SYN_001", "question": "统计每个项目类型的重大项目数量。", "query_class": "sql_only", "required_tables": ["mp_project_list"]},
            {"qid": "MP_SYN_002", "question": "查询已完成用地预审但缺少农转征记录的项目数量。", "query_class": "hybrid", "required_edges": ["HAS_PRE_REVIEW", "HAS_CONVERSION"]},
            {"qid": "MP_SYN_003", "question": "统计通过空间叠加补全关联的项目数量。", "query_class": "hybrid", "required_tables": ["mp_relation_confidence"]},
            {"qid": "MP_SYN_004", "question": "列出存在审批流程断点的项目。", "query_class": "graph", "required_edges": ["MISSING_STAGE"]},
        ]
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
```

Add CLI entry point:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic major-project DBMS and KG data.")
    parser.add_argument("--profile", default="small_dev", choices=["small_dev", "medium_eval", "stress_optional"])
    parser.add_argument("--project-count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260604)
    parser.add_argument("--output-dir", type=Path, default=Path("data_agent/synthetic/major_projects"))
    args = parser.parse_args()

    cfg = GenerationConfig(
        profile=args.profile,
        project_count=args.project_count,
        seed=args.seed,
        output_dir=args.output_dir,
    )
    generator = SyntheticMajorProjectGenerator(cfg)
    written = generator.write_all(generator.build())
    print(json.dumps({"status": "success", "written": [str(p) for p in written]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create synthetic README**

Create `data_agent/synthetic/major_projects/README.md`:

```markdown
# Synthetic Major Project Data

This directory contains generated synthetic data for major-project lifecycle NL2Semantic2SQL development.

The data preserves realistic business structure but contains no production records. Project names, organization names, identifiers, geometries, dates, approval numbers, certificates, and graph relations are generated.

Use `scripts/synthetic_major_projects/generate_major_project_data.py` to regenerate the files.
```

- [ ] **Step 5: Run artifact writer test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_synthetic_generator.py -q
```

Expected: all generator tests pass.

- [ ] **Step 6: Generate small_dev artifacts**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\synthetic_major_projects\generate_major_project_data.py --profile small_dev --project-count 200 --seed 20260604 --output-dir data_agent\synthetic\major_projects
```

Expected: JSON output with `"status": "success"` and the planned artifact paths.

- [ ] **Step 7: Commit Task 2**

```powershell
git add scripts\synthetic_major_projects data_agent\synthetic\major_projects data_agent\test_major_project_synthetic_generator.py
git commit -m "feat: generate major project synthetic artifacts"
```

---

### Task 3: Major Project KG Resolver

**Files:**
- Create: `data_agent/major_project_kg_resolver.py`
- Test: `data_agent/test_major_project_kg_resolver.py`

- [ ] **Step 1: Write failing resolver tests**

Create `data_agent/test_major_project_kg_resolver.py`:

```python
from data_agent.major_project_kg_resolver import resolve_major_project_kg_hints


def test_resolver_detects_missing_stage_query():
    result = resolve_major_project_kg_hints("列出存在审批流程断点的重大项目")

    assert result["matched_entities"] == ["重大项目"]
    assert result["missing_stage_filter"] is True
    assert "MISSING_STAGE" in result["required_edges"]
    assert "mp_project_list" in result["candidate_tables"]


def test_resolver_detects_spatial_overlay_query():
    result = resolve_major_project_kg_hints("统计通过空间叠加补全关联的项目数量")

    assert result["spatial_overlap_threshold"] == 0.3
    assert "OCCUPIES_PARCEL" in result["required_edges"]
    assert "mp_relation_confidence" in result["candidate_tables"]


def test_resolver_detects_pre_review_without_conversion():
    result = resolve_major_project_kg_hints("查询已完成用地预审但未完成农转征的项目")

    assert result["lifecycle_stage"] == "pre_review_without_conversion"
    assert "HAS_PRE_REVIEW" in result["required_edges"]
    assert "HAS_CONVERSION" in result["required_edges"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_kg_resolver.py -q
```

Expected: fails because module does not exist.

- [ ] **Step 3: Implement resolver**

Create `data_agent/major_project_kg_resolver.py`:

```python
"""Major-project knowledge-graph hint resolver for NL2Semantic2SQL."""
from __future__ import annotations

from typing import Any


def resolve_major_project_kg_hints(question: str, semantic: dict | None = None, intent: str | None = None) -> dict[str, Any]:
    text = question or ""
    hints: dict[str, Any] = {
        "matched_entities": [],
        "lifecycle_stage": None,
        "required_edges": [],
        "missing_stage_filter": False,
        "spatial_overlap_threshold": None,
        "candidate_tables": [],
        "join_paths": [],
        "graph_backend": "postgres_projection",
    }

    if any(token in text for token in ["重大项目", "重点项目", "项目"]):
        hints["matched_entities"].append("重大项目")
        hints["candidate_tables"].append("mp_project_list")

    if any(token in text for token in ["断点", "缺失", "缺少", "未完成"]):
        hints["missing_stage_filter"] = True
        hints["required_edges"].append("MISSING_STAGE")

    if any(token in text for token in ["用地预审", "预审"]):
        hints["required_edges"].append("HAS_PRE_REVIEW")
        hints["candidate_tables"].append("mp_pre_review")

    if any(token in text for token in ["农转征", "农用地转用", "土地征收"]):
        hints["required_edges"].append("HAS_CONVERSION")
        hints["candidate_tables"].append("mp_conversion_expropriation")

    if "用地预审" in text and any(token in text for token in ["未完成农转征", "缺少农转征", "未完成土地征收"]):
        hints["lifecycle_stage"] = "pre_review_without_conversion"

    if any(token in text for token in ["空间叠加", "叠加补全", "重叠"]):
        hints["spatial_overlap_threshold"] = 0.3
        hints["required_edges"].append("OCCUPIES_PARCEL")
        hints["candidate_tables"].extend(["mp_relation_confidence", "mp_parcel"])

    if any(token in text for token in ["供地", "土地供应"]):
        hints["required_edges"].append("HAS_LAND_SUPPLY")
        hints["candidate_tables"].append("mp_land_supply")

    hints["required_edges"] = _dedupe(hints["required_edges"])
    hints["candidate_tables"] = _dedupe(hints["candidate_tables"])
    hints["join_paths"] = _join_paths_for(hints["candidate_tables"])
    return hints


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _join_paths_for(candidate_tables: list[str]) -> list[str]:
    paths = []
    if "mp_project_list" in candidate_tables and "mp_pre_review" in candidate_tables:
        paths.append("mp_project_list.project_id -> mp_pre_review.project_id")
    if "mp_project_list" in candidate_tables and "mp_conversion_expropriation" in candidate_tables:
        paths.append("mp_project_list.project_id -> mp_conversion_expropriation.project_id")
    if "mp_project_list" in candidate_tables and "mp_land_supply" in candidate_tables:
        paths.append("mp_project_list.project_id -> mp_land_supply.project_id")
    if "mp_project_list" in candidate_tables and "mp_parcel" in candidate_tables:
        paths.append("mp_project_list.project_id -> mp_parcel.project_id")
    return paths
```

- [ ] **Step 4: Run resolver tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_kg_resolver.py -q
```

Expected: all resolver tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add data_agent\major_project_kg_resolver.py data_agent\test_major_project_kg_resolver.py
git commit -m "feat: add major project kg resolver"
```

---

### Task 4: NL2SQL Grounding Integration

**Files:**
- Modify: `data_agent/nl2sql_grounding.py`
- Create: `data_agent/test_nl2sql_major_project_kg_hints.py`

- [ ] **Step 1: Write failing grounding test**

Create `data_agent/test_nl2sql_major_project_kg_hints.py`:

```python
from unittest.mock import patch


def test_build_context_includes_major_project_kg_hints(monkeypatch):
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [{
            "table_name": "mp_project_list",
            "display_name": "重大项目清单",
            "description": "合成重大项目主表",
            "confidence": 0.9,
        }],
        "matched_columns": {},
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }
    schema = {
        "status": "success",
        "table_name": "mp_project_list",
        "display_name": "重大项目清单",
        "columns": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["项目ID"], "semantic_domain": "PROJECT_ID"},
            {"column_name": "geom", "data_type": "USER-DEFINED", "aliases": ["项目范围"], "is_geometry": True},
        ],
    }

    monkeypatch.setattr(
        "data_agent.nl2sql_grounding.list_semantic_sources",
        lambda: {"status": "error", "sources": []},
        raising=False,
    )

    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=200):
        result = build_nl2sql_context("列出存在审批流程断点的重大项目")

    assert result["kg_hints"]["missing_stage_filter"] is True
    assert "MISSING_STAGE" in result["kg_hints"]["required_edges"]
    assert "KG hints" in result["grounding_prompt"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_nl2sql_major_project_kg_hints.py -q
```

Expected: fails because `kg_hints` is not included in `build_nl2sql_context`.

- [ ] **Step 3: Add resolver import helper**

Modify `data_agent/nl2sql_grounding.py` near other imports or inside `build_nl2sql_context()` with a safe helper:

```python
def _resolve_major_project_kg_hints(user_text: str, semantic: dict, intent: str | None) -> dict:
    try:
        from data_agent.major_project_kg_resolver import resolve_major_project_kg_hints
        return resolve_major_project_kg_hints(user_text, semantic=semantic, intent=intent)
    except Exception as exc:
        logger.warning("[NL2SQL grounding] major project KG resolver failed: %s", exc)
        return {}
```

- [ ] **Step 4: Merge kg_hints into payload**

Inside `build_nl2sql_context()`, after `warehouse_join_hints` is built and before the `payload` dictionary is created, add:

```python
    kg_hints = _resolve_major_project_kg_hints(
        user_text,
        semantic=semantic,
        intent=getattr(intent_result.primary, "value", intent_result.primary),
    )
```

Inside the `payload` dictionary add:

```python
        "kg_hints": kg_hints,
```

- [ ] **Step 5: Render compact KG hints in prompt**

Modify `_format_grounding_prompt_compact()` and `_format_grounding_prompt_legacy()` to append compact KG hint lines when `payload.get("kg_hints")` is not empty:

```python
    kg_hints = payload.get("kg_hints") or {}
    if kg_hints.get("matched_entities") or kg_hints.get("required_edges"):
        lines.append("")
        lines.append("KG hints:")
        if kg_hints.get("matched_entities"):
            lines.append(f"- matched entities: {', '.join(kg_hints['matched_entities'])}")
        if kg_hints.get("required_edges"):
            lines.append(f"- required graph edges: {', '.join(kg_hints['required_edges'])}")
        if kg_hints.get("missing_stage_filter"):
            lines.append("- lifecycle filter: projects with missing lifecycle stages")
        if kg_hints.get("join_paths"):
            lines.append("- graph-derived join paths:")
            for path in kg_hints["join_paths"][:5]:
                lines.append(f"  - {path}")
```

Use the exact local `lines` variable in each formatter.

- [ ] **Step 6: Run grounding integration test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_nl2sql_major_project_kg_hints.py -q
```

Expected: test passes.

- [ ] **Step 7: Run nearby grounding tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_nl2sql_grounding.py data_agent/test_nl2sql_grounding_family.py data_agent/test_nl2sql_major_project_kg_hints.py -q
```

Expected: tests pass.

- [ ] **Step 8: Commit Task 4**

```powershell
git add data_agent\nl2sql_grounding.py data_agent\test_nl2sql_major_project_kg_hints.py
git commit -m "feat: inject major project kg hints into nl2sql grounding"
```

---

### Task 5: Benchmark and Artifact Verification

**Files:**
- Modify: `scripts/synthetic_major_projects/generate_major_project_data.py`
- Create: `data_agent/test_major_project_artifact_contract.py`

- [ ] **Step 1: Write failing contract test**

Create `data_agent/test_major_project_artifact_contract.py`:

```python
import json

import yaml

from scripts.synthetic_major_projects.generate_major_project_data import (
    GenerationConfig,
    SyntheticMajorProjectGenerator,
)


def test_generated_semantic_artifacts_are_parseable(tmp_path):
    cfg = GenerationConfig(profile="small_dev", project_count=20, seed=99, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(cfg)
    generator.write_all(generator.build())

    sources = json.loads((tmp_path / "semantic_sources.json").read_text(encoding="utf-8"))
    registry = json.loads((tmp_path / "semantic_registry.json").read_text(encoding="utf-8"))
    relation_map = json.loads((tmp_path / "semantic_relation_map.json").read_text(encoding="utf-8"))
    models = yaml.safe_load((tmp_path / "semantic_models.yaml").read_text(encoding="utf-8"))

    assert sources
    assert registry
    assert relation_map
    assert models["semantic_models"][0]["name"] == "mp_project_lifecycle"


def test_benchmark_questions_cover_sql_graph_and_hybrid(tmp_path):
    cfg = GenerationConfig(profile="small_dev", project_count=20, seed=99, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(cfg)
    generator.write_all(generator.build())

    rows = [
        json.loads(line)
        for line in (tmp_path / "nl2sql_benchmark_questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    classes = {row["query_class"] for row in rows}
    assert {"sql_only", "graph", "hybrid"}.issubset(classes)
```

- [ ] **Step 2: Run contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_artifact_contract.py -q
```

Expected: tests pass if Task 2 semantic and benchmark writers are correct.

- [ ] **Step 3: Expand benchmark questions to at least 30**

Modify `_benchmark_questions_jsonl()` to return at least 30 JSONL rows covering:

- SQL-only project count by project type.
- SQL-only planned land area by city.
- SQL-only supplied project count.
- Graph missing stage.
- Graph lifecycle path.
- Hybrid pre-review without conversion.
- Hybrid supply without verification.
- Hybrid spatial overlay.
- Fuzzy match.
- Farmland occupation.

Use deterministic hard-coded question definitions, not LLM generation.

- [ ] **Step 4: Update contract test for minimum count**

Add to `test_benchmark_questions_cover_sql_graph_and_hybrid`:

```python
    assert len(rows) >= 30
```

- [ ] **Step 5: Run contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_artifact_contract.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add scripts\synthetic_major_projects\generate_major_project_data.py data_agent\test_major_project_artifact_contract.py
git commit -m "test: verify major project synthetic artifact contracts"
```

---

### Task 6: Optional PostGIS and Neo4j Load Documentation

**Files:**
- Modify: `data_agent/synthetic/major_projects/README.md`

- [ ] **Step 1: Add PostGIS load instructions**

Append:

```markdown
## Optional PostGIS Load

Requires PostgreSQL with PostGIS enabled.

```powershell
psql "$env:DATABASE_URL" -f schema_postgis.sql
psql "$env:DATABASE_URL" -f seed_small.sql
```

The SQL files are synthetic and can be loaded into a test database. Do not load them into a production schema without a dedicated demo namespace.
```
```

- [ ] **Step 2: Add Neo4j load instructions**

Append:

```markdown
## Optional Neo4j Load

Copy these files into the Neo4j import directory:

- `neo4j_nodes_small.csv`
- `neo4j_edges_small.csv`
- `neo4j_import.cypher`

Then run:

```cypher
:source neo4j_import.cypher
```

The initial NL2Semantic2SQL integration does not require Neo4j. Neo4j is used to validate the external graph-database route.
```
```

- [ ] **Step 3: Run README sanity check**

Run:

```powershell
Select-String -Path data_agent\synthetic\major_projects\README.md -Pattern "Optional PostGIS Load","Optional Neo4j Load"
```

Expected: both headings are found.

- [ ] **Step 4: Commit Task 6**

```powershell
git add data_agent\synthetic\major_projects\README.md
git commit -m "docs: document major project synthetic data loading"
```

---

### Task 7: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_major_project_synthetic_generator.py data_agent/test_major_project_kg_resolver.py data_agent/test_major_project_artifact_contract.py data_agent/test_nl2sql_major_project_kg_hints.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run nearby NL2SQL tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/test_nl2sql_grounding.py data_agent/test_nl2sql_grounding_family.py data_agent/test_semantic_model_metricflow.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Regenerate small_dev artifacts**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\synthetic_major_projects\generate_major_project_data.py --profile small_dev --project-count 200 --seed 20260604 --output-dir data_agent\synthetic\major_projects
```

Expected: JSON success output listing all generated artifacts.

- [ ] **Step 4: Verify no generated artifact claims to contain production records**

Run:

```powershell
Select-String -Path data_agent\synthetic\major_projects\README.md,data_agent\synthetic\major_projects\schema_postgis.sql,data_agent\synthetic\major_projects\seed_small.sql -Pattern "Synthetic","synthetic","production records"
```

Expected: matches are found in README and SQL headers.

- [ ] **Step 5: Check git status**

Run:

```powershell
git status --short
```

Expected: only intentional generated files and source changes are present.

- [ ] **Step 6: Commit final generated artifacts if not already committed**

If `git status --short` shows generated files not yet committed, run:

```powershell
git add data_agent\synthetic\major_projects scripts\synthetic_major_projects data_agent\major_project_kg_resolver.py data_agent\nl2sql_grounding.py data_agent\test_major_project_*.py data_agent\test_nl2sql_major_project_kg_hints.py
git commit -m "feat: integrate synthetic major project kg data with nl2sql"
```

Expected: commit succeeds or there is nothing left to commit.
