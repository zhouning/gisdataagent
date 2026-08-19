from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS,
    IdempotencyMode,
    OperationKind,
    SideEffect,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
)
from data_agent.cross_store_projection_compensation_trust import (
    CustomerCompensationApprovalTrustConfigurationError,
)
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_assess_federated_projection_compensation_rules,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
    _rule_contract,
    _trust_registry,
)
from data_agent.user_context import current_tenant_id, current_user_role


def _request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "compensation-rule-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(tenant_id: str, role: str = "platform_operator"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def test_rule_assessment_capability_and_mcp_surface_are_read_only() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS

    assert spec.operation is OperationKind.QUERY
    assert spec.side_effect is SideEffect.NONE
    assert spec.execution.idempotency is IdempotencyMode.NOT_APPLICABLE
    assert spec.http is not None
    assert spec.http.path.endswith("/compensation-rule-assessments")
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "assess_federated_projection_compensation_rules"
    )
    assert definition["annotations"].readOnlyHint is True
    assert callable(
        _get_tool_functions()["assess_federated_projection_compensation_rules"]
    )
    assert spec.http.path in {route.path for route in routes.get_platform_gateway_routes()}


def test_rest_returns_missing_rule_assessment_without_persistence_or_execution() -> None:
    proposal = _proposal()
    body = {"proposal": proposal.model_dump(mode="json"), "rules": []}
    request = _request(
        body=body,
        headers={
            "x-request-id": "compensation-rule-request-1",
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS.fingerprint
            ),
        },
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ):
        response = asyncio.run(
            routes.assess_federated_projection_compensation_rules(request)
        )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["data"]["proposal_sha256"] == proposal.proposal_sha256
    assert payload["data"]["missing_rule_ids"] == list(
        proposal.missing_customer_rule_ids
    )
    assert payload["data"]["execution_allowed"] is False
    assert payload["data"]["automatic_mutating_selection_allowed"] is False


def test_rest_rejects_body_tenant_override_and_capability_drift() -> None:
    proposal = _proposal()
    body = {"proposal": proposal.model_dump(mode="json"), "rules": []}
    body["tenant_id"] = proposal.tenant_id

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ):
        override = asyncio.run(
            routes.assess_federated_projection_compensation_rules(
                _request(body=body)
            )
        )
    assert override.status_code == 422
    assert json.loads(override.body)["error"]["code"] == "contract_validation_failed"

    trust_override_body = {
        "proposal": proposal.model_dump(mode="json"),
        "rules": [],
        "trust_registry": {"anchors": []},
    }
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ):
        trust_override = asyncio.run(
            routes.assess_federated_projection_compensation_rules(
                _request(body=trust_override_body)
            )
        )
    assert trust_override.status_code == 422
    assert json.loads(trust_override.body)["error"]["code"] == (
        "contract_validation_failed"
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ):
        drift = asyncio.run(
            routes.assess_federated_projection_compensation_rules(
                _request(
                    body={"proposal": proposal.model_dump(mode="json"), "rules": []},
                    headers={"X-GDA-Capability-Fingerprint": "f" * 64},
                )
            )
        )
    assert drift.status_code == 409
    assert json.loads(drift.body)["error"]["code"] == "capability_contract_mismatch"


def test_rest_requires_server_trust_registry_for_customer_approved_rules() -> None:
    proposal = _proposal()
    contracts = tuple(
        _rule_contract(
            proposal,
            rule_id,
            CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
        )
        for rule_id in proposal.missing_customer_rule_ids
    )
    body = {
        "proposal": proposal.model_dump(mode="json"),
        "rules": [contract.model_dump(mode="json") for contract in contracts],
    }
    headers = {
        "x-request-id": "compensation-rule-approved-request-1",
        "X-GDA-Capability-Fingerprint": (
            FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS.fingerprint
        ),
    }

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ), patch.object(
        routes,
        "load_customer_compensation_approval_trust_registry",
        return_value=_trust_registry(contracts),
    ):
        response = asyncio.run(
            routes.assess_federated_projection_compensation_rules(
                _request(body=body, headers=headers)
            )
        )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["data"]["all_required_rule_contracts_approved"] is True
    assert all(
        item["customer_approval_trusted"]
        for item in payload["data"]["assessments"]
    )


def test_rest_surfaces_trust_registry_configuration_error() -> None:
    proposal = _proposal()
    body = {"proposal": proposal.model_dump(mode="json"), "rules": []}
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(proposal.tenant_id),
    ), patch.object(
        routes,
        "load_customer_compensation_approval_trust_registry",
        side_effect=CustomerCompensationApprovalTrustConfigurationError(
            "invalid trust registry"
        ),
    ):
        response = asyncio.run(
            routes.assess_federated_projection_compensation_rules(
                _request(
                    body=body,
                    headers={
                        "x-request-id": "compensation-rule-config-error",
                        "X-GDA-Capability-Fingerprint": (
                            FEDERATED_PROJECTION_COMPENSATION_RULE_ASSESS.fingerprint
                        ),
                    },
                )
            )
        )
    assert response.status_code == 500
    assert json.loads(response.body)["error"]["code"] == (
        "customer_approval_trust_registry_configuration_error"
    )


def test_mcp_requires_context_and_returns_only_readiness_evidence() -> None:
    proposal = _proposal()
    document = proposal.model_dump(mode="json")

    missing_tenant = json.loads(
        _mcp_assess_federated_projection_compensation_rules(document, [])
    )
    assert missing_tenant["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(proposal.tenant_id)
    role_token = current_user_role.set("viewer")
    try:
        denied = json.loads(
            _mcp_assess_federated_projection_compensation_rules(document, [])
        )
        assert denied["code"] == "platform_role_required"

        current_user_role.set("platform_operator")
        result = json.loads(
            _mcp_assess_federated_projection_compensation_rules(document, [])
        )
        assert result["proposal_sha256"] == proposal.proposal_sha256
        assert result["execution_allowed"] is False

        current_tenant_id.set("another-tenant")
        mismatch = json.loads(
            _mcp_assess_federated_projection_compensation_rules(document, [])
        )
        assert mismatch["code"] == "tenant_mismatch"
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)


def test_mcp_surfaces_deployment_trust_registry_configuration_error() -> None:
    proposal = _proposal()
    tenant_token = current_tenant_id.set(proposal.tenant_id)
    role_token = current_user_role.set("platform_operator")
    try:
        with patch(
            "data_agent.cross_store_projection_compensation_trust."
            "load_customer_compensation_approval_trust_registry",
            side_effect=CustomerCompensationApprovalTrustConfigurationError(
                "invalid trust registry"
            ),
        ):
            result = json.loads(
                _mcp_assess_federated_projection_compensation_rules(
                    proposal.model_dump(mode="json"),
                    [],
                )
            )
        assert result["code"] == (
            "customer_approval_trust_registry_configuration_error"
        )
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)
