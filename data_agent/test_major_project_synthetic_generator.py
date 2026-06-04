import csv
import json

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


def test_generator_repeated_build_is_deterministic_on_same_instance():
    cfg = GenerationConfig(profile="small_dev", project_count=5, seed=42)
    generator = SyntheticMajorProjectGenerator(cfg)

    first = generator.build()
    second = generator.build()

    assert first == second


def test_small_profile_contains_expected_lifecycle_anomalies():
    cfg = GenerationConfig(profile="small_dev", project_count=30, seed=7)
    data = SyntheticMajorProjectGenerator(cfg).build()

    anomaly_types = {edge["edge_type"] for edge in data.kg_edges}
    assert "MISSING_STAGE" in anomaly_types
    assert "HAS_RISK" in anomaly_types
    assert any(row["match_method"] == "spatial_overlay" for row in data.relation_confidence)
    assert any(row["match_method"] == "fuzzy_name" for row in data.relation_confidence)


def test_relation_confidence_uses_parcel_table_and_synthetic_provenance():
    cfg = GenerationConfig(profile="small_dev", project_count=10, seed=7)
    data = SyntheticMajorProjectGenerator(cfg).build()

    assert data.relation_confidence
    assert {row["target_table"] for row in data.relation_confidence} == {"mp_parcel"}
    for row in data.relation_confidence:
        assert row["synthetic_seed"] == cfg.seed
        assert row["profile"] == cfg.profile
        assert row["generator_version"]
        assert isinstance(json.loads(row["evidence"]), dict)


def test_anomaly_and_risk_node_properties_include_synthetic_provenance():
    cfg = GenerationConfig(profile="small_dev", project_count=30, seed=7)
    data = SyntheticMajorProjectGenerator(cfg).build()

    audit_nodes = [
        node for node in data.kg_nodes if node["label"] in {"LifecycleAnomaly", "RiskEvent"}
    ]
    assert audit_nodes
    for node in audit_nodes:
        properties = json.loads(node["properties"])
        assert properties["synthetic_seed"] == cfg.seed
        assert properties["profile"] == cfg.profile
        assert properties["generator_version"]


def test_kg_edges_reference_existing_nodes_and_have_parseable_evidence():
    cfg = GenerationConfig(profile="small_dev", project_count=30, seed=7)
    data = SyntheticMajorProjectGenerator(cfg).build()
    node_ids = {node["node_id"] for node in data.kg_nodes}

    assert data.kg_edges
    for edge in data.kg_edges:
        assert edge["source_node_id"] in node_ids
        assert edge["target_node_id"] in node_ids
        assert isinstance(json.loads(edge["evidence"]), dict)


def test_generator_writes_expected_artifacts(tmp_path):
    cfg = GenerationConfig(profile="small_dev", project_count=12, seed=20260604, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(cfg)
    data = generator.build()

    written_paths = generator.write_all(data)

    expected_names = {
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
    assert {path.name for path in written_paths} == expected_names
    for name in expected_names:
        assert (tmp_path / name).exists()

    schema_sql = (tmp_path / "schema_postgis.sql").read_text(encoding="utf-8")
    assert "Synthetic major-project PostGIS schema" in schema_sql
    assert "no production records" in schema_sql.lower()
    for table_name in [
        "mp_project_list",
        "mp_land_plan",
        "mp_pre_review",
        "mp_conversion_expropriation",
        "mp_land_supply",
        "mp_parcel",
        "mp_relation_confidence",
        "kg_nodes",
        "kg_edges",
        "kg_query_result",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema_sql
    assert "mp_project_parcel" not in schema_sql

    seed_sql = (tmp_path / "seed_small.sql").read_text(encoding="utf-8")
    assert seed_sql.startswith("-- Synthetic major-project seed data")
    assert "ST_GeomFromText" in seed_sql
    assert "INSERT INTO mp_parcel" in seed_sql
    assert "mp_project_parcel" not in seed_sql

    with (tmp_path / "kg_nodes_small.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["node_id", "label", "biz_id", "name", "properties"]
    assert len(rows) > 1

    cypher = (tmp_path / "neo4j_import.cypher").read_text(encoding="utf-8")
    assert "synthetic" in cypher.lower()
    assert "no production records" in cypher.lower()
    assert "neo4j_nodes_small.csv" in cypher
    assert "neo4j_edges_small.csv" in cypher

    semantic_sources = json.loads((tmp_path / "semantic_sources.json").read_text(encoding="utf-8"))
    assert "mp_project_list" in semantic_sources["sources"]
    assert "重大项目清单" in semantic_sources["sources"]["mp_project_list"]["display_name"]

    semantic_registry = json.loads((tmp_path / "semantic_registry.json").read_text(encoding="utf-8"))
    assert "project_id" in semantic_registry["columns"]
    assert "geom" in semantic_registry["columns"]

    semantic_models = (tmp_path / "semantic_models.yaml").read_text(encoding="utf-8")
    assert "mp_project_lifecycle:" in semantic_models

    relation_map = json.loads((tmp_path / "semantic_relation_map.json").read_text(encoding="utf-8"))
    for edge_type in ["HAS_PRE_REVIEW", "HAS_CONVERSION", "OCCUPIES_PARCEL"]:
        assert edge_type in relation_map["kg_edge_types"]
    assert relation_map["kg_edge_types"]["OCCUPIES_PARCEL"]["sql_table"] == "mp_relation_confidence"

    questions = [
        json.loads(line)
        for line in (tmp_path / "nl2sql_benchmark_questions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(questions) >= 4
    assert {"sql_only", "graph", "hybrid"} <= {question["class"] for question in questions}
