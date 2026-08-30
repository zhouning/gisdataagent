import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from data_agent.dataops_invocation import (
    DATAOPS_INVOCATION_SEMANTIC_TYPE,
    DataOpsInvocation,
    build_dataops_invocation_resources,
    dataops_invocation_version_id,
)
from data_agent.dolphinscheduler_adapter import (
    DOLPHINSCHEDULER_BINDING_MEDIA_TYPE,
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerConfigurationError,
    DolphinSchedulerContractError,
    DolphinSchedulerCorrelationConflictError,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerInstance,
    DolphinSchedulerProfile,
    DolphinSchedulerProtocolError,
    DolphinSchedulerReconciliationRequired,
    DolphinSchedulerRejectedError,
    DolphinSchedulerUnavailableError,
    _read_token_file,
    build_dolphinscheduler_adapter_report,
    build_dolphinscheduler_binding_artifact,
    compile_dolphinscheduler_workflow,
    parse_dolphinscheduler_binding_artifact,
)
from data_agent.platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
)
from data_agent.platform_contracts import (
    ApprovalRecord,
    ArtifactRole,
    OrchestrationClass,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    PolicyEffect,
    ResourceBinding,
    RunPolicyReferences,
    RunStatus,
    SubjectContext,
    platform_definition_fingerprint,
    validate_run_transition,
)
from data_agent.platform_gateway import GatewayNotFoundError, GatewayWriteResult

TENANT = "tenant-a"
DEFINITION_ID = UUID("20000000-0000-4000-8000-000000000010")
RUN_ID = UUID("20000000-0000-4000-8000-000000000020")
SOURCE_ID = UUID("20000000-0000-4000-8000-000000000030")
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
ACTOR = "workload:dataops-adapter"
POLICY_EVALUATOR = "workload:policy-evaluator"
APPROVER = "human:dataops-approver"


def _profile(**overrides):
    values = {
        "base_url": "https://ds.example.test/dolphinscheduler",
        "access_token": "sandbox-token-value",
        "project_code": 123456789,
        "workload_subject": ACTOR,
        "policy_evaluator_subject": POLICY_EVALUATOR,
        "tenant_code": "gda",
        "worker_group": "gda-dataops",
        "cancel_terminal_stop_capability": "certified",
        "cancel_terminal_stop_evidence_ref": "gda://tenant-a/evidence/dolphinscheduler-cancel:v1",
    }
    values.update(overrides)
    return DolphinSchedulerProfile(**values)


def _definition(**document_overrides):
    provider_document = {
        "name": "gda_land_use_publish_v1",
        "description": "Publish the controlled land-use slice",
        "task_definitions": [
            {
                "code": 1001,
                "name": "publish",
                "taskType": "SHELL",
                "taskParams": {"rawScript": "true"},
            }
        ],
        "task_relations": [{"preTaskCode": 0, "postTaskCode": 1001}],
        "locations": [{"taskCode": 1001, "x": 120, "y": 80}],
        "global_params": [
            {"prop": "business_date", "direct": "IN", "type": "VARCHAR", "value": ""}
        ],
    }
    provider_document.update(document_overrides)
    definition_document = {"dolphinscheduler": provider_document}
    input_contract = {"source": "gis.land_use.parcels"}
    output_contract = {"product": "gis.land_use.parcels.standardized"}
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="land_use.publish",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=f"gda://{TENANT}/definition/land-use-publish",
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        capability_id="land_use.publish",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def _run(**overrides):
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "subject_context": SubjectContext(
            tenant_id=TENANT,
            subject_id="dataops-adapter",
            subject_type="workload",
            roles=("platform_operator",),
            purpose="publish controlled land-use slice",
        ),
        "input_bindings": (
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.land_use.parcels",
            },
        ),
        "idempotency_key": "land-use:publish:snapshot-1",
        "submitted_at": NOW,
    }
    values.update(overrides)
    return PlatformRun(**values)


def _backfill_invocation(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_version_id": DEFINITION_ID,
        "trigger_kind": "backfill",
        "logical_start": datetime(2026, 7, 1, tzinfo=UTC),
        "logical_end": datetime(2026, 7, 3, tzinfo=UTC),
        "schedule_times": (datetime(2026, 7, 1, tzinfo=UTC),),
        "schedule_ref": "gda://tenant-a/schedule/land-use-daily",
        "requested_by": "human:data-platform-operator",
        "requested_at": NOW - timedelta(minutes=1),
    }
    values.update(overrides)
    return DataOpsInvocation.create(**values)


def _schedule_invocation(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_version_id": DEFINITION_ID,
        "trigger_kind": "schedule",
        "logical_start": datetime(2026, 7, 1, tzinfo=UTC),
        "logical_end": datetime(2026, 7, 2, tzinfo=UTC),
        "schedule_times": (datetime(2026, 7, 2, 0, 5, tzinfo=UTC),),
        "schedule_ref": "gda://tenant-a/schedule/land-use-daily",
        "requested_by": ACTOR,
        "requested_at": NOW - timedelta(minutes=1),
    }
    values.update(overrides)
    return DataOpsInvocation.create(**values)


def _manual_invocation(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_version_id": DEFINITION_ID,
        "trigger_kind": "manual",
        "logical_start": datetime(2026, 7, 1, tzinfo=UTC),
        "logical_end": datetime(2026, 7, 2, tzinfo=UTC),
        "requested_by": "human:data-platform-operator",
        "requested_at": NOW - timedelta(minutes=1),
        "client_request_id": "operator-console-20260801-001",
    }
    values.update(overrides)
    return DataOpsInvocation.create(**values)


def _binding():
    spec = compile_dolphinscheduler_workflow(_definition())
    return DolphinSchedulerDefinitionBinding(
        tenant_id=TENANT,
        definition_version_id=DEFINITION_ID,
        project_code=123456789,
        workflow_definition_code=987654321,
        workflow_definition_version=1,
        compiled_sha256=spec.compiled_sha256,
    )


class _FakeGateway:
    def __init__(
        self,
        *,
        authorized=True,
        policy_effect=PolicyEffect.ALLOW,
        requires_approval=False,
        include_approval=True,
        approval_verdict="approved",
        policy_evaluator=POLICY_EVALUATOR,
        invocation=None,
    ):
        self.transitions = []
        self.cancellation_incidents = []
        self.observations = {}
        self.artifacts = {}
        self.resource_versions = {}
        run = _run()
        if invocation is not None:
            _resource, invocation_version = build_dataops_invocation_resources(invocation)
            self.resource_versions[invocation_version.resource_version_id] = invocation_version
            run = run.model_copy(
                update={
                    "input_bindings": (
                        *run.input_bindings,
                        ResourceBinding(
                            binding_name="invocation",
                            resource_version_id=invocation_version.resource_version_id,
                            semantic_type=DATAOPS_INVOCATION_SEMANTIC_TYPE,
                        ),
                    )
                }
            )
        if not authorized:
            self.run = run
            return
        binding_artifact = build_dolphinscheduler_binding_artifact(
            _binding(), created_by=ACTOR, created_at=NOW
        )
        decision = PolicyDecision(
            tenant_id=TENANT,
            run_id=RUN_ID,
            subject_context=run.subject_context,
            action="dolphinscheduler.dispatch",
            definition_version_id=DEFINITION_ID,
            resource_version_ids=tuple(
                sorted(
                    {
                        DEFINITION_ID,
                        *(item.resource_version_id for item in run.input_bindings),
                    },
                    key=str,
                )
            ),
            execution_plan_artifact_id=binding_artifact.artifact_id,
            effect=policy_effect,
            policy_version_ref="gda://tenant-a/policy/dataops-dispatch:v1",
            evaluator_subject=policy_evaluator,
            requires_approval=requires_approval,
            decided_at=NOW,
            expires_at=NOW + timedelta(days=3650),
        )
        decision_artifact = build_policy_decision_artifact(decision)
        approval_artifact = None
        if requires_approval and include_approval:
            approval_artifact = build_approval_artifact(
                ApprovalRecord(
                    tenant_id=TENANT,
                    run_id=RUN_ID,
                    definition_version_id=DEFINITION_ID,
                    policy_decision_artifact_id=decision_artifact.artifact_id,
                    policy_decision_sha256=decision_artifact.content_sha256,
                    verdict=approval_verdict,
                    approver_subject=APPROVER,
                    reason="approved controlled land-use publication",
                    decided_at=NOW + timedelta(minutes=1),
                    expires_at=decision.expires_at,
                )
            )
        self.artifacts = {
            binding_artifact.artifact_id: binding_artifact,
            decision_artifact.artifact_id: decision_artifact,
        }
        if approval_artifact is not None:
            self.artifacts[approval_artifact.artifact_id] = approval_artifact
        self.run = run.model_copy(
            update={
                "policy_refs": RunPolicyReferences(
                    policy_decision_artifact_id=decision_artifact.artifact_id,
                    approval_artifact_id=(
                        approval_artifact.artifact_id if approval_artifact is not None else None
                    ),
                )
            }
        )

    def get_run(self, tenant_id, run_id):
        assert tenant_id == self.run.tenant_id
        assert run_id == self.run.run_id
        return self.run

    def transition_run(
        self,
        tenant_id,
        run_id,
        expected_state_version,
        to_status,
        actor_subject,
        reason,
        details=None,
    ):
        assert tenant_id == self.run.tenant_id
        assert run_id == self.run.run_id
        assert expected_state_version == self.run.state_version
        target = RunStatus(to_status)
        validate_run_transition(self.run.status, target)
        self.run = self.run.model_copy(
            update={"status": target, "state_version": self.run.state_version + 1}
        )
        self.transitions.append((target, actor_subject, reason, details or {}))
        return self.run

    def record_attempt(self, observation):
        existing = self.observations.get(observation.observation_id)
        if existing is not None:
            assert existing == observation
            return GatewayWriteResult(existing, False)
        self.observations[observation.observation_id] = observation
        return GatewayWriteResult(observation, True)

    def record_cancellation_terminal_mismatch(self, observation, *, actor_subject):
        self.cancellation_incidents.append(observation)
        run = self.transition_run(
            self.run.tenant_id,
            self.run.run_id,
            self.run.state_version,
            RunStatus.FAILED,
            actor_subject,
            "provider cancellation did not converge to STOP",
            {"observation_id": str(observation.observation_id)},
        )
        return SimpleNamespace(run=run)

    def record_artifact(self, artifact):
        existing = self.artifacts.get(artifact.artifact_id)
        if existing is not None:
            assert existing == artifact
            return GatewayWriteResult(existing, False)
        self.artifacts[artifact.artifact_id] = artifact
        return GatewayWriteResult(artifact, True)

    def get_artifact(self, tenant_id, artifact_id):
        artifact = self.artifacts.get(artifact_id)
        if artifact is None or artifact.tenant_id != tenant_id:
            raise GatewayNotFoundError("Artifact was not found")
        return artifact

    def get_resource_version(self, tenant_id, resource_version_id):
        version = self.resource_versions.get(resource_version_id)
        if version is None or version.tenant_id != tenant_id:
            raise GatewayNotFoundError("ResourceVersion was not found")
        return version


def _cancel_policy_artifact_id(gateway: _FakeGateway, plan_id: UUID) -> UUID:
    run = gateway.run
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=run.subject_context,
        action="dolphinscheduler.cancel",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=tuple(
            sorted(
                {
                    DEFINITION_ID,
                    *(item.resource_version_id for item in run.input_bindings),
                },
                key=str,
            )
        ),
        execution_plan_artifact_id=plan_id,
        effect="allow",
        policy_version_ref="gda://tenant-a/policy/dataops-cancel:v1",
        evaluator_subject=POLICY_EVALUATOR,
        decided_at=NOW,
        expires_at=NOW + timedelta(days=3650),
    )
    artifact = build_policy_decision_artifact(decision)
    gateway.artifacts[artifact.artifact_id] = artifact
    return artifact.artifact_id


class _FakeClient:
    def __init__(self):
        self.instances = []
        self.start_calls = 0
        self.start_error = None
        self.control_calls = []
        self.state = "SUBMITTED_SUCCESS"
        self.start_time = "2026-07-24 12:01:00"
        self.end_time = None
        self.invocations = []

    def find_instances(self, _binding_value, _run_value, invocation=None):
        self.invocations.append(invocation)
        return list(self.instances)

    def start_workflow(self, binding, _run_value, invocation=None):
        self.start_calls += 1
        self.invocations.append(invocation)
        if self.start_error:
            raise self.start_error
        instance = DolphinSchedulerInstance(
            instance_id=901,
            workflow_definition_code=binding.workflow_definition_code,
            workflow_definition_version=binding.workflow_definition_version,
            state=self.state,
            start_time=self.start_time,
        )
        self.instances.append(instance)
        return instance.instance_id

    def get_instance(self, instance_id, workflow_definition_code):
        return DolphinSchedulerInstance(
            instance_id=instance_id,
            workflow_definition_code=workflow_definition_code,
            workflow_definition_version=1,
            state=self.state,
            start_time=self.start_time,
            end_time=self.end_time,
        )

    def control_instance(self, instance_id, execute_type):
        self.control_calls.append((instance_id, execute_type))


def test_compiler_adds_stable_control_params_and_fingerprint():
    spec = compile_dolphinscheduler_workflow(_definition())
    params = {item["prop"]: item["value"] for item in spec.global_params}

    assert spec.api_profile == "3.4"
    assert params["gda_tenant_id"] == TENANT
    assert params["gda_definition_version_id"] == str(DEFINITION_ID)
    assert params["gda_definition_sha256"] == _definition().definition_sha256
    assert spec == compile_dolphinscheduler_workflow(_definition())


def test_binding_artifact_round_trip_has_stable_identity_and_exact_content():
    first = build_dolphinscheduler_binding_artifact(_binding(), created_by=ACTOR, created_at=NOW)
    second = build_dolphinscheduler_binding_artifact(
        _binding(), created_by="workload:replay", created_at=NOW
    )

    assert first.artifact_id == second.artifact_id
    assert first.artifact_role.value == "execution_plan"
    assert first.media_type == DOLPHINSCHEDULER_BINDING_MEDIA_TYPE
    assert first.resource_version_id == DEFINITION_ID
    assert first.run_id is None
    assert parse_dolphinscheduler_binding_artifact(first) == _binding()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("artifact_id", UUID("20000000-0000-4000-8000-000000000099")),
        ("artifact_key", "dolphinscheduler-binding:tampered:v1"),
        ("artifact_role", ArtifactRole.EVIDENCE),
        ("storage_uri", "postgresql://gda-control/execution-plans/tampered"),
        ("media_type", "application/json"),
        ("content_sha256", "f" * 64),
        ("size_bytes", 1),
        ("run_id", RUN_ID),
        ("resource_version_id", SOURCE_ID),
    ),
)
def test_binding_artifact_metadata_tampering_fails_closed(field, value):
    artifact = build_dolphinscheduler_binding_artifact(
        _binding(), created_by=ACTOR, created_at=NOW
    ).model_copy(update={field: value})

    with pytest.raises(DolphinSchedulerContractError, match="metadata"):
        parse_dolphinscheduler_binding_artifact(artifact)


def test_binding_artifact_manifest_tampering_fails_closed():
    artifact = build_dolphinscheduler_binding_artifact(_binding(), created_by=ACTOR, created_at=NOW)
    manifest = artifact.manifest | {
        "binding": artifact.manifest["binding"] | {"workflow_definition_version": 2}
    }

    with pytest.raises(DolphinSchedulerContractError, match="metadata"):
        parse_dolphinscheduler_binding_artifact(artifact.model_copy(update={"manifest": manifest}))


def test_persisted_binding_is_idempotent_and_loadable():
    gateway = _FakeGateway(authorized=False)
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=_FakeClient())

    first = adapter.persist_binding(_binding(), actor_subject=ACTOR, created_at=NOW)
    replay = adapter.persist_binding(_binding(), actor_subject=ACTOR, created_at=NOW)

    assert first.created is True
    assert replay.created is False
    assert replay.value == first.value
    assert adapter.load_binding(TENANT, first.value.artifact_id) == _binding()


def test_artifact_uuid_drives_dispatch_reconcile_and_cancel():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)
    persisted = adapter.persist_binding(_binding(), actor_subject=ACTOR, created_at=NOW)

    dispatched = adapter.dispatch(TENANT, RUN_ID, persisted.value.artifact_id, actor_subject=ACTOR)
    client.state = "RUNNING_EXECUTION"
    reconciled = adapter.reconcile(TENANT, RUN_ID, persisted.value.artifact_id, actor_subject=ACTOR)
    cancel_policy_id = _cancel_policy_artifact_id(gateway, persisted.value.artifact_id)
    cancelled = adapter.cancel(
        TENANT,
        RUN_ID,
        persisted.value.artifact_id,
        actor_subject=ACTOR,
        policy_decision_artifact_id=cancel_policy_id,
    )

    assert dispatched.workflow_instance_id == 901
    assert reconciled.run.status == RunStatus.RUNNING
    assert cancelled.status == RunStatus.CANCELLING
    assert client.control_calls == [(901, "STOP")]


def test_missing_binding_artifact_is_not_reconstructed_or_submitted():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(GatewayNotFoundError, match="Artifact was not found"):
        adapter.dispatch(
            TENANT,
            RUN_ID,
            UUID("20000000-0000-4000-8000-000000000099"),
            actor_subject=ACTOR,
        )
    with pytest.raises(DolphinSchedulerContractError, match="artifact UUID"):
        adapter.dispatch(TENANT, RUN_ID, str(DEFINITION_ID), actor_subject=ACTOR)
    assert client.start_calls == 0


@pytest.mark.parametrize(
    ("gateway", "message"),
    (
        (_FakeGateway(policy_effect=PolicyEffect.DENY), "does not allow"),
        (
            _FakeGateway(requires_approval=True, include_approval=False),
            "requires approval",
        ),
        (
            _FakeGateway(requires_approval=True, approval_verdict="rejected"),
            "does not authorize",
        ),
    ),
)
def test_dispatch_authorization_failures_never_reach_provider(gateway, message):
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerContractError, match=message):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert gateway.run.status == RunStatus.ACCEPTED
    assert gateway.transitions == []
    assert client.start_calls == 0


def test_dispatch_requires_policy_references_and_configured_evaluator():
    gateway = _FakeGateway()
    gateway.run = gateway.run.model_copy(update={"policy_refs": None})
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerContractError, match="policy decision"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    gateway = _FakeGateway(policy_evaluator="workload:other-evaluator")
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)
    with pytest.raises(DolphinSchedulerContractError, match="configured evaluator"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert client.start_calls == 0


def test_dispatch_requires_exact_workload_identity():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerContractError, match="workload identity"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject="human:dataops-adapter")

    gateway.run = gateway.run.model_copy(
        update={
            "subject_context": SubjectContext(
                **{
                    **gateway.run.subject_context.model_dump(),
                    "subject_type": "human",
                }
            )
        }
    )
    with pytest.raises(DolphinSchedulerContractError, match="workload SubjectContext"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert client.start_calls == 0


def test_dispatch_accepts_independent_human_approval():
    gateway = _FakeGateway(requires_approval=True)
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    result = adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert result.run.status == RunStatus.DISPATCHING
    assert client.start_calls == 1


def test_compiler_rejects_non_dataops_and_inline_secrets():
    definition = _definition(
        task_definitions=[
            {
                "code": 1001,
                "name": "unsafe",
                "taskType": "HTTP",
                "taskParams": {"token": "inline-secret"},
            }
        ]
    )
    with pytest.raises(DolphinSchedulerContractError, match="inline secret"):
        compile_dolphinscheduler_workflow(definition)

    with pytest.raises(DolphinSchedulerContractError, match="only accepts dataops"):
        compile_dolphinscheduler_workflow(
            _definition().model_copy(
                update={"orchestration_class": OrchestrationClass.DURABLE_AGENT}
            )
        )


def test_http_client_preserves_context_path_and_start_contract():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["token"] = request.headers.get("token")
        seen["form"] = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": [901]})

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        instance_id = client.start_workflow(_binding(), _run())
    finally:
        client.close()

    assert instance_id == 901
    assert seen["path"] == (
        "/dolphinscheduler/projects/123456789/executors/start-workflow-instance"
    )
    assert seen["token"] == "sandbox-token-value"
    assert seen["form"]["workflowDefinitionCode"] == ["987654321"]
    start_params = json.loads(seen["form"]["startParams"][0])
    assert start_params["gda_run_id"] == str(RUN_ID)
    assert start_params["gda_idempotency_key"] == _run().idempotency_key


def test_http_client_maps_governed_backfill_to_complement_data_form():
    seen = {}
    invocation = _backfill_invocation()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": [902]})

    client = DolphinSchedulerClient(
        _profile(timezone_name="Asia/Shanghai"),
        transport=httpx.MockTransport(handler),
    )
    try:
        instance_id = client.start_workflow(_binding(), _run(), invocation)
    finally:
        client.close()

    assert instance_id == 902
    assert seen["form"]["execType"] == ["COMPLEMENT_DATA"]
    backfill_time = json.loads(seen["form"]["scheduleTime"][0])
    assert backfill_time == {
        "complementStartDate": "",
        "complementEndDate": "",
        "complementScheduleDateList": "2026-07-01 08:00:00",
    }
    assert seen["form"]["runMode"] == ["RUN_MODE_SERIAL"]
    assert seen["form"]["expectedParallelismNumber"] == ["1"]
    assert seen["form"]["complementDependentMode"] == ["OFF_MODE"]
    assert seen["form"]["executionOrder"] == ["ASC_ORDER"]
    params = json.loads(seen["form"]["startParams"][0])
    assert params["gda_invocation_version_id"] == str(dataops_invocation_version_id(invocation))
    assert params["gda_trigger_kind"] == "backfill"
    assert params["gda_logical_start"] == "2026-07-01T00:00:00+00:00"


def test_http_client_maps_governed_schedule_to_correlated_start_without_native_cron():
    seen = {}
    invocation = _schedule_invocation()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": [903]})

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        instance_id = client.start_workflow(_binding(), _run(), invocation)
    finally:
        client.close()

    assert instance_id == 903
    assert seen["form"]["execType"] == ["START_PROCESS"]
    assert seen["form"]["scheduleTime"] == [""]
    assert "runMode" not in seen["form"]
    params = json.loads(seen["form"]["startParams"][0])
    assert params["gda_trigger_kind"] == "schedule"
    assert params["gda_schedule_ref"] == invocation.schedule_ref
    assert params["gda_schedule_time"] == "2026-07-02T00:05:00+00:00"


def test_http_client_maps_governed_manual_request_to_correlated_start():
    seen = {}
    invocation = _manual_invocation()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = parse_qs(request.content.decode("utf-8"), keep_blank_values=True)
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": [904]})

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        instance_id = client.start_workflow(_binding(), _run(), invocation)
    finally:
        client.close()

    assert instance_id == 904
    assert seen["form"]["execType"] == ["START_PROCESS"]
    assert seen["form"]["scheduleTime"] == [""]
    params = json.loads(seen["form"]["startParams"][0])
    assert params["gda_trigger_kind"] == "manual"
    assert params["gda_client_request_id"] == invocation.client_request_id
    assert "gda_schedule_ref" not in params


def test_http_client_creates_workflow_with_compiled_form():
    seen = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode("utf-8"))
        seen["requests"].append((request.url.path, form))
        if request.url.path.endswith("/987654321/release"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "success", "data": True},
            )
        return httpx.Response(
            201,
            json={
                "code": 0,
                "msg": "success",
                "data": {"code": 987654321, "version": 1},
            },
        )

    spec = compile_dolphinscheduler_workflow(_definition())
    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        binding = client.create_workflow(spec)
    finally:
        client.close()

    assert binding.workflow_definition_code == 987654321
    assert binding.compiled_sha256 == spec.compiled_sha256
    assert seen["requests"][0][0].endswith("/workflow-definition")
    assert seen["requests"][0][1]["executionType"] == ["PARALLEL"]
    assert seen["requests"][1] == (
        "/dolphinscheduler/projects/123456789/workflow-definition/987654321/release",
        {"releaseState": ["ONLINE"]},
    )


def test_http_client_generates_valid_task_codes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/task-definition/gen-task-codes")
        assert request.url.params["genNum"] == "2"
        return httpx.Response(
            200,
            json={"code": 0, "msg": "success", "data": [123456, 123457]},
        )

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        assert client.generate_task_codes(2) == (123456, 123457)
    finally:
        client.close()


def test_http_client_rejects_invalid_generated_task_codes():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "msg": "success", "data": [123456, 123456]},
        )

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DolphinSchedulerProtocolError, match="unique positive"):
            client.generate_task_codes(2)
        with pytest.raises(DolphinSchedulerContractError, match="between 1 and 100"):
            client.generate_task_codes(0)
    finally:
        client.close()


def test_http_client_finds_exact_correlation_through_variables():
    expected = DolphinSchedulerClient.start_params(_run())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workflow-instances"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "totalList": [
                            {
                                "id": 901,
                                "workflowDefinitionCode": 987654321,
                                "workflowDefinitionVersion": 1,
                                "state": "RUNNING_EXECUTION",
                            }
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "globalParams": [
                        {"prop": key, "value": value} for key, value in expected.items()
                    ]
                },
            },
        )

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        matches = client.find_instances(_binding(), _run())
    finally:
        client.close()

    assert [item.instance_id for item in matches] == [901]


def test_invocation_lookup_skips_unrelated_legacy_instance_without_window_keys():
    invocation = _backfill_invocation()
    legacy = DolphinSchedulerClient.start_params(
        _run(
            run_id=UUID("20000000-0000-4000-8000-000000000099"),
            idempotency_key="legacy-run",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workflow-instances"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "totalList": [
                            {
                                "id": 900,
                                "workflowDefinitionCode": 987654321,
                                "state": "SUCCESS",
                            }
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "globalParams": [{"prop": key, "value": value} for key, value in legacy.items()]
                },
            },
        )

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        assert client.find_instances(_binding(), _run(), invocation) == []
    finally:
        client.close()


def test_correlation_lookup_rejects_unknown_page_shape():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "data": {"unexpected": []}},
        )

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DolphinSchedulerProtocolError, match="unknown shape"):
            client.find_instances(_binding(), _run())
    finally:
        client.close()


def test_correlation_lookup_rejects_missing_variables_and_page_exhaustion():
    expected = DolphinSchedulerClient.start_params(_run())

    def missing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workflow-instances"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "totalList": [
                            {
                                "id": 901,
                                "workflowDefinitionCode": 987654321,
                                "state": "RUNNING_EXECUTION",
                            }
                        ]
                    },
                },
            )
        return httpx.Response(200, json={"code": 0, "data": {"globalParams": []}})

    missing_client = DolphinSchedulerClient(
        _profile(), transport=httpx.MockTransport(missing_handler)
    )
    try:
        with pytest.raises(DolphinSchedulerProtocolError, match="missing required"):
            missing_client.find_instances(_binding(), _run())
    finally:
        missing_client.close()

    def full_page_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workflow-instances"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "totalList": [
                            {
                                "id": value,
                                "workflowDefinitionCode": 987654321,
                                "state": "SUCCESS",
                            }
                            for value in range(1, 101)
                        ]
                    },
                },
            )
        variables = dict(expected)
        variables["gda_run_id"] = "different-run"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "globalParams": [
                        {"prop": key, "value": value} for key, value in variables.items()
                    ]
                },
            },
        )

    limited_client = DolphinSchedulerClient(
        _profile(reconciliation_page_limit=1),
        transport=httpx.MockTransport(full_page_handler),
    )
    try:
        with pytest.raises(DolphinSchedulerReconciliationRequired, match="page limit"):
            limited_client.find_instances(_binding(), _run())
    finally:
        limited_client.close()


def test_http_errors_do_not_expose_access_token():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10001, "msg": "sandbox-token-value is invalid"})

    client = DolphinSchedulerClient(_profile(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DolphinSchedulerRejectedError) as caught:
            client.list_workflows()
    finally:
        client.close()
    assert "sandbox-token-value" not in str(caught.value)


def test_probe_token_file_requires_owner_only_permissions(tmp_path):
    token_file = tmp_path / "dolphinscheduler.token"
    token_file.write_text("sandbox-token-value\n", encoding="utf-8")
    token_file.chmod(0o644)

    with pytest.raises(DolphinSchedulerConfigurationError, match="group or other"):
        _read_token_file(token_file)

    token_file.chmod(0o600)
    assert _read_token_file(token_file) == "sandbox-token-value"


def test_dispatch_is_idempotently_recovered_without_resubmission():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    first = adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    second = adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert first.run.status == RunStatus.DISPATCHING
    assert first.observation_created is True
    assert second.recovered is True
    assert second.observation_created is False
    assert client.start_calls == 1
    assert [item[0] for item in gateway.transitions] == [RunStatus.DISPATCHING]


def test_dispatch_resolves_invocation_and_records_window_evidence():
    invocation = _backfill_invocation()
    gateway = _FakeGateway(invocation=invocation)
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    result = adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert client.start_calls == 1
    assert client.invocations == [invocation, invocation]
    assert result.observation.evidence["invocation"]["trigger_kind"] == "backfill"
    assert result.observation.evidence["correlation"]["gda_invocation_version_id"] == str(
        dataops_invocation_version_id(invocation)
    )


def test_dispatch_rejects_invalid_invocation_binding_before_provider_call():
    invocation = _backfill_invocation()
    gateway = _FakeGateway(invocation=invocation)
    invocation_binding = gateway.run.input_bindings[-1]
    gateway.run = gateway.run.model_copy(
        update={
            "input_bindings": (
                gateway.run.input_bindings[0],
                invocation_binding.model_copy(update={"semantic_type": "tampered"}),
            )
        }
    )
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerContractError, match="semantic type"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert client.start_calls == 0


def test_unknown_dispatch_outcome_moves_to_reconcile_and_never_blindly_retries():
    gateway = _FakeGateway()
    client = _FakeClient()
    client.start_error = DolphinSchedulerUnavailableError("unknown outcome")
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerReconciliationRequired):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    with pytest.raises(DolphinSchedulerReconciliationRequired, match="do not resubmit"):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert client.start_calls == 1
    assert gateway.run.status == RunStatus.RECONCILING
    assert [item[0] for item in gateway.transitions] == [
        RunStatus.DISPATCHING,
        RunStatus.RECONCILING,
    ]


def test_unknown_dispatch_response_recovers_visible_instance():
    class _UnknownThenVisibleClient(_FakeClient):
        def start_workflow(self, binding, _run_value, invocation=None):
            self.start_calls += 1
            self.invocations.append(invocation)
            self.instances.append(
                DolphinSchedulerInstance(
                    instance_id=901,
                    workflow_definition_code=binding.workflow_definition_code,
                    workflow_definition_version=binding.workflow_definition_version,
                    state=self.state,
                    start_time=self.start_time,
                )
            )
            raise DolphinSchedulerUnavailableError("response was lost")

    gateway = _FakeGateway()
    client = _UnknownThenVisibleClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    result = adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert result.recovered is True
    assert result.workflow_instance_id == 901
    assert result.run.status == RunStatus.DISPATCHING
    assert client.start_calls == 1


def test_reconcile_projects_running_but_keeps_provider_success_nonterminal():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)
    adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    client.state = "RUNNING_EXECUTION"
    running = adapter.reconcile(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert running.run.status == RunStatus.RUNNING

    client.state = "SUCCESS"
    client.end_time = "2026-07-24 12:05:00"
    completed = adapter.reconcile(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert completed.provider_state == "SUCCESS"
    assert completed.run.status == RunStatus.RECONCILING
    assert completed.run.status != RunStatus.SUCCEEDED


def test_cancel_uses_cas_before_external_stop():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)
    adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    cancel_policy_id = _cancel_policy_artifact_id(
        gateway,
        build_dolphinscheduler_binding_artifact(
            _binding(), created_by=ACTOR, created_at=NOW
        ).artifact_id,
    )

    run = adapter.cancel(
        TENANT,
        RUN_ID,
        _binding(),
        actor_subject=ACTOR,
        policy_decision_artifact_id=cancel_policy_id,
    )

    assert run.status == RunStatus.CANCELLING
    assert client.control_calls == [(901, "STOP")]

    client.state = "STOP"
    terminal = adapter.reconcile(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert terminal.run.status == RunStatus.CANCELLED


def test_cancel_admission_fails_closed_without_terminal_stop_capability():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(
        _profile(
            cancel_terminal_stop_capability="unknown",
            cancel_terminal_stop_evidence_ref=None,
        ),
        gateway=gateway,
        client=client,
    )

    with pytest.raises(DolphinSchedulerContractError, match="not certified"):
        adapter.cancel(
            TENANT,
            RUN_ID,
            _binding(),
            actor_subject=ACTOR,
            policy_decision_artifact_id=UUID("20000000-0000-4000-8000-000000000099"),
        )

    assert gateway.run.status == RunStatus.ACCEPTED
    assert client.control_calls == []


def test_capability_report_fingerprint_binds_version_and_admission():
    adapter = DolphinSchedulerAdapter(
        _profile(), gateway=_FakeGateway(), client=_FakeClient()
    )

    report = adapter.capability_report()

    assert report.server_version == "3.4.2"
    assert report.api_profile == "3.4"
    assert report.cancel_admission == "allowed"
    assert report.cancel_terminal_stop_capability == "certified"
    assert report.capability_sha256


def test_cancel_provider_failure_opens_incident_and_terminates_run_failed():
    gateway = _FakeGateway()
    client = _FakeClient()
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)
    adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    cancel_policy_id = _cancel_policy_artifact_id(
        gateway,
        build_dolphinscheduler_binding_artifact(
            _binding(), created_by=ACTOR, created_at=NOW
        ).artifact_id,
    )
    adapter.cancel(
        TENANT,
        RUN_ID,
        _binding(),
        actor_subject=ACTOR,
        policy_decision_artifact_id=cancel_policy_id,
    )

    client.state = "FAILURE"
    client.end_time = "2026-07-24 12:05:00"
    result = adapter.reconcile(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)

    assert result.provider_state == "FAILURE"
    assert result.run.status == RunStatus.FAILED
    assert result.run.status != RunStatus.CANCELLED
    assert len(gateway.cancellation_incidents) == 1
    assert gateway.cancellation_incidents[0].observed_state == "failure"


def test_multiple_external_correlations_fail_closed():
    gateway = _FakeGateway()
    client = _FakeClient()
    client.instances = [
        DolphinSchedulerInstance(
            instance_id=value,
            workflow_definition_code=987654321,
            workflow_definition_version=1,
            state="RUNNING_EXECUTION",
        )
        for value in (901, 902)
    ]
    adapter = DolphinSchedulerAdapter(_profile(), gateway=gateway, client=client)

    with pytest.raises(DolphinSchedulerCorrelationConflictError):
        adapter.dispatch(TENANT, RUN_ID, _binding(), actor_subject=ACTOR)
    assert gateway.run.status == RunStatus.ACCEPTED


def test_static_adapter_report_detects_missing_fail_closed_marker(tmp_path):
    report = build_dolphinscheduler_adapter_report()
    assert report["status"] == "valid"
    assert report["server_version"] == "3.4.2"

    unsafe = tmp_path / "unsafe_adapter.py"
    source = Path(__import__("data_agent.dolphinscheduler_adapter", fromlist=["__file__"]).__file__)
    unsafe.write_text(
        source.read_text(encoding="utf-8").replace(
            "dispatch outcome is unknown; reconcile before retry", "retry now"
        ),
        encoding="utf-8",
    )
    unsafe_report = build_dolphinscheduler_adapter_report(unsafe)
    assert unsafe_report["status"] == "invalid"


def test_sandbox_image_provides_process_tree_for_shell_task_cancel():
    repository = Path(__file__).resolve().parents[1]
    compose = (repository / "docker-compose.dolphinscheduler-sandbox.yml").read_text(
        encoding="utf-8"
    )
    dockerfile = (
        repository / "deploy/dolphinscheduler-sandbox/Dockerfile"
    ).read_text(encoding="utf-8")

    assert "dockerfile: deploy/dolphinscheduler-sandbox/Dockerfile" in compose
    assert "gisdataagent-dolphinscheduler-sandbox:3.4.2-pstree" in compose
    assert "apt-get install -y --no-install-recommends psmisc" in dockerfile
