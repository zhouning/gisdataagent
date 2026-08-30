"""Contracts for reconciled master-data projection into OpenMetadata."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from data_agent.master_data_authority import MasterDataDomain, MasterEntityVersion
from data_agent.metadata_fabric import (
    MasterMetadataProjectionChange,
    MasterMetadataProjectionEnvelope,
    MetadataFabricBinding,
    metadata_fabric_binding_fingerprint,
)
from data_agent.openmetadata_master_data_worker import (
    OpenMetadataMasterDataBindingError,
    OpenMetadataMasterDataClient,
    OpenMetadataMasterDataConfigurationError,
    OpenMetadataMasterDataDeliveryError,
    OpenMetadataMasterDataWorker,
    OpenMetadataMasterDataWorkerConfig,
    render_master_glossary_term,
)
from data_agent.platform_contracts import ResourceVersion

TENANT = "tenant-a"
ENTITY_REF = "gda://tenant-a/master_entity/administrative-unit-500112"
VERSION_REF = f"{ENTITY_REF}.v2"
SOURCE_REF = (
    "gda://tenant-a/master_source_record/11111111111111111111111111111111"
)
RESOURCE_VERSION_ID = UUID("50000000-0000-5000-8000-000000000001")
CHANGE_ID = UUID("50000000-0000-4000-8000-000000000002")
TERM_ID = "50000000-0000-4000-8000-000000000003"
BINDING_ID = UUID("50000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
FINGERPRINT = "b" * 64
WORKER_ID = "worker:master-metadata:test"


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "openmetadata-token"
    path.write_text("provider-token\n", encoding="utf-8")
    return path


def _binding(
    *,
    object_type: str = "glossaryTerm",
    namespace: str = "NaturalResources",
) -> MetadataFabricBinding:
    values = {
        "tenant_id": TENANT,
        "binding_id": BINDING_ID,
        "resource_urn": ENTITY_REF,
        "system": "openmetadata",
        "binding_kind": "governance_entity",
        "external_namespace": namespace,
        "external_object_id": TERM_ID,
        "external_object_type": object_type,
        "external_version_ref": "1.13.1",
        "created_by": "human:metadata-steward",
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


def _master_version() -> MasterEntityVersion:
    return MasterEntityVersion(
        tenant_id=TENANT,
        entity_ref=ENTITY_REF,
        entity_version_ref=VERSION_REF,
        version=2,
        domain=MasterDataDomain.ADMINISTRATIVE_UNIT,
        business_key="500112",
        canonical_name="Bishan District",
        attributes={"level": "county"},
        source_record_refs=(SOURCE_REF,),
        valid_from=date(2026, 1, 1),
        owner_subject="team:natural-resource-governance",
        created_by="human:master-data-steward",
        creation_reason="publish governed administrative unit",
        created_at=NOW,
        entity_fingerprint=FINGERPRINT,
    )


def _resource_version() -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=ENTITY_REF,
        resource_version_id=RESOURCE_VERSION_ID,
        version_key="v2",
        content_sha256=FINGERPRINT,
        authority_version_ref={
            "authority_system": "gda_control.master_data",
            "entity_version_ref": VERSION_REF,
            "entity_fingerprint": FINGERPRINT,
        },
        created_by="human:master-data-steward",
        created_at=NOW,
    )


def _change(*, attempt_count: int = 1) -> MasterMetadataProjectionChange:
    return MasterMetadataProjectionChange(
        tenant_id=TENANT,
        projection_change_id=CHANGE_ID,
        entity_ref=ENTITY_REF,
        activation_version=2,
        resource_version_id=RESOURCE_VERSION_ID,
        entity_fingerprint=FINGERPRINT,
        destination_ref="openmetadata:default",
        payload_sha256=FINGERPRINT,
        status="in_flight",
        attempt_count=attempt_count,
        claimed_by=WORKER_ID,
        claimed_until=NOW + timedelta(minutes=10),
        available_at=NOW,
        created_at=NOW,
    )


def _envelope(
    *,
    binding: MetadataFabricBinding | None = None,
) -> MasterMetadataProjectionEnvelope:
    return MasterMetadataProjectionEnvelope(
        change=_change(),
        master_version=_master_version(),
        resource_version=_resource_version(),
        openmetadata_binding=binding if binding is not None else _binding(),
    )


def _term_response(
    envelope: MasterMetadataProjectionEnvelope,
    *,
    projected: bool,
    namespace: str = "NaturalResources",
) -> dict:
    desired = render_master_glossary_term(envelope)
    return {
        "id": TERM_ID,
        "name": "administrative-unit-500112",
        "displayName": desired["displayName"] if projected else "Old name",
        "description": desired["description"] if projected else "Old description",
        "glossary": {"name": namespace, "fullyQualifiedName": namespace},
        "deleted": False,
    }


def _client(tmp_path: Path, handler) -> OpenMetadataMasterDataClient:
    return OpenMetadataMasterDataClient(
        "https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        transport=httpx.MockTransport(handler),
    )


def test_rendered_glossary_projection_is_content_bound_and_minimal() -> None:
    desired = render_master_glossary_term(_envelope())

    assert desired["displayName"] == "Bishan District"
    assert VERSION_REF in desired["description"]
    assert FINGERPRINT in desired["description"]
    assert "`" not in desired["description"]
    assert set(desired) == {"displayName", "description"}


def test_existing_exact_term_completes_without_patch(tmp_path: Path) -> None:
    envelope = _envelope()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_term_response(envelope, projected=True))

    with _client(tmp_path, handler) as client:
        client.deliver(envelope)

    assert [request.method for request in requests] == ["GET"]
    assert requests[0].url.path == f"/api/v1/glossaryTerms/{TERM_ID}"
    assert requests[0].headers["authorization"] == "Bearer provider-token"


def test_patch_is_minimal_and_requires_exact_read_after_write(tmp_path: Path) -> None:
    envelope = _envelope()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json=_term_response(envelope, projected=len(requests) == 3),
        )

    with _client(tmp_path, handler) as client:
        client.deliver(envelope)

    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]
    patch = json.loads(requests[1].content)
    assert {operation["path"] for operation in patch} == {
        "/displayName",
        "/description",
    }
    assert requests[1].headers["content-type"] == "application/json-patch+json"


def test_patch_timeout_succeeds_only_after_provider_confirmation(tmp_path: Path) -> None:
    envelope = _envelope()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            raise httpx.ReadTimeout("commit outcome unknown", request=request)
        return httpx.Response(
            200,
            json=_term_response(envelope, projected=len(requests) == 3),
        )

    with _client(tmp_path, handler) as client:
        client.deliver(envelope)

    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]


def test_missing_wrong_or_stale_binding_never_guesses_identity(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404)

    with _client(tmp_path, handler) as client:
        with pytest.raises(OpenMetadataMasterDataBindingError, match="missing"):
            client.deliver(_envelope().model_copy(update={"openmetadata_binding": None}))
        with pytest.raises(OpenMetadataMasterDataBindingError, match="not a glossaryTerm"):
            client.deliver(_envelope(binding=_binding(object_type="table")))
        with pytest.raises(OpenMetadataMasterDataBindingError, match="stale"):
            client.deliver(_envelope())

    assert [request.method for request in requests] == ["GET"]


def test_namespace_mismatch_and_unconfirmed_patch_remain_retryable(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    with _client(
        tmp_path,
        lambda _request: httpx.Response(
            200,
            json=_term_response(envelope, projected=False, namespace="OtherGlossary"),
        ),
    ) as client:
        with pytest.raises(OpenMetadataMasterDataBindingError, match="namespace"):
            client.deliver(envelope)

    def rejected_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(503)
        return httpx.Response(200, json=_term_response(envelope, projected=False))

    with _client(tmp_path, rejected_handler) as client:
        with pytest.raises(OpenMetadataMasterDataDeliveryError, match="HTTP 503"):
            client.deliver(envelope)


class _Gateway:
    def __init__(self, envelope, *, failed_status="pending"):
        self.envelope = envelope
        self.failed_status = failed_status
        self.completed = []
        self.failed = []

    def claim_master_metadata_projections(self, *_args, **_kwargs):
        return (self.envelope,)

    def complete_master_metadata_projection(self, tenant_id, change_id, **kwargs):
        self.completed.append((tenant_id, change_id, kwargs))
        return MasterMetadataProjectionChange(
            **{
                **self.envelope.change.model_dump(),
                "status": "done",
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )

    def fail_master_metadata_projection(self, tenant_id, change_id, **kwargs):
        self.failed.append((tenant_id, change_id, kwargs))
        return MasterMetadataProjectionChange(
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


def _worker(tmp_path: Path, gateway, client) -> OpenMetadataMasterDataWorker:
    return OpenMetadataMasterDataWorker(
        OpenMetadataMasterDataWorkerConfig(
            tenant_id=TENANT,
            worker_id=WORKER_ID,
            openmetadata_url="https://metadata.internal",
            bearer_token_file=_token_file(tmp_path),
        ),
        gateway=gateway,
        client=client,
    )


def test_worker_completes_only_confirmed_projection(tmp_path: Path) -> None:
    envelope = _envelope()
    gateway = _Gateway(envelope)
    client = _ProjectionClient()

    cycle = _worker(tmp_path, gateway, client).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert client.delivered == [envelope]
    assert len(gateway.completed) == 1
    assert gateway.failed == []


def test_worker_tracks_retry_and_dead_letter_without_acknowledging_bug(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    retry_gateway = _Gateway(envelope)
    retry_cycle = _worker(
        tmp_path,
        retry_gateway,
        _ProjectionClient(OpenMetadataMasterDataBindingError("mapping missing")),
    ).run_once()
    assert (retry_cycle.retrying, retry_cycle.dead_lettered) == (1, 0)

    dead_gateway = _Gateway(envelope, failed_status="failed")
    dead_cycle = _worker(
        tmp_path,
        dead_gateway,
        _ProjectionClient(OpenMetadataMasterDataDeliveryError("provider unavailable")),
    ).run_once()
    assert (dead_cycle.retrying, dead_cycle.dead_lettered) == (0, 1)

    bug_gateway = _Gateway(envelope)
    with pytest.raises(ValueError, match="adapter bug"):
        _worker(
            tmp_path,
            bug_gateway,
            _ProjectionClient(ValueError("adapter bug")),
        ).run_once()
    assert bug_gateway.completed == []
    assert bug_gateway.failed == []


def test_worker_configuration_lease_covers_http_budget(tmp_path: Path) -> None:
    config = OpenMetadataMasterDataWorkerConfig(
        tenant_id=TENANT,
        worker_id=WORKER_ID,
        openmetadata_url="https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        batch_size=10,
        lease_seconds=300,
        timeout_seconds=10,
    )
    with pytest.raises(OpenMetadataMasterDataConfigurationError, match="worst-case"):
        config.validate()
