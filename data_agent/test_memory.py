import unittest
import os
import json
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from data_agent.memory import (
    ensure_memory_table,
    save_memory,
    recall_memories,
    list_memories,
    delete_memory,
    get_user_preferences,
    get_recent_analysis_results,
    get_analysis_perspective,
    extract_facts_from_conversation,
    save_auto_extract_memories,
    list_auto_extract_memories,
    VALID_MEMORY_TYPES,
)
from data_agent.user_context import current_user_id


class TestMemoryNoDB(unittest.TestCase):
    """Tests for graceful degradation when database is not configured."""

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_save_memory_no_db(self, mock_engine):
        result = save_memory("region", "华东", '{"districts": ["上海"]}')
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库未配置", result["message"])

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_recall_memories_no_db(self, mock_engine):
        result = recall_memories()
        self.assertEqual(result["status"], "error")

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_delete_memory_no_db(self, mock_engine):
        result = delete_memory("1")
        self.assertEqual(result["status"], "error")

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_get_user_preferences_no_db(self, mock_engine):
        result = get_user_preferences()
        self.assertEqual(result, {})

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_get_recent_analysis_no_db(self, mock_engine):
        result = get_recent_analysis_results()
        self.assertEqual(result, [])


class TestMemoryValidation(unittest.TestCase):
    """Tests for input validation (no DB needed)."""

    @patch('data_agent.memory.get_engine', return_value=MagicMock())
    def test_invalid_memory_type(self, mock_engine):
        result = save_memory("invalid_type", "key", '{}')
        self.assertEqual(result["status"], "error")
        self.assertIn("无效的记忆类型", result["message"])

    @patch('data_agent.memory.get_engine', return_value=MagicMock())
    def test_invalid_json_value(self, mock_engine):
        result = save_memory("region", "key", "not json")
        self.assertEqual(result["status"], "error")
        self.assertIn("JSON", result["message"])

    @patch('data_agent.memory.get_engine', return_value=MagicMock())
    def test_invalid_memory_id(self, mock_engine):
        result = delete_memory("not_a_number")
        self.assertEqual(result["status"], "error")
        self.assertIn("数字", result["message"])

    def test_valid_memory_types(self):
        self.assertIn("region", VALID_MEMORY_TYPES)
        self.assertIn("viz_preference", VALID_MEMORY_TYPES)
        self.assertIn("analysis_result", VALID_MEMORY_TYPES)
        self.assertIn("custom", VALID_MEMORY_TYPES)
        self.assertIn("analysis_perspective", VALID_MEMORY_TYPES)
        self.assertIn("auto_extract", VALID_MEMORY_TYPES)


class TestAnalysisPerspective(unittest.TestCase):
    """Tests for get_analysis_perspective helper."""

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_no_db_returns_empty(self, _mock_engine):
        result = get_analysis_perspective()
        self.assertEqual(result, "")

    @patch('data_agent.memory.get_engine')
    def test_returns_perspective_text(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            json.dumps({"perspective": "关注生态红线"}),
        )
        from data_agent.user_context import current_user_id
        current_user_id.set("test_user")
        result = get_analysis_perspective()
        self.assertEqual(result, "关注生态红线")

    @patch('data_agent.memory.get_engine')
    def test_no_perspective_returns_empty(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        from data_agent.user_context import current_user_id
        current_user_id.set("test_user")
        result = get_analysis_perspective()
        self.assertEqual(result, "")


class TestMemoryCRUD(unittest.TestCase):
    """Integration tests for memory CRUD — requires PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        from data_agent.database_tools import get_db_connection_url
        if not get_db_connection_url():
            raise unittest.SkipTest("Database not configured")
        # Set test user context
        current_user_id.set("test_memory_user")
        ensure_memory_table()

    def setUp(self):
        current_user_id.set("test_memory_user")

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        try:
            from data_agent.database_tools import get_db_connection_url
            from sqlalchemy import create_engine, text
            db_url = get_db_connection_url()
            if db_url:
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    conn.execute(text(
                        "DELETE FROM agent_user_memories WHERE username = 'test_memory_user'"
                    ))
                    conn.commit()
        except Exception:
            pass

    def test_01_save_region(self):
        """Save a region memory."""
        result = save_memory(
            "region", "华东区域",
            json.dumps({"districts": ["上海市", "江苏省", "浙江省"]}, ensure_ascii=False),
            "常用分析区域"
        )
        print(f"\nSave region: {result['message']}")
        self.assertEqual(result["status"], "success")

    def test_02_save_viz_preference(self):
        """Save a visualization preference."""
        result = save_memory(
            "viz_preference", "默认配色",
            json.dumps({"basemap": "CartoDB dark_matter", "color_scheme": "YlGnBu"}, ensure_ascii=False)
        )
        print(f"\nSave viz pref: {result['message']}")
        self.assertEqual(result["status"], "success")

    def test_03_recall_by_type(self):
        """Recall memories filtered by type."""
        result = recall_memories(memory_type="region")
        print(f"\nRecall region: {result['message']}")
        self.assertEqual(result["status"], "success")
        self.assertGreater(len(result["memories"]), 0)
        # Check the region we saved
        found = [m for m in result["memories"] if m["key"] == "华东区域"]
        self.assertEqual(len(found), 1)
        self.assertIn("上海市", found[0]["value"]["districts"])

    def test_04_recall_by_keyword(self):
        """Recall memories by keyword search."""
        result = recall_memories(keyword="华东")
        print(f"\nRecall keyword: {result['message']}")
        self.assertEqual(result["status"], "success")
        self.assertGreater(len(result["memories"]), 0)

    def test_05_list_all(self):
        """List all memories."""
        result = list_memories()
        print(f"\nList all: {result['message']}")
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(len(result["memories"]), 2)  # region + viz_pref

    def test_06_upsert(self):
        """Saving with same type+key should update, not duplicate."""
        save_memory(
            "region", "华东区域",
            json.dumps({"districts": ["上海市", "江苏省", "浙江省", "安徽省"]}, ensure_ascii=False),
            "更新后的华东区域"
        )
        result = recall_memories(memory_type="region", keyword="华东")
        found = [m for m in result["memories"] if m["key"] == "华东区域"]
        self.assertEqual(len(found), 1)
        self.assertIn("安徽省", found[0]["value"]["districts"])
        print(f"\nUpsert: now includes 安徽省")

    def test_07_get_user_preferences(self):
        """Internal helper returns merged preferences."""
        prefs = get_user_preferences()
        print(f"\nPreferences: {prefs}")
        self.assertIn("basemap", prefs)
        self.assertEqual(prefs["basemap"], "CartoDB dark_matter")

    def test_08_save_analysis_result(self):
        """Save an analysis result memory."""
        result = save_memory(
            "analysis_result", "选址分析_天安门周围",
            json.dumps({
                "pipeline": "general",
                "files": ["poi_nearby_abc.shp"],
                "summary": "在天安门周围3公里内找到15个银行"
            }, ensure_ascii=False),
            "General Pipeline - 2026-02-24 15:00"
        )
        self.assertEqual(result["status"], "success")

    def test_09_get_recent_analysis_results(self):
        """Internal helper returns recent analysis results."""
        results = get_recent_analysis_results(limit=5)
        print(f"\nRecent analyses: {len(results)} results")
        self.assertGreater(len(results), 0)
        self.assertIn("key", results[0])

    def test_10_delete_memory(self):
        """Delete a specific memory by ID."""
        # First list to get an ID
        all_mems = list_memories()
        self.assertGreater(len(all_mems["memories"]), 0)
        target_id = str(all_mems["memories"][-1]["id"])
        result = delete_memory(target_id)
        print(f"\nDelete: {result['message']}")
        self.assertEqual(result["status"], "success")

    def test_11_delete_others_memory(self):
        """Cannot delete another user's memory."""
        # Save as test_memory_user, then try to delete as another user
        save_result = save_memory("custom", "temp_test", '{"data": 1}')
        self.assertEqual(save_result["status"], "success")

        all_mems = recall_memories(keyword="temp_test")
        if all_mems["memories"]:
            target_id = str(all_mems["memories"][0]["id"])
            # Switch to different user
            current_user_id.set("other_user")
            result = delete_memory(target_id)
            self.assertEqual(result["status"], "error")  # should fail
            # Restore
            current_user_id.set("test_memory_user")


class TestAutoExtract(unittest.TestCase):
    """Tests for auto-extract memory functions (v7.5)."""

    def test_extract_empty_input(self):
        """Empty or short report text returns empty list without calling LLM."""
        result = extract_facts_from_conversation("", "query")
        self.assertEqual(result, [])
        result2 = extract_facts_from_conversation("short", "query")
        self.assertEqual(result2, [])

    @patch('google.genai.Client')
    def test_extract_facts_success(self, mock_client_cls):
        """LLM returns valid JSON array."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = MagicMock(
            text='[{"key": "耕地面积", "value": "总面积1200亩", "category": "data_characteristic"}]'
        )
        result = extract_facts_from_conversation("A" * 100, "分析耕地")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], "耕地面积")

    @patch('google.genai.Client')
    def test_extract_facts_with_code_fences(self, mock_client_cls):
        """LLM wraps JSON in markdown code fences."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = MagicMock(
            text='```json\n[{"key": "k", "value": "v"}]\n```'
        )
        result = extract_facts_from_conversation("A" * 100, "query")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "data_characteristic")  # default

    @patch('google.genai.Client')
    def test_extract_facts_parse_error(self, mock_client_cls):
        """LLM returns non-JSON -> returns empty list."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = MagicMock(text="not json at all")
        result = extract_facts_from_conversation("A" * 100, "query")
        self.assertEqual(result, [])

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_save_auto_extract_no_db(self, _):
        """save_auto_extract_memories returns error when no DB."""
        result = save_auto_extract_memories([{"key": "test", "value": "v", "category": "data_characteristic"}])
        self.assertEqual(result["status"], "error")

    def test_save_auto_extract_empty(self):
        """Empty facts list returns success with saved=0."""
        result = save_auto_extract_memories([])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["saved"], 0)

    @patch('data_agent.memory.get_engine', return_value=None)
    def test_list_auto_extract_no_db(self, _):
        """list_auto_extract_memories returns error when no DB."""
        result = list_auto_extract_memories()
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
