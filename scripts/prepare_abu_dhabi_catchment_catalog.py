#!/usr/bin/env python3
"""Normalize the customer hydraulic-model Catchment shapefiles to GeoJSON.

The customer export is a ZIP of model-area folders.  Musaffah_00 and Shaliela
include DBF attributes; RB3 currently contains geometry sidecars only.  This
script preserves that distinction in feature properties and emits one compact,
EPSG:4326 catalog for the hydro workbench area selector.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import mapping
from shapely.ops import unary_union
from shapely.validation import make_valid


REGIONS = ("Musaffah_00", "RB3", "Shaliela")


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _feature(region: str, index: int, row: Any, geometry: Any) -> dict[str, Any]:
    has_attributes = "ID" in row.index
    original_id = _json_value(row.get("ID")) if has_attributes else None
    original_label = _json_value(row.get("LABEL")) if has_attributes else None
    suffix = str(original_id or f"geometry-{index + 1:05d}")
    option_id = f"{region}:{suffix}"
    option_name = str(original_label or suffix)
    properties: dict[str, Any] = {
        "id": option_id,
        "name": f"{region} · {option_name}",
        "region": region,
        "source_attribute_status": "complete" if has_attributes else "geometry_only",
        "source_crs": "EPSG:32640",
        "source_crs_status": "inferred_pending_customer_confirmation",
        "original_id": original_id,
        "original_label": original_label,
    }
    for field in (
        "A_UNIFIED",
        "A",
        "Q_(MAX)",
        "OUT_NODEID",
        "OUT_NODE",
        "SCS_CN",
        "TC",
        "LOSS_ME",
        "UHM",
        "RUNOFF_VOL",
    ):
        if has_attributes and field in row.index:
            properties[field] = _json_value(row.get(field))
    return {
        "type": "Feature",
        "id": option_id,
        "properties": properties,
        "geometry": mapping(geometry),
    }


def build_catalog(archive: Path, output: Path, *, source_crs: str, simplify_degrees: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="abu-dhabi-catchments-") as temporary:
        temporary_path = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temporary_path)
        root = next(temporary_path.glob("Hydraulic Model Data Export"))
        features: list[dict[str, Any]] = []
        region_summary: list[dict[str, Any]] = []
        for region in REGIONS:
            path = root / region / "Catchment.shp"
            if not path.exists():
                continue
            frame = gpd.read_file(path)
            if frame.crs is None:
                frame = frame.set_crs(source_crs, allow_override=True)
            else:
                frame = frame.to_crs(source_crs)
            frame = frame.to_crs("EPSG:4326")
            valid_count = 0
            region_features = 0
            has_attributes = "ID" in frame.columns
            for index, row in frame.iterrows():
                geometry = row.geometry
                if geometry is None or geometry.is_empty:
                    continue
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                if geometry is None or geometry.is_empty:
                    continue
                valid_count += 1
                if simplify_degrees > 0:
                    geometry = geometry.simplify(simplify_degrees, preserve_topology=True)
                if geometry.geom_type == "GeometryCollection":
                    polygon_parts = [
                        part
                        for part in geometry.geoms
                        if part.geom_type in {"Polygon", "MultiPolygon"}
                    ]
                    if not polygon_parts:
                        continue
                    geometry = unary_union(polygon_parts)
                if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                    continue
                features.append(_feature(region, int(index), row, geometry))
                region_features += 1
            region_summary.append(
                {
                    "region": region,
                    "source_layer": f"{region}/Catchment.shp",
                    "feature_count": int(len(frame)),
                    "catalog_feature_count": region_features,
                    "valid_geometry_count": valid_count,
                    "attributes": "complete" if has_attributes else "geometry_only",
                }
            )
    catalog = {
        "type": "FeatureCollection",
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.catchment_catalog.v1",
            "source_archive": archive.name,
            "source_crs": source_crs,
            "source_crs_status": "inferred_pending_customer_confirmation",
            "output_crs": "EPSG:4326",
            "regions": region_summary,
            "feature_count": len(features),
            "etl": {
                "geometry_repair": True,
                "simplify_degrees": simplify_degrees,
                "rb3_attribute_gap": "RB3 Catchment.dbf is absent from the customer export",
            },
        },
        "features": features,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-crs", default="EPSG:32640")
    parser.add_argument("--simplify-degrees", type=float, default=0.00002)
    args = parser.parse_args()
    catalog = build_catalog(
        args.archive,
        args.output,
        source_crs=args.source_crs,
        simplify_degrees=args.simplify_degrees,
    )
    print(json.dumps(catalog["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
