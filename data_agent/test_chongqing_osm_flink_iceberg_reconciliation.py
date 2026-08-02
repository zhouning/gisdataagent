"""Focused contracts for Flink/Iceberg uncertain-commit acceptance."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_reconciliation import (
    DEFAULT_SOURCE,
    build_reconciliation_plan,
)
from scripts.certify_chongqing_osm_flink_iceberg_recovery import render_recovery_input


def test_reconciliation_plan_binds_commit_token_to_real_source_slice() -> None:
    first = build_reconciliation_plan(DEFAULT_SOURCE)
    second = build_reconciliation_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["commit_tag"] == first["source_slice_sha256"]
    assert len(first["baseline_rows"]) == 3
    assert len(first["stream_rows"]) == 4
    assert len(first["final_rows"]) == 7
    assert all(row["stream_event_id"] is None for row in first["baseline_rows"])
    assert all(row["flink_commit_tag"] is None for row in first["baseline_rows"])


def test_reconciliation_input_is_exact_and_token_bound() -> None:
    plan = build_reconciliation_plan(DEFAULT_SOURCE)
    lines = render_recovery_input(plan).splitlines()

    assert len(lines) == 4
    assert {line.split("\t")[5] for line in lines} == {plan["commit_tag"]}
    assert [line.split("\t")[4] for line in lines] == plan["stream_event_ids"]
