"""Tests for grid_anonymize governance tool."""

import json
import os
import tempfile
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box


@pytest.fixture
def sample_dltb_gdf(tmp_path):
    """Create a minimal cq_dltb-like shapefile for testing."""
    polys = [
        box(35608800, 3276500, 35608900, 3276600),
        box(35608900, 3276500, 35609000, 3276600),
        box(35608800, 3276600, 35608900, 3276700),
        box(35608900, 3276600, 35609000, 3276700),
        box(35609000, 3276500, 35609100, 3276600),
    ]
    gdf = gpd.GeoDataFrame({
        "bsm": [1001, 1002, 1003, 1004, 1005],
        "dlbm": ["031", "013", "031", "023", "013"],
        "dlmc": ["有林地", "旱地", "有林地", "其他园地", "旱地"],
        "qsdwdm": ["500116002", "500116002", "500116002", "500116002", "500116002"],
        "qsdwmc": ["红豆村坪山社", "红豆村坪山社", "壁山县飞入地", "现龙村犀牛社", "红豆村天星社"],
        "zldwdm": ["500116002", "500116002", "500116002", "500116002", "500116002"],
        "zldwmc": ["红豆村坪山社", "红豆村坪山社", "壁山县飞入地", "现龙村犀牛社", "红豆村天星社"],
        "tbmj": [5073.14, 14288.70, 688.51, 5439.31, 2519.48],
    }, geometry=polys, crs="EPSG:4523")

    out_path = str(tmp_path / "test_dltb.shp")
    gdf.to_file(out_path, encoding="utf-8")
    return out_path


def test_grid_anonymize_basic(sample_dltb_gdf, tmp_path):
    """Basic grid anonymize produces output with sensitive fields stripped."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    with patch("data_agent.gis_processors._generate_output_path",
               return_value=str(tmp_path / "output.shp")):
        result = json.loads(grid_anonymize(
            file_path=sample_dltb_gdf,
            grid_size_m=100.0,
            level="L2",
            keep_attrs="dlmc,tbmj",
            agg_strategy="mode",
            random_offset=False,
        ))

    assert result["status"] == "ok"
    assert result["grid_count"] > 0
    assert result["grid_size_m"] == 100.0
    assert result["level"] == "L2"
    assert "dlmc" in result["kept_attrs"]
    assert "bsm" in result["stripped_sensitive_fields"]
    assert "qsdwmc" in result["stripped_sensitive_fields"]
    assert "zldwmc" in result["stripped_sensitive_fields"]

    out_gdf = gpd.read_file(result["output_file"])
    assert "GRID_ID" in out_gdf.columns
    assert "dlmc" in out_gdf.columns
    assert "bsm" not in out_gdf.columns
    assert "qsdwmc" not in out_gdf.columns
    assert "qsdwdm" not in out_gdf.columns


def test_grid_anonymize_level_overrides_size(sample_dltb_gdf, tmp_path):
    """Level parameter overrides grid_size_m."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    with patch("data_agent.gis_processors._generate_output_path",
               return_value=str(tmp_path / "output_l3.shp")):
        result = json.loads(grid_anonymize(
            file_path=sample_dltb_gdf,
            grid_size_m=50.0,
            level="L3",
            keep_attrs="dlmc",
            agg_strategy="mode",
            random_offset=False,
        ))

    assert result["status"] == "ok"
    assert result["grid_size_m"] == 250.0
    assert "可公开发布" in result["note"]


def test_grid_anonymize_topk_strategy(sample_dltb_gdf, tmp_path):
    """TopK aggregation produces percentage strings."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    with patch("data_agent.gis_processors._generate_output_path",
               return_value=str(tmp_path / "output_topk.shp")):
        result = json.loads(grid_anonymize(
            file_path=sample_dltb_gdf,
            grid_size_m=200.0,
            level="L2",
            keep_attrs="dlmc",
            agg_strategy="topk",
            random_offset=False,
        ))

    assert result["status"] == "ok"
    out_gdf = gpd.read_file(result["output_file"])
    sample_val = out_gdf["dlmc"].iloc[0]
    assert "%" in sample_val


def test_grid_anonymize_sensitive_field_forced_strip(sample_dltb_gdf, tmp_path):
    """Even if user requests sensitive fields, they are stripped."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    with patch("data_agent.gis_processors._generate_output_path",
               return_value=str(tmp_path / "output_force.shp")):
        result = json.loads(grid_anonymize(
            file_path=sample_dltb_gdf,
            keep_attrs="dlmc,qsdwmc,bsm,tbmj",
            level="L2",
            random_offset=False,
        ))

    assert result["status"] == "ok"
    assert "qsdwmc" in result["stripped_sensitive_fields"]
    assert "bsm" in result["stripped_sensitive_fields"]
    assert "qsdwmc" not in result["kept_attrs"]
    assert "bsm" not in result["kept_attrs"]


def test_grid_anonymize_random_offset(sample_dltb_gdf, tmp_path):
    """Random offset produces different grid origins."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    with patch("data_agent.gis_processors._generate_output_path",
               return_value=str(tmp_path / "output_rnd.shp")):
        result = json.loads(grid_anonymize(
            file_path=sample_dltb_gdf,
            level="L2",
            keep_attrs="dlmc",
            random_offset=True,
        ))

    assert result["status"] == "ok"
    assert result["random_offset_applied"] is True


def test_grid_anonymize_empty_data(tmp_path):
    """Empty input returns error."""
    from data_agent.toolsets.governance_tools import grid_anonymize

    empty_gdf = gpd.GeoDataFrame(
        {"dlmc": []}, geometry=[], crs="EPSG:4523"
    )
    empty_path = str(tmp_path / "empty.shp")
    empty_gdf.to_file(empty_path)

    result = json.loads(grid_anonymize(file_path=empty_path, level="L2"))
    assert result["status"] == "error"
    assert "为空" in result["message"]
