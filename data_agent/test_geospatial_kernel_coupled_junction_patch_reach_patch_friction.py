from __future__ import annotations

from dataclasses import replace

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    coupled_junction_patch_reach_patch_friction as patch_friction,
)
from scripts.compile_geotransport_stage19_source_split_patch_reach_gates import (
    _contract,
    _geometry,
    _network,
    _rotate_vector,
    _state,
)


JunctionPatchCellManningRoughness = (
    patch_friction.JunctionPatchCellManningRoughness
)
JunctionPatchManningRoughnessField = (
    patch_friction.JunctionPatchManningRoughnessField
)
advance_patch_friction_source_split = (
    patch_friction.advance_patch_friction_source_split
)
apply_junction_patch_manning_friction = (
    patch_friction.apply_junction_patch_manning_friction
)
maximum_patch_friction_source_split_timestep_seconds = (
    patch_friction.maximum_patch_friction_source_split_timestep_seconds
)


COURANT_NUMBER = 0.4


def _roughness(geometry):
    values = (0.030, 0.035, 0.040, 0.045)
    return JunctionPatchManningRoughnessField(
        geometry.junction_id,
        geometry.provenance_id,
        tuple(
            JunctionPatchCellManningRoughness(
                cell.cell_id,
                value,
                geometry.cell_areas_m2[cell.cell_id],
                f"manufactured:stage20:{cell.cell_id}",
            )
            for cell, value in zip(geometry.cells, values, strict=True)
        ),
        "manufactured:stage20-spatial-roughness-field",
    )


def _advance(
    state,
    geometry,
    roughness,
    contract,
    network,
    *,
    convention="matched_local_velocity",
    fraction=0.5,
):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_patch_friction_source_split_timestep_seconds(
        state,
        geometry,
        roughness,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        courant_number=COURANT_NUMBER,
    )
    result = advance_patch_friction_source_split(
        state,
        geometry,
        roughness,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    return stable, result


def test_patch_manning_friction_preserves_mass_direction_and_dissipates_energy():
    geometry = _geometry()
    state = _state()
    result = apply_junction_patch_manning_friction(
        state,
        geometry,
        _roughness(geometry),
        timestep_seconds=1.0,
    )
    report = result.as_dict()

    assert result.state_after.total_volume_m3 == state.total_volume_m3
    assert result.volume_ledger_error_m3 == 0.0
    assert result.momentum_ledger_error_magnitude_m4s <= 1e-14
    assert result.kinetic_energy_dissipation_m5s2 > 0.0
    assert result.kinetic_energy_after_m5s2 < result.kinetic_energy_before_m5s2
    for before, after, trace in zip(
        state.cells, result.state_after.cells, result.cell_traces, strict=True
    ):
        assert after.volume_m3 == before.volume_m3
        assert 0.0 < trace.damping_factor <= 1.0
        cross = (
            before.momentum_east_m4s * after.momentum_north_m4s
            - before.momentum_north_m4s * after.momentum_east_m4s
        )
        dot = (
            before.momentum_east_m4s * after.momentum_east_m4s
            + before.momentum_north_m4s * after.momentum_north_m4s
        )
        assert cross == pytest.approx(0.0, abs=1e-14)
        assert dot >= 0.0
    assert report["roughness_field"]["spatial_support"] == (
        "exact_junction_patch_cell_polygon"
    )
    assert report["semi_implicit_vector_drag"] is True
    assert report["operator_admitted"] is False


def test_patch_manning_friction_is_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    baseline = apply_junction_patch_manning_friction(
        _state(), geometry, _roughness(geometry), timestep_seconds=1.0
    )
    rotated = apply_junction_patch_manning_friction(
        _state(rotation_degrees=rotation),
        rotated_geometry,
        _roughness(rotated_geometry),
        timestep_seconds=1.0,
    )

    assert rotated.kinetic_energy_dissipation_m5s2 == pytest.approx(
        baseline.kinetic_energy_dissipation_m5s2, abs=1e-14
    )
    for actual, expected in zip(
        rotated.state_after.cells, baseline.state_after.cells, strict=True
    ):
        vector = _rotate_vector(
            expected.momentum_east_m4s,
            expected.momentum_north_m4s,
            rotation,
        )
        assert actual.volume_m3 == expected.volume_m3
        assert (
            actual.momentum_east_m4s,
            actual.momentum_north_m4s,
        ) == pytest.approx(vector, abs=1e-12)


def test_patch_friction_full_split_closes_global_ledgers():
    geometry = _geometry()
    state = _state()
    stable, result = _advance(
        state,
        geometry,
        _roughness(geometry),
        _contract(),
        _network(),
    )
    report = result.as_dict()

    assert stable > 0.0
    assert result.patch_kinetic_energy_dissipation_m5s2 > 0.0
    assert result.patch_friction_momentum_change_magnitude_m4s > 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-8
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-9
    assert (
        result.reach_source_split_step.conservative_core_step
        .maximum_opening_momentum_closure_error_m4s
        <= 1e-12
    )
    assert report["spatially_supported_patch_roughness"] is True
    assert report["stage19_reach_source_split_preserved"] is True
    assert report["persistent_transverse_momentum_reservoir"] is False
    assert report["operator_admitted"] is False


def test_patch_friction_full_split_preserves_lake_at_rest():
    geometry = _geometry()
    state = _state(lake=True)
    network = _network(
        discharges=(0.0, 0.0, 0.0), lateral=(0.0, 0.0, 0.0)
    )
    _, result = _advance(
        state,
        geometry,
        _roughness(geometry),
        _contract(),
        network,
        convention="zero_longitudinal_momentum",
        fraction=1.0,
    )
    upstream, downstream, _, _ = network

    assert result.patch_state_after == state
    assert result.upstream_states == tuple(value.state for value in upstream)
    assert result.downstream_state == downstream.state
    assert result.patch_kinetic_energy_dissipation_m5s2 == 0.0
    assert result.patch_friction_momentum_change_magnitude_m4s == 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10


def test_patch_friction_full_split_is_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    network = _network()
    baseline_stable = maximum_patch_friction_source_split_timestep_seconds(
        _state(),
        geometry,
        _roughness(geometry),
        _contract(),
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        courant_number=COURANT_NUMBER,
    )
    rotated_stable = maximum_patch_friction_source_split_timestep_seconds(
        _state(rotation_degrees=rotation),
        rotated_geometry,
        _roughness(rotated_geometry),
        _contract(rotation_degrees=rotation),
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(baseline_stable, rotated_stable)
    baseline = advance_patch_friction_source_split(
        _state(),
        geometry,
        _roughness(geometry),
        _contract(),
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_patch_friction_source_split(
        _state(rotation_degrees=rotation),
        rotated_geometry,
        _roughness(rotated_geometry),
        _contract(rotation_degrees=rotation),
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )

    assert rotated_stable == pytest.approx(baseline_stable, abs=1e-12)
    for actual, expected in zip(
        (*rotated.upstream_states, rotated.downstream_state),
        (*baseline.upstream_states, baseline.downstream_state),
        strict=True,
    ):
        assert actual.area_m2 == pytest.approx(expected.area_m2, abs=1e-12)
        assert actual.discharge_m3s == pytest.approx(
            expected.discharge_m3s, abs=1e-12
        )
    for actual, expected in zip(
        rotated.patch_state_after.cells,
        baseline.patch_state_after.cells,
        strict=True,
    ):
        vector = _rotate_vector(
            expected.momentum_east_m4s,
            expected.momentum_north_m4s,
            rotation,
        )
        assert actual.volume_m3 == pytest.approx(expected.volume_m3, abs=1e-12)
        assert (
            actual.momentum_east_m4s,
            actual.momentum_north_m4s,
        ) == pytest.approx(vector, abs=1e-12)
    expected_friction = _rotate_vector(
        baseline.patch_friction_momentum_change_east_m4s,
        baseline.patch_friction_momentum_change_north_m4s,
        rotation,
    )
    assert (
        rotated.patch_friction_momentum_change_east_m4s,
        rotated.patch_friction_momentum_change_north_m4s,
    ) == pytest.approx(expected_friction, abs=1e-12)
    assert rotated.patch_kinetic_energy_dissipation_m5s2 == pytest.approx(
        baseline.patch_kinetic_energy_dissipation_m5s2, abs=1e-12
    )


def test_patch_friction_multistep_stays_positive_and_dissipative():
    geometry = _geometry()
    roughness = _roughness(geometry)
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    minimum_area = 20.0
    minimum_volume = min(value.volume_m3 for value in state.cells)
    total_patch_dissipation = 0.0

    for _ in range(20):
        _, result = _advance(
            state,
            geometry,
            roughness,
            contract,
            (upstream, downstream, upstream_external, downstream_external),
        )
        upstream = tuple(
            replace(reach, state=next_state)
            for reach, next_state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        state = result.patch_state_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(minimum_volume, result.minimum_patch_cell_volume_m3)
        total_patch_dissipation += result.patch_kinetic_energy_dissipation_m5s2
        assert result.patch_kinetic_energy_dissipation_m5s2 >= 0.0
        assert "transverse_momentum_after" not in result.as_dict()

    assert minimum_area > 0.0
    assert minimum_volume > 0.0
    assert maximum_mass_error <= 1e-8
    assert maximum_momentum_error <= 1e-9
    assert total_patch_dissipation > 0.0


def test_patch_friction_rejects_spatial_support_and_cfl_violations():
    geometry = _geometry()
    state = _state()
    roughness = _roughness(geometry)
    with pytest.raises(
        ValueError, match="junction_patch_manning_support_area_mismatch"
    ):
        apply_junction_patch_manning_friction(
            state,
            geometry,
            replace(
                roughness,
                cells=(
                    replace(roughness.cells[0], support_area_m2=99.0),
                    *roughness.cells[1:],
                ),
            ),
            timestep_seconds=1.0,
        )
    with pytest.raises(
        ValueError, match="junction_patch_manning_spatial_binding_mismatch"
    ):
        apply_junction_patch_manning_friction(
            state,
            geometry,
            replace(roughness, geometry_provenance_id="wrong"),
            timestep_seconds=1.0,
        )
    with pytest.raises(
        ValueError, match="junction_patch_cell_manning_roughness_invalid"
    ):
        replace(roughness.cells[0], manning_n=0.0)

    network = _network()
    stable = maximum_patch_friction_source_split_timestep_seconds(
        state,
        geometry,
        roughness,
        _contract(),
        network[0],
        network[1],
        upstream_external_boundaries=network[2],
        downstream_external_boundary=network[3],
        lateral_momentum_convention="matched_local_velocity",
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(
        ValueError, match="patch_friction_source_split_cfl_exceeded"
    ):
        advance_patch_friction_source_split(
            state,
            geometry,
            roughness,
            _contract(),
            network[0],
            network[1],
            upstream_external_boundaries=network[2],
            downstream_external_boundary=network[3],
            lateral_momentum_convention="matched_local_velocity",
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )


def test_compiled_stage20_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_stage20_patch_friction_source_split_gates,
    )

    report = (
        compile_geotransport_stage20_patch_friction_source_split_gates
        .compile_report()
    )

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "spatially_supported_patch_manning_friction_implemented"
    ] is True
    assert report["claim_boundary"][
        "persistent_transverse_momentum_reservoir"
    ] is False
    assert report["claim_boundary"]["roughness_calibrated"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
