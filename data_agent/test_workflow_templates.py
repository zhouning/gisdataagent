"""Tests for Workflow Templates (v10.0.4).

Covers CRUD, publishing, cloning, rating, seed templates, and REST endpoints.
"""
import asyncio
import json
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


class TestTemplateConstants(unittest.TestCase):
    def test_table_name(self):
        from data_agent.workflow_templates import T_WORKFLOW_TEMPLATES
        self.assertEqual(T_WORKFLOW_TEMPLATES, "agent_workflow_templates")

    def test_builtin_templates_count(self):
        from data_agent.workflow_templates import _BUILTIN_TEMPLATES
        self.assertEqual(len(_BUILTIN_TEMPLATES), 8)


class TestTemplateCRUD(unittest.TestCase):
    def test_create_no_user(self):
        from data_agent.workflow_templates import create_template
        with patch("data_agent.workflow_templates.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = ""
            result = create_template("test", steps=[{"id": "s1"}])
            self.assertIsNone(result)

    def test_create_no_steps(self):
        from data_agent.workflow_templates import create_template
        with patch("data_agent.workflow_templates.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            result = create_template("test", steps=None)
            self.assertIsNone(result)

    @patch("data_agent.workflow_templates.get_engine")
    def test_create_success(self, mock_eng):
        from data_agent.workflow_templates import create_template
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.scalar.return_value = 42

        with patch("data_agent.workflow_templates.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            result = create_template("my-template", steps=[{"id": "s1", "prompt": "test"}])
        self.assertEqual(result, 42)

    @patch("data_agent.workflow_templates.get_engine", return_value=None)
    def test_list_no_engine(self, _):
        from data_agent.workflow_templates import list_templates
        self.assertEqual(list_templates(), [])

    @patch("data_agent.workflow_templates.get_engine")
    def test_list_templates(self, mock_eng):
        from data_agent.workflow_templates import list_templates
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "template1", "desc", "general", "alice", "general",
             [{"id": "s1"}], {}, ["tag1"], True, 5, 20, 5, None, None),
        ]
        result = list_templates()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["template_name"], "template1")
        self.assertEqual(result[0]["rating_avg"], 4.0)  # 20/5

    @patch("data_agent.workflow_templates.get_engine")
    def test_get_template(self, mock_eng):
        from data_agent.workflow_templates import get_template
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            1, "template1", "desc", "general", "alice", "general",
            [{"id": "s1"}], {}, ["tag1"], True, 3, 12, 3, None, None
        )
        result = get_template(1)
        self.assertIsNotNone(result)
        self.assertEqual(result["template_name"], "template1")

    @patch("data_agent.workflow_templates.get_engine")
    def test_get_template_not_found(self, mock_eng):
        from data_agent.workflow_templates import get_template
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        self.assertIsNone(get_template(999))

    @patch("data_agent.workflow_templates.get_engine")
    def test_delete_template(self, mock_eng):
        from data_agent.workflow_templates import delete_template
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1
        with patch("data_agent.workflow_templates.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "alice"
            self.assertTrue(delete_template(1))


class TestTemplateRating(unittest.TestCase):
    def test_rate_invalid_score(self):
        from data_agent.workflow_templates import rate_template
        self.assertFalse(rate_template(1, 0))
        self.assertFalse(rate_template(1, 6))

    @patch("data_agent.workflow_templates.get_engine")
    def test_rate_success(self, mock_eng):
        from data_agent.workflow_templates import rate_template
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1
        self.assertTrue(rate_template(1, 4))


class TestTemplateClone(unittest.TestCase):
    @patch("data_agent.workflow_templates.get_template")
    def test_clone_not_found(self, mock_get):
        from data_agent.workflow_templates import clone_template
        mock_get.return_value = None
        self.assertIsNone(clone_template(999))

    @patch("data_agent.workflow_templates.get_engine")
    @patch("data_agent.workflow_templates.get_template")
    def test_clone_success(self, mock_get, mock_eng):
        from data_agent.workflow_templates import clone_template
        mock_get.return_value = {
            "template_name": "test",
            "pipeline_type": "general",
            "steps": [{"id": "s1"}],
            "default_parameters": {"key": "val"},
        }
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=99)),  # INSERT workflow
            MagicMock(),  # UPDATE clone_count
        ]
        with patch("data_agent.workflow_templates.current_user_id") as mock_ctx:
            mock_ctx.get.return_value = "bob"
            wf_id = clone_template(1)
        self.assertEqual(wf_id, 99)


class TestTemplateRoutes(unittest.TestCase):
    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/templates", paths)
        self.assertIn("/api/templates/{id:int}", paths)
        self.assertIn("/api/templates/{id:int}/clone", paths)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_list_unauthorized(self, _):
        from data_agent.frontend_api import _api_templates_list
        resp = _run_async(_api_templates_list(MagicMock()))
        self.assertEqual(resp.status_code, 401)


class TestTemplateSeed(unittest.TestCase):
    def test_builtin_template_structure(self):
        from data_agent.workflow_templates import _BUILTIN_TEMPLATES
        for tmpl in _BUILTIN_TEMPLATES:
            self.assertIn("template_name", tmpl)
            self.assertIn("steps", tmpl)
            self.assertIsInstance(tmpl["steps"], list)
            self.assertGreater(len(tmpl["steps"]), 0)
            for step in tmpl["steps"]:
                self.assertIn("id", step)
                self.assertIn("prompt", step)


if __name__ == "__main__":
    unittest.main()
