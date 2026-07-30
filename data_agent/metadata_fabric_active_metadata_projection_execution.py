"""Execute an authorized Active Metadata projection through DolphinScheduler.

This M3-18 local-only rehearsal extends the M3-17 delivery boundary. An
authorized provider-native DolphinScheduler task calls a short-lived local
projection executor. The executor validates an independent, content-bound
``metadata_fabric.apply`` authorization before reusing the M3-2 provider
clients to create and read back OpenMetadata and Gravitino projections. It
then applies the exact plan again and requires a zero-mutation replay.

The callback is ephemeral HTTP on the Docker Desktop host gateway,
OpenMetadata still uses its local bootstrap administrator, and Gravitino is
still unauthenticated. Provider and scheduler success leave PlatformRun in
``reconciling``; no production readiness claim is made.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import create_engine, text

from . import metadata_fabric_active_metadata_authorization as authorization
from . import metadata_fabric_active_metadata_scheduler_delivery as delivery
from . import metadata_fabric_ingestion as ingestion
from . import metadata_fabric_ingestion_replay as replay
from . import metadata_fabric_provider_metrics as provider_metrics
from .active_metadata_authorization import (
    MetadataActivationAuthorization,
    build_metadata_activation_authorization,
)
from .dolphinscheduler_adapter import (
    DOLPHINSCHEDULER_API_PROFILE,
    DOLPHINSCHEDULER_SERVER_VERSION,
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    DolphinSchedulerWorkflowSpec,
    build_dolphinscheduler_binding_artifact,
    compile_dolphinscheduler_workflow,
)
from .dolphinscheduler_command_consumer import DolphinSchedulerCommandConsumer
from .platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
)
from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    Resource,
    ResourceVersion,
    RunPolicyReferences,
    RunStatus,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)
from .platform_gateway import DefinitionRegistration, PlatformGateway
from .spatial_dataset_bundle import validate_shapefile_bundle_inventory

CONTRACT_SCHEMA = "gda.active_metadata_projection_execution_contract.v1"
REQUEST_SCHEMA = "gda.active_metadata_projection_execution_request.v1"
EVIDENCE_SCHEMA = "gda.active_metadata_projection_execution_evidence.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEDULER_DEPENDENCY_PATH = delivery.DEFAULT_EVIDENCE_PATH
DEFAULT_INGESTION_DEPENDENCY_PATH = replay.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-active-metadata-projection-execution-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-active-metadata-projection-execution.sh"
TENANT = authorization.TENANT
SOURCE_ID = authorization.SOURCE_ID
DEFINITION_ID = UUID("a8000000-0000-4000-8000-000000000002")
RUN_ID = UUID("a8000000-0000-4000-8000-000000000003")
TASK_CODE = 180000000000001
WORKER = "worker:active-metadata-projection-execution-1"
RUNNER = delivery.RUNNER
POLICY_EVALUATOR = delivery.POLICY_EVALUATOR
AUTHORIZER = delivery.AUTHORIZER
APPROVER = delivery.APPROVER
CALLBACK_PATH = "/v1/execute-projection"
FALSE_CLAIMS = (
    "dataset_source_committed",
    "dataset_absolute_path_committed",
    "dataset_required_in_ci",
    "deployment_applied",
    "protected_workload_identity_verified",
    "provider_minimum_privilege_verified",
    "gravitino_authentication_verified",
    "oidc_verified",
    "tls_verified",
    "binding_persisted_to_gda_control",
    "live_openlineage_emission_verified",
    "production_scheduler_submission_verified",
    "production_ingestion_verified",
    "production_ready",
)


class ActiveMetadataProjectionExecutionError(RuntimeError):
    """The local scheduler-to-provider projection rehearsal failed closed."""


class ProjectionExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_schema: Literal["gda.active_metadata_projection_execution_request.v1"] = Field(
        default=REQUEST_SCHEMA, alias="schema"
    )
    tenant_id: str
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    apply_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprint(self) -> Self:
        stable = self.model_dump(mode="json", by_alias=True, exclude={"request_sha256"})
        if self.request_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("projection execution request fingerprint does not match")
        return self


@dataclass(frozen=True)
class ProjectionDefinitionBundle:
    registration: DefinitionRegistration
    definition: PlatformDefinitionVersion
    workflow: DolphinSchedulerWorkflowSpec


@dataclass(frozen=True)
class ProjectionDispatchBundle:
    source_resource: Resource
    source_version: ResourceVersion
    request: Any
    registration: Any
    definition_registration: DefinitionRegistration
    dispatch_plan: Artifact
    dispatch_policy_decision: Artifact
    dispatch_approval: Artifact
    run: PlatformRun
    activation_authorization: MetadataActivationAuthorization


def _file_sha256(path: Path) -> str:
    return replay.recovery._file_sha256(path)


def _file_record(path: Path) -> dict[str, str | None]:
    relative = path.resolve().relative_to(REPO_ROOT).as_posix()
    return {
        "path": relative,
        "sha256": _file_sha256(path) if path.is_file() else None,
    }


def build_projection_profile(authorized_at: datetime) -> replay.LocalIngestionProfile:
    if authorized_at.tzinfo is None or authorized_at.utcoffset() is None:
        raise ActiveMetadataProjectionExecutionError(
            "projection authorization time must include a timezone"
        )
    base = replay.load_profile()
    profile = {
        "schema": replay.PROFILE_SCHEMA,
        "environment": "local_docker_desktop",
        "cluster": base.cluster.model_dump(mode="json"),
        "providers": base.providers.model_dump(mode="json"),
        "targets": {
            "openmetadata": {
                "service": "gda_chongqing_m3_18",
                "service_type": "CustomDatabase",
                "database": "cultural_heritage",
                "schema": "published",
                "table": "cultural_districts",
                "owner_team": "data-platform",
                "domain": "natural-resources",
                "classification": "Sensitivity",
                "classification_tag": "Internal",
                "glossary": "CulturalHeritage",
                "glossary_term": "CulturalDistrict",
            },
            "gravitino": {
                "metalake": "gda_chongqing_m3_18",
                "catalog": "iceberg",
                "schema": "cultural_heritage",
                "table": "cultural_districts",
                "catalog_type": "RELATIONAL",
                "catalog_provider": "lakehouse-iceberg",
                "catalog_backend": "memory",
                "uri": "file:///tmp/gda-m3-local",
                "warehouse": "file:///tmp/gda-m3-local",
            },
        },
        "authorization": {
            "action": replay.ACTION,
            "policy_version_ref": (f"gda://{TENANT}/policy/active-metadata-provider-apply-v1"),
            "evaluator_subject": POLICY_EVALUATOR,
            "approver_subject": APPROVER,
            "approval_reason": ("Approved bounded scheduler-triggered Metadata Fabric projection"),
            "decided_at": authorized_at - timedelta(minutes=3),
            "approval_decided_at": authorized_at - timedelta(minutes=2),
            "authorized_at": authorized_at - timedelta(minutes=1),
            "approval_expires_at": authorized_at + timedelta(days=180),
            "expires_at": authorized_at + timedelta(days=365),
        },
        "claims": base.claims.model_dump(mode="json"),
    }
    return replay.LocalIngestionProfile.model_validate(profile)


def build_projection_plan(
    content_sha256: str,
    profile: replay.LocalIngestionProfile,
) -> replay.LocalApplyPlan:
    resource_urn = f"gda://{TENANT}/dataset/chongqing-cultural-districts"
    common = {
        "resource_urn": resource_urn,
        "resource_version_id": str(SOURCE_ID),
        "content_sha256": content_sha256,
    }
    projections = (
        ingestion._projection(
            provider="openmetadata",
            target_identity=profile.targets.openmetadata.table_fqn,
            desired_state={
                **common,
                "owner_refs": ["team:data-platform"],
                "domain_refs": ["domain:natural-resources"],
                "tag_refs": [
                    "CulturalHeritage.CulturalDistrict",
                    "Sensitivity.Internal",
                ],
            },
        ),
        ingestion._projection(
            provider="gravitino",
            target_identity=profile.targets.gravitino.identity,
            desired_state={
                **common,
                "provider_revision": f"shapefile-bundle-{content_sha256[:16]}",
            },
        ),
    )
    source_plan_sha256 = canonical_json_fingerprint(
        {
            "schema": "gda.active_metadata_projection_intent.v1",
            "tenant_id": TENANT,
            "resource_urn": resource_urn,
            "resource_version_id": str(SOURCE_ID),
            "content_sha256": content_sha256,
            "targets": [item.target_identity for item in projections],
        }
    )
    values: dict[str, Any] = {
        "source_plan_sha256": source_plan_sha256,
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "source_resource_version_id": SOURCE_ID,
        "resource_urn": resource_urn,
        "resource_version_id": SOURCE_ID,
        "content_sha256": content_sha256,
        "openmetadata_fqn": profile.targets.openmetadata.table_fqn,
        "gravitino_identity": profile.targets.gravitino.identity,
        "projections": projections,
    }
    stable = {
        "schema": replay.APPLY_PLAN_SCHEMA,
        **{
            key: (
                [item.model_dump(mode="json") for item in value]
                if key == "projections"
                else str(value)
                if isinstance(value, UUID)
                else value
            )
            for key, value in values.items()
        },
        "provider_apply_authorized": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
    }
    return replay.LocalApplyPlan(
        **values,
        apply_plan_sha256=canonical_json_fingerprint(stable),
    )


def build_execution_request(plan: replay.LocalApplyPlan) -> ProjectionExecutionRequest:
    stable = {
        "schema": REQUEST_SCHEMA,
        "tenant_id": plan.tenant_id,
        "run_id": str(plan.run_id),
        "definition_version_id": str(plan.definition_version_id),
        "source_resource_version_id": str(plan.source_resource_version_id),
        "content_sha256": plan.content_sha256,
        "apply_plan_sha256": plan.apply_plan_sha256,
    }
    return ProjectionExecutionRequest(
        **stable,
        request_sha256=canonical_json_fingerprint(stable),
    )


def build_provider_apply_authorization(
    plan: replay.LocalApplyPlan,
    run: PlatformRun,
    profile: replay.LocalIngestionProfile,
) -> replay.ApplyAuthorizationBundle:
    """Authorize a source projection without fabricating a target ResourceVersion."""
    auth = profile.authorization
    actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    execution_plan = replay.build_execution_plan_artifact(
        plan,
        created_by=actor,
        created_at=auth.decided_at,
    )
    resource_versions = tuple(
        sorted(
            {
                plan.definition_version_id,
                plan.source_resource_version_id,
                plan.resource_version_id,
            },
            key=str,
        )
    )
    decision = PolicyDecision(
        tenant_id=plan.tenant_id,
        run_id=plan.run_id,
        subject_context=run.subject_context,
        action=auth.action,
        definition_version_id=plan.definition_version_id,
        resource_version_ids=resource_versions,
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref=auth.policy_version_ref,
        evaluator_subject=auth.evaluator_subject,
        requires_approval=True,
        obligations=(),
        decided_at=auth.decided_at,
        expires_at=auth.expires_at,
    )
    decision_artifact = build_policy_decision_artifact(decision)
    approval_artifact = build_approval_artifact(
        ApprovalRecord(
            tenant_id=plan.tenant_id,
            run_id=plan.run_id,
            definition_version_id=plan.definition_version_id,
            policy_decision_artifact_id=decision_artifact.artifact_id,
            policy_decision_sha256=decision_artifact.content_sha256,
            verdict="approved",
            approver_subject=auth.approver_subject,
            reason=auth.approval_reason,
            decided_at=auth.approval_decided_at,
            expires_at=auth.approval_expires_at,
        )
    )
    values = {
        "execution_plan_artifact": execution_plan,
        "policy_decision_artifact": decision_artifact,
        "approval_artifact": approval_artifact,
    }
    bundle = replay.ApplyAuthorizationBundle(
        **values,
        authorization_sha256=canonical_json_fingerprint(
            {key: value.model_dump(mode="json") for key, value in values.items()}
        ),
    )
    replay.validate_apply_authorization(
        plan,
        run,
        bundle,
        at=auth.authorized_at,
    )
    return bundle


def _workflow_document(
    callback_url: str,
    request: ProjectionExecutionRequest,
) -> dict[str, Any]:
    request_json = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    raw_script = " ".join(
        (
            "curl --fail --silent --show-error --max-time 300",
            "--request POST --header 'Content-Type: application/json'",
            f"--data-binary {shlex.quote(request_json)}",
            shlex.quote(callback_url),
        )
    )
    task = {
        "code": TASK_CODE,
        "name": "execute_active_metadata_projection",
        "version": 1,
        "description": "Execute one authorized local Metadata Fabric projection",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": raw_script,
            "resourceList": [],
            "dependence": {},
            "conditionResult": {"successNode": [], "failedNode": []},
            "waitStartTimeout": {},
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "default",
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 360,
    }
    relation = {
        "name": "",
        "preTaskCode": 0,
        "preTaskVersion": 0,
        "postTaskCode": TASK_CODE,
        "postTaskVersion": 1,
        "conditionType": "NONE",
        "conditionParams": {},
    }
    return {
        "dolphinscheduler": {
            "name": "gda_active_metadata_projection_execution_v1",
            "description": "Authorized local provider projection execution",
            "task_definitions": [task],
            "task_relations": [relation],
            "locations": [{"taskCode": TASK_CODE, "x": 160, "y": 100}],
            "global_params": [],
            "timeout_seconds": 420,
            "execution_type": "PARALLEL",
        }
    }


def build_scheduler_definition(
    callback_url: str,
    request: ProjectionExecutionRequest,
    *,
    created_at: datetime,
) -> ProjectionDefinitionBundle:
    definition_urn = f"gda://{TENANT}/definition/metadata-projection-execution"
    definition_document = _workflow_document(callback_url, request)
    input_contract = {
        "metadata_change": "gis.cultural_districts",
        "execution_request_sha256": request.request_sha256,
    }
    output_contract = {
        "openmetadata_projection_readback": True,
        "gravitino_projection_readback": True,
        "zero_mutation_replay": True,
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    resource = Resource(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/metadata-projection-execution",
        owner_ref="team:metadata-platform",
    )
    resource_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_ID,
        version_key="dolphinscheduler-3.4.2-local-provider-apply-v1",
        content_sha256=definition_sha256,
        authority_version_ref={
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
            "callback_transport": "docker_desktop_host_gateway_http",
        },
        created_by="workload:metadata-definition-registrar",
        created_at=created_at,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=definition_urn,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="provider_native",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha256,
    )
    return ProjectionDefinitionBundle(
        registration=DefinitionRegistration(
            resource=resource,
            resource_version=resource_version,
            definition=definition,
        ),
        definition=definition,
        workflow=compile_dolphinscheduler_workflow(definition),
    )


def build_dispatch_bundle(
    content_sha256: str,
    definition_bundle: ProjectionDefinitionBundle,
    binding: DolphinSchedulerDefinitionBinding,
    *,
    authorized_at: datetime,
) -> ProjectionDispatchBundle:
    base = authorization.build_authorization_bundle(content_sha256)
    if binding.definition_version_id != DEFINITION_ID:
        raise ActiveMetadataProjectionExecutionError(
            "DolphinScheduler binding does not match the projection definition"
        )
    if binding.compiled_sha256 != definition_bundle.workflow.compiled_sha256:
        raise ActiveMetadataProjectionExecutionError(
            "DolphinScheduler binding does not match the compiled projection workflow"
        )
    dispatch_plan = build_dolphinscheduler_binding_artifact(
        binding,
        created_by=RUNNER,
        created_at=authorized_at - timedelta(seconds=3),
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=RUNNER.removeprefix("workload:"),
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="execute authorized active metadata projection",
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, SOURCE_ID),
        execution_plan_artifact_id=dispatch_plan.artifact_id,
        effect="allow",
        policy_version_ref=f"gda://{TENANT}/policy/metadata-dispatch-v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=True,
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=365),
    )
    dispatch_policy = build_policy_decision_artifact(decision)
    dispatch_approval = build_approval_artifact(
        ApprovalRecord(
            tenant_id=TENANT,
            run_id=RUN_ID,
            definition_version_id=DEFINITION_ID,
            policy_decision_artifact_id=dispatch_policy.artifact_id,
            policy_decision_sha256=dispatch_policy.content_sha256,
            verdict="approved",
            approver_subject=APPROVER,
            reason="approved bounded local scheduler-triggered provider projection",
            decided_at=authorized_at - timedelta(seconds=2),
            expires_at=authorized_at + timedelta(days=180),
        )
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "metadata_change",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key="metadata-projection:cultural-districts:execution:v1",
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=dispatch_policy.artifact_id,
            approval_artifact_id=dispatch_approval.artifact_id,
        ),
        submitted_at=authorized_at - timedelta(seconds=1),
    )
    activation = build_metadata_activation_authorization(
        base.request,
        base.registration.resource_version,
        definition_bundle.definition,
        run,
        dispatch_plan,
        dispatch_policy,
        dispatch_approval,
        authorized_by=AUTHORIZER,
        authorized_at=authorized_at,
    )
    return ProjectionDispatchBundle(
        source_resource=base.source_resource,
        source_version=base.registration.resource_version,
        request=base.request,
        registration=base.registration,
        definition_registration=definition_bundle.registration,
        dispatch_plan=dispatch_plan,
        dispatch_policy_decision=dispatch_policy,
        dispatch_approval=dispatch_approval,
        run=run,
        activation_authorization=activation,
    )


class ProjectionExecutor:
    def __init__(
        self,
        request: ProjectionExecutionRequest,
        profile: replay.LocalIngestionProfile,
        plan: replay.LocalApplyPlan,
        run: PlatformRun,
        apply_authorization: replay.ApplyAuthorizationBundle,
        *,
        openmetadata: replay.OpenMetadataApplyClient,
        gravitino: replay.GravitinoApplyClient,
    ) -> None:
        self.request = request
        self.profile = profile
        self.plan = plan
        self.run = run
        self.apply_authorization = apply_authorization
        self.openmetadata = openmetadata
        self.gravitino = gravitino
        self.request_count = 0
        self.first: replay.ApplyOutcome | None = None
        self.replayed: replay.ApplyOutcome | None = None
        self.error_type: str | None = None

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.request_count += 1
        try:
            observed = ProjectionExecutionRequest.model_validate(payload)
            if observed != self.request:
                raise ActiveMetadataProjectionExecutionError(
                    "projection callback request does not match the compiled workflow"
                )
            if self.request_count != 1:
                raise ActiveMetadataProjectionExecutionError(
                    "projection executor accepts exactly one scheduler callback"
                )
            now = datetime.now(UTC)
            replay.validate_apply_authorization(
                self.plan,
                self.run,
                self.apply_authorization,
                at=now,
            )
            self.first = replay.apply_once(
                self.plan,
                self.profile,
                self.apply_authorization,
                self.run,
                openmetadata=self.openmetadata,
                gravitino=self.gravitino,
                at=now,
            )
            self.replayed = replay.apply_once(
                self.plan,
                self.profile,
                self.apply_authorization,
                self.run,
                openmetadata=self.openmetadata,
                gravitino=self.gravitino,
                at=datetime.now(UTC),
            )
            if self.first.status != replay.ApplyStatus.CREATED or not self.first.mutations:
                raise ActiveMetadataProjectionExecutionError(
                    "first scheduler-triggered provider apply did not create projection state"
                )
            if self.replayed.status != replay.ApplyStatus.NO_OP or self.replayed.mutations:
                raise ActiveMetadataProjectionExecutionError(
                    "exact provider replay performed duplicate mutations"
                )
            if self.first.binding_candidate_sha256 != self.replayed.binding_candidate_sha256:
                raise ActiveMetadataProjectionExecutionError(
                    "provider binding read-back drifted across exact replay"
                )
            return {
                "schema": "gda.active_metadata_projection_execution_response.v1",
                "status": "applied_and_replayed",
                "request_sha256": self.request.request_sha256,
            }
        except Exception as exc:
            self.error_type = type(exc).__name__
            raise


class ProjectionExecutionServer:
    def __init__(self, request: ProjectionExecutionRequest) -> None:
        self.request = request
        self.executor: ProjectionExecutor | None = None
        self.started = False
        self.cleanup_verified = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != CALLBACK_PATH:
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if length <= 0 or length > 16384:
                    self.send_error(413)
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict) or owner.executor is None:
                        raise ValueError("projection executor request is unavailable")
                    response = owner.executor.execute(payload)
                except Exception:
                    self.send_error(500)
                    return
                body = json.dumps(
                    response,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = HTTPServer(("0.0.0.0", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="gda-m3-18-projection-executor",
            daemon=True,
        )

    @property
    def callback_url(self) -> str:
        return f"http://host.docker.internal:{self._server.server_port}{CALLBACK_PATH}"

    def start(self) -> None:
        if self.executor is None:
            raise ActiveMetadataProjectionExecutionError(
                "projection executor must be attached before callback server starts"
            )
        self._thread.start()
        self.started = True

    def stop(self) -> bool:
        if self.started:
            self._server.shutdown()
            self._thread.join(timeout=30)
        self._server.server_close()
        self.cleanup_verified = not self._thread.is_alive()
        return self.cleanup_verified


def _register_control_chain(
    gateway: PlatformGateway,
    bundle: ProjectionDispatchBundle,
    apply_authorization: replay.ApplyAuthorizationBundle,
) -> None:
    gateway.register_resource(bundle.source_resource)
    gateway.register_resource_version_with_metadata_event(bundle.registration)
    claimed = gateway.claim_metadata_changes(
        TENANT,
        WORKER,
        consumer_subject=authorization.CONSUMER_SUBJECT,
    )
    if len(claimed) != 1:
        raise ActiveMetadataProjectionExecutionError("expected exactly one Active Metadata change")
    gateway.stage_metadata_activation_request(
        TENANT,
        claimed[0].event.event_id,
        worker_id=WORKER,
        request=bundle.request,
    )
    gateway.register_definition(bundle.definition_registration)
    for artifact in (
        bundle.dispatch_plan,
        bundle.dispatch_policy_decision,
        bundle.dispatch_approval,
        apply_authorization.execution_plan_artifact,
        apply_authorization.policy_decision_artifact,
        apply_authorization.approval_artifact,
    ):
        gateway.record_artifact(artifact)
    gateway.submit_run(bundle.run)


def _attempt_summary(engine: Any) -> tuple[int, int, int, int, list[str]]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*) AS total,
                    count(DISTINCT external_namespace || ':' || external_run_id)
                        AS correlations,
                    count(*) FILTER (WHERE observed_state = 'submitted') AS submitted,
                    count(*) FILTER (WHERE observed_state = 'success') AS succeeded,
                    array_agg(observed_state ORDER BY observed_at, observation_id)
                        AS states
                FROM gda_control.framework_attempt_observation
                WHERE tenant_id = :tenant_id AND run_id = :run_id
                """
            ),
            {"tenant_id": TENANT, "run_id": RUN_ID},
        ).one()
    return row.total, row.correlations, row.submitted, row.succeeded, list(row.states)


def _validate_dependencies(
    scheduler_evidence: dict[str, Any],
    ingestion_evidence: dict[str, Any],
) -> None:
    if delivery.validate_rehearsal_evidence(scheduler_evidence):
        raise ActiveMetadataProjectionExecutionError("M3-17 scheduler delivery evidence is invalid")
    ingestion_errors = replay.verify_evidence_integrity(ingestion_evidence)
    expected_contract = replay.build_contract_report()["contract_fingerprint"]
    observed_contract = (
        ingestion_evidence.get("observation", {}).get("contract", {}).get("contract_fingerprint")
    )
    if ingestion_errors or observed_contract != expected_contract:
        raise ActiveMetadataProjectionExecutionError("M3-2 provider ingestion evidence is invalid")


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    paths = {
        "projection_execution": Path(__file__).resolve(),
        "scheduler_delivery": Path(delivery.__file__).resolve(),
        "provider_apply": Path(replay.__file__).resolve(),
        "wrapper": DEFAULT_WRAPPER_PATH,
    }
    required = {
        "projection_execution": (
            "class ProjectionExecutor",
            "class ProjectionExecutionServer",
            "def run_scheduler_projection_rehearsal(",
            "provider_mutations_executed",
            "production_ready",
        ),
        "scheduler_delivery": (
            "class EphemeralDolphinScheduler",
            "class EphemeralPostgresDatabase",
            "def _wait_for_terminal_instance(",
        ),
        "provider_apply": (
            "class OpenMetadataApplyClient",
            "class GravitinoApplyClient",
            "def apply_once(",
        ),
        "wrapper": (
            "set -euo pipefail",
            "metadata_fabric_active_metadata_projection_execution",
        ),
    }
    files: dict[str, dict[str, str | None]] = {}
    for name, path in paths.items():
        try:
            text_value = path.read_text(encoding="utf-8")
            for marker in required[name]:
                if marker not in text_value:
                    errors.append(f"{name} is missing marker: {marker}")
        except OSError as exc:
            errors.append(f"{name} is unavailable: {type(exc).__name__}")
        files[name] = _file_record(path)
    stable = {
        "schema": CONTRACT_SCHEMA,
        "scheduler_provider": {
            "name": "apache-dolphinscheduler",
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "image": delivery.IMAGE,
            "image_id": delivery.IMAGE_ID,
        },
        "projection_providers": {
            "openmetadata": "1.13.1",
            "gravitino": "1.3.0",
        },
        "scheduler_execution_boundary": (
            "dolphinscheduler_shell_to_ephemeral_local_projection_executor"
        ),
        "provider_mutation_mode": "authorized_apply_then_zero_mutation_replay",
        "provider_success_platform_state": "reconciling",
        "local_static_contract_verified": not errors,
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def run_scheduler_projection_rehearsal(
    database_url: str,
    scheduler_profile: DolphinSchedulerProfile,
    scheduler_dependency: dict[str, Any],
    ingestion_dependency: dict[str, Any],
    projection_profile: replay.LocalIngestionProfile,
    runtime_identity: dict[str, Any],
    principal: dict[str, Any],
    gravitino_version: str,
    openmetadata: replay.OpenMetadataApplyClient,
    gravitino: replay.GravitinoApplyClient,
    callback_server: ProjectionExecutionServer,
    *,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    _validate_dependencies(scheduler_dependency, ingestion_dependency)
    dataset = scheduler_dependency["dataset_bundle"]
    if validate_shapefile_bundle_inventory(dataset):
        raise ActiveMetadataProjectionExecutionError(
            "real Chongqing dataset bundle inventory is invalid"
        )
    if scheduler_profile.workload_subject != RUNNER:
        raise ActiveMetadataProjectionExecutionError(
            "scheduler workload does not match the authorized runner"
        )
    if scheduler_profile.policy_evaluator_subject != POLICY_EVALUATOR:
        raise ActiveMetadataProjectionExecutionError(
            "scheduler evaluator does not match policy evidence"
        )

    started_at = datetime.now(UTC)
    plan = build_projection_plan(dataset["content_sha256"], projection_profile)
    request = build_execution_request(plan)
    if callback_server.request != request:
        raise ActiveMetadataProjectionExecutionError(
            "callback server is not bound to the exact projection request"
        )
    definition_bundle = build_scheduler_definition(
        callback_server.callback_url,
        request,
        created_at=started_at,
    )
    engine = create_engine(database_url)
    client = DolphinSchedulerClient(scheduler_profile)
    try:
        binding = client.create_workflow(definition_bundle.workflow)
        authorized_at = datetime.now(UTC)
        bundle = build_dispatch_bundle(
            dataset["content_sha256"],
            definition_bundle,
            binding,
            authorized_at=authorized_at,
        )
        apply_authorization = build_provider_apply_authorization(
            plan,
            bundle.run,
            projection_profile,
        )
        callback_server.executor = ProjectionExecutor(
            request,
            projection_profile,
            plan,
            bundle.run,
            apply_authorization,
            openmetadata=openmetadata,
            gravitino=gravitino,
        )
        authorization._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_control_chain(gateway, bundle, apply_authorization)
        first_auth = gateway.authorize_metadata_activation(bundle.activation_authorization)
        replay_auth = gateway.authorize_metadata_activation(bundle.activation_authorization)
        callback_server.start()

        adapter = DolphinSchedulerAdapter(
            scheduler_profile,
            gateway=gateway,
            client=client,
            clock=lambda: authorized_at,
        )
        consumer_result = DolphinSchedulerCommandConsumer(
            adapter,
            gateway=gateway,
        ).run_once(TENANT, worker_id=WORKER, limit=1, lease_seconds=600)
        if consumer_result.completed != 1:
            raise ActiveMetadataProjectionExecutionError(
                "authorized projection command was not completed"
            )
        command = gateway.get_command(
            TENANT,
            bundle.activation_authorization.command_id,
        )
        with engine.connect() as connection:
            instance_id = int(
                connection.execute(
                    text(
                        """
                        SELECT external_run_id
                        FROM gda_control.framework_attempt_observation
                        WHERE tenant_id = :tenant_id
                          AND run_id = :run_id
                          AND observed_state = 'submitted'
                        """
                    ),
                    {"tenant_id": TENANT, "run_id": RUN_ID},
                ).scalar_one()
            )
        terminal = delivery._wait_for_terminal_instance(
            client,
            instance_id,
            binding.workflow_definition_code,
            timeout_seconds=terminal_timeout_seconds,
        )
        variables = client.get_instance_variables(instance_id)
        expected_variables = {
            str(item["prop"]): str(item["value"])
            for item in definition_bundle.workflow.global_params
        }
        expected_variables.update(DolphinSchedulerClient.start_params(bundle.run))
        matching_instances = client.find_instances(binding, bundle.run)
        reconciled = adapter.reconcile(
            TENANT,
            RUN_ID,
            bundle.dispatch_plan.artifact_id,
            actor_subject=RUNNER,
            attempt_no=1,
        )
        attempts = _attempt_summary(engine)
        final_run = gateway.get_run(TENANT, RUN_ID)
        executor = callback_server.executor
        if executor is None or executor.first is None or executor.replayed is None:
            raise ActiveMetadataProjectionExecutionError(
                "scheduler callback did not produce both provider outcomes"
            )
        first_outcome = replay._outcome_evidence(executor.first)
        replay_outcome = replay._outcome_evidence(executor.replayed)
        verified = (
            first_auth.created
            and not replay_auth.created
            and command.status.value == "done"
            and consumer_result.claimed == consumer_result.completed == 1
            and terminal.state.upper() == "SUCCESS"
            and variables == expected_variables
            and len(matching_instances) == 1
            and matching_instances[0].instance_id == instance_id
            and reconciled.provider_state == "SUCCESS"
            and attempts[:4] == (2, 1, 1, 1)
            and attempts[4] == ["submitted", "success"]
            and final_run.status == RunStatus.RECONCILING
            and executor.request_count == 1
            and first_outcome["status"] == "created"
            and first_outcome["mutation_count"] > 0
            and replay_outcome["status"] == "no_op"
            and replay_outcome["mutation_count"] == 0
            and first_outcome["binding_candidate_sha256"]
            == replay_outcome["binding_candidate_sha256"]
            and bundle.source_version.content_sha256
            == dataset["content_sha256"]
            == scheduler_dependency["resource_version_content_sha256"]
        )
        contract = build_contract_report()
        stable = {
            "schema": EVIDENCE_SCHEMA,
            "status": (
                "local_scheduler_provider_projection_execution_verified" if verified else "blocked"
            ),
            "contract_sha256": contract["contract_sha256"],
            "scheduler_dependency_evidence_sha256": scheduler_dependency["evidence_sha256"],
            "ingestion_dependency_evidence_sha256": ingestion_dependency["evidence_fingerprint"],
            "dataset_bundle": dataset,
            "dataset_source_committed": False,
            "dataset_absolute_path_committed": False,
            "dataset_required_in_ci": False,
            "real_dataset_resource_version_bound": True,
            "resource_version_id": str(SOURCE_ID),
            "resource_version_content_sha256": bundle.source_version.content_sha256,
            "definition_version_id": str(DEFINITION_ID),
            "definition_sha256": definition_bundle.definition.definition_sha256,
            "compiled_workflow_sha256": definition_bundle.workflow.compiled_sha256,
            "run_id": str(RUN_ID),
            "dispatch_execution_plan_artifact_id": str(bundle.dispatch_plan.artifact_id),
            "dispatch_authorization_id": str(bundle.activation_authorization.authorization_id),
            "dispatch_authorization_sha256": (bundle.activation_authorization.authorization_sha256),
            "dispatch_authorization_created": first_auth.created,
            "exact_dispatch_authorization_replay_created": replay_auth.created,
            "provider_apply_execution_plan_artifact_id": str(
                apply_authorization.execution_plan_artifact.artifact_id
            ),
            "provider_apply_authorization_sha256": (apply_authorization.authorization_sha256),
            "provider_apply_authorized": True,
            "execution_request_sha256": request.request_sha256,
            "execution_callback_request_count": executor.request_count,
            "execution_callback_exact_request_verified": executor.error_type is None,
            "command_id": str(bundle.activation_authorization.command_id),
            "command_status": command.status.value,
            "command_claimed_count": consumer_result.claimed,
            "command_completed_count": consumer_result.completed,
            "scheduler_provider": {
                "name": "apache-dolphinscheduler",
                "server_version": binding.server_version,
                "api_profile": binding.api_profile,
                "image": delivery.IMAGE,
                "image_id": delivery.IMAGE_ID,
                "architecture": platform.machine(),
                "project_code": binding.project_code,
                "workflow_definition_code": binding.workflow_definition_code,
                "workflow_definition_version": binding.workflow_definition_version,
                "workflow_instance_id": instance_id,
                "terminal_state": terminal.state.upper(),
            },
            "correlation_variables": variables,
            "exact_correlation_variable_readback_verified": (variables == expected_variables),
            "matching_provider_instance_count": len(matching_instances),
            "attempt_observation_count": attempts[0],
            "external_correlation_count": attempts[1],
            "submitted_observation_count": attempts[2],
            "success_observation_count": attempts[3],
            "attempt_states": attempts[4],
            "scheduler_success_readback_verified": (reconciled.provider_state == "SUCCESS"),
            "platform_run_status": final_run.status.value,
            "platform_run_succeeded": final_run.status == RunStatus.SUCCEEDED,
            "projection_targets": {
                "openmetadata": projection_profile.targets.openmetadata.table_fqn,
                "gravitino": projection_profile.targets.gravitino.identity,
            },
            "provider_runtime": runtime_identity,
            "provider_security": {
                "openmetadata": {
                    "auth_mode": (projection_profile.providers.openmetadata.auth_mode),
                    "authenticated_principal": principal,
                    "minimum_privilege_verified": False,
                },
                "gravitino": {
                    "auth_mode": projection_profile.providers.gravitino.auth_mode,
                    "version": gravitino_version,
                    "authentication_verified": False,
                },
            },
            "first_apply": first_outcome,
            "replay": replay_outcome,
            "provider_mutations_executed": verified,
            "openmetadata_readback_verified": verified,
            "gravitino_readback_verified": verified,
            "deterministic_live_replay_verified": verified,
            "local_scheduler_projection_execution_verified": verified,
            "callback_server_cleanup_verified": False,
            "provider_port_forwards_cleanup_verified": False,
            "standalone_container_cleanup_verified": False,
            "temporary_database_cleanup_verified": False,
            "provider_objects_retained_for_readback": True,
            "writes_to_legacy": False,
            "deployment_applied": False,
            "protected_workload_identity_verified": False,
            "provider_minimum_privilege_verified": False,
            "gravitino_authentication_verified": False,
            "oidc_verified": False,
            "tls_verified": False,
            "binding_persisted_to_gda_control": False,
            "live_openlineage_emission_verified": False,
            "production_scheduler_submission_verified": False,
            "production_ingestion_verified": False,
            "production_ready": False,
            "errors": [] if verified else ["local projection execution failed"],
        }
        return stable
    finally:
        client.close()
        engine.dispose()


def run_managed_rehearsal(
    database_admin_url: str,
    scheduler_dependency: dict[str, Any],
    ingestion_dependency: dict[str, Any],
    admin_password: SecretStr,
    openmetadata_username: str,
    openmetadata_password: SecretStr,
    *,
    readiness_timeout_seconds: float = 180,
    terminal_timeout_seconds: float = 600,
) -> dict[str, Any]:
    _validate_dependencies(scheduler_dependency, ingestion_dependency)
    authorized_at = datetime.now(UTC)
    profile = build_projection_profile(authorized_at)
    plan = build_projection_plan(
        scheduler_dependency["dataset_bundle"]["content_sha256"],
        profile,
    )
    request = build_execution_request(plan)
    database = delivery.EphemeralPostgresDatabase(database_admin_url)
    scheduler = delivery.EphemeralDolphinScheduler(
        admin_password,
        readiness_timeout=readiness_timeout_seconds,
    )
    callback_server = ProjectionExecutionServer(request)
    om_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.openmetadata.service,
        target_port=profile.providers.openmetadata.service_port,
    )
    gravitino_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.gravitino.service,
        target_port=profile.providers.gravitino.service_port,
    )
    evidence: dict[str, Any] | None = None
    provider_forwards_stopped = False
    openmetadata: replay.OpenMetadataApplyClient | None = None
    gravitino: replay.GravitinoApplyClient | None = None
    try:
        om_forward.start()
        gravitino_forward.start()
        openmetadata = replay.OpenMetadataApplyClient(
            base_url=f"http://127.0.0.1:{om_forward.local_port}/api/v1",
            username=openmetadata_username,
            password=openmetadata_password,
        )
        gravitino = replay.GravitinoApplyClient(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api"
        )
        principal = openmetadata.authenticated_principal()
        gravitino_version = gravitino.version()
        runtime_identity = replay._provider_runtime_identity(profile)
        with database:
            with scheduler:
                project_code, access_token = scheduler.provision_project()
                scheduler_profile = DolphinSchedulerProfile(
                    base_url=scheduler.base_url,
                    access_token=access_token,
                    project_code=project_code,
                    workload_subject=RUNNER,
                    policy_evaluator_subject=POLICY_EVALUATOR,
                    tenant_code="default",
                    worker_group="default",
                    timezone_name="UTC",
                    request_timeout_seconds=300,
                    reconciliation_page_limit=5,
                )
                if database.database_url is None:
                    raise ActiveMetadataProjectionExecutionError(
                        "temporary PostgreSQL database was not created"
                    )
                evidence = run_scheduler_projection_rehearsal(
                    database.database_url,
                    scheduler_profile,
                    scheduler_dependency,
                    ingestion_dependency,
                    profile,
                    runtime_identity,
                    principal,
                    gravitino_version,
                    openmetadata,
                    gravitino,
                    callback_server,
                    terminal_timeout_seconds=terminal_timeout_seconds,
                )
    finally:
        callback_server.stop()
        if openmetadata is not None:
            openmetadata.close()
        if gravitino is not None:
            gravitino.close()
        provider_forwards_stopped = om_forward.stop() and gravitino_forward.stop()
    if evidence is None:
        raise ActiveMetadataProjectionExecutionError(
            "local scheduler projection rehearsal produced no evidence"
        )
    evidence["callback_server_cleanup_verified"] = callback_server.cleanup_verified
    evidence["provider_port_forwards_cleanup_verified"] = provider_forwards_stopped
    evidence["standalone_container_cleanup_verified"] = scheduler.cleanup_verified
    evidence["temporary_database_cleanup_verified"] = database.cleanup_verified
    cleanup_verified = all(
        (
            callback_server.cleanup_verified,
            provider_forwards_stopped,
            scheduler.cleanup_verified,
            database.cleanup_verified,
        )
    )
    if not cleanup_verified:
        evidence["errors"].append("ephemeral projection runtime cleanup failed")
        evidence["status"] = "blocked"
        evidence["local_scheduler_projection_execution_verified"] = False
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveMetadataProjectionExecutionError(f"{path.name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ActiveMetadataProjectionExecutionError(f"{path.name} must contain an object")
    return value


def validate_rehearsal_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("projection execution evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("projection execution evidence SHA-256 does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("projection execution contract fingerprint is stale")
    try:
        scheduler_dependency = _load_json_object(DEFAULT_SCHEDULER_DEPENDENCY_PATH)
        ingestion_dependency = _load_json_object(DEFAULT_INGESTION_DEPENDENCY_PATH)
    except ActiveMetadataProjectionExecutionError:
        scheduler_dependency = {}
        ingestion_dependency = {}
        errors.append("projection execution dependency evidence is unavailable")
    if evidence.get("scheduler_dependency_evidence_sha256") != (
        scheduler_dependency.get("evidence_sha256")
    ):
        errors.append("M3-17 scheduler dependency fingerprint is stale")
    if evidence.get("ingestion_dependency_evidence_sha256") != (
        ingestion_dependency.get("evidence_fingerprint")
    ):
        errors.append("M3-2 ingestion dependency fingerprint is stale")
    dataset = evidence.get("dataset_bundle")
    if not isinstance(dataset, dict):
        errors.append("projection execution dataset bundle is missing")
    else:
        errors.extend(validate_shapefile_bundle_inventory(dataset))
        if evidence.get("resource_version_content_sha256") != dataset.get("content_sha256"):
            errors.append("real dataset fingerprint is not bound to ResourceVersion")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"local projection execution may not claim {claim}")
    for claim in (
        "real_dataset_resource_version_bound",
        "provider_apply_authorized",
        "execution_callback_exact_request_verified",
        "exact_correlation_variable_readback_verified",
        "scheduler_success_readback_verified",
        "openmetadata_readback_verified",
        "gravitino_readback_verified",
        "deterministic_live_replay_verified",
        "provider_mutations_executed",
        "local_scheduler_projection_execution_verified",
        "callback_server_cleanup_verified",
        "provider_port_forwards_cleanup_verified",
        "standalone_container_cleanup_verified",
        "temporary_database_cleanup_verified",
        "provider_objects_retained_for_readback",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"projection execution did not verify {claim}")
    if evidence.get("dispatch_authorization_created") is not True:
        errors.append("projection dispatch authorization was not created")
    if evidence.get("exact_dispatch_authorization_replay_created") is not False:
        errors.append("exact projection dispatch authorization replay created a row")
    if evidence.get("execution_callback_request_count") != 1:
        errors.append("projection executor must receive exactly one callback")
    if evidence.get("command_status") != "done":
        errors.append("authorized projection command must be done")
    if evidence.get("command_claimed_count") != 1:
        errors.append("projection execution must claim one command")
    if evidence.get("command_completed_count") != 1:
        errors.append("projection execution must complete one command")
    scheduler = evidence.get("scheduler_provider")
    expected_scheduler = {
        "name": "apache-dolphinscheduler",
        "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
        "api_profile": DOLPHINSCHEDULER_API_PROFILE,
        "image": delivery.IMAGE,
        "image_id": delivery.IMAGE_ID,
        "terminal_state": "SUCCESS",
    }
    if not isinstance(scheduler, dict) or any(
        scheduler.get(key) != value for key, value in expected_scheduler.items()
    ):
        errors.append("projection scheduler provider identity or state does not match")
    if evidence.get("matching_provider_instance_count") != 1:
        errors.append("projection execution must read back one scheduler instance")
    if evidence.get("attempt_observation_count") != 2:
        errors.append("projection execution must record two attempt observations")
    if evidence.get("external_correlation_count") != 1:
        errors.append("projection execution must retain one external correlation")
    if evidence.get("attempt_states") != ["submitted", "success"]:
        errors.append("projection scheduler attempt states do not match")
    if evidence.get("platform_run_status") != "reconciling":
        errors.append("provider success must leave PlatformRun reconciling")
    if evidence.get("platform_run_succeeded") is not False:
        errors.append("local provider success may not claim platform success")
    first = evidence.get("first_apply")
    replayed = evidence.get("replay")
    if not isinstance(first, dict) or not isinstance(replayed, dict):
        errors.append("provider apply outcomes are missing")
    else:
        if first.get("status") != "created" or first.get("mutation_count", 0) <= 0:
            errors.append("first scheduler-triggered provider apply did not mutate")
        if replayed.get("status") != "no_op" or replayed.get("mutation_count") != 0:
            errors.append("exact scheduler-triggered replay was not mutation-free")
        for key in ("binding_candidate_sha256", "openmetadata", "gravitino"):
            if first.get(key) != replayed.get(key):
                errors.append(f"provider read-back drifted across replay: {key}")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "Downloads/",
        ".tmp/",
        "host.docker.internal",
        '"token"',
        '"password"',
        '"session"',
    ):
        if forbidden in serialized:
            errors.append("projection execution evidence contains sensitive local material")
            break
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--database-admin-url", required=True)
    rehearse.add_argument(
        "--admin-password-env",
        default="GDA_DOLPHINSCHEDULER_ADMIN_PASSWORD",
    )
    rehearse.add_argument(
        "--scheduler-dependency",
        type=Path,
        default=DEFAULT_SCHEDULER_DEPENDENCY_PATH,
    )
    rehearse.add_argument(
        "--ingestion-dependency",
        type=Path,
        default=DEFAULT_INGESTION_DEPENDENCY_PATH,
    )
    rehearse.add_argument("--readiness-timeout-seconds", type=float, default=180)
    rehearse.add_argument("--terminal-timeout-seconds", type=float, default=600)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_contract_report()
        try:
            report["errors"].extend(validate_rehearsal_evidence(_load_json_object(args.evidence)))
        except ActiveMetadataProjectionExecutionError as exc:
            report["errors"].append(
                f"projection execution evidence is invalid: {type(exc).__name__}"
            )
        report["status"] = "valid" if not report["errors"] else "invalid"
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    scheduler_dependency = _load_json_object(args.scheduler_dependency)
    ingestion_dependency = _load_json_object(args.ingestion_dependency)
    provider_profile = replay.load_profile()
    try:
        username = os.environ[provider_profile.providers.openmetadata.username_env]
        password = SecretStr(os.environ[provider_profile.providers.openmetadata.password_env])
    except KeyError as exc:
        raise ActiveMetadataProjectionExecutionError(
            "OpenMetadata local bootstrap credential environment is missing"
        ) from exc
    evidence = run_managed_rehearsal(
        args.database_admin_url,
        scheduler_dependency,
        ingestion_dependency,
        delivery._read_admin_password(args.admin_password_env),
        username,
        password,
        readiness_timeout_seconds=args.readiness_timeout_seconds,
        terminal_timeout_seconds=args.terminal_timeout_seconds,
    )
    args.evidence_out.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
