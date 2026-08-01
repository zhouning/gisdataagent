import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import (
    acquire_geospatial_kernel_horizon_assimilation_holdout_outcomes as acquire,
)
from scripts import (
    freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as holdout,
)
from scripts import (
    freeze_geospatial_kernel_horizon_assimilation_holdout_scoring_protocol as freeze,
)
from scripts import score_geospatial_kernel_horizon_assimilation_holdout as score


def test_scoring_protocol_freezes_two_exact_urls_and_script_hashes() -> None:
    report = freeze.compile_scoring_protocol(
        frozen_at=datetime(2026, 8, 1, tzinfo=UTC)
    )

    requests = report["outcome_request_lock"]["requests"]
    assert [value["system_id"] for value in requests] == list(holdout.SYSTEM_IDS)
    assert report["outcome_request_lock"]["logical_request_count"] == 2
    assert report["outcome_request_lock"]["maximum_total_remote_attempts"] == 2
    assert requests[0]["url"] == (
        "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=03424860&"
        "parameterCd=00060&startDT=2022-04-28T01%3A00%3A00Z&"
        "endDT=2022-05-26T01%3A00%3A00Z&siteStatus=all"
    )
    assert requests[1]["url"] == (
        "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=03430200&"
        "parameterCd=00060&startDT=2022-04-28T01%3A00%3A00Z&"
        "endDT=2022-05-26T01%3A00%3A00Z&siteStatus=all"
    )
    assert report["target_lock"]["support_interval"] == (
        "(target_time_minus_1h,target_time]"
    )
    assert report["pre_access_audit"]["score_computed"] is False
    assert set(report["frozen_artifacts"]) == {
        "holdout_protocol",
        "input_plan",
        "rollout_report",
        "rollout_verification",
        "predictions",
        "outcome_acquisition_script",
        "scorer_script",
        "native_hourly_parser_helper",
    }


def test_complete_native_samples_are_right_closed_hourly_mean() -> None:
    support_end = holdout.START + timedelta(hours=1)
    payload = _usgs_payload(
        timestamps=[
            holdout.START,
            holdout.START + timedelta(minutes=15),
            holdout.START + timedelta(minutes=30),
            holdout.START + timedelta(minutes=45),
            support_end,
        ],
        values=["999", "100", "200", "300", "400"],
    )

    parsed, qualifiers, counts, cadence = acquire._parse_usgs_native_hourly(
        payload,
        system={"outcome": {"site_id": "03424860", "parameter_code": "00060"}},
        support_starts=(holdout.START,),
        support_ends=(support_end,),
    )

    assert cadence == 900
    assert counts[support_end] == 4
    assert qualifiers[support_end] == "A"
    assert parsed[support_end] == pytest.approx(250 * 0.028316846592)


def test_incomplete_native_hour_is_missing_and_never_imputed() -> None:
    support_end = holdout.START + timedelta(hours=1)
    payload = _usgs_payload(
        timestamps=[
            holdout.START + timedelta(minutes=15),
            holdout.START + timedelta(minutes=30),
            support_end,
        ],
        values=["100", "200", "400"],
    )

    parsed, _, counts, cadence = acquire._parse_usgs_native_hourly(
        payload,
        system={"outcome": {"site_id": "03424860", "parameter_code": "00060"}},
        support_starts=(holdout.START,),
        support_ends=(support_end,),
    )

    assert cadence == 900
    assert counts[support_end] == 3
    assert parsed[support_end] is None
    body = acquire._outcome_csv((support_end,), parsed).decode("utf-8")
    assert f"{acquire._iso(support_end)},,independent_observation,target" in body


def test_score_uses_separate_common_mask_and_strict_ties_fail() -> None:
    prediction_rows = score._prediction_rows(
        freeze.DEFAULT_PREDICTIONS.read_bytes()
    )
    axis = {
        holdout.START + timedelta(hours=index + 1): 100.0
        for index in range(holdout.HOUR_COUNT)
    }
    observations = {system_id: dict(axis) for system_id in holdout.SYSTEM_IDS}
    missing_target = holdout.START + timedelta(hours=1)
    observations["center_hill"][missing_target] = None
    protocol = json.loads(freeze.DEFAULT_HOLDOUT_PROTOCOL.read_bytes())

    cases, groups = score._score_all(
        prediction_rows=prediction_rows,
        observations=observations,
        protocol=protocol,
    )

    assert len(cases) == 448
    assert groups["center_hill:1h"]["scored_issue_count"] == 55
    assert groups["center_hill:1h"]["exclusion_counts"] == {
        "target_hour_incomplete": 1,
        "persistence_issue_observation_missing": 0,
        "nonfinite_prediction": 0,
    }
    assert groups["center_hill:3h"]["scored_issue_count"] == 56
    for system_id in holdout.SYSTEM_IDS:
        group = groups[f"{system_id}:3h"]
        assert group["rmse_deltas_m3s"]["policy_minus_fixed_quadratic"] == 0.0
        assert (
            group["gates"]["policy_strictly_beats_fixed_quadratic_rmse"]
            is False
        )


def test_metrics_report_rmse_mae_and_signed_bias() -> None:
    metrics = score._metrics([1.0, 3.0], [2.0, 2.0])

    assert metrics == {"rmse_m3s": 1.0, "mae_m3s": 1.0, "bias_m3s": 0.0}


def _usgs_payload(*, timestamps, values) -> dict:
    return {
        "value": {
            "timeSeries": [
                {
                    "sourceInfo": {"siteCode": [{"value": "03424860"}]},
                    "variable": {
                        "variableCode": [{"value": "00060"}],
                        "unit": {"unitCode": "ft3/s"},
                        "noDataValue": -999999.0,
                    },
                    "values": [
                        {
                            "value": [
                                {
                                    "dateTime": acquire._iso(timestamp),
                                    "value": value,
                                    "qualifiers": ["A"],
                                }
                                for timestamp, value in zip(
                                    timestamps, values, strict=True
                                )
                            ]
                        }
                    ],
                }
            ]
        }
    }
