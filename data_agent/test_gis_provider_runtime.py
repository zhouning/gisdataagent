from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from data_agent.gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    MartinMVTWarmupSample,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    ProviderHealthState,
    martin_mvt_endpoint_warmup_fingerprint,
    martin_mvt_warmup_sample_set_fingerprint,
    martin_provider_manifest,
    provider_manifest_fingerprint,
)
from data_agent.gis_service_control_plane import (
    CacheKeyDimension,
    CachePolicyVersion,
    EndpointProtocol,
    EndpointRevision,
    GISServiceType,
    MVTServingProjectionVersion,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
    cache_policy_version_fingerprint,
    endpoint_revision_fingerprint,
    mvt_serving_projection_fingerprint,
    service_release_binding_fingerprint,
    tile_matrix_set_definition_fingerprint,
)

TENANT = "planning"
NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)


def _release_and_tms() -> tuple[
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
    MVTServingProjectionVersion,
]:
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
    serving_projection_values = {
        "tenant_id": TENANT,
        "mvt_serving_projection_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "projection_key": "district-features-serving",
        "version_key": "v1.0.0",
        "source_output_resource_version_id": uuid4(),
        "source_schema": "serving",
        "source_table": "district_features_v1",
        "geometry_column": "geom",
        "geometry_srid": 4326,
        "feature_id_column": "district_id",
        "property_allowlist": ("name",),
        "allowed_spatial_extent": (-180.0, -90.0, 180.0, 90.0),
        "max_features_per_tile": 10_000,
        "source_content_sha256": "a" * 64,
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    serving_projection = MVTServingProjectionVersion(
        **serving_projection_values,
        projection_sha256=mvt_serving_projection_fingerprint(
            serving_projection_values
        ),
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
        "mvt_serving_projection_version_id": (
            serving_projection.mvt_serving_projection_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    return release, tms, serving_projection


def _context() -> MVTProviderReleaseContext:
    release, tms, serving_projection = _release_and_tms()
    return MVTProviderReleaseContext.from_release(
        release,
        tms,
        serving_projection,
        service_type=GISServiceType.VECTOR_TILE,
        provider_layer_ref="gda_mvt_serving_projection",
        provider_query={
            "serving_projection_version_id": str(
                serving_projection.mvt_serving_projection_version_id
            )
        },
    )


def _deployment(context: MVTProviderReleaseContext) -> ServiceDeploymentRevision:
    values = {
        "tenant_id": TENANT,
        "deployment_revision_id": uuid4(),
        "service_definition_version_id": context.service_definition_version_id,
        "service_release_binding_id": context.service_release_binding_id,
        "run_id": uuid4(),
        "revision_key": "r1",
        "provider_system": "martin",
        "provider_namespace": "planning-prod",
        "provider_deployment_id": "district-features-r1",
        "provider_revision_ref": "deployment:17",
        "config_sha256": "b" * 64,
        "created_by": "workload:service-controller",
        "created_at": NOW,
        "updated_at": NOW,
    }
    from data_agent.gis_service_control_plane import service_deployment_fingerprint

    return ServiceDeploymentRevision(
        **values,
        deployment_sha256=service_deployment_fingerprint(values),
    )


def _warmup_bundle():
    release, tms, serving_projection = _release_and_tms()
    cache_values = {
        "tenant_id": TENANT,
        "cache_policy_version_id": uuid4(),
        "service_definition_version_id": release.service_definition_version_id,
        "cache_policy_key": "district-features-private",
        "version_key": "v1.0.0",
        "cache_namespace": "district-features-v1",
        "cache_max_age_seconds": 120,
        "cache_key_dimensions": tuple(CacheKeyDimension),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    cache_policy = CachePolicyVersion(
        **cache_values,
        policy_sha256=cache_policy_version_fingerprint(cache_values),
    )
    release_values = release.model_dump(mode="python", exclude={"binding_sha256"})
    release_values["cache_policy_version_id"] = cache_policy.cache_policy_version_id
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    context = MVTProviderReleaseContext.from_release(
        release,
        tms,
        serving_projection,
        service_type=GISServiceType.VECTOR_TILE,
        provider_layer_ref="gda_mvt_serving_projection",
        provider_query={
            "serving_projection_version_id": str(
                serving_projection.mvt_serving_projection_version_id
            )
        },
    )
    planned = _deployment(context)
    deployment = ServiceDeploymentRevision.model_validate(
        {
            **planned.model_dump(mode="python"),
            "state": ServiceDeploymentState.READY,
            "state_version": 2,
            "terminal_observation_id": uuid4(),
            "updated_at": NOW,
            "terminal_at": NOW,
        }
    )
    endpoint_values = {
        "tenant_id": TENANT,
        "endpoint_revision_id": uuid4(),
        "service_urn": "gda://planning/gis_service/district-features",
        "deployment_revision_id": deployment.deployment_revision_id,
        "endpoint_protocol": EndpointProtocol.MVT,
        "endpoint_uri": "https://tiles.example.test/district-features/v1.0.0",
        "endpoint_contract": {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": dict(context.provider_query),
        },
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    endpoint = EndpointRevision(
        **endpoint_values,
        endpoint_sha256=endpoint_revision_fingerprint(endpoint_values),
    )
    return context, release, deployment, endpoint, cache_policy


def test_manifest_is_immutable_and_declares_read_only_mvt():
    manifest = martin_provider_manifest()

    assert manifest.provider_system == "martin"
    assert manifest.read_only is True
    assert "mvt_read" in {capability.value for capability in manifest.capabilities}
    assert manifest.manifest_sha256 == provider_manifest_fingerprint(manifest)


def test_release_context_rejects_mismatched_tms():
    release, tms, serving_projection = _release_and_tms()
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
            serving_projection,
            service_type="vector_tile",
            provider_layer_ref="gda_mvt_serving_projection",
        )


@pytest.mark.asyncio
async def test_martin_adapter_discovers_health_fetches_tile_and_builds_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={
                    "tiles": {
                        "gda_mvt_serving_projection": {
                            "content_type": "application/x-protobuf"
                        }
                    }
                },
            )
        if request.url.path == "/gda_mvt_serving_projection/0/0/0":
            assert request.url.params.get("serving_projection_version_id")
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

    assert "gda_mvt_serving_projection" in catalog["tiles"]
    assert health.state is ProviderHealthState.READY
    assert tile.content == b"mvt-bytes"
    assert tile.etag == '"revision-1"'
    assert observation.observed_state == "ready"
    assert observation.evidence["service_release_binding_id"] == str(
        context.service_release_binding_id
    )


@pytest.mark.asyncio
async def test_martin_adapter_builds_release_bound_deployment_readiness_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, text="OK")

    provider = MartinVectorTileProvider(
        "https://martin.example.test",
        transport=httpx.MockTransport(handler),
    )
    context = _context()
    deployment = _deployment(context)
    observation = await provider.build_deployment_ready_observation(
        context,
        deployment,
        observation_id=uuid4(),
        attempt_no=1,
        endpoint_uri="https://tiles.example.test/district-features",
        provider_receipt={"catalog": "verified", "health_status": 200},
        observed_at=NOW,
    )

    assert observation.run_id == deployment.run_id
    assert observation.external_namespace == deployment.provider_namespace
    assert observation.evidence["schema"] == (
        "gda.gis_service_deployment_observation.v2"
    )
    assert observation.evidence["config_sha256"] == deployment.config_sha256
    assert observation.evidence["health_evidence_sha256"]

    with pytest.raises(GISProviderContractError, match="credential-free HTTPS"):
        await provider.build_deployment_ready_observation(
            context,
            deployment,
            observation_id=uuid4(),
            attempt_no=1,
            endpoint_uri="https://tiles.example.test/districts?token=bad",
            provider_receipt={"catalog": "verified"},
            observed_at=NOW,
        )


@pytest.mark.asyncio
async def test_martin_adapter_builds_readiness_evidence_from_real_mvt_conformance():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={
                    "tiles": {
                        "gda_mvt_serving_projection": {
                            "content_type": "application/x-protobuf"
                        }
                    }
                },
            )
        if request.url.path == "/gda_mvt_serving_projection/0/0/0":
            assert request.url.params.get("serving_projection_version_id")
            return httpx.Response(
                200,
                content=b"release-bound-mvt",
                headers={"content-type": "application/x-protobuf", "etag": '"r1"'},
            )
        return httpx.Response(404)

    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(handler),
    )
    context = _context()
    observation = await provider.build_deployment_ready_conformance_observation(
        context,
        _deployment(context),
        observation_id=uuid4(),
        attempt_no=1,
        endpoint_uri="https://tiles.example.test/district-features",
        z=0,
        x=0,
        y=0,
    )

    receipt = observation.evidence["provider_receipt"]
    assert receipt["schema"] == "gda.gis_martin_mvt_conformance.v1"
    assert receipt["provider_layer_ref"] == "gda_mvt_serving_projection"
    assert receipt["tile_content_bytes"] == len(b"release-bound-mvt")
    assert receipt["tile_content_sha256"]
    assert receipt["mvt_serving_projection_version_id"] == str(
        context.mvt_serving_projection_version_id
    )
    assert observation.evidence["health_evidence_sha256"] == receipt["health"][
        "evidence_sha256"
    ]


@pytest.mark.asyncio
async def test_martin_adapter_rejects_incomplete_or_empty_readiness_conformance():
    context = _context()

    def missing_layer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(200, json={"tiles": {}})
        return httpx.Response(404)

    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(missing_layer),
    )
    with pytest.raises(GISProviderContractError, match="does not advertise"):
        await provider.conform_mvt_read(context, 0, 0, 0)

    def empty_tile(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200, json={"tiles": {"gda_mvt_serving_projection": {}}}
            )
        return httpx.Response(
            200,
            content=b"",
            headers={"content-type": "application/x-protobuf"},
        )

    empty_provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(empty_tile),
    )
    with pytest.raises(GISProviderContractError, match="non-empty HTTP 200"):
        await empty_provider.conform_mvt_read(context, 0, 0, 0)


@pytest.mark.asyncio
async def test_martin_adapter_builds_release_bound_deployment_failure_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(503, text="unavailable")

    provider = MartinVectorTileProvider(
        "https://martin.example.test",
        transport=httpx.MockTransport(handler),
    )
    context = _context()
    deployment = _deployment(context)
    observation = await provider.build_deployment_failed_observation(
        context,
        deployment,
        observation_id=uuid4(),
        attempt_no=1,
        endpoint_uri="https://tiles.example.test/district-features",
        provider_receipt={"health_status": 503, "failure": "unavailable"},
        observed_at=NOW,
    )

    assert observation.observed_state == "failed"
    assert observation.evidence["schema"] == (
        "gda.gis_service_deployment_observation.v2"
    )
    assert observation.evidence["health_evidence_sha256"]

    with pytest.raises(GISProviderUnavailable, match="HTTP 503"):
        await provider.health()


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


@pytest.mark.asyncio
async def test_martin_adapter_warms_exact_release_with_real_multi_tile_reads():
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={"tiles": {"gda_mvt_serving_projection": {}}},
            )
        if request.url.path.startswith("/gda_mvt_serving_projection/"):
            assert request.url.params.get("serving_projection_version_id")
            return httpx.Response(
                200,
                content=f"mvt:{request.url.path}".encode(),
                headers={
                    "content-type": "application/x-protobuf",
                    "etag": f'"{request.url.path}"',
                },
            )
        return httpx.Response(404)

    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(handler),
    )
    context, release, deployment, endpoint, cache_policy = _warmup_bundle()
    samples = (
        MartinMVTWarmupSample(z=0, x=0, y=0),
        MartinMVTWarmupSample(z=1, x=0, y=0),
        MartinMVTWarmupSample(z=1, x=1, y=1),
    )

    receipt = await provider.warmup_mvt_tiles(
        context,
        release,
        deployment,
        endpoint,
        cache_policy,
        samples,
    )

    assert requested_paths == [
        "/health",
        "/catalog",
        "/gda_mvt_serving_projection/0/0/0",
        "/gda_mvt_serving_projection/1/0/0",
        "/gda_mvt_serving_projection/1/1/1",
    ]
    assert receipt.provider_origin_uri == "http://martin:3000"
    assert receipt.consumer_endpoint_uri == endpoint.endpoint_uri
    assert receipt.endpoint_revision_id == endpoint.endpoint_revision_id
    assert receipt.deployment_revision_id == deployment.deployment_revision_id
    assert receipt.cache_policy_version_id == cache_policy.cache_policy_version_id
    assert receipt.requested_sample_count == 3
    assert receipt.successful_sample_count == 3
    assert receipt.sample_set_sha256 == martin_mvt_warmup_sample_set_fingerprint(
        samples
    )
    assert receipt.receipt_sha256 == martin_mvt_endpoint_warmup_fingerprint(
        receipt
    )
    assert all(sample.content_bytes > 0 for sample in receipt.samples)
    assert len({sample.content_sha256 for sample in receipt.samples}) == 3


@pytest.mark.asyncio
async def test_martin_warmup_rejects_duplicate_or_mismatched_control_identity():
    provider = MartinVectorTileProvider(
        "http://martin:3000",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )
    context, release, deployment, endpoint, cache_policy = _warmup_bundle()
    sample = MartinMVTWarmupSample(z=0, x=0, y=0)

    with pytest.raises(GISProviderContractError, match="unique"):
        await provider.warmup_mvt_tiles(
            context,
            release,
            deployment,
            endpoint,
            cache_policy,
            (sample, sample),
        )

    wrong_endpoint = endpoint.model_copy(
        update={"deployment_revision_id": uuid4()}
    )
    with pytest.raises(GISProviderContractError, match="does not match"):
        await provider.warmup_mvt_tiles(
            context,
            release,
            deployment,
            wrong_endpoint,
            cache_policy,
            (sample,),
        )


@pytest.mark.asyncio
async def test_martin_warmup_fails_closed_on_missing_layer_or_empty_tile():
    context, release, deployment, endpoint, cache_policy = _warmup_bundle()
    sample = (MartinMVTWarmupSample(z=0, x=0, y=0),)

    def missing_layer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/catalog":
            return httpx.Response(200, json={"tiles": {}})
        return httpx.Response(404)

    with pytest.raises(GISProviderContractError, match="does not advertise"):
        await MartinVectorTileProvider(
            "http://martin:3000",
            transport=httpx.MockTransport(missing_layer),
        ).warmup_mvt_tiles(
            context, release, deployment, endpoint, cache_policy, sample
        )

    def empty_tile(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={"tiles": {"gda_mvt_serving_projection": {}}},
            )
        return httpx.Response(204)

    with pytest.raises(GISProviderContractError, match="non-empty HTTP 200"):
        await MartinVectorTileProvider(
            "http://martin:3000",
            transport=httpx.MockTransport(empty_tile),
        ).warmup_mvt_tiles(
            context, release, deployment, endpoint, cache_policy, sample
        )
