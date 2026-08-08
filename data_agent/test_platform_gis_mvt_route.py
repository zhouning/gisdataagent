from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from data_agent.api import platform_gateway_routes as routes
from data_agent.gis_provider_runtime import ProviderTileResponse
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    GISServiceType,
    ServiceDeploymentState,
)
from data_agent.test_gis_provider_runtime import _release_and_tms

SERVICE_URN = "gda://planning/gis_service/district-features"


class _User:
    identifier = "operator"
    metadata = {"role": "platform_operator", "tenant_id": "planning"}


def _client() -> TestClient:
    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())
    return TestClient(app)


def _projection(*, release_key: str = "v1.0.0", endpoint_contract: dict | None = None):
    release, tile_matrix_set = _release_and_tms()
    if release_key != release.release_key:
        release = release.model_copy(update={"release_key": release_key})
    endpoint = SimpleNamespace(
        endpoint_protocol=EndpointProtocol.MVT,
        endpoint_uri="https://martin.example.test",
        endpoint_contract=endpoint_contract
        or {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "map_publication",
            "provider_query": {"publication_id": "00000000-0000-4000-8000-000000000421"},
        },
    )
    deployment = SimpleNamespace(
        provider_system="martin",
        state=ServiceDeploymentState.READY,
    )
    definition = SimpleNamespace(service_type=GISServiceType.VECTOR_TILE)
    return SimpleNamespace(
        endpoint_state_version=4,
        active_endpoint_revision=endpoint,
        active_deployment_revision=deployment,
        active_service_definition_version=definition,
        active_release_binding=release,
        active_tile_matrix_set_definition_version=tile_matrix_set,
    )


def _route_request(path: str, *, projection=None, provider=None):
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = projection or _projection()
    provider = provider or MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_User()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", return_value=provider),
    ):
        return _client().get(path, params={"service_urn": SERVICE_URN}), provider


def test_governed_mvt_route_requires_authentication():
    with patch.object(routes, "_get_user_from_request", return_value=None):
        response = _client().get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": SERVICE_URN},
        )

    assert response.status_code == 401


def test_governed_mvt_route_rejects_non_active_release_without_provider_call():
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v9.9.9/0/0/0.pbf"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "active_release_mismatch"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_invalid_coordinate_before_provider_call():
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/3/0/0.pbf"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_tile_coordinate"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_unbound_publication_contract():
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=_projection(
            endpoint_contract={
                "schema": "gda.mvt_endpoint.v1",
                "provider_layer_ref": "map_publication",
                "provider_query": {},
            }
        ),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_mvt_endpoint_contract"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_reads_active_release_and_stamps_version_headers():
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"mvt-bytes",
            status_code=200,
            media_type="application/x-protobuf",
            etag='"revision-1"',
        )
    )
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf", provider=provider
    )

    assert response.status_code == 200
    assert response.content == b"mvt-bytes"
    assert response.headers["etag"] == '"revision-1"'
    assert response.headers["x-gda-service-release"] == "v1.0.0"
    assert response.headers["x-gda-endpoint-state-version"] == "4"
    assert response.headers["cache-control"] == "private, no-store"
    context = provider.fetch_tile.await_args.args[0]
    assert context.provider_layer_ref == "map_publication"
    assert context.provider_query["publication_id"]
