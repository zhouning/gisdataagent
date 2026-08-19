from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST,
    FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST,
    IdempotencyMode,
    OperationKind,
    SideEffect,
)
from data_agent.cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalCaseResult,
    FederatedProjectionCompensationApprovalNotFoundError,
    FederatedProjectionCompensationExecutionApprovalResult,
    build_federated_projection_compensation_approval_binding,
    build_federated_projection_compensation_approval_case,
    build_federated_projection_compensation_execution_approval_case,
    build_federated_projection_compensation_execution_binding,
)
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_request_federated_projection_compensation_approval,
    _mcp_request_federated_projection_compensation_execution_approval,
)
from data_agent.test_cross_store_projection_compensation_approval import (
    _approved_review,
    _evidence,
)
from data_agent.test_cross_store_projection_compensation_approval import (
    _request as approval_request,
)
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)


def _request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "compensation-approval-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(tenant_id: str, role: str = "platform_operator"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={
            "role": role,
            "tenant_id": tenant_id,
            "subject_type": "human",
        },
    )


def _result(*, requester_subject: str, created: bool = True):
    evidence, candidate = _evidence()
    request = approval_request(candidate)
    binding = build_federated_projection_compensation_approval_binding(
        evidence,
        candidate.candidate_sha256,
    )
    case = build_federated_projection_compensation_approval_case(
        binding,
        request,
        requester_subject=requester_subject,
    )
    return (
        FederatedProjectionCompensationApprovalCaseResult(
            binding=binding,
            approval_case=case,
            idempotency_key=request.idempotency_key,
            created=created,
        ),
        request,
    )


def _execution_result(*, requester_subject: str, created: bool = True):
    _, _, review_binding, _, approved, request = _approved_review()
    binding = build_federated_projection_compensation_execution_binding(
        review_binding,
        approved,
        request,
    )
    case = build_federated_projection_compensation_execution_approval_case(
        binding,
        request,
        requester_subject=requester_subject,
    )
    return (
        FederatedProjectionCompensationExecutionApprovalResult(
            execution_binding=binding,
            approval_case=case,
            idempotency_key=request.idempotency_key,
            created=created,
        ),
        request,
    )


def test_capability_and_mcp_declare_idempotent_non_destructive_control_write() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST

    assert spec.operation is OperationKind.COMMAND
    assert spec.side_effect is SideEffect.CONTROL_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.http is not None
    assert spec.http.method == "POST"
    assert spec.http.path.endswith("/compensation-approval-cases")
    assert spec.http.path in {route.path for route in routes.get_platform_gateway_routes()}
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "request_federated_projection_compensation_approval"
    )
    assert definition["annotations"].readOnlyHint is False
    assert definition["annotations"].destructiveHint is False
    assert definition["annotations"].idempotentHint is True
    assert callable(
        _get_tool_functions()["request_federated_projection_compensation_approval"]
    )


def test_rest_uses_authenticated_tenant_and_requester_for_review_only_case() -> None:
    result, submission = _result(requester_subject="human:operator-1")
    service = MagicMock()
    service.request_review.return_value = result
    request = _request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "compensation-approval-1",
            "idempotency-key": submission.idempotency_key,
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_APPROVAL_REQUEST.fingerprint
            ),
        },
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(result.binding.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_approval_service",
            return_value=service,
        ) as service_factory,
    ):
        response = asyncio.run(
            routes.request_federated_projection_compensation_approval(request)
        )

    payload = json.loads(response.body)
    assert response.status_code == 201
    assert payload["created"] is True
    assert payload["data"]["approval_case"]["action"] == (
        "projection.federated.compensation.review"
    )
    assert payload["data"]["approval_case_is_execution_authority"] is False
    assert payload["data"]["execution_allowed"] is False
    service_factory.assert_called_once_with(result.binding.tenant_id)
    call = service.request_review.call_args
    assert call.args[0] == submission
    assert call.kwargs["requester_subject"] == "human:operator-1"


def test_rest_rejects_idempotency_mismatch_and_reports_missing_proposal() -> None:
    result, submission = _result(requester_subject="human:operator-1")
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(result.binding.tenant_id),
    ):
        conflict = asyncio.run(
            routes.request_federated_projection_compensation_approval(
                _request(
                    body=submission.model_dump(mode="json"),
                    headers={"idempotency-key": "another-key"},
                )
            )
        )
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == (
        "idempotency_key_mismatch"
    )

    service = MagicMock()
    service.request_review.side_effect = (
        FederatedProjectionCompensationApprovalNotFoundError("proposal missing")
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(result.binding.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_approval_service",
            return_value=service,
        ),
    ):
        missing = asyncio.run(
            routes.request_federated_projection_compensation_approval(
                _request(body=submission.model_dump(mode="json"))
            )
        )
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == (
        "compensation_proposal_not_found"
    )


def test_mcp_uses_agent_context_and_never_returns_execution_authority() -> None:
    result, submission = _result(requester_subject="agent:mcp-operator")
    missing_context = json.loads(
        _mcp_request_federated_projection_compensation_approval(
            **submission.model_dump(mode="json")
        )
    )
    assert missing_context["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(result.binding.tenant_id)
    role_token = current_user_role.set("platform_operator")
    user_token = current_user_id.set("mcp-operator")
    try:
        service = MagicMock()
        service.request_review.return_value = result
        with patch(
            "data_agent.cross_store_projection_compensation_approval."
            "FederatedProjectionCompensationApprovalService",
            return_value=service,
        ):
            payload = json.loads(
                _mcp_request_federated_projection_compensation_approval(
                    **submission.model_dump(mode="json")
                )
            )
        assert payload["approval_case_is_execution_authority"] is False
        assert payload["execution_allowed"] is False
        assert service.request_review.call_args.kwargs["requester_subject"] == (
            "agent:mcp-operator"
        )
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)


def test_execution_approval_capability_is_separate_idempotent_control_write() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST

    assert spec.operation is OperationKind.COMMAND
    assert spec.side_effect is SideEffect.CONTROL_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.policy.action == "projection.federated.compensation.execute"
    assert spec.http is not None
    assert spec.http.path.endswith("/compensation-execution-approval-cases")
    assert spec.http.path in {route.path for route in routes.get_platform_gateway_routes()}
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"]
        == "request_federated_projection_compensation_execution_approval"
    )
    assert definition["annotations"].destructiveHint is False
    assert definition["annotations"].idempotentHint is True
    assert callable(
        _get_tool_functions()[
            "request_federated_projection_compensation_execution_approval"
        ]
    )


def test_execution_approval_rest_uses_authenticated_context_without_execution() -> None:
    result, submission = _execution_result(requester_subject="human:operator-1")
    service = MagicMock()
    service.request_execution_authorization.return_value = result
    request = _request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "compensation-execution-approval-1",
            "idempotency-key": submission.idempotency_key,
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_EXECUTION_APPROVAL_REQUEST.fingerprint
            ),
        },
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(result.execution_binding.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_execution_approval_service",
            return_value=service,
        ) as service_factory,
    ):
        response = asyncio.run(
            routes.request_federated_projection_compensation_execution_approval(
                request
            )
        )

    payload = json.loads(response.body)
    assert response.status_code == 201
    assert payload["data"]["approval_case"]["action"] == (
        "projection.federated.compensation.execute"
    )
    assert payload["data"]["review_approval_is_execution_authority"] is False
    assert payload["data"]["execution_case_is_provider_execution"] is False
    assert payload["data"]["provider_execution_performed"] is False
    assert payload["data"]["execution_binding"]["review_binding"][
        "review_state"
    ] == "technical_baseline_unreviewed"
    service_factory.assert_called_once_with(result.execution_binding.tenant_id)
    call = service.request_execution_authorization.call_args
    assert call.args[0] == submission
    assert call.kwargs["requester_subject"] == "human:operator-1"


def test_execution_approval_mcp_uses_agent_context_and_does_not_execute() -> None:
    result, submission = _execution_result(requester_subject="agent:mcp-operator")
    missing_context = json.loads(
        _mcp_request_federated_projection_compensation_execution_approval(
            **submission.model_dump(mode="json")
        )
    )
    assert missing_context["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(result.execution_binding.tenant_id)
    role_token = current_user_role.set("platform_operator")
    user_token = current_user_id.set("mcp-operator")
    try:
        service = MagicMock()
        service.request_execution_authorization.return_value = result
        with patch(
            "data_agent.cross_store_projection_compensation_approval."
            "FederatedProjectionCompensationExecutionApprovalService",
            return_value=service,
        ):
            payload = json.loads(
                _mcp_request_federated_projection_compensation_execution_approval(
                    **submission.model_dump(mode="json")
                )
            )
        assert payload["review_approval_is_execution_authority"] is False
        assert payload["execution_case_is_provider_execution"] is False
        assert payload["provider_execution_performed"] is False
        assert service.request_execution_authorization.call_args.kwargs[
            "requester_subject"
        ] == "agent:mcp-operator"
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
