"""Capability, REST, and MCP contracts for Chongqing package reconciliation."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import CHONGQING_DATA_PACKAGE_RECONCILE
from data_agent.chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationError,
    build_chongqing_data_package_reconciliation_plan,
)
from data_agent.chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
    execute_chongqing_data_package_reconciliation,
)
from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)
from data_agent.mcp_tool_registry import _mcp_reconcile_entity_data_package
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)

TENANT = "chongqing-customer"
HUMAN_ACTOR = "human:operator-1"
AGENT_ACTOR = "agent:package-agent"
BASELINE = build_chongqing_entity_link_baseline(tenant_id=TENANT)
BASELINE_JSON = BASELINE.model_dump(mode="json")
EFFECTIVE_AT = BASELINE.link_assertion_drafts[0].valid_from + timedelta(days=1)
EVALUATED_AT = EFFECTIVE_AT + timedelta(hours=1)


def _submission(
    *,
    recorded_by: str = HUMAN_ACTOR,
) -> ChongqingDataPackageReconciliationRequest:
    return ChongqingDataPackageReconciliationRequest(
        tenant_id=TENANT,
        previous_baseline=BASELINE,
        desired_baseline=BASELINE,
        effective_at=EFFECTIVE_AT,
        evaluated_at=EVALUATED_AT,
        batch_size=200,
        verify_replay=True,
        idempotency_key="cq.package.reconcile.customer-v1",
        recorded_by=recorded_by,
    )


def _response(
    submission: ChongqingDataPackageReconciliationRequest,
) -> ChongqingDataPackageReconciliationResponse:
    return ChongqingDataPackageReconciliationResponse(
        tenant_id=submission.tenant_id,
        idempotency_key=submission.idempotency_key,
        recorded_by=submission.recorded_by,
        request_sha256=submission.request_sha256,
        previous_customer_bundle_version=BASELINE.customer_bundle_version,
        desired_customer_bundle_version=BASELINE.customer_bundle_version,
        effective_at=submission.effective_at,
        evaluated_at=submission.evaluated_at,
        plan_sha256="a" * 64,
        receipt_sha256="b" * 64,
        previous_baseline_sha256="c" * 64,
        desired_baseline_sha256="c" * 64,
        authority_state_sha256="d" * 64,
        operation_count=0,
        batch_count=0,
        unchanged_entity_count=len(BASELINE.temporal_entity_drafts),
        unchanged_source_count=len(BASELINE.source_binding_drafts),
        retained_retired_source_count=0,
        entity_correction_count=0,
        entity_addition_count=0,
        entity_activation_count=0,
        source_binding_count=0,
        entity_retirement_count=0,
        link_operation_count=0,
        link_correction_count=0,
        link_retraction_count=0,
        link_restoration_count=0,
        link_addition_count=0,
        replay_verification="passed",
        write_mode="phased_chunked_atomic_authority_batches",
        atomicity_status="atomic_per_batch_resumable_across_phases",
    )


class _FakeLedger:
    def __init__(self) -> None:
        self.entry: dict | None = None
        self.reserve_count = 0
        self.complete_count = 0

    def load(self, request):
        return self.entry

    def reserve(self, request, plan):
        self.reserve_count += 1
        if self.entry is None:
            self.entry = {
                "status": "pending",
                "request_sha256": request.request_sha256,
                "plan_document": plan.model_dump(mode="json"),
                "response_document": None,
            }
        return self.entry

    def complete(self, request, receipt, response):
        self.complete_count += 1
        self.entry = {
            "status": "completed",
            "request_sha256": request.request_sha256,
            "plan_document": self.entry["plan_document"],
            "response_document": response.model_dump(mode="json"),
        }
        return self.entry["response_document"]


def _request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "reconcile-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, role: str = "platform_operator", tenant_id: str = TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def test_request_rejects_client_authority_state_and_baseline_actor_spoofing() -> None:
    payload = _submission().model_dump(mode="json")
    payload["entity_assertions"] = {}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ChongqingDataPackageReconciliationRequest.model_validate(payload)

    spoofed_entity = BASELINE.temporal_entity_drafts[0].model_copy(
        update={"recorded_by": "human:spoofed"}
    )
    spoofed_baseline = BASELINE.model_copy(
        update={
            "temporal_entity_drafts": (
                spoofed_entity,
                *BASELINE.temporal_entity_drafts[1:],
            )
        }
    )
    payload = _submission().model_dump(mode="python")
    payload["desired_baseline"] = spoofed_baseline
    with pytest.raises(ValidationError, match="pinned baseline builder"):
        ChongqingDataPackageReconciliationRequest.model_validate(payload)


def test_service_delegates_only_baselines_and_returns_stable_proof() -> None:
    desired_link = BASELINE.link_assertion_drafts[0]
    endpoint_refs = {desired_link.source_entity_ref, desired_link.target_entity_ref}
    desired_entities = tuple(
        draft
        for draft in BASELINE.temporal_entity_drafts
        if draft.entity_ref in endpoint_refs
    )
    desired_sources = tuple(
        draft
        for draft in BASELINE.source_binding_drafts
        if draft.entity_ref in endpoint_refs
    )
    previous = BASELINE.model_copy(
        update={
            "customer_bundle_version": "service-previous",
            "temporal_entity_drafts": (),
            "source_binding_drafts": (),
            "link_identity_count": 0,
            "link_assertion_drafts": (),
        }
    )
    desired = BASELINE.model_copy(
        update={
            "customer_bundle_version": "service-desired",
            "temporal_entity_drafts": desired_entities,
            "source_binding_drafts": desired_sources,
            "link_identity_count": 1,
            "link_assertion_drafts": (desired_link,),
        }
    )
    submission = _submission().model_copy(
        update={"previous_baseline": previous, "desired_baseline": desired}
    )
    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        entity_assertions={draft.entity_ref: None for draft in desired_entities},
        source_bindings={
            draft.source_identity_ref: None for draft in desired_sources
        },
        link_assertions={desired_link.link_ref: None},
        effective_at=EFFECTIVE_AT,
    )
    expected = _response(submission)
    receipt = SimpleNamespace(**expected.model_dump(mode="python"))
    receipt.receipt_sha256 = expected.receipt_sha256
    ledger = _FakeLedger()

    with (
        patch(
            "data_agent.chongqing_data_package_reconciliation_service."
            "plan_chongqing_data_package_reconciliation",
            return_value=plan,
        ) as compile_plan,
        patch(
            "data_agent.chongqing_data_package_reconciliation_service."
            "apply_chongqing_data_package_reconciliation_plan",
            return_value=receipt,
        ) as apply_plan,
    ):
        first = execute_chongqing_data_package_reconciliation(
            submission,
            ledger=ledger,
        )
        second = execute_chongqing_data_package_reconciliation(
            submission,
            ledger=ledger,
        )

    assert first == second
    assert first.plan_sha256 == plan.plan_sha256
    assert first.receipt_sha256 == "b" * 64
    assert first.technical_baseline_status == "technical_baseline_unreviewed"
    assert first.decision_status == "assisted_precheck_not_for_production_decision"
    assert compile_plan.call_count == 1
    assert apply_plan.call_count == 1
    assert ledger.reserve_count == 1
    assert ledger.complete_count == 1
    call = compile_plan.call_args
    assert call.kwargs["previous_baseline"] is previous
    assert call.kwargs["desired_baseline"] is desired
    assert call.kwargs["effective_at"] == EFFECTIVE_AT
    assert call.kwargs["evaluated_at"] == EVALUATED_AT
    assert "entity_assertions" not in call.kwargs
    assert "source_bindings" not in call.kwargs
    assert "link_assertions" not in call.kwargs


def test_capability_projects_one_contract_to_rest_sdk_and_mcp() -> None:
    spec = CHONGQING_DATA_PACKAGE_RECONCILE
    surfaces = {binding.surface.value: binding.status.value for binding in spec.surfaces}

    assert spec.version == "1.0.0"
    assert spec.policy.allowed_roles == ("admin", "platform_operator")
    assert spec.execution.idempotency.value == "required"
    assert surfaces["api"] == "implemented"
    assert surfaces["sdk"] == "implemented"
    assert surfaces["agent"] == "implemented"
    assert spec.mcp is not None
    assert spec.mcp.tool_name == "reconcile_entity_data_package"
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    }
    assert "/api/platform/v1/entity-authority/reconciliations" in (
        spec.openapi_projection()["paths"]
    )
    input_properties = spec.input.json_schema["properties"]
    assert "previous_baseline" in input_properties
    assert "desired_baseline" in input_properties
    assert "entity_assertions" not in input_properties


@pytest.mark.parametrize(
    ("user", "status", "code"),
    (
        (None, 401, "unauthorized"),
        (_user(role="viewer"), 403, "platform_role_required"),
    ),
)
def test_route_requires_authentication_and_platform_role(user, status, code) -> None:
    request = _request(body=_submission().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=user):
        response = asyncio.run(routes.reconcile_entity_data_package(request))
    assert response.status_code == status
    assert json.loads(response.body)["error"]["code"] == code


def test_route_enforces_fingerprint_tenant_actor_and_idempotency() -> None:
    submission = _submission()
    drift = _request(
        body={},
        headers={"X-GDA-Capability-Fingerprint": "0" * 64},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.reconcile_entity_data_package(drift))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == (
        "capability_contract_mismatch"
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(tenant_id="other-tenant"),
    ):
        response = asyncio.run(
            routes.reconcile_entity_data_package(
                _request(body=submission.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"

    spoofed = _submission(recorded_by="human:spoofed")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.reconcile_entity_data_package(
                _request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"

    mismatch = _request(
        body=submission.model_dump(mode="json"),
        headers={"idempotency-key": "different.key"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.reconcile_entity_data_package(mismatch))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == (
        "idempotency_key_mismatch"
    )


def test_route_returns_valid_envelope_registers_path_and_maps_conflict() -> None:
    submission = _submission()
    result = _response(submission)
    request = _request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "reconcile-request-1",
            "X-GDA-Capability-Fingerprint": (
                CHONGQING_DATA_PACKAGE_RECONCILE.fingerprint
            ),
            "idempotency-key": submission.idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_chongqing_data_package_reconciliation",
            return_value=result,
        ),
    ):
        response = asyncio.run(routes.reconcile_entity_data_package(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "reconcile-request-1"
    assert CHONGQING_DATA_PACKAGE_RECONCILE.validate_output(payload["data"])[
        "receipt_sha256"
    ] == "b" * 64
    paths = {route.path for route in routes.get_platform_gateway_routes()}
    assert "/api/platform/v1/entity-authority/reconciliations" in paths

    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_chongqing_data_package_reconciliation",
            side_effect=ChongqingDataPackageReconciliationError("authority drift"),
        ),
    ):
        response = asyncio.run(
            routes.reconcile_entity_data_package(
                _request(body=submission.model_dump(mode="json"))
            )
        )
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == (
        "chongqing_data_package_reconciliation_conflict"
    )


def test_mcp_enforces_context_actor_and_executes_canonical_contract() -> None:
    submission = _submission(recorded_by=AGENT_ACTOR)
    result = _response(submission)
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("package-agent")
    role_token = current_user_role.set("viewer")
    try:
        denied = json.loads(
            _mcp_reconcile_entity_data_package(
                TENANT,
                BASELINE_JSON,
                BASELINE_JSON,
                EFFECTIVE_AT.isoformat(),
                EVALUATED_AT.isoformat(),
                submission.idempotency_key,
                AGENT_ACTOR,
            )
        )
        assert denied["code"] == "platform_role_required"

        current_user_role.set("platform_operator")
        mismatch = json.loads(
            _mcp_reconcile_entity_data_package(
                "other-tenant",
                BASELINE_JSON,
                BASELINE_JSON,
                EFFECTIVE_AT.isoformat(),
                EVALUATED_AT.isoformat(),
                submission.idempotency_key,
                AGENT_ACTOR,
            )
        )
        assert mismatch["code"] == "tenant_mismatch"

        actor_error = json.loads(
            _mcp_reconcile_entity_data_package(
                TENANT,
                BASELINE_JSON,
                BASELINE_JSON,
                EFFECTIVE_AT.isoformat(),
                EVALUATED_AT.isoformat(),
                submission.idempotency_key,
                "agent:spoofed",
            )
        )
        assert actor_error["code"] == "actor_mismatch"

        with patch(
            "data_agent.chongqing_data_package_reconciliation_service."
            "execute_chongqing_data_package_reconciliation",
            return_value=result,
        ) as execute:
            payload = json.loads(
                _mcp_reconcile_entity_data_package(
                    TENANT,
                    BASELINE_JSON,
                    BASELINE_JSON,
                    EFFECTIVE_AT.isoformat(),
                    EVALUATED_AT.isoformat(),
                    submission.idempotency_key,
                    AGENT_ACTOR,
                    batch_size=200,
                    verify_replay=True,
                )
            )
        assert payload["plan_sha256"] == "a" * 64
        assert payload["receipt_sha256"] == "b" * 64
        assert payload["technical_baseline_status"] == (
            "technical_baseline_unreviewed"
        )
        request = execute.call_args.args[0]
        assert request.tenant_id == TENANT
        assert request.recorded_by == AGENT_ACTOR
        assert request.verify_replay is True
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
