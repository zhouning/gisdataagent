from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_dedup import (
    SPARK_SOURCE,
    build_sql_merge_auto_dedup_plan,
)


def test_auto_dedup_plan_is_deterministic_and_has_ranked_candidates() -> None:
    first = build_sql_merge_auto_dedup_plan(DEFAULT_SOURCE)
    second = build_sql_merge_auto_dedup_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["deduplication_policy"] == "highest_rank_then_source_row_id"
    assert [row["dedup_rank"] for row in first["merge_source_candidates"]] == [100, 10]
    assert first["deduplication_selected_source_row_id"] == "fresh-source-deduplicated"


def test_auto_retry_worker_records_and_applies_deduplication_selection() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    assert "spark_chongqing_osm_iceberg_sql_merge_auto_retry" in source
    implementation = (
        SPARK_SOURCE.parent / "spark_chongqing_osm_iceberg_sql_merge_auto_retry.py"
    ).read_text(encoding="utf-8")
    assert "merge_source_candidates" in implementation
    assert "automatic_deduplication_selected" in implementation


def test_unselected_candidate_cannot_change_final_product() -> None:
    plan = build_sql_merge_auto_dedup_plan(DEFAULT_SOURCE)
    selected = plan["merge_source_candidates"][0]
    unselected = plan["merge_source_candidates"][1]

    assert selected["new_revision"] == 3
    assert unselected["new_revision"] == 88
    assert any(row["revision"] == 3 for row in plan["final_merge_rows"])
