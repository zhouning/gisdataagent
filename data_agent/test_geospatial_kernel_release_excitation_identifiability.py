from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/geotransport_v0_1"


def _development_windows():
    pool = json.loads(
        (
            DATA_ROOT
            / "stage30_center_hill_regime_validation_events/raw/"
            "cwms_release_candidate_pool.json"
        ).read_bytes()
    )["values"]
    series = [
        (
            datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc),
            float(row[1]),
        )
        for row in pool
    ]
    by_time = {time: index for index, (time, _) in enumerate(series)}
    result = []
    for stage in (
        "stage29_center_hill_blind_transfer_events",
        "stage30_center_hill_regime_validation_events",
    ):
        manifest = json.loads(
            (DATA_ROOT / stage / "event_selection_manifest.json").read_bytes()
        )
        for event in manifest["selected_events"]:
            step = datetime.fromisoformat(
                event["step_time_utc"].replace("Z", "+00:00")
            )
            index = by_time[step]
            values = tuple(
                value
                for _, value in series[index - 24 : index + 49]
            )
            result.append(
                (
                    stage,
                    event["event_id"],
                    excitation.compile_release_excitation_identifiability(
                        values
                    ),
                )
            )
    return result


def test_release_excitation_rejects_one_hour_rebound():
    values = tuple([200.0] * 23 + [0.0, 200.0] + [200.0] * 48)

    report = excitation.compile_release_excitation_identifiability(values)

    assert report.excitation_mode == "recovery"
    assert report.excursion_support_hours == 1
    assert report.normalized_excitation_volume_step_hours == 1.0
    assert report.blind_response_test_admissible is False
    assert "excursion_support_below_three_hours" in report.rejection_reasons


def test_release_excitation_admits_sustained_onset_for_blind_testing():
    values = tuple([20.0] * 24 + [120.0] * 12 + [20.0] * 37)

    report = excitation.compile_release_excitation_identifiability(values)

    assert report.excitation_mode == "onset"
    assert report.excursion_support_hours == 12
    assert report.normalized_excitation_volume_step_hours == 12.0
    assert report.blind_response_test_admissible is True
    assert report.rejection_reasons == ()
    report.require_blind_response_test_support()


def test_release_excitation_separates_stage30_counterexample():
    windows = _development_windows()
    by_event = {event_id: report for _, event_id, report in windows}

    rejected = by_event["release_step_20210925T1900Z"]
    assert rejected.excitation_mode == "recovery"
    assert rejected.excursion_support_hours == 1
    assert rejected.normalized_excitation_volume_step_hours == pytest.approx(
        1.0233966418903535
    )
    assert rejected.blind_response_test_admissible is False
    assert all(
        report.blind_response_test_admissible
        for event_id, report in by_event.items()
        if event_id != "release_step_20210925T1900Z"
    )


def test_release_excitation_keeps_response_and_exact_lag_unclaimed():
    report = next(
        report
        for _, event_id, report in _development_windows()
        if event_id == "release_step_20250910T1400Z"
    )

    calls = (
        (
            report.require_observed_downstream_response,
            "release_excitation_input_support_is_not_observed_response",
        ),
        (
            report.require_exact_lag_identification,
            "release_excitation_input_support_does_not_identify_exact_lag",
        ),
        (
            report.require_physical_travel_time,
            "release_excitation_input_support_is_not_physical_travel_time",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()

    payload = report.as_dict()
    assert payload["input_support_only"] is True
    assert payload["observed_downstream_response_admitted"] is False
    assert payload["exact_lag_identified"] is False
    assert payload["physical_travel_time_admitted"] is False


def test_release_excitation_requires_exact_finite_support():
    with pytest.raises(ValueError, match="73_finite_values_required"):
        excitation.compile_release_excitation_identifiability((1.0,) * 72)
    with pytest.raises(ValueError, match="nonzero_primary_step_required"):
        excitation.compile_release_excitation_identifiability((1.0,) * 73)
