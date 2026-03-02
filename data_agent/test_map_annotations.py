"""Tests for map_annotations module — collaborative spatial commenting."""
import unittest
from unittest.mock import patch, MagicMock


class TestAnnotationsNoDB(unittest.TestCase):
    """Tests for graceful degradation when database is not configured."""

    @patch('data_agent.map_annotations.get_engine', return_value=None)
    def test_create_no_db(self, _):
        from data_agent.map_annotations import create_annotation
        result = create_annotation("user1", 114.3, 30.5, title="test")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["message"])

    @patch('data_agent.map_annotations.get_engine', return_value=None)
    def test_list_no_db(self, _):
        from data_agent.map_annotations import list_annotations
        result = list_annotations("user1")
        self.assertEqual(result["annotations"], [])
        self.assertEqual(result["count"], 0)

    @patch('data_agent.map_annotations.get_engine', return_value=None)
    def test_update_no_db(self, _):
        from data_agent.map_annotations import update_annotation
        result = update_annotation(1, "user1", is_resolved=True)
        self.assertEqual(result["status"], "error")

    @patch('data_agent.map_annotations.get_engine', return_value=None)
    def test_delete_no_db(self, _):
        from data_agent.map_annotations import delete_annotation
        result = delete_annotation(1, "user1")
        self.assertEqual(result["status"], "error")

    def test_update_no_fields(self):
        from data_agent.map_annotations import update_annotation
        with patch('data_agent.map_annotations.get_engine') as mock_engine:
            mock_engine.return_value = MagicMock()
            result = update_annotation(1, "user1")
        self.assertEqual(result["status"], "error")
        self.assertIn("无更新字段", result["message"])


class TestAnnotationAPI(unittest.TestCase):
    """Tests for annotation API endpoints in frontend_api."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_list_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_annotations_list
        req = MagicMock()
        req.query_params = {}
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_list(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_create_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_annotations_create
        req = MagicMock()
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_create(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_update_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_annotations_update
        req = MagicMock()
        req.path_params = {"id": "1"}
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_update(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_delete_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_annotations_delete
        req = MagicMock()
        req.path_params = {"id": "1"}
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_delete(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_create_missing_coords(self, mock_user):
        import asyncio
        import json
        from unittest.mock import AsyncMock
        from data_agent.frontend_api import _api_annotations_create
        user = MagicMock()
        user.identifier = "testuser"
        user.metadata = {"role": "analyst"}
        mock_user.return_value = user
        req = MagicMock()
        req.cookies = {}
        req.json = AsyncMock(return_value={"title": "test"})
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_create(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("lng", body["error"])

    @patch("data_agent.map_annotations.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_list_success(self, mock_user, _):
        import asyncio
        import json
        from data_agent.frontend_api import _api_annotations_list
        user = MagicMock()
        user.identifier = "testuser"
        user.metadata = {"role": "analyst"}
        mock_user.return_value = user
        req = MagicMock()
        req.cookies = {}
        req.query_params = {}
        resp = asyncio.get_event_loop().run_until_complete(_api_annotations_list(req))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("annotations", body)


class TestAnnotationRoutes(unittest.TestCase):
    """Test that annotation routes are registered."""

    def test_routes_include_annotations(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/annotations", paths)
        self.assertIn("/api/annotations/{id:int}", paths)


if __name__ == "__main__":
    unittest.main()
