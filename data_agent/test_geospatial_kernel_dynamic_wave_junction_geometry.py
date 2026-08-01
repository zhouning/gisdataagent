from __future__ import annotations

import pytest
from pyproj import Geod

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_dag import (
    DynamicWaveDendriticTopology,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_geometry import (
    STAGE8_LOSS_COEFFICIENT_SEMANTICS,
    GeographicJunctionBranchSource,
    JunctionEnergyLossCoefficientEvidence,
    JunctionStructureEvidence,
    adjudicate_geographic_junction_energy_loss,
    bind_admitted_geographic_losses_to_dag,
    compile_geographic_junction_geometry,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SOURCE_URI = "https://example.test/public-centerlines.geojson"


def _sources(*, reversed_coordinates: bool = False):
    rows = (
        ("A", "upstream", ((-0.002, 0.0), (0.0, 0.0))),
        ("B", "upstream", ((0.0, 0.002), (0.0, 0.0))),
        ("C", "downstream", ((0.0, 0.0), (0.002, 0.0))),
    )
    return tuple(
        GeographicJunctionBranchSource(
            branch_id,
            role,
            branch_id,
            tuple(reversed(coordinates))
            if reversed_coordinates
            else coordinates,
            _SOURCE_URI,
            _SHA_A,
        )
        for branch_id, role, coordinates in rows
    )


def _geometry(*, structure_verified: bool = False, reversed_coordinates=False):
    evidence = (
        JunctionStructureEvidence(
            "natural_confluence",
            "https://example.test/structure-inventory",
            _SHA_B,
            "junction-1",
        )
        if structure_verified
        else None
    )
    return compile_geographic_junction_geometry(
        "C",
        (0.0, 0.0),
        _sources(reversed_coordinates=reversed_coordinates),
        geometry_window_length_m=100.0,
        terminal_snap_tolerance_m=1.0,
        minimum_terminal_path_length_m=20.0,
        structure_evidence=evidence,
    )


def _coefficient_evidence(**overrides):
    values = {
        "junction_id": "C",
        "upstream_branch_ids": ("A", "B"),
        "downstream_branch_id": "C",
        "upstream_loss_coefficients": (0.2, 0.3),
        "downstream_loss_coefficient": 0.1,
        "coefficient_semantics": STAGE8_LOSS_COEFFICIENT_SEMANTICS,
        "derivation_method": "site_specific_engineering_assessment",
        "applicability_confirmed": True,
        "structure_classification": "natural_confluence",
        "source_uri": "https://example.test/engineering-record",
        "source_sha256": _SHA_C,
        "source_record_id": "loss-assessment-1",
    }
    values.update(overrides)
    return JunctionEnergyLossCoefficientEvidence(**values)


def test_manufactured_geodesic_angles_are_recovered():
    geometry = _geometry()

    assert geometry.upstream_branch_ids == ("A", "B")
    assert geometry.downstream_branch_id == "C"
    assert geometry.upstream_to_downstream_deflection_degrees == pytest.approx(
        (0.0, 90.0), abs=1e-8
    )
    assert geometry.upstream_pair_angles_degrees[0][2] == pytest.approx(
        90.0, abs=1e-8
    )
    assert all(
        value.sampled_window_length_m == pytest.approx(100.0)
        for value in (*geometry.upstream_branches, geometry.downstream_branch)
    )


def test_coordinate_sequence_order_does_not_change_geometry():
    forward = _geometry()
    reverse = _geometry(reversed_coordinates=True)

    assert [
        value.flow_azimuth_degrees
        for value in (*forward.upstream_branches, forward.downstream_branch)
    ] == pytest.approx(
        [
            value.flow_azimuth_degrees
            for value in (*reverse.upstream_branches, reverse.downstream_branch)
        ],
        abs=1e-10,
    )
    assert forward.upstream_to_downstream_deflection_degrees == pytest.approx(
        reverse.upstream_to_downstream_deflection_degrees, abs=1e-10
    )


def test_sample_coordinate_uses_ellipsoidal_distance():
    geometry = _geometry()
    geod = Geod(ellps="WGS84")

    for branch in (*geometry.upstream_branches, geometry.downstream_branch):
        _, _, distance = geod.inv(
            branch.junction_endpoint[0],
            branch.junction_endpoint[1],
            branch.local_reference_coordinate[0],
            branch.local_reference_coordinate[1],
        )
        assert distance == pytest.approx(100.0, abs=1e-7)


def test_unsnapped_endpoint_and_unsupported_crs_fail_closed():
    sources = list(_sources())
    sources[0] = GeographicJunctionBranchSource(
        "A",
        "upstream",
        "A",
        ((-0.002, 0.0), (-0.001, 0.0)),
        _SOURCE_URI,
        _SHA_A,
    )
    with pytest.raises(
        ValueError, match="geographic_junction_branch_endpoint_not_snapped"
    ):
        compile_geographic_junction_geometry(
            "C",
            (0.0, 0.0),
            tuple(sources),
            geometry_window_length_m=100.0,
            terminal_snap_tolerance_m=1.0,
            minimum_terminal_path_length_m=20.0,
        )

    sources = list(_sources())
    source = sources[0]
    sources[0] = GeographicJunctionBranchSource(
        source.branch_id,
        source.role,
        source.source_feature_id,
        source.coordinates,
        source.source_uri,
        source.source_sha256,
        "EPSG:3857",
    )
    with pytest.raises(
        ValueError, match="geographic_junction_geometry_contract_invalid"
    ):
        compile_geographic_junction_geometry(
            "C",
            (0.0, 0.0),
            tuple(sources),
            geometry_window_length_m=100.0,
            terminal_snap_tolerance_m=1.0,
            minimum_terminal_path_length_m=20.0,
        )


def test_centerline_only_geometry_does_not_admit_loss_coefficients():
    geometry = _geometry()

    admission = adjudicate_geographic_junction_energy_loss(geometry)

    assert admission.admitted is False
    assert admission.energy_loss is None
    assert admission.reason_codes == (
        "structure_classification_unknown",
        "loss_coefficient_evidence_missing",
        "centerline_geometry_does_not_determine_loss_coefficient",
    )
    assert admission.as_dict()["implicit_zero_loss_assumed"] is False


def test_centerline_angle_formula_is_not_an_admitted_derivation():
    geometry = _geometry(structure_verified=True)
    evidence = _coefficient_evidence(
        derivation_method="centerline_angle_formula"
    )

    admission = adjudicate_geographic_junction_energy_loss(geometry, evidence)

    assert admission.admitted is False
    assert admission.reason_codes == ("loss_derivation_method_not_admitted",)


def test_exact_site_specific_evidence_can_bind_to_stage8_dag_contract():
    geometry = _geometry(structure_verified=True)
    admission = adjudicate_geographic_junction_energy_loss(
        geometry, _coefficient_evidence()
    )
    topology = DynamicWaveDendriticTopology(
        ("A", "B", "C"), ("C", "C", None)
    )

    losses = bind_admitted_geographic_losses_to_dag(
        topology, {"C": admission}
    )

    assert admission.admitted is True
    assert losses["C"].upstream_branch_ids == ("A", "B")
    assert losses["C"].upstream_loss_coefficients == (0.2, 0.3)
    assert losses["C"].downstream_loss_coefficient == 0.1


def test_non_admitted_geometry_cannot_bind_to_dag():
    admission = adjudicate_geographic_junction_energy_loss(_geometry())
    topology = DynamicWaveDendriticTopology(
        ("A", "B", "C"), ("C", "C", None)
    )

    with pytest.raises(
        ValueError,
        match="geographic_junction_energy_loss_dag_binding_not_admitted",
    ):
        bind_admitted_geographic_losses_to_dag(topology, {"C": admission})


def test_misattached_coefficient_evidence_fails_closed():
    geometry = _geometry(structure_verified=True)
    evidence = _coefficient_evidence(
        upstream_branch_ids=("B", "A"),
        upstream_loss_coefficients=(0.3, 0.2),
    )

    with pytest.raises(
        ValueError, match="geographic_junction_loss_evidence_misattached"
    ):
        adjudicate_geographic_junction_energy_loss(geometry, evidence)


def test_public_center_hill_geometry_gate_report_passes():
    from scripts import (
        compile_geotransport_dynamic_wave_junction_geometry_gates as gates,
    )

    report = gates.compile_gates(write_geometry=False)

    assert report["all_gates_passed"] is True
    assert report["public_case"]["geometry"]["junction_id"] == "18421703"
    assert report["public_case"]["loss_admission"]["admitted"] is False
    assert report["claim_boundary"]["public_loss_coefficient_admitted"] is False
