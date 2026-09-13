from data_agent.uwm.contracts import UWM_OBSERVATION_SCHEMA, validate_uwm_observation
from data_agent.uwm.mmfe_state_input import build_uwm_state_input_from_semantic_product
from data_agent.uwm.renderer import build_canonical_observation_from_state_input


def test_renderer_builds_canonical_observation_from_mmfe_state_input():
    state_input = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "sfp-uwm-renderer",
            "product_type": "semantic_fusion_product",
            "version": "1.0",
            "quality": {"score": 0.83},
        },
        semantic_relations=[
            {"semantic_relation_type": "grid_adjacent_to_grid", "uwm_usage": "spatial_graph", "relation_count": "4"},
            {"semantic_relation_type": "road_connects_grid", "uwm_usage": "mobility_graph", "relation_count": "2"},
        ],
        input_contract={
            "spatial_unit": {"unit_type": "grid_500m", "crs": "EPSG:4490", "spatial_extent": "Chongqing central"},
            "role_bindings": [
                {
                    "role": "buildings",
                    "uwm_role": "urban_form",
                    "object_type": "building",
                    "source_dataset_id": "chongqing_buildings",
                    "synthetic_status": "real",
                },
                {
                    "role": "lst",
                    "uwm_role": "heat_exposure",
                    "object_type": "raster",
                    "source_dataset_id": "modis_lst",
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "synthetic_air",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "grid",
                    "source_dataset_id": "synthetic_air_quality",
                    "synthetic_status": "synthetic",
                },
            ],
        },
        timestamp="2026-07-04T01:00:00+00:00",
    )
    manifest_audit = {
        "path": "docs/reports/uwm_data_foundation_manifest.csv",
        "valid": True,
        "row_count": 3,
        "claim_boundary_counts": {"bounded_support": 2, "exploratory_only": 1},
        "synthetic_status_counts": {"real": 1, "public_proxy": 1, "synthetic": 1},
    }

    observation = build_canonical_observation_from_state_input(
        state_input,
        manifest_audit=manifest_audit,
        observation_id="uwm-obs-001",
        timestamp="2026-07-04T01:05:00+00:00",
    )
    validation = validate_uwm_observation(observation)

    assert validation["valid"], validation["errors"]
    assert observation["schema"] == UWM_OBSERVATION_SCHEMA
    assert observation["observation_id"] == "uwm-obs-001"
    assert observation["spatial_units"][0]["unit_type"] == "grid_500m"
    assert {layer["role"] for layer in observation["object_layers"]} == {"buildings"}
    assert {feature["role"] for feature in observation["raster_features"]} == {"lst", "synthetic_air"}
    assert observation["graph_edges"][0]["edge_type"] == "grid_adjacent_to_grid"
    assert observation["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert observation["synthetic_flags"] == [
        {"dataset_id": "modis_lst", "status": "public_proxy"},
        {"dataset_id": "synthetic_air_quality", "status": "synthetic"},
    ]
    assert observation["renderer_trace"][0]["step"] == "load_mmfe_uwm_state_input"


def test_renderer_refuses_invalid_state_input_schema():
    state_input = {"schema": "wrong.schema"}

    observation = build_canonical_observation_from_state_input(state_input)

    assert observation["schema"] == UWM_OBSERVATION_SCHEMA
    assert observation["quality_flags"][0]["level"] == "error"
    assert observation["claim_boundary"]["max_claim_level"] == "not_for_claim"


def test_renderer_does_not_downgrade_public_proxy_observation_because_of_unrelated_manifest_rows():
    state_input = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "mmfe-openmeteo-history-2024-07-01-2024-07-07",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.54},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "point_has_air_quality_hourly_record",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": 168,
            }
        ],
        input_contract={
            "spatial_unit": {"unit_type": "point_environmental_proxy", "crs": "EPSG:4326"},
            "role_bindings": [
                {
                    "role": "openmeteo_air_quality_hourly_pollutants",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "point_timeseries",
                    "source_dataset_id": "openmeteo_air_quality_historical_point_proxy",
                    "synthetic_status": "public_proxy",
                }
            ],
        },
        timestamp="2026-07-05T01:30:00+00:00",
    )
    manifest_audit = {
        "path": "docs/reports/uwm_data_foundation_manifest.csv",
        "valid": True,
        "row_count": 22,
        "claim_boundary_counts": {"bounded_support": 19, "exploratory_only": 2, "fragile": 1},
        "synthetic_status_counts": {"public_proxy": 12, "synthetic": 1},
    }

    observation = build_canonical_observation_from_state_input(
        state_input,
        manifest_audit=manifest_audit,
        observation_id="uwm-openmeteo-obs-001",
        timestamp="2026-07-05T01:35:00+00:00",
    )

    assert validate_uwm_observation(observation)["valid"]
    assert observation["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert observation["synthetic_flags"] == [
        {"dataset_id": "openmeteo_air_quality_historical_point_proxy", "status": "public_proxy"}
    ]


def test_renderer_deduplicates_repeated_public_proxy_flags_for_same_source_dataset():
    state_input = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "mmfe-ghsl-admin-alignment-2020",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.62},
        },
        input_contract={
            "spatial_unit": {"unit_type": "township_admin_unit", "crs": "EPSG:4326"},
            "role_bindings": [
                {
                    "role": "ghsl_population_2020_zonal_sum",
                    "uwm_role": "population_vulnerability",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": "ghsl_admin_zonal_proxy_alignment",
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "ghsl_built_surface_2020_zonal_sum",
                    "uwm_role": "urban_form",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": "ghsl_admin_zonal_proxy_alignment",
                    "synthetic_status": "public_proxy",
                },
            ],
        },
    )

    observation = build_canonical_observation_from_state_input(state_input)

    assert observation["synthetic_flags"] == [
        {"dataset_id": "ghsl_admin_zonal_proxy_alignment", "status": "public_proxy"}
    ]
