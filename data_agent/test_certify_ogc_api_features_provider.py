from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from data_agent.gis_provider_runtime import GISProviderContractError
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    ServiceDeploymentState,
)
from data_agent.test_gis_service_control_plane import _definition, _release_bundle
from scripts.certify_ogc_api_features_provider import _active_release_context

SERVICE_URN = "gda://planning/gis_service/district-features"


def _gateway(*, contract: dict | None = None) -> MagicMock:
    definition = _definition()
    layer, _style, _tms, release = _release_bundle(definition)
    contract = contract or {
        "schema": "gda.ogc_api_features_endpoint.v1",
        "collection_id": layer.layer_key,
    }
    projection = SimpleNamespace(
        active_release_binding=release,
        active_layer_definition_version=layer,
        active_service_definition_version=definition,
        active_deployment_revision=SimpleNamespace(
            provider_system="pygeoapi",
            state=ServiceDeploymentState.READY,
            deployment_revision_id=uuid4(),
        ),
        active_endpoint_revision=SimpleNamespace(
            endpoint_protocol=EndpointProtocol.OGC_API_FEATURES,
            endpoint_contract=contract,
            endpoint_uri="https://geo.example.test/districts",
            endpoint_revision_id=uuid4(),
        ),
        endpoint_state_version=4,
    )
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = projection
    return gateway


def test_active_release_context_uses_existing_gateway_authority():
    gateway = _gateway()
    context, target = _active_release_context(
        gateway,
        tenant_id="planning",
        service_urn=SERVICE_URN,
    )

    assert context.collection_id == "districts"
    assert target["service_urn"] == SERVICE_URN
    assert target["service_release_binding_id"]
    gateway.get_gis_service_control_projection.assert_called_once_with(
        "planning", SERVICE_URN
    )


def test_active_release_context_rejects_generic_or_wrong_endpoint_contract():
    with pytest.raises(GISProviderContractError, match="unsupported contract"):
        _active_release_context(
            _gateway(contract={"schema": "gda.endpoint_revision.v1"}),
            tenant_id="planning",
            service_urn=SERVICE_URN,
        )

    with pytest.raises(GISProviderContractError, match="collection_id"):
        _active_release_context(
            _gateway(
                contract={"schema": "gda.ogc_api_features_endpoint.v1"}
            ),
            tenant_id="planning",
            service_urn=SERVICE_URN,
        )
