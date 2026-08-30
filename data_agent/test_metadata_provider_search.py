from pathlib import Path

import httpx
import pytest

from data_agent.metadata_provider_read import MetadataProviderReadError
from data_agent.metadata_provider_search import (
    GravitinoMetadataProviderSearchClient,
    MetadataProviderSearchService,
    OpenMetadataMetadataProviderSearchClient,
)


def test_gravitino_search_is_namespace_bound_deterministic_and_paginated() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "identifiers": [
                    {"name": "parcel_z", "namespace": ["m", "c", "n"]},
                    {"name": "parcel_a", "namespace": ["m", "c", "n"]},
                    {"name": "roads", "namespace": ["m", "c", "n"]},
                    {"name": "parcel_wrong", "namespace": ["m", "c", "other"]},
                    {"name": "invalid/name", "namespace": ["m", "c", "n"]},
                ],
            },
        )

    with GravitinoMetadataProviderSearchClient(
        "http://gravitino.internal",
        transport=httpx.MockTransport(handler),
    ) as client:
        page = client.search(
            "tenant-a",
            provider_namespace="m/c/n",
            query="parcel",
            limit=1,
            offset=1,
        )

    assert requests[0].url.path == "/api/metalakes/m/catalogs/c/schemas/n/tables"
    assert requests[0].headers["accept"] == "*/*"
    assert [item.external_object_id for item in page.items] == ["parcel_z"]
    assert page.count == 1
    assert page.offset == 1
    assert page.has_more is False
    assert page.items[0].evidence == {"name": "parcel_z", "namespace": ["m", "c", "n"]}


def test_gravitino_search_rejects_unbounded_provider_response() -> None:
    with GravitinoMetadataProviderSearchClient(
        "http://gravitino.internal",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"x" * (512 * 1024 + 1))
        ),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="exceeds the bounded contract"):
            client.search("tenant-a", provider_namespace="m/c/n")


def test_gravitino_search_rejects_invalid_namespace_and_object_type() -> None:
    with GravitinoMetadataProviderSearchClient(
        "http://gravitino.internal",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"code": 0})),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="metalake/catalog/namespace"):
            client.search("tenant-a", provider_namespace="m/c")
        with pytest.raises(MetadataProviderReadError, match="object type"):
            client.search("tenant-a", provider_namespace="m/c/n", object_type="unknown")


def test_openmetadata_search_is_service_bound_and_returns_identity_candidates(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "provider-token"
    token_path.write_text("provider-token\n", encoding="utf-8")
    requests: list[httpx.Request] = []
    table_id = "60000000-0000-4000-8000-000000000001"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "hits": {
                    "total": {"value": 3, "relation": "eq"},
                    "hits": [
                        {
                            "_id": table_id,
                            "_source": {
                                "id": table_id,
                                "name": "parcels",
                                "fullyQualifiedName": "iceberg_prod.parcels",
                                "service": {"name": "iceberg_prod"},
                            },
                        },
                        {
                            "_id": "70000000-0000-4000-8000-000000000001",
                            "_source": {
                                "id": "70000000-0000-4000-8000-000000000001",
                                "name": "parcels-other-service",
                                "fullyQualifiedName": "other.parcels-other-service",
                                "service": {"name": "other"},
                            },
                        },
                        {
                            "_id": "not-a-uuid",
                            "_source": {
                                "id": "not-a-uuid",
                                "name": "parcels-invalid",
                                "service": {"name": "iceberg_prod"},
                            },
                        },
                    ],
                }
            },
        )

    with OpenMetadataMetadataProviderSearchClient(
        "https://metadata.internal",
        bearer_token_file=token_path,
        transport=httpx.MockTransport(handler),
    ) as client:
        page = client.search(
            "tenant-a",
            provider_namespace="service:iceberg_prod",
            query="parcel",
            limit=10,
        )

    assert requests[0].url.path == "/api/v1/search/query"
    assert requests[0].url.params["q"] == "parcel"
    assert requests[0].url.params["index"] == "table_search_index"
    assert requests[0].url.params["from"] == "0"
    assert requests[0].url.params["size"] == "10"
    assert requests[0].headers["authorization"] == "Bearer provider-token"
    assert [item.external_object_id for item in page.items] == [table_id]
    assert page.items[0].evidence == {
        "name": "parcels",
        "fullyQualifiedName": "iceberg_prod.parcels",
        "namespace": "service:iceberg_prod",
    }
    assert page.has_more is False


def test_openmetadata_search_rejects_unbounded_or_unscoped_queries(tmp_path: Path) -> None:
    token_path = tmp_path / "provider-token"
    token_path.write_text("provider-token", encoding="utf-8")
    with OpenMetadataMetadataProviderSearchClient(
        "https://metadata.internal",
        bearer_token_file=token_path,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
    ) as client:
        with pytest.raises(MetadataProviderReadError, match="requires a query"):
            client.search("tenant-a", provider_namespace="service:iceberg_prod")
        with pytest.raises(MetadataProviderReadError, match="service:<name>"):
            client.search(
                "tenant-a",
                provider_namespace="iceberg_prod",
                query="parcel",
            )


def test_search_service_is_explicitly_unavailable_without_gravitino(monkeypatch) -> None:
    monkeypatch.delenv("GDA_GRAVITINO_URL", raising=False)
    monkeypatch.delenv("GDA_OPENMETADATA_URL", raising=False)
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", raising=False)
    with MetadataProviderSearchService.from_env() as service:
        with pytest.raises(MetadataProviderReadError, match="adapter is configured"):
            service.search("tenant-a", provider_namespace="m/c/n")


def test_search_service_dispatches_openmetadata_without_gravitino(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "provider-token"
    token_path.write_text("provider-token", encoding="utf-8")
    table_id = "60000000-0000-4000-8000-000000000001"
    monkeypatch.delenv("GDA_GRAVITINO_URL", raising=False)
    monkeypatch.setenv("GDA_OPENMETADATA_URL", "https://metadata.internal")
    monkeypatch.setenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", str(token_path))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "hits": {
                    "total": 1,
                    "hits": [
                        {
                            "_id": table_id,
                            "_source": {
                                "id": table_id,
                                "name": "parcels",
                                "fullyQualifiedName": "iceberg_prod.parcels",
                                "service": {"name": "iceberg_prod"},
                            },
                        }
                    ],
                }
            },
        )

    with MetadataProviderSearchService.from_env(
        transport=httpx.MockTransport(handler)
    ) as service:
        page = service.search(
            "tenant-a",
            system="openmetadata",
            provider_namespace="service:iceberg_prod",
            query="parcel",
        )

    assert page.system.value == "openmetadata"
    assert page.items[0].external_object_id == table_id
