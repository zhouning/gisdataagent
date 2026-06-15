"""Data source profiling — detect type, CRS, bounds, columns, statistics."""
import logging
import os
import re

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
        stats = {}
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
            columns.append(column)
            if len(valid) > 0:
                stats[band_name] = {
                    "min": float(np.nanmin(valid)),
                    "max": float(np.nanmax(valid)),
                    "mean": float(np.nanmean(valid)),
                }

        semantic_domain, semantic_hints = _infer_raster_semantic_hints(
            path,
            columns,
            stats,
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


def _infer_raster_semantic_hints(
    path: str,
    columns: list[dict],
    stats: dict,
) -> tuple[str | None, list[dict]]:
    """Infer conservative semantic hints for common raster products."""
    filename = os.path.splitext(os.path.basename(path))[0]
    filename_text = _normalize_semantic_text(filename)
    theme_by_value: dict[str, dict] = {}
    band_hints = []

    for rule in RASTER_SEMANTIC_RULES:
        value = rule["value"]
        filename_evidence = _keyword_evidence(
            filename_text,
            "filename",
            rule["keywords"],
        )
        for column in columns:
            band_name = column.get("name", "")
            band_evidence = list(filename_evidence)

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
    semantic_hints = theme_hints + band_hints
    return semantic_domain, semantic_hints


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
