from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from data_agent.local_gis_runtime import (
    inspect_vector,
    quality_raster,
    quality_vector,
    runtime_info,
    write_cog,
    write_vector,
)


def test_bundled_runtime_reports_filegdb_and_materializers():
    info = runtime_info()
    assert info["adapter"] == "python_gis_runtime"
    assert info["filegdb_reader"] is True
    assert info["vector_writer"] is True
    assert info["raster_cog_writer"] is True


def test_vector_profile_materialization_and_quality(tmp_path):
    source = tmp_path / "source.gpkg"
    frame = gpd.GeoDataFrame(
        {"BSM": ["a", "a"], "DLBM": ["0101", "0102"]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]),
        ],
        crs="EPSG:4490",
    )
    frame.to_file(source, layer="DLTB", driver="GPKG")
    profile = inspect_vector(source)
    assert profile[0]["name"] == "DLTB"
    assert profile[0]["feature_count"] == 2
    target = tmp_path / "DLTB.parquet"
    materialized = write_vector(source, target, layer="DLTB")
    assert materialized["adapter"] == "geopandas_pyogrio"
    assert target.exists()
    quality = quality_vector(source, layer="DLTB", key_fields=["BSM"])
    assert quality["status"] == "review"
    assert quality["duplicate_key_count"] == 2
    assert quality["invalid_geometry_count"] == 1


def test_raster_materialization_is_streaming_and_quality_checked(tmp_path):
    source = tmp_path / "source.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="int16",
        crs="EPSG:4490",
        transform=from_origin(100, 40, 0.01, 0.01),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.ones((1, 32, 32), dtype=np.int16))
    target = tmp_path / "source.cog.tif"
    profile = write_cog(source, target)
    assert profile["adapter"] == "rasterio_gdal"
    assert profile["cloud_optimized"] is True
    quality = quality_raster(target)
    assert quality["status"] == "pass"
    assert quality["sample_valid_pixel_count"] == 32 * 32
