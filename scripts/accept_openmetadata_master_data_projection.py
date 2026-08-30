#!/usr/bin/env python3
"""Real-provider acceptance for governed master-data projection to OpenMetadata."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from sqlalchemy import create_engine, text

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.master_data_authority import (
    MASTER_DATA_ACTIVATION_ACTION,
    MasterDataAuthority,
    MasterDataDomain,
    MasterEntityVersion,
    MasterEntityVersionDraft,
    MasterSourceRecordDraft,
)
from data_agent.metadata_fabric import (
    MetadataFabricBinding,
    metadata_fabric_binding_fingerprint,
)
from data_agent.openmetadata_master_data_worker import (
    OpenMetadataMasterDataClient,
    OpenMetadataMasterDataWorker,
    OpenMetadataMasterDataWorkerConfig,
    render_master_glossary_term,
)
from data_agent.platform_contracts import ApprovalCase, build_resource_urn
from data_agent.platform_gateway import PlatformGateway

MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "102_source_schema_drift_ledger.sql",
    "103_unified_approval_case_authority.sql",
    "112_metadata_fabric_binding_outbox.sql",
    "118_approval_case_sla_notification_outbox.sql",
    "119_approval_notification_governed_recovery.sql",
    "120_approval_case_assignment_authority.sql",
    "121_approval_principal_directory.sql",
    "124_reference_master_data_authority.sql",
    "125_master_data_resource_projection.sql",
    "126_master_metadata_projection_outbox.sql",
)
APPROVER = "human:openmetadata-acceptance-steward"
CONTROLLER = "workload:openmetadata-master-acceptance"
OWNER = "team:natural-resource-governance"


class AcceptanceError(RuntimeError):
    """A required real-provider acceptance assertion failed."""


class RecordingHTTPTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self._delegate = httpx.HTTPTransport()
        self.methods: list[str] = []
        self.patch_paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        if request.method == "PATCH":
            try:
                operations = json.loads(request.content)
            except (TypeError, ValueError) as exc:
                raise AcceptanceError("worker sent an invalid JSON Patch") from exc
            if not isinstance(operations, list):
                raise AcceptanceError("worker JSON Patch was not an operation list")
            self.patch_paths = [
                operation.get("path") for operation in operations if isinstance(operation, dict)
            ]
        return self._delegate.handle_request(request)

    def close(self) -> None:
        self._delegate.close()


class CommitThenTimeoutTransport(RecordingHTTPTransport):
    """Hide one successful provider PATCH response to force reconciliation."""

    def __init__(self) -> None:
        super().__init__()
        self.masked_status: int | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        if (
            request.method == "PATCH"
            and "/api/v1/glossaryTerms/" in request.url.path
            and 200 <= response.status_code < 300
            and self.masked_status is None
        ):
            response.read()
            self.masked_status = response.status_code
            response.close()
            raise httpx.ReadTimeout(
                "acceptance harness masked the committed response",
                request=request,
            )
        return response


class CapturingProjectionClient:
    def __init__(self, delegate: OpenMetadataMasterDataClient) -> None:
        self.delegate = delegate
        self.envelopes = []

    def deliver(self, envelope) -> None:
        self.envelopes.append(envelope)
        self.delegate.deliver(envelope)


def _require_success(response: httpx.Response, operation: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        body = response.text[:500].replace("\n", " ")
        raise AcceptanceError(f"{operation} failed with HTTP {response.status_code}: {body}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AcceptanceError(f"{operation} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AcceptanceError(f"{operation} returned an invalid document")
    return payload


def _login(client: httpx.Client) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@open-metadata.org",
            "password": base64.b64encode(b"admin").decode("ascii"),
        },
    )
    payload = _require_success(response, "OpenMetadata basic login")
    token = payload.get("accessToken")
    if not isinstance(token, str) or not token:
        raise AcceptanceError("OpenMetadata login did not return an access token")
    return token


def _put_entity(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    return _require_success(
        client.put(path, json=payload, headers=headers),
        f"OpenMetadata PUT {path}",
    )


def _create_provider_entities(
    client: httpx.Client,
    headers: dict[str, str],
    suffix: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    glossary = _put_entity(
        client,
        "/api/v1/glossaries",
        {
            "name": f"GDAAcceptance{suffix}",
            "description": "Disposable GDA master-data projection acceptance glossary.",
        },
        headers,
    )
    term = _put_entity(
        client,
        "/api/v1/glossaryTerms",
        {
            "name": f"administrative-unit-{suffix}",
            "displayName": "Pre-projection administrative unit",
            "description": "Pre-projection acceptance value.",
            "glossary": glossary["fullyQualifiedName"],
        },
        headers,
    )
    return glossary, term


def _prepare_control_database(database_url: str, repository_root: Path) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            for filename in MIGRATIONS:
                migration = repository_root / "data_agent" / "migrations" / filename
                connection.execute(text(migration.read_text(encoding="utf-8")))
    finally:
        engine.dispose()


def _write_token(path: Path, token: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, token.encode("utf-8"))
    finally:
        os.close(descriptor)


def _seed_control_ledger(
    engine: Any,
    glossary: dict[str, Any],
    term: dict[str, Any],
    suffix: str,
) -> tuple[str, int, MasterEntityVersion]:
    tenant_id = f"om-master-acceptance-{suffix}"
    source_system_ref = f"gda://{tenant_id}/source/admin-codes"
    entity_ref = f"gda://{tenant_id}/master_entity/administrative-unit-{suffix}"
    now = datetime.now(UTC).replace(microsecond=0)
    master_authority = MasterDataAuthority(engine)
    approval_authority = ApprovalCaseAuthority(engine)
    gateway = PlatformGateway(engine)

    approval_authority.upsert_principal(
        tenant_id=tenant_id,
        principal_subject=APPROVER,
        expected_directory_version=0,
        principal_type="human",
        display_name="OpenMetadata acceptance steward",
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
        actor_subject="human:platform-admin",
        reason="register disposable real-provider acceptance approver",
    )
    source_record_ref = build_resource_urn(
        tenant_id,
        "master_source_record",
        uuid5(
            NAMESPACE_URL,
            f"openmetadata-master-acceptance|{tenant_id}|source-v1",
        ).hex,
    )
    source = master_authority.observe(
        MasterSourceRecordDraft(
            tenant_id=tenant_id,
            source_record_ref=source_record_ref,
            domain=MasterDataDomain.ADMINISTRATIVE_UNIT,
            source_system_ref=source_system_ref,
            source_record_id=f"acceptance-{suffix}",
            source_revision="provider-v1",
            business_key=f"acceptance-{suffix}",
            display_name="Pre-projection administrative unit",
            attributes={"level": "county", "acceptance": "openmetadata-1.13.1"},
            observed_by=CONTROLLER,
            observed_at=now,
        )
    )
    version = master_authority.stage(
        MasterEntityVersionDraft(
            tenant_id=tenant_id,
            entity_ref=entity_ref,
            entity_version_ref=f"{entity_ref}.v1",
            version=1,
            domain=MasterDataDomain.ADMINISTRATIVE_UNIT,
            business_key=f"acceptance-{suffix}",
            canonical_name=f"Governed Administrative Unit {suffix}",
            attributes={"level": "county", "acceptance": "openmetadata-1.13.1"},
            source_record_refs=(source.source_record_ref,),
            valid_from=now.date(),
            owner_subject=OWNER,
            created_by=CONTROLLER,
            creation_reason="stage real-provider projection acceptance version",
            created_at=now,
        )
    )
    approval_case = ApprovalCase(
        tenant_id=tenant_id,
        approval_case_ref=build_resource_urn(
            tenant_id,
            "approval_case",
            f"openmetadata-master-{suffix}",
        ),
        target_resource_urn=version.entity_version_ref,
        target_fingerprint=version.entity_fingerprint,
        action=MASTER_DATA_ACTIVATION_ACTION,
        requester_subject=CONTROLLER,
        request_reason="request real-provider projection acceptance activation",
        request_context={"acceptance": "openmetadata-1.13.1"},
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )
    approval_authority.create(approval_case, owner_ref=OWNER)
    approved = approval_authority.decide(
        tenant_id=tenant_id,
        approval_case_ref=approval_case.approval_case_ref,
        expected_state_version=0,
        verdict="approved",
        actor_subject=APPROVER,
        reason="approve disposable real-provider acceptance activation",
    )
    activation = master_authority.activate(
        tenant_id=tenant_id,
        entity_version_ref=version.entity_version_ref,
        entity_fingerprint=version.entity_fingerprint,
        approval_case_ref=approved.approval_case_ref,
        expected_activation_version=0,
        actor_subject=CONTROLLER,
        reason="activate governed master version for real-provider acceptance",
    )

    binding_values = {
        "tenant_id": tenant_id,
        "binding_id": uuid4(),
        "resource_urn": entity_ref,
        "system": "openmetadata",
        "binding_kind": "governance_entity",
        "external_namespace": glossary["fullyQualifiedName"],
        "external_object_id": term["id"],
        "external_object_type": "glossaryTerm",
        "external_version_ref": "1.13.1",
        "created_by": CONTROLLER,
        "created_at": now,
    }
    binding_values["binding_sha256"] = metadata_fabric_binding_fingerprint(
        **{
            key: binding_values[key]
            for key in (
                "tenant_id",
                "resource_urn",
                "system",
                "binding_kind",
                "external_namespace",
                "external_object_id",
                "external_object_type",
                "external_version_ref",
            )
        }
    )
    gateway.register_metadata_fabric_binding(MetadataFabricBinding(**binding_values))
    projections = master_authority.resource_projections(tenant_id, entity_ref)
    if len(projections.items) != 1:
        raise AcceptanceError("activation did not create exactly one resource projection")
    return tenant_id, activation.activation_version, version


def _glossary_term_counts(
    client: httpx.Client,
    headers: dict[str, str],
    glossary_id: str,
    term_id: str,
) -> tuple[int, int]:
    payload = _require_success(
        client.get(
            "/api/v1/glossaryTerms",
            params={"glossary": glossary_id, "limit": 100},
            headers=headers,
        ),
        "OpenMetadata glossary term list",
    )
    data = payload.get("data")
    if not isinstance(data, list):
        raise AcceptanceError("OpenMetadata glossary term list returned invalid data")
    exact_count = sum(1 for item in data if isinstance(item, dict) and item.get("id") == term_id)
    return len(data), exact_count


def _cleanup_provider_entities(
    client: httpx.Client,
    headers: dict[str, str],
    glossary_id: str,
    term_id: str,
) -> dict[str, Any]:
    term_delete = client.delete(
        f"/api/v1/glossaryTerms/{term_id}",
        params={"hardDelete": "true", "recursive": "true"},
        headers=headers,
    )
    if not 200 <= term_delete.status_code < 300:
        raise AcceptanceError(
            f"OpenMetadata glossary term cleanup failed with HTTP {term_delete.status_code}"
        )
    glossary_delete = client.delete(
        f"/api/v1/glossaries/{glossary_id}",
        params={"hardDelete": "true", "recursive": "true"},
        headers=headers,
    )
    if not 200 <= glossary_delete.status_code < 300:
        raise AcceptanceError(
            f"OpenMetadata glossary cleanup failed with HTTP {glossary_delete.status_code}"
        )
    term_get = client.get(f"/api/v1/glossaryTerms/{term_id}", headers=headers)
    glossary_get = client.get(f"/api/v1/glossaries/{glossary_id}", headers=headers)
    if term_get.status_code != 404 or glossary_get.status_code != 404:
        raise AcceptanceError("OpenMetadata provider resources were not hard-deleted")
    return {
        "term_delete_status": term_delete.status_code,
        "glossary_delete_status": glossary_delete.status_code,
        "term_read_after_delete_status": term_get.status_code,
        "glossary_read_after_delete_status": glossary_get.status_code,
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[1]
    _prepare_control_database(args.control_database_url, repository_root)
    engine = create_engine(args.control_database_url)
    gateway = PlatformGateway(engine)
    glossary: dict[str, Any] | None = None
    term: dict[str, Any] | None = None
    token: str | None = None
    cleanup: dict[str, Any] | None = None

    try:
        with httpx.Client(
            base_url=args.openmetadata_url.rstrip("/"),
            timeout=args.timeout_seconds,
            follow_redirects=False,
        ) as provider:
            token = _login(provider)
            headers = {"Authorization": f"Bearer {token}"}
            suffix = uuid4().hex[:12]
            glossary, term = _create_provider_entities(provider, headers, suffix)
            unauthorized = provider.patch(
                f"/api/v1/glossaryTerms/{term['id']}",
                json=[{"op": "replace", "path": "/description", "value": "denied"}],
                headers={"Content-Type": "application/json-patch+json"},
            )
            if unauthorized.status_code not in {401, 403}:
                raise AcceptanceError(
                    "unauthenticated OpenMetadata glossary term PATCH was not rejected"
                )

        _write_token(args.token_file, token)
        tenant_id, activation_version, version = _seed_control_ledger(
            engine,
            glossary,
            term,
            suffix,
        )

        uncertain_transport = CommitThenTimeoutTransport()
        reconciled_client = OpenMetadataMasterDataClient(
            args.openmetadata_url,
            bearer_token_file=args.token_file,
            timeout_seconds=args.timeout_seconds,
            transport=uncertain_transport,
        )
        capturing_client = CapturingProjectionClient(reconciled_client)
        worker = OpenMetadataMasterDataWorker(
            OpenMetadataMasterDataWorkerConfig(
                tenant_id=tenant_id,
                worker_id="worker:openmetadata-master-real-acceptance",
                openmetadata_url=args.openmetadata_url,
                bearer_token_file=args.token_file,
                batch_size=1,
                lease_seconds=max(65, int(args.timeout_seconds * 4)),
                retry_delay_seconds=0,
                poll_interval_seconds=1,
                timeout_seconds=args.timeout_seconds,
            ),
            gateway=gateway,
            client=capturing_client,
        )
        try:
            cycle = worker.run_once()
        finally:
            reconciled_client.close()
        if (cycle.claimed, cycle.delivered, cycle.retrying, cycle.dead_lettered) != (
            1,
            1,
            0,
            0,
        ):
            with engine.connect() as connection:
                failed_delivery = (
                    connection.execute(
                        text(
                            """
                            SELECT status, attempt_count, last_error
                            FROM gda_control.master_metadata_projection_outbox
                            WHERE tenant_id = :tenant_id
                              AND entity_ref = :entity_ref
                              AND activation_version = :activation_version
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "entity_ref": version.entity_ref,
                            "activation_version": activation_version,
                        },
                    )
                    .mappings()
                    .one()
                )
            raise AcceptanceError(
                f"unexpected worker cycle: {cycle}; delivery={dict(failed_delivery)}"
            )
        if uncertain_transport.methods != ["GET", "PATCH", "GET"]:
            raise AcceptanceError(
                f"uncertain patch did not reconcile as expected: {uncertain_transport.methods}"
            )
        if set(uncertain_transport.patch_paths) != {"/displayName", "/description"}:
            raise AcceptanceError(
                f"worker patched fields outside its authority: {uncertain_transport.patch_paths}"
            )
        if uncertain_transport.masked_status is None:
            raise AcceptanceError("acceptance transport did not mask a committed PATCH")
        if len(capturing_client.envelopes) != 1:
            raise AcceptanceError("worker did not deliver exactly one projection envelope")

        replay_transport = RecordingHTTPTransport()
        with OpenMetadataMasterDataClient(
            args.openmetadata_url,
            bearer_token_file=args.token_file,
            timeout_seconds=args.timeout_seconds,
            transport=replay_transport,
        ) as replay_client:
            replay_client.deliver(capturing_client.envelopes[0])
        if replay_transport.methods != ["GET"]:
            raise AcceptanceError(
                f"idempotent replay issued a provider write: {replay_transport.methods}"
            )

        with httpx.Client(
            base_url=args.openmetadata_url.rstrip("/"),
            timeout=args.timeout_seconds,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {token}"},
        ) as provider:
            final_term = _require_success(
                provider.get(f"/api/v1/glossaryTerms/{term['id']}"),
                "OpenMetadata final glossary term query",
            )
            desired = render_master_glossary_term(capturing_client.envelopes[0])
            if any(final_term.get(field) != value for field, value in desired.items()):
                raise AcceptanceError("provider term does not match the active master version")
            glossary_term_count, exact_term_count = _glossary_term_counts(
                provider,
                {"Authorization": f"Bearer {token}"},
                glossary["id"],
                term["id"],
            )
            if glossary_term_count != 1 or exact_term_count != 1:
                raise AcceptanceError(
                    "expected one unique provider glossary term, found "
                    f"{glossary_term_count} total and {exact_term_count} exact"
                )

        with engine.connect() as connection:
            outbox = (
                connection.execute(
                    text(
                        """
                        SELECT status, attempt_count, completed_at IS NOT NULL AS completed
                        FROM gda_control.master_metadata_projection_outbox
                        WHERE tenant_id = :tenant_id
                          AND entity_ref = :entity_ref
                          AND activation_version = :activation_version
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "entity_ref": version.entity_ref,
                        "activation_version": activation_version,
                    },
                )
                .mappings()
                .one()
            )
        if outbox["status"] != "done" or outbox["attempt_count"] != 1 or not outbox["completed"]:
            raise AcceptanceError(f"outbox was not completed exactly once: {dict(outbox)}")

        with httpx.Client(
            base_url=args.openmetadata_url.rstrip("/"),
            timeout=args.timeout_seconds,
            follow_redirects=False,
        ) as provider:
            cleanup = _cleanup_provider_entities(
                provider,
                {"Authorization": f"Bearer {token}"},
                glossary["id"],
                term["id"],
            )

        return {
            "schema": "gda.openmetadata_master_data_acceptance.v1",
            "status": "passed",
            "verified_at": datetime.now(UTC).isoformat(),
            "provider": {
                "product": "OpenMetadata",
                "version": "1.13.1",
                "authentication": "basic-login-to-jwt",
                "unauthenticated_patch_status": unauthorized.status_code,
            },
            "control_ledger": {
                "tenant_id": tenant_id,
                "entity_ref": version.entity_ref,
                "entity_version_ref": version.entity_version_ref,
                "entity_fingerprint": version.entity_fingerprint,
                "activation_version": activation_version,
                "outbox_status": outbox["status"],
                "attempt_count": outbox["attempt_count"],
            },
            "projection": {
                "glossary_id": glossary["id"],
                "glossary_fqn": glossary["fullyQualifiedName"],
                "term_id": term["id"],
                "uncertain_delivery_methods": uncertain_transport.methods,
                "masked_provider_status": uncertain_transport.masked_status,
                "patch_paths": uncertain_transport.patch_paths,
                "replay_methods": replay_transport.methods,
                "glossary_term_count": glossary_term_count,
                "exact_term_count": exact_term_count,
                "desired_fields": desired,
            },
            "cleanup": cleanup,
        }
    finally:
        engine.dispose()
        if cleanup is None and token is not None and glossary is not None and term is not None:
            try:
                with httpx.Client(
                    base_url=args.openmetadata_url.rstrip("/"),
                    timeout=args.timeout_seconds,
                    follow_redirects=False,
                ) as provider:
                    _cleanup_provider_entities(
                        provider,
                        {"Authorization": f"Bearer {token}"},
                        glossary["id"],
                        term["id"],
                    )
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openmetadata-url", default="http://127.0.0.1:18585")
    parser.add_argument(
        "--control-database-url",
        default=(
            "postgresql+psycopg://postgres:gda_acceptance_password@"
            "127.0.0.1:15433/gda_control_acceptance"
        ),
    )
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()
    if not args.token_file.is_absolute():
        raise AcceptanceError("--token-file must be absolute")
    evidence = run_acceptance(args)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.evidence_file is not None:
        args.evidence_file.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
