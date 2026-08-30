from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from data_agent.governed_query import (
    AdmissionState,
    Claim,
    EvidenceCitation,
    EvidenceItem,
    GovernedQueryRequest,
    GovernedQueryResponse,
    QueryChannel,
    QueryExecutionStatus,
    QueryPolicyDeniedError,
    execute_governed_query,
    plan_query_route,
    verify_claim_citations,
)
from data_agent.governed_rag import GovernedRAGError, GovernedRAGHit
from data_agent.metric_query import (
    MetricQueryPlanner,
    MetricQueryRequest,
    MetricQuerySecurityContext,
)
from data_agent.metric_query_execution import (
    MetricQueryCacheStatus,
    MetricQueryExecutionAuthority,
    MetricQueryExecutionConfigurationError,
    MetricQueryExecutionObservation,
    MetricQueryOutcome,
)
from data_agent.nl2sql_source_authority import NL2SQLSourceBinding
from data_agent.platform_contracts import ResourceVersion, RunStatus, SubjectContext, SubjectType
from data_agent.test_metric_query_execution import RUN_ID, _record
from data_agent.test_metric_query_planning import (
    NOW,
    TENANT,
    _active_projection,
    _metric,
)


def _request(**overrides) -> GovernedQueryRequest:
    payload = {
        "request_id": "feidu-slice-001",
        "question": "土地是什么？",
        "purpose": "validate governed ontology query",
        "channel": "auto",
        "ontology_plan": {
            "query_type": "concept_explanation",
            "subject": "土地",
        },
    }
    payload.update(overrides)
    return GovernedQueryRequest.model_validate(payload)


def _subject(purpose: str = "validate governed ontology query") -> SubjectContext:
    return SubjectContext(
        tenant_id="tenant-a",
        subject_id="analyst-a",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose=purpose,
        trace_id="feidu-slice-001",
    )


def _rag_request(**overrides) -> GovernedQueryRequest:
    digest = "a" * 64
    payload = {
        "request_id": "rag-route-001",
        "question": "规划政策有哪些要求？",
        "purpose": "governed policy retrieval",
        "channel": "rag",
        "rag_request": {"knowledge_base_ids": [7], "top_k": 2},
        "resource_version_refs": [{
            "resource_kind": "document",
            "resource_id": "kb:7/documents/11",
            "version": f"sha256-{digest}",
            "content_sha256": digest,
        }],
        "budget": {
            "max_result_items": 2,
            "max_evidence_items": 2,
            "max_result_bytes": 10_000,
        },
    }
    payload.update(overrides)
    return GovernedQueryRequest.model_validate(payload)


def test_request_rejects_identity_spoofing_and_arbitrary_query_language() -> None:
    with pytest.raises(ValidationError, match="tenant_id"):
        GovernedQueryRequest.model_validate({
            **_request().model_dump(mode="json"),
            "tenant_id": "spoofed",
        })
    with pytest.raises(ValidationError, match="sql"):
        GovernedQueryRequest.model_validate({
            **_request().model_dump(mode="json"),
            "ontology_plan": {
                "query_type": "concept_explanation",
                "subject": "土地",
                "sql": "DROP TABLE ontology",
            },
        })


def test_deterministic_router_requires_a_validated_plan() -> None:
    admitted = plan_query_route(_request())
    assert admitted.admission is AdmissionState.ADMITTED
    assert admitted.selected_channel is QueryChannel.ONTOLOGY
    assert admitted.adapter_id == "gda.ontology.typed-query.v1"
    assert "validated ontology_plan" in admitted.reasons[0]

    unresolved = plan_query_route(_request(ontology_plan=None))
    assert unresolved.admission is AdmissionState.NOT_ADMITTED
    assert unresolved.selected_channel is None
    assert "question text alone is not executable" in unresolved.reasons[0]


def test_typed_plan_cannot_exceed_the_result_budget() -> None:
    with pytest.raises(ValidationError, match="max_result_items"):
        _request(
            budget={"max_result_items": 10},
            ontology_plan={
                "query_type": "hierarchy",
                "subject": "土地",
                "limit": 11,
            },
        )


def test_rag_channel_requires_a_typed_version_pinned_request() -> None:
    with pytest.raises(ValidationError, match="rag_request"):
        _request(channel="rag", ontology_plan=None)

    with pytest.raises(ValidationError, match="content_sha256"):
        _request(
            channel="rag",
            ontology_plan=None,
            rag_request={"knowledge_base_ids": [7]},
            resource_version_refs=[{
                "resource_kind": "document",
                "resource_id": "kb:7/documents/11",
                "version": "sha256-" + "a" * 64,
            }],
        )


def test_governed_rag_returns_verified_chunk_evidence(monkeypatch) -> None:
    document_digest = "a" * 64
    chunk_digest = "b" * 64
    monkeypatch.setattr(
        "data_agent.governed_query.search_governed_knowledge_base",
        lambda **kwargs: (
            GovernedRAGHit(
                chunk_id=19,
                knowledge_base_id=7,
                document_id=11,
                document_resource_id="kb:7/documents/11",
                document_version=f"sha256-{document_digest}",
                document_content_sha256=document_digest,
                chunk_index=0,
                content="规划审批必须保留版本化依据。",
                chunk_content_sha256=chunk_digest,
                locator="kb:7/documents/11/chunks/0",
                filename="policy.txt",
                content_type="text/plain",
                score=0.98,
            ),
        ),
    )

    result = execute_governed_query(
        _rag_request(),
        _subject("governed policy retrieval"),
    )

    assert result.status is QueryExecutionStatus.COMPLETED
    assert result.route_plan.selected_channel is QueryChannel.RAG
    assert result.route_plan.adapter_id == "gda.rag.versioned-evidence.v1"
    assert result.result["execution"]["rows"] == 1
    assert result.usage.llm_calls == 0
    assert result.evidence_bundle.verification.valid is True
    evidence = result.evidence_bundle.evidence[0]
    assert evidence.source_kind == "document"
    assert evidence.resource_version_ref == (
        f"kb:7/documents/11@sha256-{document_digest}"
    )
    assert evidence.locator == "kb:7/documents/11/chunks/0"
    assert evidence.content_sha256 == chunk_digest


def test_governed_rag_authority_failure_is_not_admitted(monkeypatch) -> None:
    monkeypatch.setattr(
        "data_agent.governed_query.search_governed_knowledge_base",
        lambda **kwargs: (_ for _ in ()).throw(
            GovernedRAGError("document digest changed after ingestion")
        ),
    )

    result = execute_governed_query(
        _rag_request(),
        _subject("governed policy retrieval"),
    )

    assert result.status is QueryExecutionStatus.NOT_ADMITTED
    assert result.result is None
    assert result.evidence_bundle.evidence == ()
    assert any("digest changed" in reason for reason in result.route_plan.reasons)


def test_citation_verifier_rejects_unknown_and_digest_mismatched_sources() -> None:
    item = EvidenceItem(
        evidence_id="ev_" + "a" * 24,
        source_kind="document",
        source_id="feidu-requirements",
        resource_version_ref="feidu-requirements@1",
        locator="page:12",
        content_sha256="b" * 64,
        retrieved_at="2026-08-13T00:00:00Z",
    )
    claims = [
        Claim(
            claim_id="claim_001",
            statement="A claim with a fabricated source.",
            citations=(EvidenceCitation(
                evidence_id="ev_" + "f" * 24,
                content_sha256="b" * 64,
            ),),
        ),
        Claim(
            claim_id="claim_002",
            statement="A claim with a changed source digest.",
            citations=(EvidenceCitation(
                evidence_id=item.evidence_id,
                content_sha256="c" * 64,
            ),),
        ),
    ]

    verification = verify_claim_citations([item], claims)
    assert verification.valid is False
    assert verification.verified_claim_count == 0
    assert {issue.code for issue in verification.issues} == {
        "unknown_evidence",
        "digest_mismatch",
    }


def test_real_ontology_execution_returns_versioned_verified_evidence(monkeypatch) -> None:
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    result = execute_governed_query(_request(), _subject())

    assert result.status is QueryExecutionStatus.COMPLETED
    assert result.subject_context.tenant_id == "tenant-a"
    assert result.policy.effect == "allow"
    assert result.result["status"] == "ok"
    assert result.evidence_bundle.verification.valid is True
    assert result.evidence_bundle.verification.verified_claim_count >= 1
    evidence = result.evidence_bundle.evidence[0]
    assert evidence.source_kind == "ontology_package"
    assert len(evidence.content_sha256) == 64
    assert evidence.resource_version_ref.endswith(
        f"@{result.result['ontology_evidence']['semantic_version']}"
    )
    assert result.usage.llm_calls == 0
    assert result.usage.estimated_cost_usd == 0


def test_requested_ontology_version_mismatch_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    request = _request(resource_version_refs=[{
        "resource_kind": "ontology_package",
        "resource_id": "natural-resource-one-map",
        "version": "0.0.0",
    }])
    result = execute_governed_query(request, _subject())

    assert result.status is QueryExecutionStatus.NOT_ADMITTED
    assert result.result is None
    assert any("does not match active version" in reason for reason in result.route_plan.reasons)


def test_subject_purpose_and_role_are_enforced() -> None:
    with pytest.raises(QueryPolicyDeniedError, match="purpose"):
        execute_governed_query(_request(), _subject("different purpose"))

    subject = _subject().model_copy(update={"roles": ("anonymous",)})
    with pytest.raises(QueryPolicyDeniedError, match="role"):
        execute_governed_query(_request(), subject)


def test_metric_route_returns_planned_status_and_plan_evidence(monkeypatch) -> None:
    metric = _metric()
    projection = _active_projection()
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        metric,
        (projection,),
        now=NOW,
    )
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    request = _request(
        request_id="metric-route-001",
        question="查询土地面积",
        purpose="metric planning request",
        purpose_code="natural_resource_reporting",
        channel="metric",
        ontology_plan=None,
        metric_request={"metric_name": "land_area"},
    )
    subject = _subject("metric planning request").model_copy(
        update={"tenant_id": TENANT}
    )

    result = execute_governed_query(request, subject)

    assert result.status is QueryExecutionStatus.PLANNED
    assert result.route_plan.selected_channel is QueryChannel.METRIC
    assert result.route_plan.admission is AdmissionState.ADMITTED
    assert result.result["status"] == "planned"
    assert result.evidence_bundle.verification.valid is True
    assert len(result.evidence_bundle.evidence) == 3
    assert any("provider observation" in item for item in result.evidence_bundle.missing_evidence)


def test_metric_request_requires_controlled_purpose_code() -> None:
    with pytest.raises(ValidationError, match="purpose_code"):
        _request(
            channel="metric",
            ontology_plan=None,
            metric_request={"metric_name": "land_area"},
        )


def test_metric_channel_requires_typed_request() -> None:
    with pytest.raises(ValidationError, match="metric_request"):
        _request(channel="metric", ontology_plan=None)


def test_metric_run_admission_returns_run_ref_and_plan_artifact(monkeypatch) -> None:
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )
    record = _record().model_copy(update={
        "admission": _record().admission.model_copy(update={
            "plan": expected_plan,
            "cache_key": expected_plan.cache_key,
            "client_request_id": "metric-route-run-001",
        }),
        "run": _record().run.model_copy(update={
            "run_id": RUN_ID,
            "config_fingerprint": expected_plan.cache_key,
        }),
    })
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: record,
    )
    request = _request(
        request_id="metric-route-run-001",
        question="提交土地面积指标查询",
        purpose="metric run admission",
        purpose_code="natural_resource_reporting",
        channel="metric",
        ontology_plan=None,
        metric_request={"metric_name": "land_area"},
        metric_execution_mode="admit_run",
    )
    subject = _subject("metric run admission").model_copy(
        update={"tenant_id": TENANT}
    )

    result = execute_governed_query(request, subject)

    assert result.status is QueryExecutionStatus.RUN_ADMITTED
    assert result.run_ref is not None
    assert result.run_ref.run_id == RUN_ID
    assert result.run_ref.observation_status == "not_started"
    assert result.run_ref.result_artifact_id is None
    assert len(result.evidence_bundle.evidence) == 4
    assert result.evidence_bundle.evidence[-1].source_kind == "execution_plan"
    assert any("not yet available" in item for item in result.evidence_bundle.missing_evidence)


def test_metric_run_admission_failure_does_not_fall_back_to_planned(monkeypatch) -> None:
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: MetricQueryPlanner().plan_from(
            request,
            security,
            _metric(),
            (_active_projection(),),
            now=NOW,
        ),
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: (_ for _ in ()).throw(
            MetricQueryExecutionConfigurationError("PostgreSQL control plane unavailable")
        ),
    )
    request = _request(
        request_id="metric-route-run-002",
        question="提交土地面积指标查询",
        purpose="metric run admission",
        purpose_code="natural_resource_reporting",
        channel="metric",
        ontology_plan=None,
        metric_request={"metric_name": "land_area"},
        metric_execution_mode="admit_run",
    )
    subject = _subject("metric run admission").model_copy(
        update={"tenant_id": TENANT}
    )

    result = execute_governed_query(request, subject)

    assert result.status is QueryExecutionStatus.NOT_ADMITTED
    assert result.result is None
    assert result.run_ref is None
    assert any("PostgreSQL control plane unavailable" in item for item in result.route_plan.reasons)


def test_metric_run_replay_projects_completed_result_reference(monkeypatch) -> None:
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )
    base = _record()
    observation = MetricQueryExecutionObservation(
        tenant_id=TENANT,
        query_observation_id="00000000-0000-4000-8000-000000000411",
        run_id=RUN_ID,
        attempt_no=1,
        start_observation_id="00000000-0000-4000-8000-000000000412",
        terminal_observation_id="00000000-0000-4000-8000-000000000413",
        result_artifact_id="00000000-0000-4000-8000-000000000414",
        outcome=MetricQueryOutcome.SUCCEEDED,
        cache_status=MetricQueryCacheStatus.MISS,
        rows_returned=10,
        rows_scanned=100,
        bytes_scanned=4096,
        duration_ms=50,
        result_sha256="d" * 64,
        observed_at=NOW,
        recorded_by="workload:metric-provider",
    )
    record = base.model_copy(update={
        "admission": base.admission.model_copy(update={
            "plan": expected_plan,
            "cache_key": expected_plan.cache_key,
            "client_request_id": "metric-route-run-003",
        }),
        "run": base.run.model_copy(update={
            "status": RunStatus.SUCCEEDED,
            "state_version": 3,
            "config_fingerprint": expected_plan.cache_key,
        }),
        "observation": observation,
    })
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: record,
    )
    request = _request(
        request_id="metric-route-run-003",
        question="查询已完成的土地面积指标运行",
        purpose="metric run replay",
        purpose_code="natural_resource_reporting",
        channel="metric",
        ontology_plan=None,
        metric_request={"metric_name": "land_area"},
        metric_execution_mode="admit_run",
    )
    subject = _subject("metric run replay").model_copy(update={"tenant_id": TENANT})

    result = execute_governed_query(request, subject)

    assert result.status is QueryExecutionStatus.RUN_SUCCEEDED
    assert result.run_ref is not None
    assert result.run_ref.outcome == "succeeded"
    assert str(result.run_ref.result_artifact_id).endswith("0414")
    assert result.run_ref.result_access_path.endswith(f"/{RUN_ID}/result-access")
    assert result.evidence_bundle.missing_evidence == ()
    assert result.evidence_bundle.evidence[-1].source_kind == "query_result"


def test_response_rejects_run_status_without_run_reference() -> None:
    completed = execute_governed_query(_request(), _subject())
    payload = completed.model_dump(mode="json", by_alias=True)
    payload["status"] = "run_admitted"

    with pytest.raises(ValidationError, match="run_admitted requires run_ref"):
        GovernedQueryResponse.model_validate(payload)


def test_response_rejects_success_without_result_evidence(monkeypatch) -> None:
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )
    base = _record()
    record = base.model_copy(update={
        "admission": base.admission.model_copy(update={
            "plan": expected_plan,
            "cache_key": expected_plan.cache_key,
            "client_request_id": "metric-route-run-004",
        }),
        "run": base.run.model_copy(update={
            "config_fingerprint": expected_plan.cache_key,
        }),
    })
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: record,
    )
    result = execute_governed_query(
        _request(
            request_id="metric-route-run-004",
            question="提交土地面积指标查询",
            purpose="metric result invariant",
            purpose_code="natural_resource_reporting",
            channel="metric",
            ontology_plan=None,
            metric_request={"metric_name": "land_area"},
            metric_execution_mode="admit_run",
        ),
        _subject("metric result invariant").model_copy(update={"tenant_id": TENANT}),
    )
    payload = result.model_dump(mode="json", by_alias=True)
    payload["status"] = "run_succeeded"
    payload["run_ref"]["run_status"] = "succeeded"

    with pytest.raises(ValidationError, match="result artifact access"):
        GovernedQueryResponse.model_validate(payload)


def test_response_rejects_failed_run_with_result_artifact(monkeypatch) -> None:
    expected_plan = MetricQueryPlanner().plan_from(
        MetricQueryRequest(metric_name="land_area"),
        MetricQuerySecurityContext(
            tenant_id=TENANT,
            subject_ref="human:analyst-a",
            roles=("analyst",),
            purpose="natural_resource_reporting",
        ),
        _metric(),
        (_active_projection(),),
        now=NOW,
    )
    base = _record()
    record = base.model_copy(update={
        "admission": base.admission.model_copy(update={
            "plan": expected_plan,
            "cache_key": expected_plan.cache_key,
            "client_request_id": "metric-route-run-005",
        }),
        "run": base.run.model_copy(update={
            "config_fingerprint": expected_plan.cache_key,
        }),
    })
    monkeypatch.setattr(
        MetricQueryPlanner,
        "plan",
        lambda self, request, security, now=None: expected_plan,
    )
    monkeypatch.setattr(
        MetricQueryExecutionAuthority,
        "admit",
        lambda self, plan, security, client_request_id: record,
    )
    result = execute_governed_query(
        _request(
            request_id="metric-route-run-005",
            question="提交土地面积指标查询",
            purpose="metric failure invariant",
            purpose_code="natural_resource_reporting",
            channel="metric",
            ontology_plan=None,
            metric_request={"metric_name": "land_area"},
            metric_execution_mode="admit_run",
        ),
        _subject("metric failure invariant").model_copy(update={"tenant_id": TENANT}),
    )
    payload = result.model_dump(mode="json", by_alias=True)
    payload["status"] = "run_failed"
    payload["run_ref"].update({
        "run_status": "failed",
        "observation_status": "completed",
        "outcome": "failed",
        "result_artifact_id": "00000000-0000-4000-8000-000000000414",
        "result_access_path": "/api/platform/v1/metric-query-runs/fake/result-access",
    })

    with pytest.raises(ValidationError, match="cannot expose"):
        GovernedQueryResponse.model_validate(payload)


def _nl2sql_binding(*, source_mode: str = "immutable_snapshot") -> NL2SQLSourceBinding:
    version = ResourceVersion(
        tenant_id="tenant-a",
        resource_urn="gda://tenant-a/dataset/land-parcels",
        resource_version_id="00000000-0000-4000-8000-000000000601",
        version_key="sha256-aaaaaaaaaaaa",
        content_sha256="a" * 64,
        authority_version_ref={
            "postgis_table": "land_parcels_snapshot",
            "source_mode": source_mode,
        },
        created_by="workload:ingestion-provider",
        created_at=NOW,
    )
    return NL2SQLSourceBinding.create(
        tenant_id="tenant-a",
        semantic_source_name="land_parcels_snapshot",
        execution_engine="postgis",
        physical_locator="land_parcels_snapshot",
        source_mode=source_mode,
        resource_version=version,
    )


def _nl2sql_request(**overrides) -> GovernedQueryRequest:
    payload = {
        "request_id": "nl2sql-route-001",
        "question": "统计地块数量",
        "purpose": "governed parcel count",
        "channel": "nl2sql",
        "nl2sql_request": {
            "execution_engine": "postgis",
            "semantic_source_names": ["land_parcels_snapshot"],
        },
        "budget": {
            "max_result_items": 100,
            "max_evidence_items": 5,
            "max_llm_tokens": 1000,
            "max_cost_usd": 1.0,
        },
    }
    payload.update(overrides)
    return GovernedQueryRequest.model_validate(payload)


def test_nl2sql_executes_only_with_immutable_versioned_sources(monkeypatch) -> None:
    binding = _nl2sql_binding()
    monkeypatch.setattr(
        "data_agent.nl2sql_source_authority.NL2SQLSourceAuthority.resolve",
        lambda self, tenant_id, source_name, engine: binding,
    )
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda *args, **kwargs: json.dumps({
            "status": "ok",
            "sql": "SELECT COUNT(*) AS count FROM land_parcels_snapshot",
            "execution_engine": "postgis",
            "execution": {"status": "ok", "rows": 1, "data": [{"count": 42}]},
            "llm_usage": {
                "calls": 1,
                "input_tokens": 120,
                "output_tokens": 20,
                "total_tokens": 140,
                "estimated_cost_usd": 0.01,
                "cost_status": "estimated",
            },
        }),
    )

    result = execute_governed_query(
        _nl2sql_request(),
        _subject("governed parcel count"),
    )

    assert result.status is QueryExecutionStatus.COMPLETED
    assert result.result["nl2sql_sources"] == [
        binding.model_dump(mode="json", by_alias=True)
    ]
    assert result.usage.llm_calls == 1
    assert result.usage.input_tokens == 120
    assert result.usage.estimated_cost_usd == 0.01
    assert result.evidence_bundle.verification.valid is True
    assert [item.source_kind for item in result.evidence_bundle.evidence] == [
        "dataset",
        "query_result",
    ]


def test_nl2sql_mutable_source_fails_closed_before_llm(monkeypatch) -> None:
    binding = _nl2sql_binding(source_mode="mutable_view")
    monkeypatch.setattr(
        "data_agent.nl2sql_source_authority.NL2SQLSourceAuthority.resolve",
        lambda self, tenant_id, source_name, engine: binding,
    )
    executed = False

    def fake_execute(*args, **kwargs):
        nonlocal executed
        executed = True
        return "{}"

    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        fake_execute,
    )

    result = execute_governed_query(
        _nl2sql_request(),
        _subject("governed parcel count"),
    )

    assert result.status is QueryExecutionStatus.NOT_ADMITTED
    assert executed is False
    assert any("mutable" in reason for reason in result.route_plan.reasons)


def test_nl2sql_unknown_cost_is_not_reported_within_budget(monkeypatch) -> None:
    binding = _nl2sql_binding()
    monkeypatch.setattr(
        "data_agent.nl2sql_source_authority.NL2SQLSourceAuthority.resolve",
        lambda self, tenant_id, source_name, engine: binding,
    )
    monkeypatch.setattr(
        "data_agent.nl2sql_executor.run_nl2semantic2sql",
        lambda *args, **kwargs: json.dumps({
            "status": "ok",
            "sql": "SELECT COUNT(*) FROM land_parcels_snapshot",
            "execution_engine": "postgis",
            "execution": {"status": "ok", "rows": 1, "data": [{"count": 42}]},
            "llm_usage": {
                "calls": 1,
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "estimated_cost_usd": None,
                "cost_status": "unavailable",
            },
        }),
    )

    result = execute_governed_query(
        _nl2sql_request(),
        _subject("governed parcel count"),
    )

    assert result.status is QueryExecutionStatus.NEEDS_CLARIFICATION
    assert result.usage.estimated_cost_usd is None
    assert result.usage.within_budget is False
    assert result.usage.budget_verification_issues == ("llm_cost_unavailable",)
