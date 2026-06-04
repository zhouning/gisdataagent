import json

import yaml

from scripts.synthetic_major_projects.generate_major_project_data import (
    GenerationConfig,
    SyntheticMajorProjectGenerator,
)


REQUIRED_BENCHMARK_CATEGORIES = {
    "sql_project_count_by_type",
    "sql_planned_land_area_by_city",
    "sql_supplied_project_count",
    "graph_missing_stage",
    "graph_lifecycle_path",
    "hybrid_pre_review_without_conversion",
    "hybrid_supply_without_verification",
    "hybrid_spatial_overlay",
    "fuzzy_match",
    "farmland_occupation",
}


def _write_artifacts(tmp_path):
    config = GenerationConfig(profile="small_dev", project_count=30, seed=20260604, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(config)
    bundle = generator.build()
    generator.write_all(bundle)
    return tmp_path


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_major_project_semantic_artifacts_are_parseable(tmp_path):
    artifact_dir = _write_artifacts(tmp_path)

    semantic_sources = json.loads((artifact_dir / "semantic_sources.json").read_text(encoding="utf-8"))
    semantic_registry = json.loads((artifact_dir / "semantic_registry.json").read_text(encoding="utf-8"))
    semantic_relation_map = json.loads((artifact_dir / "semantic_relation_map.json").read_text(encoding="utf-8"))
    semantic_models = yaml.safe_load((artifact_dir / "semantic_models.yaml").read_text(encoding="utf-8"))
    benchmark_questions = _jsonl(artifact_dir / "nl2sql_benchmark_questions.jsonl")

    assert "mp_project_list" in semantic_sources["sources"]
    assert "project_id" in semantic_registry["columns"]
    assert "OCCUPIES_PARCEL" in semantic_relation_map["kg_edge_types"]
    assert semantic_models["semantic_models"][0]["name"] == "mp_project_lifecycle"
    assert benchmark_questions


def test_major_project_benchmark_contract_and_coverage(tmp_path):
    artifact_dir = _write_artifacts(tmp_path)

    questions = _jsonl(artifact_dir / "nl2sql_benchmark_questions.jsonl")

    assert len(questions) >= 30
    assert {"sql_only", "graph", "hybrid"} <= {row["query_class"] for row in questions}
    assert REQUIRED_BENCHMARK_CATEGORIES <= {row["coverage_category"] for row in questions}

    for row in questions:
        assert row["class"] == row["query_class"]
        assert row["id"]
        assert row["question"]
        assert row["expected_route"]
        assert row["expected_sql_tables"]
        assert "notes" in row
        assert "\ufffd" not in row["question"]

