"""HTTP boundary tests for governed GIS analysis Runs."""

from __future__ import annotations

import json
from unittest.mock import Mock
from uuid import UUID

import pytest
from starlette.requests import Request

from data_agent.api import gis_analysis_routes
from data_agent.capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    GIS_ANALYSIS_EXECUTE,
)
from data_agent.gis_analysis_execution import (
    GIS_POSTGIS_WORKLOAD,
    GISAnalysisExecutionValidationError,
)
from data_agent.gis_workflow_proposal import GISWorkflowProposalPlanner
from data_agent.openai_compatible_llm import LLMServiceError
from data_agent.test_gis_analysis_command_consumer import (
    BACKEND,
    NOW,
    RUN_ID,
    TENANT,
    _plan,
    _record,
)
from data_agent.test_gis_workflow import (
    QUESTION,
    _preview_request,
)
from data_agent.test_gis_workflow import (
    _planner as _workflow_planner,
)
from data_agent.test_gis_workflow_proposal import (
    _configure_llm,
    _llm_evidence,
    _supported_payload,
)


def _request(
    path: str,
    *,
    body: dict | None = None,
    method: str = "POST",
    run_id: bool = False,
    fingerprint: str | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    headers = [(b"content-type", b"application/json")]
    if fingerprint is not None:
        headers.append(
            (CAPABILITY_FINGERPRINT_HEADER.lower().encode(), fingerprint.encode())
        )
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "path_params": {"run_id": str(RUN_ID)} if run_id else {},
    }
    return Request(scope, receive)


def _user(
    identifier: str = "analyst",
    *,
    role: str = "analyst",
    subject_type: str = "human",
) -> dict:
    return {
        "identifier": identifier,
        "metadata": {
            "tenant_id": TENANT,
            "role": role,
            "subject_type": subject_type,
        },
    }


@pytest.mark.asyncio
async def test_workflow_preview_returns_confirmable_five_step_plan(monkeypatch) -> None:
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    planner = _workflow_planner()
    monkeypatch.setattr(gis_analysis_routes, "_workflow_planner", lambda: planner)

    response = await gis_analysis_routes.preview_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/preview",
            body=_preview_request().model_dump(mode="json"),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["data"]["status"] == "ready"
    assert payload["data"]["executable"] is True
    assert len(payload["data"]["steps"]) == 5
    assert len(payload["data"]["plan_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_workflow_proposal_route_exposes_planner_mode_and_fingerprint(
    monkeypatch,
) -> None:
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())

    class ProposalPlanner:
        def propose(self, question):
            assert question == QUESTION
            request = _preview_request()
            from data_agent.gis_workflow_proposal import GISWorkflowProposalEnvelope

            return GISWorkflowProposalEnvelope.create(
                request.proposal,
                request.planner_evidence,
                question=question,
            )

    monkeypatch.setattr(
        gis_analysis_routes,
        "_workflow_proposal_planner",
        lambda: ProposalPlanner(),
    )

    response = await gis_analysis_routes.propose_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/proposals",
            body={"question": QUESTION},
        )
    )
    payload = json.loads(response.body)["data"]

    assert response.status_code == 200
    assert payload["evidence"]["mode"] == "deterministic_fallback"
    assert len(payload["proposal_fingerprint"]) == 64
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_workflow_proposal_route_calls_llm_and_returns_validated_candidate(
    monkeypatch,
) -> None:
    _configure_llm(monkeypatch)
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        gis_analysis_routes,
        "_workflow_proposal_planner",
        lambda: GISWorkflowProposalPlanner(
            lambda **_: (json.dumps(_supported_payload()), _llm_evidence())
        ),
    )

    response = await gis_analysis_routes.propose_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/proposals",
            body={"question": QUESTION},
        )
    )
    payload = json.loads(response.body)["data"]

    assert response.status_code == 200
    assert payload["evidence"]["mode"] == "llm"
    assert payload["evidence"]["validation_status"] == "validated"
    assert payload["proposal"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_workflow_proposal_route_marks_llm_timeout_as_fallback(monkeypatch) -> None:
    _configure_llm(monkeypatch)
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())

    def timeout(**_):
        raise LLMServiceError("timeout")

    monkeypatch.setattr(
        gis_analysis_routes,
        "_workflow_proposal_planner",
        lambda: GISWorkflowProposalPlanner(timeout),
    )

    response = await gis_analysis_routes.propose_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/proposals",
            body={"question": QUESTION},
        )
    )
    payload = json.loads(response.body)["data"]

    assert response.status_code == 200
    assert payload["evidence"]["mode"] == "deterministic_fallback"
    assert payload["evidence"]["fallback_reason"] == "llm_unavailable:LLMServiceError"


@pytest.mark.asyncio
async def test_workflow_proposal_route_rejects_malformed_llm_contract(monkeypatch) -> None:
    _configure_llm(monkeypatch)
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        gis_analysis_routes,
        "_workflow_proposal_planner",
        lambda: GISWorkflowProposalPlanner(
            lambda **_: ('{"status":"supported","sql":"SELECT secret"}', _llm_evidence())
        ),
    )

    response = await gis_analysis_routes.propose_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/proposals",
            body={"question": QUESTION},
        )
    )
    payload = json.loads(response.body)["data"]

    assert response.status_code == 200
    assert payload["proposal"]["status"] == "unsupported"
    assert payload["evidence"]["validation_status"] == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("tampering", ["attestation", "question"])
async def test_workflow_preview_rejects_proposal_rebinding(monkeypatch, tampering) -> None:
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    body = _preview_request().model_dump(mode="json")
    if tampering == "attestation":
        body["proposal_attestation"] = "f" * 64
    else:
        body["question"] = QUESTION + "，并导出明细"

    response = await gis_analysis_routes.preview_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/preview",
            body=body,
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["error"]["code"] == "contract_validation_failed"


@pytest.mark.asyncio
async def test_workflow_execute_rejects_stale_preview_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        gis_analysis_routes, "_workflow_planner", lambda: _workflow_planner()
    )

    response = await gis_analysis_routes.execute_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/execute",
            body={
                **_preview_request().model_dump(mode="json"),
                "confirmed_plan_fingerprint": "a" * 64,
                "confirm_assumptions": True,
            },
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["error"]["code"] == "gis_workflow_plan_changed"


@pytest.mark.asyncio
async def test_workflow_execute_requires_analyst_role(monkeypatch) -> None:
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user(role="viewer"),
    )
    response = await gis_analysis_routes.execute_gis_workflow(
        _request(
            "/api/platform/v1/gis-workflows/execute",
            body={
                **_preview_request().model_dump(mode="json"),
                "confirmed_plan_fingerprint": "a" * 64,
                "confirm_assumptions": True,
            },
        )
    )

    assert response.status_code == 403


def _admission_body() -> dict:
    return {
        "client_request_id": "gis-analysis-route-001",
        "analysis": {
            "operation": "buffer",
            "input_source_name": "parcels",
            "distance_meters": 100,
            "output_crs": "EPSG:4490",
        },
        "budget": {
            "max_features": 100,
            "max_output_bytes": 100000,
            "max_duration_ms": 30000,
        },
    }


@pytest.mark.asyncio
async def test_analyst_admission_uses_typed_planner_and_authority(monkeypatch) -> None:
    planner = Mock()
    planner.plan.return_value = _plan()
    authority = Mock()
    authority.admit.return_value = _record()
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_planner", lambda: planner)
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.create_gis_analysis_run(
        _request(
            "/api/platform/v1/gis-analysis-runs",
            body=_admission_body(),
            fingerprint=GIS_ANALYSIS_EXECUTE.fingerprint,
        )
    )

    assert response.status_code == 202
    subject = planner.plan.call_args.args[1]
    assert subject.tenant_id == TENANT
    assert subject.subject_id == "analyst"
    assert subject.roles == ("analyst",)
    authority.admit.assert_called_once()


@pytest.mark.asyncio
async def test_admission_rejects_capability_fingerprint_drift_before_planning(
    monkeypatch,
) -> None:
    planner = Mock()
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_planner", lambda: planner)

    response = await gis_analysis_routes.create_gis_analysis_run(
        _request(
            "/api/platform/v1/gis-analysis-runs",
            body=_admission_body(),
            fingerprint="0" * 64,
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "capability_contract_mismatch"
    planner.plan.assert_not_called()


@pytest.mark.asyncio
async def test_admission_authenticates_before_contract_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: None
    )

    response = await gis_analysis_routes.create_gis_analysis_run(
        _request(
            "/api/platform/v1/gis-analysis-runs",
            body=_admission_body(),
            fingerprint="0" * 64,
        )
    )

    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_authenticated_user_can_discover_released_gis_algorithms(monkeypatch) -> None:
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )

    response = await gis_analysis_routes.list_gis_analysis_algorithms(
        _request(
            "/api/platform/v1/gis-analysis-algorithms",
            method="GET",
        )
    )

    assert response.status_code == 200
    catalog = json.loads(response.body)["data"]
    assert len(catalog["registry_fingerprint"]) == 64
    assert {item["operation"] for item in catalog["algorithms"]} == {
        "buffer",
        "clip",
        "intersection",
    }
    assert all(item["spec_fingerprint"] for item in catalog["algorithms"])


@pytest.mark.asyncio
async def test_unregistered_algorithm_selection_is_reported_as_validation_error(
    monkeypatch,
) -> None:
    planner = Mock()
    planner.plan.side_effect = GISAnalysisExecutionValidationError(
        "GIS algorithm release is not registered for this operation"
    )
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_planner", lambda: planner)

    body = _admission_body()
    body["analysis"] |= {
        "algorithm_id": "postgis.unknown",
        "algorithm_version": "gda.unknown.v1",
    }
    response = await gis_analysis_routes.create_gis_analysis_run(
        _request(
            "/api/platform/v1/gis-analysis-runs",
            body=body,
            fingerprint=GIS_ANALYSIS_EXECUTE.fingerprint,
        )
    )

    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == (
        "gis_analysis_execution_validation_error"
    )


@pytest.mark.asyncio
async def test_non_owner_cannot_read_another_analyst_run(monkeypatch) -> None:
    authority = Mock()
    authority.get.return_value = _record()
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user("other-analyst"),
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.get_gis_analysis_run(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}",
            method="GET",
            run_id=True,
        )
    )

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == (
        "gis_analysis_run_owner_required"
    )


@pytest.mark.asyncio
async def test_provider_receipt_requires_exact_postgis_workload(monkeypatch) -> None:
    authority = Mock()
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user(
            "another-provider",
            role="platform_operator",
            subject_type="workload",
        ),
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.start_gis_analysis_run(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/start",
            run_id=True,
            body={
                "attempt_no": 1,
                "external_namespace": "gda/gis-analysis/postgis",
                "external_run_id": "provider-run-1",
                "observed_at": NOW.isoformat(),
                "backend": BACKEND.model_dump(mode="json"),
                "expected_state_version": 0,
            },
        )
    )

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == (
        "gis_provider_identity_required"
    )
    authority.start.assert_not_called()


@pytest.mark.asyncio
async def test_exact_provider_can_record_start_receipt(monkeypatch) -> None:
    authority = Mock()
    authority.start.return_value = _record()
    workload_id = GIS_POSTGIS_WORKLOAD.removeprefix("workload:")
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user(
            workload_id,
            role="platform_operator",
            subject_type="workload",
        ),
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.start_gis_analysis_run(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/start",
            run_id=True,
            body={
                "attempt_no": 1,
                "external_namespace": "gda/gis-analysis/postgis",
                "external_run_id": "provider-run-1",
                "observed_at": NOW.isoformat(),
                "backend": BACKEND.model_dump(mode="json"),
                "expected_state_version": 0,
            },
        )
    )

    assert response.status_code == 200
    call = authority.start.call_args
    assert call.kwargs["actor_subject"] == GIS_POSTGIS_WORKLOAD
    assert call.kwargs["expected_state_version"] == 0
    assert call.args[2].backend == BACKEND


@pytest.mark.asyncio
async def test_provider_start_rejects_missing_backend_identity(monkeypatch) -> None:
    authority = Mock()
    workload_id = GIS_POSTGIS_WORKLOAD.removeprefix("workload:")
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user(
            workload_id,
            role="platform_operator",
            subject_type="workload",
        ),
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.start_gis_analysis_run(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/start",
            run_id=True,
            body={
                "attempt_no": 1,
                "external_namespace": "gda/gis-analysis/postgis",
                "external_run_id": "provider-run-1",
                "observed_at": NOW.isoformat(),
                "expected_state_version": 0,
            },
        )
    )

    assert response.status_code == 422
    authority.start.assert_not_called()


@pytest.mark.asyncio
async def test_owner_prestart_cancel_is_delegated_with_state_version(monkeypatch) -> None:
    authority = Mock()
    authority.cancel.return_value = _record()
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.cancel_gis_analysis_run(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/cancel",
            run_id=True,
            body={
                "cancel_request_id": "gis-cancel-route-001",
                "expected_state_version": 0,
                "reason": "source snapshot was superseded",
            },
        )
    )

    assert response.status_code == 200
    authority.cancel.assert_called_once_with(
        TENANT,
        RUN_ID,
        cancel_request_id="gis-cancel-route-001",
        actor_subject="human:analyst",
        roles=("analyst",),
        reason="source snapshot was superseded",
        expected_state_version=0,
    )


@pytest.mark.asyncio
async def test_platform_operator_can_fail_closed_reconciliation(monkeypatch) -> None:
    authority = Mock()
    authority.resolve_reconciliation.return_value = _record()
    monkeypatch.setattr(
        gis_analysis_routes,
        "_get_user_from_request",
        lambda _: _user("operator", role="platform_operator"),
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)
    incident_id = "00000000-0000-4000-8000-000000000120"

    response = await gis_analysis_routes.resolve_gis_analysis_reconciliation(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/reconciliation-resolution",
            run_id=True,
            body={
                "incident_id": incident_id,
                "expected_run_state_version": 4,
                "expected_incident_state_version": 1,
                "reason": "provider terminal evidence remained unavailable",
            },
        )
    )

    assert response.status_code == 200
    authority.resolve_reconciliation.assert_called_once_with(
        TENANT,
        RUN_ID,
        incident_id=UUID(incident_id),
        expected_run_state_version=4,
        expected_incident_state_version=1,
        actor_subject="human:operator",
        roles=("platform_operator",),
        reason="provider terminal evidence remained unavailable",
    )


@pytest.mark.asyncio
async def test_analyst_cannot_resolve_reconciliation(monkeypatch) -> None:
    authority = Mock()
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_authority", lambda: authority)

    response = await gis_analysis_routes.resolve_gis_analysis_reconciliation(
        _request(
            f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/reconciliation-resolution",
            run_id=True,
            body={
                "incident_id": "00000000-0000-4000-8000-000000000120",
                "expected_run_state_version": 4,
                "expected_incident_state_version": 0,
                "reason": "attempted closure",
            },
        )
    )

    assert response.status_code == 403
    authority.resolve_reconciliation.assert_not_called()


def test_all_gis_analysis_routes_are_mounted() -> None:
    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    base = "/api/platform/v1/gis-analysis-runs"
    assert {
        base,
        "/api/platform/v1/gis-analysis-algorithms",
        f"{base}/{{run_id}}",
        f"{base}/{{run_id}}/start",
        f"{base}/{{run_id}}/complete",
        f"{base}/{{run_id}}/cancel",
        f"{base}/{{run_id}}/reconciliation-resolution",
        f"{base}/{{run_id}}/result-access",
    } <= mounted
