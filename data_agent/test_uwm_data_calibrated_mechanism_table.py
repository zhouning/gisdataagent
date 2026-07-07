import json
from pathlib import Path

from data_agent.uwm.data_calibrated_mechanism_table import (
    UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA,
    build_uwm_data_calibrated_mechanism_table,
    validate_uwm_data_calibrated_mechanism_table,
)
from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.simulator import simulate_livability_rollout
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_GATE_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
)
NOAA_WEATHER_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07/noaa_isd_weather_proxy.json"
)
ADMIN_LIVABILITY_PANEL_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.json"
)


def _observation() -> dict:
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": "uwm-mechanism-table-sim-test",
        "spatial_units": [
            {
                "unit_id": "grid-1",
                "unit_type": "grid_500m",
                "heat_risk": 0.82,
                "air_pollution_exposure": 0.72,
                "service_accessibility": 0.32,
                "equity": 0.38,
                "livability": 0.35,
            }
        ],
        "object_layers": [{"role": "buildings", "source_dataset_id": "chongqing_buildings"}],
        "raster_features": [{"role": "tap_pm25", "source_dataset_id": "tap_pm25_observed_gridded"}],
        "graph_edges": [],
        "temporal_index": {"observation_created_at": "2026-07-06T18:00:00+00:00"},
        "quality_flags": [{"level": "info", "message": "mechanism table simulator test"}],
        "synthetic_flags": [{"dataset_id": "tap_pm25_observed_gridded", "status": "public_proxy"}],
        "provenance": {"manifest_path": "docs/reports/uwm_data_foundation_manifest.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "renderer_trace": [{"step": "derive_canonical_observation"}],
    }


def test_data_calibrated_mechanism_table_uses_real_evidence_without_policy_claim():
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=EVIDENCE_GATE_PATH,
        noaa_weather_path=NOAA_WEATHER_PATH,
        admin_livability_panel_path=ADMIN_LIVABILITY_PANEL_PATH,
        table_id="uwm-data-calibrated-mechanism-table-real-test",
        created_at="2026-07-06T18:05:00Z",
    )

    assert table["schema"] == UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA
    assert validate_uwm_data_calibrated_mechanism_table(table) == {
        "valid": True,
        "errors": [],
    }
    assert table["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert table["observed_policy_outcome_superiority_claim"] is False
    assert table["empirical_superiority_claim"] is False

    calibration = table["calibration_evidence"]
    assert calibration["openaq_observation_count"] == 600
    assert calibration["tap_holdout_count"] == 40000
    assert calibration["station_aligned_observation_count"] == 100
    assert calibration["noaa_scene_observation_count"] == 224
    assert calibration["admin_livability_row_count"] >= 36
    assert calibration["air_quality_observed_advantage_over_static"] is True
    assert calibration["external_temporal_transition_claim"] is True
    assert calibration["observed_policy_outcome_ready"] is False

    assert table["mechanism_coefficients"]["traffic_emission_control"][
        "air_pollution_exposure_delta"
    ] < -0.16
    assert table["mechanism_coefficients"]["increase_green_infrastructure"][
        "heat_risk_delta"
    ] < -0.18
    assert table["mechanism_coefficients"]["add_community_service"][
        "service_accessibility_delta"
    ] > 0.18
    assert table["traditional_baseline_comparison"][
        "observed_state_prediction_superiority_claim"
    ] is True
    assert table["traditional_baseline_comparison"][
        "mechanism_policy_outcome_superiority_claim"
    ] is False
    assert "observed_policy_outcome_required" in table["remaining_gates"]


def test_simulator_consumes_data_calibrated_mechanism_table_with_trace():
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=EVIDENCE_GATE_PATH,
        noaa_weather_path=NOAA_WEATHER_PATH,
        admin_livability_panel_path=ADMIN_LIVABILITY_PANEL_PATH,
        table_id="uwm-data-calibrated-mechanism-table-sim-test",
        created_at="2026-07-06T18:10:00Z",
    )
    observation = _observation()
    action = [
        {
            "action_id": "lez-grid-1",
            "action_type": "traffic_emission_control",
            "target_units": ["grid-1"],
            "intensity": 1.0,
        }
    ]

    default_rollout = simulate_livability_rollout(
        observation,
        action,
        scenario={"scenario_id": "default-mechanism"},
    )
    calibrated_rollout = simulate_livability_rollout(
        observation,
        action,
        scenario={"scenario_id": "calibrated-mechanism"},
        mechanism_table=table,
    )

    assert calibrated_rollout["backend"] == "mechanistic_urban_livability_v0"
    assert calibrated_rollout["air_pollution_exposure_delta"] < default_rollout[
        "air_pollution_exposure_delta"
    ]
    assert calibrated_rollout["livability_delta"] > default_rollout["livability_delta"]
    assert calibrated_rollout["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert any(
        step["step"] == "read_data_calibrated_mechanism_table"
        and step["mechanism_table_id"] == table["table_id"]
        and step["valid"] is True
        for step in calibrated_rollout["simulator_trace"]
    )
    assert any(
        step["step"] == "apply_action_effects"
        and step["mechanism_source"] == "data_calibrated_mechanism_table"
        for step in calibrated_rollout["simulator_trace"]
    )


def test_data_calibrated_mechanism_table_roundtrips_json(tmp_path: Path):
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=EVIDENCE_GATE_PATH,
        noaa_weather_path=NOAA_WEATHER_PATH,
        admin_livability_panel_path=ADMIN_LIVABILITY_PANEL_PATH,
        table_id="uwm-data-calibrated-mechanism-table-roundtrip-test",
        created_at="2026-07-06T18:15:00Z",
    )
    path = tmp_path / "mechanism_table.json"
    path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert validate_uwm_data_calibrated_mechanism_table(loaded)["valid"] is True


def test_data_foundation_gate_tracks_data_calibrated_mechanism_without_policy_claim(
    tmp_path: Path,
):
    table = build_uwm_data_calibrated_mechanism_table(
        evidence_gate_path=EVIDENCE_GATE_PATH,
        noaa_weather_path=NOAA_WEATHER_PATH,
        admin_livability_panel_path=ADMIN_LIVABILITY_PANEL_PATH,
        table_id="uwm-data-calibrated-mechanism-table-gate-test",
        created_at="2026-07-06T18:20:00Z",
    )
    table_path = tmp_path / "uwm_data_calibrated_mechanism_table.json"
    table_path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")

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
        data_calibrated_mechanism_table_path=table_path,
        gate_id="uwm-data-foundation-evidence-gate-mechanism-table-test",
        created_at="2026-07-06T18:25:00Z",
    )

    mechanism_slice = gate["evidence_slices"]["data_calibrated_mechanism_table"]
    assert mechanism_slice["source_artifact_exists"] is True
    assert mechanism_slice["data_calibrated_mechanism_ready"] is True
    assert mechanism_slice["hardcoded_mechanism_replacement_ready"] is True
    assert mechanism_slice["observed_policy_outcome_superiority_claim"] is False
    assert mechanism_slice["claim_level"] == "bounded_support"
    assert "data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients" in {
        claim["claim"] for claim in gate["supported_claims"]
    }
    assert "observed_policy_outcome_required" in gate["remaining_gates"]

    readiness = build_world_model_evidence_readiness(gate)
    simulator_arch = readiness["architecture_evidence"]["simulator"]
    assert simulator_arch["data_calibrated_mechanism_ready"] is True
    assert simulator_arch["hardcoded_mechanism_replacement_ready"] is True
    assert readiness["empirical_superiority_claim"] is False
