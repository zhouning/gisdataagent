"""Raster reprojection and resampling helpers."""
import os
import uuid


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
