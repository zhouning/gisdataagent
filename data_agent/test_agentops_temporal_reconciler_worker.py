from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from data_agent.agentops_provider_identity import derive_specialist_provider_receipt_ref
from data_agent.agentops_specialist_providers import (
    InMemorySpecialistCancellationAdapter,
    InMemorySpecialistOperationAuthority,
    LocalArtifact,
    SpecialistReconciliationVerdict,
    SpecialistUncertaintyType,
    build_gwm_provider_spec,
)
from data_agent.agentops_temporal_adapter import TemporalAdapterError
from data_agent.agentops_temporal_checkpoint_authority import (
    AgentOpsTemporalCheckpointAuthorityConfigurationError,
    AgentOpsTemporalCheckpointAuthorityConflictError,
    AgentOpsTemporalReconcilerLease,
)
from data_agent.agentops_temporal_reconciler_worker import (
    AgentOpsTemporalReconcilerCycleStatus,
    AgentOpsTemporalReconcilerDiscoveryConfig,
    AgentOpsTemporalReconcilerDiscoveryStatus,
    AgentOpsTemporalReconcilerDiscoveryStatusStore,
    AgentOpsTemporalReconcilerDiscoveryWorker,
    AgentOpsTemporalReconcilerLeaseLostError,
    AgentOpsTemporalReconcilerWorker,
    AgentOpsTemporalReconcilerWorkerConfig,
    AgentOpsTemporalReconcilerWorkerConfigurationError,
    AgentOpsTemporalSpecialistCycleStatus,
    _build_specialist_runtime_dependencies,
    evaluate_discovery_health,
    evaluate_discovery_liveness,
    evaluate_runtime_image_contract,
)
from data_agent.agentops_temporal_reconciliation import (
    TemporalHistoryReconciliationError,
    TemporalProviderActivityHistoryStatus,
    reconcile_specialist_activity_history,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
from data_agent.test_agentops_temporal_checkpoint_authority import (
    _checkpoint,
    _observation,
)
from data_agent.test_agentops_temporal_reconciliation import (
    _history_activity,
    _input,
    _subject,
    _workflow_observation,
)


class _Observer:
    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.calls = 0

    async def observe_workflow_history(self, **_kwargs: Any):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return _observation()


class _ObservationObserver(_Observer):
    def __init__(self, observation: Any) -> None:
        super().__init__()
        self.observation = observation

    async def observe_workflow_history(self, **_kwargs: Any):
        self.calls += 1
        return self.observation


class _Authority:
    def __init__(
        self,
        *,
        renew_error: Exception | None = None,
        recovered: Any | None = None,
        write_error: Exception | None = None,
    ) -> None:
        self.checkpoint = _checkpoint("checkpoint_after")
        self.renew_error = renew_error
        self.recovered = recovered
        self.write_error = write_error
        self.renewed = 0
        self.released = 0
        self.recorded = 0

    @staticmethod
    def _lease(expires_in: float = 3) -> AgentOpsTemporalReconcilerLease:
        now = datetime.now(UTC)
        checkpoint = _checkpoint("checkpoint_after")
        return AgentOpsTemporalReconcilerLease(
            tenant_id=checkpoint.workflow_input.tenant_id,
            workflow_id=checkpoint.workflow_input.identity.workflow_id,
            lease_owner="workload:agentops-reconciler-test",
            lease_epoch=7,
            lease_acquired_at=now,
            lease_expires_at=now + timedelta(seconds=expires_in),
            lease_updated_at=now,
        )

    def acquire_reconciler_lease(self, **_kwargs: Any):
        return self._lease()

    def renew_reconciler_lease(self, lease, *, lease_seconds: int):
        self.renewed += 1
        if self.renew_error is not None:
            raise self.renew_error
        return lease.model_copy(
            update={
                "lease_expires_at": datetime.now(UTC)
                + timedelta(seconds=lease_seconds),
                "lease_updated_at": datetime.now(UTC),
            }
        )

    def release_reconciler_lease(self, lease):
        self.released += 1
        return lease

    def current_checkpoint(self, **_kwargs: Any):
        return self.checkpoint

    def resolve_reconciliation_write(self, *_args: Any):
        return self.recovered

    def record_reconciliation(self, *_args: Any, **_kwargs: Any):
        self.recorded += 1
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(created=True)


def _config(**overrides: Any) -> AgentOpsTemporalReconcilerWorkerConfig:
    checkpoint = _checkpoint("checkpoint_after")
    values = {
        "tenant_id": checkpoint.workflow_input.tenant_id,
        "namespace_ref": (
            checkpoint.workflow_input.identity.namespace.namespace_ref
        ),
        "frontend_target": "temporal:7233",
        "workflow_id": checkpoint.workflow_input.identity.workflow_id,
        "provider_run_id": _observation().provider_run_id,
        "lease_owner": "workload:agentops-reconciler-test",
        "lease_seconds": 3,
        "heartbeat_interval_seconds": 0.1,
        "observation_timeout_seconds": 2,
        "poll_interval_seconds": 0.1,
    }
    values.update(overrides)
    return AgentOpsTemporalReconcilerWorkerConfig(**values)


def _provider_bound_fixture():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    step = workflow_input.task_graph.steps[0]
    harness.start_step(workflow_id, step.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref="tool:agentops-specialist:v1",
        capability_ref="capability:agentops.specialist:v1",
        subject_context=_subject(),
        side_effect="none",
        policy_decision_ref="artifact://policy-decision-agent-run",
        idempotency_key="specialist-worker:tool-call",
    )
    call = snapshot.execution.tool_calls[0]
    spec = build_gwm_provider_spec(input_artifact_ids=(), observation_id="worker-test")
    schedule = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.specialist.activity",
        schedule_to_close_timeout_seconds=40,
        start_to_close_timeout_seconds=20,
        heartbeat_timeout_seconds=2,
        provider_spec=spec,
    ).activity_schedules[0]
    checkpoint = harness.checkpoint(workflow_id)
    activity = _history_activity(
        schedule,
        status=TemporalProviderActivityHistoryStatus.TIMED_OUT,
        scheduled_event_id=5,
        started_event_id=6,
        terminal_event_id=7,
        timeout_type="TIMEOUT_TYPE_START_TO_CLOSE",
    )
    observation = _workflow_observation(workflow_input, (activity,))
    return workflow_input, checkpoint, schedule, activity, observation


class _ArtifactStore:
    def __init__(self, artifact: LocalArtifact) -> None:
        self.artifact = artifact

    def resolve_input(self, tenant_id: str, artifact_id: UUID) -> LocalArtifact:
        if tenant_id != self.artifact.tenant_id or artifact_id != self.artifact.artifact_id:
            raise RuntimeError("artifact not found")
        return self.artifact


def test_worker_renews_during_observation_records_and_releases() -> None:
    authority = _Authority()
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(),
            provider=_Observer(delay=0.25),
            authority=authority,
        ).run_once()
    )

    assert authority.renewed >= 2
    assert authority.recorded == 1
    assert authority.released == 1
    assert cycle.status is AgentOpsTemporalReconcilerCycleStatus.RECORDED
    assert cycle.created is True
    assert cycle.lease_epoch == 7
    assert cycle.verdict.value == "matched"


def test_worker_reconciles_provider_timeout_as_unknown_pending_without_evidence(
    tmp_path,
) -> None:
    _workflow_input, checkpoint, _schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    from data_agent.agentops_specialist_providers import FilesystemSpecialistArtifactStore

    artifact_store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(
                tenant_id=checkpoint.workflow_input.tenant_id,
                namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                workflow_id=checkpoint.workflow_input.identity.workflow_id,
                provider_run_id=observation.provider_run_id,
            ),
            provider=_ObservationObserver(observation),
            authority=authority,
            artifact_store=artifact_store,
            operation_authority=specialist_authority,
        ).run_once()
    )

    activity_id = str(observation.activities[0].activity_id)
    assert cycle.specialist_status is AgentOpsTemporalSpecialistCycleStatus.UNKNOWN_PENDING
    assert cycle.specialist_unknown_pending_ids == (activity_id,)
    assert cycle.checkpoint_missing_evidence_ids == (activity_id,)
    assert cycle.verdict.value == "checkpoint_behind"


def test_worker_reconciles_provider_receipt_and_artifact_as_success(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=f"provider://worker/{schedule.activity_id}",
    )
    output_id = uuid5(
        NAMESPACE_URL,
        f"gda-specialist-output:{schedule.request.tenant_id}:{schedule.activity_id}:{schedule.attempt_no}",
    )
    content = b'{"observation_id":"worker-test"}\n'
    content_sha = __import__("hashlib").sha256(content).hexdigest()
    path = tmp_path / "output.json"
    path.write_bytes(content)
    manifest = {
        "request_sha256": schedule.request.request_sha256,
        "provider_ref": schedule.request.provider_spec.provider_ref,
        "operation_ref": schedule.request.provider_spec.operation_ref,
        "input_artifact_ids": [],
        "lineage": {"source_artifact_ids": []},
        "content_sha256": content_sha,
    }
    artifact = LocalArtifact(
        tenant_id=schedule.request.tenant_id,
        artifact_id=output_id,
        storage_path=path,
        media_type=schedule.request.provider_spec.output_media_type,
        content_sha256=content_sha,
        manifest=manifest,
    )
    specialist_authority.succeed(operation_ref, output_id)
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(
                tenant_id=checkpoint.workflow_input.tenant_id,
                namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                workflow_id=checkpoint.workflow_input.identity.workflow_id,
                provider_run_id=observation.provider_run_id,
            ),
            provider=_ObservationObserver(observation),
            authority=authority,
            artifact_store=_ArtifactStore(artifact),
            operation_authority=specialist_authority,
        ).run_once()
    )

    activity_id = str(observation.activities[0].activity_id)
    assert cycle.specialist_status is AgentOpsTemporalSpecialistCycleStatus.MATCHED_SUCCEEDED
    assert cycle.specialist_matched_succeeded_ids == (activity_id,)
    assert cycle.checkpoint_missing_evidence_ids == (activity_id,)
    assert cycle.verdict.value == "checkpoint_behind"


def test_worker_reconciles_provider_cancel_receipt_as_definitive_failure(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=f"provider://worker/{schedule.activity_id}",
    )
    specialist_authority.cancel(operation_ref, "ProviderConfirmedCancel")

    class _MissingArtifactStore:
        def resolve_input(self, *_args: Any, **_kwargs: Any):
            raise RuntimeError("no output artifact")

    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(
                tenant_id=checkpoint.workflow_input.tenant_id,
                namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                workflow_id=checkpoint.workflow_input.identity.workflow_id,
                provider_run_id=observation.provider_run_id,
            ),
            provider=_ObservationObserver(observation),
            authority=authority,
            artifact_store=_MissingArtifactStore(),
            operation_authority=specialist_authority,
        ).run_once()
    )

    activity_id = str(observation.activities[0].activity_id)
    assert cycle.specialist_status is AgentOpsTemporalSpecialistCycleStatus.DEFINITIVE_FAILED
    assert cycle.specialist_definitive_failed_ids == (activity_id,)
    assert cycle.checkpoint_missing_evidence_ids == (activity_id,)
    assert cycle.verdict.value == "checkpoint_behind"


def test_worker_keeps_submitted_provider_receipt_pending(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=f"provider://worker/{schedule.activity_id}",
    )
    from data_agent.agentops_specialist_providers import FilesystemSpecialistArtifactStore

    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(
                tenant_id=checkpoint.workflow_input.tenant_id,
                namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                workflow_id=checkpoint.workflow_input.identity.workflow_id,
                provider_run_id=observation.provider_run_id,
            ),
            provider=_ObservationObserver(observation),
            authority=authority,
            artifact_store=FilesystemSpecialistArtifactStore(tmp_path / "artifacts"),
            operation_authority=specialist_authority,
        ).run_once()
    )

    activity_id = str(observation.activities[0].activity_id)
    assert cycle.specialist_status is AgentOpsTemporalSpecialistCycleStatus.UNKNOWN_PENDING
    assert cycle.specialist_unknown_pending_ids == (activity_id,)
    assert cycle.checkpoint_missing_evidence_ids == (activity_id,)


def test_managed_reconciliation_observes_provider_terminal_cancellation(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    receipt_ref = derive_specialist_provider_receipt_ref(schedule.request)
    specialist_authority = InMemorySpecialistOperationAuthority()
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )
    specialist_authority.request_cancellation(
        operation_ref,
        uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED,
    )
    cancellation_adapter = InMemorySpecialistCancellationAdapter()
    cancellation_adapter.confirm(
        schedule.request,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )

    _history_join, reconciliation, settled = reconcile_specialist_activity_history(
        observation.activities[0],
        artifact_store=__import__(
            "data_agent.agentops_specialist_providers",
            fromlist=["FilesystemSpecialistArtifactStore"],
        ).FilesystemSpecialistArtifactStore(tmp_path / "artifacts"),
        operation_authority=specialist_authority,
        cancellation_adapter=cancellation_adapter,
    )

    assert reconciliation.verdict is SpecialistReconciliationVerdict.DEFINITIVE_FAILED
    assert settled.failure_type == "ProviderCancellationConfirmed"
    receipt = specialist_authority.observe(operation_ref)
    assert receipt is not None
    assert receipt.status.value == "cancelled"
    assert receipt.uncertainty_type is None


def test_worker_passes_provider_cancellation_adapter_to_managed_reconciliation(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    receipt_ref = derive_specialist_provider_receipt_ref(schedule.request)
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )
    specialist_authority.request_cancellation(
        operation_ref,
        uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED,
    )
    cancellation_adapter = InMemorySpecialistCancellationAdapter()
    cancellation_adapter.confirm(
        schedule.request,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )
    from data_agent.agentops_specialist_providers import FilesystemSpecialistArtifactStore

    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(
                tenant_id=checkpoint.workflow_input.tenant_id,
                namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                workflow_id=checkpoint.workflow_input.identity.workflow_id,
                provider_run_id=observation.provider_run_id,
            ),
            provider=_ObservationObserver(observation),
            authority=authority,
            artifact_store=FilesystemSpecialistArtifactStore(tmp_path / "artifacts"),
            operation_authority=specialist_authority,
            cancellation_adapters={
                schedule.request.provider_spec.provider_ref: cancellation_adapter
            },
        ).run_once()
    )

    activity_id = str(observation.activities[0].activity_id)
    assert cycle.specialist_status is AgentOpsTemporalSpecialistCycleStatus.DEFINITIVE_FAILED
    assert cycle.specialist_definitive_failed_ids == (activity_id,)
    assert specialist_authority.observe(operation_ref).status.value == "cancelled"


def test_worker_fails_closed_on_success_receipt_with_mismatched_artifact(tmp_path) -> None:
    _workflow_input, checkpoint, schedule, _activity, observation = _provider_bound_fixture()
    authority = _Authority()
    authority.checkpoint = checkpoint
    specialist_authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{schedule.request.provider_spec.operation_ref}://{schedule.activity_id}"
    specialist_authority.submit(
        schedule.request,
        provider_ref=schedule.request.provider_spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=f"provider://worker/{schedule.activity_id}",
    )
    output_id = uuid5(
        NAMESPACE_URL,
        f"gda-specialist-output:{schedule.request.tenant_id}:{schedule.activity_id}:{schedule.attempt_no}",
    )
    content = b'{"observation_id":"worker-test"}\n'
    content_sha = __import__("hashlib").sha256(content).hexdigest()
    path = tmp_path / "output.json"
    path.write_bytes(content)
    artifact = LocalArtifact(
        tenant_id=schedule.request.tenant_id,
        artifact_id=output_id,
        storage_path=path,
        media_type=schedule.request.provider_spec.output_media_type,
        content_sha256=content_sha,
        manifest={
            "request_sha256": "0" * 64,
            "provider_ref": schedule.request.provider_spec.provider_ref,
            "operation_ref": schedule.request.provider_spec.operation_ref,
            "input_artifact_ids": [],
            "lineage": {"source_artifact_ids": []},
            "content_sha256": content_sha,
        },
    )
    specialist_authority.succeed(operation_ref, output_id)

    with pytest.raises(TemporalHistoryReconciliationError, match="reconciliation failed"):
        asyncio.run(
            AgentOpsTemporalReconcilerWorker(
                _config(
                    tenant_id=checkpoint.workflow_input.tenant_id,
                    namespace_ref=checkpoint.workflow_input.identity.namespace.namespace_ref,
                    workflow_id=checkpoint.workflow_input.identity.workflow_id,
                    provider_run_id=observation.provider_run_id,
                ),
                provider=_ObservationObserver(observation),
                authority=authority,
                artifact_store=_ArtifactStore(artifact),
                operation_authority=specialist_authority,
            ).run_once()
        )


def test_worker_fails_closed_when_heartbeat_loses_lease() -> None:
    authority = _Authority(
        renew_error=AgentOpsTemporalCheckpointAuthorityConflictError("lost")
    )

    with pytest.raises(AgentOpsTemporalReconcilerLeaseLostError):
        asyncio.run(
            AgentOpsTemporalReconcilerWorker(
                _config(),
                provider=_Observer(delay=1),
                authority=authority,
            ).run_once()
        )

    assert authority.recorded == 0
    assert authority.released == 0


def test_worker_recovers_exact_existing_write_without_rebinding_epoch() -> None:
    authority = _Authority(recovered=SimpleNamespace(binding=object()))
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(), provider=_Observer(), authority=authority
        ).run_once()
    )

    assert cycle.status is AgentOpsTemporalReconcilerCycleStatus.RECOVERED
    assert cycle.created is False
    assert authority.recorded == 0
    assert authority.released == 1


def test_worker_resolves_unknown_commit_before_returning_failure() -> None:
    authority = _Authority(
        write_error=AgentOpsTemporalCheckpointAuthorityConfigurationError(
            "unknown commit"
        )
    )

    def resolve_after_write(*_args: Any):
        return (
            SimpleNamespace(binding=object())
            if authority.recorded
            else None
        )

    authority.resolve_reconciliation_write = resolve_after_write  # type: ignore[method-assign]
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerWorker(
            _config(), provider=_Observer(), authority=authority
        ).run_once()
    )

    assert authority.recorded == 1
    assert cycle.status is AgentOpsTemporalReconcilerCycleStatus.RECOVERED
    assert cycle.created is False


def test_worker_rejects_checkpoint_namespace_drift_before_provider_call() -> None:
    observer = _Observer()
    authority = _Authority()

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="checkpoint namespace differs",
    ):
        asyncio.run(
            AgentOpsTemporalReconcilerWorker(
                _config(namespace_ref="other-namespace"),
                provider=observer,
                authority=authority,
            ).run_once()
        )

    assert observer.calls == 0
    assert authority.released == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"lease_seconds": 2}, "lease"),
        ({"heartbeat_interval_seconds": 1.5}, "heartbeat"),
        ({"frontend_target": "temporal"}, "host:port"),
        ({"lease_owner": "human:operator"}, "workload or agent"),
    ],
)
def test_worker_configuration_rejects_unsafe_values(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError, match=message
    ):
        _config(**overrides).validate()


def test_worker_configuration_requires_explicit_target_from_environment() -> None:
    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="GDA_AGENTOPS_RECONCILER_TENANT_ID",
    ):
        AgentOpsTemporalReconcilerWorkerConfig.from_env({})


def test_live_specialist_runtime_requires_explicit_content_backend(monkeypatch) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.delenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", raising=False)

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="SPECIALIST_ARTIFACT_BACKEND",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wraps_database_engine_initialization_failure(
    monkeypatch,
) -> None:
    def _raise_engine_error():
        raise RuntimeError("database URL could not be parsed")

    monkeypatch.setattr("data_agent.db_engine.get_engine", _raise_engine_error)

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="PostgreSQL engine could not be initialized",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wraps_gateway_initialization_failure(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "filesystem"
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT",
        str(tmp_path / "content"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    def _raise_gateway_error(_engine):
        raise RuntimeError("gateway construction failed")

    monkeypatch.setattr("data_agent.platform_gateway.PlatformGateway", _raise_gateway_error)

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="Artifact authority configuration is invalid",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wraps_generic_startup_probe_failures(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _ReceiptAuthority:
        def __init__(self, *_args, **_kwargs):
            pass

        def observe(self, _operation_ref):
            raise RuntimeError("receipt table is unavailable")

    class _Gateway:
        def __init__(self, _engine):
            pass

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr(
        "data_agent.agentops_specialist_operation_authority.PostgresSpecialistOperationAuthority",
        _ReceiptAuthority,
    )
    monkeypatch.setattr("data_agent.platform_gateway.PlatformGateway", _Gateway)
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "filesystem"
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT",
        str(tmp_path / "content"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="operation receipt authority probe failed",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wraps_generic_artifact_probe_failures(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _ReceiptAuthority:
        def __init__(self, *_args, **_kwargs):
            pass

        def observe(self, _operation_ref):
            return None

    class _Gateway:
        def __init__(self, _engine):
            pass

        def get_artifact(self, _tenant_id, _artifact_id):
            raise RuntimeError("artifact schema is unavailable")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr(
        "data_agent.agentops_specialist_operation_authority.PostgresSpecialistOperationAuthority",
        _ReceiptAuthority,
    )
    monkeypatch.setattr("data_agent.platform_gateway.PlatformGateway", _Gateway)
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "filesystem"
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT",
        str(tmp_path / "content"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="Artifact authority probe failed",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wraps_durable_authority_initialization_failure(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _ReceiptAuthority:
        def __init__(self, *_args, **_kwargs):
            pass

        def observe(self, _operation_ref):
            return None

    class _Gateway:
        def __init__(self, _engine):
            pass

        def get_artifact(self, _tenant_id, _artifact_id):
            from data_agent.platform_gateway import GatewayNotFoundError

            raise GatewayNotFoundError("not found")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr(
        "data_agent.agentops_specialist_operation_authority.PostgresSpecialistOperationAuthority",
        _ReceiptAuthority,
    )
    monkeypatch.setattr("data_agent.platform_gateway.PlatformGateway", _Gateway)
    monkeypatch.setattr(
        "data_agent.agentops_specialist_providers.PostgresArtifactAuthoritySpecialistStore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("read-only root")),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "filesystem"
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT",
        str(tmp_path / "content"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="durable authorities could not be initialized",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_wires_postgres_authorities_for_filesystem_backend(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _ReceiptAuthority:
        def __init__(self, tenant_id, engine, *, recorded_by):
            self.tenant_id = tenant_id
            self.engine = engine
            self.recorded_by = recorded_by

        def observe(self, _operation_ref):
            return None

    class _Gateway:
        def __init__(self, engine):
            self.engine = engine

        def get_artifact(self, _tenant_id, _artifact_id):
            from data_agent.platform_gateway import GatewayNotFoundError

            raise GatewayNotFoundError("not found")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr(
        "data_agent.agentops_specialist_operation_authority.PostgresSpecialistOperationAuthority",
        _ReceiptAuthority,
    )
    monkeypatch.setattr("data_agent.platform_gateway.PlatformGateway", _Gateway)
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "filesystem"
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT",
        str(tmp_path / "content"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    dependencies = _build_specialist_runtime_dependencies("planning")

    assert dependencies.operation_authority.tenant_id == "planning"
    assert dependencies.artifact_store.tenant_id == "planning"
    assert dependencies.artifact_store.materialization_root == (
        tmp_path / "materialized"
    ).resolve()


def test_live_specialist_runtime_rejects_mutable_s3_configuration(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET", "evidence")
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID", "false"
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="REQUIRE_VERSION_ID must be true",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_rejects_disabled_s3_object_lock_requirement(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET", "evidence")
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_OBJECT_LOCK_RETENTION",
        "false",
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="REQUIRE_OBJECT_LOCK_RETENTION must be true",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_rejects_s3_bucket_without_versioning(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _S3Client:
        def get_bucket_versioning(self, **_kwargs):
            return {"Status": "Suspended"}

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: _S3Client())
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET", "evidence")
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="bucket must have versioning enabled",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_live_specialist_runtime_rejects_s3_bucket_without_object_lock_retention(
    monkeypatch, tmp_path
) -> None:
    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

    class _S3Client:
        def get_bucket_versioning(self, **_kwargs):
            return {"Status": "Enabled"}

        def get_object_lock_configuration(self, **_kwargs):
            return {
                "ObjectLockConfiguration": {
                    "ObjectLockEnabled": "Disabled",
                    "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
                }
            }

    monkeypatch.setattr("data_agent.db_engine.get_engine", lambda: _Engine())
    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: _S3Client())
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET", "evidence")
    monkeypatch.setenv(
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT",
        str(tmp_path / "materialized"),
    )

    with pytest.raises(
        AgentOpsTemporalReconcilerWorkerConfigurationError,
        match="bucket must have object lock enabled",
    ):
        _build_specialist_runtime_dependencies("planning")


def test_managed_loop_retries_transient_temporal_observation_failure() -> None:
    class _FlakyObserver(_Observer):
        async def observe_workflow_history(self, **kwargs: Any):
            self.calls += 1
            if self.calls == 1:
                raise TemporalAdapterError("provider temporarily unavailable")
            return _observation()

    async def exercise() -> tuple[int, int]:
        authority = _Authority()
        observer = _FlakyObserver()
        stop = asyncio.Event()
        worker = AgentOpsTemporalReconcilerWorker(
            _config(), provider=observer, authority=authority
        )
        task = asyncio.create_task(worker.run(stop))
        deadline = asyncio.get_running_loop().time() + 2
        while authority.recorded == 0:
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("managed worker did not retry observation")
            await asyncio.sleep(0.02)
        stop.set()
        await task
        return observer.calls, authority.recorded

    calls, recorded = asyncio.run(exercise())

    assert calls >= 2
    assert recorded >= 1


def test_discovery_status_store_is_atomic_and_probes_distinguish_ready_from_live(
    tmp_path,
) -> None:
    now = datetime.now(UTC)
    store = AgentOpsTemporalReconcilerDiscoveryStatusStore(
        tmp_path / "status" / "discovery.json"
    )
    store.write(
        AgentOpsTemporalReconcilerDiscoveryStatus(
            state="ready",
            tenant_id="planning",
            worker_id="workload:discovery-test",
            started_at=now - timedelta(seconds=3),
            updated_at=now,
            last_success_at=now,
            frontend_reachable=True,
            cycles=2,
            claimed=3,
            completed=2,
            pending=1,
        )
    )

    health, healthy = evaluate_discovery_health(store, max_age_seconds=30, now=now)
    liveness, live = evaluate_discovery_liveness(store, max_age_seconds=30, now=now)
    assert healthy is True
    assert live is True
    assert health["completed"] == 2
    assert liveness["worker_state"] == "ready"
    assert not list((tmp_path / "status").glob("*.tmp"))


def test_discovery_readiness_fails_when_temporal_frontend_is_unhealthy(tmp_path) -> None:
    now = datetime.now(UTC)
    store = AgentOpsTemporalReconcilerDiscoveryStatusStore(tmp_path / "status.json")
    store.write(
        AgentOpsTemporalReconcilerDiscoveryStatus(
            state="ready",
            tenant_id="planning",
            worker_id="workload:discovery-test",
            started_at=now,
            updated_at=now,
            last_success_at=now,
            frontend_reachable=False,
        )
    )

    report, healthy = evaluate_discovery_health(store, max_age_seconds=30, now=now)
    assert healthy is False
    assert report["reason"] == "temporal_frontend_unreachable"


def test_runtime_image_contract_fails_on_temporal_sdk_drift(monkeypatch) -> None:
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.31.0")
    report, passed = evaluate_runtime_image_contract()

    assert passed is False
    assert report["missing_migrations"] == []
    assert any("version mismatch" in error for error in report["errors"])


def test_discovery_child_reconciler_reuses_all_runtime_authorities(
    monkeypatch, tmp_path
) -> None:
    from data_agent.test_agentops_temporal_start_target_authority import (
        _Provider,
        _TargetAuthority,
        _unknown_target,
    )

    target, _request, _result = _unknown_target()
    target_authority = _TargetAuthority(target)
    checkpoint_authority = _Authority()
    artifact_store = object()
    operation_authority = object()
    captured: dict[str, Any] = {}

    class _ChildReconciler:
        def __init__(
            self,
            _config,
            *,
            provider,
            authority,
            artifact_store,
            operation_authority,
            cancellation_adapters,
        ):
            captured.update(
                provider=provider,
                authority=authority,
                artifact_store=artifact_store,
                operation_authority=operation_authority,
                cancellation_adapters=cancellation_adapters,
            )

        async def run_once(self):
            return SimpleNamespace(status=AgentOpsTemporalReconcilerCycleStatus.NO_CHECKPOINT)

    monkeypatch.setattr(
        "data_agent.agentops_temporal_reconciler_worker.AgentOpsTemporalReconcilerWorker",
        _ChildReconciler,
    )
    config = AgentOpsTemporalReconcilerDiscoveryConfig(
        tenant_id=target.tenant_id,
        namespace_ref=target.namespace_ref,
        worker_id="workload:target-worker",
        lease_seconds=5,
        heartbeat_interval_seconds=0.1,
        observation_timeout_seconds=2,
        poll_interval_seconds=0.1,
        status_file=tmp_path / "discovery-status.json",
    )
    worker = AgentOpsTemporalReconcilerDiscoveryWorker(
        config,
        provider=_Provider(target),
        target_authority=target_authority,
        checkpoint_authority=checkpoint_authority,
        artifact_store=artifact_store,
        operation_authority=operation_authority,
    )

    outcome = asyncio.run(worker._process_target(target))

    assert outcome == "pending"
    assert captured["authority"] is checkpoint_authority
    assert captured["artifact_store"] is artifact_store
    assert captured["operation_authority"] is operation_authority
