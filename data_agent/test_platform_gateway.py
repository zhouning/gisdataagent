import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.platform_contracts import (
    PlatformRun,
    Resource,
    ResourceVersion,
    SubjectContext,
    platform_definition_fingerprint,
)
from data_agent.platform_gateway import (
    DefinitionRegistration,
    GATEWAY_ROLE_MIGRATION,
    GatewayConflictError,
    GatewayWriteResult,
    build_gateway_report,
)


TENANT = "tenant-a"
ACTOR = "human:operator-1"
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000010")
RUN_ID = UUID("00000000-0000-4000-8000-000000000020")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000000030")
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _request(*, body=None, path=None, headers=None):
    request = MagicMock()
    request.json = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = path or {}
    request.headers = headers or {"x-request-id": "request-1"}
    return request


def _user(
    role="platform_operator",
    tenant_id=TENANT,
    *,
    subject_type=None,
    identifier="operator-1",
):
    metadata = {"role": role, "tenant_id": tenant_id}
    if subject_type is not None:
        metadata["subject_type"] = subject_type
    return SimpleNamespace(
        identifier=identifier,
        metadata=metadata,
    )


def _resource(**overrides):
    values = {
        "tenant_id": TENANT,
        "resource_urn": "gda://tenant-a/dataset/source-parcels",
        "resource_kind": "dataset",
        "authority_system": "iceberg",
        "authority_locator": "geo.source_parcels",
        "owner_ref": "team:data-platform",
    }
    values.update(overrides)
    return Resource(**values)


def _version(**overrides):
    values = {
        "tenant_id": TENANT,
        "resource_urn": "gda://tenant-a/dataset/source-parcels",
        "resource_version_id": SOURCE_ID,
        "version_key": "snapshot-1",
        "content_sha256": "a" * 64,
        "authority_version_ref": {"snapshot": 1},
        "created_by": ACTOR,
        "created_at": NOW,
    }
    values.update(overrides)
    return ResourceVersion(**values)


def _run():
    return PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id="operator-1",
            subject_type="human",
            roles=("platform_operator",),
            purpose="publish parcels",
        ),
        input_bindings=(
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.land_use.parcels",
            },
        ),
        idempotency_key="publish:parcels:1",
        submitted_at=NOW,
    )


def test_definition_registration_requires_resource_version_identity_chain():
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="land_use.publish",
        portability_class="portable",
        definition_document={"tasks": ["publish"]},
        input_contract={"source": "dataset"},
        output_contract={"product": "dataset"},
    )
    definition_resource = _resource(
        resource_urn="gda://tenant-a/definition/parcel-publish",
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/parcel-publish",
    )
    definition_version = _version(
        resource_urn=definition_resource.resource_urn,
        resource_version_id=DEFINITION_ID,
        content_sha256=fingerprint,
    )
    definition = {
        "tenant_id": TENANT,
        "definition_urn": definition_resource.resource_urn,
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "capability_id": "land_use.publish",
        "portability_class": "portable",
        "definition_document": {"tasks": ["publish"]},
        "input_contract": {"source": "dataset"},
        "output_contract": {"product": "dataset"},
        "definition_sha256": fingerprint,
    }

    registration = DefinitionRegistration(
        resource=definition_resource,
        resource_version=definition_version,
        definition=definition,
    )

    assert registration.definition.definition_version_id == DEFINITION_ID
    with pytest.raises(ValidationError, match="IDs must match"):
        DefinitionRegistration(
            resource=definition_resource,
            resource_version=definition_version.model_copy(
                update={"resource_version_id": SOURCE_ID}
            ),
            definition=definition,
        )


def test_resource_route_requires_authentication_and_platform_role():
    request = _request(body=_resource().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=None):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 401

    with patch.object(
        routes, "_get_user_from_request", return_value=_user(role="analyst")
    ):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "platform_role_required"


def test_resource_route_fails_closed_without_tenant_and_rejects_tenant_override():
    request = _request(body=_resource().model_dump(mode="json"))
    with patch.object(
        routes, "_get_user_from_request", return_value=_user(tenant_id=None)
    ):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_context_required"

    other = _resource(
        tenant_id="tenant-b",
        resource_urn="gda://tenant-b/dataset/source-parcels",
    )
    request = _request(body=other.model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_resource(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"


def test_resource_route_distinguishes_created_and_idempotent_replay():
    resource = _resource()
    gateway = MagicMock()
    gateway.register_resource.side_effect = (
        GatewayWriteResult(resource, True),
        GatewayWriteResult(resource, False),
    )
    request = _request(body=resource.model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        created = asyncio.run(routes.create_resource(request))
        replay = asyncio.run(routes.create_resource(request))

    assert created.status_code == 201
    assert replay.status_code == 200
    assert json.loads(replay.body)["created"] is False


def test_resource_version_route_rejects_actor_spoofing():
    request = _request(
        body=_version(created_by="human:someone-else").model_dump(mode="json")
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_resource_version(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"


def test_run_route_derives_subject_and_tenant_from_authenticated_principal():
    gateway = MagicMock()
    gateway.submit_run.side_effect = lambda run: GatewayWriteResult(run, True)
    body = {
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_ID),
        "orchestration_class": "dataops",
        "input_bindings": [
            {
                "binding_name": "source",
                "resource_version_id": str(SOURCE_ID),
                "semantic_type": "gis.land_use.parcels",
            }
        ],
        "idempotency_key": "publish:parcels:1",
        "purpose": "publish parcels",
        "submitted_at": NOW.isoformat(),
    }
    request = _request(body=body)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_run(request))

    assert response.status_code == 201
    submitted = gateway.submit_run.call_args.args[0]
    assert submitted == _run()
    assert submitted.subject_context.tenant_id == TENANT
    assert submitted.subject_context.subject_id == "operator-1"


def test_run_route_preserves_policy_refs_for_workload_identity():
    gateway = MagicMock()
    gateway.submit_run.side_effect = lambda run: GatewayWriteResult(run, True)
    decision_id = UUID("00000000-0000-4000-8000-000000000080")
    approval_id = UUID("00000000-0000-4000-8000-000000000090")
    body = {
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_ID),
        "orchestration_class": "dataops",
        "input_bindings": [],
        "idempotency_key": "publish:authorized:1",
        "policy_refs": {
            "policy_decision_artifact_id": str(decision_id),
            "approval_artifact_id": str(approval_id),
        },
        "purpose": "execute authorized dataops run",
        "submitted_at": NOW.isoformat(),
    }
    request = _request(body=body)
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(subject_type="workload", identifier="dataops-adapter"),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_run(request))

    assert response.status_code == 201
    submitted = gateway.submit_run.call_args.args[0]
    assert submitted.subject_context.subject_type.value == "workload"
    assert submitted.policy_refs.policy_decision_artifact_id == decision_id
    assert submitted.policy_refs.approval_artifact_id == approval_id


def test_gateway_conflict_has_stable_safe_error_envelope():
    gateway = MagicMock()
    gateway.register_resource.side_effect = GatewayConflictError("identity conflict")
    request = _request(body=_resource().model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_resource(request))

    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["error"]["code"] == "platform_conflict"
    assert body["request_id"] == "request-1"


def test_run_transition_rejects_negative_state_version_at_http_boundary():
    request = _request(
        body={
            "expected_state_version": -1,
            "to_status": "dispatching",
            "reason": "invalid replay cursor",
        },
        path={"run_id": str(RUN_ID)},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.create_run_transition(request))

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "contract_validation_failed"


def test_platform_gateway_routes_are_versioned_and_registered():
    registered = routes.get_platform_gateway_routes()
    assert len(registered) == 9
    assert all(route.path.startswith("/api/platform/v1/") for route in registered)

    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    assert {route.path for route in registered}.issubset(mounted)


def test_platform_gateway_static_contract_and_fail_closed_role(tmp_path):
    report = build_gateway_report()
    assert report["status"] == "valid"
    assert report["database_role"] == "gda_control_gateway"
    assert report["route_count"] == 9

    unsafe = tmp_path / "unsafe_gateway.sql"
    unsafe.write_text(
        GATEWAY_ROLE_MIGRATION.read_text(encoding="utf-8").replace(
            "NOBYPASSRLS", "BYPASSRLS"
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(role_migration=unsafe)
    assert unsafe_report["status"] == "invalid"
    assert "role_migration" in unsafe_report["missing_markers"]
