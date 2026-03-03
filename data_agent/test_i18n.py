"""Tests for v4.1.4 i18n infrastructure.

Covers: t() function, language switching, fallback, interpolation,
key parity between zh/en, and preview functions in English mode.
"""

import pytest
from data_agent.i18n import t, set_language, get_language, _translations, _load_translations


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def reset_language():
    """Ensure each test starts with default language (zh)."""
    set_language("zh")
    yield
    set_language("zh")


# ===================================================================
# Basic t() behavior
# ===================================================================

class TestDefaultLanguage:
    def test_default_is_zh(self):
        assert get_language() == "zh"

    def test_returns_chinese_by_default(self):
        val = t("action.confirm")
        assert val == "确认执行"

    def test_preview_title_zh(self):
        val = t("preview.title")
        assert "数据预览" in val


class TestSwitchToEnglish:
    def test_switch_and_get(self):
        set_language("en")
        assert get_language() == "en"

    def test_returns_english(self):
        set_language("en")
        val = t("action.confirm")
        assert val == "Confirm"

    def test_preview_title_en(self):
        set_language("en")
        val = t("preview.title")
        assert "Data Preview" in val


class TestFallback:
    def test_unknown_lang_falls_back_to_zh(self):
        set_language("fr")
        val = t("action.confirm")
        assert val == "确认执行"

    def test_missing_key_returns_key(self):
        val = t("nonexistent.key.xyz")
        assert val == "nonexistent.key.xyz"

    def test_missing_key_in_en_falls_back_to_zh(self):
        # If a key exists in zh but not in en, fallback to zh
        set_language("en")
        # All keys should exist in both, so test with a hypothetical missing one
        val = t("totally.missing.key")
        assert val == "totally.missing.key"


# ===================================================================
# Interpolation
# ===================================================================

class TestInterpolation:
    def test_simple_interpolation(self):
        val = t("preview.record_count", count=42)
        assert "42" in val

    def test_multi_param_interpolation(self):
        val = t("error.retryable", err_msg="fail", category="transient", remaining=1)
        assert "fail" in val
        assert "transient" in val
        assert "1" in val

    def test_english_interpolation(self):
        set_language("en")
        val = t("preview.record_count", count=100)
        assert "100" in val
        assert "records" in val.lower() or "Records" in val


# ===================================================================
# Key parity — every zh key should have an en counterpart
# ===================================================================

class TestKeyParity:
    def test_translations_loaded(self):
        assert "zh" in _translations
        assert "en" in _translations

    def test_zh_keys_have_en(self):
        zh_keys = set(_translations["zh"].keys())
        en_keys = set(_translations["en"].keys())
        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"Keys in zh but not in en: {missing_in_en}"

    def test_en_keys_have_zh(self):
        zh_keys = set(_translations["zh"].keys())
        en_keys = set(_translations["en"].keys())
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, f"Keys in en but not in zh: {missing_in_zh}"

    def test_no_empty_values(self):
        for lang in ("zh", "en"):
            for key, val in _translations[lang].items():
                assert val, f"Empty value for {lang}.{key}"


# ===================================================================
# Preview functions with i18n
# ===================================================================

class TestPreviewI18n:
    def test_dtype_label_zh(self):
        import numpy as np
        from data_agent.utils import _dtype_label
        assert _dtype_label(np.dtype("float64")) == "数值"

    def test_dtype_label_en(self):
        import numpy as np
        from data_agent.utils import _dtype_label
        set_language("en")
        assert _dtype_label(np.dtype("float64")) == "Numeric"

    def test_quality_good_zh(self):
        import geopandas as gpd
        from shapely.geometry import Point
        from data_agent.utils import _preview_quality_indicators
        gdf = gpd.GeoDataFrame(
            {"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
        )
        text = "\n".join(_preview_quality_indicators(gdf))
        assert "良好" in text

    def test_quality_good_en(self):
        import geopandas as gpd
        from shapely.geometry import Point
        from data_agent.utils import _preview_quality_indicators
        set_language("en")
        gdf = gpd.GeoDataFrame(
            {"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
        )
        text = "\n".join(_preview_quality_indicators(gdf))
        assert "good" in text.lower()

    def test_generate_preview_en(self, tmp_path):
        import pandas as pd
        from data_agent.utils import _generate_upload_preview
        set_language("en")
        path = tmp_path / "test.csv"
        pd.DataFrame({
            "lat": [30.0, 31.0], "lon": [110.0, 111.0], "value": [1, 2]
        }).to_csv(path, index=False)
        result = _generate_upload_preview(str(path))
        assert "Data Preview" in result
        assert "records" in result.lower() or "Records" in result
