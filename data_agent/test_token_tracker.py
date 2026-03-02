import unittest
import os
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from data_agent.token_tracker import (
    ensure_token_table,
    record_usage,
    get_daily_usage,
    get_monthly_usage,
    check_usage_limit,
    get_usage_summary,
    get_pipeline_breakdown,
)
from data_agent.user_context import current_user_id


class TestTokenTrackerNoDB(unittest.TestCase):
    """Tests for graceful degradation when database is not configured."""

    @patch('data_agent.token_tracker.get_engine', return_value=None)
    def test_record_usage_no_db(self, mock_engine):
        # Should not raise
        record_usage("user1", "general", 100, 50)

    @patch('data_agent.token_tracker.get_engine', return_value=None)
    def test_get_daily_usage_no_db(self, mock_engine):
        result = get_daily_usage("user1")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["tokens"], 0)

    @patch('data_agent.token_tracker.get_engine', return_value=None)
    def test_get_monthly_usage_no_db(self, mock_engine):
        result = get_monthly_usage("user1")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total_tokens"], 0)
        self.assertEqual(result["input_tokens"], 0)
        self.assertEqual(result["output_tokens"], 0)

    @patch('data_agent.token_tracker.get_engine', return_value=None)
    def test_get_pipeline_breakdown_no_db(self, mock_engine):
        result = get_pipeline_breakdown("user1")
        self.assertEqual(result, [])


class TestUsageLimits(unittest.TestCase):
    """Tests for usage limit logic."""

    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 0, "tokens": 0})
    def test_admin_no_limits(self, mock_daily):
        result = check_usage_limit("admin_user", "admin")
        self.assertTrue(result["allowed"])

    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 19, "tokens": 50000})
    def test_under_daily_limit(self, mock_daily):
        result = check_usage_limit("user1", "analyst")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["daily_count"], 19)

    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 20, "tokens": 60000})
    def test_at_daily_limit(self, mock_daily):
        result = check_usage_limit("user1", "analyst")
        self.assertFalse(result["allowed"])
        self.assertIn("上限", result["reason"])

    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 25, "tokens": 80000})
    def test_over_daily_limit(self, mock_daily):
        result = check_usage_limit("user1", "viewer")
        self.assertFalse(result["allowed"])

    @patch.dict(os.environ, {"DAILY_ANALYSIS_LIMIT": "5"})
    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 5, "tokens": 10000})
    def test_custom_daily_limit(self, mock_daily):
        result = check_usage_limit("user1", "analyst")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["daily_limit"], 5)

    @patch.dict(os.environ, {"MONTHLY_TOKEN_LIMIT": "100000"})
    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 5, "tokens": 10000})
    @patch('data_agent.token_tracker.get_monthly_usage', return_value={
        "count": 30, "total_tokens": 100000, "input_tokens": 80000, "output_tokens": 20000
    })
    def test_monthly_token_limit_hit(self, mock_monthly, mock_daily):
        result = check_usage_limit("user1", "analyst")
        self.assertFalse(result["allowed"])
        self.assertIn("Token", result["reason"])

    @patch.dict(os.environ, {"MONTHLY_TOKEN_LIMIT": "100000"})
    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 5, "tokens": 10000})
    @patch('data_agent.token_tracker.get_monthly_usage', return_value={
        "count": 30, "total_tokens": 50000, "input_tokens": 40000, "output_tokens": 10000
    })
    def test_monthly_token_under_limit(self, mock_monthly, mock_daily):
        result = check_usage_limit("user1", "analyst")
        self.assertTrue(result["allowed"])

    @patch.dict(os.environ, {"MONTHLY_TOKEN_LIMIT": "100000"})
    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 25, "tokens": 80000})
    def test_admin_exempt_from_monthly_limit(self, mock_daily):
        result = check_usage_limit("admin_user", "admin")
        self.assertTrue(result["allowed"])


class TestUsageSummary(unittest.TestCase):
    """Tests for the get_usage_summary tool function."""

    @patch('data_agent.token_tracker.get_monthly_usage', return_value={
        "count": 10, "total_tokens": 25000, "input_tokens": 20000, "output_tokens": 5000
    })
    @patch('data_agent.token_tracker.get_daily_usage', return_value={"count": 3, "tokens": 5000})
    def test_summary_format(self, mock_daily, mock_monthly):
        current_user_id.set("test_user")
        result = get_usage_summary()
        self.assertEqual(result["status"], "success")
        self.assertIn("3 次分析", result["message"])
        self.assertIn("5,000 tokens", result["message"])
        self.assertIn("10 次分析", result["message"])
        self.assertIn("25,000 tokens", result["message"])


class TestTokenCRUD(unittest.TestCase):
    """Integration tests for token tracking — requires PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        from data_agent.database_tools import get_db_connection_url
        if not get_db_connection_url():
            raise unittest.SkipTest("Database not configured")
        current_user_id.set("test_token_user")
        ensure_token_table()

    def setUp(self):
        current_user_id.set("test_token_user")

    @classmethod
    def tearDownClass(cls):
        try:
            from data_agent.database_tools import get_db_connection_url
            from sqlalchemy import create_engine, text
            db_url = get_db_connection_url()
            if db_url:
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    conn.execute(text(
                        "DELETE FROM agent_token_usage WHERE username = 'test_token_user'"
                    ))
                    conn.commit()
        except Exception:
            pass

    def test_01_record_and_query_daily(self):
        """Record usage and verify daily query."""
        record_usage("test_token_user", "general", 1000, 500)
        daily = get_daily_usage("test_token_user")
        self.assertGreater(daily["count"], 0)
        self.assertGreater(daily["tokens"], 0)
        print(f"\nDaily: {daily}")

    def test_02_record_and_query_monthly(self):
        """Record usage and verify monthly query."""
        record_usage("test_token_user", "optimization", 2000, 800)
        monthly = get_monthly_usage("test_token_user")
        self.assertGreater(monthly["count"], 0)
        self.assertGreater(monthly["total_tokens"], 0)
        self.assertGreater(monthly["input_tokens"], 0)
        self.assertGreater(monthly["output_tokens"], 0)
        print(f"\nMonthly: {monthly}")

    def test_03_usage_summary(self):
        """Test get_usage_summary integration."""
        result = get_usage_summary()
        self.assertEqual(result["status"], "success")
        self.assertIn("次分析", result["message"])
        print(f"\nSummary: {result['message']}")

    def test_04_check_limit_allowed(self):
        """Verify limit check passes for admin."""
        result = check_usage_limit("test_token_user", "admin")
        self.assertTrue(result["allowed"])

    def test_05_pipeline_breakdown(self):
        """Verify pipeline breakdown groups by pipeline_type."""
        result = get_pipeline_breakdown("test_token_user")
        self.assertIsInstance(result, list)
        if len(result) > 0:
            item = result[0]
            self.assertIn("pipeline_type", item)
            self.assertIn("count", item)
            self.assertIn("tokens", item)
            self.assertGreater(item["tokens"], 0)
        print(f"\nBreakdown: {result}")


if __name__ == "__main__":
    unittest.main()
