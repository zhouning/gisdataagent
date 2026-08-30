import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.data_architecture_ledger import ProviderObjectState
from data_agent.metadata_fabric import (
    GRAVITINO_REFERENCE_SCHEMA,
    GravitinoTechnicalObjectReference,
    MetadataChange,
    MetadataFabricBinding,
    MetadataLineageProjectionEnvelope,
    build_gravitino_architecture_observation,
    build_gravitino_reference,
    gravitino_reference_fingerprint,
    gravitino_reference_from_binding,
    metadata_fabric_binding_fingerprint,
)
from data_agent.metadata_provider_read import ProviderReadResult
from data_agent.metadata_provider_search import (
    ProviderSearchItem,
    ProviderSearchPage,
    provider_search_candidate_fingerprint,
)
from data_agent.platform_contracts import LineageEvent, ResourceVersion
from data_agent.platform_gateway import GatewayWriteResult, MetadataFabricBindingPage

TENANT = "tenant-a"
ACTOR = "human:metadata-operator"
RESOURCE_URN = "gda://tenant-a/dataset/parcels"
TARGET_URN = "gda://tenant-a/dataset/published-parcels"
BINDING_ID = UUID("20000000-0000-4000-8000-000000000001")
TARGET_BINDING_ID = UUID("20000000-0000-4000-8000-000000000002")
SOURCE_VERSION_ID = UUID("20000000-0000-4000-8000-000000000003")
TARGET_VERSION_ID = UUID("20000000-0000-4000-8000-000000000004")
LINEAGE_ID = UUID("20000000-0000-4000-8000-000000000005")
CHANGE_ID = UUID("20000000-0000-4000-8000-000000000006")
SOURCE_OPENMETADATA_ID = "20000000-0000-4000-8000-000000000007"
TARGET_OPENMETADATA_ID = "20000000-0000-4000-8000-000000000008"
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)


def _binding(
    *,
    binding_id: UUID = BINDING_ID,
    resource_urn: str = RESOURCE_URN,
    system: str = "openmetadata",
    binding_kind: str = "governance_entity",
    external_object_id: str = SOURCE_OPENMETADATA_ID,
) -> MetadataFabricBinding:
    values = {
        "tenant_id": TENANT,
        "binding_id": binding_id,
        "resource_urn": resource_urn,
        "system": system,
        "binding_kind": binding_kind,
        "external_namespace": "service:iceberg-prod",
        "external_object_id": external_object_id,
        "external_object_type": "table",
        "external_version_ref": "1.13.1",
        "created_by": ACTOR,
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


def _version(resource_urn: str, version_id: UUID, content: str) -> ResourceVersion:
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


def _lineage() -> LineageEvent:
    return LineageEvent(
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


def _change() -> MetadataChange:
    return MetadataChange(
        tenant_id=TENANT,
        change_id=CHANGE_ID,
        change_type="lineage_upsert",
        aggregate_id=LINEAGE_ID,
        destination_ref="openmetadata:default",
        payload_sha256="c" * 64,
        status="in_flight",
        attempt_count=1,
        claimed_by="worker:metadata-fabric",
        claimed_until=NOW + timedelta(minutes=1),
        available_at=NOW,
        created_at=NOW,
    )


def _request(*, body=None, query=None):
    request = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = {}
    request.query_params = query or {}
    request.headers = {"x-request-id": "metadata-fabric-request"}
    return request


def _user(*, tenant_id=TENANT):
    return SimpleNamespace(
        identifier="metadata-operator",
        metadata={
            "role": "platform_operator",
            "tenant_id": tenant_id,
            "subject_type": "human",
        },
    )


def test_metadata_fabric_binding_enforces_authority_and_fingerprint():
    binding = _binding()
    assert binding.system.value == "openmetadata"
    assert len(binding.binding_sha256) == 64

    with pytest.raises(ValidationError, match="binding_kind"):
        _binding(system="gravitino", binding_kind="governance_entity")
    with pytest.raises(ValidationError, match="binding_sha256"):
        MetadataFabricBinding(
            **{
                **binding.model_dump(),
                "binding_sha256": "0" * 64,
            }
        )
    with pytest.raises(ValidationError, match="external_object_id must be a UUID"):
        _binding(external_object_id="om-entity-parcels")

    gravitino = _binding(
        system="gravitino",
        binding_kind="technical_object",
        external_object_id="catalog.schema.parcels",
    )
    assert gravitino.external_object_id == "catalog.schema.parcels"


def test_gravitino_reference_round_trips_to_technical_binding():
    resource_version = _version(RESOURCE_URN, SOURCE_VERSION_ID, "a")
    reference = build_gravitino_reference(
        resource_version,
        metalake="gda-prod",
        catalog="iceberg",
        namespace="transportation",
        object_name="parcels",
        object_type="table",
        object_version_ref="snapshot-42",
    )

    binding = reference.to_metadata_binding(
        binding_id=UUID("20000000-0000-4000-8000-000000000009"),
        created_by=ACTOR,
        created_at=NOW,
    )
    assert binding.external_namespace == "gda-prod/iceberg/transportation"
    assert binding.external_object_id == "parcels"
    restored = gravitino_reference_from_binding(
        binding,
        resource_version=resource_version,
    )
    assert restored == reference
    assert restored.schema_version == GRAVITINO_REFERENCE_SCHEMA

    with pytest.raises(ValueError, match="ResourceVersion identity"):
        gravitino_reference_from_binding(
            binding,
            resource_version=_version(TARGET_URN, TARGET_VERSION_ID, "b"),
        )


def test_gravitino_reference_rejects_namespace_and_fingerprint_drift():
    with pytest.raises(ValidationError, match="canonical names"):
        GravitinoTechnicalObjectReference(
            tenant_id=TENANT,
            resource_urn=RESOURCE_URN,
            resource_version_id=SOURCE_VERSION_ID,
            metalake="gda/prod",
            catalog="iceberg",
            namespace="transportation",
            object_name="parcels",
            object_type="table",
            object_version_ref="snapshot-42",
            reference_sha256="0" * 64,
        )

    reference = GravitinoTechnicalObjectReference(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=SOURCE_VERSION_ID,
        metalake="gda-prod",
        catalog="iceberg",
        namespace="transportation",
        object_name="parcels",
        object_type="table",
        object_version_ref="snapshot-42",
        reference_sha256=gravitino_reference_fingerprint(
            tenant_id=TENANT,
            resource_urn=RESOURCE_URN,
            resource_version_id=SOURCE_VERSION_ID,
            metalake="gda-prod",
            catalog="iceberg",
            namespace="transportation",
            object_name="parcels",
            object_type="table",
            object_version_ref="snapshot-42",
        ),
    )
    with pytest.raises(ValidationError, match="reference_sha256"):
        GravitinoTechnicalObjectReference(
            **{**reference.model_dump(), "object_name": "other"}
        )


def test_gravitino_architecture_observation_projects_present_state_deterministically():
    resource_version = _version(RESOURCE_URN, SOURCE_VERSION_ID, "a")
    reference = build_gravitino_reference(
        resource_version,
        metalake="gda-prod",
        catalog="iceberg",
        namespace="transportation",
        object_name="parcels",
        object_type="table",
        object_version_ref="snapshot-42",
    )
    values = {
        "source_revision": "snapshot-42",
        "schema_content_sha256": "b" * 64,
        "schema_version_sha256": "c" * 64,
        "physical_location_sha256": "d" * 64,
        "observed_at": NOW,
        "fresh_until": NOW + timedelta(minutes=5),
        "observed_by": "workload:gravitino-harvester",
        "recorded_at": NOW + timedelta(seconds=1),
    }
    observation = build_gravitino_architecture_observation(reference, **values)
    replay = build_gravitino_architecture_observation(reference, **values)

    assert observation.provider_system == "gravitino"
    assert observation.provider_namespace == "gda-prod/iceberg/transportation"
    assert observation.provider_object_id == "parcels"
    assert observation.object_state == ProviderObjectState.PRESENT
    assert observation.source_revision == "snapshot-42"
    assert observation.observation_id == replay.observation_id
    assert observation.observation_sha256 == replay.observation_sha256
    assert observation.observation_id != build_gravitino_architecture_observation(
        reference,
        **(values | {"fresh_until": NOW + timedelta(minutes=6)})
    ).observation_id


def test_gravitino_architecture_tombstone_cannot_carry_current_fingerprints():
    resource_version = _version(RESOURCE_URN, SOURCE_VERSION_ID, "a")
    reference = build_gravitino_reference(
        resource_version,
        metalake="gda-prod",
        catalog="iceberg",
        namespace="transportation",
        object_name="parcels",
        object_type="table",
        object_version_ref="snapshot-42",
    )
    tombstone = build_gravitino_architecture_observation(
        reference,
        source_revision=None,
        schema_content_sha256=None,
        schema_version_sha256=None,
        physical_location_sha256=None,
        observed_at=NOW,
        fresh_until=NOW + timedelta(minutes=5),
        observed_by="workload:gravitino-harvester",
        recorded_at=NOW,
        object_state=ProviderObjectState.TOMBSTONED,
    )
    assert tombstone.object_state == ProviderObjectState.TOMBSTONED
    assert tombstone.source_revision is None
    assert tombstone.schema_content_sha256 is None

    with pytest.raises(ValidationError, match="tombstone observation"):
        build_gravitino_architecture_observation(
            reference,
            source_revision="snapshot-41",
            schema_content_sha256="b" * 64,
            schema_version_sha256="c" * 64,
            physical_location_sha256="d" * 64,
            observed_at=NOW,
            fresh_until=NOW + timedelta(minutes=5),
            observed_by="workload:gravitino-harvester",
            recorded_at=NOW,
            object_state="tombstoned",
        )


def test_metadata_lineage_projection_binds_hash_versions_and_openmetadata_entities():
    source = _version(RESOURCE_URN, SOURCE_VERSION_ID, "a")
    target = _version(TARGET_URN, TARGET_VERSION_ID, "b")
    envelope = MetadataLineageProjectionEnvelope(
        change=_change(),
        lineage_event=_lineage(),
        source_resource_version=source,
        target_resource_version=target,
        source_binding=_binding(),
        target_binding=_binding(
            binding_id=TARGET_BINDING_ID,
            resource_urn=TARGET_URN,
            external_object_id=TARGET_OPENMETADATA_ID,
        ),
    )
    assert envelope.source_binding.resource_urn == RESOURCE_URN
    assert envelope.target_binding.resource_urn == TARGET_URN

    with pytest.raises(ValidationError, match="payload hash"):
        MetadataLineageProjectionEnvelope(
            **{
                **envelope.model_dump(),
                "change": _change().model_copy(update={"payload_sha256": "0" * 64}),
            }
        )


def test_metadata_fabric_binding_routes_are_tenant_scoped_and_idempotent():
    binding = _binding()
    gateway = MagicMock()
    gateway.register_metadata_fabric_binding.return_value = GatewayWriteResult(
        binding,
        True,
    )
    create_request = _request(body=binding.model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        created = asyncio.run(routes.create_metadata_fabric_binding(create_request))

    assert created.status_code == 201
    assert json.loads(created.body)["created"] is True
    gateway.register_metadata_fabric_binding.assert_called_once_with(binding)

    gateway.list_metadata_fabric_bindings.return_value = (binding,)
    list_request = _request(
        query={"resource_urn": RESOURCE_URN, "system": "openmetadata"}
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        listed = asyncio.run(routes.list_metadata_fabric_bindings(list_request))
    body = json.loads(listed.body)
    assert listed.status_code == 200
    assert body["data"]["count"] == 1
    assert gateway.list_metadata_fabric_bindings.call_args.args == (
        TENANT,
        RESOURCE_URN,
    )
    assert gateway.list_metadata_fabric_bindings.call_args.kwargs["system"].value == (
        "openmetadata"
    )


def test_metadata_fabric_routes_reject_actor_and_urn_tenant_mismatch():
    binding = _binding()
    gateway = MagicMock()
    actor_mismatch = _request(
        body={**binding.model_dump(mode="json"), "created_by": "human:someone-else"}
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        rejected = asyncio.run(routes.create_metadata_fabric_binding(actor_mismatch))
    assert rejected.status_code == 403
    assert json.loads(rejected.body)["error"]["code"] == "actor_mismatch"

    tenant_mismatch = _request(query={"resource_urn": RESOURCE_URN})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(tenant_id="tenant-b"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        rejected = asyncio.run(routes.list_metadata_fabric_bindings(tenant_mismatch))
    assert rejected.status_code == 403
    assert json.loads(rejected.body)["error"]["code"] == "tenant_mismatch"
    gateway.list_metadata_fabric_bindings.assert_not_called()


def test_metadata_fabric_search_route_is_tenant_scoped_and_paginated():
    binding = _binding()
    gateway = MagicMock()
    gateway.search_metadata_fabric_bindings.return_value = MetadataFabricBindingPage(
        items=(binding,),
        offset=5,
        limit=10,
        has_more=True,
    )
    request = _request(
        query={
            "q": "parcels",
            "system": "openmetadata",
            "limit": "10",
            "offset": "5",
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.search_metadata_fabric_bindings(request))

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["data"]["count"] == 1
    assert body["data"]["offset"] == 5
    assert body["data"]["limit"] == 10
    assert body["data"]["has_more"] is True
    assert gateway.search_metadata_fabric_bindings.call_args.args == (TENANT,)
    assert gateway.search_metadata_fabric_bindings.call_args.kwargs == {
        "query": "parcels",
        "system": "openmetadata",
        "limit": 10,
        "offset": 5,
    }


def test_metadata_fabric_search_route_rejects_unbounded_query():
    request = _request(query={"q": "x" * 129})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.search_metadata_fabric_bindings(request))
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == (
        "invalid_metadata_fabric_search_query"
    )


def test_metadata_provider_read_route_returns_typed_provider_observation():
    binding = _binding()
    gateway = MagicMock()
    gateway.list_metadata_fabric_bindings.return_value = (binding,)
    result = ProviderReadResult(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        binding_id=str(binding.binding_id),
        system="openmetadata",
        external_namespace=binding.external_namespace,
        external_object_id=binding.external_object_id,
        external_object_type=binding.external_object_type,
        status="present",
        provider_revision="7.2",
        provider_fingerprint="a" * 64,
        observed_at=NOW,
        evidence={"fullyQualifiedName": "iceberg_prod.parcels"},
    )
    request = _request(
        query={"resource_urn": RESOURCE_URN, "system": "openmetadata"}
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_read_metadata_provider_binding", return_value=result),
    ):
        response = asyncio.run(routes.read_metadata_fabric_provider_binding(request))

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["data"]["result"]["status"] == "present"
    assert body["data"]["result"]["provider_fingerprint"] == "a" * 64
    gateway.list_metadata_fabric_bindings.assert_called_once_with(
        TENANT, RESOURCE_URN, system="openmetadata"
    )


def test_metadata_provider_search_route_requires_bound_namespace_and_returns_page():
    binding = _binding(
        system="gravitino",
        binding_kind="technical_object",
        external_object_id="parcels",
    )
    gateway = MagicMock()
    gateway.search_metadata_fabric_bindings.return_value = MetadataFabricBindingPage(
        items=(binding,), offset=0, limit=100, has_more=False
    )
    page = ProviderSearchPage(
        tenant_id=TENANT,
        provider_namespace=binding.external_namespace,
        object_type="table",
        query="parcel",
        items=(
            ProviderSearchItem(
                tenant_id=TENANT,
                provider_namespace=binding.external_namespace,
                external_object_id="parcels",
                external_object_type="table",
                candidate_sha256=provider_search_candidate_fingerprint(
                    tenant_id=TENANT,
                    provider_namespace=binding.external_namespace,
                    external_object_id="parcels",
                    external_object_type="table",
                ),
                evidence={"name": "parcels"},
            ),
        ),
        count=1,
        offset=0,
        limit=50,
        has_more=False,
        observed_at=NOW,
    )
    request = _request(
        query={
            "provider_namespace": binding.external_namespace,
            "system": "gravitino",
            "q": "parcel",
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_search_metadata_provider", return_value=page),
    ):
        response = asyncio.run(routes.search_metadata_fabric_provider(request))

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["data"]["page"]["items"][0]["external_object_id"] == "parcels"
    gateway.search_metadata_fabric_bindings.assert_called_once_with(
        TENANT,
        query=binding.external_namespace,
        system="gravitino",
        limit=100,
        offset=0,
    )


def test_openmetadata_provider_search_route_requires_query_and_returns_bound_page():
    binding = _binding()
    page = ProviderSearchPage(
        tenant_id=TENANT,
        system="openmetadata",
        provider_namespace=binding.external_namespace,
        object_type="table",
        query="parcel",
        items=(
            ProviderSearchItem(
                tenant_id=TENANT,
                system="openmetadata",
                provider_namespace=binding.external_namespace,
                external_object_id=binding.external_object_id,
                external_object_type="table",
                candidate_sha256=provider_search_candidate_fingerprint(
                    tenant_id=TENANT,
                    provider_namespace=binding.external_namespace,
                    external_object_id=binding.external_object_id,
                    external_object_type="table",
                    system="openmetadata",
                ),
                evidence={"name": "parcels"},
            ),
        ),
        count=1,
        offset=0,
        limit=50,
        has_more=False,
        observed_at=NOW,
    )
    request = _request(
        query={
            "provider_namespace": binding.external_namespace,
            "system": "openmetadata",
            "q": "parcel",
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_metadata_provider_namespace_is_bound", return_value=True),
        patch.object(routes, "_search_metadata_provider", return_value=page),
    ):
        response = asyncio.run(routes.search_metadata_fabric_provider(request))

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["data"]["page"]["system"] == "openmetadata"
    assert body["data"]["page"]["items"][0]["external_object_id"] == binding.external_object_id


def test_openmetadata_provider_search_route_rejects_missing_query():
    request = _request(
        query={
            "provider_namespace": "service:iceberg-prod",
            "system": "openmetadata",
        }
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.search_metadata_fabric_provider(request))

    assert response.status_code == 400
    body = json.loads(response.body)
    assert body["error"]["code"] == "invalid_metadata_provider_search_query"
