from __future__ import annotations

import pandas as pd

from scripts.extract_abu_dhabi_gwm_confirmatory_sentinel2_batch import (
    build_forcing,
    select_optical_cohort,
)


def test_select_optical_cohort_advances_backups_in_frozen_order() -> None:
    events = [
        {"event_id": f"event-{index}", "cohort_order": index, "cohort_role": "primary"}
        for index in range(1, 4)
    ]
    events.append({"event_id": "event-4", "cohort_order": 4, "cohort_role": "backup"})
    pairs = pd.DataFrame(
        {
            "event_id": ["event-1", "event-2", "event-3", "event-4"],
            "cohort_order": [1, 2, 3, 4],
            "sentinel2_pair_admitted": [True, False, True, True],
            "selected_before_date": ["2020-01-01"] * 4,
            "selected_after_date": ["2020-01-02"] * 4,
            "selected_before_datetime_utc": ["2020-01-01T07:00:00Z"] * 4,
            "selected_after_datetime_utc": ["2020-01-02T07:00:00Z"] * 4,
        }
    )

    selected = select_optical_cohort(events, pairs, 3)

    assert [event["event_id"] for event in selected] == ["event-1", "event-3", "event-4"]


def test_build_forcing_averages_support_points(tmp_path) -> None:
    hourly = pd.DataFrame(
        {
            "event_id": ["event-1"] * 4,
            "point_id": ["a", "b", "a", "b"],
            "timestamp_utc": [
                "2020-01-01T00:00:00Z",
                "2020-01-01T00:00:00Z",
                "2020-01-01T01:00:00Z",
                "2020-01-01T01:00:00Z",
            ],
            "precipitation_mm": [1.0, 3.0, 2.0, 4.0],
            "inside_noaa_event_window": [True] * 4,
        }
    )
    event = {
        "event_id": "event-1",
        "start_utc": "2020-01-01T00:00:00Z",
        "end_utc": "2020-01-01T02:00:00Z",
    }

    forcing = build_forcing(
        hourly,
        event,
        source_path=tmp_path / "era5.parquet",
        source_sha256="abc",
    )

    assert forcing["hourly_precipitation_mm"] == [2.0, 3.0]
    assert forcing["support_point_count"] == 2
