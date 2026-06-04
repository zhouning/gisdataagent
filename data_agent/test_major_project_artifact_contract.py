import json
import re
from pathlib import Path

import yaml

from scripts.synthetic_major_projects.generate_major_project_data import (
    GenerationConfig,
    SyntheticMajorProjectGenerator,
)


COMMITTED_BENCHMARK_PATH = (
    Path(__file__).parent / "synthetic" / "major_projects" / "nl2sql_benchmark_questions.jsonl"
)

ALLOWED_QUERY_CLASSES = {"sql_only", "graph", "hybrid"}
ALLOWED_EXPECTED_ROUTES_BY_QUERY_CLASS = {
    "sql_only": {"sql"},
    "graph": {"graph"},
    "hybrid": {"semantic_graph_sql"},
}

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


def _write_artifacts(tmp_path, project_count=30):
    config = GenerationConfig(profile="small_dev", project_count=project_count, seed=20260604, output_dir=tmp_path)
    generator = SyntheticMajorProjectGenerator(config)
    bundle = generator.build()
    generator.write_all(bundle)
    return tmp_path


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _assert_benchmark_contract(questions, semantic_sources, semantic_relation_map):
    ids = [row["id"] for row in questions]
    query_classes = {row["query_class"] for row in questions}
    coverage_categories = {row["coverage_category"] for row in questions}
    semantic_source_names = set(semantic_sources["sources"])
    kg_edge_types = set(semantic_relation_map["kg_edge_types"])

    assert len(questions) >= 30
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"mp_bench_[a-z0-9_]+_\d{3}", row_id) for row_id in ids)
    assert query_classes <= ALLOWED_QUERY_CLASSES
    assert ALLOWED_QUERY_CLASSES <= query_classes
    assert REQUIRED_BENCHMARK_CATEGORIES <= coverage_categories

    for row in questions:
        assert row["class"] == row["query_class"]
        assert row["expected_route"] in ALLOWED_EXPECTED_ROUTES_BY_QUERY_CLASS[row["query_class"]]
        assert row["question"]
        assert row["expected_sql_tables"]
        assert set(row["expected_sql_tables"]) <= semantic_source_names
        assert set(row.get("expected_kg_edge_types", [])) <= kg_edge_types
        assert "notes" in row
        assert "\ufffd" not in row["question"]


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

    semantic_sources = json.loads((artifact_dir / "semantic_sources.json").read_text(encoding="utf-8"))
    semantic_relation_map = json.loads((artifact_dir / "semantic_relation_map.json").read_text(encoding="utf-8"))
    questions = _jsonl(artifact_dir / "nl2sql_benchmark_questions.jsonl")

    _assert_benchmark_contract(questions, semantic_sources, semantic_relation_map)


def test_committed_benchmark_artifact_matches_default_generator_output(tmp_path):
    artifact_dir = _write_artifacts(tmp_path, project_count=200)

    generated_questions = _jsonl(artifact_dir / "nl2sql_benchmark_questions.jsonl")
    committed_questions = _jsonl(COMMITTED_BENCHMARK_PATH)

    assert committed_questions == generated_questions
