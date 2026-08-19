from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from data_agent.cross_store_projection_compensation_chongqing_federated_recovery import (
    ChongqingFederatedCompensationProviderRecoveryAdapter,
    ChongqingFederatedCompensationRecoveryExecutionError,
    ChongqingFederatedCompensationRecoveryState,
    ChongqingFederatedCompensationRecoveryValidationError,
    resume_chongqing_federated_compensation_unknown_position,
)
from data_agent.cross_store_projection_compensation_chongqing_federated_recovery_attempt import (
    ChongqingFederatedCompensationUnknownResumeAttemptRequest,
    build_chongqing_federated_compensation_unknown_resume_attempt_receipt,
)
from data_agent.cross_store_projection_compensation_chongqing_five_provider_authority import (
    record_chongqing_federated_compensation_five_provider_authority,
)
from data_agent.cross_store_projection_compensation_chongqing_security_audit import (
    InMemoryChongqingCompensationSecurityAudit,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    build_chongqing_federated_compensation_source_lineage_reconciliation_case,
)
from data_agent.cross_store_projection_compensation_completion_authority import (
    FederatedProjectionCompensationCompletionReceipt,
    FederatedProjectionCompensationCompletionWriteResult,
)
from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunProviderUnknownError,
)
from data_agent.cross_store_projection_compensation_provider_reconciliation import (
    ProviderReconciliationConflictError,
    observe_provider_unknown_outcome,
    resume_provider_unknown_outcome,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionEngine,
    ProjectionTargetObservation,
)
from data_agent.lakehouse_projection_executor import LakehouseProjectionRepairReceipt
from data_agent.object_projection_executor import ObjectProjectionRepairReceipt
from data_agent.postgis_projection_executor import PostGISProjectionRepairReceipt
from data_agent.rdf_projection_executor import RDFProjectionRepairReceipt
from data_agent.test_cross_store_projection_compensation_checkpoint_writer import _Authority
from data_agent.test_cross_store_projection_compensation_chongqing_five_provider_execution import (
    _TENANT,
    _execute_five_provider_inputs,
    _execution_subject,
    _five_provider_inputs,
    _receipt_document,
    _StaticExecutionSecurityReader,
)
from data_agent.vector_projection_executor import VectorProjectionRepairReceipt

PREPARED_BY = "workload:chongqing-five-provider-recovery-preparer"
WRITER_SUBJECT = "workload:chongqing-five-provider-recovery-writer"
COMPLETED_BY = "workload:chongqing-five-provider-recovery-completion"
AUTHORITY_AT = datetime(2026, 8, 18, 12, 2, tzinfo=UTC)


def _recovery_security_kwargs(*, reader=None, subject_id="test", security_audit_port=None):
    return {
        "subject_context": _execution_subject(subject_id=subject_id),
        "execution_security_reader": reader or _StaticExecutionSecurityReader(),
        "security_audit_port": security_audit_port
        or InMemoryChongqingCompensationSecurityAudit(_TENANT),
    }


class _NativeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    run_id: str
    position: int
    request_sha256: str = ""
    materialization_binding_sha256: str
    provider_plan_sha256: str
    provider_idempotency_key: str
    provider_execution_status: str
    provider_execution_performed_by_adapter: bool
    checkpoint_authority_write_performed_by_adapter: bool
    compensation_completion_recorded_by_adapter: bool
    provider_mutation_performed: bool = True
    receipt: Any


_RECEIPT_TYPES = {
    ProjectionEngine.POSTGIS: PostGISProjectionRepairReceipt,
    ProjectionEngine.VECTOR: VectorProjectionRepairReceipt,
    ProjectionEngine.RDF: RDFProjectionRepairReceipt,
    ProjectionEngine.OBJECT_STORE: ObjectProjectionRepairReceipt,
    ProjectionEngine.LAKEHOUSE: LakehouseProjectionRepairReceipt,
}


class _TargetRegistry:
    def __init__(self, target: Any):
        self.target = target

    def resolve(self, **_: Any) -> Any:
        return self.target


class _MemoryAttemptAuthority:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.receipts = {}

    def consume(self, request: ChongqingFederatedCompensationUnknownResumeAttemptRequest):
        key = (request.run_id, request.request_bundle_sha256, request.position)
        if request.tenant_id != self.tenant_id or key in self.receipts:
            raise RuntimeError("unknown-resume attempt budget is exhausted")
        receipt = build_chongqing_federated_compensation_unknown_resume_attempt_receipt(
            request
        )
        self.receipts[key] = receipt
        return receipt


class _Executor:
    def __init__(
        self,
        request: Any,
        receipt: BaseModel | None,
        observation: Any,
        materialized_by_position: dict[int, Any],
    ):
        self.request = request
        self.receipt = receipt
        self.observation = observation
        self.materialized_by_position = materialized_by_position
        self.registry = _TargetRegistry(getattr(request, "target", None))

    def recover_receipt(self, _: Any) -> BaseModel | None:
        return self.receipt

    def observe(self, _: Any) -> Any:
        return self.observation

    def execute(self, request: Any) -> _NativeResult:
        plan = request.execution_plan
        receipt = _RECEIPT_TYPES[plan.target_engine].model_validate(
            _receipt_document(self.materialized_by_position[plan.position])
        )
        self.receipt = None
        return _native_result(request, receipt)


def _native_result(request_or_binding: Any, receipt: BaseModel) -> _NativeResult:
    binding = getattr(request_or_binding, "execution_plan", request_or_binding)
    tenant_id = request_or_binding.tenant_id
    run_id = request_or_binding.run_id
    return _NativeResult(
        tenant_id=tenant_id,
        run_id=run_id,
        position=binding.position,
        request_sha256=getattr(request_or_binding, "request_sha256", ""),
        materialization_binding_sha256=binding.materialization_binding_sha256,
        provider_plan_sha256=binding.provider_plan_sha256,
        provider_idempotency_key=binding.provider_idempotency_key,
        provider_execution_status="provider_mutation_committed",
        provider_execution_performed_by_adapter=True,
        checkpoint_authority_write_performed_by_adapter=False,
        compensation_completion_recorded_by_adapter=False,
        receipt=receipt,
    )


def _recovery_inputs(monkeypatch):
    inputs = _five_provider_inputs(monkeypatch)
    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        profile_release_history,
        source_lineage_set,
        profiled_binding,
        profile_execution_release_binding,
        requests,
        request_bundle,
    ) = inputs
    materialized_by_position = {item.position: item for item in materialization.bindings}
    calls: list[int] = []

    def invoke(engine: ProjectionEngine):
        def callback(binding):
            calls.append(binding.position)
            if binding.position == 1:
                raise FederatedCompensationRunProviderUnknownError("timeout")
            receipt = _RECEIPT_TYPES[engine].model_validate(
                _receipt_document(materialized_by_position[binding.position])
            )
            return _native_result(binding, receipt)

        return callback

    registry = FederatedCompensationProviderInvokerRegistry(
        {engine: invoke(engine) for engine in ProjectionEngine}
    )
    prior_execution = _execute_five_provider_inputs(
        inputs,
        registry,
        request_bundle=request_bundle,
        requests=requests,
    )
    case = build_chongqing_federated_compensation_source_lineage_reconciliation_case(
        deployment_binding,
        source_lineage_set,
        prior_execution.profiled_execution.source_lineage_execution,
    )

    executors = {}
    for engine, request in requests.items():
        position = request.execution_plan.position
        receipt = (
            _RECEIPT_TYPES[engine].model_validate(
                _receipt_document(materialized_by_position[position])
            )
            if position < 1
            else None
        )
        executors[engine] = _Executor(
            request,
            receipt,
            request.execution_plan.observation,
            materialized_by_position,
        )

    def observe(request, stopped_case, *, executor, reconciled_by, reconciled_at):
        return observe_provider_unknown_outcome(
            request,
            stopped_case,
            executor=executor,
            engine=request.execution_plan.target_engine,
            provider="fake",
            recover_receipt=lambda current, plan: current.recover_receipt(plan),
            observe_target=lambda current, target: current.observe(target),
            reconciled_by=reconciled_by,
            reconciled_at=reconciled_at,
        )

    def resume(request, stopped_case, safe, *, executor, resumed_by, resumed_at):
        return resume_provider_unknown_outcome(
            request,
            stopped_case,
            safe,
            executor=executor,
            engine=request.execution_plan.target_engine,
            provider="fake",
            recover_receipt=lambda current, plan: current.recover_receipt(plan),
            observe_target=lambda current, target: current.observe(target),
            execute_mutation=lambda current, current_executor: current_executor.execute(current),
            resumed_by=resumed_by,
            resumed_at=resumed_at,
        )

    adapters = {
        engine: ChongqingFederatedCompensationProviderRecoveryAdapter(
            engine,
            lambda executor, plan: executor.recover_receipt(plan),
            observe,
            resume,
        )
        for engine in ProjectionEngine
    }
    unknown_engine = next(
        engine for engine, request in requests.items() if request.execution_plan.position == 1
    )
    safe_observation = observe(
        requests[unknown_engine],
        case,
        executor=executors[unknown_engine],
        reconciled_by="workload:test",
        reconciled_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
    )
    return (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    )


def test_unknown_position_resume_rebuilds_five_receipts_without_prefix_replay(
    monkeypatch,
):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)
    security_reader = _StaticExecutionSecurityReader()

    result = resume_chongqing_federated_compensation_unknown_position(
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        case,
        requests,
        executors,
        adapters,
        safe_observation,
        registry,
        **_recovery_security_kwargs(reader=security_reader),
        attempt_authority=attempt_authority,
        reconciled_by="workload:test",
        resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
    )

    assert result.state is (
        ChongqingFederatedCompensationRecoveryState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    assert result.receipt_validation_set is not None
    assert result.receipt_validation_set.receipt_count == 5
    assert result.reconciliation_case_closed is True
    assert [item.action for item in result.position_evidence] == [
        "prefix_receipt_recovered",
        "unknown_position_resumed",
        "suffix_provider_invoked",
        "suffix_provider_invoked",
        "suffix_provider_invoked",
    ]
    assert calls == [0, 1, 2, 3, 4]
    assert result.recovered_execution_result is not None
    assert result.unknown_resume_attempt_receipt is not None
    assert len(attempt_authority.receipts) == 1
    assert security_reader.calls == 1
    assert result.subject_purpose_resource_preflight_performed is True
    assert result.execution_security_authority_live_read_performed is True
    assert result.security_audit_admission.request_sha256 == (
        result.execution_security_decision.request.request_sha256
    )
    assert result.security_audit_outcome.outcome == "success"
    assert result.security_audit_outcome.provider_invocations == 4
    assert (
        result.execution_security_decision.request.operation
        == "chongqing.five_provider.recover_unknown"
    )
    assert [
        item.access_mode
        for item in result.execution_security_decision.request.resources
    ] == ["read_receipt", "mutate", "mutate", "mutate", "mutate"]


def test_recovery_security_audit_admission_failure_stops_before_attempt_or_provider(
    monkeypatch,
):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    requests, request_bundle = inputs[-2:]
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)
    calls_before_recovery = tuple(calls)

    class _FailingAudit(InMemoryChongqingCompensationSecurityAudit):
        def record_admission(self, *args, **kwargs):
            raise RuntimeError("audit ledger unavailable")

    with pytest.raises(
        ChongqingFederatedCompensationRecoveryValidationError,
        match="security admission audit",
    ):
        resume_chongqing_federated_compensation_unknown_position(
            prior_execution,
            request_bundle,
            inputs[0],
            inputs[1],
            inputs[2],
            case,
            requests,
            executors,
            adapters,
            safe_observation,
            registry,
            **_recovery_security_kwargs(
                security_audit_port=_FailingAudit(_TENANT)
            ),
            attempt_authority=attempt_authority,
            reconciled_by="workload:test",
            resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
        )
    assert attempt_authority.receipts == {}
    assert tuple(calls) == calls_before_recovery


def test_recovery_security_denial_stops_before_attempt_or_provider_callback(monkeypatch):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)
    security_reader = _StaticExecutionSecurityReader(effect="deny")
    calls_before_recovery = tuple(calls)

    with pytest.raises(
        ChongqingFederatedCompensationRecoveryValidationError,
        match="subject-purpose-resource authorization",
    ):
        resume_chongqing_federated_compensation_unknown_position(
            prior_execution,
            request_bundle,
            intent,
            plan_set,
            materialization,
            case,
            requests,
            executors,
            adapters,
            safe_observation,
            registry,
            **_recovery_security_kwargs(reader=security_reader),
            attempt_authority=attempt_authority,
            reconciled_by="workload:test",
            resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
        )

    assert security_reader.calls == 1
    assert tuple(calls) == calls_before_recovery
    assert attempt_authority.receipts == {}


def test_durable_attempt_budget_rejects_second_resume_before_provider_callback(
    monkeypatch,
):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)
    arguments = (
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        case,
        requests,
        executors,
        adapters,
        safe_observation,
        registry,
    )

    resume_chongqing_federated_compensation_unknown_position(
        *arguments,
        **_recovery_security_kwargs(),
        attempt_authority=attempt_authority,
        reconciled_by="workload:test",
        resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
    )
    calls_after_first_attempt = tuple(calls)

    with pytest.raises(
        ChongqingFederatedCompensationRecoveryExecutionError,
        match="could not be consumed",
    ):
        resume_chongqing_federated_compensation_unknown_position(
            *arguments,
            **_recovery_security_kwargs(),
            attempt_authority=attempt_authority,
            reconciled_by="workload:test",
            resumed_at=datetime(2026, 8, 18, 12, 2, tzinfo=UTC),
        )

    assert tuple(calls) == calls_after_first_attempt
    assert len(attempt_authority.receipts) == 1


def test_unknown_position_observation_that_changed_stops_before_suffix(
    monkeypatch,
):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    unknown_engine = next(
        engine for engine, request in requests.items() if request.execution_plan.position == 1
    )
    unknown_request = requests[unknown_engine]
    sealed_observation = unknown_request.execution_plan.observation
    desired = unknown_request.execution_plan.desired_state
    changed = sealed_observation.model_copy(
        update=(
            {
                "target_exists": False,
                "observed_content_sha256": None,
                "observed_row_count": 0,
            }
            if sealed_observation.target_exists
            else {
                "target_exists": True,
                "observed_content_sha256": desired.expected_target_content_sha256,
                "observed_row_count": desired.expected_row_count,
            }
        )
    )
    executors[unknown_engine].observation = changed
    changed_observation = adapters[unknown_engine].observe_unknown(
        unknown_request,
        case,
        executor=executors[unknown_engine],
        reconciled_by="workload:test",
        reconciled_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
    )
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)

    result = resume_chongqing_federated_compensation_unknown_position(
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        case,
        requests,
        executors,
        adapters,
        changed_observation,
        registry,
        **_recovery_security_kwargs(),
        attempt_authority=attempt_authority,
        reconciled_by="workload:test",
        resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
    )

    assert result.state is (
        ChongqingFederatedCompensationRecoveryState.RECONCILIATION_OR_OPERATOR_REQUIRED
    )
    assert result.receipt_validation_set is None
    assert result.reconciliation_case_closed is False
    assert calls == [0, 1]
    assert result.position_evidence[-1].action == "unknown_operator_required"
    assert result.unknown_resume_attempt_receipt is None
    assert attempt_authority.receipts == {}


def _with_unknown_resume(
    adapters: dict[ProjectionEngine, ChongqingFederatedCompensationProviderRecoveryAdapter],
    unknown_engine: ProjectionEngine,
    resume_unknown: Any,
) -> dict[ProjectionEngine, ChongqingFederatedCompensationProviderRecoveryAdapter]:
    updated = dict(adapters)
    adapter = adapters[unknown_engine]
    updated[unknown_engine] = replace(adapter, resume_unknown=resume_unknown)
    return updated


def _unknown_resume_failure_result(monkeypatch, exception: Exception):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    unknown_engine = next(
        engine for engine, request in requests.items() if request.execution_plan.position == 1
    )
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)

    def fail_resume(*_: Any, **__: Any) -> Any:
        raise exception

    result = resume_chongqing_federated_compensation_unknown_position(
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        case,
        requests,
        executors,
        _with_unknown_resume(adapters, unknown_engine, fail_resume),
        safe_observation,
        registry,
        **_recovery_security_kwargs(),
        attempt_authority=attempt_authority,
        reconciled_by="workload:test",
        resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
    )
    return result, calls


def test_resume_exception_returns_unknown_without_running_suffix(monkeypatch):
    result, calls = _unknown_resume_failure_result(
        monkeypatch,
        RuntimeError("transport response lost"),
    )

    assert result.state is (
        ChongqingFederatedCompensationRecoveryState.RECONCILIATION_OR_OPERATOR_REQUIRED
    )
    assert result.run_result.state.value == "unknown_pending_reconciliation"
    assert result.receipt_validation_set is None
    evidence = result.position_evidence[-1]
    assert evidence.action == "unknown_resume_outcome_unknown"
    assert evidence.provider_invocation_performed is None
    assert result.unknown_resume_attempt_receipt is not None
    assert calls == [0, 1]


def test_resume_observation_conflict_returns_operator_required_without_provider_call(
    monkeypatch,
):
    result, calls = _unknown_resume_failure_result(
        monkeypatch,
        ProviderReconciliationConflictError("target changed after observation"),
    )

    evidence = result.position_evidence[-1]
    assert evidence.action == "unknown_operator_required"
    assert evidence.provider_invocation_performed is False
    assert result.run_result.steps[-1].outcome.error_code == (
        "provider_state_changed_before_resume"
    )
    assert result.unknown_resume_attempt_receipt is not None
    assert calls == [0, 1]


class _MemoryCompletionAuthority:
    def __init__(self):
        self.receipt: FederatedProjectionCompensationCompletionReceipt | None = None

    def current(self, run_id: str):
        if self.receipt is None or self.receipt.run_id != run_id:
            return None
        return self.receipt

    def record(self, request):
        created = self.receipt is None
        if created:
            self.receipt = FederatedProjectionCompensationCompletionReceipt(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                write_request_set_sha256=request.write_request_set_sha256,
                authority_record_set_sha256=request.authority_record_set_sha256,
                targets=request.targets,
                completion_idempotency_key=request.completion_idempotency_key,
                completion_request_sha256=request.request_sha256,
                completed_by=request.completed_by,
                completed_at=AUTHORITY_AT,
            )
        return FederatedProjectionCompensationCompletionWriteResult(
            receipt=self.receipt,
            created=created,
        )


def test_completed_recovery_result_is_accepted_by_existing_authority_path(monkeypatch):
    (
        inputs,
        prior_execution,
        case,
        executors,
        adapters,
        safe_observation,
        registry,
        calls,
    ) = _recovery_inputs(monkeypatch)
    intent, plan_set, materialization = inputs[:3]
    requests, request_bundle = inputs[-2:]
    attempt_authority = _MemoryAttemptAuthority(prior_execution.tenant_id)
    result = resume_chongqing_federated_compensation_unknown_position(
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        case,
        requests,
        executors,
        adapters,
        safe_observation,
        registry,
        **_recovery_security_kwargs(),
        attempt_authority=attempt_authority,
        reconciled_by="workload:test",
        resumed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
    )
    assert result.recovered_execution_result is not None

    repair_plans = tuple(
        request.execution_plan.source_plan
        for request in sorted(requests.values(), key=lambda item: item.execution_plan.position)
    )
    final_observations = tuple(
        ProjectionTargetObservation(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_engine=plan.target_engine,
            target_ref=plan.target_ref,
            target_exists=plan.desired_state.target_exists,
            observed_content_sha256=plan.desired_state.expected_target_content_sha256,
            observed_row_count=plan.desired_state.expected_row_count,
            observed_by="workload:chongqing-five-provider-final-observer",
            observed_at=AUTHORITY_AT,
        )
        for plan in repair_plans
    )
    authority_result = record_chongqing_federated_compensation_five_provider_authority(
        result.recovered_execution_result,
        request_bundle,
        plan_set,
        materialization,
        repair_plans,
        final_observations,
        _Authority(),
        _MemoryCompletionAuthority(),
        prepared_by=PREPARED_BY,
        writer_subject=WRITER_SUBJECT,
        completed_by=COMPLETED_BY,
        prepared_at=AUTHORITY_AT,
        updated_at=AUTHORITY_AT,
    )

    assert authority_result.authority_state == "five_provider_compensation_completion_recorded"
    assert authority_result.checkpoint_count_recorded == 5
    assert authority_result.compensation_completion_recorded is True
    assert authority_result.provider_execution_performed_by_authority is False
