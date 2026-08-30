from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_cross_target_survivorship import (
    SPARK_SOURCE,
    build_cross_target_survivorship_plan,
)


def test_cross_target_survivorship_plan_is_deterministic() -> None:
    first = build_cross_target_survivorship_plan(DEFAULT_SOURCE)
    second = build_cross_target_survivorship_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["survivorship_policy"] == "highest_rank_then_source_row_id_per_target"
    assert len(first["survivorship_candidates"]) == 4
    assert len(first["merge_source_rows"]) == 2


def test_cross_target_worker_selects_one_candidate_per_target() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    implementation = (
        SPARK_SOURCE.parent / "spark_chongqing_osm_iceberg_sql_merge_multi_target.py"
    ).read_text(encoding="utf-8")

    assert "survivorship_candidates" in implementation
    assert "unselected_survivorship_tokens_absent" in implementation
    assert "spark_chongqing_osm_iceberg_sql_merge_multi_target" in source


def test_unselected_cross_target_candidates_do_not_change_final_rows() -> None:
    plan = build_cross_target_survivorship_plan(DEFAULT_SOURCE)
    selected_ids = {row["source_row_id"] for row in plan["merge_source_rows"]}
    unselected = [
        row for row in plan["survivorship_candidates"] if row["source_row_id"] not in selected_ids
    ]

    assert len(unselected) == 2
    final_tokens = {item["commit_token"] for item in plan["final_merge_rows"]}
    assert all(row["commit_token"] not in final_tokens for row in unselected)
