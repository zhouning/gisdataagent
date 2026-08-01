#!/usr/bin/env python3
"""Compile Stage 13 native conservative-vector junction gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

if __package__:
    from .assess_geotransport_stage13_confluence_evidence import (
        assess as assess_public_evidence,
    )
else:
    from assess_geotransport_stage13_confluence_evidence import (
        assess as assess_public_evidence,
    )
from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    advance_conservative_vector_confluence_network_open,
    solve_conservative_vector_junction,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
    maximum_subcritical_confluence_stable_timestep_seconds,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage13_conservative_vector_junction_gates.json"
)
SCHEMA = "gwm.geotransport.stage13_conservative_vector_junction_gates.v1"
MASS_TOLERANCE_M3S = 2e-12
VECTOR_TOLERANCE_M4S2 = 2e-12
ROTATION_DEGREES = 73.0

FROZEN_PREDECESSOR_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/__init__.py": (
        "7db7e6459143d2a54e742a732fcd3f85c422a9775559296dc39a985ab632315d"
    ),
    "data_agent/uwm/geospatial_kernel_v2/dynamic_wave_junction_momentum.py": (
        "64cd7ae682784a2d9fc4be48bf6a3a7fc2eb074d5e31bca97fdc5bd6f298a873"
    ),
    "data_agent/uwm/geospatial_kernel_v2/irregular_section.py": (
        "3cde5d5bbdce22738516fed8ff2dd078f9eb50824b66b7155e10849f440e07cd"
    ),
    "data_agent/uwm/geospatial_kernel_v2/hec_ras_reference.py": (
        "9536a02990743a456574a737059be6d0a4134d44bf98a629095d7ce28515b39d"
    ),
    "data_agent/uwm/geospatial_kernel_v2/hec_ras_force_diagnostic.py": (
        "db17609e7b10b6f7e54b3d6eb620c763c60dc928e4bed6029176de3ad12553cb"
    ),
    "scripts/acquire_geotransport_hec_ras_stage12_evidence.py": (
        "5d878c6ebc81cf5bff4351c6308cd8d64421ae0b2286061ff71c72c90559c89d"
    ),
    "scripts/compile_geotransport_hec_ras_stage12_force_diagnostic.py": (
        "1032df71711c6b540f1337e8fc8675039ce1cc44da2088e940be4e1f6bdeaee2"
    ),
    "data_agent/test_geospatial_kernel_hec_ras_force_diagnostic.py": (
        "a3d4a46168c0a0133a7330680a7bd51cc6876413d21d767fa95f8df771677c7f"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "hec_ras_example10_force_decomposition_diagnostic.json"
    ): (
        "2d3f07e8619ad0144c2446be0ac5fb5921f08be516a42e84ff27a763925d42a9"
    ),
    (
        "docs/architecture-decisions/"
        "adr-053-junction-force-decomposition-and-refusal.md"
    ): (
        "eacb1a934ca0b67c5e222e1bd6866788dcb4cbbebbba771a70bddd955634430b"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report() -> dict[str, Any]:
    public_evidence = assess_public_evidence()
    upstream, downstream, contract = _manufactured_junction()
    baseline = solve_conservative_vector_junction(
        upstream, downstream, contract
    )
    rotated_contract = replace(
        contract,
        upstream_flow_azimuth_degrees=tuple(
            (value + ROTATION_DEGREES) % 360.0
            for value in contract.upstream_flow_azimuth_degrees
        ),
        downstream_flow_azimuth_degrees=(
            contract.downstream_flow_azimuth_degrees + ROTATION_DEGREES
        )
        % 360.0,
    )
    rotated = solve_conservative_vector_junction(
        upstream, downstream, rotated_contract
    )
    expected_rotated = _rotate_vector(
        baseline.junction_on_fluid_reaction_east_m4s2,
        baseline.junction_on_fluid_reaction_north_m4s2,
        ROTATION_DEGREES,
    )
    rotation_error = (
        rotated.junction_on_fluid_reaction_east_m4s2
        - expected_rotated[0],
        rotated.junction_on_fluid_reaction_north_m4s2
        - expected_rotated[1],
    )

    reordered_contract = replace(
        contract,
        upstream_branch_ids=tuple(reversed(contract.upstream_branch_ids)),
        upstream_flow_azimuth_degrees=tuple(
            reversed(contract.upstream_flow_azimuth_degrees)
        ),
    )
    reordered = solve_conservative_vector_junction(
        tuple(reversed(upstream)), downstream, reordered_contract
    )
    permutation_error = (
        reordered.boundary_total_flux_east_m4s2
        - baseline.boundary_total_flux_east_m4s2,
        reordered.boundary_total_flux_north_m4s2
        - baseline.boundary_total_flux_north_m4s2,
    )

    lake = _lake_at_rest()
    network_step = _network_step()
    lake_reaction = lake.junction_on_fluid_reaction_east_m4s2
    decomposition_error = max(
        abs(
            value.total_flux_m4s2
            - value.convective_flux_m4s2
            - value.hydrostatic_flux_m4s2
        )
        for value in (*baseline.upstream_fluxes, baseline.downstream_flux)
    )
    predecessor_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_PREDECESSOR_HASHES.items()
    }
    predecessors_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in predecessor_hashes.values()
    )
    gates = {
        "predecessor_stages_hash_frozen": predecessors_frozen,
        "public_evidence_refusal_assessment_passed": (
            public_evidence["all_gates_passed"] is True
            and public_evidence["admission_requirements"]["admitted_dataset"]
            is None
        ),
        "zero_storage_mass_ledger_closed": (
            abs(baseline.net_outward_mass_flux_m3s)
            <= MASS_TOLERANCE_M3S
        ),
        "explicit_vector_momentum_ledger_closed": (
            baseline.momentum_ledger_residual_magnitude_m4s2
            <= VECTOR_TOLERANCE_M4S2
        ),
        "nonzero_reaction_retained": (
            baseline.junction_reaction_magnitude_m4s2 > 0.0
        ),
        "convective_and_hydrostatic_terms_explicit": (
            decomposition_error <= VECTOR_TOLERANCE_M4S2
        ),
        "rotation_covariance": (
            math.hypot(*rotation_error) <= VECTOR_TOLERANCE_M4S2
        ),
        "rotation_preserves_reaction_magnitude": (
            abs(
                rotated.junction_reaction_magnitude_m4s2
                - baseline.junction_reaction_magnitude_m4s2
            )
            <= VECTOR_TOLERANCE_M4S2
        ),
        "rotation_preserves_hydraulic_solution": (
            rotated.hydraulic_solution == baseline.hydraulic_solution
        ),
        "upstream_permutation_invariance": (
            math.hypot(*permutation_error) <= VECTOR_TOLERANCE_M4S2
        ),
        "lake_at_rest_state_preserved": (
            abs(
                lake.hydraulic_solution.common_free_surface_elevation_m
                - 2.0
            )
            <= 1e-12
            and lake.net_outward_mass_flux_m3s == 0.0
            and all(
                value.state.discharge_m3s == 0.0
                for value in lake.hydraulic_solution.upstream_boundaries
            )
            and lake.hydraulic_solution.downstream_boundary.state.discharge_m3s
            == 0.0
        ),
        "symmetric_lake_transverse_reaction_cancels": (
            abs(lake_reaction) <= VECTOR_TOLERANCE_M4S2
        ),
        "lake_vector_ledger_closed": (
            lake.momentum_ledger_residual_magnitude_m4s2
            <= VECTOR_TOLERANCE_M4S2
        ),
        "synchronous_network_step_mass_and_vector_ledgers_close": (
            abs(network_step.hydraulic_step.network_volume_balance_error_m3)
            <= 1e-8
            and abs(network_step.vector_junction.net_outward_mass_flux_m3s)
            <= MASS_TOLERANCE_M3S
            and network_step.vector_junction.momentum_ledger_residual_magnitude_m4s2
            <= VECTOR_TOLERANCE_M4S2
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "native_candidate_manufactured_invariants_pass_"
            "public_validation_pending"
        ),
        "law": {
            "hydraulic_coupling": (
                "common_stage_plus_zero_storage_mass_plus_outgoing_"
                "characteristics"
            ),
            "branch_generalized_momentum_flux": "Q^2/A+g*I1",
            "direction_projection": (
                "WGS84_flow_azimuth_to_east_north_unit_tangent"
            ),
            "vector_balance": (
                "boundary_generalized_flux-junction_on_fluid_reaction=0"
            ),
            "reaction_semantics": (
                "unresolved_junction_walls_and_bed_source_on_water"
            ),
            "fitted_parameters": [],
        },
        "tolerances": {
            "mass_m3s": MASS_TOLERANCE_M3S,
            "vector_m4s2": VECTOR_TOLERANCE_M4S2,
        },
        "baseline": baseline.as_dict(),
        "rotation_control": {
            "rotation_degrees": ROTATION_DEGREES,
            "expected_reaction_east_north_m4s2": list(expected_rotated),
            "actual_reaction_east_north_m4s2": [
                rotated.junction_on_fluid_reaction_east_m4s2,
                rotated.junction_on_fluid_reaction_north_m4s2,
            ],
            "error_east_north_m4s2": list(rotation_error),
        },
        "permutation_control": {
            "error_east_north_m4s2": list(permutation_error),
        },
        "lake_at_rest_control": lake.as_dict(),
        "synchronous_network_step": network_step.as_dict(),
        "predecessor_hashes": predecessor_hashes,
        "public_validation_evidence_audit": {
            "schema": public_evidence["schema"],
            "status": public_evidence["status"],
            "sources": public_evidence["evidence_scope"]["sources"],
            "search_is_exhaustive": public_evidence["evidence_scope"][
                "search_is_exhaustive"
            ],
            "admitted_dataset": public_evidence["admission_requirements"][
                "admitted_dataset"
            ],
            "all_assessment_gates_passed": public_evidence[
                "all_gates_passed"
            ],
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "native_junction_law_fully_specified": True,
            "zero_storage_mass_conservation_implemented": True,
            "two_dimensional_directional_ledger_implemented": True,
            "junction_reaction_retained": True,
            "reaction_independently_observed": False,
            "multidimensional_junction_state_solved": False,
            "hec_ras_force_variant_selected": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _terminal(
    branch_id: str,
    *,
    section: TrapezoidalChannelSection,
    bed: float,
    surface: float,
    discharge: float,
) -> DynamicWaveJunctionTerminal:
    return DynamicWaveJunctionTerminal(
        branch_id=branch_id,
        interior_state=DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        section=section,
        bed_elevation_m=bed,
    )


def _manufactured_junction():
    surface = 3.0
    upstream = (
        _terminal(
            "up-a",
            section=TrapezoidalChannelSection(8.0, 1.0),
            bed=0.2,
            surface=surface,
            discharge=3.0,
        ),
        _terminal(
            "up-b",
            section=TrapezoidalChannelSection(6.0, 0.5),
            bed=0.5,
            surface=surface,
            discharge=4.0,
        ),
    )
    downstream = _terminal(
        "down",
        section=TrapezoidalChannelSection(12.0, 2.0),
        bed=0.1,
        surface=surface,
        discharge=7.0,
    )
    contract = ConservativeVectorJunctionContract(
        "manufactured-y",
        ("up-a", "up-b"),
        "down",
        (35.0, 315.0),
        5.0,
        "manufactured:stage13",
    )
    return upstream, downstream, contract


def _lake_at_rest():
    section = TrapezoidalChannelSection(10.0, 2.0)
    upstream = tuple(
        _terminal(
            branch_id,
            section=section,
            bed=0.0,
            surface=2.0,
            discharge=0.0,
        )
        for branch_id in ("up-left", "up-right")
    )
    downstream = _terminal(
        "down",
        section=section,
        bed=0.0,
        surface=2.0,
        discharge=0.0,
    )
    contract = ConservativeVectorJunctionContract(
        "symmetric-lake",
        ("up-left", "up-right"),
        "down",
        (45.0, 315.0),
        0.0,
        "manufactured:lake-at-rest",
    )
    return solve_conservative_vector_junction(
        upstream, downstream, contract
    )


def _network_step():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)

    def reach(reach_id: str, discharge: float) -> DynamicWaveNetworkReach:
        return DynamicWaveNetworkReach(
            reach_id=reach_id,
            state=PrismaticDynamicWaveState(
                (area,) * 4, (discharge,) * 4
            ),
            bed_elevation_m=(0.0,) * 4,
            sections=(section,) * 4,
            cell_length_m=100.0,
            manning_n=(1e-6,) * 4,
            lateral_inflow_m2s=(0.0,) * 4,
        )

    upstream = (reach("up-a", 5.0), reach("up-b", 7.0))
    downstream = reach("down", 12.0)
    left_boundaries = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(area, discharge), 0.0
        )
        for discharge in (5.0, 7.0)
    )
    right_boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, 12.0), 0.0
    )
    contract = ConservativeVectorJunctionContract(
        "network-y",
        ("up-a", "up-b"),
        "down",
        (45.0, 315.0),
        0.0,
        "manufactured:network-step",
    )
    timestep = maximum_subcritical_confluence_stable_timestep_seconds(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        courant_number=0.4,
    )
    return advance_conservative_vector_confluence_network_open(
        upstream,
        downstream,
        contract,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )


def _rotate_vector(
    east: float,
    north: float,
    angle_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
