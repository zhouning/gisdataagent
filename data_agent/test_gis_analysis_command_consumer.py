"""Focused tests for the governed PostGIS GIS provider and consumer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from data_agent.gis_analysis_command_consumer import (
    GISAnalysisCommandConsumer,
    GISAnalysisProviderCancelled,
    GISAnalysisProviderContractError,
    GISAnalysisProviderResult,
    GISAnalysisProviderTransientError,
    PostGISAnalysisProvider,
    gis_analysis_command_identity,
)
from data_agent.gis_analysis_execution import (
    GISAnalysisBackendBinding,
    GISAnalysisBudget,
    GISAnalysisCancelAdmission,
    GISAnalysisCancelOutcome,
    GISAnalysisCancelReceipt,
    GISAnalysisExecutionAdmission,
    GISAnalysisOperation,
    GISAnalysisOutcome,
    GISAnalysisPlan,
    GISAnalysisRunRecord,
)
from data_agent.platform_contracts import (
    Artifact,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformRun,
    RunStatus,
    SubjectContext,
)

TENANT = "tenant-a"
NOW = datetime(2026, 8, 13, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000000101")
PLAN_ID = UUID("00000000-0000-4000-8000-000000000102")
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000103")
BACKEND = GISAnalysisBackendBinding.create(
    backend_pid=4242,
    backend_start=NOW,
    database_oid=100,
    user_oid=200,
    application_name=f"gda-gis-analysis/{RUN_ID}",
)


def _plan(operation: GISAnalysisOperation = GISAnalysisOperation.BUFFER) -> GISAnalysisPlan:
    sources = [
        {
            "role": "input",
            "semantic_source_name": "parcels",
            "binding_id": "00000000-0000-4000-8000-000000000111",
            "resource_version_id": "00000000-0000-4000-8000-000000000112",
            "resource_urn": "gda://tenant-a/source_snapshot/parcels",
            "version_key": "v1",
            "content_sha256": "a" * 64,
            "authority_version_sha256": "b" * 64,
            "physical_binding_sha256": "c" * 64,
            "physical_relation": "public.parcels",
            "geometry_column": "geom",
            "source_srid": 4490,
        }
    ]
    distance = 100.0
    if operation is not GISAnalysisOperation.BUFFER:
        sources.append({**sources[0], "role": "overlay", "semantic_source_name": "zones"})
        distance = None
    return GISAnalysisPlan.create(
        tenant_id=TENANT,
        operation=operation,
        sources=tuple(sources),
        distance_meters=distance,
        output_srid=4490,
        budget=GISAnalysisBudget(
            max_features=100,
            max_output_bytes=100_000,
            max_duration_ms=30_000,
        ),
        security_context_fingerprint="d" * 64,
    )


def test_postgis_provider_compiles_all_supported_operations_without_literals() -> None:
    engine = create_engine("postgresql+psycopg2://")
    provider = PostGISAnalysisProvider(engine, result_root=Path("/tmp/gda-gis-test"))
    for operation in GISAnalysisOperation:
        query, evidence, parameters = provider._queries(_plan(operation))
        assert "ST_AsGeoJSON" in query
        assert "ST_Intersects" in query or operation is GISAnalysisOperation.BUFFER
        assert ";" not in query
        if operation is GISAnalysisOperation.BUFFER:
            assert parameters == {"distance_meters": 100.0}
        else:
            assert parameters == {}
        assert "pg_column_size" in evidence


def test_postgis_provider_rejects_unsafe_identifier(tmp_path: Path) -> None:
    engine = create_engine("postgresql+psycopg2://")
    provider = PostGISAnalysisProvider(engine, result_root=tmp_path)
    unsafe = _plan().model_copy(update={
        "sources": (
            _plan().sources[0].model_copy(update={"geometry_column": "geom;DROP"}),
        )
    })
    with pytest.raises(
        GISAnalysisProviderContractError,
        match="unsafe PostGIS identifier",
    ):
        provider._queries(unsafe)


def test_command_identity_is_stable_and_provider_result_shape_is_explicit() -> None:
    first = gis_analysis_command_identity(TENANT, RUN_ID, PLAN_ID, "a" * 64)
    second = gis_analysis_command_identity(TENANT, RUN_ID, PLAN_ID, "a" * 64)
    assert first == second
    assert first[0].startswith("gis_analysis.execute:tenant-a:")
    result = GISAnalysisProviderResult(
        storage_uri="file:///tmp/gis-result.geojson",
        media_type="application/geo+json",
        sha256="f" * 64,
        size_bytes=42,
        manifest={"schema": "gda.gis_analysis_result.v1"},
        features_returned=1,
        bytes_scanned=100,
        duration_ms=5,
    )
    assert result.media_type == "application/geo+json"


def _record() -> GISAnalysisRunRecord:
    plan = _plan()
    admission = GISAnalysisExecutionAdmission(
        tenant_id=TENANT,
        run_id=RUN_ID,
        client_request_id="gis-analysis-101",
        definition_version_id=DEFINITION_ID,
        plan_artifact_id=PLAN_ID,
        plan=plan,
        plan_fingerprint="e" * 64,
        cache_key=plan.cache_key,
        admitted_by="human:analyst",
        admitted_at=NOW,
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id="analyst",
            subject_type="human",
            roles=("analyst",),
            purpose="gis analysis",
        ),
        idempotency_key="gis-analysis:v1:gis-analysis-101",
        config_fingerprint=plan.cache_key,
        submitted_at=NOW,
    )
    artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="gis-analysis-plan",
        artifact_role="execution_plan",
        storage_uri=f"postgresql://gda-control/gis-analysis-plan/{RUN_ID}",
        media_type="application/vnd.gda.gis-analysis-plan+json",
        content_sha256="e" * 64,
        size_bytes=100,
        run_id=RUN_ID,
        created_by="human:analyst",
        created_at=NOW,
    )
    return GISAnalysisRunRecord(admission=admission, run=run, plan_artifact=artifact)


def _command() -> PlatformCommand:
    record = _record()
    admission = record.admission
    dedupe_key, command_id = gis_analysis_command_identity(
        TENANT, RUN_ID, PLAN_ID, admission.plan_fingerprint
    )
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=command_id,
        run_id=RUN_ID,
        command_type="gis_analysis.execute",
        execution_plan_artifact_id=PLAN_ID,
        dedupe_key=dedupe_key,
        actor_subject="workload:gis-analysis-postgis",
        payload={
            "schema": "gda.gis_analysis_execute_command.v1",
            "run_id": str(RUN_ID),
            "plan_artifact_id": str(PLAN_ID),
            "plan_fingerprint": admission.plan_fingerprint,
            "cache_key": admission.cache_key,
            "engine": "postgis",
            "execution_mode": "asynchronous",
            "operation": "buffer",
            "algorithm_id": "postgis.st_buffer_geography",
            "algorithm_version": "gda.postgis-spatial-analysis.v1",
            "algorithm_spec_fingerprint": record.admission.plan.algorithm_spec_fingerprint,
        },
        status="in_flight",
        attempt_count=1,
        max_attempts=3,
        available_at=NOW,
        claimed_by="worker:gis-analysis-1",
        claimed_until=NOW + timedelta(minutes=1),
        created_at=NOW,
    )


class _GISGateway:
    def __init__(self, command: PlatformCommand):
        self.command = command
        self.completed = []

    def claim_commands(self, tenant_id, worker_id, *, actor_subject, limit, lease_seconds):
        return [self.command]

    def complete_command(self, tenant_id, command_id, *, worker_id):
        self.completed.append(command_id)
        return self.command

    def fail_command(self, tenant_id, command_id, *, worker_id, error, retry_delay_seconds):
        return self.command.model_copy(update={"status": PlatformCommandStatus.PENDING})


class _GISAuthority:
    def __init__(self):
        self.record = _record()
        self.starts = []
        self.completions = []
        self.cancelled = []

    def get(self, tenant_id, run_id):
        return self.record

    def start(self, tenant_id, run_id, spec, *, actor_subject, expected_state_version):
        self.starts.append(spec)
        self.record = self.record.model_copy(update={
            "run": self.record.run.model_copy(update={"status": "running", "state_version": 2})
        })
        return self.record

    def complete(self, tenant_id, run_id, spec, *, actor_subject, expected_state_version):
        self.completions.append(spec)
        return self.record

    def complete_cancelled(self, tenant_id, run_id, **values):
        self.cancelled.append(values)
        return self.record


class _GISProvider:
    engine_name = "postgis"
    workload_subject = "workload:gis-analysis-postgis"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def execute(self, plan, *, run_id, plan_fingerprint, on_backend_ready):
        self.calls.append((plan, run_id, plan_fingerprint))
        on_backend_ready(BACKEND)
        if self.error:
            raise self.error
        return GISAnalysisProviderResult(
            storage_uri="file:///tmp/gis-result.geojson",
            media_type="application/geo+json",
            sha256="f" * 64,
            size_bytes=100,
            manifest={
                "result_schema": "gda.gis_analysis_result.v1",
                "format": "canonical-geojson",
                "output_crs": "EPSG:4490",
                "operation": "buffer",
            },
            features_returned=1,
            bytes_scanned=200,
            duration_ms=5,
        )


def test_consumer_writes_start_and_success_receipts() -> None:
    command = _command()
    gateway = _GISGateway(command)
    authority = _GISAuthority()
    result = GISAnalysisCommandConsumer(
        _GISProvider(), gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id="worker:gis-analysis-1")
    assert result.analysis_succeeded == 1
    assert len(authority.starts) == 1
    assert authority.starts[0].observed_at >= command.created_at
    assert authority.completions[0].outcome is GISAnalysisOutcome.SUCCEEDED
    assert gateway.completed == [command.command_id]


def test_consumer_records_failure_without_result_artifact() -> None:
    command = _command()
    gateway = _GISGateway(command)
    authority = _GISAuthority()
    result = GISAnalysisCommandConsumer(
        _GISProvider(GISAnalysisProviderTransientError("temporary")),
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-1")
    assert result.retry_pending == 1
    assert authority.completions == []


def _record_with_signalled_cancel():
    record = _record()
    start_observation_id = UUID("00000000-0000-4000-8000-000000000104")
    cancel_command_id = UUID("00000000-0000-4000-8000-000000000105")
    admission = GISAnalysisCancelAdmission(
        tenant_id=TENANT,
        run_id=RUN_ID,
        cancel_request_id="gis-cancel-101",
        cancel_command_id=cancel_command_id,
        start_observation_id=start_observation_id,
        requested_by="human:analyst",
        reason="source snapshot was superseded",
        backend=BACKEND,
        requested_at=NOW + timedelta(seconds=1),
    )
    receipt = GISAnalysisCancelReceipt(
        tenant_id=TENANT,
        run_id=RUN_ID,
        cancel_command_id=cancel_command_id,
        cancel_observation_id=UUID("00000000-0000-4000-8000-000000000106"),
        outcome=GISAnalysisCancelOutcome.SIGNALLED,
        backend=BACKEND,
        observed_at=NOW + timedelta(seconds=2),
        recorded_by="workload:gis-analysis-postgis-canceller",
    )
    return record.model_copy(
        update={
            "run": record.run.model_copy(
                update={"status": RunStatus.CANCELLING, "state_version": 3}
            ),
            "cancel_admission": admission,
            "cancel_receipt": receipt,
        }
    )


def test_consumer_waits_for_signal_receipt_before_cancelled_terminal() -> None:
    command = _command()
    gateway = _GISGateway(command)
    authority = _GISAuthority()
    signalled = _record_with_signalled_cancel()
    original_start = authority.start

    def start(*args, **kwargs):
        result = original_start(*args, **kwargs)
        authority.record = signalled
        return result

    authority.start = start

    result = GISAnalysisCommandConsumer(
        _GISProvider(GISAnalysisProviderCancelled(BACKEND)),
        gateway=gateway,
        authority=authority,
        cancel_receipt_wait_seconds=0.1,
    ).run_once(TENANT, worker_id="worker:gis-analysis-1")

    assert result.completed == 1
    assert authority.cancelled
    assert gateway.completed == [command.command_id]


def test_consumer_retries_when_cancel_signal_receipt_is_not_visible() -> None:
    command = _command()
    gateway = _GISGateway(command)
    authority = _GISAuthority()

    result = GISAnalysisCommandConsumer(
        _GISProvider(GISAnalysisProviderCancelled(BACKEND)),
        gateway=gateway,
        authority=authority,
        cancel_receipt_wait_seconds=0.1,
    ).run_once(TENANT, worker_id="worker:gis-analysis-1")

    assert result.retry_pending == 1
    assert result.completed == 0
    assert authority.cancelled == []
    assert gateway.completed == []
