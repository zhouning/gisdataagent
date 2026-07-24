"""Auth tests."""
from __future__ import annotations

from data_agent.auth import _VALID_ROLES, register_user


def test_valid_roles_includes_standard_reviewer():
    """Wave 4: standard_reviewer is a recognized role."""
    assert "standard_reviewer" in _VALID_ROLES
    assert "standard_editor" in _VALID_ROLES
    assert "platform_operator" in _VALID_ROLES


def test_register_user_rejects_invalid_role():
    """register_user should return error for unknown role."""
    out = register_user("testuser_w4", "Password123", role="bogus_role")
    assert out["status"] == "error"
    assert "invalid role" in out["message"]
