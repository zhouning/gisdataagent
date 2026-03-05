"""
Multi-modal Data Fusion Engine — intelligent fusion of heterogeneous data sources.

v7.0: Enhanced with four major improvements:
  - Vector embedding semantic matching (Gemini text-embedding-004) for long-tail fields
  - LLM-enhanced strategy routing (Gemini 2.0 Flash) for intent-aware fusion
  - Distributed/chunked computing for large datasets (>500K rows / >500MB)

v5.6: Enhanced with MGIM-inspired improvements:
  - Fuzzy semantic field matching (SequenceMatcher) replacing hardcoded-only groups
  - Active unit detection & conversion (m²↔亩, m↔km, etc.)
  - Data-aware strategy scoring (IoU, geometry type, data volume)
  - Multi-source fusion orchestration (N>2 sources via pairwise decomposition)
  - Enhanced quality validation (attribute ranges, topological integrity, statistical comparison)

v5.5: Self-contained engine (no ADK dependency) that profiles, aligns, and fuses
multi-modal GIS and non-GIS data. Exposed to agents via FusionToolset.

Supported data types:
  - vector:      GeoJSON, Shapefile, GPKG, KML
  - raster:      GeoTIFF, IMG, other GDAL formats
  - tabular:     CSV, Excel (.xlsx/.xls)
  - point_cloud: LAS/LAZ (metadata only — height extraction)
  - stream:      Real-time snapshot (via streaming_tools integration)

Fusion strategies:
  - spatial_join:     Vector × Vector spatial join
  - attribute_join:   Vector × Tabular attribute merge
  - zonal_statistics: Raster → Vector zone-based statistics
  - point_sampling:   Raster → Point location sampling
  - band_stack:       Raster × Raster band stacking
  - overlay:          Vector overlay analysis (union/intersection/difference)
  - time_snapshot:    Stream → temporal snapshot join
  - height_assign:    Point cloud → Vector height assignment
  - raster_vectorize: Raster → Vector conversion then join
  - nearest_join:     Vector × Vector nearest-neighbor join
"""

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from .db_engine import get_engine
from .gis_processors import _generate_output_path, _resolve_path
from .user_context import current_user_id

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding-based Semantic Matching (v7.0)
# ---------------------------------------------------------------------------

_embedding_cache: dict[str, list[float]] = {}
_EMBEDDING_MODEL = "text-embedding-004"


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for field names using Gemini embedding API.

    Uses module-level cache to avoid redundant API calls.
    Returns empty list on failure (graceful degradation).
    """
    uncached = [t for t in texts if t not in _embedding_cache]
    if uncached:
        try:
            from google import genai
            client = genai.Client()
            response = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=uncached,
            )
            for txt, emb in zip(uncached, response.embeddings):
                _embedding_cache[txt] = emb.values
        except Exception as e:
            logger.warning("Embedding API failed: %s — skipping embedding tier", e)
            return []
    return [_embedding_cache.get(t, []) for t in texts]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Raster Helpers
# ---------------------------------------------------------------------------

def _reproject_raster(
    src_path: str,
    target_crs: str,
    resampling: str = "bilinear",
) -> str:
    """Reproject a raster file to a target CRS.

    Args:
        src_path: Path to source raster.
        target_crs: Target CRS string (e.g. "EPSG:4326").
        resampling: Resampling method — nearest, bilinear, or cubic.

    Returns:
        Path to reprojected temporary GeoTIFF.
    """
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    resamp_map = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
    }
    resamp = resamp_map.get(resampling, Resampling.bilinear)

    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": target_crs,
            "transform": transform,
            "width": width,
            "height": height,
        })

        out_path = os.path.join(
            os.path.dirname(src_path),
            f"_reproj_{uuid.uuid4().hex[:8]}_{os.path.basename(src_path)}",
        )
        with rasterio.open(out_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=resamp,
                )

    return out_path


def _resample_raster_to_match(
    src_path: str,
    ref_path: str,
    resampling: str = "bilinear",
) -> str:
    """Resample a raster to match the grid of a reference raster.

    Args:
        src_path: Path to raster to resample.
        ref_path: Path to reference raster (target grid).
        resampling: Resampling method.

    Returns:
        Path to resampled temporary GeoTIFF.
    """
    import rasterio
    from rasterio.warp import reproject, Resampling

    resamp_map = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
    }
    resamp = resamp_map.get(resampling, Resampling.bilinear)

    with rasterio.open(ref_path) as ref:
        ref_transform = ref.transform
        ref_crs = ref.crs
        ref_width = ref.width
        ref_height = ref.height

    with rasterio.open(src_path) as src:
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": ref_crs,
            "transform": ref_transform,
            "width": ref_width,
            "height": ref_height,
        })

        out_path = os.path.join(
            os.path.dirname(src_path),
            f"_resamp_{uuid.uuid4().hex[:8]}_{os.path.basename(src_path)}",
        )
        with rasterio.open(out_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=ref_transform,
                    dst_crs=ref_crs,
                    resampling=resamp,
                )

    return out_path


# ---------------------------------------------------------------------------
# Large Dataset Detection & Chunked I/O (v7.0)
# ---------------------------------------------------------------------------

LARGE_ROW_THRESHOLD = 500_000
LARGE_FILE_MB = 500


def _is_large_dataset(file_path: str, row_hint: int = 0) -> bool:
    """Check if a dataset exceeds the large-data threshold.

    Returns True if row_hint > 500K or file size > 500MB.
    """
    if row_hint > LARGE_ROW_THRESHOLD:
        return True
    try:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        return size_mb > LARGE_FILE_MB
    except OSError:
        return False


def _read_vector_chunked(path: str, chunk_size: int = 100_000) -> gpd.GeoDataFrame:
    """Read a vector file, using chunked reading for large files.

    For files below the threshold, uses standard gpd.read_file().
    For large files, reads in chunks via fiona row slicing.
    """
    if not _is_large_dataset(path):
        return gpd.read_file(path)

    logger.info("Large vector file detected (%s), using chunked reading", path)
    import fiona

    chunks = []
    with fiona.open(path) as src:
        total = len(src)
        if total <= chunk_size:
            return gpd.read_file(path)
        for start in range(0, total, chunk_size):
            chunk = gpd.read_file(path, rows=slice(start, start + chunk_size))
            chunks.append(chunk)

    return pd.concat(chunks, ignore_index=True)


def _read_tabular_lazy(path: str):
    """Read a tabular file, using dask for large CSV files.

    Returns a dask DataFrame for large CSVs, pandas DataFrame otherwise.
    Callers that need pandas can call .compute() on dask results.
    """
    ext = os.path.splitext(path)[1].lower()
    if not _is_large_dataset(path):
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(path)
        return pd.read_csv(path, encoding="utf-8")

    logger.info("Large tabular file detected (%s), using lazy reading", path)
    if ext == ".csv":
        import dask.dataframe as dd
        return dd.read_csv(path, encoding="utf-8")
    # Excel not supported by dask — fallback to pandas
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8")


def _materialize_df(df) -> pd.DataFrame:
    """Convert dask DataFrame to pandas if needed."""
    if hasattr(df, "compute"):
        return df.compute()
    return df


def _fuse_large_datasets_spatial(
    gdf_left: gpd.GeoDataFrame,
    gdf_right: gpd.GeoDataFrame,
    predicate: str = "intersects",
    chunk_size: int = 50_000,
) -> gpd.GeoDataFrame:
    """Chunked spatial join for large datasets.

    Splits the left GeoDataFrame into chunks, joins each chunk
    with the right GeoDataFrame (using its spatial index), then concatenates.
    """
    if len(gdf_left) <= chunk_size:
        return gpd.sjoin(gdf_left, gdf_right, how="left", predicate=predicate)

    logger.info("Using chunked spatial join: %d left rows in %d-row chunks",
                len(gdf_left), chunk_size)
    results = []
    for start in range(0, len(gdf_left), chunk_size):
        chunk = gdf_left.iloc[start:start + chunk_size]
        joined = gpd.sjoin(chunk, gdf_right, how="left", predicate=predicate)
        results.append(joined)

    return pd.concat(results, ignore_index=True)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class FusionSource:
    """Profile of a single data source for fusion."""
    file_path: str
    data_type: str              # vector | raster | tabular | point_cloud | stream
    crs: Optional[str] = None
    bounds: Optional[tuple] = None   # (minx, miny, maxx, maxy)
    row_count: int = 0
    columns: list = field(default_factory=list)   # [{name, dtype, null_pct}]
    geometry_type: Optional[str] = None
    temporal_range: Optional[tuple] = None
    semantic_domain: Optional[str] = None
    stats: dict = field(default_factory=dict)      # {col: {min, max, mean, unique}}
    band_count: int = 0
    resolution: Optional[tuple] = None  # (x_res, y_res) for raster


@dataclass
class CompatibilityReport:
    """Result of compatibility assessment between data sources."""
    crs_compatible: bool = True
    spatial_overlap_iou: float = 0.0
    temporal_aligned: Optional[bool] = None
    field_matches: list = field(default_factory=list)   # [{left, right, confidence}]
    overall_score: float = 0.0
    recommended_strategies: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class FusionResult:
    """Result of a fusion operation."""
    output_path: str = ""
    strategy_used: str = ""
    row_count: int = 0
    column_count: int = 0
    quality_score: float = 0.0
    quality_warnings: list = field(default_factory=list)
    alignment_log: list = field(default_factory=list)
    duration_s: float = 0.0
    provenance: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy Matrix
# ---------------------------------------------------------------------------

STRATEGY_MATRIX: dict[tuple[str, str], list[str]] = {
    ("vector", "vector"):       ["spatial_join", "overlay", "nearest_join"],
    ("vector", "raster"):       ["zonal_statistics", "point_sampling"],
    ("raster", "vector"):       ["zonal_statistics", "point_sampling"],
    ("raster", "raster"):       ["band_stack"],
    ("vector", "tabular"):      ["attribute_join"],
    ("tabular", "vector"):      ["attribute_join"],
    ("vector", "stream"):       ["time_snapshot"],
    ("stream", "vector"):       ["time_snapshot"],
    ("vector", "point_cloud"):  ["height_assign"],
    ("point_cloud", "vector"):  ["height_assign"],
    ("raster", "tabular"):      ["raster_vectorize"],
}

# Unit conversion factors (source_unit → target_unit → factor)
UNIT_CONVERSIONS = {
    ("m2", "mu"):    1 / 666.67,       # 平方米 → 亩
    ("mu", "m2"):    666.67,
    ("m2", "ha"):    1 / 10000,
    ("ha", "m2"):    10000,
    ("mu", "ha"):    1 / 15,
    ("ha", "mu"):    15,
    ("m", "km"):     1 / 1000,
    ("km", "m"):     1000,
}

# Column name patterns for unit detection
UNIT_PATTERNS = {
    "mu": ["亩", "mu"],
    "m2": ["平方米", "m2", "sqm", "square_m"],
    "ha": ["公顷", "ha", "hectare"],
    "m":  ["米", "meter"],
    "km": ["千米", "公里", "km", "kilometer"],
}


# ---------------------------------------------------------------------------
# Table name
# ---------------------------------------------------------------------------

T_FUSION_OPS = "agent_fusion_operations"


# ---------------------------------------------------------------------------
# Data Source Profiling
# ---------------------------------------------------------------------------

def _detect_data_type(file_path: str) -> str:
    """Detect data type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    vector_exts = {".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".json"}
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
            columns.append({"name": band_name, "dtype": str(ds.dtypes[i - 1]), "null_pct": 0})
            if len(valid) > 0:
                stats[band_name] = {
                    "min": float(np.nanmin(valid)),
                    "max": float(np.nanmax(valid)),
                    "mean": float(np.nanmean(valid)),
                }

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
    )


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
    try:
        import laspy
        with laspy.read(path) as las:
            bounds = (
                float(las.header.x_min), float(las.header.y_min),
                float(las.header.x_max), float(las.header.y_max),
            )
            row_count = las.header.point_count
            crs_str = None
            if hasattr(las.header, "parse_crs") and las.header.parse_crs():
                crs_str = str(las.header.parse_crs())
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
        columns=[{"name": "x", "dtype": "float64", "null_pct": 0},
                 {"name": "y", "dtype": "float64", "null_pct": 0},
                 {"name": "z", "dtype": "float64", "null_pct": 0}],
        geometry_type="Point",
    )


# ---------------------------------------------------------------------------
# Compatibility Assessment
# ---------------------------------------------------------------------------

def assess_compatibility(
    sources: list[FusionSource],
    use_embedding: bool = False,
) -> CompatibilityReport:
    """Assess fusion compatibility between data sources.

    Checks CRS consistency, spatial overlap, and field semantic matches.

    Args:
        sources: List of profiled FusionSource objects.
        use_embedding: If True, enable Gemini embedding-based field matching.

    Returns:
        CompatibilityReport with overall score and recommendations.
    """
    if len(sources) < 2:
        return CompatibilityReport(
            warnings=["Need at least 2 data sources to assess compatibility"],
            overall_score=0.0,
        )

    warnings = []

    # --- CRS compatibility ---
    crs_set = {s.crs for s in sources if s.crs is not None}
    crs_compatible = len(crs_set) <= 1
    if not crs_compatible:
        warnings.append(f"CRS mismatch: {crs_set}. Auto-reprojection will be applied.")

    # --- Spatial overlap (IoU on bounding boxes) ---
    spatial_iou = _compute_spatial_overlap(sources)
    if spatial_iou < 0.01:
        no_bounds = [s for s in sources if s.bounds is None]
        has_bounds = [s for s in sources if s.bounds is not None]
        if len(has_bounds) >= 2:
            warnings.append("Very low spatial overlap between sources.")

    # --- Field semantic matching ---
    field_matches = _find_field_matches(sources, use_embedding=use_embedding)

    # --- Recommended strategies ---
    type_pair = (sources[0].data_type, sources[1].data_type)
    recommended = STRATEGY_MATRIX.get(type_pair, [])
    if not recommended:
        # Try reverse pair
        type_pair_rev = (sources[1].data_type, sources[0].data_type)
        recommended = STRATEGY_MATRIX.get(type_pair_rev, [])
    if not recommended:
        warnings.append(f"No built-in strategy for {type_pair[0]}+{type_pair[1]}. Manual strategy needed.")

    # --- Overall score ---
    score = 0.0
    if crs_compatible:
        score += 0.3
    elif len(crs_set) > 0:
        score += 0.15  # fixable via reprojection
    if spatial_iou > 0.1:
        score += 0.3
    elif any(s.data_type == "tabular" for s in sources):
        score += 0.2  # tabular doesn't need spatial overlap
    if field_matches:
        score += 0.2
    if recommended:
        score += 0.2
    score = min(score, 1.0)

    return CompatibilityReport(
        crs_compatible=crs_compatible,
        spatial_overlap_iou=round(spatial_iou, 4),
        field_matches=field_matches,
        overall_score=round(score, 2),
        recommended_strategies=recommended,
        warnings=warnings,
    )


def _compute_spatial_overlap(sources: list[FusionSource]) -> float:
    """Compute IoU of bounding boxes between first two sources with bounds."""
    bounded = [s for s in sources if s.bounds is not None]
    if len(bounded) < 2:
        return 0.0

    b1 = box(*bounded[0].bounds)
    b2 = box(*bounded[1].bounds)

    if not b1.intersects(b2):
        return 0.0

    intersection = b1.intersection(b2).area
    union = b1.union(b2).area
    return intersection / union if union > 0 else 0.0


# Module-level cache for catalog-driven equivalence groups
_catalog_equiv_cache: list[set] | None = None


def _load_catalog_equiv_groups() -> list[set]:
    """Load equivalence groups from semantic_catalog.yaml common_aliases."""
    global _catalog_equiv_cache
    if _catalog_equiv_cache is not None:
        return _catalog_equiv_cache

    try:
        import yaml
        catalog_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "semantic_catalog.yaml"
        )
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = yaml.safe_load(f)

        groups = []
        for domain in catalog.get("domains", []):
            aliases = domain.get("common_aliases", [])
            if len(aliases) >= 2:
                groups.append({a.lower() for a in aliases})
        _catalog_equiv_cache = groups
        return groups
    except Exception:
        _catalog_equiv_cache = []
        return []


def _get_equiv_groups() -> list[set]:
    """Get merged equivalence groups: hardcoded + catalog-driven."""
    hardcoded = [
        {"area", "面积", "zmj", "tbmj", "mj", "shape_area"},
        {"name", "名称", "mc", "dlmc", "qsdwmc", "dkmc"},
        {"code", "编码", "dm", "dlbm", "bm", "dkbm"},
        {"type", "类型", "lx", "dllx", "tdlylx"},
        {"slope", "坡度", "pd", "slope_deg"},
        {"id", "objectid", "fid", "gid", "pkid"},
        {"population", "人口", "rk", "rksl", "pop"},
        {"address", "地址", "dz", "addr", "location"},
        {"elevation", "高程", "dem", "gc", "alt", "height"},
        {"perimeter", "周长", "zc", "shape_length"},
    ]

    catalog_groups = _load_catalog_equiv_groups()

    # Merge: if a catalog group overlaps with a hardcoded group, union them
    merged = [set(g) for g in hardcoded]
    for cg in catalog_groups:
        found_overlap = False
        for mg in merged:
            if mg & cg:
                mg |= cg
                found_overlap = True
                break
        if not found_overlap:
            merged.append(set(cg))

    return merged


def _tokenize_field_name(name: str) -> list[str]:
    """Split a field name into tokens by underscore, camelCase, and digit boundaries.

    Examples:
        "land_use_type" → ["land", "use", "type"]
        "landUseType"   → ["land", "use", "type"]
        "area2d"        → ["area", "2", "d"]
    """
    # Split by underscores first
    parts = name.replace("-", "_").split("_")
    tokens = []
    for part in parts:
        # Split camelCase and digit boundaries
        sub = re.sub(r"([a-z])([A-Z])", r"\1_\2", part)
        sub = re.sub(r"([A-Za-z])(\d)", r"\1_\2", sub)
        sub = re.sub(r"(\d)([A-Za-z])", r"\1_\2", sub)
        tokens.extend(t.lower() for t in sub.split("_") if t)
    return tokens


def _tokenized_similarity(name_a: str, name_b: str) -> float:
    """Compute similarity between two field names using tokenized comparison.

    Weighted blend: 60% Jaccard token overlap + 40% SequenceMatcher ratio.
    """
    tokens_a = set(_tokenize_field_name(name_a))
    tokens_b = set(_tokenize_field_name(name_b))

    if not tokens_a or not tokens_b:
        return 0.0

    # Jaccard
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    jaccard = intersection / union if union > 0 else 0.0

    # SequenceMatcher on full name
    seq_ratio = SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()

    return 0.6 * jaccard + 0.4 * seq_ratio


def _types_compatible(dtype_a: str, dtype_b: str) -> bool:
    """Check if two column data types are compatible for semantic matching.

    Prevents numeric fields from matching text fields (e.g., slope vs slope_type).
    """
    if not dtype_a or not dtype_b:
        return True  # unknown types → allow match

    numeric_indicators = {"int", "float", "double", "numeric", "decimal", "number"}
    text_indicators = {"object", "str", "string", "text", "char", "varchar", "category"}

    a_lower = dtype_a.lower()
    b_lower = dtype_b.lower()

    a_numeric = any(ind in a_lower for ind in numeric_indicators)
    b_numeric = any(ind in b_lower for ind in numeric_indicators)
    a_text = any(ind in a_lower for ind in text_indicators)
    b_text = any(ind in b_lower for ind in text_indicators)

    # Block numeric↔text mismatches
    if (a_numeric and b_text) or (a_text and b_numeric):
        return False

    return True


def _find_field_matches(
    sources: list[FusionSource],
    use_embedding: bool = False,
) -> list[dict]:
    """Find semantically matching fields across sources.

    Uses progressive semantic matching tiers:
      1. Exact match (case-insensitive) — confidence 1.0
      2. Equivalence group match (hardcoded + catalog-driven) — confidence 0.8
      2.5. Embedding match (Gemini text-embedding-004, opt-in) — confidence 0.78
      3. Unit-aware matching — confidence 0.75
      4. Tokenized fuzzy match with type compatibility — confidence 0.5-0.7
    """
    if len(sources) < 2:
        return []

    matches = []
    left_cols = {c["name"].lower(): c["name"] for c in sources[0].columns}
    right_cols = {c["name"].lower(): c["name"] for c in sources[1].columns}

    # Build dtype maps for type compatibility checking
    left_dtypes = {c["name"].lower(): c.get("dtype", "") for c in sources[0].columns}
    right_dtypes = {c["name"].lower(): c.get("dtype", "") for c in sources[1].columns}

    # Tier 1: Exact match (case-insensitive)
    matched_right = set()
    for lk, lv in left_cols.items():
        if lk in right_cols:
            matches.append({"left": lv, "right": right_cols[lk], "confidence": 1.0})
            matched_right.add(lk)

    # Tier 2: Known equivalence patterns (hardcoded + catalog-driven)
    equiv_groups = _get_equiv_groups()

    for group in equiv_groups:
        left_hit = [(lk, lv) for lk, lv in left_cols.items() if lk in group]
        right_hit = [(rk, rv) for rk, rv in right_cols.items()
                     if rk in group and rk not in matched_right]
        for rk, rv in right_hit:
            for _, lv in left_hit:
                if lv.lower() != rv.lower():
                    matches.append({"left": lv, "right": rv, "confidence": 0.8})
                    matched_right.add(rk)
                    break

    # Tier 2.5: Embedding-based semantic matching (opt-in, Gemini API)
    if use_embedding:
        unmatched_left_emb = {lk: lv for lk, lv in left_cols.items()
                              if not any(m["left"].lower() == lk for m in matches)}
        unmatched_right_emb = {rk: rv for rk, rv in right_cols.items()
                               if rk not in matched_right}
        if unmatched_left_emb and unmatched_right_emb:
            left_texts = [f"{lv} ({left_dtypes.get(lk, '')})"
                          for lk, lv in unmatched_left_emb.items()]
            right_texts = [f"{rv} ({right_dtypes.get(rk, '')})"
                           for rk, rv in unmatched_right_emb.items()]
            left_embeddings = _get_embeddings(left_texts)
            right_embeddings = _get_embeddings(right_texts)

            if left_embeddings and right_embeddings:
                left_keys = list(unmatched_left_emb.keys())
                right_keys = list(unmatched_right_emb.keys())
                for i, lk in enumerate(left_keys):
                    if not left_embeddings[i]:
                        continue
                    best_sim = 0.0
                    best_rk = None
                    for j, rk in enumerate(right_keys):
                        if rk in matched_right or not right_embeddings[j]:
                            continue
                        if not _types_compatible(
                            left_dtypes.get(lk, ""), right_dtypes.get(rk, "")
                        ):
                            continue
                        sim = _cosine_similarity(
                            left_embeddings[i], right_embeddings[j]
                        )
                        if sim > best_sim and sim >= 0.75:
                            best_sim = sim
                            best_rk = rk
                    if best_rk is not None:
                        matches.append({
                            "left": unmatched_left_emb[lk],
                            "right": unmatched_right_emb[best_rk],
                            "confidence": 0.78,
                            "match_type": "embedding",
                            "similarity": round(best_sim, 3),
                        })
                        matched_right.add(best_rk)

    # Tier 3: Unit-aware matching
    for lk, lv in left_cols.items():
        if any(m["left"].lower() == lk for m in matches):
            continue
        for rk, rv in right_cols.items():
            if rk in matched_right:
                continue
            left_unit = _detect_unit(lk)
            right_unit = _detect_unit(rk)
            if left_unit and right_unit and left_unit != right_unit:
                left_base = _strip_unit_suffix(lk)
                right_base = _strip_unit_suffix(rk)
                if left_base and right_base:
                    base_ratio = SequenceMatcher(None, left_base, right_base).ratio()
                    if base_ratio >= 0.6:
                        matches.append({
                            "left": lv, "right": rv, "confidence": 0.75,
                            "match_type": "unit_aware",
                            "left_unit": left_unit, "right_unit": right_unit,
                        })
                        matched_right.add(rk)

    # Tier 4: Tokenized fuzzy matching with type compatibility
    unmatched_left = {lk: lv for lk, lv in left_cols.items()
                      if not any(m["left"].lower() == lk for m in matches)}
    unmatched_right = {rk: rv for rk, rv in right_cols.items()
                       if rk not in matched_right}

    for lk, lv in unmatched_left.items():
        if len(lk) < 3:
            continue
        best_score = 0.0
        best_rk = None
        for rk, rv in unmatched_right.items():
            if len(rk) < 3:
                continue
            # Type compatibility gate
            if not _types_compatible(left_dtypes.get(lk, ""), right_dtypes.get(rk, "")):
                continue
            # Use original names for tokenization (preserves camelCase)
            score = _tokenized_similarity(lv, unmatched_right[rk])
            if score > best_score and score >= 0.65:
                best_score = score
                best_rk = rk
        if best_rk is not None:
            confidence = round(0.5 + best_score * 0.2, 2)
            matches.append({
                "left": lv, "right": unmatched_right[best_rk],
                "confidence": confidence, "match_type": "fuzzy",
            })
            matched_right.add(best_rk)

    return matches


# ---------------------------------------------------------------------------
# Unit Detection & Conversion (v5.6 — activated from dormant constants)
# ---------------------------------------------------------------------------

def _detect_unit(column_name: str) -> Optional[str]:
    """Detect measurement unit from column name using UNIT_PATTERNS.

    Returns unit key (e.g., 'mu', 'm2', 'ha') or None.
    """
    col_lower = column_name.lower()
    for unit_key, patterns in UNIT_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in col_lower:
                return unit_key
    return None


def _strip_unit_suffix(column_name: str) -> str:
    """Strip unit-related suffix from column name to get base semantic name."""
    col_lower = column_name.lower()
    for patterns in UNIT_PATTERNS.values():
        for pattern in patterns:
            p = pattern.lower()
            if col_lower.endswith(p):
                base = col_lower[:-len(p)].rstrip("_- ")
                if base:
                    return base
    return col_lower


def _convert_column_units(
    data: pd.DataFrame,
    column: str,
    from_unit: str,
    to_unit: str,
    log: list[str],
) -> None:
    """Convert numeric column values from one unit to another (in-place)."""
    factor = UNIT_CONVERSIONS.get((from_unit, to_unit))
    if factor is None:
        log.append(f"No conversion factor for {from_unit} → {to_unit}")
        return
    if column not in data.columns:
        return
    if pd.api.types.is_numeric_dtype(data[column]):
        data[column] = data[column] * factor
        log.append(f"Converted '{column}': {from_unit} → {to_unit} (×{factor:.6g})")


# ---------------------------------------------------------------------------
# Semantic Alignment
# ---------------------------------------------------------------------------

def align_sources(
    sources: list[FusionSource],
    report: CompatibilityReport,
    target_crs: Optional[str] = None,
) -> tuple[list, list[str]]:
    """Align data sources for fusion: CRS unification, unit conversion, field renaming.

    v5.6 enhancements:
      - Automatic unit conversion for matched fields with different units
      - Raster CRS awareness in alignment log

    Args:
        sources: Profiled source list.
        report: Compatibility report (used for unit-aware field matches).
        target_crs: Target CRS (default: use first source's CRS).

    Returns:
        Tuple of (loaded data objects, alignment log messages).
    """
    log = []
    loaded = []

    # Determine target CRS
    if target_crs is None:
        crs_sources = [s for s in sources if s.crs is not None]
        target_crs = crs_sources[0].crs if crs_sources else "EPSG:4326"

    for src in sources:
        if src.data_type == "vector":
            gdf = _read_vector_chunked(src.file_path)
            if gdf.crs and str(gdf.crs) != target_crs:
                gdf = gdf.to_crs(target_crs)
                log.append(f"Reprojected {os.path.basename(src.file_path)} "
                           f"from {src.crs} to {target_crs}")
            loaded.append(("vector", gdf))

        elif src.data_type == "raster":
            raster_path = src.file_path
            if src.crs and src.crs != target_crs:
                try:
                    raster_path = _reproject_raster(src.file_path, target_crs)
                    log.append(f"Reprojected raster {os.path.basename(src.file_path)} "
                               f"from {src.crs} to {target_crs}")
                except Exception as e:
                    log.append(f"Raster reprojection failed for "
                               f"{os.path.basename(src.file_path)}: {e} — using original")
            loaded.append(("raster", raster_path))

        elif src.data_type == "tabular":
            df = _materialize_df(_read_tabular_lazy(src.file_path))
            loaded.append(("tabular", df))

        elif src.data_type == "point_cloud":
            loaded.append(("point_cloud", src.file_path))

        else:
            loaded.append((src.data_type, src.file_path))

    # Resolve naming conflicts between vector/tabular pairs
    if len(loaded) >= 2:
        _resolve_column_conflicts(loaded, log)

    # v5.6: Apply unit conversions for unit-aware field matches
    if report and report.field_matches:
        _apply_unit_conversions(loaded, report.field_matches, log)

    return loaded, log


def _apply_unit_conversions(
    loaded: list,
    field_matches: list[dict],
    log: list[str],
) -> None:
    """Apply unit conversions for field matches with different units (in-place).

    Converts the second source's column to match the first source's unit.
    """
    for match in field_matches:
        if match.get("match_type") != "unit_aware":
            continue
        left_unit = match.get("left_unit")
        right_unit = match.get("right_unit")
        right_col = match.get("right", "")
        if not (left_unit and right_unit and right_col):
            continue

        # Find the second data source (where conversion should happen)
        for dtype, data in loaded:
            if isinstance(data, (gpd.GeoDataFrame, pd.DataFrame)):
                if right_col in data.columns:
                    _convert_column_units(data, right_col, right_unit, left_unit, log)
                    break


def _resolve_column_conflicts(loaded: list, log: list[str]) -> None:
    """Rename conflicting columns between data sources (in-place)."""
    if len(loaded) < 2:
        return

    def _get_columns(item):
        dtype, data = item
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            return set(c for c in data.columns if c != "geometry")
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            return set(data.columns)
        return set()

    cols_0 = _get_columns(loaded[0])
    cols_1 = _get_columns(loaded[1])
    conflicts = cols_0 & cols_1

    if conflicts:
        # Rename in the second source by adding _right suffix
        dtype_1, data_1 = loaded[1]
        if isinstance(data_1, (gpd.GeoDataFrame, pd.DataFrame)):
            rename_map = {c: f"{c}_right" for c in conflicts if c != "geometry"}
            if rename_map:
                data_1.rename(columns=rename_map, inplace=True)
                log.append(f"Renamed conflicting columns in source 2: "
                           f"{list(rename_map.keys())} → {list(rename_map.values())}")


# ---------------------------------------------------------------------------
# Fusion Execution
# ---------------------------------------------------------------------------

def execute_fusion(
    aligned_data: list[tuple[str, object]],
    strategy: str,
    sources: list[FusionSource],
    params: Optional[dict] = None,
    report: CompatibilityReport | None = None,
    user_hint: str = "",
) -> FusionResult:
    """Execute a fusion strategy on aligned data.

    Args:
        aligned_data: List of (data_type, data_object) tuples from align_sources.
        strategy: Fusion strategy name ('auto', 'llm_auto', or specific strategy).
        sources: Original source profiles (for provenance).
        params: Strategy-specific parameters (join_column, spatial_predicate, etc.).
        report: Compatibility report (used by LLM routing).
        user_hint: User intent description (used by LLM routing).

    Returns:
        FusionResult with output path and quality metrics.
    """
    params = params or {}
    start = time.time()

    use_llm = strategy == "llm_auto"
    if strategy in ("auto", "llm_auto"):
        strategy = _auto_select_strategy(
            aligned_data, sources,
            report=report, user_hint=user_hint, use_llm=use_llm,
        )

    strategy_fn = _STRATEGY_REGISTRY.get(strategy)
    if not strategy_fn:
        raise ValueError(f"Unknown fusion strategy: {strategy}. "
                         f"Available: {list(_STRATEGY_REGISTRY.keys())}")

    # v5.6: Multi-source orchestration for N>2 inputs
    if len(aligned_data) > 2:
        return _orchestrate_multisource(aligned_data, strategy, sources, params)

    output_gdf, alignment_log = strategy_fn(aligned_data, params)

    # Save output
    output_path = _generate_output_path("fused", "geojson")
    output_gdf.to_file(output_path, driver="GeoJSON")

    duration = round(time.time() - start, 2)

    # Quality validation
    quality = validate_quality(output_gdf, sources)

    return FusionResult(
        output_path=output_path,
        strategy_used=strategy,
        row_count=len(output_gdf),
        column_count=len([c for c in output_gdf.columns if c != "geometry"]),
        quality_score=quality["score"],
        quality_warnings=quality["warnings"],
        alignment_log=alignment_log,
        duration_s=duration,
        provenance={
            "sources": [s.file_path for s in sources],
            "strategy": strategy,
            "params": params,
        },
    )


def _auto_select_strategy(
    aligned_data: list[tuple[str, object]],
    sources: list[FusionSource],
    report: CompatibilityReport | None = None,
    user_hint: str = "",
    use_llm: bool = False,
) -> str:
    """Automatically select the best fusion strategy based on data characteristics.

    v7.0: Optional LLM-enhanced routing via use_llm=True.
    v5.6: Data-aware scoring replaces always-pick-first approach (MGIM-inspired
    context-aware reasoning). Considers:
      - Spatial overlap IoU (prefer nearest_join when low)
      - Geometry type compatibility (point vs polygon)
      - Data volume ratio
      - Null rate burden
    """
    if len(aligned_data) < 2:
        raise ValueError("Need at least 2 data sources for fusion.")

    type_pair = (aligned_data[0][0], aligned_data[1][0])
    strategies = STRATEGY_MATRIX.get(type_pair, [])
    if not strategies:
        type_pair_rev = (aligned_data[1][0], aligned_data[0][0])
        strategies = STRATEGY_MATRIX.get(type_pair_rev, [])

    if not strategies:
        raise ValueError(f"No strategy available for {type_pair[0]} + {type_pair[1]}")

    if len(strategies) == 1:
        return strategies[0]

    # Rule-based scoring
    best_rule = _score_strategies(strategies, aligned_data, sources)

    if not use_llm:
        return best_rule

    # LLM-enhanced routing: consult Gemini for strategy recommendation
    llm_strategy, reasoning = _llm_select_strategy(
        strategies, sources, report, user_hint
    )
    if llm_strategy:
        logger.info("LLM recommended strategy: %s — %s", llm_strategy, reasoning)
        return llm_strategy

    return best_rule


def _score_strategies(
    candidates: list[str],
    aligned_data: list[tuple[str, object]],
    sources: list[FusionSource],
) -> str:
    """Score candidate strategies and return the best one.

    Scoring heuristics:
      - spatial_join: prefers high IoU + polygon geometry
      - nearest_join: prefers low IoU or point geometry
      - overlay: prefers polygon × polygon with moderate overlap
      - point_sampling: prefers point vector + raster
      - zonal_statistics: prefers polygon vector + raster
    """
    scores = {}
    iou = _compute_spatial_overlap(sources) if len(sources) >= 2 else 0.0
    geom_types = [s.geometry_type for s in sources if s.geometry_type]
    has_point = any("point" in (g or "").lower() for g in geom_types)
    has_polygon = any("polygon" in (g or "").lower() for g in geom_types)
    row_ratio = 1.0
    if len(sources) >= 2 and sources[0].row_count > 0 and sources[1].row_count > 0:
        row_ratio = min(sources[0].row_count, sources[1].row_count) / \
                    max(sources[0].row_count, sources[1].row_count)

    for strategy in candidates:
        score = 1.0  # base score

        if strategy == "spatial_join":
            score += 0.3 if iou > 0.1 else -0.2
            score += 0.2 if has_polygon else 0.0
            score += 0.1 if row_ratio > 0.3 else -0.1

        elif strategy == "nearest_join":
            score += 0.3 if iou < 0.1 else -0.1
            score += 0.2 if has_point else 0.0

        elif strategy == "overlay":
            score += 0.2 if has_polygon else -0.3
            score += 0.1 if 0.05 < iou < 0.8 else -0.1

        elif strategy == "zonal_statistics":
            score += 0.3 if has_polygon else -0.2

        elif strategy == "point_sampling":
            score += 0.3 if has_point else -0.2

        scores[strategy] = round(score, 2)

    return max(scores, key=scores.get)


def _llm_select_strategy(
    candidates: list[str],
    sources: list[FusionSource],
    report: CompatibilityReport | None = None,
    user_hint: str = "",
) -> tuple[str, str]:
    """Use Gemini to reason about the best fusion strategy.

    Returns (selected_strategy, reasoning) or ("", "") on failure.
    """
    source_info = json.dumps([{
        "file": os.path.basename(s.file_path),
        "type": s.data_type,
        "rows": s.row_count,
        "geometry": s.geometry_type,
        "columns": len(s.columns),
    } for s in sources], ensure_ascii=False, indent=2)

    report_info = ""
    if report:
        report_info = (
            f"CRS兼容: {report.crs_compatible}\n"
            f"空间重叠IoU: {report.spatial_overlap_iou}\n"
            f"字段匹配数: {len(report.field_matches)}\n"
            f"总体评分: {report.overall_score}"
        )

    prompt = (
        "你是多模态数据融合专家。根据数据源特征和兼容性报告，"
        "从候选策略中选择最佳融合策略并给出简短理由。\n\n"
        f"数据源:\n{source_info}\n\n"
        f"兼容性报告:\n{report_info}\n\n"
        f"候选策略: {candidates}\n"
        + (f"用户意图: {user_hint}\n" if user_hint else "")
        + '\n请返回JSON: {"strategy": "策略名", "reasoning": "理由"}\n'
        "只返回JSON。"
    )

    try:
        from google import genai
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fence if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        strategy = result.get("strategy", "")
        reasoning = result.get("reasoning", "")
        if strategy in candidates:
            return strategy, reasoning
        logger.warning("LLM suggested '%s' not in candidates %s", strategy, candidates)
    except Exception as e:
        logger.warning("LLM strategy routing failed: %s", e)

    return "", ""


# ---------------------------------------------------------------------------
# Multi-Source Fusion Orchestration (v5.6)
# ---------------------------------------------------------------------------

def _orchestrate_multisource(
    aligned_data: list[tuple[str, object]],
    strategy: str,
    sources: list[FusionSource],
    params: dict,
) -> FusionResult:
    """Orchestrate fusion of N>2 sources via pairwise decomposition.

    Fuses sources progressively: (s0 ⊕ s1) → intermediate → (intermediate ⊕ s2) → ...
    Selects optimal pairing order: vector sources first, then raster, then tabular.
    """
    start = time.time()
    all_log = []

    # Sort by priority: vector first (accumulates geometry), then others
    type_priority = {"vector": 0, "raster": 1, "tabular": 2, "point_cloud": 3, "stream": 4}
    indexed = list(enumerate(aligned_data))
    indexed.sort(key=lambda x: type_priority.get(x[1][0], 9))
    ordered_data = [item for _, item in indexed]
    ordered_sources = [sources[i] for i, _ in indexed]

    # Pairwise fusion: accumulate into the first result
    current_data = ordered_data[0]
    current_source = ordered_sources[0]

    for i in range(1, len(ordered_data)):
        pair = [current_data, ordered_data[i]]
        pair_sources = [current_source, ordered_sources[i]]

        # Select strategy for this pair
        pair_strategy = strategy
        if pair_strategy == "auto" or pair_strategy not in _STRATEGY_REGISTRY:
            pair_strategy = _auto_select_strategy(pair, pair_sources)

        strategy_fn = _STRATEGY_REGISTRY.get(pair_strategy)
        if not strategy_fn:
            all_log.append(f"Skipping source {i}: no strategy for pair")
            continue

        result_gdf, step_log = strategy_fn(pair, params)
        all_log.extend(step_log)
        all_log.append(f"Step {i}/{len(ordered_data)-1}: "
                       f"{pair[0][0]}+{pair[1][0]} via {pair_strategy} → {len(result_gdf)} rows")

        # Update current for next iteration
        current_data = ("vector", result_gdf)
        current_source = FusionSource(
            file_path="<intermediate>",
            data_type="vector",
            row_count=len(result_gdf),
            columns=[{"name": c, "dtype": str(result_gdf[c].dtype), "null_pct": 0}
                     for c in result_gdf.columns if c != "geometry"],
        )

    # Final output
    final_gdf = current_data[1]
    if not isinstance(final_gdf, gpd.GeoDataFrame):
        raise ValueError("Multi-source fusion did not produce a GeoDataFrame.")

    output_path = _generate_output_path("fused_multi", "geojson")
    final_gdf.to_file(output_path, driver="GeoJSON")

    duration = round(time.time() - start, 2)
    quality = validate_quality(final_gdf, sources)

    return FusionResult(
        output_path=output_path,
        strategy_used=f"multi_source({strategy})",
        row_count=len(final_gdf),
        column_count=len([c for c in final_gdf.columns if c != "geometry"]),
        quality_score=quality["score"],
        quality_warnings=quality["warnings"],
        alignment_log=all_log,
        duration_s=duration,
        provenance={
            "sources": [s.file_path for s in sources],
            "strategy": strategy,
            "params": params,
            "steps": len(ordered_data) - 1,
        },
    )


# --- Strategy implementations ---

def _extract_geodataframe(aligned: list, index: int) -> gpd.GeoDataFrame:
    """Extract a GeoDataFrame from aligned data at the given index."""
    dtype, data = aligned[index]
    if isinstance(data, gpd.GeoDataFrame):
        return data
    raise ValueError(f"Expected GeoDataFrame at index {index}, got {type(data)}")


def _strategy_spatial_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Spatial join between two vector datasets."""
    log = []
    predicate = params.get("spatial_predicate", "intersects")

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = _fuse_large_datasets_spatial(gdf_left, gdf_right, predicate=predicate)

    # Clean up index_right column
    if "index_right" in result.columns:
        result = result.drop(columns=["index_right"])

    log.append(f"Spatial join ({predicate}): {len(gdf_left)} left × {len(gdf_right)} right → {len(result)} rows")
    return result, log


def _strategy_overlay(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Vector overlay analysis."""
    log = []
    how = params.get("overlay_how", "union")

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = gpd.overlay(gdf_left, gdf_right, how=how)
    log.append(f"Overlay ({how}): {len(gdf_left)} + {len(gdf_right)} → {len(result)} features")
    return result, log


def _strategy_nearest_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Nearest-neighbor spatial join."""
    log = []

    gdf_left = _extract_geodataframe(aligned, 0)
    gdf_right = _extract_geodataframe(aligned, 1)

    result = gpd.sjoin_nearest(gdf_left, gdf_right, how="left")

    if "index_right" in result.columns:
        result = result.drop(columns=["index_right"])

    log.append(f"Nearest join: {len(gdf_left)} left × {len(gdf_right)} right → {len(result)} rows")
    return result, log


def _strategy_attribute_join(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Attribute join between vector/tabular data on a key column."""
    log = []
    join_column = params.get("join_column", "")

    # Find the vector and tabular sources
    gdf = None
    df = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            df = data

    if gdf is None or df is None:
        raise ValueError("attribute_join requires one vector and one tabular source.")

    # Auto-detect join column if not specified
    if not join_column:
        join_column = _auto_detect_join_column(gdf, df)
        log.append(f"Auto-detected join column: {join_column}")

    if join_column not in gdf.columns:
        raise ValueError(f"Join column '{join_column}' not found in vector data.")

    # Find matching column in tabular data
    right_col = join_column
    if right_col not in df.columns:
        # Try case-insensitive match
        for c in df.columns:
            if c.lower() == join_column.lower():
                right_col = c
                break
        else:
            # Try _right suffix (added by conflict resolution)
            right_suffixed = f"{join_column}_right"
            if right_suffixed in df.columns:
                right_col = right_suffixed
            else:
                for c in df.columns:
                    if c.lower() == right_suffixed.lower():
                        right_col = c
                        break
                else:
                    raise ValueError(f"Join column '{join_column}' not found in tabular data.")

    result = gdf.merge(df, left_on=join_column, right_on=right_col, how="left")
    if not isinstance(result, gpd.GeoDataFrame):
        result = gpd.GeoDataFrame(result, geometry="geometry", crs=gdf.crs)

    log.append(f"Attribute join on '{join_column}': {len(gdf)} rows → {len(result)} rows, "
               f"+{len(df.columns) - 1} columns")
    return result, log


def _strategy_zonal_statistics(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Compute raster statistics within vector polygon zones."""
    from rasterstats import zonal_stats

    log = []
    stats_list = params.get("stats", ["mean", "min", "max", "count"])

    # Find vector and raster sources
    gdf = None
    raster_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "raster" and isinstance(data, str):
            raster_path = data

    if gdf is None or raster_path is None:
        raise ValueError("zonal_statistics requires one vector and one raster source.")

    zs = zonal_stats(gdf, raster_path, stats=stats_list)
    stats_df = pd.DataFrame(zs)

    # Prefix stats columns
    stats_df.columns = [f"raster_{c}" for c in stats_df.columns]

    result = gdf.copy()
    for col in stats_df.columns:
        result[col] = stats_df[col].values

    log.append(f"Zonal statistics: {len(gdf)} zones × {len(stats_list)} stats → "
               f"+{len(stats_df.columns)} columns")
    return result, log


def _strategy_point_sampling(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Sample raster values at point locations."""
    import rasterio

    log = []

    gdf = None
    raster_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "raster" and isinstance(data, str):
            raster_path = data

    if gdf is None or raster_path is None:
        raise ValueError("point_sampling requires one vector (point) and one raster source.")

    with rasterio.open(raster_path) as src:
        coords = [(geom.x, geom.y) for geom in gdf.geometry if geom is not None]
        samples = list(src.sample(coords))

    result = gdf.copy()
    for band_idx in range(len(samples[0]) if samples else 0):
        result[f"raster_band_{band_idx + 1}"] = [s[band_idx] for s in samples]

    log.append(f"Point sampling: {len(gdf)} points × {len(samples[0]) if samples else 0} bands")
    return result, log


def _strategy_band_stack(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Stack multiple raster bands (returns vectorized result as GeoDataFrame).

    When rasters have different shapes, automatically resamples the second raster
    to match the first raster's grid before band stacking.
    """
    import rasterio
    from rasterio.features import shapes

    log = []

    raster_paths = [data for dtype, data in aligned if dtype == "raster" and isinstance(data, str)]
    if len(raster_paths) < 2:
        raise ValueError("band_stack requires at least 2 raster sources.")

    ref_path = raster_paths[0]
    second_path = raster_paths[1]

    # Read first raster as reference
    with rasterio.open(ref_path) as src:
        data_0 = src.read(1)
        transform = src.transform
        crs = src.crs
        ref_shape = data_0.shape

    # Read second raster
    with rasterio.open(second_path) as src:
        data_1 = src.read(1)

    # Auto-resample if shapes differ
    if data_0.shape != data_1.shape:
        resampling = params.get("resampling", "bilinear")
        try:
            resampled_path = _resample_raster_to_match(second_path, ref_path, resampling)
            with rasterio.open(resampled_path) as src:
                data_1 = src.read(1)
            log.append(f"Auto-resampled raster from {data_1.shape} to {ref_shape} "
                       f"(method={resampling})")
            # Clean up temp file
            try:
                os.remove(resampled_path)
            except OSError:
                pass
        except Exception as e:
            raise ValueError(
                f"Raster dimensions don't match ({ref_shape} vs {data_1.shape}) "
                f"and auto-resampling failed: {e}"
            )

    # Band ratio classification and vectorization
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(data_0 + data_1 > 0,
                         (data_0.astype(float) - data_1.astype(float)) /
                         (data_0.astype(float) + data_1.astype(float)),
                         0)
    classified = np.digitize(ratio, bins=[-0.5, -0.2, 0.0, 0.2, 0.5])
    mask = classified > 0

    geoms = []
    vals = []
    for geom, val in shapes(classified.astype(np.int32), mask=mask, transform=transform):
        geoms.append(geom)
        vals.append(val)

    if geoms:
        from shapely.geometry import shape as shapely_shape
        result = gpd.GeoDataFrame(
            {"class": vals},
            geometry=[shapely_shape(g) for g in geoms],
            crs=crs,
        )
    else:
        result = gpd.GeoDataFrame(columns=["class", "geometry"], crs=crs)

    log.append(f"Band stack: {len(raster_paths)} rasters → {len(result)} polygons (classified)")

    return result, log


def _strategy_time_snapshot(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Join stream/temporal data to vector features via spatial+temporal filtering.

    Loads stream data (CSV/JSON with timestamp, lat, lng, value columns),
    filters by time window, spatially joins to vector features, and aggregates.

    Params:
        window_minutes (int): Time window in minutes (default: 60).
        value_column (str): Column name for values to aggregate (default: "value").
        agg_stats (list[str]): Aggregation stats — count, mean, latest (default: all).
        timestamp_column (str): Timestamp column name (default: "timestamp").
    """
    log = []

    gdf = None
    stream_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype in ("stream", "tabular") and isinstance(data, (str, pd.DataFrame)):
            if isinstance(data, str):
                stream_path = data
            else:
                stream_path = data  # already loaded DataFrame

    if gdf is None:
        raise ValueError("time_snapshot requires at least one vector source.")

    result = gdf.copy()
    result["_fusion_timestamp"] = pd.Timestamp.now().isoformat()

    # Load and process stream data if available
    stream_df = None
    if stream_path is not None:
        try:
            if isinstance(stream_path, pd.DataFrame):
                stream_df = stream_path
            elif stream_path.endswith(".json"):
                stream_df = pd.read_json(stream_path)
            else:
                stream_df = pd.read_csv(stream_path, encoding="utf-8")
        except Exception as e:
            log.append(f"Stream data load failed: {e} — timestamp-only fallback")

    if stream_df is not None and len(stream_df) > 0:
        ts_col = params.get("timestamp_column", "timestamp")
        val_col = params.get("value_column", "value")
        window_min = params.get("window_minutes", 60)
        agg_stats = params.get("agg_stats", ["count", "mean", "latest"])

        # Time window filtering
        if ts_col in stream_df.columns:
            try:
                stream_df[ts_col] = pd.to_datetime(stream_df[ts_col])
                cutoff = pd.Timestamp.now() - pd.Timedelta(minutes=window_min)
                before_filter = len(stream_df)
                stream_df = stream_df[stream_df[ts_col] >= cutoff]
                log.append(f"Time window filter: {before_filter} → {len(stream_df)} "
                           f"events (last {window_min} min)")
            except Exception:
                log.append("Time parsing failed — using all stream records")

        # Spatial join: stream points to vector polygons
        lat_col = None
        lng_col = None
        for c in stream_df.columns:
            cl = c.lower()
            if cl in ("lat", "latitude", "y"):
                lat_col = c
            elif cl in ("lng", "lon", "longitude", "x"):
                lng_col = c

        if lat_col and lng_col:
            try:
                stream_gdf = gpd.GeoDataFrame(
                    stream_df,
                    geometry=gpd.points_from_xy(stream_df[lng_col], stream_df[lat_col]),
                    crs=gdf.crs or "EPSG:4326",
                )
                joined = gpd.sjoin(stream_gdf, gdf, how="inner", predicate="within")

                # Aggregate per target polygon
                if val_col in joined.columns and len(joined) > 0:
                    agg_dict = {}
                    if "count" in agg_stats:
                        agg_dict["stream_count"] = (val_col, "count")
                    if "mean" in agg_stats:
                        agg_dict["stream_mean"] = (val_col, "mean")

                    if agg_dict:
                        grouped = joined.groupby("index_right").agg(**agg_dict)
                        for col_name in grouped.columns:
                            result[col_name] = result.index.map(
                                grouped[col_name]
                            ).fillna(0)

                    if "latest" in agg_stats and ts_col in joined.columns:
                        latest = joined.groupby("index_right")[ts_col].max()
                        result["stream_latest"] = result.index.map(latest)

                log.append(f"Stream fusion: {len(joined)} events joined to "
                           f"{len(result)} features")
            except Exception as e:
                log.append(f"Stream spatial join failed: {e} — timestamp-only fallback")
        else:
            log.append("No coordinate columns found in stream data — timestamp-only")
    else:
        log.append(f"Time snapshot: annotated {len(result)} features with timestamp")

    return result, log


def _strategy_height_assign(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Assign height values from point cloud (LAS/LAZ) to vector features.

    For each vector feature, finds point cloud points within its bounding box
    and computes height statistics (mean, median, min, max).

    Params:
        height_stat (str): Statistic to use — mean, median, min, max (default: mean).
    """
    log = []

    gdf = None
    pc_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype == "point_cloud" and isinstance(data, str):
            pc_path = data

    if gdf is None:
        raise ValueError("height_assign requires a vector source.")

    result = gdf.copy()
    height_stat = params.get("height_stat", "mean")

    if pc_path is None:
        result["height_m"] = 0.0
        log.append(f"Height assignment: {len(result)} features (no point cloud path)")
        return result, log

    # Try loading point cloud with laspy
    try:
        import laspy
    except ImportError:
        result["height_m"] = 0.0
        log.append(f"Height assignment: {len(result)} features (laspy not installed — fallback 0.0)")
        return result, log

    try:
        las = laspy.read(pc_path)
        pc_x = np.array(las.x)
        pc_y = np.array(las.y)
        pc_z = np.array(las.z)
    except Exception as e:
        result["height_m"] = 0.0
        log.append(f"Height assignment: point cloud read failed ({e}) — fallback 0.0")
        return result, log

    stat_funcs = {
        "mean": np.mean,
        "median": np.median,
        "min": np.min,
        "max": np.max,
    }
    stat_func = stat_funcs.get(height_stat, np.mean)

    heights = []
    matched_count = 0
    for _, row in result.iterrows():
        geom = row.geometry
        if geom is None:
            heights.append(0.0)
            continue
        minx, miny, maxx, maxy = geom.bounds
        mask = (pc_x >= minx) & (pc_x <= maxx) & (pc_y >= miny) & (pc_y <= maxy)
        pts_z = pc_z[mask]
        if len(pts_z) > 0:
            heights.append(float(stat_func(pts_z)))
            matched_count += 1
        else:
            heights.append(0.0)

    result["height_m"] = heights
    log.append(f"Height assignment: {matched_count}/{len(result)} features matched "
               f"(stat={height_stat}, {len(pc_x)} total points)")
    return result, log


def _strategy_raster_vectorize(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Vectorize raster then join with tabular data."""
    import rasterio
    from rasterio.features import shapes as rasterio_shapes
    from shapely.geometry import shape as shapely_shape

    log = []

    raster_path = None
    df = None
    for dtype, data in aligned:
        if dtype == "raster" and isinstance(data, str):
            raster_path = data
        elif dtype == "tabular" and isinstance(data, pd.DataFrame):
            df = data

    if raster_path is None:
        raise ValueError("raster_vectorize requires a raster source.")

    with rasterio.open(raster_path) as src:
        band = src.read(1)
        transform = src.transform
        crs = src.crs

    mask = band != (src.nodata if hasattr(src, 'nodata') and src.nodata else 0)
    geoms = []
    vals = []
    for geom, val in rasterio_shapes(band.astype(np.int32), mask=mask, transform=transform):
        geoms.append(shapely_shape(geom))
        vals.append(int(val))

    result = gpd.GeoDataFrame(
        {"raster_value": vals},
        geometry=geoms,
        crs=crs,
    )

    if df is not None:
        # Simple concat if no obvious join key
        for col in df.columns:
            if col not in result.columns:
                if len(df) == len(result):
                    result[col] = df[col].values
                else:
                    log.append(f"Tabular row count ({len(df)}) differs from vectorized "
                               f"({len(result)}), skipping attribute join")
                    break

    log.append(f"Raster vectorize: → {len(result)} polygons")
    return result, log


# Strategy registry
_STRATEGY_REGISTRY = {
    "spatial_join":     _strategy_spatial_join,
    "overlay":          _strategy_overlay,
    "nearest_join":     _strategy_nearest_join,
    "attribute_join":   _strategy_attribute_join,
    "zonal_statistics": _strategy_zonal_statistics,
    "point_sampling":   _strategy_point_sampling,
    "band_stack":       _strategy_band_stack,
    "time_snapshot":    _strategy_time_snapshot,
    "height_assign":    _strategy_height_assign,
    "raster_vectorize": _strategy_raster_vectorize,
}


# ---------------------------------------------------------------------------
# Helper: auto-detect join column
# ---------------------------------------------------------------------------

def _auto_detect_join_column(gdf: gpd.GeoDataFrame, df: pd.DataFrame) -> str:
    """Auto-detect the best join column between GeoDataFrame and DataFrame."""
    gdf_cols = {c.lower(): c for c in gdf.columns if c != "geometry"}
    df_cols = {c.lower(): c for c in df.columns}

    # Exact matches (case-insensitive)
    common = set(gdf_cols.keys()) & set(df_cols.keys())
    if common:
        # Prefer ID-like columns
        id_cols = [c for c in common if any(kw in c for kw in ["id", "code", "bm", "dm", "fid"])]
        if id_cols:
            return gdf_cols[id_cols[0]]
        return gdf_cols[list(common)[0]]

    raise ValueError("Cannot auto-detect join column. Please specify join_column parameter.")


# ---------------------------------------------------------------------------
# Quality Validation
# ---------------------------------------------------------------------------

def validate_quality(
    data: gpd.GeoDataFrame | str,
    sources: Optional[list[FusionSource]] = None,
) -> dict:
    """Validate quality of fusion output.

    v5.6 enhancements (MGIM-inspired comprehensive validation):
      - Original: empty check, null rate, geometry validity, row completeness
      - New: attribute value range validation, micro-polygon detection,
             per-column completeness, statistical distribution comparison

    Args:
        data: GeoDataFrame or path to output file.
        sources: Original source profiles for completeness check.

    Returns:
        Dict with score (0-1), warnings list, and details dict.
    """
    if isinstance(data, str):
        data = gpd.read_file(data)

    warnings = []
    details = {}
    score = 1.0

    # 1. Check for empty result
    if len(data) == 0:
        warnings.append("Fusion result is empty (0 rows)")
        return {"score": 0.0, "warnings": warnings, "details": {"empty": True}}

    # 2. Null rate check (per-column)
    non_geom = [c for c in data.columns if c != "geometry"]
    null_cols = {}
    for col in non_geom:
        null_pct = data[col].isna().mean()
        null_cols[col] = round(null_pct, 3)
        if null_pct > 0.5:
            warnings.append(f"Column '{col}' has {null_pct:.0%} null values")
            score -= 0.1
        elif null_pct > 0.2:
            warnings.append(f"Column '{col}' has {null_pct:.0%} null values (moderate)")
            score -= 0.05
    details["null_rates"] = null_cols

    # 3. Geometry validity
    if "geometry" in data.columns and not data.geometry.isna().all():
        invalid = ~data.geometry.is_valid
        invalid_pct = invalid.mean()
        details["invalid_geometry_pct"] = round(invalid_pct, 3)
        if invalid_pct > 0:
            warnings.append(f"{invalid_pct:.0%} invalid geometries detected")
            score -= 0.15

    # 4. Row count completeness (compared to sources)
    if sources:
        max_source_rows = max((s.row_count for s in sources if s.row_count > 0), default=0)
        if max_source_rows > 0:
            completeness = len(data) / max_source_rows
            details["row_completeness"] = round(completeness, 3)
            if completeness < 0.5:
                warnings.append(f"Output has {len(data)} rows vs max source {max_source_rows} "
                                f"({completeness:.0%} completeness)")
                score -= 0.15

    # 5. v5.6: Attribute value range validation
    # Detect absurd numeric values that may indicate unit mismatch
    numeric_cols = [c for c in non_geom if pd.api.types.is_numeric_dtype(data[c])]
    outlier_cols = []
    for col in numeric_cols[:20]:  # cap at 20 columns
        valid = data[col].dropna()
        if len(valid) < 5:
            continue
        q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            extreme_low = (valid < q1 - 5 * iqr).sum()
            extreme_high = (valid > q3 + 5 * iqr).sum()
            extreme_pct = (extreme_low + extreme_high) / len(valid)
            if extreme_pct > 0.05:
                outlier_cols.append(col)
    if outlier_cols:
        warnings.append(f"Extreme outliers in {len(outlier_cols)} column(s): "
                        f"{outlier_cols[:3]} — possible unit mismatch")
        score -= 0.05
    details["outlier_columns"] = outlier_cols

    # 6. v5.6: Micro-polygon detection (topological integrity indicator)
    if "geometry" in data.columns and not data.geometry.isna().all():
        geom_types = data.geometry.geom_type.dropna()
        if len(geom_types) > 0 and geom_types.str.contains("Polygon").any():
            areas = data.geometry.area
            if areas.max() > 0:
                micro_threshold = areas.median() * 0.001
                micro_count = (areas < micro_threshold).sum() if micro_threshold > 0 else 0
                micro_pct = micro_count / len(data)
                details["micro_polygon_pct"] = round(micro_pct, 3)
                if micro_pct > 0.1:
                    warnings.append(f"{micro_pct:.0%} micro-polygons detected "
                                    f"(area < 0.1% of median) — possible sliver polygons")
                    score -= 0.05

    # 7. v5.6: Per-column completeness vs source (not just row count)
    if sources:
        source_col_count = max((len(s.columns) for s in sources), default=0)
        output_col_count = len(non_geom)
        if source_col_count > 0:
            col_completeness = output_col_count / (source_col_count + 1)  # +1 for joined cols
            details["column_completeness"] = round(min(col_completeness, 1.0), 3)

    # 8. CRS consistency check
    if sources and "geometry" in data.columns and data.crs:
        output_crs = str(data.crs)
        details["output_crs"] = output_crs
        source_crs_set = {s.crs for s in sources if s.crs}
        if source_crs_set and output_crs not in source_crs_set:
            # CRS was reprojected — informational, not penalized
            details["crs_reprojected"] = True

    # 9. Topological validation — check for self-intersections
    if "geometry" in data.columns and not data.geometry.isna().all():
        geom_types = data.geometry.geom_type.dropna()
        if len(geom_types) > 0 and geom_types.str.contains("Polygon").any():
            try:
                from shapely.validation import explain_validity
                invalid_reasons = []
                for idx, geom in data.geometry.items():
                    if geom is not None and not geom.is_valid:
                        reason = explain_validity(geom)
                        if reason != "Valid Geometry":
                            invalid_reasons.append(reason)
                if invalid_reasons:
                    # Deduplicate reasons
                    unique_reasons = list(set(invalid_reasons))[:5]
                    details["topology_issues"] = unique_reasons
                    warnings.append(f"Topology issues in {len(invalid_reasons)} geometries: "
                                    f"{unique_reasons[0]}")
                    score -= 0.1
            except ImportError:
                pass  # shapely.validation not available

    # 10. Distribution shift detection (KS test)
    if sources:
        try:
            from scipy.stats import ks_2samp
            shift_warnings = []
            for src in sources:
                for col_info in src.columns[:10]:  # cap at 10 columns per source
                    col_name = col_info["name"]
                    if col_name in data.columns and pd.api.types.is_numeric_dtype(data[col_name]):
                        src_stats = src.stats.get(col_name, {})
                        if "mean" in src_stats and "min" in src_stats and "max" in src_stats:
                            output_vals = data[col_name].dropna()
                            if len(output_vals) >= 10:
                                # Generate synthetic source distribution from stats
                                src_mean = src_stats["mean"]
                                src_min = src_stats["min"]
                                src_max = src_stats["max"]
                                src_std = (src_max - src_min) / 4 if src_max > src_min else 1.0
                                rng = np.random.default_rng(42)
                                synthetic_src = rng.normal(src_mean, src_std, size=len(output_vals))
                                stat, p_val = ks_2samp(output_vals.values, synthetic_src)
                                if p_val < 0.01:
                                    shift_warnings.append(col_name)
            if shift_warnings:
                details["distribution_shift_cols"] = shift_warnings[:5]
                if len(shift_warnings) > len(numeric_cols) * 0.5 and len(numeric_cols) > 2:
                    warnings.append(f"Distribution shift detected in {len(shift_warnings)} columns")
                    score -= 0.05
        except ImportError:
            pass  # scipy not available

    score = max(round(score, 2), 0.0)
    return {"score": score, "warnings": warnings, "details": details}


# ---------------------------------------------------------------------------
# Database Recording
# ---------------------------------------------------------------------------

def ensure_fusion_tables():
    """Create fusion operations table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_FUSION_OPS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    source_files JSONB NOT NULL DEFAULT '[]'::jsonb,
                    strategy VARCHAR(50) NOT NULL,
                    parameters JSONB DEFAULT '{{}}'::jsonb,
                    output_file TEXT,
                    quality_score FLOAT,
                    quality_report JSONB DEFAULT '{{}}'::jsonb,
                    duration_s FLOAT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_fusion_ops_user "
                f"ON {T_FUSION_OPS} (username)"
            ))
            conn.commit()
    except Exception as e:
        print(f"[Fusion] WARNING: Failed to create tables: {e}")


def record_operation(
    sources: list[FusionSource],
    strategy: str,
    output_path: str,
    quality_score: float,
    quality_warnings: list[str],
    duration_s: float,
    params: Optional[dict] = None,
) -> None:
    """Record a fusion operation to the database."""
    engine = get_engine()
    if not engine:
        return

    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_FUSION_OPS}
                (username, source_files, strategy, parameters, output_file,
                 quality_score, quality_report, duration_s)
                VALUES (:username, :sources, :strategy, :params, :output,
                        :quality, :report, :duration)
            """), {
                "username": username,
                "sources": json.dumps([s.file_path for s in sources]),
                "strategy": strategy,
                "params": json.dumps(params or {}),
                "output": output_path,
                "quality": quality_score,
                "report": json.dumps({"warnings": quality_warnings}),
                "duration": duration_s,
            })
            conn.commit()
    except Exception as e:
        print(f"[Fusion] WARNING: Failed to record operation: {e}")
