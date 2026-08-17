import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from data_agent.platform_gateway import (
    GatewayConflictError,
    LandingRegistration,
    PlatformGateway,
)
from data_agent.public_source_landing import (
    PublicSourceLandingRequest,
    stage_public_source,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
    )
)
NOW = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)


def _stage(tmp_path: Path, *, tenant: str, dataset_id: str, payload: bytes):
    source = tmp_path / f"{dataset_id}.geojson"
    source.write_bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    return stage_public_source(
        PublicSourceLandingRequest(
            tenant_id=tenant,
            dataset_id=dataset_id,
            source_uri=f"https://example.org/open-data/{dataset_id}.geojson",
            license_id="CC0-1.0",
            owner_ref="team:data-platform",
            expected_sha256=sha256,
            media_type="application/geo+json",
            created_by="workload:public-source-ingest",
            created_at=NOW,
        ),
        source_path=source,
        landing_root=tmp_path / "landing",
    )


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_registers_landing_atomically_and_replays(tmp_path):
    engine = create_engine(DATABASE_URL)
    tenant = f"landing-{uuid4().hex[:12]}"
    try:
        with engine.begin() as connection:
            is_superuser = connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one()
            if not is_superuser:
                pytest.skip("landing gateway test requires a PostgreSQL superuser")
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS agent_app_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL
                )
                """
            )
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

        first = _stage(
            tmp_path,
            tenant=tenant,
            dataset_id="natural-earth-countries",
            payload=b'{"type":"FeatureCollection","features":[]}\n',
        )
        gateway = PlatformGateway(engine)
        created = gateway.register_landing(first.registration)
        assert created.created is True
        assert created.value == first.registration
        replay = gateway.register_landing(first.registration)
        assert replay.created is False
        assert replay.value == first.registration

        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM gda_control.resource
                       WHERE tenant_id = :tenant_id),
                      (SELECT count(*) FROM gda_control.resource_version
                       WHERE tenant_id = :tenant_id),
                      (SELECT count(*) FROM gda_control.artifact
                       WHERE tenant_id = :tenant_id)
                    """
                ),
                {"tenant_id": tenant},
            ).one()
        assert counts == (1, 1, 1)

        second = _stage(
            tmp_path,
            tenant=tenant,
            dataset_id="natural-earth-rivers",
            payload=b'{"type":"FeatureCollection","features":[{}]}\n',
        )
        conflicting = LandingRegistration(
            resource=second.registration.resource,
            resource_version=second.registration.resource_version,
            artifact=second.registration.artifact.model_copy(
                update={"artifact_id": first.registration.artifact.artifact_id}
            ),
        )
        with pytest.raises(GatewayConflictError, match="different payload"):
            gateway.register_landing(conflicting)

        with engine.connect() as connection:
            rolled_back = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM gda_control.resource
                       WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn),
                      (SELECT count(*) FROM gda_control.resource_version
                       WHERE tenant_id = :tenant_id
                         AND resource_version_id = :resource_version_id)
                    """
                ),
                {
                    "tenant_id": tenant,
                    "resource_urn": second.registration.resource.resource_urn,
                    "resource_version_id": (
                        second.registration.resource_version.resource_version_id
                    ),
                },
            ).one()
        assert rolled_back == (0, 0)
    finally:
        engine.dispose()
