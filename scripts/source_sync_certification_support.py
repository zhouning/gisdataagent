"""Shared lightweight helpers for isolated SourceSync certifications."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def connection_url(endpoint_url: str, auth_config: dict) -> str:
    """Apply runtime basic credentials without ad-hoc URL interpolation."""

    if (auth_config or {}).get("type") != "basic":
        return endpoint_url
    url = make_url(endpoint_url)
    username = auth_config.get("username")
    password = auth_config.get("password")
    return url.set(
        username=str(username) if username is not None else url.username,
        password=str(password) if password is not None else url.password,
    ).render_as_string(hide_password=False)


def main_sync_counts(admin_url: str) -> tuple[int, int, int]:
    """Read persistent SourceSync row counts without importing a provider stack."""

    engine = create_engine(admin_url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.source_sync_definition),
                        (SELECT count(*) FROM gda_control.source_sync_checkpoint),
                        (SELECT count(*) FROM gda_control.source_sync_commit)
                    """
                )
            ).one()
            connection.rollback()
        return tuple(int(value) for value in row)
    finally:
        engine.dispose()
