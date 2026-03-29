"""元数据提取器 - 从数据文件自动提取元数据"""
import geopandas as gpd
import rasterio
from pathlib import Path
from typing import Dict, Any


class MetadataExtractor:
    """元数据提取器"""

    def extract_from_file(self, file_path: str) -> Dict[str, Any]:
        """从文件提取完整元数据"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        metadata = {
            "technical": {"storage": {"path": str(file_path), "size_bytes": path.stat().st_size, "format": suffix[1:]}},
            "business": {},
            "operational": {"source": {"type": "uploaded", "method": "file_upload"}},
        }

        if suffix in [".shp", ".geojson", ".gpkg", ".kml"]:
            metadata["technical"].update(self.extract_spatial_metadata(file_path))
            metadata["technical"].update(self.extract_schema_metadata(file_path))
        elif suffix in [".tif", ".tiff"]:
            metadata["technical"].update(self._extract_raster_metadata(file_path))

        return metadata

    def extract_spatial_metadata(self, file_path: str) -> dict:
        """提取空间元数据"""
        try:
            gdf = gpd.read_file(file_path)
            bounds = gdf.total_bounds

            return {
                "spatial": {
                    "extent": {"minx": float(bounds[0]), "miny": float(bounds[1]), "maxx": float(bounds[2]), "maxy": float(bounds[3])},
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "srid": gdf.crs.to_epsg() if gdf.crs else None,
                    "geometry_type": gdf.geom_type.mode()[0] if len(gdf) > 0 else None,
                }
            }
        except Exception:
            return {"spatial": {}}

    def extract_schema_metadata(self, file_path: str) -> dict:
        """提取结构元数据"""
        try:
            gdf = gpd.read_file(file_path)
            columns = [{"name": col, "type": str(gdf[col].dtype)} for col in gdf.columns if col != "geometry"]
            return {"structure": {"columns": columns, "feature_count": len(gdf)}}
        except Exception:
            return {"structure": {}}

    def _extract_raster_metadata(self, file_path: str) -> dict:
        """提取栅格元数据"""
        try:
            with rasterio.open(file_path) as src:
                bounds = src.bounds
                return {
                    "spatial": {
                        "extent": {"minx": bounds.left, "miny": bounds.bottom, "maxx": bounds.right, "maxy": bounds.top},
                        "crs": str(src.crs) if src.crs else None,
                        "srid": src.crs.to_epsg() if src.crs else None,
                    },
                    "structure": {
                        "band_count": src.count,
                        "width": src.width,
                        "height": src.height,
                        "resolution": src.res,
                    }
                }
        except Exception:
            return {"spatial": {}, "structure": {}}
