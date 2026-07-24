#!/usr/bin/env python3
"""Build fail-closed Cook County adjacency from official 2020 TIGER tracts."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import fiona
from shapely import STRtree
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_SHAPEFILE_INPUT = (
    EVIDENCE_DIR
    / "tiger2020_illinois_tract/tl_2020_17_tract.shp"
)
DEFAULT_CROSSWALK_INPUT = EVIDENCE_DIR / "historical_cohort_spatial_crosswalk.json"
DEFAULT_OUTPUT = EVIDENCE_DIR / "chicago_official_tiger2020_tract_adjacency.json"
OFFICIAL_ARCHIVE_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/"
    "tl_2020_17_tract.zip"
)
ILLINOIS_STATEFP = "17"
COOK_COUNTYFP = "031"
EXPECTED_ILLINOIS_TRACT_COUNT = 3265
EXPECTED_COOK_TRACT_COUNT = 1332
EXPECTED_EPSG = 4269
REQUIRED_FIELDS = {"STATEFP", "COUNTYFP", "TRACTCE", "GEOID"}
SHAPEFILE_COMPONENT_SUFFIXES = (
    ".cpg",
    ".dbf",
    ".prj",
    ".shp",
    ".shp.ea.iso.xml",
    ".shp.iso.xml",
    ".shx",
)
ROOK_LENGTH_TOLERANCE_DEGREES = 1e-10


def build_official_tract_adjacency(
    *,
    shapefile_path: Path = DEFAULT_SHAPEFILE_INPUT,
    crosswalk_path: Path = DEFAULT_CROSSWALK_INPUT,
) -> dict[str, Any]:
    """Return validated official 2020 Cook County tract topology."""

    crosswalk = _read_json(crosswalk_path)
    component_paths = _component_paths(shapefile_path)
    missing_components = [
        str(path) for path in component_paths if not path.is_file()
    ]
    if missing_components:
        raise ValueError(f"missing_shapefile_components:{missing_components}")

    geoids: list[str] = []
    geometries = []
    geometry_types: set[str] = set()
    valid_geometry_count = 0
    state_feature_count = 0
    schema_fields: set[str]
    source_driver: str
    source_crs: str
    source_epsg: int | None
    source_bounds: list[float]

    with fiona.open(shapefile_path) as source:
        source_driver = source.driver
        source_crs = source.crs_wkt
        source_epsg = source.crs.to_epsg() if source.crs else None
        source_bounds = [round(value, 6) for value in source.bounds]
        state_feature_count = len(source)
        schema_fields = set(source.schema.get("properties", {}))
        for feature in source:
            properties = feature.get("properties")
            properties = properties if isinstance(properties, Mapping) else {}
            if str(properties.get("STATEFP") or "") != ILLINOIS_STATEFP:
                raise ValueError("non_illinois_feature_in_state_shapefile")
            if str(properties.get("COUNTYFP") or "") != COOK_COUNTYFP:
                continue
            geoid = str(properties.get("GEOID") or "")
            tractce = str(properties.get("TRACTCE") or "")
            if geoid != f"{ILLINOIS_STATEFP}{COOK_COUNTYFP}{tractce}":
                raise ValueError(f"inconsistent_tract_geoid:{geoid}")
            geometry = shape(feature.get("geometry"))
            geoids.append(geoid)
            geometries.append(geometry)
            geometry_types.add(geometry.geom_type)
            valid_geometry_count += geometry.is_valid and not geometry.is_empty

    _validate_source(
        source_driver=source_driver,
        source_epsg=source_epsg,
        source_bounds=source_bounds,
        state_feature_count=state_feature_count,
        schema_fields=schema_fields,
        geoids=geoids,
        geometries=geometries,
        geometry_types=geometry_types,
        valid_geometry_count=valid_geometry_count,
    )

    queen_edges, rook_edges, queen_neighbors, rook_neighbors = _build_edges(
        geoids, geometries
    )
    cohort = _target_cohort(
        crosswalk=crosswalk,
        available_geoids=set(geoids),
        queen_neighbors=queen_neighbors,
        rook_neighbors=rook_neighbors,
    )

    queen_isolated_count = sum(
        not queen_neighbors.get(geoid) for geoid in geoids
    )
    rook_isolated_count = sum(not rook_neighbors.get(geoid) for geoid in geoids)
    queen_isolated_share = queen_isolated_count / len(geoids)
    rook_isolated_share = rook_isolated_count / len(geoids)
    rook_to_queen_edge_ratio = len(rook_edges) / len(queen_edges)
    topology_quality_pass = bool(
        queen_isolated_share <= 0.01
        and rook_to_queen_edge_ratio >= 0.75
        and not cohort["missing_target_tracts"]
        and not cohort["tracts_with_zero_rook_neighbors"]
    )

    payload = {
        "schema": "gwm.chicago_official_tiger2020_tract_adjacency.v1",
        "observed_on": "2026-07-24",
        "source": {
            "provider": "United States Census Bureau",
            "product": "2020 TIGER/Line Illinois Census Tracts",
            "canonical_url": OFFICIAL_ARCHIVE_URL,
            "scope": "Illinois statewide source filtered to Cook County 031",
            "authority_status": "verified_official",
            "license": "CC0-1.0",
            "access_method": "headed Safari direct download with automatic archive expansion",
            "archive_bytes_preserved": False,
            "archive_digest_available": False,
            "format": "ESRI Shapefile",
        },
        "geometry_validation": {
            "driver": source_driver,
            "source_feature_count": state_feature_count,
            "cook_county_feature_count": len(geoids),
            "unique_cook_tract_geoid_count": len(set(geoids)),
            "geometry_types": sorted(geometry_types),
            "valid_nonempty_geometry_count": valid_geometry_count,
            "schema_fields": sorted(schema_fields),
            "required_fields": sorted(REQUIRED_FIELDS),
            "coordinate_reference_system": f"EPSG:{source_epsg}",
            "crs_wkt": source_crs,
            "source_bounds": source_bounds,
        },
        "topology_definition": {
            "queen": "official tract polygon boundaries touch at one or more points",
            "rook": "official tract polygon boundaries share positive-length linework",
            "rook_length_tolerance_degrees": ROOK_LENGTH_TOLERANCE_DEGREES,
            "edge_direction": "undirected",
            "self_edges": False,
            "network_time_mode": "fixed_2020_official_tiger_geometry",
            "network_scope": "Cook County internal adjacency only",
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
        },
        "queen_edges": queen_edges,
        "rook_edges": rook_edges,
        "target_cohort": cohort,
        "artifacts": {
            path.name: _artifact(path) for path in component_paths
        }
        | {crosswalk_path.name: _artifact(crosswalk_path)},
        "readiness": {
            "official_tiger_geometry_verified": True,
            "official_cook_geometry_verified": True,
            "official_queen_adjacency_constructed": bool(queen_edges),
            "official_rook_adjacency_constructed": bool(rook_edges),
            "official_topology_quality_pass": topology_quality_pass,
            "official_cook_internal_interference_network_usable": topology_quality_pass,
            "all_target_tracts_present": not cohort["missing_target_tracts"],
            "all_target_tracts_have_queen_neighbors": not cohort[
                "tracts_with_zero_queen_neighbors"
            ],
            "all_target_tracts_have_rook_neighbors": not cohort[
                "tracts_with_zero_rook_neighbors"
            ],
            "network_to_unit_time_ready": topology_quality_pass,
            "cross_county_interference_ready": False,
            "dynamic_network_ready": False,
            "outcome_panel_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "original_download_archive_bytes_not_preserved": True,
            "component_level_hashes_preserved": True,
            "cook_county_scope_omits_cross_county_neighbors": True,
            "fixed_2020_geometry_not_dynamic_network": True,
            "adjacency_not_outcome_panel": True,
            "adjacency_not_causal_identification": True,
            "paper6_effect_estimation_validated": False,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    payload["adjacency_digest"] = _canonical_digest(payload)
    return payload


def _component_paths(shapefile_path: Path) -> list[Path]:
    stem = shapefile_path.with_suffix("")
    return [Path(f"{stem}{suffix}") for suffix in SHAPEFILE_COMPONENT_SUFFIXES]


def _validate_source(
    *,
    source_driver: str,
    source_epsg: int | None,
    source_bounds: list[float],
    state_feature_count: int,
    schema_fields: set[str],
    geoids: list[str],
    geometries: list[Any],
    geometry_types: set[str],
    valid_geometry_count: int,
) -> None:
    if source_driver != "ESRI Shapefile":
        raise ValueError(f"unexpected_source_driver:{source_driver}")
    if source_epsg != EXPECTED_EPSG:
        raise ValueError(f"unexpected_source_epsg:{source_epsg}")
    if source_bounds != [-91.513079, 36.970298, -87.019935, 42.508481]:
        raise ValueError(f"unexpected_source_bounds:{source_bounds}")
    if state_feature_count != EXPECTED_ILLINOIS_TRACT_COUNT:
        raise ValueError(
            f"unexpected_illinois_tract_count:{state_feature_count}"
        )
    if not REQUIRED_FIELDS <= schema_fields:
        raise ValueError(
            f"missing_required_fields:{sorted(REQUIRED_FIELDS - schema_fields)}"
        )
    if len(geoids) != EXPECTED_COOK_TRACT_COUNT:
        raise ValueError(f"unexpected_cook_tract_count:{len(geoids)}")
    if len(set(geoids)) != len(geoids):
        raise ValueError("duplicate_cook_tract_geoid")
    if geometry_types != {"Polygon"}:
        raise ValueError(f"unexpected_geometry_types:{sorted(geometry_types)}")
    if valid_geometry_count != len(geometries):
        raise ValueError("invalid_or_empty_geometry")


def _build_edges(
    geoids: list[str], geometries: list[Any]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    tree = STRtree(geometries)
    queen_edges: list[dict[str, Any]] = []
    rook_edges: list[dict[str, Any]] = []
    queen_neighbors: dict[str, set[str]] = defaultdict(set)
    rook_neighbors: dict[str, set[str]] = defaultdict(set)
    for source_index, source_geometry in enumerate(geometries):
        for target_index_value in tree.query(
            source_geometry, predicate="touches"
        ):
            target_index = int(target_index_value)
            if target_index <= source_index:
                continue
            source_geoid = geoids[source_index]
            target_geoid = geoids[target_index]
            shared_boundary_length = source_geometry.boundary.intersection(
                geometries[target_index].boundary
            ).length
            edge = {
                "source_geoid": source_geoid,
                "target_geoid": target_geoid,
                "shared_boundary_degrees": round(shared_boundary_length, 12),
            }
            queen_edges.append(edge)
            queen_neighbors[source_geoid].add(target_geoid)
            queen_neighbors[target_geoid].add(source_geoid)
            if shared_boundary_length > ROOK_LENGTH_TOLERANCE_DEGREES:
                rook_edges.append(edge)
                rook_neighbors[source_geoid].add(target_geoid)
                rook_neighbors[target_geoid].add(source_geoid)
    queen_edges.sort(key=_edge_key)
    rook_edges.sort(key=_edge_key)
    return queen_edges, rook_edges, queen_neighbors, rook_neighbors


def _target_cohort(
    *,
    crosswalk: Mapping[str, Any],
    available_geoids: set[str],
    queen_neighbors: Mapping[str, set[str]],
    rook_neighbors: Mapping[str, set[str]],
) -> dict[str, Any]:
    events = crosswalk.get("events")
    events = events if isinstance(events, list) else []
    events_by_tract: dict[str, list[str]] = defaultdict(list)
    for event in events:
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
        geoid = str(tract_crosswalk.get("tract_geoid") or "")
        events_by_tract[geoid].append(str(event.get("record_number") or ""))

    target_tracts = sorted(events_by_tract)
    return {
        "spatial_crosswalk_digest": crosswalk.get("crosswalk_digest"),
        "event_count": sum(len(records) for records in events_by_tract.values()),
        "distinct_tract_count": len(target_tracts),
        "missing_target_tracts": sorted(set(target_tracts) - available_geoids),
        "tracts_with_zero_queen_neighbors": sorted(
            tract for tract in target_tracts if not queen_neighbors.get(tract)
        ),
        "tracts_with_zero_rook_neighbors": sorted(
            tract for tract in target_tracts if not rook_neighbors.get(tract)
        ),
        "adjacency": {
            tract: {
                "event_record_numbers": sorted(events_by_tract[tract]),
                "queen_neighbors": sorted(queen_neighbors.get(tract, set())),
                "rook_neighbors": sorted(rook_neighbors.get(tract, set())),
            }
            for tract in target_tracts
        },
    }


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
    parser.add_argument(
        "--shapefile", type=Path, default=DEFAULT_SHAPEFILE_INPUT
    )
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_official_tract_adjacency(
        shapefile_path=args.shapefile,
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
