"""Tests for A2A Server (v11.0.4)."""
import unittest
from unittest.mock import patch, MagicMock


class TestAgentCard(unittest.TestCase):
    def test_build_card(self):
        from data_agent.a2a_server import build_agent_card
        card = build_agent_card()
        self.assertEqual(card["name"], "GIS Data Agent")
        self.assertEqual(len(card["skills"]), 5)
        self.assertEqual(card["version"], "11.0")

    def test_card_skills(self):
        from data_agent.a2a_server import build_agent_card
        card = build_agent_card()
        skill_ids = [s["id"] for s in card["skills"]]
        self.assertIn("spatial-analysis", skill_ids)
        self.assertIn("data-governance", skill_ids)
        self.assertIn("land-optimization", skill_ids)
        self.assertIn("visualization", skill_ids)
        self.assertIn("data-fusion", skill_ids)

    def test_card_custom_url(self):
        from data_agent.a2a_server import build_agent_card
        card = build_agent_card(base_url="https://gis.example.com")
        self.assertEqual(card["url"], "https://gis.example.com")


class TestA2AStatus(unittest.TestCase):
    def test_status_default(self):
        from data_agent.a2a_server import get_a2a_status
        status = get_a2a_status()
        self.assertIn("enabled", status)
        self.assertIn("default_role", status)

    def test_mark_started(self):
        from data_agent.a2a_server import mark_started, get_a2a_status
        mark_started()
        status = get_a2a_status()
        self.assertIsNotNone(status["started_at"])
        self.assertGreaterEqual(status["uptime_seconds"], 0)


class TestA2AConstants(unittest.TestCase):
    def test_defaults(self):
        from data_agent.a2a_server import A2A_DEFAULT_ROLE
        self.assertEqual(A2A_DEFAULT_ROLE, "analyst")


class TestA2ARoutes(unittest.TestCase):
    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/a2a/card", paths)
        self.assertIn("/api/a2a/status", paths)


if __name__ == "__main__":
    unittest.main()
