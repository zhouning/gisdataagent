"""Tests for v4.1.3 data upload preview enhancement.

Tests all preview helper functions as pure functions.
No Chainlit or DB mocking required — uses synthetic GeoDataFrames.
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString

import pytest

from data_agent.utils import (
    _format_file_size,
    _dtype_label,
    _preview_file_info,
    _preview_spatial_info,
    _preview_column_info,
    _preview_quality_indicators,
    _preview_numeric_stats,
    _preview_sample_rows,
    _generate_upload_preview,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def point_gdf():
    return gpd.GeoDataFrame({
        "name": ["A", "B", None],
        "value": [10.5, 20.3, 30.1],
        "category": ["cat1", "cat2", "cat1"],
        "geometry": [Point(110, 30), Point(111, 31), Point(112, 32)],
    }, crs="EPSG:4326")


@pytest.fixture
def polygon_gdf():
    p1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    p2 = Polygon([(1, 1), (2, 1), (2, 2), (1, 2)])
    return gpd.GeoDataFrame({
        "DLMC": ["耕地", "林地"],
        "AREA": [100.0, 200.0],
        "geometry": [p1, p2],
    }, crs="EPSG:4326")


@pytest.fixture
def line_gdf():
    return gpd.GeoDataFrame({
        "road_name": ["S101", "G205"],
        "length_km": [12.5, 45.8],
        "geometry": [
            LineString([(110, 30), (111, 31)]),
            LineString([(112, 32), (113, 33)]),
        ],
    }, crs="EPSG:4326")


@pytest.fixture
def null_heavy_gdf():
    return gpd.GeoDataFrame({
        "a": [1, None, None, 4, None],
        "b": [None, None, None, None, None],
        "c": ["x", "y", None, "z", "w"],
        "geometry": [Point(0, 0), None, Point(1, 1), Point(2, 2), Point(3, 3)],
    }, crs="EPSG:4326")


# ===================================================================
# _format_file_size
# ===================================================================

class TestFormatFileSize:
    def test_zero(self):
        assert _format_file_size(0) == "0 B"

    def test_bytes(self):
        assert _format_file_size(500) == "500 B"

    def test_kilobytes(self):
        assert _format_file_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _format_file_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert _format_file_size(1024 ** 3) == "1.00 GB"


# ===================================================================
# _dtype_label
# ===================================================================

class TestDtypeLabel:
    def test_numeric(self):
        assert _dtype_label(np.dtype("float64")) == "数值"
        assert _dtype_label(np.dtype("int32")) == "数值"

    def test_text(self):
        assert _dtype_label(np.dtype("object")) == "文本"

    def test_bool(self):
        assert _dtype_label(np.dtype("bool")) == "布尔"


# ===================================================================
# _preview_spatial_info
# ===================================================================

class TestPreviewSpatialInfo:
    def test_point_data(self, point_gdf):
        lines = _preview_spatial_info(point_gdf)
        text = "\n".join(lines)
        assert "EPSG:4326" in text
        assert "Point" in text
        assert "点要素数" in text

    def test_polygon_area_stats(self, polygon_gdf):
        lines = _preview_spatial_info(polygon_gdf)
        text = "\n".join(lines)
        assert "面积统计" in text

    def test_line_length_stats(self, line_gdf):
        lines = _preview_spatial_info(line_gdf)
        text = "\n".join(lines)
        assert "长度统计" in text

    def test_no_geometry(self):
        gdf = gpd.GeoDataFrame({"a": [1, 2]})
        gdf["geometry"] = None
        lines = _preview_spatial_info(gdf)
        text = "\n".join(lines)
        assert "无空间数据" in text


# ===================================================================
# _preview_column_info
# ===================================================================

class TestPreviewColumnInfo:
    def test_shows_dtypes_and_nulls(self, null_heavy_gdf):
        lines = _preview_column_info(null_heavy_gdf)
        text = "\n".join(lines)
        assert "字段概览" in text
        assert "类型" in text
        assert "空值" in text

    def test_caps_at_12_columns(self):
        cols = {f"col_{i}": range(5) for i in range(15)}
        gdf = gpd.GeoDataFrame(cols, geometry=[Point(0, 0)] * 5)
        lines = _preview_column_info(gdf)
        text = "\n".join(lines)
        assert "还有" in text


# ===================================================================
# _preview_quality_indicators
# ===================================================================

class TestPreviewQuality:
    def test_clean_data(self, polygon_gdf):
        lines = _preview_quality_indicators(polygon_gdf)
        text = "\n".join(lines)
        assert "良好" in text

    def test_null_heavy(self, null_heavy_gdf):
        lines = _preview_quality_indicators(null_heavy_gdf)
        text = "\n".join(lines)
        assert "缺失值" in text
        assert "空几何" in text


# ===================================================================
# _preview_numeric_stats
# ===================================================================

class TestPreviewNumericStats:
    def test_has_stats(self, point_gdf):
        lines = _preview_numeric_stats(point_gdf)
        text = "\n".join(lines)
        assert "数值统计" in text
        assert "最小值" in text

    def test_no_numeric_cols(self):
        gdf = gpd.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[Point(0, 0), Point(1, 1)],
        )
        lines = _preview_numeric_stats(gdf)
        assert lines == []


# ===================================================================
# _generate_upload_preview (end-to-end)
# ===================================================================

class TestGenerateUploadPreview:
    def test_csv_full_preview(self, tmp_path):
        path = tmp_path / "test_data.csv"
        pd.DataFrame({
            "lat": [30.1, 30.2, 30.3],
            "lon": [110.1, 110.2, 110.3],
            "name": ["A", "B", "C"],
            "value": [1, 2, 3],
        }).to_csv(path, index=False)

        result = _generate_upload_preview(str(path))
        assert "数据预览" in result
        assert "CSV" in result
        assert "字段概览" in result
        assert "数值统计" in result

    def test_error_returns_message(self):
        result = _generate_upload_preview("/nonexistent/file.shp")
        assert "数据预览失败" in result

    def test_empty_dataset(self, tmp_path):
        path = tmp_path / "empty.geojson"
        empty = gpd.GeoDataFrame(
            {"id": pd.Series(dtype="int")},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
        )
        empty.to_file(str(path), driver="GeoJSON")
        result = _generate_upload_preview(str(path))
        assert "0 条记录" in result
