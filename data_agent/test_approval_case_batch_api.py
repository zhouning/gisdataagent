from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from data_agent.api import platform_gateway_routes as routes
from data_agent.approval_case_authority import ApprovalCaseConfigurationError
from data_agent.approval_case_batch import (
    ApprovalCaseBatchEscalationItem,
    ApprovalCaseBatchEscalationRequest,
    ApprovalCaseBatchEscalationResponse,
    ApprovalCaseBatchEscalationResult,
)
from data_agent.capability_registry import APPROVAL_CASE_BATCH_ESCALATION
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_schedule_approval_case_batch_escalation,
)
from data_agent.platform_contracts import (
    ApprovalCaseEscalation,
    approval_case_escalation_idempotency_key,
)
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)

TENANT = "tenant-a"
NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _item(case_id: str = "case-1") -> ApprovalCaseBatchEscalationItem:
    return ApprovalCaseBatchEscalationItem(
        approval_case_ref=f"gda://{TENANT}/approval_case/{case_id}",
        expected_state_version=0,
        escalation_stage=1,
        due_at=NOW + timedelta(minutes=5),
        target_team_subject="team:data-governance",
        on_call_ref="oncall:data-governance",
        reason=f"Escalate {case_id}",
    )


def _batch(*, actor: str = "human:operator-1") -> ApprovalCaseBatchEscalationRequest:
    return ApprovalCaseBatchEscalationRequest(
        tenant_id=TENANT,
        actor_subject=actor,
        items=(_item(),),
    )


def _result(request: ApprovalCaseBatchEscalationRequest) -> ApprovalCaseBatchEscalationResponse:
    item = request.items[0]
    escalation = ApprovalCaseEscalation(
        tenant_id=TENANT,
        escalation_id=UUID("00000000-0000-4000-8000-000000000121"),
        approval_case_ref=item.approval_case_ref,
        expected_state_version=item.expected_state_version,
        action="data_product.release",
        target_fingerprint="a" * 64,
        escalation_stage=item.escalation_stage,
        due_at=item.due_at,
        target_team_subject=item.target_team_subject,
        on_call_ref=item.on_call_ref,
        actor_subject=request.actor_subject,
        reason=item.reason,
        idempotency_key=approval_case_escalation_idempotency_key(
            tenant_id=TENANT,
            approval_case_ref=item.approval_case_ref,
            expected_state_version=item.expected_state_version,
            action="data_product.release",
            target_fingerprint="a" * 64,
            escalation_stage=item.escalation_stage,
            due_at=item.due_at,
            target_team_subject=item.target_team_subject,
            on_call_ref=item.on_call_ref,
        ),
        created_at=NOW,
    )
    return ApprovalCaseBatchEscalationResponse(
        tenant_id=TENANT,
        actor_subject=request.actor_subject,
        request_sha256=request.request_sha256,
        requested_count=1,
        scheduled_count=1,
        conflict_count=0,
        not_found_count=0,
        forbidden_count=0,
        rejected_count=0,
        results=(
            ApprovalCaseBatchEscalationResult(
                item_index=0,
                approval_case_ref=item.approval_case_ref,
                outcome="scheduled",
                escalation=escalation,
            ),
        ),
    )


def _request(*, body: dict | None = None, headers: dict | None = None) -> MagicMock:
    request = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, role: str = "platform_operator", tenant: str = TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant, "subject_type": "human"},
    )


def test_capability_registers_canonical_api_and_agent_contract() -> None:
    spec = APPROVAL_CASE_BATCH_ESCALATION
    surfaces = {binding.surface.value: binding.status.value for binding in spec.surfaces}

    assert spec.policy.action == "agentops.approval-case.batch-escalate"
    assert spec.execution.idempotency.value == "optional"
    assert surfaces["api"] == "implemented"
    assert surfaces["sdk"] == "implemented"
    assert surfaces["agent"] == "implemented"
    assert spec.mcp is not None
    assert spec.mcp.tool_name == "schedule_approval_case_batch_escalation"
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
    assert spec.validate_input(_batch().model_dump(mode="json"))["tenant_id"] == TENANT
    assert spec.validate_output(_result(_batch()).model_dump(mode="json"))[
        "scheduled_count"
    ] == 1
    assert spec.http is not None
    assert spec.http.path in spec.openapi_projection()["paths"]
    assert "schedule_approval_case_batch_escalation" in _get_tool_functions()
    assert any(
        item["name"] == "schedule_approval_case_batch_escalation"
        for item in TOOL_DEFINITIONS
    )


def test_route_enforces_auth_contract_tenant_and_actor() -> None:
    body = _batch().model_dump(mode="json")
    cases = (
        (None, body, {}, 401, "unauthorized"),
        (_user(role="viewer"), body, {}, 403, "platform_role_required"),
        (
            _user(),
            body,
            {"X-GDA-Capability-Fingerprint": "0" * 64},
            409,
            "capability_contract_mismatch",
        ),
        (_user(tenant="tenant-b"), body, {}, 403, "tenant_mismatch"),
        (
            _user(),
            _batch(actor="human:spoofed").model_dump(mode="json"),
            {},
            403,
            "actor_mismatch",
        ),
    )
    for user, payload, headers, expected_status, expected_code in cases:
        request_headers = {"x-request-id": "request-1", **headers}
        with patch.object(routes, "_get_user_from_request", return_value=user):
            response = asyncio.run(
                routes.schedule_approval_case_batch_escalation(
                    _request(body=payload, headers=request_headers)
                )
            )
        assert response.status_code == expected_status
        assert json.loads(response.body)["error"]["code"] == expected_code


def test_route_returns_canonical_partial_success_envelope_and_system_error() -> None:
    batch = _batch()
    result = _result(batch)
    request = _request(
        body=batch.model_dump(mode="json"),
        headers={
            "x-request-id": "request-1",
            "X-GDA-Capability-Fingerprint": APPROVAL_CASE_BATCH_ESCALATION.fingerprint,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_approval_case_batch_escalation",
            return_value=result,
        ) as execute,
    ):
        response = asyncio.run(routes.schedule_approval_case_batch_escalation(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "request-1"
    assert payload["data"]["scheduled_count"] == 1
    assert execute.call_args.args[0] == batch

    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_approval_case_batch_escalation",
            side_effect=ApprovalCaseConfigurationError("database unavailable"),
        ),
    ):
        unavailable = asyncio.run(
            routes.schedule_approval_case_batch_escalation(
                _request(body=batch.model_dump(mode="json"))
            )
        )
    assert unavailable.status_code == 503
    assert json.loads(unavailable.body)["error"]["code"] == "approval_case_unavailable"


def test_mcp_surface_enforces_context_and_returns_canonical_result() -> None:
    batch = _batch(actor="agent:mcp-operator")
    result = _result(batch)
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("mcp-operator")
    role_token = current_user_role.set("viewer")
    try:
        denied = json.loads(
            _mcp_schedule_approval_case_batch_escalation(
                TENANT,
                batch.actor_subject,
                [item.model_dump(mode="json") for item in batch.items],
            )
        )
        assert denied["code"] == "platform_role_required"

        current_user_role.set("platform_operator")
        spoofed = json.loads(
            _mcp_schedule_approval_case_batch_escalation(
                TENANT,
                "agent:spoofed",
                [item.model_dump(mode="json") for item in batch.items],
            )
        )
        assert spoofed["code"] == "actor_mismatch"

        with patch(
            "data_agent.approval_case_batch.execute_approval_case_batch_escalation",
            return_value=result,
        ) as execute:
            payload = json.loads(
                _mcp_schedule_approval_case_batch_escalation(
                    TENANT,
                    batch.actor_subject,
                    [item.model_dump(mode="json") for item in batch.items],
                )
            )
        assert payload["scheduled_count"] == 1
        assert execute.call_args.args[0] == batch
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)


def test_batch_escalation_route_precedes_dynamic_case_route() -> None:
    routes_list = routes.get_platform_gateway_routes()
    paths = [route.path for route in routes_list]
    batch_path = "/api/platform/v1/approval-cases/escalation-batches"
    case_path = "/api/platform/v1/approval-cases/{case_id}"

    assert paths.count(batch_path) == 1
    assert paths.index(batch_path) < paths.index(case_path)
