"""HTTP regression tests for retired generic Martin route shims."""

from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import tile_routes


def _client() -> TestClient:
    return TestClient(Starlette(routes=tile_routes.get_tile_routes()))


@pytest.mark.parametrize(
    "path",
    [
        "/api/tiles/martin/arbitrary_catalog_entry/0/0/0.pbf",
        "/api/tiles/martin/catalog",
    ],
)
def test_retired_martin_routes_require_authentication(monkeypatch, path: str):
    monkeypatch.setattr(tile_routes, "_get_user_from_request", lambda request: None)

    response = _client().get(path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/tiles/martin/arbitrary_catalog_entry/0/0/0.pbf",
        "/api/tiles/martin/catalog",
    ],
)
def test_retired_martin_routes_never_initialize_a_provider_client(monkeypatch, path: str):
    monkeypatch.setattr(tile_routes, "_get_user_from_request", lambda request: object())
    monkeypatch.setattr(tile_routes, "_set_user_context", lambda user: ("alice", "analyst"))
    monkeypatch.setattr(tile_routes, "MARTIN_URL", "http://provider.invalid", raising=False)

    with patch("httpx.AsyncClient") as provider_client:
        response = _client().get(path)

    assert response.status_code == 410
    assert response.json() == {
        "error": "Legacy Martin table proxy is retired",
        "code": "legacy_martin_proxy_retired",
        "replacement": "/api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    provider_client.assert_not_called()
