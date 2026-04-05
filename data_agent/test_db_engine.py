"""Tests for the connection pool singleton (db_engine.py)."""
import unittest
from unittest.mock import patch, MagicMock

import data_agent.db_engine as db_engine


class TestGetEngine(unittest.TestCase):
    """Test get_engine() singleton behavior."""

    def setUp(self):
        db_engine.reset_engine()

    def tearDown(self):
        db_engine.reset_engine()

    @patch("data_agent.database_tools.get_db_connection_url", return_value=None)
    def test_no_db_returns_none(self, mock_url):
        result = db_engine.get_engine()
        self.assertIsNone(result)

    @patch("data_agent.db_engine._create_sa_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@localhost/db")
    def test_creates_engine_once(self, mock_url, mock_create):
        mock_create.return_value = MagicMock()
        e1 = db_engine.get_engine()
        e2 = db_engine.get_engine()
        self.assertIs(e1, e2)
        mock_create.assert_called_once()

    @patch("data_agent.db_engine._create_sa_engine")
    @patch("data_agent.database_tools.get_db_connection_url", return_value="postgresql://u:p@localhost/db")
    def test_pool_config(self, mock_url, mock_create):
        mock_create.return_value = MagicMock()
        db_engine.get_engine()
        args, kwargs = mock_create.call_args
        # URL should be passed as first positional arg
        self.assertEqual(args[0], "postgresql://u:p@localhost/db")


class TestResetEngine(unittest.TestCase):
    """Test reset_engine() disposal."""

    def setUp(self):
        db_engine.reset_engine()

    def tearDown(self):
        db_engine.reset_engine()

    def test_reset_disposes_engine(self):
        mock_eng = MagicMock()
        db_engine._engine = mock_eng
        db_engine.reset_engine()
        mock_eng.dispose.assert_called_once()
        self.assertIsNone(db_engine._engine)

    def test_reset_disposes_read_engine(self):
        mock_eng = MagicMock()
        mock_read = MagicMock()
        db_engine._engine = mock_eng
        db_engine._read_engine = mock_read
        db_engine.reset_engine()
        mock_eng.dispose.assert_called_once()
        mock_read.dispose.assert_called_once()
        self.assertIsNone(db_engine._engine)
        self.assertIsNone(db_engine._read_engine)

    def test_reset_noop_when_none(self):
        db_engine.reset_engine()  # should not raise
        self.assertIsNone(db_engine._engine)


if __name__ == "__main__":
    unittest.main()
