#!/usr/bin/env python3
"""Certify real JSON schema drift from MinIO and STAC into the control ledger."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from data_agent.connectors.database import _connection_url
from data_agent.source_connector_governance import (
    CertificationStatus,
    CredentialAuthType,
    CredentialReference,
    MappingCredentialResolver,
    SchemaDriftEvent,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
)
from data_agent.source_schema_drift_ledger import SchemaDriftStatus, SourceSchemaDriftLedger
from data_agent.source_schema_drift_observer import observe_certification_schema_drift
from scripts.certify_minio_credential_rotation import _auth as _minio_auth
from scripts.certify_minio_credential_rotation import _MinioCertificationSandbox
from scripts.certify_minio_credential_rotation import _settings as _minio_settings
from scripts.certify_source_schema_drift_ledger import _PostgresDatabaseSandbox
from scripts.certify_source_schema_drift_ledger import _settings as _postgres_settings
from scripts.certify_stac_credential_rotation import (
    OSM_COLLECTION,
    _AuthenticatedStacTransport,
    _CredentialState,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-connector-certification/object-stac-drift-report.json"
PROBE_FIELD = "properties.gda:schema_drift_probe_v1"
TENANT_ID = "source-provider-drift-certification"


def _credential(kind: SourceConnectorKind) -> CredentialReference:
    if kind is SourceConnectorKind.OBJECT_STORAGE:
        return CredentialReference(
            credential_id="credential:minio-schema-drift-certification",
            version=1,
            auth_type=CredentialAuthType.AWS_SIGV4,
            provider="ephemeral-minio-user",
        )
    return CredentialReference(
        credential_id="credential:stac-schema-drift-certification",
        version=1,
        auth_type=CredentialAuthType.BEARER,
        provider="ephemeral-authenticated-stac-transport",
    )


def _object_definition(
    endpoint_url: str,
    sandbox: _MinioCertificationSandbox,
    credential: CredentialReference,
) -> SourceDefinition:
    return SourceDefinition(
        source_id="chongqing-osm-object-schema-certification",
        version="1.0.0",
        source_kind=SourceConnectorKind.OBJECT_STORAGE,
        endpoint_url=endpoint_url,
        owner_ref="team:data-platform",
        credential_reference=credential,
        connector_version="1.0.0",
        query_config={
            "bucket": sandbox.bucket,
            "key": sandbox.key,
            "format": "geojson",
            "discovery_limit": 50,
        },
    )


def _stac_definition(endpoint_url: str, credential: CredentialReference) -> SourceDefinition:
    return SourceDefinition(
        source_id="chongqing-osm-stac-schema-certification",
        version="1.0.0",
        source_kind=SourceConnectorKind.STAC,
        endpoint_url=endpoint_url,
        owner_ref="team:data-platform",
        credential_reference=credential,
        connector_version="1.0.0",
        query_config={"collection_id": OSM_COLLECTION},
    )


def _mutations(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(item.get("properties"), dict):
        raise RuntimeError("governed STAC item does not contain a properties object")
    if "gda:schema_drift_probe_v1" in item["properties"]:
        raise RuntimeError("governed STAC item already contains the certification probe field")
    additive = copy.deepcopy(item)
    additive["properties"]["gda:schema_drift_probe_v1"] = "accepted"
    breaking = copy.deepcopy(additive)
    breaking["properties"]["gda:schema_drift_probe_v1"] = 1
    return additive, breaking


async def _certify_snapshots(
    *,
    item: dict[str, Any],
    minio_url: str,
    minio: _MinioCertificationSandbox,
    stac: _AuthenticatedStacTransport,
    stac_token: str,
) -> dict[str, tuple[Any, Any, Any]]:
    object_credential = _credential(SourceConnectorKind.OBJECT_STORAGE)
    stac_credential = _credential(SourceConnectorKind.STAC)
    object_definition = _object_definition(minio_url, minio, object_credential)
    stac_definition = _stac_definition(stac.endpoint_url, stac_credential)
    object_resolver = MappingCredentialResolver(
        {
            (object_credential.credential_id, object_credential.version): _minio_auth(
                minio.user,
                minio.secret_v1,
                minio.region,
            )
        }
    )
    stac_resolver = MappingCredentialResolver(
        {
            (stac_credential.credential_id, stac_credential.version): {
                "type": "bearer",
                "token": stac_token,
            }
        }
    )
    additive_item, breaking_item = _mutations(item)
    certified_at = datetime.now(UTC)

    async def certify_pair() -> tuple[Any, Any]:
        return (
            await certify_source_connector(
                object_definition,
                object_resolver,
                certified_at=certified_at,
            ),
            await certify_source_connector(
                stac_definition,
                stac_resolver,
                certified_at=certified_at,
            ),
        )

    minio.replace_item(item)
    stac.replace_item(item)
    initial_object, initial_stac = await certify_pair()
    minio.replace_item(additive_item)
    stac.replace_item(additive_item)
    additive_object, additive_stac = await certify_pair()
    minio.replace_item(breaking_item)
    stac.replace_item(breaking_item)
    breaking_object, breaking_stac = await certify_pair()
    return {
        "object_storage": (initial_object, additive_object, breaking_object),
        "stac": (initial_stac, additive_stac, breaking_stac),
    }


def _matching_change(event: SchemaDriftEvent, kind: str) -> bool:
    return any(
        change.field_name == PROBE_FIELD and change.change_kind == kind
        for change in event.field_changes
    )


def _record_and_verify(
    reports: dict[str, tuple[Any, Any, Any]],
    ledger: SourceSchemaDriftLedger,
) -> tuple[dict[str, Any], dict[str, bool]]:
    evidence: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for provider, (initial, additive, breaking) in reports.items():
        certifications_passed = all(
            report.status is CertificationStatus.PASSED
            for report in (initial, additive, breaking)
        )
        additive_observation = observe_certification_schema_drift(
            tenant_id=TENANT_ID,
            previous=initial,
            current=additive,
            ledger=ledger,
            detected_by="workload:source-connector-certification",
        )
        additive_replay = observe_certification_schema_drift(
            tenant_id=TENANT_ID,
            previous=initial,
            current=additive,
            ledger=ledger,
            detected_by="workload:source-connector-certification",
        )
        breaking_observation = observe_certification_schema_drift(
            tenant_id=TENANT_ID,
            previous=additive,
            current=breaking,
            ledger=ledger,
            detected_by="workload:source-connector-certification",
        )
        if (
            additive_observation.event is None
            or additive_observation.write_result is None
            or additive_replay.write_result is None
            or breaking_observation.event is None
            or breaking_observation.write_result is None
        ):
            raise RuntimeError(f"{provider} certification did not produce drift evidence")

        additive_event = additive_observation.event
        breaking_event = breaking_observation.event
        additive_record = additive_observation.write_result
        breaking_record = breaking_observation.write_result
        reconciled = ledger.transition(
            tenant_id=TENANT_ID,
            drift_event_id=additive_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.RECONCILED,
            actor_subject="workload:schema-reconciler",
            reason="non-breaking provider schema drift reconciled",
            details={"schema": "gda.schema_drift_reconciliation.v1", "provider": provider},
        )
        breaking_lifecycle = ledger.lifecycle(TENANT_ID, breaking_event.event_id)

        checks[f"{provider}_certifications_passed"] = certifications_passed
        checks[f"{provider}_additive_detected"] = (
            not additive_event.breaking
            and _matching_change(additive_event, "added")
            and additive_record.created
            and additive_record.drift.status is SchemaDriftStatus.OBSERVED
        )
        checks[f"{provider}_duplicate_idempotent"] = not additive_replay.write_result.created
        checks[f"{provider}_additive_reconciled"] = (
            reconciled.status is SchemaDriftStatus.RECONCILED
            and reconciled.state_version == 1
        )
        checks[f"{provider}_breaking_approval_required"] = (
            breaking_event.breaking
            and _matching_change(breaking_event, "type_changed")
            and breaking_record.created
            and breaking_record.drift.status is SchemaDriftStatus.APPROVAL_REQUIRED
            and len(breaking_lifecycle) == 1
            and breaking_lifecycle[0].to_status is SchemaDriftStatus.APPROVAL_REQUIRED
        )
        evidence[provider] = {
            "definition_fingerprint": initial.source_definition_fingerprint,
            "discovery_fingerprints": [
                report.discovery.fingerprint if report.discovery else None
                for report in (initial, additive, breaking)
            ],
            "profile_fingerprints": [
                report.profile.fingerprint if report.profile else None
                for report in (initial, additive, breaking)
            ],
            "additive_event": additive_event.model_dump(mode="json"),
            "additive_replay_created": additive_replay.write_result.created,
            "additive_final_status": reconciled.status.value,
            "breaking_event": breaking_event.model_dump(mode="json"),
            "breaking_status": breaking_record.drift.status.value,
            "certifications": [
                report.model_dump(mode="json") for report in (initial, additive, breaking)
            ],
        }
    return evidence, checks


def _run(
    *,
    real_item: dict[str, Any],
    minio_url: str,
    minio: _MinioCertificationSandbox,
    stac: _AuthenticatedStacTransport,
    postgres: _PostgresDatabaseSandbox,
    stac_token: str,
) -> dict[str, Any]:
    reports = asyncio.run(
        _certify_snapshots(
            item=real_item,
            minio_url=minio_url,
            minio=minio,
            stac=stac,
            stac_token=stac_token,
        )
    )
    if postgres.engine is None:
        raise RuntimeError("schema drift certification database engine was not created")
    evidence, checks = _record_and_verify(reports, SourceSchemaDriftLedger(postgres.engine))
    event_shapes = {
        provider: {
            "additive": [
                (change["field_name"], change["change_kind"], change["breaking"])
                for change in provider_evidence["additive_event"]["field_changes"]
            ],
            "breaking": [
                (change["field_name"], change["change_kind"], change["breaking"])
                for change in provider_evidence["breaking_event"]["field_changes"]
            ],
        }
        for provider, provider_evidence in evidence.items()
    }
    checks["providers_agree_on_semantic_drift"] = (
        event_shapes["object_storage"] == event_shapes["stac"]
    )
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    checks["runtime_secrets_redacted"] = (
        minio.secret_v1 not in payload and stac_token not in payload
    )
    generated_at = datetime.now(UTC)
    return {
        "schema": "gda.object_stac_schema_drift.acceptance.v1",
        "generated_at": generated_at.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "real_input": {
            "item_id": real_item.get("id"),
            "collection": real_item.get("collection"),
            "source": "governed Chongqing OSM roads STAC item v1.2.0",
        },
        "mutations": {
            "additive": {"field": PROBE_FIELD, "type": "string"},
            "breaking": {"field": PROBE_FIELD, "from_type": "string", "to_type": "integer"},
            "persistent": False,
        },
        "checks": checks,
        "providers": evidence,
        "ledger": {
            "tenant_id": TENANT_ID,
            "database": postgres.database,
            "persistent": False,
        },
        "not_claimed": [
            "production stac-fastapi or pgSTAC provider certification",
            "non-JSON object schema drift certification",
            "unified ApprovalCase authority",
            "automatic provider schema migration",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--osm-stac-item-url",
        default="http://127.0.0.1:8000/api/data-products/chongqing-osm-roads/stac",
    )
    parser.add_argument("--minio-url", default="http://127.0.0.1:9000")
    parser.add_argument(
        "--postgres-url",
        default="postgresql://127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    with urlopen(args.osm_stac_item_url, timeout=10) as response:
        real_item = json.load(response)
    if real_item.get("id") != "chongqing-osm-roads-v1.2.0":
        raise RuntimeError("governed OSM STAC v1.2.0 item is not active")

    minio = _MinioCertificationSandbox(args.minio_url, _minio_settings())
    postgres_settings = _postgres_settings()
    admin_url = args.postgres_url
    admin_auth = {
        "type": "basic",
        "username": postgres_settings.get("POSTGRES_USER", "postgres"),
        "password": postgres_settings.get(
            "POSTGRES_ADMIN_PASSWORD",
            postgres_settings.get("POSTGRES_PASSWORD", "postgres"),
        ),
    }
    postgres = _PostgresDatabaseSandbox(_connection_url(admin_url, admin_auth))
    stac_token = secrets.token_urlsafe(32)
    stac = _AuthenticatedStacTransport(real_item, _CredentialState(stac_token))
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    stac_started = False
    try:
        minio.setup()
        postgres.setup()
        stac.start()
        stac_started = True
        report = _run(
            real_item=real_item,
            minio_url=args.minio_url,
            minio=minio,
            stac=stac,
            postgres=postgres,
            stac_token=stac_token,
        )
    finally:
        cleanup.update({f"minio_{key}": value for key, value in minio.cleanup().items()})
        cleanup.update({f"postgres_{key}": value for key, value in postgres.cleanup().items()})
        if stac_started:
            cleanup.update({f"stac_{key}": value for key, value in stac.stop().items()})
    if report is None:
        raise RuntimeError("object/STAC schema drift certification did not produce a report")
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
