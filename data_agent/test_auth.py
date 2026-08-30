"""Auth tests."""
from __future__ import annotations

from unittest.mock import MagicMock

from data_agent.auth import _VALID_ROLES, register_user, upsert_oauth_user


def test_valid_roles_includes_standard_reviewer():
    """Wave 4: standard_reviewer is a recognized role."""
    assert "standard_reviewer" in _VALID_ROLES
    assert "standard_editor" in _VALID_ROLES


def test_register_user_rejects_invalid_role():
    """register_user should return error for unknown role."""
    out = register_user("testuser_w4", "Password123", role="bogus_role")
    assert out["status"] == "error"
    assert "invalid role" in out["message"]


def test_upsert_oauth_user_creates_missing_user(monkeypatch):
    result = MagicMock()
    result.fetchone.return_value = None
    connection = MagicMock()
    connection.execute.side_effect = [result, MagicMock()]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr("data_agent.auth.get_engine", lambda: engine)

    user = upsert_oauth_user("user@example.com", "Test User", "github")

    assert user == {
        "username": "user@example.com",
        "display_name": "Test User",
        "role": "analyst",
    }
    assert connection.execute.call_count == 2
    connection.commit.assert_called_once_with()
