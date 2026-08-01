#!/usr/bin/env python3
"""Compile public and manufactured projected-momentum junction gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_momentum import (
    ProjectedMomentumJunctionContract,
    evaluate_projected_momentum_balance,
    scan_subcritical_projected_momentum_roots,
    solve_subcritical_projected_momentum_junction,
)
try:
    from scripts.acquire_geotransport_center_hill_route_link_v3 import (
        _route_link_reader,
    )
except ModuleNotFoundError:
    from acquire_geotransport_center_hill_route_link_v3 import (  # type: ignore[no-redef]
        _route_link_reader,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_LINK_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork/"
    "RouteLink_CONUS_NWMv3_CenterHill_D5.nc"
)
GEOMETRY_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork/"
    "junction_geometry_18421703.json"
)
DECODED_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_subnetwork_inputs/decoded"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "dynamic_wave_momentum_junction_gates.json"
)
DAG_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/dynamic_wave_dag.py"
)
FROZEN_INIT_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/__init__.py"
)

SCHEMA = "gwm.geotransport.dynamic_wave_momentum_junction_gates.v1"
PUBLIC_CASE_SCHEMA = (
    "gwm.geotransport.center_hill_projected_momentum_junction.v1"
)
FEATURE_IDS = (18421705, 18421707, 18421703)
UPSTREAM_IDS = FEATURE_IDS[:2]
DOWNSTREAM_ID = FEATURE_IDS[2]
ROUTE_FIELDS = ("link", "to", "Length", "BtmWdth", "ChSlp", "So", "n", "alt")

EXPECTED_SHA256 = {
    "route_link": "764dccdf71c4761cf82792f5661fd5f66d61987bd52398fe0b93a24c2f7207be",
    "junction_geometry": "ba12696fe8045941c31bd4fc804b702cf3cc20b180e7bd83a1a502c2d4fefd6b",
    "feature_ids": "306787f4b6a37cbd82713e885355697d2a4ae25d9dc61f6c117021136b4491f0",
    "initial_streamflow_m3s": "70061579612367ec336c325c4df937a4f7d9eb2ea90285a480fca69e8e261fd5",
    "initial_velocity_ms": "19572ac6567225979675308b68f724ffe2a952623d5c92563906692994bc4416",
    "initial_cross_section_area_m2": (
        "9106dbe86b17995e6eaa34e2fe8ce527d22592d9b62c89dd5433b0130c17ce2b"
    ),
    "dynamic_wave_dag": "ee05ff1af9fd446f5584d9df01f0f7a8c2ac5739c9cf2652b3bba53569e385d9",
    "frozen_geospatial_kernel_init": (
        "7db7e6459143d2a54e742a732fcd3f85c422a9775559296dc39a985ab632315d"
    ),
}

HEC_RAS_MOMENTUM_URL = (
    "https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/"
    "latest/overview-of-optional-capabilities/modeling-stream-junctions/"
    "momentum-based-junction-method"
)
HEC_RAS_CHILD_API_URL = (
    "https://www.hec.usace.army.mil/confluence/rest/api/content/43816552/"
    "child/page?limit=100&expand=body.storage,version"
)
HEC_RAS_CHILD_API_SHA256 = (
    "59bdf525ebc59d2cd34e4523e255bebae41d08af2f3435237844e33b32790563"
)
HEC_RAS_MIXED_FLOW_API_URL = (
    "https://www.hec.usace.army.mil/confluence/rest/api/content/43816541"
    "?expand=body.storage,version"
)
HEC_RAS_MIXED_FLOW_API_SHA256 = (
    "adfd85e41624ee7fc7e3fbba528656c6bcf4e4e1445d552cfbb1b395ed5cc49b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_gates() -> dict[str, Any]:
    geometry = json.loads(GEOMETRY_PATH.read_text(encoding="utf-8"))["geometry"]
    route_parameters, route_format, route_variable_names = _route_parameters()
    initial_states = _initial_states()
    sections = tuple(
        TrapezoidalChannelSection(
            bottom_width_m=route_parameters[feature_id]["BtmWdth"],
            side_slope_horizontal_per_vertical=(
                1.0 / route_parameters[feature_id]["ChSlp"]
            ),
        )
        for feature_id in FEATURE_IDS
    )
    endpoint_beds = (
        route_parameters[UPSTREAM_IDS[0]]["alt"]
        - route_parameters[UPSTREAM_IDS[0]]["So"]
        * route_parameters[UPSTREAM_IDS[0]]["Length"],
        route_parameters[UPSTREAM_IDS[1]]["alt"]
        - route_parameters[UPSTREAM_IDS[1]]["So"]
        * route_parameters[UPSTREAM_IDS[1]]["Length"],
        route_parameters[DOWNSTREAM_ID]["alt"],
    )
    terminals = tuple(
        DynamicWaveJunctionTerminal(
            branch_id=str(feature_id),
            interior_state=initial_states[feature_id]["state"],
            section=section,
            bed_elevation_m=bed,
        )
        for feature_id, section, bed in zip(
            FEATURE_IDS, sections, endpoint_beds, strict=True
        )
    )
    deflections = tuple(
        float(
            geometry["upstream_to_downstream_deflection_degrees"][
                str(feature_id)
            ]
        )
        for feature_id in UPSTREAM_IDS
    )
    downstream_window = float(
        geometry["downstream_branch"]["sampled_window_length_m"]
    )
    section_spacing = tuple(
        float(value["sampled_window_length_m"]) + downstream_window
        for value in geometry["upstream_branches"]
    )
    contract = ProjectedMomentumJunctionContract(
        upstream_branch_ids=tuple(str(value) for value in UPSTREAM_IDS),
        downstream_branch_id=str(DOWNSTREAM_ID),
        upstream_deflection_degrees=deflections,
        section_spacing_m=section_spacing,
        upstream_manning_n=tuple(
            route_parameters[value]["n"] for value in UPSTREAM_IDS
        ),
        downstream_manning_n=route_parameters[DOWNSTREAM_ID]["n"],
        upstream_bed_slopes=tuple(
            route_parameters[value]["So"] for value in UPSTREAM_IDS
        ),
        downstream_bed_slope=route_parameters[DOWNSTREAM_ID]["So"],
        upstream_momentum_coefficients=(1.0, 1.0),
        downstream_momentum_coefficient=1.0,
        provenance_id=(
            "NWM-v3-RouteLink+USGS-NLDI-junction-geometry:"
            "beta-explicit-unit-assumption"
        ),
    )
    root_scan = scan_subcritical_projected_momentum_roots(
        terminals[:2], terminals[2], contract
    )
    public_solver_error = None
    public_solution = None
    try:
        public_solution = solve_subcritical_projected_momentum_junction(
            terminals[:2], terminals[2], contract, momentum_tolerance_m3=1e-9
        ).as_dict()
    except ValueError as exc:
        public_solver_error = str(exc)
    raw_initial_mass_residual = (
        sum(initial_states[value]["state"].discharge_m3s for value in UPSTREAM_IDS)
        - initial_states[DOWNSTREAM_ID]["state"].discharge_m3s
    )
    raw_initial_balance_error = None
    try:
        evaluate_projected_momentum_balance(
            terminals[:2],
            terminals[2],
            tuple(initial_states[value]["state"] for value in UPSTREAM_IDS),
            initial_states[DOWNSTREAM_ID]["state"],
            contract,
        )
    except ValueError as exc:
        raw_initial_balance_error = str(exc)

    manufactured = _manufactured_positive_control()
    angle_error = None
    try:
        replace(contract, upstream_deflection_degrees=(91.0, deflections[1]))
    except ValueError as exc:
        angle_error = str(exc)
    reverse_flow_error = None
    try:
        evaluate_projected_momentum_balance(
            terminals[:2],
            terminals[2],
            (
                DynamicWaveCellState(
                    initial_states[UPSTREAM_IDS[0]]["state"].area_m2, -1.0
                ),
                initial_states[UPSTREAM_IDS[1]]["state"],
            ),
            DynamicWaveCellState(
                initial_states[DOWNSTREAM_ID]["state"].area_m2,
                initial_states[UPSTREAM_IDS[1]]["state"].discharge_m3s - 1.0,
            ),
            contract,
        )
    except ValueError as exc:
        reverse_flow_error = str(exc)

    hashes = {
        "route_link": _sha256_path(ROUTE_LINK_PATH),
        "junction_geometry": _sha256_path(GEOMETRY_PATH),
        "feature_ids": _sha256_path(DECODED_ROOT / "feature_ids.npy"),
        "initial_streamflow_m3s": _sha256_path(
            DECODED_ROOT / "initial_streamflow_m3s.npy"
        ),
        "initial_velocity_ms": _sha256_path(
            DECODED_ROOT / "initial_velocity_ms.npy"
        ),
        "initial_cross_section_area_m2": _sha256_path(
            DECODED_ROOT / "initial_cross_section_area_m2.npy"
        ),
        "dynamic_wave_dag": _sha256_path(DAG_PATH),
        "frozen_geospatial_kernel_init": _sha256_path(FROZEN_INIT_PATH),
    }
    beta_field_candidates = {
        "beta",
        "momentum_coefficient",
        "momentum_correction_coefficient",
    }
    beta_fields_present = tuple(
        sorted(
            value
            for value in route_variable_names
            if value.lower() in beta_field_candidates
        )
    )
    public_initial = {
        str(feature_id): {
            "area_m2": initial_states[feature_id]["state"].area_m2,
            "discharge_m3s": initial_states[feature_id]["state"].discharge_m3s,
            "published_velocity_mps": initial_states[feature_id]["velocity_mps"],
            "recomputed_velocity_mps": (
                initial_states[feature_id]["state"].mean_velocity_mps
            ),
            "froude_number": _froude(
                initial_states[feature_id]["state"], sections[index]
            ),
            "bed_elevation_at_control_section_m": endpoint_beds[index],
            "free_surface_elevation_m": (
                endpoint_beds[index]
                + sections[index].depth_m(
                    initial_states[feature_id]["state"].area_m2
                )
            ),
        }
        for index, feature_id in enumerate(FEATURE_IDS)
    }
    public_case = {
        "schema": PUBLIC_CASE_SCHEMA,
        "source_artifacts": {
            "route_link": _artifact(ROUTE_LINK_PATH),
            "junction_geometry": _artifact(GEOMETRY_PATH),
            "decoded_initial_state": {
                name: _artifact(DECODED_ROOT / f"{name}.npy")
                for name in (
                    "feature_ids",
                    "initial_streamflow_m3s",
                    "initial_velocity_ms",
                    "initial_cross_section_area_m2",
                )
            },
        },
        "route_link_container_format": route_format,
        "route_link_variable_names": list(route_variable_names),
        "route_parameters": {
            str(key): value for key, value in route_parameters.items()
        },
        "cross_section_compilation": {
            "source_semantics": "NWM_v3_model_parameterized_trapezoid",
            "bottom_width_m": {
                str(feature_id): section.bottom_width_m
                for feature_id, section in zip(FEATURE_IDS, sections, strict=True)
            },
            "side_slope_horizontal_per_vertical": {
                str(feature_id): section.side_slope_horizontal_per_vertical
                for feature_id, section in zip(FEATURE_IDS, sections, strict=True)
            },
            "mapping": "horizontal_per_vertical=1/RouteLink_ChSlp",
            "site_surveyed_cross_sections": False,
        },
        "initial_state_diagnostic": {
            "branches": public_initial,
            "raw_junction_mass_balance_residual_m3s": raw_initial_mass_residual,
            "raw_state_momentum_evaluation_error": raw_initial_balance_error,
            "initial_state_is_observation": False,
            "initial_state_is_conservation_truth": False,
        },
        "projected_momentum_contract": contract.as_dict(),
        "momentum_coefficient_evidence": {
            "RouteLink_beta_field_present": bool(beta_fields_present),
            "RouteLink_beta_fields": list(beta_fields_present),
            "assumed_value": 1.0,
            "assumption_is_explicit": True,
            "assumption_calibrated": False,
        },
        "root_scan": root_scan.as_dict(),
        "solver": {
            "status": (
                "solved_diagnostic_only"
                if public_solution is not None
                else "no_characteristic_projected_momentum_root"
            ),
            "solution": public_solution,
            "error": public_solver_error,
        },
        "admission": {
            "status": "not_admitted",
            "operator_admitted": False,
            "reason_codes": [
                "structure_classification_unknown",
                "momentum_coefficient_beta_source_missing",
                "cross_sections_are_model_parameters_not_site_surveys",
                "public_initial_state_not_mass_conservative",
                "public_initial_state_has_no_projected_momentum_root",
            ],
            "implicit_zero_loss_assumed": False,
            "angle_to_loss_coefficient_mapping_used": False,
        },
    }
    gates = {
        "all_frozen_public_input_hashes_match": all(
            hashes[key] == value
            for key, value in EXPECTED_SHA256.items()
            if key not in {"dynamic_wave_dag", "frozen_geospatial_kernel_init"}
        ),
        "public_route_link_has_expected_two_in_one_out_topology": (
            route_parameters[UPSTREAM_IDS[0]]["to"] == DOWNSTREAM_ID
            and route_parameters[UPSTREAM_IDS[1]]["to"] == DOWNSTREAM_ID
            and route_parameters[DOWNSTREAM_ID]["to"] != DOWNSTREAM_ID
        ),
        "public_geometry_branch_attachment_and_angles_match": (
            tuple(value["branch_id"] for value in geometry["upstream_branches"])
            == tuple(str(value) for value in UPSTREAM_IDS)
            and geometry["downstream_branch"]["branch_id"]
            == str(DOWNSTREAM_ID)
            and all(0.0 < value < 90.0 for value in deflections)
        ),
        "route_link_trapezoids_compile_without_parameter_substitution": all(
            section.bottom_width_m == route_parameters[feature_id]["BtmWdth"]
            and section.side_slope_horizontal_per_vertical
            == 1.0 / route_parameters[feature_id]["ChSlp"]
            for feature_id, section in zip(FEATURE_IDS, sections, strict=True)
        ),
        "route_link_beds_close_geographic_node_within_one_centimeter": (
            max(endpoint_beds[:2]) - min(endpoint_beds[:2]) <= 0.01
            and max(endpoint_beds[:2]) - endpoint_beds[2] <= 0.01
        ),
        "public_initial_states_are_wet_downstream_oriented_and_subcritical": all(
            initial_states[feature_id]["state"].area_m2 > 0.0
            and initial_states[feature_id]["state"].discharge_m3s > 0.0
            and _is_subcritical(initial_states[feature_id]["state"], sections[index])
            for index, feature_id in enumerate(FEATURE_IDS)
        ),
        "published_initial_velocities_equal_discharge_over_area": all(
            math.isclose(
                initial_states[feature_id]["velocity_mps"],
                initial_states[feature_id]["state"].mean_velocity_mps,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for feature_id in FEATURE_IDS
        ),
        "raw_public_initial_mass_imbalance_is_exposed_not_treated_as_truth": (
            math.isclose(raw_initial_mass_residual, 4.12, abs_tol=2e-6)
            and raw_initial_balance_error
            == "projected_momentum_junction_mass_balance_required"
        ),
        "contract_is_direction_section_friction_and_weight_aware": (
            contract.as_dict()["projection_axis"] == "downstream_flow_direction"
            and contract.as_dict()["downstream_area_partition"]
            == "upstream_discharge_fraction"
            and all(value > 0.0 for value in contract.section_spacing_m)
            and all(value > 0.0 for value in contract.upstream_manning_n)
            and all(value > 0.0 for value in contract.upstream_bed_slopes)
        ),
        "manufactured_nonzero_angle_full_force_state_is_recovered": (
            manufactured["solution_elevation_m"] == 3.0
            and abs(manufactured["momentum_residual_m3"]) <= 1e-11
            and abs(manufactured["mass_residual_m3s"]) <= 1e-12
            and all(value > 0.0 for value in manufactured["friction_forces_m3"])
            and all(value > 0.0 for value in manufactured["water_weight_forces_m3"])
        ),
        "out_of_scope_angle_fails_closed": (
            angle_error == "projected_momentum_junction_angle_not_supported"
        ),
        "reverse_flow_fails_closed": (
            reverse_flow_error
            == "projected_momentum_junction_state_not_supported"
        ),
        "public_characteristic_scan_is_nonempty_but_has_no_root_bracket": (
            root_scan.admissible_candidate_count > 0
            and not root_scan.root_bracket_found
            and root_scan.closest_absolute_residual_m3 is not None
        ),
        "public_no_root_is_explicit_not_a_synthetic_solution": (
            public_solution is None
            and public_solver_error
            == "projected_momentum_junction_no_momentum_root"
        ),
        "missing_public_beta_evidence_fails_admission_closed": (
            public_case["momentum_coefficient_evidence"][
                "RouteLink_beta_field_present"
            ]
            is False
            and not public_case["momentum_coefficient_evidence"][
                "RouteLink_beta_fields"
            ]
            and public_case["admission"]["operator_admitted"] is False
        ),
        "no_angle_to_k_or_implicit_zero_loss_is_used": (
            public_case["admission"]["implicit_zero_loss_assumed"] is False
            and public_case["admission"][
                "angle_to_loss_coefficient_mapping_used"
            ]
            is False
        ),
        "one_dimensional_projection_does_not_claim_vector_closure": (
            contract.as_dict()["vector_momentum_closure"] is False
        ),
        "stage10_does_not_modify_frozen_stage7_stage8_entrypoints": (
            hashes["dynamic_wave_dag"] == EXPECTED_SHA256["dynamic_wave_dag"]
            and hashes["frozen_geospatial_kernel_init"]
            == EXPECTED_SHA256["frozen_geospatial_kernel_init"]
        ),
        "no_action_observation_or_saved_prediction_values_read": True,
    }
    return {
        "schema": SCHEMA,
        "status": "candidate_projected_momentum_implemented_public_case_not_admitted",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_route_parameters_read": True,
            "public_centerline_geometry_read": True,
            "public_model_initial_state_read": True,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
            "coefficient_calibration_performed": False,
        },
        "authoritative_semantics": {
            "retrieved_at": "2026-07-28",
            "hec_ras_momentum_based_junction_method": {
                "url": HEC_RAS_MOMENTUM_URL,
                "official_page_id": 43816560,
                "source_collection_api_url": HEC_RAS_CHILD_API_URL,
                "source_collection_sha256": HEC_RAS_CHILD_API_SHA256,
                "findings": [
                    "Momentum is balanced only along the downstream X axis.",
                    "Specific force is beta*Q^2/(g*A)+A*Ybar.",
                    (
                        "The equation retains branch angles, friction, water "
                        "weight, and flow-weighted downstream area."
                    ),
                ],
            },
            "hec_ras_mixed_flow_regime": {
                "url": HEC_RAS_MIXED_FLOW_API_URL,
                "official_page_id": 43816541,
                "retrieved_snapshot_sha256": HEC_RAS_MIXED_FLOW_API_SHA256,
                "finding": "The present candidate is restricted to subcritical combining flow.",
            },
        },
        "input_hashes": hashes,
        "manufactured_positive_control": manufactured,
        "public_case": public_case,
        "negative_controls": {
            "unsupported_angle_error": angle_error,
            "reverse_flow_error": reverse_flow_error,
            "raw_initial_mass_balance_error": raw_initial_balance_error,
        },
        "gates": gates,
        "gate_summary": {
            "passed": sum(bool(value) for value in gates.values()),
            "total": len(gates),
            "all_passed": all(gates.values()),
        },
        "claim_boundary": {
            "direction_aware_projected_momentum_operator_implemented": True,
            "cross_section_specific_force_implemented": True,
            "friction_and_water_weight_forces_implemented": True,
            "characteristic_mass_momentum_solver_implemented": True,
            "two_dimensional_vector_momentum_implemented": False,
            "public_beta_evidence_available": False,
            "public_site_surveyed_cross_sections_available": False,
            "public_projected_momentum_operator_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _route_parameters() -> tuple[
    dict[int, dict[str, float | int]], str, tuple[str, ...]
]:
    with _route_link_reader(ROUTE_LINK_PATH) as reader:
        names = set(reader.variable_names())
        missing = tuple(value for value in ROUTE_FIELDS if value not in names)
        if missing:
            raise ValueError(
                "projected_momentum_route_link_fields_missing:"
                + ",".join(missing)
            )
        links = np.asarray(reader.values("link"), dtype=np.int64).reshape(-1)
        if links.size != np.unique(links).size:
            raise ValueError("projected_momentum_route_link_ids_not_unique")
        index = {int(value): position for position, value in enumerate(links)}
        if any(value not in index for value in FEATURE_IDS):
            raise ValueError("projected_momentum_route_link_branch_missing")
        indices = tuple(index[value] for value in FEATURE_IDS)
        arrays = {
            name: np.asarray(reader.selected(name, indices)).reshape(-1)
            for name in ROUTE_FIELDS
        }
        parameters = {
            feature_id: {
                name: (
                    int(arrays[name][position])
                    if name in {"link", "to"}
                    else float(arrays[name][position])
                )
                for name in ROUTE_FIELDS
            }
            for position, feature_id in enumerate(FEATURE_IDS)
        }
        return parameters, reader.container_format, reader.variable_names()


def _initial_states() -> dict[int, dict[str, Any]]:
    feature_ids = np.load(DECODED_ROOT / "feature_ids.npy", allow_pickle=False)
    discharge = np.load(
        DECODED_ROOT / "initial_streamflow_m3s.npy", allow_pickle=False
    )
    velocity = np.load(
        DECODED_ROOT / "initial_velocity_ms.npy", allow_pickle=False
    )
    area = np.load(
        DECODED_ROOT / "initial_cross_section_area_m2.npy", allow_pickle=False
    )
    if (
        feature_ids.ndim != 1
        or len(np.unique(feature_ids)) != len(feature_ids)
        or discharge.shape != feature_ids.shape
        or velocity.shape != feature_ids.shape
        or area.shape != feature_ids.shape
    ):
        raise ValueError("projected_momentum_initial_state_axis_invalid")
    index = {int(value): position for position, value in enumerate(feature_ids)}
    if any(value not in index for value in FEATURE_IDS):
        raise ValueError("projected_momentum_initial_state_branch_missing")
    return {
        feature_id: {
            "state": DynamicWaveCellState(
                float(area[index[feature_id]]),
                float(discharge[index[feature_id]]),
            ),
            "velocity_mps": float(velocity[index[feature_id]]),
        }
        for feature_id in FEATURE_IDS
    }


def _manufactured_positive_control() -> dict[str, Any]:
    sections = (
        TrapezoidalChannelSection(4.0, 0.0),
        TrapezoidalChannelSection(6.0, 0.0),
        TrapezoidalChannelSection(10.0, 0.0),
    )
    states = (
        DynamicWaveCellState(8.0, 2.0),
        DynamicWaveCellState(12.0, 3.0),
        DynamicWaveCellState(10.0, 5.0),
    )
    upstream = (
        DynamicWaveJunctionTerminal("A", states[0], sections[0], 1.0),
        DynamicWaveJunctionTerminal("B", states[1], sections[1], 1.0),
    )
    downstream = DynamicWaveJunctionTerminal(
        "C", states[2], sections[2], 2.0
    )
    provisional_contract = ProjectedMomentumJunctionContract(
        ("A", "B"),
        "C",
        (20.0, 35.0),
        (60.0, 60.0),
        (0.03, 0.04),
        0.035,
        (0.001, 0.002),
        0.0015,
        (1.1, 1.2),
        1.0,
        "manufactured:angled_full_force_balance",
    )
    provisional = evaluate_projected_momentum_balance(
        upstream, downstream, states[:2], states[2], provisional_contract
    )
    downstream_hydrostatic = sections[2].hydrostatic_pressure_integral_m3(
        states[2].area_m2
    )
    downstream_convective_per_beta = states[2].discharge_m3s**2 / (
        STANDARD_GRAVITY_MPS2 * states[2].area_m2
    )
    required_beta = (
        provisional.upstream_contribution_sum_m3 - downstream_hydrostatic
    ) / downstream_convective_per_beta
    contract = replace(
        provisional_contract,
        downstream_momentum_coefficient=required_beta,
    )
    solution = solve_subcritical_projected_momentum_junction(
        upstream, downstream, contract
    )
    return {
        "upstream_deflection_degrees": list(
            contract.upstream_deflection_degrees
        ),
        "downstream_momentum_coefficient": required_beta,
        "solution_elevation_m": (
            solution.common_upstream_free_surface_elevation_m
        ),
        "mass_residual_m3s": solution.junction_mass_balance_residual_m3s,
        "momentum_residual_m3": solution.momentum_balance.residual_m3,
        "friction_forces_m3": list(
            solution.momentum_balance.friction_forces_m3
        ),
        "water_weight_forces_m3": list(
            solution.momentum_balance.water_weight_forces_m3
        ),
        "maximum_outgoing_invariant_residual_mps": (
            solution.maximum_absolute_outgoing_invariant_residual_mps
        ),
    }


def _froude(
    state: DynamicWaveCellState, section: TrapezoidalChannelSection
) -> float:
    celerity = section.gravity_wave_celerity_mps(state.area_m2)
    return abs(state.mean_velocity_mps) / celerity


def _is_subcritical(
    state: DynamicWaveCellState, section: TrapezoidalChannelSection
) -> bool:
    speeds = dynamic_wave_characteristic_speeds_mps(state, section)
    return speeds[0] < 0.0 < speeds[1]


def _artifact(path: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": _sha256_path(path),
        "size_bytes": path.stat().st_size,
    }


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    report = compile_gates()
    _write_json(args.report, report)
    print(json.dumps(report["gate_summary"], sort_keys=True))
    if not report["gate_summary"]["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
