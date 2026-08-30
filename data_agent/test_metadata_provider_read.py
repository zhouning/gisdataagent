import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from data_agent.metadata_fabric import MetadataFabricBinding, metadata_fabric_binding_fingerprint
from data_agent.metadata_provider_read import (
    GravitinoMetadataProviderReadClient,
    MetadataProviderReadError,
    OpenMetadataProviderReadClient,
    ProviderReadStatus,
)
from data_agent.platform_contracts import canonical_json_fingerprint

TENANT = "tenant-a"
RESOURCE_URN = "gda://tenant-a/dataset/parcels"
OPEN_ID = "60000000-0000-4000-8000-000000000001"
BINDING_ID = UUID("60000000-0000-4000-8000-000000000002")


def _binding(
    *,
    system: str,
    namespace: str,
    object_id: str,
    object_type: str,
    version_ref: str,
) -> MetadataFabricBinding:
    values = {
        "tenant_id": TENANT,
        "binding_id": BINDING_ID,
        "resource_urn": RESOURCE_URN,
        "system": system,
        "binding_kind": "governance_entity"
        if system == "openmetadata"
        else "technical_object",
        "external_namespace": namespace,
        "external_object_id": object_id,
        "external_object_type": object_type,
        "external_version_ref": version_ref,
        "created_by": "human:metadata-operator",
        "created_at": "2026-08-18T00:00:00Z",
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


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "provider-token"
    path.write_text("provider-token\n", encoding="utf-8")
    return path


def test_gravitino_read_is_namespace_bound_and_returns_bounded_evidence() -> None:
    table = {
        "name": "parcels",
        "columns": [{"name": "parcel_id", "type": "integer"}],
        "properties": {
            "provider": "iceberg",
            "format": "parquet",
            "format-version": "2",
            "location": "s3://warehouse/parcels",
            "current-snapshot-id": "42",
            "secret": "must-not-leak",
        },
        "audit": {"createTime": "2026-08-18T00:00:00Z", "creator": "anonymous"},
        "owner": {"name": "should-not-be-returned"},
    }
    stable_table = dict(table)
    stable_table.pop("audit")
    fingerprint = canonical_json_fingerprint(stable_table)
    binding = _binding(
        system="gravitino",
        namespace="gda_acceptance/iceberg/transportation",
        object_id="parcels",
        object_type="table",
        version_ref=f"metadata-sha256:{fingerprint}",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "table": table})

    with GravitinoMetadataProviderReadClient(
        "http://gravitino.internal",
        bearer_token_file=None,
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.read(binding)

    assert requests[0].url.path == (
        "/api/metalakes/gda_acceptance/catalogs/iceberg/schemas/transportation/tables/parcels"
    )
    assert "Authorization" not in requests[0].headers
    assert result.status is ProviderReadStatus.PRESENT
    assert result.provider_fingerprint == fingerprint
    assert result.evidence["properties"]["current-snapshot-id"] == "42"
    assert "secret" not in json.dumps(result.evidence)
    assert "owner" not in json.dumps(result.evidence)


def test_gravitino_read_preserves_explicit_not_found() -> None:
    binding = _binding(
        system="gravitino",
        namespace="metalake/catalog/schema",
        object_id="missing",
        object_type="table",
        version_ref="metadata-sha256:" + "a" * 64,
    )
    with GravitinoMetadataProviderReadClient(
        "http://gravitino.internal",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    ) as client:
        result = client.read(binding)

    assert result.status is ProviderReadStatus.NOT_FOUND
    assert result.provider_fingerprint is None
    assert result.evidence == {}


def test_gravitino_read_rejects_provider_version_drift() -> None:
    table = {"name": "parcels", "properties": {"provider": "iceberg"}}
    binding = _binding(
        system="gravitino",
        namespace="metalake/catalog/schema",
        object_id="parcels",
        object_type="table",
        version_ref="metadata-sha256:" + "b" * 64,
    )
    with GravitinoMetadataProviderReadClient(
        "http://gravitino.internal",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"code": 0, "table": table})
        ),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="fingerprint differs"):
            client.read(binding)


def test_openmetadata_read_uses_bearer_auth_and_root_entity_projection(tmp_path: Path) -> None:
    binding = _binding(
        system="openmetadata",
        namespace="service:iceberg-prod",
        object_id=OPEN_ID,
        object_type="table",
        version_ref="1.13.1",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": OPEN_ID,
                "fullyQualifiedName": "iceberg_prod.parcels",
                "version": "7.2",
                "updatedAt": 1720000000000,
                "owner": {"name": "not returned"},
            },
        )

    with OpenMetadataProviderReadClient(
        "https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.read(binding)

    assert requests[0].url.path == f"/api/v1/tables/{OPEN_ID}"
    assert requests[0].headers["authorization"] == "Bearer provider-token"
    assert result.provider_revision == "7.2"
    assert result.evidence["fullyQualifiedName"] == "iceberg_prod.parcels"
    assert "owner" not in result.evidence


def test_openmetadata_read_rejects_redirects_and_wrong_identity(tmp_path: Path) -> None:
    binding = _binding(
        system="openmetadata",
        namespace="service:iceberg-prod",
        object_id=OPEN_ID,
        object_type="table",
        version_ref="1.13.1",
    )
    with OpenMetadataProviderReadClient(
        "https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"id": "70000000-0000-4000-8000-000000000001"},
            )
        ),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="wrong object"):
            client.read(binding)


def test_provider_read_rejects_unbounded_selected_evidence(tmp_path: Path) -> None:
    binding = _binding(
        system="openmetadata",
        namespace="service:iceberg-prod",
        object_id=OPEN_ID,
        object_type="table",
        version_ref="1.13.1",
    )
    with OpenMetadataProviderReadClient(
        "https://metadata.internal",
        bearer_token_file=_token_file(tmp_path),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"id": OPEN_ID, "description": "x" * 17_000},
            )
        ),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="bounded contract"):
            client.read(binding)
