"""
Remote Sensing Basics — Raster profiling, NDVI, band math, classification, visualization.

PRD F10: Foundational remote sensing tools for satellite/aerial imagery analysis.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from .gis_processors import _generate_output_path, _resolve_path


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
