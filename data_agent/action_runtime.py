"""Governed Proposal/Action contracts over CapabilitySpec and PlatformRun.

The module deliberately does not introduce another scheduler or ActionRun
authority.  An action occurrence is correlated to the existing PlatformRun;
the in-memory ledger is a bounded development adapter used by contract tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capability_registry import (
    CapabilityRegistry,
    CapabilitySpec,
    IdempotencyMode,
    OperationKind,
    RiskClass,
    SideEffect,
    Surface,
    SurfaceStatus,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    NonEmptyText,
    OrchestrationClass,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    PolicyEffect,
    PortabilityClass,
    ResourceBinding,
    ResourceURNText,
    RunPolicyReferences,
    RunStatus,
    Sha256,
    ShortName,
    SubjectContext,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
    platform_definition_fingerprint,
    validate_run_transition,
)


class ActionRuntimeError(RuntimeError):
    """Base error for a fail-closed Proposal/Action admission."""


class ActionContractError(ActionRuntimeError):
    """A definition, proposal, or capability binding is inconsistent."""


class ActionAdmissionError(ActionRuntimeError):
    """Current policy, object versions, or approval did not admit execution."""


class ActionIdempotencyConflictError(ActionRuntimeError):
    """An idempotency key is already bound to a different immutable intent."""


class ActionSideEffectLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class ActionApprovalRequirement(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


class ActionInvocationChannel(StrEnum):
    WEB = "web"
    API = "api"
    MCP = "mcp"
    AGENT = "agent"

    @property
    def capability_surface(self) -> Surface:
        return {
            ActionInvocationChannel.WEB: Surface.WEB,
            ActionInvocationChannel.API: Surface.API,
            ActionInvocationChannel.MCP: Surface.AGENT,
            ActionInvocationChannel.AGENT: Surface.AGENT,
        }[self]


class ChangeOperation(StrEnum):
    DERIVE = "derive"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ProviderOutcome(StrEnum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ChangeComparison(StrEnum):
    EXACT = "exact"
    OUT_OF_BOUNDS = "out_of_bounds"
    NOT_OBSERVED = "not_observed"


class ActionResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECONCILING = "reconciling"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _jsonable(payload)})


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat().replace("+00:00", "Z")
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("action runtime timestamps must be timezone-aware")
    return value.astimezone(UTC)


class CapabilityVersionBinding(_FrozenModel):
    """Exact CapabilitySpec current copied into an ActionType definition."""

    schema_id: ClassVar[str] = "gda.action-capability-binding.v1"
    capability_id: NonEmptyText
    capability_version: NonEmptyText
    capability_fingerprint: Sha256
    operation: OperationKind
    risk: RiskClass
    side_effect: SideEffect
    policy_action: NonEmptyText
    idempotency: IdempotencyMode
    compensatable: bool
    reconcilable: bool


class ActionTypeDefinition(_FrozenModel):
    """Versioned domain action semantics backed by one CapabilitySpec version."""

    schema_id: ClassVar[str] = "gda.action-type-definition.v1"
    tenant_id: TenantId
    definition_urn: ResourceURNText
    definition_version_id: UUID
    action_type_id: ShortName
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    target_object_types: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    parameter_schema: dict[str, Any]
    result_schema: dict[str, Any]
    allowed_change_operations: tuple[ChangeOperation, ...] = Field(
        min_length=1,
        max_length=4,
    )
    required_evidence_types: tuple[NonEmptyText, ...] = Field(max_length=16)
    side_effect_level: ActionSideEffectLevel
    approval: ActionApprovalRequirement
    capability: CapabilityVersionBinding
    evaluator_ref: NonEmptyText
    compensation_ref: NonEmptyText | None = None
    definition_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_definition(self) -> ActionTypeDefinition:
        identity = parse_resource_urn(self.definition_urn)
        if identity["tenant_id"] != self.tenant_id or identity["resource_kind"] != "definition":
            raise ValueError("ActionType definition URN must be a tenant definition")
        for values, label in (
            (self.target_object_types, "target object types"),
            (self.required_evidence_types, "required evidence types"),
            (self.allowed_change_operations, "allowed change operations"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"ActionType {label} must be unique")

        writes = self.capability.side_effect is not SideEffect.NONE
        if self.side_effect_level is ActionSideEffectLevel.L1:
            if writes or self.approval is not ActionApprovalRequirement.NOT_REQUIRED:
                raise ValueError("L1 ActionType must be non-mutating without mandatory approval")
        if self.side_effect_level in {
            ActionSideEffectLevel.L3,
            ActionSideEffectLevel.L4,
        }:
            if not writes or self.approval is not ActionApprovalRequirement.REQUIRED:
                raise ValueError("L3/L4 ActionType must be mutating and approval-required")
            if self.capability.idempotency is not IdempotencyMode.REQUIRED:
                raise ValueError("L3/L4 ActionType requires Capability idempotency")
        if self.capability.side_effect is SideEffect.EXTERNAL_WRITE:
            if not self.capability.reconcilable:
                raise ValueError("external-write ActionType must be reconcilable")
        if self.compensation_ref is not None and not self.capability.compensatable:
            raise ValueError("ActionType cannot add unsupported compensation")

        expected = platform_definition_fingerprint(
            orchestration_class=OrchestrationClass.ACTION,
            capability_id=self.capability.capability_id,
            portability_class=PortabilityClass.PORTABLE,
            definition_document=self.definition_document(),
            input_contract=self.parameter_schema,
            output_contract=self.result_schema,
        )
        if self.definition_sha256 != expected:
            raise ValueError("ActionType definition fingerprint is invalid")
        return self

    def definition_document(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"parameter_schema", "result_schema", "definition_sha256"},
        )

    def to_platform_definition(self) -> PlatformDefinitionVersion:
        return PlatformDefinitionVersion(
            tenant_id=self.tenant_id,
            definition_urn=self.definition_urn,
            definition_version_id=self.definition_version_id,
            orchestration_class=OrchestrationClass.ACTION,
            capability_id=self.capability.capability_id,
            portability_class=PortabilityClass.PORTABLE,
            definition_document=self.definition_document(),
            input_contract=self.parameter_schema,
            output_contract=self.result_schema,
            definition_sha256=self.definition_sha256,
        )


def build_action_type_definition(
    *,
    tenant_id: str,
    definition_urn: str,
    definition_version_id: UUID,
    action_type_id: str,
    version: str,
    target_object_types: tuple[str, ...],
    allowed_change_operations: tuple[ChangeOperation, ...],
    required_evidence_types: tuple[str, ...],
    side_effect_level: ActionSideEffectLevel,
    approval: ActionApprovalRequirement,
    capability: CapabilitySpec,
    evaluator_ref: str,
    compensation_ref: str | None = None,
) -> ActionTypeDefinition:
    binding = CapabilityVersionBinding(
        capability_id=capability.capability_id,
        capability_version=capability.version,
        capability_fingerprint=capability.fingerprint,
        operation=capability.operation,
        risk=capability.risk,
        side_effect=capability.side_effect,
        policy_action=capability.policy.action,
        idempotency=capability.execution.idempotency,
        compensatable=capability.execution.compensatable,
        reconcilable=capability.execution.reconcilable,
    )
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "definition_urn": definition_urn,
        "definition_version_id": definition_version_id,
        "action_type_id": action_type_id,
        "version": version,
        "target_object_types": target_object_types,
        "parameter_schema": capability.input.json_schema,
        "result_schema": capability.output.json_schema,
        "allowed_change_operations": allowed_change_operations,
        "required_evidence_types": required_evidence_types,
        "side_effect_level": side_effect_level,
        "approval": approval,
        "capability": binding,
        "evaluator_ref": evaluator_ref,
        "compensation_ref": compensation_ref,
    }
    draft = ActionTypeDefinition.model_construct(**values, definition_sha256="0" * 64)
    values["definition_sha256"] = platform_definition_fingerprint(
        orchestration_class=OrchestrationClass.ACTION,
        capability_id=capability.capability_id,
        portability_class=PortabilityClass.PORTABLE,
        definition_document=draft.definition_document(),
        input_contract=capability.input.json_schema,
        output_contract=capability.output.json_schema,
    )
    return ActionTypeDefinition.model_validate(values)


def validate_action_capability_binding(
    definition: ActionTypeDefinition,
    capability: CapabilitySpec,
) -> None:
    expected = CapabilityVersionBinding(
        capability_id=capability.capability_id,
        capability_version=capability.version,
        capability_fingerprint=capability.fingerprint,
        operation=capability.operation,
        risk=capability.risk,
        side_effect=capability.side_effect,
        policy_action=capability.policy.action,
        idempotency=capability.execution.idempotency,
        compensatable=capability.execution.compensatable,
        reconcilable=capability.execution.reconcilable,
    )
    if definition.capability != expected:
        raise ActionContractError("ActionType CapabilitySpec binding drifted")
    if (
        definition.parameter_schema != capability.input.json_schema
        or definition.result_schema != capability.output.json_schema
    ):
        raise ActionContractError("ActionType schema differs from bound CapabilitySpec")


class ObjectVersionRef(_FrozenModel):
    schema_id: ClassVar[str] = "gda.action-object-version-ref.v1"
    tenant_id: TenantId
    object_urn: ResourceURNText
    object_type: NonEmptyText
    resource_version_id: UUID
    content_sha256: Sha256

    @model_validator(mode="after")
    def _tenant_bound(self) -> ObjectVersionRef:
        if parse_resource_urn(self.object_urn)["tenant_id"] != self.tenant_id:
            raise ValueError("Action object reference tenant differs")
        return self


class ObjectStateChange(_FrozenModel):
    schema_id: ClassVar[str] = "gda.action-object-state-change.v1"
    object_urn: ResourceURNText
    operation: ChangeOperation
    before_version_id: UUID | None = None
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _coherent_change(self) -> ObjectStateChange:
        before = (self.before_version_id, self.before_sha256)
        if (before[0] is None) != (before[1] is None):
            raise ValueError("change before version and hash must be set together")
        if self.operation in {ChangeOperation.DERIVE, ChangeOperation.CREATE}:
            if before != (None, None) or self.after_sha256 is None:
                raise ValueError("derive/create change requires only an after hash")
        elif self.operation is ChangeOperation.UPDATE:
            if before[0] is None or self.after_sha256 is None:
                raise ValueError("update change requires before and after identities")
        elif before[0] is None or self.after_sha256 is not None:
            raise ValueError("delete change requires a before identity and no after hash")
        return self


class ChangeSet(_FrozenModel):
    schema_id: ClassVar[str] = "gda.change-set.v1"
    tenant_id: TenantId
    action_definition_sha256: Sha256
    target_versions: tuple[ObjectVersionRef, ...] = Field(min_length=1, max_length=64)
    expected_changes: tuple[ObjectStateChange, ...] = Field(min_length=1, max_length=64)
    idempotency_key: NonEmptyText
    compensation_ref: NonEmptyText | None = None
    change_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_change_set(self) -> ChangeSet:
        if any(target.tenant_id != self.tenant_id for target in self.target_versions):
            raise ValueError("ChangeSet target tenant differs")
        target_urns = tuple(target.object_urn for target in self.target_versions)
        if len(target_urns) != len(set(target_urns)):
            raise ValueError("ChangeSet targets must be unique")
        change_keys = tuple(
            (change.object_urn, change.operation) for change in self.expected_changes
        )
        if len(change_keys) != len(set(change_keys)):
            raise ValueError("ChangeSet changes must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"change_set_sha256"}),
            "change_set_sha256",
        )
        if self.change_set_sha256 != expected:
            raise ValueError("ChangeSet fingerprint is invalid")
        return self


def build_change_set(
    *,
    tenant_id: str,
    action_definition_sha256: str,
    target_versions: tuple[ObjectVersionRef, ...],
    expected_changes: tuple[ObjectStateChange, ...],
    idempotency_key: str,
    compensation_ref: str | None = None,
) -> ChangeSet:
    values = {
        "tenant_id": tenant_id,
        "action_definition_sha256": action_definition_sha256,
        "target_versions": target_versions,
        "expected_changes": expected_changes,
        "idempotency_key": idempotency_key,
        "compensation_ref": compensation_ref,
    }
    return ChangeSet(
        **values,
        change_set_sha256=_fingerprint(ChangeSet.schema_id, values, "change_set_sha256"),
    )


class ProposalArtifact(_FrozenModel):
    """Immutable suggestion.  It is explicitly not execution authorization."""

    schema_id: ClassVar[str] = "gda.proposal-artifact.v1"
    tenant_id: TenantId
    proposal_urn: ResourceURNText
    proposal_version_id: UUID
    proposal_artifact_id: UUID
    proposed_run_id: UUID
    action_definition_version_id: UUID
    action_definition_sha256: Sha256
    capability_fingerprint: Sha256
    subject_context: SubjectContext
    parameters: dict[str, Any]
    parameters_sha256: Sha256
    change_set: ChangeSet
    evidence_artifact_ids: tuple[UUID, ...] = Field(max_length=64)
    uncertainty_codes: tuple[ShortName, ...] = Field(max_length=16)
    created_at: datetime
    execution_authorized: Literal[False] = False
    proposal_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed_proposal(self) -> ProposalArtifact:
        identity = parse_resource_urn(self.proposal_urn)
        if identity["tenant_id"] != self.tenant_id or identity["resource_kind"] != "proposal":
            raise ValueError("Proposal URN must be a tenant proposal")
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("Proposal subject tenant differs")
        if (
            self.change_set.tenant_id != self.tenant_id
            or self.change_set.action_definition_sha256 != self.action_definition_sha256
        ):
            raise ValueError("Proposal ChangeSet binding differs")
        if len(self.evidence_artifact_ids) != len(set(self.evidence_artifact_ids)):
            raise ValueError("Proposal evidence artifacts must be unique")
        if len(self.uncertainty_codes) != len(set(self.uncertainty_codes)):
            raise ValueError("Proposal uncertainty codes must be unique")
        expected_parameters = canonical_json_fingerprint(self.parameters)
        if self.parameters_sha256 != expected_parameters:
            raise ValueError("Proposal parameter fingerprint is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"proposal_sha256"}),
            "proposal_sha256",
        )
        if self.proposal_sha256 != expected:
            raise ValueError("Proposal fingerprint is invalid")
        return self


def build_proposal_artifact(
    *,
    definition: ActionTypeDefinition,
    capability: CapabilitySpec,
    proposal_urn: str,
    proposal_version_id: UUID,
    proposal_artifact_id: UUID,
    proposed_run_id: UUID,
    subject_context: SubjectContext,
    parameters: dict[str, Any],
    change_set: ChangeSet,
    evidence_artifact_ids: tuple[UUID, ...],
    uncertainty_codes: tuple[str, ...],
    created_at: datetime,
) -> ProposalArtifact:
    validate_action_capability_binding(definition, capability)
    validated_parameters = capability.validate_input(parameters)
    if change_set.action_definition_sha256 != definition.definition_sha256:
        raise ActionContractError("Proposal ChangeSet uses a different ActionType version")
    operations = {change.operation for change in change_set.expected_changes}
    if not operations.issubset(set(definition.allowed_change_operations)):
        raise ActionContractError("Proposal ChangeSet contains a disallowed operation")
    target_types = {target.object_type for target in change_set.target_versions}
    if not target_types.issubset(set(definition.target_object_types)):
        raise ActionContractError("Proposal target ObjectType is not supported")
    if set(definition.required_evidence_types) and not evidence_artifact_ids:
        raise ActionContractError("Proposal lacks required evidence artifacts")

    values: dict[str, Any] = {
        "tenant_id": definition.tenant_id,
        "proposal_urn": proposal_urn,
        "proposal_version_id": proposal_version_id,
        "proposal_artifact_id": proposal_artifact_id,
        "proposed_run_id": proposed_run_id,
        "action_definition_version_id": definition.definition_version_id,
        "action_definition_sha256": definition.definition_sha256,
        "capability_fingerprint": capability.fingerprint,
        "subject_context": subject_context,
        "parameters": validated_parameters,
        "parameters_sha256": canonical_json_fingerprint(validated_parameters),
        "change_set": change_set,
        "evidence_artifact_ids": evidence_artifact_ids,
        "uncertainty_codes": uncertainty_codes,
        "created_at": created_at,
        "execution_authorized": False,
    }
    return ProposalArtifact(
        **values,
        proposal_sha256=_fingerprint(
            ProposalArtifact.schema_id,
            values,
            "proposal_sha256",
        ),
    )


class ActionExecutionIntent(_FrozenModel):
    """Caller-owned immutable values rechecked against the sealed Proposal."""

    schema_id: ClassVar[str] = "gda.action-execution-intent.v1"
    proposal: ProposalArtifact
    parameters: dict[str, Any]
    change_set: ChangeSet
    current_object_versions: tuple[ObjectVersionRef, ...] = Field(
        min_length=1,
        max_length=64,
    )
    policy_decision: PolicyDecision
    policy_decision_artifact_id: UUID
    approval_artifact_id: UUID | None = None
    idempotency_key: NonEmptyText
    channel: ActionInvocationChannel
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None

    @model_validator(mode="after")
    def _agent_correlation(self) -> ActionExecutionIntent:
        if (self.agent_run_id is None) != (self.tool_call_id is None):
            raise ValueError("AgentRun and ToolCall correlations must be set together")
        if self.agent_run_id is not None and self.channel is not ActionInvocationChannel.AGENT:
            raise ValueError("AgentRun correlation requires the agent channel")
        return self


def action_admission_binding(
    definition: ActionTypeDefinition,
    intent: ActionExecutionIntent,
) -> dict[str, Any]:
    values = {
        "schema": "gda.action-admission-binding.v1",
        "tenant_id": definition.tenant_id,
        "action_definition_version_id": str(definition.definition_version_id),
        "action_definition_sha256": definition.definition_sha256,
        "capability_fingerprint": definition.capability.capability_fingerprint,
        "proposal_urn": intent.proposal.proposal_urn,
        "proposal_sha256": intent.proposal.proposal_sha256,
        "target_versions_sha256": canonical_json_fingerprint(
            [item.model_dump(mode="json") for item in intent.current_object_versions]
        ),
        "parameters_sha256": canonical_json_fingerprint(intent.parameters),
        "change_set_sha256": intent.change_set.change_set_sha256,
        "policy_decision_sha256": intent.policy_decision.contract_fingerprint(),
        "idempotency_key": intent.idempotency_key,
        "channel": intent.channel.value,
    }
    return {**values, "binding_sha256": canonical_json_fingerprint(values)}


def build_action_approval_case(
    *,
    definition: ActionTypeDefinition,
    intent: ActionExecutionIntent,
    approval_case_ref: str,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    binding = action_admission_binding(definition, intent)
    return ApprovalCase(
        tenant_id=definition.tenant_id,
        approval_case_ref=approval_case_ref,
        target_resource_urn=intent.proposal.proposal_urn,
        target_fingerprint=binding["binding_sha256"],
        action=definition.capability.policy_action,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=binding,
        requested_at=requested_at,
        expires_at=expires_at,
    )


class ActionExecutorObservation(_FrozenModel):
    schema_id: ClassVar[str] = "gda.action-executor-observation.v1"
    provider_outcome: ProviderOutcome
    actual_changes: tuple[ObjectStateChange, ...] = Field(max_length=64)
    result_document: dict[str, Any]
    receipt_ref: NonEmptyText | None = None
    receipt_sha256: Sha256 | None = None
    output_artifact_ids: tuple[UUID, ...] = Field(max_length=64)
    failure_code: ShortName | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _coherent_outcome(self) -> ActionExecutorObservation:
        if (self.receipt_ref is None) != (self.receipt_sha256 is None):
            raise ValueError("receipt reference and fingerprint must be set together")
        if self.provider_outcome is ProviderOutcome.CONFIRMED:
            if self.failure_code is not None:
                raise ValueError("confirmed outcome cannot contain a failure code")
        elif self.failure_code is None:
            raise ValueError("failed/unknown outcome requires a reason code")
        if self.provider_outcome is ProviderOutcome.UNKNOWN and self.actual_changes:
            raise ValueError("unknown provider outcome cannot assert actual changes")
        return self


class ActionExecutor(Protocol):
    def execute(
        self,
        *,
        definition: ActionTypeDefinition,
        run: PlatformRun,
        parameters: dict[str, Any],
        expected_change: ChangeSet,
    ) -> ActionExecutorObservation: ...


class ActionResult(_FrozenModel):
    schema_id: ClassVar[str] = "gda.action-result.v1"
    tenant_id: TenantId
    run_id: UUID
    proposal_sha256: Sha256
    action_definition_sha256: Sha256
    change_set_sha256: Sha256
    status: ActionResultStatus
    provider_outcome: ProviderOutcome
    change_comparison: ChangeComparison
    actual_changes: tuple[ObjectStateChange, ...]
    output_document_sha256: Sha256
    output_artifact_ids: tuple[UUID, ...]
    receipt_ref: NonEmptyText | None = None
    receipt_sha256: Sha256 | None = None
    failure_code: ShortName | None = None
    reconciliation_required: bool
    compensation_required: bool
    observed_at: datetime
    result_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed_result(self) -> ActionResult:
        if self.status is ActionResultStatus.SUCCEEDED:
            if (
                self.provider_outcome is not ProviderOutcome.CONFIRMED
                or self.change_comparison is not ChangeComparison.EXACT
                or self.reconciliation_required
                or self.failure_code is not None
            ):
                raise ValueError("successful ActionResult lacks exact confirmed evidence")
        if self.provider_outcome is ProviderOutcome.UNKNOWN:
            if (
                self.status is not ActionResultStatus.RECONCILING
                or not self.reconciliation_required
            ):
                raise ValueError("unknown provider result must reconcile")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("ActionResult fingerprint is invalid")
        return self


class ActionOccurrence(_FrozenModel):
    """Correlation view only; PlatformRun remains the execution authority."""

    schema_id: ClassVar[str] = "gda.action-occurrence.v1"
    tenant_id: TenantId
    proposal_sha256: Sha256
    platform_run_id: UUID
    platform_run_status: RunStatus
    result_sha256: Sha256
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None


class ActionExecutionResponse(_FrozenModel):
    schema_id: ClassVar[str] = "gda.action-execution-response.v1"
    occurrence: ActionOccurrence
    result: ActionResult
    replayed: bool


@dataclass
class _LedgerRecord:
    binding_sha256: str
    run: PlatformRun
    result: ActionResult | None = None


class DevelopmentPlatformActionLedger:
    """Thread-safe development adapter storing PlatformRun-correlated results."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, UUID, str], _LedgerRecord] = {}

    def lookup(
        self,
        key: tuple[str, UUID, str],
        binding_sha256: str,
    ) -> _LedgerRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is not None and record.binding_sha256 != binding_sha256:
                raise ActionIdempotencyConflictError(
                    "idempotency key is sealed to a different action intent"
                )
            return record

    def reserve(
        self,
        key: tuple[str, UUID, str],
        binding_sha256: str,
        run: PlatformRun,
    ) -> tuple[_LedgerRecord, bool]:
        with self._lock:
            current = self.lookup(key, binding_sha256)
            if current is not None:
                return current, False
            record = _LedgerRecord(binding_sha256=binding_sha256, run=run)
            self._records[key] = record
            return record, True

    def transition(self, record: _LedgerRecord, status: RunStatus) -> PlatformRun:
        with self._lock:
            validate_run_transition(record.run.status, status)
            record.run = record.run.model_copy(
                update={
                    "status": status,
                    "state_version": record.run.state_version + 1,
                }
            )
            return record.run

    def complete(self, record: _LedgerRecord, result: ActionResult) -> PlatformRun:
        terminal = {
            ActionResultStatus.SUCCEEDED: RunStatus.SUCCEEDED,
            ActionResultStatus.FAILED: RunStatus.FAILED,
            ActionResultStatus.RECONCILING: RunStatus.RECONCILING,
        }[result.status]
        run = self.transition(record, terminal)
        with self._lock:
            record.result = result
        return run


class GovernedActionRuntime:
    """One fail-closed execution path shared by Web/API/MCP/Agent callers."""

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        *,
        ledger: DevelopmentPlatformActionLedger | None = None,
    ) -> None:
        self._capabilities = capability_registry
        self._ledger = ledger or DevelopmentPlatformActionLedger()

    def execute(
        self,
        *,
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        executor: ActionExecutor,
        approval_case: ApprovalCase | None = None,
        now: datetime | None = None,
    ) -> ActionExecutionResponse:
        current_time = _aware_utc(now or datetime.now(UTC))
        capability = self._capabilities.get(
            definition.capability.capability_id,
            definition.capability.capability_version,
        )
        validate_action_capability_binding(definition, capability)
        self._validate_immutable_intent(definition, intent, capability)
        binding = action_admission_binding(definition, intent)
        key = (
            definition.tenant_id,
            definition.definition_version_id,
            intent.idempotency_key,
        )
        existing = self._ledger.lookup(key, binding["binding_sha256"])
        if existing is not None:
            if existing.result is None:
                raise ActionIdempotencyConflictError("action intent is already executing")
            return self._response(existing, intent, replayed=True)

        self._validate_live_admission(
            definition,
            intent,
            capability,
            binding,
            approval_case,
            current_time,
        )
        run = self._platform_run(definition, intent, current_time)
        record, created = self._ledger.reserve(key, binding["binding_sha256"], run)
        if not created:
            if record.result is None:
                raise ActionIdempotencyConflictError("action intent is already executing")
            return self._response(record, intent, replayed=True)

        self._ledger.transition(record, RunStatus.DISPATCHING)
        self._ledger.transition(record, RunStatus.RUNNING)
        try:
            observation = executor.execute(
                definition=definition,
                run=record.run,
                parameters=intent.parameters,
                expected_change=intent.change_set,
            )
            observation = ActionExecutorObservation.model_validate(observation)
            capability.validate_output(observation.result_document)
            if (
                definition.capability.side_effect is SideEffect.EXTERNAL_WRITE
                and observation.receipt_ref is None
            ):
                raise ActionContractError("external-write result lacks a provider receipt")
            result = self._result(definition, intent, observation)
        except Exception:
            result = self._failed_result(definition, intent, current_time)
        self._ledger.complete(record, result)
        return self._response(record, intent, replayed=False)

    @staticmethod
    def _validate_immutable_intent(
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        capability: CapabilitySpec,
    ) -> None:
        proposal = intent.proposal
        if (
            proposal.tenant_id != definition.tenant_id
            or proposal.action_definition_version_id != definition.definition_version_id
            or proposal.action_definition_sha256 != definition.definition_sha256
            or proposal.capability_fingerprint != capability.fingerprint
        ):
            raise ActionAdmissionError("Proposal ActionType or Capability binding drifted")
        validated_parameters = capability.validate_input(intent.parameters)
        if (
            validated_parameters != proposal.parameters
            or canonical_json_fingerprint(intent.parameters) != proposal.parameters_sha256
        ):
            raise ActionAdmissionError("Proposal parameters drifted")
        if intent.change_set != proposal.change_set:
            raise ActionAdmissionError("Proposal ChangeSet drifted")
        if intent.idempotency_key != intent.change_set.idempotency_key:
            raise ActionAdmissionError("Action idempotency key differs from ChangeSet")
        if intent.current_object_versions != intent.change_set.target_versions:
            raise ActionAdmissionError("target object version drifted")
        bindings = {binding.surface: binding for binding in capability.surfaces}
        surface = intent.channel.capability_surface
        if surface not in bindings or bindings[surface].status is not SurfaceStatus.IMPLEMENTED:
            raise ActionAdmissionError("invocation channel is not implemented by Capability")

    @staticmethod
    def _validate_live_admission(
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        capability: CapabilitySpec,
        binding: dict[str, Any],
        approval_case: ApprovalCase | None,
        now: datetime,
    ) -> None:
        decision = intent.policy_decision
        expected_resources = tuple(
            sorted(
                {
                    definition.definition_version_id,
                    *(item.resource_version_id for item in intent.current_object_versions),
                },
                key=str,
            )
        )
        if (
            decision.tenant_id != definition.tenant_id
            or decision.run_id != intent.proposal.proposed_run_id
            or decision.subject_context != intent.proposal.subject_context
            or decision.action != capability.policy.action
            or decision.definition_version_id != definition.definition_version_id
            or decision.resource_version_ids != expected_resources
            or decision.execution_plan_artifact_id != intent.proposal.proposal_artifact_id
            or decision.effect is not PolicyEffect.ALLOW
            or decision.expires_at <= now
            or decision.decided_at > now
        ):
            raise ActionAdmissionError("current PolicyDecision does not admit action")

        approval_required = (
            definition.approval is ActionApprovalRequirement.REQUIRED or decision.requires_approval
        )
        if not approval_required:
            if approval_case is not None or intent.approval_artifact_id is not None:
                raise ActionAdmissionError("unexpected approval binding for non-approved action")
            return
        if approval_case is None or intent.approval_artifact_id is None:
            raise ActionAdmissionError("action requires an approved ApprovalCase")
        if (
            approval_case.tenant_id != definition.tenant_id
            or approval_case.target_resource_urn != intent.proposal.proposal_urn
            or approval_case.target_fingerprint != binding["binding_sha256"]
            or approval_case.action != capability.policy.action
            or approval_case.request_context != binding
            or approval_case.status is not ApprovalCaseStatus.APPROVED
            or approval_case.decided_at is None
            or approval_case.decided_at > now
            or approval_case.expires_at <= now
        ):
            raise ActionAdmissionError("ApprovalCase does not bind the current action intent")

    @staticmethod
    def _platform_run(
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        submitted_at: datetime,
    ) -> PlatformRun:
        input_bindings = tuple(
            ResourceBinding(
                binding_name=f"target_{index}",
                resource_version_id=target.resource_version_id,
                semantic_type=target.object_type,
            )
            for index, target in enumerate(intent.current_object_versions)
        )
        return PlatformRun(
            tenant_id=definition.tenant_id,
            run_id=intent.proposal.proposed_run_id,
            definition_version_id=definition.definition_version_id,
            orchestration_class=OrchestrationClass.ACTION,
            subject_context=intent.proposal.subject_context,
            input_bindings=input_bindings,
            idempotency_key=intent.idempotency_key,
            policy_refs=RunPolicyReferences(
                policy_decision_artifact_id=intent.policy_decision_artifact_id,
                approval_artifact_id=intent.approval_artifact_id,
            ),
            config_fingerprint=intent.proposal.proposal_sha256,
            submitted_at=submitted_at,
        )

    @staticmethod
    def _result(
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        observation: ActionExecutorObservation,
    ) -> ActionResult:
        if observation.provider_outcome is ProviderOutcome.UNKNOWN:
            comparison = ChangeComparison.NOT_OBSERVED
            status = ActionResultStatus.RECONCILING
            reconcile = True
            compensate = False
        else:
            exact = observation.actual_changes == intent.change_set.expected_changes
            comparison = ChangeComparison.EXACT if exact else ChangeComparison.OUT_OF_BOUNDS
            if observation.provider_outcome is ProviderOutcome.FAILED:
                reconcile = bool(observation.actual_changes)
                status = ActionResultStatus.RECONCILING if reconcile else ActionResultStatus.FAILED
            elif exact:
                status = ActionResultStatus.SUCCEEDED
                reconcile = False
            elif definition.capability.side_effect is SideEffect.NONE:
                status = ActionResultStatus.FAILED
                reconcile = False
            else:
                status = ActionResultStatus.RECONCILING
                reconcile = True
            compensate = (
                comparison is ChangeComparison.OUT_OF_BOUNDS and definition.capability.compensatable
            )
        values: dict[str, Any] = {
            "tenant_id": definition.tenant_id,
            "run_id": intent.proposal.proposed_run_id,
            "proposal_sha256": intent.proposal.proposal_sha256,
            "action_definition_sha256": definition.definition_sha256,
            "change_set_sha256": intent.change_set.change_set_sha256,
            "status": status,
            "provider_outcome": observation.provider_outcome,
            "change_comparison": comparison,
            "actual_changes": observation.actual_changes,
            "output_document_sha256": canonical_json_fingerprint(observation.result_document),
            "output_artifact_ids": observation.output_artifact_ids,
            "receipt_ref": observation.receipt_ref,
            "receipt_sha256": observation.receipt_sha256,
            "failure_code": observation.failure_code,
            "reconciliation_required": reconcile,
            "compensation_required": compensate,
            "observed_at": observation.observed_at,
        }
        return ActionResult(
            **values,
            result_sha256=_fingerprint(
                ActionResult.schema_id,
                values,
                "result_sha256",
            ),
        )

    @staticmethod
    def _failed_result(
        definition: ActionTypeDefinition,
        intent: ActionExecutionIntent,
        observed_at: datetime,
    ) -> ActionResult:
        outcome_unknown = definition.capability.side_effect is SideEffect.EXTERNAL_WRITE
        values: dict[str, Any] = {
            "tenant_id": definition.tenant_id,
            "run_id": intent.proposal.proposed_run_id,
            "proposal_sha256": intent.proposal.proposal_sha256,
            "action_definition_sha256": definition.definition_sha256,
            "change_set_sha256": intent.change_set.change_set_sha256,
            "status": (
                ActionResultStatus.RECONCILING if outcome_unknown else ActionResultStatus.FAILED
            ),
            "provider_outcome": (
                ProviderOutcome.UNKNOWN if outcome_unknown else ProviderOutcome.FAILED
            ),
            "change_comparison": ChangeComparison.NOT_OBSERVED,
            "actual_changes": (),
            "output_document_sha256": canonical_json_fingerprint({}),
            "output_artifact_ids": (),
            "receipt_ref": None,
            "receipt_sha256": None,
            "failure_code": (
                "executor_outcome_unknown" if outcome_unknown else "executor_contract_failure"
            ),
            "reconciliation_required": outcome_unknown,
            "compensation_required": False,
            "observed_at": observed_at,
        }
        return ActionResult(
            **values,
            result_sha256=_fingerprint(
                ActionResult.schema_id,
                values,
                "result_sha256",
            ),
        )

    @staticmethod
    def _response(
        record: _LedgerRecord,
        intent: ActionExecutionIntent,
        *,
        replayed: bool,
    ) -> ActionExecutionResponse:
        if record.result is None:
            raise ActionIdempotencyConflictError("action result is not available")
        occurrence = ActionOccurrence(
            tenant_id=record.run.tenant_id,
            proposal_sha256=intent.proposal.proposal_sha256,
            platform_run_id=record.run.run_id,
            platform_run_status=record.run.status,
            result_sha256=record.result.result_sha256,
            agent_run_id=intent.agent_run_id,
            tool_call_id=intent.tool_call_id,
        )
        return ActionExecutionResponse(
            occurrence=occurrence,
            result=record.result,
            replayed=replayed,
        )


def default_action_approval_case_ref(
    tenant_id: str,
    proposal_sha256: str,
) -> str:
    return build_resource_urn(
        tenant_id,
        "approval_case",
        f"action-{proposal_sha256[:32]}",
    )


__all__ = [
    "ActionAdmissionError",
    "ActionApprovalRequirement",
    "ActionContractError",
    "ActionExecutionIntent",
    "ActionExecutionResponse",
    "ActionExecutor",
    "ActionExecutorObservation",
    "ActionIdempotencyConflictError",
    "ActionInvocationChannel",
    "ActionOccurrence",
    "ActionResult",
    "ActionResultStatus",
    "ActionSideEffectLevel",
    "ActionTypeDefinition",
    "ChangeComparison",
    "ChangeOperation",
    "ChangeSet",
    "DevelopmentPlatformActionLedger",
    "GovernedActionRuntime",
    "ObjectStateChange",
    "ObjectVersionRef",
    "ProposalArtifact",
    "ProviderOutcome",
    "action_admission_binding",
    "build_action_approval_case",
    "build_action_type_definition",
    "build_change_set",
    "build_proposal_artifact",
    "default_action_approval_case_ref",
    "validate_action_capability_binding",
]
