import json
import logging
import math
from typing import Any
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, mapping

logger = logging.getLogger(__name__)


class ExportEngine:
    """Export engine for converting parsed CAD/3D data to GIS formats."""

    def to_geojson(self, entities: list[dict], crs: str = "EPSG:4326") -> dict[str, Any]:
        """Convert parsed DXF entities to GeoJSON FeatureCollection."""
        features = []
        geom_types: set[str] = set()

        for i, ent in enumerate(entities):
            etype = ent.get("type", "")
            geom = None
            try:
                if etype == "LINE":
                    start = ent.get("start", [0, 0])
                    end = ent.get("end", [0, 0])
                    geom = LineString([start, end])
                elif etype in ("LWPOLYLINE", "POLYLINE"):
                    pts = ent.get("points", [])
                    if len(pts) >= 2:
                        closed = ent.get("closed", False)
                        if closed and pts[0] != pts[-1]:
                            pts = pts + [pts[0]]
                        if closed and len(pts) >= 4:
                            geom = Polygon(pts)
                        else:
                            geom = LineString(pts)
                elif etype == "CIRCLE":
                    center = ent.get("center", [0, 0])
                    radius = ent.get("radius", 1)
                    geom = Point(center).buffer(radius, resolution=32)
                elif etype in ("POINT", "TEXT", "MTEXT"):
                    loc = ent.get("location") or ent.get("insert") or ent.get("center", [0, 0])
                    geom = Point(loc)
            except Exception as e:
                logger.warning("Skipping entity %d (%s): %s", i, etype, e)
                continue

            if geom is not None:
                geom_types.add(geom.geom_type)
                props = {"layer": ent.get("layer", "0"), "id": i, "type": etype}
                features.append({
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": props,
                })

        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": crs}},
            "features": features,
            "geometry_types": sorted(geom_types),
        }

    def save_geojson(self, geojson: dict, output_path: str) -> str:
        """Write GeoJSON dict to file."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        return output_path

    def to_shapefile(self, entities: list[dict], output_dir: str, crs: str = "EPSG:4326") -> str:
        """Convert parsed entities to Shapefile via geopandas."""
        import geopandas as gpd
        geojson = self.to_geojson(entities, crs)
        if not geojson["features"]:
            raise ValueError("No features to export")
        gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs=crs)
        out = str(Path(output_dir) / "output.shp")
        gdf.to_file(out)
        return out
