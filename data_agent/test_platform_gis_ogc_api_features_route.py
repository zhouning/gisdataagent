from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from data_agent.api import platform_gateway_routes as routes
from data_agent.gis_ogc_api_features_access import OGCFeaturesAccessService
from data_agent.gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    ProviderFeatureResponse,
)
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    ServiceDeploymentState,
    ServiceReleaseBinding,
    service_policy_binding_fingerprint,
    service_release_binding_fingerprint,
)
from data_agent.test_gis_service_control_plane import _definition, _release_bundle

SERVICE_URN = "gda://planning/gis_service/district-features"


class _Operator:
    identifier = "operator"
    metadata = {"role": "platform_operator", "tenant_id": "planning"}


class _Viewer:
    identifier = "viewer"
    metadata = {"role": "viewer", "tenant_id": "planning"}


class _Analyst:
    identifier = "analyst-01"
    metadata = {"role": "analyst", "tenant_id": "planning"}


def _client() -> TestClient:
    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())
    return TestClient(app)


def _projection(
    *,
    release_key: str = "v1.0.0",
    protocol: EndpointProtocol = EndpointProtocol.OGC_API_FEATURES,
    provider_system: str = "pygeoapi",
    state: ServiceDeploymentState = ServiceDeploymentState.READY,
    collection_id: str = "districts",
):
    definition = _definition()
    layer, _style, _tms, release = _release_bundle(definition)
    if release_key != release.release_key:
        values = release.model_dump(mode="python", exclude={"binding_sha256"})
        values["release_key"] = release_key
        release = ServiceReleaseBinding(
            **values,
            binding_sha256=service_release_binding_fingerprint(values),
        )
    deployment = SimpleNamespace(
        provider_system=provider_system,
        provider_revision_ref="pygeoapi-0.25.dev0",
        state=state,
        deployment_revision_id=uuid4(),
    )
    endpoint = SimpleNamespace(
        endpoint_protocol=protocol,
        endpoint_contract={
            "schema": "gda.ogc_api_features_endpoint.v1",
            "collection_id": collection_id,
        },
        endpoint_uri="https://geo.example.test/collections/districts",
        endpoint_revision_id=uuid4(),
    )
    policy_values = {
        "tenant_id": "planning",
        "service_policy_binding_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "policy_key": "ogc-features-gateway-read",
        "version_key": "v1.0.0",
        "action": "ogc_features.read",
        "enforcement_point": "gateway",
        "allowed_roles": ("platform_operator", "analyst"),
        "consumer_binding_required_roles": ("analyst",),
        "required_consumer_operation": "read",
        "created_by": "workload:service-controller",
        "created_at": release.created_at,
    }
    policy = SimpleNamespace(
        **policy_values,
        policy_sha256=service_policy_binding_fingerprint(policy_values),
    )
    return SimpleNamespace(
        endpoint_state_version=7,
        active_endpoint_revision=endpoint,
        active_deployment_revision=deployment,
        active_service_definition_version=definition,
        active_release_binding=release,
        active_layer_definition_version=layer,
        active_service_policy_binding=policy,
    )


def _request(
    *,
    projection=None,
    provider=None,
    user=None,
    params=None,
    collection="districts",
    consumer_binding=...,
):
    gateway = MagicMock()
    projection = projection or _projection()
    gateway.get_gis_service_control_projection.return_value = projection
    if consumer_binding is not ...:
        gateway.get_active_service_consumer_binding_for_release.return_value = consumer_binding
    if provider is None:
        provider = MagicMock()
        provider.fetch_items = AsyncMock(
            return_value=ProviderFeatureResponse(
                content=b'{"type":"FeatureCollection","features":[]}',
                status_code=200,
                media_type="application/geo+json",
                feature_count=0,
                payload={"type": "FeatureCollection", "features": []},
                etag='"features-v1"',
            )
        )
    with (
        patch.object(routes, "_get_user_from_request", return_value=user or _Operator()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "OGCAPIFeaturesProvider", return_value=provider),
        patch.object(
            routes,
            "_ogc_features_access_service",
            return_value=OGCFeaturesAccessService(ledger=MagicMock()),
        ),
        patch.object(routes, "_pygeoapi_provider_endpoint", return_value="http://pygeoapi:5000"),
        patch.dict(routes.os.environ, {"PYGEOAPI_PROVIDER_VERSION": "0.25.dev0"}),
    ):
        response = _client().get(
            f"/api/platform/v1/gis/features/v1.0.0/collections/{collection}/items",
            params={"service_urn": SERVICE_URN, **(params or {})},
        )
    return response, provider, gateway


def test_governed_ogc_features_route_reads_active_release_and_provider():
    response, provider, _gateway = _request(params={"limit": "2", "bbox": "120,30,122,32"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-gda-service-release"] == "v1.0.0"
    provider.fetch_items.assert_awaited_once()
    context = provider.fetch_items.await_args.args[0]
    assert context.collection_id == "districts"
    assert provider.fetch_items.await_args.kwargs == {
        "limit": 2,
        "bbox": (120.0, 30.0, 122.0, 32.0),
    }


def test_governed_ogc_features_route_rejects_collection_mismatch():
    response, provider, _gateway = _request(collection="other")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "collection_mismatch"
    assert provider.fetch_items.await_count == 0


def test_governed_ogc_features_route_rejects_inactive_release_protocol_provider_and_state():
    for projection in (
        _projection(release_key="v2.0.0"),
        _projection(protocol=EndpointProtocol.MVT),
        _projection(provider_system="martin"),
        _projection(state=ServiceDeploymentState.DEPLOYING),
    ):
        response, provider, _gateway = _request(projection=projection)
        assert response.status_code == 409
        assert provider.fetch_items.await_count == 0


def test_governed_ogc_features_route_rejects_invalid_limit_and_bbox_at_gateway():
    for params in (
        {"limit": "0"},
        {"limit": "1001"},
        {"limit": "x"},
        {"bbox": "1,2,3"},
        {"bbox": "4,2,1,3"},
    ):
        response, provider, _gateway = _request(params=params)
        assert response.status_code == 400
        assert provider.fetch_items.await_count == 0


def test_governed_ogc_features_route_requires_platform_role():
    response, provider, _gateway = _request(user=_Viewer())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_policy_denied"
    assert provider.fetch_items.await_count == 0


def test_governed_ogc_features_route_requires_exact_consumer_binding():
    missing, provider, gateway = _request(user=_Analyst(), consumer_binding=None)
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "service_consumer_binding_required"
    assert provider.fetch_items.await_count == 0
    projection = _projection()
    binding = SimpleNamespace(
        tenant_id="planning",
        service_urn=SERVICE_URN,
        service_definition_version_id=projection.active_service_definition_version.service_definition_version_id,
        service_release_binding_id=projection.active_release_binding.service_release_binding_id,
        consumer_ref="human:analyst-01",
        action="ogc_features.read",
        purpose="ogc_features_read",
        scope={"operations": ["read"]},
        expires_at=projection.active_release_binding.created_at.replace(year=2027),
        service_consumer_binding_id=uuid4(),
        binding_sha256="d" * 64,
    )
    success, provider, _gateway = _request(
        user=_Analyst(), projection=projection, consumer_binding=binding
    )
    assert success.status_code == 200
    provider.fetch_items.assert_awaited_once()


def test_governed_ogc_features_route_fails_closed_on_provider_failure():
    provider = MagicMock()
    provider.fetch_items = AsyncMock(
        side_effect=GISProviderUnavailable("provider unavailable")
    )
    response, _provider, _gateway = _request(provider=provider)
    provider.fetch_items.assert_awaited_once()
    assert response.status_code == 503

    provider.fetch_items = AsyncMock(
        side_effect=GISProviderContractError("provider rejected request")
    )
    response, _provider, _gateway = _request(provider=provider)
    assert response.status_code == 502
