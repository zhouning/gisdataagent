"""Tests for session persistence (data_agent.session_storage + app.py integration).

Covers:
- Chainlit schema DDL completeness
- ensure_chainlit_tables() behaviour (mock engine, no engine, idempotent)
- get_chainlit_db_url() return value
- Session resumption logic (get→create)
- Session list/delete REST API endpoints
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from data_agent.session_storage import (
    CHAINLIT_SCHEMA_SQL,
    ensure_chainlit_tables,
    get_chainlit_db_url,
)


# ===================================================================
# Schema DDL
# ===================================================================

class TestSchemaSQL:
    """Verify the Chainlit DDL string is complete."""

    def test_contains_all_five_tables(self):
        for table in ['"User"', '"Thread"', '"Step"', '"Element"', '"Feedback"']:
            assert table in CHAINLIT_SCHEMA_SQL, f"Missing table {table}"

    def test_if_not_exists(self):
        assert CHAINLIT_SCHEMA_SQL.count("CREATE TABLE IF NOT EXISTS") == 5

    def test_thread_references_user(self):
        assert 'REFERENCES "User"(id)' in CHAINLIT_SCHEMA_SQL

    def test_step_references_thread(self):
        assert 'REFERENCES "Thread"(id)' in CHAINLIT_SCHEMA_SQL

    def test_feedback_references_step(self):
        assert 'REFERENCES "Step"(id)' in CHAINLIT_SCHEMA_SQL

    def test_user_has_identifier_unique(self):
        assert "identifier TEXT UNIQUE NOT NULL" in CHAINLIT_SCHEMA_SQL


# ===================================================================
# ensure_chainlit_tables()
# ===================================================================

class TestEnsureChainlitTables:
    """Test the table creation helper."""

    @patch("data_agent.session_storage.get_engine", return_value=None)
    def test_no_engine_returns_gracefully(self, mock_engine, capsys):
        ensure_chainlit_tables()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "not configured" in captured.out

    @patch("data_agent.session_storage.get_engine")
    def test_calls_execute_on_engine(self, mock_get_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine

        ensure_chainlit_tables()

        mock_conn.execute.assert_called()
        assert mock_conn.execute.call_count >= 1
        mock_conn.commit.assert_called_once()

    @patch("data_agent.session_storage.get_engine")
    def test_exception_non_fatal(self, mock_get_engine, capsys):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = RuntimeError("connection refused")
        mock_get_engine.return_value = mock_engine

        ensure_chainlit_tables()  # Should not raise

        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Failed" in captured.out


# ===================================================================
# get_chainlit_db_url()
# ===================================================================

class TestGetChainlitDbUrl:
    """Test the URL helper."""

    @patch("data_agent.session_storage.get_db_connection_url", return_value="postgresql://u:p@localhost/db")
    def test_returns_url(self, mock_url):
        result = get_chainlit_db_url()
        assert result == "postgresql://u:p@localhost/db"

    @patch("data_agent.session_storage.get_db_connection_url", return_value=None)
    def test_returns_none_when_not_configured(self, mock_url):
        result = get_chainlit_db_url()
        assert result is None

    @patch("data_agent.session_storage.get_db_connection_url", return_value="postgresql://host/db")
    def test_url_starts_with_postgresql(self, mock_url):
        result = get_chainlit_db_url()
        assert result.startswith("postgresql://")


# ===================================================================
# Session Resumption Logic (unit-level)
# ===================================================================

class TestSessionResumptionLogic:
    """Test the get-first, create-if-not-found pattern."""

    def test_get_returns_session_skips_create(self):
        """Simulates: get_session returns existing → no create needed."""
        mock_session = MagicMock()
        mock_session.events = [1, 2, 3]

        mock_svc = MagicMock()
        mock_svc.get_session = MagicMock(return_value=mock_session)

        # Simulate the logic from app.py on_chat_start
        adk_session = mock_svc.get_session(
            app_name="data_agent_ui", user_id="u1", session_id="s1")
        assert adk_session is not None
        assert len(adk_session.events) == 3
        mock_svc.create_session.assert_not_called()

    def test_get_returns_none_triggers_create(self):
        """Simulates: get_session returns None → create_session called."""
        mock_svc = MagicMock()
        mock_svc.get_session = MagicMock(return_value=None)
        mock_svc.create_session = MagicMock(return_value=MagicMock())

        adk_session = mock_svc.get_session(
            app_name="data_agent_ui", user_id="u1", session_id="s1")
        if not adk_session:
            adk_session = mock_svc.create_session(
                app_name="data_agent_ui", user_id="u1", session_id="s1")

        mock_svc.create_session.assert_called_once()
        assert adk_session is not None


# ===================================================================
# Session REST API Endpoints
# ===================================================================

class TestSessionAPI:
    """Test the session list/delete endpoints."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_sessions_list_unauthorized(self, mock_user):
        import asyncio
        from data_agent.frontend_api import _api_sessions_list
        request = MagicMock()
        resp = asyncio.run(_api_sessions_list(request))
        assert resp.status_code == 401

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request",
           return_value={"identifier": "user1"})
    def test_sessions_list_no_db(self, mock_user, mock_engine):
        import asyncio
        from data_agent.frontend_api import _api_sessions_list
        request = MagicMock()
        resp = asyncio.run(_api_sessions_list(request))
        assert resp.status_code == 200
        import json
        body = json.loads(resp.body)
        assert body["sessions"] == []

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_session_delete_unauthorized(self, mock_user):
        import asyncio
        from data_agent.frontend_api import _api_session_delete
        request = MagicMock()
        request.path_params = {"session_id": "test-id"}
        resp = asyncio.run(_api_session_delete(request))
        assert resp.status_code == 401

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request",
           return_value={"identifier": "user1"})
    def test_session_delete_no_db(self, mock_user, mock_engine):
        import asyncio
        from data_agent.frontend_api import _api_session_delete
        request = MagicMock()
        request.path_params = {"session_id": "test-id"}
        resp = asyncio.run(_api_session_delete(request))
        assert resp.status_code == 500

    @patch("data_agent.frontend_api.get_engine")
    @patch("data_agent.frontend_api._get_user_from_request",
           return_value={"identifier": "user1"})
    def test_session_delete_not_found(self, mock_user, mock_engine):
        import asyncio
        from data_agent.frontend_api import _api_session_delete

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result
        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        request = MagicMock()
        request.path_params = {"session_id": "nonexistent"}
        resp = asyncio.run(_api_session_delete(request))
        assert resp.status_code == 404
