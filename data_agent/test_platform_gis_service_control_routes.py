"""HTTP contracts for the governed GIS Service Control Plane entry points."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from data_agent.api import platform_gateway_routes as routes
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    EndpointRevision,
    GISServiceControlProjection,
    GISServiceSLOBinding,
    ServiceDeploymentEvent,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    endpoint_revision_fingerprint,
    service_deployment_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayWriteResult,
)

TENANT = "planning"
SERVICE_ID = "district-features"
SERVICE_URN = f"gda://{TENANT}/gis_service/{SERVICE_ID}"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
DEPLOYMENT_ID = UUID("00000000-0000-4000-8000-000000000701")
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000702")
OBSERVATION_ID = UUID("00000000-0000-4000-8000-000000000703")


def _user(
    *,
    role: str = "platform_operator",
    identifier: str = "operator",
    subject_type: str = "human",
):
    return SimpleNamespace(
        identifier=identifier,
        metadata={"role": role, "tenant_id": TENANT, "subject_type": subject_type},
    )


def _projection(*, endpoint_state_version: int = 0) -> GISServiceControlProjection:
    return GISServiceControlProjection(
        tenant_id=TENANT,
        service_urn=SERVICE_URN,
        endpoint_state_version=endpoint_state_version,
        created_at=NOW,
        updated_at=NOW,
    )


def _service_slo_binding() -> GISServiceSLOBinding:
    slo_ref = f"gda://{TENANT}/slo_definition/district-features-availability"
    return GISServiceSLOBinding(
        tenant_id=TENANT,
        binding_id=UUID("00000000-0000-4000-8000-000000000709"),
        service_urn=SERVICE_URN,
        slo_definition_ref=slo_ref,
        active_version_ref=f"{slo_ref}.v1",
        definition_fingerprint="d" * 64,
        approval_case_ref=f"gda://{TENANT}/approval_case/district-slo-v1",
        activation_version=1,
        bound_by="human:operator",
        binding_reason="bind the approved district feature objective",
        bound_at=NOW,
    )


def _deployment(
    state: ServiceDeploymentState = ServiceDeploymentState.PLANNED,
) -> ServiceDeploymentRevision:
    values = {
        "tenant_id": TENANT,
        "deployment_revision_id": DEPLOYMENT_ID,
        "service_definition_version_id": DEFINITION_ID,
        "service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000704"
        ),
        "run_id": UUID("00000000-0000-4000-8000-000000000705"),
        "revision_key": "r1",
        "provider_system": "martin",
        "provider_namespace": "planning-prod",
        "provider_deployment_id": "district-features",
        "provider_revision_ref": "deployment:17",
        "config_sha256": "a" * 64,
        "created_by": "workload:gis-deployment-controller",
        "created_at": NOW,
        "state": state,
        "state_version": 0 if state is ServiceDeploymentState.PLANNED else 1,
        "updated_at": (
            NOW
            if state is ServiceDeploymentState.PLANNED
            else NOW + timedelta(minutes=1)
        ),
    }
    if state in {ServiceDeploymentState.READY, ServiceDeploymentState.FAILED}:
        values.update(
            {
                "state_version": 2,
                "terminal_observation_id": OBSERVATION_ID,
                "terminal_at": NOW + timedelta(minutes=2),
                "updated_at": NOW + timedelta(minutes=2),
            }
        )
    return ServiceDeploymentRevision(
        **values,
        deployment_sha256=service_deployment_fingerprint(values),
    )


def _bind_deployment(
    gateway: MagicMock,
    *,
    service_urn: str = SERVICE_URN,
    deployment: ServiceDeploymentRevision | None = None,
):
    gateway.get_service_deployment_revision.return_value = deployment or _deployment()
    gateway.get_gis_service_definition_version.return_value = SimpleNamespace(
        service_urn=service_urn
    )


def _endpoint() -> EndpointRevision:
    values = {
        "tenant_id": TENANT,
        "endpoint_revision_id": UUID("00000000-0000-4000-8000-000000000706"),
        "service_urn": SERVICE_URN,
        "deployment_revision_id": DEPLOYMENT_ID,
        "endpoint_protocol": EndpointProtocol.MVT,
        "endpoint_uri": "https://martin.example.test/district-features",
        "endpoint_contract": {"schema": "gda.mvt_endpoint.v1"},
        "created_by": "workload:gis-deployment-controller",
        "created_at": NOW + timedelta(minutes=3),
    }
    return EndpointRevision(
        **values,
        endpoint_sha256=endpoint_revision_fingerprint(values),
    )


def _client() -> TestClient:
    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())
    return TestClient(app)


def _activation_payload(**changes):
    payload = {
        "endpoint_revision_id": str(uuid4()),
        "expected_state_version": 0,
        "reason": "activate the reviewed MVT endpoint",
        "idempotency_key": "gis-activation-001",
        "occurred_at": NOW.isoformat(),
    }
    payload.update(changes)
    return payload


def _transition_payload(**changes):
    payload = {
        "expected_state_version": 0,
        "to_state": "deploying",
        "reason": "provider deployment command was dispatched",
        "idempotency_key": "gis-deployment-transition-001",
        "occurred_at": NOW.isoformat(),
    }
    payload.update(changes)
    return payload


def _endpoint_payload(**changes):
    endpoint = _endpoint()
    payload = {
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
        "endpoint_protocol": endpoint.endpoint_protocol.value,
        "endpoint_uri": endpoint.endpoint_uri,
        "endpoint_contract": endpoint.endpoint_contract,
        "created_at": endpoint.created_at.isoformat(),
    }
    payload.update(changes)
    return payload


def _deployment_registration_payload(**changes):
    deployment = _deployment()
    payload = {
        "deployment_revision_id": str(deployment.deployment_revision_id),
        "service_definition_version_id": str(deployment.service_definition_version_id),
        "service_release_binding_id": str(deployment.service_release_binding_id),
        "run_id": str(deployment.run_id),
        "revision_key": deployment.revision_key,
        "provider_system": deployment.provider_system,
        "provider_namespace": deployment.provider_namespace,
        "provider_deployment_id": deployment.provider_deployment_id,
        "provider_revision_ref": deployment.provider_revision_ref,
        "config_sha256": deployment.config_sha256,
        "created_at": deployment.created_at.isoformat(),
    }
    payload.update(changes)
    return payload


def _deployment_event() -> ServiceDeploymentEvent:
    return ServiceDeploymentEvent(
        tenant_id=TENANT,
        event_id=UUID("00000000-0000-4000-8000-000000000707"),
        deployment_revision_id=DEPLOYMENT_ID,
        sequence_no=0,
        to_state=ServiceDeploymentState.PLANNED,
        actor_subject="workload:gis-deployment-controller",
        reason="deployment revision recorded",
        idempotency_key=f"planned:{DEPLOYMENT_ID}",
        event_sha256="b" * 64,
        occurred_at=NOW,
    )


def _deployment_observation_payload(**changes):
    payload = {
        "observation_id": str(UUID("00000000-0000-4000-8000-000000000708")),
        "attempt_no": 1,
        "framework_kind": "cloud",
        "observed_state": "ready",
        "provider_version": "0.18.0",
        "endpoint_uri": "https://martin.example.test/district-features",
        "health_evidence_sha256": "c" * 64,
        "provider_receipt": {"health_status": 200, "catalog": "verified"},
        "observed_at": NOW.isoformat(),
    }
    payload.update(changes)
    return payload


def _deployment_terminal_settlement_payload(**changes):
    payload = {
        **_deployment_observation_payload(),
        "expected_state_version": 1,
        "reason": "Martin health check reached terminal state",
        "idempotency_key": "gis-deployment-terminal-001",
        "occurred_at": (NOW + timedelta(minutes=2)).isoformat(),
    }
    payload.update(changes)
    return payload


def test_gis_service_control_projection_requires_platform_principal():
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/control-projection"
    with patch.object(routes, "_get_user_from_request", return_value=None):
        unauthenticated = _client().get(path)
    assert unauthenticated.status_code == 401

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(role="viewer"),
    ):
        denied = _client().get(path)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "platform_role_required"


def test_gis_service_control_projection_reads_only_tenant_scoped_service():
    gateway = MagicMock()
    gateway.get_gis_service_control_projection.return_value = _projection()
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/control-projection"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().get(path)

    assert response.status_code == 200
    assert response.json()["data"]["service_urn"] == SERVICE_URN
    gateway.get_gis_service_control_projection.assert_called_once_with(TENANT, SERVICE_URN)


def test_gis_service_slo_read_is_bound_to_authenticated_tenant_and_service():
    gateway = MagicMock()
    gateway.get_gis_service_slo_binding.return_value = _service_slo_binding()
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/slo"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().get(path)

    assert response.status_code == 200
    assert response.json()["data"]["service_urn"] == SERVICE_URN
    gateway.get_gis_service_slo_binding.assert_called_once_with(TENANT, SERVICE_URN)


def test_gis_service_slo_binding_derives_exact_active_authority_and_actor():
    binding = _service_slo_binding()
    authority = MagicMock()
    authority.active.return_value = (
        SimpleNamespace(
            version=1,
            service_resource_urn=SERVICE_URN,
            slo_definition_ref=binding.slo_definition_ref,
            slo_version_ref=binding.active_version_ref,
            definition_fingerprint=binding.definition_fingerprint,
        ),
        SimpleNamespace(
            approval_case_ref=binding.approval_case_ref,
            activation_version=1,
        ),
    )
    gateway = MagicMock()
    gateway.bind_gis_service_slo.return_value = GatewayWriteResult(binding, True)
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/slo-binding"
    payload = {
        "slo_definition_id": "district-features-availability",
        "version": 1,
        "expected_activation_version": 1,
        "reason": binding.binding_reason,
    }
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin"),
        ),
        patch.object(routes, "_slo_authority", return_value=authority),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = _client().post(path, json=payload)

    assert response.status_code == 201
    recorded = gateway.bind_gis_service_slo.call_args.args[0]
    assert recorded.tenant_id == TENANT
    assert recorded.service_urn == SERVICE_URN
    assert recorded.bound_by == "human:operator"
    assert recorded.active_version_ref == binding.active_version_ref
    assert recorded.activation_version == 1


def test_gis_service_slo_binding_rejects_non_admin_and_service_mismatch():
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/slo-binding"
    payload = {
        "slo_definition_id": "district-features-availability",
        "version": 1,
        "expected_activation_version": 1,
        "reason": "bind the approved objective",
    }
    gateway = MagicMock()
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        denied = _client().post(path, json=payload)
    assert denied.status_code == 403

    authority = MagicMock()
    authority.active.return_value = (
        SimpleNamespace(
            version=1,
            service_resource_urn=f"gda://{TENANT}/gis_service/other",
        ),
        SimpleNamespace(activation_version=1),
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin"),
        ),
        patch.object(routes, "_slo_authority", return_value=authority),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        mismatch = _client().post(path, json=payload)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "gis_service_slo_service_mismatch"
    gateway.bind_gis_service_slo.assert_not_called()


def test_gis_service_control_projection_rejects_invalid_id_and_maps_not_found():
    invalid_path = "/api/platform/v1/gis/services/Not-Canonical/control-projection"
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid = _client().get(invalid_path)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_gis_service_id"
    gateway.get_gis_service_control_projection.assert_not_called()

    gateway.get_gis_service_control_projection.side_effect = GatewayNotFoundError(
        "GIS service was not found"
    )
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/control-projection"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        missing = _client().get(path)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "platform_not_found"


def test_gis_service_deployment_read_checks_service_ownership():
    gateway = MagicMock()
    _bind_deployment(gateway)
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/{DEPLOYMENT_ID}"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().get(path)

    assert response.status_code == 200
    assert response.json()["data"]["deployment_revision_id"] == str(DEPLOYMENT_ID)
    gateway.get_service_deployment_revision.assert_called_once_with(
        TENANT,
        DEPLOYMENT_ID,
    )
    gateway.get_gis_service_definition_version.assert_called_once_with(
        TENANT,
        DEFINITION_ID,
    )


def test_gis_service_deployment_event_timeline_is_service_bound_and_read_only():
    gateway = MagicMock()
    _bind_deployment(gateway)
    event = _deployment_event()
    gateway.list_service_deployment_events.return_value = (event,)
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/events"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().get(path)

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert response.json()["data"]["items"][0]["event_id"] == str(event.event_id)
    gateway.list_service_deployment_events.assert_called_once_with(TENANT, DEPLOYMENT_ID)


def test_gis_service_deployment_observation_is_workload_bound_and_server_bound():
    gateway = MagicMock()
    deploying = _deployment(ServiceDeploymentState.DEPLOYING)
    _bind_deployment(gateway, deployment=deploying)
    observed = SimpleNamespace(
        value=SimpleNamespace(model_dump=lambda **_: {}),
        created=True,
    )
    gateway.record_gis_service_deployment_observation.return_value = observed
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/observations"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_deployment_observation_payload())

    assert response.status_code == 201
    recorded = gateway.record_gis_service_deployment_observation.call_args.args
    assert recorded[0] == DEPLOYMENT_ID
    observation = recorded[1]
    assert observation.tenant_id == TENANT
    assert observation.run_id == deploying.run_id
    assert observation.external_namespace == "planning-prod"
    assert observation.evidence["service_release_binding_id"] == str(
        deploying.service_release_binding_id
    )
    assert observation.evidence["provider_deployment_id"] == "district-features"
    assert observation.evidence["reported_by"] == "workload:operator"


def test_gis_service_deployment_observation_rejects_human_and_bad_endpoint():
    gateway = MagicMock()
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/observations"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        human = _client().post(path, json=_deployment_observation_payload())
    assert human.status_code == 403
    assert human.json()["error"]["code"] == "gis_service_deployment_workload_required"
    gateway.get_service_deployment_revision.assert_not_called()

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid = _client().post(
            path,
            json=_deployment_observation_payload(endpoint_uri="http://martin.test"),
        )
    assert invalid.status_code == 422
    gateway.get_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_terminal_settlement_is_workload_bound_and_atomic():
    gateway = MagicMock()
    deploying = _deployment(ServiceDeploymentState.DEPLOYING)
    _bind_deployment(gateway, deployment=deploying)
    gateway.settle_gis_service_deployment_terminal.return_value = SimpleNamespace(
        observation_created=True,
        model_dump=lambda **_: {"deployment": {"state": "ready"}},
    )
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/terminal-settlements"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(
            path,
            json=_deployment_terminal_settlement_payload(),
        )

    assert response.status_code == 201
    args, kwargs = gateway.settle_gis_service_deployment_terminal.call_args
    assert args[0] == DEPLOYMENT_ID
    observation = args[1]
    assert observation.run_id == deploying.run_id
    assert observation.evidence["deployment_revision_id"] == str(DEPLOYMENT_ID)
    assert observation.evidence["reported_by"] == "workload:operator"
    assert kwargs == {
        "expected_state_version": 1,
        "actor_subject": "workload:operator",
        "reason": "Martin health check reached terminal state",
        "idempotency_key": "gis-deployment-terminal-001",
        "occurred_at": NOW + timedelta(minutes=2),
    }
    gateway.record_gis_service_deployment_observation.assert_not_called()
    gateway.transition_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_terminal_settlement_rejects_human_and_bad_chronology():
    gateway = MagicMock()
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/terminal-settlements"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        human = _client().post(path, json=_deployment_terminal_settlement_payload())
    assert human.status_code == 403
    assert human.json()["error"]["code"] == "gis_service_deployment_workload_required"
    gateway.get_service_deployment_revision.assert_not_called()

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid = _client().post(
            path,
            json=_deployment_terminal_settlement_payload(
                occurred_at=(NOW - timedelta(seconds=1)).isoformat(),
            ),
        )
    assert invalid.status_code == 422
    gateway.get_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_rejects_invalid_id_and_service_mismatch():
    gateway = MagicMock()
    _bind_deployment(gateway)
    invalid_path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/not-a-uuid"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid = _client().get(invalid_path)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_gis_deployment_revision_id"
    gateway.get_service_deployment_revision.assert_not_called()

    _bind_deployment(gateway, service_urn="gda://planning/gis_service/other")
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/{DEPLOYMENT_ID}"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        mismatched = _client().get(path)
    assert mismatched.status_code == 404
    assert mismatched.json()["error"]["code"] == "gis_service_deployment_not_found"

    events_path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/events"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        events = _client().get(events_path)
    assert events.status_code == 404
    gateway.list_service_deployment_events.assert_not_called()


def test_gis_service_deployment_registration_requires_workload_identity():
    gateway = MagicMock()
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments"
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_deployment_registration_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "gis_service_deployment_workload_required"
    gateway.get_gis_service_definition_version.assert_not_called()
    gateway.register_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_registration_binds_service_release_and_actor():
    gateway = MagicMock()
    deployment = _deployment()
    gateway.get_gis_service_definition_version.return_value = SimpleNamespace(
        service_urn=SERVICE_URN
    )
    gateway.get_service_release_binding.return_value = SimpleNamespace(
        service_definition_version_id=DEFINITION_ID
    )
    gateway.register_service_deployment_revision.return_value = SimpleNamespace(
        value=deployment,
        created=True,
    )
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments"
    workload = _user(
        identifier="gis-deployment-controller",
        subject_type="workload",
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_deployment_registration_payload())

    assert response.status_code == 201
    assert response.json()["created"] is True
    registered = gateway.register_service_deployment_revision.call_args.args[0]
    assert registered.tenant_id == TENANT
    assert registered.created_by == "workload:gis-deployment-controller"
    assert registered.service_release_binding_id == deployment.service_release_binding_id
    assert registered.state is ServiceDeploymentState.PLANNED
    assert registered.state_version == 0
    assert registered.deployment_sha256 == service_deployment_fingerprint(registered)


def test_gis_service_deployment_registration_rejects_release_for_other_definition():
    gateway = MagicMock()
    gateway.get_gis_service_definition_version.return_value = SimpleNamespace(
        service_urn=SERVICE_URN
    )
    gateway.get_service_release_binding.return_value = SimpleNamespace(
        service_definition_version_id=uuid4()
    )
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments"
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_deployment_registration_payload())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "gis_service_release_not_found"
    gateway.register_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_registration_maps_run_evidence_conflict():
    gateway = MagicMock()
    provider_constructor = MagicMock()
    gateway.get_gis_service_definition_version.return_value = SimpleNamespace(
        service_urn=SERVICE_URN
    )
    gateway.get_service_release_binding.return_value = SimpleNamespace(
        service_definition_version_id=DEFINITION_ID
    )
    gateway.register_service_deployment_revision.side_effect = GatewayConflictError(
        "service deployment Run does not bind the service definition"
    )
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments"
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
    ):
        response = _client().post(path, json=_deployment_registration_payload())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_conflict"
    provider_constructor.assert_not_called()


def test_gis_service_deployment_transition_requires_workload_identity():
    gateway = MagicMock()
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/transitions"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="admin-01"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_transition_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == (
        "gis_service_deployment_workload_required"
    )
    gateway.transition_service_deployment_revision.assert_not_called()


def test_gis_service_deployment_transition_delegates_run_bound_event():
    gateway = MagicMock()
    _bind_deployment(gateway)
    gateway.transition_service_deployment_revision.return_value = _deployment(
        ServiceDeploymentState.DEPLOYING
    )
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/transitions"
    )
    workload = _user(
        identifier="gis-deployment-controller",
        subject_type="workload",
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_transition_payload())

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "deploying"
    gateway.transition_service_deployment_revision.assert_called_once_with(
        TENANT,
        DEPLOYMENT_ID,
        expected_state_version=0,
        to_state=ServiceDeploymentState.DEPLOYING,
        provider_observation_id=None,
        actor_subject="workload:gis-deployment-controller",
        reason="provider deployment command was dispatched",
        idempotency_key="gis-deployment-transition-001",
        occurred_at=NOW,
    )


def test_gis_service_deployment_transition_validates_observation_shape():
    gateway = MagicMock()
    _bind_deployment(gateway)
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/transitions"
    )
    workload = _user(subject_type="workload")
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        missing_terminal_evidence = _client().post(
            path,
            json=_transition_payload(to_state="ready", expected_state_version=1),
        )
        deploying_with_evidence = _client().post(
            path,
            json=_transition_payload(provider_observation_id=str(OBSERVATION_ID)),
        )
        transition_to_planned = _client().post(
            path,
            json=_transition_payload(to_state="planned"),
        )

    assert missing_terminal_evidence.status_code == 422
    assert deploying_with_evidence.status_code == 422
    assert transition_to_planned.status_code == 422
    gateway.get_service_deployment_revision.assert_not_called()
    gateway.transition_service_deployment_revision.assert_not_called()


def test_gis_service_terminal_deployment_transition_maps_cas_conflict():
    gateway = MagicMock()
    provider_constructor = MagicMock()
    _bind_deployment(gateway)
    gateway.transition_service_deployment_revision.side_effect = GatewayConflictError(
        "deployment state version conflict"
    )
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/transitions"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
    ):
        response = _client().post(
            path,
            json=_transition_payload(
                to_state="ready",
                expected_state_version=1,
                provider_observation_id=str(OBSERVATION_ID),
            ),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_conflict"
    provider_constructor.assert_not_called()


def test_gis_service_endpoint_registration_requires_workload_identity():
    gateway = MagicMock()
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/endpoints"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_endpoint_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "gis_service_endpoint_workload_required"
    gateway.get_service_deployment_revision.assert_not_called()
    gateway.register_endpoint_revision.assert_not_called()


def test_gis_service_endpoint_registration_builds_server_owned_endpoint_contract():
    gateway = MagicMock()
    ready = _deployment(ServiceDeploymentState.READY)
    _bind_deployment(gateway, deployment=ready)
    endpoint = _endpoint()
    gateway.register_endpoint_revision.return_value = SimpleNamespace(
        value=endpoint,
        created=True,
    )
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/endpoints"
    )
    workload = _user(
        identifier="gis-deployment-controller",
        subject_type="workload",
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=_endpoint_payload())

    assert response.status_code == 201
    assert response.json()["created"] is True
    registered = gateway.register_endpoint_revision.call_args.args[0]
    assert registered.tenant_id == TENANT
    assert registered.service_urn == SERVICE_URN
    assert registered.deployment_revision_id == DEPLOYMENT_ID
    assert registered.created_by == "workload:gis-deployment-controller"
    assert registered.endpoint_sha256 == endpoint_revision_fingerprint(registered)


def test_gis_service_endpoint_registration_rejects_bad_contract_before_authority():
    gateway = MagicMock()
    _bind_deployment(gateway, deployment=_deployment(ServiceDeploymentState.READY))
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/endpoints"
    )
    workload = _user(subject_type="workload")
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid_uri = _client().post(
            path,
            json=_endpoint_payload(endpoint_uri="http://martin.example.test/tiles"),
        )

    assert invalid_uri.status_code == 422
    assert invalid_uri.json()["error"]["code"] == "gis_service_endpoint_invalid"
    gateway.register_endpoint_revision.assert_not_called()


def test_gis_service_endpoint_registration_maps_ready_gate_conflict_without_provider_call():
    gateway = MagicMock()
    provider_constructor = MagicMock()
    _bind_deployment(gateway, deployment=_deployment(ServiceDeploymentState.PLANNED))
    gateway.register_endpoint_revision.side_effect = GatewayConflictError(
        "endpoint revision requires a ready deployment for this service"
    )
    path = (
        f"/api/platform/v1/gis/services/{SERVICE_ID}/deployments/"
        f"{DEPLOYMENT_ID}/endpoints"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
    ):
        response = _client().post(path, json=_endpoint_payload())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_conflict"
    provider_constructor.assert_not_called()


def test_gis_service_endpoint_activation_is_admin_only_and_delegates_cas_event():
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/activation"
    payload = _activation_payload()
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(role="platform_operator"),
    ):
        denied = _client().post(path, json=payload)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "gis_service_activation_admin_required"

    gateway = MagicMock()
    gateway.activate_gis_service_endpoint.return_value = _projection(
        endpoint_state_version=1
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin", identifier="admin-01"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = _client().post(path, json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["endpoint_state_version"] == 1
    gateway.activate_gis_service_endpoint.assert_called_once_with(
        TENANT,
        SERVICE_URN,
        UUID(payload["endpoint_revision_id"]),
        expected_state_version=0,
        actor_subject="human:admin-01",
        reason="activate the reviewed MVT endpoint",
        idempotency_key="gis-activation-001",
        occurred_at=NOW,
    )


def test_gis_service_endpoint_activation_rejects_invalid_contract_before_authority():
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/activation"
    gateway = MagicMock()
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        invalid_uuid = _client().post(
            path,
            json=_activation_payload(endpoint_revision_id="not-a-uuid"),
        )
        naive_time = _client().post(
            path,
            json=_activation_payload(occurred_at="2026-08-21T12:00:00"),
        )

    assert invalid_uuid.status_code == 422
    assert naive_time.status_code == 422
    gateway.activate_gis_service_endpoint.assert_not_called()


def test_gis_service_endpoint_activation_maps_cas_conflict_without_provider_call():
    path = f"/api/platform/v1/gis/services/{SERVICE_ID}/activation"
    gateway = MagicMock()
    provider_constructor = MagicMock()
    gateway.activate_gis_service_endpoint.side_effect = GatewayConflictError(
        "endpoint active pointer state version conflict"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(role="admin"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "MartinVectorTileProvider", provider_constructor),
    ):
        response = _client().post(path, json=_activation_payload())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_conflict"
    provider_constructor.assert_not_called()


def test_gis_service_control_routes_are_registered_with_platform_auth_contract():
    schema = _client().get("/openapi.json").json()
    control = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/control-projection"
    ]["get"]
    deployment = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}"
    ]["get"]
    deployment_events = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/events"
    ]["get"]
    deployment_observation = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/observations"
    ]["post"]
    deployment_terminal_settlement = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/terminal-settlements"
    ]["post"]
    deployment_registration = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments"
    ]["post"]
    transition = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/transitions"
    ]["post"]
    endpoint = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/deployments/{deployment_revision_id}/endpoints"
    ]["post"]
    activation = schema["paths"][
        "/api/platform/v1/gis/services/{service_id}/activation"
    ]["post"]

    assert control["operationId"] == "platform_get_gis_service_control_projection"
    assert deployment["operationId"] == "platform_get_gis_service_deployment"
    assert (
        deployment_events["operationId"]
        == "platform_list_gis_service_deployment_events"
    )
    assert (
        deployment_observation["operationId"]
        == "platform_record_gis_service_deployment_observation"
    )
    assert (
        deployment_terminal_settlement["operationId"]
        == "platform_settle_gis_service_deployment_terminal"
    )
    assert (
        deployment_registration["operationId"]
        == "platform_register_gis_service_deployment"
    )
    assert transition["operationId"] == "platform_transition_gis_service_deployment"
    assert endpoint["operationId"] == "platform_register_gis_service_endpoint"
    assert activation["operationId"] == "platform_activate_gis_service_endpoint"
    assert control["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert deployment["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert deployment_events["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert deployment_observation["security"] == [
        {"OAuth2PasswordBearerWithCookie": []}
    ]
    assert deployment_terminal_settlement["security"] == [
        {"OAuth2PasswordBearerWithCookie": []}
    ]
    assert deployment_registration["security"] == [
        {"OAuth2PasswordBearerWithCookie": []}
    ]
    assert transition["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert endpoint["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
    assert activation["security"] == [{"OAuth2PasswordBearerWithCookie": []}]
