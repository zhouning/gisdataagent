"""Tests for Custom Skill Bundles (v10.0.2).

Covers validation, CRUD, matching, factory, and REST API endpoints.
"""
import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# TestBundleConstants
# ---------------------------------------------------------------------------

class TestBundleConstants(unittest.TestCase):
    def test_table_name(self):
        from data_agent.custom_skill_bundles import T_SKILL_BUNDLES
        self.assertEqual(T_SKILL_BUNDLES, "agent_skill_bundles")

    def test_max_bundles(self):
        from data_agent.custom_skill_bundles import MAX_BUNDLES_PER_USER
        self.assertGreater(MAX_BUNDLES_PER_USER, 0)

    def test_audit_actions(self):
        from data_agent.custom_skill_bundles import (
            ACTION_BUNDLE_CREATE, ACTION_BUNDLE_DELETE, ACTION_BUNDLE_UPDATE)
        self.assertTrue(ACTION_BUNDLE_CREATE)
        self.assertTrue(ACTION_BUNDLE_DELETE)
        self.assertTrue(ACTION_BUNDLE_UPDATE)


# ---------------------------------------------------------------------------
# TestBundleValidation
# ---------------------------------------------------------------------------

class TestBundleValidation(unittest.TestCase):
    def test_validate_bundle_name_ok(self):
        from data_agent.custom_skill_bundles import validate_bundle_name
        self.assertIsNone(validate_bundle_name("my-bundle"))
        self.assertIsNone(validate_bundle_name("空间分析"))
        self.assertIsNone(validate_bundle_name("test_bundle_123"))

    def test_validate_bundle_name_empty(self):
        from data_agent.custom_skill_bundles import validate_bundle_name
        self.assertIsNotNone(validate_bundle_name(""))
        self.assertIsNotNone(validate_bundle_name("   "))

    def test_validate_bundle_name_too_long(self):
        from data_agent.custom_skill_bundles import validate_bundle_name
        self.assertIsNotNone(validate_bundle_name("a" * 101))

    def test_validate_bundle_name_invalid_chars(self):
        from data_agent.custom_skill_bundles import validate_bundle_name
        self.assertIsNotNone(validate_bundle_name("my bundle"))  # space
        self.assertIsNotNone(validate_bundle_name("test@#$"))

    def test_validate_toolset_names_ok(self):
        from data_agent.custom_skill_bundles import validate_toolset_names
        self.assertIsNone(validate_toolset_names(["ExplorationToolset", "DatabaseToolset"]))

    def test_validate_toolset_names_unknown(self):
        from data_agent.custom_skill_bundles import validate_toolset_names
        err = validate_toolset_names(["NonExistentToolset"])
        self.assertIsNotNone(err)
        self.assertIn("NonExistentToolset", err)

    def test_validate_toolset_names_empty(self):
        from data_agent.custom_skill_bundles import validate_toolset_names
        self.assertIsNone(validate_toolset_names([]))

    def test_validate_skill_names_check(self):
        from data_agent.custom_skill_bundles import validate_skill_names
        # unknown skill
        err = validate_skill_names(["nonexistent-skill-xyz"])
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# TestBundleCRUD
# ---------------------------------------------------------------------------

class TestBundleCRUD(unittest.TestCase):
    def test_create_no_user(self):
        from data_agent.custom_skill_bundles import create_skill_bundle
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = ""
            result = create_skill_bundle("test")
            self.assertIsNone(result)

    @patch("data_agent.custom_skill_bundles.get_engine", return_value=None)
    def test_create_no_engine(self, _):
        from data_agent.custom_skill_bundles import create_skill_bundle
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            result = create_skill_bundle("test", toolset_names=["ExplorationToolset"])
            self.assertIsNone(result)

    def test_create_empty_toolsets_and_skills(self):
        from data_agent.custom_skill_bundles import create_skill_bundle
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            # Must have at least one toolset or skill
            result = create_skill_bundle("test", toolset_names=[], skill_names=[])
            self.assertIsNone(result)

    @patch("data_agent.custom_skill_bundles.get_engine")
    def test_create_success(self, mock_engine):
        from data_agent.custom_skill_bundles import create_skill_bundle
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=0)),  # quota check
            MagicMock(scalar=MagicMock(return_value=42)),  # INSERT RETURNING id
        ]
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            result = create_skill_bundle("my-bundle", toolset_names=["ExplorationToolset"])
            self.assertEqual(result, 42)

    @patch("data_agent.custom_skill_bundles.get_engine")
    def test_list_bundles(self, mock_engine):
        from data_agent.custom_skill_bundles import list_skill_bundles
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "alice", "bundle1", "desc", ["ExplorationToolset"], [], ["spatial"], False, True, 5, None, None),
        ]
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            bundles = list_skill_bundles()
            self.assertEqual(len(bundles), 1)
            self.assertEqual(bundles[0]["bundle_name"], "bundle1")

    @patch("data_agent.custom_skill_bundles.get_engine", return_value=None)
    def test_list_bundles_no_engine(self, _):
        from data_agent.custom_skill_bundles import list_skill_bundles
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            result = list_skill_bundles()
            self.assertEqual(result, [])

    @patch("data_agent.custom_skill_bundles.get_engine")
    def test_delete_bundle(self, mock_engine):
        from data_agent.custom_skill_bundles import delete_skill_bundle
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            self.assertTrue(delete_skill_bundle(1))

    def test_delete_no_user(self):
        from data_agent.custom_skill_bundles import delete_skill_bundle
        with patch("data_agent.custom_skill_bundles.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = ""
            self.assertFalse(delete_skill_bundle(1))


# ---------------------------------------------------------------------------
# TestBundleMatching
# ---------------------------------------------------------------------------

class TestBundleMatching(unittest.TestCase):
    @patch("data_agent.custom_skill_bundles.list_skill_bundles")
    def test_find_by_trigger(self, mock_list):
        from data_agent.custom_skill_bundles import find_bundle_by_trigger
        mock_list.return_value = [
            {"bundle_name": "spatial", "intent_triggers": ["buffer", "clip"]},
            {"bundle_name": "data", "intent_triggers": ["query", "sql"]},
        ]
        result = find_bundle_by_trigger("请进行buffer分析")
        self.assertIsNotNone(result)
        self.assertEqual(result["bundle_name"], "spatial")

    @patch("data_agent.custom_skill_bundles.list_skill_bundles")
    def test_find_by_trigger_no_match(self, mock_list):
        from data_agent.custom_skill_bundles import find_bundle_by_trigger
        mock_list.return_value = [
            {"bundle_name": "spatial", "intent_triggers": ["buffer"]},
        ]
        self.assertIsNone(find_bundle_by_trigger("hello world"))

    @patch("data_agent.custom_skill_bundles.list_skill_bundles")
    def test_find_by_name(self, mock_list):
        from data_agent.custom_skill_bundles import find_bundle_by_name
        mock_list.return_value = [
            {"bundle_name": "SpatialBundle"},
        ]
        result = find_bundle_by_name("spatialbundle")
        self.assertIsNotNone(result)

    @patch("data_agent.custom_skill_bundles.list_skill_bundles")
    def test_find_by_name_no_match(self, mock_list):
        from data_agent.custom_skill_bundles import find_bundle_by_name
        mock_list.return_value = []
        self.assertIsNone(find_bundle_by_name("nonexistent"))


# ---------------------------------------------------------------------------
# TestBundleFactory
# ---------------------------------------------------------------------------

class TestBundleFactory(unittest.TestCase):
    @patch("data_agent.custom_skills._get_toolset_registry")
    def test_build_toolsets(self, mock_registry):
        from data_agent.custom_skill_bundles import build_toolsets_from_bundle
        mock_cls = MagicMock()
        mock_registry.return_value = {"ExplorationToolset": mock_cls}
        bundle = {"toolset_names": ["ExplorationToolset"], "skill_names": []}
        result = build_toolsets_from_bundle(bundle)
        self.assertEqual(len(result), 1)
        mock_cls.assert_called_once()

    @patch("data_agent.custom_skills._get_toolset_registry")
    def test_build_unknown_toolset_skipped(self, mock_registry):
        from data_agent.custom_skill_bundles import build_toolsets_from_bundle
        mock_registry.return_value = {}
        bundle = {"toolset_names": ["NonexistentToolset"], "skill_names": []}
        result = build_toolsets_from_bundle(bundle)
        self.assertEqual(len(result), 0)

    def test_get_available_tools(self):
        from data_agent.custom_skill_bundles import get_available_tools
        result = get_available_tools()
        self.assertIn("toolset_names", result)
        self.assertIn("skill_names", result)
        self.assertIsInstance(result["toolset_names"], list)
        self.assertIn("ExplorationToolset", result["toolset_names"])


# ---------------------------------------------------------------------------
# TestBundleRoutes
# ---------------------------------------------------------------------------

class TestBundleRoutes(unittest.TestCase):
    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/bundles", paths)
        self.assertIn("/api/bundles/available-tools", paths)
        self.assertIn("/api/bundles/{id:int}", paths)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_list_unauthorized(self, _):
        from data_agent.frontend_api import _api_bundles_list
        resp = _run_async(_api_bundles_list(MagicMock()))
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# TestADKSkillNames
# ---------------------------------------------------------------------------

class TestADKSkillNames(unittest.TestCase):
    def test_get_adk_skill_names(self):
        from data_agent.custom_skill_bundles import _get_adk_skill_names
        names = _get_adk_skill_names()
        self.assertIsInstance(names, set)
        # There should be at least some skills (16 expected)
        # but allow for flexible count
        if os.path.isdir(os.path.join(os.path.dirname(__file__), "skills")):
            self.assertGreater(len(names), 0)


if __name__ == "__main__":
    unittest.main()
