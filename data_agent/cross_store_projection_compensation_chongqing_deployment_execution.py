"""Run a registered compensation workflow only after Chongqing deployment preflight.

This module composes the customer catalog/deployment binding with the existing
single-call registered run and receipt-set workflow.  It does not replace any
Provider adapter or authority admission path, and it deliberately retains no
raw customer source data or native receipt documents in its result.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationDeploymentError,
    ChongqingFederatedCompensationSourceCatalog,
    build_chongqing_federated_compensation_deployment_binding,
)
from .cross_store_projection_compensation_chongqing_internal_execution import (
    ChongqingFederatedCompensationInternalExecutionPermitError,
    _ChongqingFederatedCompensationInternalExecutionPermit,
    _validate_chongqing_federated_compensation_internal_execution_permit,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionResult,
    FederatedCompensationRegisteredReceiptExecutionState,
    execute_registered_federated_compensation_run_with_receipt_set,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFederatedCompensationDeploymentExecutionError(RuntimeError):
    """A registered run cannot safely proceed from the Chongqing deployment package."""


class ChongqingFederatedCompensationDeploymentExecutionValidationError(
    ChongqingFederatedCompensationDeploymentExecutionError,
):
    """The customer catalog, deployment binding, or sealed run chain drifted."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingFederatedCompensationDeploymentExecutionResult(_FrozenModel):
    """Run evidence after catalog preflight and before any authority admission."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-deployment-execution-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_catalog_sha256: Sha256
    field_mapping_set_sha256: Sha256
    registered_execution: FederatedCompensationRegisteredReceiptExecutionResult
    state: FederatedCompensationRegisteredReceiptExecutionState
    customer_catalog_preflight_performed: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationDeploymentExecutionResult:
        execution = self.registered_execution
        if (
            self.tenant_id != execution.tenant_id
            or self.run_id != execution.run_id
            or self.state is not execution.state
        ):
            raise ValueError("Chongqing deployment execution differs from registered run")
        if execution.receipt_set_authority_admission_performed:
            raise ValueError("registered run claims receipt-set authority admission")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("Chongqing deployment execution fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ChongqingFederatedCompensationSourceCatalog,
    ChongqingFederatedCompensationDeploymentBinding,
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
            ChongqingFederatedCompensationSourceCatalog.model_validate(
                source_catalog.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationDeploymentExecutionValidationError(
            "Chongqing deployment execution input violates a sealed contract"
        ) from exc


def execute_chongqing_federated_compensation_deployment_with_receipt_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    registry: FederatedCompensationProviderInvokerRegistry,
    *,
    execution_permit: (
        _ChongqingFederatedCompensationInternalExecutionPermit | None
    ) = None,
) -> ChongqingFederatedCompensationDeploymentExecutionResult:
    """Internal primitive; direct calls fail closed without an exact run permit."""

    try:
        _validate_chongqing_federated_compensation_internal_execution_permit(
            execution_permit,
            intent=intent,
            registry=registry,
        )
    except ChongqingFederatedCompensationInternalExecutionPermitError as exc:
        raise ChongqingFederatedCompensationDeploymentExecutionValidationError(
            "Chongqing deployment internal execution permit cannot pass preflight"
        ) from exc

    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
    ) = _validated_inputs(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
    )
    try:
        expected_binding = build_chongqing_federated_compensation_deployment_binding(
            intent,
            plan_set,
            materialization,
            source_catalog,
        )
    except ChongqingFederatedCompensationDeploymentError as exc:
        raise ChongqingFederatedCompensationDeploymentExecutionValidationError(
            "Chongqing deployment cannot pass catalog preflight"
        ) from exc
    if deployment_binding != expected_binding:
        raise ChongqingFederatedCompensationDeploymentExecutionValidationError(
            "Chongqing deployment binding differs from current sealed inputs"
        )
    registered_execution = execute_registered_federated_compensation_run_with_receipt_set(
        intent,
        plan_set,
        materialization,
        registry,
    )
    values = {
        "tenant_id": deployment_binding.tenant_id,
        "run_id": deployment_binding.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_catalog_sha256": source_catalog.source_catalog_sha256,
        "field_mapping_set_sha256": source_catalog.field_mapping_set_sha256,
        "registered_execution": registered_execution,
        "state": registered_execution.state,
        "customer_catalog_preflight_performed": True,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationDeploymentExecutionResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationDeploymentExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationDeploymentExecutionError",
    "ChongqingFederatedCompensationDeploymentExecutionResult",
    "ChongqingFederatedCompensationDeploymentExecutionValidationError",
]
