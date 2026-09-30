"""Generate map-ready infrastructure and customer hotspot GeoJSON for the
real Mussafah_00 SWMM + ANUGA coupled deliveries.

The geometries are derived from the exact SWMM scenario inputs and the frozen
parcel/design evidence used to build the runs.  This is a presentation asset;
it does not change the hydraulic inputs.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import numpy as np
from pyproj import Transformer


ROOT = Path("/Users/zhouning")
FORMAL = ROOT / "Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926"
OUT = ROOT / ".tmp/mussafah00_coupled/real_runs"
HOTSPOT_SOURCE = ROOT / "gisdataagent/data_agent/uploads/admin/abu_dhabi_customer_hotspots_506.geojson"
HOTSPOT_INTERSECTION = ROOT / "Downloads/阿布扎比/flood/解决方案_20260924/局部试点_20260925/Mussafah_00_1D2D_binding_candidates/hotspot_506_intersection.csv"
DESIGN = FORMAL / "actual_review_v2/design.json"
TO_WGS84 = Transformer.from_crs(32640, 4326, always_xy=True)

SCENARIOS = {
    "L1": FORMAL / "MUSSAFAH_SOURCE_MODEL_L1_PROXY/Mussafah_00.inp",
    "L2": FORMAL / "MUSSAFAH_SOURCE_MODEL_L2_PROXY/Mussafah_00.inp",
    "PARSONS": FORMAL / "MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2/Mussafah_00.inp",
    "B1": FORMAL / "actual_review_v2/B1/Mussafah_00.inp",
    "B2": FORMAL / "actual_review_v2/B2/Mussafah_00.inp",
    "L2B6": FORMAL / "five_state/L2plusB/Mussafah_00.inp",
    "L2AB": FORMAL / "five_state/L2plusAplusB/Mussafah_00.inp",
}


def xy(x: float, y: float) -> list[float]:
    lon, lat = TO_WGS84.transform(float(x), float(y))
    return [round(lon, 8), round(lat, 8)]


def transform_geometry(value):
    if isinstance(value, list):
        if value and isinstance(value[0], (int, float)):
            return xy(value[0], value[1])
        return [transform_geometry(v) for v in value]
    return value


def feature(geometry, properties, fid=None):
    item = {"type": "Feature", "geometry": geometry, "properties": properties}
    if fid is not None:
        item["id"] = fid
    return item


def parse_inp(path: Path):
    sections: dict[str, list[str]] = {}
    current = None
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line.upper()
            sections[current] = []
        elif current and line and not line.startswith(";"):
            sections[current].append(line)

    coords: dict[str, tuple[float, float]] = {}
    for line in sections.get("[COORDINATES]", []):
        parts = line.split()
        if len(parts) >= 3:
            try:
                coords[parts[0]] = (float(parts[1]), float(parts[2]))
            except ValueError:
                pass

    nodes: dict[str, str] = {}
    for section, role in (("[JUNCTIONS]", "junction"), ("[OUTFALLS]", "outfall"), ("[STORAGE]", "storage")):
        for line in sections.get(section, []):
            parts = line.split()
            if parts and parts[0] in coords:
                nodes[parts[0]] = role

    links = []
    for line in sections.get("[CONDUITS]", []):
        parts = line.split()
        if len(parts) >= 4 and parts[1] in coords and parts[2] in coords:
            links.append((parts[0], parts[1], parts[2], "conduit", float(parts[3])))
    for line in sections.get("[PUMPS]", []):
        parts = line.split()
        if len(parts) >= 3 and parts[1] in coords and parts[2] in coords:
            links.append((parts[0], parts[1], parts[2], "pump", None))
    return coords, nodes, links


def square(cx: float, cy: float, area: float) -> list[list[float]]:
    side = math.sqrt(float(area))
    h = side / 2
    return [[cx - h, cy - h], [cx - h, cy + h], [cx + h, cy + h], [cx + h, cy - h], [cx - h, cy - h]]


def make_infrastructure(key: str, inp: Path) -> dict:
    coords, nodes, links = parse_inp(inp)
    box_items = {}
    metadata_path = inp.with_suffix(".metadata.json")
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            box_items = {f"BX-NP{item['id']}": item for item in metadata.get("items", [])}
        except (OSError, ValueError, KeyError, TypeError):
            box_items = {}
    # The 2D preparation grid provides the local surface reference needed to
    # place a buried storage node below the map plane in the 3D renderer.  It
    # is a display attribute only; it does not alter the hydraulic model.
    terrain_by_node = {}
    grid_path = OUT.parent / "prepared" / key / "grid.npz"
    if box_items and grid_path.is_file():
        try:
            grid = np.load(grid_path)
            grid_x = np.asarray(grid["x"])
            grid_y = np.asarray(grid["y"])
            grid_values = np.asarray(grid["values"])
            for node_name in box_items:
                if node_name not in coords:
                    continue
                # INP coordinates are already in the model's UTM 40N frame.
                gx, gy = coords[node_name]
                ix = int(np.abs(grid_x - gx).argmin())
                iy = int(np.abs(grid_y - gy).argmin())
                terrain_by_node[node_name] = float(grid_values[iy, ix])
        except (OSError, KeyError, IndexError, ValueError, TypeError):
            terrain_by_node = {}
    features = []
    for name, role in nodes.items():
        x, y = coords[name]
        props = {
            "asset_type": role, "asset_id": name, "scenario": key,
            "source": "EPA SWMM scenario input", "model_node": True,
        }
        if name in box_items:
            item = box_items[name]
            box_height = (float(item.get("top_m")) - float(item.get("bottom_m"))) if item.get("top_m") is not None and item.get("bottom_m") is not None else None
            capacity = float(item.get("capacity_m3")) if item.get("capacity_m3") is not None else None
            effective_area = (capacity / box_height) if capacity is not None and box_height and box_height > 0 else None
            equivalent_radius = math.sqrt(effective_area / math.pi) if effective_area and effective_area > 0 else None
            props.update({
                "asset_type": "underground_box_culvert",
                "asset_id": name,
                "box_id": item.get("id"),
                "capacity_m3": item.get("capacity_m3"),
                "bottom_m": item.get("bottom_m"),
                "top_m": item.get("top_m"),
                "inlet_diameter_m": item.get("inlet_diameter_m"),
                "inlet_node": item.get("inlet_node"),
                "outlet_node": item.get("outlet_node"),
                "outlet_distance_m": item.get("outlet_distance_m"),
                "terrain_m": terrain_by_node.get(name),
                "height_m": box_height,
                "effective_area_m2": effective_area,
                "equivalent_radius_m": equivalent_radius,
                "bottom_relative_to_surface_m": (float(item.get("bottom_m")) - terrain_by_node[name]) if name in terrain_by_node and item.get("bottom_m") is not None else None,
                "top_relative_to_surface_m": (float(item.get("top_m")) - terrain_by_node[name]) if name in terrain_by_node and item.get("top_m") is not None else None,
                "burial_depth_m": (terrain_by_node[name] - float(item.get("top_m"))) if name in terrain_by_node and item.get("top_m") is not None else None,
                "scenario_family": "L2+B / L2+A+B",
                "source": "Mussafah 五态缺口.html compiled SWMM storage metadata",
                "geometry_status": "point representation with sampled 5 m surface reference",
            })
        features.append(feature({"type": "Point", "coordinates": xy(x, y)}, props, f"{key}-node-{name}"))
    for name, start, end, role, length in links:
        sx, sy = coords[start]; ex, ey = coords[end]
        box_node = start if start in box_items else (end if end in box_items else None)
        box_item = box_items.get(box_node or "")
        terrain = terrain_by_node.get(box_node or "")
        underground_level = None
        underground_absolute_level = None
        if box_item and terrain is not None and box_item.get("bottom_m") is not None and box_item.get("top_m") is not None:
            underground_level = ((float(box_item["bottom_m"]) + float(box_item["top_m"])) / 2.0) - terrain
            underground_absolute_level = (float(box_item["bottom_m"]) + float(box_item["top_m"])) / 2.0
        features.append(feature({"type": "LineString", "coordinates": [xy(sx, sy), xy(ex, ey)]}, {
            "asset_type": role, "asset_id": name, "from_node": start, "to_node": end,
            "length_m": length, "scenario": key, "source": "EPA SWMM scenario input",
            "asset_group": "underground_box_culvert_connection" if name.startswith("BX-NP") else role,
            "underground_elevation_m": underground_level,
            "underground_absolute_elevation_m": underground_absolute_level,
        }, f"{key}-{role}-{name}"))

    if key in {"PARSONS", "L2AB"}:
        if "STO-PO3" in coords:
            cx, cy = coords["STO-PO3"]
            top = square(cx, cy, 800.0)
            features.append(feature({"type": "Polygon", "coordinates": [transform_geometry(top)]}, {
                "asset_type": "planned_pond", "asset_id": "STO-PO3", "scenario": key,
                "design_owner": "Parsons", "pond_name": "PO-2 / STO-PO3",
                "top_area_m2": 800, "reported_capacity_m3": 900, "depth_m": 1.5,
                "side_slope_h_over_v": 3, "geometry_status": "report_dimension_footprint_proxy",
                "source": "Parsons PO-2 scenario_receipt.json",
            }, "PARSONS-pond-STO-PO3"))
    elif key in {"B1", "B2"}:
        design = json.loads(DESIGN.read_text(encoding="utf-8"))
        for geom_key, asset_type, label in (("parcel_geometry_utm", "candidate_parcel", "Makani parcel 167073"), ("footprint_geometry_utm", "planned_pond", f"Autonomous {key} pond")):
            geometry = design.get(geom_key)
            if not geometry:
                continue
            g = json.loads(json.dumps(geometry))
            g["coordinates"] = transform_geometry(g["coordinates"])
            props = {
                "asset_type": asset_type, "asset_id": "167073" if asset_type == "candidate_parcel" else f"OPT-B-167073-{key}",
                "scenario": key, "label": label, "land_use": design.get("land_use"),
                "parcel_objectid": design.get("parcel_objectid"), "gisid": design.get("gisid"),
                "source": "actual_review_v2/design.json",
            }
            if asset_type == "planned_pond":
                props.update({"top_area_m2": design.get("top_area_m2"), "bottom_area_m2": design.get("bottom_area_m2"),
                              "depth_m": design.get("depth_m"), "storage_volume_m3": design.get("exact_frustum_volume_m3"),
                              "side_slope_h_over_v": design.get("side_slope_h_over_v"),
                              "inlet_diameter_m": design.get("inlet_diameter_m"),
                              "outlet_diameter_m": 0.15 if key == "B1" else 0.30,
                              "geometry_status": "design_footprint"})
            features.append(feature(g, props, f"{key}-{asset_type}"))
        pond = "OPT-B-167073"
        for name, start, end, role, length in links:
            if start == pond or end == pond:
                # The model input line is authoritative for the actual connection.
                pass

    return {"type": "FeatureCollection", "features": features, "metadata": {
        "schema": "mussafah00.real.infrastructure.v1", "scenario": key,
        "crs": "EPSG:4326", "source_model": str(inp),
        "engineering_admitted": False,
    }}


def make_hotspots():
    data = json.loads(HOTSPOT_SOURCE.read_text(encoding="utf-8"))
    flags = {}
    with HOTSPOT_INTERSECTION.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            flags[str(row.get("hotspot_id"))] = row
    for f in data.get("features", []):
        p = f.setdefault("properties", {})
        hid = str(p.get("hotspot_id", f.get("id", "")))
        row = flags.get(hid, {})
        p.update({
            "in_current_5m_domain": str(row.get("in_current_5m_domain", "False")).lower() == "true",
            "in_full_mussafah_asset_extent": str(row.get("in_full_mussafah_asset_extent", "False")).lower() == "true",
            "hydraulic_status_basis": "current 5 m domain membership only",
            "hydraulic_status": "modelled_domain" if str(row.get("in_current_5m_domain", "False")).lower() == "true" else "outside_current_5m_domain",
        })
    data["metadata"] = {"schema": "mussafah00.customer.hotspots.v1", "count": len(data.get("features", [])), "current_5m_domain_count": sum(1 for f in data.get("features", []) if f.get("properties", {}).get("in_current_5m_domain")), "engineering_admitted": False}
    return data


def main():
    for key, inp in SCENARIOS.items():
        target = OUT / key / "infrastructure.geojson"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(make_infrastructure(key, inp), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(key, target, len(json.loads(target.read_text())["features"]))
    hotspots = OUT / "hotspots_506.geojson"
    hotspots.write_text(json.dumps(make_hotspots(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("hotspots", hotspots, len(json.loads(hotspots.read_text())["features"]))


if __name__ == "__main__":
    main()
