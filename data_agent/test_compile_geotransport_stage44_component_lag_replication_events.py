from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts import (
    compile_geotransport_stage44_component_lag_replication_events as stage44,
)
from scripts import (
    compile_geotransport_stage44_target_exposure_inventory as exposure,
)
from scripts import (
    freeze_geotransport_stage44_component_lag_replication_protocol as freeze,
)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def test_stage44_source_selection_reproduces_frozen_counts_and_events():
    selection = stage44.compile_selection()

    assert len(selection.candidates) == 1_343
    assert dict(selection.candidate_counts_by_stratum) == freeze.EXPECTED_STRATUM_COUNTS
    assert dict(selection.component_gate_candidate_counts) == freeze.EXPECTED_COMPONENT_COUNTS
    assert tuple(value["event_id"] for value in selection.selected_events) == (
        freeze.EXPECTED_EVENT_IDS
    )


def test_stage44_events_do_not_overlap_any_expanded_target_exposure():
    selection = stage44.compile_selection()
    inventory = exposure.compile_inventory()
    radius = timedelta(days=freeze.EXCLUSION_RADIUS_DAYS)

    for event in selection.selected_events:
        event_begin = _parse(str(event["start_utc"]))
        event_end = _parse(str(event["end_utc"]))
        assert all(
            event_begin > _parse(end) + radius or event_end < _parse(begin) - radius
            for begin, end in inventory.excluded_windows_utc
        )


def test_stage44_events_preserve_four_strata_and_separation():
    events = stage44.compile_selection().selected_events

    assert tuple(value["selection_stratum"] for value in events) == (
        "high_increase",
        "high_decrease",
        "low_increase",
        "low_decrease",
    )
    assert all(value["active_step_components"] == ["turbine"] for value in events)
    assert all(
        abs(_parse(str(left["step_time_utc"])) - _parse(str(right["step_time_utc"])))
        >= timedelta(days=180)
        for index, left in enumerate(events)
        for right in events[index + 1 :]
    )
