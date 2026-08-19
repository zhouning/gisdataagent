"""Customer-signed mapping from one compensation action to Provider work.

The map is a proposal-specific approval artifact. Its fingerprint is signed as
the existing customer rule approval artifact hash, so Provider operations and
unknown-outcome handling are not inferred later by a deployment adapter.
Building the map never selects a candidate or invokes a Provider.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationDispatchRuleCurrentBinding,
)
from .cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
    FederatedProjectionCompensationProposal,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_compensation_rule_contract import (
    RULE_ID_BY_ACTION,
    CustomerCompensationRule,
    CustomerCompensationRuleContract,
    CustomerCompensationRuleStatus,
    CustomerRuleId,
    SemanticVersion,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class CustomerCompensationRuleProviderActionMappingError(ValueError):
    """A customer rule cannot be mapped to the sealed candidate plans."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class CustomerCompensationRuleProviderActionMapItem(_FrozenModel):
    """One exact customer-approved Provider operation and recovery policy."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-provider-action-map-item.v1"
    )
    position: int = Field(ge=0, le=31)
    plan_sha256: Sha256
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    unknown_outcome_policy: Literal[
        "observe_receipt_and_target_then_resume_if_safe"
    ] = "observe_receipt_and_target_then_resume_if_safe"
    committed_prefix_replay_allowed: Literal[False] = False
    unknown_position_resume_attempt_limit: Literal[1] = 1
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> CustomerCompensationRuleProviderActionMapItem:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("customer Provider action map item fingerprint is invalid")
        return self


class CustomerCompensationRuleProviderActionMap(_FrozenModel):
    """Exact Provider action map covered by one customer approval artifact."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-provider-action-map.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    source_snapshot_sha256: Sha256
    candidate_sha256: Sha256
    candidate_action: CompensationProposalAction
    candidate_scope: Literal["blocked_plan", "committed_prefix", "federated_run"]
    customer_rule_id: CustomerRuleId
    customer_rule_semantic_version: SemanticVersion
    customer_rule_sha256: Sha256
    items: tuple[CustomerCompensationRuleProviderActionMapItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    mapping_state: Literal[
        "customer_signed_provider_actions_pending_governed_execution"
    ] = "customer_signed_provider_actions_pending_governed_execution"
    customer_approval_artifact_must_equal_action_map: Literal[True] = True
    production_execution_authorized: Literal[False] = False
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    action_map_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> CustomerCompensationRuleProviderActionMap:
        positions = tuple(item.position for item in self.items)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("customer Provider action map positions must be unique and sorted")
        plan_sha256s = tuple(item.plan_sha256 for item in self.items)
        if len(set(plan_sha256s)) != len(plan_sha256s):
            raise ValueError("customer Provider action map plans must be unique")
        targets = tuple(
            (item.target_engine.value, item.target_ref) for item in self.items
        )
        if len(set(targets)) != len(targets):
            raise ValueError("customer Provider action map targets must be unique")
        expected_rule_id = RULE_ID_BY_ACTION.get(self.candidate_action)
        if (
            expected_rule_id is None
            or self.customer_rule_id != expected_rule_id
            or self.candidate_action
            in {
                CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME,
                CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN,
            }
        ):
            raise ValueError("customer Provider action map action is not mutating")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"action_map_sha256"}),
            "action_map_sha256",
        )
        if self.action_map_sha256 != expected:
            raise ValueError("customer Provider action map fingerprint is invalid")
        return self


class CustomerCompensationRuleProviderRequestBindingInput(_FrozenModel):
    """Minimal native request identity supplied to the execution binder."""

    position: int = Field(ge=0, le=31)
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    request_sha256: Sha256
    execution_plan_sha256: Sha256


class CustomerCompensationRuleProviderExecutionBindingItem(_FrozenModel):
    """One signed customer mapping joined to one exact native request."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-provider-execution-binding-item.v1"
    )
    position: int = Field(ge=0, le=31)
    target_engine: ProjectionEngine
    projection_id: NonEmptyText
    target_ref: NonEmptyText
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    action_map_item_sha256: Sha256
    source_plan_sha256: Sha256
    plan_binding_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    request_sha256: Sha256
    execution_plan_sha256: Sha256
    unknown_outcome_policy: Literal[
        "observe_receipt_and_target_then_resume_if_safe"
    ]
    committed_prefix_replay_allowed: Literal[False] = False
    unknown_position_resume_attempt_limit: Literal[1] = 1
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> CustomerCompensationRuleProviderExecutionBindingItem:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("customer Provider execution item fingerprint is invalid")
        return self


class CustomerCompensationRuleProviderExecutionBinding(_FrozenModel):
    """Callback-time binding from signed action map to exact Provider requests."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-rule-provider-execution-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    customer_rule_current_binding_sha256: Sha256
    customer_rule_contract_sha256: Sha256
    customer_approval_artifact_sha256: Sha256
    action_map_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    request_bundle_sha256: Sha256
    items: tuple[CustomerCompensationRuleProviderExecutionBindingItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    binding_state: Literal[
        "customer_signed_provider_actions_bound_pending_callback"
    ] = "customer_signed_provider_actions_bound_pending_callback"
    customer_action_mapping_preflight_performed: Literal[True] = True
    production_execution_authorized: Literal[False] = False
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> CustomerCompensationRuleProviderExecutionBinding:
        positions = tuple(item.position for item in self.items)
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("customer Provider execution positions must be unique and sorted")
        if self.customer_approval_artifact_sha256 != self.action_map_sha256:
            raise ValueError("customer approval artifact differs from Provider action map")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"binding_sha256"}),
            "binding_sha256",
        )
        if self.binding_sha256 != expected:
            raise ValueError("customer Provider execution binding fingerprint is invalid")
        return self


def build_customer_compensation_rule_provider_action_map(
    proposal: FederatedProjectionCompensationProposal,
    candidate_sha256: str,
    rule: CustomerCompensationRule,
) -> CustomerCompensationRuleProviderActionMap:
    """Build the exact map that a customer approval artifact must fingerprint."""

    try:
        proposal = FederatedProjectionCompensationProposal.model_validate(
            proposal.model_dump(mode="python")
        )
        rule = CustomerCompensationRule.model_validate(rule.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer Provider action map input violates a sealed contract"
        ) from exc
    candidate = next(
        (
            current
            for current in proposal.candidates
            if current.candidate_sha256 == candidate_sha256
        ),
        None,
    )
    if (
        candidate is None
        or not candidate.mutates_provider
        or rule.action is not candidate.action
        or rule.rule_id != RULE_ID_BY_ACTION.get(candidate.action)
        or rule.rule_id not in candidate.missing_customer_rule_ids
    ):
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer rule differs from the mutating proposal candidate"
        )
    if candidate.action is CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX:
        raise CustomerCompensationRuleProviderActionMappingError(
            "rollback requires customer-derived reverse plans before action mapping"
        )
    source_by_plan = {
        source.plan_sha256: source for source in proposal.source_bindings
    }
    rule_targets = {
        (target.target_engine.value, target.target_ref)
        for target in rule.applicable_targets
    }
    items = []
    for plan_sha256 in candidate.plan_sha256s:
        source = source_by_plan.get(plan_sha256)
        if source is None or (source.target_engine, source.target_ref) not in rule_targets:
            raise CustomerCompensationRuleProviderActionMappingError(
                "customer rule does not cover a candidate Provider target"
            )
        provider_action = {
            CompensationProposalAction.DELETE_TARGET: "delete",
            CompensationProposalAction.RESTORE_TARGET: "rebuild",
        }.get(candidate.action, source.sealed_action)
        item_values = {
            "position": source.position,
            "plan_sha256": source.plan_sha256,
            "target_engine": source.target_engine,
            "target_ref": source.target_ref,
            "provider_action": provider_action,
            "unknown_outcome_policy": (
                "observe_receipt_and_target_then_resume_if_safe"
            ),
            "committed_prefix_replay_allowed": False,
            "unknown_position_resume_attempt_limit": 1,
        }
        items.append(
            CustomerCompensationRuleProviderActionMapItem(
                **item_values,
                item_sha256=_fingerprint(
                    CustomerCompensationRuleProviderActionMapItem.schema_id,
                    item_values,
                    "item_sha256",
                ),
            )
        )
    items = sorted(items, key=lambda item: item.position)
    values = {
        "tenant_id": proposal.tenant_id,
        "run_id": proposal.run_id,
        "proposal_sha256": proposal.proposal_sha256,
        "source_snapshot_sha256": proposal.source_snapshot_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_action": candidate.action,
        "candidate_scope": candidate.scope,
        "customer_rule_id": rule.rule_id,
        "customer_rule_semantic_version": rule.semantic_version,
        "customer_rule_sha256": rule.rule_sha256,
        "items": tuple(items),
        "mapping_state": (
            "customer_signed_provider_actions_pending_governed_execution"
        ),
        "customer_approval_artifact_must_equal_action_map": True,
        "production_execution_authorized": False,
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
    }
    return CustomerCompensationRuleProviderActionMap(
        **values,
        action_map_sha256=_fingerprint(
            CustomerCompensationRuleProviderActionMap.schema_id,
            {
                **values,
                "items": tuple(item.model_dump(mode="json") for item in items),
            },
            "action_map_sha256",
        ),
    )


def build_customer_compensation_rule_provider_execution_binding(
    action_map: CustomerCompensationRuleProviderActionMap,
    rule_contract: CustomerCompensationRuleContract,
    rule_current_binding: FederatedProjectionCompensationDispatchRuleCurrentBinding,
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    request_bindings: tuple[CustomerCompensationRuleProviderRequestBindingInput, ...],
    *,
    request_bundle_sha256: str,
) -> CustomerCompensationRuleProviderExecutionBinding:
    """Bind the signed map to exact Provider requests before any callback."""

    try:
        action_map = CustomerCompensationRuleProviderActionMap.model_validate(
            action_map.model_dump(mode="python")
        )
        rule_contract = CustomerCompensationRuleContract.model_validate(
            rule_contract.model_dump(mode="python")
        )
        rule_current_binding = (
            FederatedProjectionCompensationDispatchRuleCurrentBinding.model_validate(
                rule_current_binding.model_dump(mode="python")
            )
        )
        intent = FederatedProjectionCompensationDispatchIntent.model_validate(
            intent.model_dump(mode="python")
        )
        plan_set = FederatedProjectionCompensationProviderPlanSet.model_validate(
            plan_set.model_dump(mode="python")
        )
        materialization = (
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            )
        )
        request_bindings = tuple(
            CustomerCompensationRuleProviderRequestBindingInput.model_validate(
                item.model_dump(mode="python")
            )
            for item in request_bindings
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer Provider execution mapping input violates a sealed contract"
        ) from exc

    approval = rule_contract.approval_evidence
    trusted_rule = next(
        (
            item
            for item in rule_current_binding.approved_rules
            if item.rule_id == action_map.customer_rule_id
        ),
        None,
    )
    if (
        rule_contract.status is not CustomerCompensationRuleStatus.CUSTOMER_APPROVED
        or approval is None
        or approval.approval_artifact_sha256 != action_map.action_map_sha256
        or rule_contract.rule.rule_id != action_map.customer_rule_id
        or rule_contract.rule.semantic_version
        != action_map.customer_rule_semantic_version
        or rule_contract.rule.rule_sha256 != action_map.customer_rule_sha256
        or trusted_rule is None
        or trusted_rule.semantic_version != rule_contract.rule.semantic_version
        or trusted_rule.rule_sha256 != rule_contract.rule.rule_sha256
        or trusted_rule.contract_sha256 != rule_contract.contract_sha256
        or trusted_rule.approval_artifact_sha256
        != approval.approval_artifact_sha256
    ):
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer approval artifact does not authorize the Provider action map"
        )
    if (
        action_map.tenant_id != intent.tenant_id
        or action_map.run_id != intent.run_id
        or action_map.proposal_sha256 != intent.proposal_sha256
        or action_map.source_snapshot_sha256 != intent.source_snapshot_sha256
        or action_map.candidate_sha256 != intent.candidate_sha256
        or action_map.candidate_action is not intent.candidate_action
        or action_map.candidate_scope != intent.candidate_scope
        or rule_current_binding.tenant_id != intent.tenant_id
        or rule_current_binding.run_id != intent.run_id
        or rule_current_binding.dispatch_intent_sha256
        != intent.dispatch_intent_sha256
        or plan_set.tenant_id != intent.tenant_id
        or plan_set.run_id != intent.run_id
        or plan_set.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or plan_set.candidate_action is not intent.candidate_action
        or materialization.tenant_id != intent.tenant_id
        or materialization.run_id != intent.run_id
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
    ):
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer Provider action map differs from the sealed execution chain"
        )
    if intent.candidate_action is CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX:
        raise CustomerCompensationRuleProviderActionMappingError(
            "rollback requires customer-derived reverse plans before Provider execution"
        )

    map_by_position = {item.position: item for item in action_map.items}
    source_by_position = {item.position: item for item in intent.plan_bindings}
    plan_by_position = {item.position: item for item in plan_set.plan_bindings}
    materialized_by_position = {
        item.position: item for item in materialization.bindings
    }
    request_by_position = {item.position: item for item in request_bindings}
    positions = tuple(sorted(map_by_position))
    if (
        positions != tuple(sorted(source_by_position))
        or positions != tuple(sorted(plan_by_position))
        or positions != tuple(sorted(materialized_by_position))
        or positions != tuple(sorted(request_by_position))
        or len(request_by_position) != len(request_bindings)
    ):
        raise CustomerCompensationRuleProviderActionMappingError(
            "customer Provider action map does not cover the exact request positions"
        )

    items = []
    for position in positions:
        mapped = map_by_position[position]
        source = source_by_position[position]
        planned = plan_by_position[position]
        materialized = materialized_by_position[position]
        request = request_by_position[position]
        if (
            mapped.plan_sha256 != source.plan_sha256
            or mapped.plan_sha256 != planned.source_plan_sha256
            or mapped.target_engine.value != source.target_engine
            or mapped.target_engine is not planned.target_engine
            or mapped.target_engine is not materialized.target_engine
            or mapped.target_engine is not request.target_engine
            or mapped.target_ref != source.target_ref
            or mapped.target_ref != planned.target_ref
            or mapped.target_ref != materialized.target_ref
            or mapped.target_ref != request.target_ref
            or (
                intent.candidate_action
                is CompensationProposalAction.CORRECTIVE_FORWARD
                and mapped.provider_action != source.sealed_action
            )
            or mapped.provider_action != planned.provider_action
            or mapped.provider_action != materialized.provider_action
            or mapped.provider_action != request.provider_action
        ):
            raise CustomerCompensationRuleProviderActionMappingError(
                "customer Provider action map differs from a native request"
            )
        if (
            intent.candidate_action is CompensationProposalAction.DELETE_TARGET
            and (
                mapped.provider_action != "delete"
                or materialized.expected_target_exists
            )
        ):
            raise CustomerCompensationRuleProviderActionMappingError(
                "delete action map does not produce a deleted target"
            )
        if (
            intent.candidate_action is CompensationProposalAction.RESTORE_TARGET
            and (
                mapped.provider_action != "rebuild"
                or not materialized.expected_target_exists
            )
        ):
            raise CustomerCompensationRuleProviderActionMappingError(
                "restore action map does not rebuild an existing target"
            )
        item_values = {
            "position": position,
            "target_engine": mapped.target_engine,
            "projection_id": materialized.projection_id,
            "target_ref": mapped.target_ref,
            "provider_action": mapped.provider_action,
            "action_map_item_sha256": mapped.item_sha256,
            "source_plan_sha256": planned.source_plan_sha256,
            "plan_binding_sha256": planned.plan_binding_sha256,
            "materialization_binding_sha256": (
                materialized.materialization_binding_sha256
            ),
            "provider_plan_sha256": materialized.provider_plan_sha256,
            "provider_idempotency_key": materialized.provider_idempotency_key,
            "request_sha256": request.request_sha256,
            "execution_plan_sha256": request.execution_plan_sha256,
            "unknown_outcome_policy": mapped.unknown_outcome_policy,
            "committed_prefix_replay_allowed": False,
            "unknown_position_resume_attempt_limit": 1,
        }
        items.append(
            CustomerCompensationRuleProviderExecutionBindingItem(
                **item_values,
                item_sha256=_fingerprint(
                    CustomerCompensationRuleProviderExecutionBindingItem.schema_id,
                    item_values,
                    "item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "customer_rule_current_binding_sha256": (
            rule_current_binding.rule_current_binding_sha256
        ),
        "customer_rule_contract_sha256": rule_contract.contract_sha256,
        "customer_approval_artifact_sha256": approval.approval_artifact_sha256,
        "action_map_sha256": action_map.action_map_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "request_bundle_sha256": request_bundle_sha256,
        "items": tuple(items),
        "binding_state": (
            "customer_signed_provider_actions_bound_pending_callback"
        ),
        "customer_action_mapping_preflight_performed": True,
        "production_execution_authorized": False,
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
    }
    return CustomerCompensationRuleProviderExecutionBinding(
        **values,
        binding_sha256=_fingerprint(
            CustomerCompensationRuleProviderExecutionBinding.schema_id,
            {
                **values,
                "items": tuple(item.model_dump(mode="json") for item in items),
            },
            "binding_sha256",
        ),
    )


__all__ = [
    "CustomerCompensationRuleProviderActionMap",
    "CustomerCompensationRuleProviderActionMapItem",
    "CustomerCompensationRuleProviderActionMappingError",
    "CustomerCompensationRuleProviderExecutionBinding",
    "CustomerCompensationRuleProviderExecutionBindingItem",
    "CustomerCompensationRuleProviderRequestBindingInput",
    "build_customer_compensation_rule_provider_action_map",
    "build_customer_compensation_rule_provider_execution_binding",
]
