"""
Remote Sensing Basics — Raster profiling, NDVI, band math, classification,
visualization, and cloud data download (LULC / DEM).

PRD F10: Foundational remote sensing tools for satellite/aerial imagery analysis.
"""
import json
import math
import os

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import requests as _requests
from shapely.geometry import mapping as _shapely_mapping

from .gis_processors import _generate_output_path, _resolve_path


# ---------------------------------------------------------------------------
# ArcGIS LULC constants
# ---------------------------------------------------------------------------
_LULC_SERVICE_URL = (
    "https://ic.imagery1.arcgis.com/arcgis/rest/services/"
    "Sentinel2_10m_LandCover/ImageServer/exportImage"
)
_LULC_YEARS = range(2017, 2025)  # 2017-2024
_LULC_LABELS = {
    2: "Trees", 4: "Flooded Vegetation", 5: "Crops",
    7: "Built Area", 8: "Bare Ground", 9: "Snow/Ice",
    10: "Clouds", 11: "Rangeland",
}
_LULC_MAX_PIXELS = 10000
_LULC_PIXEL_DEG = 0.0000898  # ~10m at equator in degrees


def _shapely_to_esri_json(geom):
    """Convert a Shapely Polygon/MultiPolygon to Esri JSON format."""
    geojson = _shapely_mapping(geom)
    geom_type = geojson["type"]
    if geom_type == "Polygon":
        return {
            "rings": [list(ring) for ring in geojson["coordinates"]],
            "spatialReference": {"wkid": 4326},
        }
    elif geom_type == "MultiPolygon":
        rings = []
        for polygon_coords in geojson["coordinates"]:
            for ring in polygon_coords:
                rings.append(list(ring))
        return {
            "rings": rings,
            "spatialReference": {"wkid": 4326},
        }
    raise ValueError(f"Unsupported geometry type for Esri JSON: {geom_type}")


def describe_raster(raster_path: str) -> str:
    """
    栅格数据画像：统计波段数、形状、CRS、数据类型、NoData值，以及每个波段的统计信息。

    Args:
        raster_path: Path to a GeoTIFF raster file.

    Returns:
        JSON string with raster metadata and per-band statistics.
    """
    try:
        path = _resolve_path(raster_path)
        with rasterio.open(path) as src:
            profile = {
                "file": os.path.basename(path),
                "driver": src.driver,
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "crs": str(src.crs) if src.crs else None,
                "dtype": str(src.dtypes[0]),
                "nodata": src.nodata,
                "bounds": {
                    "left": src.bounds.left,
                    "bottom": src.bounds.bottom,
                    "right": src.bounds.right,
                    "top": src.bounds.top,
                },
                "pixel_size": {
                    "x": abs(src.transform[0]),
                    "y": abs(src.transform[4]),
                },
            }

            bands_stats = []
            for i in range(1, src.count + 1):
                data = src.read(i, masked=True)
                valid = data.compressed()
                if len(valid) == 0:
                    bands_stats.append({
                        "band": i,
                        "valid_pixels": 0,
                        "nodata_pixels": int(data.size),
                    })
                    continue
                bands_stats.append({
                    "band": i,
                    "valid_pixels": int(len(valid)),
                    "nodata_pixels": int(data.size - len(valid)),
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": round(float(np.mean(valid)), 4),
                    "std": round(float(np.std(valid)), 4),
                    "p5": round(float(np.percentile(valid, 5)), 4),
                    "p25": round(float(np.percentile(valid, 25)), 4),
                    "p50": round(float(np.percentile(valid, 50)), 4),
                    "p75": round(float(np.percentile(valid, 75)), 4),
                    "p95": round(float(np.percentile(valid, 95)), 4),
                })

            profile["bands"] = bands_stats
            return json.dumps(profile, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Error in describe_raster: {str(e)}"


def calculate_ndvi(raster_path: str, red_band: int = 3, nir_band: int = 4) -> str:
    """
    计算归一化植被指数 (NDVI)。NDVI = (NIR - Red) / (NIR + Red)。

    Args:
        raster_path: Path to a multi-band GeoTIFF.
        red_band: Band number for red (1-indexed, default 3).
        nir_band: Band number for NIR (1-indexed, default 4).

    Returns:
        Path to the output NDVI GeoTIFF and vegetation statistics.
    """
    try:
        path = _resolve_path(raster_path)
        with rasterio.open(path) as src:
            if src.count < max(red_band, nir_band):
                return (
                    f"Error: raster has {src.count} band(s), "
                    f"but red_band={red_band} and nir_band={nir_band} requested."
                )

            red = src.read(red_band).astype(np.float32)
            nir = src.read(nir_band).astype(np.float32)

            nodata_val = -9999.0
            denominator = nir + red
            # Avoid division by zero
            valid_mask = denominator != 0
            ndvi = np.full_like(red, nodata_val, dtype=np.float32)
            ndvi[valid_mask] = (nir[valid_mask] - red[valid_mask]) / denominator[valid_mask]

            # Handle source nodata
            if src.nodata is not None:
                src_nodata_mask = (src.read(red_band) == src.nodata) | (src.read(nir_band) == src.nodata)
                ndvi[src_nodata_mask] = nodata_val

            out_path = _generate_output_path("ndvi", "tif")
            out_profile = src.profile.copy()
            out_profile.update(
                count=1,
                dtype=rasterio.float32,
                nodata=nodata_val,
                driver="GTiff",
            )

            with rasterio.open(out_path, "w", **out_profile) as dst:
                dst.write(ndvi, 1)

            # Vegetation statistics
            valid_ndvi = ndvi[ndvi != nodata_val]
            if len(valid_ndvi) > 0:
                veg_count = int(np.sum(valid_ndvi > 0.3))
                veg_pct = round(veg_count / len(valid_ndvi) * 100, 1)
                stats_msg = (
                    f"NDVI统计: min={float(np.min(valid_ndvi)):.3f}, "
                    f"max={float(np.max(valid_ndvi)):.3f}, "
                    f"mean={float(np.mean(valid_ndvi)):.3f}, "
                    f"植被覆盖(>0.3): {veg_pct}% ({veg_count}/{len(valid_ndvi)}像素)"
                )
            else:
                stats_msg = "NDVI统计: 无有效像素"

            return f"{out_path}\n{stats_msg}"

    except Exception as e:
        return f"Error in calculate_ndvi: {str(e)}"


def raster_band_math(
    raster_path: str,
    expression: str,
    output_name: str = "band_math",
) -> str:
    """
    波段代数运算：对栅格波段执行自定义数学表达式。

    波段用 b1, b2, b3... 表示（1-indexed）。支持 numpy 函数（np.sqrt, np.log 等）。
    示例: "(b4 - b3) / (b4 + b3)" 计算 NDVI, "np.sqrt(b1**2 + b2**2)" 计算幅值。

    Args:
        raster_path: Path to a GeoTIFF raster file.
        expression: Band math expression using b1, b2, ... and np functions.
        output_name: Prefix for the output filename.

    Returns:
        Path to the output GeoTIFF.
    """
    try:
        path = _resolve_path(raster_path)
        with rasterio.open(path) as src:
            # Build safe namespace
            namespace = {"__builtins__": {}, "np": np}
            for i in range(1, src.count + 1):
                namespace[f"b{i}"] = src.read(i).astype(np.float32)

            # Validate expression doesn't contain dangerous patterns
            forbidden = ["import", "exec", "eval", "open", "os.", "sys.", "__"]
            expr_lower = expression.lower()
            for f in forbidden:
                if f in expr_lower:
                    return f"Error: expression contains forbidden pattern '{f}'"

            result = eval(expression, namespace)  # noqa: S307

            if not isinstance(result, np.ndarray):
                return "Error: expression did not produce a numpy array"

            # Ensure 2D
            if result.ndim != 2:
                return f"Error: expression produced {result.ndim}D array, expected 2D"

            out_path = _generate_output_path(output_name, "tif")
            out_profile = src.profile.copy()
            out_profile.update(
                count=1,
                dtype=rasterio.float32,
                driver="GTiff",
            )

            with rasterio.open(out_path, "w", **out_profile) as dst:
                dst.write(result.astype(np.float32), 1)

            return out_path

    except Exception as e:
        return f"Error in raster_band_math: {str(e)}"


def classify_raster(
    raster_path: str,
    n_classes: int = 5,
    method: str = "kmeans",
    band_indices: str = "",
) -> str:
    """
    非监督分类：对栅格数据进行 KMeans 聚类分类。

    Args:
        raster_path: Path to a GeoTIFF raster file.
        n_classes: Number of classes (default 5).
        method: "kmeans" or "mini_batch" (for large rasters).
        band_indices: Comma-separated band numbers to use (e.g. "1,2,3").
                      Empty string = use all bands.

    Returns:
        Path to the classified GeoTIFF and class statistics CSV.
    """
    try:
        from sklearn.cluster import KMeans, MiniBatchKMeans

        path = _resolve_path(raster_path)
        with rasterio.open(path) as src:
            # Select bands
            if band_indices.strip():
                bands = [int(b.strip()) for b in band_indices.split(",")]
                for b in bands:
                    if b < 1 or b > src.count:
                        return f"Error: band {b} out of range (1..{src.count})"
            else:
                bands = list(range(1, src.count + 1))

            # Read selected bands
            data = np.stack([src.read(b).astype(np.float32) for b in bands])
            height, width = data.shape[1], data.shape[2]

            # Build nodata mask
            nodata_mask = np.zeros((height, width), dtype=bool)
            if src.nodata is not None:
                for i, b in enumerate(bands):
                    nodata_mask |= (data[i] == src.nodata)

            # Reshape to (pixels, bands)
            pixels = data.reshape(len(bands), -1).T
            valid_mask = ~nodata_mask.ravel()
            valid_pixels = pixels[valid_mask]

            if len(valid_pixels) == 0:
                return "Error: no valid pixels found for classification"

            # Cluster
            if method == "mini_batch":
                model = MiniBatchKMeans(n_clusters=n_classes, random_state=42, batch_size=1024)
            else:
                model = KMeans(n_clusters=n_classes, random_state=42, n_init=10)

            labels = model.fit_predict(valid_pixels)

            # Build output array
            classified = np.zeros(height * width, dtype=np.uint8)
            classified[valid_mask] = labels.astype(np.uint8) + 1  # 1-indexed classes
            classified = classified.reshape(height, width)

            # Save classified raster
            out_tif = _generate_output_path("classified", "tif")
            out_profile = src.profile.copy()
            out_profile.update(
                count=1,
                dtype=rasterio.uint8,
                nodata=0,
                driver="GTiff",
            )
            with rasterio.open(out_tif, "w", **out_profile) as dst:
                dst.write(classified, 1)

            # Generate class statistics CSV
            import csv
            out_csv = _generate_output_path("class_stats", "csv")
            with open(out_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                header = ["class"] + [f"band_{b}_mean" for b in bands] + ["pixel_count", "percentage"]
                writer.writerow(header)
                total_valid = len(valid_pixels)
                for c in range(n_classes):
                    mask = labels == c
                    count = int(np.sum(mask))
                    pct = round(count / total_valid * 100, 2)
                    means = [round(float(np.mean(valid_pixels[mask, i])), 4) for i in range(len(bands))]
                    writer.writerow([c + 1] + means + [count, pct])

            return f"分类完成: {out_tif}\n类别统计: {out_csv}\n共 {n_classes} 类, {total_valid} 个有效像素"

    except Exception as e:
        return f"Error in classify_raster: {str(e)}"


def visualize_raster(
    raster_path: str,
    band: int = 1,
    colormap: str = "viridis",
    title: str = "",
) -> str:
    """
    栅格可视化：将栅格波段渲染为 PNG 图片。

    Args:
        raster_path: Path to a GeoTIFF raster file.
        band: Band number to visualize (1-indexed). Use 0 for RGB composite (bands 1,2,3).
        colormap: Matplotlib colormap name (default "viridis").
        title: Optional title for the plot.

    Returns:
        Path to the output PNG image.
    """
    try:
        path = _resolve_path(raster_path)
        with rasterio.open(path) as src:
            fig, ax = plt.subplots(1, 1, figsize=(10, 8))

            if band == 0:
                # RGB composite
                if src.count < 3:
                    return f"Error: RGB composite requires >= 3 bands, got {src.count}"
                r = src.read(1).astype(np.float32)
                g = src.read(2).astype(np.float32)
                b = src.read(3).astype(np.float32)

                # Normalize each channel to 0-1
                def _normalize(arr):
                    mn, mx = np.nanmin(arr), np.nanmax(arr)
                    if mx - mn == 0:
                        return np.zeros_like(arr)
                    return (arr - mn) / (mx - mn)

                rgb = np.stack([_normalize(r), _normalize(g), _normalize(b)], axis=-1)

                # Handle nodata
                if src.nodata is not None:
                    nodata_mask = (src.read(1) == src.nodata)
                    rgb[nodata_mask] = 1.0  # white for nodata

                ax.imshow(rgb, extent=[
                    src.bounds.left, src.bounds.right,
                    src.bounds.bottom, src.bounds.top,
                ])
            else:
                if band > src.count:
                    return f"Error: band {band} out of range (1..{src.count})"

                data = src.read(band).astype(np.float32)

                # Mask nodata
                if src.nodata is not None:
                    data = np.ma.masked_equal(data, src.nodata)

                im = ax.imshow(
                    data,
                    cmap=colormap,
                    extent=[
                        src.bounds.left, src.bounds.right,
                        src.bounds.bottom, src.bounds.top,
                    ],
                )
                plt.colorbar(im, ax=ax, shrink=0.7, label=f"Band {band}")

            plot_title = title if title else f"{os.path.basename(path)}"
            ax.set_title(plot_title, fontsize=12)
            ax.set_xlabel("X")
            ax.set_ylabel("Y")

            out_path = _generate_output_path("raster_viz", "png")
            plt.savefig(out_path, dpi=150, bbox_inches="tight")
            plt.close(fig)

            return out_path

    except Exception as e:
        return f"Error in visualize_raster: {str(e)}"


# ---------------------------------------------------------------------------
# download_lulc — Sentinel-2 10m Land Use / Land Cover
# ---------------------------------------------------------------------------

def download_lulc(admin_boundary_path: str, year: int = 2023) -> str:
    """
    下载 Sentinel-2 10m 土地利用/土地覆盖数据 (LULC)，按行政区边界裁剪。

    数据源: Esri Sentinel-2 10m Land Use/Land Cover Time Series (ArcGIS Online, 全球覆盖)。
    分类体系: 2=Trees, 4=Flooded Vegetation, 5=Crops, 7=Built Area,
    8=Bare Ground, 9=Snow/Ice, 10=Clouds, 11=Rangeland。
    输出: 裁剪后的 GeoTIFF (uint8, ~10m分辨率, EPSG:4326)。

    Args:
        admin_boundary_path: 行政区边界文件路径 (.shp / .geojson / .gpkg)。
        year: 数据年份 (2017-2024)，默认 2023。

    Returns:
        下载后的 GeoTIFF 路径与土地覆盖统计信息，或错误信息。
    """
    try:
        if year not in _LULC_YEARS:
            return f"Error in download_lulc: year must be 2017-2024, got {year}"

        path = _resolve_path(admin_boundary_path)
        gdf = gpd.read_file(path)
        gdf_4326 = gdf.to_crs("EPSG:4326")
        union_geom = gdf_4326.geometry.union_all()
        bounds = gdf_4326.total_bounds  # [minx, miny, maxx, maxy]

        esri_geom = _shapely_to_esri_json(union_geom)

        rendering_rule = json.dumps({
            "rasterFunction": "Clip",
            "rasterFunctionArguments": {
                "ClippingGeometry": esri_geom,
                "ClippingType": 1,
            },
        })
        mosaic_rule = json.dumps({
            "mosaicMethod": "esriMosaicAttribute",
            "where": (
                f"StdTime >= '{year}-01-01T00:00:00' "
                f"AND StdTime <= '{year}-12-31T23:59:59'"
            ),
            "sortField": "StdTime",
            "ascending": False,
        })

        # Determine pixel dimensions
        width_deg = bounds[2] - bounds[0]
        height_deg = bounds[3] - bounds[1]
        width_px = max(1, int(width_deg / _LULC_PIXEL_DEG))
        height_px = max(1, int(height_deg / _LULC_PIXEL_DEG))

        needs_tiling = width_px > _LULC_MAX_PIXELS or height_px > _LULC_MAX_PIXELS

        if not needs_tiling:
            # Single-tile download
            raw_path = _download_lulc_tile(
                bounds, min(width_px, _LULC_MAX_PIXELS),
                min(height_px, _LULC_MAX_PIXELS),
                rendering_rule, mosaic_rule,
            )
        else:
            # Multi-tile download and merge
            raw_path = _download_lulc_tiled(
                bounds, width_px, height_px, rendering_rule, mosaic_rule,
            )

        # Precise clip with rasterio.mask
        from rasterio.mask import mask as rio_mask

        out_path = _generate_output_path("lulc", "tif")
        with rasterio.open(raw_path) as src:
            out_image, out_transform = rio_mask(
                src, [union_geom], crop=True, nodata=0,
            )
            out_profile = src.profile.copy()
            out_profile.update(
                height=out_image.shape[1],
                width=out_image.shape[2],
                transform=out_transform,
                nodata=0,
            )

        with rasterio.open(out_path, "w", **out_profile) as dst:
            dst.write(out_image)

        # Clean up raw file
        if os.path.exists(raw_path) and raw_path != out_path:
            os.remove(raw_path)

        # Generate class statistics
        data = out_image[0]
        valid = data[data > 0]
        total_valid = len(valid)
        class_lines = []
        for code, label in sorted(_LULC_LABELS.items()):
            count = int(np.sum(valid == code))
            if count > 0:
                pct = round(count / total_valid * 100, 1)
                class_lines.append(f"  {label}({code}): {pct}%")

        stats_msg = "\n".join(class_lines) if class_lines else "  无有效分类像素"
        return (
            f"{out_path}\n"
            f"数据源: Esri Sentinel-2 10m LULC {year}\n"
            f"分辨率: ~10m, 投影: EPSG:4326\n"
            f"有效像素: {total_valid}\n"
            f"土地覆盖分类统计:\n{stats_msg}"
        )

    except Exception as e:
        return f"Error in download_lulc: {str(e)}"


def _download_lulc_tile(bbox, width_px, height_px, rendering_rule, mosaic_rule):
    """Download a single LULC tile and save to a temp GeoTIFF."""
    params = {
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{width_px},{height_px}",
        "format": "tiff",
        "pixelType": "U8",
        "interpolation": "RSP_NearestNeighbor",
        "renderingRule": rendering_rule,
        "mosaicRule": mosaic_rule,
        "f": "image",
    }
    resp = _requests.get(_LULC_SERVICE_URL, params=params, timeout=120)
    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type or resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message", resp.text[:200])
        except Exception:
            msg = resp.text[:200]
        raise RuntimeError(f"ArcGIS ImageServer error: {msg}")

    raw_path = _generate_output_path("lulc_raw", "tif")
    with open(raw_path, "wb") as f:
        f.write(resp.content)
    return raw_path


def _download_lulc_tiled(bbox, total_w, total_h, rendering_rule, mosaic_rule):
    """Download LULC in tiles and merge with rasterio."""
    from rasterio.merge import merge as rio_merge

    n_cols = math.ceil(total_w / _LULC_MAX_PIXELS)
    n_rows = math.ceil(total_h / _LULC_MAX_PIXELS)
    tile_w_deg = (bbox[2] - bbox[0]) / n_cols
    tile_h_deg = (bbox[3] - bbox[1]) / n_rows

    temp_tiles = []
    try:
        for row in range(n_rows):
            for col in range(n_cols):
                tile_bbox = [
                    bbox[0] + col * tile_w_deg,
                    bbox[1] + row * tile_h_deg,
                    bbox[0] + (col + 1) * tile_w_deg,
                    bbox[1] + (row + 1) * tile_h_deg,
                ]
                tw = min(_LULC_MAX_PIXELS, int((tile_bbox[2] - tile_bbox[0]) / _LULC_PIXEL_DEG))
                th = min(_LULC_MAX_PIXELS, int((tile_bbox[3] - tile_bbox[1]) / _LULC_PIXEL_DEG))
                tw = max(1, tw)
                th = max(1, th)
                tile_path = _download_lulc_tile(
                    tile_bbox, tw, th, rendering_rule, mosaic_rule,
                )
                temp_tiles.append(tile_path)

        # Merge tiles
        datasets = [rasterio.open(t) for t in temp_tiles]
        mosaic_arr, out_transform = rio_merge(datasets)
        for ds in datasets:
            ds.close()

        merged_path = _generate_output_path("lulc_merged", "tif")
        out_profile = {
            "driver": "GTiff",
            "dtype": "uint8",
            "width": mosaic_arr.shape[2],
            "height": mosaic_arr.shape[1],
            "count": 1,
            "crs": "EPSG:4326",
            "transform": out_transform,
            "nodata": 0,
        }
        with rasterio.open(merged_path, "w", **out_profile) as dst:
            dst.write(mosaic_arr)
        return merged_path

    finally:
        for tp in temp_tiles:
            if os.path.exists(tp):
                try:
                    os.remove(tp)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# download_dem — Copernicus DEM GLO-30 (Google Earth Engine)
# ---------------------------------------------------------------------------

def _initialize_ee():
    """Initialize Google Earth Engine with multi-strategy auth."""
    import ee

    if ee.data._credentials is not None:
        return  # already initialized

    # Strategy 1: Service account key file
    sa_key = os.environ.get("GEE_SERVICE_ACCOUNT_KEY")
    if sa_key and os.path.exists(sa_key):
        credentials = ee.ServiceAccountCredentials(None, key_file=sa_key)
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        ee.Initialize(credentials=credentials, project=project)
        return

    # Strategy 2: Application Default Credentials via GCP project
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        try:
            ee.Initialize(project=project)
            return
        except Exception:
            pass

    raise RuntimeError(
        "Earth Engine 认证失败。请设置 GOOGLE_CLOUD_PROJECT 环境变量，"
        "或配置 GEE_SERVICE_ACCOUNT_KEY 指向服务账号密钥文件。"
    )


def download_dem(admin_boundary_path: str) -> str:
    """
    下载 Copernicus DEM GLO-30 高程数据（30m分辨率），按行政区边界裁剪。

    数据源: Google Earth Engine — COPERNICUS/DEM/GLO30 (全球30m数字高程模型)。
    需要安装 earthengine-api 包并配置 GOOGLE_CLOUD_PROJECT 环境变量。
    对于乡镇级区域 (≤200km²) 使用直接下载；更大区域提交异步导出任务到 Google Drive。

    Args:
        admin_boundary_path: 行政区边界文件路径 (.shp / .geojson / .gpkg)。

    Returns:
        下载后的 GeoTIFF 路径与高程统计信息，或错误/状态信息。
    """
    try:
        import ee
    except ImportError:
        return (
            "Error in download_dem: earthengine-api 未安装。"
            "请执行 `pip install earthengine-api` 后重试。"
        )

    try:
        _initialize_ee()

        path = _resolve_path(admin_boundary_path)
        gdf = gpd.read_file(path)
        gdf_4326 = gdf.to_crs("EPSG:4326")
        union_geom = gdf_4326.geometry.union_all()

        # Calculate area in km²
        gdf_proj = gdf_4326.to_crs(gdf_4326.estimate_utm_crs())
        area_km2 = gdf_proj.geometry.union_all().area / 1e6

        # Convert Shapely geometry to ee.Geometry
        geojson = _shapely_mapping(union_geom)
        ee_geom = ee.Geometry(geojson)

        # Build DEM image
        dem = (
            ee.ImageCollection("COPERNICUS/DEM/GLO30")
            .select("DEM")
            .mosaic()
            .clip(ee_geom)
        )

        AREA_THRESHOLD = 200  # km²

        if area_km2 > AREA_THRESHOLD:
            # Large area — async export to Google Drive
            import uuid as _uuid
            task_desc = f"dem_export_{_uuid.uuid4().hex[:8]}"
            task = ee.batch.Export.image.toDrive(
                image=dem,
                description=task_desc,
                scale=30,
                region=ee_geom,
                crs="EPSG:4326",
                maxPixels=int(1e9),
                fileFormat="GeoTIFF",
            )
            task.start()
            return (
                f"DEM数据区域面积 {area_km2:.1f} km² 超过直接下载阈值({AREA_THRESHOLD}km²)。\n"
                f"已提交 Google Earth Engine 异步导出任务。\n"
                f"任务ID: {task.id}\n"
                f"状态: {task.status()['state']}\n"
                f"导出完成后数据将保存到 Google Drive 根目录。"
            )

        # Small area — direct download
        url = dem.getDownloadURL({
            "scale": 30,
            "crs": "EPSG:4326",
            "region": ee_geom,
            "format": "GEO_TIFF",
            "filePerBand": False,
        })

        resp = _requests.get(url, timeout=300)
        resp.raise_for_status()

        raw_path = _generate_output_path("dem_raw", "tif")
        with open(raw_path, "wb") as f:
            f.write(resp.content)

        # Precise clip with rasterio.mask
        from rasterio.mask import mask as rio_mask

        out_path = _generate_output_path("dem", "tif")
        with rasterio.open(raw_path) as src:
            out_image, out_transform = rio_mask(
                src, [union_geom], crop=True, nodata=-9999,
            )
            out_profile = src.profile.copy()
            out_profile.update(
                height=out_image.shape[1],
                width=out_image.shape[2],
                transform=out_transform,
                nodata=-9999,
                dtype="float32",
            )

        with rasterio.open(out_path, "w", **out_profile) as dst:
            dst.write(out_image.astype(np.float32))

        # Clean up raw file
        if os.path.exists(raw_path):
            os.remove(raw_path)

        # Elevation statistics
        data = out_image[0]
        valid = data[data != -9999]
        if len(valid) > 0:
            stats_msg = (
                f"高程统计: min={float(np.min(valid)):.1f}m, "
                f"max={float(np.max(valid)):.1f}m, "
                f"mean={float(np.mean(valid)):.1f}m, "
                f"std={float(np.std(valid)):.1f}m"
            )
        else:
            stats_msg = "高程统计: 无有效像素"

        return (
            f"{out_path}\n"
            f"数据源: Copernicus DEM GLO-30\n"
            f"分辨率: 30m, 投影: EPSG:4326\n"
            f"区域面积: {area_km2:.1f} km²\n"
            f"{stats_msg}"
        )

    except ImportError:
        return (
            "Error in download_dem: earthengine-api 未安装。"
            "请执行 `pip install earthengine-api` 后重试。"
        )
    except Exception as e:
        return f"Error in download_dem: {str(e)}"
