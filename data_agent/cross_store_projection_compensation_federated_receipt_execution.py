"""Execute one registered federated run and immediately seal its receipt-set candidate.

This orchestration layer keeps native receipt documents in memory only long
enough to validate them against materialization.  It never writes receipt-set,
checkpoint, or completion authority state, and it never retries a Provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunResult,
    FederatedCompensationRunState,
    FederatedCompensationRunValidationError,
    build_federated_compensation_provider_outcome_from_native_result,
    build_federated_compensation_run_bindings,
    execute_federated_compensation_run,
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
    FederatedProjectionCompensationProviderReceiptSetError,
    FederatedProjectionCompensationProviderReceiptValidationSet,
    build_federated_compensation_provider_receipt_validation_set_from_run,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class FederatedCompensationRegisteredReceiptExecutionError(RuntimeError):
    """A native receipt cannot be safely joined to its federated run."""


class FederatedCompensationRegisteredReceiptExecutionValidationError(
    FederatedCompensationRegisteredReceiptExecutionError
):
    """A sealed invocation chain or native receipt is inconsistent."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FederatedCompensationRegisteredReceiptExecutionState(StrEnum):
    COMPLETED_RECEIPT_SET_PENDING_AUTHORITY = (
        "completed_receipt_set_pending_authority"
    )
    RECONCILIATION_OR_OPERATOR_REQUIRED = "reconciliation_or_operator_required"


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
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


class FederatedCompensationRegisteredReceiptExecutionResult(_FrozenModel):
    """Minimal run and receipt-set evidence, always before authority admission."""

    schema_id: ClassVar[str] = (
        "gda.federated-compensation-registered-receipt-execution-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    run_result: FederatedCompensationRunResult
    receipt_validation_set: FederatedProjectionCompensationProviderReceiptValidationSet | None = (
        None
    )
    state: FederatedCompensationRegisteredReceiptExecutionState
    native_receipts_validated: bool
    receipt_set_authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> FederatedCompensationRegisteredReceiptExecutionResult:
        if self.tenant_id != self.run_result.tenant_id or self.run_id != self.run_result.run_id:
            raise ValueError("registered receipt execution identity differs from run")
        if self.state is (
            FederatedCompensationRegisteredReceiptExecutionState
            .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
        ):
            if (
                self.run_result.state
                is not FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY
                or self.receipt_validation_set is None
                or not self.native_receipts_validated
            ):
                raise ValueError("completed registered execution lacks validated receipt set")
            if (
                self.receipt_validation_set.tenant_id != self.tenant_id
                or self.receipt_validation_set.run_id != self.run_id
                or not self.receipt_validation_set.provider_receipts_complete
            ):
                raise ValueError("registered receipt set differs from completed run")
        elif (
            self.state
            is FederatedCompensationRegisteredReceiptExecutionState
            .RECONCILIATION_OR_OPERATOR_REQUIRED
        ) and (
            self.run_result.state
            not in {
                FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION,
                FederatedCompensationRunState.UNKNOWN_PENDING_RECONCILIATION,
                FederatedCompensationRunState.FAILED_CLOSED,
            }
            or self.receipt_validation_set is not None
            or self.native_receipts_validated
        ):
            raise ValueError("incomplete registered execution contains receipt-set evidence")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("registered receipt execution fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
]:
    try:
        return (
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "registered receipt execution input violates its sealed contract"
        ) from exc


def _receipt_document_from_native_result(native_result: BaseModel) -> dict[str, Any]:
    try:
        values = native_result.model_dump(mode="python")
    except (AttributeError, TypeError, ValueError) as exc:
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "native Provider result cannot expose a structured receipt"
        ) from exc
    receipt = values.get("receipt")
    if isinstance(receipt, BaseModel):
        return receipt.model_dump(mode="json")
    if isinstance(receipt, Mapping):
        return dict(receipt)
    raise FederatedCompensationRegisteredReceiptExecutionValidationError(
        "native Provider result does not contain a structured receipt"
    )


def _result(
    *,
    run_result: FederatedCompensationRunResult,
    receipt_validation_set: FederatedProjectionCompensationProviderReceiptValidationSet | None,
) -> FederatedCompensationRegisteredReceiptExecutionResult:
    completed = receipt_validation_set is not None
    values = {
        "tenant_id": run_result.tenant_id,
        "run_id": run_result.run_id,
        "run_result": run_result,
        "receipt_validation_set": receipt_validation_set,
        "state": (
            FederatedCompensationRegisteredReceiptExecutionState
            .COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
            if completed
            else FederatedCompensationRegisteredReceiptExecutionState
            .RECONCILIATION_OR_OPERATOR_REQUIRED
        ),
        "native_receipts_validated": completed,
        "receipt_set_authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return FederatedCompensationRegisteredReceiptExecutionResult(
        **values,
        result_sha256=_fingerprint(
            FederatedCompensationRegisteredReceiptExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


def execute_registered_federated_compensation_run_with_receipt_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    registry: FederatedCompensationProviderInvokerRegistry,
) -> FederatedCompensationRegisteredReceiptExecutionResult:
    """Run registered Providers once and validate their receipts in the same process.

    Native result objects are retained only during this call.  Any partial,
    failed, or unknown run returns without a receipt-set candidate so a later
    reconciliation path cannot mistake it for authority-admissible success.
    """

    if not isinstance(registry, FederatedCompensationProviderInvokerRegistry):
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "registered receipt execution requires the governed Provider registry"
        )
    intent, plan_set, materialization = _validated_inputs(
        intent,
        plan_set,
        materialization,
    )
    try:
        bindings = build_federated_compensation_run_bindings(plan_set, materialization)
    except FederatedCompensationRunValidationError as exc:
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "registered receipt execution binding chain is invalid"
        ) from exc
    native_results: dict[int, BaseModel] = {}

    def invoke(binding):
        native_result = registry.invoke_native(binding)
        native_results[binding.position] = native_result
        return build_federated_compensation_provider_outcome_from_native_result(
            binding,
            native_result,
        )

    run_result = execute_federated_compensation_run(bindings, invoke)
    if run_result.state is not FederatedCompensationRunState.COMPLETED_PENDING_AUTHORITY:
        return _result(run_result=run_result, receipt_validation_set=None)
    if set(native_results) != set(run_result.expected_positions):
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "completed federated run lacks a native result at one or more positions"
        )
    validations: list[FederatedProjectionCompensationProviderReceiptValidation] = []
    materialization_by_position = {
        binding.position: binding for binding in materialization.bindings
    }
    try:
        for binding in bindings:
            materialized = materialization_by_position.get(binding.position)
            if materialized is None:
                raise FederatedCompensationRegisteredReceiptExecutionValidationError(
                    "completed federated run position lacks materialization"
                )
            receipt_document = _receipt_document_from_native_result(
                native_results[binding.position]
            )
            candidate = build_federated_compensation_provider_receipt_candidate(
                materialization,
                materialized,
                receipt_document,
            )
            validations.append(
                validate_federated_compensation_provider_receipt_candidate(
                    materialization,
                    candidate,
                )
            )
        receipt_validation_set = (
            build_federated_compensation_provider_receipt_validation_set_from_run(
                intent,
                plan_set,
                materialization,
                run_result,
                tuple(validations),
            )
        )
    except (
        FederatedProjectionCompensationProviderReceiptValidationError,
        FederatedProjectionCompensationProviderReceiptSetError,
    ) as exc:
        raise FederatedCompensationRegisteredReceiptExecutionValidationError(
            "native Provider receipts cannot form a federated receipt-set candidate"
        ) from exc
    return _result(
        run_result=run_result,
        receipt_validation_set=receipt_validation_set,
    )


__all__ = [
    "FederatedCompensationRegisteredReceiptExecutionError",
    "FederatedCompensationRegisteredReceiptExecutionResult",
    "FederatedCompensationRegisteredReceiptExecutionState",
    "FederatedCompensationRegisteredReceiptExecutionValidationError",
    "execute_registered_federated_compensation_run_with_receipt_set",
]
