"""Deployment-time membership binding for the platform gateway role."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from sqlalchemy import text

from .db_engine import get_engine


GATEWAY_ROLE = "gda_control_gateway"
POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def grant_gateway_membership(login_role: str, *, engine=None) -> dict[str, Any]:
    """Grant and verify membership without broadening the gateway privileges."""
    if not POSTGRES_IDENTIFIER_RE.fullmatch(login_role or ""):
        raise ValueError("login_role must be a PostgreSQL identifier")
    database = engine or get_engine()
    if database is None:
        raise RuntimeError("database unavailable")
    if database.dialect.name != "postgresql":
        raise RuntimeError("platform gateway membership requires PostgreSQL")

    with database.begin() as connection:
        roles = connection.execute(
            text(
                "SELECT rolname FROM pg_roles "
                "WHERE rolname IN (:gateway_role, :login_role)"
            ),
            {"gateway_role": GATEWAY_ROLE, "login_role": login_role},
        ).scalars().all()
        missing = sorted({GATEWAY_ROLE, login_role} - set(roles))
        if missing:
            raise RuntimeError("database roles are missing: " + ", ".join(missing))

        quoted_login = connection.dialect.identifier_preparer.quote(login_role)
        connection.execute(text(f"GRANT {GATEWAY_ROLE} TO {quoted_login}"))
        member = bool(connection.execute(
            text("SELECT pg_has_role(:login_role, :gateway_role, 'MEMBER')"),
            {"login_role": login_role, "gateway_role": GATEWAY_ROLE},
        ).scalar_one())
        if not member:
            raise RuntimeError("platform gateway membership verification failed")

    return {
        "status": "granted",
        "login_role": login_role,
        "gateway_role": GATEWAY_ROLE,
        "member": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-role", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(grant_gateway_membership(args.login_role), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
