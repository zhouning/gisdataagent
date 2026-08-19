from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET,
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ,
    IdempotencyMode,
    OperationKind,
    SideEffect,
)
from data_agent.cross_store_projection_compensation_proposal import (
    FederatedProjectionCompensationProposalReadResponse,
    FederatedProjectionCompensationProposalRequest,
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_proposal_authority import (
    FederatedProjectionCompensationProposalConfigurationError,
)
from data_agent.mcp_tool_registry import (
    TOOL_DEFINITIONS,
    _get_tool_functions,
    _mcp_generate_federated_projection_compensation_proposal,
    _mcp_get_federated_projection_compensation_proposal,
)
from data_agent.test_cross_store_projection_compensation_proposal import (
    _blocked_unknown_outcome,
)
from data_agent.user_context import current_tenant_id, current_user_role


def _request(
    *,
    body: dict | None = None,
    headers: dict | None = None,
    path_params: dict | None = None,
    query_params: dict | None = None,
):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "compensation-proposal-request-1"}
    request.path_params = path_params or {}
    request.query_params = query_params or {}
    return request


def _user(tenant_id: str, role: str = "platform_operator"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def _payload(plans, snapshot) -> dict:
    return FederatedProjectionCompensationProposalRequest(
        plans=plans,
        snapshot=snapshot,
    ).model_dump(mode="json")


def test_capability_and_mcp_registry_declare_a_truthful_read_only_surface() -> None:
    spec = FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ

    assert spec.operation is OperationKind.QUERY
    assert spec.side_effect is SideEffect.NONE
    assert spec.execution.idempotency is IdempotencyMode.NOT_APPLICABLE
    assert spec.http is not None
    assert spec.http.path == (
        "/api/platform/v1/projections/federated/compensation-proposals"
    )
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }

    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "generate_federated_projection_compensation_proposal"
    )
    assert definition["annotations"].readOnlyHint is True
    assert callable(
        _get_tool_functions()["generate_federated_projection_compensation_proposal"]
    )
    paths = {route.path for route in routes.get_platform_gateway_routes()}
    assert spec.http.path in paths

    read_spec = FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET
    assert read_spec.operation is OperationKind.QUERY
    assert read_spec.side_effect is SideEffect.NONE
    assert read_spec.http is not None
    assert read_spec.http.path.endswith("/compensation-proposals/{run_id}")
    assert read_spec.mcp_projection()["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    read_definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "get_federated_projection_compensation_proposal"
    )
    assert read_definition["annotations"].readOnlyHint is True
    assert callable(
        _get_tool_functions()["get_federated_projection_compensation_proposal"]
    )
    assert read_spec.http.path in paths


def test_rest_returns_snapshot_bound_proposal_without_provider_execution() -> None:
    plans, providers, snapshot = _blocked_unknown_outcome()
    before = tuple(provider.execute_count for provider in providers.values())
    body = _payload(plans, snapshot)
    request = _request(
        body=body,
        headers={
            "x-request-id": "compensation-proposal-request-1",
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ.fingerprint
            ),
        },
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(snapshot.tenant_id),
    ):
        response = asyncio.run(
            routes.generate_federated_projection_compensation_proposal(request)
        )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "compensation-proposal-request-1"
    assert payload["data"]["source_snapshot_sha256"] == snapshot.snapshot_sha256
    assert payload["data"]["execution_allowed"] is False
    assert payload["data"]["automatic_mutating_selection_allowed"] is False
    assert FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_READ.validate_output(
        payload["data"]
    )["review_state"] == "technical_baseline_unreviewed"
    assert tuple(provider.execute_count for provider in providers.values()) == before


def test_rest_rejects_tenant_override_and_contract_drift() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()
    body = _payload(plans, snapshot)
    body["tenant_id"] = snapshot.tenant_id

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(snapshot.tenant_id),
    ):
        override = asyncio.run(
            routes.generate_federated_projection_compensation_proposal(
                _request(body=body)
            )
        )
    assert override.status_code == 422
    assert json.loads(override.body)["error"]["code"] == "contract_validation_failed"

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user("another-tenant"),
    ):
        mismatch = asyncio.run(
            routes.generate_federated_projection_compensation_proposal(
                _request(body=_payload(plans, snapshot))
            )
        )
    assert mismatch.status_code == 403
    assert json.loads(mismatch.body)["error"]["code"] == "tenant_mismatch"

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(snapshot.tenant_id),
    ):
        drift = asyncio.run(
            routes.generate_federated_projection_compensation_proposal(
                _request(
                    body=_payload(plans, snapshot),
                    headers={"X-GDA-Capability-Fingerprint": "f" * 64},
                )
            )
        )
    assert drift.status_code == 409
    assert json.loads(drift.body)["error"]["code"] == "capability_contract_mismatch"


def test_mcp_enforces_context_and_remains_non_executing() -> None:
    plans, providers, snapshot = _blocked_unknown_outcome()
    plan_documents = [plan.model_dump(mode="json") for plan in plans]
    snapshot_document = snapshot.model_dump(mode="json")
    before = tuple(provider.execute_count for provider in providers.values())

    missing_tenant = json.loads(
        _mcp_generate_federated_projection_compensation_proposal(
            plan_documents,
            snapshot_document,
        )
    )
    assert missing_tenant["code"] == "tenant_context_required"

    tenant_token = current_tenant_id.set(snapshot.tenant_id)
    role_token = current_user_role.set("viewer")
    try:
        denied = json.loads(
            _mcp_generate_federated_projection_compensation_proposal(
                plan_documents,
                snapshot_document,
            )
        )
        assert denied["code"] == "platform_role_required"

        current_user_role.set("platform_operator")
        result = json.loads(
            _mcp_generate_federated_projection_compensation_proposal(
                plan_documents,
                snapshot_document,
            )
        )
        assert result["source_snapshot_sha256"] == snapshot.snapshot_sha256
        assert result["execution_allowed"] is False

        current_tenant_id.set("another-tenant")
        mismatch = json.loads(
            _mcp_generate_federated_projection_compensation_proposal(
                plan_documents,
                snapshot_document,
            )
        )
        assert mismatch["code"] == "tenant_mismatch"
    finally:
        current_user_role.reset(role_token)
        current_tenant_id.reset(tenant_token)

    assert tuple(provider.execute_count for provider in providers.values()) == before


def test_rest_reads_persisted_current_and_history_from_authenticated_tenant() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    result = FederatedProjectionCompensationProposalReadResponse(
        tenant_id=snapshot.tenant_id,
        run_id=snapshot.run_id,
        current=proposal,
        history=(proposal,),
        history_count=1,
    )
    store = MagicMock()
    store.lookup.return_value = result
    request = _request(
        path_params={"run_id": snapshot.run_id},
        headers={
            "x-request-id": "compensation-proposal-read-1",
            "X-GDA-Capability-Fingerprint": (
                FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET.fingerprint
            ),
        },
    )

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(snapshot.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_proposal_store",
            return_value=store,
        ) as factory,
    ):
        response = asyncio.run(
            routes.get_federated_projection_compensation_proposal(request)
        )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "compensation-proposal-read-1"
    assert payload["data"]["current"]["proposal_sha256"] == proposal.proposal_sha256
    assert payload["data"]["history_count"] == 1
    assert payload["data"]["execution_allowed"] is False
    assert FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_GET.validate_output(
        payload["data"]
    )["run_id"] == snapshot.run_id
    factory.assert_called_once_with(snapshot.tenant_id)
    store.lookup.assert_called_once_with(snapshot.run_id)


def test_rest_distinguishes_not_found_unavailable_and_unexpected_query() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()
    store = MagicMock()
    store.lookup.return_value = None

    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(snapshot.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_proposal_store",
            return_value=store,
        ),
    ):
        missing = asyncio.run(
            routes.get_federated_projection_compensation_proposal(
                _request(path_params={"run_id": snapshot.run_id})
            )
        )
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == (
        "compensation_proposal_not_found"
    )

    store.lookup.side_effect = FederatedProjectionCompensationProposalConfigurationError(
        "authority unavailable"
    )
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(snapshot.tenant_id),
        ),
        patch.object(
            routes,
            "_federated_compensation_proposal_store",
            return_value=store,
        ),
    ):
        unavailable = asyncio.run(
            routes.get_federated_projection_compensation_proposal(
                _request(path_params={"run_id": snapshot.run_id})
            )
        )
    assert unavailable.status_code == 503
    assert json.loads(unavailable.body)["error"]["code"] == (
        "compensation_proposal_authority_unavailable"
    )

    store.reset_mock()
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(snapshot.tenant_id),
    ):
        unexpected = asyncio.run(
            routes.get_federated_projection_compensation_proposal(
                _request(
                    path_params={"run_id": snapshot.run_id},
                    query_params={"tenant_id": snapshot.tenant_id},
                )
            )
        )
    assert unexpected.status_code == 422
    assert json.loads(unexpected.body)["error"]["code"] == (
        "unexpected_query_parameters"
    )
    store.lookup.assert_not_called()


def test_mcp_reads_persisted_history_and_separates_not_found_from_outage() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    result = FederatedProjectionCompensationProposalReadResponse(
        tenant_id=snapshot.tenant_id,
        run_id=snapshot.run_id,
        current=proposal,
        history=(proposal,),
        history_count=1,
    )
    store = MagicMock()
    store.lookup.return_value = result
    tenant_token = current_tenant_id.set(snapshot.tenant_id)
    role_token = current_user_role.set("platform_operator")
    try:
        with patch(
            "data_agent.cross_store_projection_compensation_proposal_authority."
            "PostgresFederatedProjectionCompensationProposalStore",
            return_value=store,
        ) as store_type:
            payload = json.loads(
                _mcp_get_federated_projection_compensation_proposal(snapshot.run_id)
            )
            assert payload["history_count"] == 1
            assert payload["execution_allowed"] is False
            store_type.assert_called_once_with(snapshot.tenant_id)
            store.lookup.assert_called_once_with(snapshot.run_id)

            store.lookup.return_value = None
            missing = json.loads(
                _mcp_get_federated_projection_compensation_proposal(snapshot.run_id)
            )
            assert missing["code"] == "compensation_proposal_not_found"

            store.lookup.side_effect = (
                FederatedProjectionCompensationProposalConfigurationError(
                    "authority unavailable"
                )
            )
            unavailable = json.loads(
                _mcp_get_federated_projection_compensation_proposal(snapshot.run_id)
            )
            assert unavailable["code"] == (
                "compensation_proposal_authority_unavailable"
            )
    finally:
        current_user_role.reset(role_token)
        current_tenant_id.reset(tenant_token)
