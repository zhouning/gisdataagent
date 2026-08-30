"""Tests for Lite Mode (v22.0)."""
import os
import tempfile
from unittest.mock import patch

import pytest

from data_agent.lite_mode import get_lite_status, init_lite_database, is_lite_mode


def test_is_lite_mode_false():
    with patch.dict("os.environ", {"DB_BACKEND": "postgres"}):
        assert is_lite_mode() is False


def test_is_lite_mode_true():
    with patch.dict("os.environ", {"DB_BACKEND": "duckdb"}):
        assert is_lite_mode() is True


def test_is_lite_mode_default():
    with patch.dict("os.environ", {}, clear=True):
        os.environ.pop("DB_BACKEND", None)
        assert is_lite_mode() is False


def test_init_lite_database():
    pytest.importorskip("duckdb")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "test_lite.duckdb")
    result = init_lite_database(db_path)
    assert result["status"] == "ok"
    assert len(result["tables_created"]) >= 4
    assert os.path.exists(db_path)

    # Verify tables exist
    from data_agent.duckdb_adapter import DuckDBAdapter
    adapter = DuckDBAdapter(db_path)
    tables = adapter.list_tables()
    assert "agent_users" in tables
    assert "agent_app_users" in tables
    assert "agent_data_assets" in tables
    assert "agent_audit_log" in tables
    assert "agent_feedback" in tables

    # Verify seed data
    users = adapter.execute("SELECT username FROM agent_users")
    assert ("admin",) in users
    auth_users = adapter.execute(
        "SELECT username, role FROM agent_app_users WHERE username = 'admin'"
    )
    assert auth_users == [("admin", "admin")]
    adapter.close()


def test_init_lite_database_idempotent():
    """Running init twice should not duplicate seed data."""
    pytest.importorskip("duckdb")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "test_idem.duckdb")
    init_lite_database(db_path)
    init_lite_database(db_path)  # second run

    from data_agent.duckdb_adapter import DuckDBAdapter
    adapter = DuckDBAdapter(db_path)
    count = adapter.execute("SELECT COUNT(*) FROM agent_users WHERE username = 'admin'")
    assert count[0][0] == 1  # not duplicated
    adapter.close()


def test_duckdb_path_can_live_outside_application_directory():
    pytest.importorskip("duckdb")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "control", "site.duckdb")
    with patch.dict("os.environ", {"GDA_DUCKDB_PATH": db_path}):
        result = init_lite_database()
        assert result["status"] == "ok"
        assert result["db_path"] == db_path
        assert os.path.exists(db_path)


def test_lite_authentication_registration_and_password_change(tmp_path):
    from data_agent.auth import authenticate_user, change_password, register_user

    db_path = tmp_path / "auth.duckdb"
    with patch.dict(
        "os.environ",
        {
            "DB_BACKEND": "duckdb",
            "GDA_DUCKDB_PATH": str(db_path),
            "GDA_LITE_ADMIN_PASSWORD": "Initial123",
        },
        clear=False,
    ):
        admin = authenticate_user("admin", "Initial123")
        assert admin and admin["role"] == "admin"
        assert authenticate_user("admin", "wrong-password") is None

        registered = register_user("analyst01", "Analyst123", role="analyst")
        assert registered["status"] == "success"
        assert authenticate_user("analyst01", "Analyst123") is not None

        changed = change_password("analyst01", "Analyst123", "Updated123")
        assert changed["status"] == "success"
        assert authenticate_user("analyst01", "Analyst123") is None
        assert authenticate_user("analyst01", "Updated123") is not None


def test_get_lite_status_postgres():
    with patch.dict("os.environ", {"DB_BACKEND": "postgres"}):
        status = get_lite_status()
        assert status["lite_mode"] is False


def test_get_lite_status_duckdb():
    pytest.importorskip("duckdb")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "test_status.duckdb")
    init_lite_database(db_path)

    with patch.dict("os.environ", {"DB_BACKEND": "duckdb"}):
        with patch("data_agent.lite_mode.os.path.dirname", return_value=d):
            # Need to patch the db_path lookup
            status = get_lite_status()
            assert status["lite_mode"] is True
