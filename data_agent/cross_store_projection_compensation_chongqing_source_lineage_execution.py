"""Execute a Chongqing deployment only after explicit source-lineage preflight.

This is a thin guard around the existing Chongqing deployment executor.  It
rebuilds the selected customer-source lineage from the catalog and deployment
binding before any Provider is called.  It does not grant checkpoint or
completion authority.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceCatalog,
)
from .cross_store_projection_compensation_chongqing_deployment_execution import (
    ChongqingFederatedCompensationDeploymentExecutionResult,
    execute_chongqing_federated_compensation_deployment_with_receipt_set,
)
from .cross_store_projection_compensation_chongqing_internal_execution import (
    ChongqingFederatedCompensationInternalExecutionPermitError,
    _ChongqingFederatedCompensationInternalExecutionPermit,
    _validate_chongqing_federated_compensation_internal_execution_permit,
)
from .cross_store_projection_compensation_chongqing_source_lineage import (
    ChongqingFederatedCompensationSourceLineageError,
    ChongqingFederatedCompensationSourceLineageSet,
    build_chongqing_federated_compensation_source_lineage_set,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
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


class ChongqingFederatedCompensationSourceLineageExecutionError(RuntimeError):
    """A source-lineage-gated Chongqing deployment cannot safely proceed."""


class ChongqingFederatedCompensationSourceLineageExecutionValidationError(
    ChongqingFederatedCompensationSourceLineageExecutionError,
):
    """The sealed customer source lineage differs from the supplied run chain."""


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


class ChongqingFederatedCompensationSourceLineageExecutionResult(_FrozenModel):
    """Run evidence after source-lineage and customer-catalog preflight."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-source-lineage-execution-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_lineage_set_sha256: Sha256
    deployment_execution: ChongqingFederatedCompensationDeploymentExecutionResult
    source_lineage_preflight_performed: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceLineageExecutionResult:
        execution = self.deployment_execution
        if (
            self.tenant_id != execution.tenant_id
            or self.run_id != execution.run_id
            or self.deployment_binding_sha256 != execution.deployment_binding_sha256
            or execution.authority_admission_performed
        ):
            raise ValueError("source lineage execution differs from Chongqing deployment execution")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("source lineage execution fingerprint is invalid")
        return self


def _validated_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ChongqingFederatedCompensationSourceCatalog,
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceLineageSet,
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
            ChongqingFederatedCompensationSourceLineageSet.model_validate(
                source_lineage_set.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceLineageExecutionValidationError(
            "Chongqing source lineage execution input violates a sealed contract"
        ) from exc


def execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    registry: FederatedCompensationProviderInvokerRegistry,
    *,
    execution_permit: (
        _ChongqingFederatedCompensationInternalExecutionPermit | None
    ) = None,
) -> ChongqingFederatedCompensationSourceLineageExecutionResult:
    """Internal primitive; direct calls fail closed without an exact run permit."""

    try:
        _validate_chongqing_federated_compensation_internal_execution_permit(
            execution_permit,
            intent=intent,
            registry=registry,
        )
    except ChongqingFederatedCompensationInternalExecutionPermitError as exc:
        raise ChongqingFederatedCompensationSourceLineageExecutionValidationError(
            "Chongqing source lineage internal execution permit cannot pass preflight"
        ) from exc

    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    ) = _validated_inputs(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        source_lineage_set,
    )
    source_roles_by_position = {
        item.position: tuple(source.source_role for source in item.customer_sources)
        for item in source_lineage_set.items
    }
    try:
        expected_lineage = build_chongqing_federated_compensation_source_lineage_set(
            source_catalog,
            deployment_binding,
            source_roles_by_position,
        )
    except ChongqingFederatedCompensationSourceLineageError as exc:
        raise ChongqingFederatedCompensationSourceLineageExecutionValidationError(
            "Chongqing source lineage cannot pass preflight"
        ) from exc
    if source_lineage_set != expected_lineage:
        raise ChongqingFederatedCompensationSourceLineageExecutionValidationError(
            "Chongqing source lineage differs from current sealed inputs"
        )
    deployment_execution = (
        execute_chongqing_federated_compensation_deployment_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            registry,
            execution_permit=execution_permit,
        )
    )
    values = {
        "tenant_id": source_lineage_set.tenant_id,
        "run_id": source_lineage_set.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_lineage_set_sha256": source_lineage_set.source_lineage_set_sha256,
        "deployment_execution": deployment_execution,
        "source_lineage_preflight_performed": True,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationSourceLineageExecutionResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationSourceLineageExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationSourceLineageExecutionError",
    "ChongqingFederatedCompensationSourceLineageExecutionResult",
    "ChongqingFederatedCompensationSourceLineageExecutionValidationError",
]
