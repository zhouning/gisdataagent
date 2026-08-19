"""Gate one complete five-Provider Chongqing compensation execution.

The existing native invokers keep Provider endpoints, credentials, and payloads
inside their engine-specific executors.  This module adds a hash-only request
bundle proving that the same sealed Chongqing run contains exactly one PostGIS,
pgvector, RDF, object-store, and Lakehouse mutation request before any callback
is invoked.  It does not grant checkpoint or completion authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceCatalog,
)
from .cross_store_projection_compensation_chongqing_execution_security import (
    ChongqingFederatedCompensationExecutionSecurityCurrentReader,
    ChongqingFederatedCompensationExecutionSecurityDecision,
    ChongqingFederatedCompensationExecutionSecurityError,
    authorize_chongqing_federated_compensation_execution_security,
    build_chongqing_federated_compensation_execution_security_request,
    build_chongqing_federated_compensation_execution_security_resource,
    chongqing_execution_subject_ref,
)
from .cross_store_projection_compensation_chongqing_internal_execution import (
    ChongqingFederatedCompensationInternalExecutionPermitError,
    _issue_chongqing_federated_compensation_governed_execution_permit,
)
from .cross_store_projection_compensation_chongqing_security_audit import (
    ChongqingFederatedCompensationSecurityAuditAdmission,
    ChongqingFederatedCompensationSecurityAuditOutcome,
    ChongqingFederatedCompensationSecurityAuditPort,
    require_security_audit_port,
)
from .cross_store_projection_compensation_chongqing_source_lineage import (
    ChongqingFederatedCompensationSourceLineageSet,
)
from .cross_store_projection_compensation_chongqing_source_selection_profile import (
    ChongqingFederatedCompensationProfiledSourceLineageBinding,
    ChongqingFederatedCompensationProfiledSourceLineageExecutionResult,
    ChongqingFederatedCompensationSourceSelectionProfile,
    execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set,
)
from .cross_store_projection_compensation_chongqing_source_selection_profile_release import (
    ChongqingSourceSelectionProfileExecutionReleaseBinding,
    ChongqingSourceSelectionProfileReleaseCurrentReader,
    ChongqingSourceSelectionProfileReleaseError,
    ChongqingSourceSelectionProfileReleaseHistory,
    build_chongqing_source_selection_profile_execution_release_binding,
)
from .cross_store_projection_compensation_customer_action_mapping import (
    CustomerCompensationRuleProviderActionMap,
    CustomerCompensationRuleProviderExecutionBinding,
    CustomerCompensationRuleProviderRequestBindingInput,
    build_customer_compensation_rule_provider_action_map,
    build_customer_compensation_rule_provider_execution_binding,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchError,
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationDispatchRuleCurrentBinding,
    FederatedProjectionCompensationRuleAuthorityCurrentReader,
    build_federated_projection_compensation_dispatch_rule_current_binding,
)
from .cross_store_projection_compensation_federated_receipt_execution import (
    FederatedCompensationRegisteredReceiptExecutionState as RegisteredExecutionState,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunState,
)
from .cross_store_projection_compensation_lakehouse_adapter import (
    FederatedProjectionCompensationLakehouseMutationRequest,
)
from .cross_store_projection_compensation_object_adapter import (
    FederatedProjectionCompensationObjectMutationRequest,
)
from .cross_store_projection_compensation_postgis_adapter import (
    FederatedProjectionCompensationPostGISMutationRequest,
)
from .cross_store_projection_compensation_production_admission import (
    ChongqingFiveProviderProductionAdmissionCurrentReader,
    ChongqingFiveProviderProductionAdmissionEvent,
    ChongqingFiveProviderProductionAdmissionHistory,
    build_chongqing_five_provider_production_admission_target,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_compensation_rdf_adapter import (
    FederatedProjectionCompensationRDFMutationRequest,
)
from .cross_store_projection_compensation_vector_adapter import (
    FederatedProjectionCompensationVectorMutationRequest,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)


class ChongqingFederatedCompensationFiveProviderExecutionError(RuntimeError):
    """A complete five-Provider Chongqing run cannot safely proceed."""


class ChongqingFederatedCompensationFiveProviderExecutionValidationError(
    ChongqingFederatedCompensationFiveProviderExecutionError,
):
    """The five-Provider request bundle differs from the sealed deployment chain."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


FiveProviderMutationRequest: TypeAlias = (
    FederatedProjectionCompensationPostGISMutationRequest
    | FederatedProjectionCompensationVectorMutationRequest
    | FederatedProjectionCompensationRDFMutationRequest
    | FederatedProjectionCompensationObjectMutationRequest
    | FederatedProjectionCompensationLakehouseMutationRequest
)

_REQUEST_TYPES: dict[ProjectionEngine, type[FiveProviderMutationRequest]] = {
    ProjectionEngine.POSTGIS: FederatedProjectionCompensationPostGISMutationRequest,
    ProjectionEngine.VECTOR: FederatedProjectionCompensationVectorMutationRequest,
    ProjectionEngine.RDF: FederatedProjectionCompensationRDFMutationRequest,
    ProjectionEngine.OBJECT_STORE: FederatedProjectionCompensationObjectMutationRequest,
    ProjectionEngine.LAKEHOUSE: FederatedProjectionCompensationLakehouseMutationRequest,
}
_REQUIRED_ENGINES = tuple(sorted(_REQUEST_TYPES, key=lambda engine: engine.value))


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingFederatedCompensationFiveProviderRequestItem(_FrozenModel):
    """Hash-only identity for one native Provider request in the deployment."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-five-provider-request-item.v1"
    position: int = Field(ge=0, le=4)
    target_engine: ProjectionEngine
    projection_id: NonEmptyText
    target_ref: NonEmptyText
    source_plan_sha256: Sha256
    plan_binding_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationFiveProviderRequestItem:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("five-Provider request item fingerprint is invalid")
        return self


class ChongqingFederatedCompensationFiveProviderRequestBundle(_FrozenModel):
    """A complete no-payload request bundle for one Chongqing deployment run."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-five-provider-request-bundle.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    deployment_binding_sha256: Sha256
    items: tuple[ChongqingFederatedCompensationFiveProviderRequestItem, ...] = Field(
        min_length=5,
        max_length=5,
    )
    bundle_state: Literal["complete_five_provider_requests_pending_execution"] = (
        "complete_five_provider_requests_pending_execution"
    )
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_bundle_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationFiveProviderRequestBundle:
        if tuple(item.position for item in self.items) != tuple(range(5)):
            raise ValueError("five-Provider request positions must be contiguous")
        engines = tuple(
            sorted(
                (item.target_engine for item in self.items),
                key=lambda item: item.value,
            )
        )
        if engines != _REQUIRED_ENGINES:
            raise ValueError("five-Provider request bundle must contain every engine exactly once")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_bundle_sha256"}),
            "request_bundle_sha256",
        )
        if self.request_bundle_sha256 != expected:
            raise ValueError("five-Provider request bundle fingerprint is invalid")
        return self


class ChongqingFederatedCompensationFiveProviderExecutionResult(_FrozenModel):
    """Profile-gated five-Provider execution evidence before authority admission."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-five-provider-execution-result.v8"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    request_bundle_sha256: Sha256
    profiled_execution: ChongqingFederatedCompensationProfiledSourceLineageExecutionResult
    profile_execution_release_binding: ChongqingSourceSelectionProfileExecutionReleaseBinding
    customer_rule_current_binding: FederatedProjectionCompensationDispatchRuleCurrentBinding
    customer_provider_action_map: CustomerCompensationRuleProviderActionMap
    customer_provider_action_execution_binding: (
        CustomerCompensationRuleProviderExecutionBinding
    )
    production_admission_event: ChongqingFiveProviderProductionAdmissionEvent
    execution_security_decision: (
        ChongqingFederatedCompensationExecutionSecurityDecision
    )
    security_audit_admission: ChongqingFederatedCompensationSecurityAuditAdmission
    security_audit_outcome: ChongqingFederatedCompensationSecurityAuditOutcome
    request_bundle_items: tuple[
        ChongqingFederatedCompensationFiveProviderRequestItem, ...
    ] = Field(min_length=5, max_length=5)
    five_provider_preflight_performed: Literal[True] = True
    profile_release_preflight_performed: Literal[True] = True
    profile_release_authority_live_read_performed: Literal[True] = True
    customer_rule_current_preflight_performed: Literal[True] = True
    customer_rule_authority_live_read_performed: Literal[True] = True
    customer_action_mapping_preflight_performed: Literal[True] = True
    production_admission_preflight_performed: Literal[True] = True
    production_admission_authority_live_read_performed: Literal[True] = True
    subject_purpose_resource_preflight_performed: Literal[True] = True
    execution_security_authority_live_read_performed: Literal[True] = True
    production_execution_authorized: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationFiveProviderExecutionResult:
        action_map = self.customer_provider_action_map
        action_binding = self.customer_provider_action_execution_binding
        bundle_items_by_position = {
            item.position: item for item in self.request_bundle_items
        }
        action_binding_items_by_position = {
            item.position: item for item in action_binding.items
        }
        action_map_items_by_position = {
            item.position: item for item in action_map.items
        }
        security_request = self.execution_security_decision.request
        security_resources_by_position = {
            item.position: item for item in security_request.resources
        }
        approved_action_rule = next(
            (
                rule
                for rule in self.customer_rule_current_binding.approved_rules
                if rule.contract_sha256
                == action_binding.customer_rule_contract_sha256
            ),
            None,
        )
        if (
            self.tenant_id != self.profiled_execution.tenant_id
            or self.run_id != self.profiled_execution.run_id
            or self.profiled_execution.authority_admission_performed
            or self.profile_execution_release_binding.tenant_id != self.tenant_id
            or self.profile_execution_release_binding.run_id != self.run_id
            or self.profile_execution_release_binding.source_selection_profile_sha256
            != self.profiled_execution.source_selection_profile_sha256
            or self.profile_execution_release_binding.profiled_source_lineage_binding_sha256
            != self.profiled_execution.profiled_source_lineage_binding_sha256
            or self.customer_rule_current_binding.tenant_id != self.tenant_id
            or self.customer_rule_current_binding.run_id != self.run_id
            or action_binding.tenant_id != self.tenant_id
            or action_binding.run_id != self.run_id
            or action_binding.dispatch_intent_sha256
            != self.customer_rule_current_binding.dispatch_intent_sha256
            or action_binding.customer_rule_current_binding_sha256
            != self.customer_rule_current_binding.rule_current_binding_sha256
            or action_binding.request_bundle_sha256 != self.request_bundle_sha256
            or not (
                action_binding.customer_action_mapping_preflight_performed
            )
            or action_binding.production_execution_authorized
            or approved_action_rule is None
            or approved_action_rule.approval_artifact_sha256
            != action_binding.customer_approval_artifact_sha256
            or self.production_admission_event.tenant_id != self.tenant_id
            or self.production_admission_event.run_id != self.run_id
            or self.production_admission_event.admission_state != "active"
            or not self.production_admission_event.production_execution_authorized
            or self.execution_security_decision.effect != "allow"
            or self.execution_security_decision.obligations
            or self.security_audit_admission.tenant_id != self.tenant_id
            or self.security_audit_admission.run_id != self.run_id
            or self.security_audit_admission.operation
            != "chongqing.five_provider.execute"
            or self.security_audit_admission.request_sha256
            != security_request.request_sha256
            or self.security_audit_admission.decision_sha256
            != self.execution_security_decision.decision_sha256
            or self.security_audit_outcome.tenant_id != self.tenant_id
            or self.security_audit_outcome.run_id != self.run_id
            or self.security_audit_outcome.operation
            != "chongqing.five_provider.execute"
            or self.security_audit_outcome.admission_sha256
            != self.security_audit_admission.admission_sha256
            or (
                self.security_audit_outcome.outcome == "success"
                and (
                    self.security_audit_outcome.evidence_sha256
                    != self.request_bundle_sha256
                    or self.security_audit_outcome.provider_invocations != 5
                )
            )
            or security_request.tenant_id != self.tenant_id
            or security_request.run_id != self.run_id
            or security_request.operation != "chongqing.five_provider.execute"
            or security_request.request_bundle_sha256 != self.request_bundle_sha256
            or security_request.action_map_sha256 != action_map.action_map_sha256
            or security_request.action_execution_binding_sha256
            != action_binding.binding_sha256
            or security_request.production_admission_event_sha256
            != self.production_admission_event.event_sha256
            or self.production_admission_event.target.request_bundle_sha256
            != self.request_bundle_sha256
            or self.production_admission_event.target.rule_current_binding_sha256
            != self.customer_rule_current_binding.rule_current_binding_sha256
            or action_binding.customer_rule_contract_sha256
            not in self.production_admission_event.target.approved_rule_contract_sha256s
            or action_map.tenant_id != self.tenant_id
            or action_map.run_id != self.run_id
            or action_map.proposal_sha256
            != self.production_admission_event.target.proposal_sha256
            or action_map.candidate_sha256
            != self.production_admission_event.target.candidate_sha256
            or action_map.action_map_sha256 != action_binding.action_map_sha256
            or tuple(bundle_items_by_position)
            != tuple(range(len(self.request_bundle_items)))
            or tuple(action_binding_items_by_position)
            != tuple(range(len(self.request_bundle_items)))
            or tuple(action_map_items_by_position)
            != tuple(range(len(self.request_bundle_items)))
            or tuple(security_resources_by_position)
            != tuple(range(len(self.request_bundle_items)))
            or any(
                bundle_items_by_position[position].request_sha256
                != action_binding_items_by_position[position].request_sha256
                for position in range(len(self.request_bundle_items))
            )
            or any(
                bundle_items_by_position[position].target_engine
                != action_binding_items_by_position[position].target_engine
                or bundle_items_by_position[position].projection_id
                != action_binding_items_by_position[position].projection_id
                or bundle_items_by_position[position].target_ref
                != action_binding_items_by_position[position].target_ref
                or bundle_items_by_position[position].source_plan_sha256
                != action_binding_items_by_position[position].source_plan_sha256
                or bundle_items_by_position[position].plan_binding_sha256
                != action_binding_items_by_position[position].plan_binding_sha256
                or bundle_items_by_position[position].materialization_binding_sha256
                != action_binding_items_by_position[position].materialization_binding_sha256
                or bundle_items_by_position[position].provider_plan_sha256
                != action_binding_items_by_position[position].provider_plan_sha256
                or bundle_items_by_position[position].provider_idempotency_key
                != action_binding_items_by_position[position].provider_idempotency_key
                or bundle_items_by_position[position].execution_plan_sha256
                != action_binding_items_by_position[position].execution_plan_sha256
                for position in range(len(self.request_bundle_items))
            )
            or any(
                action_map_items_by_position[position].item_sha256
                != action_binding_items_by_position[position].action_map_item_sha256
                for position in range(len(self.request_bundle_items))
            )
            or any(
                action_map_items_by_position[position].plan_sha256
                != action_binding_items_by_position[position].source_plan_sha256
                or action_map_items_by_position[position].target_engine
                != action_binding_items_by_position[position].target_engine
                or action_map_items_by_position[position].target_ref
                != action_binding_items_by_position[position].target_ref
                or action_map_items_by_position[position].provider_action
                != action_binding_items_by_position[position].provider_action
                for position in range(len(self.request_bundle_items))
            )
            or any(
                security_resources_by_position[position].target_engine
                != action_binding_items_by_position[position].target_engine
                or security_resources_by_position[position].target_ref
                != action_binding_items_by_position[position].target_ref
                or security_resources_by_position[position].provider_action
                != action_binding_items_by_position[position].provider_action
                or security_resources_by_position[position].request_sha256
                != action_binding_items_by_position[position].request_sha256
                or security_resources_by_position[position].action_map_item_sha256
                != action_binding_items_by_position[position].action_map_item_sha256
                or security_resources_by_position[
                    position
                ].action_execution_binding_item_sha256
                != action_binding_items_by_position[position].item_sha256
                or security_resources_by_position[position].access_mode != "mutate"
                for position in range(len(self.request_bundle_items))
            )
            or action_binding.plan_set_sha256
            != self.production_admission_event.target.plan_set_sha256
            or action_binding.materialization_set_sha256
            != self.production_admission_event.target.materialization_set_sha256
            or action_binding.dispatch_intent_sha256
            != self.production_admission_event.target.dispatch_intent_sha256
        ):
            raise ValueError("five-Provider result differs from profiled execution")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("five-Provider execution result fingerprint is invalid")
        return self


def _validated_chain(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
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
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider execution chain violates a sealed contract"
        ) from exc


def _validated_requests(
    requests: Mapping[ProjectionEngine, FiveProviderMutationRequest],
) -> dict[ProjectionEngine, FiveProviderMutationRequest]:
    if not isinstance(requests, Mapping):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider requests must be supplied as an engine mapping"
        )
    try:
        normalized_keys = tuple(
            sorted(
                (ProjectionEngine(engine) for engine in requests),
                key=lambda engine: engine.value,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider request mapping contains an unsupported engine"
        ) from exc
    if normalized_keys != _REQUIRED_ENGINES or len(requests) != 5:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider request mapping must contain every engine exactly once"
        )
    validated: dict[ProjectionEngine, FiveProviderMutationRequest] = {}
    for raw_engine, request in requests.items():
        engine = ProjectionEngine(raw_engine)
        request_type = _REQUEST_TYPES[engine]
        if not isinstance(request, request_type):
            raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
                f"{engine.value} request uses the wrong native request contract"
            )
        try:
            validated[engine] = request_type.model_validate(request.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
                f"{engine.value} request violates its sealed contract"
            ) from exc
    return validated


def build_chongqing_federated_compensation_five_provider_request_bundle(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    requests: Mapping[ProjectionEngine, FiveProviderMutationRequest],
) -> ChongqingFederatedCompensationFiveProviderRequestBundle:
    """Bind exactly five native mutation requests to one sealed Chongqing chain."""

    intent, plan_set, materialization, deployment_binding = _validated_chain(
        intent,
        plan_set,
        materialization,
        deployment_binding,
    )
    requests = _validated_requests(requests)
    if (
        len(intent.plan_bindings) != 5
        or len(plan_set.plan_bindings) != 5
        or len(materialization.bindings) != 5
        or len(deployment_binding.items) != 5
        or deployment_binding.tenant_id != intent.tenant_id
        or deployment_binding.run_id != intent.run_id
        or deployment_binding.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or deployment_binding.plan_set_sha256 != plan_set.plan_set_sha256
        or deployment_binding.materialization_set_sha256
        != materialization.materialization_set_sha256
    ):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider deployment chain is incomplete or inconsistent"
        )
    plan_by_position = {item.position: item for item in plan_set.plan_bindings}
    materialized_by_position = {item.position: item for item in materialization.bindings}
    deployed_by_position = {item.position: item for item in deployment_binding.items}
    request_by_position = {
        request.execution_plan.position: (engine, request) for engine, request in requests.items()
    }
    if any(
        len(values) != 5
        for values in (
            plan_by_position,
            materialized_by_position,
            deployed_by_position,
            request_by_position,
        )
    ) or set(request_by_position) != set(range(5)):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider positions are incomplete or duplicated"
        )

    items: list[ChongqingFederatedCompensationFiveProviderRequestItem] = []
    for position in range(5):
        plan_binding = plan_by_position[position]
        materialized = materialized_by_position[position]
        deployed = deployed_by_position[position]
        engine, request = request_by_position[position]
        execution_plan = request.execution_plan
        source_plan = execution_plan.source_plan
        if (
            request.tenant_id != intent.tenant_id
            or request.run_id != intent.run_id
            or engine is not plan_binding.target_engine
            or engine is not materialized.target_engine
            or engine is not deployed.target_engine
            or engine is not source_plan.target_engine
            or source_plan.target_ref != plan_binding.target_ref
            or execution_plan.dispatch_intent_sha256 != intent.dispatch_intent_sha256
            or execution_plan.plan_set_sha256 != plan_set.plan_set_sha256
            or execution_plan.materialization_set_sha256
            != materialization.materialization_set_sha256
            or execution_plan.plan_binding_sha256 != plan_binding.plan_binding_sha256
            or execution_plan.materialization_binding_sha256
            != materialized.materialization_binding_sha256
            or execution_plan.provider_plan_sha256 != materialized.provider_plan_sha256
            or execution_plan.provider_idempotency_key != materialized.provider_idempotency_key
            or source_plan.plan_sha256 != plan_binding.source_plan_sha256
            or deployed.source_plan_sha256 != source_plan.plan_sha256
        ):
            raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
                f"five-Provider request at position {position} differs from deployment"
            )
        item_values = {
            "position": position,
            "target_engine": engine,
            "projection_id": source_plan.projection_id,
            "target_ref": source_plan.target_ref,
            "source_plan_sha256": source_plan.plan_sha256,
            "plan_binding_sha256": plan_binding.plan_binding_sha256,
            "materialization_binding_sha256": materialized.materialization_binding_sha256,
            "provider_plan_sha256": materialized.provider_plan_sha256,
            "provider_idempotency_key": materialized.provider_idempotency_key,
            "request_sha256": request.request_sha256,
            "execution_plan_sha256": execution_plan.execution_plan_sha256,
        }
        items.append(
            ChongqingFederatedCompensationFiveProviderRequestItem(
                **item_values,
                item_sha256=_fingerprint(
                    ChongqingFederatedCompensationFiveProviderRequestItem.schema_id,
                    item_values,
                    "item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "items": tuple(items),
        "bundle_state": "complete_five_provider_requests_pending_execution",
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationFiveProviderRequestBundle(
        **values,
        request_bundle_sha256=_fingerprint(
            ChongqingFederatedCompensationFiveProviderRequestBundle.schema_id,
            values,
            "request_bundle_sha256",
        ),
    )


def execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    profile_release_history: ChongqingSourceSelectionProfileReleaseHistory,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    profiled_source_lineage_binding: ChongqingFederatedCompensationProfiledSourceLineageBinding,
    profile_execution_release_binding: ChongqingSourceSelectionProfileExecutionReleaseBinding,
    request_bundle: ChongqingFederatedCompensationFiveProviderRequestBundle,
    requests: Mapping[ProjectionEngine, FiveProviderMutationRequest],
    registry: FederatedCompensationProviderInvokerRegistry,
    *,
    profile_release_reader: ChongqingSourceSelectionProfileReleaseCurrentReader,
    rule_authority_reader: FederatedProjectionCompensationRuleAuthorityCurrentReader,
    customer_rule_current_binding: FederatedProjectionCompensationDispatchRuleCurrentBinding,
    production_admission_history: ChongqingFiveProviderProductionAdmissionHistory,
    production_admission_reader: ChongqingFiveProviderProductionAdmissionCurrentReader,
    subject_context: SubjectContext,
    execution_security_reader: (
        ChongqingFederatedCompensationExecutionSecurityCurrentReader
    ),
    security_audit_port: ChongqingFederatedCompensationSecurityAuditPort,
    production_admission_evaluated_at: datetime | None = None,
) -> ChongqingFederatedCompensationFiveProviderExecutionResult:
    """Require live release, rule, admission, and SPR policy before callbacks."""

    try:
        request_bundle = ChongqingFederatedCompensationFiveProviderRequestBundle.model_validate(
            request_bundle.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider request bundle violates its sealed contract"
        ) from exc
    expected = build_chongqing_federated_compensation_five_provider_request_bundle(
        intent,
        plan_set,
        materialization,
        deployment_binding,
        requests,
    )
    if request_bundle != expected:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider request bundle differs from current sealed inputs"
        )
    try:
        profile_execution_release_binding = (
            ChongqingSourceSelectionProfileExecutionReleaseBinding.model_validate(
                profile_execution_release_binding.model_dump(mode="python")
            )
        )
        expected_release_binding = (
            build_chongqing_source_selection_profile_execution_release_binding(
                profile_release_history,
                profile,
                deployment_binding,
                profiled_source_lineage_binding,
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        ValidationError,
        ChongqingSourceSelectionProfileReleaseError,
    ) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "active source-selection profile release cannot pass execution preflight"
        ) from exc
    if profile_execution_release_binding != expected_release_binding:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "active source-selection profile release binding differs from current inputs"
        )
    try:
        if (
            getattr(profile_release_reader, "tenant_id", None) != intent.tenant_id
            or not callable(
                getattr(profile_release_reader, "release_history_current", None)
            )
        ):
            raise ValueError("profile release reader is not tenant-bound")
        live_profile_release_history = profile_release_reader.release_history_current(
            profile_release_history.profile_id,
            profile_release_history.scenario_id,
        )
        if live_profile_release_history is None:
            raise ValueError("profile release current history was not found")
    except Exception as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "profile release authority live current read cannot pass execution preflight"
        ) from exc
    try:
        live_profile_release_history = (
            ChongqingSourceSelectionProfileReleaseHistory.model_validate(
                live_profile_release_history.model_dump(mode="python")
            )
        )
        live_release_binding = (
            build_chongqing_source_selection_profile_execution_release_binding(
                live_profile_release_history,
                profile,
                deployment_binding,
                profiled_source_lineage_binding,
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        ValidationError,
        ChongqingSourceSelectionProfileReleaseError,
    ) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "profile release authority current cannot pass execution preflight"
        ) from exc
    if (
        live_profile_release_history != profile_release_history
        or live_release_binding != profile_execution_release_binding
    ):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "profile release binding differs from current authority history"
        )
    try:
        if (
            getattr(rule_authority_reader, "tenant_id", None) != intent.tenant_id
            or not callable(
                getattr(rule_authority_reader, "assessment_evidence_current", None)
            )
        ):
            raise ValueError("rule authority reader is not tenant-bound")
        live_rule_authority_evidence = (
            rule_authority_reader.assessment_evidence_current(intent.run_id)
        )
        if live_rule_authority_evidence is None:
            raise ValueError("rule authority current evidence was not found")
    except Exception as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "customer-rule authority live current read cannot pass execution preflight"
        ) from exc
    try:
        customer_rule_current_binding = (
            FederatedProjectionCompensationDispatchRuleCurrentBinding.model_validate(
                customer_rule_current_binding.model_dump(mode="python")
            )
        )
        expected_rule_current_binding = (
            build_federated_projection_compensation_dispatch_rule_current_binding(
                live_rule_authority_evidence,
                intent,
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        ValidationError,
        FederatedProjectionCompensationDispatchError,
    ) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "customer-rule authority current cannot pass execution preflight"
        ) from exc
    if customer_rule_current_binding != expected_rule_current_binding:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "customer-rule current binding differs from current authority evidence"
        )
    try:
        rule_contract = next(
            contract
            for contract in live_rule_authority_evidence.current_rules
            if contract.rule.action is intent.candidate_action
        )
        customer_action_map = build_customer_compensation_rule_provider_action_map(
            live_rule_authority_evidence.proposal,
            intent.candidate_sha256,
            rule_contract.rule,
        )
        customer_provider_action_execution_binding = (
            build_customer_compensation_rule_provider_execution_binding(
                customer_action_map,
                rule_contract,
                expected_rule_current_binding,
                intent,
                plan_set,
                materialization,
                tuple(
                    CustomerCompensationRuleProviderRequestBindingInput(
                        position=request.execution_plan.position,
                        target_engine=engine,
                        target_ref=request.execution_plan.source_plan.target_ref,
                        provider_action=request.execution_plan.source_plan.action,
                        request_sha256=request.request_sha256,
                        execution_plan_sha256=request.execution_plan.execution_plan_sha256,
                    )
                    for engine, request in sorted(
                        requests.items(),
                        key=lambda item: item[1].execution_plan.position,
                    )
                ),
                request_bundle_sha256=request_bundle.request_bundle_sha256,
            )
        )
    except (
        AttributeError,
        StopIteration,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "customer-approved Provider action mapping cannot pass execution preflight"
        ) from exc
    try:
        if (
            getattr(production_admission_reader, "tenant_id", None)
            != intent.tenant_id
            or not callable(
                getattr(
                    production_admission_reader,
                    "admission_history_current",
                    None,
                )
            )
        ):
            raise ValueError("production admission reader is not tenant-bound")
        live_production_admission_history = (
            production_admission_reader.admission_history_current(intent.run_id)
        )
        if live_production_admission_history is None:
            raise ValueError("production admission current history was not found")
    except Exception as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission authority live current read cannot pass execution preflight"
        ) from exc
    try:
        production_admission_history = (
            ChongqingFiveProviderProductionAdmissionHistory.model_validate(
                production_admission_history.model_dump(mode="python")
            )
        )
        live_production_admission_history = (
            ChongqingFiveProviderProductionAdmissionHistory.model_validate(
                live_production_admission_history.model_dump(mode="python")
            )
        )
        production_admission_evaluated_at = (
            production_admission_evaluated_at or datetime.now(UTC)
        )
        if (
            production_admission_evaluated_at.tzinfo is None
            or production_admission_evaluated_at.utcoffset() is None
        ):
            raise ValueError("production admission evaluation time is not timezone-aware")
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission authority current cannot pass execution preflight"
        ) from exc
    if live_production_admission_history != production_admission_history:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission differs from current authority history"
        )
    try:
        expected_production_admission_target = (
            build_chongqing_five_provider_production_admission_target(
                intent,
                plan_set,
                materialization,
                deployment_binding,
                live_release_binding,
                expected_rule_current_binding,
                request_bundle_sha256=request_bundle.request_bundle_sha256,
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission target cannot pass execution preflight"
        ) from exc
    if (
        live_production_admission_history.current_event.target
        != expected_production_admission_target
    ):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission target differs from current sealed execution"
        )
    if not live_production_admission_history.authorizes(
        expected_production_admission_target,
        evaluated_at=production_admission_evaluated_at,
    ):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "production admission is not active and current"
        )
    if (
        not isinstance(registry, FederatedCompensationProviderInvokerRegistry)
        or registry.engines != _REQUIRED_ENGINES
    ):
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "five-Provider execution requires the complete governed invoker registry"
        )
    try:
        subject_context = SubjectContext.model_validate(
            subject_context.model_dump(mode="python")
        )
        actor_subject = chongqing_execution_subject_ref(subject_context)
        if any(
            getattr(request, "dispatched_by", None) != actor_subject
            for request in requests.values()
        ):
            raise ValueError(
                "execution security subject differs from Provider dispatcher"
            )
        action_items = {
            item.position: item
            for item in customer_provider_action_execution_binding.items
        }
        bundle_items = {item.position: item for item in request_bundle.items}
        security_resources = tuple(
            build_chongqing_federated_compensation_execution_security_resource(
                position=position,
                target_engine=action_items[position].target_engine,
                target_ref=action_items[position].target_ref,
                access_mode="mutate",
                provider_action=action_items[position].provider_action,
                request_sha256=bundle_items[position].request_sha256,
                action_map_item_sha256=(
                    action_items[position].action_map_item_sha256
                ),
                action_execution_binding_item_sha256=(
                    action_items[position].item_sha256
                ),
            )
            for position in range(5)
        )
        security_request = (
            build_chongqing_federated_compensation_execution_security_request(
                tenant_id=intent.tenant_id,
                run_id=intent.run_id,
                subject_context=subject_context,
                operation="chongqing.five_provider.execute",
                request_bundle_sha256=request_bundle.request_bundle_sha256,
                action_map_sha256=customer_action_map.action_map_sha256,
                action_execution_binding_sha256=(
                    customer_provider_action_execution_binding.binding_sha256
                ),
                production_admission_event_sha256=(
                    live_production_admission_history.current_event.event_sha256
                ),
                resources=security_resources,
                evaluated_at=production_admission_evaluated_at,
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
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "subject-purpose-resource authorization cannot pass execution preflight"
        ) from exc
    try:
        security_audit_port = require_security_audit_port(
            security_audit_port, intent.tenant_id
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
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "immutable security admission audit cannot pass execution preflight"
        ) from exc
    try:
        execution_permit = (
            _issue_chongqing_federated_compensation_governed_execution_permit(
                intent=intent,
                registry=registry,
                production_admission_event=(
                    live_production_admission_history.current_event
                ),
                execution_security_decision=execution_security_decision,
                evaluated_at=production_admission_evaluated_at,
            )
        )
    except ChongqingFederatedCompensationInternalExecutionPermitError as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "governed internal execution permit cannot pass execution preflight"
        ) from exc
    profiled_execution = (
        execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            profile,
            source_lineage_set,
            profiled_source_lineage_binding,
            registry,
            execution_permit=execution_permit,
        )
    )
    registered_execution = (
        profiled_execution.source_lineage_execution.deployment_execution.registered_execution
    )
    run_result = registered_execution.run_result
    complete = (
        registered_execution.state
        is RegisteredExecutionState.COMPLETED_RECEIPT_SET_PENDING_AUTHORITY
    )
    audit_outcome = (
        "success"
        if complete
        else (
            "failure"
            if run_result.state
            in {
                FederatedCompensationRunState.FAILED_CLOSED,
                FederatedCompensationRunState.PARTIAL_SUCCESS_PENDING_RECONCILIATION,
            }
            else "unknown"
        )
    )
    audit_evidence = (
        request_bundle.request_bundle_sha256 if complete else run_result.result_sha256
    )
    provider_invocations = 5 if complete else len(run_result.steps)
    try:
        security_audit_outcome = security_audit_port.record_outcome(
            security_audit_admission,
            outcome=audit_outcome,
            evidence_sha256=audit_evidence,
            provider_invocations=provider_invocations,
            recorded_at=datetime.now(UTC),
        )
        security_audit_outcome = (
            ChongqingFederatedCompensationSecurityAuditOutcome.model_validate(
                security_audit_outcome.model_dump(mode="python")
            )
        )
    except Exception as exc:
        raise ChongqingFederatedCompensationFiveProviderExecutionValidationError(
            "immutable security outcome audit cannot be recorded"
        ) from exc
    values = {
        "tenant_id": profiled_execution.tenant_id,
        "run_id": profiled_execution.run_id,
        "request_bundle_sha256": request_bundle.request_bundle_sha256,
        "profiled_execution": profiled_execution,
        "profile_execution_release_binding": profile_execution_release_binding,
        "customer_rule_current_binding": customer_rule_current_binding,
        "customer_provider_action_map": customer_action_map,
        "customer_provider_action_execution_binding": (
            customer_provider_action_execution_binding
        ),
        "production_admission_event": (
            live_production_admission_history.current_event
        ),
        "execution_security_decision": execution_security_decision,
        "security_audit_admission": security_audit_admission,
        "security_audit_outcome": security_audit_outcome,
        "request_bundle_items": request_bundle.items,
        "five_provider_preflight_performed": True,
        "profile_release_preflight_performed": True,
        "profile_release_authority_live_read_performed": True,
        "customer_rule_current_preflight_performed": True,
        "customer_rule_authority_live_read_performed": True,
        "customer_action_mapping_preflight_performed": True,
        "production_admission_preflight_performed": True,
        "production_admission_authority_live_read_performed": True,
        "subject_purpose_resource_preflight_performed": True,
        "execution_security_authority_live_read_performed": True,
        "production_execution_authorized": True,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationFiveProviderExecutionResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationFiveProviderExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationFiveProviderExecutionError",
    "ChongqingFederatedCompensationFiveProviderExecutionResult",
    "ChongqingFederatedCompensationFiveProviderExecutionValidationError",
    "ChongqingFederatedCompensationFiveProviderRequestBundle",
    "ChongqingFederatedCompensationFiveProviderRequestItem",
    "FiveProviderMutationRequest",
    "build_chongqing_federated_compensation_five_provider_request_bundle",
    "execute_chongqing_federated_compensation_profiled_five_provider_with_receipt_set",
]
