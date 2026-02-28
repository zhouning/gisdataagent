"""Tests for the audit logging system (audit_logger.py)."""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
from contextvars import copy_context

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.audit_logger import (
    ensure_audit_table,
    record_audit,
    get_user_audit_log,
    get_audit_stats,
    query_audit_log,
    cleanup_old_audit_logs,
    ACTION_LOGIN_SUCCESS,
    ACTION_LOGIN_FAILURE,
    ACTION_USER_REGISTER,
    ACTION_SESSION_START,
    ACTION_FILE_UPLOAD,
    ACTION_PIPELINE_COMPLETE,
    ACTION_REPORT_EXPORT,
    ACTION_SHARE_CREATE,
    ACTION_FILE_DELETE,
    ACTION_TABLE_SHARE,
    ACTION_RBAC_DENIED,
    ACTION_LABELS,
)
from data_agent.database_tools import T_AUDIT_LOG


class TestAuditConstants(unittest.TestCase):
    """Test that all action constants and labels exist."""

    def test_audit_table_name(self):
        self.assertEqual(T_AUDIT_LOG, "agent_audit_log")

    def test_all_action_constants_defined(self):
        actions = [
            ACTION_LOGIN_SUCCESS, ACTION_LOGIN_FAILURE, ACTION_USER_REGISTER,
            ACTION_SESSION_START, ACTION_FILE_UPLOAD, ACTION_PIPELINE_COMPLETE,
            ACTION_REPORT_EXPORT, ACTION_SHARE_CREATE, ACTION_FILE_DELETE,
            ACTION_TABLE_SHARE, ACTION_RBAC_DENIED,
        ]
        self.assertEqual(len(actions), 11)
        for a in actions:
            self.assertIsInstance(a, str)
            self.assertTrue(len(a) > 0)

    def test_all_actions_have_labels(self):
        actions = [
            ACTION_LOGIN_SUCCESS, ACTION_LOGIN_FAILURE, ACTION_USER_REGISTER,
            ACTION_SESSION_START, ACTION_FILE_UPLOAD, ACTION_PIPELINE_COMPLETE,
            ACTION_REPORT_EXPORT, ACTION_SHARE_CREATE, ACTION_FILE_DELETE,
            ACTION_TABLE_SHARE, ACTION_RBAC_DENIED,
        ]
        for a in actions:
            self.assertIn(a, ACTION_LABELS, f"Missing label for {a}")
            self.assertIsInstance(ACTION_LABELS[a], str)

    def test_action_values_are_unique(self):
        actions = [
            ACTION_LOGIN_SUCCESS, ACTION_LOGIN_FAILURE, ACTION_USER_REGISTER,
            ACTION_SESSION_START, ACTION_FILE_UPLOAD, ACTION_PIPELINE_COMPLETE,
            ACTION_REPORT_EXPORT, ACTION_SHARE_CREATE, ACTION_FILE_DELETE,
            ACTION_TABLE_SHARE, ACTION_RBAC_DENIED,
        ]
        self.assertEqual(len(actions), len(set(actions)))


class TestAuditNoDB(unittest.TestCase):
    """Test audit functions when database is not configured (graceful degradation)."""

    @patch("data_agent.audit_logger.get_engine", return_value=None)
    def test_record_audit_noop(self, mock_engine):
        # Should not raise
        record_audit("testuser", ACTION_LOGIN_SUCCESS)

    @patch("data_agent.audit_logger.get_engine", return_value=None)
    def test_ensure_audit_table_prints_warning(self, mock_engine):
        with patch("builtins.print") as mock_print:
            ensure_audit_table()
            printed = " ".join(str(c) for c in mock_print.call_args_list)
            self.assertIn("WARNING", printed)

    @patch("data_agent.audit_logger.get_engine", return_value=None)
    def test_get_user_audit_log_empty(self, mock_engine):
        result = get_user_audit_log("testuser")
        self.assertEqual(result, [])

    @patch("data_agent.audit_logger.get_engine", return_value=None)
    def test_get_audit_stats_zeroed(self, mock_engine):
        result = get_audit_stats()
        self.assertEqual(result["total_events"], 0)
        self.assertEqual(result["active_users"], 0)
        self.assertEqual(result["events_by_action"], {})

    @patch("data_agent.audit_logger.get_engine", return_value=None)
    def test_cleanup_returns_zero(self, mock_engine):
        result = cleanup_old_audit_logs()
        self.assertEqual(result, 0)

    def test_query_audit_log_requires_admin(self):
        """Non-admin users should be denied."""
        from data_agent.user_context import current_user_role
        ctx = copy_context()

        def _run():
            current_user_role.set("analyst")
            return query_audit_log(days=7)

        result = ctx.run(_run)
        self.assertEqual(result["status"], "error")
        self.assertIn("权限不足", result["message"])


class TestAuditWithDB(unittest.TestCase):
    """Integration tests requiring a running PostgreSQL database.
    Auto-skipped if POSTGRES_USER is not set."""

    @classmethod
    def setUpClass(cls):
        from data_agent.database_tools import get_db_connection_url
        if not get_db_connection_url():
            raise unittest.SkipTest("PostgreSQL not configured")
        ensure_audit_table()

    def test_record_and_query_roundtrip(self):
        """Record an event and retrieve it."""
        from data_agent.user_context import current_user_role
        ctx = copy_context()

        test_user = "_test_audit_roundtrip_"
        details = {"test_key": "test_value"}

        # Record
        record_audit(test_user, ACTION_SESSION_START, details=details)

        # Query via get_user_audit_log
        logs = get_user_audit_log(test_user, days=1, limit=10)
        self.assertGreater(len(logs), 0)
        latest = logs[0]
        self.assertEqual(latest["username"], test_user)
        self.assertEqual(latest["action"], ACTION_SESSION_START)
        self.assertEqual(latest["details"].get("test_key"), "test_value")

        # Cleanup
        from data_agent.database_tools import get_db_connection_url
        from sqlalchemy import create_engine, text
        engine = create_engine(get_db_connection_url())
        with engine.connect() as conn:
            conn.execute(text(
                f"DELETE FROM {T_AUDIT_LOG} WHERE username = :u"
            ), {"u": test_user})
            conn.commit()

    def test_audit_stats(self):
        """Stats should return reasonable structure."""
        stats = get_audit_stats(days=1)
        self.assertIn("total_events", stats)
        self.assertIn("active_users", stats)
        self.assertIn("events_by_action", stats)
        self.assertIn("events_by_status", stats)
        self.assertIn("daily_counts", stats)

    def test_query_audit_log_admin(self):
        """Admin should be able to query audit log."""
        from data_agent.user_context import current_user_role
        ctx = copy_context()

        def _run():
            current_user_role.set("admin")
            return query_audit_log(days=1)

        result = ctx.run(_run)
        self.assertEqual(result["status"], "success")

    def test_cleanup_does_not_crash(self):
        """Cleanup should run without error even on empty table."""
        deleted = cleanup_old_audit_logs()
        self.assertIsInstance(deleted, int)
        self.assertGreaterEqual(deleted, 0)


if __name__ == "__main__":
    unittest.main()
