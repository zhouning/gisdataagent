"""Result-access contracts for governed GIS analysis."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest
from starlette.requests import Request

from data_agent.api import gis_analysis_routes
from data_agent.gis_analysis_execution import (
    GISAnalysisExecutionNotFoundError,
    GISAnalysisExecutionObservation,
    GISAnalysisOutcome,
)
from data_agent.gis_analysis_result_access import (
    GIS_ANALYSIS_RESULT_ACCESS_ACTION,
    GISAnalysisResultAccessForbidden,
    GISAnalysisResultAccessGrant,
    GISAnalysisResultAccessNotFound,
    GISAnalysisResultAccessService,
    GISAnalysisResultAccessUnavailable,
    GISAnalysisResultIntegrityError,
    GISAnalysisResultNotReady,
    build_s3_gis_analysis_result_access_backend,
)
from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.platform_contracts import Artifact, RunStatus, SubjectType
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError
from data_agent.test_gis_analysis_command_consumer import NOW, RUN_ID, TENANT, _record

RESULT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000201")
ACCESS_ID = UUID("00000000-0000-4000-8000-000000000202")
RESULT_SHA256 = "f" * 64
DOWNLOAD_URL = (
    "https://download.example.test/gis-result.geojson"
    "?X-Amz-Signature=temporary"
)


def _successful_record():
    base = _record()
    observation = GISAnalysisExecutionObservation(
        tenant_id=TENANT,
        analysis_observation_id=UUID("00000000-0000-4000-8000-000000000203"),
        run_id=RUN_ID,
        attempt_no=1,
        start_observation_id=UUID("00000000-0000-4000-8000-000000000204"),
        terminal_observation_id=UUID("00000000-0000-4000-8000-000000000205"),
        result_artifact_id=RESULT_ARTIFACT_ID,
        outcome=GISAnalysisOutcome.SUCCEEDED,
        features_returned=1,
        bytes_scanned=200,
        duration_ms=5,
        result_sha256=RESULT_SHA256,
        observed_at=NOW,
        recorded_by="workload:gis-analysis-postgis",
    )
    return base.model_copy(
        update={
            "run": base.run.model_copy(
                update={"status": RunStatus.SUCCEEDED, "state_version": 3}
            ),
            "observation": observation,
        }
    )


def _result_artifact(**updates) -> Artifact:
    record = _successful_record()
    values = {
        "tenant_id": TENANT,
        "artifact_id": RESULT_ARTIFACT_ID,
        "artifact_key": "gis-analysis-result",
        "artifact_role": "output",
        "storage_uri": (
            f"s3://gis-analysis-results/gis-analysis-results/v1/"
            f"{TENANT}/{RUN_ID}.json"
        ),
        "media_type": "application/geo+json",
        "content_sha256": RESULT_SHA256,
        "size_bytes": 128,
        "run_id": RUN_ID,
        "manifest": {
            "schema": "gda.gis_analysis_result_artifact.v1",
            "plan_artifact_id": str(record.admission.plan_artifact_id),
            "cache_key": record.admission.cache_key,
            "operation": "buffer",
            "features_returned": 1,
            "bytes_scanned": 200,
            "duration_ms": 5,
            "storage_evidence": {
                "schema": "gda.s3_object_version.v1",
                "version_id": "immutable-version-1",
                "etag": "result-etag-1",
            },
        },
        "created_by": "workload:gis-analysis-postgis",
        "created_at": NOW,
    }
    values.update(updates)
    return Artifact(**values)


def _service(*, record=None, artifact=None, backend=None, ledger=None):
    authority = Mock()
    authority.get.return_value = record or _successful_record()
    gateway = Mock()
    gateway.get_artifact.return_value = artifact or _result_artifact()
    result_backend = backend or Mock()
    result_backend.verify_and_presign.return_value = DOWNLOAD_URL
    return (
        GISAnalysisResultAccessService(
            authority=authority,
            gateway=gateway,
            ledger=ledger or Mock(),
            backend=result_backend,
            now=lambda: NOW,
            access_id_factory=lambda: ACCESS_ID,
        ),
        authority,
        gateway,
        result_backend,
    )


def _security_authority(*, publish_policy: bool = True):
    authority = InMemoryGovernedQueryPolicyAuthority(TENANT, clock=lambda: NOW)
    authority.register_purpose(
        build_purpose_registration(
            tenant_id=TENANT,
            purpose_code="query_result_access",
            description="Read immutable GIS analysis results",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=1),
        )
    )
    if publish_policy:
        authority.register_policy(
            build_policy_version(
                tenant_id=TENANT,
                policy_ref="policy:gis-result-access",
                policy_version="v1",
                purpose_code="query_result_access",
                subject_types=(SubjectType.HUMAN,),
                required_roles=("analyst",),
                channels=("gis_result",),
                adapter_ids=("gda.gis-analysis.result-access.v1",),
                resource_prefixes=(f"gda://{TENANT}/",),
                valid_from=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(seconds=1),
                published_by="human:policy-admin",
            )
        )
    return authority


def test_owner_access_verifies_artifact_and_audits_without_signed_url() -> None:
    ledger = Mock()
    service, authority, gateway, backend = _service(ledger=ledger)

    grant = service.issue(
        tenant_id=TENANT,
        run_id=RUN_ID,
        actor_subject="human:analyst",
        role="analyst",
        expires_in_seconds=120,
    )

    assert grant.access_id == ACCESS_ID
    assert grant.artifact_id == RESULT_ARTIFACT_ID
    assert grant.expires_at == NOW + timedelta(seconds=120)
    authority.get.assert_called_once_with(TENANT, RUN_ID)
    gateway.get_artifact.assert_called_once_with(TENANT, RESULT_ARTIFACT_ID)
    backend.verify_and_presign.assert_called_once()
    audit = ledger.append.call_args.kwargs
    assert audit["action"] == GIS_ANALYSIS_RESULT_ACCESS_ACTION
    assert audit["phase"] == "outcome"
    assert audit["outcome"] == "success"
    rendered = json.dumps(audit, default=str)
    assert "download.example.test" not in rendered
    assert "X-Amz" not in rendered


def test_gis_result_access_requires_live_spr_allow_before_storage() -> None:
    ledger = Mock()
    service, _, gateway, backend = _service(ledger=ledger)

    grant = service.issue(
        tenant_id=TENANT,
        run_id=RUN_ID,
        actor_subject="human:analyst",
        role="analyst",
        expires_in_seconds=120,
        purpose_code="query_result_access",
        security_reader=_security_authority(),
    )

    assert grant.artifact_id == RESULT_ARTIFACT_ID
    assert gateway.get_artifact.call_count == 1
    assert backend.verify_and_presign.call_count == 1
    assert ledger.append.call_count == 2
    admission = ledger.append.call_args_list[0].kwargs
    outcome = ledger.append.call_args_list[1].kwargs
    assert admission["phase"] == "admitted"
    assert admission["details"]["policy_ref"] == "policy:gis-result-access"
    assert outcome["details"]["security_request_sha256"] == (
        admission["details"]["request_sha256"]
    )


def test_gis_result_access_spr_deny_precedes_artifact_and_storage() -> None:
    ledger = Mock()
    service, _, gateway, backend = _service(ledger=ledger)

    with pytest.raises(GISAnalysisResultAccessForbidden, match="current policy"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
            security_reader=_security_authority(publish_policy=False),
        )

    gateway.get_artifact.assert_not_called()
    backend.verify_and_presign.assert_not_called()
    assert ledger.append.call_args.kwargs["reason"] == "spr_policy_denied"


def test_cross_owner_is_denied_before_artifact_or_storage_access() -> None:
    ledger = Mock()
    service, _, gateway, backend = _service(ledger=ledger)

    with pytest.raises(GISAnalysisResultAccessForbidden, match="submitter"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:other",
            role="analyst",
        )

    gateway.get_artifact.assert_not_called()
    backend.verify_and_presign.assert_not_called()
    assert ledger.append.call_args.kwargs["reason"] == "run_owner_required"


def test_result_access_requires_success_and_exact_artifact_manifest() -> None:
    pending_service, _, pending_gateway, _ = _service(record=_record())
    with pytest.raises(GISAnalysisResultNotReady, match="no successful result"):
        pending_service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )
    pending_gateway.get_artifact.assert_not_called()

    artifact = _result_artifact(
        manifest={**_result_artifact().manifest, "cache_key": "0" * 64}
    )
    mismatch_service, _, _, backend = _service(artifact=artifact)
    with pytest.raises(GISAnalysisResultIntegrityError, match="inconsistent"):
        mismatch_service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )
    backend.verify_and_presign.assert_not_called()


def test_unknown_run_is_hidden_and_denial_is_audited() -> None:
    ledger = Mock()
    service, authority, _, _ = _service(ledger=ledger)
    authority.get.side_effect = GISAnalysisExecutionNotFoundError("private detail")

    with pytest.raises(GISAnalysisResultAccessNotFound, match="not found") as raised:
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )

    assert "private" not in str(raised.value)
    assert ledger.append.call_args.kwargs["reason"] == "run_not_found"


def test_success_fails_closed_when_audit_is_unavailable() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("offline")
    service, _, _, _ = _service(ledger=ledger)

    with pytest.raises(GISAnalysisResultAccessUnavailable, match="verification"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )


def test_backend_builder_separates_verification_and_signing_endpoints(
    monkeypatch,
) -> None:
    created = []

    def create_client(service: str, **kwargs):
        assert service == "s3"
        created.append(kwargs)
        return Mock()

    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_S3_BUCKET", "gis-agent-analysis-results"
    )
    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_S3_PREFIX", "gis-analysis-results/v1"
    )
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_ACCESS_ENDPOINT_URL",
        "https://objects.example.test",
    )
    monkeypatch.setenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_KEY_ID", "scoped-reader")
    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_ACCESS_SECRET_ACCESS_KEY", "private-secret"
    )
    monkeypatch.setattr("boto3.client", create_client)

    backend = build_s3_gis_analysis_result_access_backend()

    assert backend.client is not backend.signing_client
    assert [item["endpoint_url"] for item in created] == [
        "http://minio:9000",
        "https://objects.example.test",
    ]
    assert all(item["aws_access_key_id"] == "scoped-reader" for item in created)


def test_backend_builder_rejects_incomplete_credentials_without_disclosure(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_S3_BUCKET", "gis-agent-analysis-results"
    )
    monkeypatch.setenv(
        "GDA_GIS_ANALYSIS_RESULT_ACCESS_KEY_ID", "private-reader-id"
    )
    monkeypatch.delenv(
        "GDA_GIS_ANALYSIS_RESULT_ACCESS_SECRET_ACCESS_KEY", raising=False
    )

    with pytest.raises(GISAnalysisResultAccessUnavailable) as raised:
        build_s3_gis_analysis_result_access_backend()

    assert "private-reader-id" not in str(raised.value)


def _request(*, body: dict | None = None) -> Request:
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
            "method": "POST",
            "path": f"/api/platform/v1/gis-analysis-runs/{RUN_ID}/result-access",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path_params": {"run_id": str(RUN_ID)},
        },
        receive,
    )


def _user(identifier: str = "analyst", role: str = "analyst") -> dict:
    return {
        "identifier": identifier,
        "metadata": {
            "tenant_id": TENANT,
            "role": role,
            "subject_type": "human",
        },
    }


@pytest.mark.asyncio
async def test_result_access_route_returns_only_temporary_grant(monkeypatch) -> None:
    service = Mock()
    service.issue.return_value = GISAnalysisResultAccessGrant(
        tenant_id=TENANT,
        access_id=ACCESS_ID,
        run_id=RUN_ID,
        artifact_id=RESULT_ARTIFACT_ID,
        delivery="presigned_get",
        download_url=DOWNLOAD_URL,
        media_type="application/geo+json",
        size_bytes=128,
        content_sha256=RESULT_SHA256,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=120),
    )
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_result_access", lambda: service)

    response = await gis_analysis_routes.create_gis_analysis_result_access(
        _request(body={"expires_in_seconds": 120})
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    data = json.loads(response.body)["data"]
    assert data["delivery"] == "presigned_get"
    assert "storage_uri" not in data
    assert "credentials" not in data


@pytest.mark.asyncio
async def test_result_access_route_maps_not_ready_and_rejects_invalid_ttl(
    monkeypatch,
) -> None:
    service = Mock()
    monkeypatch.setattr(
        gis_analysis_routes, "_get_user_from_request", lambda _: _user()
    )
    monkeypatch.setattr(gis_analysis_routes, "_result_access", lambda: service)

    invalid = await gis_analysis_routes.create_gis_analysis_result_access(
        _request(body={"expires_in_seconds": 3600})
    )
    assert invalid.status_code == 422
    service.issue.assert_not_called()

    service.issue.side_effect = GISAnalysisResultNotReady("not ready")
    conflict = await gis_analysis_routes.create_gis_analysis_result_access(_request())
    assert conflict.status_code == 409
