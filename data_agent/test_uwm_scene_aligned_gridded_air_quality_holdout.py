import json
from functools import lru_cache
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.scene_aligned_gridded_air_quality_holdout import (
    build_uwm_scene_aligned_gridded_air_quality_holdout,
    validate_uwm_scene_aligned_gridded_air_quality_holdout,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
CHAP_ADMIN_PROXY_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/chap_pm25_admin_proxy.json"
)
TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")


@lru_cache(maxsize=1)
def _build_scene_gridded_holdout() -> dict:
    chap = json.loads(CHAP_ADMIN_PROXY_PATH.read_text(encoding="utf-8"))
    return build_uwm_scene_aligned_gridded_air_quality_holdout(
        chap_admin_proxy=chap,
        tap_root=TAP_ROOT,
        benchmark_id="uwm-scene-aligned-gridded-air-quality-holdout-test",
        created_at="2026-07-06T21:00:00Z",
        train_days=3,
    )


def test_scene_aligned_gridded_holdout_uses_chap_points_and_tap_daily_grid():
    holdout = _build_scene_gridded_holdout()
    validation = validate_uwm_scene_aligned_gridded_air_quality_holdout(holdout)

    assert validation["valid"], validation["errors"]
    assert holdout["schema"] == "uwm.scene_aligned_gridded_air_quality_holdout.v1"
    assert holdout["source_dataset_ids"] == [
        "chap_pm25_monthly_1km_2024_07_proxy",
        "tap_pm25_observed_gridded_chongqing_2018_2024",
    ]
    assert holdout["scene_period"] == {
        "start_date": "2024-07-01",
        "end_date": "2024-07-07",
    }
    assert holdout["admin_unit_count"] == 36
    assert holdout["holdout_count"] == 144
    assert holdout["tap_sampling_summary"]["sampled_admin_units"] == 36
    assert holdout["tap_sampling_summary"]["missing_admin_units"] == 0
    assert holdout["chap_anchor_summary"]["valid_pm25_admin_units"] == 36
    assert holdout["overall_results"]["best_uwm_method"] == (
        "spatial_idw_message_reconstruction"
    )
    assert holdout["overall_results"]["best_uwm_mae"] < holdout["overall_results"][
        "best_static_baseline_mae"
    ]
    assert holdout["overall_results"]["beats_all_traditional_static_baselines"] is True
    uncertainty = holdout["uncertainty_calibration"]
    assert uncertainty["method"] == "split_conformal_leave_one_train_day"
    assert uncertainty["confidence_level"] == 0.9
    assert uncertainty["calibration_count"] == 108
    assert uncertainty["holdout_count"] == 144
    assert uncertainty["best_uwm_method"] == "spatial_idw_message_reconstruction"
    assert uncertainty["static_baseline_method"] == "static_train_mean"
    assert uncertainty["uwm_interval_radius"] == 2.291251
    assert uncertainty["static_interval_radius"] == 6.85
    assert uncertainty["uwm_interval_coverage"] == 0.944444
    assert uncertainty["static_interval_coverage"] == 1.0
    assert uncertainty["uwm_mean_interval_width"] == 4.582503
    assert uncertainty["static_mean_interval_width"] == 13.7
    assert uncertainty["uwm_interval_score"] == 5.559385
    assert uncertainty["static_interval_score"] == 13.7
    assert uncertainty["uwm_interval_score_reduction"] == 8.140615
    assert uncertainty["uwm_uncertainty_calibration_ready"] is True
    assert uncertainty["supported_claim"] == (
        "scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline"
    )
    assert holdout["spatial_message_negative_control_summary"][
        "spatial_shuffle_negative_control_passed"
    ] is True
    assert holdout["scene_aligned_gridded_air_quality_holdout_ready"] is True
    assert holdout["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert holdout["observed_policy_outcome_superiority_claim"] is False
    assert holdout["empirical_superiority_claim"] is False
    assert holdout["supported_claim"] == (
        "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines"
    )


def test_data_foundation_gate_tracks_scene_aligned_gridded_holdout(tmp_path: Path):
    holdout = _build_scene_gridded_holdout()
    holdout_path = tmp_path / "scene_aligned_gridded_holdout.json"
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False), encoding="utf-8")

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
        scene_aligned_gridded_air_quality_holdout_path=holdout_path,
        gate_id="uwm-data-foundation-evidence-gate-scene-gridded-test",
        created_at="2026-07-06T21:05:00Z",
    )

    scene_slice = gate["evidence_slices"]["scene_aligned_gridded_air_quality_holdout"]
    assert scene_slice["source_artifact_exists"] is True
    assert scene_slice["scene_aligned_gridded_air_quality_holdout_ready"] is True
    assert scene_slice["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert scene_slice["holdout_count"] == 144
    assert scene_slice["best_uwm_method"] == "spatial_idw_message_reconstruction"
    assert scene_slice["best_uwm_mae"] < scene_slice["best_static_baseline_mae"]
    assert scene_slice["uwm_uncertainty_calibration_ready"] is True
    assert scene_slice["uwm_interval_score"] == 5.559385
    assert scene_slice["static_interval_score"] == 13.7
    assert scene_slice["uwm_interval_score_reduction"] == 8.140615
    assert scene_slice["observed_policy_outcome_superiority_claim"] is False
    claims = {claim["claim"] for claim in gate["supported_claims"]}
    assert "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines" in claims
    assert (
        "scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline"
        in claims
    )
    assert "scene_aligned_station_calibrated_air_quality_holdout_required" in gate[
        "remaining_gates"
    ]

    readiness = build_world_model_evidence_readiness(gate)
    air_quality = readiness["architecture_evidence"]["scene_aligned_gridded_air_quality"]
    assert air_quality["ready"] is True
    assert air_quality["best_method"] == "spatial_idw_message_reconstruction"
    assert air_quality["uncertainty_calibration_ready"] is True
    assert air_quality["uwm_interval_score"] == 5.559385
    assert air_quality["station_calibrated_ready"] is False
    assert readiness["policy_outcome_superiority_ready"] is False
