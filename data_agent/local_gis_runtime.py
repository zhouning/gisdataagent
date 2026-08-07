"""Built-in, offline GIS adapters used by the Windows ingest worker.

The production host is a plain Windows machine.  It must not depend on
ArcPy, ArcGIS Pro, an MCP service, or a network download at run time.  The
GIS Data Agent distribution installs the pyogrio/geopandas/rasterio wheels
alongside the application; those wheels ship the GDAL/PROJ native libraries
needed for FileGDB, Shapefile and GeoTIFF work.

This module keeps the optional CLI adapters as a compatibility fallback for
large installations that deliberately provision ``ogr2ogr``/``gdal_translate``.
The Python adapters are the default and are therefore the path exercised by
the isolated Windows acceptance drill.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def runtime_info() -> dict[str, Any]:
    """Return installed offline GIS runtime capabilities without side effects."""

    modules: dict[str, dict[str, Any]] = {}
    for name in ("pyogrio", "geopandas", "rasterio", "shapely", "pyarrow", "pyproj"):
        try:
            module = importlib.import_module(name)
            modules[name] = {"available": True, "version": getattr(module, "__version__", None)}
        except Exception as exc:  # pragma: no cover - exercised on a bare host
            modules[name] = {"available": False, "error": str(exc)}
    pyogrio = modules["pyogrio"]["available"]
    rasterio = modules["rasterio"]["available"]
    geopandas = modules["geopandas"]["available"]
    filegdb_driver = False
    if pyogrio:
        try:
            pyogrio_module = importlib.import_module("pyogrio")
            drivers = pyogrio_module.list_drivers()
            filegdb_driver = (
                "OpenFileGDB" in drivers
                and str(drivers["OpenFileGDB"]).lower().startswith("r")
            )
        except Exception:
            filegdb_driver = False
    return {
        "adapter": "python_gis_runtime",
        "modules": modules,
        "filegdb_reader": filegdb_driver,
        "filegdb_driver": "OpenFileGDB" if filegdb_driver else None,
        "vector_writer": pyogrio and geopandas and modules["pyarrow"]["available"],
        "raster_reader": rasterio,
        "raster_cog_writer": rasterio,
    }


def _epsg_from_crs(value: Any) -> int | None:
    if not value:
        return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(value).to_epsg()
    except Exception:
        return None


def inspect_vector(path: str | Path) -> list[dict[str, Any]]:
    """Return the same layer profile used by the ingest control plane."""

    import pyogrio

    source = Path(path)
    layers: list[dict[str, Any]] = []
    for raw_name, raw_geometry in pyogrio.list_layers(source):
        name = str(raw_name)
        info = pyogrio.read_info(
            source,
            layer=name,
            force_feature_count=True,
            force_total_bounds=True,
        )
        fields = []
        names = list(info.get("fields")) if info.get("fields") is not None else []
        dtypes = list(info.get("dtypes")) if info.get("dtypes") is not None else []
        ogr_types = list(info.get("ogr_types")) if info.get("ogr_types") is not None else []
        for index, field_name in enumerate(names):
            fields.append(
                {
                    "name": str(field_name),
                    "type": ogr_types[index] if index < len(ogr_types) else (
                        str(dtypes[index]) if index < len(dtypes) else None
                    ),
                    "data_type": str(dtypes[index]) if index < len(dtypes) else None,
                    "nullable": True,
                }
            )
        crs = info.get("crs")
        layers.append(
            {
                "name": name,
                "geometry_type": str(info.get("geometry_type") or raw_geometry or ""),
                "feature_count": (
                    int(info["features"]) if info.get("features") is not None else None
                ),
                "srid": _epsg_from_crs(crs),
                "crs_name": str(crs) if crs else None,
                "extent": _jsonable(info.get("total_bounds")),
                "fields": fields,
                "fid_column": info.get("fid_column"),
                "geometry_name": info.get("geometry_name"),
                "driver": info.get("driver"),
            }
        )
    return layers


def read_vector(path: str | Path, *, layer: str | None = None):
    """Read a vector layer with the bundled GDAL-backed GeoPandas engine."""

    import geopandas as gpd

    kwargs = {"layer": layer} if layer else {}
    return gpd.read_file(path, **kwargs)


def write_vector(
    source: str | Path,
    target: str | Path,
    *,
    layer: str | None = None,
    format_name: str = "Parquet",
) -> dict[str, Any]:
    """Materialize a vector layer without calling an external executable."""

    frame = read_vector(source, layer=layer)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "Parquet":
        frame.to_parquet(destination, index=False)
    elif format_name == "GPKG":
        frame.to_file(destination, layer=layer or destination.stem, driver="GPKG")
    else:
        raise ValueError(f"unsupported Python vector format: {format_name}")
    return {
        "adapter": "geopandas_pyogrio",
        "feature_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns if column != frame.geometry.name],
        "crs": frame.crs.to_string() if frame.crs else None,
    }


def write_cog(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Write a Cloud Optimized GeoTIFF using rasterio's bundled GDAL."""

    import rasterio
    from rasterio.shutil import copy as rio_copy

    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Open once up front so a corrupt/unreadable source fails before creating
    # a destination artifact.
    with rasterio.open(source):
        pass
    try:
        rio_copy(
            source,
            destination,
            driver="COG",
            compress="DEFLATE",
            BIGTIFF="IF_SAFER",
        )
    except Exception:
        # Keep the fallback streaming inside GDAL. Reading the complete raster
        # into a NumPy array would exhaust memory on multi-GB TIFFs.
        rio_copy(
            source,
            destination,
            driver="GTiff",
            compress="DEFLATE",
            tiled=True,
            blockxsize=512,
            blockysize=512,
            BIGTIFF="IF_SAFER",
            copy_src_overviews=True,
        )
    is_cog = _is_cog(destination)
    return {
        "adapter": "rasterio_gdal",
        "driver": "COG" if is_cog else "GTiff",
        "cloud_optimized": is_cog,
    }


def _is_cog(path: Path) -> bool:
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            # COGs are opened as GTiff, so the driver is not sufficient. GDAL
            # records the physical layout in IMAGE_STRUCTURE metadata.
            return dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"
    except Exception:
        return False


def quality_vector(
    path: str | Path,
    *,
    layer: str | None = None,
    key_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Run deterministic, local geometry and key-field checks on a layer."""

    frame = read_vector(path, layer=layer)
    geometry = frame.geometry if hasattr(frame, "geometry") else None
    result: dict[str, Any] = {
        "feature_count": int(len(frame)),
        "null_geometry_count": 0,
        "empty_geometry_count": 0,
        "invalid_geometry_count": 0,
        "duplicate_key_count": 0,
        "key_fields": key_fields or [],
        "status": "pass",
    }
    if geometry is not None:
        result["null_geometry_count"] = int(geometry.isna().sum())
        non_null = geometry[~geometry.isna()]
        result["empty_geometry_count"] = int(non_null.is_empty.sum())
        result["invalid_geometry_count"] = int((~non_null.is_valid).sum())
    for field in key_fields or []:
        if field not in frame.columns:
            result.setdefault("missing_key_fields", []).append(field)
            continue
        result["duplicate_key_count"] += int(frame[field].duplicated(keep=False).sum())
    if any(
        result.get(name, 0) > 0
        for name in ("null_geometry_count", "empty_geometry_count", "invalid_geometry_count")
    ):
        result["status"] = "review"
    if result.get("missing_key_fields") or result["duplicate_key_count"]:
        result["status"] = "review"
    return result


def quality_raster(path: str | Path) -> dict[str, Any]:
    """Profile raster validity from a bounded overview-sized sample."""

    import numpy as np
    import rasterio

    with rasterio.open(path) as dataset:
        height = min(dataset.height, 512)
        width = min(dataset.width, 512)
        sample = dataset.read(
            1,
            out_shape=(height, width),
            masked=True,
            resampling=rasterio.enums.Resampling.nearest,
        )
        valid = sample.compressed()
        total = int(sample.size)
        valid_count = int(valid.size)
        result = {
            "width": int(dataset.width),
            "height": int(dataset.height),
            "band_count": int(dataset.count),
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "nodata": dataset.nodata,
            "sample_pixel_count": total,
            "sample_valid_pixel_count": valid_count,
            "sample_valid_fraction": round(valid_count / total, 6) if total else 0.0,
            "sample_min": float(np.nanmin(valid)) if valid_count else None,
            "sample_max": float(np.nanmax(valid)) if valid_count else None,
            "status": "pass",
        }
    if not result["crs"] or not valid_count:
        result["status"] = "blocked"
    elif result["sample_valid_fraction"] < 0.5:
        result["status"] = "review"
    return result


def json_runtime_info() -> str:
    return json.dumps(runtime_info(), ensure_ascii=False, indent=2, default=str)
