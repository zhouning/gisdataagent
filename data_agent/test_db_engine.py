"""Tests for the connection pool singleton (db_engine.py)."""
import unittest
from unittest.mock import patch, MagicMock

import data_agent.db_engine as db_engine


class TestGetEngine(unittest.TestCase):
    """Test get_engine() singleton behavior."""

    def setUp(self):
        db_engine._engine = None

    def tearDown(self):
        db_engine._engine = None

    @patch("data_agent.database_tools.get_db_connection_url", return_value=None)
    def test_no_db_returns_none(self, mock_url):
        result = db_engine.get_engine()
        self.assertIsNone(result)

    @patch("data_agent.db_engine.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@localhost/db")
    def test_creates_engine_once(self, mock_url, mock_create):
        mock_create.return_value = MagicMock()
        e1 = db_engine.get_engine()
        e2 = db_engine.get_engine()
        self.assertIs(e1, e2)
        mock_create.assert_called_once()

    @patch("data_agent.db_engine.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@localhost/db")
    def test_pool_config(self, mock_url, mock_create):
        mock_create.return_value = MagicMock()
        db_engine.get_engine()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["pool_size"], 5)
        self.assertEqual(kwargs["max_overflow"], 10)
        self.assertEqual(kwargs["pool_recycle"], 1800)
        self.assertTrue(kwargs["pool_pre_ping"])


class TestResetEngine(unittest.TestCase):
    """Test reset_engine() disposal."""

    def setUp(self):
        db_engine._engine = None

    def tearDown(self):
        db_engine._engine = None

    def test_reset_disposes_engine(self):
        mock_eng = MagicMock()
        db_engine._engine = mock_eng
        db_engine.reset_engine()
        mock_eng.dispose.assert_called_once()
        self.assertIsNone(db_engine._engine)

    def test_reset_noop_when_none(self):
        db_engine.reset_engine()  # should not raise
        self.assertIsNone(db_engine._engine)


if __name__ == "__main__":
    unittest.main()
