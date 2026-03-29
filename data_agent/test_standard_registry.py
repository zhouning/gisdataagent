"""Tests for Data Standard Registry (v14.5)."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestStandardRegistryLoad(unittest.TestCase):
    def setUp(self):
        from data_agent.standard_registry import StandardRegistry
        StandardRegistry.reset()

    def tearDown(self):
        from data_agent.standard_registry import StandardRegistry
        StandardRegistry.reset()

    def test_load_from_standards_dir(self):
        from data_agent.standard_registry import StandardRegistry
        standards_dir = os.path.join(os.path.dirname(__file__), "standards")
        count = StandardRegistry.load_from_directory(standards_dir)
        self.assertGreaterEqual(count, 2)  # dltb_2023 + gb_t_21010_2017

    def test_list_standards(self):
        from data_agent.standard_registry import StandardRegistry
        standards = StandardRegistry.list_standards()
        self.assertIsInstance(standards, list)
        self.assertGreaterEqual(len(standards), 2)
        ids = [s["id"] for s in standards]
        self.assertIn("dltb_2023", ids)
        self.assertIn("gb_t_21010_2017", ids)

    def test_get_dltb(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        self.assertIsNotNone(std)
        self.assertEqual(std.id, "dltb_2023")
        self.assertEqual(std.name, "地类图斑 (DLTB)")

    def test_get_unknown_returns_none(self):
        from data_agent.standard_registry import StandardRegistry
        self.assertIsNone(StandardRegistry.get("nonexistent_standard"))

    def test_all_ids(self):
        from data_agent.standard_registry import StandardRegistry
        ids = StandardRegistry.all_ids()
        self.assertIn("dltb_2023", ids)
        self.assertIn("gb_t_21010_2017", ids)


class TestDLTBStandard(unittest.TestCase):
    def test_field_count(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        self.assertIsNotNone(std)
        self.assertEqual(len(std.fields), 30)

    def test_mandatory_fields(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        mandatory = std.get_mandatory_fields()
        self.assertIn("BSM", mandatory)
        self.assertIn("DLBM", mandatory)
        self.assertIn("TBMJ", mandatory)
        self.assertIn("SJNF", mandatory)

    def test_qsxz_code_table(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        qsxz = std.code_tables.get("QSXZ", [])
        self.assertEqual(len(qsxz), 10)
        codes = [item["code"] for item in qsxz]
        self.assertIn("10", codes)  # 国有土地
        self.assertIn("20", codes)  # 集体土地

    def test_gdpdjb_code_table(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        pdjb = std.code_tables.get("GDPDJB", [])
        self.assertEqual(len(pdjb), 5)

    def test_get_field(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("dltb_2023")
        dlbm = std.get_field("DLBM")
        self.assertIsNotNone(dlbm)
        self.assertEqual(dlbm.type, "string")
        self.assertEqual(dlbm.required, "M")
        self.assertEqual(dlbm.max_length, 5)


class TestGBT21010Standard(unittest.TestCase):
    def test_dlbm_code_table(self):
        from data_agent.standard_registry import StandardRegistry
        std = StandardRegistry.get("gb_t_21010_2017")
        self.assertIsNotNone(std)
        dlbm = std.code_tables.get("DLBM", [])
        self.assertGreaterEqual(len(dlbm), 60)  # At least 60 codes
        codes = [item["code"] for item in dlbm]
        self.assertIn("0101", codes)  # 水田
        self.assertIn("0301", codes)  # 乔木林地


class TestGetFieldSchema(unittest.TestCase):
    def test_schema_from_dltb(self):
        from data_agent.standard_registry import StandardRegistry
        schema = StandardRegistry.get_field_schema("dltb_2023")
        self.assertIsInstance(schema, dict)
        self.assertIn("QSXZ", schema)
        self.assertIn("allowed", schema["QSXZ"])
        self.assertEqual(len(schema["QSXZ"]["allowed"]), 10)

    def test_schema_from_unknown(self):
        from data_agent.standard_registry import StandardRegistry
        schema = StandardRegistry.get_field_schema("nonexistent")
        self.assertEqual(schema, {})

    def test_get_code_table(self):
        from data_agent.standard_registry import StandardRegistry
        table = StandardRegistry.get_code_table("dltb_2023", "ZZSXDM")
        self.assertEqual(len(table), 8)


class TestLoadFromBadDirectory(unittest.TestCase):
    def test_nonexistent_dir(self):
        from data_agent.standard_registry import StandardRegistry
        StandardRegistry.reset()
        count = StandardRegistry.load_from_directory("/nonexistent/path")
        self.assertEqual(count, 0)


class TestListFgdbLayers(unittest.TestCase):
    @patch("fiona.listlayers", return_value=["roads", "buildings"])
    @patch("fiona.open")
    def test_list_layers(self, mock_fiona_open, mock_listlayers):
        mock_src = MagicMock()
        mock_src.__len__ = MagicMock(return_value=100)
        mock_src.schema = {"geometry": "Polygon", "properties": {"name": "str"}}
        mock_src.__enter__ = MagicMock(return_value=mock_src)
        mock_src.__exit__ = MagicMock(return_value=False)
        mock_fiona_open.return_value = mock_src

        from data_agent.gis_processors import list_fgdb_layers
        with patch("data_agent.gis_processors._resolve_path", return_value="/test.gdb"):
            result = list_fgdb_layers("/test.gdb")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["layer_count"], 2)
        self.assertEqual(result["layers"][0]["name"], "roads")


if __name__ == "__main__":
    unittest.main()
