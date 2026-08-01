#!/usr/bin/env python3
"""Compile a public linear reference for the Smith Fork internal gauge."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform

if __package__:
    from scripts.acquire_geotransport_center_hill_multigauge_development import (
        _fetch,
        _opener,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _read_verified,
    )
else:
    from acquire_geotransport_center_hill_multigauge_development import (
        _fetch,
        _opener,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _read_verified,
    )


DEFAULT_MULTIGAUGE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_multigauge_development_inputs_report.json"
)
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/smith_fork_internal_boundary_reference"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_internal_boundary_reference_report.json"
)
SCHEMA = "gwm.geotransport.smith_fork_internal_boundary_reference.v1"
MULTIGAUGE_SCHEMA = (
    "gwm.geotransport.center_hill_multigauge_development_inputs.v1"
)
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
SITE_ID = "03424730"
FEATURE_ID = 18_421_273
DOWNSTREAM_FEATURE_ID = 18_421_279
NLDI_BASE = "https://api.water.usgs.gov/nldi/linked-data"
PROJECTED_CRS = "EPSG:32616"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--multigauge-report", type=Path, default=DEFAULT_MULTIGAUGE_REPORT
    )
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan(
    *,
    multigauge_report_path: Path = DEFAULT_MULTIGAUGE_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    multigauge_body = multigauge_report_path.read_bytes()
    multigauge = json.loads(multigauge_body)
    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        multigauge.get("schema") != MULTIGAUGE_SCHEMA
        or multigauge.get("status")
        != "pass_public_multigauge_development_inputs_acquired"
        or topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
    ):
        raise ValueError("internal_boundary_reference_parent_report_invalid")
    station_body = _read_descriptor(
        multigauge["sources"]["nldi_upstream_nwissite"]
    )
    station = _station(json.loads(station_body))
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network = json.loads(network_body)["network"]
    index = network["feature_ids"].index(FEATURE_ID)
    if (
        network["downstream_feature_ids"][index] != DOWNSTREAM_FEATURE_ID
        or float(network["full_lengths_m"][index]) <= 0.0
        or float(network["effective_lengths_m"][index])
        != float(network["full_lengths_m"][index])
    ):
        raise ValueError("internal_boundary_reference_network_identity_invalid")
    urls = {
        "gauge_feature_flowline": f"{NLDI_BASE}/comid/{FEATURE_ID}?f=json",
        "downstream_feature_flowline": (
            f"{NLDI_BASE}/comid/{DOWNSTREAM_FEATURE_ID}?f=json"
        ),
    }
    plan = {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "ready_to_acquire_internal_boundary_reference",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": {
            "site_id": SITE_ID,
            "feature_id": FEATURE_ID,
            "downstream_feature_id": DOWNSTREAM_FEATURE_ID,
            "reachcode": station["properties"]["reachcode"],
            "nldi_measure": float(station["properties"]["measure"]),
            "point": station["geometry"],
        },
        "source_reports": {
            "multigauge": _artifact(multigauge_report_path, multigauge_body),
            "topology": _artifact(topology_report_path, topology_body),
            "station_catalog": multigauge["sources"]["nldi_upstream_nwissite"],
            "full_subnetwork": topology["artifacts"]["full_subnetwork"],
        },
        "requests": {
            name: {"url": url, "maximum_bytes": 1_000_000}
            for name, url in urls.items()
        },
        "compile_lock": {
            "projected_crs": PROJECTED_CRS,
            "line_direction_rule": (
                "gauge flowline endpoint shared with first downstream-flowline "
                "coordinate is the downstream endpoint"
            ),
            "gauge_projection_rule": "nearest point on NLDI COMID LineString",
            "central_partial_length_rule": (
                "RouteLink full length times projected downstream fraction"
            ),
            "nldi_measure_role": (
                "independent normalized-route address cross-check, not silently "
                "treated as a physical COMID length fraction"
            ),
        },
        "claim_boundary": {
            "public_data_without_user_supplied_data": True,
            "linear_reference_compiled": False,
            "internal_boundary_operator_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    return plan, network


def acquire(
    *,
    multigauge_report_path: Path = DEFAULT_MULTIGAUGE_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 120.0,
    retries: int = 4,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    plan, network = compile_plan(
        multigauge_report_path=multigauge_report_path,
        topology_report_path=topology_report_path,
    )
    opener = _opener(proxy)
    raw: dict[str, bytes] = {}
    retrievals: dict[str, dict[str, Any]] = {}
    for name, request in plan["requests"].items():
        body, retrieval = _fetch(
            request["url"],
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=request["maximum_bytes"],
        )
        raw[name] = body
        retrievals[name] = retrieval
    gauge_line = _single_line(json.loads(raw["gauge_feature_flowline"]), FEATURE_ID)
    downstream_line = _single_line(
        json.loads(raw["downstream_feature_flowline"]), DOWNSTREAM_FEATURE_ID
    )
    direction = _direction(gauge_line, downstream_line)
    if not direction["downstream_endpoint_matches"]:
        raise ValueError("internal_boundary_reference_flowline_direction_unverified")
    compiled = _project_reference(plan, network, gauge_line)
    raw_paths = {
        name: output_root / "raw" / f"{name}.json" for name in raw
    }
    report = {
        **plan,
        "mode": "acquired",
        "status": "candidate_internal_boundary_reference_compiled",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            name: {
                **retrievals[name],
                **_artifact(raw_paths[name], body),
            }
            for name, body in raw.items()
        },
        "flow_direction_check": direction,
        "linear_reference": compiled,
        "quality_gates": {
            "feature_attachment_verified": True,
            "downstream_coordinate_order_verified": True,
            "route_link_vs_nldi_length_relative_error_below_one_percent": (
                compiled["route_link_vs_nldi_length_relative_error"] < 0.01
            ),
            "point_to_line_snap_distance_below_30m": (
                compiled["point_to_line_snap_distance_m"] <= 30.0
            ),
            "nldi_measure_and_projection_difference_below_two_percent": (
                compiled["nldi_measure_vs_projected_downstream_fraction_abs"]
                <= 0.02
            ),
            "all_admission_gates_passed": False,
        },
        "claim_boundary": {
            "public_data_without_user_supplied_data": True,
            "linear_reference_compiled": True,
            "linear_reference_candidate_available": True,
            "linear_reference_admitted": False,
            "linear_reference_admission_blocker": (
                "52m point-to-line offset exceeds the registered 30m precision gate"
            ),
            "internal_boundary_diagnostic_permitted": True,
            "internal_boundary_operator_admitted": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    if not all(
        report["quality_gates"][key]
        for key in (
            "feature_attachment_verified",
            "downstream_coordinate_order_verified",
            "route_link_vs_nldi_length_relative_error_below_one_percent",
            "nldi_measure_and_projection_difference_below_two_percent",
        )
    ):
        raise ValueError("internal_boundary_reference_required_quality_gate_failed")
    return raw, report


def _project_reference(
    plan: Mapping[str, Any], network: Mapping[str, Any], line: LineString
) -> dict[str, Any]:
    point = shape(plan["site"]["point"])
    project = Transformer.from_crs("EPSG:4326", PROJECTED_CRS, always_xy=True)
    projected_line = transform(project.transform, line)
    projected_point = transform(project.transform, point)
    from_upstream = float(projected_line.project(projected_point))
    nldi_length = float(projected_line.length)
    downstream_length = nldi_length - from_upstream
    downstream_fraction = downstream_length / nldi_length
    index = network["feature_ids"].index(FEATURE_ID)
    route_link_length = float(network["full_lengths_m"][index])
    nldi_measure_fraction = float(plan["site"]["nldi_measure"]) / 100.0
    return {
        "projected_crs": PROJECTED_CRS,
        "nldi_flowline_length_m": nldi_length,
        "route_link_full_length_m": route_link_length,
        "route_link_vs_nldi_length_relative_error": abs(
            route_link_length - nldi_length
        )
        / route_link_length,
        "projected_measure_from_upstream_m": from_upstream,
        "projected_downstream_length_m": downstream_length,
        "projected_downstream_fraction": downstream_fraction,
        "route_link_downstream_partial_length_m": (
            route_link_length * downstream_fraction
        ),
        "point_to_line_snap_distance_m": float(projected_point.distance(projected_line)),
        "nldi_measure_0_to_100": float(plan["site"]["nldi_measure"]),
        "nldi_measure_normalized_for_cross_check_only": nldi_measure_fraction,
        "nldi_measure_vs_projected_downstream_fraction_abs": abs(
            nldi_measure_fraction - downstream_fraction
        ),
        "uncertainty_bracket_downstream_fraction": [
            min(nldi_measure_fraction, downstream_fraction),
            max(nldi_measure_fraction, downstream_fraction),
        ],
        "central_selection_uses_outcome": False,
        "evidence_level": "candidate",
        "admitted": False,
    }


def _direction(gauge: LineString, downstream: LineString) -> dict[str, Any]:
    gauge_coordinates = list(gauge.coords)
    downstream_coordinates = list(downstream.coords)
    shared = Point(gauge_coordinates[-1]).distance(Point(downstream_coordinates[0]))
    reversed_distance = Point(gauge_coordinates[0]).distance(
        Point(downstream_coordinates[-1])
    )
    return {
        "gauge_last_to_downstream_first_coordinate_distance_degrees": float(shared),
        "gauge_first_to_downstream_last_coordinate_distance_degrees": float(
            reversed_distance
        ),
        "downstream_endpoint_matches": shared <= 1e-12,
        "gauge_linestring_coordinate_order": "upstream_to_downstream",
    }


def _station(payload: Mapping[str, Any]) -> dict[str, Any]:
    matches = [
        feature
        for feature in payload.get("features") or []
        if (feature.get("properties") or {}).get("identifier")
        == f"USGS-{SITE_ID}"
    ]
    if len(matches) != 1:
        raise ValueError("internal_boundary_reference_station_identity_invalid")
    feature = matches[0]
    properties = feature.get("properties") or {}
    if (
        int(properties.get("comid")) != FEATURE_ID
        or not properties.get("reachcode")
        or not 0.0 <= float(properties.get("measure")) <= 100.0
        or (feature.get("geometry") or {}).get("type") != "Point"
    ):
        raise ValueError("internal_boundary_reference_station_metadata_invalid")
    return feature


def _single_line(payload: Mapping[str, Any], feature_id: int) -> LineString:
    features = payload.get("features") or []
    if len(features) != 1 or int(features[0].get("id")) != feature_id:
        raise ValueError("internal_boundary_reference_flowline_identity_invalid")
    geometry = shape(features[0].get("geometry"))
    if not isinstance(geometry, LineString) or geometry.is_empty:
        raise ValueError("internal_boundary_reference_linestring_required")
    return geometry


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("internal_boundary_reference_source_outside_repo") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("internal_boundary_reference_source_identity_mismatch")
    return body


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


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("internal_boundary_reference_refuses_report_overwrite")
    raw, report = acquire(
        multigauge_report_path=args.multigauge_report,
        topology_report_path=args.topology_report,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
    )
    for name, body in raw.items():
        path = args.output / "raw" / f"{name}.json"
        if path.exists():
            raise ValueError("internal_boundary_reference_refuses_raw_overwrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
