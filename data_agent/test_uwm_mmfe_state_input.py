from data_agent.uwm.mmfe_state_input import (
    MMFE_UWM_STATE_INPUT_SCHEMA,
    build_uwm_state_input_from_semantic_product,
    validate_uwm_state_input,
)


def test_build_uwm_state_input_from_minimal_mmfe_product():
    manifest = {
        "product_id": "sfp-uwm-001",
        "product_type": "semantic_fusion_product",
        "version": "1.0",
        "quality": {"score": 0.86},
        "mmfe_bundle": {
            "layer_summaries": [
                {"role": "buildings", "geometry_type": "polygon"},
                {"role": "poi", "geometry_type": "point"},
                {"role": "lst", "geometry_type": "raster"},
            ],
            "twm_consumption": {},
        },
    }
    contract = {
        "spatial_unit": {"unit_type": "grid_500m", "crs": "EPSG:4490"},
        "role_bindings": [
            {
                "role": "buildings",
                "uwm_role": "urban_form",
                "object_type": "building",
                "source_dataset_id": "chongqing_buildings",
            },
            {
                "role": "poi",
                "uwm_role": "service_accessibility",
                "object_type": "poi",
                "source_dataset_id": "gaode_poi",
            },
            {
                "role": "lst",
                "uwm_role": "heat_exposure",
                "object_type": "raster",
                "source_dataset_id": "modis_lst",
            },
        ],
    }
    relations = [
        {"semantic_relation_type": "grid_adjacent_to_grid", "uwm_usage": "spatial_graph", "relation_count": "12"},
        {"semantic_relation_type": "poi_serves_grid", "uwm_usage": "service_accessibility", "relation_count": "5"},
    ]

    payload = build_uwm_state_input_from_semantic_product(
        manifest,
        semantic_relations=relations,
        input_contract=contract,
        timestamp="2026-07-04T00:00:00+00:00",
    )
    validation = validate_uwm_state_input(payload)

    assert validation["valid"], validation["errors"]
    assert payload["schema"] == MMFE_UWM_STATE_INPUT_SCHEMA
    assert payload["source_product"]["product_id"] == "sfp-uwm-001"
    assert payload["urban_spatial_unit"]["unit_type"] == "grid_500m"
    assert payload["state_components"]["urban_form"]["role_count"] == 1
    assert payload["state_components"]["service_accessibility"]["role_count"] == 1
    assert payload["graph_summary"]["relation_type_count"] == 2
    assert payload["production_policy"]["authoritative_data_required_for_production"] is True


def test_validate_uwm_state_input_rejects_missing_spatial_unit():
    payload = {
        "schema": MMFE_UWM_STATE_INPUT_SCHEMA,
        "source_product": {"product_id": "sfp-uwm-001"},
        "object_role_registry": [],
        "state_components": {},
        "graph_summary": {},
        "production_policy": {"authoritative_data_required_for_production": True},
    }

    validation = validate_uwm_state_input(payload)

    assert not validation["valid"]
    assert "urban_spatial_unit.unit_type is required" in validation["errors"]


def test_fitted_proxy_role_bindings_are_marked_as_synthetic_sources():
    payload = build_uwm_state_input_from_semantic_product(
        {"product_id": "sfp-fitted", "product_type": "semantic_fusion_product", "version": "0.1"},
        input_contract={
            "spatial_unit": {"unit_type": "township_admin_unit", "crs": "EPSG:4326"},
            "role_bindings": [
                {
                    "role": "district_population_total_preserving_downscale",
                    "uwm_role": "population_vulnerability",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": "uwm_fitted_admin_population_downscaling_2021",
                    "synthetic_status": "fitted_proxy",
                }
            ],
        },
        timestamp="2026-07-05T00:00:00+08:00",
    )

    assert payload["production_policy"]["contains_synthetic_sources"] is True


def test_state_input_preserves_native_geometry_and_support_metadata():
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "sfp-native-geometry",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
        },
        input_contract={
            "spatial_unit": {"unit_type": "grid_500m", "crs": "EPSG:4490"},
            "role_bindings": [
                {
                    "role": "observed_lst",
                    "uwm_role": "heat_exposure",
                    "object_type": "raster",
                    "source_dataset_id": "observed_lst_2024",
                    "synthetic_status": "real",
                    "geometry_type": "raster",
                    "spatial_support": {
                        "support_type": "grid_cell",
                        "resolution": "500m",
                        "crs": "EPSG:4490",
                    },
                    "temporal_support": {
                        "resolution": "daily",
                        "valid_from": "2024-07-01",
                        "valid_to": "2024-07-31",
                    },
                    "aggregation_semantics": "mean",
                    "observation_semantics": "observed",
                }
            ],
        },
    )

    validation = validate_uwm_state_input(payload)
    role = payload["object_role_registry"][0]

    assert validation["valid"], validation["errors"]
    assert role["geometry_type"] == "raster"
    assert role["spatial_support"]["support_type"] == "grid_cell"
    assert role["temporal_support"]["resolution"] == "daily"
    assert role["aggregation_semantics"] == "mean"
    assert role["observation_semantics"] == "observed"
    assert payload["native_geometry_contract"]["metadata_complete"] is True
    assert payload["native_geometry_contract"]["complete_role_count"] == 1


def test_state_input_rejects_inferred_geometry_without_uncertainty_and_calibration():
    payload = build_uwm_state_input_from_semantic_product(
        {"product_id": "sfp-invalid-downscale"},
        input_contract={
            "spatial_unit": {"unit_type": "grid_500m"},
            "role_bindings": [
                {
                    "role": "downscaled_population",
                    "object_type": "raster",
                    "geometry_type": "raster",
                    "spatial_support": {"support_type": "grid_cell"},
                    "observation_semantics": "downscaled",
                    "aggregation_semantics": "density",
                }
            ],
        },
    )

    validation = validate_uwm_state_input(payload)

    assert not validation["valid"]
    assert any("uncertainty is required for downscaled" in error for error in validation["errors"])
    assert any(
        "calibration.status is required for downscaled" in error
        for error in validation["errors"]
    )
