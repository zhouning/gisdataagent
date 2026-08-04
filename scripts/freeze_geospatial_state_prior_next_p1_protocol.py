"""Freeze the internally governed protocol for the next observed P1 period."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.state_prior_p1_prospective_protocol import (
    build_state_prior_p1_prospective_protocol,
    validate_state_prior_p1_prospective_protocol,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_DIAGNOSTIC = (
    DATA_ROOT
    / "geospatial_state_prior_p1_failure_diagnostic_2018_10_18_23"
    / "uwm_geospatial_state_prior_p1_failure_diagnostic.json"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    diagnostic = _read_json(args.diagnostic)
    protocol = build_state_prior_p1_prospective_protocol(
        protocol_id="chongqing-observed-station-next-p1-2024-07-02-07",
        created_at=args.created_at,
        frozen_at=args.frozen_at,
        prior_diagnostic_sha256=diagnostic["diagnostic_sha256"],
        development_window={
            "start_date": "2018-10-18",
            "end_date": "2018-10-23",
        },
        final_holdout_window={
            "start_date": "2024-07-02",
            "end_date": "2024-07-07",
        },
        eligible_feature_sources=_eligible_feature_sources(),
        evidence_refs=[
            str(args.diagnostic.relative_to(ROOT)),
            "data/uwm_public_proxy/chongqing_central/"
            "geospatial_state_prior_observed_station_benchmark_2018_10_18_23/"
            "uwm_geospatial_state_prior_benchmark.json",
            "data/uwm_public_proxy/chongqing_central/"
            "openaq_station_observations_2024_07_attempt/snapshot_manifest.json",
            "/Users/zhouning/Downloads/tap_uwm/chongqing_pm25_2024_07_01_07/downloaded",
        ],
    )
    validation = validate_state_prior_p1_prospective_protocol(protocol)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_prospective_protocol:" + ";".join(validation["errors"])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "protocol_sha256": protocol["protocol_sha256"],
                "final_holdout_window": protocol["window_design"]["final_holdout_window"],
                "p1_execution_permitted": protocol["p1_execution_permitted"],
                "p2_admission_permitted": protocol["p2_admission_permitted"],
                "supported_claim": protocol["supported_claim"],
            },
            ensure_ascii=False,
        )
    )


def _eligible_feature_sources() -> dict[str, dict[str, Any]]:
    return {
        "target": {
            "source_id": "openaq_v3_station_pm25",
            "source_role": "observed_target_only_not_input_feature",
            "feature_names": ["openaq_daily_pm25_mean_ugm3"],
            "temporal_rule": "aggregate only measurements inside each UTC target day",
            "uses_target_values": False,
            "limitations": [
                "station_and_sensor_support_must_be_reassessed_after_acquisition",
                "target_values_must_never_enter_candidate_features",
                "prior_local_2024_attempt_contains_zero_measurements",
            ],
        },
        "raster": {
            "source_id": "tap_pm25_observed_gridded_chongqing_2024_07_01_07",
            "source_role": "lagged_raster_predictor",
            "feature_names": [
                "lag1_tap_pm25_ugm3",
                "tap_grid_distance_degrees",
            ],
            "temporal_rule": "target day t may use TAP day t-minus-1 only",
            "uses_target_values": False,
            "limitations": [
                "tap_may_assimilate_related_monitoring_sources",
                "lagged_tap_is_not_independent_source_proof",
            ],
        },
        "admin": {
            "source_id": "chongqing_township_admin_units_local_snapshot",
            "source_role": "static_polygon_geometry_predictor",
            "feature_names": [
                "polygon_area_square_degrees",
                "polygon_perimeter_degrees",
            ],
            "temporal_rule": "static snapshot requires boundary-vintage gate before use",
            "uses_target_values": False,
            "limitations": [
                "boundary_vintage_not_verified",
                "license_and_official_code_status_not_verified",
            ],
        },
        "graph_object": {
            "source_id": "uwm_admin_spatial_adjacency_graph_2026_07_05",
            "source_role": "static_admin_adjacency_predictor",
            "feature_names": ["admin_adjacency_degree"],
            "temporal_rule": "static topology requires boundary-vintage gate before use",
            "uses_target_values": False,
            "limitations": [
                "inherits_admin_boundary_vintage_uncertainty",
                "degree_only_route_has_limited_expressive_capacity",
            ],
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
