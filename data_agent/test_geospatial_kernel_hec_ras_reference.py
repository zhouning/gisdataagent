from __future__ import annotations

import json
import math
from pathlib import Path
import zipfile

import pytest

from data_agent.uwm.geospatial_kernel_v2.hec_ras_reference import (
    CFS_TO_CUBIC_METRES_PER_SECOND,
    FEET_TO_METRES,
    HecRasSteadyFlow,
    evaluate_hec_ras_projected_momentum_reference,
    load_hec_ras_example_archive,
    parse_hec_ras_geometry,
    parse_hec_ras_plan,
    parse_hec_ras_steady_flow,
)
from data_agent.uwm.geospatial_kernel_v2.irregular_section import (
    ManningRoughnessZone,
    PiecewiseLinearChannelSection,
    conveyance_momentum_distribution,
)
from scripts import acquire_geotransport_hec_ras_example10 as acquisition


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vertical_bank_section_has_exact_wet_geometry_and_pressure() -> None:
    section = PiecewiseLinearChannelSection(
        (0.0, 0.0, 2.0, 2.0),
        (2.0, 0.0, 0.0, 2.0),
    )

    wet = section.wet_properties_at_elevation(1.0)

    assert wet.area_m2 == pytest.approx(2.0)
    assert wet.top_width_m == pytest.approx(2.0)
    assert wet.wetted_perimeter_m == pytest.approx(4.0)
    assert wet.hydraulic_radius_m == pytest.approx(0.5)
    assert wet.hydrostatic_pressure_integral_m3 == pytest.approx(1.0)
    assert section.depth_m(2.0) == pytest.approx(1.0)
    assert section.area_m2(1.0) == pytest.approx(2.0)
    assert section.gravity_wave_celerity_mps(2.0) == pytest.approx(
        math.sqrt(9.80665)
    )


def test_conveyance_partition_has_no_artificial_wall_and_recovers_beta() -> None:
    section = PiecewiseLinearChannelSection(
        (0.0, 0.0, 2.0, 2.0),
        (2.0, 0.0, 0.0, 2.0),
    )
    distribution = conveyance_momentum_distribution(
        section,
        (
            ManningRoughnessZone(0.0, 0.03),
            ManningRoughnessZone(1.0, 0.06),
        ),
        water_surface_elevation_m=1.0,
        discharge_m3s=3.0,
    )

    assert distribution.total_area_m2 == pytest.approx(2.0)
    assert [value.area_m2 for value in distribution.subsections] == pytest.approx(
        [1.0, 1.0]
    )
    assert [
        value.wetted_perimeter_m for value in distribution.subsections
    ] == pytest.approx([2.0, 2.0])
    assert [
        value.discharge_m3s for value in distribution.subsections
    ] == pytest.approx([2.0, 1.0])
    assert distribution.momentum_coefficient_beta == pytest.approx(10.0 / 9.0)
    assert distribution.as_dict()[
        "discharge_partition"
    ] == "Manning_conveyance_fraction"


def test_real_vertical_segment_on_zone_boundary_is_counted_once() -> None:
    section = PiecewiseLinearChannelSection(
        (0.0, 0.0, 1.0, 1.0, 2.0, 2.0),
        (2.0, 0.0, 0.0, 1.0, 1.0, 2.0),
    )
    distribution = conveyance_momentum_distribution(
        section,
        (
            ManningRoughnessZone(0.0, 0.03),
            ManningRoughnessZone(1.0, 0.04),
        ),
        water_surface_elevation_m=1.5,
        discharge_m3s=2.0,
    )

    total_subsection_perimeter = sum(
        value.wetted_perimeter_m for value in distribution.subsections
    )
    total_section_perimeter = section.wet_properties_at_elevation(
        1.5
    ).wetted_perimeter_m
    assert total_subsection_perimeter == pytest.approx(total_section_perimeter)


def test_invalid_irregular_section_states_fail_closed() -> None:
    with pytest.raises(ValueError, match="irregular_section_geometry_invalid"):
        PiecewiseLinearChannelSection((0.0, 1.0), (0.0, 0.0))

    section = PiecewiseLinearChannelSection(
        (0.0, 1.0, 2.0),
        (2.0, 0.0, 2.0),
    )
    with pytest.raises(ValueError, match="irregular_section_wet_state_invalid"):
        section.wet_properties_at_elevation(2.1)
    with pytest.raises(
        ValueError, match="conveyance_momentum_distribution_contract_invalid"
    ):
        conveyance_momentum_distribution(
            section,
            (ManningRoughnessZone(0.1, 0.03),),
            water_surface_elevation_m=1.0,
            discharge_m3s=1.0,
        )


def test_manufactured_hec_text_parses_and_evaluates_subcritical_balance() -> None:
    geometry = parse_hec_ras_geometry(_geometry_text())
    flow = parse_hec_ras_steady_flow(_flow_text())
    plan = parse_hec_ras_plan(_plan_text())

    upstream, downstream = geometry.junction_terminal_sections()
    assert geometry.title == "Manufactured Momentum Junction"
    assert geometry.junction.name == "Test Junction"
    assert geometry.junction.upstream_reaches == (
        ("Main", "Upper"),
        ("Trib", "Trib"),
    )
    assert geometry.junction.downstream_reach == ("Main", "Lower")
    assert geometry.junction.reach_lengths_m == pytest.approx(
        (80.0 * FEET_TO_METRES, 70.0 * FEET_TO_METRES)
    )
    assert geometry.junction.deflection_degrees == (0.0, 45.0)
    assert [value.river_station for value in upstream] == ["10.106", "0.013"]
    assert downstream.river_station == "10.091"
    assert flow.discharge_for_reach(("Main", "Lower")) == pytest.approx(
        50.0 * CFS_TO_CUBIC_METRES_PER_SECOND
    )

    balance = evaluate_hec_ras_projected_momentum_reference(
        geometry,
        flow,
        plan,
        common_upstream_water_surface_elevation_m=5.0 * FEET_TO_METRES,
        downstream_water_surface_elevation_m=5.0 * FEET_TO_METRES,
    )

    assert math.isfinite(balance.residual_m3)
    assert balance.downstream_specific_force_m3 > 0.0
    assert balance.downstream_froude_number < 1.0
    assert all(value.froude_number < 1.0 for value in balance.branches)


def test_manufactured_supercritical_state_is_rejected() -> None:
    geometry = parse_hec_ras_geometry(_geometry_text())
    plan = parse_hec_ras_plan(_plan_text())
    flow = HecRasSteadyFlow(
        title="Manufactured high flow",
        profile_name="high",
        discharges_m3s=(
            (("Main", "Upper"), 3_000.0 * CFS_TO_CUBIC_METRES_PER_SECOND),
            (("Trib", "Trib"), 2_000.0 * CFS_TO_CUBIC_METRES_PER_SECOND),
            (("Main", "Lower"), 5_000.0 * CFS_TO_CUBIC_METRES_PER_SECOND),
        ),
        downstream_normal_depth_slope=0.001,
    )

    with pytest.raises(
        ValueError, match="hec_ras_reference_state_not_subcritical"
    ):
        evaluate_hec_ras_projected_momentum_reference(
            geometry,
            flow,
            plan,
            common_upstream_water_surface_elevation_m=FEET_TO_METRES,
            downstream_water_surface_elevation_m=FEET_TO_METRES,
        )


def test_archive_loader_selects_strict_required_members(tmp_path: Path) -> None:
    path = tmp_path / "example.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("example/JUNCTION.G02", _geometry_text())
        archive.writestr("example/JUNCTION.F01", _flow_text())
        archive.writestr("example/JUNCTION.P02", _plan_text())

    loaded = load_hec_ras_example_archive(path)

    assert loaded.geometry_text == _geometry_text()
    assert loaded.flow_text == _flow_text()
    assert loaded.plan_text == _plan_text()


def test_acquisition_plan_is_bounded_and_marks_secondary_evidence() -> None:
    plan = acquisition.compile_plan()

    assert plan["request_boundary"]["planned_exact_bytes"] == 486_368
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False
    assert set(plan["request_boundary"]["allowed_hosts"]) == {
        "raw.githubusercontent.com",
        "www.hec.usace.army.mil",
    }
    assert "not a USACE original observation" in plan["evidence_roles"][
        "HydroClaude_fixed_commit_HDF"
    ]


def test_frozen_stage11_report_preserves_partial_conformance() -> None:
    report = json.loads(
        (
            REPO_ROOT
            / "benchmarks/geotransport_v0_1/"
            "hec_ras_example10_momentum_gates.json"
        ).read_text(encoding="utf-8")
    )

    assert report["gate_summary"]["all_expected_behaviors_passed"] is True
    assert report["conformance_summary"] == {
        "conveyance_and_flow_partition_conformed": True,
        "documented_projected_momentum_stage_conformed": False,
        "full_reference_conformance": False,
        "irregular_section_geometry_conformed": True,
        "momentum_coefficient_beta_conformed": True,
        "operator_admitted": False,
    }
    assert report["claim_boundary"]["coefficient_calibration_performed"] is False
    assert report["secondary_recomputation"][
        "is_official_usace_observation"
    ] is False


def _geometry_text() -> str:
    return """Geom Title=Manufactured Momentum Junction
Junct Name=Test Junction
Junct Desc=manufactured,-1,-1,-1
Up River,Reach=Main,Upper
Up River,Reach=Trib,Trib
Dn River,Reach=Main,Lower
Junc L&A=80,0
Junc L&A=70,45
River Reach=Main,Upper
Type RM Length L Ch R = 1,10.106,0,0,0
#Sta/Elev=4
0 10 0 0 10 0 10 10
#Mann=1,0
0 0.03 0
Bank Sta=0,10
River Reach=Trib,Trib
Type RM Length L Ch R = 1,0.013,0,0,0
#Sta/Elev=4
0 10 0 0 10 0 10 10
#Mann=1,0
0 0.04 0
Bank Sta=0,10
River Reach=Main,Lower
Type RM Length L Ch R = 1,10.091,0,0,0
#Sta/Elev=4
0 10 0 0 10 0 10 10
#Mann=1,0
0 0.035 0
Bank Sta=0,10
"""


def _flow_text() -> str:
    return """Flow Title=Manufactured steady flow
Number of Profiles=1
Profile Names=base
River Rch & RM=Main,Upper,10.106
30
River Rch & RM=Trib,Trib,0.013
20
River Rch & RM=Main,Lower,10.091
50
Dn Slope=0.001
"""


def _plan_text() -> str:
    return """Plan Title=Manufactured Momentum
Short Identifier=Momentum
Geom File=g02
Flow File=f01
Subcritical Flow
Friction Slope Method=1
"""
