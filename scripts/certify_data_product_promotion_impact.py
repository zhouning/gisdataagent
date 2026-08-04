#!/usr/bin/env python3
"""Certify consumer-aware DataProduct promotion in disposable PostgreSQL 16."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.data_product_registry import (
    DataProductPromotionImpactError,
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    REPO_ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "100_data_product_registry.sql",
        "101_data_product_promotion.sql",
        "105_asset_distribution_grant.sql",
        "106_version_locked_distribution_grant.sql",
        "107_distribution_grant_package_quota.sql",
        "108_data_product_promotion_impact.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "113_data_architecture_version_authority.sql",
        "114_data_architecture_provider_observation.sql",
        "115_architecture_successor_adoption_lock.sql",
        "116_architecture_successor_data_product_release.sql",
    )
)
TENANT = "promotion-cert"
OTHER_TENANT = "promotion-other"
PRODUCT_URN = f"gda://{TENANT}/data_product/districts"
PRODUCT_SLUG = "districts"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _wait_for_postgres(container: str) -> None:
    for _ in range(120):
        ready = _docker(
            "exec",
            container,
            "pg_isready",
            "-U",
            "postgres",
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _start_postgres(image: str) -> tuple[str, int]:
    container = f"gda-promotion-impact-{secrets.token_hex(5)}"
    _docker(
        "run",
        "--rm",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        image,
    )
    _wait_for_postgres(container)
    binding = _docker("port", container, "5432/tcp").stdout.strip().splitlines()[0]
    return container, int(binding.rsplit(":", 1)[1])


def _wait_for_host_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _bootstrap(admin_engine) -> None:
    with admin_engine.begin() as connection:
        connection.exec_driver_sql("CREATE ROLE agent_user LOGIN NOINHERIT")
        connection.exec_driver_sql(
            """
            CREATE TABLE agent_data_assets (
                id SERIAL PRIMARY KEY,
                asset_name TEXT NOT NULL,
                operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE agent_data_requests (
                id SERIAL PRIMARY KEY,
                asset_id INTEGER NOT NULL REFERENCES agent_data_assets(id),
                requester VARCHAR(100) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'pending',
                approver VARCHAR(100),
                approved_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql("GRANT gda_control_gateway TO agent_user")


def _seed_dependencies(admin_engine) -> tuple[UUID, UUID, UUID]:
    source_version_id = uuid4()
    output_version_id = uuid4()
    quality_artifact_id = uuid4()
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref
                ) VALUES
                    (:tenant_id, :source_urn, 'dataset', 'certification',
                     'source/districts', 'team:data-platform'),
                    (:tenant_id, :output_urn, 'dataset', 'certification',
                     'output/districts', 'team:data-platform')
                """
            ),
            {
                "tenant_id": TENANT,
                "source_urn": f"gda://{TENANT}/dataset/source-districts",
                "output_urn": f"gda://{TENANT}/dataset/output-districts",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    content_sha256, authority_version_ref, created_by
                ) VALUES
                    (:tenant_id, :source_id, :source_urn, 'snapshot-1',
                     repeat('a', 64), '{"snapshot": 1}', 'workload:certifier'),
                    (:tenant_id, :output_id, :output_urn, 'snapshot-1',
                     repeat('b', 64), '{"snapshot": 1}', 'workload:certifier')
                """
            ),
            {
                "tenant_id": TENANT,
                "source_id": source_version_id,
                "output_id": output_version_id,
                "source_urn": f"gda://{TENANT}/dataset/source-districts",
                "output_urn": f"gda://{TENANT}/dataset/output-districts",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.artifact (
                    tenant_id, artifact_id, artifact_key, artifact_role,
                    storage_uri, media_type, content_sha256, size_bytes,
                    created_by
                ) VALUES (
                    :tenant_id, :artifact_id, 'quality/districts.json', 'evidence',
                    'file:///tmp/quality-districts.json', 'application/json',
                    repeat('c', 64), 2, 'workload:certifier'
                )
                """
            ),
            {"tenant_id": TENANT, "artifact_id": quality_artifact_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO agent_data_assets (
                    id, asset_name, operational_metadata
                ) VALUES (
                    42, 'districts.gpkg',
                    jsonb_build_object(
                        'publication',
                        jsonb_build_object('data_product_urn', :product_urn)
                    )
                )
                """
            ),
            {"product_urn": PRODUCT_URN},
        )
    return source_version_id, output_version_id, quality_artifact_id


def _product(created_at: datetime) -> DataProductSpec:
    return DataProductSpec(
        tenant_id=TENANT,
        product_urn=PRODUCT_URN,
        product_slug=PRODUCT_SLUG,
        title="District boundaries",
        description="Certified district boundaries",
        domain="planning",
        owner_ref="team:data-platform",
        governance_ref={
            "classification": "internal",
            "visibility": "private",
            "license_id": "internal",
            "attribution": "promotion certification",
        },
        created_at=created_at,
    )


def _version(
    *,
    version_key: str,
    version_id: UUID,
    predecessor_id: UUID | None,
    source_version_id: UUID,
    output_version_id: UUID,
    quality_artifact_id: UUID,
    published_at: datetime,
) -> DataProductVersionSpec:
    payload = {
        "tenant_id": TENANT,
        "data_product_version_id": version_id,
        "product_urn": PRODUCT_URN,
        "version_key": version_key,
        "predecessor_version_id": predecessor_id,
        "source_resource_version_id": source_version_id,
        "output_resource_version_id": output_version_id,
        "standard_version_ref": "standard:administrative-boundary:v1",
        "mapping_contract": {"mapping": {"district_id": "district_id"}},
        "quality_contract": {"verdict": "passed", "checks": ["geometry"]},
        "quality_evidence_artifact_id": quality_artifact_id,
        "distribution_manifest": {"formats": [{"kind": "GeoPackage"}]},
        "published_by": "workload:certifier",
        "published_at": published_at,
    }
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    return DataProductVersionSpec.model_validate(payload)


def _insert_grant(
    admin_engine,
    *,
    requester: str,
    version_id: UUID,
    version_key: str,
    package_quota: int,
) -> int:
    with admin_engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO agent_data_requests (
                        asset_id, requester, status, approver, approved_at,
                        requested_operations, requested_duration_days,
                        granted_operations, expires_at, product_tenant_id,
                        product_urn, data_product_version_id,
                        data_product_version_key, requested_package_quota,
                        granted_package_quota
                    ) VALUES (
                        42, :requester, 'approved', 'platform-admin', NOW(),
                        '["download"]', 30, '["download"]',
                        NOW() + INTERVAL '30 days', :tenant_id,
                        :product_urn, :version_id, :version_key,
                        :package_quota, :package_quota
                    ) RETURNING id
                    """
                ),
                {
                    "requester": requester,
                    "tenant_id": TENANT,
                    "product_urn": PRODUCT_URN,
                    "version_id": version_id,
                    "version_key": version_key,
                    "package_quota": package_quota,
                },
            ).scalar_one()
        )


def _cross_tenant_hidden(app_engine, version_id: UUID) -> bool:
    with app_engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": OTHER_TENANT},
        )
        function_rows = connection.execute(
            text(
                """
                SELECT count(*)
                  FROM gda_control.active_distribution_grant_impact(
                      :tenant_id, :product_urn, CAST(:version_id AS uuid)
                  )
                """
            ),
            {
                "tenant_id": TENANT,
                "product_urn": PRODUCT_URN,
                "version_id": version_id,
            },
        ).scalar_one()
        table_rows = connection.execute(
            text(
                """
                SELECT count(*)
                  FROM gda_control.data_product_promotion_impact
                 WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": TENANT},
        ).scalar_one()
    return function_rows == 0 and table_rows == 0


def _evidence_checks(admin_engine) -> dict[str, bool | int]:
    with admin_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT event.event_type, event.promotion_impact_id IS NOT NULL,
                       impact.acknowledgement_mode, impact.active_grant_count
                  FROM gda_control.data_product_event event
                  LEFT JOIN gda_control.data_product_promotion_impact impact
                    ON impact.tenant_id = event.tenant_id
                   AND impact.impact_id = event.promotion_impact_id
                 WHERE event.tenant_id = :tenant_id
                   AND event.product_urn = :product_urn
                   AND event.event_type IN ('staged', 'promoted')
                 ORDER BY event.occurred_at, event.event_id
                """
            ),
            {"tenant_id": TENANT, "product_urn": PRODUCT_URN},
        ).all()
        postgres_version = connection.exec_driver_sql("SHOW server_version").scalar_one()
    immutable = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE gda_control.data_product_promotion_impact
                       SET assessed_by = 'tampered'
                     WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": TENANT},
            )
    except DBAPIError:
        immutable = True
    return {
        "postgres_16": str(postgres_version).startswith("16."),
        "staged_event_has_pending_evidence": any(
            row[0] == "staged" and row[1] and row[2] == "pending" and row[3] == 1
            for row in rows
        ),
        "promotion_event_has_explicit_evidence": any(
            row[0] == "promoted"
            and row[1]
            and row[2] == "explicit"
            and row[3] == 2
            for row in rows
        ),
        "impact_evidence_immutable": immutable,
        "audited_event_count": len(rows),
    }


def certify(image: str) -> dict[str, object]:
    container = ""
    admin_engine = None
    app_engine = None
    try:
        container, port = _start_postgres(image)
        admin_engine = create_engine(
            f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        )
        _wait_for_host_connection(admin_engine)
        _bootstrap(admin_engine)
        source_id, output_id, quality_id = _seed_dependencies(admin_engine)
        app_engine = create_engine(
            f"postgresql+psycopg2://agent_user@127.0.0.1:{port}/postgres"
        )
        registry = DataProductRegistry(app_engine)
        published_at = datetime.now(UTC) - timedelta(minutes=5)
        product = _product(published_at)
        v1_id = uuid4()
        v2_id = uuid4()
        v1 = _version(
            version_key="v1.0.0",
            version_id=v1_id,
            predecessor_id=None,
            source_version_id=source_id,
            output_version_id=output_id,
            quality_artifact_id=quality_id,
            published_at=published_at,
        )
        first = registry.publish(
            product,
            v1,
            idempotency_key="publish-v1",
            reason="certify initial product version",
        )
        _insert_grant(
            admin_engine,
            requester="planner-a",
            version_id=v1_id,
            version_key="v1.0.0",
            package_quota=5,
        )
        v2 = _version(
            version_key="v2.0.0",
            version_id=v2_id,
            predecessor_id=v1_id,
            source_version_id=source_id,
            output_version_id=output_id,
            quality_artifact_id=quality_id,
            published_at=published_at + timedelta(minutes=1),
        )
        staged = registry.publish(
            product,
            v2,
            idempotency_key="publish-v2",
            reason="certify consumer-aware staged publication",
        )
        replay = registry.publish(
            product,
            v2,
            idempotency_key="publish-v2",
            reason="retry consumer-aware staged publication",
        )
        old_impact = registry.preview_promotion_impact(TENANT, PRODUCT_SLUG, "v2.0.0")
        _insert_grant(
            admin_engine,
            requester="planner-b",
            version_id=v1_id,
            version_key="v1.0.0",
            package_quota=3,
        )
        latest_impact = registry.preview_promotion_impact(
            TENANT, PRODUCT_SLUG, "v2.0.0"
        )
        stale_rejected = False
        try:
            registry.promote(
                TENANT,
                PRODUCT_SLUG,
                "v2.0.0",
                actor_subject="human:platform-admin",
                reason="attempt with stale impact",
                idempotency_key="promote-v2-stale",
                impact_acknowledgement=old_impact["impact_fingerprint"],
            )
        except DataProductPromotionImpactError as exc:
            stale_rejected = (
                exc.impact["impact_fingerprint"]
                == latest_impact["impact_fingerprint"]
            )
        promoted = registry.promote(
            TENANT,
            PRODUCT_SLUG,
            "v2.0.0",
            actor_subject="human:platform-admin",
            reason="acknowledged latest consumer impact",
            idempotency_key="promote-v2-latest",
            impact_acknowledgement=latest_impact["impact_fingerprint"],
        )
        final_product = registry.get_product(TENANT, PRODUCT_SLUG)
        evidence = _evidence_checks(admin_engine)
        checks: dict[str, bool | int] = {
            "initial_version_activated": first["pointer_changed"] is True,
            "v2_staged_while_v1_remains_active": (
                staged["promotion_deferred"] is True
                and staged["pointer_changed"] is False
                and staged["product"]["current_version_key"] == "v1.0.0"
            ),
            "staged_publish_replay_is_idempotent": (
                replay["idempotent_replay"] is True
                and replay["promotion_impact"]["impact_fingerprint"]
                == staged["promotion_impact"]["impact_fingerprint"]
            ),
            "preview_lists_first_consumer_and_quota": (
                old_impact["impacted_consumers"] == ["planner-a"]
                and old_impact["remaining_package_quota"] == 5
            ),
            "new_grant_invalidates_old_acknowledgement": (
                latest_impact["active_grant_count"] == 2
                and latest_impact["remaining_package_quota"] == 8
                and latest_impact["impact_fingerprint"]
                != old_impact["impact_fingerprint"]
                and stale_rejected
            ),
            "latest_acknowledgement_promotes_v2": (
                promoted["pointer_changed"] is True
                and final_product["current_version_key"] == "v2.0.0"
            ),
            "cross_tenant_impact_is_hidden": _cross_tenant_hidden(app_engine, v1_id),
            **evidence,
        }
        failed = [name for name, passed in checks.items() if not bool(passed)]
        if failed:
            raise RuntimeError(f"promotion impact certification failed: {failed}")
        return {
            "schema": "gda.data_product_promotion_impact_certification.v1",
            "status": "passed",
            "checks": checks,
        }
    finally:
        if app_engine is not None:
            app_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        if container:
            _docker("stop", "--time", "3", container, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    args = parser.parse_args()
    print(json.dumps(certify(args.postgres_image), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
