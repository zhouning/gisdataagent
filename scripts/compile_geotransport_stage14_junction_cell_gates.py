#!/usr/bin/env python3
"""Compile Stage 14 finite-area shallow-water junction-cell gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    solve_conservative_vector_junction,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
)
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_cell import (
    JunctionCellBoundaryFace,
    ShallowWaterJunctionCellGeometry,
    ShallowWaterJunctionCellState,
    advance_shallow_water_junction_cell,
    maximum_shallow_water_junction_cell_timestep_seconds,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage14_shallow_water_junction_cell_gates.json"
)
SCHEMA = "gwm.geotransport.stage14_shallow_water_junction_cell_gates.v1"
MASS_TOLERANCE_M3 = 1e-12
MOMENTUM_TOLERANCE_M4S = 1e-12
ROTATION_DEGREES = 37.0
COURANT_NUMBER = 0.4
MULTISTEP_COUNT = 25

FROZEN_STAGE13_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/conservative_vector_junction.py": (
        "d2616ce17813a6aa09af8612dda036814fc6b5439062131bae9718a50541c6c3"
    ),
    "data_agent/test_geospatial_kernel_conservative_vector_junction.py": (
        "c691bb59468575f2b96aa6080fefadc72bb07f651d0287b0e4c94382995644ca"
    ),
    "data_agent/test_acquire_geotransport_stage13_confluence_evidence.py": (
        "69b24f875e3792c336a40d39080048b257a32d842aa5f1b7d634e9fb1e3495b3"
    ),
    "data_agent/test_assess_geotransport_stage13_confluence_evidence.py": (
        "a6cba6eb996354bf9082dd033c30e463437c1ccbf3e5fd607f5c5a23f89361a9"
    ),
    "scripts/acquire_geotransport_stage13_confluence_evidence.py": (
        "c19e8e339b3a8233a756939899bf70dd618c478f3b4d1ee53ca06f4b373bda70"
    ),
    "scripts/assess_geotransport_stage13_confluence_evidence.py": (
        "d764a1ededcae4ca280fb3e4c3902c1f175ba3763956860cba5d82c3171e36c3"
    ),
    "scripts/compile_geotransport_stage13_vector_junction_gates.py": (
        "ed8dbf57446b6db16bfe033e01d92424fecdffdb9825e8e3d409e8534193182c"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage13_conservative_vector_junction_gates.json"
    ): (
        "1defe9c20a265b4989a761b832e41136fac6a2535943e0d6ac13c7d4a58c6032"
    ),
    (
        "benchmarks/geotransport_v0_1/"
        "stage13_confluence_evidence_assessment.json"
    ): (
        "4fa9bb2965094d0803def2fd3c158d7a6c67b721991b93c20e94ac0f21fcc50c"
    ),
    (
        "docs/architecture-decisions/"
        "adr-054-native-conservative-vector-junction.md"
    ): (
        "825c67539810fb17944b8920de48ae2dd04feb39d158afb3ffbaafaee1053b2d"
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
    geometry = _geometry()
    upstream, downstream, junction = _junction()
    initial = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        initial,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    baseline = advance_shallow_water_junction_cell(
        initial,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=COURANT_NUMBER,
    )

    lake_upstream, lake_downstream, lake_junction = _junction(
        discharges=(0.0, 0.0, 0.0)
    )
    lake_stable = maximum_shallow_water_junction_cell_timestep_seconds(
        initial,
        geometry,
        lake_upstream,
        lake_downstream,
        lake_junction,
        courant_number=COURANT_NUMBER,
    )
    lake = advance_shallow_water_junction_cell(
        initial,
        geometry,
        lake_upstream,
        lake_downstream,
        lake_junction,
        timestep_seconds=lake_stable,
        maximum_courant_number=COURANT_NUMBER,
    )

    rotated_geometry = _geometry(rotation_degrees=ROTATION_DEGREES)
    rotated_upstream, rotated_downstream, rotated_junction = _junction(
        rotation_degrees=ROTATION_DEGREES
    )
    rotated_stable = maximum_shallow_water_junction_cell_timestep_seconds(
        initial,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        courant_number=COURANT_NUMBER,
    )
    rotation_timestep = 0.5 * min(stable, rotated_stable)
    rotation_baseline = advance_shallow_water_junction_cell(
        initial,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=rotation_timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_shallow_water_junction_cell(
        initial,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        timestep_seconds=rotation_timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    expected_rotated_momentum = _rotate_vector(
        rotation_baseline.state_after.momentum_east_m4s,
        rotation_baseline.state_after.momentum_north_m4s,
        ROTATION_DEGREES,
    )
    rotation_error = (
        rotated.state_after.momentum_east_m4s
        - expected_rotated_momentum[0],
        rotated.state_after.momentum_north_m4s
        - expected_rotated_momentum[1],
    )

    multistep = _run_multistep()
    refusals = _run_refusals()
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE13_HASHES.items()
    }
    stage13_frozen = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_hashes.values()
    )
    closure = geometry.closure_residual_east_north_m
    gates = {
        "stage13_artifacts_hash_frozen": stage13_frozen,
        "oriented_boundary_measure_closed": (
            math.hypot(*closure) <= 1e-12
        ),
        "finite_area_and_storage_state_present": (
            geometry.plan_area_m2 > 0.0
            and baseline.state_before.volume_m3 > 0.0
        ),
        "single_step_mass_ledger_closed": (
            abs(baseline.mass_ledger_error_m3) <= MASS_TOLERANCE_M3
        ),
        "single_step_east_momentum_ledger_closed": (
            abs(baseline.momentum_ledger_error_east_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "single_step_north_momentum_ledger_closed": (
            abs(baseline.momentum_ledger_error_north_m4s)
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "hll_exchange_updates_cell_state": (
            baseline.state_after != baseline.state_before
        ),
        "cell_remains_positive_and_finite": (
            baseline.state_after.volume_m3 > 0.0
            and math.isfinite(baseline.state_after.momentum_east_m4s)
            and math.isfinite(baseline.state_after.momentum_north_m4s)
        ),
        "lake_at_rest_mass_identity": (
            abs(lake.state_after.volume_m3 - lake.state_before.volume_m3)
            <= MASS_TOLERANCE_M3
        ),
        "lake_at_rest_momentum_identity": (
            math.hypot(
                lake.state_after.momentum_east_m4s,
                lake.state_after.momentum_north_m4s,
            )
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "rotation_preserves_mass_exchange": (
            abs(
                rotated.net_outward_opening_mass_flux_m3s
                - rotation_baseline.net_outward_opening_mass_flux_m3s
            )
            <= 1e-12
        ),
        "rotation_covaries_two_component_momentum": (
            math.hypot(*rotation_error) <= MOMENTUM_TOLERANCE_M4S
        ),
        "multistep_cell_state_remains_positive": (
            multistep["minimum_volume_m3"] > 0.0
        ),
        "multistep_ledgers_close": (
            multistep["maximum_mass_ledger_error_m3"]
            <= MASS_TOLERANCE_M3
            and multistep["maximum_momentum_ledger_error_m4s"]
            <= MOMENTUM_TOLERANCE_M4S
        ),
        "cell_state_changes_subsequent_hll_exchange": (
            abs(
                multistep["last_opening_mass_flux_m3s"]
                - multistep["first_opening_mass_flux_m3s"]
            )
            > 1e-8
        ),
        "unsupported_contracts_fail_closed": all(refusals.values()),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "explicit_2d_junction_cell_manufactured_invariants_pass_"
            "coupled_reach_update_and_public_validation_pending"
        ),
        "law": {
            "cell_state": [
                "water_volume_m3",
                "integrated_east_momentum_m4s",
                "integrated_north_momentum_m4s",
            ],
            "opening_flux": "rotated_two_dimensional_shallow_water_HLL",
            "solid_wall_flux": "hydrostatic_reflective_slip_pressure",
            "boundary_closure": "sum(face_length*unit_outward_normal)=0",
            "fitted_parameters": [],
        },
        "baseline_step": baseline.as_dict(),
        "lake_at_rest": lake.as_dict(),
        "rotation_control": {
            "rotation_degrees": ROTATION_DEGREES,
            "expected_momentum_after_east_north_m4s": list(
                expected_rotated_momentum
            ),
            "actual_momentum_after_east_north_m4s": [
                rotated.state_after.momentum_east_m4s,
                rotated.state_after.momentum_north_m4s,
            ],
            "error_east_north_m4s": list(rotation_error),
            "mass_flux_error_m3s": (
                rotated.net_outward_opening_mass_flux_m3s
                - rotation_baseline.net_outward_opening_mass_flux_m3s
            ),
        },
        "multistep_control": multistep,
        "typed_refusals": refusals,
        "frozen_stage13_hashes": frozen_hashes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "finite_area_junction_cell_implemented": True,
            "finite_storage_state_implemented": True,
            "two_component_junction_momentum_state_implemented": True,
            "cell_to_branch_hll_flux_implemented": True,
            "solid_wall_pressure_flux_implemented": True,
            "stage13_inferred_reaction_used": False,
            "single_uniform_junction_cell_only": True,
            "branch_reach_states_updated_conservatively": False,
            "polygon_vertex_topology_verified": False,
            "variable_bed_or_irregular_openings_supported": False,
            "public_confluence_validation_completed": False,
            "candidate_operator_admitted": False,
        },
    }


def _run_multistep() -> dict[str, Any]:
    geometry = _geometry()
    upstream, downstream, junction = _junction()
    state = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    initial = state
    mass_fluxes = []
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    minimum_volume = state.volume_m3
    elapsed = 0.0
    for _ in range(MULTISTEP_COUNT):
        stable = maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=COURANT_NUMBER,
        )
        step = advance_shallow_water_junction_cell(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=0.5 * stable,
            maximum_courant_number=COURANT_NUMBER,
        )
        state = step.state_after
        elapsed += step.timestep_seconds
        mass_fluxes.append(step.net_outward_opening_mass_flux_m3s)
        maximum_mass_error = max(
            maximum_mass_error, abs(step.mass_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            step.momentum_ledger_error_magnitude_m4s,
        )
        minimum_volume = min(minimum_volume, state.volume_m3)
    return {
        "step_count": MULTISTEP_COUNT,
        "elapsed_seconds": elapsed,
        "initial_state": initial.as_dict(geometry),
        "final_state": state.as_dict(geometry),
        "minimum_volume_m3": minimum_volume,
        "first_opening_mass_flux_m3s": mass_fluxes[0],
        "last_opening_mass_flux_m3s": mass_fluxes[-1],
        "maximum_mass_ledger_error_m3": maximum_mass_error,
        "maximum_momentum_ledger_error_m4s": maximum_momentum_error,
    }


def _run_refusals() -> dict[str, bool]:
    geometry = _geometry()
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    upstream, downstream, junction = _junction()
    results = {}
    try:
        replace(
            geometry,
            faces=(
                *geometry.faces[:-1],
                replace(geometry.faces[-1], length_m=16.0),
            ),
        )
    except ValueError as exc:
        results["nonclosed_geometry"] = str(exc) == (
            "shallow_water_junction_cell_boundary_not_closed"
        )
    else:
        results["nonclosed_geometry"] = False

    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    try:
        advance_shallow_water_junction_cell(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["cfl_exceeded"] = str(exc) == (
            "shallow_water_junction_cell_cfl_exceeded"
        )
    else:
        results["cfl_exceeded"] = False

    trapezoidal = (
        TrapezoidalChannelSection(10.0, 1.0),
        TrapezoidalChannelSection(10.0, 0.0),
    )
    invalid_upstream, invalid_downstream, invalid_junction = _junction(
        upstream_sections=trapezoidal
    )
    try:
        maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            invalid_upstream,
            invalid_downstream,
            invalid_junction,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["trapezoidal_opening"] = str(exc) == (
            "shallow_water_junction_cell_rectangular_opening_required"
        )
    else:
        results["trapezoidal_opening"] = False

    invalid_upstream, invalid_downstream, invalid_junction = _junction(
        upstream_beds=(0.1, 0.0)
    )
    try:
        maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            invalid_upstream,
            invalid_downstream,
            invalid_junction,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        results["bed_step"] = str(exc) == (
            "shallow_water_junction_cell_flat_bed_required"
        )
    else:
        results["bed_step"] = False
    return results


def _geometry(*, rotation_degrees: float = 0.0):
    width = 10.0

    def azimuth(value: float) -> float:
        return (value + rotation_degrees) % 360.0

    return ShallowWaterJunctionCellGeometry(
        "junction-y",
        100.0,
        0.0,
        (
            JunctionCellBoundaryFace(
                "opening-a",
                "branch_opening",
                width,
                azimuth(225.0),
                "up-a",
                "upstream",
            ),
            JunctionCellBoundaryFace(
                "opening-b",
                "branch_opening",
                width,
                azimuth(135.0),
                "up-b",
                "upstream",
            ),
            JunctionCellBoundaryFace(
                "opening-down",
                "branch_opening",
                width,
                azimuth(0.0),
                "down",
                "downstream",
            ),
            JunctionCellBoundaryFace(
                "wall-north",
                "solid_wall",
                width * (math.sqrt(2.0) - 1.0),
                azimuth(0.0),
            ),
            JunctionCellBoundaryFace(
                "wall-east", "solid_wall", 15.0, azimuth(90.0)
            ),
            JunctionCellBoundaryFace(
                "wall-west", "solid_wall", 15.0, azimuth(270.0)
            ),
        ),
        "manufactured:closed-y-cell",
    )


def _junction(
    *,
    discharges: tuple[float, float, float] = (5.0, 7.0, 12.0),
    rotation_degrees: float = 0.0,
    upstream_sections: tuple[
        TrapezoidalChannelSection, TrapezoidalChannelSection
    ]
    | None = None,
    upstream_beds: tuple[float, float] = (0.0, 0.0),
):
    surface = 2.0
    if upstream_sections is None:
        upstream_sections = (
            TrapezoidalChannelSection(10.0, 0.0),
            TrapezoidalChannelSection(10.0, 0.0),
        )
    upstream = tuple(
        _terminal(
            branch_id,
            section=section,
            bed=bed,
            surface=surface,
            discharge=discharge,
        )
        for branch_id, section, bed, discharge in zip(
            ("up-a", "up-b"),
            upstream_sections,
            upstream_beds,
            discharges[:2],
            strict=True,
        )
    )
    downstream = _terminal(
        "down",
        section=TrapezoidalChannelSection(10.0, 0.0),
        bed=0.0,
        surface=surface,
        discharge=discharges[2],
    )
    contract = ConservativeVectorJunctionContract(
        "junction-y",
        ("up-a", "up-b"),
        "down",
        tuple(
            (value + rotation_degrees) % 360.0
            for value in (45.0, 315.0)
        ),
        rotation_degrees % 360.0,
        "manufactured:stage14",
    )
    return (
        upstream,
        downstream,
        solve_conservative_vector_junction(upstream, downstream, contract),
    )


def _terminal(
    branch_id: str,
    *,
    section: TrapezoidalChannelSection,
    bed: float,
    surface: float,
    discharge: float,
) -> DynamicWaveJunctionTerminal:
    return DynamicWaveJunctionTerminal(
        branch_id,
        DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        section,
        bed,
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
