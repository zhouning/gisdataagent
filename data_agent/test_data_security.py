"""Tests for data security features — classification, masking, RLS, lineage (v15.0)."""
import json
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


def _make_gdf(**cols):
    data = {"geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]}
    data.update(cols)
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


class TestClassifyColumns(unittest.TestCase):
    def test_detect_phone(self):
        from data_agent.data_classification import classify_columns
        df = pd.DataFrame({"tel": ["13812345678", "15900001111", "normal"]})
        result = classify_columns(df)
        self.assertIn("tel", result)
        self.assertTrue(any(p["type"] == "phone" for p in result["tel"]["pii_types"]))

    def test_detect_id_card(self):
        from data_agent.data_classification import classify_columns
        df = pd.DataFrame({"sfz": ["110101199001011234", "normal", "320102198505052345"]})
        result = classify_columns(df)
        self.assertIn("sfz", result)
        self.assertEqual(result["sfz"]["suggested_level"], "restricted")

    def test_detect_email(self):
        from data_agent.data_classification import classify_columns
        df = pd.DataFrame({"contact": ["user@example.com", "test@test.cn", "noemail"]})
        result = classify_columns(df)
        self.assertIn("contact", result)

    def test_no_pii(self):
        from data_agent.data_classification import classify_columns
        df = pd.DataFrame({"code": ["0101", "0201", "0301"], "area": [100.0, 200.0, 300.0]})
        result = classify_columns(df)
        # code and area should not trigger PII patterns
        self.assertNotIn("area", result)

    def test_sensitivity_levels(self):
        from data_agent.data_classification import SENSITIVITY_LEVELS
        self.assertEqual(len(SENSITIVITY_LEVELS), 5)
        self.assertEqual(SENSITIVITY_LEVELS[0], "public")
        self.assertEqual(SENSITIVITY_LEVELS[-1], "secret")


class TestClassifyAsset(unittest.TestCase):
    @patch("data_agent.utils._load_spatial_data")
    def test_classify_with_pii(self, mock_load):
        mock_load.return_value = _make_gdf(phone=["13800138000", "15912345678", "other"])
        from data_agent.data_classification import classify_asset
        result = classify_asset("/test.shp")
        self.assertEqual(result["status"], "ok")
        self.assertIn(result["sensitivity_level"], ("confidential", "restricted"))
        self.assertGreater(result["pii_fields_found"], 0)

    @patch("data_agent.utils._load_spatial_data")
    def test_classify_no_pii(self, mock_load):
        mock_load.return_value = _make_gdf(code=["0101", "0201", "0301"])
        from data_agent.data_classification import classify_asset
        result = classify_asset("/test.shp")
        self.assertEqual(result["sensitivity_level"], "public")


class TestMaskDataFrame(unittest.TestCase):
    def test_mask_partial(self):
        from data_agent.data_masking import mask_dataframe
        gdf = _make_gdf(phone=["13812345678", "15900001111", "13600002222"])
        result = mask_dataframe(gdf, {"phone": "mask"})
        self.assertIn("***", result["phone"].iloc[0])

    def test_redact(self):
        from data_agent.data_masking import mask_dataframe
        gdf = _make_gdf(secret=["confidential_data", "private", "internal"])
        result = mask_dataframe(gdf, {"secret": "redact"})
        self.assertTrue(all(v == "[REDACTED]" for v in result["secret"]))

    def test_hash(self):
        from data_agent.data_masking import mask_dataframe
        gdf = _make_gdf(id_card=["110101199001011234", "320102198505052345", "440103197010103456"])
        result = mask_dataframe(gdf, {"id_card": "hash"})
        self.assertEqual(len(result["id_card"].iloc[0]), 16)

    def test_generalize(self):
        from data_agent.data_masking import mask_dataframe
        gdf = _make_gdf(phone=["13812345678", "15900001111", "13600002222"])
        result = mask_dataframe(gdf, {"phone": "generalize"})
        self.assertIn("****", result["phone"].iloc[0])

    def test_unknown_field_skipped(self):
        from data_agent.data_masking import mask_dataframe
        gdf = _make_gdf(name=["A", "B", "C"])
        result = mask_dataframe(gdf, {"nonexistent": "redact"})
        self.assertEqual(list(result["name"]), ["A", "B", "C"])


class TestMaskSensitiveFields(unittest.TestCase):
    @patch("data_agent.gis_processors._generate_output_path", return_value="/tmp/out.gpkg")
    @patch("data_agent.utils._load_spatial_data")
    def test_mask_tool(self, mock_load, mock_out):
        mock_load.return_value = _make_gdf(phone=["13812345678", "15900001111", "13600002222"])
        with patch.object(gpd.GeoDataFrame, "to_file"):
            from data_agent.data_masking import mask_sensitive_fields
            result = json.loads(mask_sensitive_fields("/test.shp", '{"phone": "mask"}'))
        self.assertEqual(result["status"], "ok")
        self.assertIn("phone", result["masked_fields"])


class TestSetAssetSensitivity(unittest.TestCase):
    def test_invalid_level(self):
        from data_agent.data_classification import set_asset_sensitivity
        result = set_asset_sensitivity(1, "invalid_level", "admin")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.db_engine.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_classification import set_asset_sensitivity
        result = set_asset_sensitivity(1, "confidential", "admin")
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
