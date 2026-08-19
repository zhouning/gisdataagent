from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS,
    IdempotencyMode,
    OperationKind,
    SideEffect,
)
from data_agent.cross_store_projection_compensation_rule_authority import (
    CustomerCompensationRuleAuthorityConfigurationError,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    assess_federated_projection_compensation_rules,
    build_customer_compensation_rule_technical_baseline_drafts,
)
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_assess_persisted_federated_projection_compensation_rules,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
)
from data_agent.user_context import current_tenant_id, current_user_role


def _request(
    run_id: str,
    *,
    headers: dict | None = None,
    query_params: dict | None = None,
):
    request = MagicMock()
    request.headers = headers or {"x-request-id": "persisted-rule-assessment-1"}
    request.path_params = {"run_id": run_id}
    request.query_params = query_params or {}
    return request


def _user(tenant_id: str, role: str = "platform_operator"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def _assessment():
    proposal = _proposal()
    drafts = build_customer_compensation_rule_technical_baseline_drafts(proposal)
    return assess_federated_projection_compensation_rules(proposal, drafts)


def test_persisted_assessment_capability_and_mcp_are_read_only() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS
    assert spec.operation is OperationKind.QUERY
    assert spec.side_effect is SideEffect.NONE
    assert spec.execution.idempotency is IdempotencyMode.NOT_APPLICABLE
    assert spec.http is not None
    assert spec.http.method == "GET"
    assert spec.http.path.endswith("compensation-rule-assessments/{run_id}")
    assert spec.http.path in {
        route.path for route in routes.get_platform_gateway_routes()
    }
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"]
        == "assess_persisted_federated_projection_compensation_rules"
    )
    assert definition["annotations"].readOnlyHint is True
    assert callable(
        _get_tool_functions()[
            "assess_persisted_federated_projection_compensation_rules"
        ]
    )


def test_rest_assesses_only_authenticated_tenant_authority_current() -> None:
    assessment = _assessment()
    store = MagicMock()
    store.assess_current.return_value = assessment
    request = _request(
        assessment.run_id,
        headers={
            "x-request-id": "persisted-rule-assessment-1",
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_RULE_AUTHORITY_ASSESS.fingerprint
            ),
        },
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(assessment.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_rule_store",
            return_value=store,
        ) as store_factory,
    ):
        response = asyncio.run(
            routes.assess_persisted_federated_projection_compensation_rules(request)
        )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["data"]["proposal_sha256"] == assessment.proposal_sha256
    assert payload["data"]["draft_unreviewed_rule_ids"]
    assert payload["data"]["execution_allowed"] is False
    store_factory.assert_called_once_with(assessment.tenant_id)
    store.assess_current.assert_called_once_with(assessment.run_id)


def test_rest_distinguishes_missing_proposal_outage_and_query_override() -> None:
    assessment = _assessment()
    store = MagicMock()
    store.assess_current.return_value = None
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(assessment.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_rule_store",
            return_value=store,
        ),
    ):
        missing = asyncio.run(
            routes.assess_persisted_federated_projection_compensation_rules(
                _request(assessment.run_id)
            )
        )
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == (
        "compensation_proposal_not_found"
    )

    store.assess_current.side_effect = (
        CustomerCompensationRuleAuthorityConfigurationError("authority unavailable")
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(assessment.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_rule_store",
            return_value=store,
        ),
    ):
        unavailable = asyncio.run(
            routes.assess_persisted_federated_projection_compensation_rules(
                _request(assessment.run_id)
            )
        )
    assert unavailable.status_code == 503
    assert json.loads(unavailable.body)["error"]["code"] == (
        "customer_compensation_rule_authority_unavailable"
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(assessment.tenant_id),
    ):
        override = asyncio.run(
            routes.assess_persisted_federated_projection_compensation_rules(
                _request(
                    assessment.run_id,
                    query_params={"tenant_id": assessment.tenant_id},
                )
            )
        )
    assert override.status_code == 422
    assert json.loads(override.body)["error"]["code"] == (
        "unexpected_query_parameters"
    )


def test_mcp_persisted_assessment_enforces_context_and_not_found() -> None:
    assessment = _assessment()
    missing_tenant = json.loads(
        _mcp_assess_persisted_federated_projection_compensation_rules(
            assessment.run_id
        )
    )
    assert missing_tenant["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(assessment.tenant_id)
    role_token = current_user_role.set("platform_operator")
    try:
        store = MagicMock()
        store.assess_current.return_value = assessment
        with patch(
            "data_agent.cross_store_projection_compensation_rule_authority."
            "PostgresCustomerCompensationRuleAuthorityStore",
            return_value=store,
        ) as store_type:
            payload = json.loads(
                _mcp_assess_persisted_federated_projection_compensation_rules(
                    assessment.run_id
                )
            )
            assert payload["proposal_sha256"] == assessment.proposal_sha256
            assert payload["execution_allowed"] is False
            store_type.assert_called_once_with(assessment.tenant_id)

            store.assess_current.return_value = None
            missing = json.loads(
                _mcp_assess_persisted_federated_projection_compensation_rules(
                    assessment.run_id
                )
            )
            assert missing["code"] == "compensation_proposal_not_found"
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)
