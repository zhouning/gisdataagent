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
