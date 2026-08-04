import json
from functools import lru_cache
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.state_prior_observed_readiness import (
    validate_state_prior_observed_candidate_readiness,
)
from data_agent.uwm.geospatial_state_prior_benchmark import (
    validate_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_dataset,
)
from data_agent.uwm.geospatial_state_prior_observed_station import (
    build_observed_station_pm25_state_prior_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
OPENAQ_ROOT = DATA_ROOT / "openaq_station_observations_multi_station_2018_10_17_23"
CROSSWALK_PATH = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_multi_station_2018_10_17_23"
    / "uwm_geospatial_station_admin_crosswalk.json"
)
ADMIN_PATH = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
GRAPH_PATH = DATA_ROOT / "admin_spatial_graph_2026_07_05" / "uwm_admin_spatial_adjacency_graph.json"
TAP_DOWNLOADED = (
    Path("/Users/zhouning/Downloads/tap_uwm") / "chongqing_pm25_2018_10_17_23" / "downloaded"
)
DATASET_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_dataset_2018_10_18_23"
    / "uwm_geospatial_state_prior_dataset.json"
)
READINESS_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_observed_readiness_aligned_2018_10_18_23"
    / "uwm_geospatial_state_prior_observed_readiness.json"
)
BENCHMARK_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_benchmark_2018_10_18_23"
    / "uwm_geospatial_state_prior_benchmark.json"
)


def test_live_multistation_snapshot_is_complete_without_credential_persistence():
    audit = _read_json(OPENAQ_ROOT / "openaq_acquisition_audit.json")
    measurements = _read_json(OPENAQ_ROOT / "openaq_sensor_measurements_raw.json")

    counts = {sensor_id: len(payload["results"]) for sensor_id, payload in measurements.items()}
    assert audit["all_pages_complete"] is True
    assert audit["api_key_persisted"] is False
    assert len(audit["selected_bindings"]) == 15
    assert len(measurements) == 15
    assert sum(counts.values()) == 1314
    assert sum(count > 0 for count in counts.values()) == 13
    assert all(
        page_audit["complete"] is True
        for page_audit in audit["sensor_measurement_pagination"].values()
    )


@pytest.mark.skipif(
    not ADMIN_PATH.is_file() or not TAP_DOWNLOADED.is_dir(),
    reason="requires restricted admin geometry and local TAP integration files",
)
def test_observed_station_dataset_rebuild_is_deterministic_and_lagged():
    dataset = _rebuilt_dataset()
    persisted = _read_json(DATASET_PATH)

    assert dataset == persisted
    assert validate_uwm_geospatial_state_prior_dataset(dataset) == {
        "valid": True,
        "errors": [],
    }
    audit = dataset["adapter_audit"]
    assert audit["measured_station_count"] == 13
    assert audit["daily_target_count_before_lag_join"] == 91
    assert audit["dropped_missing_lag_sample_count"] == 13
    assert audit["row_count"] == 78
    assert audit["time_group_count"] == 6
    assert audit["admin_group_count"] == 13
    assert audit["tap_feature_lag_days"] == 1
    assert audit["uses_current_or_future_target_values_in_features"] is False
    assert dataset["target"]["temporal_support"] == {
        "start_date": "2018-10-18",
        "end_date": "2018-10-23",
    }


def test_aligned_observed_candidate_passes_input_readiness_but_not_p2():
    readiness = _read_json(READINESS_PATH)

    assert validate_state_prior_observed_candidate_readiness(readiness) == {
        "valid": True,
        "errors": [],
    }
    assert all(readiness["gate_results"].values())
    assert readiness["remaining_gates"] == []
    assert readiness["p1_benchmark_input_ready"] is True
    assert readiness["p2_admission_permitted"] is False
    assert readiness["claim_boundary"]["max_claim_level"] == "not_for_claim"


def test_default_p1_benchmark_fails_closed_without_multigeometry_gain():
    benchmark = _read_json(BENCHMARK_PATH)

    assert validate_uwm_geospatial_state_prior_benchmark(benchmark) == {
        "valid": True,
        "errors": [],
    }
    assert benchmark["geospatial_state_prior_benchmark_ready"] is False
    assert benchmark["remaining_gates"] == [
        "candidate_beats_required_baselines_on_every_split",
        "geometry_shuffle_negative_controls_passed",
        "split_conformal_coverage_passed",
    ]
    aggregate = benchmark["aggregate_results"]
    assert (
        aggregate["multi_geometry_soft_alignment_ridge"]["mean_mae"]
        > aggregate["raster_only_ridge"]["mean_mae"]
    )
    assert benchmark["supported_claim"] == "no_multi_geometry_state_reconstruction_claim_supported"
    assert benchmark["claim_boundary"]["max_claim_level"] == "not_for_claim"


@lru_cache(maxsize=1)
def _rebuilt_dataset():
    evidence_paths = [
        OPENAQ_ROOT / "openaq_locations_raw.json",
        OPENAQ_ROOT / "openaq_sensor_measurements_raw.json",
        CROSSWALK_PATH,
        ADMIN_PATH,
        GRAPH_PATH,
    ]
    return build_observed_station_pm25_state_prior_dataset(
        locations_payload=_read_json(evidence_paths[0]),
        sensor_measurement_payloads=_read_json(evidence_paths[1]),
        station_admin_crosswalk=_read_json(CROSSWALK_PATH),
        admin_feature_collection=_read_json(ADMIN_PATH),
        admin_spatial_graph=_read_json(GRAPH_PATH),
        tap_downloaded_dir=TAP_DOWNLOADED,
        dataset_id="chongqing-openaq-observed-station-state-prior-2018-10-18-23",
        created_at="2026-08-04T21:15:00Z",
        evidence_refs=[str(path.relative_to(ROOT)) for path in evidence_paths]
        + [str(TAP_DOWNLOADED.resolve())],
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
