from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.hec_ras_force_diagnostic import (
    CONTROL_VOLUME_AREA_UNPROJECTED_VARIANT,
    DOCUMENTED_FORCE_VARIANT,
    EXACT_BED_SINE_VARIANT,
    HEC_RAS_FORCE_VARIANTS,
    PRESSURE_UNPROJECTED_VARIANT,
    HecRasForceVariant,
    evaluate_hec_ras_force_variant,
    solve_hec_ras_force_variant,
)
from data_agent.uwm.geospatial_kernel_v2.hec_ras_reference import (
    HecRasCrossSection,
    HecRasGeometry,
    HecRasJunction,
    HecRasPlan,
    HecRasSteadyFlow,
    evaluate_hec_ras_projected_momentum_reference,
)
from data_agent.uwm.geospatial_kernel_v2.irregular_section import (
    ManningRoughnessZone,
    PiecewiseLinearChannelSection,
)
from scripts import acquire_geotransport_hec_ras_stage12_evidence as acquisition


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_documented_force_decomposition_matches_stage11_balance() -> None:
    geometry, flow, plan = _manufactured_inputs()

    stage11 = evaluate_hec_ras_projected_momentum_reference(
        geometry,
        flow,
        plan,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )
    diagnostic = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        DOCUMENTED_FORCE_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )

    assert diagnostic.residual_m3 == pytest.approx(stage11.residual_m3)
    assert diagnostic.downstream_force.specific_force_m3 == pytest.approx(
        stage11.downstream_specific_force_m3
    )
    assert [value.contribution_m3 for value in diagnostic.branches] == (
        pytest.approx([value.contribution_m3 for value in stage11.branches])
    )
    for branch in diagnostic.branches:
        assert branch.section_force.specific_force_m3 == pytest.approx(
            branch.section_force.hydrostatic_pressure_term_m3
            + branch.section_force.convective_momentum_term_m3
        )
        assert branch.projected_specific_force_m3 == pytest.approx(
            branch.projected_hydrostatic_pressure_term_m3
            + branch.projected_convective_momentum_term_m3
        )
        assert branch.contribution_m3 == pytest.approx(
            branch.projected_specific_force_m3
            - branch.friction_force_m3
            + branch.water_weight_force_m3
        )


def test_predeclared_variants_change_one_force_semantic_at_a_time() -> None:
    semantic_fields = (
        "pressure_projection",
        "control_volume_upstream_area_projection",
        "friction_downstream_allocation",
        "bed_slope_interpretation",
        "pressure_term_interpretation",
    )

    assert HEC_RAS_FORCE_VARIANTS[0] is DOCUMENTED_FORCE_VARIANT
    assert len({value.variant_id for value in HEC_RAS_FORCE_VARIANTS}) == len(
        HEC_RAS_FORCE_VARIANTS
    )
    for variant in HEC_RAS_FORCE_VARIANTS[1:]:
        changed = [
            field
            for field in semantic_fields
            if getattr(variant, field) != getattr(DOCUMENTED_FORCE_VARIANT, field)
        ]
        assert len(changed) == 1
        assert variant.matches_documented_equations is False
        assert variant.as_dict()["calibrated_to_example10"] is False
        assert variant.as_dict()["operator_admitted"] is False


def test_pressure_projection_variant_changes_only_projected_pressure() -> None:
    geometry, flow, plan = _manufactured_inputs()
    documented = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        DOCUMENTED_FORCE_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )
    alternative = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        PRESSURE_UNPROJECTED_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )

    straight_documented, angled_documented = documented.branches
    straight_alternative, angled_alternative = alternative.branches
    assert straight_alternative.contribution_m3 == pytest.approx(
        straight_documented.contribution_m3
    )
    assert angled_alternative.projected_convective_momentum_term_m3 == (
        pytest.approx(angled_documented.projected_convective_momentum_term_m3)
    )
    assert angled_alternative.friction_force_m3 == pytest.approx(
        angled_documented.friction_force_m3
    )
    assert angled_alternative.water_weight_force_m3 == pytest.approx(
        angled_documented.water_weight_force_m3
    )
    assert angled_alternative.projected_hydrostatic_pressure_term_m3 == (
        pytest.approx(
            angled_documented.section_force.hydrostatic_pressure_term_m3
        )
    )
    assert alternative.residual_m3 != pytest.approx(documented.residual_m3)


def test_control_volume_and_exact_bed_variants_are_isolated() -> None:
    geometry, flow, plan = _manufactured_inputs()
    documented = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        DOCUMENTED_FORCE_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )
    unprojected_area = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        CONTROL_VOLUME_AREA_UNPROJECTED_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )
    exact_sine = evaluate_hec_ras_force_variant(
        geometry,
        flow,
        plan,
        EXACT_BED_SINE_VARIANT,
        common_upstream_water_surface_elevation_m=1.2,
        downstream_water_surface_elevation_m=1.1,
    )

    angled_documented = documented.branches[1]
    angled_area = unprojected_area.branches[1]
    angled_sine = exact_sine.branches[1]
    assert angled_area.upstream_control_volume_area_m2 > (
        angled_documented.upstream_control_volume_area_m2
    )
    assert angled_area.projected_specific_force_m3 == pytest.approx(
        angled_documented.projected_specific_force_m3
    )
    assert angled_sine.applied_bed_slope < angled_sine.invert_tangent_slope
    assert angled_sine.friction_force_m3 == pytest.approx(
        angled_documented.friction_force_m3
    )
    assert angled_sine.projected_specific_force_m3 == pytest.approx(
        angled_documented.projected_specific_force_m3
    )


def test_variant_contract_and_solver_tolerance_fail_closed() -> None:
    with pytest.raises(ValueError, match="hec_ras_force_variant_contract_invalid"):
        HecRasForceVariant(
            variant_id="bad",
            changed_assumption="bad",
            evidence_basis="bad",
            pressure_projection="fit_to_stage",
        )

    geometry, flow, plan = _manufactured_inputs()
    with pytest.raises(ValueError, match="hec_ras_force_solver_tolerance_invalid"):
        solve_hec_ras_force_variant(
            geometry,
            flow,
            plan,
            DOCUMENTED_FORCE_VARIANT,
            downstream_water_surface_elevation_m=1.1,
            momentum_tolerance_m3=0.0,
        )


def test_stage12_acquisition_plan_is_bounded_and_sends_no_workspace_data() -> None:
    plan = acquisition.compile_plan()

    assert plan["request_boundary"] == {
        "allowed_hosts": [
            "raw.githubusercontent.com",
            "www.hec.usace.army.mil",
        ],
        "maximum_total_bytes": 320_000,
        "object_count": 4,
        "planned_exact_bytes": 280_125,
        "workspace_or_private_data_sent": False,
    }
    assert plan["claim_boundary"]["calibration_authorized"] is False
    assert plan["claim_boundary"]["operator_admitted"] is False
    assert "expected_canonical_sha256" in plan["requests"][2]


def test_frozen_stage12_report_preserves_diagnostic_refusal() -> None:
    report = json.loads(
        (
            REPO_ROOT
            / "benchmarks/geotransport_v0_1/"
            "hec_ras_example10_force_decomposition_diagnostic.json"
        ).read_text(encoding="utf-8")
    )

    assert report["status"] == "diagnostic_refusal_no_independent_discriminator"
    assert report["gate_summary"] == {
        "all_expected_behaviors_passed": True,
        "passed": 14,
        "total": 14,
    }
    assert report["selection_decision"]["selected_variant_id"] is None
    assert report["selection_decision"]["selection_performed"] is False
    assert report["claim_boundary"] == {
        "coefficient_calibration_performed": False,
        "equation_variants_evaluated": True,
        "force_terms_decomposed": True,
        "geospatial_kernel_validated": False,
        "independent_predictive_validation_complete": False,
        "projected_momentum_operator_admitted": False,
        "variant_selected_from_example10_fit": False,
    }
    variants = report["equation_variant_diagnostics"]
    assert len(variants) == 7
    assert all(
        value["root"]["within_published_stage_tolerance"] is False
        for value in variants
    )
    assert report["independent_evidence_search"][
        "independent_discriminating_case_available"
    ] is False
    assert report["independent_evidence_search"][
        "transparent_source_candidate"
    ]["momentum_junction_implemented"] is False


def _manufactured_inputs() -> tuple[HecRasGeometry, HecRasSteadyFlow, HecRasPlan]:
    upper = _section("Main", "Upper", "4.0", invert_m=0.1)
    tributary = _section("Trib", "Trib", "0.0", invert_m=0.2)
    downstream = _section("Main", "Lower", "3.0", invert_m=0.0)
    geometry = HecRasGeometry(
        title="Manufactured force diagnostic",
        junction=HecRasJunction(
            name="J",
            upstream_reaches=(upper.reach_key, tributary.reach_key),
            downstream_reach=downstream.reach_key,
            reach_lengths_m=(100.0, 100.0),
            deflection_degrees=(0.0, 45.0),
            raw_description_flags=(-1, -1, -1),
        ),
        cross_sections=(upper, tributary, downstream),
    )
    flow = HecRasSteadyFlow(
        title="Manufactured low flow",
        profile_name="base",
        discharges_m3s=(
            (upper.reach_key, 0.3),
            (tributary.reach_key, 0.2),
            (downstream.reach_key, 0.5),
        ),
        downstream_normal_depth_slope=0.001,
    )
    plan = HecRasPlan(
        title="Manufactured momentum",
        short_identifier="Momentum",
        geometry_file="g02",
        flow_file="f01",
        subcritical_flow=True,
        friction_slope_method=1,
    )
    return geometry, flow, plan


def _section(
    river: str, reach: str, station: str, *, invert_m: float
) -> HecRasCrossSection:
    return HecRasCrossSection(
        river_name=river,
        reach_name=reach,
        river_station=station,
        downstream_reach_lengths_m=(0.0, 0.0, 0.0),
        section=PiecewiseLinearChannelSection(
            (0.0, 0.0, 10.0, 10.0),
            (3.0, invert_m, invert_m, 3.0),
        ),
        roughness_zones=(ManningRoughnessZone(0.0, 0.03),),
        bank_stations_m=(0.0, 10.0),
    )
