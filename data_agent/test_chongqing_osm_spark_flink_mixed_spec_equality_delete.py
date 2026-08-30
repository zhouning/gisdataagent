from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_mixed_spec_equality_delete import (
    SPARK_SOURCE,
    build_mixed_spec_equality_delete_plan,
)
from scripts.spark_chongqing_osm_iceberg_mixed_spec_mor_delete import _evolve


def test_mixed_spec_equality_delete_plan_is_deterministic_and_cross_spec_targeted() -> None:
    first = build_mixed_spec_equality_delete_plan(DEFAULT_SOURCE)
    second = build_mixed_spec_equality_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    target = first["target_road_id"]
    assert sum(row["road_id"] == target for row in first["baseline_rows"]) == 1
    assert sum(row["road_id"] == target for row in first["after_flink_rows"]) == 2
    assert all(row["road_id"] != target for row in first["after_mixed_delete_rows"])
    assert first["flink_append_commit_token"] != first["flink_commit_token"]


def test_mixed_spec_equality_delete_runner_checks_identifier_and_mor_files() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert _evolve.__module__ == "scripts.spark_chongqing_osm_iceberg_mixed_spec_mor_delete"
    assert "setIdentifierFields" in source
    assert "equality_delete_files_materialized" in source
    assert "equality_delete_targets_identifier_key" in source
    assert "cross_spec_equality_delete_applied" in source
    assert "both_specs_still_have_data_files_under_mor" in source


def test_mixed_spec_equality_delete_runner_has_controlled_rewrite_path() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "DELETE FROM {args.table}" in source
    assert "materialized.writeTo(args.table).append()" in source
    assert "controlled_rewrite_time_travel_exact" in source
    assert "final_data_files_are_single_current_spec" in source


def test_mixed_spec_equality_delete_certifier_keeps_provider_boundary_explicit() -> None:
    certifier = Path(
        "/Users/zhouning/gisdataagent/scripts/"
        "certify_chongqing_osm_spark_flink_mixed_spec_equality_delete.py"
    ).read_text(encoding="utf-8")

    assert '"partition_evolution": "identity(road_id)"' in certifier
    assert '"delete_mode": "merge-on-read"' in certifier
    assert '"equality-delete-evolved-spec-only"' in certifier
    assert '"equality-delete-after-controlled-rewrite"' in certifier
    assert '"unsupported"' in certifier
    assert "--controlled-rewrite" in certifier
    assert "supported_after_controlled_rewrite" in certifier
    assert "multiple equality-delete files" in certifier
    assert "production HA" in certifier
