"""Deployment-side Provider adapter contracts for customer-rule dispatch.

The adapter registry describes which already-deployed implementation may accept
one exact dispatch intent.  It is an allowlist, not an executor: resolving an
adapter never opens a network connection, imports a Provider, or authorizes a
mutation.  Customer semantics remain in the signed rule contracts and the
separate ApprovalCase chain.
"""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_proposal import (
    ONTOLOGY_CONTENT_SHA256,
    ONTOLOGY_PACKAGE_ID,
    CompensationProposalAction,
)
from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
)

FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_ENV = (
    "GDA_FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_JSON"
)

_CUSTOMER_RULE_ACTIONS = frozenset(
    {
        CompensationProposalAction.CORRECTIVE_FORWARD,
        CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
        CompensationProposalAction.DELETE_TARGET,
        CompensationProposalAction.RESTORE_TARGET,
    }
)

_RECEIPT_SCHEMA_BY_ENGINE: dict[ProjectionEngine, str] = {
    ProjectionEngine.POSTGIS: "gda.postgis-projection-repair-receipt.v1",
    ProjectionEngine.VECTOR: "gda.vector-projection-repair-receipt.v1",
    ProjectionEngine.RDF: "gda.rdf-projection-repair-receipt.v1",
    ProjectionEngine.OBJECT_STORE: "gda.object-projection-repair-receipt.v1",
    ProjectionEngine.LAKEHOUSE: "gda.lakehouse-projection-repair-receipt.v1",
}


class FederatedProjectionCompensationProviderAdapterError(ValueError):
    """A deployment adapter cannot safely accept the dispatch intent."""


class FederatedProjectionCompensationProviderAdapterConfigurationError(
    FederatedProjectionCompensationProviderAdapterError
):
    """The deployment-side adapter registry is malformed or unavailable."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def federated_compensation_provider_adapter_fingerprint(**values: Any) -> str:
    return _fingerprint(
        FederatedProjectionCompensationProviderAdapterDefinition.schema_id,
        values,
        "adapter_sha256",
    )


def federated_compensation_provider_adapter_registry_fingerprint(
    **values: Any,
) -> str:
    return _fingerprint(
        FederatedProjectionCompensationProviderAdapterRegistry.schema_id,
        values,
        "registry_sha256",
    )


class FederatedProjectionCompensationProviderAdapterTarget(_FrozenModel):
    """One exact target identity accepted by a registered adapter."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-adapter-target.v1"
    )
    target_engine: ProjectionEngine
    target_ref: NonEmptyText

    @property
    def identity(self) -> tuple[str, str]:
        return self.target_engine.value, self.target_ref


class FederatedProjectionCompensationProviderReceiptContract(_FrozenModel):
    """Provider-native receipt schema expected for one target engine."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-receipt-contract.v1"
    )
    target_engine: ProjectionEngine
    receipt_schema_id: NonEmptyText

    @model_validator(mode="after")
    def _known_receipt_schema(
        self,
    ) -> FederatedProjectionCompensationProviderReceiptContract:
        expected = _RECEIPT_SCHEMA_BY_ENGINE[self.target_engine]
        if self.receipt_schema_id != expected:
            raise ValueError("receipt schema is not the governed schema for target engine")
        return self


class FederatedProjectionCompensationProviderMutationContract(_FrozenModel):
    """Deployment-owned implementation contract for one action and engine."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-mutation-contract.v1"
    )
    target_engine: ProjectionEngine
    candidate_action: CompensationProposalAction
    provider_action: Literal["checkpoint", "rebuild", "delete"]
    operation_contract_sha256: Sha256
    input_mode: Literal["deployment_owned_no_request_payload"] = (
        "deployment_owned_no_request_payload"
    )

    @model_validator(mode="after")
    def _customer_rule_action(
        self,
    ) -> FederatedProjectionCompensationProviderMutationContract:
        if self.candidate_action not in _CUSTOMER_RULE_ACTIONS:
            raise ValueError("provider mutation contract action is not customer governed")
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return self.candidate_action.value, self.target_engine.value


class FederatedProjectionCompensationProviderAdapterDefinition(_FrozenModel):
    """Immutable deployment registration for a non-public adapter."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-adapter-definition.v1"
    )
    tenant_id: TenantId
    adapter_id: ShortName
    semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    implementation_artifact_sha256: Sha256
    dataset_scope: Literal["chongqing_customer_dataset"] = (
        "chongqing_customer_dataset"
    )
    ontology_package_id: Literal[
        "natural-resource-one-map:2.3.0:587915868b1221af"
    ] = ONTOLOGY_PACKAGE_ID
    ontology_content_sha256: Sha256 = ONTOLOGY_CONTENT_SHA256
    targets: tuple[FederatedProjectionCompensationProviderAdapterTarget, ...] = Field(
        min_length=1,
        max_length=32,
    )
    supported_actions: tuple[CompensationProposalAction, ...] = Field(
        min_length=1,
        max_length=4,
    )
    receipt_contracts: tuple[
        FederatedProjectionCompensationProviderReceiptContract, ...
    ] = Field(min_length=1, max_length=5)
    mutation_contracts: tuple[
        FederatedProjectionCompensationProviderMutationContract, ...
    ] = Field(min_length=1, max_length=20)
    adapter_sha256: Sha256
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    provider_execution_performed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _sealed_definition(
        self,
    ) -> FederatedProjectionCompensationProviderAdapterDefinition:
        if self.ontology_content_sha256 != ONTOLOGY_CONTENT_SHA256:
            raise ValueError("provider adapter ontology package differs from 2.3.0")
        target_ids = tuple(target.identity for target in self.targets)
        if tuple(sorted(set(target_ids))) != target_ids:
            raise ValueError("provider adapter targets must be unique and sorted")
        if any(action not in _CUSTOMER_RULE_ACTIONS for action in self.supported_actions):
            raise ValueError("provider adapter supports only customer-rule mutations")
        if tuple(sorted(set(self.supported_actions), key=lambda value: value.value)) != (
            self.supported_actions
        ):
            raise ValueError("provider adapter actions must be unique and sorted")
        engines = tuple(contract.target_engine for contract in self.receipt_contracts)
        if tuple(sorted(set(engines), key=lambda value: value.value)) != engines:
            raise ValueError("provider adapter receipt contracts must be unique and sorted")
        target_engines = tuple(
            sorted(
                {target.target_engine for target in self.targets},
                key=lambda value: value.value,
            )
        )
        if engines != target_engines:
            raise ValueError("provider adapter receipt contracts must cover target engines")
        mutation_ids = tuple(contract.identity for contract in self.mutation_contracts)
        if tuple(sorted(set(mutation_ids))) != mutation_ids:
            raise ValueError("provider adapter mutation contracts must be unique and sorted")
        expected_mutation_ids = tuple(
            sorted(
                (action.value, engine.value)
                for action in self.supported_actions
                for engine in target_engines
            )
        )
        if mutation_ids != expected_mutation_ids:
            raise ValueError("provider adapter mutation contracts do not cover its scope")
        expected = federated_compensation_provider_adapter_fingerprint(
            **self.model_dump(mode="json", exclude={"adapter_sha256"})
        )
        if self.adapter_sha256 != expected:
            raise ValueError("provider adapter fingerprint is invalid")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.adapter_id, self.semantic_version


class FederatedProjectionCompensationProviderAdapterRegistry(_FrozenModel):
    """Deployment-owned immutable adapter allowlist."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-adapter-registry.v1"
    )
    adapters: tuple[FederatedProjectionCompensationProviderAdapterDefinition, ...] = (
        ()
    )
    registry_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_registry(
        self,
    ) -> FederatedProjectionCompensationProviderAdapterRegistry:
        identities = tuple(adapter.identity for adapter in self.adapters)
        if tuple(sorted(set(identities))) != identities:
            raise ValueError("provider adapter registrations must be unique and sorted")
        expected = federated_compensation_provider_adapter_registry_fingerprint(
            **self.model_dump(mode="json", exclude={"registry_sha256"})
        )
        if self.registry_sha256 != expected:
            raise ValueError("provider adapter registry fingerprint is invalid")
        return self

    def resolve(
        self,
        *,
        tenant_id: str,
        adapter_id: str,
        semantic_version: str,
        adapter_sha256: str,
    ) -> FederatedProjectionCompensationProviderAdapterDefinition | None:
        return next(
            (
                adapter
                for adapter in self.adapters
                if adapter.tenant_id == tenant_id
                and adapter.adapter_id == adapter_id
                and adapter.semantic_version == semantic_version
                and adapter.adapter_sha256 == adapter_sha256
            ),
            None,
        )


class FederatedProjectionCompensationProviderAdapterResolutionRequest(_FrozenModel):
    """Only deployment identity is selectable; target and customer data are not."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-adapter-resolution-request.v1"
    )
    tenant_id: TenantId
    dispatch_intent_sha256: Sha256
    adapter_id: ShortName
    adapter_semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    adapter_sha256: Sha256
    registry_sha256: Sha256
    requested_by: NonEmptyText

    @model_validator(mode="after")
    def _typed_requester(
        self,
    ) -> FederatedProjectionCompensationProviderAdapterResolutionRequest:
        if not self.requested_by.startswith(("human:", "agent:", "workload:")):
            raise ValueError("adapter resolution requester must use typed identity")
        return self


class FederatedProjectionCompensationProviderAdapterResolution(_FrozenModel):
    """Resolved adapter contract, still explicitly pending Provider execution."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-provider-adapter-resolution.v1"
    )
    tenant_id: TenantId
    dispatch_intent_sha256: Sha256
    adapter_id: ShortName
    adapter_semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    adapter_sha256: Sha256
    implementation_artifact_sha256: Sha256
    registry_sha256: Sha256
    requested_by: NonEmptyText
    targets: tuple[FederatedProjectionCompensationProviderAdapterTarget, ...] = Field(
        min_length=1,
        max_length=32,
    )
    candidate_action: CompensationProposalAction
    receipt_contracts: tuple[
        FederatedProjectionCompensationProviderReceiptContract, ...
    ] = Field(min_length=1, max_length=5)
    mutation_contracts: tuple[
        FederatedProjectionCompensationProviderMutationContract, ...
    ] = Field(min_length=1, max_length=5)
    resolution_state: Literal["adapter_resolved_pending_execution"] = (
        "adapter_resolved_pending_execution"
    )
    provider_dispatch_performed: Literal[False] = False
    execution_allowed: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    resolution_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_resolution(
        self,
    ) -> FederatedProjectionCompensationProviderAdapterResolution:
        if not self.requested_by.startswith(("human:", "agent:", "workload:")):
            raise ValueError("adapter resolution requester must use typed identity")
        target_ids = tuple(target.identity for target in self.targets)
        if tuple(sorted(set(target_ids))) != target_ids:
            raise ValueError("adapter resolution targets must be unique and sorted")
        engines = tuple(contract.target_engine for contract in self.receipt_contracts)
        if tuple(sorted(set(engines), key=lambda value: value.value)) != engines:
            raise ValueError("adapter resolution receipt contracts are not canonical")
        target_engines = tuple(
            sorted(
                {target.target_engine for target in self.targets},
                key=lambda value: value.value,
            )
        )
        if target_engines != engines:
            raise ValueError("adapter resolution receipts do not cover its targets")
        if self.candidate_action not in _CUSTOMER_RULE_ACTIONS:
            raise ValueError("adapter resolution action is not customer-rule governed")
        mutation_ids = tuple(contract.identity for contract in self.mutation_contracts)
        expected_mutation_ids = tuple(
            (self.candidate_action.value, engine.value) for engine in target_engines
        )
        if mutation_ids != expected_mutation_ids:
            raise ValueError("adapter resolution mutation contracts do not cover its targets")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"resolution_sha256"}),
            "resolution_sha256",
        )
        if self.resolution_sha256 != expected:
            raise ValueError("provider adapter resolution fingerprint is invalid")
        return self


def build_federated_compensation_provider_adapter_definition(
    *,
    tenant_id: str,
    adapter_id: str,
    semantic_version: str,
    implementation_artifact_sha256: str,
    targets: tuple[
        FederatedProjectionCompensationProviderAdapterTarget, ...
    ],
    supported_actions: tuple[CompensationProposalAction, ...],
    receipt_contracts: tuple[
        FederatedProjectionCompensationProviderReceiptContract, ...
    ],
    mutation_contracts: tuple[
        FederatedProjectionCompensationProviderMutationContract, ...
    ],
) -> FederatedProjectionCompensationProviderAdapterDefinition:
    values = {
        "tenant_id": tenant_id,
        "adapter_id": adapter_id,
        "semantic_version": semantic_version,
        "implementation_artifact_sha256": implementation_artifact_sha256,
        "dataset_scope": "chongqing_customer_dataset",
        "ontology_package_id": ONTOLOGY_PACKAGE_ID,
        "ontology_content_sha256": ONTOLOGY_CONTENT_SHA256,
        "targets": targets,
        "supported_actions": supported_actions,
        "receipt_contracts": receipt_contracts,
        "mutation_contracts": mutation_contracts,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "provider_execution_performed": False,
        "execution_allowed": False,
    }
    return FederatedProjectionCompensationProviderAdapterDefinition(
        **values,
        adapter_sha256=federated_compensation_provider_adapter_fingerprint(
            **{
                **values,
                "targets": [target.model_dump(mode="json") for target in targets],
                "supported_actions": [action.value for action in supported_actions],
                "receipt_contracts": [
                    contract.model_dump(mode="json") for contract in receipt_contracts
                ],
                "mutation_contracts": [
                    contract.model_dump(mode="json") for contract in mutation_contracts
                ],
            }
        ),
    )


def build_federated_compensation_provider_adapter_registry(
    adapters: tuple[
        FederatedProjectionCompensationProviderAdapterDefinition, ...
    ] = (),
) -> FederatedProjectionCompensationProviderAdapterRegistry:
    ordered = tuple(sorted(adapters, key=lambda adapter: adapter.identity))
    values = {"adapters": tuple(adapter.model_dump(mode="json") for adapter in ordered)}
    return FederatedProjectionCompensationProviderAdapterRegistry(
        **values,
        registry_sha256=federated_compensation_provider_adapter_registry_fingerprint(
            **values
        ),
    )


def load_federated_compensation_provider_adapter_registry(
    raw: str | None = None,
) -> FederatedProjectionCompensationProviderAdapterRegistry:
    """Load only deployment configuration; an unset variable is empty."""

    document_text = raw if raw is not None else os.getenv(
        FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_ENV
    )
    if document_text is None or not document_text.strip():
        return build_federated_compensation_provider_adapter_registry()
    try:
        document = json.loads(document_text)
    except json.JSONDecodeError as exc:
        raise FederatedProjectionCompensationProviderAdapterConfigurationError(
            "provider adapter registry must be valid JSON"
        ) from exc
    if not isinstance(document, list):
        raise FederatedProjectionCompensationProviderAdapterConfigurationError(
            "provider adapter registry must be a JSON array"
        )
    try:
        adapters = tuple(
            FederatedProjectionCompensationProviderAdapterDefinition.model_validate(
                item
            )
            for item in document
        )
        return build_federated_compensation_provider_adapter_registry(adapters)
    except (ValidationError, ValueError) as exc:
        raise FederatedProjectionCompensationProviderAdapterConfigurationError(
            "provider adapter registry violates its sealed contract"
        ) from exc


def _dispatch_target_identity(
    intent: FederatedProjectionCompensationDispatchIntent,
) -> tuple[tuple[str, str], ...]:
    identities: list[tuple[str, str]] = []
    for binding in intent.plan_bindings:
        try:
            engine = ProjectionEngine(binding.target_engine)
        except ValueError as exc:
            raise FederatedProjectionCompensationProviderAdapterError(
                "dispatch intent contains an unknown target engine"
            ) from exc
        identities.append((engine.value, binding.target_ref))
    return tuple(sorted(set(identities)))


def resolve_federated_compensation_provider_adapter(
    intent: FederatedProjectionCompensationDispatchIntent,
    request: FederatedProjectionCompensationProviderAdapterResolutionRequest,
    registry: FederatedProjectionCompensationProviderAdapterRegistry,
) -> FederatedProjectionCompensationProviderAdapterResolution:
    """Resolve a deployment adapter without dispatching or executing it."""

    try:
        intent = FederatedProjectionCompensationDispatchIntent.model_validate(
            intent.model_dump(mode="python")
        )
        request = (
            FederatedProjectionCompensationProviderAdapterResolutionRequest.model_validate(
                request.model_dump(mode="python")
            )
        )
        registry = FederatedProjectionCompensationProviderAdapterRegistry.model_validate(
            registry.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationProviderAdapterError(
            "provider adapter resolution input violates its sealed contract"
        ) from exc

    if request.tenant_id != intent.tenant_id:
        raise FederatedProjectionCompensationProviderAdapterError(
            "adapter resolution tenant differs from dispatch intent"
        )
    if request.dispatch_intent_sha256 != intent.dispatch_intent_sha256:
        raise FederatedProjectionCompensationProviderAdapterError(
            "adapter resolution dispatch intent differs"
        )
    if request.registry_sha256 != registry.registry_sha256:
        raise FederatedProjectionCompensationProviderAdapterError(
            "adapter registry fingerprint differs from resolution request"
        )
    adapter = registry.resolve(
        tenant_id=request.tenant_id,
        adapter_id=request.adapter_id,
        semantic_version=request.adapter_semantic_version,
        adapter_sha256=request.adapter_sha256,
    )
    if adapter is None:
        raise FederatedProjectionCompensationProviderAdapterError(
            "provider adapter is not registered for this tenant and version"
        )
    if (
        intent.dataset_scope != adapter.dataset_scope
        or intent.ontology_package_id != adapter.ontology_package_id
        or intent.ontology_content_sha256 != adapter.ontology_content_sha256
    ):
        raise FederatedProjectionCompensationProviderAdapterError(
            "provider adapter baseline differs from dispatch intent"
        )
    if intent.candidate_action not in adapter.supported_actions:
        raise FederatedProjectionCompensationProviderAdapterError(
            "provider adapter does not support the dispatch customer action"
        )

    expected_targets = _dispatch_target_identity(intent)
    registered_targets = tuple(target.identity for target in adapter.targets)
    if registered_targets != expected_targets:
        raise FederatedProjectionCompensationProviderAdapterError(
            "provider adapter targets differ from dispatch intent"
        )
    selected_mutation_contracts = tuple(
        contract
        for contract in adapter.mutation_contracts
        if contract.candidate_action is intent.candidate_action
    )
    values = {
        "tenant_id": intent.tenant_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "adapter_id": adapter.adapter_id,
        "adapter_semantic_version": adapter.semantic_version,
        "adapter_sha256": adapter.adapter_sha256,
        "implementation_artifact_sha256": adapter.implementation_artifact_sha256,
        "registry_sha256": registry.registry_sha256,
        "requested_by": request.requested_by,
        "targets": adapter.targets,
        "candidate_action": intent.candidate_action,
        "receipt_contracts": adapter.receipt_contracts,
        "mutation_contracts": selected_mutation_contracts,
        "resolution_state": "adapter_resolved_pending_execution",
        "provider_dispatch_performed": False,
        "execution_allowed": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = (
        FederatedProjectionCompensationProviderAdapterResolution.model_construct(
            **values,
            resolution_sha256="0" * 64,
        ).model_dump(mode="json", exclude={"resolution_sha256"})
    )
    return FederatedProjectionCompensationProviderAdapterResolution(
        **values,
        resolution_sha256=_fingerprint(
            FederatedProjectionCompensationProviderAdapterResolution.schema_id,
            normalized,
            "resolution_sha256",
        ),
    )


__all__ = [
    "FEDERATED_COMPENSATION_PROVIDER_ADAPTER_REGISTRY_ENV",
    "FederatedProjectionCompensationProviderAdapterError",
    "FederatedProjectionCompensationProviderAdapterConfigurationError",
    "FederatedProjectionCompensationProviderAdapterTarget",
    "FederatedProjectionCompensationProviderReceiptContract",
    "FederatedProjectionCompensationProviderMutationContract",
    "FederatedProjectionCompensationProviderAdapterDefinition",
    "FederatedProjectionCompensationProviderAdapterRegistry",
    "FederatedProjectionCompensationProviderAdapterResolutionRequest",
    "FederatedProjectionCompensationProviderAdapterResolution",
    "build_federated_compensation_provider_adapter_definition",
    "build_federated_compensation_provider_adapter_registry",
    "load_federated_compensation_provider_adapter_registry",
    "federated_compensation_provider_adapter_fingerprint",
    "federated_compensation_provider_adapter_registry_fingerprint",
    "resolve_federated_compensation_provider_adapter",
]
