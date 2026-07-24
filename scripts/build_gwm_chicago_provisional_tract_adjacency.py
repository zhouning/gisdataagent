#!/usr/bin/env python3
"""Build fail-closed Cook County tract adjacency from secondary geometry."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from shapely import STRtree
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_GEOMETRY_INPUT = (
    EVIDENCE_DIR / "census_reporter_tiger2024_cook_county_tracts.json"
)
DEFAULT_CROSSWALK_INPUT = EVIDENCE_DIR / "historical_cohort_spatial_crosswalk.json"
DEFAULT_OUTPUT = EVIDENCE_DIR / "chicago_provisional_tract_adjacency.json"
GEOID_PREFIX = "14000US"
ROOK_LENGTH_TOLERANCE_DEGREES = 1e-10


def build_provisional_tract_adjacency(
    *,
    geometry_path: Path = DEFAULT_GEOMETRY_INPUT,
    crosswalk_path: Path = DEFAULT_CROSSWALK_INPUT,
) -> dict[str, Any]:
    """Return queen and rook topology without admitting official TIGER evidence."""

    geometry_payload = _read_json(geometry_path)
    crosswalk = _read_json(crosswalk_path)
    features = geometry_payload.get("features")
    features = features if isinstance(features, list) else []

    geoids: list[str] = []
    geometries = []
    geometry_types: set[str] = set()
    valid_geometry_count = 0
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        full_geoid = str(properties.get("geoid") or "")
        if not full_geoid.startswith(GEOID_PREFIX):
            raise ValueError(f"unexpected_geoid:{full_geoid}")
        tract_geoid = full_geoid.removeprefix(GEOID_PREFIX)
        geometry = shape(feature.get("geometry"))
        geoids.append(tract_geoid)
        geometries.append(geometry)
        geometry_types.add(geometry.geom_type)
        valid_geometry_count += geometry.is_valid and not geometry.is_empty

    if not geoids or len(geoids) != len(features):
        raise ValueError("feature_geometry_or_geoid_missing")
    if len(set(geoids)) != len(geoids):
        raise ValueError("duplicate_tract_geoid")
    if valid_geometry_count != len(geometries):
        raise ValueError("invalid_or_empty_geometry")

    tree = STRtree(geometries)
    queen_edges: list[dict[str, Any]] = []
    rook_edges: list[dict[str, Any]] = []
    queen_neighbors: dict[str, set[str]] = defaultdict(set)
    rook_neighbors: dict[str, set[str]] = defaultdict(set)
    for source_index, source_geometry in enumerate(geometries):
        candidate_indices = tree.query(source_geometry, predicate="touches")
        for target_index_value in candidate_indices:
            target_index = int(target_index_value)
            if target_index <= source_index:
                continue
            source_geoid = geoids[source_index]
            target_geoid = geoids[target_index]
            shared_boundary_length = source_geometry.boundary.intersection(
                geometries[target_index].boundary
            ).length
            queen_edges.append(
                {
                    "source_geoid": source_geoid,
                    "target_geoid": target_geoid,
                    "shared_boundary_degrees": round(shared_boundary_length, 12),
                }
            )
            queen_neighbors[source_geoid].add(target_geoid)
            queen_neighbors[target_geoid].add(source_geoid)
            if shared_boundary_length > ROOK_LENGTH_TOLERANCE_DEGREES:
                rook_edges.append(
                    {
                        "source_geoid": source_geoid,
                        "target_geoid": target_geoid,
                        "shared_boundary_degrees": round(
                            shared_boundary_length, 12
                        ),
                    }
                )
                rook_neighbors[source_geoid].add(target_geoid)
                rook_neighbors[target_geoid].add(source_geoid)

    queen_edges.sort(key=_edge_key)
    rook_edges.sort(key=_edge_key)
    cohort_events = crosswalk.get("events")
    cohort_events = cohort_events if isinstance(cohort_events, list) else []
    target_events_by_tract: dict[str, list[str]] = defaultdict(list)
    for event in cohort_events:
        if not isinstance(event, Mapping):
            continue
        spatial_consistency = event.get("spatial_consistency")
        if not isinstance(spatial_consistency, Mapping):
            continue
        if spatial_consistency.get("ready") is not True:
            continue
        tract_crosswalk = event.get("tract_crosswalk")
        tract_crosswalk = (
            tract_crosswalk if isinstance(tract_crosswalk, Mapping) else {}
        )
        tract_geoid = str(tract_crosswalk.get("tract_geoid") or "")
        target_events_by_tract[tract_geoid].append(
            str(event.get("record_number") or "")
        )
    target_tracts = sorted(target_events_by_tract)
    missing_target_tracts = sorted(set(target_tracts) - set(geoids))
    target_adjacency = {
        tract_geoid: {
            "event_record_numbers": sorted(target_events_by_tract[tract_geoid]),
            "queen_neighbors": sorted(queen_neighbors.get(tract_geoid, set())),
            "rook_neighbors": sorted(rook_neighbors.get(tract_geoid, set())),
        }
        for tract_geoid in target_tracts
    }
    queen_isolated_count = sum(
        not queen_neighbors.get(geoid) for geoid in geoids
    )
    rook_isolated_count = sum(not rook_neighbors.get(geoid) for geoid in geoids)
    queen_isolated_share = queen_isolated_count / len(geoids)
    rook_isolated_share = rook_isolated_count / len(geoids)
    rook_to_queen_edge_ratio = len(rook_edges) / len(queen_edges)
    target_tracts_with_zero_rook_neighbors = sorted(
        tract for tract in target_tracts if not rook_neighbors.get(tract)
    )
    topology_quality_pass = bool(
        queen_isolated_share <= 0.01
        and rook_to_queen_edge_ratio >= 0.75
        and not target_tracts_with_zero_rook_neighbors
    )

    payload = {
        "schema": "gwm.chicago_provisional_tract_adjacency.v1",
        "observed_on": "2026-07-24",
        "source": {
            "provider": "Census Reporter",
            "canonical_url": (
                "https://api.censusreporter.org/1.0/geo/show/tiger2024?"
                "geo_ids=140%7C05000US17031"
            ),
            "declared_geometry_family": "tiger2024",
            "scope": "all Census tracts in Cook County, Illinois",
            "authority_status": "verified_secondary_not_official_admission",
            "access_boundary": "none",
            "format": "GeoJSON FeatureCollection",
        },
        "geometry_validation": {
            "feature_count": len(features),
            "unique_tract_geoid_count": len(set(geoids)),
            "geometry_types": sorted(geometry_types),
            "valid_nonempty_geometry_count": valid_geometry_count,
            "coordinate_reference_system": "WGS84 longitude_latitude",
        },
        "topology_definition": {
            "queen": "polygon boundaries touch at one or more points",
            "rook": "polygon boundaries share positive-length linework",
            "rook_length_tolerance_degrees": ROOK_LENGTH_TOLERANCE_DEGREES,
            "edge_direction": "undirected",
            "self_edges": False,
            "network_time_mode": "fixed_2024_secondary_geometry_candidate",
        },
        "graph_summary": {
            "node_count": len(geoids),
            "queen_edge_count": len(queen_edges),
            "rook_edge_count": len(rook_edges),
            "queen_isolated_node_count": queen_isolated_count,
            "rook_isolated_node_count": rook_isolated_count,
            "queen_connected_component_count": _component_count(
                geoids, queen_neighbors
            ),
            "rook_connected_component_count": _component_count(
                geoids, rook_neighbors
            ),
            "queen_degree": _degree_summary(geoids, queen_neighbors),
            "rook_degree": _degree_summary(geoids, rook_neighbors),
        },
        "topology_quality_diagnostics": {
            "queen_isolated_node_share": round(queen_isolated_share, 6),
            "rook_isolated_node_share": round(rook_isolated_share, 6),
            "rook_to_queen_edge_ratio": round(rook_to_queen_edge_ratio, 6),
            "maximum_queen_isolated_node_share": 0.01,
            "minimum_rook_to_queen_edge_ratio": 0.75,
            "all_target_tracts_require_rook_neighbors": True,
            "passed": topology_quality_pass,
            "failure_interpretation": (
                "secondary simplified geometry does not preserve tract boundary "
                "topology well enough for interference exposure mapping"
            ),
        },
        "queen_edges": queen_edges,
        "rook_edges": rook_edges,
        "target_cohort": {
            "spatial_crosswalk_digest": crosswalk.get("crosswalk_digest"),
            "event_count": sum(len(records) for records in target_events_by_tract.values()),
            "distinct_tract_count": len(target_tracts),
            "missing_target_tracts": missing_target_tracts,
            "tracts_with_zero_queen_neighbors": sorted(
                tract for tract in target_tracts if not queen_neighbors.get(tract)
            ),
            "tracts_with_zero_rook_neighbors": sorted(
                target_tracts_with_zero_rook_neighbors
            ),
            "adjacency": target_adjacency,
        },
        "artifacts": {
            geometry_path.name: _artifact(geometry_path),
            crosswalk_path.name: _artifact(crosswalk_path),
        },
        "readiness": {
            "secondary_full_cook_geometry_verified": (
                len(features) == 1332
                and len(set(geoids)) == 1332
                and geometry_types == {"Polygon"}
                and valid_geometry_count == 1332
            ),
            "provisional_queen_adjacency_constructed": bool(queen_edges),
            "provisional_rook_adjacency_constructed": bool(rook_edges),
            "provisional_topology_quality_pass": topology_quality_pass,
            "provisional_interference_network_usable": topology_quality_pass,
            "all_target_tracts_present": not missing_target_tracts,
            "all_target_tracts_have_queen_neighbors": all(
                queen_neighbors.get(tract) for tract in target_tracts
            ),
            "all_target_tracts_have_rook_neighbors": all(
                rook_neighbors.get(tract) for tract in target_tracts
            ),
            "official_tiger_geometry_verified": False,
            "official_adjacency_constructed": False,
            "network_to_unit_time_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "secondary_api_geometry_not_official_tigerline_shapefile": True,
            "secondary_topology_not_official_network_admission": True,
            "simplified_geometry_may_change_boundary_topology": True,
            "cook_county_scope_not_cross_county_topology": True,
            "fixed_2024_geometry_not_historical_dynamic_network": True,
            "provisional_adjacency_not_outcome_panel": True,
            "provisional_adjacency_not_causal_identification": True,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    payload["adjacency_digest"] = _canonical_digest(payload)
    return payload


def _degree_summary(
    geoids: list[str], neighbors: Mapping[str, set[str]]
) -> dict[str, float | int]:
    degrees = [len(neighbors.get(geoid, set())) for geoid in geoids]
    return {
        "minimum": min(degrees),
        "maximum": max(degrees),
        "mean": round(mean(degrees), 6),
    }


def _component_count(
    geoids: list[str], neighbors: Mapping[str, set[str]]
) -> int:
    remaining = set(geoids)
    count = 0
    while remaining:
        count += 1
        frontier = [remaining.pop()]
        while frontier:
            current = frontier.pop()
            unvisited = neighbors.get(current, set()) & remaining
            remaining.difference_update(unvisited)
            frontier.extend(unvisited)
    return count


def _edge_key(edge: Mapping[str, Any]) -> tuple[str, str]:
    return str(edge["source_geoid"]), str(edge["target_geoid"])


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY_INPUT)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_provisional_tract_adjacency(
        geometry_path=args.geometry,
        crosswalk_path=args.crosswalk,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["graph_summary"], sort_keys=True))
    print(result["adjacency_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
