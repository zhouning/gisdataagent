"""Tests for Remote Sensing Phase 1: spectral indices, experience pool, satellite presets."""
import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock
import numpy as np

from data_agent.spectral_indices import (
    SPECTRAL_INDICES,
    SpectralIndex,
    calculate_spectral_index,
    list_spectral_indices,
    recommend_indices,
    assess_cloud_cover,
    _CATEGORY_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Spectral Index Registry
# ---------------------------------------------------------------------------

class TestSpectralIndexRegistry:
    def test_has_15_plus_indices(self):
        assert len(SPECTRAL_INDICES) >= 15

    def test_all_indices_have_required_fields(self):
        for key, idx in SPECTRAL_INDICES.items():
            assert idx.name, f"{key} missing name"
            assert idx.formula, f"{key} missing formula"
            assert len(idx.bands) > 0, f"{key} missing bands"
            assert idx.description, f"{key} missing description"
            assert idx.category, f"{key} missing category"

    def test_category_coverage(self):
        categories = {idx.category for idx in SPECTRAL_INDICES.values()}
        assert "vegetation" in categories
        assert "water" in categories
        assert "urban" in categories
        assert "fire" in categories
        assert "snow" in categories

    def test_key_indices_present(self):
        expected = {"ndvi", "evi", "savi", "ndwi", "ndbi", "nbr", "mndwi",
                    "bsi", "ndsi", "gndvi", "arvi", "ndre", "lai", "ci", "ndmi"}
        actual = set(SPECTRAL_INDICES.keys())
        assert expected.issubset(actual)

    def test_sentinel2_band_mappings(self):
        """Indices should have S2 band mappings for automated processing."""
        for key, idx in SPECTRAL_INDICES.items():
            if idx.sentinel2_bands:
                for var_name in idx.bands:
                    assert var_name in idx.sentinel2_bands, \
                        f"{key}: band var '{var_name}' missing S2 mapping"


# ---------------------------------------------------------------------------
# list_spectral_indices
# ---------------------------------------------------------------------------

class TestListSpectralIndices:
    def test_returns_json_list(self):
        result = json.loads(list_spectral_indices())
        assert isinstance(result, list)
        assert len(result) >= 15

    def test_each_entry_has_fields(self):
        result = json.loads(list_spectral_indices())
        for entry in result:
            assert "name" in entry
            assert "key" in entry
            assert "category" in entry
            assert "formula" in entry


# ---------------------------------------------------------------------------
# recommend_indices
# ---------------------------------------------------------------------------

class TestRecommendIndices:
    def test_vegetation_keywords(self):
        result = json.loads(recommend_indices("监测农田植被覆盖"))
        recommended = result["recommended"]
        names = {r["key"] for r in recommended}
        assert "ndvi" in names or "evi" in names

    def test_water_keywords(self):
        result = json.loads(recommend_indices("检测水体河流湖泊"))
        recommended = result["recommended"]
        names = {r["key"] for r in recommended}
        assert "ndwi" in names or "mndwi" in names

    def test_urban_keywords(self):
        result = json.loads(recommend_indices("城市建筑检测"))
        recommended = result["recommended"]
        names = {r["key"] for r in recommended}
        assert "ndbi" in names or "bsi" in names

    def test_fire_keywords(self):
        result = json.loads(recommend_indices("fire burn scar assessment"))
        recommended = result["recommended"]
        names = {r["key"] for r in recommended}
        assert "nbr" in names

    def test_default_fallback(self):
        result = json.loads(recommend_indices("some unrelated topic"))
        recommended = result["recommended"]
        assert len(recommended) >= 2  # defaults to NDVI + EVI

    def test_returns_max_5(self):
        result = json.loads(recommend_indices("植被 水体 城市 火灾 积雪 全部"))
        assert len(result["recommended"]) <= 5


# ---------------------------------------------------------------------------
# calculate_spectral_index (mock rasterio)
# ---------------------------------------------------------------------------

class TestCalculateSpectralIndex:
    def test_unknown_index_error(self):
        result = json.loads(calculate_spectral_index("/tmp/fake.tif", "unknown_index"))
        assert result["status"] == "error"
        assert "Unknown index" in result["message"]

    @patch("rasterio.open")
    def test_ndvi_calculation(self, mock_open):
        mock_src = MagicMock()
        mock_src.count = 4
        mock_src.read.side_effect = lambda b: np.array([[0.1, 0.2], [0.3, 0.4]]) if b == 3 else np.array([[0.5, 0.6], [0.7, 0.8]])
        mock_src.nodata = None
        mock_src.profile = {"count": 4, "dtype": "float32"}
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_src

        mock_dst = MagicMock()
        mock_dst.__enter__ = MagicMock(return_value=mock_dst)
        mock_dst.__exit__ = MagicMock(return_value=False)

        # Mock both read and write opens
        mock_open.side_effect = [mock_src, mock_dst]

        with patch("data_agent.gis_processors._generate_output_path", return_value="/tmp/ndvi.tif"):
            result = json.loads(calculate_spectral_index("/tmp/test.tif", "ndvi"))

        assert result["status"] == "success"
        assert result["index"] == "NDVI"
        assert "statistics" in result
        assert result["statistics"]["mean"] is not None

    def test_band_overrides_parsing(self):
        """Band overrides should be parsed from JSON string."""
        result = json.loads(calculate_spectral_index("/tmp/fake.tif", "ndvi", '{"red": 4, "nir": 8}'))
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# assess_cloud_cover (mock rasterio)
# ---------------------------------------------------------------------------

class TestAssessCloudCover:
    @patch("rasterio.open")
    def test_low_cloud(self, mock_open):
        mock_src = MagicMock()
        mock_src.read.return_value = np.array([[0.1, 0.15], [0.2, 0.05]])
        mock_src.nodata = None
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_src

        result = json.loads(assess_cloud_cover("/tmp/clear.tif"))
        assert result["status"] == "success"
        assert result["cloud_percentage"] < 30
        assert result["usable"] is True

    @patch("rasterio.open")
    def test_high_cloud(self, mock_open):
        mock_src = MagicMock()
        mock_src.read.return_value = np.array([[0.9, 0.95], [0.85, 0.92]])
        mock_src.nodata = None
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_src

        result = json.loads(assess_cloud_cover("/tmp/cloudy.tif"))
        assert result["status"] == "success"
        assert result["cloud_percentage"] > 50
        assert result["usable"] is False


# ---------------------------------------------------------------------------
# Experience Pool
# ---------------------------------------------------------------------------

class TestExperiencePool:
    def test_search_vegetation(self):
        from data_agent.toolsets.remote_sensing_tools import search_rs_experience
        result = json.loads(search_rs_experience("植被 农田 NDVI"))
        assert result["status"] == "success"
        assert len(result["matches"]) >= 1
        assert "NDVI" in result["matches"][0]["title"] or "植被" in str(result["matches"][0].get("tags", []))

    def test_search_water(self):
        from data_agent.toolsets.remote_sensing_tools import search_rs_experience
        result = json.loads(search_rs_experience("水体检测"))
        assert result["status"] == "success"
        assert len(result["matches"]) >= 1

    def test_search_fire(self):
        from data_agent.toolsets.remote_sensing_tools import search_rs_experience
        result = json.loads(search_rs_experience("火灾 燃烧"))
        assert result["status"] == "success"
        assert len(result["matches"]) >= 1

    def test_search_no_match(self):
        from data_agent.toolsets.remote_sensing_tools import search_rs_experience
        result = json.loads(search_rs_experience("completely irrelevant topic xyz"))
        assert result["status"] == "success"
        assert len(result["matches"]) == 0

    def test_case_has_recommended_indices(self):
        from data_agent.toolsets.remote_sensing_tools import search_rs_experience
        result = json.loads(search_rs_experience("植被"))
        if result["matches"]:
            case = result["matches"][0]
            assert "recommended_indices" in case


# ---------------------------------------------------------------------------
# Satellite Presets
# ---------------------------------------------------------------------------

class TestSatellitePresets:
    def test_list_presets(self):
        from data_agent.toolsets.remote_sensing_tools import list_satellite_presets
        result = json.loads(list_satellite_presets())
        assert result["status"] == "success"
        assert len(result["presets"]) >= 4

    def test_sentinel2_preset(self):
        from data_agent.toolsets.remote_sensing_tools import list_satellite_presets
        result = json.loads(list_satellite_presets())
        names = {p["name"] for p in result["presets"]}
        assert "sentinel2_l2a" in names

    def test_preset_has_required_fields(self):
        from data_agent.toolsets.remote_sensing_tools import list_satellite_presets
        result = json.loads(list_satellite_presets())
        for preset in result["presets"]:
            assert "name" in preset
            assert "resolution_m" in preset
            assert "bands" in preset
            assert "description" in preset

    def test_sar_preset_no_cloud_cover(self):
        """SAR presets should indicate cloud cover is not applicable."""
        from data_agent.toolsets.remote_sensing_tools import list_satellite_presets
        result = json.loads(list_satellite_presets())
        sar = [p for p in result["presets"] if "sentinel1" in p["name"]]
        assert len(sar) >= 1


# ---------------------------------------------------------------------------
# Toolset integration
# ---------------------------------------------------------------------------

class TestRemoteSensingToolset:
    def test_toolset_has_new_tools(self):
        import asyncio
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        tool_names = {t.name for t in tools}
        assert "calculate_spectral_index" in tool_names
        assert "list_spectral_indices" in tool_names
        assert "recommend_indices" in tool_names
        assert "assess_cloud_cover" in tool_names
        assert "search_rs_experience" in tool_names
        assert "list_satellite_presets" in tool_names

    def test_toolset_retains_original_tools(self):
        import asyncio
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        tool_names = {t.name for t in tools}
        assert "describe_raster" in tool_names
        assert "calculate_ndvi" in tool_names
        assert "download_dem" in tool_names
        assert "download_lulc" in tool_names

    def test_total_tool_count(self):
        import asyncio
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        assert len(tools) == 13  # 7 original + 6 new
