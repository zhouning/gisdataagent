from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    FEDERATED_PROJECTION_COMPENSATION_RULE_GET,
    IdempotencyMode,
    OperationKind,
    SideEffect,
)
from data_agent.cross_store_projection_compensation_rule_authority import (
    CustomerCompensationRuleAuthorityConfigurationError,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAuthorityItem,
    CustomerCompensationRuleAuthorityReadResponse,
    CustomerCompensationRuleStatus,
)
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_get_federated_projection_compensation_rules,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
    _rule_contract,
)
from data_agent.user_context import current_tenant_id, current_user_role


def _request(*, headers: dict | None = None, query_params: dict | None = None):
    request = MagicMock()
    request.headers = headers or {"x-request-id": "compensation-rule-read-1"}
    request.path_params = {}
    request.query_params = query_params or {}
    return request


def _user(tenant_id: str, role: str = "platform_operator"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def _authority_response():
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    contract = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )
    return CustomerCompensationRuleAuthorityReadResponse(
        tenant_id=proposal.tenant_id,
        requested_rule_id=rule_id,
        items=(
            CustomerCompensationRuleAuthorityItem(
                tenant_id=proposal.tenant_id,
                rule_id=rule_id,
                current=contract,
                history=(contract,),
                history_count=1,
            ),
        ),
        rule_count=1,
    )


def test_capability_and_mcp_registry_declare_rule_authority_as_read_only() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_RULE_GET
    assert spec.operation is OperationKind.QUERY
    assert spec.side_effect is SideEffect.NONE
    assert spec.execution.idempotency is IdempotencyMode.NOT_APPLICABLE
    assert spec.http is not None
    assert spec.http.path == (
        "/api/platform/v1/projections/federated/compensation-rules"
    )
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "get_federated_projection_compensation_rules"
    )
    assert definition["annotations"].readOnlyHint is True
    assert callable(
        _get_tool_functions()["get_federated_projection_compensation_rules"]
    )
    assert spec.http.path in {route.path for route in routes.get_platform_gateway_routes()}


def test_rest_reads_rule_authority_with_authenticated_tenant_only() -> None:
    result = _authority_response()
    store = MagicMock()
    store.lookup.return_value = result
    request = _request(
        headers={
            "x-request-id": "compensation-rule-read-1",
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_RULE_GET.fingerprint
            ),
        },
        query_params={"rule_id": result.items[0].rule_id},
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user(result.tenant_id)),
        patch.object(routes, "_federated_compensation_rule_store", return_value=store),
    ):
        response = asyncio.run(routes.get_federated_projection_compensation_rules(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["data"]["tenant_id"] == result.tenant_id
    assert payload["data"]["items"][0]["current"]["status"] == "draft_unreviewed"
    assert payload["data"]["execution_allowed"] is False
    assert payload["data"]["items"][0]["current"]["rule"]["dataset_scope"] == (
        "chongqing_customer_dataset"
    )
    store.lookup.assert_called_once_with(result.items[0].rule_id)


def test_rest_distinguishes_rule_not_found_outage_and_unexpected_query() -> None:
    result = _authority_response()
    store = MagicMock()
    store.lookup.return_value = result.model_copy(update={"items": (), "rule_count": 0})
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user(result.tenant_id)),
        patch.object(routes, "_federated_compensation_rule_store", return_value=store),
    ):
        missing = asyncio.run(
            routes.get_federated_projection_compensation_rules(
                _request(query_params={"rule_id": result.items[0].rule_id})
            )
        )
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == (
        "customer_compensation_rule_not_found"
    )

    store.lookup.side_effect = CustomerCompensationRuleAuthorityConfigurationError(
        "authority unavailable"
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user(result.tenant_id)),
        patch.object(routes, "_federated_compensation_rule_store", return_value=store),
    ):
        unavailable = asyncio.run(
            routes.get_federated_projection_compensation_rules(_request())
        )
    assert unavailable.status_code == 503
    assert json.loads(unavailable.body)["error"]["code"] == (
        "customer_compensation_rule_authority_unavailable"
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(result.tenant_id),
    ):
        unexpected = asyncio.run(
            routes.get_federated_projection_compensation_rules(
                _request(query_params={"tenant_id": result.tenant_id})
            )
        )
    assert unexpected.status_code == 422
    assert json.loads(unexpected.body)["error"]["code"] == (
        "unexpected_query_parameters"
    )


def test_mcp_reads_rule_authority_and_enforces_context() -> None:
    result = _authority_response()
    store = MagicMock()
    store.lookup.return_value = result
    missing_tenant = json.loads(
        _mcp_get_federated_projection_compensation_rules(result.items[0].rule_id)
    )
    assert missing_tenant["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(result.tenant_id)
    role_token = current_user_role.set("platform_operator")
    try:
        with patch(
            "data_agent.cross_store_projection_compensation_rule_authority."
            "PostgresCustomerCompensationRuleAuthorityStore",
            return_value=store,
        ) as store_type:
            payload = json.loads(
                _mcp_get_federated_projection_compensation_rules(
                    result.items[0].rule_id
                )
            )
            assert payload["rule_count"] == 1
            assert payload["execution_allowed"] is False
            store_type.assert_called_once_with(result.tenant_id)
            store.lookup.assert_called_once_with(result.items[0].rule_id)

            store.lookup.return_value = result.model_copy(update={"items": (), "rule_count": 0})
            missing = json.loads(
                _mcp_get_federated_projection_compensation_rules(
                    result.items[0].rule_id
                )
            )
            assert missing["code"] == "customer_compensation_rule_not_found"

            store.lookup.side_effect = CustomerCompensationRuleAuthorityConfigurationError(
                "authority unavailable"
            )
            unavailable = json.loads(
                _mcp_get_federated_projection_compensation_rules()
            )
            assert unavailable["code"] == (
                "customer_compensation_rule_authority_unavailable"
            )
    finally:
        current_user_role.reset(role_token)
        current_tenant_id.reset(tenant_token)
