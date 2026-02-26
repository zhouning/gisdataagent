"""
Population Data Integration — WorldPop raster download + zonal statistics.

PRD 5.2.4: Demographic data for land-use analysis context.
Uses WorldPop open data (100m resolution, GeoTIFF, CC BY 4.0 license).
"""
import os
import hashlib
import requests
import geopandas as gpd
import numpy as np

from .gis_processors import _generate_output_path, _resolve_path
from .geocoding import get_admin_boundary

_WORLDPOP_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "uploads", ".worldpop_cache"
)

# WorldPop constrained population rasters (100m, UNadj)
_WORLDPOP_COUNTRY_URLS = {
    "CHN": "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/maxar_v1/CHN/chn_ppp_2020_UNadj_constrained.tif",
}


def _get_cache_path(url: str) -> str:
    """Generate a deterministic cache path for a given URL."""
    os.makedirs(_WORLDPOP_CACHE_DIR, exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = os.path.basename(url).split("?")[0]
    return os.path.join(_WORLDPOP_CACHE_DIR, f"{url_hash}_{filename}")


def _download_raster(url: str, cache_path: str, timeout: int = 600) -> str:
    """Download a raster file with caching. Returns local path."""
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        print(f"[WorldPop] Using cached: {cache_path}")
        return cache_path

    print(f"[WorldPop] Downloading: {url}")
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    os.replace(tmp_path, cache_path)
    print(f"[WorldPop] Saved to: {cache_path}")
    return cache_path


def _clip_raster_to_bbox(raster_path: str, bbox: tuple, output_path: str) -> str:
    """Clip a raster to a bounding box (minx, miny, maxx, maxy). Returns clipped path."""
    import rasterio
    from rasterio.mask import mask as rio_mask
    from shapely.geometry import box

    clip_geom = [box(*bbox).__geo_interface__]
    with rasterio.open(raster_path) as src:
        out_image, out_transform = rio_mask(src, clip_geom, crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
        })
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)
    return output_path


def get_population_data(
    district_name: str,
    year: int = 2020,
    country_code: str = "CHN",
) -> dict:
    """
    获取指定行政区的人口密度统计数据。
    使用 WorldPop 开源人口栅格数据（100m分辨率）与高德行政区划边界叠加统计。

    Args:
        district_name: 行政区名称（如 "北京市", "朝阳区", "浙江省"）。
        year: 数据年份, 默认 2020。
        country_code: ISO3 国家代码, 默认 "CHN"。

    Returns:
        Dict with status, output_path (CSV), total_population, summary.
    """
    try:
        # 1. Get admin boundary via Amap
        boundary_result = get_admin_boundary(district_name, with_sub_districts=True)
        if boundary_result.get("status") != "success":
            return {"status": "error",
                    "message": f"获取行政区划边界失败: {boundary_result.get('message')}"}

        boundary_path = boundary_result["output_path"]
        zones_gdf = gpd.read_file(boundary_path)

        # 2. Get or download WorldPop raster
        raster_url = _WORLDPOP_COUNTRY_URLS.get(country_code)
        if not raster_url:
            return {"status": "error",
                    "message": f"暂不支持国家代码: {country_code}，当前仅支持: {list(_WORLDPOP_COUNTRY_URLS.keys())}"}

        cache_path = _get_cache_path(raster_url)
        if not os.path.exists(cache_path):
            _download_raster(raster_url, cache_path, timeout=600)

        # 3. Clip raster to boundary bbox (for performance)
        bbox = zones_gdf.total_bounds  # (minx, miny, maxx, maxy)
        dx = (bbox[2] - bbox[0]) * 0.1
        dy = (bbox[3] - bbox[1]) * 0.1
        expanded_bbox = (bbox[0] - dx, bbox[1] - dy, bbox[2] + dx, bbox[3] + dy)

        clipped_raster = _generate_output_path("pop_clip", "tif")
        _clip_raster_to_bbox(cache_path, expanded_bbox, clipped_raster)

        # 4. Zonal statistics
        from rasterstats import zonal_stats
        import pandas as pd

        stats_result = zonal_stats(
            zones_gdf, clipped_raster,
            stats=["sum", "mean", "count", "min", "max"],
            nodata=-99999,
            geojson_out=False,
        )

        df = pd.DataFrame(stats_result)
        if "name" in zones_gdf.columns:
            df.insert(0, "name", zones_gdf["name"])
        if "adcode" in zones_gdf.columns:
            df.insert(1 if "name" in df.columns else 0, "adcode", zones_gdf["adcode"])

        df.rename(columns={
            "sum": "pop_total",
            "mean": "pop_density",
            "count": "pixel_count",
            "min": "pop_min",
            "max": "pop_max",
        }, inplace=True)

        if "pop_total" in df.columns:
            df["pop_total"] = df["pop_total"].round(0).astype("Int64")
        if "pop_density" in df.columns:
            df["pop_density"] = df["pop_density"].round(2)

        # 5. Save output
        out_path = _generate_output_path("population_stats", "csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")

        total_pop = int(df["pop_total"].sum()) if "pop_total" in df.columns else 0

        # Clean up clipped raster
        try:
            os.remove(clipped_raster)
        except Exception:
            pass

        return {
            "status": "success",
            "output_path": out_path,
            "total_population": total_pop,
            "zones": len(df),
            "year": year,
            "source": "WorldPop (100m, CC BY 4.0)",
            "message": f"'{district_name}' 人口统计完成: 估算总人口 ~{total_pop:,}, "
                       f"覆盖 {len(df)} 个区划, 数据来源 WorldPop {year}。",
        }

    except Exception as e:
        return {"status": "error", "message": f"人口数据获取异常: {str(e)}"}


def aggregate_population(
    polygon_path: str,
    raster_path: str,
    stats: str = "sum,mean,count",
) -> dict:
    """
    自定义人口聚合统计：将人口栅格数据按任意面矢量进行分区统计。

    Args:
        polygon_path: 面矢量数据路径（SHP/GeoJSON/GPKG）。
        raster_path: 人口栅格数据路径（GeoTIFF）。
        stats: 逗号分隔的统计指标, 默认 "sum,mean,count"。

    Returns:
        Dict with status, output_path (CSV), summary.
    """
    try:
        from rasterstats import zonal_stats
        import pandas as pd

        poly_path = _resolve_path(polygon_path)
        rast_path = _resolve_path(raster_path)

        gdf = gpd.read_file(poly_path)
        stats_list = [s.strip() for s in stats.split(",")]
        zs = zonal_stats(gdf, rast_path, stats=stats_list, nodata=-99999)
        df = pd.DataFrame(zs)

        # Add ID column if available
        id_col = next(
            (c for c in ["name", "Name", "NAME", "ID", "id", "fid"] if c in gdf.columns),
            None
        )
        if id_col:
            df.insert(0, id_col, gdf[id_col])

        out_path = _generate_output_path("pop_aggregate", "csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")

        return {
            "status": "success",
            "output_path": out_path,
            "zones": len(df),
            "message": f"人口聚合统计完成: {len(df)} 个分区, 统计指标: {stats_list}",
        }

    except Exception as e:
        return {"status": "error", "message": f"人口聚合统计异常: {str(e)}"}
