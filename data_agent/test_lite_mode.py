"""Tests for Lite Mode (v22.0)."""
import os
import tempfile
import pytest
from unittest.mock import patch

from data_agent.lite_mode import is_lite_mode, init_lite_database, get_lite_status


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
    try:
        import duckdb
    except ImportError:
        pytest.skip("duckdb not installed")

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
    assert "agent_data_assets" in tables
    assert "agent_audit_log" in tables
    assert "agent_feedback" in tables

    # Verify seed data
    users = adapter.execute("SELECT username FROM agent_users")
    assert ("admin",) in users
    adapter.close()


def test_init_lite_database_idempotent():
    """Running init twice should not duplicate seed data."""
    try:
        import duckdb
    except ImportError:
        pytest.skip("duckdb not installed")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "test_idem.duckdb")
    init_lite_database(db_path)
    init_lite_database(db_path)  # second run

    from data_agent.duckdb_adapter import DuckDBAdapter
    adapter = DuckDBAdapter(db_path)
    count = adapter.execute("SELECT COUNT(*) FROM agent_users WHERE username = 'admin'")
    assert count[0][0] == 1  # not duplicated
    adapter.close()


def test_get_lite_status_postgres():
    with patch.dict("os.environ", {"DB_BACKEND": "postgres"}):
        status = get_lite_status()
        assert status["lite_mode"] is False


def test_get_lite_status_duckdb():
    try:
        import duckdb
    except ImportError:
        pytest.skip("duckdb not installed")

    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "test_status.duckdb")
    init_lite_database(db_path)

    with patch.dict("os.environ", {"DB_BACKEND": "duckdb"}):
        with patch("data_agent.lite_mode.os.path.dirname", return_value=d):
            # Need to patch the db_path lookup
            status = get_lite_status()
            assert status["lite_mode"] is True
