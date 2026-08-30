from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from data_agent.gis_provider_runtime import GISProviderContractError
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    GISServiceType,
    ServiceDeploymentState,
)
from data_agent.test_gis_provider_runtime import _release_and_tms
from scripts.certify_martin_provider import _active_release_context, certify

SERVICE_URN = "gda://planning/gis_service/district-features"


def _gateway(*, endpoint_contract: dict | None = None) -> MagicMock:
    release, tile_matrix_set, serving_projection = _release_and_tms()
    endpoint_contract = endpoint_contract or {
        "schema": "gda.mvt_endpoint.v1",
        "provider_layer_ref": "gda_mvt_serving_projection",
        "provider_query": {
            "serving_projection_version_id": str(
                serving_projection.mvt_serving_projection_version_id
            )
        },
    }
    projection = SimpleNamespace(
        active_release_binding=release,
        active_tile_matrix_set_definition_version=tile_matrix_set,
        active_mvt_serving_projection_version=serving_projection,
        active_service_definition_version=SimpleNamespace(
            service_type=GISServiceType.VECTOR_TILE
        ),
        active_deployment_revision=SimpleNamespace(
            provider_system="martin",
            state=ServiceDeploymentState.READY,
            deployment_revision_id=uuid4(),
        ),
        active_endpoint_revision=SimpleNamespace(
            endpoint_protocol=EndpointProtocol.MVT,
            endpoint_contract=endpoint_contract,
            endpoint_uri="https://tiles.example.test/district-features",
            endpoint_revision_id=uuid4(),
        ),
        endpoint_state_version=3,
    )
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = projection
    return gateway


def test_active_release_certification_context_is_loaded_from_existing_authority():
    gateway = _gateway()

    context, target = _active_release_context(
        gateway,
        tenant_id="planning",
        service_urn=SERVICE_URN,
    )

    assert context.provider_layer_ref == "gda_mvt_serving_projection"
    assert context.provider_query == {
        "serving_projection_version_id": str(
            context.mvt_serving_projection_version_id
        )
    }
    assert target["service_urn"] == SERVICE_URN
    assert target["deployment_revision_id"]
    gateway.get_gis_service_control_projection.assert_called_once_with(
        "planning", SERVICE_URN
    )


def test_active_release_certification_rejects_endpoint_without_exact_projection():
    gateway = _gateway(
        endpoint_contract={
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": {"serving_projection_version_id": str(uuid4())},
        }
    )

    with pytest.raises(GISProviderContractError, match="does not bind"):
        _active_release_context(
            gateway,
            tenant_id="planning",
            service_urn=SERVICE_URN,
        )


def test_certification_rejects_partial_active_release_configuration():
    with pytest.raises(GISProviderContractError, match="requires database_url"):
        certify("http://martin:3000", tenant_id="planning")
