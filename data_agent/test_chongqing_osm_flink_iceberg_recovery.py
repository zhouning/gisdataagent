"""Focused contracts for Flink checkpoint recovery into Iceberg."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    RECOVERY_CHECKPOINT_RE,
    RECOVERY_FAILURE_RE,
    RECOVERY_FINISHED_RE,
    RECOVERY_RESTORE_RE,
)
from scripts.certify_chongqing_osm_flink_iceberg_recovery import (
    DEFAULT_SOURCE,
    build_recovery_plan,
    render_recovery_input,
)


def test_recovery_plan_is_real_deterministic_and_exact() -> None:
    first = build_recovery_plan(DEFAULT_SOURCE, commit_tag="run_123")
    second = build_recovery_plan(DEFAULT_SOURCE, commit_tag="run_123")

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["stream_rows"]) == 4
    assert len(first["final_rows"]) == 7
    assert len(set(first["stream_event_ids"])) == 4
    assert first["baseline_content_sha256"] != first["final_content_sha256"]


def test_recovery_input_is_bounded_and_lossless() -> None:
    plan = build_recovery_plan(DEFAULT_SOURCE, commit_tag="run_123")
    lines = render_recovery_input(plan).splitlines()

    assert len(lines) == 4
    assert all(len(line.split("\t")) == 6 for line in lines)
    assert [line.split("\t")[4] for line in lines] == plan["stream_event_ids"]


def test_recovery_runtime_markers_are_structured() -> None:
    output = "\n".join(
        (
            "GDA_ICEBERG_CHECKPOINT_COMPLETED id=3 offset=2",
            "GDA_ICEBERG_INTENTIONAL_FAILURE checkpoint=3 offset=2",
            "GDA_ICEBERG_SOURCE_OPEN attempt=1 restored=true offset=2",
            "GDA_ICEBERG_CHECKPOINT_COMPLETED id=5 offset=4",
            "GDA_ICEBERG_SOURCE_FINISHED offset=4",
        )
    )

    assert RECOVERY_CHECKPOINT_RE.findall(output) == [("3", "2"), ("5", "4")]
    assert RECOVERY_FAILURE_RE.search(output).groups() == ("3", "2")
    assert RECOVERY_RESTORE_RE.search(output).groups() == ("1", "2")
    assert RECOVERY_FINISHED_RE.search(output).group(1) == "4"
