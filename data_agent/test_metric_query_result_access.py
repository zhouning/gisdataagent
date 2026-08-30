"""Contracts for governed metric-query result retrieval."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID

import boto3
import pytest
from starlette.requests import Request

from data_agent.api import metric_query_routes
from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.governed_query_security import (
    configure_governed_query_security_port_resolver,
)
from data_agent.metric_query_execution import (
    MetricQueryCacheStatus,
    MetricQueryExecutionNotFoundError,
    MetricQueryExecutionObservation,
    MetricQueryOutcome,
)
from data_agent.metric_query_result_access import (
    METRIC_QUERY_RESULT_ACCESS_ACTION,
    MetricQueryResultAccessForbidden,
    MetricQueryResultAccessGrant,
    MetricQueryResultAccessNotFound,
    MetricQueryResultAccessService,
    MetricQueryResultAccessUnavailable,
    MetricQueryResultIntegrityError,
    MetricQueryResultNotReady,
    S3MetricQueryResultAccessBackend,
    build_s3_metric_query_result_access_backend,
)
from data_agent.platform_contracts import Artifact, RunStatus, SubjectType
from data_agent.security_event_ledger import SecurityEventLedgerUnavailableError
from data_agent.test_metric_query_execution import (
    RUN_ID,
    START_OBSERVATION_ID,
    _record,
)
from data_agent.test_metric_query_planning import NOW, TENANT

RESULT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000404")
ACCESS_ID = UUID("00000000-0000-4000-8000-000000000405")
RESULT_PAYLOAD = b'{"schema":"gda.metric_query_result.v1","rows":[]}\n'
RESULT_SHA256 = hashlib.sha256(RESULT_PAYLOAD).hexdigest()
RESULT_BUCKET = "gis-agent-metric-query-results"
RESULT_PREFIX = "metric-query-results/v1"
RESULT_KEY = f"{RESULT_PREFIX}/{TENANT}/{RUN_ID}.json"
RESULT_URI = f"s3://{RESULT_BUCKET}/{RESULT_KEY}"
RESULT_VERSION_ID = "immutable-version-1"
RESULT_ETAG = "result-etag-1"


class _S3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _MemoryS3:
    def __init__(self) -> None:
        self.payload = RESULT_PAYLOAD
        self.metadata_sha256 = RESULT_SHA256
        self.content_type = "application/vnd.gda.metric-query-result+json"
        self.fail_operation: str | None = None
        self.presign_calls: list[dict] = []
        self.head_versions: list[str | None] = []
        self.get_versions: list[str | None] = []
        self.current_version_id = RESULT_VERSION_ID
        self.current_payload = RESULT_PAYLOAD

    def head_object(self, *, Bucket, Key, VersionId=None):
        assert Bucket == RESULT_BUCKET
        assert Key == RESULT_KEY
        self.head_versions.append(VersionId)
        if self.fail_operation == "head":
            raise _S3Error("AccessDenied:private-endpoint")
        if VersionId is not None and VersionId != RESULT_VERSION_ID:
            raise _S3Error("NoSuchVersion")
        payload = self.payload if VersionId is not None else self.current_payload
        version_id = VersionId or self.current_version_id
        return {
            "VersionId": version_id,
            "ETag": f'"{RESULT_ETAG}"',
            "ContentLength": len(payload),
            "ContentType": self.content_type,
            "Metadata": {"sha256": self.metadata_sha256},
        }

    def get_object(self, *, Bucket, Key, VersionId=None):
        assert Bucket == RESULT_BUCKET
        assert Key == RESULT_KEY
        self.get_versions.append(VersionId)
        if self.fail_operation == "get":
            raise _S3Error("ServiceUnavailable:private-endpoint")
        if VersionId is not None and VersionId != RESULT_VERSION_ID:
            raise _S3Error("NoSuchVersion")
        payload = self.payload if VersionId is not None else self.current_payload
        return {
            "Body": io.BytesIO(payload),
            "VersionId": VersionId or self.current_version_id,
        }

    def generate_presigned_url(self, operation, **kwargs):
        if self.fail_operation == "sign":
            raise RuntimeError("private signing credential")
        self.presign_calls.append({"operation": operation, **kwargs})
        return (
            "https://download.example.test/metric-result.json"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=temporary"
        )


def _successful_record():
    base = _record()
    observation = MetricQueryExecutionObservation(
        tenant_id=TENANT,
        query_observation_id=UUID("00000000-0000-4000-8000-000000000406"),
        run_id=RUN_ID,
        attempt_no=1,
        start_observation_id=START_OBSERVATION_ID,
        terminal_observation_id=UUID("00000000-0000-4000-8000-000000000407"),
        result_artifact_id=RESULT_ARTIFACT_ID,
        outcome=MetricQueryOutcome.SUCCEEDED,
        cache_status=MetricQueryCacheStatus.MISS,
        rows_returned=0,
        rows_scanned=12,
        bytes_scanned=4096,
        duration_ms=25,
        result_sha256=RESULT_SHA256,
        observed_at=NOW,
        recorded_by="workload:metric-query-postgis-provider",
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
        "artifact_key": "metric-query-result",
        "artifact_role": "output",
        "storage_uri": RESULT_URI,
        "media_type": "application/vnd.gda.metric-query-result+json",
        "content_sha256": RESULT_SHA256,
        "size_bytes": len(RESULT_PAYLOAD),
        "run_id": RUN_ID,
        "manifest": {
            "schema": "gda.metric_query_result_artifact.v1",
            "plan_artifact_id": str(record.admission.plan_artifact_id),
            "cache_key": record.admission.cache_key,
            "rows_returned": 0,
            "rows_scanned": 12,
            "bytes_scanned": 4096,
            "duration_ms": 25,
            "storage_evidence": {
                "schema": "gda.s3_object_version.v1",
                "version_id": RESULT_VERSION_ID,
                "etag": RESULT_ETAG,
            },
        },
        "created_by": "workload:metric-query-postgis-provider",
        "created_at": NOW,
    }
    values.update(updates)
    return Artifact(**values)


def _backend(client: _MemoryS3 | None = None) -> S3MetricQueryResultAccessBackend:
    return S3MetricQueryResultAccessBackend(
        client or _MemoryS3(),
        bucket=RESULT_BUCKET,
        prefix=RESULT_PREFIX,
    )


def test_s3_access_verifies_metadata_and_exact_bytes_before_signing() -> None:
    client = _MemoryS3()

    url = _backend(client).verify_and_presign(
        _result_artifact(),
        tenant_id=TENANT,
        run_id=RUN_ID,
        expires_in_seconds=120,
    )

    assert url.startswith("https://download.example.test/")
    assert client.presign_calls == [
        {
            "operation": "get_object",
            "Params": {
                "Bucket": RESULT_BUCKET,
                "Key": RESULT_KEY,
                "VersionId": RESULT_VERSION_ID,
                "ResponseContentType": "application/vnd.gda.metric-query-result+json",
            },
            "ExpiresIn": 120,
            "HttpMethod": "GET",
        }
    ]
    assert client.head_versions == [RESULT_VERSION_ID]
    assert client.get_versions == [RESULT_VERSION_ID]


def test_s3_access_remains_bound_to_artifact_version_after_current_overwrite() -> None:
    client = _MemoryS3()
    client.current_version_id = "new-current-version"
    client.current_payload = b"overwritten-after-artifact-publication"

    _backend(client).verify_and_presign(
        _result_artifact(),
        tenant_id=TENANT,
        run_id=RUN_ID,
        expires_in_seconds=120,
    )

    assert client.head_versions == [RESULT_VERSION_ID]
    assert client.get_versions == [RESULT_VERSION_ID]
    assert client.presign_calls[0]["Params"]["VersionId"] == RESULT_VERSION_ID


@pytest.mark.parametrize(
    "storage_evidence",
    [
        None,
        {"schema": "gda.s3_object_version.v1", "etag": RESULT_ETAG},
        {
            "schema": "gda.s3_object_version.v1",
            "version_id": "null",
            "etag": RESULT_ETAG,
        },
        {
            "schema": "gda.s3_object_version.v1",
            "version_id": RESULT_VERSION_ID,
            "etag": "forged-etag",
        },
    ],
)
def test_s3_access_rejects_missing_or_forged_object_version_evidence(
    storage_evidence,
) -> None:
    artifact = _result_artifact(
        manifest={
            **_result_artifact().manifest,
            "storage_evidence": storage_evidence,
        }
    )

    with pytest.raises(MetricQueryResultIntegrityError):
        _backend().verify_and_presign(
            artifact,
            tenant_id=TENANT,
            run_id=RUN_ID,
            expires_in_seconds=120,
        )


@pytest.mark.parametrize("mutation", ["metadata", "bytes", "size", "content_type"])
def test_s3_access_rejects_tampered_object_before_signing(mutation: str) -> None:
    client = _MemoryS3()
    if mutation == "metadata":
        client.metadata_sha256 = "0" * 64
    elif mutation == "bytes":
        client.payload = b"tampered" + RESULT_PAYLOAD[8:]
    elif mutation == "size":
        client.payload += b"x"
        client.metadata_sha256 = RESULT_SHA256
    else:
        client.content_type = "application/octet-stream"

    with pytest.raises(MetricQueryResultIntegrityError, match="does not match"):
        _backend(client).verify_and_presign(
            _result_artifact(),
            tenant_id=TENANT,
            run_id=RUN_ID,
            expires_in_seconds=120,
        )

    assert client.presign_calls == []


def test_s3_access_rejects_artifact_outside_managed_bucket_and_prefix() -> None:
    with pytest.raises(MetricQueryResultIntegrityError, match="managed result location"):
        _backend().verify_and_presign(
            _result_artifact(storage_uri="s3://other-bucket/private/result.json"),
            tenant_id=TENANT,
            run_id=RUN_ID,
            expires_in_seconds=120,
        )


@pytest.mark.parametrize("operation", ["head", "get", "sign"])
def test_s3_access_redacts_provider_failures(operation: str) -> None:
    client = _MemoryS3()
    client.fail_operation = operation

    with pytest.raises(MetricQueryResultAccessUnavailable) as raised:
        _backend(client).verify_and_presign(
            _result_artifact(),
            tenant_id=TENANT,
            run_id=RUN_ID,
            expires_in_seconds=120,
        )

    assert "private" not in str(raised.value)
    assert "credential" not in str(raised.value)
    assert "endpoint" not in str(raised.value)


def test_access_backend_builder_separates_verification_and_public_signing_endpoints(
    monkeypatch,
) -> None:
    created: list[dict] = []

    def create_client(service: str, **kwargs):
        assert service == "s3"
        created.append(kwargs)
        return Mock()

    monkeypatch.setenv("GDA_METRIC_QUERY_RESULT_S3_BUCKET", RESULT_BUCKET)
    monkeypatch.setenv("GDA_METRIC_QUERY_RESULT_S3_PREFIX", RESULT_PREFIX)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv(
        "GDA_METRIC_QUERY_RESULT_ACCESS_ENDPOINT_URL", "https://objects.example.test"
    )
    monkeypatch.setenv("GDA_METRIC_QUERY_RESULT_ACCESS_KEY_ID", "scoped-reader")
    monkeypatch.setenv(
        "GDA_METRIC_QUERY_RESULT_ACCESS_SECRET_ACCESS_KEY", "private-test-secret"
    )
    monkeypatch.setattr(boto3, "client", create_client)

    backend = build_s3_metric_query_result_access_backend()

    assert backend.client is not backend.signing_client
    assert [item["endpoint_url"] for item in created] == [
        "http://minio:9000",
        "https://objects.example.test",
    ]
    assert all(item["aws_access_key_id"] == "scoped-reader" for item in created)


def test_access_backend_builder_rejects_incomplete_credentials_without_disclosure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GDA_METRIC_QUERY_RESULT_S3_BUCKET", RESULT_BUCKET)
    monkeypatch.setenv("GDA_METRIC_QUERY_RESULT_ACCESS_KEY_ID", "private-reader-id")
    monkeypatch.delenv(
        "GDA_METRIC_QUERY_RESULT_ACCESS_SECRET_ACCESS_KEY", raising=False
    )

    with pytest.raises(MetricQueryResultAccessUnavailable) as raised:
        build_s3_metric_query_result_access_backend()

    assert "private-reader-id" not in str(raised.value)


def _service(*, actor_record=None, artifact=None, backend=None, ledger=None):
    authority = Mock()
    authority.get.return_value = actor_record or _successful_record()
    gateway = Mock()
    gateway.get_artifact.return_value = artifact or _result_artifact()
    return (
        MetricQueryResultAccessService(
            authority=authority,
            gateway=gateway,
            ledger=ledger or Mock(),
            backend=backend or _backend(),
            now=lambda: NOW,
            access_id_factory=lambda: ACCESS_ID,
        ),
        authority,
        gateway,
    )


def _security_authority(*, publish_policy: bool = True):
    authority = InMemoryGovernedQueryPolicyAuthority(TENANT, clock=lambda: NOW)
    authority.register_purpose(
        build_purpose_registration(
            tenant_id=TENANT,
            purpose_code="query_result_access",
            description="Read immutable metric query results",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=1),
        )
    )
    if publish_policy:
        authority.register_policy(
            build_policy_version(
                tenant_id=TENANT,
                policy_ref="policy:metric-result-access",
                policy_version="v1",
                purpose_code="query_result_access",
                subject_types=(SubjectType.HUMAN,),
                required_roles=("analyst",),
                channels=("metric_result",),
                adapter_ids=("gda.metric-query.result-access.v1",),
                resource_prefixes=(f"gda://{TENANT}/",),
                valid_from=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(seconds=1),
                published_by="human:policy-admin",
            )
        )
    return authority


def test_service_authorizes_owner_verifies_artifact_and_audits_without_url() -> None:
    ledger = Mock()
    service, authority, gateway = _service(ledger=ledger)

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
    assert (grant.expires_at - grant.issued_at).total_seconds() == 120
    authority.get.assert_called_once_with(TENANT, RUN_ID)
    gateway.get_artifact.assert_called_once_with(TENANT, RESULT_ARTIFACT_ID)
    audit = ledger.append.call_args.kwargs
    assert audit["action"] == METRIC_QUERY_RESULT_ACCESS_ACTION
    assert audit["phase"] == "outcome"
    assert audit["outcome"] == "success"
    rendered_audit = json.dumps(audit, default=str)
    assert "download.example.test" not in rendered_audit
    assert "s3://" not in rendered_audit
    assert "X-Amz" not in rendered_audit


def test_service_requires_live_spr_allow_before_artifact_and_storage_access() -> None:
    ledger = Mock()
    backend = Mock()
    backend.verify_and_presign.return_value = (
        "https://download.example.test/result.json?X-Amz-Signature=temporary"
    )
    service, _, gateway = _service(ledger=ledger, backend=backend)

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
    assert admission["details"]["purpose_code"] == "query_result_access"
    assert admission["details"]["policy_version"] == "v1"
    assert outcome["phase"] == "outcome"
    assert outcome["details"]["security_decision_sha256"] == (
        admission["details"]["decision_sha256"]
    )
    rendered = json.dumps([admission, outcome], default=str)
    assert "X-Amz" not in rendered
    assert "s3://" not in rendered


def test_service_spr_deny_never_reads_artifact_or_result_storage() -> None:
    ledger = Mock()
    backend = Mock()
    service, _, gateway = _service(ledger=ledger, backend=backend)

    with pytest.raises(MetricQueryResultAccessForbidden, match="current policy"):
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


def test_cached_result_cannot_bypass_current_spr_policy() -> None:
    record = _successful_record()
    cached = record.model_copy(
        update={
            "observation": record.observation.model_copy(
                update={"cache_status": MetricQueryCacheStatus.HIT}
            )
        }
    )
    backend = Mock()
    service, _, gateway = _service(actor_record=cached, backend=backend)

    with pytest.raises(MetricQueryResultAccessForbidden, match="current policy"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
            security_reader=_security_authority(publish_policy=False),
        )

    gateway.get_artifact.assert_not_called()
    backend.verify_and_presign.assert_not_called()


def test_service_security_reader_failure_precedes_artifact_and_storage() -> None:
    class BrokenReader:
        tenant_id = TENANT

        def governed_query_security_decision_current(self, request):
            raise RuntimeError("policy reader offline")

    backend = Mock()
    service, _, gateway = _service(backend=backend)

    with pytest.raises(MetricQueryResultAccessUnavailable, match="security"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
            security_reader=BrokenReader(),
        )

    gateway.get_artifact.assert_not_called()
    backend.verify_and_presign.assert_not_called()


def test_service_security_admission_audit_failure_precedes_storage() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("offline")
    backend = Mock()
    service, _, gateway = _service(ledger=ledger, backend=backend)

    with pytest.raises(
        MetricQueryResultAccessUnavailable,
        match="security admission audit",
    ):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
            security_reader=_security_authority(),
        )

    gateway.get_artifact.assert_not_called()
    backend.verify_and_presign.assert_not_called()


def test_service_allows_platform_operator_but_denies_other_subject() -> None:
    operator_service, _, _ = _service()
    assert operator_service.issue(
        tenant_id=TENANT,
        run_id=RUN_ID,
        actor_subject="human:operator",
        role="platform_operator",
    ).artifact_id == RESULT_ARTIFACT_ID

    ledger = Mock()
    denied_service, _, gateway = _service(ledger=ledger)
    with pytest.raises(MetricQueryResultAccessForbidden, match="submitter"):
        denied_service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:other",
            role="analyst",
        )
    gateway.get_artifact.assert_not_called()
    assert ledger.append.call_args.kwargs["phase"] == "denied"
    assert ledger.append.call_args.kwargs["reason"] == "run_owner_required"


def test_service_requires_succeeded_run_and_exact_artifact_evidence() -> None:
    pending_service, _, pending_gateway = _service(actor_record=_record())
    with pytest.raises(MetricQueryResultNotReady, match="no successful result"):
        pending_service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )
    pending_gateway.get_artifact.assert_not_called()

    mismatch_service, _, _ = _service(
        artifact=_result_artifact(
            manifest={
                **_result_artifact().manifest,
                "cache_key": "0" * 64,
            }
        )
    )
    with pytest.raises(MetricQueryResultIntegrityError, match="inconsistent"):
        mismatch_service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )


def test_service_fails_closed_when_access_audit_is_unavailable() -> None:
    ledger = Mock()
    ledger.append.side_effect = SecurityEventLedgerUnavailableError("offline")
    service, _, _ = _service(ledger=ledger)

    with pytest.raises(MetricQueryResultAccessUnavailable, match="audit"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )


def test_service_hides_cross_tenant_or_unknown_run_and_audits_denial() -> None:
    authority = Mock()
    authority.get.side_effect = MetricQueryExecutionNotFoundError("not found")
    ledger = Mock()
    service = MetricQueryResultAccessService(
        authority=authority,
        gateway=Mock(),
        ledger=ledger,
        backend=_backend(),
        access_id_factory=lambda: ACCESS_ID,
    )

    with pytest.raises(MetricQueryResultAccessNotFound, match="not found"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )

    authority.get.assert_called_once_with(TENANT, RUN_ID)
    assert ledger.append.call_args.kwargs["phase"] == "denied"
    assert ledger.append.call_args.kwargs["reason"] == "run_not_found"


def test_service_does_not_audit_success_for_invalid_signed_url() -> None:
    backend = Mock()
    backend.verify_and_presign.return_value = "not-a-signed-url"
    ledger = Mock()
    service, _, _ = _service(backend=backend, ledger=ledger)

    with pytest.raises(MetricQueryResultAccessUnavailable, match="invalid grant"):
        service.issue(
            tenant_id=TENANT,
            run_id=RUN_ID,
            actor_subject="human:analyst",
            role="analyst",
        )

    ledger.append.assert_not_called()


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
            "path": f"/api/platform/v1/metric-query-runs/{RUN_ID}/result-access",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path_params": {"run_id": str(RUN_ID)},
        },
        receive,
    )


def _user() -> dict:
    return {
        "identifier": "analyst",
        "metadata": {
            "tenant_id": TENANT,
            "role": "analyst",
            "subject_type": "human",
        },
    }


@pytest.mark.asyncio
async def test_result_access_route_returns_only_governed_temporary_grant(
    monkeypatch,
) -> None:
    service = Mock()
    service.issue.return_value = MetricQueryResultAccessGrant(
        tenant_id=TENANT,
        access_id=ACCESS_ID,
        run_id=RUN_ID,
        artifact_id=RESULT_ARTIFACT_ID,
        delivery="presigned_get",
        download_url=(
            "https://download.example.test/result.json"
            "?X-Amz-Signature=temporary"
        ),
        media_type="application/vnd.gda.metric-query-result+json",
        size_bytes=len(RESULT_PAYLOAD),
        content_sha256=RESULT_SHA256,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=120),
    )
    monkeypatch.setattr(metric_query_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        metric_query_routes, "_query_result_access_service", lambda: service
    )

    response = await metric_query_routes.create_metric_query_result_access(
        _request(body={"expires_in_seconds": 120})
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    service.issue.assert_called_once_with(
        tenant_id=TENANT,
        run_id=RUN_ID,
        actor_subject="human:analyst",
        role="analyst",
        expires_in_seconds=120,
        purpose_code="query_result_access",
        security_reader=None,
    )
    data = json.loads(response.body)["data"]
    assert data["delivery"] == "presigned_get"
    assert "storage_uri" not in data
    assert "credentials" not in data


@pytest.mark.asyncio
async def test_result_access_route_fails_closed_when_security_is_required(
    monkeypatch,
) -> None:
    service = Mock()
    monkeypatch.setattr(metric_query_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        metric_query_routes, "_query_result_access_service", lambda: service
    )
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    configure_governed_query_security_port_resolver(None)

    response = await metric_query_routes.create_metric_query_result_access(_request())

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == (
        "metric_query_result_security_unavailable"
    )
    service.issue.assert_not_called()


@pytest.mark.asyncio
async def test_result_access_route_rejects_invalid_ttl_and_maps_integrity_error(
    monkeypatch,
) -> None:
    service = Mock()
    monkeypatch.setattr(metric_query_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(
        metric_query_routes, "_query_result_access_service", lambda: service
    )

    invalid = await metric_query_routes.create_metric_query_result_access(
        _request(body={"expires_in_seconds": 3600})
    )
    assert invalid.status_code == 422
    service.issue.assert_not_called()

    service.issue.side_effect = MetricQueryResultIntegrityError("tampered")
    conflict = await metric_query_routes.create_metric_query_result_access(_request())
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == (
        "metric_query_result_integrity_error"
    )


def test_metric_query_routes_expose_result_access_operation() -> None:
    operations = {route.operation_id for route in metric_query_routes.get_metric_query_routes()}
    assert "platform_create_metric_query_result_access" in operations
