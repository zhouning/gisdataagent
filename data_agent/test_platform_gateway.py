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
    PlatformCommand,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceVersion,
    RunStatus,
    SubjectContext,
    platform_definition_fingerprint,
    quality_result_fingerprint,
)
from data_agent.platform_gateway import (
    COMMAND_OUTBOX_MIGRATION,
    DefinitionRegistration,
    GATEWAY_ROLE_MIGRATION,
    GatewayConflictError,
    GatewayValidationError,
    GatewayWriteResult,
    PlatformGateway,
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


def _command():
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=UUID("00000000-0000-4000-8000-000000000070"),
        run_id=RUN_ID,
        command_type="dolphinscheduler.reconcile",
        execution_plan_artifact_id=DEFINITION_ID,
        trigger_observation_id=UUID("00000000-0000-4000-8000-000000000060"),
        dedupe_key="dolphinscheduler.reconcile:callback-1",
        actor_subject="workload:dataops-adapter",
        available_at=NOW,
        created_at=NOW,
    )


def _quality():
    quality_result_id = UUID("00000000-0000-4000-8000-0000000000a0")
    evidence_artifact_id = UUID("00000000-0000-4000-8000-0000000000b0")
    metrics = {"feature_count": 3, "geometry_errors": 0}
    return QualityResult(
        tenant_id=TENANT,
        quality_result_id=quality_result_id,
        run_id=RUN_ID,
        resource_version_id=DEFINITION_ID,
        rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=evidence_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=TENANT,
            run_id=RUN_ID,
            resource_version_id=DEFINITION_ID,
            rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
            verdict="passed",
            metrics=metrics,
            evidence_artifact_id=evidence_artifact_id,
            evaluated_by="workload:quality-evaluator",
            evaluated_at=NOW,
        ),
        evaluated_by="workload:quality-evaluator",
        evaluated_at=NOW,
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
    gateway.submit_run.side_effect = lambda run, **_kwargs: GatewayWriteResult(
        run, True
    )
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
    gateway.submit_run.side_effect = lambda run, **_kwargs: GatewayWriteResult(
        run, True
    )
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
        "request_dispatch": True,
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
    assert gateway.submit_run.call_args.kwargs == {"request_dispatch": True}


def test_dolphinscheduler_callback_requires_workload_and_enqueues_reconcile():
    command = _command()
    gateway = MagicMock()
    gateway.record_attempt_and_enqueue_reconcile.return_value = GatewayWriteResult(
        command, True
    )
    body = {
        "callback_id": "00000000-0000-4000-8000-000000000060",
        "attempt_no": 1,
        "project_code": 1001,
        "workflow_instance_id": 901,
        "workflow_definition_code": 701,
        "workflow_definition_version": 1,
        "provider_state": "SUCCESS",
        "observed_at": NOW.isoformat(),
    }
    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_dolphinscheduler_callback(request))
    assert rejected.status_code == 403

    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload", identifier="dataops-adapter"
            ),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_dolphinscheduler_callback(request))

    assert response.status_code == 202
    observation = gateway.record_attempt_and_enqueue_reconcile.call_args.args[0]
    assert observation.framework_kind.value == "dolphinscheduler"
    assert observation.observation_id == command.trigger_observation_id
    assert observation.observed_state == "success"
    assert gateway.record_attempt_and_enqueue_reconcile.call_args.kwargs == {
        "actor_subject": "workload:dataops-adapter"
    }


def test_quality_result_requires_evaluator_identity_and_preserves_contract():
    quality = _quality()
    gateway = MagicMock()
    gateway.record_quality_result.return_value = GatewayWriteResult(quality, True)
    body = quality.model_dump(mode="json")

    request = _request(body=body)
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_quality_result(request))
    assert rejected.status_code == 403

    request = _request(body=body)
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload", identifier="quality-evaluator"
            ),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_quality_result(request))
    assert response.status_code == 201
    assert gateway.record_quality_result.call_args.args == (quality,)


def test_success_finalization_requires_run_workload_and_builds_evidence():
    succeeded = _run().model_copy(
        update={"status": RunStatus.SUCCEEDED, "state_version": 3}
    )
    gateway = MagicMock()
    gateway.finalize_run_success.return_value = succeeded
    body = {
        "expected_state_version": 2,
        "attempt_observation_id": "00000000-0000-4000-8000-000000000050",
        "output_artifact_id": "00000000-0000-4000-8000-000000000060",
        "quality_result_id": "00000000-0000-4000-8000-000000000090",
        "lineage_event_id": "00000000-0000-4000-8000-000000000070",
        "reason": "all platform success evidence passed",
    }
    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.finalize_run_success(request))
    assert rejected.status_code == 403

    request = _request(body=body, path={"run_id": str(RUN_ID)})
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload", identifier="dataops-adapter"
            ),
        ),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.finalize_run_success(request))
    assert response.status_code == 200
    evidence = gateway.finalize_run_success.call_args.args[0]
    assert evidence.tenant_id == TENANT
    assert evidence.run_id == RUN_ID
    assert gateway.finalize_run_success.call_args.kwargs == {
        "expected_state_version": 2,
        "actor_subject": "workload:dataops-adapter",
        "reason": "all platform success evidence passed",
    }


def test_generic_gateway_transition_cannot_bypass_success_evidence_gate():
    with pytest.raises(GatewayValidationError, match="evidence-gated"):
        PlatformGateway().transition_run(
            TENANT,
            RUN_ID,
            2,
            "succeeded",
            "workload:dataops-adapter",
            "provider said success",
        )


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
    assert len(registered) == 12
    assert all(route.path.startswith("/api/platform/v1/") for route in registered)

    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    assert {route.path for route in registered}.issubset(mounted)


def test_platform_gateway_static_contract_and_fail_closed_role(tmp_path):
    report = build_gateway_report()
    assert report["status"] == "valid"
    assert report["database_role"] == "gda_control_gateway"
    assert report["route_count"] == 12

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

    unsafe_command = tmp_path / "unsafe_command.sql"
    unsafe_command.write_text(
        COMMAND_OUTBOX_MIGRATION.read_text(encoding="utf-8").replace(
            "FOR UPDATE SKIP LOCKED", "FOR UPDATE"
        ),
        encoding="utf-8",
    )
    unsafe_report = build_gateway_report(command_migration=unsafe_command)
    assert unsafe_report["status"] == "invalid"
    assert "command_migration" in unsafe_report["missing_markers"]
