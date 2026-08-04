import copy
import json
from pathlib import Path

import pytest

from data_agent.test_uwm_geospatial_state_prior_benchmark import _dataset as _fixture_dataset
from data_agent.test_uwm_geospatial_state_prior_chongqing import (
    _dataset as _chongqing_dataset,
)
from data_agent.uwm.geospatial_kernel.state_prior_observed_readiness import (
    STATE_PRIOR_OBSERVED_READINESS_GATES,
    STATE_PRIOR_OBSERVED_READINESS_SCHEMA,
    build_state_prior_observed_candidate_readiness,
    compute_state_prior_observed_readiness_sha256,
    validate_state_prior_observed_candidate_readiness,
)
from data_agent.uwm.geospatial_kernel.station_admin_crosswalk import (
    station_admin_assignment_map,
)
from data_agent.uwm.openaq_station_observations import (
    build_openaq_station_observation_proxy,
)

ROOT = Path(__file__).resolve().parents[1]
OPENAQ_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central/openaq_station_observations"
CROSSWALK_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central"
    / "geospatial_station_admin_crosswalk_2026_08_04"
    / "uwm_geospatial_station_admin_crosswalk.json"
)


def test_multi_station_period_aligned_candidate_is_ready_for_p1_only():
    locations, measurements, crosswalk = _ready_observations()
    proxy = build_openaq_station_observation_proxy(
        locations_payload=locations,
        sensor_measurement_payloads=measurements,
        requested_location={"latitude": 29.5, "longitude": 106.5, "label": "fixture"},
        scene_time_range={"start_date": "2026-01-01", "end_date": "2026-05-01"},
        fetched_at="2026-08-04T18:00:00Z",
    )

    assessment = build_state_prior_observed_candidate_readiness(
        assessment_id="period-aligned-multi-station-fixture",
        created_at="2026-08-04T18:05:00Z",
        target_parameter="pm2.5",
        locations_payload=locations,
        sensor_measurement_payloads=measurements,
        multi_geometry_dataset=_fixture_dataset(source_evidence_kind="synthetic_fixture"),
        normalized_station_proxy=proxy,
        station_admin_crosswalk=crosswalk,
        evidence_refs=["fixture://openaq", "fixture://geometry"],
    )

    assert assessment["schema"] == STATE_PRIOR_OBSERVED_READINESS_SCHEMA
    assert tuple(assessment["gate_results"]) == STATE_PRIOR_OBSERVED_READINESS_GATES
    assert all(assessment["gate_results"].values())
    assert assessment["p1_benchmark_input_ready"] is True
    assert assessment["p2_admission_permitted"] is False
    assert assessment["supported_claim"] == (
        "observed_multi_geometry_candidate_ready_for_p1_execution_only"
    )
    assert assessment["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert validate_state_prior_observed_candidate_readiness(assessment) == {
        "valid": True,
        "errors": [],
    }


@pytest.mark.skipif(
    not OPENAQ_ROOT.is_dir(),
    reason="requires local Chongqing OpenAQ and geometry integration evidence",
)
def test_current_chongqing_openaq_candidate_has_explicit_no_go_gates():
    locations = _read_json(OPENAQ_ROOT / "openaq_locations_raw.json")
    measurements = _read_json(OPENAQ_ROOT / "openaq_sensor_measurements_raw.json")
    proxy = _read_json(OPENAQ_ROOT / "openaq_station_observation_proxy.json")
    crosswalk = station_admin_assignment_map(_read_json(CROSSWALK_PATH))

    assessment = build_state_prior_observed_candidate_readiness(
        assessment_id="chongqing-openaq-state-prior-observed-readiness",
        created_at="2026-08-04T18:10:00Z",
        target_parameter="pm25",
        locations_payload=locations,
        sensor_measurement_payloads=measurements,
        multi_geometry_dataset=_chongqing_dataset(),
        normalized_station_proxy=proxy,
        station_admin_crosswalk=crosswalk,
        evidence_refs=[
            str((OPENAQ_ROOT / "openaq_locations_raw.json").relative_to(ROOT)),
            str((OPENAQ_ROOT / "openaq_sensor_measurements_raw.json").relative_to(ROOT)),
            str((OPENAQ_ROOT / "openaq_station_observation_proxy.json").relative_to(ROOT)),
            str(CROSSWALK_PATH.relative_to(ROOT)),
        ],
    )

    summary = assessment["source_summary"]
    assert summary["target_observation_count"] == 100
    assert summary["measured_sensor_count"] == 1
    assert summary["measured_station_count"] == 1
    assert summary["distinct_spatial_band_count"] == 1
    assert summary["distinct_observation_time_group_count"] == 7
    assert summary["crosswalk_covered_station_count"] == 1
    assert summary["crosswalk_admin_group_count"] == 1
    assert summary["target_observed_time_range"] == {
        "start": "2018-10-17T11:00:00Z",
        "end": "2018-10-23T22:00:00Z",
    }
    assert assessment["p1_benchmark_input_ready"] is False
    assert assessment["p2_admission_permitted"] is False
    for gate in (
        "minimum_measured_station_support_met",
        "minimum_spatial_band_support_met",
        "minimum_admin_group_support_met",
        "observed_geometry_period_overlap",
    ):
        assert assessment["gate_results"][gate] is False
        assert gate in assessment["remaining_gates"]
    assert assessment["gate_results"]["station_admin_crosswalk_complete"] is True
    assert assessment["gate_results"]["normalized_proxy_matches_raw_measurements"] is True
    assert "acquire_multi_station_observations" in assessment["required_next_actions"]
    assert "acquire_period_aligned_geometry_features" in assessment["required_next_actions"]
    assert validate_state_prior_observed_candidate_readiness(assessment) == {
        "valid": True,
        "errors": [],
    }


def test_readiness_claim_escalation_is_rejected_even_after_rehash():
    locations, measurements, crosswalk = _ready_observations()
    proxy = build_openaq_station_observation_proxy(
        locations_payload=locations,
        sensor_measurement_payloads=measurements,
        requested_location={"latitude": 29.5, "longitude": 106.5, "label": "fixture"},
        scene_time_range={"start_date": "2026-01-01", "end_date": "2026-05-01"},
        fetched_at="2026-08-04T18:00:00Z",
    )
    assessment = build_state_prior_observed_candidate_readiness(
        assessment_id="claim-escalation-fixture",
        created_at="2026-08-04T18:05:00Z",
        target_parameter="pm25",
        locations_payload=locations,
        sensor_measurement_payloads=measurements,
        multi_geometry_dataset=_fixture_dataset(source_evidence_kind="synthetic_fixture"),
        normalized_station_proxy=proxy,
        station_admin_crosswalk=crosswalk,
        evidence_refs=["fixture://openaq", "fixture://geometry"],
    )
    forged = copy.deepcopy(assessment)
    forged["claim_boundary"]["scientific_result_claim"] = True
    forged["readiness_sha256"] = compute_state_prior_observed_readiness_sha256(forged)

    validation = validate_state_prior_observed_candidate_readiness(forged)

    assert not validation["valid"]
    assert "observed_readiness_claim_boundary_invalid" in validation["errors"]
    assert "observed_readiness_sha256_mismatch" not in validation["errors"]


def _ready_observations():
    locations = {"results": []}
    measurements = {}
    crosswalk = {}
    for station_index in range(5):
        station_id = str(7000 + station_index)
        sensor_id = str(21000 + station_index)
        locations["results"].append(
            {
                "id": station_id,
                "name": f"station-{station_index}",
                "distance": float(station_index),
                "coordinates": {
                    "latitude": 29.4 + 0.05 * station_index,
                    "longitude": 106.3 + 0.05 * station_index,
                },
                "sensors": [
                    {
                        "id": sensor_id,
                        "parameter": {"name": "pm25", "units": "ug/m3"},
                    }
                ],
            }
        )
        measurements[sensor_id] = {
            "results": [
                {
                    "value": 20.0 + station_index + month,
                    "parameter": {"name": "pm25", "units": "ug/m3"},
                    "datetime": {"utc": f"2026-{month:02d}-01T00:00:00Z"},
                }
                for month in range(1, 6)
            ]
        }
        crosswalk[station_id] = f"admin-{station_index}"
    return locations, measurements, crosswalk


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
