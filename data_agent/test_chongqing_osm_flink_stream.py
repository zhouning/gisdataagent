"""Focused contracts for the real Chongqing OSM Flink acceptance."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_SOURCE,
    build_event_slice,
    render_event_slice,
)


def test_real_osm_event_slice_is_deterministic_and_complete() -> None:
    first, metadata = build_event_slice(DEFAULT_SOURCE)
    second, repeated_metadata = build_event_slice(DEFAULT_SOURCE)

    assert first == second
    assert metadata == repeated_metadata
    assert metadata["source_feature_count"] == 50_366
    assert len(metadata["selected_road_ids"]) == 4
    assert len(set(metadata["selected_road_ids"])) == 4
    assert len(first) == 10
    assert render_event_slice(first) == render_event_slice(second)


def test_event_slice_contains_required_stream_semantics() -> None:
    events, _ = build_event_slice(DEFAULT_SOURCE)
    event_ids = [event["event_id"] for event in events]
    operations = [event["operation"] for event in events]
    event_times = [event["event_time_ms"] for event in events]

    assert len(set(event_ids)) == 9
    assert event_ids.count("cq-osm-e05") == 2
    assert {"insert", "update", "delete"}.issubset(operations)
    assert event_times[3] < event_times[2]
    assert event_times[7] < event_times[6]
    assert all(len(event["geometry_sha256"]) == 64 for event in events)
