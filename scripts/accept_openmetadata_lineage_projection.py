#!/usr/bin/env python3
"""Real-provider acceptance for the GDA OpenMetadata lineage outbox worker."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, text

from data_agent.metadata_fabric import (
    MetadataFabricBinding,
    metadata_fabric_binding_fingerprint,
)
from data_agent.openmetadata_lineage_worker import (
    OpenMetadataLineageClient,
    OpenMetadataLineageWorker,
    OpenMetadataLineageWorkerConfig,
    render_openmetadata_lineage,
)
from data_agent.platform_contracts import (
    LineageEvent,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "093_app_user_tenant_context.sql",
    "094_platform_control_gateway.sql",
    "095_platform_command_outbox.sql",
    "096_platform_success_verdict.sql",
    "097_platform_cancel_command.sql",
    "098_platform_data_incident.sql",
    "099_platform_incident_notification_outbox.sql",
    "112_metadata_fabric_binding_outbox.sql",
)


class AcceptanceError(RuntimeError):
    """A required real-provider acceptance assertion failed."""


class RecordingHTTPTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self._delegate = httpx.HTTPTransport()
        self.methods: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        return self._delegate.handle_request(request)

    def close(self) -> None:
        self._delegate.close()


class CommitThenTimeoutTransport(RecordingHTTPTransport):
    """Hide one successful provider PUT response to force reconciliation."""

    def __init__(self) -> None:
        super().__init__()
        self.masked_status: int | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        if (
            request.method == "PUT"
            and request.url.path.endswith("/api/v1/lineage")
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
    def __init__(self, delegate: OpenMetadataLineageClient) -> None:
        self.delegate = delegate
        self.envelopes = []

    def deliver(self, envelope) -> None:
        self.envelopes.append(envelope)
        self.delegate.deliver(envelope)


def _require_success(response: httpx.Response, operation: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        body = response.text[:500].replace("\n", " ")
        raise AcceptanceError(
            f"{operation} failed with HTTP {response.status_code}: {body}"
        )
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
    service = _put_entity(
        client,
        "/api/v1/services/databaseServices",
        {"name": f"gda_acceptance_{suffix}", "serviceType": "Postgres"},
        headers,
    )
    database = _put_entity(
        client,
        "/api/v1/databases",
        {"name": "control", "service": service["fullyQualifiedName"]},
        headers,
    )
    schema = _put_entity(
        client,
        "/api/v1/databaseSchemas",
        {"name": "lineage", "database": database["fullyQualifiedName"]},
        headers,
    )
    tables = []
    for name in ("source_parcels", "published_parcels"):
        tables.append(
            _put_entity(
                client,
                "/api/v1/tables",
                {
                    "name": name,
                    "databaseSchema": schema["fullyQualifiedName"],
                    "columns": [{"name": "parcel_id", "dataType": "BIGINT"}],
                },
                headers,
            )
        )
    return tables[0], tables[1]


def _prepare_control_database(database_url: str, repository_root: Path) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS agent_app_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL
                )
                """
            )
            for filename in MIGRATIONS:
                migration = repository_root / "data_agent" / "migrations" / filename
                connection.execute(text(migration.read_text(encoding="utf-8")))
    finally:
        engine.dispose()


def _resource_version(
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    marker: str,
    now: datetime,
) -> ResourceVersion:
    return ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=resource_urn,
        resource_version_id=resource_version_id,
        version_key=f"snapshot-{marker}",
        content_sha256=marker * 64,
        authority_version_ref={"acceptance": marker},
        created_by="workload:openmetadata-acceptance",
        created_at=now,
    )


def _binding(
    tenant_id: str,
    resource_urn: str,
    object_id: str,
    binding_id: UUID,
    now: datetime,
) -> MetadataFabricBinding:
    values = {
        "tenant_id": tenant_id,
        "binding_id": binding_id,
        "resource_urn": resource_urn,
        "system": "openmetadata",
        "binding_kind": "governance_entity",
        "external_namespace": "acceptance:openmetadata-1.13.1",
        "external_object_id": object_id,
        "external_object_type": "table",
        "external_version_ref": "1.13.1",
        "created_by": "workload:openmetadata-acceptance",
        "created_at": now,
    }
    values["binding_sha256"] = metadata_fabric_binding_fingerprint(
        **{
            key: values[key]
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
    return MetadataFabricBinding(**values)


def _seed_control_ledger(
    gateway: PlatformGateway,
    source_table: dict[str, Any],
    target_table: dict[str, Any],
) -> tuple[str, UUID]:
    suffix = uuid4().hex[:12]
    tenant_id = f"om-acceptance-{suffix}"
    source_urn = f"gda://{tenant_id}/dataset/source-parcels"
    target_urn = f"gda://{tenant_id}/dataset/published-parcels"
    now = datetime.now(UTC)
    for urn, locator in (
        (source_urn, source_table["fullyQualifiedName"]),
        (target_urn, target_table["fullyQualifiedName"]),
    ):
        gateway.register_resource(
            Resource(
                tenant_id=tenant_id,
                resource_urn=urn,
                resource_kind="dataset",
                authority_system="openmetadata-acceptance",
                authority_locator=locator,
                owner_ref="team:data-platform",
            )
        )

    source_version_id = uuid4()
    target_version_id = uuid4()
    gateway.register_resource_version(
        _resource_version(tenant_id, source_urn, source_version_id, "a", now)
    )
    gateway.register_resource_version(
        _resource_version(tenant_id, target_urn, target_version_id, "b", now)
    )
    gateway.register_metadata_fabric_binding(
        _binding(tenant_id, source_urn, source_table["id"], uuid4(), now)
    )
    gateway.register_metadata_fabric_binding(
        _binding(tenant_id, target_urn, target_table["id"], uuid4(), now)
    )

    lineage_event_id = uuid4()
    facets = {"acceptance": "openmetadata-1.13.1", "operation": "publish"}
    gateway.record_lineage(
        LineageEvent(
            tenant_id=tenant_id,
            lineage_event_id=lineage_event_id,
            event_type="publish",
            source_resource_version_id=source_version_id,
            target_resource_version_id=target_version_id,
            producer="workload:openmetadata-acceptance",
            event_sha256=canonical_json_fingerprint(
                {
                    "tenant_id": tenant_id,
                    "source": str(source_version_id),
                    "target": str(target_version_id),
                    "facets": facets,
                }
            ),
            facets=facets,
            occurred_at=now,
        )
    )
    return tenant_id, lineage_event_id


def _write_token(path: Path, token: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, token.encode("utf-8"))
    finally:
        os.close(descriptor)


def _exact_edge_count(payload: dict[str, Any], source_id: str, target_id: str) -> int:
    edges = payload.get("downstreamEdges") or []
    if not isinstance(edges, list):
        raise AcceptanceError("OpenMetadata returned invalid downstreamEdges")
    return sum(
        1
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("fromEntity") == source_id
        and edge.get("toEntity") == target_id
    )


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[1]
    _prepare_control_database(args.control_database_url, repository_root)
    gateway = PlatformGateway(create_engine(args.control_database_url))

    with httpx.Client(
        base_url=args.openmetadata_url.rstrip("/"),
        timeout=args.timeout_seconds,
        follow_redirects=False,
    ) as provider:
        token = _login(provider)
        headers = {"Authorization": f"Bearer {token}"}
        suffix = uuid4().hex[:12]
        source_table, target_table = _create_provider_entities(
            provider, headers, suffix
        )
        unauthorized = provider.put(
            "/api/v1/lineage",
            json={
                "edge": {
                    "fromEntity": {"id": source_table["id"], "type": "table"},
                    "toEntity": {"id": target_table["id"], "type": "table"},
                }
            },
        )
        if unauthorized.status_code not in {401, 403}:
            raise AcceptanceError(
                "unauthenticated OpenMetadata lineage PUT was not rejected"
            )

    _write_token(args.token_file, token)
    tenant_id, lineage_event_id = _seed_control_ledger(
        gateway, source_table, target_table
    )

    uncertain_transport = CommitThenTimeoutTransport()
    reconciled_client = OpenMetadataLineageClient(
        args.openmetadata_url,
        bearer_token_file=args.token_file,
        timeout_seconds=args.timeout_seconds,
        transport=uncertain_transport,
    )
    capturing_client = CapturingProjectionClient(reconciled_client)
    worker = OpenMetadataLineageWorker(
        OpenMetadataLineageWorkerConfig(
            tenant_id=tenant_id,
            worker_id="worker:openmetadata-real-acceptance",
            openmetadata_url=args.openmetadata_url,
            bearer_token_file=args.token_file,
            batch_size=1,
            lease_seconds=max(60, int(args.timeout_seconds * 4)),
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
        raise AcceptanceError(f"unexpected worker cycle: {cycle}")
    if uncertain_transport.methods != ["GET", "PUT", "GET"]:
        raise AcceptanceError(
            f"uncertain write did not reconcile as expected: {uncertain_transport.methods}"
        )
    if uncertain_transport.masked_status is None:
        raise AcceptanceError("acceptance transport did not mask a committed PUT")
    if len(capturing_client.envelopes) != 1:
        raise AcceptanceError("worker did not deliver exactly one projection envelope")

    replay_transport = RecordingHTTPTransport()
    with OpenMetadataLineageClient(
        args.openmetadata_url,
        bearer_token_file=args.token_file,
        timeout_seconds=args.timeout_seconds,
        transport=replay_transport,
    ) as replay_client:
        replay_client.deliver(capturing_client.envelopes[0])
    if replay_transport.methods != ["GET"]:
        raise AcceptanceError(
            f"replay issued a provider write: {replay_transport.methods}"
        )

    with httpx.Client(
        base_url=args.openmetadata_url.rstrip("/"),
        timeout=args.timeout_seconds,
        follow_redirects=False,
        headers={"Authorization": f"Bearer {token}"},
    ) as provider:
        lineage = _require_success(
            provider.get(
                f"/api/v1/lineage/table/{source_table['id']}",
                params={"upstreamDepth": 0, "downstreamDepth": 1},
            ),
            "OpenMetadata final lineage query",
        )
    exact_edges = _exact_edge_count(
        lineage, source_table["id"], target_table["id"]
    )
    if exact_edges != 1:
        raise AcceptanceError(f"expected one exact provider edge, found {exact_edges}")

    engine = create_engine(args.control_database_url)
    try:
        with engine.connect() as connection:
            outbox = (
                connection.execute(
                    text(
                        """
                        SELECT status, attempt_count, completed_at IS NOT NULL AS completed
                        FROM gda_control.metadata_change_outbox
                        WHERE tenant_id = :tenant_id AND aggregate_id = :aggregate_id
                        """
                    ),
                    {"tenant_id": tenant_id, "aggregate_id": lineage_event_id},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    if outbox["status"] != "done" or outbox["attempt_count"] != 1 or not outbox["completed"]:
        raise AcceptanceError(f"outbox was not completed exactly once: {dict(outbox)}")

    return {
        "schema": "gda.openmetadata_lineage_acceptance.v1",
        "status": "passed",
        "verified_at": datetime.now(UTC).isoformat(),
        "provider": {
            "product": "OpenMetadata",
            "version": "1.13.1",
            "authentication": "basic-login-to-jwt",
            "unauthenticated_lineage_status": unauthorized.status_code,
        },
        "control_ledger": {
            "tenant_id": tenant_id,
            "lineage_event_id": str(lineage_event_id),
            "outbox_status": outbox["status"],
            "attempt_count": outbox["attempt_count"],
        },
        "projection": {
            "source_entity_id": source_table["id"],
            "target_entity_id": target_table["id"],
            "uncertain_delivery_methods": uncertain_transport.methods,
            "masked_provider_status": uncertain_transport.masked_status,
            "replay_methods": replay_transport.methods,
            "exact_edge_count": exact_edges,
            "request": render_openmetadata_lineage(
                capturing_client.envelopes[0].source_binding,
                capturing_client.envelopes[0].target_binding,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openmetadata-url", default="http://127.0.0.1:18585"
    )
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
