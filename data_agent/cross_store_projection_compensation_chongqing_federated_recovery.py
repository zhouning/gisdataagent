"""Resume one unknown position in a stopped Chongqing five-Provider run.

The stopped source-lineage case deliberately contains hash-only outcomes.  This
module therefore rebuilds receipt evidence from the Provider's receipt store,
uses the Provider-specific unknown-outcome wrapper for the one safe resume, and
invokes only the still-unattempted suffix.  It never retries a committed prefix
and never writes checkpoint or completion authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_execution_security import (
    ChongqingFederatedCompensationExecutionSecurityCurrentReader,
    ChongqingFederatedCompensationExecutionSecurityDecision,
    ChongqingFederatedCompensationExecutionSecurityError,
    authorize_chongqing_federated_compensation_execution_security,
    build_chongqing_federated_compensation_execution_security_request,
    build_chongqing_federated_compensation_execution_security_resource,
    chongqing_execution_subject_ref,
)
from .cross_store_projection_compensation_chongqing_federated_recovery_attempt import (
    ChongqingFederatedCompensationUnknownResumeAttemptAuthority,
    ChongqingFederatedCompensationUnknownResumeAttemptReceipt,
    build_chongqing_federated_compensation_unknown_resume_attempt_request,
)
from .cross_store_projection_compensation_chongqing_five_provider_execution import (
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
    FiveProviderMutationRequest,
)
from .cross_store_projection_compensation_chongqing_security_audit import (
    ChongqingFederatedCompensationSecurityAuditAdmission,
    ChongqingFederatedCompensationSecurityAuditOutcome,
    ChongqingFederatedCompensationSecurityAuditPort,
    require_security_audit_port,
)
from .cross_store_projection_compensation_chongqing_source_lineage_reconciliation import (
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationProviderOutcome,
    FederatedCompensationProviderOutcomeStatus,
    FederatedCompensationRunBinding,
    FederatedCompensationRunProviderFailureError,
    FederatedCompensationRunProviderUnknownError,
    FederatedCompensationRunResult,
    FederatedCompensationRunState,
    FederatedCompensationRunStep,
    build_federated_compensation_provider_outcome_from_native_result,
    build_federated_compensation_run_bindings,
    seal_federated_compensation_run_result,
)
from .cross_store_projection_compensation_lakehouse_reconciliation import (
    observe_federated_compensation_lakehouse_unknown_outcome,
    resume_federated_compensation_lakehouse_unknown_outcome,
)
from .cross_store_projection_compensation_object_reconciliation import (
    observe_federated_compensation_object_unknown_outcome,
    resume_federated_compensation_object_unknown_outcome,
)
from .cross_store_projection_compensation_postgis_reconciliation import (
    observe_federated_compensation_postgis_unknown_outcome,
    resume_federated_compensation_postgis_unknown_outcome,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_compensation_provider_receipt import (
    FederatedProjectionCompensationProviderReceiptValidation,
    FederatedProjectionCompensationProviderReceiptValidationError,
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from .cross_store_projection_compensation_provider_receipt_set import (
    FederatedProjectionCompensationProviderReceiptValidationSet,
    build_federated_compensation_provider_receipt_validation_set_from_run,
)
from .cross_store_projection_compensation_provider_reconciliation import (
    ProviderReconciliationConflictError,
    ProviderReconciliationObservation,
    ProviderReconciliationResumeResult,
)
from .cross_store_projection_compensation_rdf_reconciliation import (
    observe_federated_compensation_rdf_unknown_outcome,
    resume_federated_compensation_rdf_unknown_outcome,
)
from .cross_store_projection_compensation_vector_reconciliation import (
    observe_federated_compensation_vector_unknown_outcome,
    resume_federated_compensation_vector_unknown_outcome,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)


class ChongqingFederatedCompensationRecoveryError(RuntimeError):
    """The stopped run cannot be resumed without guessing."""


class ChongqingFederatedCompensationRecoveryValidationError(
    ChongqingFederatedCompensationRecoveryError
):
    """The stopped case, request bundle, or evidence is inconsistent."""


class ChongqingFederatedCompensationRecoveryConfigurationError(
    ChongqingFederatedCompensationRecoveryError
):
    """A complete typed Provider recovery registry is not available."""


class ChongqingFederatedCompensationRecoveryExecutionError(
    ChongqingFederatedCompensationRecoveryError
):
    """A suffix Provider invocation or receipt recovery failed closed."""


class ChongqingFederatedCompensationRecoveryState(StrEnum):
    COMPLETED_RECEIPT_SET_PENDING_AUTHORITY = "completed_receipt_set_pending_authority"
    RECONCILIATION_OR_OPERATOR_REQUIRED = "reconciliation_or_operator_required"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery fingerprint datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


@dataclass(frozen=True)
class ChongqingFederatedCompensationProviderRecoveryAdapter:
    """Typed wrapper boundary for one concrete Provider's recovery contract."""

    engine: ProjectionEngine
    recover_receipt: Callable[[Any, Any], BaseModel | None]
    observe_unknown: Callable[..., ProviderReconciliationObservation]
    resume_unknown: Callable[..., ProviderReconciliationResumeResult]


def _recover_provider_receipt(executor: Any, plan: Any) -> BaseModel | None:
    return executor.recover_receipt(plan)


def build_chongqing_federated_compensation_provider_recovery_adapters() -> dict[
    ProjectionEngine, ChongqingFederatedCompensationProviderRecoveryAdapter
]:
    """Return the governed five-wrapper registry used by Chongqing recovery."""

    return {
        ProjectionEngine.POSTGIS: ChongqingFederatedCompensationProviderRecoveryAdapter(
            ProjectionEngine.POSTGIS,
            _recover_provider_receipt,
            observe_federated_compensation_postgis_unknown_outcome,
            resume_federated_compensation_postgis_unknown_outcome,
        ),
        ProjectionEngine.VECTOR: ChongqingFederatedCompensationProviderRecoveryAdapter(
            ProjectionEngine.VECTOR,
            _recover_provider_receipt,
            observe_federated_compensation_vector_unknown_outcome,
            resume_federated_compensation_vector_unknown_outcome,
        ),
        ProjectionEngine.RDF: ChongqingFederatedCompensationProviderRecoveryAdapter(
            ProjectionEngine.RDF,
            _recover_provider_receipt,
            observe_federated_compensation_rdf_unknown_outcome,
            resume_federated_compensation_rdf_unknown_outcome,
        ),
        ProjectionEngine.OBJECT_STORE: ChongqingFederatedCompensationProviderRecoveryAdapter(
            ProjectionEngine.OBJECT_STORE,
            _recover_provider_receipt,
            observe_federated_compensation_object_unknown_outcome,
            resume_federated_compensation_object_unknown_outcome,
        ),
        ProjectionEngine.LAKEHOUSE: ChongqingFederatedCompensationProviderRecoveryAdapter(
            ProjectionEngine.LAKEHOUSE,
            _recover_provider_receipt,
            observe_federated_compensation_lakehouse_unknown_outcome,
            resume_federated_compensation_lakehouse_unknown_outcome,
        ),
    }


class ChongqingFederatedCompensationRecoveryPositionEvidence(_FrozenModel):
    """Hash-only evidence for one prefix, resumed, or suffix position."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-recovery-position-evidence.v2"
    position: int = Field(ge=0, le=31)
    target_engine: ProjectionEngine
    action: Literal[
        "prefix_receipt_recovered",
        "unknown_commit_confirmed",
        "unknown_position_resumed",
        "unknown_operator_required",
        "unknown_resume_outcome_unknown",
        "suffix_provider_invoked",
        "suffix_provider_stopped_unknown",
        "suffix_provider_stopped_failed",
    ]
    outcome_sha256: Sha256
    receipt_validation_sha256: Sha256 | None = None
    observation_sha256: Sha256 | None = None
    resume_result_sha256: Sha256 | None = None
    unknown_resume_attempt_receipt_sha256: Sha256 | None = None
    # None means the recovery wrapper was entered but it did not establish
    # whether its Provider mutation was invoked or committed.
    provider_invocation_performed: bool | None
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationRecoveryPositionEvidence:
        if (
            self.action == "prefix_receipt_recovered"
            and self.provider_invocation_performed is not False
        ):
            raise ValueError("recovered prefix evidence cannot claim a Provider invocation")
        if self.action == "unknown_commit_confirmed" and (
            self.provider_invocation_performed is not False or self.observation_sha256 is None
        ):
            raise ValueError("confirmed unknown evidence is missing observation contract")
        if self.action == "unknown_operator_required" and (
            self.provider_invocation_performed is not False or self.observation_sha256 is None
        ):
            raise ValueError("operator-required unknown evidence is inconsistent")
        if self.action == "unknown_resume_outcome_unknown" and (
            self.provider_invocation_performed is not None or self.observation_sha256 is None
        ):
            raise ValueError("unknown resume evidence must preserve invocation uncertainty")
        if self.action == "unknown_position_resumed" and (
            self.provider_invocation_performed is not True
            or self.observation_sha256 is None
            or self.resume_result_sha256 is None
            or self.unknown_resume_attempt_receipt_sha256 is None
        ):
            raise ValueError("resumed unknown evidence is incomplete")
        if self.action == "unknown_resume_outcome_unknown" and (
            self.unknown_resume_attempt_receipt_sha256 is None
        ):
            raise ValueError("unknown resume evidence lacks durable attempt authority")
        if self.action not in {
            "unknown_position_resumed",
            "unknown_operator_required",
            "unknown_resume_outcome_unknown",
        } and self.unknown_resume_attempt_receipt_sha256 is not None:
            raise ValueError("non-resume evidence cannot contain an attempt receipt")
        if (
            self.action == "suffix_provider_invoked"
            and self.provider_invocation_performed is not True
        ):
            raise ValueError("suffix invocation evidence lacks the invocation marker")
        if (
            self.action.startswith("suffix_provider_stopped")
            and self.provider_invocation_performed is not True
        ):
            raise ValueError("stopped suffix evidence lacks the invocation marker")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"evidence_sha256"}),
            "evidence_sha256",
        )
        if self.evidence_sha256 != expected:
            raise ValueError("recovery position evidence fingerprint is invalid")
        return self


class ChongqingFederatedCompensationRecoveryResult(_FrozenModel):
    """Federated recovery result before the existing authority admission path."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-recovery-result.v3"
    tenant_id: TenantId
    run_id: NonEmptyText
    prior_execution_result_sha256: Sha256
    reconciliation_case_sha256: Sha256
    request_bundle_sha256: Sha256
    action_map_sha256: Sha256
    action_execution_binding_sha256: Sha256
    production_admission_event_sha256: Sha256
    recovered_position: int = Field(ge=0, le=31)
    run_result: FederatedCompensationRunResult
    receipt_validation_set: FederatedProjectionCompensationProviderReceiptValidationSet | None = (
        None
    )
    recovered_execution_result: ChongqingFederatedCompensationFiveProviderExecutionResult | None = (
        None
    )
    unknown_resume_attempt_receipt: (
        ChongqingFederatedCompensationUnknownResumeAttemptReceipt | None
    ) = None
    execution_security_decision: (
        ChongqingFederatedCompensationExecutionSecurityDecision
    )
    security_audit_admission: ChongqingFederatedCompensationSecurityAuditAdmission
    security_audit_outcome: ChongqingFederatedCompensationSecurityAuditOutcome
    position_evidence: tuple[ChongqingFederatedCompensationRecoveryPositionEvidence, ...] = Field(
        min_length=1, max_length=32
    )
    state: ChongqingFederatedCompensationRecoveryState
    reconciliation_case_closed: bool
    subject_purpose_resource_preflight_performed: Literal[True] = True
    execution_security_authority_live_read_performed: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationRecoveryResult:
        complete = self.state is (
            ChongqingFederatedCompensationRecoveryState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
        )
        if self.tenant_id != self.run_result.tenant_id or self.run_id != self.run_result.run_id:
            raise ValueError("recovery identity differs from run result")
        if complete:
            if (
                self.receipt_validation_set is None
                or not self.run_result.provider_receipts_complete
                or self.run_result.state
                is not (FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY)
                or self.recovered_execution_result is None
                or not self.reconciliation_case_closed
            ):
                raise ValueError("completed recovery lacks authority-admissible evidence")
            recovered_profiled = self.recovered_execution_result.profiled_execution
            recovered_lineage = recovered_profiled.source_lineage_execution
            recovered_deployment = recovered_lineage.deployment_execution
            registered = recovered_deployment.registered_execution
            if (
                registered.receipt_validation_set != self.receipt_validation_set
                or registered.run_result != self.run_result
            ):
                raise ValueError("recovered authority execution differs from recovery evidence")
        elif (
            self.receipt_validation_set is not None
            or self.recovered_execution_result is not None
            or self.reconciliation_case_closed
        ):
            raise ValueError("incomplete recovery contains completion evidence")
        if self.recovered_position not in self.run_result.expected_positions:
            raise ValueError("recovered position is outside the run")
        security_request = self.execution_security_decision.request
        if (
            self.execution_security_decision.effect != "allow"
            or self.execution_security_decision.obligations
            or self.security_audit_admission.tenant_id != self.tenant_id
            or self.security_audit_admission.run_id != self.run_id
            or self.security_audit_admission.operation
            != "chongqing.five_provider.recover_unknown"
            or self.security_audit_admission.request_sha256
            != security_request.request_sha256
            or self.security_audit_admission.decision_sha256
            != self.execution_security_decision.decision_sha256
            or self.security_audit_outcome.tenant_id != self.tenant_id
            or self.security_audit_outcome.run_id != self.run_id
            or self.security_audit_outcome.operation
            != "chongqing.five_provider.recover_unknown"
            or self.security_audit_outcome.admission_sha256
            != self.security_audit_admission.admission_sha256
            or self.security_audit_outcome.evidence_sha256
            != self.run_result.result_sha256
            or security_request.tenant_id != self.tenant_id
            or security_request.run_id != self.run_id
            or security_request.operation
            != "chongqing.five_provider.recover_unknown"
            or security_request.prior_execution_result_sha256
            != self.prior_execution_result_sha256
            or security_request.reconciliation_case_sha256
            != self.reconciliation_case_sha256
            or security_request.request_bundle_sha256
            != self.request_bundle_sha256
            or security_request.action_map_sha256 != self.action_map_sha256
            or security_request.action_execution_binding_sha256
            != self.action_execution_binding_sha256
            or security_request.production_admission_event_sha256
            != self.production_admission_event_sha256
            or security_request.unknown_position != self.recovered_position
            or any(
                item.access_mode
                != (
                    "read_receipt"
                    if item.position < self.recovered_position
                    else "mutate"
                )
                for item in security_request.resources
            )
        ):
            raise ValueError("recovery SPR decision differs from recovery evidence")
        recovered_observation_sha256 = next(
            (
                item.observation_sha256
                for item in self.position_evidence
                if item.position == self.recovered_position
            ),
            None,
        )
        if security_request.safe_observation_sha256 != recovered_observation_sha256:
            raise ValueError("recovery SPR observation differs from position evidence")
        attempt_evidence = tuple(
            item
            for item in self.position_evidence
            if item.unknown_resume_attempt_receipt_sha256 is not None
        )
        if self.unknown_resume_attempt_receipt is None:
            if attempt_evidence:
                raise ValueError("recovery evidence names a missing attempt receipt")
        else:
            receipt = self.unknown_resume_attempt_receipt
            request = receipt.request
            if (
                len(attempt_evidence) != 1
                or attempt_evidence[0].position != self.recovered_position
                or attempt_evidence[0].unknown_resume_attempt_receipt_sha256
                != receipt.receipt_sha256
                or request.tenant_id != self.tenant_id
                or request.run_id != self.run_id
                or request.prior_execution_result_sha256
                != self.prior_execution_result_sha256
                or request.reconciliation_case_sha256
                != self.reconciliation_case_sha256
                or request.request_bundle_sha256 != self.request_bundle_sha256
                or request.position != self.recovered_position
                or request.committed_prefix_replay_allowed
                or receipt.provider_invocation_performed
            ):
                raise ValueError("durable unknown-resume attempt evidence differs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("Chongqing recovery result fingerprint is invalid")
        return self


def _reseal(model: BaseModel, updates: Mapping[str, Any], hash_field: str) -> BaseModel:
    values = model.model_dump(mode="python")
    values.update(updates)
    values[hash_field] = _fingerprint(type(model).schema_id, values, hash_field)
    return type(model)(**values)


def _receipt_values(receipt: BaseModel) -> dict[str, Any]:
    if not isinstance(receipt, BaseModel):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "Provider receipt recovery must return a typed receipt model"
        )
    try:
        return receipt.model_dump(mode="python")
    except (TypeError, ValueError) as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "Provider receipt cannot be serialized"
        ) from exc


def _outcome_from_receipt(
    binding: FederatedCompensationRunBinding,
    receipt: BaseModel,
) -> FederatedCompensationProviderOutcome:
    values = _receipt_values(receipt)
    commit_ref = values.get("provider_commit_ref")
    if not isinstance(commit_ref, Mapping) or not isinstance(commit_ref.get("receipt_sha256"), str):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovered Provider receipt lacks a receipt fingerprint"
        )
    if (
        values.get("tenant_id") != binding.tenant_id
        or values.get("plan_sha256") != binding.provider_plan_sha256
        or values.get("idempotency_key") != binding.provider_idempotency_key
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovered Provider receipt differs from its sealed binding"
        )
    status = (
        FederatedCompensationProviderOutcomeStatus.REPLAYED
        if values.get("status") == "replayed"
        else FederatedCompensationProviderOutcomeStatus.COMMITTED
    )
    outcome_values = {
        "tenant_id": binding.tenant_id,
        "run_id": binding.run_id,
        "position": binding.position,
        "source_plan_sha256": binding.source_plan_sha256,
        "provider_plan_sha256": binding.provider_plan_sha256,
        "provider_idempotency_key": binding.provider_idempotency_key,
        "status": status,
        "provider_receipt_sha256": commit_ref["receipt_sha256"],
        "error_code": None,
    }
    return FederatedCompensationProviderOutcome(
        **outcome_values,
        outcome_sha256=_fingerprint(
            FederatedCompensationProviderOutcome.schema_id,
            outcome_values,
            "outcome_sha256",
        ),
    )


def _step(
    binding: FederatedCompensationRunBinding,
    outcome: FederatedCompensationProviderOutcome,
) -> FederatedCompensationRunStep:
    values = {"binding_sha256": binding.binding_sha256, "outcome": outcome}
    return FederatedCompensationRunStep(
        **values,
        step_sha256=_fingerprint(FederatedCompensationRunStep.schema_id, values, "step_sha256"),
    )


def _stopped_outcome(
    binding: FederatedCompensationRunBinding,
    *,
    status: FederatedCompensationProviderOutcomeStatus,
    error_code: str,
) -> FederatedCompensationProviderOutcome:
    values = {
        "tenant_id": binding.tenant_id,
        "run_id": binding.run_id,
        "position": binding.position,
        "source_plan_sha256": binding.source_plan_sha256,
        "provider_plan_sha256": binding.provider_plan_sha256,
        "provider_idempotency_key": binding.provider_idempotency_key,
        "status": status,
        "provider_receipt_sha256": None,
        "error_code": error_code[:128] or status.value,
    }
    return FederatedCompensationProviderOutcome(
        **values,
        outcome_sha256=_fingerprint(
            FederatedCompensationProviderOutcome.schema_id,
            values,
            "outcome_sha256",
        ),
    )


def _validate_receipt(
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    binding: FederatedCompensationRunBinding,
    receipt: BaseModel,
) -> FederatedProjectionCompensationProviderReceiptValidation:
    materialized = next(
        item
        for item in materialization.bindings
        if item.materialization_binding_sha256 == binding.materialization_binding_sha256
    )
    try:
        candidate = build_federated_compensation_provider_receipt_candidate(
            materialization,
            materialized,
            receipt.model_dump(mode="json"),
        )
        return validate_federated_compensation_provider_receipt_candidate(
            materialization, candidate
        )
    except (FederatedProjectionCompensationProviderReceiptValidationError, StopIteration) as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "Provider receipt cannot be revalidated for the sealed materialization"
        ) from exc


def _call_recover(
    adapter: ChongqingFederatedCompensationProviderRecoveryAdapter,
    executor: Any,
    plan: Any,
) -> BaseModel:
    try:
        receipt = adapter.recover_receipt(executor, plan)
    except Exception as exc:
        raise ChongqingFederatedCompensationRecoveryExecutionError(
            f"{adapter.engine.value} receipt recovery failed"
        ) from exc
    if receipt is None:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            f"{adapter.engine.value} committed prefix has no persisted receipt"
        )
    return receipt


def _complete_execution_result(
    prior: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    run_result: FederatedCompensationRunResult,
    receipt_set: FederatedProjectionCompensationProviderReceiptValidationSet,
) -> ChongqingFederatedCompensationFiveProviderExecutionResult:
    old_profiled = prior.profiled_execution
    old_lineage = old_profiled.source_lineage_execution
    old_deployment = old_lineage.deployment_execution
    old_registered = old_deployment.registered_execution
    registered = _reseal(
        old_registered,
        {
            "run_result": run_result,
            "receipt_validation_set": receipt_set,
            "state": (
                FederatedCompensationRegisteredReceiptExecutionState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
            ),
            "native_receipts_validated": True,
        },
        "result_sha256",
    )
    deployment = _reseal(
        old_deployment,
        {"registered_execution": registered, "state": registered.state},
        "result_sha256",
    )
    lineage = _reseal(
        old_lineage,
        {"deployment_execution": deployment},
        "result_sha256",
    )
    profiled = _reseal(
        old_profiled,
        {"source_lineage_execution": lineage},
        "result_sha256",
    )
    return _reseal(
        prior,
        {
            "request_bundle_sha256": request_bundle.request_bundle_sha256,
            "profiled_execution": profiled,
        },
        "result_sha256",
    )


def _validated_inputs(
    prior_execution: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
) -> tuple[
    ChongqingFederatedCompensationFiveProviderExecutionResult,
    ChongqingFederatedCompensationFiveProviderRequestBundle,
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ChongqingFederatedCompensationSourceLineageReconciliationCase,
]:
    try:
        return (
            ChongqingFederatedCompensationFiveProviderExecutionResult.model_validate(
                prior_execution.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationFiveProviderRequestBundle.model_validate(
                request_bundle.model_dump(mode="python")
            ),
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceLineageReconciliationCase.model_validate(
                reconciliation_case.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "Chongqing recovery input violates a sealed contract"
        ) from exc


def _result(
    *,
    prior_execution: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    recovered_position: int,
    run_result: FederatedCompensationRunResult,
    position_evidence: tuple[ChongqingFederatedCompensationRecoveryPositionEvidence, ...],
    receipt_set: FederatedProjectionCompensationProviderReceiptValidationSet | None,
    recovered_execution: ChongqingFederatedCompensationFiveProviderExecutionResult | None,
    execution_security_decision: (
        ChongqingFederatedCompensationExecutionSecurityDecision
    ),
    security_audit_admission: ChongqingFederatedCompensationSecurityAuditAdmission,
    security_audit_port: ChongqingFederatedCompensationSecurityAuditPort,
    unknown_resume_attempt_receipt: (
        ChongqingFederatedCompensationUnknownResumeAttemptReceipt | None
    ) = None,
) -> ChongqingFederatedCompensationRecoveryResult:
    complete = receipt_set is not None
    values = {
        "tenant_id": prior_execution.tenant_id,
        "run_id": prior_execution.run_id,
        "prior_execution_result_sha256": prior_execution.result_sha256,
        "reconciliation_case_sha256": reconciliation_case.case_sha256,
        "request_bundle_sha256": request_bundle.request_bundle_sha256,
        "action_map_sha256": (
            prior_execution.customer_provider_action_map.action_map_sha256
        ),
        "action_execution_binding_sha256": (
            prior_execution.customer_provider_action_execution_binding.binding_sha256
        ),
        "production_admission_event_sha256": (
            prior_execution.production_admission_event.event_sha256
        ),
        "recovered_position": recovered_position,
        "run_result": run_result,
        "receipt_validation_set": receipt_set,
        "recovered_execution_result": recovered_execution,
        "unknown_resume_attempt_receipt": unknown_resume_attempt_receipt,
        "execution_security_decision": execution_security_decision,
        "security_audit_admission": security_audit_admission,
        "position_evidence": position_evidence,
        "state": (
            ChongqingFederatedCompensationRecoveryState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
            if complete
            else ChongqingFederatedCompensationRecoveryState.RECONCILIATION_OR_OPERATOR_REQUIRED
        ),
        "reconciliation_case_closed": complete,
        "subject_purpose_resource_preflight_performed": True,
        "execution_security_authority_live_read_performed": True,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    try:
        security_audit_outcome = security_audit_port.record_outcome(
            security_audit_admission,
            outcome="success" if complete else "unknown",
            evidence_sha256=run_result.result_sha256,
            provider_invocations=sum(
                1 for item in position_evidence if item.provider_invocation_performed
            ),
            recorded_at=datetime.now(UTC),
        )
        values["security_audit_outcome"] = (
            ChongqingFederatedCompensationSecurityAuditOutcome.model_validate(
                security_audit_outcome.model_dump(mode="python")
            )
        )
    except Exception as exc:
        raise ChongqingFederatedCompensationRecoveryExecutionError(
            "immutable security outcome audit cannot be recorded"
        ) from exc
    return ChongqingFederatedCompensationRecoveryResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationRecoveryResult.schema_id,
            values,
            "result_sha256",
        ),
    )


def resume_chongqing_federated_compensation_unknown_position(
    prior_execution: ChongqingFederatedCompensationFiveProviderExecutionResult,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    reconciliation_case: ChongqingFederatedCompensationSourceLineageReconciliationCase,
    requests: Mapping[ProjectionEngine | str, FiveProviderMutationRequest],
    executors: Mapping[ProjectionEngine | str, Any],
    adapters: Mapping[
        ProjectionEngine | str, ChongqingFederatedCompensationProviderRecoveryAdapter
    ],
    safe_observation: ProviderReconciliationObservation,
    registry: FederatedCompensationProviderInvokerRegistry,
    *,
    subject_context: SubjectContext,
    execution_security_reader: (
        ChongqingFederatedCompensationExecutionSecurityCurrentReader
    ),
    security_audit_port: ChongqingFederatedCompensationSecurityAuditPort,
    attempt_authority: ChongqingFederatedCompensationUnknownResumeAttemptAuthority,
    attempt_id: UUID | None = None,
    reconciled_by: str,
    resumed_at: datetime,
) -> ChongqingFederatedCompensationRecoveryResult:
    """Consume one durable resume budget, then recover the unattempted suffix."""

    (
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        reconciliation_case,
    ) = _validated_inputs(
        prior_execution,
        request_bundle,
        intent,
        plan_set,
        materialization,
        reconciliation_case,
    )
    if not isinstance(registry, FederatedCompensationProviderInvokerRegistry):
        raise ChongqingFederatedCompensationRecoveryConfigurationError(
            "recovery requires the governed Provider invoker registry"
        )
    if (
        prior_execution.profiled_execution.source_lineage_execution.deployment_execution.registered_execution.state
        is not (
            FederatedCompensationRegisteredReceiptExecutionState.RECONCILIATION_OR_OPERATOR_REQUIRED
        )
        or reconciliation_case.federated_run_state
        is not FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION
        or prior_execution.tenant_id != reconciliation_case.tenant_id
        or prior_execution.run_id != reconciliation_case.run_id
        or request_bundle.tenant_id != prior_execution.tenant_id
        or request_bundle.run_id != prior_execution.run_id
        or request_bundle.deployment_binding_sha256 != reconciliation_case.deployment_binding_sha256
        or intent.tenant_id != prior_execution.tenant_id
        or intent.run_id != prior_execution.run_id
        or intent.dispatch_intent_sha256 != request_bundle.dispatch_intent_sha256
        or plan_set.plan_set_sha256 != request_bundle.plan_set_sha256
        or materialization.materialization_set_sha256 != request_bundle.materialization_set_sha256
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovery requires the same stopped Chongqing unknown-outcome run"
        )
    action_map = prior_execution.customer_provider_action_map
    action_binding = prior_execution.customer_provider_action_execution_binding
    if (
        prior_execution.request_bundle_items != request_bundle.items
        or action_map.tenant_id != prior_execution.tenant_id
        or action_map.run_id != prior_execution.run_id
        or action_map.candidate_sha256 != intent.candidate_sha256
        or action_map.candidate_action is not intent.candidate_action
        or action_map.action_map_sha256 != action_binding.action_map_sha256
        or action_binding.tenant_id != prior_execution.tenant_id
        or action_binding.run_id != prior_execution.run_id
        or action_binding.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or action_binding.request_bundle_sha256
        != request_bundle.request_bundle_sha256
        or action_binding.plan_set_sha256 != plan_set.plan_set_sha256
        or action_binding.materialization_set_sha256
        != materialization.materialization_set_sha256
        or not action_binding.customer_action_mapping_preflight_performed
        or action_binding.production_execution_authorized
        or tuple(item.position for item in action_binding.items) != tuple(range(5))
        or tuple(item.position for item in action_map.items) != tuple(range(5))
        or any(
            item.unknown_outcome_policy
            != "observe_receipt_and_target_then_resume_if_safe"
            or item.committed_prefix_replay_allowed
            or item.unknown_position_resume_attempt_limit != 1
            for item in action_map.items
        )
        or any(
            item.unknown_outcome_policy
            != "observe_receipt_and_target_then_resume_if_safe"
            or item.committed_prefix_replay_allowed
            or item.unknown_position_resume_attempt_limit != 1
            for item in action_binding.items
        )
        or any(
            action_map_item.item_sha256
            != binding_item.action_map_item_sha256
            for action_map_item, binding_item in zip(
                action_map.items,
                action_binding.items,
                strict=True,
            )
        )
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovery action mapping differs from the stopped customer-approved execution"
        )
    try:
        bindings = build_federated_compensation_run_bindings(plan_set, materialization)
    except Exception as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovery binding chain is invalid"
        ) from exc
    if (
        len(bindings) != 5
        or request_bundle.request_bundle_sha256 != prior_execution.request_bundle_sha256
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovery request bundle differs from the stopped execution"
        )
    request_by_engine: dict[ProjectionEngine, FiveProviderMutationRequest] = {}
    executor_by_engine: dict[ProjectionEngine, Any] = {}
    adapter_by_engine: dict[
        ProjectionEngine, ChongqingFederatedCompensationProviderRecoveryAdapter
    ] = {}
    try:
        for raw_engine, request in requests.items():
            engine = ProjectionEngine(raw_engine)
            if engine in request_by_engine or not isinstance(request, BaseModel):
                raise ValueError("duplicate or invalid Provider request")
            if request.execution_plan.target_engine is not engine:
                raise ValueError("Provider request engine differs from execution plan")
            request_by_engine[engine] = request
        for raw_engine, executor in executors.items():
            engine = ProjectionEngine(raw_engine)
            if engine in executor_by_engine:
                raise ValueError("duplicate Provider executor")
            executor_by_engine[engine] = executor
        for raw_engine, adapter in adapters.items():
            engine = ProjectionEngine(raw_engine)
            if engine in adapter_by_engine or not isinstance(
                adapter, ChongqingFederatedCompensationProviderRecoveryAdapter
            ):
                raise ValueError("duplicate or invalid Provider recovery adapter")
            if adapter.engine is not engine:
                raise ValueError("Provider recovery adapter engine differs")
            adapter_by_engine[engine] = adapter
    except (TypeError, ValueError) as exc:
        raise ChongqingFederatedCompensationRecoveryConfigurationError(
            "Provider recovery registries are invalid"
        ) from exc
    required = set(ProjectionEngine)
    if (
        set(request_by_engine) != required
        or set(executor_by_engine) != required
        or set(adapter_by_engine) != required
    ):
        raise ChongqingFederatedCompensationRecoveryConfigurationError(
            "Provider recovery registries must cover all five engines"
        )
    request_by_position = {
        request.execution_plan.position: request for request in request_by_engine.values()
    }
    if set(request_by_position) != set(range(5)):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "Provider requests must cover all five positions exactly once"
        )
    bundle_items = {item.position: item for item in request_bundle.items}
    for position, request in request_by_position.items():
        binding = bindings[position]
        item = bundle_items[position]
        plan = request.execution_plan
        if (
            plan.position != position
            or plan.target_engine is not binding.target_engine
            or plan.provider_plan_sha256 != binding.provider_plan_sha256
            or plan.provider_idempotency_key != binding.provider_idempotency_key
            or plan.materialization_binding_sha256 != binding.materialization_binding_sha256
            or item.request_sha256 != request.request_sha256
            or item.request_sha256
            != prior_execution.request_bundle_items[position].request_sha256
            or item.execution_plan_sha256 != plan.execution_plan_sha256
            or item.target_engine is not binding.target_engine
        ):
            raise ChongqingFederatedCompensationRecoveryValidationError(
                f"Provider request at position {position} differs from its sealed bundle"
            )
    unknown_items = [
        item
        for item in reconciliation_case.items
        if item.outcome_class == "provider_outcome_unknown"
    ]
    if len(unknown_items) != 1:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovery requires exactly one unknown stopped position"
        )
    unknown_position = unknown_items[0].position
    stopped_profiled = prior_execution.profiled_execution
    stopped_lineage = stopped_profiled.source_lineage_execution
    stopped_deployment = stopped_lineage.deployment_execution
    stopped_run = stopped_deployment.registered_execution.run_result
    outcome_by_position = {step.outcome.position: step.outcome for step in stopped_run.steps}
    if (
        set(outcome_by_position) != set(range(unknown_position + 1))
        or outcome_by_position[unknown_position].status
        is not FederatedCompensationProviderOutcomeStatus.UNKNOWN
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "stopped run does not contain the expected committed prefix and unknown position"
        )
    try:
        safe_observation = ProviderReconciliationObservation.model_validate(
            safe_observation.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "safe unknown observation violates its sealed contract"
        ) from exc
    unknown_engine = bindings[unknown_position].target_engine
    unknown_request = request_by_engine[unknown_engine]
    unknown_executor = executor_by_engine[unknown_engine]
    unknown_adapter = adapter_by_engine[unknown_engine]
    if (
        safe_observation.position != unknown_position
        or safe_observation.target_engine is not unknown_engine
        or safe_observation.reconciliation_case_sha256 != reconciliation_case.case_sha256
        or safe_observation.reconciliation_item_sha256 != unknown_items[0].item_sha256
        or safe_observation.unknown_outcome_sha256 != unknown_items[0].outcome_sha256
        or safe_observation.tenant_id != prior_execution.tenant_id
        or safe_observation.run_id != prior_execution.run_id
        or safe_observation.request_sha256 != unknown_request.request_sha256
    ):
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "safe observation differs from the unknown stopped position"
        )

    try:
        subject_context = SubjectContext.model_validate(
            subject_context.model_dump(mode="python")
        )
        if chongqing_execution_subject_ref(subject_context) != reconciled_by:
            raise ValueError("recovery subject differs from reconciler workload")
        security_resources = tuple(
            build_chongqing_federated_compensation_execution_security_resource(
                position=position,
                target_engine=action_binding.items[position].target_engine,
                target_ref=action_binding.items[position].target_ref,
                access_mode=(
                    "read_receipt" if position < unknown_position else "mutate"
                ),
                provider_action=action_binding.items[position].provider_action,
                request_sha256=request_bundle.items[position].request_sha256,
                action_map_item_sha256=(
                    action_binding.items[position].action_map_item_sha256
                ),
                action_execution_binding_item_sha256=(
                    action_binding.items[position].item_sha256
                ),
            )
            for position in range(5)
        )
        security_request = (
            build_chongqing_federated_compensation_execution_security_request(
                tenant_id=prior_execution.tenant_id,
                run_id=prior_execution.run_id,
                subject_context=subject_context,
                operation="chongqing.five_provider.recover_unknown",
                request_bundle_sha256=request_bundle.request_bundle_sha256,
                action_map_sha256=action_map.action_map_sha256,
                action_execution_binding_sha256=action_binding.binding_sha256,
                production_admission_event_sha256=(
                    prior_execution.production_admission_event.event_sha256
                ),
                resources=security_resources,
                prior_execution_result_sha256=prior_execution.result_sha256,
                reconciliation_case_sha256=reconciliation_case.case_sha256,
                safe_observation_sha256=safe_observation.observation_sha256,
                unknown_position=unknown_position,
                evaluated_at=resumed_at,
            )
        )
        execution_security_decision = (
            authorize_chongqing_federated_compensation_execution_security(
                security_request,
                execution_security_reader,
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        ValidationError,
        ChongqingFederatedCompensationExecutionSecurityError,
    ) as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "subject-purpose-resource authorization cannot pass recovery preflight"
        ) from exc
    try:
        security_audit_port = require_security_audit_port(
            security_audit_port, prior_execution.tenant_id
        )
        security_audit_admission = security_audit_port.record_admission(
            security_request, execution_security_decision
        )
        security_audit_admission = (
            ChongqingFederatedCompensationSecurityAuditAdmission.model_validate(
                security_audit_admission.model_dump(mode="python")
            )
        )
    except Exception as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "immutable security admission audit cannot pass recovery preflight"
        ) from exc

    steps: list[FederatedCompensationRunStep] = []
    validations: list[FederatedProjectionCompensationProviderReceiptValidation] = []
    evidence: list[ChongqingFederatedCompensationRecoveryPositionEvidence] = []
    unknown_resume_attempt_receipt: (
        ChongqingFederatedCompensationUnknownResumeAttemptReceipt | None
    ) = None
    for position in range(unknown_position):
        binding = bindings[position]
        engine = binding.target_engine
        request = request_by_engine[engine]
        receipt = _call_recover(  # Prefix recovery is read-only and never replays a Provider.
            adapter_by_engine[engine], executor_by_engine[engine], request.execution_plan
        )
        outcome = _outcome_from_receipt(binding, receipt)
        stopped_outcome = outcome_by_position[position]
        if (
            stopped_outcome.provider_receipt_sha256 != outcome.provider_receipt_sha256
            or stopped_outcome.status is not outcome.status
        ):
            raise ChongqingFederatedCompensationRecoveryValidationError(
                f"recovered prefix receipt differs from stopped outcome at position {position}"
            )
        validation = _validate_receipt(materialization, binding, receipt)
        steps.append(_step(binding, outcome))
        validations.append(validation)
        values = {
            "position": position,
            "target_engine": engine,
            "action": "prefix_receipt_recovered",
            "outcome_sha256": outcome.outcome_sha256,
            "receipt_validation_sha256": validation.validation_sha256,
            "observation_sha256": None,
            "resume_result_sha256": None,
            "unknown_resume_attempt_receipt_sha256": None,
            "provider_invocation_performed": False,
        }
        evidence.append(
            ChongqingFederatedCompensationRecoveryPositionEvidence(
                **values,
                evidence_sha256=_fingerprint(
                    ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                    values,
                    "evidence_sha256",
                ),
            )
        )

    def _stop_after_unknown_resume(
        outcome: FederatedCompensationProviderOutcome,
        *,
        action: Literal["unknown_operator_required", "unknown_resume_outcome_unknown"],
        provider_invocation_performed: bool | None,
    ) -> ChongqingFederatedCompensationRecoveryResult:
        """Seal a new UNKNOWN result without touching the remaining suffix."""

        steps.append(_step(bindings[unknown_position], outcome))
        values = {
            "position": unknown_position,
            "target_engine": unknown_engine,
            "action": action,
            "outcome_sha256": outcome.outcome_sha256,
            "receipt_validation_sha256": None,
            "observation_sha256": safe_observation.observation_sha256,
            "resume_result_sha256": None,
            "unknown_resume_attempt_receipt_sha256": (
                None
                if unknown_resume_attempt_receipt is None
                else unknown_resume_attempt_receipt.receipt_sha256
            ),
            "provider_invocation_performed": provider_invocation_performed,
        }
        evidence.append(
            ChongqingFederatedCompensationRecoveryPositionEvidence(
                **values,
                evidence_sha256=_fingerprint(
                    ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                    values,
                    "evidence_sha256",
                ),
            )
        )
        return _result(
            prior_execution=prior_execution,
            request_bundle=request_bundle,
            reconciliation_case=reconciliation_case,
            recovered_position=unknown_position,
            run_result=seal_federated_compensation_run_result(bindings, tuple(steps)),
            position_evidence=tuple(evidence),
            receipt_set=None,
            recovered_execution=None,
            execution_security_decision=execution_security_decision,
            security_audit_admission=security_audit_admission,
            security_audit_port=security_audit_port,
            unknown_resume_attempt_receipt=unknown_resume_attempt_receipt,
        )

    if safe_observation.decision == "provider_commit_confirmed_from_persisted_receipt":
        if (
            safe_observation.recovered_receipt is None
            or safe_observation.reconciled_provider_outcome is None
        ):
            raise ChongqingFederatedCompensationRecoveryValidationError(
                "confirmed unknown observation lacks receipt evidence"
            )
        receipt = safe_observation.recovered_receipt
        outcome = safe_observation.reconciled_provider_outcome
        recovered_outcome = _outcome_from_receipt(bindings[unknown_position], receipt)
        if (
            outcome.provider_receipt_sha256 != recovered_outcome.provider_receipt_sha256
            or outcome.status is not FederatedCompensationProviderOutcomeStatus.COMMITTED
        ):
            raise ChongqingFederatedCompensationRecoveryValidationError(
                "confirmed unknown observation outcome differs from its receipt"
            )
        validation = _validate_receipt(materialization, bindings[unknown_position], receipt)
        steps.append(_step(bindings[unknown_position], outcome))
        validations.append(validation)
        action = "unknown_commit_confirmed"
        resume_hash = None
        invoked = False
    elif safe_observation.decision == "provider_not_committed_safe_to_resume":
        if (
            getattr(attempt_authority, "tenant_id", None) != prior_execution.tenant_id
            or not callable(getattr(attempt_authority, "consume", None))
        ):
            raise ChongqingFederatedCompensationRecoveryConfigurationError(
                "recovery requires a tenant-bound durable attempt authority"
            )
        try:
            attempt_request = (
                build_chongqing_federated_compensation_unknown_resume_attempt_request(
                    tenant_id=prior_execution.tenant_id,
                    run_id=prior_execution.run_id,
                    prior_execution_result_sha256=prior_execution.result_sha256,
                    reconciliation_case_sha256=reconciliation_case.case_sha256,
                    request_bundle_sha256=request_bundle.request_bundle_sha256,
                    action_map_sha256=action_map.action_map_sha256,
                    action_execution_binding_sha256=action_binding.binding_sha256,
                    position=unknown_position,
                    target_engine=unknown_engine,
                    request_sha256=unknown_request.request_sha256,
                    unknown_outcome_sha256=unknown_items[0].outcome_sha256,
                    observation_sha256=safe_observation.observation_sha256,
                    attempt_id=attempt_id or uuid4(),
                    consumed_by=reconciled_by,
                    requested_at=resumed_at,
                )
            )
            unknown_resume_attempt_receipt = (
                ChongqingFederatedCompensationUnknownResumeAttemptReceipt.model_validate(
                    attempt_authority.consume(attempt_request).model_dump(mode="python")
                )
            )
        except Exception as exc:
            raise ChongqingFederatedCompensationRecoveryExecutionError(
                "durable unknown-position resume attempt could not be consumed"
            ) from exc
        if unknown_resume_attempt_receipt.request != attempt_request:
            raise ChongqingFederatedCompensationRecoveryExecutionError(
                "durable unknown-position resume attempt evidence drifted"
            )
        try:
            resumed = unknown_adapter.resume_unknown(
                unknown_request,
                reconciliation_case,
                safe_observation,
                executor=unknown_executor,
                resumed_by=reconciled_by,
                resumed_at=resumed_at,
            )
        except ProviderReconciliationConflictError:
            # The wrapper performed a fresh observation and rejected the
            # stale safe-to-resume evidence before invoking the Provider.
            outcome = _stopped_outcome(
                bindings[unknown_position],
                status=FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                error_code="provider_state_changed_before_resume",
            )
            return _stop_after_unknown_resume(
                outcome,
                action="unknown_operator_required",
                provider_invocation_performed=False,
            )
        except Exception as exc:
            # Any other exception may have happened after a Provider mutation
            # was submitted. Preserve uncertainty and stop before the suffix.
            outcome = _stopped_outcome(
                bindings[unknown_position],
                status=FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                error_code=str(exc) or "provider_resume_outcome_unknown",
            )
            return _stop_after_unknown_resume(
                outcome,
                action="unknown_resume_outcome_unknown",
                provider_invocation_performed=None,
            )
        try:
            if not isinstance(resumed, ProviderReconciliationResumeResult):
                raise TypeError("Provider resume wrapper returned an untyped result")
            outcome = resumed.reconciled_provider_outcome
            receipt = resumed.mutation_result.model_dump(mode="python").get("receipt")
            if not isinstance(receipt, BaseModel):
                receipt = getattr(resumed.mutation_result, "receipt", None)
            if not isinstance(receipt, BaseModel):
                raise TypeError("Provider resume result lacks a typed receipt")
            validation = _validate_receipt(materialization, bindings[unknown_position], receipt)
        except Exception as exc:
            outcome = _stopped_outcome(
                bindings[unknown_position],
                status=FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                error_code=str(exc) or "provider_resume_result_unknown",
            )
            return _stop_after_unknown_resume(
                outcome,
                action="unknown_resume_outcome_unknown",
                provider_invocation_performed=None,
            )
        steps.append(_step(bindings[unknown_position], outcome))
        validations.append(validation)
        action = "unknown_position_resumed"
        resume_hash = resumed.result_sha256
        invoked = True
    else:
        unknown_outcome = outcome_by_position[unknown_position]
        steps.append(_step(bindings[unknown_position], unknown_outcome))
        values = {
            "position": unknown_position,
            "target_engine": unknown_engine,
            "action": "unknown_operator_required",
            "outcome_sha256": unknown_outcome.outcome_sha256,
            "receipt_validation_sha256": None,
            "observation_sha256": safe_observation.observation_sha256,
            "resume_result_sha256": None,
            "unknown_resume_attempt_receipt_sha256": None,
            "provider_invocation_performed": False,
        }
        evidence.append(
            ChongqingFederatedCompensationRecoveryPositionEvidence(
                **values,
                evidence_sha256=_fingerprint(
                    ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                    values,
                    "evidence_sha256",
                ),
            )
        )
        run_result = seal_federated_compensation_run_result(bindings, tuple(steps))
        return _result(
            prior_execution=prior_execution,
            request_bundle=request_bundle,
            reconciliation_case=reconciliation_case,
            recovered_position=unknown_position,
            run_result=run_result,
            position_evidence=tuple(evidence),
            receipt_set=None,
            recovered_execution=None,
            execution_security_decision=execution_security_decision,
            security_audit_admission=security_audit_admission,
            security_audit_port=security_audit_port,
            unknown_resume_attempt_receipt=unknown_resume_attempt_receipt,
        )
    values = {
        "position": unknown_position,
        "target_engine": unknown_engine,
        "action": action,
        "outcome_sha256": outcome.outcome_sha256,
        "receipt_validation_sha256": validation.validation_sha256,
        "observation_sha256": safe_observation.observation_sha256,
        "resume_result_sha256": resume_hash,
        "unknown_resume_attempt_receipt_sha256": (
            None
            if unknown_resume_attempt_receipt is None
            else unknown_resume_attempt_receipt.receipt_sha256
        ),
        "provider_invocation_performed": invoked,
    }
    evidence.append(
        ChongqingFederatedCompensationRecoveryPositionEvidence(
            **values,
            evidence_sha256=_fingerprint(
                ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                values,
                "evidence_sha256",
            ),
        )
    )

    native_results: dict[int, BaseModel] = {}
    for position in range(unknown_position + 1, len(bindings)):
        binding = bindings[position]
        engine = binding.target_engine
        try:
            native = registry.invoke_native(binding)
            native_results[position] = native
            outcome = build_federated_compensation_provider_outcome_from_native_result(
                binding, native
            )
        except FederatedCompensationRunProviderUnknownError as exc:
            outcome = _stopped_outcome(
                binding,
                status=FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                error_code=str(exc) or "provider_outcome_unknown",
            )
            steps.append(_step(binding, outcome))
            values = {
                "position": position,
                "target_engine": engine,
                "action": "suffix_provider_stopped_unknown",
                "outcome_sha256": outcome.outcome_sha256,
                "receipt_validation_sha256": None,
                "observation_sha256": None,
                "resume_result_sha256": None,
                "unknown_resume_attempt_receipt_sha256": None,
                "provider_invocation_performed": True,
            }
            evidence.append(
                ChongqingFederatedCompensationRecoveryPositionEvidence(
                    **values,
                    evidence_sha256=_fingerprint(
                        ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                        values,
                        "evidence_sha256",
                    ),
                )
            )
            break
        except FederatedCompensationRunProviderFailureError as exc:
            outcome = _stopped_outcome(
                binding,
                status=FederatedCompensationProviderOutcomeStatus.FAILED,
                error_code=str(exc) or "provider_mutation_failed",
            )
            steps.append(_step(binding, outcome))
            values = {
                "position": position,
                "target_engine": engine,
                "action": "suffix_provider_stopped_failed",
                "outcome_sha256": outcome.outcome_sha256,
                "receipt_validation_sha256": None,
                "observation_sha256": None,
                "resume_result_sha256": None,
                "unknown_resume_attempt_receipt_sha256": None,
                "provider_invocation_performed": True,
            }
            evidence.append(
                ChongqingFederatedCompensationRecoveryPositionEvidence(
                    **values,
                    evidence_sha256=_fingerprint(
                        ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                        values,
                        "evidence_sha256",
                    ),
                )
            )
            break
        except Exception as exc:
            # A transport or adapter exception may have happened after the
            # Provider committed. Preserve the unknown state and stop before
            # touching any later position.
            outcome = _stopped_outcome(
                binding,
                status=FederatedCompensationProviderOutcomeStatus.UNKNOWN,
                error_code=str(exc) or "unclassified_provider_exception",
            )
            steps.append(_step(binding, outcome))
            values = {
                "position": position,
                "target_engine": engine,
                "action": "suffix_provider_stopped_unknown",
                "outcome_sha256": outcome.outcome_sha256,
                "receipt_validation_sha256": None,
                "observation_sha256": None,
                "resume_result_sha256": None,
                "unknown_resume_attempt_receipt_sha256": None,
                "provider_invocation_performed": True,
            }
            evidence.append(
                ChongqingFederatedCompensationRecoveryPositionEvidence(
                    **values,
                    evidence_sha256=_fingerprint(
                        ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                        values,
                        "evidence_sha256",
                    ),
                )
            )
            break
        receipt_value = getattr(native, "receipt", None)
        if not isinstance(receipt_value, BaseModel):
            raise ChongqingFederatedCompensationRecoveryValidationError(
                f"{engine.value} suffix result lacks a typed receipt"
            )
        validation = _validate_receipt(materialization, binding, receipt_value)
        validations.append(validation)
        steps.append(_step(binding, outcome))
        values = {
            "position": position,
            "target_engine": engine,
            "action": "suffix_provider_invoked",
            "outcome_sha256": outcome.outcome_sha256,
            "receipt_validation_sha256": validation.validation_sha256,
            "observation_sha256": None,
            "resume_result_sha256": None,
            "unknown_resume_attempt_receipt_sha256": None,
            "provider_invocation_performed": True,
        }
        evidence.append(
            ChongqingFederatedCompensationRecoveryPositionEvidence(
                **values,
                evidence_sha256=_fingerprint(
                    ChongqingFederatedCompensationRecoveryPositionEvidence.schema_id,
                    values,
                    "evidence_sha256",
                ),
            )
        )
        if outcome.status not in {
            FederatedCompensationProviderOutcomeStatus.COMMITTED,
            FederatedCompensationProviderOutcomeStatus.REPLAYED,
        }:
            break

    run_result = seal_federated_compensation_run_result(bindings, tuple(steps))
    if run_result.state is not FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY:
        return _result(
            prior_execution=prior_execution,
            request_bundle=request_bundle,
            reconciliation_case=reconciliation_case,
            recovered_position=unknown_position,
            run_result=run_result,
            position_evidence=tuple(evidence),
            receipt_set=None,
            recovered_execution=None,
            execution_security_decision=execution_security_decision,
            security_audit_admission=security_audit_admission,
            security_audit_port=security_audit_port,
            unknown_resume_attempt_receipt=unknown_resume_attempt_receipt,
        )
    try:
        receipt_set = build_federated_compensation_provider_receipt_validation_set_from_run(
            intent,
            plan_set,
            materialization,
            run_result,
            tuple(validations),
        )
    except Exception as exc:
        raise ChongqingFederatedCompensationRecoveryValidationError(
            "recovered receipts cannot form a complete federated receipt set"
        ) from exc
    recovered_execution = _complete_execution_result(
        prior_execution,
        request_bundle,
        run_result,
        receipt_set,
    )
    return _result(
        prior_execution=prior_execution,
        request_bundle=request_bundle,
        reconciliation_case=reconciliation_case,
        recovered_position=unknown_position,
        run_result=run_result,
        position_evidence=tuple(evidence),
        receipt_set=receipt_set,
        recovered_execution=recovered_execution,
        execution_security_decision=execution_security_decision,
        security_audit_admission=security_audit_admission,
        security_audit_port=security_audit_port,
        unknown_resume_attempt_receipt=unknown_resume_attempt_receipt,
    )


__all__ = [
    "ChongqingFederatedCompensationProviderRecoveryAdapter",
    "ChongqingFederatedCompensationRecoveryConfigurationError",
    "ChongqingFederatedCompensationRecoveryError",
    "ChongqingFederatedCompensationRecoveryExecutionError",
    "ChongqingFederatedCompensationRecoveryPositionEvidence",
    "ChongqingFederatedCompensationRecoveryResult",
    "ChongqingFederatedCompensationRecoveryState",
    "ChongqingFederatedCompensationRecoveryValidationError",
    "build_chongqing_federated_compensation_provider_recovery_adapters",
    "resume_chongqing_federated_compensation_unknown_position",
]
