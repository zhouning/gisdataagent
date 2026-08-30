from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from data_agent.gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    OGCAPIFeaturesProvider,
    OGCAPIFeaturesReleaseContext,
    ProviderHealthState,
    ogc_api_features_conformance_fingerprint,
    pygeoapi_provider_manifest,
)
from data_agent.test_gis_service_control_plane import (
    _definition,
    _deployment,
    _release_bundle,
)

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _context() -> OGCAPIFeaturesReleaseContext:
    definition = _definition()
    layer, _style, _tms, release = _release_bundle(definition)
    return OGCAPIFeaturesReleaseContext.from_release(
        release,
        definition,
        layer,
        collection_id=layer.layer_key,
    )


def _deployment_for_context(context: OGCAPIFeaturesReleaseContext):
    definition = _definition()
    definition = definition.model_copy(
        update={"service_definition_version_id": context.service_definition_version_id}
    )
    layer, _style, _tms, release = _release_bundle(definition)
    release = release.model_copy(
        update={
            "service_release_binding_id": context.service_release_binding_id,
            "layer_definition_version_id": context.layer_definition_version_id,
        }
    )
    # The provider adapter only consumes deployment identity; use the normal
    # control-plane fixture and overwrite its exact release lineage.
    deployment = _deployment(definition, release)
    return deployment.model_copy(
        update={
            "service_definition_version_id": context.service_definition_version_id,
            "service_release_binding_id": context.service_release_binding_id,
        }
    )


def _handler(*, collection_id: str = "districts", features: list | None = None):
    feature_payload = features if features is not None else [
        {
            "type": "Feature",
            "id": "d-1",
            "geometry": {"type": "Point", "coordinates": [121.1, 31.2]},
            "properties": {"name": "district"},
        }
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, json={"title": "pygeoapi"})
        if request.url.path == "/conformance":
            return httpx.Response(
                200,
                json={"conformsTo": ["http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"]},
            )
        if request.url.path == "/collections":
            return httpx.Response(200, json={"collections": [{"id": collection_id}]})
        if request.url.path == f"/collections/{collection_id}/items":
            assert request.url.params["f"] == "json"
            assert request.url.params["limit"] in {"25", "100"}
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": feature_payload},
                headers={"etag": '"features-r1"'},
            )
        return httpx.Response(404)

    return handle


def test_manifest_and_context_bind_feature_release_and_product_identity():
    manifest = pygeoapi_provider_manifest()
    context = _context()

    assert manifest.provider_system == "pygeoapi"
    assert manifest.manifest_sha256
    assert context.service_type.value == "feature"
    assert context.collection_id == "districts"
    assert context.source_product_urn == "gda://planning/data_product/districts"


def test_context_rejects_cross_lineage_components():
    definition = _definition()
    layer, _style, _tms, release = _release_bundle(definition)
    other_definition = _definition()
    with pytest.raises(GISProviderContractError, match="one service lineage"):
        OGCAPIFeaturesReleaseContext.from_release(
            release,
            other_definition,
            layer,
            collection_id="districts",
        )


@pytest.mark.asyncio
async def test_provider_conformance_reads_health_conformance_catalog_and_features():
    provider = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(_handler()),
    )
    context = _context()

    receipt = await provider.conform_features_read(
        context,
        limit=25,
        bbox=(120.0, 30.0, 122.0, 32.0),
    )

    assert receipt.provider_system == "pygeoapi"
    assert receipt.collection_id == "districts"
    assert receipt.feature_count == 1
    assert receipt.requested_limit == 25
    assert receipt.requested_bbox == (120.0, 30.0, 122.0, 32.0)
    assert receipt.items_media_type == "application/json"
    assert receipt.receipt_sha256 == ogc_api_features_conformance_fingerprint(receipt)
    assert receipt.health.state is ProviderHealthState.READY


@pytest.mark.asyncio
async def test_provider_builds_release_bound_deployment_observation():
    provider = OGCAPIFeaturesProvider(
        "https://pygeoapi.example.test",
        transport=httpx.MockTransport(_handler()),
    )
    context = _context()
    deployment = _deployment_for_context(context)

    observation = await provider.build_deployment_ready_conformance_observation(
        context,
        deployment,
        observation_id=uuid4(),
        attempt_no=1,
        endpoint_uri="https://geo.example.test/districts",
        limit=25,
    )

    receipt = observation.evidence["provider_receipt"]
    assert observation.observed_state == "ready"
    assert observation.run_id == deployment.run_id
    assert receipt["schema"] == "gda.gis_ogc_api_features_conformance.v1"
    assert receipt["source_product_urn"] == context.source_product_urn
    assert receipt["layer_definition_version_id"] == str(context.layer_definition_version_id)
    assert observation.evidence["health_evidence_sha256"] == receipt["health"][
        "evidence_sha256"
    ]


@pytest.mark.asyncio
async def test_provider_fails_closed_for_missing_collection_invalid_geojson_and_empty_response():
    context = _context()
    missing = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(_handler(collection_id="other")),
    )
    with pytest.raises(GISProviderContractError, match="does not advertise"):
        await missing.conform_features_read(context)

    invalid_feature = {
        "type": "Feature",
        "geometry": "not-geometry",
        "properties": {},
    }
    invalid = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(_handler(features=[invalid_feature])),
    )
    with pytest.raises(GISProviderContractError, match="invalid geometry"):
        await invalid.fetch_items(context, limit=25)

    empty = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(_handler(features=[])),
    )
    with pytest.raises(GISProviderContractError, match="non-empty"):
        await empty.conform_features_read(context)


@pytest.mark.asyncio
async def test_provider_fails_closed_when_conformance_or_media_type_is_not_advertised():
    context = _context()

    def no_conformance(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, json={"title": "pygeoapi"})
        if request.url.path == "/conformance":
            return httpx.Response(200, json={"conformsTo": []})
        return _handler()(request)

    provider = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(no_conformance),
    )
    with pytest.raises(GISProviderContractError, match="does not advertise OGC API Features"):
        await provider.conform_features_read(context)

    def bad_media(request: httpx.Request) -> httpx.Response:
        response = _handler()(request)
        if request.url.path.endswith("/items"):
            response.headers["content-type"] = "text/plain"
        return response

    provider = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(bad_media),
    )
    with pytest.raises(GISProviderContractError, match="unsupported media type"):
        await provider.fetch_items(context)


@pytest.mark.asyncio
async def test_provider_rejects_http_failures_bad_bbox_and_bad_endpoint_identity():
    context = _context()
    server_failure = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )
    with pytest.raises(GISProviderUnavailable, match="HTTP 503"):
        await server_failure.health()

    provider = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(_handler()),
    )
    with pytest.raises(GISProviderContractError, match="bbox"):
        await provider.fetch_items(context, bbox=(2.0, 1.0, 0.0, 3.0))
    with pytest.raises(GISProviderContractError, match="between 1 and 1000"):
        await provider.fetch_items(context, limit=1001)

    with pytest.raises(GISProviderContractError, match="credential-free"):
        OGCAPIFeaturesProvider("https://geo.example.test?token=secret")


@pytest.mark.asyncio
async def test_provider_rejects_version_header_drift():
    def drifted_health(request: httpx.Request) -> httpx.Response:
        response = _handler()(request)
        if request.url.path == "/":
            response.headers["x-powered-by"] = "pygeoapi 9.9.9"
        return response

    provider = OGCAPIFeaturesProvider(
        "http://pygeoapi:5000",
        transport=httpx.MockTransport(drifted_health),
    )
    with pytest.raises(GISProviderContractError, match="version header"):
        await provider.health()
