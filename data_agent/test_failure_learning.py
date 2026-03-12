"""
Tests for Failure Learning & Adaptation module.

Covers: table initialization, failure recording, hint retrieval,
mark-resolved, graceful degradation without DB.
"""
import unittest
from unittest.mock import MagicMock, patch, call


class TestEnsureFailureTable(unittest.TestCase):
    @patch("data_agent.failure_learning.get_engine")
    def test_creates_table(self, mock_engine):
        """ensure_failure_table executes CREATE TABLE."""
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import ensure_failure_table
        ensure_failure_table()

        # Should have executed CREATE TABLE + 3 indexes + commit = 4 execute + 1 commit
        self.assertTrue(mock_conn.execute.called)
        # At least 4 calls: CREATE TABLE + 3 CREATE INDEX
        self.assertGreaterEqual(mock_conn.execute.call_count, 4)
        mock_conn.commit.assert_called_once()

    @patch("data_agent.failure_learning.get_engine", return_value=None)
    def test_no_db_no_crash(self, mock_engine):
        """ensure_failure_table degrades gracefully without DB."""
        from data_agent.failure_learning import ensure_failure_table
        ensure_failure_table()  # Should not raise


class TestRecordFailure(unittest.TestCase):
    @patch("data_agent.failure_learning.current_user_id")
    @patch("data_agent.failure_learning.get_engine")
    def test_inserts_failure(self, mock_engine, mock_uid):
        """record_failure inserts a row with correct parameters."""
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import record_failure
        record_failure("query_database", "error: relation not found", "list_tables hint")

        mock_conn.execute.assert_called_once()
        # Verify the parameters dict
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        self.assertEqual(params["u"], "test_user")
        self.assertEqual(params["tool"], "query_database")
        self.assertIn("relation not found", params["err"])
        mock_conn.commit.assert_called_once()

    @patch("data_agent.failure_learning.get_engine", return_value=None)
    def test_no_db_no_crash(self, mock_engine):
        """record_failure does nothing without DB."""
        from data_agent.failure_learning import record_failure
        record_failure("some_tool", "error msg")  # Should not raise

    @patch("data_agent.failure_learning.current_user_id")
    @patch("data_agent.failure_learning.get_engine")
    def test_truncates_long_error(self, mock_engine, mock_uid):
        """error_snippet is truncated to 500 chars."""
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import record_failure
        long_error = "x" * 1000
        record_failure("some_tool", long_error)

        params = mock_conn.execute.call_args[0][1]
        self.assertLessEqual(len(params["err"]), 500)


class TestGetFailureHints(unittest.TestCase):
    @patch("data_agent.failure_learning.current_user_id")
    @patch("data_agent.failure_learning.get_engine")
    def test_returns_hints(self, mock_engine, mock_uid):
        """get_failure_hints returns formatted hint strings."""
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("relation not found", "list_tables hint"),
            ("column x missing", "describe_table hint"),
        ]
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import get_failure_hints
        hints = get_failure_hints("query_database")

        self.assertEqual(len(hints), 2)
        self.assertIn("历史经验", hints[0])
        self.assertIn("list_tables", hints[0])

    @patch("data_agent.failure_learning.get_engine", return_value=None)
    def test_no_db_returns_empty(self, mock_engine):
        """get_failure_hints returns empty list without DB."""
        from data_agent.failure_learning import get_failure_hints
        self.assertEqual(get_failure_hints("any_tool"), [])

    @patch("data_agent.failure_learning.current_user_id")
    @patch("data_agent.failure_learning.get_engine")
    def test_empty_hint_skipped(self, mock_engine, mock_uid):
        """Rows with empty hint are not included."""
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("some error", ""),
            ("other error", None),
        ]
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import get_failure_hints
        hints = get_failure_hints("some_tool")
        self.assertEqual(len(hints), 0)


class TestMarkResolved(unittest.TestCase):
    @patch("data_agent.failure_learning.current_user_id")
    @patch("data_agent.failure_learning.get_engine")
    def test_updates_resolved(self, mock_engine, mock_uid):
        """mark_resolved executes an UPDATE with correct params."""
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        from data_agent.failure_learning import mark_resolved
        mark_resolved("query_database")

        mock_conn.execute.assert_called_once()
        params = mock_conn.execute.call_args[0][1]
        self.assertEqual(params["tool"], "query_database")
        self.assertEqual(params["u"], "test_user")
        mock_conn.commit.assert_called_once()

    @patch("data_agent.failure_learning.get_engine", return_value=None)
    def test_no_db_no_crash(self, mock_engine):
        """mark_resolved does nothing without DB."""
        from data_agent.failure_learning import mark_resolved
        mark_resolved("any_tool")  # Should not raise


class TestSelfCorrectionIntegration(unittest.TestCase):
    """Test that _self_correction_after_tool integrates with failure learning."""

    @patch("data_agent.utils._HAS_FAILURE_LEARNING", True)
    @patch("data_agent.utils.record_failure")
    @patch("data_agent.utils.get_failure_hints", return_value=[])
    def test_records_failure_on_error(self, mock_hints, mock_record):
        """Error response triggers record_failure."""
        from data_agent.utils import _self_correction_after_tool, _tool_retry_counts

        tool = MagicMock()
        tool.name = "query_database"
        ctx = MagicMock()
        # Use error text that matches the is_error detection patterns
        response = {"error": "error: relation not found"}

        # Clear retry counts
        _tool_retry_counts.clear()

        _self_correction_after_tool(tool, {}, ctx, response)

        mock_record.assert_called_once()
        self.assertEqual(mock_record.call_args[0][0], "query_database")

    @patch("data_agent.utils._HAS_FAILURE_LEARNING", True)
    @patch("data_agent.utils.mark_resolved")
    def test_marks_resolved_on_success(self, mock_resolve):
        """Successful response triggers mark_resolved."""
        from data_agent.utils import _self_correction_after_tool

        tool = MagicMock()
        tool.name = "query_database"
        ctx = MagicMock()
        response = {"result": "success: 10 rows returned"}

        _self_correction_after_tool(tool, {}, ctx, response)

        mock_resolve.assert_called_once_with("query_database")

    @patch("data_agent.utils._HAS_FAILURE_LEARNING", True)
    @patch("data_agent.utils.record_failure")
    @patch("data_agent.utils.get_failure_hints", return_value=["[历史经验] 曾在此表出错 → 请确认表名"])
    def test_prepends_historical_hints(self, mock_hints, mock_record):
        """Historical hints are prepended to correction hint."""
        from data_agent.utils import _self_correction_after_tool, _tool_retry_counts

        tool = MagicMock()
        tool.name = "query_database"
        ctx = MagicMock()
        # Must match is_error detection: "error" in first 30 chars
        response = {"error": "error: table not found"}

        _tool_retry_counts.clear()

        result = _self_correction_after_tool(tool, {}, ctx, response)

        self.assertIn("历史经验", result["_correction_hint"])


class TestTableConstant(unittest.TestCase):
    def test_tool_failures_constant(self):
        """T_TOOL_FAILURES is defined in database_tools."""
        from data_agent.database_tools import T_TOOL_FAILURES
        self.assertEqual(T_TOOL_FAILURES, "agent_tool_failures")


if __name__ == "__main__":
    unittest.main()
