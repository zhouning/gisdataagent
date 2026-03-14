"""
Advanced Spatial Analysis Tier 2 (v10.0.3).

Five analytical functions: IDW interpolation, Kriging, GWR,
change detection, and viewshed analysis.
"""
import json
import os
from typing import Optional

import numpy as np

try:
    from .observability import get_logger
    logger = get_logger("spatial_analysis_tier2")
except Exception:
    import logging
    logger = logging.getLogger("spatial_analysis_tier2")


def _resolve_path(file_path: str) -> str:
    """Resolve file path using project conventions."""
    try:
        from .gis_processors import _resolve_path as resolve
        return resolve(file_path)
    except Exception:
        return file_path


def _generate_output_path(prefix: str, ext: str) -> str:
    """Generate UUID-suffixed output path in user sandbox."""
    try:
        from .gis_processors import _generate_output_path as gen
        return gen(prefix, ext)
    except Exception:
        import uuid
        return os.path.join(os.path.dirname(__file__), "uploads",
                            f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}")


# ---------------------------------------------------------------------------
# 1. IDW Interpolation
# ---------------------------------------------------------------------------

def idw_interpolation(
    data_path: str,
    value_column: str,
    resolution: str = "100",
    power: str = "2",
    output_format: str = "geotiff",
) -> str:
    """Inverse Distance Weighted interpolation from point data.

    Args:
        data_path: 点数据文件路径 (CSV/SHP/GeoJSON)
        value_column: 待插值的属性列名
        resolution: 输出栅格分辨率 (米)
        power: IDW 权重幂次 (默认2)
        output_format: 输出格式 (geotiff)

    Returns:
        JSON string with output file path and statistics.
    """
    import geopandas as gpd
    from scipy.interpolate import griddata

    try:
        resolved = _resolve_path(data_path)
        if resolved.endswith(".csv"):
            import pandas as pd
            df = pd.read_csv(resolved)
            # Auto-detect coordinate columns
            lon_col = next((c for c in df.columns if c.lower() in
                           ("lng", "lon", "longitude", "x", "经度")), None)
            lat_col = next((c for c in df.columns if c.lower() in
                           ("lat", "latitude", "y", "纬度")), None)
            if not lon_col or not lat_col:
                return json.dumps({"status": "error", "message": "无法识别坐标列"})
            from shapely.geometry import Point
            gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df[lon_col], df[lat_col])])
        else:
            gdf = gpd.read_file(resolved)

        if value_column not in gdf.columns:
            return json.dumps({"status": "error",
                               "message": f"列 '{value_column}' 不存在。可用列: {list(gdf.columns)}"})

        # Extract coordinates and values
        coords = np.array([(g.x, g.y) for g in gdf.geometry if g is not None])
        values = gdf.loc[gdf.geometry.notna(), value_column].values.astype(float)

        # Remove NaN values
        mask = ~np.isnan(values)
        coords = coords[mask]
        values = values[mask]

        if len(coords) < 3:
            return json.dumps({"status": "error", "message": "至少需要3个有效数据点"})

        res = float(resolution)
        p = float(power)

        # Create interpolation grid
        x_min, y_min = coords.min(axis=0)
        x_max, y_max = coords.max(axis=0)
        xi = np.arange(x_min, x_max + res, res)
        yi = np.arange(y_min, y_max + res, res)
        xi_grid, yi_grid = np.meshgrid(xi, yi)

        # IDW interpolation using scipy as base + custom weighting
        grid_points = np.column_stack([xi_grid.ravel(), yi_grid.ravel()])

        # Compute IDW manually for better control
        result_grid = np.zeros(len(grid_points))
        for i, gp in enumerate(grid_points):
            dists = np.sqrt(np.sum((coords - gp) ** 2, axis=1))
            dists = np.maximum(dists, 1e-10)  # avoid division by zero
            weights = 1.0 / (dists ** p)
            result_grid[i] = np.sum(weights * values) / np.sum(weights)

        result_grid = result_grid.reshape(xi_grid.shape)

        # Save as GeoTIFF
        out_path = _generate_output_path("idw_interpolation", "tif")
        try:
            import rasterio
            from rasterio.transform import from_bounds
            transform = from_bounds(x_min, y_min, x_max + res, y_max + res,
                                    len(xi), len(yi))
            with rasterio.open(out_path, 'w', driver='GTiff',
                              height=len(yi), width=len(xi), count=1,
                              dtype='float32', transform=transform) as dst:
                dst.write(result_grid.astype(np.float32), 1)
        except ImportError:
            # Fallback: save as numpy file
            out_path = _generate_output_path("idw_interpolation", "npy")
            np.save(out_path, result_grid)

        # Generate visualization
        png_path = _generate_output_path("idw_interpolation", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 1, figsize=(10, 8))
            im = ax.imshow(result_grid, extent=[x_min, x_max, y_min, y_max],
                          origin='lower', cmap='RdYlBu_r')
            ax.scatter(coords[:, 0], coords[:, 1], c='black', s=5, alpha=0.5)
            plt.colorbar(im, ax=ax, label=value_column)
            ax.set_title(f"IDW 插值 (power={p})")
            plt.tight_layout()
            plt.savefig(png_path, dpi=150)
            plt.close(fig)
        except Exception:
            png_path = None

        stats = {
            "min": float(np.nanmin(result_grid)),
            "max": float(np.nanmax(result_grid)),
            "mean": float(np.nanmean(result_grid)),
            "std": float(np.nanstd(result_grid)),
            "grid_size": f"{len(xi)}×{len(yi)}",
            "point_count": len(coords),
        }

        return json.dumps({
            "status": "ok",
            "output_file": out_path,
            "visualization": png_path,
            "statistics": stats,
            "method": f"IDW (power={p}, resolution={res})",
        })

    except Exception as e:
        logger.warning("IDW interpolation failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# 2. Kriging Interpolation
# ---------------------------------------------------------------------------

def kriging_interpolation(
    data_path: str,
    value_column: str,
    variogram_model: str = "spherical",
    resolution: str = "100",
) -> str:
    """Ordinary Kriging interpolation with variogram modeling.

    Args:
        data_path: 点数据文件路径
        value_column: 待插值的属性列名
        variogram_model: 变异函数模型 (linear/gaussian/spherical/exponential)
        resolution: 输出栅格分辨率 (米)

    Returns:
        JSON string with output file path, variogram params, and statistics.
    """
    import geopandas as gpd

    try:
        resolved = _resolve_path(data_path)
        gdf = gpd.read_file(resolved)

        if value_column not in gdf.columns:
            return json.dumps({"status": "error",
                               "message": f"列 '{value_column}' 不存在"})

        coords = np.array([(g.x, g.y) for g in gdf.geometry if g is not None])
        values = gdf.loc[gdf.geometry.notna(), value_column].values.astype(float)
        mask = ~np.isnan(values)
        coords = coords[mask]
        values = values[mask]

        if len(coords) < 5:
            return json.dumps({"status": "error", "message": "Kriging 至少需要5个有效数据点"})

        res = float(resolution)
        x_min, y_min = coords.min(axis=0)
        x_max, y_max = coords.max(axis=0)
        xi = np.arange(x_min, x_max + res, res)
        yi = np.arange(y_min, y_max + res, res)

        try:
            from pykrige.ok import OrdinaryKriging
            ok = OrdinaryKriging(
                coords[:, 0], coords[:, 1], values,
                variogram_model=variogram_model, verbose=False, enable_plotting=False
            )
            z, ss = ok.execute("grid", xi, yi)
            variogram_params = {
                "model": variogram_model,
                "sill": float(ok.variogram_model_parameters[0]) if len(ok.variogram_model_parameters) > 0 else None,
                "range": float(ok.variogram_model_parameters[1]) if len(ok.variogram_model_parameters) > 1 else None,
                "nugget": float(ok.variogram_model_parameters[2]) if len(ok.variogram_model_parameters) > 2 else None,
            }
        except ImportError:
            # Fallback to simple IDW if pykrige not installed
            logger.warning("pykrige not installed, falling back to IDW")
            xi_grid, yi_grid = np.meshgrid(xi, yi)
            grid_points = np.column_stack([xi_grid.ravel(), yi_grid.ravel()])
            z = np.zeros(len(grid_points))
            for i, gp in enumerate(grid_points):
                dists = np.sqrt(np.sum((coords - gp) ** 2, axis=1))
                dists = np.maximum(dists, 1e-10)
                weights = 1.0 / (dists ** 2)
                z[i] = np.sum(weights * values) / np.sum(weights)
            z = z.reshape(xi_grid.shape)
            ss = np.zeros_like(z)
            variogram_params = {"model": "IDW_fallback"}

        out_path = _generate_output_path("kriging", "tif")
        try:
            import rasterio
            from rasterio.transform import from_bounds
            transform = from_bounds(x_min, y_min, x_max + res, y_max + res, len(xi), len(yi))
            with rasterio.open(out_path, 'w', driver='GTiff',
                              height=z.shape[0], width=z.shape[1], count=1,
                              dtype='float32', transform=transform) as dst:
                dst.write(z.astype(np.float32), 1)
        except ImportError:
            out_path = _generate_output_path("kriging", "npy")
            np.save(out_path, z)

        # Visualization
        png_path = _generate_output_path("kriging", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, 2, figsize=(14, 6))
            im0 = axes[0].imshow(z, extent=[x_min, x_max, y_min, y_max],
                                origin='lower', cmap='RdYlBu_r')
            axes[0].scatter(coords[:, 0], coords[:, 1], c='black', s=5)
            plt.colorbar(im0, ax=axes[0], label=value_column)
            axes[0].set_title("Kriging 插值结果")

            im1 = axes[1].imshow(ss, extent=[x_min, x_max, y_min, y_max],
                                origin='lower', cmap='YlOrRd')
            plt.colorbar(im1, ax=axes[1], label="Kriging 方差")
            axes[1].set_title("插值不确定性")
            plt.tight_layout()
            plt.savefig(png_path, dpi=150)
            plt.close(fig)
        except Exception:
            png_path = None

        return json.dumps({
            "status": "ok",
            "output_file": out_path,
            "visualization": png_path,
            "variogram": variogram_params,
            "statistics": {
                "min": float(np.nanmin(z)), "max": float(np.nanmax(z)),
                "mean": float(np.nanmean(z)), "point_count": len(coords),
            },
        })

    except Exception as e:
        logger.warning("Kriging failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# 3. Geographically Weighted Regression (GWR)
# ---------------------------------------------------------------------------

def gwr_analysis(
    data_path: str,
    dependent_column: str,
    independent_columns: str,
    kernel: str = "bisquare",
    bandwidth: str = "auto",
) -> str:
    """Geographically Weighted Regression — spatially varying coefficients.

    Args:
        data_path: 空间数据文件路径 (需要几何信息)
        dependent_column: 因变量列名
        independent_columns: 自变量列名 (逗号分隔)
        kernel: 核函数 (gaussian/bisquare/exponential)
        bandwidth: 带宽 (auto=自适应, 或具体数值)

    Returns:
        JSON with coefficient summary, local R², output files.
    """
    import geopandas as gpd

    try:
        resolved = _resolve_path(data_path)
        gdf = gpd.read_file(resolved)

        indep_cols = [c.strip() for c in independent_columns.split(",")]
        all_cols = [dependent_column] + indep_cols
        for c in all_cols:
            if c not in gdf.columns:
                return json.dumps({"status": "error",
                                   "message": f"列 '{c}' 不存在。可用列: {list(gdf.columns)}"})

        # Extract coordinates from centroids
        centroids = gdf.geometry.centroid
        coords_arr = np.column_stack([centroids.x.values, centroids.y.values])

        y = gdf[dependent_column].values.astype(float)
        X = gdf[indep_cols].values.astype(float)

        # Remove NaN rows
        mask = ~(np.isnan(y) | np.any(np.isnan(X), axis=1))
        y = y[mask]
        X = X[mask]
        coords_arr = coords_arr[mask]

        if len(y) < 10:
            return json.dumps({"status": "error", "message": "GWR 至少需要10个有效观测"})

        try:
            from mgwr.gwr import GWR
            from mgwr.sel_bw import Sel_BW
            import libpysal

            # Add intercept
            X_with_intercept = np.column_stack([np.ones(len(y)), X])

            # Bandwidth selection
            if bandwidth == "auto":
                sel = Sel_BW(coords_arr, y.reshape(-1, 1), X_with_intercept)
                bw = sel.search()
            else:
                bw = float(bandwidth)

            gwr_model = GWR(coords_arr, y.reshape(-1, 1), X_with_intercept,
                           bw=bw, kernel=kernel, fixed=False)
            results = gwr_model.fit()

            # Extract local coefficients
            coef_names = ["intercept"] + indep_cols
            coef_summary = {}
            for i, name in enumerate(coef_names):
                col = results.params[:, i]
                coef_summary[name] = {
                    "min": float(np.min(col)), "max": float(np.max(col)),
                    "mean": float(np.mean(col)), "std": float(np.std(col)),
                }

            local_r2 = results.localR2.flatten()
            global_r2 = float(np.mean(local_r2))

            # Save local R² to shapefile
            gdf_out = gdf[mask].copy()
            gdf_out["local_R2"] = local_r2
            for i, name in enumerate(coef_names):
                gdf_out[f"coef_{name}"] = results.params[:, i]

            shp_path = _generate_output_path("gwr_results", "shp")
            gdf_out.to_file(shp_path)

            result_data = {
                "status": "ok",
                "output_file": shp_path,
                "bandwidth": float(bw),
                "kernel": kernel,
                "global_R2": global_r2,
                "coefficient_summary": coef_summary,
                "observations": len(y),
            }

        except ImportError:
            # Fallback: OLS regression for comparison
            logger.warning("mgwr not installed, running OLS fallback")
            from numpy.linalg import lstsq
            X_with_intercept = np.column_stack([np.ones(len(y)), X])
            coeffs, residuals, _, _ = lstsq(X_with_intercept, y, rcond=None)

            y_pred = X_with_intercept @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

            coef_names = ["intercept"] + indep_cols
            coef_summary = {name: {"value": float(c)} for name, c in zip(coef_names, coeffs)}

            result_data = {
                "status": "ok",
                "method": "OLS_fallback (mgwr not installed)",
                "global_R2": float(r2),
                "coefficient_summary": coef_summary,
                "observations": len(y),
            }

        # Visualization
        png_path = _generate_output_path("gwr_results", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            if 'local_r2' in dir():
                fig, ax = plt.subplots(1, 1, figsize=(10, 8))
                sc = ax.scatter(coords_arr[:, 0], coords_arr[:, 1],
                               c=local_r2, cmap='RdYlGn', s=20)
                plt.colorbar(sc, ax=ax, label="Local R²")
                ax.set_title("GWR Local R² Distribution")
                plt.tight_layout()
                plt.savefig(png_path, dpi=150)
                plt.close(fig)
                result_data["visualization"] = png_path
        except Exception:
            pass

        return json.dumps(result_data)

    except Exception as e:
        logger.warning("GWR analysis failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# 4. Spatial Change Detection
# ---------------------------------------------------------------------------

def spatial_change_detection(
    data_path_t1: str,
    data_path_t2: str,
    id_column: str = "auto",
    compare_columns: str = "",
) -> str:
    """Multi-temporal spatial change detection.

    Compare two snapshots of the same area to detect attribute and geometry changes.

    Args:
        data_path_t1: 时期1数据文件路径
        data_path_t2: 时期2数据文件路径
        id_column: 匹配要素的ID列名 (auto=自动检测)
        compare_columns: 比较的属性列 (逗号分隔, 留空=全部)

    Returns:
        JSON with change matrix, summary statistics, output files.
    """
    import geopandas as gpd

    try:
        gdf1 = gpd.read_file(_resolve_path(data_path_t1))
        gdf2 = gpd.read_file(_resolve_path(data_path_t2))

        # Auto-detect ID column
        if id_column == "auto":
            candidates = ["id", "ID", "objectid", "OBJECTID", "fid", "FID", "gid",
                          "pkid", "编号", "地块编号"]
            for c in candidates:
                if c in gdf1.columns and c in gdf2.columns:
                    id_column = c
                    break
            else:
                id_column = gdf1.columns[0]  # fallback to first column

        if id_column not in gdf1.columns or id_column not in gdf2.columns:
            return json.dumps({"status": "error",
                               "message": f"ID列 '{id_column}' 不在两个数据集中"})

        # Determine comparison columns
        if compare_columns:
            comp_cols = [c.strip() for c in compare_columns.split(",")]
        else:
            common = set(gdf1.columns) & set(gdf2.columns) - {"geometry", id_column}
            comp_cols = sorted(common)

        # Match features by ID
        ids_t1 = set(gdf1[id_column].astype(str))
        ids_t2 = set(gdf2[id_column].astype(str))

        added = ids_t2 - ids_t1
        removed = ids_t1 - ids_t2
        common_ids = ids_t1 & ids_t2

        # Detect attribute changes in common features
        changes = []
        gdf1_indexed = gdf1.set_index(gdf1[id_column].astype(str))
        gdf2_indexed = gdf2.set_index(gdf2[id_column].astype(str))

        for fid in sorted(common_ids):
            row1 = gdf1_indexed.loc[fid]
            row2 = gdf2_indexed.loc[fid]
            feature_changes = {"id": fid, "attribute_changes": {}, "geometry_changed": False}

            # Attribute changes
            for col in comp_cols:
                if col in row1.index and col in row2.index:
                    v1 = row1[col] if not hasattr(row1, 'iloc') else row1.iloc[0] if hasattr(row1, 'iloc') else row1[col]
                    v2 = row2[col] if not hasattr(row2, 'iloc') else row2.iloc[0] if hasattr(row2, 'iloc') else row2[col]
                    # Handle Series case (duplicate IDs)
                    if hasattr(v1, 'iloc'):
                        v1 = v1.iloc[0]
                    if hasattr(v2, 'iloc'):
                        v2 = v2.iloc[0]
                    if str(v1) != str(v2):
                        feature_changes["attribute_changes"][col] = {
                            "from": str(v1), "to": str(v2)
                        }

            # Geometry change (area delta)
            geom1 = row1.geometry if not hasattr(row1.geometry, 'iloc') else row1.geometry.iloc[0]
            geom2 = row2.geometry if not hasattr(row2.geometry, 'iloc') else row2.geometry.iloc[0]
            if geom1 is not None and geom2 is not None:
                try:
                    area_delta = abs(geom2.area - geom1.area)
                    if area_delta > 0.01:  # threshold
                        feature_changes["geometry_changed"] = True
                        feature_changes["area_delta"] = float(area_delta)
                except Exception:
                    pass

            if feature_changes["attribute_changes"] or feature_changes["geometry_changed"]:
                changes.append(feature_changes)

        # Build change matrix for categorized columns
        change_matrix = {}
        for col in comp_cols[:5]:  # limit to first 5 columns
            if col in gdf1.columns and col in gdf2.columns:
                transitions = {}
                for ch in changes:
                    if col in ch["attribute_changes"]:
                        key = f"{ch['attribute_changes'][col]['from']} → {ch['attribute_changes'][col]['to']}"
                        transitions[key] = transitions.get(key, 0) + 1
                if transitions:
                    change_matrix[col] = transitions

        # Save change report
        csv_path = _generate_output_path("change_detection", "csv")
        try:
            import csv
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["feature_id", "change_type", "column", "from_value", "to_value"])
                for fid in added:
                    writer.writerow([fid, "added", "", "", ""])
                for fid in removed:
                    writer.writerow([fid, "removed", "", "", ""])
                for ch in changes:
                    for col, vals in ch["attribute_changes"].items():
                        writer.writerow([ch["id"], "changed", col, vals["from"], vals["to"]])
                    if ch["geometry_changed"]:
                        writer.writerow([ch["id"], "geometry_changed", "geometry",
                                        "", f"area_delta={ch.get('area_delta', 'N/A')}"])
        except Exception:
            csv_path = None

        summary = {
            "total_t1": len(ids_t1),
            "total_t2": len(ids_t2),
            "added": len(added),
            "removed": len(removed),
            "unchanged": len(common_ids) - len(changes),
            "changed": len(changes),
            "attribute_changes": sum(len(c["attribute_changes"]) for c in changes),
            "geometry_changes": sum(1 for c in changes if c["geometry_changed"]),
        }

        return json.dumps({
            "status": "ok",
            "summary": summary,
            "change_matrix": change_matrix,
            "output_file": csv_path,
            "id_column": id_column,
            "compared_columns": comp_cols,
        })

    except Exception as e:
        logger.warning("Change detection failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# 5. Viewshed Analysis
# ---------------------------------------------------------------------------

def viewshed_analysis(
    dem_path: str,
    observer_x: str,
    observer_y: str,
    observer_height: str = "1.7",
    max_distance: str = "5000",
) -> str:
    """DEM-based viewshed (visible area) analysis.

    Args:
        dem_path: DEM 栅格文件路径 (GeoTIFF)
        observer_x: 观察点 X 坐标
        observer_y: 观察点 Y 坐标
        observer_height: 观察者高度 (米, 默认1.7)
        max_distance: 最大分析距离 (米, 默认5000)

    Returns:
        JSON with viewshed raster output and statistics.
    """
    try:
        import rasterio
        resolved = _resolve_path(dem_path)

        with rasterio.open(resolved) as src:
            dem = src.read(1)
            transform = src.transform
            profile = src.profile.copy()

        obs_x = float(observer_x)
        obs_y = float(observer_y)
        obs_h = float(observer_height)
        max_dist = float(max_distance)

        # Convert observer coordinates to pixel indices
        inv_transform = ~transform
        col_obs, row_obs = inv_transform * (obs_x, obs_y)
        row_obs, col_obs = int(round(row_obs)), int(round(col_obs))

        if not (0 <= row_obs < dem.shape[0] and 0 <= col_obs < dem.shape[1]):
            return json.dumps({"status": "error", "message": "观察点不在 DEM 范围内"})

        obs_elevation = dem[row_obs, col_obs] + obs_h

        # Simple line-of-sight viewshed
        nrows, ncols = dem.shape
        viewshed = np.zeros_like(dem, dtype=np.uint8)
        pixel_size = abs(transform.a)  # assume square pixels

        max_pixels = int(max_dist / pixel_size) if pixel_size > 0 else min(nrows, ncols)

        # Ray casting from observer to all cells within max_distance
        for row in range(max(0, row_obs - max_pixels), min(nrows, row_obs + max_pixels + 1)):
            for col in range(max(0, col_obs - max_pixels), min(ncols, col_obs + max_pixels + 1)):
                if row == row_obs and col == col_obs:
                    viewshed[row, col] = 1
                    continue

                dx = col - col_obs
                dy = row - row_obs
                dist_pixels = np.sqrt(dx**2 + dy**2)
                dist_meters = dist_pixels * pixel_size

                if dist_meters > max_dist:
                    continue

                # Line of sight: check if any intermediate cell blocks view
                target_elev = dem[row, col]
                target_angle = np.arctan2(target_elev - obs_elevation, dist_meters)

                steps = max(abs(dx), abs(dy))
                visible = True
                for s in range(1, steps):
                    frac = s / steps
                    check_r = int(round(row_obs + dy * frac))
                    check_c = int(round(col_obs + dx * frac))
                    if 0 <= check_r < nrows and 0 <= check_c < ncols:
                        check_dist = np.sqrt((check_c - col_obs)**2 + (check_r - row_obs)**2) * pixel_size
                        if check_dist > 0:
                            check_angle = np.arctan2(dem[check_r, check_c] - obs_elevation, check_dist)
                            if check_angle > target_angle:
                                visible = False
                                break

                if visible:
                    viewshed[row, col] = 1

        # Save viewshed raster
        out_path = _generate_output_path("viewshed", "tif")
        profile.update(dtype='uint8', count=1, nodata=0)
        with rasterio.open(out_path, 'w', **profile) as dst:
            dst.write(viewshed, 1)

        visible_cells = int(np.sum(viewshed))
        total_cells = int(np.sum(viewshed >= 0))
        visible_area = visible_cells * (pixel_size ** 2)

        # Visualization
        png_path = _generate_output_path("viewshed", "png")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 1, figsize=(10, 8))
            ax.imshow(dem, cmap='terrain', alpha=0.7)
            ax.imshow(viewshed, cmap='Greens', alpha=0.5,
                     vmin=0, vmax=1)
            ax.plot(col_obs, row_obs, 'r*', markersize=15, label='观察点')
            ax.legend()
            ax.set_title(f"可视域分析 (高度={obs_h}m, 最大距离={max_dist}m)")
            plt.tight_layout()
            plt.savefig(png_path, dpi=150)
            plt.close(fig)
        except Exception:
            png_path = None

        return json.dumps({
            "status": "ok",
            "output_file": out_path,
            "visualization": png_path,
            "statistics": {
                "visible_cells": visible_cells,
                "total_cells": total_cells,
                "visible_ratio": round(visible_cells / max(total_cells, 1), 4),
                "visible_area_m2": round(visible_area, 2),
                "observer": {"x": obs_x, "y": obs_y, "height": obs_h},
                "max_distance": max_dist,
            },
        })

    except ImportError:
        return json.dumps({"status": "error", "message": "rasterio 未安装，无法执行可视域分析"})
    except Exception as e:
        logger.warning("Viewshed analysis failed: %s", e)
        return json.dumps({"status": "error", "message": str(e)})
