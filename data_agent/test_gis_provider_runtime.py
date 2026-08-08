from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from data_agent.gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    ProviderHealthState,
    martin_provider_manifest,
    provider_manifest_fingerprint,
)
from data_agent.gis_service_control_plane import (
    GISServiceType,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
    service_release_binding_fingerprint,
    tile_matrix_set_definition_fingerprint,
)

TENANT = "planning"
NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)


def _release_and_tms() -> tuple[ServiceReleaseBinding, TileMatrixSetDefinitionVersion]:
    service_definition_id = uuid4()
    layer_id = uuid4()
    tms_values = {
        "tenant_id": TENANT,
        "tile_matrix_set_definition_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "tile_matrix_set_key": "webmercatorquad",
        "version_key": "v1.0.0",
        "crs_uri": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "tile_width": 256,
        "tile_height": 256,
        "min_zoom": 0,
        "max_zoom": 2,
        "scale_denominators": (559082264.029, 279541132.015, 139770566.007),
        "spatial_extent": (-20037508.0, -20037508.0, 20037508.0, 20037508.0),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    tms = TileMatrixSetDefinitionVersion(
        **tms_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(tms_values),
    )
    release_values = {
        "tenant_id": TENANT,
        "service_release_binding_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "style_definition_version_id": uuid4(),
        "tile_matrix_set_definition_version_id": (
            tms.tile_matrix_set_definition_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    return release, tms


def _context() -> MVTProviderReleaseContext:
    release, tms = _release_and_tms()
    return MVTProviderReleaseContext.from_release(
        release,
        tms,
        service_type=GISServiceType.VECTOR_TILE,
        provider_layer_ref="map_publication",
        provider_query={"publication_id": str(uuid4())},
    )


def test_manifest_is_immutable_and_declares_read_only_mvt():
    manifest = martin_provider_manifest()

    assert manifest.provider_system == "martin"
    assert manifest.read_only is True
    assert "mvt_read" in {capability.value for capability in manifest.capabilities}
    assert manifest.manifest_sha256 == provider_manifest_fingerprint(manifest)


def test_release_context_rejects_mismatched_tms():
    release, tms = _release_and_tms()
    other_values = {
        **tms.model_dump(mode="python", exclude={"definition_sha256"}),
        "tile_matrix_set_definition_version_id": uuid4(),
    }
    other_tms = TileMatrixSetDefinitionVersion(
        **other_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(other_values),
    )
    with pytest.raises(GISProviderContractError, match="does not match"):
        MVTProviderReleaseContext.from_release(
            release,
            other_tms,
            service_type="vector_tile",
            provider_layer_ref="map_publication",
        )


@pytest.mark.asyncio
async def test_martin_adapter_discovers_health_fetches_tile_and_builds_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={"tiles": {"map_publication": {"content_type": "application/x-protobuf"}}},
            )
        if request.url.path == "/map_publication/0/0/0":
            assert request.url.params.get("publication_id")
            return httpx.Response(
                200,
                content=b"mvt-bytes",
                headers={
                    "content-type": "application/x-protobuf",
                    "etag": '"revision-1"',
                },
            )
        return httpx.Response(404)

    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(handler),
    )
    context = _context()
    catalog = await provider.discover_capabilities()
    health = await provider.health()
    tile = await provider.fetch_tile(context, 0, 0, 0)
    observation = await provider.build_ready_observation(
        context,
        run_id=uuid4(),
        observation_id=uuid4(),
        attempt_no=1,
        external_run_id="martin-reconcile-1",
        external_attempt_id="health-1",
        observed_at=NOW,
    )

    assert "map_publication" in catalog["tiles"]
    assert health.state is ProviderHealthState.READY
    assert tile.content == b"mvt-bytes"
    assert tile.etag == '"revision-1"'
    assert observation.observed_state == "ready"
    assert observation.evidence["service_release_binding_id"] == str(
        context.service_release_binding_id
    )


@pytest.mark.asyncio
async def test_martin_adapter_rejects_bad_media_type_and_server_failure():
    def bad_media(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-mvt", headers={"content-type": "text/plain"})

    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(bad_media),
    )
    with pytest.raises(GISProviderContractError, match="unsupported media type"):
        await provider.fetch_tile(_context(), 0, 0, 0)

    def server_failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    unavailable = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(server_failure),
    )
    with pytest.raises(GISProviderUnavailable, match="HTTP 503"):
        await unavailable.fetch_tile(_context(), 0, 0, 0)
