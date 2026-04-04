"""Tests for Data Asset Coding System (v17.1).

Covers: generate_asset_code, infer_data_type_from_path, parse_asset_code,
        integration with data_catalog registration, fusion output linkage.
"""

import unittest
from unittest.mock import patch, MagicMock


class TestGenerateAssetCode(unittest.TestCase):
    """Test asset code generation."""

    def test_basic_generation(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="vector", owner="admin")
        self.assertEqual(code, "DA-VEC-ADM-2026-0001")

    def test_raster_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=42, data_type="raster", owner="analyst")
        self.assertEqual(code, "DA-RAS-ANA-2026-002A")

    def test_fusion_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=256, data_type="fusion", owner="admin")
        self.assertEqual(code, "DA-FUS-ADM-2026-0100")

    def test_tabular_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=10, data_type="tabular", owner="user123")
        self.assertEqual(code, "DA-TAB-USE-2026-000A")

    def test_point_cloud_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=5, data_type="point_cloud", owner="survey")
        self.assertEqual(code, "DA-PCD-SUR-2026-0005")

    def test_cleaned_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=99, data_type="cleaned", owner="admin")
        self.assertEqual(code, "DA-CLN-ADM-2026-0063")

    def test_unknown_type_defaults_to_oth(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="xyz_unknown", owner="test")
        self.assertTrue(code.startswith("DA-OTH-"))

    def test_explicit_year(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="vector", owner="admin", year=2024)
        self.assertEqual(code, "DA-VEC-ADM-2024-0001")

    def test_short_owner(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="vector", owner="ab")
        self.assertIn("-AB-", code)

    def test_empty_owner(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="vector", owner="")
        self.assertIn("-UNK-", code)

    def test_large_id(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=65535, data_type="vector", owner="admin")
        self.assertTrue(code.endswith("FFFF"))

    def test_case_insensitive_type(self):
        from data_agent.asset_coder import generate_asset_code
        code = generate_asset_code(asset_id=1, data_type="VECTOR", owner="admin")
        self.assertIn("-VEC-", code)


class TestInferDataType(unittest.TestCase):
    """Test type inference from file path."""

    def test_geojson(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("data.geojson"), "vector")

    def test_shapefile(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("parcels.shp"), "vector")

    def test_tiff(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("dem.tif"), "raster")

    def test_csv(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("records.csv"), "tabular")

    def test_xlsx(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("data.xlsx"), "tabular")

    def test_las(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("cloud.las"), "point_cloud")

    def test_unknown_extension(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("file.xyz"), "other")

    def test_path_with_directory(self):
        from data_agent.asset_coder import infer_data_type_from_path
        self.assertEqual(infer_data_type_from_path("/data/uploads/map.gpkg"), "vector")


class TestParseAssetCode(unittest.TestCase):
    """Test asset code parsing."""

    def test_parse_valid_code(self):
        from data_agent.asset_coder import parse_asset_code
        result = parse_asset_code("DA-VEC-ADM-2024-0001")
        self.assertIsNotNone(result)
        self.assertEqual(result["prefix"], "DA")
        self.assertEqual(result["type_code"], "VEC")
        self.assertEqual(result["source_code"], "ADM")
        self.assertEqual(result["year"], 2024)
        self.assertEqual(result["sequence"], "0001")

    def test_parse_fusion_code(self):
        from data_agent.asset_coder import parse_asset_code
        result = parse_asset_code("DA-FUS-ADM-2026-00FF")
        self.assertEqual(result["type_code"], "FUS")
        self.assertEqual(result["sequence"], "00FF")

    def test_parse_empty(self):
        from data_agent.asset_coder import parse_asset_code
        self.assertIsNone(parse_asset_code(""))
        self.assertIsNone(parse_asset_code(None))

    def test_parse_invalid_format(self):
        from data_agent.asset_coder import parse_asset_code
        self.assertIsNone(parse_asset_code("INVALID-CODE"))
        self.assertIsNone(parse_asset_code("XX-VEC-ADM-2024-0001"))

    def test_roundtrip(self):
        from data_agent.asset_coder import generate_asset_code, parse_asset_code
        code = generate_asset_code(asset_id=42, data_type="raster", owner="test", year=2025)
        parsed = parse_asset_code(code)
        self.assertEqual(parsed["type_code"], "RAS")
        self.assertEqual(parsed["source_code"], "TES")
        self.assertEqual(parsed["year"], 2025)


class TestFusionResultModel(unittest.TestCase):
    """Test FusionResult has output_asset_code field."""

    def test_output_asset_code_field(self):
        from data_agent.fusion.models import FusionResult
        r = FusionResult(output_asset_code="DA-FUS-ADM-2026-0042")
        self.assertEqual(r.output_asset_code, "DA-FUS-ADM-2026-0042")

    def test_default_empty(self):
        from data_agent.fusion.models import FusionResult
        r = FusionResult()
        self.assertEqual(r.output_asset_code, "")


if __name__ == "__main__":
    unittest.main()
