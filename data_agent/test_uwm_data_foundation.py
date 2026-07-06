from data_agent.uwm.data_foundation import (
    UWM_CORE_DATA_ROLES,
    audit_uwm_data_foundation_manifest,
    audit_uwm_data_foundation_roles,
)


def test_data_foundation_role_audit_distinguishes_real_proxy_and_missing_roles():
    rows = [
        {
            "dataset_id": "buildings",
            "access_status": "available",
            "synthetic_status": "real",
            "used_by": "urban_form;renderer",
            "claim_boundary": "bounded_support",
        },
        {
            "dataset_id": "era5",
            "access_status": "planned_public_download",
            "synthetic_status": "public_proxy",
            "used_by": "meteorology;uwm_heat",
            "claim_boundary": "bounded_support",
        },
        {
            "dataset_id": "synthetic_air",
            "access_status": "available",
            "synthetic_status": "synthetic",
            "used_by": "uwm_air",
            "claim_boundary": "exploratory_only",
        },
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["schema"] == "uwm.data_foundation_role_audit.v1"
    assert audit["role_coverage"]["urban_form"]["coverage_level"] == "usable_real"
    assert audit["role_coverage"]["meteorology"]["coverage_level"] == "planned_proxy"
    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "synthetic_only"
    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "missing"
    assert "population_vulnerability" in audit["missing_required_roles"]
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]
    assert audit["claim_ceiling"] == "not_for_claim"


def test_administrative_equity_evaluation_layer_does_not_satisfy_population_vulnerability():
    rows = [
        {
            "dataset_id": "township_admin_units",
            "dataset_name": "Township administrative units",
            "access_status": "available",
            "synthetic_status": "real",
            "used_by": "administrative_units;equity_evaluation;planner",
            "claim_boundary": "fragile",
        }
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["administrative_units"]["coverage_level"] == "usable_real"
    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "missing"


def test_raw_public_proxy_download_is_visible_but_still_blocks_empirical_claims():
    rows = [
        {
            "dataset_id": "ghsl_raw_tiles",
            "dataset_name": "GHSL raw tiles",
            "access_status": "raw_public_proxy_available",
            "synthetic_status": "public_proxy",
            "used_by": "population_vulnerability;urban_form",
            "claim_boundary": "bounded_support",
        }
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "raw_proxy_available"
    assert "population_vulnerability" in audit["empirical_superiority_blockers"]


def test_fitted_proxy_is_visible_but_still_blocks_empirical_claims_when_used_alone():
    rows = [
        {
            "dataset_id": "uwm_fitted_admin_population_downscaling_2021",
            "dataset_name": "UWM fitted admin population downscaling proxy",
            "access_status": "available",
            "synthetic_status": "fitted_proxy",
            "used_by": "population_vulnerability;simulator_context",
            "claim_boundary": "exploratory_only",
        }
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "fitted_proxy_available"
    assert audit["role_coverage"]["population_vulnerability"]["claim_ceiling"] == "exploratory_only"
    assert "population_vulnerability" in audit["empirical_superiority_blockers"]


def test_point_environmental_proxy_available_still_blocks_observed_empirical_claims():
    rows = [
        {
            "dataset_id": "openmeteo_weather_history",
            "dataset_name": "Open-Meteo weather point history",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "point_history_proxy_not_holdout",
            "used_by": "meteorology;simulator_context",
            "claim_boundary": "bounded_support",
        },
        {
            "dataset_id": "openmeteo_air_history",
            "dataset_name": "Open-Meteo air quality point history",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "point_history_proxy_not_holdout",
            "used_by": "air_pollution_exposure;simulator_context",
            "claim_boundary": "bounded_support",
        },
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["meteorology"]["coverage_level"] == "proxy_available"
    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "proxy_available"
    assert {"meteorology", "air_pollution_exposure"}.issubset(set(audit["empirical_superiority_blockers"]))


def test_holdout_ready_environmental_proxy_can_unblock_observed_empirical_claims():
    rows = [
        {
            "dataset_id": "station_calibrated_air_grid",
            "dataset_name": "Station calibrated air quality grid",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "station_calibrated_holdout_ready",
            "used_by": "air_pollution_exposure;evidence_gate",
            "claim_boundary": "bounded_support",
        }
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "proxy_available"
    assert "air_pollution_exposure" not in audit["empirical_superiority_blockers"]


def test_observed_temporal_holdout_not_policy_outcome_does_not_unblock_empirical_superiority():
    rows = [
        {
            "dataset_id": "openaq_temporal_state_benchmark",
            "dataset_name": "OpenAQ observed temporal state benchmark",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "observed_holdout_not_policy_outcome",
            "lineage": "observed temporal holdout for state prediction; not policy intervention outcome",
            "used_by": "air_pollution_exposure;evidence_gate;state_dynamics_validation",
            "claim_boundary": "bounded_support",
        }
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "proxy_available"
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]


def test_not_for_claim_proxy_guard_does_not_lower_role_ceiling_when_claimable_proxy_exists():
    rows = [
        {
            "dataset_id": "tap_pm25_observed_gridded",
            "dataset_name": "TAP observed gridded PM2.5",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "tap_gridded_temporal_state_prediction_bounded",
            "used_by": "air_pollution_exposure;state_dynamics_validation",
            "claim_boundary": "bounded_support",
        },
        {
            "dataset_id": "tap_pm25_external_spatiotemporal_dynamics",
            "dataset_name": "TAP external spatiotemporal dynamics no-claim guard",
            "access_status": "available",
            "synthetic_status": "public_proxy",
            "quality_status": "external_dynamics_no_claim_supported",
            "used_by": "air_pollution_exposure;state_dynamics_validation",
            "claim_boundary": "not_for_claim",
        },
    ]

    audit = audit_uwm_data_foundation_roles(rows)

    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "proxy_available"
    assert audit["role_coverage"]["air_pollution_exposure"]["claim_ceiling"] == "bounded_support"
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]


def test_current_manifest_has_required_roles_but_blocks_empirical_claims_until_holdout_air_arrives():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    assert audit["schema"] == "uwm.data_foundation_manifest_role_audit.v1"
    assert audit["manifest_valid"], audit["manifest_errors"]
    assert set(UWM_CORE_DATA_ROLES).issubset(audit["role_coverage"])
    assert "population_vulnerability" not in audit["missing_required_roles"]
    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "usable_real"
    assert audit["role_coverage"]["air_pollution_exposure"]["coverage_level"] == "proxy_available"
    assert audit["role_coverage"]["meteorology"]["coverage_level"] == "proxy_available"
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]
    assert "meteorology" not in audit["empirical_superiority_blockers"]
    assert "population_vulnerability" not in audit["empirical_superiority_blockers"]
    assert "administrative_units" not in audit["empirical_superiority_blockers"]
    assert audit["claim_ceiling"] == "fragile"
    assert "download_or_mount_population_vulnerability_public_proxy" not in audit["public_acquisition_queue"]


def test_current_manifest_includes_administrative_units_for_governance_alignment():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    assert "administrative_units" in audit["role_coverage"]
    assert audit["role_coverage"]["administrative_units"]["coverage_level"] == "usable_real"
    assert "chongqing_township_admin_units_local" in audit["role_coverage"]["administrative_units"]["dataset_ids"]


def test_current_manifest_includes_admin_spatial_adjacency_graph_for_model_based_rl():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    assert "spatial_adjacency_graph" in audit["role_coverage"]
    assert audit["role_coverage"]["spatial_adjacency_graph"]["coverage_level"] == "usable_real"
    assert "chongqing_admin_spatial_adjacency_graph_2026_07_05" in audit["role_coverage"]["spatial_adjacency_graph"]["dataset_ids"]
    assert "spatial_adjacency_graph" not in audit["empirical_superiority_blockers"]


def test_current_manifest_includes_ghsl_admin_alignment_as_population_proxy():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    assert "ghsl_admin_zonal_proxy_alignment" in audit["role_coverage"]["population_vulnerability"]["dataset_ids"]
    assert "chongqing_district_population_stats_2021_local" in audit["role_coverage"]["population_vulnerability"]["dataset_ids"]
    assert audit["role_coverage"]["population_vulnerability"]["coverage_level"] == "usable_real"


def test_current_manifest_includes_openmeteo_historical_point_proxies_without_unblocking_holdout_claims():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    assert "openmeteo_weather_historical_point_proxy" in audit["role_coverage"]["meteorology"]["dataset_ids"]
    assert "openmeteo_air_quality_historical_point_proxy" in audit["role_coverage"]["air_pollution_exposure"]["dataset_ids"]
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]


def test_current_manifest_includes_chap_pm25_proxy_noaa_weather_and_pending_tap():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    air_ids = set(audit["role_coverage"]["air_pollution_exposure"]["dataset_ids"])
    meteorology_ids = set(audit["role_coverage"]["meteorology"]["dataset_ids"])

    assert "chap_pm25_monthly_1km_2024_07_proxy" in air_ids
    assert "tap_pm25_china_access_pending" in air_ids
    assert "noaa_isd_chongqing_weather_observation_2024_07" in meteorology_ids
    assert "meteorology" not in audit["empirical_superiority_blockers"]
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]


def test_current_manifest_includes_tap_external_dynamics_without_unblocking_claims():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")

    air_ids = set(audit["role_coverage"]["air_pollution_exposure"]["dataset_ids"])

    assert "tap_pm25_external_spatiotemporal_dynamics_chongqing_2018_2024" in air_ids
    assert audit["manifest_audit"]["row_count"] == 66
    assert audit["manifest_audit"]["claim_boundary_counts"]["bounded_support"] >= 46
    assert audit["role_coverage"]["air_pollution_exposure"]["claim_ceiling"] == "bounded_support"
    assert "air_pollution_exposure" in audit["empirical_superiority_blockers"]
