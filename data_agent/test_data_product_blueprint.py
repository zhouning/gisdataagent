import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from data_agent.api import platform_gateway_routes as routes
from data_agent.approval_case_authority import (
    ApprovalCaseWriteResult,
)
from data_agent.data_product_blueprint import (
    DataProductBlueprint,
    DataProductBlueprintProviderCancellationTimeoutRequest,
    DataProductBlueprintProviderReconcileRequest,
    DataProductBlueprintProviderRetryRequest,
    DataProductBlueprintTestRunRequest,
    build_data_product_blueprint_approval_case,
    build_data_product_blueprint_preview,
    build_data_product_blueprint_release_binding,
    build_data_product_blueprint_test_report,
    compile_data_product_blueprint,
    data_product_blueprint_fingerprint,
    data_product_blueprint_provider_cancellation_timeout_fingerprint,
    data_product_blueprint_provider_reconcile_fingerprint,
    data_product_blueprint_provider_retry_backoff_seconds,
    data_product_blueprint_provider_retry_fingerprint,
)
from data_agent.platform_contracts import (
    FrameworkAttemptObservation,
    FrameworkKind,
    OrchestrationClass,
    PortabilityClass,
    ResourceBinding,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import GatewayWriteResult


def _payload() -> dict:
    payload = {
        "tenant_id": "planning",
        "definition_urn": "gda://planning/definition/districts-build",
        "definition_version_id": UUID("00000000-0000-4000-8000-000000000731"),
        "version_key": "v1.0.0",
        "product_urn": "gda://planning/data_product/districts",
        "domain": "planning",
        "owner_ref": "team:geo-platform",
        "source_refs": ("gda://planning/dataset/district-source",),
        "storage_placement": {"profile": "default", "table_format": "iceberg"},
        "model_contract": {"schema": "districts.v1", "geometry": "polygon"},
        "quality_contract": {"verdict": "passed", "rules": ["geometry_valid"]},
        "security_policy": {"classification": "internal", "row_filter": "tenant"},
        "slo_contract": {"freshness_minutes": 60},
        "pipeline": {"engine": "spark", "mode": "batch"},
        "projections": ({"kind": "postgis", "name": "districts"},),
        "retention_policy": {"days": 365},
        "cost_policy": {"budget_class": "standard"},
        "created_by": "human:planner",
        "created_at": datetime(2026, 8, 20, tzinfo=UTC),
    }
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
    return payload


def _request(body: dict):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = {"x-request-id": "blueprint-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = "planning", identifier: str = "planner"):
    return SimpleNamespace(
        identifier=identifier,
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


def _provider_reconcile_payload(
    *,
    run_id: UUID,
    plan_id: UUID,
    provider_state: str = "running",
) -> dict:
    observation_id = UUID("00000000-0000-4000-8000-000000000752")
    observed_at = datetime(2026, 8, 20, 1, tzinfo=UTC)
    evidence = {
        "schema": "gda.data_product_blueprint_provider_observation.v1",
        "execution_plan_artifact_id": str(plan_id),
        "provider_state": provider_state,
        "observation_id": str(observation_id),
        "attempt_no": 1,
        "framework_kind": "spark",
        "external_namespace": "spark-blueprint-tests",
        "external_run_id": "spark-app-752",
        "external_attempt_id": "attempt-1",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "provider_receipt": {"exit_code": None},
    }
    observation = FrameworkAttemptObservation(
        tenant_id="planning",
        observation_id=observation_id,
        run_id=run_id,
        attempt_no=1,
        framework_kind=FrameworkKind.SPARK,
        external_namespace="spark-blueprint-tests",
        external_run_id="spark-app-752",
        external_attempt_id="attempt-1",
        observed_state=provider_state,
        observation_sha256=canonical_json_fingerprint(evidence),
        evidence=evidence,
        observed_at=observed_at,
    )
    payload = {
        "tenant_id": "planning",
        "run_id": run_id,
        "execution_plan_artifact_id": plan_id,
        "provider_state": provider_state,
        "attempt_observation": observation,
        "reason": f"Spark provider reports {provider_state}",
    }
    payload["reconcile_receipt_sha256"] = (
        data_product_blueprint_provider_reconcile_fingerprint(payload)
    )
    return payload


def _provider_timeout_payload(
    *,
    run_id: UUID,
    plan_id: UUID,
    provider_state: str = "ready_stop",
) -> dict:
    observation_id = UUID("00000000-0000-4000-8000-000000000754")
    observed_at = datetime(2026, 8, 20, 2, tzinfo=UTC)
    evidence = {
        "schema": "gda.data_product_blueprint_provider_cancellation_timeout.v1",
        "execution_plan_artifact_id": str(plan_id),
        "provider_state": provider_state,
        "observation_id": str(observation_id),
        "attempt_no": 3,
        "framework_kind": "spark",
        "external_namespace": "spark-blueprint-tests",
        "external_run_id": "spark-app-timeout-754",
        "external_attempt_id": "attempt-3",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "reconcile_attempt": 3,
        "max_reconcile_attempts": 3,
        "provider_receipt": {"application_state": provider_state},
    }
    observation = FrameworkAttemptObservation(
        tenant_id="planning",
        observation_id=observation_id,
        run_id=run_id,
        attempt_no=3,
        framework_kind=FrameworkKind.SPARK,
        external_namespace="spark-blueprint-tests",
        external_run_id="spark-app-timeout-754",
        external_attempt_id="attempt-3",
        observed_state=provider_state,
        observation_sha256=canonical_json_fingerprint(evidence),
        evidence=evidence,
        observed_at=observed_at,
    )
    payload = {
        "tenant_id": "planning",
        "run_id": run_id,
        "execution_plan_artifact_id": plan_id,
        "provider_state": provider_state,
        "reconcile_attempt": 3,
        "max_reconcile_attempts": 3,
        "attempt_observation": observation,
        "reason": "provider cancellation retries exhausted",
    }
    payload["timeout_receipt_sha256"] = (
        data_product_blueprint_provider_cancellation_timeout_fingerprint(payload)
    )
    return payload


def _provider_retry_payload(
    *,
    run_id: UUID,
    plan_id: UUID,
    retry_attempt: int = 1,
    max_retry_attempts: int = 3,
) -> dict:
    observation_id = UUID("00000000-0000-4000-8000-000000000755")
    observed_at = datetime(2026, 8, 20, 3, tzinfo=UTC)
    evidence = {
        "schema": "gda.data_product_blueprint_provider_retry.v1",
        "execution_plan_artifact_id": str(plan_id),
        "provider_state": "failed",
        "observation_id": str(observation_id),
        "attempt_no": retry_attempt,
        "framework_kind": "spark",
        "external_namespace": "spark-blueprint-tests",
        "external_run_id": "spark-app-retry-755",
        "external_attempt_id": f"attempt-{retry_attempt}",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "retry_attempt": retry_attempt,
        "max_retry_attempts": max_retry_attempts,
        "provider_receipt": {"application_state": "FAILED", "retryable": True},
    }
    observation = FrameworkAttemptObservation(
        tenant_id="planning",
        observation_id=observation_id,
        run_id=run_id,
        attempt_no=retry_attempt,
        framework_kind=FrameworkKind.SPARK,
        external_namespace="spark-blueprint-tests",
        external_run_id="spark-app-retry-755",
        external_attempt_id=f"attempt-{retry_attempt}",
        observed_state="failed",
        observation_sha256=canonical_json_fingerprint(evidence),
        evidence=evidence,
        observed_at=observed_at,
    )
    payload = {
        "tenant_id": "planning",
        "run_id": run_id,
        "execution_plan_artifact_id": plan_id,
        "provider_state": "failed",
        "retry_attempt": retry_attempt,
        "max_retry_attempts": max_retry_attempts,
        "attempt_observation": observation,
        "reason": "transient provider failure; retry with bounded backoff",
    }
    payload["retry_receipt_sha256"] = (
        data_product_blueprint_provider_retry_fingerprint(payload)
    )
    return payload


class _IdempotentDefinitionGateway:
    def __init__(self):
        self.registrations = []

    def register_definition(self, registration):
        created = not self.registrations
        if self.registrations:
            assert registration == self.registrations[0]
        self.registrations.append(registration)
        return GatewayWriteResult(value=registration, created=created)


class _PreviewDefinitionGateway:
    def __init__(self, predecessor):
        self.predecessor = predecessor

    def get_definition(self, tenant_id, definition_version_id):
        assert tenant_id == "planning"
        assert definition_version_id == self.predecessor.definition_version_id
        return self.predecessor


class _IdempotentApprovalAuthority:
    def __init__(self):
        self.cases = []

    def create(self, approval_case, *, owner_ref):
        assert owner_ref == "team:data-platform"
        created = not self.cases
        if self.cases:
            assert approval_case == self.cases[0]
        self.cases.append(approval_case)
        return ApprovalCaseWriteResult(approval_case=approval_case, created=created)


def test_blueprint_is_tamper_evident_and_compiles_to_existing_definition_contract():
    blueprint = DataProductBlueprint.model_validate(_payload())

    registration = compile_data_product_blueprint(blueprint)

    assert registration.resource.resource_kind == "definition"
    assert registration.resource_version.content_sha256 == registration.definition.definition_sha256
    assert registration.definition.orchestration_class is OrchestrationClass.DATAOPS
    assert registration.definition.portability_class is PortabilityClass.PORTABLE
    assert registration.definition.definition_document["schema"] == "gda.data_product_blueprint.v1"
    assert (
        registration.definition.definition_document["blueprint_sha256"]
        == blueprint.blueprint_sha256
    )
    assert registration.resource.technical_refs[0]["schema"] == "gda.data_product_blueprint.v1"

    report = build_data_product_blueprint_test_report(blueprint)
    assert report.verdict == "passed"
    assert report.definition_sha256 == registration.definition.definition_sha256
    assert report.test_report_sha256
    assert report == build_data_product_blueprint_test_report(blueprint)


def test_blueprint_fingerprint_is_stable_for_mapping_order():
    first = _payload()
    second = {**first}
    second["storage_placement"] = {"table_format": "iceberg", "profile": "default"}
    second["model_contract"] = {"geometry": "polygon", "schema": "districts.v1"}

    assert data_product_blueprint_fingerprint(first) == data_product_blueprint_fingerprint(second)


def test_blueprint_fingerprint_normalizes_equivalent_timezone_offsets():
    first = _payload()
    second = {**first, "created_at": "2026-08-20T04:00:00+04:00"}

    assert data_product_blueprint_fingerprint(first) == data_product_blueprint_fingerprint(
        DataProductBlueprint.model_validate(first)
    )
    second["blueprint_sha256"] = data_product_blueprint_fingerprint(second)
    assert DataProductBlueprint.model_validate(second).blueprint_sha256 == first[
        "blueprint_sha256"
    ]


def test_blueprint_preview_is_deterministic_and_binds_predecessor_diff():
    predecessor = DataProductBlueprint.model_validate(_payload())
    successor_payload = {
        **_payload(),
        "definition_version_id": UUID("00000000-0000-4000-8000-000000000732"),
        "predecessor_definition_version_id": predecessor.definition_version_id,
        "version_key": "v1.1.0",
        "model_contract": {"schema": "districts.v2", "geometry": "multipolygon"},
    }
    successor_payload["blueprint_sha256"] = data_product_blueprint_fingerprint(
        successor_payload
    )
    successor = DataProductBlueprint.model_validate(successor_payload)
    predecessor_definition = compile_data_product_blueprint(predecessor).definition

    preview = build_data_product_blueprint_preview(
        successor,
        predecessor=predecessor_definition,
    )

    assert preview.compile_verdict == "passed"
    assert preview.product_urn == successor.product_urn
    assert preview.version_key == successor.version_key
    assert preview.predecessor_definition_version_id == predecessor.definition_version_id
    assert preview.review_target_resource_urn == successor.definition_urn
    assert preview.review_target_fingerprint == preview.change_set_sha256
    assert any(
        change.path == "definition_document.model_contract.schema"
        for change in preview.changes
    )
    assert {check.check_id for check in preview.compile_checks} == {
        "blueprint_integrity",
        "tenant_boundary",
        "definition_integrity",
        "predecessor_binding",
    }
    assert preview == build_data_product_blueprint_preview(
        successor,
        predecessor=predecessor_definition,
    )


def test_blueprint_preview_route_is_non_mutating():
    predecessor = DataProductBlueprint.model_validate(_payload())
    predecessor_definition = compile_data_product_blueprint(predecessor).definition
    payload = {
        **_payload(),
        "definition_version_id": UUID("00000000-0000-4000-8000-000000000732"),
        "predecessor_definition_version_id": predecessor.definition_version_id,
        "version_key": "v1.1.0",
        "model_contract": {"schema": "districts.v2", "geometry": "multipolygon"},
    }
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
    gateway = _PreviewDefinitionGateway(predecessor_definition)
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.preview_data_product_blueprint(_request(payload)))

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["data"]["compile_verdict"] == "passed"
    assert body["data"]["review_action"] == "data_product_blueprint.change_review"


def test_blueprint_contract_test_route_is_non_mutating_and_deterministic():
    payload = _payload()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
    ):
        first = asyncio.run(routes.test_data_product_blueprint(_request(payload)))
        second = asyncio.run(routes.test_data_product_blueprint(_request(payload)))

    assert first.status_code == 200
    first_body = json.loads(first.body)["data"]
    second_body = json.loads(second.body)["data"]
    assert first_body == second_body
    assert first_body["verdict"] == "passed"
    assert first_body["test_report_sha256"]
    assert {check["check_id"] for check in first_body["checks"]} == {
        "blueprint_integrity",
        "definition_integrity",
        "source_contract",
        "storage_contract",
        "pipeline_contract",
        "quality_security_slo_contract",
        "projection_contract",
    }


def test_blueprint_test_run_request_binds_explicit_input_versions_and_rejects_duplicates():
    blueprint = DataProductBlueprint.model_validate(_payload())
    binding = ResourceBinding(
        binding_name="source",
        resource_version_id=UUID("00000000-0000-4000-8000-000000000741"),
        semantic_type="source.dataset",
    )
    request = DataProductBlueprintTestRunRequest(
        blueprint=blueprint,
        run_id=UUID("00000000-0000-4000-8000-000000000742"),
        idempotency_key="blueprint-test-1",
        input_bindings=(binding,),
    )
    assert request.input_bindings == (binding,)
    with pytest.raises(ValueError, match="must be unique"):
        DataProductBlueprintTestRunRequest(
            blueprint=blueprint,
            run_id=UUID("00000000-0000-4000-8000-000000000743"),
            idempotency_key="blueprint-test-2",
            input_bindings=(binding, binding),
        )


def test_blueprint_test_execution_route_requires_workload_and_matches_path_identity():
    run_id = UUID("00000000-0000-4000-8000-000000000744")
    request = _request({"run_id": str(run_id), "reason": "execute test"})
    request.path_params = {"run_id": str(run_id)}
    human = _user(identifier="planner")
    with patch.object(routes, "_get_user_from_request", return_value=human):
        response = asyncio.run(routes.execute_data_product_blueprint_test_run(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(
        {"run_id": str(run_id), "reason": "execute test"}
    )
    mismatched.path_params = {
        "run_id": "00000000-0000-4000-8000-000000000745"
    }
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.execute_data_product_blueprint_test_run(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.execute_blueprint_test_run.assert_not_called()


def test_blueprint_duckdb_execution_route_requires_workload_and_matches_path_identity():
    run_id = UUID("00000000-0000-4000-8000-000000000801")
    request = _request({"run_id": str(run_id), "reason": "execute in DuckDB"})
    request.path_params = {"run_id": str(run_id)}
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(identifier="planner"),
    ):
        response = asyncio.run(
            routes.execute_data_product_blueprint_duckdb_test_run(request)
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-duckdb-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(
        {"run_id": str(run_id), "reason": "execute in DuckDB"}
    )
    mismatched.path_params = {
        "run_id": "00000000-0000-4000-8000-000000000802"
    }
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.execute_data_product_blueprint_duckdb_test_run(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.execute_blueprint_duckdb_test_run.assert_not_called()


def test_blueprint_test_failure_route_requires_workload_and_matches_path_identity():
    run_id = UUID("00000000-0000-4000-8000-000000000746")
    human = _user(identifier="planner")
    request = _request(
        {"run_id": str(run_id), "error_code": "provider_timeout", "reason": "timeout"}
    )
    request.path_params = {"run_id": str(run_id)}
    with patch.object(routes, "_get_user_from_request", return_value=human):
        response = asyncio.run(routes.fail_data_product_blueprint_test_run(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(
        {"run_id": str(run_id), "error_code": "provider_timeout", "reason": "timeout"}
    )
    mismatched.path_params = {
        "run_id": "00000000-0000-4000-8000-000000000747"
    }
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.fail_data_product_blueprint_test_run(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.fail_blueprint_test_run.assert_not_called()


def test_blueprint_test_cancellation_route_requires_workload_and_matches_path_identity():
    run_id = UUID("00000000-0000-4000-8000-000000000748")
    human = _user(identifier="planner")
    request = _request(
        {
            "run_id": str(run_id),
            "external_cancel_ref": "cancel-1",
            "reason": "governed cancellation converged",
        }
    )
    request.path_params = {"run_id": str(run_id)}
    with patch.object(routes, "_get_user_from_request", return_value=human):
        response = asyncio.run(
            routes.cancel_data_product_blueprint_test_run(request)
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(
        {
            "run_id": str(run_id),
            "external_cancel_ref": "cancel-1",
            "reason": "governed cancellation converged",
        }
    )
    mismatched.path_params = {
        "run_id": "00000000-0000-4000-8000-000000000749"
    }
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.cancel_data_product_blueprint_test_run(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.complete_blueprint_test_run_cancellation.assert_not_called()


def test_blueprint_provider_reconcile_receipt_is_content_bound_and_execution_provider_only():
    run_id = UUID("00000000-0000-4000-8000-000000000750")
    plan_id = UUID("00000000-0000-4000-8000-000000000751")
    payload = _provider_reconcile_payload(run_id=run_id, plan_id=plan_id)
    receipt = DataProductBlueprintProviderReconcileRequest.model_validate(payload)
    assert receipt.provider_state == "running"
    assert receipt.attempt_observation.framework_kind == FrameworkKind.SPARK

    tampered = {**payload, "reason": "tampered reason"}
    with pytest.raises(ValueError, match="receipt fingerprint"):
        DataProductBlueprintProviderReconcileRequest.model_validate(tampered)

    scheduler_observation = receipt.attempt_observation.model_copy(
        update={"framework_kind": FrameworkKind.DOLPHINSCHEDULER}
    )
    scheduler_payload = {
        **payload,
        "attempt_observation": scheduler_observation,
    }
    scheduler_payload["reconcile_receipt_sha256"] = (
        data_product_blueprint_provider_reconcile_fingerprint(scheduler_payload)
    )
    with pytest.raises(ValueError, match="execution provider"):
        DataProductBlueprintProviderReconcileRequest.model_validate(scheduler_payload)


def test_blueprint_provider_reconcile_route_requires_workload_and_matches_identities():
    run_id = UUID("00000000-0000-4000-8000-000000000750")
    plan_id = UUID("00000000-0000-4000-8000-000000000751")
    payload = _provider_reconcile_payload(run_id=run_id, plan_id=plan_id)
    request = _request(
        DataProductBlueprintProviderReconcileRequest.model_validate(payload).model_dump(
            mode="json"
        )
    )
    request.path_params = {"run_id": str(run_id)}
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(identifier="planner"),
    ):
        response = asyncio.run(
            routes.reconcile_data_product_blueprint_test_provider(request)
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(
        DataProductBlueprintProviderReconcileRequest.model_validate(payload).model_dump(
            mode="json"
        )
    )
    mismatched.path_params = {
        "run_id": "00000000-0000-4000-8000-000000000753"
    }
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.reconcile_data_product_blueprint_test_provider(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.reconcile_blueprint_test_provider.assert_not_called()


    other_tenant = _request(
        DataProductBlueprintProviderReconcileRequest.model_validate(payload).model_dump(
            mode="json"
        )
    )
    other_tenant.path_params = {"run_id": str(run_id)}
    other_workload = _user(tenant_id="other", identifier="blueprint-test-executor")
    other_workload.metadata["subject_type"] = "workload"
    with (
        patch.object(routes, "_get_user_from_request", return_value=other_workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.reconcile_data_product_blueprint_test_provider(other_tenant)
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"
    gateway.reconcile_blueprint_test_provider.assert_not_called()


def test_blueprint_provider_timeout_receipt_and_route_require_exhaustion_and_workload():
    run_id = UUID("00000000-0000-4000-8000-000000000750")
    plan_id = UUID("00000000-0000-4000-8000-000000000751")
    payload = _provider_timeout_payload(run_id=run_id, plan_id=plan_id)
    receipt = DataProductBlueprintProviderCancellationTimeoutRequest.model_validate(
        payload
    )
    assert receipt.reconcile_attempt == receipt.max_reconcile_attempts == 3

    tampered = {**payload, "reason": "tampered timeout reason"}
    with pytest.raises(ValueError, match="receipt fingerprint"):
        DataProductBlueprintProviderCancellationTimeoutRequest.model_validate(tampered)

    not_exhausted = {**payload, "reconcile_attempt": 2}
    not_exhausted["timeout_receipt_sha256"] = (
        data_product_blueprint_provider_cancellation_timeout_fingerprint(not_exhausted)
    )
    with pytest.raises(ValueError, match="exhausted"):
        DataProductBlueprintProviderCancellationTimeoutRequest.model_validate(not_exhausted)

    request = _request(receipt.model_dump(mode="json"))
    request.path_params = {"run_id": str(run_id)}
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.record_data_product_blueprint_provider_cancellation_timeout(request)
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(receipt.model_dump(mode="json"))
    mismatched.path_params = {"run_id": "00000000-0000-4000-8000-000000000753"}
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(
            routes.record_data_product_blueprint_provider_cancellation_timeout(mismatched)
        )
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.record_blueprint_provider_cancellation_timeout.assert_not_called()


def test_blueprint_provider_retry_receipt_binds_backoff_and_route_identity():
    run_id = UUID("00000000-0000-4000-8000-000000000750")
    plan_id = UUID("00000000-0000-4000-8000-000000000751")
    payload = _provider_retry_payload(run_id=run_id, plan_id=plan_id)
    receipt = DataProductBlueprintProviderRetryRequest.model_validate(payload)
    assert data_product_blueprint_provider_retry_backoff_seconds(1) == 5
    assert data_product_blueprint_provider_retry_backoff_seconds(7) == 300

    tampered = {**payload, "reason": "tampered retry reason"}
    with pytest.raises(ValueError, match="receipt fingerprint"):
        DataProductBlueprintProviderRetryRequest.model_validate(tampered)

    exhausted = _provider_retry_payload(
        run_id=run_id,
        plan_id=plan_id,
        retry_attempt=3,
        max_retry_attempts=3,
    )
    with pytest.raises(ValueError, match="exhausted"):
        DataProductBlueprintProviderRetryRequest.model_validate(exhausted)

    request = _request(receipt.model_dump(mode="json"))
    request.path_params = {"run_id": str(run_id)}
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.retry_data_product_blueprint_test_provider(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"

    workload = _user(identifier="blueprint-test-executor")
    workload.metadata["subject_type"] = "workload"
    mismatched = _request(receipt.model_dump(mode="json"))
    mismatched.path_params = {"run_id": "00000000-0000-4000-8000-000000000753"}
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.retry_data_product_blueprint_test_provider(mismatched))
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "run_id_mismatch"
    gateway.retry_blueprint_test_provider.assert_not_called()


def test_blueprint_review_case_binds_exact_change_set_and_bounded_context():
    predecessor = DataProductBlueprint.model_validate(_payload())
    predecessor_definition = compile_data_product_blueprint(predecessor).definition
    payload = {
        **_payload(),
        "definition_version_id": UUID("00000000-0000-4000-8000-000000000732"),
        "predecessor_definition_version_id": predecessor.definition_version_id,
        "version_key": "v1.1.0",
        "model_contract": {"schema": "districts.v2", "geometry": "multipolygon"},
    }
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
    successor = DataProductBlueprint.model_validate(payload)
    preview = build_data_product_blueprint_preview(
        successor,
        predecessor=predecessor_definition,
    )

    approval_case = build_data_product_blueprint_approval_case(
        preview,
        requester_subject="human:planner",
        request_reason="review model contract successor",
        requested_at=datetime(2026, 8, 21, tzinfo=UTC),
        expires_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert approval_case.approval_case_ref.endswith(
        "/data-product-blueprint-00000000000040008000000000000732"
    )
    assert approval_case.target_resource_urn == preview.definition_urn
    assert approval_case.target_fingerprint == preview.change_set_sha256
    assert approval_case.action == "data_product_blueprint.change_review"
    assert approval_case.request_context["change_set_sha256"] == preview.change_set_sha256
    assert approval_case.request_context["product_urn"] == successor.product_urn
    assert approval_case.request_context["version_key"] == successor.version_key
    assert "model_contract" not in approval_case.request_context

    release = build_data_product_blueprint_release_binding(
        preview,
        approval_case_ref=approval_case.approval_case_ref,
    )
    assert release.product_urn == successor.product_urn
    assert release.version_key == successor.version_key
    assert release.definition_version_id == successor.definition_version_id
    assert release.change_set_sha256 == preview.change_set_sha256
    assert release.approval_case_ref == approval_case.approval_case_ref


def test_blueprint_review_route_rebuilds_preview_and_reuses_approval_authority():
    predecessor = DataProductBlueprint.model_validate(_payload())
    predecessor_definition = compile_data_product_blueprint(predecessor).definition
    payload = {
        **_payload(),
        "definition_version_id": UUID("00000000-0000-4000-8000-000000000732"),
        "predecessor_definition_version_id": predecessor.definition_version_id,
        "version_key": "v1.1.0",
        "model_contract": {"schema": "districts.v2", "geometry": "multipolygon"},
    }
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
    body = {
        "blueprint": payload,
        "request_reason": "review model contract successor",
        "requested_at": datetime(2026, 8, 21, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 23, tzinfo=UTC),
    }
    gateway = _PreviewDefinitionGateway(predecessor_definition)
    authority = _IdempotentApprovalAuthority()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        created = asyncio.run(
            routes.create_data_product_blueprint_review(_request(body))
        )
        replayed = asyncio.run(
            routes.create_data_product_blueprint_review(_request(body))
        )

    assert created.status_code == 201
    assert json.loads(created.body)["created"] is True
    assert replayed.status_code == 200
    assert json.loads(replayed.body)["created"] is False
    assert len(authority.cases) == 2
    assert authority.cases[0].target_fingerprint == json.loads(created.body)["data"][
        "preview"
    ]["change_set_sha256"]


def test_blueprint_review_route_rejects_actor_spoofing_before_authority():
    payload = _payload()
    body = {
        "blueprint": payload,
        "request_reason": "review initial definition",
        "requested_at": datetime(2026, 8, 21, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 23, tzinfo=UTC),
    }
    authority = MagicMock()
    with (
        patch.object(
            routes,
            "_get_user_from_request",
            return_value=_user(identifier="other"),
        ),
        patch.object(routes, "_approval_case_authority", return_value=authority),
    ):
        response = asyncio.run(
            routes.create_data_product_blueprint_review(_request(body))
        )

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"
    authority.create.assert_not_called()


@pytest.mark.parametrize(
    "field, value",
    [
        ("product_urn", "gda://planning/dataset/not-a-product"),
        ("source_refs", ("gda://planning/dataset/source", "gda://planning/dataset/source")),
        ("source_refs", ("gda://other/dataset/source",)),
        ("storage_placement", {}),
    ],
)
def test_blueprint_rejects_invalid_identity_or_empty_contract(field, value):
    payload = _payload()
    payload[field] = value
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)

    with pytest.raises(ValueError):
        DataProductBlueprint.model_validate(payload)


def test_blueprint_route_compiles_into_existing_authority_and_is_idempotent():
    gateway = _IdempotentDefinitionGateway()
    payload = _payload()
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        created = asyncio.run(routes.create_data_product_blueprint(_request(payload)))
        replayed = asyncio.run(routes.create_data_product_blueprint(_request(payload)))

    assert created.status_code == 201
    assert json.loads(created.body)["created"] is True
    assert replayed.status_code == 200
    assert json.loads(replayed.body)["created"] is False
    assert len(gateway.registrations) == 2
    registration = gateway.registrations[0]
    assert registration.resource.resource_urn == payload["definition_urn"]
    assert registration.definition.definition_document["product_urn"] == payload[
        "product_urn"
    ]


@pytest.mark.parametrize(
    "user, payload_update, error_code",
    [
        (_user(identifier="other"), {}, "actor_mismatch"),
        (_user(tenant_id="other"), {}, "tenant_mismatch"),
        (_user(), {"storage_placement": {}}, "contract_validation_failed"),
    ],
)
def test_blueprint_route_rejects_spoofed_or_invalid_payloads(
    user, payload_update, error_code
):
    payload = {**_payload(), **payload_update}
    payload["blueprint_sha256"] = data_product_blueprint_fingerprint(payload)
    gateway = MagicMock()
    with (
        patch.object(routes, "_get_user_from_request", return_value=user),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_data_product_blueprint(_request(payload)))

    assert response.status_code in {403, 422}
    assert json.loads(response.body)["error"]["code"] == error_code
    gateway.register_definition.assert_not_called()
