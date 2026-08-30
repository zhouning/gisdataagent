"""Contracts for governed metric query execution admission and receipts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from data_agent.api import metric_query_routes
from data_agent.metric_query import MetricQueryPlanner, MetricQueryRequest
from data_agent.metric_query_execution import (
    MetricQueryCacheStatus,
    MetricQueryCompletionSpec,
    MetricQueryExecutionAdmission,
    MetricQueryExecutionAuthority,
    MetricQueryExecutionValidationError,
    MetricQueryOutcome,
    MetricQueryRunRecord,
    _execution_definition_registration,
)
from data_agent.platform_contracts import (
    Artifact,
    PlatformRun,
    SubjectContext,
)
from data_agent.test_metric_query_planning import (
    NOW,
    TENANT,
    _active_projection,
    _metric,
    _security,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000000401")
PLAN_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000402")
START_OBSERVATION_ID = UUID("00000000-0000-4000-8000-000000000403")


def _plan():
    return MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        _security(),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )


def _admission() -> MetricQueryExecutionAdmission:
    plan = _plan()
    registration = _execution_definition_registration(TENANT, plan.execution_mode)
    return MetricQueryExecutionAdmission(
        tenant_id=TENANT,
        run_id=RUN_ID,
        client_request_id="metric-query-401",
        definition_version_id=registration.definition.definition_version_id,
        plan_artifact_id=PLAN_ARTIFACT_ID,
        plan=plan,
        plan_fingerprint="f" * 64,
        cache_key=plan.cache_key,
        engine=plan.engine,
        execution_mode=plan.execution_mode,
        admitted_by="human:analyst",
        admitted_at=NOW,
    )


def _record(*, admitted_by: str = "human:analyst") -> MetricQueryRunRecord:
    admission = _admission().model_copy(update={"admitted_by": admitted_by})
    subject_type, subject_id = admitted_by.split(":", 1)
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=admission.definition_version_id,
        orchestration_class="synchronous",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id=subject_id,
            subject_type=subject_type,
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        idempotency_key="metric-query:v1:metric-query-401",
        config_fingerprint=admission.cache_key,
        submitted_at=NOW,
    )
    plan_artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ARTIFACT_ID,
        artifact_key="metric-query-plan",
        artifact_role="execution_plan",
        storage_uri=f"postgresql://gda-control/metric-query-plan/{RUN_ID}",
        media_type="application/vnd.gda.metric-query-plan+json",
        content_sha256=admission.plan_fingerprint,
        size_bytes=1024,
        run_id=RUN_ID,
        created_by=admitted_by,
        created_at=NOW,
    )
    return MetricQueryRunRecord(
        admission=admission,
        run=run,
        plan_artifact=plan_artifact,
    )


def _request(
    method: str,
    *,
    body: dict | None = None,
    path_params: dict[str, str] | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/platform/v1/metric-query-runs",
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-gda-query-purpose", b"natural_resource_reporting"),
            ],
            "query_string": b"",
            "path_params": path_params or {},
        },
        receive,
    )


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


def test_executor_definitions_are_deterministic_and_mode_specific() -> None:
    sync_first = _execution_definition_registration(TENANT, "synchronous")
    sync_replay = _execution_definition_registration(TENANT, "synchronous")
    batch = _execution_definition_registration(TENANT, "asynchronous")

    assert sync_first == sync_replay
    assert sync_first.definition.definition_version_id != (
        batch.definition.definition_version_id
    )
    assert sync_first.definition.orchestration_class.value == "synchronous"
    assert batch.definition.orchestration_class.value == "dataops"
    assert sync_first.definition.definition_document["engines"] == [
        "postgis",
        "duckdb",
    ]
    assert batch.definition.definition_document["engines"] == ["iceberg_spark"]


def test_admission_rejects_plan_from_another_security_context_before_database() -> None:
    plan = _plan()

    with pytest.raises(
        MetricQueryExecutionValidationError,
        match="does not bind this security context",
    ):
        MetricQueryExecutionAuthority(engine=object()).admit(
            plan,
            _security(subject_ref="human:other-analyst"),
            "metric-query-security-mismatch",
            admitted_at=NOW,
        )


def test_admission_binds_exact_plan_identity() -> None:
    admission = _admission()

    assert admission.plan.cache_key == admission.cache_key
    assert admission.plan.engine == admission.engine
    with pytest.raises(ValidationError, match="bind the exact plan"):
        MetricQueryExecutionAdmission(
            **{
                **admission.model_dump(),
                "cache_key": "0" * 64,
            }
        )


def test_completion_requires_exactly_one_success_result_or_failure_error() -> None:
    success = MetricQueryCompletionSpec(
        start_observation_id=START_OBSERVATION_ID,
        outcome=MetricQueryOutcome.SUCCEEDED,
        cache_status=MetricQueryCacheStatus.MISS,
        rows_returned=12,
        rows_scanned=100,
        bytes_scanned=4096,
        duration_ms=25,
        result_storage_uri="s3://metric-results/query-401.parquet",
        result_media_type="application/vnd.apache.parquet",
        result_sha256="a" * 64,
        result_size_bytes=2048,
        observed_at=NOW,
    )
    failure = MetricQueryCompletionSpec(
        start_observation_id=START_OBSERVATION_ID,
        outcome=MetricQueryOutcome.FAILED,
        duration_ms=25,
        error_code="provider_timeout",
        error_message="provider did not finish before its deadline",
        observed_at=NOW,
    )

    assert success.result_sha256 == "a" * 64
    assert failure.result_storage_uri is None
    with pytest.raises(ValidationError, match="requires result evidence only"):
        MetricQueryCompletionSpec(
            start_observation_id=START_OBSERVATION_ID,
            outcome=MetricQueryOutcome.SUCCEEDED,
            duration_ms=25,
            error_code="invalid_result",
            error_message="result is missing",
            observed_at=NOW,
        )
    with pytest.raises(ValidationError, match="requires error evidence only"):
        MetricQueryCompletionSpec(
            start_observation_id=START_OBSERVATION_ID,
            outcome=MetricQueryOutcome.FAILED,
            duration_ms=25,
            result_storage_uri="s3://metric-results/query-401.parquet",
            result_media_type="application/vnd.apache.parquet",
            result_sha256="a" * 64,
            result_size_bytes=2048,
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "storage_uri",
    (
        "ftp://metric-results/query.csv",
        "s3://user:secret@metric-results/query.csv",
        "https://metric-results/query.csv?signature=secret",
        "file://remote-host/query.csv",
        "file:relative/query.csv",
    ),
)
def test_completion_rejects_unsafe_result_uri(storage_uri: str) -> None:
    with pytest.raises(ValidationError, match=r"result (storage )?URI"):
        MetricQueryCompletionSpec(
            start_observation_id=START_OBSERVATION_ID,
            outcome=MetricQueryOutcome.SUCCEEDED,
            duration_ms=25,
            result_storage_uri=storage_uri,
            result_media_type="text/csv",
            result_sha256="a" * 64,
            result_size_bytes=128,
            observed_at=NOW,
        )


def test_run_record_requires_exact_run_and_plan_artifact_binding() -> None:
    record = _record()

    assert record.run.run_id == RUN_ID
    with pytest.raises(ValidationError, match="not exactly bound"):
        MetricQueryRunRecord(
            admission=record.admission,
            run=record.run,
            plan_artifact=record.plan_artifact.model_copy(
                update={"content_sha256": "0" * 64}
            ),
        )


@pytest.mark.asyncio
async def test_run_admission_api_replans_and_never_accepts_a_client_plan(
    monkeypatch,
) -> None:
    plan = _plan()
    planner = Mock()
    planner.plan.return_value = plan
    authority = Mock()
    authority.admit.return_value = _record()
    monkeypatch.setattr(
        metric_query_routes,
        "_get_user_from_request",
        lambda request: _user(),
    )
    monkeypatch.setattr(metric_query_routes, "_query_planner", lambda: planner)
    monkeypatch.setattr(
        metric_query_routes,
        "_query_execution_authority",
        lambda: authority,
    )

    response = await metric_query_routes.create_metric_query_run(
        _request(
            "POST",
            body={
                "client_request_id": "metric-query-api-001",
                "query": {"metric_name": "land_area"},
            },
        )
    )

    assert response.status_code == 202
    planned_request, security = planner.plan.call_args.args
    assert planned_request.metric_name == "land_area"
    assert security.subject_ref == "human:analyst"
    assert security.purpose == "natural_resource_reporting"
    assert authority.admit.call_args.args == (
        plan,
        security,
        "metric-query-api-001",
    )

    rejected = await metric_query_routes.create_metric_query_run(
        _request(
            "POST",
            body={
                "client_request_id": "metric-query-api-002",
                "query": {"metric_name": "land_area"},
                "plan": plan.model_dump(mode="json"),
            },
        )
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_run_read_is_limited_to_submitter_or_platform_operator(
    monkeypatch,
) -> None:
    authority = Mock()
    authority.get.return_value = _record(admitted_by="human:owner")
    monkeypatch.setattr(
        metric_query_routes,
        "_query_execution_authority",
        lambda: authority,
    )
    monkeypatch.setattr(
        metric_query_routes,
        "_get_user_from_request",
        lambda request: _user(),
    )
    request = _request("GET", path_params={"run_id": str(RUN_ID)})

    forbidden = await metric_query_routes.get_metric_query_run(request)

    assert forbidden.status_code == 403
    monkeypatch.setattr(
        metric_query_routes,
        "_get_user_from_request",
        lambda request: _user("operator", role="platform_operator"),
    )
    allowed = await metric_query_routes.get_metric_query_run(
        _request("GET", path_params={"run_id": str(RUN_ID)})
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    (
        metric_query_routes.start_metric_query_run,
        metric_query_routes.complete_metric_query_run,
    ),
)
async def test_provider_receipt_apis_require_workload_identity(
    monkeypatch,
    endpoint,
) -> None:
    monkeypatch.setattr(
        metric_query_routes,
        "_principal",
        lambda request: metric_query_routes.GatewayPrincipal(
            TENANT,
            "operator",
            metric_query_routes.SubjectType.HUMAN,
            "platform_operator",
        ),
    )

    response = await endpoint(
        _request("POST", path_params={"run_id": str(RUN_ID)})
    )

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "workload_identity_required"


def test_metric_query_execution_migration_is_evidence_gated_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/137_metric_query_run_evidence.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.metric_query_execution_admission",
        "CREATE TABLE IF NOT EXISTS gda_control.metric_query_execution_observation",
        "admit_metric_query_execution",
        "start_metric_query_execution",
        "complete_metric_query_execution",
        "exact active metric and projection evidence",
        "apply_platform_run_transition",
        "result Artifact evidence",
        "FORCE ROW LEVEL SECURITY",
        "reject_immutable_mutation",
        "GRANT SELECT ON gda_control.metric_query_execution_admission",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.metric_query_execution_admission" not in sql
    assert "GRANT INSERT ON gda_control.metric_query_execution_observation" not in sql
