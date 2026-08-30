#!/usr/bin/env python3
"""Certify MVT ConsumerBinding lookup against disposable PostgreSQL 16."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent.consumer_binding import ConsumerBinding, consumer_binding_fingerprint
from data_agent.migration_runner import catalog_fingerprint, discover_migrations
from data_agent.platform_gateway import PlatformGateway

MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "100_data_product_registry.sql",
    "101_data_product_promotion.sql",
    "105_asset_distribution_grant.sql",
    "106_version_locked_distribution_grant.sql",
    "107_distribution_grant_package_quota.sql",
    "108_data_product_promotion_impact.sql",
    "149_consumer_binding.sql",
)


def _sql_file(filename: str) -> str:
    path = Path(__file__).resolve().parents[1] / "data_agent/migrations" / filename
    return path.read_text(encoding="utf-8").replace("%", "%%")


def _bootstrap(engine, login_role: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_assets ("
            "id SERIAL PRIMARY KEY, asset_name TEXT NOT NULL, "
            "operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_requests ("
            "id SERIAL PRIMARY KEY, asset_id INTEGER NOT NULL "
            "REFERENCES agent_data_assets(id), requester VARCHAR(100) NOT NULL, "
            "status VARCHAR(30) NOT NULL DEFAULT 'pending', approver VARCHAR(100), "
            "approved_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW())"
        )
        for filename in MIGRATIONS:
            connection.exec_driver_sql(_sql_file(filename))
        connection.exec_driver_sql(f'GRANT gda_control_gateway TO "{login_role}"')


def _seed_product(engine) -> tuple[str, str, str, str, datetime]:
    tenant = "planning"
    product_urn = "gda://planning/data_product/districts"
    now = datetime(2026, 8, 7, tzinfo=UTC)
    source_urn = "gda://planning/dataset/source"
    output_urn = "gda://planning/dataset/output"
    source_id, output_id = uuid4(), uuid4()
    current_id, target_id, artifact_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref
                ) VALUES
                    (:tenant, :source_urn, 'dataset', 'certifier', 'source', 'team:test'),
                    (:tenant, :output_urn, 'dataset', 'certifier', 'output', 'team:test')
                """
            ),
            {"tenant": tenant, "source_urn": source_urn, "output_urn": output_urn},
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    content_sha256, authority_version_ref, created_by, created_at
                ) VALUES
                    (:tenant, :source_id, :source_urn, 'v1', :source_sha,
                     '{}'::jsonb, 'workload:certifier', :now),
                    (:tenant, :output_id, :output_urn, 'v1', :output_sha,
                     '{}'::jsonb, 'workload:certifier', :now)
                """
            ),
            {
                "tenant": tenant,
                "source_id": source_id,
                "source_urn": source_urn,
                "source_sha": "1" * 64,
                "output_id": output_id,
                "output_urn": output_urn,
                "output_sha": "2" * 64,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.artifact (
                    tenant_id, artifact_id, artifact_key, artifact_role,
                    storage_uri, media_type, content_sha256, size_bytes,
                    manifest, created_by, created_at
                ) VALUES (
                    :tenant, :artifact_id, 'quality.json', 'evidence',
                    'file:///quality.json', 'application/json', :sha, 1,
                    '{}'::jsonb, 'workload:certifier', :now
                )
                """
            ),
            {"tenant": tenant, "artifact_id": artifact_id, "sha": "3" * 64, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product (
                    tenant_id, product_urn, product_slug, title, description,
                    domain, owner_ref, governance_ref, created_at, updated_at
                ) VALUES (
                    :tenant, :product_urn, 'districts', 'Districts', 'Districts',
                    'planning', 'team:test',
                    '{"classification":"internal","visibility":"private",
                      "license_id":"internal","attribution":"test"}'::jsonb,
                    :now, :now
                )
                """
            ),
            {"tenant": tenant, "product_urn": product_urn, "now": now},
        )
        for version_id, version_key, predecessor_id, manifest_sha in (
            (current_id, "v1.0.0", None, "4" * 64),
            (target_id, "v1.1.0", current_id, "5" * 64),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_version (
                        tenant_id, data_product_version_id, product_urn,
                        version_key, predecessor_version_id,
                        source_resource_version_id, output_resource_version_id,
                        standard_version_ref, mapping_contract, quality_contract,
                        quality_verdict, quality_evidence_artifact_id,
                        distribution_manifest, manifest_sha256, published_by,
                        published_at
                    ) VALUES (
                        :tenant, :version_id, :product_urn, :version_key,
                        :predecessor_id, :source_id, :output_id, 'standard:v1',
                        CAST(:mapping_contract AS jsonb),
                        CAST(:quality_contract AS jsonb), 'passed', :artifact_id,
                        CAST(:distribution_manifest AS jsonb), :manifest_sha,
                        'workload:certifier', :now
                    )
                    """
                ),
                {
                    "tenant": tenant,
                    "version_id": version_id,
                    "product_urn": product_urn,
                    "version_key": version_key,
                    "predecessor_id": predecessor_id,
                    "source_id": source_id,
                    "output_id": output_id,
                    "artifact_id": artifact_id,
                    "mapping_contract": '{"mapping":{"ok":true}}',
                    "quality_contract": '{"verdict":"passed"}',
                    "distribution_manifest": '{"formats":[]}',
                    "manifest_sha": manifest_sha,
                    "now": now,
                },
            )
        connection.execute(
            text(
                """
                UPDATE gda_control.data_product
                   SET current_version_id = :current_id, updated_at = :now
                 WHERE tenant_id = :tenant AND product_urn = :product_urn
                """
            ),
            {
                "tenant": tenant,
                "product_urn": product_urn,
                "current_id": current_id,
                "now": now,
            },
        )
    return tenant, product_urn, str(current_id), str(target_id), now


def _binding(
    *,
    tenant: str,
    product_urn: str,
    subject: str,
    now,
    min_product_version: str | None = None,
    max_product_version: str | None = None,
    expires_at=None,
    created_at=None,
) -> ConsumerBinding:
    payload = {
        "tenant_id": tenant,
        "binding_id": uuid4(),
        "product_urn": product_urn,
        "consumer_ref": subject,
        "purpose": "governed MVT read certification",
        "scope": {"operations": ["read"]},
        "min_product_version": min_product_version,
        "max_product_version": max_product_version,
        "credential_ref": f"credential:mvt-{subject.split(':', 1)[1]}",
        "quota": {"max_packages": 5},
        "expires_at": expires_at or now + timedelta(days=5000),
        "compatibility_fingerprint": (subject[-1] * 64),
        "compatibility_evidence": {"schema": "districts.v1"},
        "created_by": "human:certifier",
        "created_at": created_at or now,
    }
    payload["binding_sha256"] = consumer_binding_fingerprint(payload)
    return ConsumerBinding.model_validate(payload)


def certify(database_url: str, *, report_path: Path | None = None) -> dict[str, object]:
    source_url = make_url(database_url)
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    temp_name = f"gda_mvt_auth_cert_{uuid4().hex[:10]}"
    login_role = f"gda_mvt_auth_login_{uuid4().hex[:10]}"
    password = uuid4().hex
    with admin.connect() as connection:
        connection.execute(
            text(f'CREATE ROLE "{login_role}" LOGIN PASSWORD :password'),
            {"password": password},
        )
        connection.execute(text(f'CREATE DATABASE "{temp_name}"'))

    temp_url = source_url.set(database=temp_name)
    login_url = source_url.set(
        username=login_role,
        password=password,
        database=temp_name,
    )
    engine = create_engine(temp_url)
    login_engine = create_engine(login_url)
    try:
        _bootstrap(engine, login_role)
        tenant, product_urn, current_id, target_id, now = _seed_product(engine)
        gateway = PlatformGateway(login_engine)

        active = _binding(
            tenant=tenant,
            product_urn=product_urn,
            subject="human:analyst-01",
            now=now,
            min_product_version="v1.0.0",
            max_product_version="v2.0.0",
        )
        expired = _binding(
            tenant=tenant,
            product_urn=product_urn,
            subject="human:expired",
            now=now,
            expires_at=now - timedelta(days=1),
            created_at=now - timedelta(days=2),
        )
        future = _binding(
            tenant=tenant,
            product_urn=product_urn,
            subject="human:future",
            now=now,
            min_product_version="v2.0.0",
            max_product_version="v3.0.0",
        )
        for binding in (active, expired, future):
            gateway.register_consumer_binding(binding)

        checks = {
            "active_exact_version": gateway.get_active_consumer_binding_for_product_version(
                tenant, product_urn, UUID(current_id), active.consumer_ref
            )
            == active,
            "missing_consumer_rejected": gateway.get_active_consumer_binding_for_product_version(
                tenant, product_urn, UUID(current_id), "human:missing"
            )
            is None,
            "expired_binding_rejected": gateway.get_active_consumer_binding_for_product_version(
                tenant, product_urn, UUID(current_id), expired.consumer_ref
            )
            is None,
            "version_bounds_rejected": gateway.get_active_consumer_binding_for_product_version(
                tenant, product_urn, UUID(current_id), future.consumer_ref
            )
            is None,
            "in_range_successor_version": gateway.get_active_consumer_binding_for_product_version(
                tenant, product_urn, UUID(target_id), active.consumer_ref
            )
            == active,
        }
        report = {
            "schema": "gda.gis_mvt_consumer_authorization_certification.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "database": temp_name,
            "login_role": login_role,
            "migration_catalog": {
                "latest": discover_migrations()[-1].migration_id,
                "fingerprint": catalog_fingerprint(),
            },
            "checks": checks,
        }
        if report["status"] != "passed":
            raise RuntimeError(f"MVT consumer authorization certification failed: {report}")
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return report
    finally:
        engine.dispose()
        login_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{temp_name}" WITH (FORCE)'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{login_role}"'))
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(certify(args.database_url, report_path=args.report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
