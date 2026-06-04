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
