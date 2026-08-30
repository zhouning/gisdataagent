from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api.map_publication_routes import get_map_publication_routes
from data_agent.map_publications import (
    MapPublicationForbidden,
    MapPublicationMaterializationRequired,
)


class _User:
    identifier = "alice"
    metadata = {"role": "analyst", "tenant_id": "local-dev"}


def _client() -> TestClient:
    return TestClient(Starlette(routes=get_map_publication_routes()))


def _route_methods(route_list, path: str) -> set[str]:
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def _auth_patches():
    return (
        patch(
            "data_agent.api.map_publication_routes._get_user_from_request",
            return_value=_User(),
        ),
        patch(
            "data_agent.api.map_publication_routes._set_user_context",
            return_value=("alice", "analyst"),
        ),
    )


def test_unauthenticated_map_publication_request_is_rejected():
    with patch(
        "data_agent.api.map_publication_routes._get_user_from_request",
        return_value=None,
    ):
        response = _client().get("/api/catalog/7/map-publications/current")

    assert response.status_code == 401


def test_publish_maps_forbidden_and_materialization_errors():
    for exception, expected_status, expected_code in [
        (MapPublicationForbidden("owner required"), 403, None),
        (
            MapPublicationMaterializationRequired("projection required"),
            409,
            "serving_projection_required",
        ),
    ]:
        service = MagicMock()
        service.publish.side_effect = exception
        auth, context = _auth_patches()
        with (
            auth,
            context,
            patch(
                "data_agent.api.map_publication_routes._service",
                return_value=service,
            ),
        ):
            response = _client().post("/api/catalog/7/map-publications", json={})

        assert response.status_code == expected_status
        if expected_code:
            assert response.json()["code"] == expected_code


def test_tile_coordinate_is_validated_before_service_lookup():
    service = MagicMock()
    auth, context = _auth_patches()
    publication_id = uuid4()
    with (
        auth,
        context,
        patch(
            "data_agent.api.map_publication_routes._service",
            return_value=service,
        ),
    ):
        response = _client().get(
            f"/api/map-publications/{publication_id}/tiles/1/2/0.pbf"
        )

    assert response.status_code == 400
    service.get.assert_not_called()


def test_tile_proxy_returns_503_when_martin_is_unavailable():
    service = MagicMock()
    service.get.return_value = {"status": "ready", "min_zoom": 0, "max_zoom": 20}
    auth, context = _auth_patches()
    publication_id = uuid4()
    with (
        auth,
        context,
        patch(
            "data_agent.api.map_publication_routes._service",
            return_value=service,
        ),
        patch(
            "data_agent.api.map_publication_routes._fetch_martin_tile",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ),
    ):
        response = _client().get(
            f"/api/map-publications/{publication_id}/tiles/1/1/1.pbf"
        )

    assert response.status_code == 503


def test_map_publication_routes_are_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = get_map_publication_routes()
    frontend_routes = get_frontend_api_routes()
    create_path = "/api/catalog/{asset_id:int}/map-publications"
    tile_path = (
        "/api/map-publications/{publication_id:uuid}/tiles/"
        "{z:int}/{x:int}/{y:int}.pbf"
    )

    assert "POST" in _route_methods(route_list, create_path)
    assert "POST" in _route_methods(frontend_routes, create_path)
    assert "GET" in _route_methods(route_list, tile_path)
    assert "GET" in _route_methods(frontend_routes, tile_path)

