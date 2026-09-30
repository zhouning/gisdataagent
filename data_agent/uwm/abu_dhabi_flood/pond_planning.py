"""Versioned private GIS screening for pond planning; no hydraulic admission.

This milestone locates land and survey connections. A straight connection is
a distance lower bound, never a gravity route, pipe design, or flood benefit.
Raw attributes and geometry provenance survive the immutable intake snapshot.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "gwm.abu_dhabi_flood.pond_planning.v1"
DEFAULT_ROOT = Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater/pond_planning"
LEVEL_DEFINITIONS = {
    "L1": "Existing / Permanent Infrastructure",
    "L2": "Intermediate / Temporary Measures implemented pre-event",
    "L3": "ERP Resources dynamically deployed during the event",
}
BLOCKERS = [
    "land_and_connection_permission", "surveyed_elevations_and_vertical_datum",
    "groundwater_and_geotechnics", "stage_area_storage_and_safe_overflow",
    "inlet_and_connection_hydraulics", "pump_curves_if_pumped",
    "rainfall_tailwater_and_initial_state", "protection_targets_and_unit_costs",
    "independent_model_validation",
]
REQUIRED_LAYERS = {"catchments", "hotspots", "parcels", "ponds", "utilities", "corridors", "stormwater"}
# Optional layers are populated by the Makani-aware intake.  Keeping them
# optional preserves compatibility with earlier frozen snapshots, while new
# snapshots can apply building and road setbacks during screening.
OPTIONAL_LAYERS = {"buildings", "roads"}
CAPABILITIES = {"spatial_screening": True, "hydraulic_prediction": False, "cost_optimization": False}
_ID = re.compile(r"pond-[0-9a-f]{20}\Z")
# Only explicit meanings are excluded; undocumented numeric codes stay unknown.
BUILT_STATUSES = {"constructed", "built", "completed", "developed", "under construction"}
HARD_EXCLUDED_LAND_USE_TOKENS = (
    # In addition to existing occupied/sensitive uses, Makani's "Not
    # Constructed" parcels can still be reserved for future housing,
    # development, roads or public services.  Exclude those explicit planned
    # uses; an undeveloped/unknown parcel remains review-only, never approved.
    "residential", "residentialland", "housing", "citizenshousing",
    "religious", "mosque", "school", "hospital", "health", "police",
    "civildefence", "communityfacility", "communityfacil", "library",
    "shoppingcenter", "commercialland", "weddinghall",
    "utility", "primarystation", "publichouse", "publicbuilding",
    "roadreserve", "rightofway", "right of way", "roadway", "highway",
)
CONDITIONAL_LAND_USE_TOKENS = (
    "industrial", "sportsclub", "publicgarden", "office", "surfaceparking", "projectlimits",
    "governmentreserve", "sitepreparation", "ministry",
)
DETENTION_LAND_USE_TOKENS = ("detention", "retention", "storm water", "stormwater", "pond")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_root(root: Path | None = None) -> Path:
    result = (root or Path(os.environ.get("ABU_DHABI_POND_PLANNING_ROOT", str(DEFAULT_ROOT)))).expanduser().resolve()
    repository = Path(__file__).resolve().parents[3]
    if result == repository or repository in result.parents:
        raise ValueError("pond_customer_output_must_be_outside_repository")
    return result


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(payload))
    temporary.replace(path)


def freeze_snapshot(layers: dict[str, dict], provenance: dict, *, root: Path | None = None) -> dict:
    """Freeze minimal private WGS84 layers; do not infer engineering approval."""
    from shapely.geometry import shape
    if not REQUIRED_LAYERS.issubset(set(layers)) or set(layers) - REQUIRED_LAYERS - OPTIONAL_LAYERS:
        raise ValueError("pond_snapshot_layer_set_invalid")
    evidence_class = provenance.get("evidence_class")
    if evidence_class not in {"customer_source_unverified", "synthetic_test"}:
        raise ValueError("pond_snapshot_evidence_class_required")
    receipts = {}
    for name, collection in layers.items():
        if collection.get("type") != "FeatureCollection" or "crs" in collection:
            raise ValueError("pond_snapshot_requires_wgs84_geojson")
        seen = set()
        for feature in collection.get("features", []):
            key = feature.get("properties", {}).get("source_key")
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError("pond_source_key_missing_or_duplicate")
            seen.add(key)
            if feature.get("geometry") is None:
                continue
            geom = shape(feature["geometry"])
            if geom.is_empty:
                continue
            x0, y0, x1, y1 = geom.bounds
            if not all(math.isfinite(v) for v in geom.bounds) or not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
                raise ValueError("pond_snapshot_coordinate_bounds_invalid")
        data = canonical(collection)
        receipts[name] = {"file": f"{name}.geojson", "sha256": hashlib.sha256(data).hexdigest(), "count": len(seen)}
    basis = {"schema": SCHEMA, "layers": receipts, "provenance": provenance}
    snapshot_id = "pond-" + hashlib.sha256(canonical(basis)).hexdigest()[:20]
    base = private_root(root)
    target = base / "snapshots" / snapshot_id
    manifest = {**basis, "snapshot_id": snapshot_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "engineering_admitted": False, "level_definitions": LEVEL_DEFINITIONS,
                "capabilities": CAPABILITIES}
    if target.exists():
        existing, _ = load_snapshot(snapshot_id, root=base)
        manifest = existing
    else:
        target.mkdir(parents=True, exist_ok=False)
        for name, collection in layers.items():
            write_json(target / receipts[name]["file"], collection)
        write_json(target / "manifest.json", manifest)
    write_json(base / "latest.json", {"snapshot_id": snapshot_id})
    return manifest


def load_snapshot(snapshot_id: str | None = None, *, root: Path | None = None, layer_names: set[str] | None = None) -> tuple[dict, dict]:
    base = private_root(root)
    if snapshot_id is None:
        snapshot_id = json.loads((base / "latest.json").read_text())["snapshot_id"]
    if not isinstance(snapshot_id, str) or not _ID.fullmatch(snapshot_id):
        raise ValueError("pond_snapshot_id_invalid")
    target = base / "snapshots" / snapshot_id
    manifest = json.loads((target / "manifest.json").read_text())
    if manifest.get("schema") != SCHEMA or manifest.get("snapshot_id") != snapshot_id or manifest.get("engineering_admitted") is not False:
        raise ValueError("pond_snapshot_manifest_invalid")
    if manifest.get("capabilities") != CAPABILITIES or manifest.get("level_definitions") != LEVEL_DEFINITIONS:
        raise ValueError("pond_snapshot_admission_metadata_invalid")
    manifest_layers = set(manifest.get("layers", {}))
    if not REQUIRED_LAYERS.issubset(manifest_layers) or manifest_layers - REQUIRED_LAYERS - OPTIONAL_LAYERS:
        raise ValueError("pond_snapshot_layer_set_invalid")
    basis = {k: manifest[k] for k in ("schema", "layers", "provenance")}
    if "pond-" + hashlib.sha256(canonical(basis)).hexdigest()[:20] != snapshot_id:
        raise ValueError("pond_snapshot_manifest_checksum_mismatch")
    layers = {}
    for name, receipt in manifest["layers"].items():
        if layer_names is not None and name not in layer_names:
            continue
        if receipt["file"] != f"{name}.geojson":
            raise ValueError("pond_snapshot_file_invalid")
        content = (target / receipt["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != receipt["sha256"]:
            raise ValueError("pond_snapshot_checksum_mismatch")
        layers[name] = json.loads(content)
    return manifest, layers


@dataclass(frozen=True)
class ScreeningPolicy:
    maximum_distance_m: float = 1500
    minimum_area_m2: float = 500
    setback_m: float = 3
    utility_buffer_m: float = 2
    building_setback_m: float = 30
    road_setback_m: float = 15
    highway_setback_m: float = 45
    # The current diagnostic pond template supplied by the customer is an
    # approximately 2,500 m2 open excavation, 1 m deep, with 3:1 side slopes.
    # These are screening parameters, not design approval values.  Keeping
    # them in the run identity prevents a candidate from silently changing
    # shape between land screening and hydraulic comparison.
    pond_top_area_m2: float = 2500
    pond_depth_m: float = 1
    pond_side_slope_hv: float = 3
    pond_target_volume_m3: float = 2380
    alternatives_per_hotspot: int = 3
    maximum_candidates: int = 60

    def __post_init__(self):
        limits = {"maximum_distance_m": (10, 5000), "minimum_area_m2": (10, 100000),
                  "setback_m": (0, 30), "utility_buffer_m": (0, 30),
                  "building_setback_m": (0, 100), "road_setback_m": (0, 100),
                  "highway_setback_m": (0, 200),
                  "pond_top_area_m2": (100, 100000), "pond_depth_m": (0.1, 20),
                  "pond_side_slope_hv": (0.5, 10), "pond_target_volume_m3": (1, 1000000),
                  "alternatives_per_hotspot": (1, 5), "maximum_candidates": (1, 200)}
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"pond_policy_{key}_invalid")
            if key not in {"alternatives_per_hotspot", "maximum_candidates"}:
                object.__setattr__(self, key, float(value))
        if not isinstance(self.alternatives_per_hotspot, int) or not isinstance(self.maximum_candidates, int):
            raise ValueError("pond_policy_integer_required")

    @classmethod
    def from_dict(cls, data: dict | None):
        if data is None:
            return cls()
        if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
            raise ValueError("pond_policy_unknown_fields")
        return cls(**data)


def _project(collection: dict) -> list[tuple[dict, Any]]:
    if "_projected_rows" in collection:
        return collection["_projected_rows"]
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    import shapely
    project = Transformer.from_crs(4326, 32640, always_xy=True).transform
    result = []
    for feature in collection["features"]:
        geom = feature.get("geometry")
        if geom is not None:
            result.append((feature["properties"], transform(project, shapely.force_2d(shape(geom)))))
    return result


def _feature(properties: dict, geom: Any) -> dict:
    from pyproj import Transformer
    from shapely.ops import transform
    from shapely.geometry import mapping
    project = Transformer.from_crs(32640, 4326, always_xy=True).transform
    return {"type": "Feature", "properties": properties, "geometry": mapping(transform(project, geom))}


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _land_use_text(props: dict) -> str:
    values = []
    for key in ("primaryuseeng", "primaryuseengdesc", "secuseeng", "elms_landusename_e",
                "elms_parentlanduse_e", "elms_landuse_const", "elms_parentlanduse_const"):
        value = props.get(key)
        if value is not None and str(value).strip():
            values.append(str(value).strip().casefold())
    return " | ".join(values)


def _land_use_screening(props: dict) -> tuple[str, str | None]:
    """Classify land use conservatively; absence of fields stays unknown."""
    text = _land_use_text(props)
    if not text:
        return "unknown", None
    if any(token in text for token in DETENTION_LAND_USE_TOKENS):
        return "stormwater_designated", None
    if any(token in text for token in HARD_EXCLUDED_LAND_USE_TOKENS):
        return "hard_excluded", "protected_or_occupied_land_use"
    if any(token in text for token in CONDITIONAL_LAND_USE_TOKENS):
        return "conditional", "land_use_permission_and_safety_review"
    return "unknown", "land_use_unrecognized_requires_review"


def _road_is_highway(props: dict) -> bool:
    text = " ".join(str(props.get(key) or "").casefold() for key in ("roadtype_en", "roadtype", "dmt_roadclass", "roadname_en", "road_name_en"))
    road_type = str(props.get("roadtype") or "").strip().casefold()
    # Makani's current road centreline values use code 1 for Highway Street,
    # 2 for Main Street and 5 for Main Street - Secondary.  Treat the main
    # and secondary classes as the higher road setback class until DMT gives
    # us a route-specific right-of-way standard.
    return road_type in {"1", "2", "5"} or any(token in text for token in (
        "highway", "motorway", "expressway", "freeway", "main road", "main street", "arterial", "secondary street"))


def _pond_geometry_screening(usable, policy: ScreeningPolicy) -> dict:
    """Return a conservative footprint and volume check for the pond template.

    The screening geometry is deliberately explicit: a 2,500 m2 square
    equivalent requires a 50 m clear short side.  A parcel that has enough
    area but is too narrow is retained as an exclusion with a different
    reason so that planners can revise the aspect ratio rather than treating
    it as an acceptable excavation automatically.
    """
    top_side = math.sqrt(policy.pond_top_area_m2)
    bottom_side = max(0.0, top_side - 2 * policy.pond_side_slope_hv * policy.pond_depth_m)
    top_area = policy.pond_top_area_m2
    bottom_area = bottom_side * bottom_side
    nominal_volume = policy.pond_depth_m / 3 * (top_area + bottom_area + math.sqrt(top_area * bottom_area))
    target = policy.pond_target_volume_m3
    discrepancy = None if target <= 0 else (nominal_volume - target) / target
    minimum_side = None
    try:
        rectangle = usable.minimum_rotated_rectangle
        coords = list(rectangle.exterior.coords)
        lengths = sorted({round(math.hypot(coords[i][0] - coords[i + 1][0], coords[i][1] - coords[i + 1][1]), 9)
                          for i in range(len(coords) - 1)})
        if lengths:
            minimum_side = float(lengths[0])
    except Exception:
        minimum_side = None
    if usable.area < policy.pond_top_area_m2:
        fit_status = "insufficient_pond_top_area"
    elif minimum_side is not None and minimum_side + 1e-6 < top_side:
        fit_status = "pond_footprint_too_narrow"
    else:
        fit_status = "pond_template_area_and_bbox_possible"
    if discrepancy is None:
        volume_consistency = "not_evaluated"
    elif abs(discrepancy) <= 0.10:
        volume_consistency = "consistent_within_10pct"
    elif discrepancy < 0:
        volume_consistency = "target_exceeds_1m_3to1_square_geometry"
    else:
        volume_consistency = "target_below_1m_3to1_square_geometry"
    return {
        "pond_top_area_m2": round(top_area, 2),
        "pond_depth_m": round(policy.pond_depth_m, 3),
        "pond_side_slope_hv": round(policy.pond_side_slope_hv, 3),
        "pond_top_side_equivalent_m": round(top_side, 2),
        "pond_bottom_side_equivalent_m": round(bottom_side, 2),
        "pond_nominal_volume_m3": round(nominal_volume, 2),
        "pond_target_volume_m3": round(target, 2),
        "pond_volume_discrepancy_fraction": None if discrepancy is None else round(discrepancy, 4),
        "pond_volume_consistency": volume_consistency,
        "pond_minimum_rotated_bbox_side_m": None if minimum_side is None else round(minimum_side, 2),
        "pond_fit_status": fit_status,
    }


def catalog(*, root: Path | None = None) -> dict:
    manifest, layers = load_snapshot(root=root, layer_names={"catchments"})
    catchments = [{**f["properties"], "has_screening_inputs": str(f["properties"]["source_fid"]) in manifest["provenance"]["selected_catchment_fids"]}
                  for f in layers["catchments"]["features"]]
    return {"schema": SCHEMA, "snapshot_id": manifest["snapshot_id"], "created_at_utc": manifest["created_at_utc"],
            "counts": {name: row["count"] for name, row in manifest["layers"].items()},
            "catchments": catchments, "engineering_admitted": False, "capabilities": manifest["capabilities"],
            "source_summary": manifest["provenance"].get("source_summary", {}),
            "quality_findings": manifest["provenance"].get("quality_findings", []), "level_definitions": LEVEL_DEFINITIONS}


def screen(payload: dict, *, root: Path | None = None) -> dict:
    from shapely import STRtree, shortest_line
    from shapely.ops import unary_union
    if not isinstance(payload, dict) or set(payload) - {"snapshot_id", "catchment_fid", "policy"}:
        raise ValueError("pond_screening_request_invalid")
    policy = ScreeningPolicy.from_dict(payload.get("policy"))
    fid = str(payload.get("catchment_fid", ""))
    if not fid.isdigit():
        raise ValueError("pond_catchment_fid_required")
    manifest, layers = load_snapshot(payload.get("snapshot_id"), root=root, layer_names={"catchments"})
    if fid not in manifest["provenance"]["selected_catchment_fids"]:
        raise ValueError("pond_catchment_not_in_frozen_intake")
    areas = [(p, g) for p, g in _project(layers["catchments"]) if str(p["source_fid"]) == fid]
    if len(areas) != 1 or not areas[0][1].is_valid or areas[0][1].is_empty:
        raise ValueError("pond_catchment_geometry_invalid")
    catchment, area = areas[0]
    # An intake halo is a GIS search envelope, not an upstream/downstream model boundary.
    halo_m = float(manifest["provenance"]["context_buffer_m"])
    if policy.maximum_distance_m + policy.utility_buffer_m > halo_m:
        raise ValueError("pond_search_exceeds_frozen_context")
    from .pond_spatial_index import read_index_context
    indexed = read_index_context(manifest, area.buffer(halo_m).bounds, root=root)
    if indexed is None:
        _, layers = load_snapshot(manifest["snapshot_id"], root=root)
    else:
        layers = indexed
    hotspots = [(p, g) for p, g in _project(layers["hotspots"]) if g.geom_type == "Point" and area.covers(g)]
    if not hotspots:
        raise ValueError("pond_catchment_has_no_geolocated_hotspots")
    utilities = [(p, g) for p, g in _project(layers["utilities"]) if not g.is_empty and g.is_valid]
    utility_tree = STRtree([g for _, g in utilities])
    corridors = [g for _, g in _project(layers["corridors"]) if not g.is_empty and g.is_valid and g.intersects(area.buffer(halo_m))]
    corridor_union = unary_union(corridors) if corridors else None
    stormwater = [(p, g) for p, g in _project(layers["stormwater"]) if not g.is_empty and g.is_valid and g.intersects(area.buffer(halo_m))]
    inlets = [(p, g) for p, g in stormwater if p.get("asset_role") == "inlet"]
    inlet_tree = STRtree([g for _, g in inlets])
    buildings = [(p, g) for p, g in _project(layers.get("buildings", {"type": "FeatureCollection", "features": []}))
                 if not g.is_empty and g.is_valid and g.intersects(area.buffer(halo_m))]
    building_tree = STRtree([g for _, g in buildings]) if buildings else None
    roads = [(p, g) for p, g in _project(layers.get("roads", {"type": "FeatureCollection", "features": []}))
             if not g.is_empty and g.is_valid and g.intersects(area.buffer(halo_m))]
    road_tree = STRtree([g for _, g in roads]) if roads else None
    candidates = []
    exclusions = []
    counts = Counter()
    for props, geom in _project(layers["parcels"]):
        if geom.is_empty or not geom.intersects(area):
            continue
        reason = None
        land_use_class, land_use_reason = _land_use_screening(props)
        if not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
            reason = "invalid_parcel_geometry"
        elif str(props.get("construction_status") or "").strip().casefold() in BUILT_STATUSES:
            reason = "existing_or_active_construction"
        elif land_use_class == "hard_excluded":
            reason = land_use_reason or "protected_or_occupied_land_use"
        if reason:
            counts[reason] += 1
            exclusions.append({"source_key": props["source_key"], "reason": reason})
            continue
        usable = geom.intersection(area).buffer(-policy.setback_m)
        building_count = 0
        residential_building_count = 0
        building_hit_indices = []
        if building_tree is not None:
            # Buildings just outside a parcel boundary still consume the
            # safety setback, so query the parcel expanded by that setback.
            building_hit_indices = list(building_tree.query(geom.buffer(policy.building_setback_m), predicate="intersects"))
            building_count = len(building_hit_indices)
            residential_building_count = sum(
                1 for index in building_hit_indices
                if any(token in " ".join(str(buildings[int(index)][0].get(k) or "").casefold()
                                          for k in ("primaryuseengdesc", "plot_primarylanduse", "plot_seclanduse"))
                       for token in ("residen", "villa", "house"))
            )
            if building_count:
                usable = usable.difference(unary_union([buildings[int(index)][1].buffer(policy.building_setback_m)
                                                        for index in building_hit_indices]))
        road_count = 0
        highway_road_count = 0
        if road_tree is not None:
            # Centreline data do not carry the full right-of-way polygon.  A
            # buffered query is therefore required before subtracting the
            # ordinary/highway setback from the usable footprint.
            road_hit_indices = list(road_tree.query(geom.buffer(policy.highway_setback_m), predicate="intersects"))
            road_count = len(road_hit_indices)
            highway_road_count = sum(1 for index in road_hit_indices if _road_is_highway(roads[int(index)][0]))
            if road_hit_indices:
                buffers = [roads[int(index)][1].buffer(policy.highway_setback_m if _road_is_highway(roads[int(index)][0]) else policy.road_setback_m)
                           for index in road_hit_indices]
                usable = usable.difference(unary_union(buffers))
        pond_geometry = _pond_geometry_screening(usable, policy)
        effective_minimum_area = max(policy.minimum_area_m2, policy.pond_top_area_m2)
        if usable.is_empty or usable.area < effective_minimum_area or pond_geometry["pond_fit_status"] == "pond_footprint_too_narrow":
            exclusion_reason = "insufficient_screening_area"
            if building_count and usable.is_empty:
                exclusion_reason = "building_footprint_or_setback"
            elif highway_road_count and usable.is_empty:
                exclusion_reason = "highway_or_road_setback"
            elif pond_geometry["pond_fit_status"] == "pond_footprint_too_narrow":
                exclusion_reason = "pond_footprint_too_narrow"
            counts[exclusion_reason] += 1
            exclusions.append({"source_key": props["source_key"], "reason": exclusion_reason,
                               "land_use_class": land_use_class, "building_count": building_count,
                               "highway_road_count": highway_road_count, **pond_geometry})
            continue
        candidate_status = "requires_verification"
        candidate_flags = []
        if land_use_class == "conditional":
            candidate_flags.append(land_use_reason or "land_use_permission_and_safety_review")
        elif land_use_class == "unknown":
            candidate_flags.append(land_use_reason or "land_use_unrecognized_requires_review")
        if building_count:
            candidate_flags.append("building_setback_applied")
        if road_count:
            candidate_flags.append("road_setback_applied")
        candidates.append(({"candidate_id": props["source_key"], "kind": "parcel", "source_fid": props["source_fid"],
            "object_id": props.get("object_id", props.get("source_fid")), "plot_id": props.get("plot_id"), "gis_id": props.get("gis_id"),
            "construction_status": props.get("construction_status"), "ownership_type": props.get("ownership_type"),
            "planning_status": props.get("planning_status"), "allocation_status": props.get("allocation_status"),
            "land_use_class": land_use_class, "land_use_text": _land_use_text(props),
            "building_count": building_count, "residential_building_count": residential_building_count,
            "nearby_road_count": road_count, "nearby_highway_or_arterial_count": highway_road_count,
            "screening_flags": sorted(set(candidate_flags)),
            "screening_area_m2": round(usable.area, 2), "area_scope": "parcel_intersection_with_catchment_after_assumed_setback",
            **pond_geometry,
            "status": "requires_verification", "permission_status": "unverified", "defence_level": None,
            "available_storage_m3": None, "estimated_cost_aed": None, "required_data": BLOCKERS}, usable))
    for props, geom in _project(layers["ponds"]):
        if geom.is_empty or not geom.is_valid or not geom.intersects(area.buffer(policy.maximum_distance_m)):
            continue
        # The search halo intentionally includes potential cross-catchment
        # connections. Do not present those assets as inside the catchment.
        overlap_m2 = geom.intersection(area).area
        spatial_scope = ("inside_catchment" if area.covers(geom) else
                         "crosses_catchment_boundary" if overlap_m2 > 0 else
                         "touches_catchment_boundary" if geom.intersects(area) else
                         "outside_catchment_search_context")
        candidates.append(({"candidate_id": props["source_key"], "kind": "existing_pond_asset", "source_fid": props["source_fid"],
            "screening_area_m2": None, "status": "requires_verification", "permission_status": "unverified",
            "defence_level": None, "available_storage_m3": None, "estimated_cost_aed": None,
            "raw_reported_volume": props.get("volume"), "raw_reported_depth": props.get("depth"),
            "asset_status": props.get("asset_status"), "asset_condition": props.get("asset_condition"),
            "projectid": props.get("projectid"), "unitid": props.get("unitid"),
            "raw_cover_level": props.get("cover_level"), "raw_bottom_floor_level": props.get("bottom_floor_level"),
            "raw_no_of_connected_pipes": props.get("no_of_connected_pipes"),
            "raw_side_slope": props.get("side_slope"), "raw_floor_slope": props.get("floor_slope"),
            "catchment_spatial_scope": spatial_scope,
            "catchment_overlap_m2": round(overlap_m2, 3),
            "pond_area_inside_catchment_fraction": overlap_m2 / geom.area if geom.area > 0 else None,
            "distance_to_catchment_m": round(geom.distance(area), 3),
            "hydraulic_connection_verified": False,
            "required_data": BLOCKERS, "geometry_evidence": "asset_geometry_unverified_for_hydraulic_storage"}, geom))
    pairs = []
    for hotspot, point in hotspots:
        ranked = sorted(((float(point.distance(geom)), candidate, geom) for candidate, geom in candidates), key=lambda row: (row[0], row[1]["candidate_id"]))
        for distance, candidate, geom in [row for row in ranked if row[0] <= policy.maximum_distance_m][:policy.alternatives_per_hotspot]:
            pairs.append((distance, hotspot, point, candidate, geom))
    pairs.sort(key=lambda row: (row[0], row[3]["candidate_id"], row[1]["source_key"]))
    retained_ids = list(dict.fromkeys(row[3]["candidate_id"] for row in pairs))[:policy.maximum_candidates]
    retained = set(retained_ids)
    selected = [(c, g) for c, g in candidates if c["candidate_id"] in retained]
    links, link_features = [], []
    for distance, hotspot, point, candidate, geom in pairs:
        if candidate["candidate_id"] not in retained:
            continue
        line = shortest_line(point, geom)
        search_geometry = line.buffer(policy.utility_buffer_m) if policy.utility_buffer_m > 0 else line
        hits = utility_tree.query(search_geometry, predicate="intersects")
        groups = Counter(utilities[int(index)][0].get("utility_type", "unknown") for index in hits)
        fraction = None if corridor_union is None or line.length <= 1e-9 else min(1.0, line.intersection(corridor_union).length / line.length)
        nearest = None if not inlets else int(inlet_tree.nearest(point))
        link = {"connection_id": hashlib.sha256(canonical([hotspot["source_key"], candidate["candidate_id"]])).hexdigest()[:20],
                "hotspot_id": hotspot["source_key"], "candidate_id": candidate["candidate_id"],
                "distance_lower_bound_m": round(distance, 2), "connection_type": "straight_survey_connection",
                "utility_intersections": len(hits), "utility_types": dict(sorted(groups.items())),
                "corridor_overlap_fraction": None if fraction is None else round(fraction, 4),
                "nearest_inlet_source_key": None if nearest is None else inlets[nearest][0]["source_key"],
                "nearest_inlet_distance_m": None if nearest is None else round(point.distance(inlets[nearest][1]), 2),
                "gravity_feasible": None, "pump_required": None, "design_flow_m3s": None,
                "status": "requires_survey_and_permissions"}
        links.append(link)
        # Coincident points have zero separation; omit a degenerate line from the map.
        if line.length > 1e-9:
            link_features.append(_feature(link, line))
    candidate_rows = []
    for candidate, geom in selected:
        hit_ids = utility_tree.query(geom.buffer(policy.utility_buffer_m), predicate="intersects")
        row = {**candidate, "utility_overlap_count": len(hit_ids), "minimum_distance_m": min(x["distance_lower_bound_m"] for x in links if x["candidate_id"] == candidate["candidate_id"])}
        candidate_rows.append((row, geom))
    candidate_rows.sort(key=lambda row: (row[0]["minimum_distance_m"], row[0]["candidate_id"]))
    mapped = {
        "catchment": _fc([_feature(catchment, area)]),
        "hotspots": _fc([_feature(p, g) for p, g in hotspots]),
        "candidates": _fc([_feature(p, g) for p, g in candidate_rows]),
        "connections": _fc(link_features),
        "existing_ponds": _fc([_feature(p, g) for p, g in candidates if p["kind"] == "existing_pond_asset"]),
    }
    payload_basis = {"snapshot_id": manifest["snapshot_id"], "catchment_fid": fid, "policy": asdict(policy), "algorithm": "spatial-screen-v1",
                     "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("pond_spatial_index.py").read_bytes()).hexdigest()}
    result = {"schema": SCHEMA, "screening_id": hashlib.sha256(canonical(payload_basis)).hexdigest()[:20], **payload_basis,
              "catchment": catchment, "engineering_admitted": False, "hydraulic_simulation_executed": False,
              "cost_optimization_executed": False, "ranking_basis": "distance_lower_bound_only",
              "evidence_class": manifest["provenance"]["evidence_class"],
              "summary": {"hotspots": len(hotspots), "spatial_candidates_before_nearest_filter": len(candidates),
                          "selected_candidates": len(candidate_rows), "connections": len(links),
                          "existing_pond_references": len(mapped["existing_ponds"]["features"]),
                          "existing_ponds_with_positive_catchment_overlap": sum(
                              p["catchment_spatial_scope"] in {"inside_catchment", "crosses_catchment_boundary"}
                              for p, _ in candidates if p["kind"] == "existing_pond_asset"),
                          "existing_ponds_outside_catchment": sum(
                              p["catchment_spatial_scope"] == "outside_catchment_search_context"
                              for p, _ in candidates if p["kind"] == "existing_pond_asset"),
                          "hotspots_without_candidate": sum(not any(x["hotspot_id"] == p["source_key"] for x in links) for p, _ in hotspots),
                          "exclusion_counts": dict(counts), "candidate_limit_applied": len(set(row[3]["candidate_id"] for row in pairs)) > len(retained),
                          "context_stormwater_records": len(stormwater), "context_inlets": len(inlets)},
              "candidates": [p for p, _ in candidate_rows], "connections": links, "exclusions": exclusions,
              "required_data": BLOCKERS, "geojson": mapped,
              "quality_findings": manifest["provenance"].get("quality_findings", []),
              "level_definitions": LEVEL_DEFINITIONS}
    center = mapped["catchment"]["features"][0]["geometry"]
    from shapely.geometry import shape
    midpoint = shape(center).representative_point()
    result["map_update"] = {"schema": "map_update.v1", "center": [midpoint.y, midpoint.x], "zoom": 13,
        "summary": {"title": f"Pond spatial screening · {catchment.get('label', fid)}", "result_status": "spatial_candidates_require_verification"},
        "layers": [{"name": name, "type": "geojson", "layer_id": f"pond-{name}-{result['screening_id']}",
                    "geojsonData": mapped[key], "style": {"color": color, "weight": 2, "fillOpacity": opacity},
                    "tooltip_fields": tips}
                   for name, key, color, opacity, tips in [
                       ("Catchment reference", "catchment", "#607d8b", 0.03, ["label", "source_fid"]),
                       ("Existing pond references (catchment + search context)", "existing_ponds", "#3494c2", 0.18, ["source_fid", "catchment_spatial_scope", "catchment_overlap_m2", "distance_to_catchment_m", "raw_reported_depth", "raw_reported_volume", "status"]),
                       ("Candidate land / ponds — permission unverified", "candidates", "#c18320", 0.24, ["candidate_id", "screening_area_m2", "status", "utility_overlap_count"]),
                       ("Straight survey connections — distance lower bounds", "connections", "#d96737", 0.0, ["distance_lower_bound_m", "utility_intersections", "status"]),
                       ("Customer static hotspots", "hotspots", "#c03150", 0.8, ["source_key", "priority"]),
                   ]]}
    return result


def screening_csv(result: dict) -> str:
    output = io.StringIO(newline="")
    names = ["connection_id", "hotspot_id", "candidate_id", "distance_lower_bound_m", "utility_intersections", "corridor_overlap_fraction", "nearest_inlet_distance_m", "status"]
    writer = csv.DictWriter(output, fieldnames=["snapshot_id", "screening_id", *names, "engineering_admitted"], extrasaction="ignore")
    writer.writeheader()
    for row in result["connections"]:
        clean = {k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for k, v in row.items()}
        writer.writerow({**clean, "snapshot_id": result["snapshot_id"], "screening_id": result["screening_id"], "engineering_admitted": False})
    return output.getvalue()
