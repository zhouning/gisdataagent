from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest

from data_agent.action_runtime import (
    ActionAdmissionError,
    ActionApprovalRequirement,
    ActionExecutionIntent,
    ActionExecutorObservation,
    ActionIdempotencyConflictError,
    ActionInvocationChannel,
    ActionResultStatus,
    ActionSideEffectLevel,
    ChangeComparison,
    ChangeOperation,
    GovernedActionRuntime,
    ObjectStateChange,
    ObjectVersionRef,
    ProviderOutcome,
    build_action_approval_case,
    build_action_type_definition,
    build_change_set,
    build_proposal_artifact,
    default_action_approval_case_ref,
)
from data_agent.capability_registry import (
    CapabilityRegistry,
    CapabilitySpec,
    ExecutionContract,
    IdempotencyMode,
    OperationKind,
    PolicyContract,
    PreviewMode,
    ResultMode,
    RiskClass,
    SemanticJsonSchema,
    SideEffect,
    Surface,
    SurfaceBinding,
    SurfaceStatus,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    PolicyDecision,
    SubjectContext,
    build_resource_urn,
)

TENANT = "tenant-action"
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
DEFINITION_ID = UUID("71000000-0000-4000-8000-000000000001")
TARGET_VERSION_ID = UUID("71000000-0000-4000-8000-000000000002")
PROPOSAL_VERSION_ID = UUID("71000000-0000-4000-8000-000000000003")
PROPOSAL_ARTIFACT_ID = UUID("71000000-0000-4000-8000-000000000004")
RUN_ID = UUID("71000000-0000-4000-8000-000000000005")
POLICY_ARTIFACT_ID = UUID("71000000-0000-4000-8000-000000000006")
APPROVAL_ARTIFACT_ID = UUID("71000000-0000-4000-8000-000000000007")
EVIDENCE_ARTIFACT_ID = UUID("71000000-0000-4000-8000-000000000008")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _schema(semantic_type: str, *, output: bool = False) -> SemanticJsonSchema:
    if output:
        properties = {"status": {"type": "string", "enum": ["accepted"]}}
        required = ["status"]
    else:
        properties = {
            "object_id": {"type": "string", "minLength": 1},
            "value": {"type": "integer", "minimum": 0},
        }
        required = ["object_id", "value"]
    return SemanticJsonSchema(
        semantic_type=semantic_type,
        json_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    )


def _surfaces() -> tuple[SurfaceBinding, ...]:
    return (
        SurfaceBinding(
            surface=Surface.WEB,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="action_runtime.execute",
        ),
        SurfaceBinding(
            surface=Surface.API,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="action_runtime.execute",
        ),
        SurfaceBinding(
            surface=Surface.AGENT,
            status=SurfaceStatus.IMPLEMENTED,
            entrypoint="action_runtime.execute",
        ),
    )


def _capability(*, l3: bool) -> CapabilitySpec:
    suffix = "write" if l3 else "derive"
    return CapabilitySpec(
        capability_id=f"action.fixture.{suffix}",
        version="1.0.0",
        title=f"Action fixture {suffix}",
        description=f"Deterministic {suffix} capability for Action runtime tests",
        owner="action.runtime",
        tier="P1",
        lifecycle="active",
        operation=OperationKind.COMMAND if l3 else OperationKind.QUERY,
        risk=RiskClass.HIGH if l3 else RiskClass.LOW,
        side_effect=SideEffect.EXTERNAL_WRITE if l3 else SideEffect.NONE,
        input=_schema(f"gda.action.fixture.{suffix}.input.v1"),
        output=_schema(f"gda.action.fixture.{suffix}.output.v1", output=True),
        policy=PolicyContract(
            action=f"action.fixture.{suffix}.execute",
            allowed_roles=("editor",),
            resource_kinds=("dataset",),
        ),
        execution=ExecutionContract(
            idempotency=(IdempotencyMode.REQUIRED if l3 else IdempotencyMode.NOT_APPLICABLE),
            preview=PreviewMode.REQUIRED if l3 else PreviewMode.UNSUPPORTED,
            result=ResultMode.SYNCHRONOUS,
            compensatable=l3,
            reconcilable=l3,
        ),
        surfaces=_surfaces(),
    )


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id=TENANT,
        subject_id="developer-1",
        subject_type="human",
        roles=("editor",),
        purpose="develop governed action runtime",
        trace_id="trace-action-1",
    )


def _target(*, sha256: str = SHA_A) -> ObjectVersionRef:
    return ObjectVersionRef(
        tenant_id=TENANT,
        object_urn=build_resource_urn(TENANT, "dataset", "parcel-001"),
        object_type="gis.dataset",
        resource_version_id=TARGET_VERSION_ID,
        content_sha256=sha256,
    )


def _definition(capability: CapabilitySpec, *, l3: bool):
    return build_action_type_definition(
        tenant_id=TENANT,
        definition_urn=build_resource_urn(
            TENANT,
            "definition",
            "parcel-update" if l3 else "parcel-derive",
        ),
        definition_version_id=DEFINITION_ID,
        action_type_id="parcel.update" if l3 else "parcel.derive",
        version="1.0.0",
        target_object_types=("gis.dataset",),
        allowed_change_operations=((ChangeOperation.UPDATE,) if l3 else (ChangeOperation.DERIVE,)),
        required_evidence_types=(("quality-report",) if l3 else ()),
        side_effect_level=(ActionSideEffectLevel.L3 if l3 else ActionSideEffectLevel.L1),
        approval=(
            ActionApprovalRequirement.REQUIRED if l3 else ActionApprovalRequirement.NOT_REQUIRED
        ),
        capability=capability,
        evaluator_ref="evaluator:action-result@1.0.0",
        compensation_ref="capability:parcel.restore@1.0.0" if l3 else None,
    )


def _fixture(
    *,
    l3: bool,
    channel: ActionInvocationChannel = ActionInvocationChannel.API,
    idempotency_key: str | None = None,
):
    capability = _capability(l3=l3)
    definition = _definition(capability, l3=l3)
    target = _target()
    change = (
        ObjectStateChange(
            object_urn=target.object_urn,
            operation=ChangeOperation.UPDATE,
            before_version_id=target.resource_version_id,
            before_sha256=target.content_sha256,
            after_sha256=SHA_B,
        )
        if l3
        else ObjectStateChange(
            object_urn=build_resource_urn(TENANT, "artifact", "parcel-summary"),
            operation=ChangeOperation.DERIVE,
            after_sha256=SHA_B,
        )
    )
    key = idempotency_key or ("parcel-write-001" if l3 else "parcel-derive-001")
    change_set = build_change_set(
        tenant_id=TENANT,
        action_definition_sha256=definition.definition_sha256,
        target_versions=(target,),
        expected_changes=(change,),
        idempotency_key=key,
        compensation_ref=definition.compensation_ref,
    )
    proposal = build_proposal_artifact(
        definition=definition,
        capability=capability,
        proposal_urn=build_resource_urn(
            TENANT,
            "proposal",
            "parcel-write-001" if l3 else "parcel-derive-001",
        ),
        proposal_version_id=PROPOSAL_VERSION_ID,
        proposal_artifact_id=PROPOSAL_ARTIFACT_ID,
        proposed_run_id=RUN_ID,
        subject_context=_subject(),
        parameters={"object_id": "parcel-001", "value": 7},
        change_set=change_set,
        evidence_artifact_ids=((EVIDENCE_ARTIFACT_ID,) if l3 else ()),
        uncertainty_codes=(),
        created_at=NOW - timedelta(minutes=10),
    )
    resources = tuple(sorted((DEFINITION_ID, TARGET_VERSION_ID), key=str))
    policy = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=_subject(),
        action=capability.policy.action,
        definition_version_id=DEFINITION_ID,
        resource_version_ids=resources,
        execution_plan_artifact_id=PROPOSAL_ARTIFACT_ID,
        effect="allow",
        policy_version_ref="policy:action@1.0.0",
        evaluator_subject="workload:policy-engine",
        requires_approval=l3,
        decided_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
    )
    intent = ActionExecutionIntent(
        proposal=proposal,
        parameters=proposal.parameters,
        change_set=change_set,
        current_object_versions=(target,),
        policy_decision=policy,
        policy_decision_artifact_id=POLICY_ARTIFACT_ID,
        approval_artifact_id=APPROVAL_ARTIFACT_ID if l3 else None,
        idempotency_key=key,
        channel=channel,
    )
    approval = None
    if l3:
        pending = build_action_approval_case(
            definition=definition,
            intent=intent,
            approval_case_ref=default_action_approval_case_ref(
                TENANT,
                proposal.proposal_sha256,
            ),
            requester_subject="agent:planner",
            request_reason="review bounded parcel update",
            requested_at=NOW - timedelta(minutes=4),
            expires_at=NOW + timedelta(minutes=20),
        )
        approval = ApprovalCase.model_validate(
            {
                **pending.model_dump(mode="python"),
                "status": ApprovalCaseStatus.APPROVED,
                "state_version": 1,
                "decided_by": "human:reviewer",
                "decision_reason": "bounded change accepted",
                "decided_at": NOW - timedelta(minutes=1),
            }
        )
    return capability, definition, intent, approval


class _Executor:
    def __init__(
        self,
        *,
        outcome: ProviderOutcome = ProviderOutcome.CONFIRMED,
        actual_changes: tuple[ObjectStateChange, ...] | None = None,
    ) -> None:
        self.outcome = outcome
        self.actual_changes = actual_changes
        self.calls = 0

    def execute(self, *, definition, run, parameters, expected_change):
        self.calls += 1
        external = definition.capability.side_effect is SideEffect.EXTERNAL_WRITE
        return ActionExecutorObservation(
            provider_outcome=self.outcome,
            actual_changes=(
                ()
                if self.outcome is ProviderOutcome.UNKNOWN
                else self.actual_changes or expected_change.expected_changes
            ),
            result_document={"status": "accepted"},
            receipt_ref=("provider:receipt-001" if external else None),
            receipt_sha256=(SHA_C if external else None),
            output_artifact_ids=(),
            failure_code=(
                "provider_outcome_unknown"
                if self.outcome is ProviderOutcome.UNKNOWN
                else ("provider_rejected" if self.outcome is ProviderOutcome.FAILED else None)
            ),
            observed_at=NOW,
        )


def _runtime(capability: CapabilitySpec) -> GovernedActionRuntime:
    return GovernedActionRuntime(CapabilityRegistry((capability,)))


def test_action_type_is_a_platform_definition_not_a_second_scheduler() -> None:
    capability, definition, _intent, _approval = _fixture(l3=True)

    platform_definition = definition.to_platform_definition()

    assert platform_definition.orchestration_class.value == "action"
    assert platform_definition.capability_id == capability.capability_id
    assert platform_definition.definition_version_id == definition.definition_version_id
    assert platform_definition.definition_sha256 == definition.definition_sha256


@pytest.mark.parametrize(
    "channel",
    [
        ActionInvocationChannel.WEB,
        ActionInvocationChannel.API,
        ActionInvocationChannel.MCP,
        ActionInvocationChannel.AGENT,
    ],
)
def test_l1_uses_one_runtime_for_web_api_mcp_and_agent(channel) -> None:
    capability, definition, intent, _approval = _fixture(
        l3=False,
        channel=channel,
    )
    executor = _Executor()

    response = _runtime(capability).execute(
        definition=definition,
        intent=intent,
        executor=executor,
        now=NOW,
    )

    assert executor.calls == 1
    assert response.result.status is ActionResultStatus.SUCCEEDED
    assert response.result.change_comparison is ChangeComparison.EXACT
    assert response.occurrence.platform_run_status.value == "succeeded"
    assert response.occurrence.platform_run_id == RUN_ID
    assert response.replayed is False


def test_unapproved_l3_has_zero_executor_calls() -> None:
    capability, definition, intent, _approval = _fixture(l3=True)
    executor = _Executor()

    with pytest.raises(ActionAdmissionError, match="requires an approved"):
        _runtime(capability).execute(
            definition=definition,
            intent=intent,
            executor=executor,
            approval_case=None,
            now=NOW,
        )

    assert executor.calls == 0


def test_approved_l3_binds_receipt_and_succeeds() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    executor = _Executor()

    response = _runtime(capability).execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )

    assert executor.calls == 1
    assert response.result.status is ActionResultStatus.SUCCEEDED
    assert response.result.receipt_ref == "provider:receipt-001"
    assert response.result.receipt_sha256 == SHA_C
    assert response.result.reconciliation_required is False


@pytest.mark.parametrize(
    "drift",
    ["parameters", "change_set", "object_version", "policy", "proposal"],
)
def test_l3_drift_after_approval_has_zero_executor_calls(drift) -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    if drift == "parameters":
        intent = intent.model_copy(update={"parameters": {"object_id": "parcel-001", "value": 8}})
    elif drift == "change_set":
        changed = ObjectStateChange(
            object_urn=intent.change_set.expected_changes[0].object_urn,
            operation=ChangeOperation.UPDATE,
            before_version_id=TARGET_VERSION_ID,
            before_sha256=SHA_A,
            after_sha256=SHA_C,
        )
        intent = intent.model_copy(
            update={
                "change_set": build_change_set(
                    tenant_id=TENANT,
                    action_definition_sha256=definition.definition_sha256,
                    target_versions=intent.current_object_versions,
                    expected_changes=(changed,),
                    idempotency_key=intent.idempotency_key,
                    compensation_ref=definition.compensation_ref,
                )
            }
        )
    elif drift == "object_version":
        intent = intent.model_copy(update={"current_object_versions": (_target(sha256=SHA_C),)})
    elif drift == "policy":
        intent = intent.model_copy(
            update={
                "policy_decision": intent.policy_decision.model_copy(
                    update={"policy_version_ref": "policy:action@1.0.1"}
                )
            }
        )
    else:
        alternate = build_proposal_artifact(
            definition=definition,
            capability=capability,
            proposal_urn=build_resource_urn(TENANT, "proposal", "parcel-write-002"),
            proposal_version_id=UUID("72000000-0000-4000-8000-000000000003"),
            proposal_artifact_id=PROPOSAL_ARTIFACT_ID,
            proposed_run_id=RUN_ID,
            subject_context=_subject(),
            parameters=intent.parameters,
            change_set=intent.change_set,
            evidence_artifact_ids=(EVIDENCE_ARTIFACT_ID,),
            uncertainty_codes=(),
            created_at=NOW - timedelta(minutes=9),
        )
        intent = intent.model_copy(update={"proposal": alternate})
    executor = _Executor()

    with pytest.raises(ActionAdmissionError):
        _runtime(capability).execute(
            definition=definition,
            intent=intent,
            executor=executor,
            approval_case=approval,
            now=NOW,
        )

    assert executor.calls == 0


def test_exact_idempotent_retry_has_no_duplicate_side_effect() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    runtime = _runtime(capability)
    executor = _Executor()

    first = runtime.execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )
    replay = runtime.execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )

    assert executor.calls == 1
    assert first.result == replay.result
    assert replay.replayed is True


def test_concurrent_same_key_cannot_duplicate_side_effect() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    runtime = _runtime(capability)
    entered = Event()
    release = Event()

    class _BlockingExecutor(_Executor):
        def execute(self, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return super().execute(**kwargs)

    executor = _BlockingExecutor()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            runtime.execute,
            definition=definition,
            intent=intent,
            executor=executor,
            approval_case=approval,
            now=NOW,
        )
        assert entered.wait(timeout=5)
        with pytest.raises(ActionIdempotencyConflictError, match="already executing"):
            runtime.execute(
                definition=definition,
                intent=intent,
                executor=executor,
                approval_case=approval,
                now=NOW,
            )
        release.set()
        assert first.result(timeout=5).result.status is ActionResultStatus.SUCCEEDED

    assert executor.calls == 1


def test_same_idempotency_key_rejects_a_different_sealed_proposal() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    runtime = _runtime(capability)
    executor = _Executor()
    runtime.execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )
    alternate = build_proposal_artifact(
        definition=definition,
        capability=capability,
        proposal_urn=build_resource_urn(TENANT, "proposal", "parcel-write-replay"),
        proposal_version_id=UUID("73000000-0000-4000-8000-000000000003"),
        proposal_artifact_id=PROPOSAL_ARTIFACT_ID,
        proposed_run_id=RUN_ID,
        subject_context=_subject(),
        parameters=intent.parameters,
        change_set=intent.change_set,
        evidence_artifact_ids=(EVIDENCE_ARTIFACT_ID,),
        uncertainty_codes=(),
        created_at=NOW - timedelta(minutes=8),
    )
    changed_intent = intent.model_copy(update={"proposal": alternate})
    changed_pending = build_action_approval_case(
        definition=definition,
        intent=changed_intent,
        approval_case_ref=default_action_approval_case_ref(
            TENANT,
            alternate.proposal_sha256,
        ),
        requester_subject="agent:planner",
        request_reason="review alternate sealed proposal",
        requested_at=NOW - timedelta(minutes=4),
        expires_at=NOW + timedelta(minutes=20),
    )
    changed_approval = ApprovalCase.model_validate(
        {
            **changed_pending.model_dump(mode="python"),
            "status": "approved",
            "state_version": 1,
            "decided_by": "human:reviewer",
            "decision_reason": "alternate accepted",
            "decided_at": NOW - timedelta(minutes=1),
        }
    )

    with pytest.raises(ActionIdempotencyConflictError):
        runtime.execute(
            definition=definition,
            intent=changed_intent,
            executor=executor,
            approval_case=changed_approval,
            now=NOW,
        )

    assert executor.calls == 1


def test_actual_change_outside_change_set_enters_reconciliation() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    extra = ObjectStateChange(
        object_urn=build_resource_urn(TENANT, "dataset", "parcel-002"),
        operation=ChangeOperation.UPDATE,
        before_version_id=UUID("71000000-0000-4000-8000-000000000009"),
        before_sha256=SHA_A,
        after_sha256=SHA_C,
    )
    executor = _Executor(
        actual_changes=(*intent.change_set.expected_changes, extra),
    )

    response = _runtime(capability).execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )

    assert response.result.status is ActionResultStatus.RECONCILING
    assert response.result.change_comparison is ChangeComparison.OUT_OF_BOUNDS
    assert response.result.reconciliation_required is True
    assert response.result.compensation_required is True
    assert response.occurrence.platform_run_status.value == "reconciling"


def test_unknown_external_receipt_never_records_success() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    executor = _Executor(outcome=ProviderOutcome.UNKNOWN)

    response = _runtime(capability).execute(
        definition=definition,
        intent=intent,
        executor=executor,
        approval_case=approval,
        now=NOW,
    )

    assert response.result.provider_outcome is ProviderOutcome.UNKNOWN
    assert response.result.status is ActionResultStatus.RECONCILING
    assert response.result.change_comparison is ChangeComparison.NOT_OBSERVED
    assert response.result.reconciliation_required is True
    assert response.occurrence.platform_run_status.value == "reconciling"


def test_expired_policy_and_rejected_approval_are_fail_closed() -> None:
    capability, definition, intent, approval = _fixture(l3=True)
    expired = intent.model_copy(
        update={"policy_decision": intent.policy_decision.model_copy(update={"expires_at": NOW})}
    )
    executor = _Executor()
    with pytest.raises(ActionAdmissionError, match="PolicyDecision"):
        _runtime(capability).execute(
            definition=definition,
            intent=expired,
            executor=executor,
            approval_case=approval,
            now=NOW,
        )

    rejected = ApprovalCase.model_validate(
        {
            **approval.model_dump(mode="python"),
            "status": "rejected",
            "decision_reason": "rejected during development test",
        }
    )
    with pytest.raises(ActionAdmissionError, match="ApprovalCase"):
        _runtime(capability).execute(
            definition=definition,
            intent=intent,
            executor=executor,
            approval_case=rejected,
            now=NOW,
        )

    assert executor.calls == 0
