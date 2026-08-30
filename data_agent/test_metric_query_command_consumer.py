"""Focused contracts for metric-query command delivery and PostGIS compilation."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from data_agent.metric_query_command_consumer import (
    POSTGIS_WORKLOAD,
    MetricQueryCommandConsumer,
    MetricQueryProviderContractError,
    MetricQueryProviderResult,
    MetricQueryProviderTransientError,
    PostGISMetricQueryProvider,
    _grouped_observation_projection,
    _scalar_observation_projection,
    metric_query_command_identity,
)
from data_agent.metric_query_execution import MetricQueryExecutionObservation
from data_agent.metric_query_result_store import (
    MetricQueryResultPublication,
    MetricQueryResultStoreConflict,
    MetricQueryResultStoreUnavailable,
)
from data_agent.platform_contracts import Artifact, PlatformCommand, PlatformCommandStatus
from data_agent.test_metric_query_execution import _record
from data_agent.test_metric_query_planning import NOW, TENANT

WORKER = "worker:metric-query-1"


def _command(
    *, attempt_count: int = 1, max_attempts: int = 3, record=None
) -> PlatformCommand:
    record = record or _record()
    admission = record.admission
    dedupe_key, command_id = metric_query_command_identity(
        TENANT,
        admission.run_id,
        admission.plan_artifact_id,
        admission.plan_fingerprint,
    )
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=command_id,
        run_id=admission.run_id,
        command_type="metric_query.execute",
        execution_plan_artifact_id=admission.plan_artifact_id,
        dedupe_key=dedupe_key,
        actor_subject=POSTGIS_WORKLOAD,
        payload={
            "schema": "gda.metric_query_execute_command.v1",
            "run_id": str(admission.run_id),
            "plan_artifact_id": str(admission.plan_artifact_id),
            "plan_fingerprint": admission.plan_fingerprint,
            "cache_key": admission.cache_key,
            "engine": admission.engine,
            "execution_mode": admission.execution_mode,
        },
        status="in_flight",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=NOW,
        claimed_by=WORKER,
        claimed_until=NOW + timedelta(minutes=1),
        created_at=admission.admitted_at,
    )


class _Gateway:
    def __init__(self, command: PlatformCommand, *, artifact: Artifact | None = None):
        self.command = command
        self.artifact = artifact
        self.completed = []
        self.failed = []

    def claim_commands(
        self, tenant_id, worker_id, *, actor_subject, limit, lease_seconds
    ):
        assert (tenant_id, worker_id, actor_subject) == (
            TENANT,
            WORKER,
            POSTGIS_WORKLOAD,
        )
        assert (limit, lease_seconds) == (10, 60)
        return [self.command]

    def complete_command(self, tenant_id, command_id, *, worker_id):
        self.completed.append((tenant_id, command_id, worker_id))
        return self.command.model_copy(
            update={
                "status": PlatformCommandStatus.DONE,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )

    def get_artifact(self, tenant_id, artifact_id):
        assert self.artifact is not None
        assert (tenant_id, artifact_id) == (
            self.artifact.tenant_id,
            self.artifact.artifact_id,
        )
        return self.artifact

    def fail_command(
        self,
        tenant_id,
        command_id,
        *,
        worker_id,
        error,
        retry_delay_seconds,
    ):
        self.failed.append(
            (tenant_id, command_id, worker_id, error, retry_delay_seconds)
        )
        terminal = self.command.attempt_count >= self.command.max_attempts
        return self.command.model_copy(
            update={
                "status": (
                    PlatformCommandStatus.FAILED
                    if terminal
                    else PlatformCommandStatus.PENDING
                ),
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW if terminal else None,
            }
        )


class _Authority:
    def __init__(self, *, terminal: bool = False, record=None):
        self.record = record or _record()
        if terminal:
            self.record = self.record.model_copy(
                update={
                    "run": self.record.run.model_copy(
                        update={"status": "succeeded", "state_version": 3}
                    )
                }
            )
        self.starts = []
        self.completions = []

    def get(self, tenant_id, run_id):
        assert (tenant_id, run_id) == (TENANT, self.record.run.run_id)
        return self.record

    def start(self, tenant_id, run_id, spec, *, actor_subject, expected_state_version):
        self.starts.append((tenant_id, run_id, spec, actor_subject, expected_state_version))
        return self.record.model_copy(
            update={
                "run": self.record.run.model_copy(
                    update={"status": "running", "state_version": 2}
                )
            }
        )

    def complete(
        self, tenant_id, run_id, spec, *, actor_subject, expected_state_version
    ):
        self.completions.append(
            (tenant_id, run_id, spec, actor_subject, expected_state_version)
        )
        return self.record


class _CompletingAuthority(_Authority):
    def __init__(self, accepted_record, completed_record):
        super().__init__(record=accepted_record)
        self.completed_record = completed_record

    def complete(
        self, tenant_id, run_id, spec, *, actor_subject, expected_state_version
    ):
        self.completions.append(
            (tenant_id, run_id, spec, actor_subject, expected_state_version)
        )
        self.record = self.completed_record
        return self.completed_record


class _Provider:
    engine_name = "postgis"
    workload_subject = POSTGIS_WORKLOAD

    def __init__(self, error=None, result=None):
        self.error = error
        self.result = result
        self.calls = []

    def execute(self, plan, *, run_id, plan_fingerprint):
        self.calls.append((plan, run_id, plan_fingerprint))
        if self.error is not None:
            raise self.error
        return self.result or MetricQueryProviderResult(
            storage_uri="file:///tmp/metric-result.json",
            media_type="application/vnd.gda.metric-query-result+json",
            sha256="a" * 64,
            size_bytes=100,
            manifest={"format": "canonical-json"},
            rows_returned=2,
            rows_scanned=4,
            bytes_scanned=512,
            duration_ms=5,
        )


class _ObservationAuthority:
    def __init__(self):
        self.projects = []
        self.batch_projects = []

    def project(self, tenant_id, run_id, spec, *, actor_subject, role):
        self.projects.append((tenant_id, run_id, spec, actor_subject, role))

    def project_batch(self, tenant_id, run_id, batch, *, actor_subject, role):
        self.batch_projects.append(
            (tenant_id, run_id, batch, actor_subject, role)
        )


def _terminal_scalar_record_and_artifact():
    record = _record()
    run_id = record.run.run_id
    result_sha256 = "c" * 64
    result_artifact_id = uuid5(run_id, f"metric-query-result:{result_sha256}")
    projection = _scalar_observation_projection(
        record.admission.plan,
        [{"metric_value": "25.00"}],
        result_sha256,
    )
    assert projection is not None
    observation = MetricQueryExecutionObservation(
        tenant_id=TENANT,
        query_observation_id=UUID("00000000-0000-4000-8000-000000000601"),
        run_id=run_id,
        attempt_no=1,
        start_observation_id=UUID("00000000-0000-4000-8000-000000000602"),
        terminal_observation_id=UUID("00000000-0000-4000-8000-000000000603"),
        result_artifact_id=result_artifact_id,
        outcome="succeeded",
        cache_status="miss",
        rows_returned=1,
        rows_scanned=2,
        bytes_scanned=128,
        duration_ms=5,
        result_sha256=result_sha256,
        observed_at=NOW,
        recorded_by=POSTGIS_WORKLOAD,
    )
    terminal = record.model_copy(
        update={
            "run": record.run.model_copy(
                update={"status": "succeeded", "state_version": 3}
            ),
            "observation": observation,
        }
    )
    artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=result_artifact_id,
        artifact_key="metric-query-result",
        artifact_role="output",
        storage_uri="file:///tmp/metric-result.json",
        media_type="application/vnd.gda.metric-query-result+json",
        content_sha256=result_sha256,
        size_bytes=100,
        run_id=run_id,
        manifest={
            "schema": "gda.metric_query_result_artifact.v1",
            "result_schema": "gda.metric_query_result.v1",
            "columns": ["metric_value"],
            "rows_returned": 1,
            "metric_observation_projection": projection.model_dump(mode="json"),
        },
        created_by=POSTGIS_WORKLOAD,
        created_at=NOW,
    )
    return terminal, artifact


def _terminal_grouped_record_and_artifact():
    record = _record()
    intent = record.admission.plan.physical_intent.model_copy(
        update={
            "group_by_columns": ("district_code", "observation_date"),
            "group_by_dimensions": ("district", "observation_date"),
        }
    )
    plan = record.admission.plan.model_copy(update={"physical_intent": intent})
    admission = record.admission.model_copy(update={"plan": plan})
    record = record.model_copy(update={"admission": admission})
    run_id = record.run.run_id
    rows = [
        {
            "district_code": "d01",
            "observation_date": "2026-08-01",
            "metric_value": "25.00",
        },
        {
            "district_code": "d01",
            "observation_date": "2026-08-02",
            "metric_value": "30.00",
        },
    ]
    result_sha256 = "d" * 64
    batch = _grouped_observation_projection(plan, rows, result_sha256)
    assert batch is not None
    result_artifact_id = uuid5(run_id, f"metric-query-result:{result_sha256}")
    observation = MetricQueryExecutionObservation(
        tenant_id=TENANT,
        query_observation_id=UUID("00000000-0000-4000-8000-000000000611"),
        run_id=run_id,
        attempt_no=1,
        start_observation_id=UUID("00000000-0000-4000-8000-000000000612"),
        terminal_observation_id=UUID("00000000-0000-4000-8000-000000000613"),
        result_artifact_id=result_artifact_id,
        outcome="succeeded",
        cache_status="miss",
        rows_returned=2,
        rows_scanned=2,
        bytes_scanned=256,
        duration_ms=5,
        result_sha256=result_sha256,
        observed_at=NOW,
        recorded_by=POSTGIS_WORKLOAD,
    )
    terminal = record.model_copy(
        update={
            "run": record.run.model_copy(
                update={"status": "succeeded", "state_version": 3}
            ),
            "observation": observation,
        }
    )
    artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=result_artifact_id,
        artifact_key="metric-query-result",
        artifact_role="output",
        storage_uri="file:///tmp/grouped-metric-result.json",
        media_type="application/vnd.gda.metric-query-result+json",
        content_sha256=result_sha256,
        size_bytes=200,
        run_id=run_id,
        manifest={
            "schema": "gda.metric_query_result_artifact.v1",
            "result_schema": "gda.metric_query_result.v1",
            "columns": ["district_code", "observation_date", "metric_value"],
            "rows_returned": 2,
            "metric_observation_batch_projection": batch.model_dump(mode="json"),
        },
        created_by=POSTGIS_WORKLOAD,
        created_at=NOW,
    )
    return terminal, artifact


def test_metric_query_command_contract_requires_exact_plan_payload() -> None:
    command = _command()

    assert command.command_type.value == "metric_query.execute"
    with pytest.raises(ValidationError, match="exact executable plan"):
        PlatformCommand(
            **{
                **command.model_dump(),
                "payload": {**command.payload, "plan_fingerprint": "bad"},
            }
        )


def test_consumer_completes_a_successful_query_and_receipt() -> None:
    command = _command()
    gateway = _Gateway(command)
    authority = _Authority()
    provider = _Provider()

    result = MetricQueryCommandConsumer(
        provider, gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id=WORKER)

    assert result.query_succeeded == 1
    assert result.completed == 1
    assert len(authority.starts) == 1
    assert authority.completions[0][2].outcome.value == "succeeded"
    assert gateway.completed == [(TENANT, command.command_id, WORKER)]


def test_terminal_run_recovery_completes_command_without_reexecuting() -> None:
    command = _command(attempt_count=2)
    gateway = _Gateway(command)
    authority = _Authority(terminal=True)
    provider = _Provider()

    result = MetricQueryCommandConsumer(
        provider, gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id=WORKER)

    assert result.completed == 1
    assert provider.calls == []
    assert authority.starts == []


def test_terminal_scalar_run_reconciles_observation_without_reexecuting() -> None:
    record, artifact = _terminal_scalar_record_and_artifact()
    command = _command(attempt_count=2, record=record)
    gateway = _Gateway(command, artifact=artifact)
    authority = _Authority(record=record)
    observations = _ObservationAuthority()
    provider = _Provider()

    result = MetricQueryCommandConsumer(
        provider,
        gateway=gateway,
        authority=authority,
        observation_authority=observations,
    ).run_once(TENANT, worker_id=WORKER)

    assert result.completed == 1
    assert provider.calls == []
    assert len(observations.projects) == 1
    tenant_id, run_id, spec, actor_subject, role = observations.projects[0]
    assert (tenant_id, run_id) == (TENANT, record.run.run_id)
    assert spec.value.as_tuple() == (0, (2, 5, 0, 0), -2)
    assert actor_subject == POSTGIS_WORKLOAD
    assert role == "platform_operator"


def test_terminal_grouped_run_reconciles_batch_without_reexecuting() -> None:
    record, artifact = _terminal_grouped_record_and_artifact()
    command = _command(attempt_count=2, record=record)
    observations = _ObservationAuthority()
    provider = _Provider()

    result = MetricQueryCommandConsumer(
        provider,
        gateway=_Gateway(command, artifact=artifact),
        authority=_Authority(record=record),
        observation_authority=observations,
    ).run_once(TENANT, worker_id=WORKER)

    assert result.completed == 1
    assert provider.calls == []
    assert len(observations.batch_projects) == 1
    tenant_id, run_id, batch, actor_subject, role = observations.batch_projects[0]
    assert (tenant_id, run_id) == (TENANT, record.run.run_id)
    assert [item.projection.value for item in batch.projections] == [
        Decimal("25.00"),
        Decimal("30.00"),
    ]
    assert actor_subject == POSTGIS_WORKLOAD
    assert role == "platform_operator"


def test_successful_scalar_query_projects_observation_before_command_completion() -> None:
    completed_record, artifact = _terminal_scalar_record_and_artifact()
    accepted_record = completed_record.model_copy(
        update={
            "run": completed_record.run.model_copy(
                update={"status": "accepted", "state_version": 0}
            ),
            "observation": None,
        }
    )
    command = _command(record=accepted_record)
    gateway = _Gateway(command, artifact=artifact)
    authority = _CompletingAuthority(accepted_record, completed_record)
    observations = _ObservationAuthority()
    provider = _Provider(
        result=MetricQueryProviderResult(
            storage_uri=artifact.storage_uri,
            media_type=artifact.media_type,
            sha256=artifact.content_sha256,
            size_bytes=artifact.size_bytes,
            manifest={
                key: value
                for key, value in artifact.manifest.items()
                if key not in {"schema", "rows_returned"}
            },
            rows_returned=1,
            rows_scanned=2,
            bytes_scanned=128,
            duration_ms=5,
        )
    )

    result = MetricQueryCommandConsumer(
        provider,
        gateway=gateway,
        authority=authority,
        observation_authority=observations,
    ).run_once(TENANT, worker_id=WORKER)

    assert result.query_succeeded == 1
    assert result.completed == 1
    assert len(provider.calls) == 1
    assert len(observations.projects) == 1
    assert gateway.completed == [(TENANT, command.command_id, WORKER)]


def test_scalar_observation_reconciliation_rejects_result_hash_drift() -> None:
    record, artifact = _terminal_scalar_record_and_artifact()
    command = _command(record=record)
    consumer = MetricQueryCommandConsumer(
        _Provider(),
        gateway=_Gateway(
            command,
            artifact=artifact.model_copy(update={"content_sha256": "d" * 64}),
        ),
        authority=_Authority(record=record),
        observation_authority=_ObservationAuthority(),
    )

    with pytest.raises(
        MetricQueryProviderContractError,
        match="not bound to exact result evidence",
    ):
        consumer._reconcile_observation(record)


def test_scalar_result_projection_is_derived_from_exact_provider_row() -> None:
    plan = _record().admission.plan

    projection = _scalar_observation_projection(
        plan,
        [{"metric_value": "25.00"}],
        "e" * 64,
    )

    assert projection is not None
    assert projection.result_sha256 == "e" * 64
    assert projection.projection.value.as_tuple() == (0, (2, 5, 0, 0), -2)
    grouped = plan.model_copy(
        update={
            "physical_intent": plan.physical_intent.model_copy(
                update={"group_by_columns": ("district_code",)}
            )
        }
    )
    assert (
        _scalar_observation_projection(
            grouped,
            [{"district_code": "d01", "metric_value": "25.00"}],
            "e" * 64,
        )
        is None
    )


def test_grouped_result_projection_preserves_order_and_duplicate_dimensions() -> None:
    plan = _record().admission.plan
    grouped = plan.model_copy(
        update={
            "physical_intent": plan.physical_intent.model_copy(
                update={
                    "group_by_columns": ("district_code",),
                    "group_by_dimensions": ("district",),
                }
            )
        }
    )
    rows = [
        {"district_code": "d01", "metric_value": "25.00"},
        {"district_code": "d01", "metric_value": "30.00"},
    ]

    batch = _grouped_observation_projection(grouped, rows, "e" * 64)

    assert batch is not None
    assert [item.result_row_index for item in batch.projections] == [0, 1]
    assert [item.projection.dimensions for item in batch.projections] == [
        {"district": "d01"},
        {"district": "d01"},
    ]
    assert batch.projections[0].result_row_fingerprint != (
        batch.projections[1].result_row_fingerprint
    )

def test_postgis_provider_binds_scalar_observation_to_result_bytes(tmp_path: Path) -> None:
    connection = MagicMock()
    read_only_result = MagicMock()
    read_only_result.scalar_one.return_value = "on"
    evidence_result = MagicMock()
    evidence_result.mappings.return_value.one.return_value = {
        "rows_scanned": 2,
        "bytes_scanned": 128,
    }
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = [
        {"metric_value": Decimal("25.00")}
    ]
    connection.execute.side_effect = [
        MagicMock(),
        read_only_result,
        evidence_result,
        rows_result,
    ]
    engine = MagicMock()
    engine.dialect = create_engine("postgresql+psycopg2://").dialect
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    provider = PostGISMetricQueryProvider(engine, result_root=tmp_path)
    record = _record()

    result = provider.execute(
        record.admission.plan,
        run_id=record.run.run_id,
        plan_fingerprint=record.admission.plan_fingerprint,
    )

    payload = Path(urlsplit(result.storage_uri).path).read_bytes()
    document = json.loads(payload)
    projection = result.manifest["metric_observation_projection"]
    assert document["rows"] == [{"metric_value": "25.00"}]
    assert projection["result_sha256"] == result.sha256
    assert projection["projection"]["value"] == "25.00"


def test_retry_exhaustion_writes_query_failure_before_failing_command() -> None:
    command = _command(attempt_count=3, max_attempts=3)
    gateway = _Gateway(command)
    authority = _Authority()
    provider = _Provider(MetricQueryProviderTransientError("database unavailable"))

    result = MetricQueryCommandConsumer(
        provider, gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id=WORKER)

    assert result.failed == 1
    assert result.query_failed == 1
    assert authority.completions[0][2].error_code == "provider_retry_exhausted"
    assert gateway.failed


def test_postgis_compiler_quotes_identifiers_and_binds_values(tmp_path: Path) -> None:
    engine = create_engine("postgresql+psycopg2://")
    provider = PostGISMetricQueryProvider(
        engine,
        result_root=tmp_path,
        relation_authority="serving",
    )
    plan = _record().admission.plan

    query, evidence, parameters = provider._queries(plan)

    assert 'FROM "metrics"."land_area_daily" AS source' in query
    assert "SELECT count(*)::bigint" in evidence
    assert ";" not in query
    assert parameters == {}


def test_postgis_provider_rejects_unsafe_plan_identifier(tmp_path: Path) -> None:
    engine = create_engine("postgresql+psycopg2://")
    provider = PostGISMetricQueryProvider(engine, result_root=tmp_path)
    plan = _record().admission.plan
    unsafe = plan.model_copy(
        update={
            "physical_intent": plan.physical_intent.model_copy(
                update={"value_column": 'metric_value"; DELETE FROM secrets; --'}
            )
        }
    )

    with pytest.raises(MetricQueryProviderContractError, match="unsafe PostGIS"):
        provider._queries(unsafe)


def test_postgis_result_storage_failure_is_retryable_and_redacted(
    tmp_path: Path,
) -> None:
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("fixture", encoding="utf-8")
    provider = PostGISMetricQueryProvider(
        create_engine("postgresql+psycopg2://"),
        result_root=blocked_root,
    )
    record = _record()

    with pytest.raises(
        MetricQueryProviderTransientError,
        match="result storage is unavailable",
    ) as raised:
        provider._write_result(record.admission.plan, record.run.run_id, b"{}")

    assert str(blocked_root) not in str(raised.value)


@pytest.mark.parametrize(
    ("storage_error", "provider_error"),
    [
        (
            MetricQueryResultStoreUnavailable("private object endpoint"),
            MetricQueryProviderTransientError,
        ),
        (
            MetricQueryResultStoreConflict("private object identity"),
            MetricQueryProviderContractError,
        ),
    ],
)
def test_postgis_provider_maps_result_store_errors_without_detail(
    storage_error,
    provider_error,
) -> None:
    class _FailingStore:
        backend_name = "s3"

        def put(self, *_args, **_kwargs):
            raise storage_error

        def probe(self):
            return None

    provider = PostGISMetricQueryProvider(
        create_engine("postgresql+psycopg2://"),
        result_store=_FailingStore(),
    )
    record = _record()

    with pytest.raises(provider_error) as raised:
        provider._write_result(record.admission.plan, record.run.run_id, b"{}")

    assert "private object" not in str(raised.value)


def test_postgis_provider_carries_exact_s3_version_into_result_manifest() -> None:
    class _Result:
        def __init__(self, *, scalar=None, one=None, rows=None):
            self.scalar = scalar
            self.one_value = one
            self.rows = rows

        def scalar_one(self):
            return self.scalar

        def mappings(self):
            return self

        def one(self):
            return self.one_value

        def all(self):
            return self.rows

    class _Connection:
        def __init__(self):
            self.results = [
                _Result(),
                _Result(scalar="on"),
                _Result(one={"rows_scanned": 4, "bytes_scanned": 512}),
                _Result(rows=[]),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def begin(self):
            return self

        def exec_driver_sql(self, _statement):
            return None

        def execute(self, _statement, _parameters=None):
            return self.results.pop(0)

    class _Engine:
        def __init__(self, dialect):
            self.dialect = dialect

        def connect(self):
            return _Connection()

    class _VersionedStore:
        backend_name = "s3"

        def put(self, tenant_id, run_id, payload, **_kwargs):
            return MetricQueryResultPublication(
                storage_uri=f"s3://gis-agent-results/results/{tenant_id}/{run_id}.json",
                backend="s3",
                version_id="immutable-version-1",
                etag="result-etag-1",
            )

        def probe(self):
            return None

    dialect = create_engine("postgresql+psycopg2://").dialect
    provider = PostGISMetricQueryProvider(
        _Engine(dialect),
        result_store=_VersionedStore(),
    )
    record = _record()

    result = provider.execute(
        record.admission.plan,
        run_id=record.run.run_id,
        plan_fingerprint=record.admission.plan_fingerprint,
    )

    assert result.manifest["storage_evidence"] == {
        "schema": "gda.s3_object_version.v1",
        "version_id": "immutable-version-1",
        "etag": "result-etag-1",
    }
