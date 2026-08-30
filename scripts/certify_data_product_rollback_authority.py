#!/usr/bin/env python3
"""Certify incident- and ApprovalCase-bound DataProduct rollback authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.data_product_registry import (
    DATA_PRODUCT_ROLLBACK_APPROVAL_ACTION,
    DATA_PRODUCT_ROLLBACK_SCHEMA,
    DataProductRegistry,
    data_product_rollback_fingerprint,
)
from data_agent.platform_contracts import ApprovalCase, ApprovalCaseStatus
from data_agent.platform_gateway import PlatformGateway

ROOT = Path(__file__).resolve().parents[1]
TENANT = "rollback-cert"
PRODUCT_URN = f"gda://{TENANT}/data_product/land-parcels"
INCIDENT_ID = UUID("8c62df58-3745-5af4-a847-8f293db08077")
MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "096_platform_success_verdict.sql",
    "098_platform_data_incident.sql",
    "100_data_product_registry.sql",
    "101_data_product_promotion.sql",
    "102_source_schema_drift_ledger.sql",
    "103_unified_approval_case_authority.sql",
    "123_resource_bound_data_incident.sql",
    "151_data_product_rollback_authority.sql",
)


def _sql(filename: str) -> str:
    return (ROOT / "data_agent/migrations" / filename).read_text(
        encoding="utf-8"
    ).replace("%", "%%")


def _bootstrap(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') "
            "THEN CREATE ROLE agent_user NOLOGIN; END IF; "
            "END $$"
        )
        for filename in MIGRATIONS:
            connection.exec_driver_sql(_sql(filename))
        current_user = str(connection.execute(text("SELECT current_user")).scalar_one())
        connection.exec_driver_sql(
            f'GRANT gda_control_gateway TO "{current_user.replace(chr(34), chr(34) * 2)}"'
        )


def _seed(engine: Engine) -> tuple[UUID, UUID, UUID]:
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    source_urn = f"gda://{TENANT}/dataset/source"
    output_urn = f"gda://{TENANT}/dataset/output"
    source_id, output_id, artifact_id = uuid4(), uuid4(), uuid4()
    version_ids = (uuid4(), uuid4(), uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref
                ) VALUES
                    (:tenant_id, :source_urn, 'dataset', 'certifier', 'source', 'team:test'),
                    (:tenant_id, :output_urn, 'dataset', 'certifier', 'output', 'team:test'),
                    (:tenant_id, :product_urn, 'data_product', 'gda_control',
                     :product_urn, 'team:test')
                """
            ),
            {
                "tenant_id": TENANT,
                "source_urn": source_urn,
                "output_urn": output_urn,
                "product_urn": PRODUCT_URN,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    content_sha256, authority_version_ref, created_by, created_at
                ) VALUES
                    (:tenant_id, :source_id, :source_urn, 'v1', :source_sha,
                     '{}'::jsonb, 'workload:certifier', :created_at),
                    (:tenant_id, :output_id, :output_urn, 'v1', :output_sha,
                     '{}'::jsonb, 'workload:certifier', :created_at)
                """
            ),
            {
                "tenant_id": TENANT,
                "source_id": source_id,
                "source_urn": source_urn,
                "source_sha": "1" * 64,
                "output_id": output_id,
                "output_urn": output_urn,
                "output_sha": "2" * 64,
                "created_at": now,
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
                    :tenant_id, :artifact_id, 'quality.json', 'evidence',
                    'file:///quality.json', 'application/json', :sha, 1,
                    '{}'::jsonb, 'workload:certifier', :created_at
                )
                """
            ),
            {
                "tenant_id": TENANT,
                "artifact_id": artifact_id,
                "sha": "3" * 64,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product (
                    tenant_id, product_urn, product_slug, title, description,
                    domain, owner_ref, governance_ref, created_at, updated_at
                ) VALUES (
                    :tenant_id, :product_urn, 'land-parcels', 'Land parcels',
                    'Rollback certification product', 'planning', 'team:test',
                    '{"classification":"internal","visibility":"private",
                      "license_id":"internal","attribution":"test"}'::jsonb,
                    :created_at, :created_at
                )
                """
            ),
            {"tenant_id": TENANT, "product_urn": PRODUCT_URN, "created_at": now},
        )
        for index, version_id in enumerate(version_ids, start=1):
            predecessor = version_ids[index - 2] if index > 1 else None
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
                        :tenant_id, :version_id, :product_urn, :version_key,
                        :predecessor, :source_id, :output_id, 'standard:v1',
                        '{"mapping":"certified"}'::jsonb,
                        '{"verdict":"passed"}'::jsonb, 'passed', :artifact_id,
                        '{"formats":[{"kind":"GeoJSON"}]}'::jsonb, :manifest,
                        'workload:certifier', :published_at
                    )
                    """
                ),
                {
                    "tenant_id": TENANT,
                    "version_id": version_id,
                    "product_urn": PRODUCT_URN,
                    "version_key": f"v{index}.0.0",
                    "predecessor": predecessor,
                    "source_id": source_id,
                    "output_id": output_id,
                    "artifact_id": artifact_id,
                    "manifest": str(index) * 64,
                    "published_at": now + timedelta(minutes=index),
                },
            )
        connection.execute(
            text(
                """
                UPDATE gda_control.data_product
                   SET current_version_id = :current_id
                 WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                """
            ),
            {"tenant_id": TENANT, "product_urn": PRODUCT_URN, "current_id": version_ids[-1]},
        )
    return version_ids


def _case_for_rollback(
    engine: Engine,
    *,
    current_id: UUID,
    target_id: UUID,
    now: datetime,
) -> str:
    authority = ApprovalCaseAuthority(engine)
    case_ref = f"gda://{TENANT}/approval_case/rollback-v1"
    fingerprint = data_product_rollback_fingerprint(
        tenant_id=TENANT,
        product_urn=PRODUCT_URN,
        from_version_id=current_id,
        to_version_id=target_id,
    )
    case = ApprovalCase(
        tenant_id=TENANT,
        approval_case_ref=case_ref,
        target_resource_urn=PRODUCT_URN,
        target_fingerprint=fingerprint,
        action=DATA_PRODUCT_ROLLBACK_APPROVAL_ACTION,
        requester_subject="workload:rollback-controller",
        request_reason="certify human rollback authority",
        request_context={
            "schema": DATA_PRODUCT_ROLLBACK_SCHEMA,
            "product_urn": PRODUCT_URN,
            "from_version_id": str(current_id),
            "to_version_id": str(target_id),
        },
        requested_at=now,
        expires_at=now + timedelta(hours=2),
    )
    authority.create(case, owner_ref="team:test")
    return authority.decide(
        tenant_id=TENANT,
        approval_case_ref=case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject="human:rollback-owner",
        reason="rollback is approved",
    ).approval_case_ref


def certify(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url)
    _bootstrap(engine)
    first, second, third = _seed(engine)
    gateway = PlatformGateway(engine)
    registry = DataProductRegistry(engine)
    incident_id = INCIDENT_ID
    opened = gateway.open_resource_incident(
        tenant_id=TENANT,
        subject_resource_urn=PRODUCT_URN,
        incident_id=incident_id,
        dedupe_key="rollback-cert-incident",
        incident_type="slo_error_budget_burn",
        severity="critical",
        summary="serving reliability breach",
        details={"source": "certifier"},
        detected_by="workload:certifier",
    )
    incident_rollback = registry.rollback(
        TENANT,
        "land-parcels",
        "v2.0.0",
        actor_subject="workload:rollback-controller",
        reason="active incident rollback",
        idempotency_key="rollback-incident",
        incident_id=incident_id,
    )
    case_ref = _case_for_rollback(
        engine,
        current_id=second,
        target_id=first,
        now=datetime.now(UTC).replace(microsecond=0),
    )
    case_rollback = registry.rollback(
        TENANT,
        "land-parcels",
        "v1.0.0",
        actor_subject="human:rollback-owner",
        reason="approved human rollback",
        idempotency_key="rollback-approval",
        rollback_approval_case_ref=case_ref,
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": TENANT},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_event (
                        tenant_id, event_id, product_urn, event_type,
                        from_version_id, to_version_id, actor_subject,
                        reason, idempotency_key, occurred_at,
                        rollback_authority_kind, rollback_authority_ref,
                        rollback_authority_sha256
                    ) VALUES (:tenant_id, :event_id, :product_urn, 'rolled_back',
                              :from_id, :to_id, 'workload:forged', 'bypass',
                              'forged', clock_timestamp(), 'incident',
                              :incident_id, :sha)
                    """
                ),
                {
                    "tenant_id": TENANT,
                    "event_id": uuid4(),
                    "product_urn": PRODUCT_URN,
                    "from_id": third,
                    "to_id": second,
                    "incident_id": str(incident_id),
                    "sha": "f" * 64,
                },
            )
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        direct_sql_rejected = sqlstate == "55000"
    else:
        direct_sql_rejected = False
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT event_type, rollback_authority_kind, rollback_authority_ref
                  FROM gda_control.data_product_event
                 WHERE tenant_id = :tenant_id AND product_urn = :product_urn
                   AND event_type = 'rolled_back'
                 ORDER BY occurred_at
                """
            ),
            {"tenant_id": TENANT, "product_urn": PRODUCT_URN},
        ).mappings().all()
    return {
        "schema": "gda.data_product.rollback_authority.certification.v1",
        "status": "passed" if direct_sql_rejected and opened.created else "failed",
        "incident_idempotent_open": opened.created,
        "incident_rollback": incident_rollback["pointer_changed"],
        "approval_case_rollback": case_rollback["pointer_changed"],
        "direct_sql_insert_rejected": direct_sql_rejected,
        "rollback_events": [dict(row) for row in rows],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("GDA_ROLLBACK_CERTIFICATION_DATABASE_URL"),
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or GDA_ROLLBACK_CERTIFICATION_DATABASE_URL is required")
    report = certify(args.database_url)
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    print(f"report_sha256={hashlib.sha256(payload.encode()).hexdigest()}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
