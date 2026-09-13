import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.station_aligned_air_quality_holdout import (
    UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA,
    build_uwm_station_aligned_air_quality_holdout,
    validate_uwm_station_aligned_air_quality_holdout,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
OPENAQ_MEASUREMENTS_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_sensor_measurements_raw.json"
)
OPENAQ_PROXY_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_station_observation_proxy.json"
)
OPENAQ_2024_ATTEMPT_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations_2024_07_attempt/openaq_station_observation_proxy.json"
)
TAP_ROOT = ROOT.parent / "Downloads/tap_uwm"


def _build_real_station_holdout() -> dict:
    return build_uwm_station_aligned_air_quality_holdout(
        openaq_measurements_path=OPENAQ_MEASUREMENTS_PATH,
        openaq_station_proxy_path=OPENAQ_PROXY_PATH,
        openaq_scene_attempt_path=OPENAQ_2024_ATTEMPT_PATH,
        tap_root=TAP_ROOT,
        holdout_id="uwm-station-aligned-air-quality-holdout-real-test",
        created_at="2026-07-06T14:05:00Z",
    )


def test_station_aligned_air_quality_holdout_uses_real_openaq_and_tap_without_scene_claim():
    holdout = _build_real_station_holdout()

    assert holdout["schema"] == UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA
    assert validate_uwm_station_aligned_air_quality_holdout(holdout) == {
        "valid": True,
        "errors": [],
    }
    assert holdout["historical_station_aligned_holdout_ready"] is True
    assert holdout["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert holdout["observed_policy_outcome_superiority_claim"] is False
    assert holdout["empirical_superiority_claim"] is False
    assert holdout["claim_boundary"]["max_claim_level"] == "bounded_support"

    station = holdout["station_alignment"]
    assert station["station_name"] == "上清寺"
    assert station["station_observation_count"] == 100
    assert station["tap_aligned_observation_count"] == 100
    assert station["nearest_tap_tile_id"] == "075"
    assert station["nearest_tap_grid_id"] == "62722"
    assert station["nearest_tap_grid_distance_m"] < 600

    benchmark = holdout["holdout_benchmark"]
    assert benchmark["train_count"] == 70
    assert benchmark["holdout_count"] == 30
    assert benchmark["best_station_aligned_method"] == "raw_tap_nearest_grid"
    assert benchmark["raw_tap_mae"] == 5.463333
    assert benchmark["static_train_mean_mae"] == 12.895238
    assert benchmark["static_last_observation_mae"] == 9.466667
    assert benchmark["linear_station_calibrated_tap_mae"] == 9.608119
    assert benchmark["raw_tap_beats_static_station_baselines"] is True
    assert benchmark["linear_calibration_beats_raw_tap"] is False

    scene_attempt = holdout["scene_attempt_evidence"]
    assert scene_attempt["scene_time_range"] == {
        "start_date": "2024-07-01",
        "end_date": "2024-07-07",
    }
    assert scene_attempt["scene_station_measurement_count"] == 0
    assert scene_attempt["scene_holdout_ready"] is False

    assert "scene_station_measurements_missing" in holdout["limitations"]
    assert "historical_2018_validation_not_2024_scene_holdout" in holdout["limitations"]
    claim = holdout["supported_claims"][0]
    assert claim["claim"] == "historical_station_aligned_tap_pm25_beats_static_station_baselines"
    assert claim["policy_outcome_claim"] is False


def test_data_foundation_keeps_scene_gate_when_only_historical_station_alignment_exists(
    tmp_path: Path,
):
    holdout = _build_real_station_holdout()
    holdout_path = tmp_path / "uwm_station_aligned_air_quality_holdout.json"
    holdout_path.write_text(json.dumps(holdout), encoding="utf-8")

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        station_aligned_air_quality_holdout_path=holdout_path,
        gate_id="uwm-data-foundation-evidence-gate-station-aligned-test",
        created_at="2026-07-06T14:10:00Z",
    )

    station_slice = gate["evidence_slices"]["station_aligned_air_quality_holdout"]
    assert station_slice["source_artifact_exists"] is True
    assert station_slice["historical_station_aligned_holdout_ready"] is True
    assert station_slice["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert "scene_aligned_station_calibrated_air_quality_holdout_required" in gate["remaining_gates"]
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False

    readiness = build_world_model_evidence_readiness(gate)
    station_arch = readiness["architecture_evidence"]["station_aligned_air_quality"]
    assert station_arch["historical_station_aligned_holdout_ready"] is True
    assert station_arch["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert "build_scene_aligned_station_calibrated_air_quality_holdout" in readiness["next_actions"]
