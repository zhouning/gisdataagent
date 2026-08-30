import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from data_agent.metadata_fabric import (
    MetadataChange,
    MetadataFabricBinding,
    MetadataLineageProjectionEnvelope,
    metadata_fabric_binding_fingerprint,
)
from data_agent.openmetadata_lineage_worker import (
    OpenMetadataLineageBindingError,
    OpenMetadataLineageClient,
    OpenMetadataLineageConfigurationError,
    OpenMetadataLineageDeliveryError,
    OpenMetadataLineageWorker,
    OpenMetadataLineageWorkerConfig,
    normalize_openmetadata_api_url,
    render_openmetadata_lineage,
)
from data_agent.platform_contracts import LineageEvent, ResourceVersion

TENANT = "tenant-a"
SOURCE_URN = "gda://tenant-a/dataset/parcels"
TARGET_URN = "gda://tenant-a/dataset/published-parcels"
SOURCE_ID = "40000000-0000-4000-8000-000000000001"
TARGET_ID = "40000000-0000-4000-8000-000000000002"
SOURCE_VERSION_ID = UUID("40000000-0000-4000-8000-000000000003")
TARGET_VERSION_ID = UUID("40000000-0000-4000-8000-000000000004")
LINEAGE_ID = UUID("40000000-0000-4000-8000-000000000005")
CHANGE_ID = UUID("40000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "openmetadata-token"
    path.write_text("provider-token\n", encoding="utf-8")
    return path


def _binding(resource_urn: str, object_id: str, binding_id: UUID):
    values = {
        "tenant_id": TENANT,
        "binding_id": binding_id,
        "resource_urn": resource_urn,
        "system": "openmetadata",
        "binding_kind": "governance_entity",
        "external_namespace": "service:iceberg-prod",
        "external_object_id": object_id,
        "external_object_type": "table",
        "external_version_ref": "1.13.1",
        "created_by": "human:metadata-operator",
        "created_at": NOW,
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


def _version(resource_urn: str, version_id: UUID, content: str):
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=resource_urn,
        resource_version_id=version_id,
        version_key=str(version_id),
        content_sha256=content * 64,
        authority_version_ref={"snapshot": str(version_id)},
        created_by="workload:publisher",
        created_at=NOW,
    )


def _envelope(
    *,
    source_binding: MetadataFabricBinding | None = None,
    target_binding: MetadataFabricBinding | None = None,
    attempt_count: int = 1,
) -> MetadataLineageProjectionEnvelope:
    change = MetadataChange(
        tenant_id=TENANT,
        change_id=CHANGE_ID,
        change_type="lineage_upsert",
        aggregate_id=LINEAGE_ID,
        destination_ref="openmetadata:default",
        payload_sha256="c" * 64,
        status="in_flight",
        attempt_count=attempt_count,
        claimed_by="worker:test",
        claimed_until=NOW + timedelta(minutes=10),
        available_at=NOW,
        created_at=NOW,
    )
    lineage = LineageEvent(
        tenant_id=TENANT,
        lineage_event_id=LINEAGE_ID,
        event_type="publish",
        source_resource_version_id=SOURCE_VERSION_ID,
        target_resource_version_id=TARGET_VERSION_ID,
        producer="workload:publisher",
        event_sha256="c" * 64,
        facets={"source": "openlineage"},
        occurred_at=NOW,
    )
    return MetadataLineageProjectionEnvelope(
        change=change,
        lineage_event=lineage,
        source_resource_version=_version(SOURCE_URN, SOURCE_VERSION_ID, "a"),
        target_resource_version=_version(TARGET_URN, TARGET_VERSION_ID, "b"),
        source_binding=(
            source_binding
            if source_binding is not None
            else _binding(SOURCE_URN, SOURCE_ID, UUID(SOURCE_ID))
        ),
        target_binding=(
            target_binding
            if target_binding is not None
            else _binding(TARGET_URN, TARGET_ID, UUID(TARGET_ID))
        ),
    )


def _lineage_response(*, include_edge: bool) -> dict:
    return {
        "entity": {"id": SOURCE_ID, "type": "table"},
        "nodes": [],
        "upstreamEdges": [],
        "downstreamEdges": (
            [{"fromEntity": SOURCE_ID, "toEntity": TARGET_ID}]
            if include_edge
            else []
        ),
    }


def _client(tmp_path: Path, handler) -> OpenMetadataLineageClient:
    return OpenMetadataLineageClient(
        "https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        transport=httpx.MockTransport(handler),
    )


def test_openmetadata_contract_renders_verified_1_13_1_put_shape():
    envelope = _envelope()
    assert render_openmetadata_lineage(
        envelope.source_binding, envelope.target_binding
    ) == {
        "edge": {
            "fromEntity": {"id": SOURCE_ID, "type": "table"},
            "toEntity": {"id": TARGET_ID, "type": "table"},
        }
    }


def test_existing_edge_is_completed_without_put(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_lineage_response(include_edge=True))

    with _client(tmp_path, handler) as client:
        client.deliver(_envelope())

    assert [request.method for request in requests] == ["GET"]
    assert requests[0].url.path == f"/api/v1/lineage/table/{SOURCE_ID}"
    assert requests[0].url.params["upstreamDepth"] == "0"
    assert requests[0].headers["authorization"] == "Bearer provider-token"


def test_put_is_followed_by_exact_edge_confirmation(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(201, json={})
        return httpx.Response(
            200,
            json=_lineage_response(include_edge=len(requests) == 3),
        )

    with _client(tmp_path, handler) as client:
        client.deliver(_envelope())

    assert [request.method for request in requests] == ["GET", "PUT", "GET"]
    assert requests[1].url.path == "/api/v1/lineage"
    assert json.loads(requests[1].content)["edge"]["toEntity"]["id"] == TARGET_ID


def test_put_timeout_is_success_only_when_reconciliation_finds_edge(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            raise httpx.ReadTimeout("commit outcome unknown", request=request)
        return httpx.Response(
            200,
            json=_lineage_response(include_edge=len(requests) == 3),
        )

    with _client(tmp_path, handler) as client:
        client.deliver(_envelope())

    assert [request.method for request in requests] == ["GET", "PUT", "GET"]


def test_unconfirmed_write_and_query_failures_remain_retryable(tmp_path):
    def rejected_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(503)
        return httpx.Response(200, json=_lineage_response(include_edge=False))

    with _client(tmp_path, rejected_handler) as client:
        with pytest.raises(OpenMetadataLineageDeliveryError, match="HTTP 503"):
            client.deliver(_envelope())

    with _client(
        tmp_path,
        lambda _request: httpx.Response(200, content=b"not-json"),
    ) as client:
        with pytest.raises(OpenMetadataLineageDeliveryError, match="invalid JSON"):
            client.deliver(_envelope())


def test_missing_binding_does_not_send_provider_request(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    envelope = _envelope().model_copy(update={"source_binding": None})
    with _client(tmp_path, handler) as client:
        with pytest.raises(OpenMetadataLineageBindingError, match="source binding"):
            client.deliver(envelope)

    assert requests == []


@pytest.mark.parametrize(
    "url",
    (
        "file:///tmp/openmetadata",
        "https://user:secret@metadata.internal",
        "https://metadata.internal/api/v1?token=secret",
        "https://metadata.internal/api/v2",
    ),
)
def test_openmetadata_url_rejects_unsafe_or_ambiguous_forms(url):
    with pytest.raises(OpenMetadataLineageConfigurationError):
        normalize_openmetadata_api_url(url)


def test_client_requires_absolute_token_file():
    with pytest.raises(OpenMetadataLineageConfigurationError, match="absolute path"):
        OpenMetadataLineageClient(
            "https://metadata.internal",
            bearer_token_file=Path("relative-token"),
        )


class _Gateway:
    def __init__(self, envelope, *, failed_status="pending"):
        self.envelope = envelope
        self.failed_status = failed_status
        self.completed = []
        self.failed = []

    def claim_metadata_changes(self, *_args, **_kwargs):
        return (self.envelope,)

    def complete_metadata_change(self, tenant_id, change_id, **kwargs):
        self.completed.append((tenant_id, change_id, kwargs))
        return MetadataChange(
            **{
                **self.envelope.change.model_dump(),
                "status": "done",
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )

    def fail_metadata_change(self, tenant_id, change_id, **kwargs):
        self.failed.append((tenant_id, change_id, kwargs))
        return MetadataChange(
            **{
                **self.envelope.change.model_dump(),
                "status": self.failed_status,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW if self.failed_status == "failed" else None,
            }
        )


class _ProjectionClient:
    def __init__(self, error=None):
        self.error = error
        self.delivered = []

    def deliver(self, envelope):
        if self.error:
            raise self.error
        self.delivered.append(envelope)


def _worker(tmp_path, gateway, client):
    return OpenMetadataLineageWorker(
        OpenMetadataLineageWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            openmetadata_url="https://metadata.internal",
            bearer_token_file=_token_file(tmp_path),
        ),
        gateway=gateway,
        client=client,
    )


def test_worker_completes_only_after_client_confirms_edge(tmp_path):
    envelope = _envelope()
    gateway = _Gateway(envelope)
    client = _ProjectionClient()

    cycle = _worker(tmp_path, gateway, client).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert client.delivered == [envelope]
    assert len(gateway.completed) == 1
    assert gateway.failed == []


def test_worker_retries_binding_dependency_and_tracks_dead_letter(tmp_path):
    envelope = _envelope()
    retry_gateway = _Gateway(envelope)
    retry_cycle = _worker(
        tmp_path,
        retry_gateway,
        _ProjectionClient(OpenMetadataLineageBindingError("mapping missing")),
    ).run_once()
    assert (retry_cycle.retrying, retry_cycle.dead_lettered) == (1, 0)
    assert len(retry_gateway.failed) == 1

    dead_gateway = _Gateway(envelope, failed_status="failed")
    dead_cycle = _worker(
        tmp_path,
        dead_gateway,
        _ProjectionClient(OpenMetadataLineageDeliveryError("provider unavailable")),
    ).run_once()
    assert (dead_cycle.retrying, dead_cycle.dead_lettered) == (0, 1)


def test_worker_does_not_acknowledge_programming_errors(tmp_path):
    gateway = _Gateway(_envelope())
    with pytest.raises(ValueError, match="adapter bug"):
        _worker(
            tmp_path,
            gateway,
            _ProjectionClient(ValueError("adapter bug")),
        ).run_once()
    assert gateway.completed == []
    assert gateway.failed == []


def test_worker_lease_must_cover_worst_case_claimed_batch(tmp_path):
    config = OpenMetadataLineageWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:test",
        openmetadata_url="https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        batch_size=10,
        lease_seconds=300,
        timeout_seconds=10,
    )
    with pytest.raises(OpenMetadataLineageConfigurationError, match="worst-case"):
        config.validate()
