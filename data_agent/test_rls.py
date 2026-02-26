"""
Tests for Row-Level Security (RLS) infrastructure:
- _inject_user_context: injects user + role via set_config
- list_tables: uses table_ownership with context injection
- describe_table: ownership check before describe, access denied for unauthorized
- register_table_ownership: UPSERT into table_ownership
- share_table: admin-only toggle
- ensure_table_ownership_table: startup + superuser warning
- memory.py / token_tracker.py: context injection in DML
"""
import unittest
from unittest.mock import patch, MagicMock, call


class TestInjectUserContext(unittest.TestCase):
    """Test _inject_user_context() helper."""

    @patch("data_agent.database_tools.current_user_role")
    @patch("data_agent.database_tools.current_user_id")
    def test_injects_user_and_role(self, mock_uid, mock_role):
        from data_agent.database_tools import _inject_user_context
        mock_uid.get.return_value = "alice"
        mock_role.get.return_value = "analyst"
        conn = MagicMock()
        _inject_user_context(conn)
        calls = conn.execute.call_args_list
        self.assertEqual(len(calls), 2)
        # First call: set app.current_user
        sql1 = str(calls[0][0][0].text)
        self.assertIn("app.current_user", sql1)
        self.assertEqual(calls[0][1]["uid"], "alice") if calls[0][1] else None
        # Second call: set app.current_user_role
        sql2 = str(calls[1][0][0].text)
        self.assertIn("app.current_user_role", sql2)

    @patch("data_agent.database_tools.current_user_role")
    @patch("data_agent.database_tools.current_user_id")
    def test_anonymous_fallback(self, mock_uid, mock_role):
        from data_agent.database_tools import _inject_user_context
        mock_uid.get.return_value = "anonymous"
        mock_role.get.return_value = "viewer"
        conn = MagicMock()
        _inject_user_context(conn)
        calls = conn.execute.call_args_list
        self.assertEqual(len(calls), 2)

    @patch("data_agent.database_tools.current_user_role")
    @patch("data_agent.database_tools.current_user_id")
    def test_none_user_treated_as_anonymous(self, mock_uid, mock_role):
        from data_agent.database_tools import _inject_user_context
        mock_uid.get.return_value = None
        mock_role.get.return_value = None
        conn = MagicMock()
        _inject_user_context(conn)
        calls = conn.execute.call_args_list
        self.assertEqual(len(calls), 2)


class TestListTables(unittest.TestCase):
    """Test list_tables() with table_ownership registry."""

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_with_registry(self, mock_url, mock_engine, mock_inject):
        from data_agent.database_tools import list_tables
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # has_registry check returns True
        mock_conn.execute.return_value.scalar.return_value = True
        # Table rows: (name, is_shared, owner, is_spatial)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("my_table", False, "alice", True),
            ("shared_data", True, "admin", False),
        ]

        result = list_tables()
        self.assertEqual(result["status"], "success")
        mock_inject.assert_called_once_with(mock_conn)

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_no_db(self, mock_url, mock_engine, mock_inject):
        from data_agent.database_tools import list_tables
        mock_url.return_value = None
        result = list_tables()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_fallback_no_registry(self, mock_url, mock_engine, mock_inject):
        """When table_ownership doesn't exist, fallback to information_schema."""
        from data_agent.database_tools import list_tables
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # has_registry returns False
        mock_conn.execute.return_value.scalar.return_value = False
        # Then two fetchall calls: tables and spatial tables
        mock_conn.execute.return_value.fetchall.side_effect = [
            [("table_a",), ("table_b",)],
            [("table_a",)],
        ]

        result = list_tables()
        self.assertEqual(result["status"], "success")
        self.assertIn("table_a (Spatial)", result["tables"])


class TestDescribeTable(unittest.TestCase):
    """Test describe_table() with ownership check."""

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_system_table_bypass(self, mock_url, mock_engine, mock_inject):
        """System tables skip ownership check."""
        from data_agent.database_tools import describe_table
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # columns query
        mock_conn.execute.return_value.fetchall.return_value = [
            ("id", "integer"), ("username", "character varying"),
        ]

        result = describe_table("agent_app_users")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_access_denied(self, mock_url, mock_engine, mock_inject):
        """Non-system table not in registry → access denied."""
        from data_agent.database_tools import describe_table
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # has_registry = True, then access count = 0
        mock_conn.execute.return_value.scalar.side_effect = [True, 0]

        result = describe_table("secret_table")
        self.assertEqual(result["status"], "error")
        self.assertIn("access denied", result["message"].lower())

    def test_invalid_table_name(self):
        from data_agent.database_tools import describe_table
        result = describe_table("DROP TABLE; --")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid", result["message"])


class TestRegisterTableOwnership(unittest.TestCase):
    """Test register_table_ownership() UPSERT."""

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_register_success(self, mock_url, mock_engine, mock_inject):
        from data_agent.database_tools import register_table_ownership
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = register_table_ownership("my_data", "alice", is_shared=False)
        self.assertEqual(result["status"], "success")
        mock_inject.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("data_agent.database_tools.get_db_connection_url")
    def test_no_db(self, mock_url):
        from data_agent.database_tools import register_table_ownership
        mock_url.return_value = None
        result = register_table_ownership("tbl", "user")
        self.assertEqual(result["status"], "error")


class TestShareTable(unittest.TestCase):
    """Test share_table() admin-only."""

    @patch("data_agent.database_tools.current_user_role")
    def test_non_admin_denied(self, mock_role):
        from data_agent.database_tools import share_table
        mock_role.get.return_value = "analyst"
        result = share_table("some_table")
        self.assertEqual(result["status"], "error")
        self.assertIn("admin", result["message"].lower())

    @patch("data_agent.database_tools._inject_user_context")
    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    @patch("data_agent.database_tools.current_user_role")
    def test_admin_shares(self, mock_role, mock_url, mock_engine, mock_inject):
        from data_agent.database_tools import share_table
        mock_role.get.return_value = "admin"
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1

        result = share_table("my_table")
        self.assertEqual(result["status"], "success")


class TestEnsureTableOwnershipTable(unittest.TestCase):
    """Test ensure_table_ownership_table() startup."""

    @patch("data_agent.database_tools.create_engine")
    @patch("data_agent.database_tools.get_db_connection_url")
    def test_creates_table(self, mock_url, mock_engine):
        from data_agent.database_tools import ensure_table_ownership_table
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        # pg_roles check: not superuser, not bypassrls
        mock_conn.execute.return_value.fetchone.return_value = (False, False)

        ensure_table_ownership_table()
        # Verify CREATE TABLE, CREATE INDEX x2, COMMIT were called
        self.assertGreaterEqual(mock_conn.execute.call_count, 3)
        mock_conn.commit.assert_called_once()

    @patch("data_agent.database_tools.get_db_connection_url")
    def test_no_db_noop(self, mock_url):
        from data_agent.database_tools import ensure_table_ownership_table
        mock_url.return_value = None
        # Should not raise
        ensure_table_ownership_table()


class TestMemoryContextInjection(unittest.TestCase):
    """Verify memory.py DML functions call _inject_user_context."""

    @patch("data_agent.memory._inject_user_context")
    @patch("data_agent.memory.current_user_id")
    @patch("data_agent.memory.create_engine")
    @patch("data_agent.memory.get_db_connection_url")
    def test_save_memory_injects_context(self, mock_url, mock_engine, mock_uid, mock_inject):
        from data_agent.memory import save_memory
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_uid.get.return_value = "alice"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = save_memory("custom", "test_key", '{"foo": "bar"}')
        self.assertEqual(result["status"], "success")
        mock_inject.assert_called_once_with(mock_conn)

    @patch("data_agent.memory._inject_user_context")
    @patch("data_agent.memory.current_user_id")
    @patch("data_agent.memory.create_engine")
    @patch("data_agent.memory.get_db_connection_url")
    def test_recall_memories_injects_context(self, mock_url, mock_engine, mock_uid, mock_inject):
        from data_agent.memory import recall_memories
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_uid.get.return_value = "alice"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        result = recall_memories()
        self.assertEqual(result["status"], "success")
        mock_inject.assert_called_once_with(mock_conn)

    @patch("data_agent.memory._inject_user_context")
    @patch("data_agent.memory.current_user_id")
    @patch("data_agent.memory.create_engine")
    @patch("data_agent.memory.get_db_connection_url")
    def test_delete_memory_injects_context(self, mock_url, mock_engine, mock_uid, mock_inject):
        from data_agent.memory import delete_memory
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_uid.get.return_value = "alice"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1

        result = delete_memory("42")
        self.assertEqual(result["status"], "success")
        mock_inject.assert_called_once_with(mock_conn)


class TestTokenTrackerContextInjection(unittest.TestCase):
    """Verify token_tracker.py DML functions call _inject_user_context."""

    @patch("data_agent.token_tracker._inject_user_context")
    @patch("data_agent.token_tracker.create_engine")
    @patch("data_agent.token_tracker.get_db_connection_url")
    def test_record_usage_injects_context(self, mock_url, mock_engine, mock_inject):
        from data_agent.token_tracker import record_usage
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        record_usage("alice", "general", 100, 50)
        mock_inject.assert_called_once_with(mock_conn)

    @patch("data_agent.token_tracker._inject_user_context")
    @patch("data_agent.token_tracker.create_engine")
    @patch("data_agent.token_tracker.get_db_connection_url")
    def test_get_daily_usage_injects_context(self, mock_url, mock_engine, mock_inject):
        from data_agent.token_tracker import get_daily_usage
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (5, 1000)

        result = get_daily_usage("alice")
        self.assertEqual(result["count"], 5)
        mock_inject.assert_called_once_with(mock_conn)

    @patch("data_agent.token_tracker._inject_user_context")
    @patch("data_agent.token_tracker.create_engine")
    @patch("data_agent.token_tracker.get_db_connection_url")
    def test_get_monthly_usage_injects_context(self, mock_url, mock_engine, mock_inject):
        from data_agent.token_tracker import get_monthly_usage
        mock_url.return_value = "postgresql://test:test@localhost/test"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (10, 5000, 3000, 2000)

        result = get_monthly_usage("alice")
        self.assertEqual(result["count"], 10)
        mock_inject.assert_called_once_with(mock_conn)


if __name__ == "__main__":
    unittest.main()
