#!/usr/bin/env python3
"""Build Chicago city tract adjacency across Cook and DuPage counties."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_gwm_chicago_official_tract_adjacency import (  # noqa: E402
    ROOK_LENGTH_TOLERANCE_DEGREES,
    _build_edges,
    _component_count,
    _degree_summary,
    _target_cohort,
)
from scripts.build_gwm_chicago_permit_tract_month_panel import (  # noqa: E402
    CHICAGO_PLACE_GEOID,
    DEFAULT_CROSSWALK,
    DEFAULT_PLACE_SHAPEFILE,
    DEFAULT_TRACT_SHAPEFILE,
    _canonical_digest,
    _city_tract_universe,
    _load_chicago_place,
    _load_illinois_tracts,
    _shapefile_components,
)


EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_OUTPUT = (
    EVIDENCE_DIR / "chicago_official_tiger2020_city_tract_adjacency.json"
)


def build_official_city_tract_adjacency() -> dict[str, Any]:
    """Return topology for every 2020 tract intersecting official Chicago PLACE."""

    all_geoids, all_geometries, tract_validation = _load_illinois_tracts(
        DEFAULT_TRACT_SHAPEFILE
    )
    chicago_geometry, place_validation = _load_chicago_place(
        DEFAULT_PLACE_SHAPEFILE
    )
    city_geoids, area_shares = _city_tract_universe(
        tract_geoids=all_geoids,
        tract_geometries=all_geometries,
        chicago_geometry=chicago_geometry,
    )
    if len(city_geoids) != 801:
        raise ValueError(f"unexpected_chicago_city_tract_count:{len(city_geoids)}")
    selected = [
        (geoid, geometry)
        for geoid, geometry in zip(all_geoids, all_geometries, strict=True)
        if geoid in city_geoids
    ]
    geoids = [geoid for geoid, _ in selected]
    geometries = [geometry for _, geometry in selected]
    county_counts = Counter(geoid[2:5] for geoid in geoids)
    if county_counts != {"031": 799, "043": 2}:
        raise ValueError(f"unexpected_city_county_counts:{county_counts}")

    queen_edges, rook_edges, queen_neighbors, rook_neighbors = _build_edges(
        geoids, geometries
    )
    crosswalk = json.loads(DEFAULT_CROSSWALK.read_text(encoding="utf-8"))
    cohort = _target_cohort(
        crosswalk=crosswalk,
        available_geoids=set(geoids),
        queen_neighbors=queen_neighbors,
        rook_neighbors=rook_neighbors,
    )
    queen_isolated = sum(not queen_neighbors.get(geoid) for geoid in geoids)
    rook_isolated = sum(not rook_neighbors.get(geoid) for geoid in geoids)
    queen_components = _component_count(geoids, queen_neighbors)
    rook_components = _component_count(geoids, rook_neighbors)
    topology_quality_pass = bool(
        queen_isolated == 0
        and rook_isolated == 0
        and queen_components == 1
        and rook_components == 1
        and not cohort["missing_target_tracts"]
        and not cohort["tracts_with_zero_rook_neighbors"]
    )

    dupage_units = [
        {
            "tract_geoid": geoid,
            "chicago_area_share": round(area_shares[geoid], 9),
            "queen_degree": len(queen_neighbors.get(geoid, set())),
            "rook_degree": len(rook_neighbors.get(geoid, set())),
            "queen_neighbors": sorted(queen_neighbors.get(geoid, set())),
            "rook_neighbors": sorted(rook_neighbors.get(geoid, set())),
        }
        for geoid in sorted(geoids)
        if geoid.startswith("17043")
    ]
    components = [
        *_shapefile_components(DEFAULT_TRACT_SHAPEFILE),
        *_shapefile_components(DEFAULT_PLACE_SHAPEFILE),
        DEFAULT_CROSSWALK,
    ]
    result = {
        "schema": "gwm.chicago_official_tiger2020_city_tract_adjacency.v1",
        "observed_on": "2026-07-24",
        "source": {
            "provider": "United States Census Bureau",
            "tract_product": "2020 TIGER/Line Illinois Census Tracts",
            "place_product": "2020 TIGER/Line Illinois Places",
            "city_place_geoid": CHICAGO_PLACE_GEOID,
            "authority_status": "verified_official",
            "license": "CC0-1.0",
        },
        "unit_contract": {
            "membership_rule": "positive area intersection with official Chicago city",
            "tract_vintage": 2020,
            "city_tract_count": len(geoids),
            "county_counts": dict(sorted(county_counts.items())),
            "cook_tract_count": county_counts["031"],
            "dupage_tract_count": county_counts["043"],
            "dupage_units": dupage_units,
            "tract_validation": tract_validation,
            "place_validation": place_validation,
        },
        "topology_definition": {
            "queen": "official tract polygon boundaries touch at one or more points",
            "rook": "official tract polygon boundaries share positive-length linework",
            "rook_length_tolerance_degrees": ROOK_LENGTH_TOLERANCE_DEGREES,
            "edge_direction": "undirected",
            "network_time_mode": "fixed_2020_official_tiger_geometry",
            "network_scope": (
                "all official 2020 tracts with positive-area intersection with "
                "Chicago city, including Cook and DuPage"
            ),
        },
        "graph_summary": {
            "node_count": len(geoids),
            "queen_edge_count": len(queen_edges),
            "rook_edge_count": len(rook_edges),
            "queen_isolated_node_count": queen_isolated,
            "rook_isolated_node_count": rook_isolated,
            "queen_connected_component_count": queen_components,
            "rook_connected_component_count": rook_components,
            "queen_degree": _degree_summary(geoids, queen_neighbors),
            "rook_degree": _degree_summary(geoids, rook_neighbors),
        },
        "topology_quality_diagnostics": {
            "all_city_units_require_queen_neighbors": True,
            "all_city_units_require_rook_neighbors": True,
            "single_queen_component_required": True,
            "single_rook_component_required": True,
            "passed": topology_quality_pass,
        },
        "queen_edges": queen_edges,
        "rook_edges": rook_edges,
        "target_cohort": cohort,
        "artifacts": {path.name: _artifact(path) for path in components},
        "readiness": {
            "official_illinois_tract_geometry_verified": True,
            "official_chicago_place_geometry_verified": True,
            "official_chicago_city_tract_universe_verified": True,
            "official_cook_dupage_city_adjacency_constructed": True,
            "official_topology_quality_pass": topology_quality_pass,
            "network_to_unit_time_ready": topology_quality_pass,
            "outside_city_interference_ready": False,
            "dynamic_network_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "positive_area_intersection_not_population_allocation": True,
            "city_internal_network_not_outside_city_interference": True,
            "fixed_2020_geometry_not_dynamic_network": True,
            "adjacency_not_causal_identification": True,
            "general_geospatial_kernel_validated": False,
            "gwm_k0_validated": False,
        },
    }
    result["adjacency_digest"] = _canonical_digest(result)
    return result


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_official_city_tract_adjacency()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(json.dumps(result["unit_contract"], sort_keys=True))
    print(json.dumps(result["graph_summary"], sort_keys=True))
    print(result["adjacency_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
