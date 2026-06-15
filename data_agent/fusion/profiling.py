"""Data source profiling — detect type, CRS, bounds, columns, statistics."""
import json
import logging
import os
import re
import xml.etree.ElementTree as ET

import geopandas as gpd
import numpy as np
import pandas as pd

from ..gis_processors import _resolve_path
from .models import FusionSource
from .io import _read_vector_chunked, _read_tabular_lazy, _materialize_df

logger = logging.getLogger(__name__)


RASTER_SEMANTIC_RULES = [
    {
        "value": "ndvi",
        "domain": "remote_sensing",
        "keywords": [
            "ndvi",
            "normalized difference vegetation index",
            "vegetation index",
            "vegetation_index",
        ],
    },
    {
        "value": "elevation",
        "domain": "terrain",
        "keywords": [
            "dem",
            "elevation",
            "altitude",
            "height",
            "dsm",
            "dtm",
            "digital elevation model",
            "digital surface model",
            "digital terrain model",
        ],
    },
    {
        "value": "slope",
        "domain": "terrain",
        "keywords": ["slope", "gradient"],
    },
    {
        "value": "landcover_class",
        "domain": "land_cover",
        "keywords": [
            "landcover",
            "land cover",
            "land_cover",
            "lulc",
            "classification",
            "classified",
        ],
    },
]


POINT_CLOUD_BASE_COLUMNS = [
    {"name": "x", "dtype": "float64", "null_pct": 0},
    {"name": "y", "dtype": "float64", "null_pct": 0},
    {"name": "z", "dtype": "float64", "null_pct": 0},
]

POINT_CLOUD_DIMENSIONS = [
    {
        "name": "classification",
        "dtype": "uint8",
        "semantic": "asprs_classification",
        "evidence": "classification dimension present",
    },
    {
        "name": "intensity",
        "dtype": "uint16",
        "semantic": "return_intensity",
        "evidence": "intensity dimension present",
    },
    {
        "name": "return_number",
        "dtype": "uint8",
        "semantic": "lidar_return_number",
        "evidence": "return_number dimension present",
    },
    {
        "name": "number_of_returns",
        "dtype": "uint8",
        "semantic": "lidar_return_count",
        "evidence": "number_of_returns dimension present",
    },
    {
        "name": "red",
        "dtype": "uint16",
        "semantic": "rgb_color",
        "evidence": "red color dimension present",
    },
    {
        "name": "green",
        "dtype": "uint16",
        "semantic": "rgb_color",
        "evidence": "green color dimension present",
    },
    {
        "name": "blue",
        "dtype": "uint16",
        "semantic": "rgb_color",
        "evidence": "blue color dimension present",
    },
    {
        "name": "scan_angle",
        "dtype": "float32",
        "semantic": "scan_angle",
        "evidence": "scan_angle dimension present",
    },
    {
        "name": "scan_angle_rank",
        "dtype": "int8",
        "semantic": "scan_angle",
        "evidence": "scan_angle_rank dimension present",
    },
]

LAS_CLASSIFICATION_LABELS = {
    0: "created_never_classified",
    1: "unclassified",
    2: "ground",
    3: "low_vegetation",
    4: "medium_vegetation",
    5: "high_vegetation",
    6: "building",
    7: "low_point_noise",
    9: "water",
    17: "bridge_deck",
    18: "high_noise",
}


def _detect_data_type(file_path: str) -> str:
    """Detect data type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    vector_exts = {".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".json", ".gdb"}
    raster_exts = {".tif", ".tiff", ".img", ".nc", ".hdf", ".jp2"}
    tabular_exts = {".csv", ".xlsx", ".xls", ".tsv"}
    point_cloud_exts = {".las", ".laz"}

    if ext in vector_exts:
        return "vector"
    elif ext in raster_exts:
        return "raster"
    elif ext in tabular_exts:
        return "tabular"
    elif ext in point_cloud_exts:
        return "point_cloud"
    else:
        return "tabular"  # default fallback


def profile_source(file_path: str) -> FusionSource:
    """Profile a data source: detect type, CRS, bounds, columns, statistics.

    Args:
        file_path: Path to the data file.

    Returns:
        FusionSource with full metadata.
    """
    resolved = _resolve_path(file_path)
    data_type = _detect_data_type(resolved)

    if data_type == "vector":
        return _profile_vector(resolved)
    elif data_type == "raster":
        return _profile_raster(resolved)
    elif data_type == "tabular":
        return _profile_tabular(resolved)
    elif data_type == "point_cloud":
        return _profile_point_cloud(resolved)
    else:
        return FusionSource(file_path=resolved, data_type="tabular")


def _profile_vector(path: str) -> FusionSource:
    """Profile a vector data source."""
    gdf = _read_vector_chunked(path)
    crs_str = str(gdf.crs) if gdf.crs else None
    bounds = tuple(gdf.total_bounds) if len(gdf) > 0 else None

    # Column info
    columns = []
    stats = {}
    non_geom_cols = [c for c in gdf.columns if c != "geometry"]
    for col in non_geom_cols:
        null_pct = round(gdf[col].isna().mean() * 100, 1)
        columns.append({"name": col, "dtype": str(gdf[col].dtype), "null_pct": null_pct})
        if pd.api.types.is_numeric_dtype(gdf[col]):
            stats[col] = {
                "min": float(gdf[col].min()) if not gdf[col].isna().all() else None,
                "max": float(gdf[col].max()) if not gdf[col].isna().all() else None,
                "mean": float(gdf[col].mean()) if not gdf[col].isna().all() else None,
            }
        else:
            stats[col] = {"unique": int(gdf[col].nunique())}

    geom_type = None
    if "geometry" in gdf.columns and not gdf.geometry.isna().all():
        geom_type = gdf.geometry.geom_type.mode().iloc[0] if len(gdf) > 0 else None

    return FusionSource(
        file_path=path,
        data_type="vector",
        crs=crs_str,
        bounds=bounds,
        row_count=len(gdf),
        columns=columns,
        geometry_type=geom_type,
        stats=stats,
    )


def _profile_raster(path: str) -> FusionSource:
    """Profile a raster data source.

    For large rasters (>1M pixels per band), uses windowed sampling of the
    centre region to avoid loading entire bands into memory.
    """
    import rasterio
    from rasterio.windows import Window

    LARGE_PIXEL_THRESHOLD = 1_000_000

    with rasterio.open(path) as ds:
        crs_str = str(ds.crs) if ds.crs else None
        bounds = tuple(ds.bounds)
        band_count = ds.count
        resolution = (ds.res[0], ds.res[1])
        total_pixels = ds.width * ds.height
        use_window = total_pixels > LARGE_PIXEL_THRESHOLD

        # For large rasters, sample a centre window (~1024×1024)
        if use_window:
            win_size = min(1024, ds.width, ds.height)
            col_off = max(0, (ds.width - win_size) // 2)
            row_off = max(0, (ds.height - win_size) // 2)
            window = Window(col_off, row_off, win_size, win_size)
        else:
            window = None

        columns = []
        stats = {"grid": _raster_grid_metadata(ds, resolution)}
        for i in range(1, min(band_count + 1, 11)):  # cap at 10 bands
            band_data = ds.read(i, window=window)
            valid = band_data[band_data != ds.nodata] if ds.nodata is not None else band_data
            band_name = f"band_{i}"
            band_description = ds.descriptions[i - 1] if ds.descriptions else None
            band_tags = ds.tags(i)
            column = {"name": band_name, "dtype": str(ds.dtypes[i - 1]), "null_pct": 0}
            if band_description:
                column["description"] = band_description
            if band_tags:
                column["tags"] = band_tags
            nodata = _raster_band_nodata(ds, i)
            scale = _raster_band_scale(ds, i, band_tags)
            offset = _raster_band_offset(ds, i, band_tags)
            unit = _raster_band_unit(ds, i, band_tags)
            if nodata is not None:
                column["nodata"] = nodata
            if scale is not None:
                column["scale"] = scale
            if offset is not None:
                column["offset"] = offset
            if unit:
                column["unit"] = unit
            columns.append(column)
            if len(valid) > 0:
                stats[band_name] = {
                    "min": float(np.nanmin(valid)),
                    "max": float(np.nanmax(valid)),
                    "mean": float(np.nanmean(valid)),
                }
                if scale is not None or offset is not None:
                    scale_value = scale if scale is not None else 1.0
                    offset_value = offset if offset is not None else 0.0
                    scaled = valid.astype("float64") * scale_value + offset_value
                    stats[band_name]["scaled_min"] = float(np.nanmin(scaled))
                    stats[band_name]["scaled_max"] = float(np.nanmax(scaled))
                    stats[band_name]["scaled_mean"] = float(np.nanmean(scaled))

        sidecar_metadata = _load_raster_sidecar_metadata(path)
        _apply_raster_sidecar_metadata(columns, sidecar_metadata)
        stats["feature_chips"] = _raster_feature_chip_summaries(ds, columns)
        semantic_domain, semantic_hints = _infer_raster_semantic_hints(
            path,
            columns,
            stats,
            sidecar_metadata,
        )

    return FusionSource(
        file_path=path,
        data_type="raster",
        crs=crs_str,
        bounds=bounds,
        row_count=0,
        columns=columns,
        stats=stats,
        band_count=band_count,
        resolution=resolution,
        semantic_domain=semantic_domain,
        semantic_hints=semantic_hints,
    )


def _raster_band_nodata(ds: object, index: int) -> float | None:
    nodata = getattr(ds, "nodata", None)
    if nodata is None:
        nodatavals = getattr(ds, "nodatavals", None)
        if nodatavals and len(nodatavals) >= index:
            nodata = nodatavals[index - 1]
    return _safe_float_or_none(nodata)


def _raster_band_scale(ds: object, index: int, tags: dict) -> float | None:
    tag_value = _first_tag_value(tags, ["scale_factor", "scale", "SCALE"])
    if tag_value is not None:
        return _safe_float_or_none(tag_value)
    scales = getattr(ds, "scales", None)
    if scales and len(scales) >= index and scales[index - 1] != 1.0:
        return _safe_float_or_none(scales[index - 1])
    return None


def _raster_band_offset(ds: object, index: int, tags: dict) -> float | None:
    tag_value = _first_tag_value(tags, ["add_offset", "offset", "OFFSET"])
    if tag_value is not None:
        return _safe_float_or_none(tag_value)
    offsets = getattr(ds, "offsets", None)
    if offsets and len(offsets) >= index and offsets[index - 1] != 0.0:
        return _safe_float_or_none(offsets[index - 1])
    return None


def _raster_band_unit(ds: object, index: int, tags: dict) -> str | None:
    tag_value = _first_tag_value(tags, ["units", "unit", "UNIT"])
    if tag_value:
        return str(tag_value)
    units = getattr(ds, "units", None)
    if units and len(units) >= index and units[index - 1]:
        return str(units[index - 1])
    return None


def _first_tag_value(tags: dict, keys: list[str]) -> object | None:
    for key in keys:
        if key in tags:
            return tags[key]
    lower_tags = {str(key).lower(): value for key, value in tags.items()}
    for key in keys:
        value = lower_tags.get(key.lower())
        if value is not None:
            return value
    return None


def _safe_float_or_none(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int_or_none(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _load_raster_sidecar_metadata(path: str) -> dict | None:
    stem, _ = os.path.splitext(path)
    candidates = [
        (f"{stem}.stac.json", "json"),
        (f"{stem}.metadata.json", "json"),
        (f"{stem}.json", "json"),
        (f"{stem}.iso.xml", "xml"),
        (f"{stem}.metadata.xml", "xml"),
        (f"{stem}.xml", "xml"),
    ]
    for candidate, sidecar_format in candidates:
        if not os.path.exists(candidate):
            continue
        if sidecar_format == "xml":
            metadata = _parse_iso_xml_sidecar(candidate)
        else:
            metadata = _parse_json_sidecar(candidate)
        if not metadata:
            continue
        if not isinstance(metadata, dict):
            continue
        kind = _raster_sidecar_kind(metadata, sidecar_format)
        return {
            "path": candidate,
            "kind": kind,
            "metadata": metadata,
        }
    return None


def _parse_json_sidecar(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return metadata if isinstance(metadata, dict) else None


def _parse_iso_xml_sidecar(path: str) -> dict | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None

    title = _xml_first_text_under(root, "title")
    abstract = _xml_first_text_under(root, "abstract")
    date_stamp = _xml_first_text_under(root, "dateStamp")
    lineage = _xml_first_text_under(root, "statement")
    keywords = _xml_all_text_under(root, "keyword")
    topics = _xml_all_text_under(root, "topicCategory")
    is_iso = _xml_local_name(root.tag) == "MD_Metadata" or any(
        "isotc211.org/2005/gmd" in element.tag for element in root.iter()
    )

    metadata = {
        "title": title,
        "abstract": abstract,
        "datetime": date_stamp,
        "lineage": lineage,
        "keywords": keywords,
        "topic_categories": topics,
    }
    if is_iso:
        metadata["metadata_standard"] = "ISO 19115"
    parsed = {key: value for key, value in metadata.items() if value}
    if not any(key != "metadata_standard" for key in parsed):
        return None
    return parsed


def _raster_sidecar_kind(metadata: dict, sidecar_format: str) -> str:
    if sidecar_format == "xml":
        if metadata.get("metadata_standard") == "ISO 19115":
            return "iso19115_sidecar"
        return "xml_metadata_sidecar"
    return "stac_sidecar" if _looks_like_stac(metadata) else "metadata_sidecar"


def _looks_like_stac(metadata: dict) -> bool:
    return bool(
        metadata.get("stac_version")
        or metadata.get("stac_extensions")
        or metadata.get("type") == "Feature"
        or metadata.get("collection")
        or metadata.get("assets")
    )


def _xml_first_text_under(root: ET.Element, local_name: str) -> str | None:
    values = _xml_all_text_under(root, local_name)
    return values[0] if values else None


def _xml_all_text_under(root: ET.Element, local_name: str) -> list[str]:
    values = []
    for element in root.iter():
        if _xml_local_name(element.tag) != local_name:
            continue
        text = _xml_descendant_text(element)
        if text:
            values.append(text)
    return _dedupe_preserve_order(values)


def _xml_descendant_text(element: ET.Element) -> str | None:
    texts = []
    for item in element.iter():
        if item.text and item.text.strip():
            texts.append(item.text.strip())
    if not texts:
        return None
    return " ".join(texts)


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _apply_raster_sidecar_metadata(
    columns: list[dict],
    sidecar_metadata: dict | None,
) -> None:
    if not sidecar_metadata:
        return
    raster_bands = _sidecar_raster_bands(sidecar_metadata.get("metadata", {}))
    for index, band_metadata in enumerate(raster_bands):
        if index >= len(columns):
            break
        column = columns[index]
        for source_key, target_key in [
            ("scale", "scale"),
            ("scale_factor", "scale"),
            ("offset", "offset"),
            ("add_offset", "offset"),
            ("nodata", "nodata"),
        ]:
            if target_key in column or source_key not in band_metadata:
                continue
            value = _safe_float_or_none(band_metadata.get(source_key))
            if value is not None:
                column[target_key] = value
        unit = (
            band_metadata.get("unit")
            or band_metadata.get("units")
            or band_metadata.get("data_type")
        )
        if unit and "unit" not in column:
            column["unit"] = str(unit)


def _sidecar_raster_bands(metadata: dict) -> list[dict]:
    bands = []
    if isinstance(metadata.get("raster:bands"), list):
        bands.extend(item for item in metadata["raster:bands"] if isinstance(item, dict))
    for asset in (metadata.get("assets") or {}).values():
        if not isinstance(asset, dict):
            continue
        if isinstance(asset.get("raster:bands"), list):
            bands.extend(item for item in asset["raster:bands"] if isinstance(item, dict))
    return bands


def _raster_grid_metadata(ds: object, resolution: tuple[float, float]) -> dict:
    crs = getattr(ds, "crs", None)
    pixel_width = abs(float(resolution[0]))
    pixel_height = abs(float(resolution[1]))
    is_geographic = bool(getattr(crs, "is_geographic", False)) if crs else False
    is_projected = bool(getattr(crs, "is_projected", False)) if crs else False
    unit = _raster_crs_unit(crs, is_geographic=is_geographic)

    grid = {
        "width": int(getattr(ds, "width", 0) or 0),
        "height": int(getattr(ds, "height", 0) or 0),
        "pixel_width": pixel_width,
        "pixel_height": pixel_height,
        "crs_unit": unit,
        "crs_is_geographic": is_geographic,
        "crs_is_projected": is_projected,
        "requires_projection_for_area": is_geographic,
    }
    if not is_geographic:
        grid["pixel_area"] = pixel_width * pixel_height
    else:
        grid["pixel_area"] = None
    return grid


def _raster_crs_unit(crs: object, is_geographic: bool) -> str | None:
    if crs is None:
        return None
    if is_geographic:
        return str(getattr(crs, "angular_units", None) or "degree")
    return str(getattr(crs, "linear_units", None) or "")


def _raster_feature_chip_summaries(
    ds: object,
    columns: list[dict],
    chip_size: int = 4,
) -> list[dict]:
    if not columns:
        return []
    window = _raster_center_chip_window(
        int(getattr(ds, "width", 0) or 0),
        int(getattr(ds, "height", 0) or 0),
        chip_size,
    )
    if not window:
        return []

    chip = {
        "chip_id": "center",
        "sampling_strategy": "center_window",
        "window": window,
        "bounds": _raster_window_bounds(ds, window),
        "bands": {},
    }
    for index, column in enumerate(columns, start=1):
        field = column.get("name") or f"band_{index}"
        band_stats = _raster_chip_band_summary(ds, index, column, window)
        if band_stats:
            chip["bands"][field] = band_stats
    return [chip] if chip["bands"] else []


def _raster_center_chip_window(
    width: int,
    height: int,
    chip_size: int,
) -> dict | None:
    if width <= 0 or height <= 0:
        return None
    win_width = min(chip_size, width)
    win_height = min(chip_size, height)
    return {
        "row_off": max(0, (height - win_height) // 2),
        "col_off": max(0, (width - win_width) // 2),
        "height": win_height,
        "width": win_width,
    }


def _raster_window_bounds(ds: object, window: dict) -> tuple | None:
    try:
        from rasterio.windows import Window

        raster_window = Window(
            window["col_off"],
            window["row_off"],
            window["width"],
            window["height"],
        )
        return tuple(float(value) for value in ds.window_bounds(raster_window))
    except Exception:
        return None


def _raster_chip_band_summary(
    ds: object,
    index: int,
    column: dict,
    window: dict,
) -> dict:
    try:
        from rasterio.windows import Window

        raster_window = Window(
            window["col_off"],
            window["row_off"],
            window["width"],
            window["height"],
        )
        data = ds.read(index, window=raster_window)
    except Exception:
        return {}

    nodata = column.get("nodata")
    if nodata is None:
        nodata = _raster_band_nodata(ds, index)
    valid = _raster_valid_pixels(data, nodata)
    if len(valid) == 0:
        return {}

    summary = {
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "std": float(np.nanstd(valid)),
        "valid_count": int(len(valid)),
    }
    scale = column.get("scale")
    offset = column.get("offset")
    if scale is not None or offset is not None:
        scale_value = float(scale) if scale is not None else 1.0
        offset_value = float(offset) if offset is not None else 0.0
        scaled = valid.astype("float64") * scale_value + offset_value
        summary["scaled_min"] = float(np.nanmin(scaled))
        summary["scaled_max"] = float(np.nanmax(scaled))
        summary["scaled_mean"] = float(np.nanmean(scaled))
        summary["scaled_std"] = float(np.nanstd(scaled))

    top_values = _raster_chip_top_values(valid)
    if top_values:
        summary["top_values"] = top_values
    return summary


def _raster_valid_pixels(data: np.ndarray, nodata: object | None) -> np.ndarray:
    flat = np.asarray(data).reshape(-1)
    valid = flat[np.isfinite(flat)]
    nodata_value = _safe_float_or_none(nodata)
    if nodata_value is not None:
        valid = valid[valid != nodata_value]
    return valid


def _raster_chip_top_values(valid: np.ndarray) -> list[dict]:
    unique, counts = np.unique(valid, return_counts=True)
    if len(unique) == 0 or len(unique) > min(10, max(3, len(valid) // 2)):
        return []
    pairs = sorted(
        zip(unique, counts),
        key=lambda item: (-int(item[1]), float(item[0])),
    )
    return [
        {"value": float(value), "count": int(count)}
        for value, count in pairs[:5]
    ]


def _infer_raster_semantic_hints(
    path: str,
    columns: list[dict],
    stats: dict,
    sidecar_metadata: dict | None = None,
) -> tuple[str | None, list[dict]]:
    """Infer conservative semantic hints for common raster products."""
    filename = os.path.splitext(os.path.basename(path))[0]
    filename_text = _normalize_semantic_text(filename)
    theme_by_value: dict[str, dict] = {}
    band_hints = []
    metadata_hints = _raster_pixel_semantic_hints(columns)
    metadata_hints.extend(_raster_sidecar_semantic_hints(sidecar_metadata))
    metadata_hints.extend(_raster_grid_semantic_hints(stats.get("grid")))
    metadata_hints.extend(_raster_feature_chip_semantic_hints(stats.get("feature_chips")))

    for rule in RASTER_SEMANTIC_RULES:
        value = rule["value"]
        filename_evidence = _keyword_evidence(
            filename_text,
            "filename",
            rule["keywords"],
        )
        sidecar_theme_evidence = _raster_sidecar_theme_evidence(
            sidecar_metadata,
            rule["keywords"],
        )
        for column in columns:
            band_name = column.get("name", "")
            band_evidence = list(filename_evidence) + list(sidecar_theme_evidence)

            description = column.get("description")
            if description:
                band_evidence.extend(
                    _keyword_evidence(
                        _normalize_semantic_text(description),
                        f"{band_name} description",
                        rule["keywords"],
                    )
                )

            tags = column.get("tags") or {}
            if isinstance(tags, dict):
                for key, value_text in tags.items():
                    band_evidence.extend(
                        _keyword_evidence(
                            _normalize_semantic_text(value_text),
                            f"{band_name} tag {key}",
                            rule["keywords"],
                        )
                    )

            if not band_evidence:
                continue

            range_evidence = _raster_range_evidence(rule["value"], band_name, stats)
            evidence = _dedupe_preserve_order(band_evidence + range_evidence)
            confidence = _raster_hint_confidence(
                evidence,
                has_filename_evidence=bool(filename_evidence),
                has_range_evidence=bool(range_evidence),
            )
            band_hints.append({
                "type": "band_semantic",
                "field": band_name,
                "value": value,
                "confidence": confidence,
                "evidence": evidence,
            })

            theme = theme_by_value.get(value)
            if theme is None or confidence > theme["confidence"]:
                theme_by_value[value] = {
                    "type": "raster_theme",
                    "value": value,
                    "domain": rule["domain"],
                    "confidence": confidence,
                    "evidence": evidence,
                }

    theme_hints = sorted(
        theme_by_value.values(),
        key=lambda item: (
            -float(item.get("confidence", 0)),
            str(item.get("value", "")),
        ),
    )
    semantic_domain = theme_hints[0]["domain"] if theme_hints else None
    semantic_hints = theme_hints + band_hints + metadata_hints
    return semantic_domain, semantic_hints


def _raster_pixel_semantic_hints(columns: list[dict]) -> list[dict]:
    hints = []
    for column in columns:
        field = column.get("name")
        if not field:
            continue
        evidence = []
        if column.get("scale") is not None:
            evidence.append(f"{field} scale is {column['scale']}")
        if column.get("offset") is not None:
            evidence.append(f"{field} offset is {column['offset']}")
        if column.get("nodata") is not None:
            evidence.append(f"{field} nodata is {column['nodata']}")
        if column.get("unit"):
            evidence.append(f"{field} unit is {column['unit']}")
        if not evidence:
            continue
        hint = {
            "type": "pixel_value_semantics",
            "field": field,
            "confidence": 0.9,
            "evidence": evidence,
        }
        for key in ["scale", "offset", "nodata", "unit"]:
            if column.get(key) is not None:
                hint[key] = column[key]
        hints.append(hint)
    return hints


def _raster_grid_semantic_hints(grid: dict | None) -> list[dict]:
    if not grid:
        return []
    evidence = [
        (
            f"pixel size is {grid.get('pixel_width')} x "
            f"{grid.get('pixel_height')} {grid.get('crs_unit') or 'unknown'}"
        )
    ]
    if grid.get("crs_is_geographic"):
        evidence.append("pixel area is angular and requires projection for metric area")
        return [{
            "type": "raster_grid_semantics",
            "value": "geographic_degree_grid",
            "confidence": 0.9,
            "pixel_width": grid.get("pixel_width"),
            "pixel_height": grid.get("pixel_height"),
            "crs_unit": grid.get("crs_unit"),
            "requires_projection_for_area": True,
            "evidence": evidence,
        }]
    if grid.get("crs_is_projected"):
        pixel_area = grid.get("pixel_area")
        if pixel_area is not None:
            evidence.append(f"pixel area is {pixel_area} square {grid.get('crs_unit')}")
        return [{
            "type": "raster_grid_semantics",
            "value": "projected_metric_grid",
            "confidence": 0.92,
            "pixel_width": grid.get("pixel_width"),
            "pixel_height": grid.get("pixel_height"),
            "pixel_area": pixel_area,
            "crs_unit": grid.get("crs_unit"),
            "requires_projection_for_area": False,
            "evidence": evidence,
        }]
    return [{
        "type": "raster_grid_semantics",
        "value": "unknown_crs_grid",
        "confidence": 0.5,
        "pixel_width": grid.get("pixel_width"),
        "pixel_height": grid.get("pixel_height"),
        "crs_unit": grid.get("crs_unit"),
        "requires_projection_for_area": False,
        "evidence": evidence,
    }]


def _raster_feature_chip_semantic_hints(chips: list[dict] | None) -> list[dict]:
    if not chips:
        return []
    hints = []
    for chip in chips:
        chip_id = chip.get("chip_id", "chip")
        window = chip.get("window") or {}
        evidence = [
            (
                f"{chip_id} chip covers "
                f"{window.get('width')}x{window.get('height')} pixels"
            )
        ]
        for field, band_stats in (chip.get("bands") or {}).items():
            if band_stats.get("mean") is not None:
                evidence.append(f"{chip_id} {field} mean is {band_stats['mean']}")
            if band_stats.get("scaled_mean") is not None:
                evidence.append(
                    f"{chip_id} {field} scaled mean is {band_stats['scaled_mean']}"
                )
            if band_stats.get("top_values"):
                evidence.append(
                    f"{chip_id} {field} dominant values are {band_stats['top_values']}"
                )
        hints.append({
            "type": "raster_feature_chip",
            "value": "summary_window",
            "chip_id": chip_id,
            "sampling_strategy": chip.get("sampling_strategy"),
            "embedding_ready": True,
            "confidence": 0.82,
            "evidence": _dedupe_preserve_order(evidence),
        })
    return hints


def _raster_sidecar_theme_evidence(
    sidecar_metadata: dict | None,
    keywords: list[str],
) -> list[str]:
    if not sidecar_metadata:
        return []
    evidence = []
    metadata = sidecar_metadata.get("metadata", {})
    for label, value in _raster_sidecar_text_fields(metadata):
        evidence.extend(
            _keyword_evidence(
                _normalize_semantic_text(value),
                f"metadata {label}",
                keywords,
            )
        )
    return _dedupe_preserve_order(evidence)


def _raster_sidecar_text_fields(metadata: dict) -> list[tuple[str, str]]:
    properties = metadata.get("properties") or {}
    fields = []
    for label, value in [
        ("title", metadata.get("title") or properties.get("title")),
        (
            "description",
            metadata.get("description")
            or metadata.get("abstract")
            or properties.get("description")
            or properties.get("abstract"),
        ),
        ("collection", metadata.get("collection") or properties.get("collection")),
        ("lineage", metadata.get("lineage") or properties.get("lineage")),
    ]:
        if value:
            fields.append((label, str(value)))
    for keyword in _as_text_list(
        metadata.get("keywords")
        or metadata.get("keyword")
        or properties.get("keywords")
        or properties.get("keyword")
    ):
        fields.append(("keyword", keyword))
    for topic in _as_text_list(metadata.get("topic_categories") or metadata.get("topic")):
        fields.append(("topic", topic))
    return fields


def _as_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None and str(item) != ""]
    return [str(value)]


def _raster_sidecar_semantic_hints(sidecar_metadata: dict | None) -> list[dict]:
    if not sidecar_metadata:
        return []
    metadata = sidecar_metadata.get("metadata", {})
    sidecar_path = sidecar_metadata.get("path", "")
    kind = sidecar_metadata.get("kind", "metadata_sidecar")
    basename = os.path.basename(sidecar_path)
    hints = [{
        "type": "metadata_source",
        "value": kind,
        "confidence": 0.95,
        "evidence": [f"sidecar metadata file: {basename}"],
    }]

    properties = metadata.get("properties") or {}
    platform = properties.get("platform") or metadata.get("platform")
    if platform:
        hints.append({
            "type": "raster_platform",
            "value": str(platform),
            "confidence": 0.9,
            "evidence": [f"metadata platform is {platform}"],
        })

    collection = metadata.get("collection") or properties.get("collection")
    if collection:
        hints.append({
            "type": "metadata_collection",
            "value": str(collection),
            "confidence": 0.88,
            "evidence": [f"metadata collection is {collection}"],
        })

    datetime_value = (
        properties.get("datetime")
        or properties.get("start_datetime")
        or metadata.get("datetime")
        or metadata.get("date")
    )
    if datetime_value:
        hints.append({
            "type": "metadata_datetime",
            "value": str(datetime_value),
            "confidence": 0.86,
            "evidence": [f"metadata datetime is {datetime_value}"],
        })

    title = metadata.get("title") or properties.get("title")
    if title:
        hints.append({
            "type": "metadata_title",
            "value": str(title),
            "confidence": 0.84,
            "evidence": [f"metadata title is {title}"],
        })

    description = (
        metadata.get("description")
        or metadata.get("abstract")
        or properties.get("description")
        or properties.get("abstract")
    )
    if description:
        hints.append({
            "type": "metadata_description",
            "value": str(description),
            "confidence": 0.82,
            "evidence": ["metadata description/abstract is present"],
        })

    for keyword in _as_text_list(
        metadata.get("keywords")
        or metadata.get("keyword")
        or properties.get("keywords")
        or properties.get("keyword")
    ):
        hints.append({
            "type": "metadata_keyword",
            "value": keyword,
            "confidence": 0.82,
            "evidence": [f"metadata keyword is {keyword}"],
        })

    for topic in _as_text_list(metadata.get("topic_categories") or metadata.get("topic")):
        hints.append({
            "type": "metadata_topic",
            "value": topic,
            "confidence": 0.8,
            "evidence": [f"metadata topic category is {topic}"],
        })

    lineage = metadata.get("lineage") or properties.get("lineage")
    if lineage:
        hints.append({
            "type": "metadata_lineage",
            "value": str(lineage),
            "confidence": 0.82,
            "evidence": ["metadata lineage statement is present"],
        })

    gsd = _safe_float_or_none(properties.get("gsd") or metadata.get("gsd"))
    if gsd is not None:
        hints.append({
            "type": "raster_gsd",
            "value": gsd,
            "confidence": 0.86,
            "evidence": [f"metadata gsd is {gsd}"],
        })

    epsg_value = _safe_int_or_none(
        properties.get("proj:epsg")
        or metadata.get("proj:epsg")
        or metadata.get("epsg")
    )
    if epsg_value is not None:
        hints.append({
            "type": "projection_epsg",
            "value": epsg_value,
            "confidence": 0.86,
            "evidence": [f"metadata proj:epsg is {epsg_value}"],
        })

    instruments = properties.get("instruments") or metadata.get("instruments") or []
    if isinstance(instruments, str):
        instruments = [instruments]
    for instrument in instruments:
        hints.append({
            "type": "raster_instrument",
            "value": str(instrument),
            "confidence": 0.86,
            "evidence": [f"metadata instrument is {instrument}"],
        })

    for index, band in enumerate(_sidecar_eo_bands(metadata), start=1):
        common_name = band.get("common_name") or band.get("name")
        if not common_name:
            continue
        evidence = [f"metadata eo:bands[{index}] common_name is {common_name}"]
        if band.get("name"):
            evidence.append(f"metadata eo:bands[{index}] name is {band['name']}")
        hints.append({
            "type": "spectral_band_semantic",
            "field": f"band_{index}",
            "value": str(common_name),
            "confidence": 0.88,
            "evidence": evidence,
        })
    return hints


def _sidecar_eo_bands(metadata: dict) -> list[dict]:
    bands = []
    if isinstance(metadata.get("eo:bands"), list):
        bands.extend(item for item in metadata["eo:bands"] if isinstance(item, dict))
    for asset in (metadata.get("assets") or {}).values():
        if not isinstance(asset, dict):
            continue
        if isinstance(asset.get("eo:bands"), list):
            bands.extend(item for item in asset["eo:bands"] if isinstance(item, dict))
    return bands


def _normalize_semantic_text(value: object) -> str:
    text = "" if value is None else str(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _keyword_evidence(
    normalized_text: str,
    label: str,
    keywords: list[str],
) -> list[str]:
    evidence = []
    for keyword in keywords:
        normalized_keyword = _normalize_semantic_text(keyword)
        if not normalized_keyword:
            continue
        if _contains_keyword(normalized_text, normalized_keyword):
            evidence.append(f"{label} contains {_evidence_keyword(keyword, label)}")
    return _dedupe_preserve_order(evidence)


def _contains_keyword(normalized_text: str, normalized_keyword: str) -> bool:
    if not normalized_text:
        return False
    if " " in normalized_keyword:
        return normalized_keyword in normalized_text
    return bool(re.search(rf"\b{re.escape(normalized_keyword)}\b", normalized_text))


def _evidence_keyword(keyword: str, label: str) -> str:
    if keyword.lower() == "ndvi" and "description" in label:
        return "NDVI"
    return _normalize_semantic_text(keyword)


def _raster_range_evidence(rule_value: str, band_name: str, stats: dict) -> list[str]:
    band_stats = stats.get(band_name) or {}
    minimum = band_stats.get("min")
    maximum = band_stats.get("max")
    if minimum is None or maximum is None:
        return []
    if (
        rule_value == "ndvi"
        and -1.05 <= float(minimum) <= 1.05
        and -1.05 <= float(maximum) <= 1.05
    ):
        return [f"{band_name} value range fits NDVI [-1, 1]"]
    if rule_value == "slope" and 0.0 <= float(minimum) and float(maximum) <= 90.0:
        return [f"{band_name} value range fits slope degrees [0, 90]"]
    return []


def _raster_hint_confidence(
    evidence: list[str],
    has_filename_evidence: bool,
    has_range_evidence: bool,
) -> float:
    metadata_count = len(evidence)
    confidence = 0.55 + min(metadata_count, 3) * 0.12
    if has_filename_evidence:
        confidence += 0.12
    if has_range_evidence:
        confidence += 0.08
    return round(min(confidence, 0.99), 2)


def _dedupe_preserve_order(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        marker = str(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _profile_tabular(path: str) -> FusionSource:
    """Profile a tabular (CSV/Excel) data source."""
    df = _materialize_df(_read_tabular_lazy(path))

    columns = []
    stats = {}
    for col in df.columns:
        null_pct = round(df[col].isna().mean() * 100, 1)
        columns.append({"name": col, "dtype": str(df[col].dtype), "null_pct": null_pct})
        if pd.api.types.is_numeric_dtype(df[col]):
            stats[col] = {
                "min": float(df[col].min()) if not df[col].isna().all() else None,
                "max": float(df[col].max()) if not df[col].isna().all() else None,
                "mean": float(df[col].mean()) if not df[col].isna().all() else None,
            }
        else:
            stats[col] = {"unique": int(df[col].nunique())}

    return FusionSource(
        file_path=path,
        data_type="tabular",
        row_count=len(df),
        columns=columns,
        stats=stats,
    )


def _profile_point_cloud(path: str) -> FusionSource:
    """Profile a point cloud (LAS/LAZ) data source — metadata only."""
    columns = list(POINT_CLOUD_BASE_COLUMNS)
    stats = {}
    semantic_domain = None
    semantic_hints = []
    try:
        import laspy
        las_data = laspy.read(path)
        if hasattr(las_data, "__enter__") and hasattr(las_data, "__exit__"):
            with las_data as las:
                bounds, row_count, crs_str = _point_cloud_header_profile(las)
                columns, stats, semantic_domain, semantic_hints = (
                    _profile_point_cloud_dimensions(las, columns)
                )
        else:
            bounds, row_count, crs_str = _point_cloud_header_profile(las_data)
            columns, stats, semantic_domain, semantic_hints = (
                _profile_point_cloud_dimensions(las_data, columns)
            )
    except Exception:
        bounds = None
        row_count = 0
        crs_str = None

    return FusionSource(
        file_path=path,
        data_type="point_cloud",
        crs=crs_str,
        bounds=bounds,
        row_count=row_count,
        columns=columns,
        geometry_type="Point",
        stats=stats,
        semantic_domain=semantic_domain,
        semantic_hints=semantic_hints,
    )


def _point_cloud_header_profile(las: object) -> tuple[tuple, int, str | None]:
    header = las.header
    bounds = (
        float(header.x_min), float(header.y_min),
        float(header.x_max), float(header.y_max),
    )
    row_count = int(header.point_count)
    crs_str = None
    if hasattr(header, "parse_crs"):
        crs = header.parse_crs()
        if crs:
            crs_str = str(crs)
    return bounds, row_count, crs_str


def _profile_point_cloud_dimensions(
    las: object,
    base_columns: list[dict],
) -> tuple[list[dict], dict, str | None, list[dict]]:
    """Extract LAS dimension profiles and conservative semantic hints."""
    dimension_names = _point_cloud_dimension_names(las)
    columns = list(base_columns)
    stats = {}
    semantic_hints = []

    for base_name in ["x", "y", "z"]:
        values = _safe_las_array(las, base_name, dimension_names)
        if values is not None:
            stats[base_name] = _numeric_array_stats(values)

    for spec in POINT_CLOUD_DIMENSIONS:
        name = spec["name"]
        values = _safe_las_array(las, name, dimension_names)
        if values is None:
            continue
        columns.append({
            "name": name,
            "dtype": spec["dtype"],
            "null_pct": 0,
        })
        if name == "classification":
            stats[name] = _classification_stats(values)
            semantic_hints.extend(_classification_hints(stats[name]))
        else:
            stats[name] = _numeric_array_stats(values)
        semantic_hints.append({
            "type": "point_dimension_semantic",
            "field": name,
            "value": spec["semantic"],
            "confidence": 0.92,
            "evidence": [spec["evidence"]],
        })

    semantic_hints = _point_cloud_theme_hints(semantic_hints) + semantic_hints
    semantic_domain = "lidar" if semantic_hints else None
    return columns, stats, semantic_domain, semantic_hints


def _point_cloud_dimension_names(las: object) -> set[str]:
    names = set()
    for owner in [las, getattr(las, "header", None)]:
        point_format = getattr(owner, "point_format", None)
        dimension_names = getattr(point_format, "dimension_names", None)
        if dimension_names is None:
            continue
        try:
            names.update(str(name).lower() for name in dimension_names)
        except TypeError:
            continue
    return names


def _safe_las_array(
    las: object,
    dimension: str,
    dimension_names: set[str],
) -> np.ndarray | None:
    if dimension_names and dimension.lower() not in dimension_names:
        return None
    try:
        value = getattr(las, dimension)
    except Exception:
        return None
    try:
        values = np.asarray(value)
    except Exception:
        return None
    if values.size == 0:
        return None
    return values


def _numeric_array_stats(values: np.ndarray) -> dict:
    if not np.issubdtype(values.dtype, np.number):
        return {"min": None, "max": None, "mean": None}
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.nanmin(clean)),
        "max": float(np.nanmax(clean)),
        "mean": float(np.nanmean(clean)),
    }


def _classification_stats(values: np.ndarray) -> dict:
    codes, counts = np.unique(values.astype(np.int64), return_counts=True)
    classes = []
    for code, count in zip(codes, counts):
        label = LAS_CLASSIFICATION_LABELS.get(int(code), f"class_{int(code)}")
        classes.append({
            "code": int(code),
            "label": label,
            "count": int(count),
        })
    return {
        "unique": len(classes),
        "classes": classes,
    }


def _classification_hints(classification_stats: dict) -> list[dict]:
    hints = []
    for item in classification_stats.get("classes", []):
        label = item.get("label")
        code = item.get("code")
        if not label:
            continue
        hints.append({
            "type": "classification_class",
            "value": label,
            "class_code": code,
            "confidence": 0.9,
            "evidence": [
                f"classification class {code} ({label}) count {item.get('count', 0)}"
            ],
        })
    return hints


def _point_cloud_theme_hints(semantic_hints: list[dict]) -> list[dict]:
    values = {hint.get("value") for hint in semantic_hints}
    themes = []
    if "asprs_classification" in values:
        themes.append({
            "type": "point_cloud_theme",
            "value": "classified_lidar",
            "domain": "lidar",
            "confidence": 0.92,
            "evidence": ["classification dimension present"],
        })
    if "return_intensity" in values:
        themes.append({
            "type": "point_cloud_theme",
            "value": "intensity_lidar",
            "domain": "lidar",
            "confidence": 0.86,
            "evidence": ["intensity dimension present"],
        })
    if "rgb_color" in values:
        themes.append({
            "type": "point_cloud_theme",
            "value": "colorized_lidar",
            "domain": "lidar",
            "confidence": 0.86,
            "evidence": ["red/green/blue color dimensions present"],
        })
    return themes


def profile_postgis_source(table_name: str) -> FusionSource:
    """Profile a PostGIS table as a FusionSource.

    Queries the database for row count, SRID, bounding box, and column metadata.

    Args:
        table_name: PostGIS table name (optionally schema-qualified).

    Returns:
        FusionSource with postgis_table and postgis_srid populated.
    """
    import re
    from sqlalchemy import text
    from ..db_engine import get_engine

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]{0,126}$', table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")

    engine = get_engine()
    if not engine:
        raise ValueError("Database engine not available")

    with engine.connect() as conn:
        # Row count
        row = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).fetchone()
        row_count = row[0] if row else 0

        # SRID and bounds from geometry column
        srid = None
        bounds = None
        geometry_type = None
        try:
            meta = conn.execute(text(
                "SELECT srid, type FROM geometry_columns "
                f"WHERE f_table_name = :tbl"
            ), {"tbl": table_name.split(".")[-1]}).fetchone()
            if meta:
                srid = meta[0]
                geometry_type = meta[1]

            bbox = conn.execute(text(
                f'SELECT ST_XMin(ext), ST_YMin(ext), ST_XMax(ext), ST_YMax(ext) '
                f'FROM (SELECT ST_Extent(geom) AS ext FROM "{table_name}") sub'
            )).fetchone()
            if bbox and bbox[0] is not None:
                bounds = tuple(float(v) for v in bbox)
        except Exception as e:
            logger.warning("PostGIS metadata query failed for %s: %s", table_name, e)

        # Column metadata
        cols_rows = conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = :tbl ORDER BY ordinal_position"
        ), {"tbl": table_name.split(".")[-1]}).fetchall()

        columns = [
            {"name": c[0], "dtype": c[1], "null_pct": 0}
            for c in cols_rows if c[0] != "geom"
        ]

    crs_str = f"EPSG:{srid}" if srid else None

    return FusionSource(
        file_path=f"postgis://{table_name}",
        data_type="vector",
        crs=crs_str,
        bounds=bounds,
        row_count=row_count,
        columns=columns,
        geometry_type=geometry_type,
        postgis_table=table_name,
        postgis_srid=srid,
    )
