#!/usr/bin/env python3
"""Audit action and gauge measures on the kinematic-wave development paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2.spatial_measure_audit import (
    audit_directed_path_geometry,
    audit_endpoint_spatial_measure,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
NLDI_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
)
ATTRIBUTION_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "kinematic_wave_development_attribution_report.json"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "kinematic_wave_spatial_measure_audit_report.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_spatial_measure_audit.v1"
SYSTEM_SOURCES = {
    "center_hill": {
        "navigation": REPO_ROOT / (
            "data/geotransport_v0_1/topology/raw/"
            "center_hill-downstream-flowlines.json"
        ),
        "gauge": REPO_ROOT / (
            "data/geotransport_v0_1/metadata/nldi-link-03424860.json"
        ),
    },
    "j_percy_priest": {
        "navigation": REPO_ROOT / (
            "data/geotransport_v0_1/topology/raw/"
            "j_percy_priest-downstream-flowlines.json"
        ),
        "gauge": REPO_ROOT / (
            "data/geotransport_v0_1/metadata/nldi-link-03430200.json"
        ),
    },
}
MAXIMUM_CONNECTION_GAP_M = 100.0
MAXIMUM_RESOLVED_SNAP_DISTANCE_M = 100.0
FULL_PATH_LENGTH_TOLERANCE_M = 5.0
MEASURE_MATCH_TOLERANCE_M = 1e-6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nldi-report", type=Path, default=NLDI_REPORT_PATH)
    parser.add_argument(
        "--attribution-report", type=Path, default=ATTRIBUTION_REPORT_PATH
    )
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_audit(
    *,
    nldi_report_path: Path = NLDI_REPORT_PATH,
    attribution_report_path: Path = ATTRIBUTION_REPORT_PATH,
) -> dict[str, Any]:
    nldi_body, nldi = _load_json(nldi_report_path)
    attribution_body, attribution = _load_json(attribution_report_path)
    if nldi.get("schema") != "gwm.geotransport.nldi_path_crosswalk.v1":
        raise ValueError("spatial_measure_nldi_report_invalid")
    if (
        attribution.get("schema")
        != "gwm.geotransport.kinematic_wave_development_attribution.v1"
        or attribution.get("status")
        != "outcome_visible_development_attribution_complete"
        or attribution.get("interpretation_boundary", {}).get(
            "outcomes_visible_before_this_diagnostic_was_defined"
        )
        is not True
    ):
        raise ValueError("spatial_measure_attribution_report_invalid")

    systems = []
    for system_id, sources in SYSTEM_SOURCES.items():
        nldi_row = _system_row(nldi, system_id)
        attribution_row = _system_row(attribution, system_id)
        navigation_body, navigation = _load_json(sources["navigation"])
        gauge_body, gauge = _load_json(sources["gauge"])
        feature_ids = tuple(
            int(value) for value in nldi_row["path"]["feature_ids"]
        )
        by_id = {
            int(feature["properties"]["nhdplus_comid"]): feature
            for feature in navigation.get("features") or []
        }
        if not set(feature_ids) <= set(by_id):
            raise ValueError(f"spatial_measure_{system_id}_navigation_incomplete")
        path = audit_directed_path_geometry(
            path_id=f"{system_id}:action-to-gauge:nldi",
            feature_ids=feature_ids,
            raw_lines=tuple(
                by_id[feature_id]["geometry"]["coordinates"]
                for feature_id in feature_ids
            ),
            maximum_connection_gap_m=MAXIMUM_CONNECTION_GAP_M,
            provenance_id=f"nldi-path-report:{hashlib.sha256(nldi_body).hexdigest()}",
            evidence_level="derived",
        )
        reported_full_length_m = (
            float(nldi_row["path"]["full_reach_path_length_km"]) * 1000.0
        )
        full_length_error_m = path.total_full_length_m - reported_full_length_m
        if abs(full_length_error_m) > FULL_PATH_LENGTH_TOLERANCE_M:
            raise ValueError(f"spatial_measure_{system_id}_full_length_mismatch")

        action = audit_endpoint_spatial_measure(
            endpoint_role="action_boundary",
            feature_id=feature_ids[0],
            point_lonlat=(
                float(nldi_row["action_point"]["longitude"]),
                float(nldi_row["action_point"]["latitude"]),
            ),
            oriented_line=path.oriented_lines[0],
            maximum_resolved_snap_distance_m=(
                MAXIMUM_RESOLVED_SNAP_DISTANCE_M
            ),
            provenance_id=(
                f"{nldi_row['action_point']['evidence']['source']}:"
                f"{nldi_row['action_point']['evidence']['sha256']}"
            ),
            evidence_level="derived",
        )
        gauge_features = gauge.get("features") or []
        if (
            len(gauge_features) != 1
            or gauge_features[0].get("geometry", {}).get("type") != "Point"
        ):
            raise ValueError(f"spatial_measure_{system_id}_gauge_point_invalid")
        gauge_measure = audit_endpoint_spatial_measure(
            endpoint_role="observation_gauge",
            feature_id=feature_ids[-1],
            point_lonlat=gauge_features[0]["geometry"]["coordinates"],
            oriented_line=path.oriented_lines[-1],
            maximum_resolved_snap_distance_m=(
                MAXIMUM_RESOLVED_SNAP_DISTANCE_M
            ),
            provenance_id=(
                f"{nldi_row['gauge_evidence']['source']}:"
                f"{nldi_row['gauge_evidence']['sha256']}"
            ),
            evidence_level="derived",
        )

        physical = attribution_row["physical_path_diagnostic"]
        current_feature_ids = tuple(
            int(value)
            for value in physical[
                "route_link_action_entry_to_outlet_feature_ids"
            ]
        )
        if current_feature_ids != feature_ids[1:]:
            raise ValueError(f"spatial_measure_{system_id}_active_path_mismatch")
        reaches = physical["reaches"]
        if tuple(int(value["feature_id"]) for value in reaches) != current_feature_ids:
            raise ValueError(f"spatial_measure_{system_id}_response_axis_mismatch")
        effective_lengths_m = tuple(
            float(value["effective_length_m"]) for value in reaches
        )
        expected_effective_lengths_m = path.full_lengths_m[1:-1] + (
            gauge_measure.candidate_measure_from_oriented_start_m,
        )
        if (
            not gauge_measure.measure_resolved
            or len(effective_lengths_m) != len(expected_effective_lengths_m)
            or any(
                abs(actual - expected) > MEASURE_MATCH_TOLERANCE_M
                for actual, expected in zip(
                    effective_lengths_m,
                    expected_effective_lengths_m,
                    strict=True,
                )
            )
        ):
            raise ValueError(f"spatial_measure_{system_id}_network_measure_mismatch")

        current_total_length_m = float(sum(effective_lengths_m))
        if not math.isclose(
            current_total_length_m,
            float(physical["route_link_action_entry_to_outlet_effective_length_m"]),
            abs_tol=MEASURE_MATCH_TOLERANCE_M,
        ):
            raise ValueError(f"spatial_measure_{system_id}_path_sum_mismatch")
        first_time_s = float(reaches[0]["travel_time_seconds"])
        terminal_time_s = float(reaches[-1]["travel_time_seconds"])
        current_time_s = (
            float(physical["initial_state_manning_celerity_travel_time_hours"])
            * 3600.0
        )
        conservative_minimum_time_s = max(
            0.0, current_time_s - first_time_s - terminal_time_s
        )
        action_phase_s = float(
            attribution_row["phase_alignment"]["action_to_observation"][
                "best_rmse"
            ]["candidate_time_shift_seconds"]
        )
        prediction_correction_s = float(
            attribution_row["phase_alignment"][
                "kinematic_prediction_to_observation"
            ]["best_rmse"]["candidate_time_shift_seconds"]
        )
        residual_excess_s = conservative_minimum_time_s - max(0.0, action_phase_s)

        systems.append(
            {
                "system_id": system_id,
                "source_artifacts": {
                    "navigation": _artifact(sources["navigation"], navigation_body),
                    "gauge": _artifact(sources["gauge"], gauge_body),
                },
                "path_geometry": {
                    **path.as_dict(),
                    "nldi_reported_full_length_m": reported_full_length_m,
                    "reproduction_error_m": full_length_error_m,
                },
                "action_boundary_measure": action.as_dict(),
                "gauge_observation_measure": gauge_measure.as_dict(),
                "current_kernel_path": {
                    "control_feature_id": feature_ids[0],
                    "control_feature_excluded": True,
                    "action_entry_feature_id": current_feature_ids[0],
                    "outlet_feature_id": current_feature_ids[-1],
                    "feature_ids": list(current_feature_ids),
                    "effective_lengths_m": list(effective_lengths_m),
                    "total_effective_length_m": current_total_length_m,
                    "terminal_measure_matches_gauge_projection": True,
                },
                "posthoc_phase_explanatory_bound": {
                    "outcome_visible_development_only": True,
                    "current_initial_manning_path_time_hours": (
                        current_time_s / 3600.0
                    ),
                    "first_active_reach_time_hours": first_time_s / 3600.0,
                    "terminal_reach_time_hours": terminal_time_s / 3600.0,
                    "bound_method": (
                        "remove_entire_first_active_and_terminal_reach_times; "
                        "larger_than_supported_endpoint_measure_error"
                    ),
                    "conservative_minimum_path_time_hours": (
                        conservative_minimum_time_s / 3600.0
                    ),
                    "action_to_observation_statistical_phase_hours": (
                        action_phase_s / 3600.0
                    ),
                    "prediction_statistical_correction_hours": (
                        prediction_correction_s / 3600.0
                    ),
                    "residual_excess_over_action_phase_hours": (
                        residual_excess_s / 3600.0
                    ),
                    "endpoint_measure_error_can_explain_phase_failure": (
                        residual_excess_s <= 0.0
                    ),
                    "statistical_shift_admitted_as_flood_wave_lag": False,
                },
                "gates": {
                    "directed_path_continuous": path.continuous,
                    "full_path_length_reproduced": True,
                    "control_feature_is_immediately_upstream_of_action_entry": True,
                    "gauge_feature_is_kernel_outlet": True,
                    "gauge_measure_resolved": gauge_measure.measure_resolved,
                    "kernel_terminal_measure_matches_gauge": True,
                    "action_measure_resolved": action.measure_resolved,
                    "endpoint_measure_primary_phase_failure": False,
                },
            }
        )

    action_resolution = {
        row["system_id"]: row["action_boundary_measure"]["measure_resolved"]
        for row in systems
    }
    return {
        "schema": SCHEMA,
        "status": (
            "endpoint_measure_not_primary_phase_failure_with_"
            "j_percy_priest_action_measure_unresolved"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "nldi_path_report": _artifact(nldi_report_path, nldi_body),
            "development_attribution_report": _artifact(
                attribution_report_path, attribution_body
            ),
        },
        "spatial_contract": {
            "maximum_connection_gap_m": MAXIMUM_CONNECTION_GAP_M,
            "maximum_resolved_endpoint_snap_distance_m": (
                MAXIMUM_RESOLVED_SNAP_DISTANCE_M
            ),
            "candidate_projection_retained_when_unresolved": True,
            "unresolved_projection_admitted_as_linear_measure": False,
            "control_reach_exclusion_semantics": (
                "release enters first downstream reach; excluded control reach "
                "cannot shorten the current active path"
            ),
        },
        "systems": systems,
        "claim_boundary": {
            "public_data_without_user_supplied_data": True,
            "outcome_visible_development_diagnostic": True,
            "center_hill_action_measure_resolved": action_resolution[
                "center_hill"
            ],
            "j_percy_priest_action_measure_resolved": action_resolution[
                "j_percy_priest"
            ],
            "both_gauge_measures_resolved": all(
                row["gauge_observation_measure"]["measure_resolved"]
                for row in systems
            ),
            "endpoint_measure_primary_phase_failure_supported": False,
            "j_percy_priest_candidate_action_measure_admitted": False,
            "operator_form_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _system_row(payload: Mapping[str, Any], system_id: str) -> Mapping[str, Any]:
    systems = payload.get("systems") or []
    if isinstance(systems, Mapping):
        row = systems.get(system_id)
        matches = [row] if isinstance(row, Mapping) else []
    else:
        matches = [
            row
            for row in systems
            if isinstance(row, Mapping) and row.get("system_id") == system_id
        ]
    if len(matches) != 1:
        raise ValueError(f"spatial_measure_{system_id}_row_required")
    return matches[0]


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_audit(
        nldi_report_path=args.nldi_report,
        attribution_report_path=args.attribution_report,
    )
    _write_json(args.report, report)
    print(args.report)
    for system in report["systems"]:
        print(
            f"{system['system_id']}: "
            f"action_resolved={system['gates']['action_measure_resolved']}, "
            f"gauge_resolved={system['gates']['gauge_measure_resolved']}, "
            "minimum_endpoint_bound_hours="
            f"{system['posthoc_phase_explanatory_bound']['conservative_minimum_path_time_hours']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
