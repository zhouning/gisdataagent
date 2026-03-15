"""
Watershed Analysis — small catchment extraction from DEM (v12.1).

Implements the complete hydrological analysis chain:
DEM preprocessing → Flow direction (D8) → Flow accumulation →
Stream network extraction → Watershed delineation → Sub-basin segmentation.

Uses pysheds for core hydrological computations.
All operations are non-fatal (never raise to caller).
"""
import json
import os
from typing import Optional

import numpy as np

try:
    from .observability import get_logger
    logger = get_logger("watershed_analysis")
except Exception:
    import logging
    logger = logging.getLogger("watershed_analysis")


def _resolve_path(file_path: str) -> str:
    try:
        from .gis_processors import _resolve_path as resolve
        return resolve(file_path)
    except Exception:
        return file_path


def _generate_output_path(prefix: str, ext: str) -> str:
    try:
        from .gis_processors import _generate_output_path as gen
        return gen(prefix, ext)
    except Exception:
        import uuid
        return os.path.join(os.path.dirname(__file__), "uploads",
                            f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")


# ---------------------------------------------------------------------------
# DEM Preprocessing
# ---------------------------------------------------------------------------

def _preprocess_dem(grid, dem):
    """Fill pits, depressions, and resolve flats in DEM.

    Returns conditioned DEM ready for flow direction computation.
    """
    # Step 1: Fill pits (single-cell depressions)
    pit_filled = grid.fill_pits(dem)
    # Step 2: Fill larger depressions
    flooded = grid.fill_depressions(pit_filled)
    # Step 3: Resolve flat areas (assign gradient for flow routing)
    inflated = grid.resolve_flats(flooded)
    return inflated


def _find_pour_point(grid, acc, fdir):
    """Auto-detect the pour point as the cell with maximum flow accumulation.

    Returns (x, y) coordinates in the grid's CRS.
    """
    # Find the cell with maximum accumulation
    acc_data = acc.copy()
    # Mask nodata
    if hasattr(acc, 'nodata') and acc.nodata is not None:
        acc_data[acc_data == acc.nodata] = 0

    max_idx = np.unravel_index(np.argmax(acc_data), acc_data.shape)
    row, col = max_idx

    # Convert pixel coordinates to geographic coordinates
    affine = grid.affine
    x = affine[2] + col * affine[0] + 0.5 * affine[0]
    y = affine[5] + row * affine[4] + 0.5 * affine[4]
    return float(x), float(y)


# ---------------------------------------------------------------------------
# Main Functions
# ---------------------------------------------------------------------------

def extract_watershed(
    dem_path: str,
    pour_point_x: str = "",
    pour_point_y: str = "",
    threshold: str = "1000",
    boundary_path: str = "",
) -> str:
    """小流域提取 — 从 DEM 数据中提取流域边界、河网和水文特征。

    完整水文分析链: DEM预处理 → 流向(D8) → 汇流累积 → 河网提取 → 流域划分。

    Args:
        dem_path: DEM 文件路径(GeoTIFF)，或 "auto" 自动从 Copernicus 下载
        pour_point_x: 出口点经度（留空=自动检测汇流累积最大点）
        pour_point_y: 出口点纬度
        threshold: 河网提取阈值（汇流累积单元数，默认1000）
        boundary_path: 当 dem_path="auto" 时，用于下载 DEM 的行政区边界文件

    Returns:
        JSON 包含流域边界文件、河网文件、统计信息和可视化路径。
    """
    try:
        from pysheds.grid import Grid

        # ---- Step 0: Resolve DEM source ----
        if dem_path.strip().lower() == "auto":
            if not boundary_path:
                return json.dumps({"status": "error",
                                   "message": "dem_path='auto' 时必须提供 boundary_path 用于下载 DEM"})
            try:
                from .remote_sensing import download_dem
                dem_result = download_dem(_resolve_path(boundary_path))
                # Extract file path from result string
                for line in dem_result.split("\n"):
                    if line.strip().endswith(".tif") or line.strip().endswith(".tiff"):
                        dem_path = line.strip()
                        break
                    if "输出文件" in line or "output" in line.lower():
                        parts = line.split(":")
                        if len(parts) > 1:
                            dem_path = parts[-1].strip()
                            break
                if dem_path.strip().lower() == "auto":
                    return json.dumps({"status": "error", "message": "DEM 下载失败"})
            except Exception as e:
                return json.dumps({"status": "error", "message": f"DEM 下载失败: {e}"})
        else:
            dem_path = _resolve_path(dem_path)

        if not os.path.exists(dem_path):
            return json.dumps({"status": "error", "message": f"DEM 文件不存在: {dem_path}"})

        # ---- Step 1: Read DEM ----
        grid = Grid.from_raster(dem_path)
        dem = grid.read_raster(dem_path)

        # ---- Step 2: Preprocess DEM ----
        conditioned_dem = _preprocess_dem(grid, dem)

        # ---- Step 3: Flow Direction (D8) ----
        fdir = grid.flowdir(conditioned_dem)

        # ---- Step 4: Flow Accumulation ----
        acc = grid.accumulation(fdir)

        # ---- Step 5: Determine pour point ----
        thresh = int(threshold)
        if pour_point_x and pour_point_y:
            px, py = float(pour_point_x), float(pour_point_y)
            # Snap pour point to nearest high-accumulation cell
            try:
                px_snap, py_snap = grid.snap_to_mask(acc > thresh, (px, py))
                px, py = float(px_snap), float(py_snap)
            except Exception:
                pass  # use original coordinates
        else:
            px, py = _find_pour_point(grid, acc, fdir)

        # ---- Step 6: Delineate Watershed ----
        catch = grid.catchment(x=px, y=py, fdir=fdir, xytype='coordinate')

        # ---- Step 7: Extract Stream Network ----
        streams = None
        try:
            streams = grid.extract_river_network(fdir, acc > thresh)
        except Exception as e:
            logger.debug("Stream network extraction failed: %s", e)

        # ---- Step 8: Vectorize watershed boundary ----
        import geopandas as gpd
        from shapely.geometry import shape, mapping

        # Convert catchment raster to polygon
        catch_mask = catch.astype(bool)
        watershed_geojson_path = _generate_output_path("watershed_boundary", "geojson")

        try:
            import rasterio
            from rasterio.features import shapes as rasterio_shapes
            transform = grid.affine

            polygons = []
            for geom, val in rasterio_shapes(catch_mask.astype(np.uint8),
                                              mask=catch_mask,
                                              transform=transform):
                if val == 1:
                    polygons.append(shape(geom))

            if polygons:
                from shapely.ops import unary_union
                merged = unary_union(polygons)
                gdf_watershed = gpd.GeoDataFrame(
                    [{"id": 1, "type": "watershed", "pour_point_x": px, "pour_point_y": py}],
                    geometry=[merged],
                    crs=grid.crs.to_epsg() if hasattr(grid.crs, 'to_epsg') else "EPSG:4326",
                )
                # Calculate area (approximate in sq meters if CRS is geographic)
                try:
                    gdf_proj = gdf_watershed.to_crs(epsg=3857)
                    gdf_watershed["area_m2"] = gdf_proj.geometry.area
                    gdf_watershed["area_km2"] = gdf_watershed["area_m2"] / 1e6
                    gdf_watershed["perimeter_m"] = gdf_proj.geometry.length
                except Exception:
                    gdf_watershed["area_km2"] = 0

                gdf_watershed.to_file(watershed_geojson_path, driver="GeoJSON")
        except Exception as e:
            logger.warning("Watershed vectorization failed: %s", e)
            watershed_geojson_path = None

        # ---- Step 9: Save stream network ----
        stream_geojson_path = None
        if streams and streams.get("features"):
            stream_geojson_path = _generate_output_path("stream_network", "geojson")
            try:
                with open(stream_geojson_path, "w", encoding="utf-8") as f:
                    json.dump(streams, f)
            except Exception:
                stream_geojson_path = None

        # ---- Step 10: Save flow accumulation raster ----
        acc_path = _generate_output_path("flow_accumulation", "tif")
        try:
            import rasterio
            profile = {
                "driver": "GTiff", "dtype": "float32",
                "width": acc.shape[1], "height": acc.shape[0], "count": 1,
                "crs": grid.crs if hasattr(grid, 'crs') else "EPSG:4326",
                "transform": grid.affine,
            }
            with rasterio.open(acc_path, 'w', **profile) as dst:
                dst.write(acc.astype(np.float32), 1)
        except Exception:
            acc_path = None

        # ---- Step 11: Visualization ----
        viz_path = _generate_output_path("watershed_map", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from .utils import _configure_fonts
            _configure_fonts()

            fig, ax = plt.subplots(1, 1, figsize=(10, 8))

            # Prepare DEM display — mask nodata properly
            dem_display = conditioned_dem.copy().astype(float)
            nodata_val = dem.nodata if hasattr(dem, 'nodata') and dem.nodata is not None else -9999
            dem_display[dem_display == nodata_val] = np.nan
            # Also mask extreme negatives (common DEM nodata patterns)
            dem_display[dem_display < -1000] = np.nan

            # Compute extent
            affine = grid.affine
            extent = [affine[2], affine[2] + affine[0] * dem.shape[1],
                      affine[5] + affine[4] * dem.shape[0], affine[5]]

            # Only show DEM within watershed for clarity
            dem_in_ws = dem_display.copy()
            dem_in_ws[~catch_mask] = np.nan

            # Show full DEM as faint background
            ax.imshow(dem_display, cmap='Greys', alpha=0.3, extent=extent)

            # Show DEM within watershed with terrain colors
            im = ax.imshow(dem_in_ws, cmap='terrain', alpha=0.8, extent=extent)
            plt.colorbar(im, ax=ax, label='高程 (m)', shrink=0.8)

            # Show streams as blue lines
            stream_mask = (acc > thresh) & catch_mask
            stream_display = np.where(stream_mask, 1.0, np.nan)
            ax.imshow(stream_display, cmap='winter', alpha=0.9, extent=extent)

            # Mark pour point
            ax.plot(px, py, 'r^', markersize=14, label=f'出口点 ({px:.4f}, {py:.4f})',
                    markeredgecolor='darkred', markeredgewidth=1.5)

            # Draw watershed boundary outline
            if watershed_geojson_path and os.path.exists(watershed_geojson_path):
                try:
                    gdf_ws = gpd.read_file(watershed_geojson_path)
                    gdf_ws.boundary.plot(ax=ax, color='red', linewidth=2, label='流域边界')
                except Exception:
                    pass

            ax.legend(loc='upper right', fontsize=10, framealpha=0.8)
            ax.set_title(f"小流域提取结果 (阈值={thresh})", fontsize=14, fontweight='bold')
            ax.set_xlabel("经度")
            ax.set_ylabel("纬度")
            plt.tight_layout()
            plt.savefig(viz_path, dpi=150, bbox_inches='tight', facecolor='white')
            plt.close(fig)
        except Exception as e:
            logger.debug("Visualization failed: %s", e)
            viz_path = None

        # ---- Step 12: Statistics ----
        watershed_cells = int(np.sum(catch_mask))
        total_cells = int(catch_mask.size)
        pixel_area = abs(grid.affine[0] * grid.affine[4])  # approximate pixel area in CRS units squared

        # Elevation stats within watershed
        dem_in_watershed = conditioned_dem[catch_mask].astype(float)
        _nodata = dem.nodata if hasattr(dem, 'nodata') and dem.nodata is not None else -9999
        valid_elev = dem_in_watershed[(dem_in_watershed != _nodata) & (dem_in_watershed > -1000)]

        stats = {
            "pour_point": {"x": px, "y": py},
            "threshold": thresh,
            "watershed_cells": watershed_cells,
            "total_cells": total_cells,
            "watershed_ratio": round(watershed_cells / max(total_cells, 1), 4),
            "pixel_area_deg2": round(pixel_area, 8),
        }

        if len(valid_elev) > 0:
            stats["elevation"] = {
                "min": round(float(np.min(valid_elev)), 1),
                "max": round(float(np.max(valid_elev)), 1),
                "mean": round(float(np.mean(valid_elev)), 1),
                "range": round(float(np.max(valid_elev) - np.min(valid_elev)), 1),
            }

        if watershed_geojson_path and os.path.exists(watershed_geojson_path):
            try:
                gdf_check = gpd.read_file(watershed_geojson_path)
                if "area_km2" in gdf_check.columns:
                    stats["area_km2"] = round(float(gdf_check["area_km2"].iloc[0]), 2)
                if "perimeter_m" in gdf_check.columns:
                    stats["perimeter_km"] = round(float(gdf_check["perimeter_m"].iloc[0]) / 1000, 2)
            except Exception:
                pass

        max_acc = int(np.max(acc[catch_mask])) if watershed_cells > 0 else 0
        stream_cells = int(np.sum((acc > thresh) & catch_mask))
        stats["max_accumulation"] = max_acc
        stats["stream_cells"] = stream_cells

        # ---- Step 13: Generate report text ----
        report_lines = [
            "# 小流域水文分析报告",
            "",
            "## 一、分析概述",
            f"- **DEM 数据源**: {os.path.basename(dem_path)}",
            f"- **分析方法**: D8 流向算法 + pysheds 水文分析引擎",
            f"- **河网提取阈值**: {thresh} (汇流累积单元数)",
            "",
            "## 二、流域基本信息",
            f"- **出口点坐标**: ({px:.6f}, {py:.6f})",
        ]
        if stats.get("area_km2"):
            report_lines.append(f"- **流域面积**: {stats['area_km2']} km²")
        if stats.get("perimeter_km"):
            report_lines.append(f"- **流域周长**: {stats['perimeter_km']} km")
        report_lines.append(f"- **流域栅格单元数**: {watershed_cells}")
        report_lines.append(f"- **流域占比**: {stats['watershed_ratio'] * 100:.1f}%")

        if stats.get("elevation"):
            elev = stats["elevation"]
            report_lines += [
                "",
                "## 三、高程特征",
                f"- **最低高程**: {elev['min']} m",
                f"- **最高高程**: {elev['max']} m",
                f"- **平均高程**: {elev['mean']} m",
                f"- **高差**: {elev['range']} m",
            ]

        report_lines += [
            "",
            "## 四、河网特征",
            f"- **河网栅格单元数**: {stream_cells}",
            f"- **最大汇流累积值**: {max_acc}",
        ]
        if stats.get("area_km2") and stream_cells > 0:
            stream_length_km = stream_cells * abs(grid.affine[0]) * 111  # approximate km per degree
            density = stream_length_km / stats["area_km2"] if stats["area_km2"] > 0 else 0
            report_lines.append(f"- **河网密度** (估算): {density:.2f} km/km²")

        report_lines += [
            "",
            "## 五、输出文件",
            f"- 流域边界: {os.path.basename(watershed_geojson_path) if watershed_geojson_path else '未生成'}",
            f"- 河网数据: {os.path.basename(stream_geojson_path) if stream_geojson_path else '未生成'}",
            f"- 汇流累积栅格: {os.path.basename(acc_path) if acc_path else '未生成'}",
            f"- 可视化地图: {os.path.basename(viz_path) if viz_path else '未生成'}",
        ]

        # Embed visualization image path so report generator auto-inserts it
        if viz_path and os.path.exists(viz_path):
            report_lines += [
                "",
                "## 六、流域分析可视化",
                "",
                viz_path,
                "",
            ]

        report_lines += [
            "## 七、方法说明",
            "本分析采用经典的 D8 单流向水文分析方法：",
            "1. **DEM 预处理**: 填充洼地 → 填充凹陷 → 解析平地，消除数据伪影",
            "2. **流向计算**: D8 算法，每个栅格单元流向最陡下降方向的 8 邻域之一",
            "3. **汇流累积**: 计算每个单元上游汇入的单元数量",
            "4. **河网提取**: 汇流累积值超过阈值的单元构成河网",
            "5. **流域划分**: 从出口点追溯所有上游汇流单元，构成流域边界",
        ]

        report_text = "\n".join(report_lines)

        result = {
            "status": "ok",
            "report_text": report_text,
            "watershed_boundary": watershed_geojson_path,
            "stream_network": stream_geojson_path,
            "flow_accumulation": acc_path,
            "visualization": viz_path,
            "statistics": stats,
        }

        return json.dumps(result, default=str, ensure_ascii=False)

    except ImportError:
        return json.dumps({"status": "error",
                           "message": "pysheds 未安装。请运行: pip install pysheds"})
    except Exception as e:
        logger.warning("Watershed extraction failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


def extract_stream_network(
    dem_path: str,
    threshold: str = "1000",
) -> str:
    """河网提取 — 从 DEM 中提取水系河网。

    Args:
        dem_path: DEM 文件路径 (GeoTIFF)
        threshold: 汇流累积阈值（单元数，越小河网越密）

    Returns:
        JSON 包含河网 GeoJSON 路径和统计信息。
    """
    try:
        from pysheds.grid import Grid

        dem_path = _resolve_path(dem_path)
        if not os.path.exists(dem_path):
            return json.dumps({"status": "error", "message": f"文件不存在: {dem_path}"})

        grid = Grid.from_raster(dem_path)
        dem = grid.read_raster(dem_path)
        conditioned = _preprocess_dem(grid, dem)
        fdir = grid.flowdir(conditioned)
        acc = grid.accumulation(fdir)

        thresh = int(threshold)
        streams = grid.extract_river_network(fdir, acc > thresh)

        stream_path = _generate_output_path("stream_network", "geojson")
        if streams and streams.get("features"):
            with open(stream_path, "w", encoding="utf-8") as f:
                json.dump(streams, f)
            feature_count = len(streams["features"])
        else:
            feature_count = 0
            stream_path = None

        # Stream cells count
        stream_cells = int(np.sum(acc > thresh))

        return json.dumps({
            "status": "ok",
            "stream_network": stream_path,
            "feature_count": feature_count,
            "stream_cells": stream_cells,
            "threshold": thresh,
        }, default=str)

    except ImportError:
        return json.dumps({"status": "error", "message": "pysheds 未安装"})
    except Exception as e:
        logger.warning("Stream extraction failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


def compute_flow_accumulation(
    dem_path: str,
) -> str:
    """汇流累积计算 — 计算 DEM 中每个单元的上游汇水量。

    Args:
        dem_path: DEM 文件路径 (GeoTIFF)

    Returns:
        JSON 包含汇流累积栅格路径和统计信息。
    """
    try:
        from pysheds.grid import Grid

        dem_path = _resolve_path(dem_path)
        if not os.path.exists(dem_path):
            return json.dumps({"status": "error", "message": f"文件不存在: {dem_path}"})

        grid = Grid.from_raster(dem_path)
        dem = grid.read_raster(dem_path)
        conditioned = _preprocess_dem(grid, dem)
        fdir = grid.flowdir(conditioned)
        acc = grid.accumulation(fdir)

        # Save accumulation raster
        acc_path = _generate_output_path("flow_accumulation", "tif")
        import rasterio
        profile = {
            "driver": "GTiff", "dtype": "float32",
            "width": acc.shape[1], "height": acc.shape[0], "count": 1,
            "crs": grid.crs if hasattr(grid, 'crs') else "EPSG:4326",
            "transform": grid.affine,
        }
        with rasterio.open(acc_path, 'w', **profile) as dst:
            dst.write(acc.astype(np.float32), 1)

        # Visualization
        viz_path = _generate_output_path("flow_accumulation", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 1, figsize=(10, 8))
            log_acc = np.log1p(acc)
            ax.imshow(log_acc, cmap='Blues',
                     extent=[grid.affine[2], grid.affine[2] + grid.affine[0] * acc.shape[1],
                             grid.affine[5] + grid.affine[4] * acc.shape[0], grid.affine[5]])
            ax.set_title("汇流累积 (对数尺度)")
            plt.colorbar(ax.images[0], ax=ax, label="log(累积值+1)")
            plt.tight_layout()
            plt.savefig(viz_path, dpi=150)
            plt.close(fig)
        except Exception:
            viz_path = None

        return json.dumps({
            "status": "ok",
            "output_file": acc_path,
            "visualization": viz_path,
            "statistics": {
                "max_accumulation": int(np.max(acc)),
                "mean_accumulation": round(float(np.mean(acc)), 1),
                "grid_shape": list(acc.shape),
            },
        }, default=str)

    except ImportError:
        return json.dumps({"status": "error", "message": "pysheds 未安装"})
    except Exception as e:
        logger.warning("Flow accumulation failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})
