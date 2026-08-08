from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data_agent.gis_service_control_plane import (
    EndpointRevision,
    GISServiceControlProjection,
    GISServiceDefinitionVersion,
    LayerDefinitionVersion,
    ServiceDeploymentRevision,
    ServiceReleaseBinding,
    StyleDefinitionVersion,
    TileMatrixSetDefinitionVersion,
    endpoint_revision_fingerprint,
    gis_service_definition_fingerprint,
    layer_definition_fingerprint,
    service_deployment_fingerprint,
    service_release_binding_fingerprint,
    style_definition_fingerprint,
    tile_matrix_set_definition_fingerprint,
)

TENANT = "planning"
SERVICE_URN = "gda://planning/gis_service/district-features"
PRODUCT_URN = "gda://planning/data_product/districts"
NOW = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)


def _definition() -> GISServiceDefinitionVersion:
    values = {
        "tenant_id": TENANT,
        "service_definition_version_id": uuid4(),
        "service_urn": SERVICE_URN,
        "version_key": "v1.0.0",
        "platform_definition_version_id": uuid4(),
        "source_product_urn": PRODUCT_URN,
        "source_data_product_version_id": uuid4(),
        "source_manifest_sha256": "a" * 64,
        "service_type": "feature",
        "service_contract": {
            "schema": "gda.gis_service_definition.v1",
            "operations": ["query", "items"],
        },
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    return GISServiceDefinitionVersion(
        **values,
        definition_sha256=gis_service_definition_fingerprint(values),
    )


def _release_bundle(
    definition: GISServiceDefinitionVersion,
) -> tuple[
    LayerDefinitionVersion,
    StyleDefinitionVersion,
    TileMatrixSetDefinitionVersion,
    ServiceReleaseBinding,
]:
    layer_values = {
        "tenant_id": TENANT,
        "layer_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_key": "districts",
        "version_key": "v1.0.0",
        "source_output_resource_version_id": uuid4(),
        "geometry_type": "multipolygon",
        "geometry_column": "geom",
        "schema_contract": {
            "schema": "gda.layer_schema.v1",
            "properties": {"district_id": {"type": "string"}},
        },
        "crs_uri": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "spatial_extent": (120.8, 30.6, 122.2, 31.9),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    layer = LayerDefinitionVersion(
        **layer_values,
        definition_sha256=layer_definition_fingerprint(layer_values),
    )
    style_values = {
        "tenant_id": TENANT,
        "style_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "style_key": "default",
        "version_key": "v1.0.0",
        "style_format": "mapbox_style",
        "style_document": {
            "version": 8,
            "layers": [{"id": "districts", "type": "fill"}],
        },
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    style = StyleDefinitionVersion(
        **style_values,
        style_sha256=style_definition_fingerprint(style_values),
    )
    tile_values = {
        "tenant_id": TENANT,
        "tile_matrix_set_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "tile_matrix_set_key": "webmercatorquad",
        "version_key": "v1.0.0",
        "crs_uri": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "tile_width": 256,
        "tile_height": 256,
        "min_zoom": 0,
        "max_zoom": 2,
        "scale_denominators": (559082264.029, 279541132.015, 139770566.007),
        "spatial_extent": (-20037508.3428, -20037508.3428, 20037508.3428, 20037508.3428),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    tile_matrix = TileMatrixSetDefinitionVersion(
        **tile_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(tile_values),
    )
    release_values = {
        "tenant_id": TENANT,
        "service_release_binding_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "style_definition_version_id": style.style_definition_version_id,
        "tile_matrix_set_definition_version_id": (
            tile_matrix.tile_matrix_set_definition_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    return layer, style, tile_matrix, release


def _deployment(
    definition: GISServiceDefinitionVersion,
    release: ServiceReleaseBinding | None = None,
) -> ServiceDeploymentRevision:
    if release is None:
        release = _release_bundle(definition)[3]
    values = {
        "tenant_id": TENANT,
        "deployment_revision_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "run_id": uuid4(),
        "revision_key": "r1",
        "provider_system": "pygeoapi",
        "provider_namespace": "planning-prod",
        "provider_deployment_id": "district-features",
        "provider_revision_ref": "deployment:17",
        "config_sha256": "b" * 64,
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    return ServiceDeploymentRevision(
        **values,
        deployment_sha256=service_deployment_fingerprint(values),
        updated_at=NOW,
    )


def _endpoint(deployment: ServiceDeploymentRevision) -> EndpointRevision:
    values = {
        "tenant_id": TENANT,
        "endpoint_revision_id": uuid4(),
        "service_urn": SERVICE_URN,
        "deployment_revision_id": deployment.deployment_revision_id,
        "endpoint_protocol": "ogc_api_features",
        "endpoint_uri": "https://geo.example.test/collections/districts",
        "endpoint_contract": {
            "schema": "gda.endpoint_revision.v1",
            "conformance": ["ogcapi-features-1"],
        },
        "created_by": "workload:service-controller",
        "created_at": NOW + timedelta(minutes=2),
    }
    return EndpointRevision(
        **values,
        endpoint_sha256=endpoint_revision_fingerprint(values),
    )


def test_gis_service_contracts_bind_deterministic_immutable_fingerprints():
    definition = _definition()
    layer, style, tile_matrix, release = _release_bundle(definition)
    deployment = _deployment(definition, release)
    endpoint = _endpoint(deployment)

    assert definition.definition_sha256 == gis_service_definition_fingerprint(definition)
    assert layer.definition_sha256 == layer_definition_fingerprint(layer)
    assert style.style_sha256 == style_definition_fingerprint(style)
    assert tile_matrix.definition_sha256 == tile_matrix_set_definition_fingerprint(
        tile_matrix
    )
    assert release.binding_sha256 == service_release_binding_fingerprint(release)
    assert deployment.deployment_sha256 == service_deployment_fingerprint(deployment)
    assert endpoint.endpoint_sha256 == endpoint_revision_fingerprint(endpoint)
    with pytest.raises(ValidationError, match="definition_sha256"):
        GISServiceDefinitionVersion.model_validate(
            {
                **definition.model_dump(mode="python"),
                "definition_sha256": "0" * 64,
            }
        )


def test_service_deployment_terminal_state_requires_provider_observation():
    deployment = _deployment(_definition())
    with pytest.raises(ValidationError, match="terminal deployment state"):
        ServiceDeploymentRevision.model_validate(
            {
                **deployment.model_dump(mode="python"),
                "state": "ready",
                "state_version": 2,
                "terminal_at": NOW + timedelta(minutes=1),
            }
        )


def test_legacy_deployment_fingerprint_remains_readable_without_release_binding():
    current = _deployment(_definition())
    legacy_values = current.model_dump(
        mode="python",
        exclude={"deployment_sha256", "service_release_binding_id"},
    )
    legacy = ServiceDeploymentRevision(
        **legacy_values,
        deployment_sha256=service_deployment_fingerprint(legacy_values),
    )

    assert legacy.service_release_binding_id is None
    assert legacy.deployment_sha256 == service_deployment_fingerprint(legacy)


@pytest.mark.parametrize(
    "uri",
    (
        "http://geo.example.test/districts",
        "https://user:token@geo.example.test/districts",
        "https://geo.example.test/districts?token=secret",
        "https://geo.example.test/districts#preview",
    ),
)
def test_endpoint_revision_rejects_unstable_or_credential_bearing_uri(uri: str):
    deployment = _deployment(_definition())
    values = _endpoint(deployment).model_dump(mode="python")
    values["endpoint_uri"] = uri
    values["endpoint_sha256"] = endpoint_revision_fingerprint(values)
    with pytest.raises(ValidationError, match="credential-free HTTPS"):
        EndpointRevision.model_validate(values)


def test_active_service_projection_must_join_endpoint_deployment_and_definition():
    definition = _definition()
    layer, style, tile_matrix, release = _release_bundle(definition)
    planned = _deployment(definition, release)
    deployment = ServiceDeploymentRevision.model_validate(
        {
            **planned.model_dump(mode="python"),
            "state": "ready",
            "state_version": 2,
            "terminal_observation_id": uuid4(),
            "updated_at": NOW + timedelta(minutes=1),
            "terminal_at": NOW + timedelta(minutes=1),
        }
    )
    endpoint = _endpoint(deployment)
    projection = GISServiceControlProjection(
        tenant_id=TENANT,
        service_urn=SERVICE_URN,
        endpoint_state_version=1,
        active_endpoint_revision=endpoint,
        active_deployment_revision=deployment,
        active_service_definition_version=definition,
        active_release_binding=release,
        active_layer_definition_version=layer,
        active_style_definition_version=style,
        active_tile_matrix_set_definition_version=tile_matrix,
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=3),
    )
    assert projection.active_endpoint_revision == endpoint

    with pytest.raises(ValidationError, match="complete or empty"):
        GISServiceControlProjection(
            tenant_id=TENANT,
            service_urn=SERVICE_URN,
            endpoint_state_version=1,
            active_endpoint_revision=endpoint,
            created_at=NOW,
            updated_at=NOW + timedelta(minutes=3),
        )


def test_active_release_projection_rejects_mixed_style_version():
    definition = _definition()
    layer, style, tile_matrix, release = _release_bundle(definition)
    deployment = _deployment(definition, release)
    endpoint = _endpoint(deployment)
    mismatched_values = {
        **style.model_dump(mode="python", exclude={"style_sha256"}),
        "style_definition_version_id": uuid4(),
    }
    mismatched_style = StyleDefinitionVersion(
        **mismatched_values,
        style_sha256=style_definition_fingerprint(mismatched_values),
    )
    with pytest.raises(ValidationError, match="release components do not match"):
        GISServiceControlProjection(
            tenant_id=TENANT,
            service_urn=SERVICE_URN,
            endpoint_state_version=1,
            active_endpoint_revision=endpoint,
            active_deployment_revision=deployment,
            active_service_definition_version=definition,
            active_release_binding=release,
            active_layer_definition_version=layer,
            active_style_definition_version=mismatched_style,
            active_tile_matrix_set_definition_version=tile_matrix,
            created_at=NOW,
            updated_at=NOW + timedelta(minutes=3),
        )
