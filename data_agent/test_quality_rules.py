"""Tests for Quality Rules CRUD + execution + trends (v14.5)."""
import json
import unittest
from unittest.mock import patch, MagicMock


class TestCreateRule(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine")
    def test_create_success(self, mock_eng):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.side_effect = [MagicMock(scalar=MagicMock(return_value=5)), None, MagicMock(scalar=MagicMock(return_value=1))]
        mock_eng.return_value = engine

        from data_agent.quality_rules import create_rule
        result = create_rule("test_rule", "field_check", {"standard_id": "dltb_2023"}, "admin")
        self.assertEqual(result["status"], "ok")

    def test_create_invalid_type(self):
        from data_agent.quality_rules import create_rule
        result = create_rule("test", "invalid_type", {}, "admin")
        self.assertEqual(result["status"], "error")

    def test_create_empty_name(self):
        from data_agent.quality_rules import create_rule
        result = create_rule("", "field_check", {}, "admin")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_create_no_db(self, _):
        from data_agent.quality_rules import create_rule
        result = create_rule("test", "field_check", {}, "admin")
        self.assertEqual(result["status"], "error")


class TestListRules(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_list_no_db(self, _):
        from data_agent.quality_rules import list_rules
        self.assertEqual(list_rules("admin"), [])


class TestDeleteRule(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_delete_no_db(self, _):
        from data_agent.quality_rules import delete_rule
        result = delete_rule(1, "admin")
        self.assertEqual(result["status"], "error")


class TestExecuteRule(unittest.TestCase):
    @patch("data_agent.gis_processors.check_field_standards")
    def test_field_check(self, mock_check):
        mock_check.return_value = {"is_standard": True, "missing_fields": [], "invalid_values": []}
        from data_agent.quality_rules import execute_rule
        rule = {"rule_type": "field_check", "config": {"standard_id": "dltb_2023"}, "standard_id": "dltb_2023"}
        result = execute_rule(rule, "/test.shp")
        self.assertTrue(result["is_standard"])

    def test_unknown_type(self):
        from data_agent.quality_rules import execute_rule
        result = execute_rule({"rule_type": "unknown", "config": {}}, "/test.shp")
        self.assertEqual(result["status"], "error")


class TestExecuteBatch(unittest.TestCase):
    @patch("data_agent.quality_rules.list_rules")
    @patch("data_agent.quality_rules.execute_rule")
    def test_batch(self, mock_exec, mock_list):
        mock_list.return_value = [
            {"id": 1, "rule_name": "R1", "rule_type": "field_check", "severity": "HIGH", "enabled": True,
             "config": {}, "standard_id": "dltb_2023"},
        ]
        mock_exec.return_value = {"is_standard": True, "missing_fields": [], "invalid_values": []}
        from data_agent.quality_rules import execute_rules_batch
        result = execute_rules_batch("/test.shp", owner="admin")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["total_rules"], 1)
        self.assertEqual(result["passed"], 1)


class TestRecordTrend(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.quality_rules import record_trend
        result = record_trend("test.shp", "dltb_2023", 85.0, {}, 3, {}, "admin")
        self.assertEqual(result["status"], "error")


class TestGetTrends(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.quality_rules import get_trends
        self.assertEqual(get_trends(), [])


class TestResourceOverview(unittest.TestCase):
    @patch("data_agent.quality_rules.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.quality_rules import get_resource_overview
        result = get_resource_overview()
        self.assertEqual(result["status"], "error")


class TestConstants(unittest.TestCase):
    def test_valid_rule_types(self):
        from data_agent.quality_rules import VALID_RULE_TYPES
        self.assertIn("field_check", VALID_RULE_TYPES)
        self.assertIn("formula", VALID_RULE_TYPES)
        self.assertIn("topology", VALID_RULE_TYPES)

    def test_valid_severities(self):
        from data_agent.quality_rules import VALID_SEVERITIES
        self.assertEqual(VALID_SEVERITIES, {"CRITICAL", "HIGH", "MEDIUM", "LOW"})


if __name__ == "__main__":
    unittest.main()
