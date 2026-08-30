from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from data_agent.api import platform_gateway_routes as routes
from data_agent.gis_mvt_access import MVTAccessDeniedError
from data_agent.gis_mvt_response_cache import DisabledMVTResponseCache
from data_agent.gis_provider_runtime import ProviderTileResponse
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    GISServiceType,
    MVTServingProjectionVersion,
    ServiceDeploymentState,
    ServiceReleaseBinding,
    mvt_serving_projection_fingerprint,
    service_release_binding_fingerprint,
)
from data_agent.test_gis_provider_runtime import _release_and_tms

SERVICE_URN = "gda://planning/gis_service/district-features"


class _User:
    identifier = "operator"
    metadata = {"role": "platform_operator", "tenant_id": "planning"}


class _ConsumerUser:
    identifier = "analyst-01"
    metadata = {
        "role": "analyst",
        "tenant_id": "planning",
        "subject_type": "human",
    }


def _client() -> TestClient:
    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())
    return TestClient(app)


def _access_service():
    service = MagicMock()
    service.admit.return_value = SimpleNamespace(
        decision=SimpleNamespace(decision_sha256="a" * 64)
    )
    return service


def _projection(*, release_key: str = "v1.0.0", endpoint_contract: dict | None = None):
    release, tile_matrix_set, serving_projection = _release_and_tms()
    cache_policy_id = uuid4()
    release_values = release.model_dump(mode="python", exclude={"binding_sha256"})
    release_values["cache_policy_version_id"] = cache_policy_id
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    if release_key != release.release_key:
        release_values = release.model_dump(mode="python", exclude={"binding_sha256"})
        release_values["release_key"] = release_key
        release = ServiceReleaseBinding(
            **release_values,
            binding_sha256=service_release_binding_fingerprint(release_values),
        )
    endpoint = SimpleNamespace(
        endpoint_revision_id=uuid4(),
        endpoint_protocol=EndpointProtocol.MVT,
        endpoint_uri="https://martin.example.test",
        endpoint_contract=endpoint_contract
        or {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": {
                "serving_projection_version_id": str(
                    serving_projection.mvt_serving_projection_version_id
                )
            },
        },
        endpoint_sha256="b" * 64,
    )
    deployment = SimpleNamespace(
        provider_system="martin",
        state=ServiceDeploymentState.READY,
    )
    definition = SimpleNamespace(
        service_type=GISServiceType.VECTOR_TILE,
        service_definition_version_id=release.service_definition_version_id,
        source_product_urn="gda://planning/data_product/district-features",
        source_data_product_version_id=UUID("00000000-0000-4000-8000-000000000422"),
    )
    cache_policy = SimpleNamespace(
        cache_policy_version_id=cache_policy_id,
        cache_namespace="district-features",
        cache_max_age_seconds=60,
        policy_sha256="c" * 64,
    )
    service_policy = SimpleNamespace(
        service_policy_binding_id=uuid4(),
        allowed_roles=(
            "admin",
            "platform_operator",
            "viewer",
            "analyst",
            "standard_editor",
            "standard_reviewer",
        ),
        consumer_binding_required_roles=(
            "viewer",
            "analyst",
            "standard_editor",
            "standard_reviewer",
        ),
        required_consumer_operation="read",
        policy_sha256="d" * 64,
        version_key="v1.0.0",
    )
    return SimpleNamespace(
        endpoint_state_version=4,
        active_endpoint_revision=endpoint,
        active_deployment_revision=deployment,
        active_service_definition_version=definition,
        active_release_binding=release,
        active_tile_matrix_set_definition_version=tile_matrix_set,
        active_cache_policy_version=cache_policy,
        active_service_policy_binding=service_policy,
        active_mvt_serving_projection_version=serving_projection,
    )


def _route_request(
    path: str,
    *,
    projection=None,
    provider=None,
    access_service=None,
    response_cache=None,
    headers=None,
):
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = projection or _projection()
    provider = provider or MagicMock()
    access_service = access_service or _access_service()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_User()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_mvt_access_service", return_value=access_service),
        patch.object(
            routes,
            "_mvt_response_cache",
            return_value=response_cache or DisabledMVTResponseCache(),
        ),
        patch.object(routes, "MartinVectorTileProvider", return_value=provider),
        patch.dict(routes.os.environ, {"MARTIN_URL": "http://martin:3000"}),
    ):
        return (
            _client().get(
                path,
                params={"service_urn": SERVICE_URN},
                headers=headers or {},
            ),
            provider,
        )


def _consumer_route_request(
    path: str,
    *,
    binding=None,
    projection=None,
    provider=None,
    access_service=None,
    response_cache=None,
):
    gateway = MagicMock()
    projection = projection or _projection()
    projection.active_service_definition_version = SimpleNamespace(
        service_type=GISServiceType.VECTOR_TILE,
        service_definition_version_id=(
            projection.active_release_binding.service_definition_version_id
        ),
        source_product_urn="gda://planning/data_product/district-features",
        source_data_product_version_id=UUID("00000000-0000-4000-8000-000000000422"),
    )
    gateway.get_gis_service_control_projection.return_value = projection
    gateway.get_active_service_consumer_binding_for_release.return_value = binding
    provider = provider or MagicMock()
    access_service = access_service or _access_service()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_ConsumerUser()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_mvt_access_service", return_value=access_service),
        patch.object(
            routes,
            "_mvt_response_cache",
            return_value=response_cache or DisabledMVTResponseCache(),
        ),
        patch.object(routes, "MartinVectorTileProvider", return_value=provider),
        patch.dict(routes.os.environ, {"MARTIN_URL": "http://martin:3000"}),
    ):
        return _client().get(path, params={"service_urn": SERVICE_URN}), provider, gateway


def test_governed_mvt_route_requires_authentication():
    with patch.object(routes, "_get_user_from_request", return_value=None):
        response = _client().get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": SERVICE_URN},
        )

    assert response.status_code == 401


def test_governed_mvt_route_uses_the_signed_cookie_principal_for_access_decision():
    from chainlit.auth.jwt import create_jwt
    from chainlit.user import User

    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"jwt-consumer-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = _projection()
    gateway.get_active_service_consumer_binding_for_release.return_value = SimpleNamespace(
        service_consumer_binding_id=uuid4(),
        binding_sha256="e" * 64,
        scope={"operations": ["read"]},
    )
    access_service = _access_service()
    user = User(
        identifier="analyst-01",
        metadata={
            "role": "analyst",
            "tenant_id": "planning",
            "subject_type": "human",
        },
    )
    with (
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_mvt_access_service", return_value=access_service),
        patch.object(routes, "MartinVectorTileProvider", return_value=provider),
        patch.dict(
            routes.os.environ,
            {
                "CHAINLIT_AUTH_SECRET": "mvt-route-test-secret-0123456789abcdef",
                "MARTIN_URL": "http://martin:3000",
            },
        ),
    ):
        token = create_jwt(user)
        client = _client()
        client.cookies.set("access_token", token)
        response = client.get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": SERVICE_URN},
            headers={"x-request-id": "mvt-jwt-request-1"},
        )

    assert response.status_code == 200
    subject = access_service.admit.call_args.kwargs["subject_context"]
    assert subject.subject_id == "analyst-01"
    assert subject.tenant_id == "planning"
    assert subject.roles == ("analyst",)
    assert subject.trace_id == "mvt-jwt-request-1"


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


def test_governed_mvt_route_rejects_unbound_serving_projection_contract():
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=_projection(
            endpoint_contract={
                "schema": "gda.mvt_endpoint.v1",
                "provider_layer_ref": "gda_mvt_serving_projection",
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
    assert response.headers["etag"] != '"revision-1"'
    assert response.headers["x-gda-service-release"] == "v1.0.0"
    assert response.headers["x-gda-endpoint-state-version"] == "4"
    assert response.headers["cache-control"] == "private, max-age=60, must-revalidate"
    assert response.headers["vary"] == "Authorization, Cookie, Accept-Encoding"
    assert response.headers["x-gda-cache-namespace"].startswith("district-features-")
    context = provider.fetch_tile.await_args.args[0]
    assert context.provider_layer_ref == "gda_mvt_serving_projection"
    assert context.provider_query["serving_projection_version_id"] == str(
        context.mvt_serving_projection_version_id
    )


def test_governed_mvt_route_uses_internal_martin_origin_not_public_endpoint():
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"mvt-bytes",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )
    provider_constructor = MagicMock(return_value=provider)
    projection = _projection()
    projection.active_endpoint_revision.endpoint_uri = "https://tiles.public.example.test"
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = projection
    with (
        patch.object(routes, "_get_user_from_request", return_value=_User()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_mvt_access_service", return_value=_access_service()),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
        patch.dict(routes.os.environ, {"MARTIN_URL": "http://martin:3000"}),
    ):
        response = _client().get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": SERVICE_URN},
        )

    assert response.status_code == 200
    assert provider_constructor.call_args.args[0] == "http://martin:3000"
    assert (
        provider_constructor.call_args.args[0]
        != projection.active_endpoint_revision.endpoint_uri
    )


def test_governed_mvt_route_rejects_missing_internal_martin_origin():
    provider_constructor = MagicMock()
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = _projection()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_User()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_mvt_access_service", return_value=_access_service()),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
        patch.dict(routes.os.environ, {}, clear=True),
    ):
        response = _client().get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": SERVICE_URN},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_configuration_error"
    provider_constructor.assert_not_called()


def test_governed_mvt_route_rejects_release_without_cache_policy_before_provider_call():
    projection = _projection()
    projection.active_cache_policy_version = None

    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cache_policy_required"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_release_without_service_policy_before_provider_call():
    projection = _projection()
    projection.active_service_policy_binding = None

    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "service_policy_required"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_release_without_serving_projection_before_provider_call():
    projection = _projection()
    projection.active_mvt_serving_projection_version = None

    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "serving_projection_required"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_endpoint_for_another_serving_projection():
    projection = _projection(
        endpoint_contract={
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": {
                "serving_projection_version_id": str(uuid4()),
            },
        }
    )

    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_mvt_endpoint_contract"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_enforces_active_service_policy_before_provider_call():
    projection = _projection()
    projection.active_service_policy_binding = SimpleNamespace(
        allowed_roles=("viewer",),
        consumer_binding_required_roles=("viewer",),
        required_consumer_operation="read",
    )

    access_service = _access_service()
    access_service.admit.side_effect = MVTAccessDeniedError(
        "service_policy_denied", "policy denied"
    )
    response, provider = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        access_service=access_service,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_policy_denied"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_cache_identity_is_stable_for_one_release_context():
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"stable-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag='"provider-revision"',
        )
    )

    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )

    assert first.headers["etag"] == second.headers["etag"]
    assert first.headers["x-gda-cache-namespace"] == second.headers[
        "x-gda-cache-namespace"
    ]
    assert len(first.headers["x-gda-cache-generation"]) == 64
    assert first.headers["x-gda-cache-generation"] == second.headers[
        "x-gda-cache-generation"
    ]


class _MemoryMVTResponseCache:
    enabled = True

    def __init__(self):
        self.entries = {}
        self.get_calls = []
        self.put_calls = []

    async def get(self, key):
        self.get_calls.append(key)
        return self.entries.get(key)

    async def put(self, key, entry, *, ttl_seconds):
        self.put_calls.append((key, entry, ttl_seconds))
        self.entries[key] = entry


def test_governed_mvt_route_reuses_authorized_shared_cache_without_provider_call():
    cache = _MemoryMVTResponseCache()
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"shared-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )

    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
        response_cache=cache,
    )
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
        response_cache=cache,
    )

    assert first.status_code == second.status_code == 200
    assert second.content == b"shared-mvt"
    assert first.headers["x-gda-shared-cache"] == "miss"
    assert second.headers["x-gda-shared-cache"] == "hit"
    provider.fetch_tile.assert_awaited_once()
    assert len(cache.put_calls) == 1
    assert cache.put_calls[0][2] == 60


def test_governed_mvt_route_cache_hit_honors_if_none_match():
    cache = _MemoryMVTResponseCache()
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"shared-mvt-304",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )
    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
        response_cache=cache,
    )
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
        response_cache=cache,
        headers={"if-none-match": first.headers["etag"]},
    )
    assert second.status_code == 304
    assert second.headers["etag"] == first.headers["etag"]
    provider.fetch_tile.assert_awaited_once()


def test_governed_mvt_route_cache_failure_falls_back_to_provider():
    class BrokenCache:
        enabled = True

        async def get(self, key):
            raise RuntimeError("redis unavailable")

        async def put(self, key, entry, *, ttl_seconds):
            raise RuntimeError("redis unavailable")

    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"fallback-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )
    response, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        provider=provider,
        response_cache=BrokenCache(),
    )
    assert response.status_code == 200
    assert response.content == b"fallback-mvt"
    provider.fetch_tile.assert_awaited_once()


def test_governed_mvt_route_does_not_cache_non_200_or_empty_tiles():
    for tile in (
        ProviderTileResponse(
            content=b"not-found",
            status_code=404,
            media_type="application/x-protobuf",
            etag=None,
        ),
        ProviderTileResponse(
            content=b"",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        ),
    ):
        cache = _MemoryMVTResponseCache()
        provider = MagicMock()
        provider.fetch_tile = AsyncMock(return_value=tile)
        response, _ = _route_request(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            provider=provider,
            response_cache=cache,
        )
        assert response.status_code == tile.status_code
        assert cache.put_calls == []


def test_governed_mvt_route_cache_identity_changes_with_service_policy():
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"policy-bound-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )

    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )
    projection.active_service_policy_binding = SimpleNamespace(
        service_policy_binding_id=uuid4(),
        allowed_roles=("platform_operator",),
        consumer_binding_required_roles=(),
        required_consumer_operation="read",
        policy_sha256="e" * 64,
    )
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )

    assert first.headers["etag"] != second.headers["etag"]
    assert first.headers["x-gda-cache-namespace"] != second.headers[
        "x-gda-cache-namespace"
    ]


def test_governed_mvt_route_rolls_cache_namespace_on_active_pointer_state_change():
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"pointer-generation-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )

    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )
    projection.endpoint_state_version += 1
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )

    assert first.headers["x-gda-cache-namespace"] != second.headers[
        "x-gda-cache-namespace"
    ]
    assert first.headers["x-gda-cache-generation"] != second.headers[
        "x-gda-cache-generation"
    ]
    assert first.headers["etag"] != second.headers["etag"]


def test_governed_mvt_route_cache_identity_changes_with_serving_projection():
    projection = _projection()
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"projection-bound-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )

    first, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )
    original_projection = projection.active_mvt_serving_projection_version
    serving_values = original_projection.model_dump(
        mode="python", exclude={"projection_sha256"}
    )
    serving_values.update(
        {
            "mvt_serving_projection_version_id": uuid4(),
            "version_key": "v1.1.0",
            "predecessor_version_id": (
                original_projection.mvt_serving_projection_version_id
            ),
        }
    )
    replacement_projection = MVTServingProjectionVersion(
        **serving_values,
        projection_sha256=mvt_serving_projection_fingerprint(serving_values),
    )
    release_values = projection.active_release_binding.model_dump(
        mode="python", exclude={"binding_sha256"}
    )
    release_values.update(
        {
            "service_release_binding_id": uuid4(),
            "mvt_serving_projection_version_id": (
                replacement_projection.mvt_serving_projection_version_id
            ),
        }
    )
    projection.active_release_binding = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    projection.active_mvt_serving_projection_version = replacement_projection
    projection.active_endpoint_revision.endpoint_contract = {
        "schema": "gda.mvt_endpoint.v1",
        "provider_layer_ref": "gda_mvt_serving_projection",
        "provider_query": {
            "serving_projection_version_id": str(
                replacement_projection.mvt_serving_projection_version_id
            )
        },
    }
    second, _ = _route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        projection=projection,
        provider=provider,
    )

    assert first.headers["etag"] != second.headers["etag"]
    assert first.headers["x-gda-cache-namespace"] != second.headers[
        "x-gda-cache-namespace"
    ]


def test_governed_mvt_route_allows_bound_consumer_with_release_read_scope():
    binding = SimpleNamespace(scope={"operations": ["read"]})
    provider = MagicMock()
    provider.fetch_tile = AsyncMock(
        return_value=ProviderTileResponse(
            content=b"consumer-mvt",
            status_code=200,
            media_type="application/x-protobuf",
            etag=None,
        )
    )

    response, provider, gateway = _consumer_route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        binding=binding,
        provider=provider,
    )

    assert response.status_code == 200
    assert response.content == b"consumer-mvt"
    gateway.get_active_service_consumer_binding_for_release.assert_called_once_with(
        "planning",
        SERVICE_URN,
        gateway.get_gis_service_control_projection.return_value.active_service_definition_version.service_definition_version_id,
        gateway.get_gis_service_control_projection.return_value.active_release_binding.service_release_binding_id,
        "human:analyst-01",
    )


def test_governed_mvt_route_rejects_consumer_without_active_binding():
    access_service = _access_service()
    access_service.admit.side_effect = MVTAccessDeniedError(
        "service_consumer_binding_required", "binding required"
    )
    response, provider, gateway = _consumer_route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        access_service=access_service,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_consumer_binding_required"
    gateway.get_active_service_consumer_binding_for_release.assert_called_once()
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_cross_tenant_consumer_before_provider_call():
    gateway = MagicMock()
    provider = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_ConsumerUser()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", return_value=provider),
    ):
        response = _client().get(
            "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
            params={"service_urn": "gda://other/gis_service/district-features"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_tenant_mismatch"
    gateway.get_gis_service_control_projection.assert_not_called()
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_consumer_without_read_scope():
    access_service = _access_service()
    access_service.admit.side_effect = MVTAccessDeniedError(
        "service_consumer_scope_denied", "scope denied"
    )
    response, provider, _ = _consumer_route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        binding=SimpleNamespace(scope={"operations": ["metadata.read"]}),
        access_service=access_service,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_consumer_scope_denied"
    provider.fetch_tile.assert_not_called()


def test_governed_mvt_route_rejects_consumer_without_active_release_binding():
    # The exact-release lookup returns no row for expired or replaced releases.
    access_service = _access_service()
    access_service.admit.side_effect = MVTAccessDeniedError(
        "service_consumer_binding_required", "binding required"
    )
    response, provider, _ = _consumer_route_request(
        "/api/platform/v1/gis/tiles/v1.0.0/0/0/0.pbf",
        access_service=access_service,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_consumer_binding_required"
    provider.fetch_tile.assert_not_called()
