from __future__ import annotations

from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multiple_successful_retries import (
    build_sql_merge_multiple_successful_retries_plan,
)


def test_multiple_successful_retry_plan_advances_revision_and_keeps_sequence() -> None:
    plan = build_sql_merge_multiple_successful_retries_plan(DEFAULT_SOURCE)
    sequence = plan["successful_retry_sequence"]
    assert plan["successful_retry_count"] == 2
    assert len(sequence) == 1
    assert sequence[0]["expected_revision"] == 3
    assert sequence[0]["new_revision"] == 4
    assert sequence[0]["source_row_id"] == "fresh-source-retry-2"
    assert any(row["revision"] == 4 for row in plan["final_merge_rows"])
