from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_complex_predicate import (
    SPARK_SOURCE,
    build_sql_merge_complex_predicate_plan,
)


def test_complex_predicate_plan_is_deterministic_and_has_guard_row() -> None:
    first = build_sql_merge_complex_predicate_plan(DEFAULT_SOURCE)
    second = build_sql_merge_complex_predicate_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["matched_source_rows"]) == 2
    assert len({row["road_id"] for row in first["matched_source_rows"]}) == 2
    assert {row["expected_revision"] for row in first["matched_source_rows"]} == {1, 2}
    assert first["guard_source_row"]["action"] == "ignore"
    assert len(first["merge_source_rows"]) == 3


def test_complex_predicate_source_uses_and_or_in_match_predicate() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "source.action = 'promote'" in source
    assert "source.action = 'refresh' AND target.road_id IN (102262020)" in source
    assert "WHEN NOT MATCHED THEN INSERT" not in source
    assert "overwritePartitions" not in source


def test_complex_predicate_final_state_updates_valid_rows_and_keeps_guard() -> None:
    plan = build_sql_merge_complex_predicate_plan(DEFAULT_SOURCE)
    for source in plan["matched_source_rows"]:
        rows = [row for row in plan["final_merge_rows"] if row["road_id"] == source["road_id"]]
        updated = [row for row in rows if row["commit_token"] == source["commit_token"]]
        assert len(updated) == 1
        assert updated[0]["revision"] == source["result_revision"]
    guard = plan["guard_source_row"]
    assert any(
        row["road_id"] == guard["road_id"]
        and row["revision"] == guard["expected_revision"]
        and row["commit_token"] is None
        for row in plan["final_merge_rows"]
    )
    assert not any(row["commit_token"] == guard["commit_token"] for row in plan["final_merge_rows"])
    assert len(plan["final_merge_rows"]) == 4
