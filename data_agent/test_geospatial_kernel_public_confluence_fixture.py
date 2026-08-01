from __future__ import annotations

from dataclasses import replace

import pytest

from data_agent.uwm.geospatial_kernel_v2 import public_confluence_fixture as fixture


def _compiled():
    return fixture.compile_public_confluence_fixture()


def test_public_confluence_fixture_binds_real_three_branch_topology():
    value = _compiled()
    report = value.as_dict()

    assert value.junction_id == "18421703"
    assert value.junction_coordinate_wgs84 == pytest.approx(
        (-85.909170702, 36.178724498), abs=1e-12
    )
    assert {
        branch.feature_id: branch.role for branch in value.branches
    } == {
        "18421705": "upstream",
        "18421707": "upstream",
        "18421703": "downstream",
    }
    assert all(
        branch.terminal_snap_distance_m <= 0.5
        and branch.sampled_reference_distance_m == pytest.approx(30.0)
        for branch in value.branches
    )
    assert report["claim_boundary"]["real_public_hydrography_bound"] is True
    assert report["claim_boundary"]["operator_admitted"] is False


def test_public_confluence_horizontal_support_is_kernel_conforming():
    value = _compiled()
    geometry = value.diagnostic_horizontal_geometry
    report = value.as_dict()["computational_patch_support"]

    assert len(geometry.cells) == 6
    assert len(geometry.branch_faces) == 3
    assert len(
        [face for face in geometry.faces if face.boundary_type == "solid_wall"]
    ) == 3
    assert geometry.total_plan_area_m2 > 100.0
    assert geometry.external_closure_east_north_m == pytest.approx(
        (0.0, 0.0), abs=1e-12
    )
    assert max(
        item["absolute_error_degrees"]
        for item in report["opening_alignment"]
    ) <= fixture.OPENING_ALIGNMENT_TOLERANCE_DEGREES
    assert report["construction"]["surveyed_bank_polygon"] is False
    assert report["construction"]["computational_support_only"] is True
    assert report["construction"]["bed_elevation_semantics"] == (
        "local_placeholder_zero_not_terrain_or_channel_bed"
    )


def test_public_rasters_bind_terrain_context_and_uncalibrated_roughness():
    value = _compiled()
    geometry = value.diagnostic_horizontal_geometry
    roughness = value.roughness_prior_field

    assert tuple(item.cell_id for item in value.cell_evidence) == tuple(
        item.cell_id for item in geometry.cells
    )
    assert tuple(item.cell_id for item in roughness.cells) == tuple(
        item.cell_id for item in geometry.cells
    )
    for cell, evidence, prior in zip(
        geometry.cells,
        value.cell_evidence,
        roughness.cells,
        strict=True,
    ):
        assert evidence.terrain_sample_count > 0
        assert evidence.terrain_minimum_m <= evidence.terrain_mean_m
        assert evidence.terrain_mean_m <= evidence.terrain_maximum_m
        assert evidence.land_cover_sample_count > 0
        assert evidence.dominant_land_cover_code in (
            fixture.LAND_COVER_ROUGHNESS_PRIORS
        )
        assert evidence.manning_n_lower < evidence.manning_n_prior
        assert evidence.manning_n_prior < evidence.manning_n_upper
        assert prior.support_area_m2 == pytest.approx(
            geometry.cell_areas_m2[cell.cell_id], abs=1e-9
        )
        assert prior.manning_n == pytest.approx(evidence.manning_n_prior)
    assert roughness.as_dict()["roughness_is_calibrated"] is False


def test_public_gauge_is_scalar_observation_not_vector_validation():
    value = _compiled()
    gauge = value.as_dict()["gauge"]

    assert gauge["site_id"] == "03424860"
    assert gauge["observed_parameter_code"] == "00060"
    assert gauge["observed_quantity"] == "scalar_stream_discharge"
    assert gauge["observation_count"] > 24
    assert gauge["distance_from_junction_m"] > 0.0
    assert "two_component_momentum_observation" in gauge["inadmissible_roles"]
    assert value.as_dict()["claim_boundary"][
        "public_vector_momentum_validation_completed"
    ] is False


def test_public_fixture_fails_closed_without_bathymetry_and_cross_sections():
    value = _compiled()

    with pytest.raises(
        ValueError,
        match="public_confluence_bathymetry_and_cross_sections_missing",
    ):
        value.require_runtime_hydraulic_geometry()


def test_unmapped_land_cover_class_fails_closed():
    value = _compiled()
    terrain = {
        "schema": "gwm.geotransport.public_terrain_samples.v1",
        "bathymetry": False,
        "samples": [
            {
                "longitude": fixture.TARGET_JUNCTION_COORDINATE[0],
                "latitude": fixture.TARGET_JUNCTION_COORDINATE[1],
                "elevation_m": 150.0,
            }
        ],
    }
    land_cover = {
        "schema": "gwm.geotransport.public_land_cover_samples.v1",
        "classification": "USDA_NASS_CDL_2024",
        "samples": [
            {
                "longitude": fixture.TARGET_JUNCTION_COORDINATE[0],
                "latitude": fixture.TARGET_JUNCTION_COORDINATE[1],
                "class_code": 999,
            }
        ],
    }

    with pytest.raises(
        ValueError, match="public_confluence_land_cover_class_unmapped:999"
    ):
        fixture._compile_cell_evidence(
            value.diagnostic_horizontal_geometry,
            terrain_samples=terrain,
            land_cover_samples=land_cover,
        )


def test_geometry_provenance_mismatch_cannot_be_hidden_in_roughness_field():
    value = _compiled()
    changed = replace(
        value.roughness_prior_field,
        geometry_provenance_id="different-geometry-vintage",
    )

    assert changed.geometry_provenance_id != (
        value.diagnostic_horizontal_geometry.provenance_id
    )
    assert value.roughness_prior_field.geometry_provenance_id == (
        value.diagnostic_horizontal_geometry.provenance_id
    )

