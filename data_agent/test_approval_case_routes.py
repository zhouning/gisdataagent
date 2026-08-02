import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from data_agent.api import platform_gateway_routes as routes
from data_agent.approval_case_authority import (
    ApprovalCaseConflictError,
    ApprovalCaseValidationError,
    ApprovalCaseWriteResult,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseEvent,
    ApprovalCaseStatus,
)

TENANT = "tenant-a"
ACTOR = "human:operator-1"
APPROVAL_CASE_REF = "gda://tenant-a/approval_case/schema-drift-1"
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _request(*, body=None, path=None):
    request = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = path or {}
    request.headers = {"x-request-id": "request-1"}
    return request


def _user(*, subject_type=None, identifier="operator-1"):
    metadata = {"role": "platform_operator", "tenant_id": TENANT}
    if subject_type is not None:
        metadata["subject_type"] = subject_type
    return SimpleNamespace(identifier=identifier, metadata=metadata)


def _approval_case(**overrides):
    values = {
        "tenant_id": TENANT,
        "approval_case_ref": APPROVAL_CASE_REF,
        "target_resource_urn": "gda://tenant-a/schema_drift/" + "a" * 64,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "requester_subject": ACTOR,
        "request_reason": "review breaking source schema drift",
        "request_context": {"compatibility": "breaking"},
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=4),
    }
    values.update(overrides)
    return ApprovalCase(**values)


def _create_body():
    return {
        "case_id": "schema-drift-1",
        "target_resource_urn": "gda://tenant-a/schema_drift/" + "a" * 64,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "request_reason": "review breaking source schema drift",
        "request_context": {"compatibility": "breaking"},
        "requested_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
    }


def test_create_derives_tenant_requester_and_resource_identity():
    authority = MagicMock()
    authority.create.side_effect = lambda case, **_kwargs: ApprovalCaseWriteResult(
        case, True
    )
    request = _request(body=_create_body())
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(
                subject_type="workload", identifier="schema-drift-observer"
            ),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
        patch.dict(
            routes.os.environ,
            {"GDA_APPROVAL_CASE_OWNER_REF": "team:data-governance"},
        ),
    ):
        response = asyncio.run(routes.create_approval_case(request))

    assert response.status_code == 201
    created = authority.create.call_args.args[0]
    assert created.approval_case_ref == APPROVAL_CASE_REF
    assert created.requester_subject == "workload:schema-drift-observer"
    assert authority.create.call_args.kwargs == {"owner_ref": "team:data-governance"}


def test_create_rejects_spoofed_identity_and_maps_conflict():
    body = {**_create_body(), "tenant_id": "tenant-b"}
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.create_approval_case(_request(body=body)))
    assert rejected.status_code == 422

    authority = MagicMock()
    authority.create.side_effect = ApprovalCaseConflictError("immutable conflict")
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        conflict = asyncio.run(routes.create_approval_case(_request(body=_create_body())))
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == "approval_case_conflict"


def test_get_and_events_are_tenant_scoped():
    event = ApprovalCaseEvent(
        tenant_id=TENANT,
        approval_event_id=UUID("00000000-0000-4000-8000-000000000091"),
        approval_case_ref=APPROVAL_CASE_REF,
        sequence_no=0,
        to_status="pending",
        actor_subject=ACTOR,
        reason="review breaking source schema drift",
        occurred_at=NOW,
    )
    authority = MagicMock()
    authority.get.return_value = _approval_case()
    authority.events.return_value = (event,)
    request = _request(path={"case_id": "schema-drift-1"})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        fetched = asyncio.run(routes.get_approval_case(request))
        listed = asyncio.run(routes.list_approval_case_events(request))

    assert fetched.status_code == 200
    assert json.loads(listed.body)["data"]["count"] == 1
    assert authority.get.call_args.args == (TENANT, APPROVAL_CASE_REF)
    assert authority.events.call_args.args == (TENANT, APPROVAL_CASE_REF)


def test_decision_requires_human_and_injects_actor():
    body = {
        "expected_state_version": 0,
        "verdict": "approved",
        "reason": "compatibility plan is acceptable",
        "details": {"ticket": "GOV-101"},
    }
    request = _request(body=body, path={"case_id": "schema-drift-1"})
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload", identifier="auto-approver"),
    ):
        rejected = asyncio.run(routes.decide_approval_case(request))
    assert rejected.status_code == 403

    authority = MagicMock()
    authority.decide.return_value = _approval_case(
        status="approved",
        state_version=1,
        decided_by="human:data-steward",
        decision_reason="compatibility plan is acceptable",
        decided_at=NOW + timedelta(minutes=5),
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(identifier="data-steward"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(
            routes.decide_approval_case(
                _request(body=body, path={"case_id": "schema-drift-1"})
            )
        )

    assert response.status_code == 200
    assert authority.decide.call_args.kwargs["verdict"] is ApprovalCaseStatus.APPROVED
    assert authority.decide.call_args.kwargs["actor_subject"] == "human:data-steward"


def test_decision_rejects_pending_and_maps_authority_validation():
    pending = _request(
        body={
            "expected_state_version": 0,
            "verdict": "pending",
            "reason": "not terminal",
        },
        path={"case_id": "schema-drift-1"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(routes.decide_approval_case(pending))
    assert json.loads(rejected.body)["error"]["code"] == "terminal_verdict_required"

    authority = MagicMock()
    authority.decide.side_effect = ApprovalCaseValidationError("self approval")
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        rejected = asyncio.run(
            routes.decide_approval_case(
                _request(
                    body={
                        "expected_state_version": 0,
                        "verdict": "approved",
                        "reason": "self approval must fail",
                    },
                    path={"case_id": "schema-drift-1"},
                )
            )
        )
    assert rejected.status_code == 422
    assert json.loads(rejected.body)["error"]["code"] == "approval_case_validation_error"
