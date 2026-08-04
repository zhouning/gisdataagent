from types import SimpleNamespace

import pytest

from data_agent.platform_gateway_role import grant_gateway_membership


def test_rejects_invalid_login_role_before_database_access():
    with pytest.raises(ValueError, match="PostgreSQL identifier"):
        grant_gateway_membership("agent_user; DROP ROLE postgres")


def test_rejects_non_postgresql_engine():
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        grant_gateway_membership("agent_user", engine=engine)
